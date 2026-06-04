from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


CANONICAL_NODE_TYPES = {
    "entry",
    "state",
    "decision",
    "parallel",
    "tool",
    "api",
    "memory",
    "guard",
    "validation",
    "notification",
    "terminal",
    "react",
}

ACTION_RUNTIME_TYPES = {
    "summarize_entry": "entry",
    "confirm_entry": "entry",
    "restore_isolation": "entry",
    "retrieve_memory": "memory",
    "save_memory": "memory",
    "save_state": "state",
    "heartbeat": "state",
    "transform_context": "state",
    "route_condition": "decision",
    "parallel_branch": "parallel",
    "run_tools": "tool",
    "call_api": "api",
    "request_approval": "guard",
    "wait_user": "guard",
    "handoff": "guard",
    "validate_output": "validation",
    "retry": "decision",
    "notify": "notification",
    "archive": "terminal",
    "exit_summary": "terminal",
    "manual": "react",
}

KIND_RUNTIME_TYPES = {
    "state": "state",
    "tool": "tool",
    "guard": "guard",
    "human": "guard",
    "api": "api",
    "memory": "memory",
    "branch": "decision",
    "loop": "decision",
    "transform": "state",
    "retrieval": "memory",
    "subflow": "react",
    "notification": "notification",
    "validation": "validation",
}


@dataclass
class NodeExecutionResult:
    node_id: str = ""
    ok: bool = True
    status: str = "completed"
    outcome: str = ""
    note: str = ""
    next_node_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    needs_react: bool = False
    blocked: bool = False
    terminal: bool = False
    advance: bool = True


@dataclass
class NodeExecutionContext:
    event: Any
    task: Any
    spec: Any
    node: dict[str, Any]
    outgoing: list[str]
    next_candidates: list[dict[str, Any]]
    reason: str = ""


NodeExecutor = Callable[[NodeExecutionContext], Awaitable[NodeExecutionResult]]


class NodeExecutorRegistry:
    """Registry for workflow node executors.

    The canvas may keep legacy kind/action names, but the runtime only reasons
    over a small canonical type set. Registered executors make a node concrete;
    unregistered nodes are deliberately handed to ReAct instead of being faked.
    """

    def __init__(self) -> None:
        self._executors: dict[str, NodeExecutor] = {}

    def register(self, action: str, executor: NodeExecutor) -> None:
        action = str(action or "").strip()
        if action:
            self._executors[action] = executor

    def can_execute(self, node: dict[str, Any]) -> bool:
        return self.action(node) in self._executors

    async def execute(self, context: NodeExecutionContext) -> NodeExecutionResult:
        action = self.action(context.node)
        executor = self._executors.get(action)
        if not executor:
            return NodeExecutionResult(
                node_id=str(context.node.get("id") or ""),
                needs_react=True,
                advance=False,
                outcome=f"No executor registered for action={action or 'manual'}.",
                note="node_executor_missing",
            )
        result = await executor(context)
        result.node_id = result.node_id or str(context.node.get("id") or "")
        return result

    @staticmethod
    def action(node: dict[str, Any]) -> str:
        return str((node or {}).get("action") or "manual").strip()

    @staticmethod
    def runtime_type(node: dict[str, Any]) -> str:
        raw = str((node or {}).get("runtime_type") or "").strip()
        if raw in CANONICAL_NODE_TYPES:
            return raw
        action = str((node or {}).get("action") or "").strip()
        if action in ACTION_RUNTIME_TYPES:
            return ACTION_RUNTIME_TYPES[action]
        kind = str((node or {}).get("kind") or "").strip()
        if kind in KIND_RUNTIME_TYPES:
            return KIND_RUNTIME_TYPES[kind]
        return "react"

    @staticmethod
    def normalize_node_runtime_type(node: dict[str, Any]) -> str:
        runtime_type = NodeExecutorRegistry.runtime_type(node)
        node["runtime_type"] = runtime_type
        return runtime_type

