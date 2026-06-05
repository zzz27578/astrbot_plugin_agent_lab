from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .models import AgentSpec, TaskState, new_id, now_iso


def _compact(value: Any, limit: int = 800) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...[truncated]"


class TaskPatternLibrary:
    """Evidence-linked task pattern library built from completed Agent Lab tasks."""

    def __init__(self, storage: Any) -> None:
        self.storage = storage
        self.path = Path(storage.registry_dir) / "task_patterns.json"

    def list_patterns(self, *, status: str = "active") -> list[dict[str, Any]]:
        rows = self._read()
        if status and status != "all":
            rows = [row for row in rows if str(row.get("status") or "active") == status]
        return sorted(rows, key=lambda row: str(row.get("updated_at") or ""), reverse=True)

    def get(self, pattern_id: str) -> dict[str, Any] | None:
        needle = str(pattern_id or "").strip()
        if not needle:
            return None
        for item in self._read():
            if item.get("pattern_id") == needle:
                return dict(item)
        return None

    def upsert_from_task(self, task: TaskState, spec: AgentSpec) -> dict[str, Any] | None:
        if task.status != "completed":
            return None
        runtime = task.workflow_data.get("agent_runtime") if isinstance(task.workflow_data, dict) else {}
        if not isinstance(runtime, dict):
            runtime = {}
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        raw_steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        steps = [
            {
                "node_id": str(step.get("node_id") or ""),
                "title": str(step.get("title") or step.get("node_id") or ""),
                "stage": str(step.get("stage") or ""),
                "action": str(step.get("action") or ""),
                "capability": str(step.get("capability") or ""),
                "success_condition": _compact(step.get("success_condition") or "", 300),
            }
            for step in raw_steps
            if isinstance(step, dict) and str(step.get("node_id") or "").strip()
        ][:40]
        if not steps:
            return None
        goal = str(task.root_goal or "").strip()
        summary = str(task.exit_summary or task.current_summary or task.last_confirmed_progress or "").strip()
        archive_path = str(task.archive_path or self._archive_path_for(task))
        if archive_path and not task.archive_path:
            task.archive_path = archive_path
        fingerprint = self._fingerprint(task, steps)
        rows = self._read()
        existing = next(
            (
                row
                for row in rows
                if row.get("source_task_id") == task.task_id or row.get("fingerprint") == fingerprint
            ),
            None,
        )
        same_source = bool(existing and existing.get("source_task_id") == task.task_id)
        pattern_id = str((existing or {}).get("pattern_id") or new_id("pattern"))
        keywords = self.keywords_for(goal, summary, " ".join(task.completion_conditions or []))
        source_tasks = self._source_tasks(existing)
        if existing and existing.get("source_task_id"):
            existing_evidence = existing.get("evidence") if isinstance(existing.get("evidence"), dict) else {}
            if not any(item.get("task_id") == existing.get("source_task_id") for item in source_tasks):
                source_tasks.append(
                    {
                        "task_id": existing.get("source_task_id") or "",
                        "umo": existing.get("source_umo") or "",
                        "archive_path": existing_evidence.get("archive_path") or "",
                        "completed_at": existing.get("updated_at") or existing.get("created_at") or "",
                        "summary": _compact(existing.get("summary") or "", 500),
                    }
                )
        source_task_entry = {
            "task_id": task.task_id,
            "umo": task.umo,
            "archive_path": archive_path,
            "completed_at": task.finished_at or task.updated_at,
            "summary": _compact(summary or goal, 500),
        }
        source_tasks = [item for item in source_tasks if item.get("task_id") != task.task_id]
        source_tasks.append(source_task_entry)
        pattern = {
            "pattern_id": pattern_id,
            "status": "active",
            "title": _compact(goal or spec.name or pattern_id, 120),
            "summary": _compact(summary or goal, 1200),
            "goal_keywords": keywords,
            "source_task_id": task.task_id,
            "source_agent_id": task.agent_id or spec.agent_id,
            "source_agent_name": task.agent_name or spec.name,
            "source_umo": task.umo,
            "fingerprint": fingerprint,
            "completion_conditions": list(task.completion_conditions or [])[:20],
            "plan_template": {
                "goal": goal,
                "steps": steps,
                "workflow_node_ids": [str(item or "") for item in (task.workflow_path or []) if str(item or "")][:60],
                "required_capabilities": sorted(
                    {
                        str(step.get("capability") or "")
                        for step in steps
                        if str(step.get("capability") or "").strip()
                    }
                ),
            },
            "workflow_template": {
                "nodes": [
                    self._pattern_node(node)
                    for node in (spec.workflow_nodes or [])
                    if isinstance(node, dict)
                ][:80],
                "edges": [
                    {"from": str(edge.get("from") or ""), "to": str(edge.get("to") or "")}
                    for edge in (spec.workflow_edges or [])
                    if isinstance(edge, dict) and edge.get("from") and edge.get("to")
                ][:120],
            },
            "evidence": {
                "source_task_id": task.task_id,
                "source_tasks": source_tasks[-20:],
                "archive_path": archive_path,
                "last_verdict_id": ((runtime.get("last_verdict") or {}).get("verdict_id") or ""),
                "observation_count": len(runtime.get("observations") or []),
                "verdict_count": len(runtime.get("verdicts") or []),
                "parallel_run_count": len(task.parallel_runs or []),
            },
            "usage_count": int((existing or {}).get("usage_count") or 0),
            "success_count": int((existing or {}).get("success_count") or 0) + (0 if same_source else 1),
            "created_at": str((existing or {}).get("created_at") or now_iso()),
            "updated_at": now_iso(),
        }
        rows = [row for row in rows if row.get("pattern_id") != pattern_id and row.get("fingerprint") != fingerprint]
        rows.append(pattern)
        self._write(rows)
        return pattern

    def recommend(self, query: str, *, limit: int = 5, exclude_task_id: str = "") -> list[dict[str, Any]]:
        query = str(query or "").strip()
        limit = max(1, min(int(limit or 5), 20))
        excluded = str(exclude_task_id or "").strip()
        scored = []
        for pattern in self.list_patterns(status="active"):
            if excluded and pattern.get("source_task_id") == excluded:
                continue
            score = self.score(query, pattern)
            if score <= 0 and query:
                continue
            row = dict(pattern)
            row["score"] = score
            scored.append(row)
        scored.sort(
            key=lambda row: (
                int(row.get("score") or 0),
                int(row.get("success_count") or 0),
                str(row.get("updated_at") or ""),
            ),
            reverse=True,
        )
        return scored[:limit]

    def mark_used(self, pattern_id: str) -> dict[str, Any] | None:
        rows = self._read()
        updated = None
        for row in rows:
            if row.get("pattern_id") != pattern_id:
                continue
            row["usage_count"] = int(row.get("usage_count") or 0) + 1
            row["updated_at"] = now_iso()
            updated = dict(row)
            break
        if updated:
            self._write(rows)
        return updated

    def prompt_for(self, query: str, *, limit: int = 3, exclude_task_id: str = "") -> str:
        rows = self.recommend(query, limit=limit, exclude_task_id=exclude_task_id)
        if not rows:
            return ""
        lines = [
            "[Agent Lab Task Pattern Recommendations]",
            "These patterns are evidence-linked templates mined from completed Agent Lab tasks. Use them as planning hints, not as facts.",
        ]
        for row in rows:
            steps = (row.get("plan_template") or {}).get("steps") or []
            step_text = " -> ".join(str(step.get("node_id") or "") for step in steps[:8] if isinstance(step, dict))
            caps = ", ".join((row.get("plan_template") or {}).get("required_capabilities") or [])
            lines.append(
                f"- {row.get('pattern_id')}: score={row.get('score', 0)} title={row.get('title') or '-'}; "
                f"caps=[{caps or '-'}]; steps={step_text or '-'}; evidence_task={row.get('source_task_id') or '-'}"
            )
        return "\n".join(lines)

    def score(self, query: str, pattern: dict[str, Any]) -> int:
        if not query:
            return 1
        query_keywords = set(self.keywords_for(query))
        pattern_keywords = set(str(item).lower() for item in pattern.get("goal_keywords") or [])
        haystack = " ".join(
            [
                str(pattern.get("title") or ""),
                str(pattern.get("summary") or ""),
                " ".join(pattern_keywords),
                " ".join(
                    str(step.get("title") or "") + " " + str(step.get("success_condition") or "")
                    for step in (pattern.get("plan_template") or {}).get("steps", [])
                    if isinstance(step, dict)
                ),
            ]
        ).lower()
        score = len(query_keywords & pattern_keywords) * 8
        for keyword in query_keywords:
            if keyword and keyword in haystack:
                score += 3
        if query.lower() in haystack:
            score += 10
        return score

    @staticmethod
    def compact_for_runtime(pattern: dict[str, Any]) -> dict[str, Any]:
        plan = pattern.get("plan_template") if isinstance(pattern.get("plan_template"), dict) else {}
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        evidence = pattern.get("evidence") if isinstance(pattern.get("evidence"), dict) else {}
        return {
            "pattern_id": pattern.get("pattern_id") or "",
            "score": int(pattern.get("score") or 0),
            "title": pattern.get("title") or "",
            "summary": _compact(pattern.get("summary") or "", 500),
            "source_task_id": pattern.get("source_task_id") or evidence.get("source_task_id") or "",
            "archive_path": evidence.get("archive_path") or "",
            "success_count": int(pattern.get("success_count") or 0),
            "usage_count": int(pattern.get("usage_count") or 0),
            "required_capabilities": list(plan.get("required_capabilities") or [])[:20],
            "steps": [
                {
                    "node_id": str(step.get("node_id") or ""),
                    "title": str(step.get("title") or step.get("node_id") or ""),
                    "stage": str(step.get("stage") or ""),
                    "action": str(step.get("action") or ""),
                    "capability": str(step.get("capability") or ""),
                    "success_condition": _compact(step.get("success_condition") or "", 240),
                }
                for step in steps[:16]
                if isinstance(step, dict)
            ],
        }

    @staticmethod
    def keywords_for(*texts: str) -> list[str]:
        text = " ".join(str(item or "") for item in texts).lower()
        tokens: list[str] = []
        for match in re.finditer(r"[a-z0-9_./-]{2,}|[\u4e00-\u9fff]{2,}", text):
            token = match.group(0).strip("._-/")
            if not token:
                continue
            tokens.append(token[:40])
            if re.fullmatch(r"[\u4e00-\u9fff]{5,}", token):
                for size in (2, 3, 4):
                    for index in range(0, max(0, len(token) - size + 1)):
                        tokens.append(token[index : index + size])
        seen: set[str] = set()
        result = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            result.append(token)
            if len(result) >= 80:
                break
        return result

    @staticmethod
    def _pattern_node(node: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "id",
            "title",
            "kind",
            "stage",
            "action",
            "instruction",
            "condition",
            "prompt",
            "parallel_group",
            "input_variable",
            "output_variable",
            "tool_name",
            "api_id",
            "ref_type",
            "ref_id",
        }
        return {key: node.get(key) for key in allowed if key in node}

    @staticmethod
    def _source_tasks(existing: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(existing, dict):
            return []
        evidence = existing.get("evidence") if isinstance(existing.get("evidence"), dict) else {}
        rows = evidence.get("source_tasks") if isinstance(evidence.get("source_tasks"), list) else []
        return [dict(item) for item in rows if isinstance(item, dict)]

    def _archive_path_for(self, task: TaskState) -> str:
        try:
            if hasattr(self.storage, "archive_task_markdown_path"):
                return str(self.storage.archive_task_markdown_path(task.umo, task.task_id))
        except Exception:
            return ""
        return ""

    @staticmethod
    def _fingerprint(task: TaskState, steps: list[dict[str, Any]]) -> str:
        payload = {
            "goal": task.root_goal,
            "conditions": task.completion_conditions,
            "steps": [
                {
                    "stage": step.get("stage"),
                    "action": step.get("action"),
                    "capability": step.get("capability"),
                }
                for step in steps
            ],
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)
