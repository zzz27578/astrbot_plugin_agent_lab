"""Shared catalog constants and adapter formatting helpers."""
from __future__ import annotations
from typing import Any

PLUGIN_NAME = "astrbot_plugin_agent_lab"
PLUGIN_VERSION = "v0.4.0"
PLUGIN_AUTHOR = "zzz27578 & Codex"
PLUGIN_DESC = "在 AstrBot 内创建、运行和管理个人任务模式。"
SKILL_NAME = "agent-mode"
ENTRY_SUMMARY_RULE_NAME = "agent-mode-entry-summary"
EXIT_SUMMARY_RULE_NAME = "agent-mode-exit-summary"
NO_EXTERNAL_TOOLS_SENTINEL = "__agent_lab_no_external_tools__"
CUSTOM_API_TOOL_NAME = "agent_lab_call_custom_api"
DEFAULT_BOT_LABEL = "当前 Bot"
AGENT_NAME_SUFFIX = "任务模式"
WORKFLOW_KINDS = {
    "state",
    "tool",
    "guard",
    "human",
    "api",
    "memory",
    "branch",
    "loop",
    "transform",
    "retrieval",
    "subflow",
    "notification",
    "validation",
    "trigger",
    "detector",
    "report",
    "rate_limit",
    "error_handler",
}
WORKFLOW_ACTIONS = {
    "listen_message",
    "match_keyword",
    "match_regex",
    "llm_detect",
    "scope_filter",
    "schedule_trigger",
    "plugin_event_trigger",
    "webhook_trigger",
    "confirm_entry",
    "summarize_entry",
    "restore_isolation",
    "variable_set",
    "variable_get",
    "text_template",
    "llm_prompt",
    "prompt_transform",
    "plugin_prompt",
    "json_transform",
    "merge",
    "iterator",
    "subflow_call",
    "plan",
    "route_condition",
    "conditional_router",
    "parallel_branch",
    "run_tools",
    "call_api",
    "http_request",
    "file_operation",
    "code_exec",
    "transform_context",
    "credential_ref",
    "cookie_jar",
    "browser_profile",
    "login_flow",
    "session_check",
    "refresh_session",
    "credential_scope",
    "secret_redaction",
    "human_login_handoff",
    "revoke_session",
    "retrieve_memory",
    "memory_filter",
    "summarize_memory",
    "export_task_memory",
    "promote_memory_candidate",
    "forget_task_memory",
    "archive_memory_folder",
    "request_approval",
    "wait_user",
    "handoff",
    "validate_output",
    "debate_validation",
    "retry",
    "limit_rate",
    "catch_error",
    "save_state",
    "save_memory",
    "write_record",
    "generate_report",
    "send_message",
    "send_private_message",
    "send_email",
    "deliver_outbox",
    "global_control",
    "skill_evolution",
    "heartbeat",
    "notify",
    "archive_task",
    "archive",
    "exit_summary",
    "manual",
    "agent_role",
    "api_scope",
    "dispatch_tasks",
    "collect_report",
    "agent_message",
    "agent_debate",
    "summarize_decision",
    "prompt_inject",
    "note",
    "delay",
}
AUTO_IDENTITY_LABEL_SOURCES = {
    "astrbot_runtime",
    "astrbot_persona",  # legacy value kept for existing AgentSpec files.
    "astrbot_config",
}
CONFIG_BOT_LABEL_KEYS = (
    "bot_label",
    "bot_display_name",
    "bot_name",
    "robot_name",
    "assistant_name",
    "wecom_ai_bot_name",
    "app_name",
    "kf_name",
)
DEFAULT_AGENT_NAMES = {
    "",
    f"{DEFAULT_BOT_LABEL}{AGENT_NAME_SUFFIX}",
    "AstrBot 任务模式",
    "任务模式",
}

BUILTIN_TOOL_CATALOG = [
    {
        "name": "astrbot_file_read_tool",
        "description": "Read files from the current AstrBot computer-use workspace.",
        "risk": "safe",
    },
    {
        "name": "astrbot_grep_tool",
        "description": "Search files with ripgrep in the current workspace.",
        "risk": "safe",
    },
    {
        "name": "astrbot_file_write_tool",
        "description": "Write UTF-8 text files in the workspace.",
        "risk": "work",
    },
    {
        "name": "astrbot_file_edit_tool",
        "description": "Edit files by replacing exact text.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_shell",
        "description": "Execute shell commands via AstrBot Computer Use.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_python",
        "description": "Execute Python in local runtime.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_ipython",
        "description": "Execute Python in sandbox/IPython runtime.",
        "risk": "work",
    },
    {
        "name": "astrbot_sandboxed_shell",
        "description": "Execute shell commands in an Agent Lab sandbox workspace when Docker/Podman is available.",
        "risk": "high",
    },
    {
        "name": "astrbot_sandboxed_python",
        "description": "Execute Python in an Agent Lab sandbox workspace when Docker/Podman is available.",
        "risk": "high",
    },
    {
        "name": "future_task",
        "description": "AstrBot proactive future task tool.",
        "risk": "work",
    },
    {
        "name": CUSTOM_API_TOOL_NAME,
        "description": "Call an Agent Lab registered custom API with managed credentials.",
        "risk": "work",
    },
    {
        "name": "agent_lab_read_task_memory",
        "description": "读取带标签的任务模式记忆，不需要进入任务模式。",
        "risk": "safe",
    },
    {
        "name": "agent_lab_recommend_task_patterns",
        "description": "Recommend reusable plan templates from completed Agent Lab tasks.",
        "risk": "safe",
    },
    {
        "name": "agent_lab_update_workflow",
        "description": "Check or edit Agent Lab workflow nodes and edges.",
        "risk": "work",
    },
    {
        "name": "agent_lab_run_parallel_workflow",
        "description": "Run outgoing workflow nodes from a parallel branch and merge their results.",
        "risk": "work",
    },
    {
        "name": "agent_lab_advance_workflow",
        "description": "Record and advance the current task workflow cursor.",
        "risk": "safe",
    },
]

# 由内置工具目录派生的名字集合，用于判断「AstrBot 核心内置工具」（不随插件隔离被关）。
_BUILTIN_TOOL_NAMES = {str(item.get("name") or "") for item in BUILTIN_TOOL_CATALOG}

BUILTIN_WORKFLOW_MODULE_CATALOG: dict[str, dict[str, Any]] = {
    "agent_role": {
        "kind": "state",
        "stage": "plan",
        "risk": "safe",
        "description": "Agent 角色块：在画布上声明子 Agent 泳道，和 AgentSpec.sub_agents 双向同步。",
    },
    "api_scope": {
        "kind": "api",
        "stage": "plan",
        "risk": "work",
        "description": "API 范围块：声明一组节点默认使用的自定义 API，与一次性 call_api 节点区分。",
    },
    "prompt_inject": {
        "kind": "state",
        "stage": "plan",
        "risk": "safe",
        "description": "提示注入节点：把局部提示写入 workflow_data.prompt_injections，影响后续执行节点。",
    },
    "note": {
        "kind": "state",
        "stage": "plan",
        "risk": "safe",
        "description": "兼容旧便签节点；保存或执行时按 prompt_inject 处理，不再是 No-Op。",
    },
    "delay": {
        "kind": "state",
        "stage": "execute",
        "risk": "safe",
        "description": "延时节点：等待 N 秒再继续（上限 300s），用于错峰/限频手动节流。",
    },
    "dispatch_tasks": {
        "kind": "branch",
        "stage": "execute",
        "risk": "work",
        "description": "主agent 把任务拆成 assignment，按领地/子Agent 指派并写入共享黑板。",
    },
    "collect_report": {
        "kind": "report",
        "stage": "checkpoint",
        "risk": "safe",
        "description": "收齐子Agent 并行输出，汇成结构化报告写入黑板。",
    },
    "agent_message": {
        "kind": "notification",
        "stage": "execute",
        "risk": "safe",
        "description": "向某个子Agent 的信箱投递一条意见或指令。",
    },
    "agent_debate": {
        "kind": "validation",
        "stage": "checkpoint",
        "risk": "work",
        "description": "让多个子Agent 互相质询/校验不确定结论（复用 debate 校验）。",
    },
    "summarize_decision": {
        "kind": "branch",
        "stage": "checkpoint",
        "risk": "work",
        "description": "主agent 读共享黑板做下一步决策，输出 next_step。",
    },
    "listen_message": {
        "kind": "trigger",
        "stage": "entry",
        "special_module": "listener",
        "risk": "safe",
        "description": "Receive AstrBot message events and start a workflow run.",
    },
    "schedule_trigger": {
        "kind": "trigger",
        "stage": "entry",
        "special_module": "listener",
        "risk": "safe",
        "description": "Start a workflow from one or more cron expressions.",
    },
    "webhook_trigger": {
        "kind": "trigger",
        "stage": "entry",
        "special_module": "listener",
        "risk": "work",
        "description": "Start a workflow from an external webhook payload.",
    },
    "plugin_event_trigger": {
        "kind": "trigger",
        "stage": "entry",
        "special_module": "listener",
        "risk": "work",
        "description": "Start a workflow from an AstrBot/plugin event payload.",
    },
    "summarize_entry": {
        "kind": "state",
        "stage": "entry",
        "special_module": "entry",
        "risk": "safe",
        "description": "Condense the trigger payload into a task brief before execution.",
    },
    "confirm_entry": {
        "kind": "guard",
        "stage": "entry",
        "special_module": "entry",
        "risk": "safe",
        "description": "Require an entry confirmation before the workflow proceeds.",
    },
    "restore_isolation": {
        "kind": "state",
        "stage": "entry",
        "special_module": "entry",
        "risk": "safe",
        "description": "Restore an isolated task snapshot for long-running agent work.",
    },
    "match_keyword": {
        "kind": "detector",
        "stage": "plan",
        "special_module": "detector",
        "risk": "safe",
        "description": "Route messages by configured keywords.",
    },
    "match_regex": {
        "kind": "detector",
        "stage": "plan",
        "special_module": "detector",
        "risk": "safe",
        "description": "Route messages by regular expression matches.",
    },
    "llm_detect": {
        "kind": "detector",
        "stage": "plan",
        "special_module": "detector",
        "risk": "work",
        "description": "Use a constrained LLM detector to classify a trigger payload.",
    },
    "scope_filter": {
        "kind": "guard",
        "stage": "guard",
        "special_module": "detector",
        "risk": "safe",
        "description": "Apply chat type, whitelist, blacklist and administrator scope rules.",
    },
    "variable_set": {"kind": "state", "stage": "plan", "risk": "safe", "description": "Write a workflow variable."},
    "variable_get": {"kind": "state", "stage": "plan", "risk": "safe", "description": "Read a workflow variable."},
    "text_template": {"kind": "transform", "stage": "plan", "risk": "safe", "description": "Render a text template from workflow context."},
    "llm_prompt": {
        "kind": "state",
        "stage": "plan",
        "special_module": "prompt",
        "risk": "work",
        "description": "Run a bounded prompt node with an explicit output contract.",
    },
    "prompt_transform": {
        "kind": "state",
        "stage": "plan",
        "special_module": "prompt",
        "risk": "work",
        "description": "Transform input with a bounded prompt and routeable result.",
    },
    "plugin_prompt": {
        "kind": "state",
        "stage": "execute",
        "special_module": "prompt",
        "risk": "work",
        "description": "Prepare a bounded prompt for an explicitly selected AstrBot plugin.",
    },
    "json_transform": {"kind": "transform", "stage": "plan", "risk": "safe", "description": "Map or reshape JSON data between nodes."},
    "merge": {"kind": "state", "stage": "plan", "risk": "safe", "description": "Merge variables or branch outputs."},
    "iterator": {"kind": "loop", "stage": "plan", "special_module": "loop", "risk": "safe", "description": "Iterate over a list and expose item state."},
    "subflow_call": {"kind": "subflow", "stage": "execute", "risk": "work", "description": "Call a reusable subflow or workflow fragment."},
    "plan": {"kind": "subflow", "stage": "plan", "risk": "work", "description": "Hand the current step to the ReAct planner."},
    "route_condition": {"kind": "branch", "stage": "plan", "risk": "safe", "description": "Route by a single condition expression."},
    "conditional_router": {"kind": "branch", "stage": "plan", "risk": "safe", "description": "Route by multiple structured conditions."},
    "parallel_branch": {"kind": "subflow", "stage": "execute", "risk": "work", "description": "Run outgoing worker nodes in parallel and merge their outputs."},
    "run_tools": {"kind": "tool", "stage": "execute", "risk": "work", "description": "Call a selected AstrBot tool or plugin-provided tool."},
    "call_api": {"kind": "api", "stage": "execute", "risk": "work", "description": "Call a registered custom API with managed credentials."},
    "http_request": {"kind": "api", "stage": "execute", "risk": "work", "description": "Perform an HTTP request under the API permission profile."},
    "file_operation": {"kind": "tool", "stage": "execute", "risk": "high", "description": "Read, write or edit files through the workflow runtime."},
    "code_exec": {"kind": "tool", "stage": "execute", "risk": "high", "description": "Execute code through a controlled tool/runtime path."},
    "transform_context": {"kind": "transform", "stage": "execute", "risk": "safe", "description": "Transform the active workflow context."},
    "credential_ref": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "work", "description": "Reference a managed credential without exposing its secret value."},
    "cookie_jar": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "high", "description": "Attach a managed cookie jar reference for authenticated workflows."},
    "browser_profile": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "high", "description": "Attach a managed browser profile reference."},
    "login_flow": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "high", "description": "Coordinate login state creation or validation."},
    "session_check": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "work", "description": "Check whether an identity/session reference is usable."},
    "refresh_session": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "high", "description": "Refresh an authenticated session with guardrails."},
    "credential_scope": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "work", "description": "Constrain where a credential/session may be used."},
    "secret_redaction": {"kind": "state", "stage": "guard", "special_module": "control", "risk": "safe", "description": "Redact secrets before reports, memory export or notifications."},
    "human_login_handoff": {"kind": "guard", "stage": "guard", "special_module": "identity", "risk": "work", "description": "Pause for a human to complete MFA, captcha or browser login."},
    "revoke_session": {"kind": "guard", "stage": "archive", "special_module": "identity", "risk": "high", "description": "Revoke or detach workflow session references."},
    "retrieve_memory": {"kind": "memory", "stage": "plan", "special_module": "memory", "risk": "safe", "description": "Retrieve task memory entries for the current workflow."},
    "memory_filter": {"kind": "memory", "stage": "entry", "special_module": "memory", "risk": "safe", "description": "Set task memory admission allow/deny lists, block daily memory and limit reflow exposure."},
    "summarize_memory": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "work", "description": "Summarize task memory before archive or handoff."},
    "export_task_memory": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "safe", "description": "Export selected task memory from workflow state."},
    "promote_memory_candidate": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "work", "description": "Promote a memory candidate into durable memory."},
    "forget_task_memory": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "work", "description": "Remove or ignore selected task memory entries."},
    "archive_memory_folder": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "work", "description": "Archive workflow memory into a scheme-level memory folder."},
    "request_approval": {"kind": "human", "stage": "guard", "risk": "work", "description": "Create an explicit approval gate before risky work."},
    "wait_user": {"kind": "human", "stage": "guard", "risk": "safe", "description": "Pause until the user provides input."},
    "handoff": {"kind": "human", "stage": "guard", "risk": "safe", "description": "Hand a workflow step to a human/operator."},
    "validate_output": {"kind": "validation", "stage": "checkpoint", "risk": "safe", "description": "Validate node output against schema or conditions."},
    "debate_validation": {"kind": "validation", "stage": "checkpoint", "risk": "work", "description": "Use a verifier/debate pass to validate uncertain output."},
    "retry": {"kind": "loop", "stage": "checkpoint", "special_module": "loop", "risk": "safe", "description": "Reverse-port retry controller with start/retry/error inputs and retry/success exits."},
    "limit_rate": {"kind": "guard", "stage": "guard", "special_module": "control", "risk": "safe", "description": "Rate-limit repeated trigger or action execution."},
    "catch_error": {"kind": "guard", "stage": "checkpoint", "special_module": "control", "risk": "safe", "description": "Catch error routes and redirect recovery flow."},
    "save_state": {"kind": "state", "stage": "checkpoint", "risk": "safe", "description": "Persist a workflow state snapshot."},
    "save_memory": {"kind": "memory", "stage": "archive", "special_module": "memory", "risk": "work", "description": "Save structured task memory."},
    "write_record": {"kind": "state", "stage": "archive", "risk": "work", "description": "Append an audit or workflow record."},
    "generate_report": {"kind": "report", "stage": "archive", "risk": "work", "description": "Generate and store a workflow report snapshot."},
    "send_message": {"kind": "notification", "stage": "archive", "risk": "work", "description": "Send a message to the current conversation."},
    "send_private_message": {"kind": "notification", "stage": "archive", "risk": "work", "description": "Send a private message notification."},
    "send_email": {"kind": "notification", "stage": "archive", "risk": "high", "description": "Send an email notification through configured tools/APIs."},
    "deliver_outbox": {"kind": "notification", "stage": "archive", "special_module": "control", "risk": "work", "description": "Deliver queued workflow outbox items."},
    "global_control": {"kind": "guard", "stage": "guard", "special_module": "control", "risk": "safe", "description": "Apply workflow-level isolation, progress, budget and error-control settings."},
    "skill_evolution": {"kind": "guard", "stage": "archive", "special_module": "control", "risk": "work", "description": "Generate a safe draft skill-rule evolution from accepted task memory."},
    "heartbeat": {"kind": "state", "stage": "checkpoint", "special_module": "control", "risk": "safe", "description": "Pulse or check heartbeat state for long-running agent tasks."},
    "notify": {"kind": "notification", "stage": "archive", "risk": "work", "description": "Create a generic workflow notification."},
    "archive_task": {"kind": "memory", "stage": "archive", "special_module": "terminal", "risk": "safe", "description": "Archive or complete a workflow-managed task."},
    "archive": {"kind": "report", "stage": "archive", "special_module": "terminal", "risk": "work", "description": "Hand archive work to the terminal ReAct path."},
    "exit_summary": {"kind": "report", "stage": "archive", "special_module": "terminal", "risk": "work", "description": "Create an exit summary for task completion and memory handoff."},
    "manual": {"kind": "subflow", "stage": "execute", "risk": "work", "description": "Blank prompt/module placeholder for custom operator instructions."},
}


def _cfg(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    try:
        return config.get(key, default)
    except Exception:
        return getattr(config, key, default)


def _bool_cfg(config: Any, key: str, default: bool = False) -> bool:
    return bool(_cfg(config, key, default))


def _message_tail(event: AstrMessageEvent, command_name: str) -> str:
    text = (event.message_str or "").strip()
    for prefix in (f"/{command_name}", command_name):
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix) :].strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _lines_or_none(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return "- none"
    return "\n".join(f"- {item}" for item in cleaned)



__all__ = ['PLUGIN_NAME', 'PLUGIN_VERSION', 'PLUGIN_AUTHOR', 'PLUGIN_DESC', 'SKILL_NAME', 'ENTRY_SUMMARY_RULE_NAME', 'EXIT_SUMMARY_RULE_NAME', 'NO_EXTERNAL_TOOLS_SENTINEL', 'CUSTOM_API_TOOL_NAME', 'DEFAULT_BOT_LABEL', 'AGENT_NAME_SUFFIX', 'WORKFLOW_KINDS', 'WORKFLOW_ACTIONS', 'AUTO_IDENTITY_LABEL_SOURCES', 'CONFIG_BOT_LABEL_KEYS', 'DEFAULT_AGENT_NAMES', 'BUILTIN_TOOL_CATALOG', '_BUILTIN_TOOL_NAMES', 'BUILTIN_WORKFLOW_MODULE_CATALOG', '_cfg', '_bool_cfg', '_message_tail', '_lines_or_none']
