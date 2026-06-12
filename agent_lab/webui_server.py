from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from quart import Quart, jsonify, request, send_from_directory


class StandaloneWebUIServer:
    """Small Quart server for the standalone Agent Lab console."""

    def __init__(
        self,
        *,
        owner: Any,
        static_dir: Path,
        host: str,
        port: int,
        token: str = "",
    ) -> None:
        self.owner = owner
        self.static_dir = Path(static_dir)
        self.host = host
        self.port = int(port)
        self.token = str(token or "").strip()
        self.url = f"http://{self.host}:{self.port}"
        self._shutdown_event: asyncio.Event | None = None
        self._task: asyncio.Task[None] | None = None
        self.app = Quart("astrbot_agent_lab_webui")
        self._wire_routes()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._shutdown_event = asyncio.Event()
        self._task = asyncio.create_task(
            self.app.run_task(
                host=self.host,
                port=self.port,
                shutdown_trigger=self._shutdown_event.wait,
            )
        )
        await asyncio.sleep(0.05)
        if self._task.done():
            await self._task

    async def stop(self) -> None:
        if self._shutdown_event:
            self._shutdown_event.set()
        if not self._task:
            return
        try:
            await asyncio.wait_for(self._task, timeout=5)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def _wire_routes(self) -> None:
        app = self.app

        @app.get("/")
        async def index():
            resp = await send_from_directory(self.static_dir, "index.html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        @app.get("/app.js")
        async def app_js():
            resp = await send_from_directory(self.static_dir, "app.js")
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.get("/style.css")
        async def style_css():
            resp = await send_from_directory(self.static_dir, "style.css")
            resp.headers["Cache-Control"] = "no-cache"
            return resp

        @app.get("/api/health")
        async def health():
            return jsonify({"ok": True, "name": "Agent Lab", "auth": bool(self.token)})

        @app.get("/api/state")
        async def state():
            return await self._guard(self.owner.api_state)

        @app.route("/api/agents", methods=["GET", "POST", "DELETE"])
        async def agents():
            return await self._guard(self.owner.api_agents)

        @app.route("/api/workflow/check", methods=["GET", "POST"])
        async def workflow_check():
            return await self._guard(self.owner.api_workflow_check)

        @app.route("/api/workflow/dry-run", methods=["GET", "POST"])
        async def workflow_dry_run():
            return await self._guard(self.owner.api_workflow_dry_run)

        @app.post("/api/workflow/trigger")
        async def workflow_trigger():
            return await self._guard(self.owner.api_workflow_trigger)

        @app.route("/api/workflow/webhook", methods=["POST"])
        @app.route("/api/workflow/webhook/<path:webhook_path>", methods=["POST"])
        async def workflow_webhook(webhook_path: str = ""):
            return await self._guard(self.owner.api_workflow_webhook)

        @app.get("/api/workflow/runs")
        async def workflow_runs():
            return await self._guard(self.owner.api_workflow_runs)

        @app.route("/api/integrations", methods=["GET", "POST"])
        async def integrations():
            return await self._guard(self.owner.api_modules)

        @app.route("/api/modules", methods=["GET", "POST"])
        async def modules():
            return await self._guard(self.owner.api_modules)

        @app.route("/api/registry", methods=["GET", "POST"])
        async def registry():
            return await self._guard(self.owner.api_registry)

        @app.route("/api/memory", methods=["GET", "POST", "DELETE"])
        async def memory():
            return await self._guard(self.owner.api_memory)

        @app.get("/api/task/logs")
        async def task_logs():
            return await self._guard(self.owner.api_task_logs)

        @app.post("/api/task/start")
        async def task_start():
            return await self._guard(self.owner.api_task_start)

        @app.post("/api/task/tick")
        async def task_tick():
            return await self._guard(self.owner.api_task_tick)

        @app.post("/api/task/finish")
        async def task_finish():
            return await self._guard(self.owner.api_task_finish)

        @app.post("/api/task/cancel")
        async def task_cancel():
            return await self._guard(self.owner.api_task_cancel)

        @app.post("/api/task/heartbeat")
        async def task_heartbeat():
            return await self._guard(self.owner.api_task_heartbeat)

        @app.post("/api/task/approval")
        async def task_approval():
            return await self._guard(self.owner.api_task_approval)

    async def _guard(self, handler: Callable[[], Awaitable[Any]]) -> Any:
        if not self._authorized():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return await handler()

    def _authorized(self) -> bool:
        if not self.token:
            return True
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer ") and header.removeprefix("Bearer ").strip() == self.token:
            return True
        if request.headers.get("X-Agent-Lab-Token", "").strip() == self.token:
            return True
        return request.args.get("token", "").strip() == self.token
