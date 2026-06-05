from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TickResult:
    message: str
    status: str = "ok"


class AgentLabService:
    """Service boundary between AstrBot adapter methods and Agent Lab runtime.

    This class intentionally starts as a thin adapter over the existing plugin
    implementation. It gives the runtime loop a stable home so subsequent work
    can move the full tick body out of main.py without changing commands,
    llm_tools, cron handlers, or WebUI APIs again.
    """

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def run_tick(self, event: Any, *, reason: str) -> TickResult:
        message = await self.adapter._tick_impl(event, reason)
        status = "paused" if "暂停" in message else "ok"
        if "失败" in message:
            status = "failed"
        return TickResult(message=message, status=status)
