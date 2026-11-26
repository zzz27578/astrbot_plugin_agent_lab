"""AstrBot Plugin: Agent Lab v1.0.0 — Hidden Isolated Long-Task Toolbox.

Design principles:
- Daily chat zero-pollution: NO global skill injection; idle state exposes ONLY 1 tool
  (`agent_lab_start_task`) + 1 short hint line (~50 chars). When an active task exists,
  dynamically exposes `agent_lab_control_task` and hides it immediately on completion.
- Isolated task execution: Inside a task's independent conversation, opens the 5 compact
  control tools (`task_plan/progress/ask/approve/finish`) + profile-authorized host tools.
- Classic WebUI: Serves both AstrBot Native Dashboard Plugin Page (`pages/agent-lab/`)
  and optional Standalone Quart server.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register

try:
    from .agent_lab.engine import TaskEngine
    from .agent_lab.guards import parse_admin_shortcut
    from .agent_lab.permissions import CONTROL_TOOL_NAMES, DAILY_TOOL_NAMES
    from .agent_lab.store import AgentLabStore
    from .agent_lab.webui_api import StandaloneWebUIServer, WebUIController
except ImportError:
    from agent_lab.engine import TaskEngine
    from agent_lab.guards import parse_admin_shortcut
    from agent_lab.permissions import CONTROL_TOOL_NAMES, DAILY_TOOL_NAMES
    from agent_lab.store import AgentLabStore
    from agent_lab.webui_api import StandaloneWebUIServer, WebUIController

logger = logging.getLogger("astrbot_plugin_agent_lab")
PLUGIN_NAME = "astrbot_plugin_agent_lab"


def _cfg(config: Any, key: str, default: Any = None) -> Any:
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _bool_cfg(config: Any, key: str, default: bool = False) -> bool:
    val = _cfg(config, key, default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"1", "true", "yes", "on"}
    return bool(default if val is None else val)


def _data_dir() -> Path:
    try:
        from astrbot.api.star import StarTools

        return Path(StarTools.get_data_dir(PLUGIN_NAME))
    except Exception:
        return Path(__file__).resolve().parent / "data"


@register(
    PLUGIN_NAME,
    "zzz27578",
    "隐藏式隔离长任务工具箱：日常零污染、后台自主规划审批执行、方案与加密凭证库及双风格 WebUI。",
    "1.0.0",
    "https://github.com/zzz27578/astrbot_plugin_agent_lab",
)
class AgentLabPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.store = AgentLabStore(_data_dir())
        self.engine = TaskEngine(self.store, context=self.context, config=self.config)
        self.webui_controller = WebUIController(self.store, self.engine, context=self.context, config=self.config)
        self.webui_server: StandaloneWebUIServer | None = None
        self._register_web_apis()

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def initialize(self):
        recovered = self.engine.recover_on_startup()
        paused = int(recovered.get("paused", 0)) if isinstance(recovered, dict) else int(recovered or 0)
        if paused:
            logger.info("[AgentLab] recovered %d interrupted task(s) into safe paused state", paused)
        if _bool_cfg(self.config, "cleanup_legacy_global_skill", True):
            self._deactivate_legacy_global_skill()
        await self._start_standalone_webui()
        logger.info("[AgentLab] v1.0.0 initialized (hidden-toolbox mode)")

    async def terminate(self):
        stop_fn = getattr(self.engine, "stop_all", None) or getattr(self.engine, "close", None)
        if callable(stop_fn):
            await stop_fn()
        if self.webui_server:
            await self.webui_server.stop()
            self.webui_server = None
        logger.info("[AgentLab] v1.0.0 terminated")

    def _deactivate_legacy_global_skill(self) -> None:
        """Stop v0.4.x auto-installed global `agent-mode` skill from polluting daily chat."""
        try:
            from astrbot.core.skills.skill_manager import SkillManager
            from astrbot.core.utils.astrbot_path import get_astrbot_skills_path

            legacy_md = Path(get_astrbot_skills_path()) / "agent-mode" / "SKILL.md"
            if legacy_md.exists():
                head = legacy_md.read_text(encoding="utf-8", errors="ignore")[:400]
                if "name: agent-mode" in head and "Agent Lab" in head:
                    SkillManager().set_skill_active("agent-mode", False)
                    logger.info("[AgentLab] deactivated legacy global agent-mode skill")
        except Exception as exc:
            logger.debug("[AgentLab] legacy skill cleanup skipped: %s", exc)

    def _register_web_apis(self) -> None:
        reg = getattr(self.context, "register_web_api", None)
        if not callable(reg):
            return
        self.webui_controller.register_astrbot_routes(self.context, PLUGIN_NAME)

    async def _start_standalone_webui(self) -> None:
        if not _bool_cfg(self.config, "standalone_webui_enabled", True):
            return
        host = str(_cfg(self.config, "standalone_webui_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(_cfg(self.config, "standalone_webui_port", 8788) or 8788)
        token = str(_cfg(self.config, "standalone_webui_token", "") or "").strip()
        if not token:
            logger.info("[AgentLab] standalone WebUI not started (standalone_webui_token is empty; AstrBot Dashboard page remains active)")
            return
        static_dir = Path(__file__).resolve().parent / "pages" / "agent-lab"
        self.webui_server = StandaloneWebUIServer(
            controller=self.webui_controller,
            static_dir=static_dir,
            host=host,
            port=port,
            token=token,
        )
        await self.webui_server.start()

    # ── Access Control ───────────────────────────────────────────────────────

    def _has_access(self, event: AstrMessageEvent) -> bool:
        if _bool_cfg(self.config, "private_only", True):
            is_private = getattr(event, "is_private_chat", None)
            if callable(is_private) and not is_private():
                return False
        if _bool_cfg(self.config, "admin_only", True):
            is_admin = getattr(event, "is_admin", None)
            if callable(is_admin) and not is_admin():
                return False
        return True

    def _require_access(self, event: AstrMessageEvent) -> None:
        if not self._has_access(event):
            raise PermissionError("仅管理员私聊可使用 Agent Lab 任务工具箱。")

    # ── Daily Chat Hook (Hidden Toolbox Gate) ────────────────────────────────

    @filter.on_llm_request()
    async def daily_toolbox_gate(self, event: AstrMessageEvent, req: ProviderRequest):
        # Inside isolated task execution: never touch prompt or toolset.
        if event.get_extra("agent_lab_runtime"):
            return

        has_access = self._has_access(event)
        active_task = self.store.load_active_task(event.unified_msg_origin) if has_access else None

        # Always strip the 5 internal control tools from daily chat;
        # hide agent_lab_control_task unless an active task exists!
        if req.func_tool:
            allowed_daily: set[str] = set()
            if has_access:
                allowed_daily.add("agent_lab_start_task")
                if active_task is not None:
                    allowed_daily.add("agent_lab_control_task")
            all_managed = set(CONTROL_TOOL_NAMES) | set(DAILY_TOOL_NAMES)
            for tool in list(getattr(req.func_tool, "tools", [])):
                if tool.name in all_managed and tool.name not in allowed_daily:
                    req.func_tool.remove_tool(tool.name)

        if not has_access or not _bool_cfg(self.config, "inject_daily_hint", True):
            return

        if active_task is None:
            req.system_prompt += (
                "\n[长任务工具箱] 多步复杂长任务调用 agent_lab_start_task 转隔离后台执行；日常对话直接回复。"
            )
        else:
            req.system_prompt += (
                f"\n[后台任务] {active_task.task_id}({active_task.status}/{active_task.phase})；"
                "查进度、补充要求、批准/拒绝、暂停/停止或按现状交付用 agent_lab_control_task。"
            )

        daily_summary = self.store.daily_summary_for_umo(event.unified_msg_origin)
        if daily_summary:
            req.system_prompt += "\n[项目共享摘要（仅供参考）]\n" + daily_summary

    # ── Priority Message Shortcut Interceptor ────────────────────────────────

    @filter.event_message_type(filter.EventMessageType.ALL, priority=10)
    async def admin_shortcut_monitor(self, event: AstrMessageEvent):
        if not self._has_access(event):
            return
        text = str(getattr(event, "message_str", "") or "").strip()
        if not text:
            return
        parsed = parse_admin_shortcut(text)
        if not parsed:
            return
        task = self.store.load_active_task(event.unified_msg_origin)
        if not task:
            return
        action, arg = parsed
        reply = await self._dispatch_admin_action(event, task.task_id, action, arg)
        if reply:
            yield event.plain_result(reply)
            event.stop_event()

    # ── Slash Commands (/al, /agentlab) ──────────────────────────────────────

    @filter.command("agentlab")
    async def cmd_agentlab(self, event: AstrMessageEvent):
        if not self._has_access(event):
            yield event.plain_result("仅管理员私聊可使用 /agentlab。")
            return
        raw = str(getattr(event, "message_str", "") or "").strip()
        _, _, tail = raw.partition(" ")
        yield event.plain_result(await self._handle_command(event, tail.strip()))

    @filter.command("al")
    async def cmd_al(self, event: AstrMessageEvent):
        if not self._has_access(event):
            yield event.plain_result("仅管理员私聊可使用 /al。")
            return
        raw = str(getattr(event, "message_str", "") or "").strip()
        _, _, tail = raw.partition(" ")
        yield event.plain_result(await self._handle_command(event, tail.strip()))

    async def _handle_command(self, event: AstrMessageEvent, tail: str) -> str:
        if not tail or tail in {"help", "帮助"}:
            return (
                "Agent Lab v1.0.0（隐藏式隔离长任务工具箱）\n"
                "/al start <目标> — 新建并启动隔离后台任务（先只读探索再出计划）\n"
                "/al status — 查看当前活跃任务状态\n"
                "/al approve / reject [理由] — 批准或拒绝待审批计划/高危操作\n"
                "/al answer <回答> — 回复任务提问\n"
                "/al steer <补充要求> — 向运行中任务发送补充引导\n"
                "/al pause / resume — 暂停或恢复任务\n"
                "/al deliver [备注] — 按现状直接交付并归档\n"
                "/al stop [理由] — 立即强制停止任务\n"
                "/al projects — 列出项目\n"
                "/al profiles — 列出可用方案"
            )
        cmd, _, rest = tail.partition(" ")
        cmd = cmd.lower().strip()
        rest = rest.strip()
        umo = event.unified_msg_origin

        if cmd == "start":
            if not rest:
                return "请提供任务目标，例如：/al start 审计并修复登录模块的超时问题"
            task = await self.engine.start_task(umo, rest, event=event)
            return f"已创建隔离任务 {task.task_id}（方案：{task.profile_id}），正在后台只读探索并拟定执行计划。"
        if cmd == "projects":
            projs = self.store.list_projects(umo=umo)
            if not projs:
                return "当前还没有项目。"
            lines = [f"- {p.project_id} | {p.title}（方案：{p.profile_id}）" for p in projs[:20]]
            return "项目列表：\n" + "\n".join(lines)
        if cmd == "profiles":
            profs = self.store.list_profiles()
            lines = [
                f"- {p.profile_id}{' [默认]' if p.is_default else ''} | {p.name}（{p.permission_mode}）: {p.description}"
                for p in profs
            ]
            return "可用方案：\n" + "\n".join(lines)

        task = self.store.load_active_task(umo)
        if not task:
            return "当前没有活跃任务。可用 /al start <目标> 启动新任务。"

        if cmd in {"approve", "reject", "pause", "resume", "stop", "deliver", "status"}:
            return await self._dispatch_admin_action(event, task.task_id, cmd, rest)
        if cmd == "steer":
            if not rest:
                return "请提供补充引导内容。"
            res = await self.engine.steer(task.task_id, rest, event=event)
            return res.get("message", "已发送引导。")
        if cmd == "answer":
            if not rest:
                return "请提供回答内容。"
            res = await self.engine.answer_question(task.task_id, rest, event=event)
            return res.get("message", "已提交回答。")
        return f"未知子命令：{cmd}，发送 /al help 查看说明。"

    async def _dispatch_admin_action(self, event: AstrMessageEvent, task_id: str, action: str, arg: str = "") -> str:
        if action == "status":
            d = self.engine.task_detail(task_id)
            m = d["meta"]
            done = sum(1 for s in m["steps"] if s["status"] == "completed")
            return (
                f"任务 {m['task_id']} | 状态：{m['status']}（阶段：{m['phase']}）\n"
                f"目标：{m['goal']}\n"
                f"进度：{done}/{len(m['steps'])} 步 | 等待原因：{m['wait_reason'] or '无'}\n"
                f"用量：{m['usage']['total_tokens']} tokens / {m['usage']['tool_calls']} 次工具调用"
            )
        if action == "approve":
            res = await self.engine.resolve_approval(task_id, "approved", note=arg, event=event)
            return res.get("message", "已批准并恢复执行。")
        if action == "reject":
            res = await self.engine.resolve_approval(task_id, "rejected", note=arg, event=event)
            return res.get("message", "已拒绝该审批。")
        if action == "pause":
            res = await self.engine.pause(task_id, human=True, event=event)
            return res.get("message", "任务已暂停。")
        if action == "resume":
            res = await self.engine.resume(task_id, event=event)
            return res.get("message", "任务已恢复。")
        if action == "stop":
            res = await self.engine.stop(task_id, reason=arg or "管理员停止任务", actor="admin", event=event)
            return res.get("message", "任务已立即停止。")
        if action == "deliver":
            res = await self.engine.deliver_as_is(task_id, note=arg, actor="admin", event=event)
            return res.get("message", "任务已按现状交付并归档。")
        return ""

    # ── Daily Tools (ONLY 2 total; idle exposes 1, active exposes 2) ─────────

    @filter.llm_tool(name="agent_lab_start_task")
    async def agent_lab_start_task(
        self,
        event: AstrMessageEvent,
        goal: str,
        project_id: str = "",
        profile_id: str = "",
        constraints: str = "",
    ) -> str:
        """将复杂多步长任务转入独立隔离会话在后台规划与执行，不污染当前日常对话。

        Args:
            goal(string): 任务最终目标与交付要求。
            project_id(string): 可选项目 ID，留空归入当前默认项目。
            profile_id(string): 可选方案 ID（如 default / readonly_research / full_autonomous）。
            constraints(string): 可选边界约束，多条用换行分隔。
        """
        self._require_access(event)
        c_list = [line.strip() for line in str(constraints or "").splitlines() if line.strip()]
        task = await self.engine.start_task(
            event.unified_msg_origin,
            goal,
            project_id=project_id,
            profile_id=profile_id,
            constraints=c_list,
            event=event,
        )
        return json.dumps(
            {
                "ok": True,
                "task_id": task.task_id,
                "project_id": task.project_id,
                "profile_id": task.profile_id,
                "status": task.status,
                "phase": task.phase,
                "note": "任务已在隔离会话启动：后台将先只读探索并提交计划供管理员审批。",
            },
            ensure_ascii=False,
        )

    @filter.llm_tool(name="agent_lab_control_task")
    async def agent_lab_control_task(
        self,
        event: AstrMessageEvent,
        action: str,
        payload: str = "",
    ) -> str:
        """查看或控制当前运行中的后台隔离任务（仅在存在活跃任务时可用）。

        Args:
            action(string): 操作类型：status | steer | approve | reject | answer | pause | resume | stop | deliver。
            payload(string): 附加内容（如 steer 的补充要求、answer 的回答、reject/stop 的理由）。
        """
        self._require_access(event)
        task = self.store.load_active_task(event.unified_msg_origin)
        if not task:
            return json.dumps({"ok": False, "error": "当前没有活跃任务。"}, ensure_ascii=False)
        act = str(action or "").strip().lower()
        if act == "status":
            d = self.engine.task_detail(task.task_id)
            m = d["meta"]
            return json.dumps(
                {
                    "ok": True,
                    "task_id": m["task_id"],
                    "status": m["status"],
                    "phase": m["phase"],
                    "wait_reason": m["wait_reason"],
                    "goal": m["goal"],
                    "current_summary": m["current_summary"],
                    "steps": [{"id": s["id"], "title": s["title"], "status": s["status"]} for s in m["steps"]],
                    "pending_approvals": len([a for a in m["approvals"] if a["status"] == "pending"]),
                    "pending_questions": len([q for q in m["questions"] if q["status"] == "pending"]),
                    "usage": m["usage"],
                },
                ensure_ascii=False,
            )
        if act == "steer":
            res = await self.engine.steer(task.task_id, payload, event=event)
            return json.dumps(res, ensure_ascii=False)
        if act == "answer":
            res = await self.engine.answer_question(task.task_id, payload, event=event)
            return json.dumps(res, ensure_ascii=False)
        if act in {"approve", "reject", "pause", "resume", "stop", "deliver"}:
            msg = await self._dispatch_admin_action(event, task.task_id, act, payload)
            return json.dumps({"ok": True, "action": act, "message": msg}, ensure_ascii=False)
        return json.dumps({"ok": False, "error": f"不支持的操作: {act}"}, ensure_ascii=False)

    # ── Internal Task-Only Control Tools (ALWAYS hidden from daily chat!) ────

    @filter.llm_tool(name="task_plan")
    async def task_plan(
        self,
        event: AstrMessageEvent,
        steps_json: str,
        summary: str = "",
        completed_step: str = "",
        message: str = "",
    ) -> str:
        """仅隔离任务内部使用：提交初始计划或调整步骤。"""
        tid = str(event.get_extra("agent_lab_runtime") or "")
        if not tid:
            return json.dumps({"ok": False, "error": "仅可在隔离任务内调用。"}, ensure_ascii=False)
        raw = json.loads(steps_json) if isinstance(steps_json, str) else steps_json
        if isinstance(raw, dict):
            steps = raw.get("steps", [])
            res = await self.engine.submit_plan(
                tid,
                steps,
                goal=str(raw.get("goal") or ""),
                completion_conditions=raw.get("completion_conditions"),
                scope_roots=raw.get("scope_roots"),
                remove_constraints=raw.get("remove_constraints"),
                constraints=raw.get("constraints"),
                summary=summary,
                completed_step=completed_step,
                message=message,
                event=event,
            )
        else:
            res = await self.engine.submit_plan(
                tid,
                raw if isinstance(raw, list) else [],
                summary=summary,
                completed_step=completed_step,
                message=message,
                event=event,
            )
        return json.dumps(res, ensure_ascii=False)

    @filter.llm_tool(name="task_progress")
    async def task_progress(self, event: AstrMessageEvent, message: str) -> str:
        """仅隔离任务内部使用：发送简短阶段进展。"""
        tid = str(event.get_extra("agent_lab_runtime") or "")
        if not tid:
            return json.dumps({"ok": False, "error": "仅可在隔离任务内调用。"}, ensure_ascii=False)
        res = await self.engine.record_progress(tid, message, event=event)
        return json.dumps(res, ensure_ascii=False)

    @filter.llm_tool(name="task_ask")
    async def task_ask(
        self, event: AstrMessageEvent, question: str, options_json: str, recommendation: str = ""
    ) -> str:
        """仅隔离任务内部使用：关键决策缺失时向管理员提问。"""
        tid = str(event.get_extra("agent_lab_runtime") or "")
        if not tid:
            return json.dumps({"ok": False, "error": "仅可在隔离任务内调用。"}, ensure_ascii=False)
        opts = json.loads(options_json) if isinstance(options_json, str) else options_json
        res = await self.engine.ask_question(
            tid,
            question,
            options=opts if isinstance(opts, list) else [],
            recommendation=recommendation,
            event=event,
        )
        return json.dumps(res, ensure_ascii=False)

    @filter.llm_tool(name="task_approve")
    async def task_approve(
        self,
        event: AstrMessageEvent,
        operation: str,
        reason: str,
        impact: str,
        operations_json: str,
        rollback: str = "",
        message: str = "",
    ) -> str:
        """仅隔离任务内部使用：越界或高危操作前请示审批。"""
        tid = str(event.get_extra("agent_lab_runtime") or "")
        if not tid:
            return json.dumps({"ok": False, "error": "仅可在隔离任务内调用。"}, ensure_ascii=False)
        ops = json.loads(operations_json) if isinstance(operations_json, str) else operations_json
        res = await self.engine.request_approval(
            tid,
            operation=operation,
            reason=reason,
            impact=impact,
            calls=ops if isinstance(ops, list) else [],
            rollback=rollback,
            message=message,
            event=event,
        )
        return json.dumps(res, ensure_ascii=False)

    @filter.llm_tool(name="task_finish")
    async def task_finish(self, event: AstrMessageEvent, final_summary: str, message: str = "") -> str:
        """仅隔离任务内部使用：完成后提交交付与核验归档。"""
        tid = str(event.get_extra("agent_lab_runtime") or "")
        if not tid:
            return json.dumps({"ok": False, "error": "仅可在隔离任务内调用。"}, ensure_ascii=False)
        res = await self.engine.finish_task(tid, final_summary, message=message, event=event)
        return json.dumps(res, ensure_ascii=False)
