from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools

try:
    from quart import jsonify, request
except Exception:  # pragma: no cover - AstrBot dashboard provides quart.
    jsonify = None
    request = None

from .agent_lab import AgentLabStorage, AgentSpec, ApprovalRequest, TaskState
from .agent_lab.models import now_iso
from .agent_lab.modules import ModuleRegistry
from .agent_lab.prompts import (
    build_agent_mode_policy,
    build_task_system_prompt,
    build_tick_prompt,
)
from .agent_lab.session_guard import SessionPluginGuard
from .agent_lab.summarizer import AgentSummarizer


PLUGIN_NAME = "astrbot_plugin_agent_lab"
SKILL_NAME = "agent-mode"


def _cfg(config: Any, key: str, default: Any = None) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        return config.get(key, default)
    try:
        return config.get(key, default)
    except Exception:
        return getattr(config, key, default)


def _bool_cfg(config: Any, key: str, default: bool = False) -> bool:
    return bool(_cfg(config, key, default))


def _message_tail(event: AstrMessageEvent, command_name: str) -> str:
    text = (event.message_str or "").strip()
    for prefix in (f"/{command_name}", command_name):
        if text.lower().startswith(prefix.lower()):
            return text[len(prefix) :].strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


class AgentLabPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.config = config or {}
        self.storage = AgentLabStorage(StarTools.get_data_dir(PLUGIN_NAME))
        self.modules = ModuleRegistry()
        self.guard = SessionPluginGuard()
        self.summarizer = AgentSummarizer(
            context,
            {
                "entry_summary_turns": int(_cfg(self.config, "entry_summary_turns", 24)),
                "fallback_summary_provider_id": str(
                    _cfg(self.config, "fallback_summary_provider_id", "")
                ),
            },
        )
        self.storage.ensure_defaults()
        self._register_web_apis()

    async def initialize(self):
        self._sync_agent_mode_skill()
        await self._rehydrate_heartbeats()
        logger.info("[AgentLab] initialized")

    async def terminate(self):
        logger.info("[AgentLab] terminated")

    @filter.command("agentlab")
    async def agentlab_command(self, event: AstrMessageEvent):
        """Agent Lab 控制台命令：status/start/tick/finish/cancel/heartbeat/approve。"""
        if not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            yield event.plain_result("Agent Lab 第一版仅允许私聊使用，避免群聊误触发和权限风险。")
            return
        result = await self._handle_command(event, _message_tail(event, "agentlab"))
        yield event.plain_result(result)

    @filter.command("al")
    async def al_command(self, event: AstrMessageEvent):
        """Agent Lab 短命令。"""
        if not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            yield event.plain_result("Agent Lab 第一版仅允许私聊使用。")
            return
        result = await self._handle_command(event, _message_tail(event, "al"))
        yield event.plain_result(result)

    @filter.llm_tool(name="agent_lab_enter_mode")
    async def agent_lab_enter_mode(
        self,
        event: AstrMessageEvent,
        goal: str,
        completion_conditions: str = "",
        risk_level: str = "work",
        user_confirmed: bool = False,
        need_heartbeat: bool = False,
    ) -> str:
        """进入 AstrBot Agent Lab 的 Agent Mode，创建任务状态。

        Args:
            goal(string): 用户原始根目标，必须稳定清楚。
            completion_conditions(string): 完成条件，多个条件可用换行分隔。
            risk_level(string): low/work/high。涉及文件写入、命令、部署、删除、密钥时至少为 work/high。
            user_confirmed(boolean): 用户是否明确同意进入 Agent Mode 或授权当前风险等级。
            need_heartbeat(boolean): 是否需要为长任务开启心跳。
        """
        spec = self.storage.get_agent()
        if spec.trigger_mode in ("manual", "confirm") and not user_confirmed:
            return (
                "需要先向用户确认：是否进入 Agent Mode？请说明将创建任务状态、"
                "按任务规则管理上下文，并在危险操作前请求审批。"
            )
        return await self._start_task(
            event,
            goal=goal,
            completion_conditions=completion_conditions,
            brief="",
            request_heartbeat=need_heartbeat,
            source="tool",
            risk_level=risk_level,
        )

    @filter.llm_tool(name="agent_lab_tick")
    async def agent_lab_tick(self, event: AstrMessageEvent, reason: str = "tool") -> str:
        """推进当前 Agent Mode 任务一轮。执行前必须确认没有待审批危险操作。"""
        return await self._tick(event, reason=reason)

    @filter.llm_tool(name="agent_lab_request_approval")
    async def agent_lab_request_approval(
        self,
        event: AstrMessageEvent,
        operation: str,
        reason: str,
        impact: str,
        rollback: str = "",
    ) -> str:
        """危险操作前请求用户审批，不要直接执行危险操作。

        Args:
            operation(string): 准备执行的危险操作。
            reason(string): 为什么需要做。
            impact(string): 影响范围。
            rollback(string): 可回滚方案。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task，无法记录审批。"
        approval = ApprovalRequest(
            operation=operation,
            reason=reason,
            impact=impact,
            rollback=rollback,
        )
        task.approvals.append(approval.to_dict())
        task.add_log("approval_requested", f"{approval.approval_id}: {operation}")
        self.storage.save_task(task)
        return (
            f"已创建审批请求 {approval.approval_id}。请向用户说明：\n"
            f"- 操作：{operation}\n- 原因：{reason}\n- 影响：{impact}\n"
            f"- 回滚：{rollback or '未提供'}\n"
            f"用户可回复 /agentlab approve {approval.approval_id}。"
        )

    @filter.llm_tool(name="agent_lab_set_heartbeat")
    async def agent_lab_set_heartbeat(
        self,
        event: AstrMessageEvent,
        enabled: bool,
        reason: str = "",
    ) -> str:
        """为当前任务开启或关闭心跳。长任务可开启；普通短任务不要滥用。"""
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        if enabled:
            return await self._enable_heartbeat(event, task, reason=reason or "tool")
        await self._disable_heartbeat(task)
        self.storage.save_task(task)
        return "已关闭当前任务心跳。"

    @filter.llm_tool(name="agent_lab_finish")
    async def agent_lab_finish(
        self,
        event: AstrMessageEvent,
        final_summary: str,
        memory_candidates: str = "",
    ) -> str:
        """任务达到完成条件后归档并退出 Agent Mode。"""
        return await self._finish_task(
            event,
            status="completed",
            final_summary=final_summary,
            memory_candidates=memory_candidates,
        )

    @filter.on_llm_request()
    async def inject_agent_lab_policy(self, event: AstrMessageEvent, req: ProviderRequest):
        if not _bool_cfg(self.config, "inject_agent_mode_policy", True):
            return
        if not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            return
        spec = self.storage.get_agent()
        task = self.storage.load_active_task(event.unified_msg_origin)
        if task:
            modules_prompt = self.modules.build_prompt(spec.module_ids)
            req.system_prompt += "\n\n" + build_task_system_prompt(
                spec, task, modules_prompt
            )
        else:
            req.system_prompt += "\n\n" + build_agent_mode_policy(spec)

    async def _handle_command(self, event: AstrMessageEvent, tail: str) -> str:
        if not tail or tail in ("help", "帮助"):
            return self._help_text()
        cmd, _, rest = tail.partition(" ")
        cmd = cmd.lower().strip()
        rest = rest.strip()

        if cmd in ("status", "状态"):
            return self._status_text(event.unified_msg_origin)
        if cmd in ("agents", "agent"):
            return self._agents_text()
        if cmd in ("plugins", "插件"):
            return self._plugins_text()
        if cmd in ("tools", "工具"):
            return self._tools_text()
        if cmd in ("skills", "技能"):
            return self._skills_text()
        if cmd in ("modules", "模块"):
            return self._modules_text()
        if cmd in ("start", "enter", "开启", "开始"):
            goal = rest or "未命名任务"
            return await self._start_task(
                event,
                goal=goal,
                completion_conditions="用户验收通过",
                brief="",
                request_heartbeat=False,
                source="command",
                risk_level="work",
            )
        if cmd in ("tick", "继续"):
            return await self._tick(event, reason="command")
        if cmd in ("finish", "done", "完成"):
            return await self._finish_task(event, "completed", rest, "")
        if cmd in ("cancel", "取消"):
            return await self._finish_task(event, "cancelled", rest or "用户取消任务。", "")
        if cmd == "heartbeat":
            sub = rest.lower()
            task = self.storage.load_active_task(event.unified_msg_origin)
            if not task:
                return "当前没有 active task。"
            if sub.startswith("on"):
                return await self._enable_heartbeat(event, task, reason="command")
            await self._disable_heartbeat(task)
            self.storage.save_task(task)
            return "已关闭当前任务心跳。"
        if cmd == "approve":
            return self._resolve_approval(event.unified_msg_origin, rest, True, event.get_sender_id())
        if cmd == "reject":
            return self._resolve_approval(event.unified_msg_origin, rest, False, event.get_sender_id())
        return f"未知命令：{cmd}\n\n{self._help_text()}"

    async def _start_task(
        self,
        event: AstrMessageEvent,
        *,
        goal: str,
        completion_conditions: str,
        brief: str,
        request_heartbeat: bool,
        source: str,
        risk_level: str,
    ) -> str:
        umo = event.unified_msg_origin
        if self.storage.load_active_task(umo):
            return "当前会话已有 active task。请先 /agentlab finish 或 /agentlab cancel。"

        spec = self.storage.get_agent()
        session_plugin_snapshot = await self.guard.apply_overrides(
            umo, spec.plugin_overrides
        )
        entry_summary = await self.summarizer.summarize_entry(event, goal, brief)
        task = TaskState(
            agent_id=spec.agent_id,
            agent_name=spec.name,
            umo=umo,
            root_goal=goal.strip(),
            completion_conditions=[
                line.strip()
                for line in completion_conditions.replace("；", "\n").splitlines()
                if line.strip()
            ]
            or ["用户验收通过"],
            task_brief=entry_summary,
            entry_summary=entry_summary,
            current_summary=f"任务由 {source} 创建，风险级别：{risk_level}。",
            next_step="根据入口摘要制定第一轮执行计划，并推进一个有限工作单元。",
            profile_snapshot={
                "agent": spec.to_dict(),
                "session_plugin_snapshot": session_plugin_snapshot,
            },
            heartbeat=spec.heartbeat_policy,
        )
        task.add_log("created", f"goal={goal}; source={source}; risk={risk_level}")
        self.storage.save_task(task)
        heartbeat_text = ""
        if request_heartbeat and task.heartbeat.allowed:
            heartbeat_text = "\n" + await self._enable_heartbeat(
                event, task, reason="start_request"
            )
        return (
            f"已进入 Agent Mode。\n"
            f"- task_id: {task.task_id}\n"
            f"- agent: {spec.name}\n"
            f"- 状态文件: {self.storage.task_markdown_path(umo, task.task_id)}\n"
            f"- 下一步: /agentlab tick\n"
            f"{heartbeat_text}"
        )

    async def _tick(self, event: AstrMessageEvent, reason: str) -> str:
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。可以先 /agentlab start <目标>。"
        if task.status not in ("running", "paused"):
            return f"当前任务状态为 {task.status}，不执行 tick。"
        if task.pending_approvals():
            pending = "\n".join(
                f"- {item.approval_id}: {item.operation}" for item in task.pending_approvals()
            )
            return f"存在待审批操作，先处理审批再继续：\n{pending}"

        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
        modules_prompt = self.modules.build_prompt(spec.module_ids)
        system_prompt = build_task_system_prompt(spec, task, modules_prompt)
        prompt = build_tick_prompt(task, reason)
        try:
            provider_id = await self.context.get_current_chat_provider_id(event.unified_msg_origin)
            resp = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system_prompt,
                tools=self._build_toolset(spec),
                max_steps=int(_cfg(self.config, "max_steps_per_tick", 12)),
                tool_call_timeout=int(_cfg(self.config, "tool_call_timeout", 120)),
                llm_compress_keep_recent=int(_cfg(self.config, "llm_compress_keep_recent", 6)),
                truncate_turns=int(_cfg(self.config, "truncate_turns", 2)),
            )
            text = (getattr(resp, "completion_text", "") or "").strip()
            task.last_observation = text[-4000:] if text else "本轮没有返回文本。"
            task.last_confirmed_progress = text[:1200] if text else task.last_confirmed_progress
            task.current_summary = self._compact_text(text, 1200) if text else task.current_summary
            task.next_step = "根据上一轮观察继续推进；若涉及危险操作，先请求审批。"
            task.status = "running"
            task.add_log("tick", f"reason={reason}; response={self._compact_text(text, 1200)}")
            self.storage.save_task(task)
            return f"tick 完成。\n\n{self._compact_text(text, 1800)}"
        except Exception as exc:
            count = task.add_blocker(type(exc).__name__, str(exc))
            if count >= task.heartbeat.max_repeated_failures:
                task.status = "blocked"
                await self._disable_heartbeat(task)
            self.storage.save_task(task)
            return (
                f"tick 失败：{exc}\n"
                f"同类问题计数：{count}。"
                f"{' 已暂停任务并关闭心跳。' if task.status == 'blocked' else ''}"
            )

    async def _finish_task(
        self,
        event: AstrMessageEvent,
        status: str,
        final_summary: str,
        memory_candidates: str,
    ) -> str:
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        exit_summary = await self.summarizer.summarize_exit(event, task, final_summary)
        task.status = status
        task.exit_summary = exit_summary
        task.memory_candidates = [
            line.strip("- ").strip()
            for line in (memory_candidates or "").splitlines()
            if line.strip()
        ]
        task.finished_at = now_iso()
        task.add_log("finished", f"status={status}")
        await self._disable_heartbeat(task)
        snapshot = task.profile_snapshot.get("session_plugin_snapshot")
        await self.guard.restore(task.umo, snapshot)
        archive_path = self.storage.archive_task(task)
        return (
            f"Agent Mode 已结束并归档。\n"
            f"- status: {status}\n"
            f"- archive: {archive_path}\n\n"
            f"{self._compact_text(exit_summary, 1800)}"
        )

    async def _enable_heartbeat(self, event: AstrMessageEvent, task: TaskState, reason: str) -> str:
        if not task.heartbeat.allowed:
            return "当前 Agent 配置禁止使用心跳。"
        if not self.context.cron_manager:
            return "cron_manager 不可用，无法开启心跳。"
        if task.heartbeat.job_id:
            return f"心跳已经开启：{task.heartbeat.job_id}"
        job = await self.context.cron_manager.add_basic_job(
            name=f"agent_lab_{task.task_id}",
            cron_expression=task.heartbeat.cron_expression,
            handler=self._heartbeat_tick,
            payload={
                "umo": task.umo,
                "task_id": task.task_id,
                "state_path": str(self.storage.task_markdown_path(task.umo, task.task_id)),
                "root_goal": task.root_goal,
                "completion_conditions": task.completion_conditions,
            },
            persistent=False,
            description=f"Agent Lab heartbeat for {task.task_id}",
            enabled=True,
        )
        task.heartbeat.enabled = True
        task.heartbeat.job_id = job.job_id
        task.heartbeat.last_pulse_at = ""
        task.add_log("heartbeat_on", f"reason={reason}; job_id={job.job_id}")
        self.storage.save_task(task)
        return f"已开启心跳：{job.job_id}，周期 {task.heartbeat.cron_expression}。"

    async def _disable_heartbeat(self, task: TaskState) -> None:
        if task.heartbeat.job_id and self.context.cron_manager:
            try:
                await self.context.cron_manager.delete_job(task.heartbeat.job_id)
            except Exception:
                pass
        task.heartbeat.enabled = False
        task.heartbeat.job_id = ""
        task.add_log("heartbeat_off", "heartbeat disabled")

    async def _heartbeat_tick(self, **payload) -> None:
        umo = str(payload.get("umo") or "")
        task = self.storage.load_active_task(umo)
        if not task or task.task_id != payload.get("task_id"):
            return
        if task.status != "running":
            await self._disable_heartbeat(task)
            self.storage.save_task(task)
            return
        task.heartbeat.last_pulse_at = now_iso()
        self.storage.save_task(task)
        event = self._make_cron_event(umo, f"Agent Lab heartbeat: {task.task_id}")
        if event is None:
            task.add_blocker("heartbeat_event", "无法构造 CronMessageEvent。")
            self.storage.save_task(task)
            return
        result = await self._tick(event, reason="heartbeat")
        logger.info("[AgentLab] heartbeat result for %s: %s", task.task_id, result[:500])

    def _make_cron_event(self, umo: str, message: str):
        try:
            from astrbot.core.cron.events import CronMessageEvent
            from astrbot.core.platform.message_session import MessageSession

            session = MessageSession.from_str(umo)
            return CronMessageEvent(
                context=self.context,
                session=session,
                message=message,
                extras={"agent_lab_heartbeat": True},
                message_type=session.message_type,
            )
        except Exception as exc:
            logger.warning("[AgentLab] cannot create cron event: %s", exc)
            return None

    async def _rehydrate_heartbeats(self) -> None:
        # Basic jobs are not persisted safely with plugin handlers. Recreate them for active tasks.
        if not self.context.cron_manager:
            return
        existing = set()
        try:
            existing = {job.job_id for job in await self.context.cron_manager.list_jobs("basic")}
        except Exception:
            existing = set()
        for task in self.storage.list_tasks():
            if task.status == "running" and task.heartbeat.enabled:
                if task.heartbeat.job_id in existing:
                    continue
                task.heartbeat.job_id = ""
                self.storage.save_task(task)
                event = self._make_cron_event(task.umo, f"Agent Lab rehydrate: {task.task_id}")
                if event:
                    await self._enable_heartbeat(event, task, reason="rehydrate")

    def _resolve_approval(self, umo: str, approval_id: str, approved: bool, user_id: str) -> str:
        task = self.storage.load_active_task(umo)
        if not task:
            return "当前没有 active task。"
        if not approval_id:
            return "请提供 approval_id。"
        found = False
        for item in task.approvals:
            if item.get("approval_id") == approval_id:
                item["status"] = "approved" if approved else "rejected"
                item["resolved_at"] = now_iso()
                item["resolved_by"] = user_id
                found = True
                break
        if not found:
            return f"未找到审批请求：{approval_id}"
        task.add_log("approval_resolved", f"{approval_id}: {'approved' if approved else 'rejected'}")
        self.storage.save_task(task)
        return f"审批已{'通过' if approved else '拒绝'}：{approval_id}"

    def _build_toolset(self, spec: AgentSpec):
        tmgr = self.context.get_llm_tool_manager()
        if not spec.enabled_tools:
            return tmgr.get_full_tool_set()
        from astrbot.core.agent.tool import ToolSet

        toolset = ToolSet()
        for name in spec.enabled_tools:
            tool = tmgr.get_func(name)
            if tool:
                toolset.add_tool(tool)
        return toolset

    def _sync_agent_mode_skill(self) -> None:
        if not _bool_cfg(self.config, "install_agent_mode_skill", True):
            return
        try:
            from astrbot.core.skills.skill_manager import SkillManager
            from astrbot.core.utils.astrbot_path import get_astrbot_skills_path

            src = Path(__file__).parent / "skills" / SKILL_NAME
            dst = Path(get_astrbot_skills_path()) / SKILL_NAME
            if src.exists():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            SkillManager().set_skill_active(SKILL_NAME, True)
        except Exception as exc:
            logger.warning("[AgentLab] skill install failed: %s", exc)

    def _register_web_apis(self) -> None:
        if jsonify is None:
            return
        self.context.register_web_api(f"/{PLUGIN_NAME}/state", self.api_state, ["GET"], "Agent Lab state")
        self.context.register_web_api(f"/{PLUGIN_NAME}/agents", self.api_agents, ["GET", "POST"], "Agent specs")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/start", self.api_task_start, ["POST"], "Start task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/tick", self.api_task_tick, ["POST"], "Tick task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/finish", self.api_task_finish, ["POST"], "Finish task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/heartbeat", self.api_task_heartbeat, ["POST"], "Toggle heartbeat")

    async def api_state(self):
        return jsonify(
            {
                "agents": [item.to_dict() for item in self.storage.list_agents()],
                "tasks": [item.to_dict() for item in self.storage.list_tasks()],
                "plugins": self._plugin_rows(),
                "tools": self._tool_rows(),
                "skills": self._skill_rows(),
                "modules": self.modules.list_modules(),
            }
        )

    async def api_agents(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            spec = AgentSpec.from_dict(payload)
            self.storage.save_agent(spec)
            return jsonify({"ok": True, "agent": spec.to_dict()})
        return jsonify({"agents": [item.to_dict() for item in self.storage.list_agents()]})

    async def api_task_start(self):
        payload = await request.get_json(force=True, silent=True) or {}
        umo = str(payload.get("umo") or "")
        if not umo:
            return jsonify({"ok": False, "error": "umo is required"})
        event = self._make_cron_event(umo, "Agent Lab WebUI start")
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        text = await self._start_task(
            event,
            goal=str(payload.get("goal") or "WebUI task"),
            completion_conditions=str(payload.get("completion_conditions") or "用户验收通过"),
            brief=str(payload.get("brief") or ""),
            request_heartbeat=bool(payload.get("heartbeat", False)),
            source="webui",
            risk_level=str(payload.get("risk_level") or "work"),
        )
        return jsonify({"ok": True, "message": text})

    async def api_task_tick(self):
        payload = await request.get_json(force=True, silent=True) or {}
        event = self._make_cron_event(str(payload.get("umo") or ""), "Agent Lab WebUI tick")
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        return jsonify({"ok": True, "message": await self._tick(event, "webui")})

    async def api_task_finish(self):
        payload = await request.get_json(force=True, silent=True) or {}
        event = self._make_cron_event(str(payload.get("umo") or ""), "Agent Lab WebUI finish")
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        msg = await self._finish_task(
            event,
            str(payload.get("status") or "completed"),
            str(payload.get("summary") or "WebUI requested finish."),
            str(payload.get("memory_candidates") or ""),
        )
        return jsonify({"ok": True, "message": msg})

    async def api_task_heartbeat(self):
        payload = await request.get_json(force=True, silent=True) or {}
        umo = str(payload.get("umo") or "")
        task = self.storage.load_active_task(umo)
        if not task:
            return jsonify({"ok": False, "error": "no active task"})
        event = self._make_cron_event(umo, "Agent Lab WebUI heartbeat")
        if bool(payload.get("enabled", False)):
            msg = await self._enable_heartbeat(event, task, "webui")
        else:
            await self._disable_heartbeat(task)
            self.storage.save_task(task)
            msg = "heartbeat disabled"
        return jsonify({"ok": True, "message": msg})

    def _plugin_rows(self) -> list[dict[str, Any]]:
        rows = []
        for plugin in self.context.get_all_stars():
            rows.append(
                {
                    "name": plugin.name,
                    "display_name": plugin.display_name,
                    "activated": plugin.activated,
                    "reserved": plugin.reserved,
                    "desc": plugin.desc,
                }
            )
        return rows

    def _tool_rows(self) -> list[dict[str, Any]]:
        rows = []
        for tool in self.context.get_llm_tool_manager().func_list:
            rows.append(
                {
                    "name": tool.name,
                    "active": getattr(tool, "active", True),
                    "description": getattr(tool, "description", ""),
                    "handler_module_path": getattr(tool, "handler_module_path", ""),
                }
            )
        return rows

    def _skill_rows(self) -> list[dict[str, Any]]:
        try:
            from astrbot.core.skills.skill_manager import SkillManager

            return [item.__dict__ for item in SkillManager().list_skills(active_only=False)]
        except Exception:
            return []

    def _status_text(self, umo: str) -> str:
        task = self.storage.load_active_task(umo)
        if not task:
            return "Agent Lab：当前没有 active task。"
        return (
            f"Agent Lab active task:\n"
            f"- id: {task.task_id}\n"
            f"- status: {task.status}\n"
            f"- goal: {task.root_goal}\n"
            f"- next: {task.next_step or '-'}\n"
            f"- heartbeat: {'on' if task.heartbeat.enabled else 'off'}\n"
            f"- pending approvals: {len(task.pending_approvals())}\n"
            f"- state: {self.storage.task_markdown_path(umo, task.task_id)}"
        )

    def _agents_text(self) -> str:
        return "\n".join(
            f"- {item.agent_id}: {item.name} ({item.trigger_mode})"
            for item in self.storage.list_agents()
        )

    def _plugins_text(self) -> str:
        return "\n".join(
            f"- [{'on' if row['activated'] else 'off'}] {row['name']} {row['display_name'] or ''}"
            for row in self._plugin_rows()
        )[:3500]

    def _tools_text(self) -> str:
        return "\n".join(
            f"- [{'on' if row['active'] else 'off'}] {row['name']}"
            for row in self._tool_rows()
        )[:3500]

    def _skills_text(self) -> str:
        return "\n".join(
            f"- [{'on' if row.get('active') else 'off'}] {row.get('name')}"
            for row in self._skill_rows()
        )[:3500]

    def _modules_text(self) -> str:
        return "\n".join(
            f"- {row['module_id']}: {row['name']} ({row['source']})"
            for row in self.modules.list_modules()
        )

    def _help_text(self) -> str:
        return (
            "Agent Lab 命令：\n"
            "/agentlab status\n"
            "/agentlab start <目标>\n"
            "/agentlab tick\n"
            "/agentlab heartbeat on|off\n"
            "/agentlab approve <approval_id>\n"
            "/agentlab reject <approval_id>\n"
            "/agentlab finish <总结>\n"
            "/agentlab cancel <原因>\n"
            "/agentlab agents|plugins|tools|skills|modules"
        )

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 20] + "\n...[truncated]"
