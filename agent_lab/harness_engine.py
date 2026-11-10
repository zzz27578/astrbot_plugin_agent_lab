"""Small asynchronous task runner; model and tool execution belong to its adapter.

The runner advances approved plans at step boundaries, keeps bounded progress,
and never restarts durable work merely because a plugin was loaded again.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .harness_store import HarnessConflict, HarnessStore, TERMINAL_STATUSES, new_identifier, utc_now


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list):
        raise ValueError("Expected a string or list of strings")
    return [str(item).strip() for item in value if str(item).strip()]


def _tool_names(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part for part in re.split(r"[\s,，;；]+", value.strip()) if part]
    return _strings(value)


def _retained_constraints(existing: Any, pending: list[dict[str, Any]] | None = None) -> list[str]:
    constraints = list(dict.fromkeys(_strings(existing)))
    for entry in pending or []:
        if entry.get("mode") == "steer":
            message = str(entry.get("message") or "")
            if message and message not in constraints:
                constraints.append(message)
    if sum(len(item) for item in constraints) > 40000:
        raise ValueError("Task constraints exceed 40000 characters; explicitly consolidate them instead of discarding earlier instructions")
    return constraints


def normalize_steps(raw: Any, graph: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Validate a finite dependency graph. Independent nodes execute serially."""
    if graph:
        nodes, edges = graph.get("nodes", []), graph.get("edges", [])
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise ValueError("Graph nodes and edges must be lists")
        raw = []
        ids = [str(node.get("id") or "") for node in nodes if isinstance(node, dict)]
        for node in nodes:
            if not isinstance(node, dict) or not isinstance(node.get("data", {}), dict):
                raise ValueError("Invalid graph node")
            data = node.get("data") or {}
            raw.append({**data, "id": str(node.get("id") or ""), "depends_on": []})
        for edge in edges:
            if not isinstance(edge, dict) or edge.get("source") not in ids or edge.get("target") not in ids:
                raise ValueError("Graph edge refers to a missing node")
            for step in raw:
                if step["id"] == edge["target"]:
                    step["depends_on"].append(str(edge["source"]))
    if not isinstance(raw, list) or not raw or len(raw) > 100:
        raise ValueError("A plan must contain between 1 and 100 steps")
    steps = []
    for index, item in enumerate(raw):
        if isinstance(item, str):
            item = {"title": item, "instruction": item}
        if not isinstance(item, dict):
            raise ValueError("Every plan step must be an object")
        step_id = str(item.get("id") or f"step_{index + 1}").strip()
        title = str(item.get("title") or item.get("instruction") or "").strip()
        instruction = str(item.get("instruction") or title).strip()
        if not step_id or not title or not instruction:
            raise ValueError("Every step needs an id, title and instruction")
        arguments = item.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        kind = str(item.get("kind") or ("tool" if item.get("tool_name") else "agent"))
        if kind not in {"agent", "tool", "approval"}:
            raise ValueError(f"Unsupported node kind: {kind}; use agent, tool or approval")
        if kind == "tool" and not str(item.get("tool_name") or "").strip():
            raise ValueError("A tool step must name a concrete tool")
        dependencies = item.get("depends_on")
        if dependencies is None:
            dependencies = [steps[-1]["id"]] if steps else []
        dependencies = _strings(dependencies)
        steps.append({
            "id": step_id, "title": title, "instruction": instruction,
            "status": "pending", "evidence": [], "summary": "",
            "kind": kind,
            "tool_name": str(item.get("tool_name") or ""), "arguments": arguments,
            "depends_on": list(dict.fromkeys(dependencies)),
        })
    by_id = {step["id"]: step for step in steps}
    if len(by_id) != len(steps):
        raise ValueError("Step ids must be unique")
    visited: set[str] = set()
    pending = set(by_id)
    while pending:
        ready = {identifier for identifier in pending if set(by_id[identifier]["depends_on"]).issubset(visited)}
        if not ready:
            raise ValueError("Plan contains a dependency cycle or unknown dependency")
        visited.update(ready)
        pending.difference_update(ready)
    return steps


def graph_for_steps(steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "nodes": [{"id": step["id"], "position": {"x": 100 + index * 280, "y": 100},
                   "data": {key: step[key] for key in ("kind", "title", "instruction", "tool_name", "arguments")}}
                  for index, step in enumerate(steps)],
        "edges": [{"id": f"{source}--{step['id']}", "source": source, "target": step["id"]}
                  for step in steps for source in step["depends_on"]],
    }


class HarnessEngine:
    def __init__(self, store: HarnessStore, adapter: Any, config: Any = None):
        self.store, self.adapter = store, adapter
        self.config = config or {}
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._queued: set[str] = set()
        self._active: dict[str, asyncio.Task] = {}
        self._workers: list[asyncio.Task] = []
        self._scheduler: asyncio.Task | None = None
        self._workspace_locks: dict[str, asyncio.Lock] = {}
        self._started = False
        self._stopping = False

    def _cfg(self, name: str, default: Any) -> Any:
        try:
            return self.config.get(name, default)
        except (AttributeError, TypeError):
            return default

    def _require(self, task_id: str, mutable: bool = False) -> dict[str, Any]:
        task = self.store.get_task(task_id)
        if task is None:
            raise KeyError(f"Task not found: {task_id}")
        if mutable and task["status"] in TERMINAL_STATUSES:
            raise HarnessConflict("A finished task cannot restart; create a new task")
        return task

    async def _validate_definition(self, task: dict[str, Any]) -> None:
        validate = getattr(self.adapter, "validate_task", None)
        if callable(validate):
            await validate(task)
        build_tools = getattr(self.adapter, "build_toolset", None)
        if callable(build_tools):
            available = {f"api:{tool.harness_api_id}" if getattr(tool, "harness_api_id", "") else str(tool.name)
                         for tool in build_tools(task).tools if getattr(tool, "active", True)}
            missing = {step["tool_name"] for step in task.get("steps", [])
                       if step.get("kind") == "tool" and step.get("tool_name") not in available}
            if missing:
                raise ValueError("Plan binds unavailable or unselected tools; select permitted tools before saving: " + ", ".join(sorted(missing)))

    async def start(self) -> None:
        if self._started:
            return
        self.store.recover_interrupted()
        self._stopping = False
        self._started = True
        concurrency = max(1, min(int(self._cfg("harness_max_concurrent_tasks", 2)), 8))
        self._workers = [asyncio.create_task(self._worker(), name=f"agent-lab-harness-{index}") for index in range(concurrency)]
        self._scheduler = asyncio.create_task(self._schedule_watch(), name="agent-lab-scheduled-tasks")

    async def stop(self) -> None:
        if not self._started:
            return
        self._stopping = True
        for operation in list(self._active.values()):
            operation.cancel()
        for worker in self._workers:
            worker.cancel()
        if self._scheduler:
            self._scheduler.cancel()
        await asyncio.gather(*self._workers, *list(self._active.values()), *([self._scheduler] if self._scheduler else []), return_exceptions=True)
        self._scheduler = None
        self._workers.clear()
        self._active.clear()
        self._queued.clear()
        self._queue = asyncio.Queue()
        self.store.recover_interrupted()
        self._started = False

    def _schedule(self, task_id: str) -> None:
        if not self._started or self._stopping or task_id in self._queued or task_id in self._active:
            return
        task = self.store.get_task(task_id)
        if task and task["status"] == "queued":
            self._queued.add(task_id)
            self._queue.put_nowait(task_id)

    def _budgets(self, payload: dict[str, Any]) -> dict[str, Any]:
        supplied = payload.get("budgets") or {}
        if not isinstance(supplied, dict):
            raise ValueError("budgets must be an object")
        defaults = {
            "max_rounds": ("harness_max_rounds", 80, 1000),
            "max_tool_calls": ("harness_max_tool_calls", 240, 10000),
            "max_tokens": ("harness_max_tokens", 240000, 10000000),
            "max_repeated_errors": ("harness_max_repeated_errors", 3, 10),
            "max_no_progress": ("harness_max_no_progress", 3, 10),
            "step_timeout_seconds": ("harness_step_timeout_seconds", 300, 3600),
        }
        result = {}
        for name, (config_key, fallback, ceiling) in defaults.items():
            value = int(supplied.get(name, self._cfg(config_key, fallback)))
            if value <= 0 or value > ceiling:
                raise ValueError(f"{name} must be between 1 and {ceiling}")
            result[name] = value
        result.update(rounds_used=0, tool_calls_used=0, tokens_used=0, no_progress_count=0,
                      repeated_error_count=0, last_error="", last_result_signature="")
        return result

    async def create_task(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        if not self._started or self._stopping:
            raise HarnessConflict("Harness is not started")
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise ValueError("Task goal is required")
        execution_mode = str(payload.get("execution_mode") or "sandbox")
        if execution_mode not in {"sandbox", "direct"}:
            raise ValueError("execution_mode must be sandbox or direct")
        graph = payload.get("graph") or {}
        if not isinstance(graph, dict):
            raise ValueError("graph must be an object")
        raw_steps = payload.get("steps") or []
        steps = normalize_steps(raw_steps, graph if graph.get("nodes") else None) if raw_steps or graph.get("nodes") else []
        allowed_tools = list(dict.fromkeys(_strings(payload.get("allowed_tools"))))
        safe_defaults = {"astrbot_file_read_tool", "astrbot_grep_tool", "agent_lab_save_report"}
        server_preapproved = {*safe_defaults, *_tool_names(self._cfg("harness_preapproved_tools", []))}
        requested_preapproved = payload.get("preapproved_tools")
        preapproved = server_preapproved if requested_preapproved is None else server_preapproved.intersection(_strings(requested_preapproved))
        preapproved.update(safe_defaults)
        if allowed_tools:
            preapproved.intersection_update(allowed_tools)
        # The internal report tool is always present, independently of external
        # tool selection; it writes only this task's private report artifact.
        preapproved.add("agent_lab_save_report")
        task = {
            "task_id": new_identifier("task"), "title": str(payload.get("title") or goal[:80]),
            "goal": goal, "source_umo": str(payload.get("source_umo") or actor.get("source_umo") or ""),
            "provider_id": str(payload.get("provider_id") or ""), "execution_mode": execution_mode,
            "workspace": str(payload.get("workspace") or ""),
            "project_key": str(payload.get("project_key") or "").strip(),
            "allowed_tools": allowed_tools, "preapproved_tools": sorted(preapproved),
            "owner_id": str(actor.get("owner_id") or actor.get("user_id") or actor.get("id") or ""),
            "owner_platform": str(actor.get("owner_platform") or actor.get("platform") or ""),
            "actor_kind": str(actor.get("actor_kind") or actor.get("kind") or "chat"),
            "status": "awaiting_plan_approval" if steps else "queued",
            "plan_version": 1 if steps else 0, "approved_version": 0,
            "steps": steps, "graph": graph if steps and graph.get("nodes") else (graph_for_steps(steps) if steps else {"nodes": [], "edges": []}),
            "current_step_id": "", "constraints": _retained_constraints(payload.get("constraints")),
            "acceptance": _strings(payload.get("acceptance")), "summary": "",
            "next_action": "Review and approve the plan" if steps else "Prepare a plan for review",
            "budgets": self._budgets(payload), "inbox": [], "followups": [], "steering": [], "history": [],
            "pause_reason": "", "last_error": "",
            "scheduled_at": "", "schedule_armed": False, "schedule_plan_version": 0,
        }
        if task["actor_kind"] not in {"chat", "dashboard"}:
            raise ValueError("actor_kind must be chat or dashboard")
        await self._validate_definition(task)
        if not self._started or self._stopping:
            raise HarnessConflict("Harness stopped while the task was being validated")
        task = self.store.create_task(task)
        self._schedule(task["task_id"])
        return task

    async def approve_plan(self, task_id: str, plan_version: int, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        task = self._require(task_id, True)
        if task["status"] != "awaiting_plan_approval" or int(plan_version) != task["plan_version"]:
            raise HarnessConflict("Only the current plan awaiting review can be approved")
        if not task.get("steps"):
            raise HarnessConflict("Cannot approve an empty plan")
        task = self.store.update_task(task_id, {"approved_version": task["plan_version"], "approved_by": actor or {}, "approved_at": utc_now(), "status": "queued",
                                                "next_action": "Execute the approved plan", "pause_reason": ""},
                                      expected_revision=task["revision"], event_type="plan.approved")
        self._schedule(task_id)
        return task

    async def revise_plan(self, task_id: str, steps: Any, expected_version: int) -> dict[str, Any]:
        task = self._require(task_id, True)
        if task["plan_version"] != int(expected_version):
            raise HarnessConflict("Plan changed; refresh the plan before revising it")
        if isinstance(steps, dict) and "graph" in steps:
            envelope = steps
            graph = envelope.get("graph")
            if graph is not None and not isinstance(graph, dict):
                raise ValueError("graph must be an object")
            graph = graph if graph and graph.get("nodes") else None
            steps = envelope.get("steps")
        else:
            graph = steps if isinstance(steps, dict) and "nodes" in steps else None
        normalized = normalize_steps(steps, graph)
        completed = {step["id"]: step for step in task["steps"] if step["status"] == "completed"}
        for identifier, old in completed.items():
            replacement = next((step for step in normalized if step["id"] == identifier), None)
            if replacement is None or any(replacement.get(key) != old.get(key) for key in ("instruction", "tool_name", "arguments", "depends_on")):
                raise HarnessConflict("Completed steps cannot be removed or rewritten; add a new corrective step")
            replacement.update(status="completed", evidence=old.get("evidence", []), summary=old.get("summary", ""))
        await self._validate_definition({**task, "steps": normalized, "graph": graph or graph_for_steps(normalized)})
        # Persist the fence before cancelling any in-flight model or tool activity.
        self.store.update_task(task_id, {"status": "paused", "pause_reason": "plan_revision", "scheduled_at": "", "schedule_armed": False}, expected_revision=task["revision"], event_type="plan.revising")
        await self._halt_running(task_id)
        task = self._require(task_id, True)
        self.store.invalidate_approvals(task_id, "Plan revision changed")
        return self.store.update_task(task_id, {"steps": normalized, "graph": graph or graph_for_steps(normalized),
            "plan_version": task["plan_version"] + 1, "approved_version": 0,
            "status": "awaiting_plan_approval", "current_step_id": "", "next_action": "Review the revised plan"},
            expected_revision=task["revision"], event_type="plan.revised")

    async def _halt_running(self, task_id: str) -> None:
        operation = self._active.get(task_id)
        if operation is not None and operation is not asyncio.current_task():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        self.store.mark_interrupted_tools(task_id, "Execution interrupted; verify the external outcome before retrying")

    async def pause(self, task_id: str, reason: str = "User paused the task") -> dict[str, Any]:
        task = self._require(task_id, True)
        self.store.update_task(task_id, {"status": "paused", "pause_reason": reason,
                                      "scheduled_at": "", "schedule_armed": False,
                                      "next_action": "Review the checkpoint and explicitly resume"}, event_type="task.paused")
        await self._halt_running(task_id)
        return self._require(task_id)

    def _resume_checks(self, task: dict[str, Any]) -> None:
        if self.store.list_approvals(task["task_id"], "pending"):
            raise HarnessConflict("Resolve pending approvals before resuming")
        uncertain = [item for item in self.store.list_tool_calls(task["task_id"]) if item["status"] in {"started", "unknown"}]
        if uncertain:
            raise HarnessConflict("A tool outcome is unknown; reconcile it before resuming")
        budget = task["budgets"]
        if budget["rounds_used"] >= budget["max_rounds"] or budget["tokens_used"] >= budget["max_tokens"] or budget["tool_calls_used"] >= budget["max_tool_calls"]:
            raise HarnessConflict("Task budget exhausted; create a new task with the checkpoint and a reviewed budget")

    async def resume(self, task_id: str) -> dict[str, Any]:
        task = self._require(task_id, True)
        if task["status"] not in {"paused", "blocked", "waiting_approval"}:
            raise HarnessConflict("Only a paused, blocked or approved waiting task can resume")
        self._resume_checks(task)
        if task["steps"] and task["approved_version"] != task["plan_version"]:
            raise HarnessConflict("Approve the current plan before executing it")
        budgets = {**task["budgets"], "no_progress_count": 0, "repeated_error_count": 0, "last_error": ""}
        steps = [{**step, "status": "pending"} if step["status"] in {"running", "blocked", "waiting_approval"} else step for step in task["steps"]]
        task = self.store.update_task(task_id, {"status": "queued", "budgets": budgets, "steps": steps,
            "scheduled_at": "", "schedule_armed": False,
            "pause_reason": "", "last_error": "", "next_action": "Continue from the saved checkpoint"}, event_type="task.resumed")
        self._schedule(task_id)
        return task

    async def cancel(self, task_id: str, reason: str = "User cancelled the task") -> dict[str, Any]:
        task = self._require(task_id, True)
        self.store.update_task(task_id, {"status": "cancelled", "summary": task.get("summary") or reason,
                                       "scheduled_at": "", "schedule_armed": False,
                                       "next_action": "", "pause_reason": reason}, event_type="task.cancelled")
        await self._halt_running(task_id)
        self.store.invalidate_approvals(task_id, "Task cancelled")
        return self._require(task_id)

    async def delete(self, task_id: str) -> bool:
        task = self.store.get_task(task_id)
        if task is None:
            return False
        if task["status"] not in TERMINAL_STATUSES:
            await self.cancel(task_id, "Task deleted by user")
        return self.store.delete_task(task_id)

    async def schedule(self, task_id: str, run_at: str, plan_version: int, actor: dict[str, Any] | None = None) -> dict[str, Any]:
        """Approve this exact plan and schedule one start; never a periodic goal loop."""
        if not self._started or self._stopping:
            raise HarnessConflict("Harness is not started")
        task = self._require(task_id, True)
        if task["status"] not in {"awaiting_plan_approval", "paused", "blocked"}:
            raise HarnessConflict("Pause the task or finish planning before scheduling it")
        if int(plan_version) != task["plan_version"] or not task.get("steps"):
            raise HarnessConflict("Review the exact current plan before scheduling it")
        try:
            when = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("run_at must be an ISO timestamp with a timezone") from exc
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError("run_at must include a timezone, for example +08:00")
        when = when.astimezone(timezone.utc)
        if when <= datetime.now(timezone.utc):
            raise ValueError("Choose a future start time")
        self._resume_checks(task)
        return self.store.update_task(task_id, {"status": "paused", "approved_version": task["plan_version"], "approved_by": actor or {}, "approved_at": utc_now(),
            "scheduled_at": when.isoformat(), "schedule_armed": True, "schedule_plan_version": task["plan_version"],
            "pause_reason": "scheduled", "next_action": "Start this approved plan once at " + when.isoformat()},
            expected_revision=task["revision"], event_type="task.scheduled")

    async def _schedule_watch(self) -> None:
        while not self._stopping:
            for task in self.store.list_tasks(include_terminal=False, limit=10000):
                if not task.get("schedule_armed") or task["status"] != "paused" or not task.get("scheduled_at"):
                    continue
                try:
                    when = datetime.fromisoformat(task["scheduled_at"])
                    if when > datetime.now(timezone.utc):
                        continue
                    if task.get("schedule_plan_version") != task["plan_version"] or task["approved_version"] != task["plan_version"]:
                        raise HarnessConflict("The scheduled plan is no longer approved")
                    self._resume_checks(task)
                    validate = getattr(self.adapter, "validate_task", None)
                    if callable(validate):
                        await validate(task)
                    latest = self._require(task["task_id"])
                    if latest["revision"] != task["revision"] or not latest.get("schedule_armed"):
                        continue
                    self.store.update_task(task["task_id"], {"status": "queued", "scheduled_at": "", "schedule_armed": False,
                        "pause_reason": "", "next_action": "Execute the scheduled approved plan"},
                        expected_revision=task["revision"], event_type="schedule.due")
                    self._schedule(task["task_id"])
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    latest = self.store.get_task(task["task_id"])
                    if latest and latest.get("schedule_armed") and latest["status"] == "paused" and latest["revision"] == task["revision"]:
                        self.store.update_task(task["task_id"], {"status": "blocked", "schedule_armed": False,
                            "last_error": str(exc)[:2000], "next_action": "Review the schedule error and schedule again explicitly"},
                            expected_revision=latest["revision"], event_type="schedule.blocked")
            await asyncio.sleep(1)

    async def steer(self, task_id: str, message: str, mode: str = "steer") -> dict[str, Any]:
        task = self._require(task_id, True)
        message = str(message).strip()
        if not message or len(message) > 20000:
            raise ValueError("Steering text must contain 1 to 20000 characters")
        if mode not in {"steer", "followup", "inject"}:
            raise ValueError("mode must be steer, followup or inject")
        # Followups are retained requests for later human action. They neither
        # amend the current approved goal nor automatically create another task.
        field = "followups" if mode == "followup" else "inbox"
        pending = list(task.get(field) or [])
        if len(pending) >= 50:
            raise HarnessConflict("Too many pending instructions; resume or revise the task first")
        entry = {"id": new_identifier("input"), "message": message, "mode": mode, "created_at": utc_now()}
        pending.append(entry)
        if mode == "steer":
            _retained_constraints(task.get("constraints"), pending)
        task = self.store.update_task(task_id, {field: pending}, event_type="task.steered")
        self.store.append_event(task_id, "input.queued", entry)
        return task

    async def reconcile_tool(self, task_id: str, intent_id: str, outcome: str, summary: str,
                             actor: dict[str, Any] | None = None) -> dict[str, Any]:
        task = self._require(task_id)
        if task["status"] in {"running", "planning", "queued"}:
            raise HarnessConflict("Pause the task before confirming a tool outcome")
        self.store.reconcile_tool(task_id, intent_id, outcome, summary, actor)
        # Reconciliation is evidence, never implicit permission to resume.
        return self._require(task_id)

    async def accept_task(self, task_id: str) -> dict[str, Any]:
        task = self._require(task_id, True)
        if task["status"] != "awaiting_acceptance":
            raise HarnessConflict("Only a task awaiting acceptance can be accepted")
        if not task["steps"] or any(step["status"] != "completed" for step in task["steps"]):
            raise HarnessConflict("Task still has unfinished steps")
        return self.store.update_task(task_id, {"status": "completed", "next_action": "", "accepted_at": utc_now()}, event_type="task.accepted")

    async def resolve_approval(self, task_id: str, approval_id: str, approved: bool,
                               actor: dict[str, Any] | None = None) -> dict[str, Any]:
        self.store.resolve_approval(task_id, approval_id, approved, actor)
        task = self._require(task_id, True)
        if not approved:
            return await self.pause(task_id, "Operation approval rejected; revise the approach")
        if self.store.list_approvals(task_id, "pending"):
            return task
        # A concurrent user pause must not be undone by approving an operation.
        if task["status"] == "waiting_approval":
            return await self.resume(task_id)
        return task

    def request_approval(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.request_approval(task_id, payload)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        return self.store.get_task(task_id)

    def list_tasks(self, source_umo: str = "", owner_id: str = "", include_terminal: bool = True, limit: int = 500) -> list[dict[str, Any]]:
        return self.store.list_tasks(source_umo, owner_id, include_terminal, limit)

    def events(self, after_id: int = 0, task_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        return self.store.events(after_id, task_id, limit)

    def save_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        graph = payload.get("graph") or {}
        steps = normalize_steps(payload.get("steps"), graph if graph.get("nodes") else None)
        return self.store.save_template({**payload, "steps": steps, "graph": graph or graph_for_steps(steps)})

    def list_templates(self) -> list[dict[str, Any]]:
        return self.store.list_templates()

    def delete_template(self, template_id: str) -> bool:
        return self.store.delete_template(template_id)

    async def _notify(self, task: dict[str, Any], message: str) -> None:
        notify = getattr(self.adapter, "notify_task", None)
        if not callable(notify):
            return
        try:
            await asyncio.wait_for(notify(task, message), timeout=20)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A deleted task or an unavailable log must not kill a worker while
            # reporting an unrelated notification failure.
            try:
                self.store.append_event(task["task_id"], "notification.failed", {"error": str(exc)[:1000]})
            except (KeyError, HarnessConflict):
                pass

    async def _worker(self) -> None:
        while True:
            task_id = await self._queue.get()
            self._queued.discard(task_id)
            try:
                task = self.store.get_task(task_id)
                if not task or task["status"] != "queued" or task_id in self._active:
                    continue
                operation = asyncio.create_task(self._advance(task_id), name=f"harness-step-{task_id}")
                self._active[task_id] = operation
                try:
                    await operation
                except asyncio.CancelledError:
                    if self._stopping:
                        raise
                except Exception as exc:
                    latest = self.store.get_task(task_id)
                    if latest and latest["status"] not in TERMINAL_STATUSES and latest["status"] not in {"paused", "waiting_approval"}:
                        latest = self.store.update_task(task_id, {"status": "blocked", "last_error": str(exc)[:2000],
                            "next_action": "Inspect the recorded error and resume explicitly"}, event_type="runner.error")
                        await self._notify(latest, "Task stopped because of a runner error: " + str(exc)[:300])
            finally:
                self._active.pop(task_id, None)
                self._queue.task_done()
                self._schedule(task_id)
            await asyncio.sleep(0)

    async def _advance(self, task_id: str) -> None:
        task = self._require(task_id)
        workspace_key = str(Path(task["workspace"]).resolve()).casefold() if task.get("workspace") else task_id
        lock = self._workspace_locks.setdefault(workspace_key, asyncio.Lock())
        async with lock:
            task = self._require(task_id)
            if task["status"] != "queued":
                return
            self._resume_checks(task)
            budgets = dict(task["budgets"])
            budgets["rounds_used"] += 1
            pending = list(task.get("inbox") or [])
            steering = [*(task.get("steering") or []), *pending]
            # Input is durable independently; the adapter receives the latest 50
            # instructions while older ones remain queryable in the event log.
            changes = {"budgets": budgets, "inbox": [], "steering": steering[-50:],
                       "constraints": _retained_constraints(task.get("constraints"), pending)}
            planning = not task.get("steps")
            changes["status"] = "planning" if planning else "running"
            if not planning:
                if task["approved_version"] != task["plan_version"]:
                    self.store.update_task(task_id, {"status": "awaiting_plan_approval"}, event_type="plan.required")
                    return
                completed = {step["id"] for step in task["steps"] if step["status"] == "completed"}
                step = next((step for step in task["steps"] if step["status"] != "completed" and set(step["depends_on"]).issubset(completed)), None)
                if step is None:
                    if len(completed) == len(task["steps"]):
                        result = self.store.update_task(task_id, {"status": "awaiting_acceptance", "current_step_id": "", "next_action": "Review the evidence and accept the result"}, event_type="task.awaiting_acceptance")
                        await self._notify(result, "All plan steps have finished. Review the result before accepting this task.")
                        return
                    raise HarnessConflict("No runnable step; dependencies need review")
                changes["current_step_id"] = step["id"]
                changes["steps"] = [{**item, "status": "running"} if item["id"] == step["id"] else item for item in task["steps"]]
            task = self.store.update_task(task_id, changes, expected_revision=task["revision"], event_type="plan.started" if planning else "step.started")
            try:
                if planning:
                    proposed = await asyncio.wait_for(self.adapter.plan_task(task), timeout=budgets["step_timeout_seconds"])
                    steps = normalize_steps(proposed)
                    current = self._require(task_id)
                    if current["status"] != "planning" or current["plan_version"] != task["plan_version"]:
                        return
                    if any(item.get("mode") == "steer" for item in current.get("inbox") or []):
                        self.store.update_task(task_id, {"status": "queued", "next_action": "Replan with the administrator's new constraints before review"},
                                               event_type="plan.superseded_by_input")
                        return
                    current = self.store.update_task(task_id, {"steps": steps, "graph": graph_for_steps(steps), "plan_version": current["plan_version"] + 1,
                        "approved_version": 0, "status": "awaiting_plan_approval", "next_action": "Review and approve the proposed plan"}, event_type="plan.proposed")
                    await self._notify(current, "The plan is ready for review. Execution will start only after approval.")
                    return
                result = await asyncio.wait_for(self.adapter.run_step(task, dict(step)), timeout=budgets["step_timeout_seconds"])
                await self._apply_result(task, step, result)
            except asyncio.CancelledError:
                self.store.mark_interrupted_tools(task_id, "Step was interrupted; the tool outcome requires review")
                raise
            except Exception as exc:
                await self._record_error(task, exc)

    async def _record_error(self, dispatched: dict[str, Any], exc: Exception) -> None:
        task_id = dispatched["task_id"]
        current = self.store.get_task(task_id)
        if current is None:
            return
        if current["status"] not in {"running", "planning"} or current["plan_version"] != dispatched["plan_version"]:
            return
        error = f"{type(exc).__name__}: {exc}"[:2000]
        budgets = dict(current["budgets"])
        budgets["repeated_error_count"] = (budgets["repeated_error_count"] + 1) if budgets.get("last_error") == error else 1
        budgets["last_error"] = error
        budgets["no_progress_count"] += 1
        self.store.mark_interrupted_tools(task_id, error)
        uncertain = bool(self.store.list_tool_calls(task_id, "unknown"))
        blocked = uncertain or budgets["repeated_error_count"] >= budgets["max_repeated_errors"] or budgets["no_progress_count"] >= budgets["max_no_progress"] or budgets["rounds_used"] >= budgets["max_rounds"]
        current = self.store.update_task(task_id, {"status": "blocked" if blocked else "queued", "budgets": budgets,
            "last_error": error, "next_action": "Review the error and uncertain operations" if blocked else "Retry the incomplete step within its budget"}, event_type="step.error")
        if blocked:
            await self._notify(current, "Task stopped after an error: " + error[:500])

    @staticmethod
    def _usage_tokens(usage: Any) -> int:
        if isinstance(usage, dict):
            value = usage.get("total_tokens", usage.get("total", 0))
            if not value:
                value = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0) + int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        else:
            value = getattr(usage, "total_tokens", getattr(usage, "total", 0)) if usage is not None else 0
        return max(0, int(value or 0))

    @staticmethod
    def _stable_evidence_value(value: Any) -> Any:
        """Remove transport identity and timing metadata, not substantive output."""
        volatile = {"intent_id", "call_id", "tool_call_id", "request_id", "trace_id", "artifact_id",
                    "created_at", "updated_at", "finished_at", "timestamp", "elapsed", "elapsed_ms",
                    "duration", "duration_ms", "latency", "latency_ms", "reused"}
        if isinstance(value, dict):
            return {str(key): HarnessEngine._stable_evidence_value(item) for key, item in value.items()
                    if str(key).lower() not in volatile}
        if isinstance(value, list):
            return [HarnessEngine._stable_evidence_value(item) for item in value]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("{", "[")):
                try:
                    return HarnessEngine._stable_evidence_value(json.loads(stripped))
                except (ValueError, TypeError):
                    pass
            return "\n".join(line.rstrip() for line in stripped.replace("\r\n", "\n").split("\n"))
        return value

    def _verified_evidence(self, task: dict[str, Any], step: dict[str, Any], references: list[str]) -> tuple[list[str], set[str], set[str]]:
        """An id is evidence only if its committed result belongs to this step.

        Generated report artifacts prove text was saved and may support a final
        completion claim. They never reset the continue-loop progress counter.
        """
        calls = {call["intent_id"]: call for call in self.store.list_tool_calls(task["task_id"])}
        artifacts = {item["memory_id"]: item for item in self.store.list_memories(task["task_id"])}
        valid: list[str] = []
        fingerprints: set[str] = set()
        artifact_fingerprints: set[str] = set()
        for identifier in dict.fromkeys(references):
            call = calls.get(identifier)
            if (not call or call.get("status") != "completed" or call.get("step_id") != step["id"]
                    or call.get("plan_version") != task["plan_version"]):
                continue
            output = call.get("result")
            if isinstance(output, dict) and (output.get("ok") is False or output.get("isError") is True):
                continue
            if call.get("tool_name") == "agent_lab_save_report":
                raw = output.get("text", "") if isinstance(output, dict) else ""
                try:
                    descriptor = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                artifact = artifacts.get(str(descriptor.get("artifact_id") or "")) if isinstance(descriptor, dict) else None
                content = str((artifact or {}).get("text") or (artifact or {}).get("content") or "").strip()
                if not artifact or artifact.get("step_id") != step["id"] or not content:
                    continue
                material = {"kind": "report", "title": artifact.get("title", ""), "content": content}
                artifact_fingerprints.add(hashlib.sha256(json.dumps(self._stable_evidence_value(material), ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest())
            else:
                material = {"tool": call.get("tool_name"), "arguments": call.get("arguments") or {},
                            "result": self._stable_evidence_value(output)}
                fingerprints.add(hashlib.sha256(json.dumps(material, ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")).encode()).hexdigest())
            valid.append(identifier)
        return valid, fingerprints, artifact_fingerprints

    async def _apply_result(self, dispatched: dict[str, Any], step: dict[str, Any], result: Any) -> None:
        if not isinstance(result, dict) or result.get("status") not in {"completed", "continue", "waiting_approval", "blocked"}:
            raise ValueError("Adapter returned an invalid step result")
        task_id = dispatched["task_id"]
        current = self._require(task_id)
        if current["status"] not in {"running", "waiting_approval"} or current["plan_version"] != dispatched["plan_version"] or current["current_step_id"] != step["id"]:
            self.store.append_event(task_id, "step.result_after_state_change", {"step_id": step["id"], "result": result})
            return
        summary = str(result.get("summary") or "")[:12000]
        claimed_evidence = _strings(result.get("evidence"))[:100]
        budgets = dict(current["budgets"])
        budgets["tokens_used"] += self._usage_tokens(result.get("usage"))
        budgets["repeated_error_count"] = 0
        budgets["last_error"] = ""
        old_step = next(item for item in current["steps"] if item["id"] == step["id"])
        combined_evidence, fingerprints, artifact_fingerprints = self._verified_evidence(
            current, step, [*(old_step.get("evidence") or []), *claimed_evidence])
        evidence = [identifier for identifier in claimed_evidence if identifier in set(combined_evidence)]
        seen_fingerprints = set(current.get("evidence_fingerprints") or [])
        # Migration of an already-saved step must not count its old call ids as
        # fresh progress merely because fingerprint bookkeeping was introduced.
        _, previous_fingerprints, _ = self._verified_evidence(current, step, old_step.get("evidence") or [])
        seen_fingerprints.update(previous_fingerprints)
        signature = hashlib.sha256(json.dumps({"step": step["id"], "evidence": sorted(fingerprints)}, sort_keys=True).encode()).hexdigest()
        new_evidence = bool(fingerprints - seen_fingerprints)
        completed = result["status"] == "completed" and bool(summary.strip()) and bool(combined_evidence)
        progress = completed or new_evidence
        budgets["no_progress_count"] = 0 if progress else budgets["no_progress_count"] + 1
        if signature == budgets.get("last_result_signature") and not progress:
            budgets["no_progress_count"] = max(2, budgets["no_progress_count"])
        budgets["last_result_signature"] = signature
        next_action = str(result.get("next_action") or "")[:4000]
        status = "queued"
        step_status = "completed" if completed else "pending"
        if current["status"] == "waiting_approval" or result["status"] == "waiting_approval":
            status, step_status = "waiting_approval", "waiting_approval"
        elif result["status"] == "blocked":
            status, step_status = "blocked", "blocked"
        elif result["status"] == "completed" and not completed:
            next_action = "The step claims completion but lacks a summary or evidence; collect evidence"
        exhausted = budgets["rounds_used"] >= budgets["max_rounds"] or budgets["tokens_used"] >= budgets["max_tokens"] or budgets["tool_calls_used"] >= budgets["max_tool_calls"]
        no_progress = budgets["no_progress_count"] >= budgets["max_no_progress"]
        steps = [{**item, "status": step_status, "summary": summary, "evidence": combined_evidence,
                  "evidence_fingerprints": sorted(fingerprints), "artifact_fingerprints": sorted(artifact_fingerprints)}
                 if item["id"] == step["id"] else item for item in current["steps"]]
        all_done = all(item["status"] == "completed" for item in steps)
        if all_done and status == "queued":
            status, next_action = "awaiting_acceptance", "Review the evidence and accept the completed task"
        elif status == "queued" and (exhausted or no_progress):
            status = "blocked"
            next_action = "Task budget exhausted" if exhausted else "No new evidence after repeated attempts; change the approach before resuming"
        if self.store.list_tool_calls(task_id, "unknown") or self.store.list_tool_calls(task_id, "started"):
            status = "blocked"
            next_action = "Resolve unfinished tool outcomes before continuing"
        history = [*(current.get("history") or []), {"step_id": step["id"], "status": result["status"], "summary": summary[:1600], "evidence": evidence, "time": utc_now()}][-30:]
        current = self.store.update_task(task_id, {"status": status, "steps": steps, "budgets": budgets,
            "evidence_fingerprints": sorted(seen_fingerprints | fingerprints),
            "summary": summary or current.get("summary", ""), "next_action": next_action,
            "current_step_id": "" if all_done else step["id"], "history": history, "last_error": ""}, event_type="step.finished")
        self.store.append_event(task_id, "step.result", {"step_id": step["id"], "result": result})
        if status in {"waiting_approval", "blocked", "awaiting_acceptance"}:
            await self._notify(current, summary + "\n" + next_action)
