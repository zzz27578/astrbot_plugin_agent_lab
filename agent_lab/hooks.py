from __future__ import annotations

from typing import Any

from astrbot.core.agent.hooks import BaseAgentRunHooks

from .storage import AgentLabStorage


def _short(value: Any, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n...[truncated]"


class AgentLabRunHooks(BaseAgentRunHooks):
    def __init__(self, storage: AgentLabStorage, umo: str, task_id: str):
        self.storage = storage
        self.umo = umo
        self.task_id = task_id

    def _load(self):
        task = self.storage.load_active_task(self.umo)
        if task and task.task_id == self.task_id:
            return task
        return None

    async def on_agent_begin(self, run_context) -> None:
        task = self._load()
        if not task:
            return
        task.add_log("agent_begin", "tool_loop_agent started")
        self.storage.save_task(task)

    async def on_tool_start(self, run_context, tool, tool_args: dict | None) -> None:
        task = self._load()
        if not task:
            return
        task.add_log(
            "tool_start",
            f"{getattr(tool, 'name', 'unknown')} args={_short(tool_args, 800)}",
        )
        self.storage.save_task(task)

    async def on_tool_end(self, run_context, tool, tool_args, tool_result) -> None:
        task = self._load()
        if not task:
            return
        task.add_log(
            "tool_end",
            f"{getattr(tool, 'name', 'unknown')} result={_short(tool_result, 1200)}",
        )
        self.storage.save_task(task)

    async def on_agent_done(self, run_context, llm_response) -> None:
        task = self._load()
        if not task:
            return
        task.add_log(
            "agent_done",
            _short(getattr(llm_response, "completion_text", ""), 1200),
        )
        self.storage.save_task(task)

