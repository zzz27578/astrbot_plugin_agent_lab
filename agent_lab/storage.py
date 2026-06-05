from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .models import AgentSpec, TaskState, new_id, now_iso


def _safe_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class AgentLabStorage:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.agents_dir = self.root / "agents"
        self.sessions_dir = self.root / "sessions"
        self.modules_dir = self.root / "modules"
        self.archives_dir = self.root / "archives"
        self.registry_dir = self.root / "registry"
        self.memories_dir = self.root / "memories"
        self.default_agent_path = self.root / "default_agent_id.txt"
        self.custom_apis_path = self.registry_dir / "custom_apis.json"
        self.credentials_path = self.registry_dir / "credentials.json"
        self.secrets_key_path = self.registry_dir / "secrets.key"
        self.skill_rules_path = self.registry_dir / "skill_rules.json"
        self.memory_entries_path = self.memories_dir / "entries.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)

    def ensure_defaults(self) -> AgentSpec:
        agents = self.list_agents()
        if agents:
            default_id = self.default_agent_id()
            for agent in agents:
                if agent.agent_id == default_id:
                    return agent
            self.set_default_agent(agents[0].agent_id)
            return agents[0]
        spec = AgentSpec(identity_label_source="astrbot_runtime")
        self.save_agent(spec)
        self.set_default_agent(spec.agent_id)
        return spec

    def list_agents(self) -> list[AgentSpec]:
        agents: list[AgentSpec] = []
        for path in sorted(self.agents_dir.glob("*.json")):
            try:
                agents.append(AgentSpec.from_dict(self._read_json(path)))
            except Exception:
                continue
        return agents

    def get_agent(self, agent_id: str | None = None) -> AgentSpec:
        if agent_id:
            path = self.agents_dir / f"{agent_id}.json"
            if path.exists():
                return AgentSpec.from_dict(self._read_json(path))
        agents = self.list_agents()
        if not agents:
            return self.ensure_defaults()
        default_id = self.default_agent_id()
        for agent in agents:
            if agent.agent_id == default_id:
                return agent
        self.set_default_agent(agents[0].agent_id)
        return agents[0]

    def save_agent(self, spec: AgentSpec) -> None:
        spec.updated_at = now_iso()
        self._write_json(self.agents_dir / f"{spec.agent_id}.json", spec.to_dict())
        if not self.default_agent_id():
            self.set_default_agent(spec.agent_id)

    def delete_agent(self, agent_id: str) -> bool:
        agent_id = str(agent_id or "").strip()
        if not agent_id:
            return False
        path = self.agents_dir / f"{agent_id}.json"
        if not path.exists():
            return False
        path.unlink()
        remaining = self.list_agents()
        if self.default_agent_id() == agent_id:
            if remaining:
                self.set_default_agent(remaining[0].agent_id)
            elif self.default_agent_path.exists():
                self.default_agent_path.unlink()
        return True

    def default_agent_id(self) -> str:
        if not self.default_agent_path.exists():
            return ""
        return self.default_agent_path.read_text(encoding="utf-8").strip()

    def set_default_agent(self, agent_id: str) -> bool:
        if not agent_id:
            return False
        if not (self.agents_dir / f"{agent_id}.json").exists():
            return False
        self._write_text(self.default_agent_path, agent_id)
        return True

    def session_dir(self, umo: str) -> Path:
        path = self.sessions_dir / _safe_hash(umo)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def active_task_path(self, umo: str) -> Path:
        return self.session_dir(umo) / "active_task.json"

    def task_path(self, umo: str, task_id: str) -> Path:
        return self.session_dir(umo) / f"{task_id}.json"

    def task_markdown_path(self, umo: str, task_id: str) -> Path:
        return self.session_dir(umo) / f"{task_id}.md"

    def has_active_task(self, umo: str) -> bool:
        return self.active_task_path(umo).exists()

    def load_active_task(self, umo: str) -> TaskState | None:
        path = self.active_task_path(umo)
        if not path.exists():
            return None
        return TaskState.from_dict(self._read_json(path))

    def save_task(self, task: TaskState, active: bool = True) -> None:
        task.updated_at = now_iso()
        payload = task.to_dict()
        self._write_json(self.task_path(task.umo, task.task_id), payload)
        self._write_text(self.task_markdown_path(task.umo, task.task_id), self.render_markdown(task))
        if active:
            self._write_json(self.active_task_path(task.umo), payload)

    def archive_task(self, task: TaskState) -> Path:
        task.finished_at = task.finished_at or now_iso()
        task.updated_at = now_iso()
        session_archive_dir = self.archives_dir / _safe_hash(task.umo)
        session_archive_dir.mkdir(parents=True, exist_ok=True)
        src_json = self.task_path(task.umo, task.task_id)
        src_md = self.task_markdown_path(task.umo, task.task_id)
        dst_json = session_archive_dir / src_json.name
        dst_md = session_archive_dir / src_md.name
        self._write_json(src_json, task.to_dict())
        self._write_text(src_md, self.render_markdown(task))
        shutil.copy2(src_json, dst_json)
        shutil.copy2(src_md, dst_md)
        task.archive_path = str(dst_md)
        self._write_json(dst_json, task.to_dict())
        self._write_text(dst_md, self.render_markdown(task))
        active = self.active_task_path(task.umo)
        if active.exists():
            active.unlink()
        if task.exit_summary.strip():
            self.save_memory_entry(
                {
                    "text": task.exit_summary,
                    "source_task_id": task.task_id,
                    "source_umo": task.umo,
                    "status": "accepted",
                    "kind": "task_archive_summary",
                    "layer": "archive_summary",
                    "tags": ["task", "archive", "summary", task.agent_id or "agent"],
                    "expose_to_normal": True,
                }
            )
        for item in task.memory_candidates:
            self.save_memory_entry(
                {
                    "text": item,
                    "source_task_id": task.task_id,
                    "source_umo": task.umo,
                    "status": "candidate",
                    "kind": "memory_candidate",
                    "layer": "candidate_memory",
                    "tags": ["task", "candidate", "private", task.agent_id or "agent"],
                    "expose_to_normal": False,
                    "evidence": {
                        "source_task_id": task.task_id,
                        "source_umo": task.umo,
                        "archive_path": task.archive_path,
                        "exit_summary": task.exit_summary[:1200],
                        "last_verdict_id": (
                            ((task.workflow_data or {}).get("agent_runtime") or {}).get("last_verdict") or {}
                        ).get("verdict_id", ""),
                        "history": [{"action": "candidate", "reason": "task_finish_memory_candidate"}],
                    },
                }
            )
        return dst_md

    def list_tasks(self, umo: str | None = None) -> list[TaskState]:
        roots = [self.session_dir(umo)] if umo else list(self.sessions_dir.glob("*"))
        tasks: list[TaskState] = []
        for root in roots:
            if not root.exists():
                continue
            path = root / "active_task.json"
            if not path.exists():
                continue
            try:
                tasks.append(TaskState.from_dict(self._read_json(path)))
            except Exception:
                continue
        return tasks

    def list_archives(self, umo: str | None = None) -> list[TaskState]:
        roots = [self.archives_dir / _safe_hash(umo)] if umo else list(self.archives_dir.glob("*"))
        tasks: list[TaskState] = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("task_*.json")):
                try:
                    task = TaskState.from_dict(self._read_json(path))
                    task.archive_path = task.archive_path or str(path.with_suffix(".md"))
                    tasks.append(task)
                except Exception:
                    continue
        return tasks

    def render_markdown(self, task: TaskState) -> str:
        approvals = task.pending_approvals()
        lines = [
            f"# Agent Lab Task {task.task_id}",
            "",
            f"- status: {task.status}",
            f"- agent: {task.agent_name or task.agent_id}",
            f"- created_at: {task.created_at}",
            f"- updated_at: {task.updated_at}",
            f"- finished_at: {task.finished_at or '-'}",
            "",
            "## Root Goal",
            task.root_goal or "-",
            "",
            "## Completion Conditions",
        ]
        lines.extend([f"- {item}" for item in task.completion_conditions] or ["- 未设置"])
        lines.extend(
            [
                "",
                "## Entry Summary",
                task.entry_summary or task.task_brief or "-",
                "",
                "## Current Summary",
                task.current_summary or "-",
                "",
                "## Last Confirmed Progress",
                task.last_confirmed_progress or "-",
                "",
                "## Next Step",
                task.next_step or "-",
                "",
                "## Last Observation",
                task.last_observation or "-",
                "",
                "## Workflow Cursor",
                f"- current_node: {task.workflow_current_node_id or '-'}",
                f"- path: {' -> '.join(task.workflow_path or []) or '-'}",
                "",
                "### Workflow Events",
            ]
        )
        if task.workflow_events:
            for item in task.workflow_events[-40:]:
                lines.append(
                    f"- {item.get('time')} [{item.get('status') or '-'}] "
                    f"{item.get('node_id') or '-'} -> {item.get('next_node_id') or '-'}: "
                    f"{item.get('outcome') or item.get('note') or '-'}"
                )
        else:
            lines.append("- none")
        workflow_data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        node_outputs = workflow_data.get("node_outputs") if isinstance(workflow_data, dict) else {}
        react_traces = workflow_data.get("react_traces") if isinstance(workflow_data, dict) else []
        agent_runtime = workflow_data.get("agent_runtime") if isinstance(workflow_data, dict) else {}
        if not isinstance(agent_runtime, dict):
            agent_runtime = {}
        runtime_plan = agent_runtime.get("plan") if isinstance(agent_runtime.get("plan"), dict) else {}
        runtime_steps = runtime_plan.get("steps") if isinstance(runtime_plan.get("steps"), list) else []
        runtime_capabilities = (
            agent_runtime.get("capabilities")
            if isinstance(agent_runtime.get("capabilities"), list)
            else []
        )
        runtime_resume = agent_runtime.get("resume") if isinstance(agent_runtime.get("resume"), dict) else {}
        runtime_last_verdict = (
            agent_runtime.get("last_verdict")
            if isinstance(agent_runtime.get("last_verdict"), dict)
            else {}
        )
        lines.extend(
            [
                "",
                "## Agent Runtime",
                f"- instance: {(agent_runtime.get('agent_instance') or {}).get('instance_id') or '-'}",
                f"- plan: {runtime_plan.get('plan_id') or '-'}",
                f"- current_node: {runtime_plan.get('current_node_id') or task.workflow_current_node_id or '-'}",
                f"- capabilities: {len(runtime_capabilities)}",
                f"- decisions: {len(agent_runtime.get('decisions') or [])}",
                f"- observations: {len(agent_runtime.get('observations') or [])}",
                f"- verdicts: {len(agent_runtime.get('verdicts') or [])}",
                f"- resume_command: {runtime_resume.get('resume_command') or '/agentlab tick'}",
                f"- waiting: {runtime_resume.get('waiting') or '-'}",
                f"- last_verdict: {runtime_last_verdict.get('status') or '-'} "
                f"passed={runtime_last_verdict.get('passed')} "
                f"{runtime_last_verdict.get('reason') or ''}",
                "",
                "### Runtime Plan",
            ]
        )
        if runtime_steps:
            for step in runtime_steps[:40]:
                if not isinstance(step, dict):
                    continue
                lines.append(
                    f"- {step.get('node_id') or '-'} [{step.get('status') or '-'}] "
                    f"{step.get('title') or step.get('action') or '-'}; "
                    f"capability={step.get('capability') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "### Runtime Capabilities"])
        if runtime_capabilities:
            for item in runtime_capabilities[:40]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {item.get('name') or '-'}: {item.get('capability') or '-'} "
                    f"risk={item.get('risk') or '-'} "
                    f"approval={'yes' if item.get('requires_approval') else 'no'} "
                    f"available={'yes' if item.get('available', True) else 'no'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "### Workflow Node Outputs"])
        if isinstance(node_outputs, dict) and node_outputs:
            for node_id, item in list(node_outputs.items())[-20:]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {node_id} [{item.get('runtime_type') or '-'}] "
                    f"{item.get('status') or '-'}: {item.get('outcome') or item.get('note') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "### ReAct Handoffs"])
        if isinstance(react_traces, list) and react_traces:
            for item in react_traces[-20:]:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"- {item.get('time')} node={item.get('node_id') or '-'} "
                    f"reason={item.get('reason') or '-'}: {item.get('response') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "### Parallel Workflow Runs"])
        if task.parallel_runs:
            for item in task.parallel_runs[-20:]:
                workers = item.get("workers") or []
                ok_count = sum(1 for worker in workers if worker.get("ok"))
                lines.append(
                    f"- {item.get('time')} branch={item.get('branch_node_id') or '-'} "
                    f"group={item.get('parallel_group') or '-'} merge={item.get('merge_node_id') or '-'} "
                    f"ok={ok_count}/{len(workers)}: {item.get('summary') or '-'}"
                )
                for worker in workers[:8]:
                    lines.append(
                        f"  - {worker.get('node_id') or '-'} [{worker.get('kind') or '-'}] "
                        f"{worker.get('status') or '-'}: {worker.get('summary') or worker.get('error') or '-'}"
                    )
        else:
            lines.append("- none")
        lines.extend(
            [
                "",
                "## Pending Approvals",
            ]
        )
        if approvals:
            lines.extend([f"- {a.approval_id}: {a.operation} | {a.reason}" for a in approvals])
        else:
            lines.append("- none")
        lines.extend(["", "## Progress Log"])
        if task.progress_log:
            for item in task.progress_log[-80:]:
                lines.append(f"- {item.get('time')} [{item.get('kind')}] {item.get('text')}")
        else:
            lines.append("- none")
        lines.extend(["", "## State Snapshots"])
        if task.state_snapshots:
            for item in task.state_snapshots[-40:]:
                lines.append(
                    f"- {item.get('time')} [{item.get('kind')}] "
                    f"status={item.get('status')} next={item.get('next_step') or '-'}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "## Token Usage"])
        lines.append(json.dumps(task.token_usage, ensure_ascii=False, sort_keys=True))
        lines.extend(["", "## Blockers"])
        if task.blockers:
            for item in task.blockers[-40:]:
                lines.append(
                    f"- {item.get('time')} {item.get('issue')} "
                    f"(count={item.get('count')}): {item.get('detail')}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "## Exit Summary", task.exit_summary or "-"])
        lines.extend(["", "## Memory Candidates"])
        lines.extend([f"- {item}" for item in task.memory_candidates] or ["- none"])
        lines.append("")
        return "\n".join(lines)

    def list_custom_apis(self) -> list[dict[str, Any]]:
        return self._read_list(self.custom_apis_path)

    def save_custom_api(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.list_custom_apis()
        item = dict(payload or {})
        item["api_id"] = str(item.get("api_id") or "").strip() or new_id("api")
        item["name"] = str(item.get("name") or item["api_id"]).strip()
        item["method"] = str(item.get("method") or "GET").upper()
        item["url"] = str(item.get("url") or "").strip()
        item["description"] = str(item.get("description") or "").strip()
        item["credential_id"] = str(item.get("credential_id") or "").strip()
        item["auth_type"] = str(item.get("auth_type") or "bearer").strip()
        item["auth_header"] = str(item.get("auth_header") or "Authorization").strip()
        item["auth_query_param"] = str(item.get("auth_query_param") or "api_key").strip()
        try:
            item["timeout_seconds"] = max(1, min(int(item.get("timeout_seconds") or 30), 120))
        except Exception:
            item["timeout_seconds"] = 30
        headers = item.get("headers") or {}
        if isinstance(headers, str):
            try:
                headers = json.loads(headers)
            except Exception:
                headers = {}
        item["headers"] = headers if isinstance(headers, dict) else {}
        item["updated_at"] = now_iso()
        if not item.get("created_at"):
            item["created_at"] = item["updated_at"]
        items = [existing for existing in items if existing.get("api_id") != item["api_id"]]
        items.append(item)
        self._write_json(self.custom_apis_path, items)
        return item

    def get_custom_api(self, api_id_or_name: str) -> dict[str, Any] | None:
        needle = str(api_id_or_name or "").strip()
        if not needle:
            return None
        for item in self.list_custom_apis():
            if item.get("api_id") == needle or item.get("name") == needle:
                return item
        return None

    def list_credentials(self) -> list[dict[str, Any]]:
        rows = []
        for item in self._read_list(self.credentials_path):
            redacted = dict(item)
            encrypted = str(redacted.pop("encrypted_value", "") or "")
            redacted["has_value"] = bool(encrypted)
            redacted["masked_value"] = "********" if encrypted else ""
            rows.append(redacted)
        return rows

    def save_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self._read_list(self.credentials_path)
        item = dict(payload or {})
        credential_id = str(item.get("credential_id") or "").strip() or new_id("cred")
        existing = next((row for row in items if row.get("credential_id") == credential_id), {})
        value = str(item.pop("value", "") or "")
        row = {
            **existing,
            "credential_id": credential_id,
            "label": str(item.get("label") or existing.get("label") or credential_id).strip(),
            "provider": str(item.get("provider") or existing.get("provider") or "").strip(),
            "scope": str(item.get("scope") or existing.get("scope") or "tool").strip(),
            "updated_at": now_iso(),
        }
        row["created_at"] = row.get("created_at") or row["updated_at"]
        if value:
            row["encrypted_value"] = self._encrypt_secret(value)
        items = [existing for existing in items if existing.get("credential_id") != credential_id]
        items.append(row)
        self._write_json(self.credentials_path, items)
        public = dict(row)
        public.pop("encrypted_value", None)
        public["has_value"] = bool(row.get("encrypted_value"))
        public["masked_value"] = "********" if row.get("encrypted_value") else ""
        return public

    def get_credential_secret(self, credential_id: str) -> str:
        credential_id = str(credential_id or "").strip()
        if not credential_id:
            return ""
        for item in self._read_list(self.credentials_path):
            if item.get("credential_id") != credential_id:
                continue
            encrypted = str(item.get("encrypted_value") or "")
            if not encrypted:
                return ""
            return self._decrypt_secret(encrypted)
        return ""

    def list_skill_rules(self) -> list[dict[str, Any]]:
        return self._read_list(self.skill_rules_path)

    def get_skill_rule(self, skill_name: str) -> dict[str, Any] | None:
        skill_name = str(skill_name or "").strip()
        if not skill_name:
            return None
        for item in self.list_skill_rules():
            if item.get("skill_name") == skill_name:
                return item
        return None

    def save_skill_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.list_skill_rules()
        item = dict(payload or {})
        item["skill_name"] = str(item.get("skill_name") or "agent-mode").strip()
        item["content"] = str(item.get("content") or "").strip()
        item["updated_at"] = now_iso()
        item["created_at"] = item.get("created_at") or item["updated_at"]
        items = [
            existing
            for existing in items
            if existing.get("skill_name") != item["skill_name"]
        ]
        items.append(item)
        self._write_json(self.skill_rules_path, items)
        return item

    def list_memory_entries(self) -> list[dict[str, Any]]:
        return self._read_list(self.memory_entries_path)

    def save_memory_entry(self, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.list_memory_entries()
        item = dict(payload or {})
        item["memory_id"] = str(item.get("memory_id") or "").strip() or new_id("mem")
        item["text"] = str(item.get("text") or "").strip()
        item["status"] = str(item.get("status") or "candidate").strip().lower()
        item["kind"] = str(item.get("kind") or "task_memory").strip()
        item["source_task_id"] = str(item.get("source_task_id") or "").strip()
        item["source_umo"] = str(item.get("source_umo") or "").strip()
        tags = item.get("tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.replace("，", ",").split(",")]
        item["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()]
        if "expose_to_normal" in item:
            item["expose_to_normal"] = bool(item.get("expose_to_normal"))
        else:
            item["expose_to_normal"] = item["kind"] == "task_archive_summary"
        item["layer"] = self._normalize_memory_layer(item)
        if item["layer"] == "archive_summary":
            item["status"] = "accepted"
            item["expose_to_normal"] = True
        elif item["layer"] == "accepted_memory":
            item["status"] = "accepted"
            item["expose_to_normal"] = True
        elif item["layer"] in {"private_task_memory", "candidate_memory"}:
            item["expose_to_normal"] = False
            if item["status"] not in {"accepted", "rejected"}:
                item["status"] = "candidate"
        item["evidence"] = self._normalize_memory_evidence(item)
        item["updated_at"] = now_iso()
        item["created_at"] = item.get("created_at") or item["updated_at"]
        items = [existing for existing in items if existing.get("memory_id") != item["memory_id"]]
        if item["text"]:
            items.append(item)
        self._write_json(self.memory_entries_path, items)
        return item

    @staticmethod
    def _normalize_memory_layer(item: dict[str, Any]) -> str:
        valid = {
            "private_task_memory",
            "accepted_memory",
            "candidate_memory",
            "archive_summary",
        }
        explicit = str(item.get("layer") or "").strip()
        if explicit in valid:
            return explicit
        kind = str(item.get("kind") or "").strip()
        status = str(item.get("status") or "candidate").strip().lower()
        exposed = bool(item.get("expose_to_normal"))
        if kind == "task_archive_summary":
            return "archive_summary"
        if kind == "workflow_private_memory":
            return "private_task_memory"
        if kind == "memory_candidate":
            return "candidate_memory"
        if exposed and status == "accepted":
            return "accepted_memory"
        if not exposed:
            return "private_task_memory"
        return "candidate_memory"

    @staticmethod
    def _normalize_memory_evidence(item: dict[str, Any]) -> dict[str, Any]:
        evidence = item.get("evidence")
        if not isinstance(evidence, dict):
            evidence = {}
        evidence.setdefault("memory_id", item.get("memory_id") or "")
        evidence.setdefault("source_task_id", item.get("source_task_id") or "")
        evidence.setdefault("source_umo", item.get("source_umo") or "")
        evidence.setdefault("kind", item.get("kind") or "")
        evidence.setdefault("layer", item.get("layer") or "")
        return evidence

    def delete_memory_entry(self, memory_id: str) -> bool:
        items = self.list_memory_entries()
        kept = [item for item in items if item.get("memory_id") != memory_id]
        if len(kept) == len(items):
            return False
        self._write_json(self.memory_entries_path, kept)
        return True

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def _fernet(self) -> Fernet:
        if not self.secrets_key_path.exists():
            self._write_text(self.secrets_key_path, Fernet.generate_key().decode("ascii"))
        return Fernet(self.secrets_key_path.read_text(encoding="utf-8").strip().encode("ascii"))

    def _encrypt_secret(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt_secret(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            return ""
