"""Service boundary between AstrBot adapter methods and Agent Lab runtime."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TickResult:
    message: str = ""
    status: str = "ok"
    task_id: str = ""
    paused: bool = False


@dataclass
class HealthStatus:
    ok: bool = True
    checks: list[dict[str, Any]] = field(default_factory=list)

    def to_text(self) -> str:
        okc = sum(1 for c in self.checks if c.get("ok"))
        total = len(self.checks)
        parts = [f"Agent Lab Health: {okc}/{total} checks passed"]
        for c in self.checks:
            st = "OK" if c.get("ok") else "FAIL"
            parts.append(f"  [{st}] {c.get('name', '?')}: {c.get('detail', '')}")
        return "\n".join(parts)


class AgentLabService:
    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    async def run_tick(self, event: Any, *, reason: str) -> TickResult:
        message = await self.adapter._tick_impl(event, reason)
        status = "paused" if "暂停" in message else "ok"
        if "失败" in message:
            status = "failed"
        return TickResult(message=message, status=status)

    def check_health(self) -> HealthStatus:
        checks: list[dict[str, Any]] = []
        a = self.adapter
        pairs = [("storage","storage"),("memory_manager","memory_manager"),("pattern_library","pattern_library"),("memory_orchestrator","memory_orchestrator"),("verifier","verifier"),("agent_runtime","agent_runtime"),("runtime_runner","runtime_runner")]
        for name, attr in pairs:
            ok = hasattr(a, attr) and getattr(a, attr, None) is not None
            checks.append({"name": name, "ok": ok, "detail": "available" if ok else "missing"})
        return HealthStatus(checks=checks)
