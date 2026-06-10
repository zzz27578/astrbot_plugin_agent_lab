from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


CANONICAL_NODE_TYPES = {
    "trigger",
    "entry",
    "detector",
    "state",
    "decision",
    "parallel",
    "tool",
    "api",
    "memory",
    "guard",
    "validation",
    "notification",
    "report",
    "terminal",
    "react",
}

ACTION_RUNTIME_TYPES = {
    "listen_message": "trigger",
    "match_keyword": "detector",
    "match_regex": "detector",
    "llm_detect": "detector",
    "scope_filter": "guard",
    "schedule_trigger": "trigger",
    "plugin_event_trigger": "trigger",
    "webhook_trigger": "trigger",
    "summarize_entry": "entry",
    "confirm_entry": "entry",
    "restore_isolation": "entry",
    "variable_set": "state",
    "variable_get": "state",
    "text_template": "state",
    "llm_prompt": "state",
    "prompt_transform": "state",
    "plugin_prompt": "state",
    "json_transform": "state",
    "merge": "state",
    "iterator": "state",
    "subflow_call": "state",
    "plan": "react",
    "retrieve_memory": "memory",
    "save_memory": "memory",
    "summarize_memory": "memory",
    "export_task_memory": "memory",
    "promote_memory_candidate": "memory",
    "forget_task_memory": "memory",
    "archive_memory_folder": "memory",
    "save_state": "state",
    "heartbeat": "state",
    "transform_context": "state",
    "credential_ref": "guard",
    "cookie_jar": "guard",
    "browser_profile": "guard",
    "login_flow": "guard",
    "session_check": "guard",
    "refresh_session": "guard",
    "credential_scope": "guard",
    "secret_redaction": "state",
    "human_login_handoff": "guard",
    "revoke_session": "guard",
    "route_condition": "decision",
    "conditional_router": "decision",
    "parallel_branch": "parallel",
    "run_tools": "tool",
    "call_api": "api",
    "http_request": "api",
    "file_operation": "tool",
    "code_exec": "tool",
    "request_approval": "guard",
    "wait_user": "guard",
    "handoff": "guard",
    "validate_output": "validation",
    "debate_validation": "validation",
    "retry": "decision",
    "limit_rate": "guard",
    "catch_error": "guard",
    "notify": "notification",
    "send_message": "notification",
    "send_private_message": "notification",
    "send_email": "notification",
    "write_record": "state",
    "generate_report": "report",
    "deliver_outbox": "notification",
    "global_control": "guard",
    "skill_evolution": "guard",
    "archive_task": "terminal",
    "archive": "terminal",
    "exit_summary": "terminal",
    "manual": "react",
}

ACTION_EXECUTION_MODES = {
    "listen_message": "deterministic",
    "match_keyword": "deterministic",
    "match_regex": "deterministic",
    "llm_detect": "llm_guided",
    "scope_filter": "deterministic",
    "schedule_trigger": "deterministic",
    "plugin_event_trigger": "deterministic",
    "webhook_trigger": "deterministic",
    "summarize_entry": "deterministic",
    "confirm_entry": "deterministic",
    "restore_isolation": "deterministic",
    "variable_set": "deterministic",
    "variable_get": "deterministic",
    "text_template": "deterministic",
    "llm_prompt": "llm_guided",
    "prompt_transform": "llm_guided",
    "plugin_prompt": "llm_guided",
    "json_transform": "deterministic",
    "merge": "deterministic",
    "iterator": "deterministic",
    "subflow_call": "deterministic",
    "plan": "llm_guided",
    "retrieve_memory": "deterministic",
    "save_memory": "deterministic",
    "summarize_memory": "hybrid",
    "export_task_memory": "deterministic",
    "promote_memory_candidate": "deterministic",
    "forget_task_memory": "deterministic",
    "archive_memory_folder": "deterministic",
    "save_state": "deterministic",
    "heartbeat": "deterministic",
    "transform_context": "deterministic",
    "credential_ref": "deterministic",
    "cookie_jar": "deterministic",
    "browser_profile": "deterministic",
    "login_flow": "deterministic",
    "session_check": "deterministic",
    "refresh_session": "deterministic",
    "credential_scope": "deterministic",
    "secret_redaction": "deterministic",
    "human_login_handoff": "deterministic",
    "revoke_session": "deterministic",
    "route_condition": "deterministic",
    "conditional_router": "deterministic",
    "parallel_branch": "hybrid",
    "run_tools": "hybrid",
    "call_api": "deterministic",
    "http_request": "deterministic",
    "file_operation": "deterministic",
    "code_exec": "hybrid",
    "request_approval": "deterministic",
    "wait_user": "deterministic",
    "handoff": "deterministic",
    "validate_output": "deterministic",
    "debate_validation": "hybrid",
    "retry": "deterministic",
    "limit_rate": "deterministic",
    "catch_error": "deterministic",
    "notify": "deterministic",
    "send_message": "deterministic",
    "send_private_message": "deterministic",
    "send_email": "deterministic",
    "write_record": "deterministic",
    "generate_report": "hybrid",
    "deliver_outbox": "deterministic",
    "global_control": "deterministic",
    "skill_evolution": "deterministic",
    "archive_task": "deterministic",
    "archive": "llm_guided",
    "exit_summary": "llm_guided",
    "manual": "llm_guided",
}

KIND_RUNTIME_TYPES = {
    "trigger": "trigger",
    "detector": "detector",
    "report": "report",
    "rate_limit": "guard",
    "error_handler": "guard",
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

NODE_PORT_SCHEMAS: dict[str, dict[str, list[str]]] = {
    "trigger": {"inputs": [], "outputs": ["success", "error"]},
    "entry": {"inputs": ["start"], "outputs": ["success", "failed", "error"]},
    "detector": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "decision": {"inputs": ["input"], "outputs": ["success", "failed", "retry", "error", "always"]},
    "parallel": {"inputs": ["input"], "outputs": ["success", "failed", "error", "always"]},
    "guard": {"inputs": ["input"], "outputs": ["success", "failed", "approved", "rejected", "error", "timeout"]},
    "validation": {"inputs": ["input"], "outputs": ["success", "failed", "retry", "error"]},
    "notification": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "report": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "terminal": {"inputs": ["input"], "outputs": []},
}

ACTION_PORT_SCHEMAS: dict[str, dict[str, list[str]]] = {
    "listen_message": {"inputs": [], "outputs": ["success", "failed", "error"]},
    "schedule_trigger": {"inputs": [], "outputs": ["success", "error"]},
    "plugin_event_trigger": {"inputs": [], "outputs": ["success", "failed", "error"]},
    "webhook_trigger": {"inputs": [], "outputs": ["success", "failed", "error"]},
    "match_keyword": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "match_regex": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "llm_detect": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "scope_filter": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "retry": {"inputs": ["start", "retry", "error"], "outputs": ["retry", "success", "failed", "error"]},
    "limit_rate": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "catch_error": {"inputs": ["input", "error"], "outputs": ["success", "error", "failed"]},
    "request_approval": {"inputs": ["input"], "outputs": ["approved", "rejected", "timeout", "error"]},
    "credential_ref": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "cookie_jar": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "browser_profile": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "login_flow": {"inputs": ["input"], "outputs": ["success", "failed", "timeout", "error"]},
    "session_check": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "refresh_session": {"inputs": ["input"], "outputs": ["success", "failed", "timeout", "error"]},
    "credential_scope": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "secret_redaction": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "human_login_handoff": {"inputs": ["input"], "outputs": ["success", "timeout", "error"]},
    "revoke_session": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "llm_prompt": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "prompt_transform": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "plugin_prompt": {"inputs": ["input"], "outputs": ["success", "failed", "uncertain", "error"]},
    "summarize_memory": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "export_task_memory": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "promote_memory_candidate": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "forget_task_memory": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "archive_memory_folder": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "deliver_outbox": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "global_control": {"inputs": ["input"], "outputs": ["success", "failed", "error"]},
    "skill_evolution": {"inputs": ["input"], "outputs": ["success", "approved", "rejected", "error"]},
    "archive_task": {"inputs": ["input"], "outputs": []},
}

SPECIAL_MODULES = {
    "listen_message": "listener",
    "schedule_trigger": "listener",
    "plugin_event_trigger": "listener",
    "webhook_trigger": "listener",
    "retry": "loop",
    "limit_rate": "control",
    "catch_error": "control",
    "match_keyword": "detector",
    "match_regex": "detector",
    "llm_detect": "detector",
    "scope_filter": "detector",
    "credential_ref": "identity",
    "cookie_jar": "identity",
    "browser_profile": "identity",
    "login_flow": "identity",
    "session_check": "identity",
    "refresh_session": "identity",
    "credential_scope": "identity",
    "human_login_handoff": "identity",
    "revoke_session": "identity",
    "secret_redaction": "control",
    "llm_prompt": "prompt",
    "prompt_transform": "prompt",
    "plugin_prompt": "prompt",
    "summarize_memory": "memory",
    "export_task_memory": "memory",
    "promote_memory_candidate": "memory",
    "forget_task_memory": "memory",
    "archive_memory_folder": "memory",
    "deliver_outbox": "control",
    "global_control": "control",
    "skill_evolution": "control",
    "archive_task": "terminal",
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
    attempts: int = 1


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

    @staticmethod
    def execution_mode(node: dict[str, Any]) -> str:
        raw = str((node or {}).get("execution_mode") or "").strip()
        if raw in {"deterministic", "llm_guided", "hybrid"}:
            return raw
        action = str((node or {}).get("action") or "").strip()
        return ACTION_EXECUTION_MODES.get(action, "llm_guided")

    @staticmethod
    def normalize_execution_mode(node: dict[str, Any]) -> str:
        mode = NodeExecutorRegistry.execution_mode(node)
        node["execution_mode"] = mode
        return mode

    @staticmethod
    def port_schema(node: dict[str, Any]) -> dict[str, list[str]]:
        raw = (node or {}).get("port_schema")
        if isinstance(raw, dict):
            inputs = raw.get("inputs") if isinstance(raw.get("inputs"), list) else []
            outputs = raw.get("outputs") if isinstance(raw.get("outputs"), list) else []
            return {
                "inputs": [str(item).strip() for item in inputs if str(item).strip()],
                "outputs": [str(item).strip() for item in outputs if str(item).strip()],
            }
        action = NodeExecutorRegistry.action(node)
        if action in ACTION_PORT_SCHEMAS:
            return {key: list(value) for key, value in ACTION_PORT_SCHEMAS[action].items()}
        runtime_type = NodeExecutorRegistry.runtime_type(node)
        schema = NODE_PORT_SCHEMAS.get(runtime_type, {"inputs": ["input"], "outputs": ["success", "error"]})
        return {key: list(value) for key, value in schema.items()}

    @staticmethod
    def normalize_port_schema(node: dict[str, Any]) -> dict[str, list[str]]:
        schema = NodeExecutorRegistry.port_schema(node)
        node["port_schema"] = schema
        special = SPECIAL_MODULES.get(NodeExecutorRegistry.action(node))
        if special:
            node["special_module"] = special
        elif "special_module" in node:
            node.pop("special_module", None)
        return schema

    @staticmethod
    def edge_type_from_port(port: str) -> str:
        port = str(port or "").strip().lower()
        aliases = {
            "ok": "success",
            "pass": "success",
            "passed": "success",
            "yes": "success",
            "true": "success",
            "fail": "failed",
            "failed": "failed",
            "no": "failed",
            "false": "failed",
            "else": "failed",
            "unknown": "uncertain",
            "uncertain": "uncertain",
            "retry": "retry",
            "again": "retry",
            "error": "error",
            "exception": "error",
            "timeout": "timeout",
            "approved": "approved",
            "rejected": "rejected",
            "always": "always",
        }
        return aliases.get(port, "")
