from __future__ import annotations

from copy import deepcopy
from typing import Any


class SessionPluginGuard:
    """Read-only compatibility boundary for legacy task plugin snapshots.

    Tasks select tools locally. AstrBot's UMO preferences belong to daily chat,
    including when an old saved task still requests snapshot restoration.
    """

    def __init__(self, protected_plugins: set[str] | None = None) -> None:
        self._sp = None
        self.protected_plugins = set(protected_plugins or set())

    @property
    def sp(self):
        if self._sp is None:
            from astrbot.core import sp

            self._sp = sp
        return self._sp

    async def snapshot(self, umo: str) -> dict[str, Any]:
        cfg = await self.sp.get_async(
            scope="umo",
            scope_id=umo,
            key="session_plugin_config",
            default={},
        )
        return deepcopy(cfg if isinstance(cfg, dict) else {})

    async def apply_overrides(self, umo: str, plugin_overrides: dict[str, bool]) -> dict[str, Any]:
        # Preserve the return contract for saved workflows without applying
        # their private tool policy to the source bot's daily conversation.
        return await self.snapshot(umo)

    async def restore(self, umo: str, snapshot: dict[str, Any] | None) -> None:
        # A legacy snapshot has no ownership/revision information. Replaying
        # it can erase daily-chat edits, even if the task itself made no write.
        return None

    def _protected_config(self, umo: str, config: dict[str, Any]) -> dict[str, Any]:
        cfg = deepcopy(config)
        session_cfg = cfg.get(umo, {})
        if not isinstance(session_cfg, dict):
            session_cfg = {}
        enabled = set(session_cfg.get("enabled_plugins", []) or [])
        disabled = set(session_cfg.get("disabled_plugins", []) or [])
        self._protect_sets(enabled, disabled)
        session_cfg["enabled_plugins"] = sorted(enabled)
        session_cfg["disabled_plugins"] = sorted(disabled)
        cfg[umo] = session_cfg
        return cfg

    def _protect_sets(self, enabled: set[str], disabled: set[str]) -> None:
        for plugin_name in self.protected_plugins:
            disabled.discard(plugin_name)
            enabled.add(plugin_name)
