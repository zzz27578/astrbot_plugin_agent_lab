from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .models import AgentSpec, TaskState, new_id, now_iso


def _compact(value: Any, limit: int = 1200) -> str:
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...[truncated]"


@dataclass
class AgentCapability:
    name: str = ""
    capability: str = "tool.call"
    risk: str = "work"
    source: str = ""
    description: str = ""
    target: str = ""
    available: bool = True
    side_effect: bool = True
    requires_approval: bool = False
    retryable: bool = True
    result_parser: str = "json_or_text"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeDecision:
    decision_id: str = field(default_factory=lambda: new_id("decision"))
    phase: str = "plan"
    action: str = "continue"
    node_id: str = ""
    reason: str = ""
    capability: str = ""
    tool_name: str = ""
    next_node_id: str = ""
    requires_user: bool = False
    requires_approval: bool = False
    confidence: str = "medium"
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeObservation:
    observation_id: str = field(default_factory=lambda: new_id("obs"))
    source: str = "runtime"
    node_id: str = ""
    decision_id: str = ""
    summary: str = ""
    payload: Any = None
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RuntimeVerdict:
    verdict_id: str = field(default_factory=lambda: new_id("verdict"))
    node_id: str = ""
    passed: bool = False
    status: str = "unknown"
    reason: str = ""
    missing: list[str] = field(default_factory=list)
    next_action: str = ""
    created_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentRuntime:
    """Structured task runtime stored inside TaskState.workflow_data.

    AstrBot still owns messages, providers, cron and the concrete tool loop. This
    object is Agent Lab's durable contract around that substrate: capabilities,
    task plan, decisions, observations, verifier verdicts and resume anchors.
    """

    KEY = "agent_runtime"

    def ensure(self, task: TaskState) -> dict[str, Any]:
        data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        runtime = data.setdefault(self.KEY, {})
        if not isinstance(runtime, dict):
            runtime = {}
            data[self.KEY] = runtime
        runtime.setdefault("version", 1)
        runtime.setdefault("agent_instance", {})
        runtime.setdefault("capabilities", [])
        runtime.setdefault("capability_index", {})
        runtime.setdefault("plan", {})
        runtime.setdefault("decisions", [])
        runtime.setdefault("observations", [])
        runtime.setdefault("verdicts", [])
        runtime.setdefault("pattern_recommendations", [])
        runtime.setdefault("resume", {})
        runtime.setdefault("metrics", {})
        task.workflow_data = data
        return runtime

    def sync(
        self,
        task: TaskState,
        spec: AgentSpec,
        *,
        capabilities: list[dict[str, Any]] | None = None,
        reason: str = "sync",
    ) -> dict[str, Any]:
        runtime = self.ensure(task)
        rows = self.normalize_capabilities(
            capabilities if capabilities is not None else self.default_capabilities(spec)
        )
        runtime["capabilities"] = rows
        runtime["capability_index"] = {
            row["name"]: {
                "capability": row.get("capability", ""),
                "risk": row.get("risk", ""),
                "available": bool(row.get("available", True)),
                "requires_approval": bool(row.get("requires_approval", False)),
            }
            for row in rows
            if row.get("name")
        }
        plan = self.ensure_plan(task, spec)
        runtime["agent_instance"] = {
            "instance_id": f"{spec.agent_id}:{task.task_id}",
            "agent_id": spec.agent_id,
            "agent_name": task.agent_name or spec.name or spec.agent_id,
            "task_id": task.task_id,
            "status": task.status,
            "goal": task.root_goal,
            "lifecycle": {
                "create_task": bool(task.created_at),
                "load_context": bool(task.entry_summary or task.task_brief),
                "plan": bool(plan.get("steps")),
                "act": bool(runtime.get("decisions")),
                "observe": bool(runtime.get("observations")),
                "verify": bool(runtime.get("verdicts")),
                "persist": bool(task.updated_at),
                "pause": bool(self.waiting_reason(task)),
                "finish": task.status in {"completed", "cancelled"},
            },
            "budgets": {
                "ticks_used": task.budget.ticks_used,
                "max_total_ticks": task.budget.max_total_ticks,
                "tool_calls_used": task.budget.tool_calls_used,
                "max_total_tool_calls": task.budget.max_total_tool_calls,
                "tokens_used": task.budget.tokens_used,
                "max_total_tokens": task.budget.max_total_tokens,
            },
            "components": {
                "planner": "workflow_task_plan",
                "executor": "workflow_node_executor_plus_astrbot_tool_loop",
                "verifier": "structured_runtime_verdicts",
                "memory": "task_state_observations_candidates",
                "policy": "capability_catalog_and_approval_policy",
            },
            "updated_at": now_iso(),
        }
        self.update_resume(task, reason=reason)
        return runtime["agent_instance"]

    def ensure_plan(self, task: TaskState, spec: AgentSpec) -> dict[str, Any]:
        runtime = self.ensure(task)
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        node_ids = [str(node.get("id") or "") for node in spec.workflow_nodes if isinstance(node, dict)]
        if steps and {str(item.get("node_id") or "") for item in steps} == set(node_ids):
            self.sync_plan_status(task)
            return plan
        built_steps = []
        for index, node in enumerate(spec.workflow_nodes[:100], start=1):
            if not isinstance(node, dict):
                continue
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue
            built_steps.append(
                {
                    "step_id": f"step_{index:02d}_{node_id}",
                    "node_id": node_id,
                    "title": str(node.get("title") or node_id),
                    "stage": str(node.get("stage") or "plan"),
                    "action": str(node.get("action") or "manual"),
                    "capability": self.capability_for_node(node),
                    "status": self.initial_step_status(task, node_id),
                    "success_condition": str(
                        node.get("success_condition")
                        or node.get("output_schema")
                        or node.get("instruction")
                        or "Record an observation and advance or pause explicitly."
                    )[:500],
                }
            )
        plan = {
            "plan_id": new_id("plan"),
            "goal": task.root_goal,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "current_node_id": task.workflow_current_node_id,
            "steps": built_steps,
        }
        runtime["plan"] = plan
        task.add_log("agent_runtime_plan", f"plan initialized with {len(built_steps)} step(s)")
        return plan

    def sync_plan_status(self, task: TaskState) -> None:
        runtime = self.ensure(task)
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        current = str(task.workflow_current_node_id or "").strip()
        path = [str(item or "") for item in (task.workflow_path or [])]
        for step in steps:
            if not isinstance(step, dict):
                continue
            node_id = str(step.get("node_id") or "").strip()
            if current and node_id == current:
                step["status"] = "done" if task.status in {"completed", "cancelled"} else "running"
            elif node_id in path and step.get("status") != "blocked":
                step["status"] = "done"
            elif step.get("status") == "running":
                step["status"] = "pending"
        if plan:
            plan["current_node_id"] = current
            plan["updated_at"] = now_iso()

    def mark_current(self, task: TaskState, *, completed_node_id: str = "") -> None:
        self.sync_plan_status(task)
        runtime = self.ensure(task)
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
            if not isinstance(step, dict):
                continue
            if completed_node_id and step.get("node_id") == completed_node_id and step.get("status") != "blocked":
                step["status"] = "done"
        if plan:
            plan["updated_at"] = now_iso()

    def record_decision(
        self,
        task: TaskState,
        *,
        phase: str,
        action: str,
        node_id: str = "",
        reason: str = "",
        capability: str = "",
        tool_name: str = "",
        next_node_id: str = "",
        requires_user: bool = False,
        requires_approval: bool = False,
        confidence: str = "medium",
    ) -> dict[str, Any]:
        runtime = self.ensure(task)
        decision = RuntimeDecision(
            phase=phase,
            action=action,
            node_id=node_id or task.workflow_current_node_id,
            reason=_compact(reason, 900),
            capability=capability,
            tool_name=tool_name,
            next_node_id=next_node_id,
            requires_user=requires_user,
            requires_approval=requires_approval,
            confidence=confidence if confidence in {"low", "medium", "high"} else "medium",
        ).to_dict()
        self._append(runtime, "decisions", decision)
        runtime["last_decision"] = decision
        self.bump(runtime, "decisions")
        task.add_log("agent_decision", f"{phase}:{action} node={decision['node_id']} {decision['reason']}")
        self.update_resume(task, reason=f"decision:{phase}:{action}")
        return decision

    def record_observation(
        self,
        task: TaskState,
        *,
        source: str,
        node_id: str = "",
        payload: Any = None,
        summary: str = "",
        decision_id: str = "",
    ) -> dict[str, Any]:
        runtime = self.ensure(task)
        observation = RuntimeObservation(
            source=source,
            node_id=node_id or task.workflow_current_node_id,
            decision_id=decision_id,
            summary=_compact(summary or payload, 900),
            payload=payload,
        ).to_dict()
        self._append(runtime, "observations", observation)
        runtime["last_observation"] = observation
        self.bump(runtime, "observations")
        self.update_resume(task, reason=f"observation:{source}")
        return observation

    def record_verdict(
        self,
        task: TaskState,
        *,
        node_id: str = "",
        passed: bool,
        status: str = "",
        reason: str = "",
        missing: list[str] | None = None,
        next_action: str = "",
    ) -> dict[str, Any]:
        runtime = self.ensure(task)
        status = status or ("passed" if passed else "needs_review")
        verdict = RuntimeVerdict(
            node_id=node_id or task.workflow_current_node_id,
            passed=bool(passed),
            status=status,
            reason=_compact(reason, 900),
            missing=[str(item).strip() for item in (missing or []) if str(item).strip()],
            next_action=_compact(next_action, 500),
        ).to_dict()
        self._append(runtime, "verdicts", verdict)
        runtime["last_verdict"] = verdict
        self.bump(runtime, "verdicts")
        task.add_log("agent_verdict", f"{status} node={verdict['node_id']}: {verdict['reason']}")
        self.update_resume(task, reason=f"verdict:{status}")
        return verdict

    def record_pause(self, task: TaskState, *, reason: str, node_id: str = "", missing: list[str] | None = None) -> None:
        self.record_decision(
            task,
            phase="resume",
            action="pause",
            node_id=node_id or task.workflow_current_node_id,
            reason=reason,
            requires_user=True,
            confidence="high",
        )
        self.record_verdict(
            task,
            node_id=node_id or task.workflow_current_node_id,
            passed=False,
            status="paused",
            reason=reason,
            missing=missing or [reason],
            next_action="wait_user_or_resume",
        )
        self.update_resume(task, reason=f"pause:{reason}")

    def record_finish(self, task: TaskState, *, status: str, summary: str, memory_candidates: list[str] | None = None) -> None:
        self.mark_current(task, completed_node_id=task.workflow_current_node_id)
        self.record_decision(
            task,
            phase="archive",
            action="finish_task",
            node_id=task.workflow_current_node_id,
            reason=summary,
            capability="task.finish",
            confidence="high",
        )
        self.record_observation(
            task,
            source="archive",
            node_id=task.workflow_current_node_id,
            payload={"status": status, "summary": summary, "memory_candidates": memory_candidates or []},
            summary=summary,
        )
        self.record_verdict(
            task,
            node_id=task.workflow_current_node_id,
            passed=status in {"completed", "cancelled"},
            status=status,
            reason=summary,
            next_action="archived",
        )
        self.update_resume(task, reason="finish")

    def update_resume(self, task: TaskState, *, reason: str = "") -> dict[str, Any]:
        runtime = self.ensure(task)
        self.sync_plan_status(task)
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        pending_steps = []
        for step in plan.get("steps", []) if isinstance(plan.get("steps"), list) else []:
            if isinstance(step, dict) and step.get("status") in {"pending", "running", "blocked"}:
                pending_steps.append(
                    {
                        "step_id": step.get("step_id"),
                        "node_id": step.get("node_id"),
                        "title": step.get("title"),
                        "status": step.get("status"),
                    }
                )
        wait_state = self.wait_state(task)
        wait_reason = str(wait_state.get("wait_reason") or "")
        resume = {
            "task_id": task.task_id,
            "updated_at": now_iso(),
            "reason": reason,
            "status": task.status,
            "current_node_id": task.workflow_current_node_id,
            "resume_node": wait_state.get("resume_node") or task.workflow_current_node_id,
            "next_step": task.next_step,
            "resume_command": wait_state.get("resume_command") or self.resume_command(task, wait_reason),
            "waiting": wait_reason,
            "wait_state": wait_state,
            "last_decision_id": (runtime.get("last_decision") or {}).get("decision_id"),
            "last_observation_id": (runtime.get("last_observation") or {}).get("observation_id"),
            "last_verdict_id": (runtime.get("last_verdict") or {}).get("verdict_id"),
            "pending_steps": pending_steps[:12],
        }
        runtime["resume"] = resume
        return resume

    def summary(self, task: TaskState) -> dict[str, Any]:
        runtime = self.ensure(task)
        plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        caps = runtime.get("capabilities") if isinstance(runtime.get("capabilities"), list) else []
        return {
            "version": runtime.get("version", 1),
            "agent_instance": runtime.get("agent_instance") or {},
            "plan_id": plan.get("plan_id") or "",
            "current_node_id": plan.get("current_node_id") or task.workflow_current_node_id,
            "step_count": len(steps),
            "steps": steps[-40:],
            "capability_count": len(caps),
            "capabilities": caps[:120],
            "decisions": len(runtime.get("decisions") or []),
            "observations": len(runtime.get("observations") or []),
            "verdicts": len(runtime.get("verdicts") or []),
            "last_decision": runtime.get("last_decision") or {},
            "last_observation": runtime.get("last_observation") or {},
            "last_verdict": runtime.get("last_verdict") or {},
            "pattern_recommendations": runtime.get("pattern_recommendations") or [],
            "resume": runtime.get("resume") or {},
        }

    def summary_text(self, task: TaskState) -> str:
        summary = self.summary(task)
        instance = summary.get("agent_instance") or {}
        verdict = summary.get("last_verdict") or {}
        resume = summary.get("resume") or {}
        cap_lines = []
        for item in (summary.get("capabilities") or [])[:12]:
            cap_lines.append(
                f"- {item.get('name')}: {item.get('capability')} risk={item.get('risk')} "
                f"approval={'yes' if item.get('requires_approval') else 'no'} "
                f"available={'yes' if item.get('available', True) else 'no'}"
            )
        step_lines = []
        for item in (summary.get("steps") or [])[:16]:
            step_lines.append(
                f"- {item.get('node_id')}: {item.get('title') or item.get('action')} "
                f"[{item.get('status')}] capability={item.get('capability') or '-'}"
            )
        pattern_lines = []
        for item in (summary.get("pattern_recommendations") or [])[:5]:
            if not isinstance(item, dict):
                continue
            pattern_lines.append(
                f"- {item.get('pattern_id')}: score={item.get('score', 0)} "
                f"success={item.get('success_count', 0)} title={item.get('title') or '-'}"
            )
        return "\n".join(
            [
                "Agent Runtime:",
                f"- instance_id: {instance.get('instance_id') or '-'}",
                f"- status: {task.status}",
                f"- current_node: {summary.get('current_node_id') or '-'}",
                f"- lifecycle: {json.dumps(instance.get('lifecycle') or {}, ensure_ascii=False, sort_keys=True)}",
                f"- capability_count: {summary.get('capability_count')}",
                "Capabilities:",
                "\n".join(cap_lines) if cap_lines else "- none",
                "TaskPlan:",
                "\n".join(step_lines) if step_lines else "- none",
                "Task Pattern Recommendations:",
                "\n".join(pattern_lines) if pattern_lines else "- none",
                "Last Verdict:",
                f"- status={verdict.get('status') or '-'} passed={verdict.get('passed')} reason={verdict.get('reason') or '-'}",
                "Resume:",
                f"- waiting: {resume.get('waiting') or '-'}",
                f"- command: {resume.get('resume_command') or '/agentlab tick'}",
                f"- node: {resume.get('resume_node') or '-'}",
            ]
        )

    def default_capabilities(self, spec: AgentSpec) -> list[dict[str, Any]]:
        rows = []
        for name in spec.enabled_tools or []:
            if name == "__agent_lab_no_external_tools__":
                continue
            risk = str((spec.tool_risk_overrides or {}).get(name) or self.risk_for_tool_name(name))
            rows.append(
                AgentCapability(
                    name=str(name),
                    capability=self.capability_for_tool_name(str(name)),
                    risk=risk if risk in {"safe", "work", "high"} else "work",
                    source="agent_spec",
                    available=True,
                    side_effect=risk != "safe",
                    requires_approval=self.requires_approval_for_tool(str(name), risk, spec),
                    retryable=risk != "high",
                ).to_dict()
            )
        return rows

    @staticmethod
    def normalize_capabilities(capabilities: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        rows = []
        for raw in capabilities or []:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            risk = str(raw.get("risk") or "work").strip()
            risk = risk if risk in {"safe", "work", "high"} else "work"
            rows.append(
                AgentCapability(
                    name=name,
                    capability=str(raw.get("capability") or "tool.call").strip() or "tool.call",
                    risk=risk,
                    source=str(raw.get("source") or raw.get("plugin_name") or "").strip(),
                    description=str(raw.get("description") or "").strip(),
                    target=str(raw.get("target") or raw.get("api_id") or raw.get("tool_name") or "").strip(),
                    available=bool(raw.get("available", raw.get("effective_active", True))),
                    side_effect=bool(raw.get("side_effect", risk != "safe")),
                    requires_approval=bool(raw.get("requires_approval", risk == "high")),
                    retryable=bool(raw.get("retryable", risk != "high")),
                    result_parser=str(raw.get("result_parser") or "json_or_text").strip() or "json_or_text",
                    input_schema=raw.get("input_schema") if isinstance(raw.get("input_schema"), dict) else {},
                    output_schema=raw.get("output_schema") if isinstance(raw.get("output_schema"), dict) else {},
                    metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
                ).to_dict()
            )
        rows.sort(key=lambda item: (item.get("risk") == "high", item.get("risk") == "work", item.get("name", "")))
        return rows[:160]

    @staticmethod
    def capability_for_node(node: dict[str, Any]) -> str:
        action = str((node or {}).get("action") or "").strip()
        kind = str((node or {}).get("kind") or "").strip()
        if action == "call_api" or kind == "api":
            return "api.call"
        if action == "run_tools" or kind == "tool":
            return "tool.call"
        if action == "retrieve_memory":
            return "memory.read"
        if action == "save_memory":
            return "memory.write"
        if action in {"request_approval", "wait_user", "handoff"} or kind in {"human", "guard"}:
            return "human.wait"
        if action in {"validate_output", "retry", "route_condition"} or kind in {"validation", "branch", "loop"}:
            return "control.decide"
        if action == "parallel_branch":
            return "worker.parallel"
        if action in {"archive", "exit_summary"}:
            return "task.finish"
        return "state.update"

    @staticmethod
    def capability_for_tool_name(name: str) -> str:
        lowered = str(name or "").lower()
        if "grep" in lowered or "search" in lowered:
            return "file.search"
        if "file_read" in lowered or "read" in lowered:
            return "file.read"
        if "file_write" in lowered or "file_edit" in lowered or "write" in lowered or "edit" in lowered:
            return "file.write"
        if "shell" in lowered or "python" in lowered or "execute" in lowered:
            return "shell.run"
        if "api" in lowered:
            return "api.call"
        if "memory" in lowered:
            return "memory.read"
        if "workflow" in lowered:
            return "workflow.control"
        if "approval" in lowered:
            return "human.approval"
        return "tool.call"

    @staticmethod
    def risk_for_tool_name(name: str) -> str:
        lowered = str(name or "").lower()
        if any(word in lowered for word in ("delete", "remove", "reset", "clean", "secret", "credential", "deploy", "restart")):
            return "high"
        if any(word in lowered for word in ("read", "grep", "search", "status", "list")):
            return "safe"
        return "work"

    @classmethod
    def requires_approval_for_tool(cls, name: str, risk: str, spec: AgentSpec) -> bool:
        if str(risk or "").strip() == "high":
            return True
        lowered = str(name or "").lower()
        required = " ".join(str(item) for item in (spec.approval_policy.require_approval or [])).lower()
        return any(part and part in lowered for part in required.replace("-", "_").split())

    @staticmethod
    def waiting_reason(task: TaskState) -> str:
        wait = getattr(task, "wait", None)
        if wait and getattr(wait, "active", False):
            return str(getattr(wait, "wait_reason", "") or "need_user_decision")
        if task.pending_approvals():
            return "need_approval"
        if task.watchdog.needs_user:
            return task.watchdog.paused_reason or "need_user_decision"
        if task.status == "paused":
            return task.watchdog.paused_reason or "paused"
        if task.status == "blocked":
            return task.watchdog.paused_reason or "blocked_by_error"
        return ""

    @classmethod
    def wait_state(cls, task: TaskState) -> dict[str, Any]:
        wait = getattr(task, "wait", None)
        if wait and getattr(wait, "active", False):
            return {
                "active": True,
                "wait_reason": str(getattr(wait, "wait_reason", "") or "need_user_decision"),
                "message": str(getattr(wait, "message", "") or ""),
                "source": str(getattr(wait, "source", "") or ""),
                "resume_command": str(getattr(wait, "resume_command", "") or cls.resume_command(task, getattr(wait, "wait_reason", ""))),
                "resume_node": str(getattr(wait, "resume_node", "") or task.workflow_current_node_id),
                "required_input": list(getattr(wait, "required_input", []) or []),
                "created_at": str(getattr(wait, "created_at", "") or ""),
                "updated_at": str(getattr(wait, "updated_at", "") or ""),
            }
        wait_reason = cls.waiting_reason(task)
        if not wait_reason:
            return {"active": False}
        return {
            "active": True,
            "wait_reason": wait_reason,
            "message": task.watchdog.paused_reason or wait_reason,
            "source": "watchdog",
            "resume_command": cls.resume_command(task, wait_reason),
            "resume_node": task.workflow_current_node_id,
            "required_input": [task.watchdog.paused_reason] if task.watchdog.paused_reason else [],
            "created_at": "",
            "updated_at": "",
        }

    @staticmethod
    def resume_command(task: TaskState, wait_reason: str) -> str:
        if wait_reason == "need_approval":
            approvals = task.pending_approvals()
            if approvals:
                return f"/agentlab approve {approvals[0].approval_id}"
        return "/agentlab tick"

    @staticmethod
    def initial_step_status(task: TaskState, node_id: str) -> str:
        current = str(task.workflow_current_node_id or "").strip()
        if current and node_id == current:
            return "running"
        if node_id in [str(item or "") for item in (task.workflow_path or [])]:
            return "done"
        return "pending"

    @staticmethod
    def _append(runtime: dict[str, Any], key: str, value: dict[str, Any]) -> None:
        items = runtime.setdefault(key, [])
        if not isinstance(items, list):
            items = []
        items.append(value)
        runtime[key] = items[-160:]

    @staticmethod
    def bump(runtime: dict[str, Any], key: str) -> None:
        metrics = runtime.setdefault("metrics", {})
        if not isinstance(metrics, dict):
            metrics = {}
            runtime["metrics"] = metrics
        metrics[key] = int(metrics.get(key) or 0) + 1
        metrics["updated_at"] = now_iso()
