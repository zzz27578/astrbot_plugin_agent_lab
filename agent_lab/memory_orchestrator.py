"""Orchestrates finish-time memory and pattern bookkeeping.

This is the glue between task completion and the memory/pattern subsystems.
It keeps task memory evidence-linked without promoting private candidates into
normal-mode memory before a user or WebUI action accepts them."""

from __future__ import annotations

from typing import Any

from .models import AgentSpec, TaskState, now_iso


class AgentMemoryOrchestrator:
    """Coordinates memory and pattern persistence when a task finishes.

    Responsibilities:
    1. Preserve finish memory candidates as private candidate evidence.
    2. Upsert completed tasks into the pattern library.
    3. Produce a structured archive evidence summary.
    """

    def __init__(self, memory: Any, pattern_library: Any, storage: Any) -> None:
        self.memory = memory
        self.pattern_library = pattern_library
        self.storage = storage

    async def on_task_finish(
        self,
        task: TaskState,
        spec: AgentSpec,
        *,
        status: str,
        exit_summary: str,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "candidate_count": 0,
            "accepted_count": 0,
            "rejected_count": 0,
            "pattern": None,
            "archive_evidence": {},
            "errors": [],
        }

        # -- Phase 1: keep memory candidates private ----------------------------
        # AgentLabStorage.archive_task persists task.memory_candidates as
        # candidate_memory after the archive file is written. Do not auto-accept
        # them here; accepted long-term memory remains a user/WebUI decision.
        result["candidate_count"] = len(task.memory_candidates or [])
        if status == "cancelled":
            for entry in self.memory.candidates_for_task(task.task_id):
                try:
                    self.memory.reject(
                        entry.get("memory_id", ""),
                        reviewer="agent_lab_finish",
                        reason=f"Task cancelled: {exit_summary[:200]}",
                    )
                    result["rejected_count"] += 1
                except Exception as exc:
                    result.setdefault("errors", []).append(
                        f"reject_memory({entry.get('memory_id', '')}): {exc}"
                    )

        # -- Phase 2: upsert pattern -------------------------------------------
        try:
            pattern = self.pattern_library.upsert_from_task(task, spec)
            result["pattern"] = pattern
            if pattern:
                self.pattern_library.mark_used(pattern["pattern_id"])
        except Exception as exc:
            result.setdefault("errors", []).append(f"upsert_pattern: {exc}")

        # -- Phase 3: structured archive evidence ------------------------------
        result["archive_evidence"] = self._build_archive_evidence(task, status, exit_summary)
        return result

    def _build_archive_evidence(
        self, task: TaskState, status: str, exit_summary: str
    ) -> dict[str, Any]:
        runtime = (
            task.workflow_data.get("agent_runtime", {})
            if isinstance(task.workflow_data, dict)
            else {}
        )
        plan = runtime.get("plan", {}) if isinstance(runtime, dict) else {}
        steps = plan.get("steps", []) if isinstance(plan.get("steps"), list) else []
        verdicts = runtime.get("verdicts", []) if isinstance(runtime.get("verdicts"), list) else []
        decisions = runtime.get("decisions", []) if isinstance(runtime.get("decisions"), list) else []

        return {
            "task_id": task.task_id,
            "umo": task.umo,
            "status": status,
            "root_goal": task.root_goal,
            "completion_conditions": list(task.completion_conditions or []),
            "exit_summary": exit_summary,
            "steps_completed": sum(
                1 for s in steps if isinstance(s, dict) and s.get("status") == "done"
            ),
            "steps_total": len(steps),
            "verdict_count": len(verdicts),
            "decision_count": len(decisions),
            "tool_calls_used": task.budget.tool_calls_used,
            "ticks_used": task.budget.ticks_used,
            "tokens_used": task.budget.tokens_used,
            "memory_candidates_count": len(task.memory_candidates or []),
            "pattern_library_entries": len(
                self.pattern_library.list_patterns(status="all")
            ),
            "workflow_path": list(task.workflow_path or []),
            "archive_path": task.archive_path or "",
            "created_at": task.created_at,
            "finished_at": task.finished_at or now_iso(),
            "parallel_run_count": len(task.parallel_runs or []),
        }
