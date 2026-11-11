"""Small durable UI defaults and per-bot progress delivery settings."""
from __future__ import annotations

import asyncio


class WorkspacePreferences:
    def __init__(self, storage):
        self.storage = storage
        self.path = storage.registry_dir / "workspace_preferences.json"
        self.lock = asyncio.Lock()

    def read(self):
        return self.storage._read_json(self.path) if self.path.exists() else {}

    def for_viewer(self, actor, identities):
        data = self.read()
        default = str(data.get("viewers", {}).get(actor, ""))
        valid = {row["platform_id"] for row in identities}
        return {"default_bot_id": default if default in valid else "",
                "progress_by_bot": {identifier: self.progress(identifier, data) for identifier in valid}}

    def progress(self, identifier, data=None):
        row = (data if data is not None else self.read()).get("progress", {}).get(identifier, {})
        return {"enabled": bool(row.get("enabled", False)),
                "min_interval_seconds": max(30, min(600, int(row.get("min_interval_seconds", 60))))}

    async def save(self, actor, identifier, *, default=False, progress=None):
        async with self.lock:
            data = self.read()
            if default:
                data.setdefault("viewers", {})[actor] = identifier
            if progress is not None:
                if not isinstance(progress.get("enabled"), bool):
                    raise ValueError("进展简报开关必须为布尔值。")
                interval = int(progress.get("min_interval_seconds", 60))
                if not 30 <= interval <= 600:
                    raise ValueError("简报间隔需要30–600秒。")
                data.setdefault("progress", {})[identifier] = {"enabled": progress["enabled"], "min_interval_seconds": interval}
            self.storage._write_json(self.path, data)
