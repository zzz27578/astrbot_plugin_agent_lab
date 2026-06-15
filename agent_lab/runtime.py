from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .models import AgentSpec, TaskState


REACT_ACTIONS = {
    "plan",
    "route_condition",
    "run_tools",
    "call_api",
    "transform_context",
    "request_approval",
    "wait_user",
    "handoff",
    "validate_output",
    "retry",
    "notify",
    "archive",
    "exit_summary",
    "manual",
}

REACT_KINDS = {"tool", "api", "subflow", "branch", "loop", "human", "validation"}

DETERMINISTIC_ACTIONS = {
    "listen_message",
    "schedule_trigger",
    "plugin_event_trigger",
    "webhook_trigger",
    "match_keyword",
    "match_regex",
    "llm_detect",
    "scope_filter",
    "limit_rate",
    "catch_error",
    "write_record",
    "generate_report",
    "send_message",
    "send_private_message",
    "send_email",
    "summarize_entry",
    "confirm_entry",
    "restore_isolation",
    "retrieve_memory",
    "save_state",
    "save_memory",
    "heartbeat",
    "agent_role",
    "api_scope",
    "prompt_inject",
    "note",
}


@dataclass
class WorkflowDecision:
    node_id: str = ""
    node: dict[str, Any] = field(default_factory=dict)
    next_node_id: str = ""
    status: str = "completed"
    outcome: str = ""
    note: str = ""
    needs_react: bool = False
    terminal: bool = False
    blocked: bool = False


@dataclass
class WorkflowRuntimeRun:
    steps: list[WorkflowDecision] = field(default_factory=list)
    needs_react: bool = False
    react_node_id: str = ""
    terminal: bool = False
    blocked: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.steps)

    def summary(self) -> str:
        parts = []
        for step in self.steps:
            arrow = f" -> {step.next_node_id}" if step.next_node_id else ""
            parts.append(f"{step.node_id}{arrow}: {step.outcome or step.note or step.status}")
        if self.needs_react and self.react_node_id:
            parts.append(f"react:{self.react_node_id}")
        return "\n".join(parts)


class WorkflowRuntime:
    """Small deterministic runner for Agent Lab canvas cursors.

    The LLM still handles open-ended ReAct work. This runner owns the cursor and
    performs safe bookkeeping nodes so the canvas is not just prompt text.
    """

    def __init__(self, max_auto_steps: int = 6) -> None:
        self.max_auto_steps = max(1, int(max_auto_steps or 6))

    def node_map(self, spec: AgentSpec) -> dict[str, dict[str, Any]]:
        return {
            str(node.get("id") or ""): node
            for node in spec.workflow_nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }

    def outgoing(self, spec: AgentSpec) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for edge in spec.workflow_edges:
            if not isinstance(edge, dict):
                continue
            start = str(edge.get("from") or "").strip()
            end = str(edge.get("to") or "").strip()
            if start and end:
                result.setdefault(start, []).append(end)
        return result

    def current_node_id(self, spec: AgentSpec, task: TaskState) -> str:
        current = str(task.workflow_current_node_id or "").strip()
        if current:
            return current
        if task.workflow_path:
            return str(task.workflow_path[-1] or "").strip()
        for node in spec.workflow_nodes:
            if node.get("action") == "summarize_entry":
                return str(node.get("id") or "").strip()
        for node in spec.workflow_nodes:
            if node.get("stage") == "entry":
                return str(node.get("id") or "").strip()
        return str(spec.workflow_nodes[0].get("id") or "").strip() if spec.workflow_nodes else ""

    def inspect(self, spec: AgentSpec, task: TaskState) -> WorkflowDecision:
        nodes = self.node_map(spec)
        current_id = self.current_node_id(spec, task)
        node = nodes.get(current_id) or {}
        if not current_id or not node:
            return WorkflowDecision(
                node_id=current_id,
                blocked=True,
                status="blocked",
                outcome="Workflow cursor does not point at a valid node.",
            )

        action = str(node.get("action") or "manual").strip()
        kind = str(node.get("kind") or "state").strip()
        outgoing = [node_id for node_id in self.outgoing(spec).get(current_id, []) if node_id in nodes]
        terminal = action in {"archive", "exit_summary"} or (
            str(node.get("stage") or "").strip() == "archive" and not outgoing
        )

        if terminal:
            return WorkflowDecision(
                node_id=current_id,
                node=node,
                terminal=True,
                needs_react=True,
                status="running",
                outcome="Archive/exit node needs final summary and finish decision.",
            )

        if action == "parallel_branch":
            return WorkflowDecision(
                node_id=current_id,
                node=node,
                status="running",
                outcome="Parallel branch should be executed by workflow runtime.",
            )

        if action in DETERMINISTIC_ACTIONS or kind in {
            "state",
            "guard",
            "memory",
            "retrieval",
            "trigger",
            "detector",
            "report",
            "rate_limit",
            "error_handler",
            "notification",
        }:
            target = outgoing[0] if len(outgoing) == 1 else ""
            needs_react = len(outgoing) > 1
            return WorkflowDecision(
                node_id=current_id,
                node=node,
                next_node_id=target,
                needs_react=needs_react,
                status="completed" if target else "running",
                outcome=self.deterministic_outcome(node, task, needs_react),
                note="workflow_runtime",
            )

        if action in REACT_ACTIONS or kind in REACT_KINDS:
            return WorkflowDecision(
                node_id=current_id,
                node=node,
                needs_react=True,
                status="running",
                outcome="Node requires ReAct reasoning, tool use, or branch choice.",
            )

        return WorkflowDecision(
            node_id=current_id,
            node=node,
            needs_react=True,
            status="running",
            outcome="Unknown node behavior is delegated to ReAct.",
        )

    @staticmethod
    def deterministic_outcome(
        node: dict[str, Any],
        task: TaskState,
        needs_react: bool = False,
    ) -> str:
        action = str(node.get("action") or "").strip()
        title = str(node.get("title") or node.get("id") or "node").strip()
        if action == "summarize_entry":
            return f"Entry brief is available for task {task.task_id}."
        if action == "confirm_entry":
            return "Entry confirmation is already satisfied because the task exists."
        if action == "restore_isolation":
            return "Session isolation snapshot is already applied for this task."
        if action == "retrieve_memory":
            return "Task memory retrieval checkpoint reached."
        if action == "save_state":
            return "Task checkpoint saved; route choice still needs reasoning." if needs_react else "Task checkpoint saved."
        if action == "save_memory":
            return "Private task memory checkpoint saved."
        if action == "heartbeat":
            return "Heartbeat checkpoint recorded."
        return f"Deterministic workflow node completed: {title}."

    def build_react_prompt(
        self,
        *,
        task: TaskState,
        node: dict[str, Any],
        next_candidates: list[dict[str, Any]],
        reason: str,
    ) -> str:
        candidate_lines = []
        for item in next_candidates:
            candidate_lines.append(
                "- "
                f"{item.get('id')}: {item.get('title') or item.get('action') or '-'}; "
                f"kind={item.get('kind') or '-'}; action={item.get('action') or '-'}; "
                f"condition={item.get('condition') or '-'}"
            )
        return "\n".join(
            [
                "Run one bounded ReAct step for the current Agent Lab workflow node.",
                f"- tick_reason: {reason or 'manual'}",
                f"- task_id: {task.task_id}",
                f"- root_goal: {task.root_goal}",
                f"- current_summary: {task.current_summary or '-'}",
                f"- last_progress: {task.last_confirmed_progress or '-'}",
                f"- last_observation: {task.last_observation or '-'}",
                f"- next_step_before_tick: {task.next_step or '-'}",
                "",
                "[Current Workflow Node]",
                f"- node_id: {node.get('id') or '-'}",
                f"- title: {node.get('title') or '-'}",
                f"- kind: {node.get('kind') or '-'}",
                f"- stage: {node.get('stage') or '-'}",
                f"- action: {node.get('action') or '-'}",
                f"- instruction: {node.get('instruction') or node.get('description') or '-'}",
                f"- node_prompt: {node.get('prompt') or '-'}",
                f"- condition: {node.get('condition') or '-'}",
                "",
                "[Next Candidates]",
                "\n".join(candidate_lines) if candidate_lines else "- none",
                "",
                "Rules:",
                "- Do not finish the task unless the completion conditions are actually met.",
                "- If this node has one clear next candidate, call agent_lab_advance_workflow after finishing the node.",
                "- If this node has multiple candidates, choose one explicitly and explain why.",
                "- Always call agent_lab_update_state before ending this tick.",
                "- For dangerous work, call agent_lab_request_approval before using the risky tool.",
            ]
        )
