from __future__ import annotations

import json
from typing import Any

from astrbot.core.agent.hooks import BaseAgentRunHooks

from .agent_runtime import AgentRuntime
from .models import now_iso
from .storage import AgentLabStorage


def _short(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...[truncated]"


class AgentLabRunHooks(BaseAgentRunHooks):
    def __init__(
        self,
        storage: AgentLabStorage,
        umo: str,
        task_id: str,
        *,
        budget_max_tools: int = 0,
    ):
        self.storage = storage
        self.umo = umo
        self.task_id = task_id
        self.budget_max_tools = max(0, int(budget_max_tools or 0))
        self.agent_runtime = AgentRuntime()

    def _load(self):
        task = self.storage.load_active_task(self.umo)
        if task and task.task_id == self.task_id:
            return task
        return None

    async def on_agent_begin(self, run_context) -> None:
        task = self._load()
        if not task:
            return
        self.agent_runtime.record_decision(
            task,
            phase="react",
            action="tool_loop_begin",
            node_id=task.workflow_current_node_id,
            reason="AstrBot tool_loop_agent started",
            capability="llm.reason",
        )
        task.add_log("agent_begin", "tool_loop_agent started")
        self.storage.save_task(task)

    async def on_tool_start(self, run_context, tool, tool_args: dict | None) -> None:
        task = self._load()
        if not task:
            return
        data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        tick = data.setdefault("tick_budget", {})
        if isinstance(tick, dict):
            tick["tool_calls_used"] = int(tick.get("tool_calls_used") or 0) + 1
            task.budget.tool_calls_used += 1
            if self.budget_max_tools and tick["tool_calls_used"] > self.budget_max_tools:
                task.status = "paused"
                task.watchdog.paused_reason = (
                    f"本轮工具预算已用尽：{tick['tool_calls_used']}/{self.budget_max_tools}"
                )
                task.watchdog.needs_user = True
                task.set_wait(
                    wait_reason="budget_exhausted",
                    message=task.watchdog.paused_reason,
                    source="tool_loop_budget",
                    required_input=[task.watchdog.paused_reason],
                )
                task.add_log("paused", task.watchdog.paused_reason)
        task.workflow_data = data
        task.add_log(
            "tool_start",
            f"{getattr(tool, 'name', 'unknown')} args={_short(tool_args, 800)}",
        )
        self.agent_runtime.record_decision(
            task,
            phase="tool",
            action="call_tool",
            node_id=task.workflow_current_node_id or "",
            reason=f"tool_loop requested {getattr(tool, 'name', 'unknown')}",
            capability="tool.call",
            tool_name=str(getattr(tool, "name", "unknown") or "unknown"),
        )
        self.storage.save_task(task)

    async def on_tool_end(self, run_context, tool, tool_args, tool_result) -> None:
        task = self._load()
        if not task:
            return
        tool_name = getattr(tool, "name", "unknown")
        observation = {
            "time": now_iso(),
            "source": "tool_loop",
            "node_id": task.workflow_current_node_id or "",
            "tool": tool_name,
            "args": _short(tool_args, 800),
            "result": _short(tool_result, 1200),
        }
        task.add_log(
            "tool_end",
            f"{tool_name} result={observation['result']}",
        )
        task.add_snapshot(
            "tool_end",
            {
                "tool": tool_name,
                "args": observation["args"],
                "result": observation["result"],
            },
        )
        data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        observations = data.setdefault("observations", [])
        if isinstance(observations, list):
            observations.append(observation)
            data["observations"] = observations[-120:]
        self.agent_runtime.record_observation(
            task,
            source="tool_loop",
            node_id=task.workflow_current_node_id or "",
            payload=observation,
            summary=observation.get("result") or "tool result",
        )
        self.agent_runtime.record_verdict(
            task,
            node_id=task.workflow_current_node_id or "",
            passed=tool_result is not None,
            status="completed" if tool_result is not None else "blocked",
            reason=(
                f"Tool {tool_name} returned a result."
                if tool_result is not None
                else f"Tool {tool_name} returned no result."
            ),
            next_action="agent_update_state",
        )
        task.last_observation = _short(
            json.dumps(observation, ensure_ascii=False, indent=2),
            4000,
        )
        data["resume"] = {
            "task_id": task.task_id,
            "updated_at": now_iso(),
            "reason": "tool_loop",
            "workflow_current_node_id": task.workflow_current_node_id,
            "workflow_path_tail": list(task.workflow_path or [])[-12:],
            "last_observation": task.last_observation,
            "node_outputs": data.get("node_outputs") or {},
            "node_output_ids": list((data.get("node_outputs") or {}).keys())[-40:],
            "variable_names": list((data.get("variables") or {}).keys())[-40:],
        }
        task.workflow_data = data
        self.storage.save_task(task)

    async def on_agent_done(self, run_context, llm_response) -> None:
        task = self._load()
        if not task:
            return
        task.add_log(
            "agent_done",
            _short(getattr(llm_response, "completion_text", ""), 1200),
        )
        task.add_snapshot(
            "agent_done",
            {"token_usage": task.token_usage},
        )
        self.agent_runtime.record_verdict(
            task,
            node_id=task.workflow_current_node_id or "",
            passed=True,
            status="completed",
            reason="tool_loop_agent completed one bounded ReAct pass.",
            next_action=task.next_step,
        )
        self.storage.save_task(task)
