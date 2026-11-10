"""Identity and transport boundary for the approved-plan Agent Lab harness."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from quart import Response, g, jsonify, request

from .agent_lab.api_executor import CustomApiExecutor
from .agent_lab.harness_adapter import HarnessAdapter
from .agent_lab.harness_engine import HarnessEngine
from .agent_lab.harness_store import HarnessConflict, HarnessStore
from .agent_lab.harness_tools import CORE_TOOLS
from .agent_lab.session_guard import SessionPluginGuard
from .agent_lab.storage import AgentLabStorage
from .agent_lab.webui_server import StandaloneWebUIServer

PLUGIN_NAME = "astrbot_plugin_agent_lab"
PLUGIN_VERSION = "v0.3.1"


def string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\s,，;；]+", value)
    return [str(item).strip() for item in value or [] if str(item).strip()] if isinstance(value, list) else []


@register(PLUGIN_NAME, "zzz27578 & Codex", "管理员长任务工作台：批准计划、持久进度和自动续接", PLUGIN_VERSION)
class AgentLabPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self.storage = AgentLabStorage(StarTools.get_data_dir(PLUGIN_NAME))
        self.harness_store = HarnessStore(self.storage.root)
        self.api_executor = CustomApiExecutor(self)
        self.harness_adapter = HarnessAdapter(self, self.harness_store, self.config)
        self.harness = HarnessEngine(self.harness_store, self.harness_adapter, self.config)
        self.webui_server: StandaloneWebUIServer | None = None
        self._closing = False
        self._register_web_apis()

    def _cfg_value(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def _group_disabled(self) -> bool:
        return bool(self._cfg_value("disable_group_tasks", True))

    def _admin_ids(self, umo: str = "") -> set[str]:
        try:
            cfg = self.context.get_config(umo=umo or None)
        except Exception:
            cfg = self.context.get_config()
        return set(string_list(cfg.get("admins_id", []))) | set(string_list(self._cfg_value("workflow_admin_ids", [])))

    def _source_allowed(self, umo: str) -> bool:
        if not umo:
            return True
        from astrbot.core.platform.message_session import MessageSession
        from astrbot.core.platform.message_type import MessageType
        try:
            session = MessageSession.from_str(umo)
        except (ValueError, TypeError):
            return False
        return not (self._group_disabled() and session.message_type != MessageType.FRIEND_MESSAGE)

    def _harness_actor_authorized(self, task: dict[str, Any]) -> bool:
        if not self._source_allowed(str(task.get("source_umo") or "")):
            return False
        if task.get("actor_kind") == "dashboard":
            return bool(task.get("owner_id"))
        return str(task.get("owner_id") or "") in self._admin_ids(str(task.get("source_umo") or ""))

    def _chat_actor(self, event: AstrMessageEvent) -> dict[str, str]:
        if self._group_disabled() and not event.is_private_chat():
            raise PermissionError("Agent Lab 已完全关闭群聊入口。请在管理员私聊或 Dashboard 中操作。")
        sender = str(event.get_sender_id() or "")
        if sender not in self._admin_ids(event.unified_msg_origin):
            raise PermissionError("此功能仅限 AstrBot 管理员或插件明确授权的管理员。")
        return {"owner_id": sender, "owner_platform": event.unified_msg_origin.split(":", 1)[0],
                "actor_kind": "chat", "source_umo": event.unified_msg_origin}

    def _web_actor(self) -> dict[str, str]:
        # AstrBot's authenticated plugin dispatcher copies username into Quart g.
        if getattr(g, "agent_lab_authenticated", False):
            return {"owner_id": "standalone-admin", "owner_platform": "dashboard", "actor_kind": "dashboard"}
        username = getattr(g, "username", None)
        if not isinstance(username, str) or not username.strip():
            raise PermissionError("Dashboard 管理员认证失效，请重新登录。")
        return {"owner_id": f"dashboard:{username}", "owner_platform": "dashboard", "actor_kind": "dashboard"}

    async def initialize(self):
        await self._retire_legacy_jobs()
        self._refresh_installed_skill()
        await self.harness.start()
        if self._cfg_value("standalone_webui_enabled", False):
            token = str(self._cfg_value("standalone_webui_token", "")).strip()
            if not token:
                logger.error("[AgentLab] 独立控制台需要 standalone_webui_token，已拒绝启动。原生页面不受影响。")
            else:
                self.webui_server = StandaloneWebUIServer(
                    owner=self, static_dir=Path(__file__).parent / "pages" / "agent-lab",
                    host=str(self._cfg_value("standalone_webui_host", "127.0.0.1")),
                    port=int(self._cfg_value("standalone_webui_port", 8788)), token=token,
                )
                await self.webui_server.start()
        logger.info(f"[AgentLab] {PLUGIN_VERSION} initialized; interrupted tasks require explicit review/resume.")

    async def terminate(self):
        self._closing = True
        await self.harness.stop()
        if self.webui_server:
            await self.webui_server.stop()
        self.context.registered_web_apis[:] = [
            api for api in self.context.registered_web_apis
            if getattr(api[1], "__self__", None) is not self
        ]
        self.harness_store.close()

    async def _retire_legacy_jobs(self):
        """Stop old bound callbacks and restore isolation; leave old data intact."""
        cron = getattr(self.context, "cron_manager", None)
        if cron:
            for job in await cron.list_jobs("basic"):
                if str(getattr(job, "name", "")).startswith(("agent_lab_", "agentlab_")):
                    await cron.delete_job(job.job_id)
        marker = self.storage.root / "harness_legacy_isolation_restored.json"
        if marker.exists():
            return
        restored = []
        guard = SessionPluginGuard(protected_plugins={PLUGIN_NAME})
        for task in self.storage.list_tasks():
            snapshot = task.profile_snapshot.get("session_plugin_snapshot")
            if isinstance(snapshot, dict) and task.profile_snapshot.get("restore_session_plugins", True):
                await guard.restore(task.umo, snapshot)
                restored.append(task.task_id)
        self.storage._write_json(marker, {"version": PLUGIN_VERSION, "restored_tasks": restored})

    def _refresh_installed_skill(self):
        """Replace only our old installed skill, retaining an upgrade backup."""
        from astrbot.core.utils.astrbot_path import get_astrbot_skills_path
        destination = Path(get_astrbot_skills_path()) / "agent-mode" / "SKILL.md"
        if not destination.is_file():
            return
        old_text = destination.read_text(encoding="utf-8")
        if "Agent Lab" not in old_text:
            return
        backup = self.storage.root / "upgrade_v0.3.0" / "agent-mode.SKILL.md"
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(destination, backup)
        source = Path(__file__).parent / "skills" / "agent-mode" / "SKILL.md"
        destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    def _task_public(self, task: dict[str, Any] | None, *, detail: bool = False) -> dict[str, Any]:
        if task is None:
            raise KeyError("任务不存在或已删除")
        row = dict(task)
        row["next_step"] = row.get("next_action", "")
        row["approvals"] = self.harness_store.list_approvals(row["task_id"])
        if detail:
            row["tool_calls"] = self.harness_store.list_tool_calls(row["task_id"])
            row["events"] = self.harness_store.task_recent_events(row["task_id"], limit=200)
            row["memories"] = self.harness_store.list_memories(row["task_id"])
            row["project_memories"] = self.harness_store.list_project_memories(str(row.get("project_key") or ""))
        return row

    def _provider_rows(self) -> list[dict[str, str]]:
        rows = []
        for provider in self.context.get_all_providers():
            meta = provider.meta()
            if callable(getattr(provider, "text_chat", None)):
                rows.append({"provider_id": str(meta.id), "model": str(provider.get_model())})
        return rows

    def _tool_rows(self) -> list[dict[str, Any]]:
        manager = self.context.get_llm_tool_manager()
        names = set(string_list(self._cfg_value("harness_allowed_tools", [])))
        rows = []
        for tool in manager.get_full_tool_set().tools:
            if tool.name.startswith("agent_lab_"):
                continue
            rows.append({"name": tool.name, "description": str(tool.description or ""),
                         "enabled": bool(tool.active), "allowed": tool.name in names or tool.name in CORE_TOOLS})
        core = {name: name for name in sorted(CORE_TOOLS)}
        for name, description in core.items():
            if not any(row["name"] == name for row in rows):
                rows.append({"name": name, "description": description, "enabled": True, "allowed": True})
        for api in self.storage.list_custom_apis():
            rows.append({"name": "api:" + api["api_id"], "description": api.get("description") or api["name"],
                         "enabled": True, "allowed": True})
        return rows

    def _legacy_rows(self) -> list[dict[str, Any]]:
        tasks = [*self.storage.list_tasks(), *self.storage.list_archives()]
        seen = set()
        rows = []
        for task in tasks:
            if task.task_id in seen:
                continue
            seen.add(task.task_id)
            rows.append({"task_id": task.task_id, "title": task.root_goal, "goal": task.root_goal,
                         "status": task.status, "source_umo": task.umo, "read_only": True,
                         "summary": task.exit_summary or task.current_summary})
        return rows[:200]

    def _register_web_apis(self):
        prefix = f"/{PLUGIN_NAME}/"
        self.context.registered_web_apis[:] = [api for api in self.context.registered_web_apis if not api[0].startswith(prefix)]
        routes = {
            "harness/state": (self.api_harness_state, ["GET"]),
            "harness/task": (self.api_harness_task, ["GET"]),
            "harness/create": (self.api_harness_create, ["POST"]),
            "harness/action": (self.api_harness_action, ["POST"]),
            "harness/template": (self.api_harness_template, ["POST"]),
            "harness/events": (self.api_harness_events, ["GET"]),
            "harness/memory": (self.api_harness_memory, ["GET", "POST"]),
            "registry": (self.api_registry, ["GET", "POST"]),
        }
        for path, (handler, methods) in routes.items():
            self.context.register_web_api(prefix + path, handler, methods, "Agent Lab " + path)

    async def _json_body(self) -> dict[str, Any]:
        payload = await request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return payload

    @staticmethod
    def _error(exc: Exception):
        code = 403 if isinstance(exc, PermissionError) else 404 if isinstance(exc, KeyError) else 409 if isinstance(exc, HarnessConflict) else 400
        return jsonify({"ok": False, "error": str(exc)}), code

    async def api_harness_state(self):
        try:
            self._web_actor()
            return jsonify({"ok": True, "version": PLUGIN_VERSION,
                "tasks": [self._task_public(task) for task in self.harness.list_tasks()],
                "templates": self.harness.list_templates(), "providers": self._provider_rows(),
                "tools": self._tool_rows(), "legacy_tasks": self._legacy_rows(),
                "config": {"disable_group_tasks": self._group_disabled(),
                           "default_execution_mode": self._cfg_value("harness_default_execution_mode", "sandbox"),
                           "default_workspace": self._cfg_value("harness_default_workspace", ""),
                           "max_concurrent_tasks": self._cfg_value("harness_max_concurrent_tasks", 1)}})
        except Exception as exc:
            return self._error(exc)

    async def api_harness_task(self):
        try:
            self._web_actor()
            return jsonify({"ok": True, "task": self._task_public(self.harness.get_task(str(request.args.get("task_id", ""))), detail=True)})
        except Exception as exc:
            return self._error(exc)

    async def _create(self, payload: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        if not self._source_allowed(str(payload.get("source_umo") or actor.get("source_umo") or "")):
            raise PermissionError("会话来源无效，或群聊任务已关闭")
        payload.setdefault("execution_mode", self._cfg_value("harness_default_execution_mode", "sandbox"))
        payload.setdefault("workspace", self._cfg_value("harness_default_workspace", ""))
        payload.setdefault("provider_id", self._cfg_value("harness_provider_id", ""))
        template_id = str(payload.get("template_id") or "")
        if template_id:
            template = next((item for item in self.harness.list_templates() if item["template_id"] == template_id), None)
            if not template:
                raise KeyError("所选模板不存在")
            payload["graph"] = template["graph"]
        payload.pop("preapproved_tools", None)
        return await self.harness.create_task(payload, actor)

    async def api_harness_create(self):
        try:
            actor = self._web_actor()
            return jsonify({"ok": True, "task": self._task_public(await self._create(await self._json_body(), actor)),
                            "message": "已立项；计划批准前不会执行。"})
        except Exception as exc:
            return self._error(exc)

    async def _action(self, payload: dict[str, Any], actor: dict[str, Any]) -> Any:
        task_id = str(payload.get("task_id") or "")
        action = str(payload.get("action") or "")
        if not task_id or not self.harness.get_task(task_id):
            raise KeyError("任务不存在，请刷新列表")
        if action == "approve_plan":
            return await self.harness.approve_plan(task_id, int(payload["plan_version"]), actor)
        if action == "schedule":
            return await self.harness.schedule(task_id, str(payload.get("run_at") or ""), int(payload["plan_version"]), actor)
        if action == "revise_plan":
            plan = payload.get("graph") or payload.get("steps")
            return await self.harness.revise_plan(task_id, plan, int(payload["plan_version"]))
        if action == "pause":
            return await self.harness.pause(task_id)
        if action == "resume":
            return await self.harness.resume(task_id)
        if action == "cancel":
            return await self.harness.cancel(task_id)
        if action == "delete":
            return await self.harness.delete(task_id)
        if action == "accept":
            return await self.harness.accept_task(task_id)
        if action == "steer":
            return await self.harness.steer(task_id, str(payload.get("message") or ""), str(payload.get("mode") or "steer"))
        if action in {"approve_tool", "reject_tool"}:
            return await self.harness.resolve_approval(task_id, str(payload.get("approval_id") or ""), action == "approve_tool", actor)
        if action == "reconcile_tool":
            return await self.harness.reconcile_tool(task_id, str(payload.get("intent_id") or ""),
                str(payload.get("outcome") or ""), str(payload.get("note") or ""), actor)
        raise ValueError("不支持的操作：" + action)

    async def api_harness_action(self):
        try:
            actor = self._web_actor()
            result = await self._action(await self._json_body(), actor)
            return jsonify({"ok": True, "task": self._task_public(result) if isinstance(result, dict) else None,
                            "deleted": result if isinstance(result, bool) else False, "message": "操作已保存。"})
        except Exception as exc:
            return self._error(exc)

    async def api_harness_template(self):
        try:
            self._web_actor()
            payload = await self._json_body()
            template = payload.get("template")
            if not isinstance(template, dict):
                raise ValueError("template 必须是对象")
            if payload.get("action", "save") == "delete":
                if not self.harness.delete_template(str(template.get("template_id") or "")):
                    raise KeyError("模板不存在")
                return jsonify({"ok": True, "deleted": True})
            if payload.get("action", "save") != "save":
                raise ValueError("未知模板操作")
            return jsonify({"ok": True, "template": self.harness.save_template(template)})
        except Exception as exc:
            return self._error(exc)

    async def api_harness_events(self):
        try:
            self._web_actor()
            cursor = max(0, int(request.args.get("after_id") or request.headers.get("Last-Event-ID") or 0))
            task_id = str(request.args.get("task_id") or "")
            standalone = bool(getattr(g, "agent_lab_authenticated", False))
        except Exception as exc:
            return self._error(exc)

        async def stream():
            nonlocal cursor
            idle = 0
            while not self._closing:
                for row in self.harness.events(cursor, task_id, 200):
                    cursor = row["id"]
                    data = {**row, "kind": row.get("type"), "time": row.get("created_at")}
                    yield f"id: {cursor}\nevent: message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                idle += 1
                if idle % 15 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(1)
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        if standalone:
            response = Response(stream(), content_type="text/event-stream", headers=headers)
            response.timeout = None
            return response
        # AstrBot's Quart compatibility buffers Quart responses; use native SSE.
        from starlette.responses import StreamingResponse
        return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)

    async def api_harness_memory(self):
        try:
            self._web_actor()
            if request.method == "POST":
                payload = await self._json_body()
                text = str(payload.get("text") or "").strip()
                if not text or len(text) > 20000:
                    raise ValueError("任务资料需为 1–20000 字符")
                payload = {key: payload[key] for key in ("task_id", "status", "share_with_project") if key in payload}
                payload["text"] = text
                item = self.harness_store.save_memory(str(payload.get("task_id") or ""), payload)
                return jsonify({"ok": True, "memory": item})
            task_id = str(request.args.get("task_id") or "")
            if not self.harness.get_task(task_id):
                raise KeyError("任务不存在")
            return jsonify({"ok": True, "memories": self.harness_store.list_memories(task_id)})
        except Exception as exc:
            return self._error(exc)

    async def api_registry(self):
        try:
            self._web_actor()
            if request.method == "POST":
                payload = await self._json_body()
                item = payload.get("item")
                if not isinstance(item, dict):
                    raise ValueError("item 必须是对象")
                kind, action = payload.get("kind"), payload.get("action", "save")
                if kind == "credential":
                    if action == "delete":
                        self.storage.delete_credential(str(item.get("credential_id") or ""))
                    elif action == "save":
                        self.storage.save_credential(item)
                    else:
                        raise ValueError("未知凭证操作")
                elif kind == "api":
                    if action == "delete":
                        identifier = str(item.get("api_id") or "")
                        rows = self.storage.list_custom_apis()
                        if not identifier or not any(row["api_id"] == identifier for row in rows):
                            raise KeyError("API 不存在")
                        self.storage._write_json(self.storage.custom_apis_path, [row for row in rows if row["api_id"] != identifier])
                    elif action == "save":
                        from urllib.parse import urlsplit
                        url = urlsplit(str(item.get("url") or ""))
                        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password:
                            raise ValueError("API URL 必须是有效 HTTP(S) 地址，凭证请单独保存")
                        if str(item.get("method") or "GET").upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
                            raise ValueError("不支持的 HTTP 方法")
                        self.storage.save_custom_api(item)
                    else:
                        raise ValueError("未知 API 操作")
                else:
                    raise ValueError("kind 必须是 api 或 credential")
            return jsonify({"ok": True, "custom_apis": self.storage.list_custom_apis(), "credentials": self.storage.list_credentials()})
        except Exception as exc:
            return self._error(exc)

    @staticmethod
    def _perform_custom_api_http_call(method, url, query, body, headers, timeout_seconds):
        return CustomApiExecutor.perform_http_call(method, url, query, body, headers, timeout_seconds)

    def _select_chat_task(self, event: AstrMessageEvent, task_id: str = "") -> dict[str, Any]:
        self._chat_actor(event)
        if task_id:
            task = self.harness.get_task(task_id)
            if task is None:
                raise KeyError("任务不存在")
            return task
        rows = self.harness.list_tasks(source_umo=event.unified_msg_origin, include_terminal=False)
        if len(rows) != 1:
            raise ValueError("请明确任务 ID。使用 /al list 查看，或在工作台选择任务。")
        return rows[0]

    @staticmethod
    def _status(task: dict[str, Any]) -> str:
        rows = [f"{task['title']}\nID: {task['task_id']}",
                f"状态: {task['status']} · 计划 v{task['plan_version']} / 已批准 v{task['approved_version']}"]
        rows.extend(f"{index + 1}. [{step['status']}] {step['title']}" for index, step in enumerate(task.get("steps", [])))
        if task.get("summary"):
            rows.append("进展: " + str(task["summary"])[:1200])
        rows.append("下一步: " + str(task.get("next_action") or "无"))
        return "\n".join(rows)

    @filter.command("al")
    async def al_command(self, event: AstrMessageEvent):
        try:
            result = await self._command(event)
        except Exception as exc:
            result = str(exc)
        yield event.plain_result(result)

    @filter.command("agentlab")
    async def agentlab_command(self, event: AstrMessageEvent):
        async for result in self.al_command(event):
            yield result

    async def _command(self, event: AstrMessageEvent) -> str:
        actor = self._chat_actor(event)
        text = str(event.message_str or "").strip()
        tail = re.sub(r"^/?(?:agentlab|al)(?:\s+|$)", "", text, count=1, flags=re.I)
        command, _, rest = tail.partition(" ")
        command, rest = command.strip().lower(), rest.strip()
        if command in {"", "help", "帮助"}:
            return ("Agent Lab 管理员任务工作台\n/al start <目标>：立项并生成计划\n/al list\n/al status [任务ID]\n"
                    "/al approve <任务ID> <计划版本号>\n/al pause|resume|cancel|accept <任务ID>\n"
                    "/al steer <任务ID> <补充要求>\n/al approve-tool|reject-tool <任务ID> <审批ID>\n"
                    "/al webui\n计划批准后自动推进；定时不再代替任务续跑。")
        if command == "webui":
            return "AstrBot Dashboard → 插件管理 → Agent Lab → agent-lab。" + (f"\n独立控制台：{self.webui_server.url}" if self.webui_server else "")
        if command == "start":
            return self._status(await self._create({"goal": rest, "source_umo": event.unified_msg_origin}, actor))
        if command in {"list", "tasks"}:
            return "\n".join(f"{task['task_id']} · {task['status']} · {task['title']}" for task in self.harness.list_tasks()) or "暂无任务。"
        identifier, _, argument = rest.partition(" ")
        task = self._select_chat_task(event, identifier)
        if command == "status":
            return self._status(task)
        payload: dict[str, Any] = {"task_id": task["task_id"], "action": command}
        if command == "approve":
            if not argument.strip().isdigit():
                raise ValueError("请提供已审阅的计划版本：/al approve <任务ID> <版本号>")
            payload.update(action="approve_plan", plan_version=int(argument))
        elif command in {"approve-tool", "reject-tool"}:
            payload.update(action=command.replace("-", "_"), approval_id=argument.strip())
        elif command == "steer":
            payload.update(message=argument, mode="steer")
        elif command not in {"pause", "resume", "cancel", "accept"}:
            raise ValueError("命令不存在。请使用 /al help。")
        return self._status(await self._action(payload, actor))

    @filter.llm_tool(name="agent_lab_enter_mode")
    async def agent_lab_enter_mode(self, event: AstrMessageEvent, goal: str, constraints: str = "", acceptance: str = "") -> str:
        """为管理员立项并生成待审批计划，不会直接执行或批准计划。

        Args:
            goal(string): 管理员明确提出的任务目标。
            constraints(string): 必须保留的限制和要求。
            acceptance(string): 完成验收条件。
        """
        try:
            actor = self._chat_actor(event)
            task = await self._create({"goal": goal, "constraints": constraints, "acceptance": acceptance}, actor)
            return self._status(task)
        except Exception as exc:
            return "无法立项：" + str(exc)

    @filter.llm_tool(name="agent_lab_read_state")
    async def agent_lab_read_state(self, event: AstrMessageEvent, task_id: str = "") -> str:
        """读取任务计划、当前位置和进度，不触发执行。

        Args:
            task_id(string): 任务ID；当前来源只有一个活动任务时可留空。
        """
        try:
            return self._status(self._select_chat_task(event, task_id))
        except Exception as exc:
            return str(exc)

    @filter.llm_tool(name="agent_lab_steer")
    async def agent_lab_steer(self, event: AstrMessageEvent, task_id: str, message: str) -> str:
        """将管理员的补充要求投递到任务，下次决策前读取；不扩大执行授权。

        Args:
            task_id(string): 要引导的任务ID。
            message(string): 管理员的新要求或纠正。
        """
        try:
            self._select_chat_task(event, task_id)
            await self.harness.steer(task_id, message, "steer")
            return "补充要求已保存，将在下一个执行边界读取；任务未重新启动。"
        except Exception as exc:
            return str(exc)

    @filter.on_llm_request()
    async def inject_agent_lab_policy(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            self._chat_actor(event)
        except PermissionError:
            if req.func_tool:
                for tool in list(req.func_tool.tools):
                    if tool.name.startswith("agent_lab_"):
                        req.func_tool.remove_tool(tool.name)
            return
        req.system_prompt += (
            "\n[Agent Lab 管理员任务入口]\n"
            "管理员要求开发、排障等长任务时，可用 agent_lab_enter_mode 立项，等待管理员在工作台或命令中批准计划。"
            "任务执行由后台负责，日常聊天只转交补充要求、按需查询进度，不复制任务全文。"
            "查询使用 agent_lab_read_state，明确任务的新要求用 agent_lab_steer；不要代替管理员审批。\n"
        )

    @filter.llm_tool(name="agent_lab_read_project_memory")
    async def agent_lab_read_project_memory(self, event: AstrMessageEvent, project_key: str, query: str = "") -> str:
        """按需读取管理员已明确共享的项目经验，不读取其他任务私有日志。

        Args:
            project_key(string): 项目标识，必须明确指定。
            query(string): 可选检索关键词。
        """
        try:
            self._chat_actor(event)
            if not project_key.strip():
                raise ValueError("请明确项目标识")
            rows = self.harness_store.list_project_memories(project_key.strip())
            if query.strip():
                terms = query.lower().split()
                rows = [row for row in rows if all(term in str(row.get("text", "")).lower() for term in terms)]
            return json.dumps(rows[-10:], ensure_ascii=False) if rows else "没有已确认共享的匹配项目经验。"
        except Exception as exc:
            return str(exc)
