"""Optional authenticated static console; the native Dashboard is preferred."""
from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any

from quart import Quart, Response, g, jsonify, request, send_from_directory


class StandaloneWebUIServer:
    def __init__(self, *, owner: Any, static_dir: Path, host: str, port: int, token: str = ""):
        if not str(token).strip():
            raise ValueError("Standalone console requires an administrator access token")
        self.owner, self.static_dir = owner, Path(static_dir)
        self.host, self.port, self.token = host, int(port), str(token).strip()
        self.url = f"http://{host}:{port}"
        self._shutdown_event: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self.app = Quart("astrbot_agent_lab_webui")
        self.app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
        self._wire_routes()

    async def start(self):
        if self._task and not self._task.done():
            return
        self._shutdown_event = asyncio.Event()
        self._task = asyncio.create_task(self.app.run_task(
            host=self.host, port=self.port, shutdown_trigger=self._shutdown_event.wait))
        await asyncio.sleep(0.05)
        if self._task.done():
            await self._task

    async def stop(self):
        if self._shutdown_event:
            self._shutdown_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, 5)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)

    def _wire_routes(self):
        app = self.app

        @app.before_request
        async def authenticate():
            if not request.path.startswith("/api/"):
                return None
            header = request.headers.get("Authorization", "")
            supplied = header.removeprefix("Bearer ") if header.startswith("Bearer ") else request.headers.get("X-Agent-Lab-Token", "")
            if not secrets.compare_digest(supplied, self.token):
                return jsonify({"ok": False, "error": "管理员 Token 无效"}), 401
            g.agent_lab_authenticated = True
            return None

        @app.get("/")
        async def index():
            html = (self.static_dir / "index.html").read_text(encoding="utf-8")
            html = html.replace('content="/api/plug/astrbot_plugin_agent_lab"', 'content="/api"')
            return Response(html, content_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})

        @app.get("/assets/<path:filename>")
        async def assets(filename: str):
            return await send_from_directory(self.static_dir / "assets", filename)

        @app.get("/api/health")
        async def health():
            return jsonify({"ok": True, "name": "Agent Lab", "auth": True})

        handlers = {
            "harness/state": (self.owner.api_harness_state, ["GET"]),
            "harness/task": (self.owner.api_harness_task, ["GET"]),
            "harness/create": (self.owner.api_harness_create, ["POST"]),
            "harness/action": (self.owner.api_harness_action, ["POST"]),
            "harness/template": (self.owner.api_harness_template, ["POST"]),
            "harness/events": (self.owner.api_harness_events, ["GET"]),
            "harness/memory": (self.owner.api_harness_memory, ["GET", "POST"]),
            "registry": (self.owner.api_registry, ["GET", "POST"]),
        }
        for path, (handler, methods) in handlers.items():
            app.add_url_rule("/api/" + path, endpoint=path.replace("/", "_"), view_func=handler, methods=methods)
