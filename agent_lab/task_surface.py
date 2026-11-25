"""Tool exposure for plain tasks, with canvas controls as an opt-in extension."""
from __future__ import annotations

from copy import copy, deepcopy
from .canvas_mode import canvas_enabled, normalize_canvas_mode
from .task_tools import CONTROL_TOOL_NAMES, TASK_TOOL_SCHEMAS

CANVAS_TOOLS = {
    "agent_lab_advance_workflow", "agent_lab_update_workflow",
    "agent_lab_run_parallel_workflow", "agent_lab_update_state",
    "agent_lab_read_runtime", "agent_lab_read_state", "agent_lab_record_report",
    "agent_lab_request_approval", "agent_lab_finish",
}
HOST_TOOLS = ("astrbot_file_read_tool", "astrbot_grep_tool", "astrbot_file_write_tool",
              "astrbot_file_edit_tool", "astrbot_execute_shell", "astrbot_execute_python",
              "astrbot_execute_ipython")


def build_toolset(owner, spec, event=None):
    from astrbot.core.agent.tool import ToolSet
    task = owner.storage.load_active_task(event.unified_msg_origin) if event else None
    if normalize_canvas_mode(task):
        owner.storage.save_task(task)
    canvas = canvas_enabled(task)
    controls = CONTROL_TOOL_NAMES | (CANVAS_TOOLS if canvas else set())
    result = ToolSet()
    mode = str(spec.isolation_policy.tool_mode or "whitelist")
    external = mode != "no_external" and "__agent_lab_no_external_tools__" not in set(spec.enabled_tools or [])
    disabled = owner._disabled_plugin_names(spec)
    candidates = list(owner.context.get_llm_tool_manager().get_full_tool_set().tools) if external else []
    if external:
        for name in HOST_TOOLS:
            try:
                tool = owner.astrbot_bridge.tool(name, event)
            except (ImportError, KeyError, ValueError):
                tool = None
            if tool:
                candidates.append(tool)
    for tool in candidates:
        if tool.name.startswith("agent_lab_") or tool.name in CONTROL_TOOL_NAMES:
            # Registered custom APIs are optional execution tools, not controls.
            if tool.name != "agent_lab_call_custom_api":
                continue
        if owner._tool_available_for_agent(tool, disabled) and owner._tool_allowed_by_agent_profile(spec, tool.name):
            result.add_tool(tool)
    for name in sorted(controls):
        tool = owner.astrbot_bridge.tool(name, event)
        if tool:
            if name in CONTROL_TOOL_NAMES:
                schema = next(row["function"] for row in TASK_TOOL_SCHEMAS if row["function"]["name"] == name)
                tool = copy(tool)
                tool.parameters = deepcopy(schema["parameters"])
                tool.description = schema["description"]
            result.add_tool(tool)
    return result
