from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolExecutionResult:
    ok: bool = True
    status: str = "completed"
    outcome: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    needs_react: bool = False
    note: str = "tool_executor"


class AstrBotToolExecutor:
    """Direct executor for concrete AstrBot tools used by workflow tool nodes.

    The owner is the plugin adapter. Keeping the AstrBot-specific dependency at
    this boundary lets the workflow runtime call a single executor while the
    plugin still owns storage, budget, schema helpers and tool manager access.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def call(
        self,
        *,
        event: Any,
        task: Any,
        spec: Any,
        node: dict[str, Any],
        tool_name: str,
        call_args: dict[str, Any],
    ) -> ToolExecutionResult:
        if not tool_name:
            return ToolExecutionResult(
                outcome="Tool node needs ReAct because no concrete tool_name is bound.",
                needs_react=True,
                note="node_executor_tool_react_fallback",
            )
        if not self.owner._tool_allowed_by_agent_profile(spec, tool_name):
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Tool is outside the Agent tool profile: {tool_name}",
                blocked=True,
                note="node_executor_tool_not_allowed",
            )
        tmgr = self.owner.context.get_llm_tool_manager()
        try:
            tool = tmgr.get_func(tool_name)
        except Exception:
            tool = None
        if not tool or not self.owner._tool_available_for_agent(tool, self.owner._disabled_plugin_names(spec)):
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Tool is unavailable or isolated: {tool_name}",
                blocked=True,
                note="node_executor_tool_unavailable",
            )
        capability = self.owner._infer_capability(
            tool_name,
            getattr(tool, "description", ""),
            getattr(tool, "handler_module_path", ""),
        )
        risk = self.owner._effective_tool_risk(
            spec,
            tool_name,
            self.owner._infer_tool_risk(tool_name, getattr(tool, "description", "")),
        )
        parameter_schema = self.owner._normalize_tool_input_schema(
            self.owner._tool_schema(
                tool,
                name=tool_name,
                description=getattr(tool, "description", ""),
            )
        )
        schema_reason = self.owner._schema_validation_message(
            parameter_schema,
            call_args,
            f"Tool arguments for {tool_name}",
        )
        if schema_reason:
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=schema_reason,
                blocked=True,
                data={
                    "tool_name": tool_name,
                    "args": call_args,
                    "parameters_schema": parameter_schema,
                },
                note="node_executor_tool_schema_mismatch",
            )
        if not self.owner._permission_allows_tool(node, capability=capability, risk=risk):
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Tool permission profile blocks {tool_name}: capability={capability}, risk={risk}",
                blocked=True,
                note="node_executor_tool_permission_blocked",
            )
        budget_reason = self.owner._consume_tool_budget(task, tool_name)
        if budget_reason:
            self.owner._pause_task_for_budget(task, budget_reason)
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                note="node_executor_tool_budget",
            )
        try:
            from astrbot.core.agent.run_context import ContextWrapper

            result = await tool.call(
                ContextWrapper(
                    context=event,
                    tool_call_timeout=int(self.owner._cfg_value("tool_call_timeout", 120)),
                ),
                **call_args,
            )
        except NotImplementedError:
            return ToolExecutionResult(
                outcome=f"Tool {tool_name} has no direct callable executor; ReAct/tool-loop is required.",
                needs_react=True,
                note="node_executor_tool_react_fallback",
            )
        except Exception as exc:
            return ToolExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"{type(exc).__name__}: {exc}",
                blocked=True,
                note="node_executor_tool_error",
            )
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        return ToolExecutionResult(
            outcome=self.owner._compact_text(text, 1000) or f"Tool {tool_name} completed.",
            data={
                "tool_name": tool_name,
                "args": call_args,
                "result": self.owner._compact_text(text, 2400),
            },
            note="node_executor_tool",
        )
