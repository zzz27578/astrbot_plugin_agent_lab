from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register

try:
    from quart import jsonify, request
except Exception:  # pragma: no cover - AstrBot dashboard provides quart.
    jsonify = None
    request = None

from .agent_lab import AgentLabStorage, AgentSpec, ApprovalRequest, TaskState
from .agent_lab.hooks import AgentLabRunHooks
from .agent_lab.models import now_iso
from .agent_lab.modules import ModuleRegistry
from .agent_lab.prompts import (
    build_agent_mode_policy,
    build_task_system_prompt,
    build_tick_prompt,
)
from .agent_lab.session_guard import SessionPluginGuard
from .agent_lab.summarizer import AgentSummarizer
from .agent_lab.webui_server import StandaloneWebUIServer


PLUGIN_NAME = "astrbot_plugin_agent_lab"
PLUGIN_VERSION = "v0.1.0"
PLUGIN_AUTHOR = "zzz27578 & Codex"
PLUGIN_DESC = "在 AstrBot 内创建、运行和管理个人 Agent Mode。"
SKILL_NAME = "agent-mode"
NO_EXTERNAL_TOOLS_SENTINEL = "__agent_lab_no_external_tools__"
DEFAULT_BOT_LABEL = "当前 Bot"
AGENT_NAME_SUFFIX = " Agent Mode"
DEFAULT_AGENT_NAMES = {
    "",
    f"{DEFAULT_BOT_LABEL}{AGENT_NAME_SUFFIX}",
    "AstrBot Agent Mode",
    "Agent Mode",
}

BUILTIN_TOOL_CATALOG = [
    {
        "name": "astrbot_file_read_tool",
        "description": "Read files from the current AstrBot computer-use workspace.",
        "risk": "safe",
    },
    {
        "name": "astrbot_grep_tool",
        "description": "Search files with ripgrep in the current workspace.",
        "risk": "safe",
    },
    {
        "name": "astrbot_file_write_tool",
        "description": "Write UTF-8 text files in the workspace.",
        "risk": "work",
    },
    {
        "name": "astrbot_file_edit_tool",
        "description": "Edit files by replacing exact text.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_shell",
        "description": "Execute shell commands via AstrBot Computer Use.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_python",
        "description": "Execute Python in local runtime.",
        "risk": "work",
    },
    {
        "name": "astrbot_execute_ipython",
        "description": "Execute Python in sandbox/IPython runtime.",
        "risk": "work",
    },
    {
        "name": "future_task",
        "description": "AstrBot proactive future task tool.",
        "risk": "work",
    },
]


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


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class AgentLabPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.config = config or {}
        self.storage = AgentLabStorage(StarTools.get_data_dir(PLUGIN_NAME))
        self.modules = ModuleRegistry(self.storage.modules_dir)
        self.guard = SessionPluginGuard(protected_plugins={PLUGIN_NAME})
        self.webui_server: StandaloneWebUIServer | None = None
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
        self._sync_default_agent_identity()
        self._register_web_apis()

    async def initialize(self):
        self._sync_default_agent_identity()
        self._sync_agent_mode_skill()
        await self._rehydrate_heartbeats()
        await self._start_webui_server()
        logger.info("[AgentLab] initialized")

    async def terminate(self):
        await self._stop_webui_server()
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
        agent_id: str = "",
    ) -> str:
        """进入 AstrBot Agent Lab 的 Agent Mode，创建任务状态。

        Args:
            goal(string): 用户原始根目标，必须稳定清楚。
            completion_conditions(string): 完成条件，多个条件可用换行分隔。
            risk_level(string): low/work/high。涉及文件写入、命令、部署、删除、密钥时至少为 work/high。
            user_confirmed(boolean): 用户是否明确同意进入 Agent Mode 或授权当前风险等级。
            need_heartbeat(boolean): 是否需要为长任务开启心跳。
            agent_id(string): 可选 AgentSpec ID。为空时使用默认 Agent。
        """
        spec = self.storage.get_agent(agent_id or None)
        if not spec.enabled:
            return "当前 AgentSpec 未启用。请先在 Agent Lab WebUI 启用，或选择另一个 AgentSpec。"
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
            agent_id=agent_id,
        )

    @filter.llm_tool(name="agent_lab_read_state")
    async def agent_lab_read_state(self, event: AstrMessageEvent, format: str = "summary") -> str:
        """读取当前 Agent Mode 任务状态。心跳或长任务继续前必须先读状态。

        Args:
            format(string): summary 或 markdown。summary 返回短摘要，markdown 返回完整任务存档。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        if format == "markdown":
            return self.storage.render_markdown(task)
        return (
            f"task_id: {task.task_id}\n"
            f"status: {task.status}\n"
            f"root_goal: {task.root_goal}\n"
            f"completion_conditions: {task.completion_conditions}\n"
            f"entry_summary: {self._compact_text(task.entry_summary or task.task_brief, 1600)}\n"
            f"current_summary: {task.current_summary or '-'}\n"
            f"last_confirmed_progress: {task.last_confirmed_progress or '-'}\n"
            f"next_step: {task.next_step or '-'}\n"
            f"last_observation: {self._compact_text(task.last_observation, 1200) or '-'}\n"
            f"pending_approvals: {len(task.pending_approvals())}\n"
            f"state_path: {self.storage.task_markdown_path(task.umo, task.task_id)}"
        )

    @filter.llm_tool(name="agent_lab_update_state")
    async def agent_lab_update_state(
        self,
        event: AstrMessageEvent,
        current_summary: str = "",
        progress: str = "",
        next_step: str = "",
        last_observation: str = "",
        status: str = "running",
        blocker: str = "",
        need_heartbeat: bool = False,
    ) -> str:
        """写回当前任务状态。每轮执行结束前都应调用。

        Args:
            current_summary(string): 当前任务现状摘要。
            progress(string): 本轮确认进度，必须具体。
            next_step(string): 下一步行动。
            last_observation(string): 工具输出、测试结果或观察摘要。
            status(string): running、paused、blocked、completed 之一。
            blocker(string): 当前阻塞点；没有则留空。
            need_heartbeat(boolean): 是否建议开启心跳。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        if current_summary.strip():
            task.current_summary = current_summary.strip()
        if progress.strip():
            task.last_confirmed_progress = progress.strip()
            task.add_log("progress", progress.strip())
        if next_step.strip():
            task.next_step = next_step.strip()
        if last_observation.strip():
            task.last_observation = last_observation.strip()
        if blocker.strip():
            count = task.add_blocker(blocker.strip(), last_observation.strip())
            if count >= task.heartbeat.max_repeated_failures:
                task.status = "blocked"
                await self._disable_heartbeat(task)
        elif status in ("running", "paused", "blocked", "completed"):
            task.status = status
        if need_heartbeat and not task.heartbeat.enabled and task.heartbeat.allowed:
            # Record the recommendation; user/tool can call agent_lab_set_heartbeat.
            task.add_log("heartbeat_recommended", "Agent judged this task needs heartbeat.")
        self.storage.save_task(task)
        return (
            f"task_state 已更新：status={task.status}, next_step={task.next_step or '-'}, "
            f"heartbeat={'on' if task.heartbeat.enabled else 'off'}"
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
            spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or spec.to_dict())
            modules_prompt = self._build_task_extensions_prompt(spec)
            req.system_prompt += "\n\n" + build_task_system_prompt(
                spec, task, modules_prompt
            )
        else:
            if not spec.enabled:
                return
            req.system_prompt += "\n\n" + build_agent_mode_policy(spec)

    async def _handle_command(self, event: AstrMessageEvent, tail: str) -> str:
        if not tail or tail in ("help", "帮助"):
            return self._help_text()
        cmd, _, rest = tail.partition(" ")
        cmd = cmd.lower().strip()
        rest = rest.strip()

        if cmd in ("status", "状态"):
            return self._status_text(event.unified_msg_origin)
        if cmd in ("webui", "控制台"):
            return self._webui_text()
        if cmd in ("agents", "agent"):
            return self._agents_text()
        if cmd in ("use", "使用"):
            return self._set_default_agent_text(rest)
        if cmd in ("plugins", "插件"):
            return self._plugins_text()
        if cmd in ("tools", "工具"):
            return self._tools_text()
        if cmd in ("skills", "技能"):
            return self._skills_text()
        if cmd in ("modules", "integrations", "blueprints", "模块", "集成", "蓝图"):
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
                agent_id="",
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
        agent_id: str = "",
    ) -> str:
        umo = event.unified_msg_origin
        if self.storage.load_active_task(umo):
            return "当前会话已有 active task。请先 /agentlab finish 或 /agentlab cancel。"

        spec = self.storage.get_agent(agent_id or None)
        if not spec.enabled:
            return "当前 AgentSpec 未启用。请先在 Agent Lab WebUI 启用后再进入 Agent Mode。"
        effective_agent_name = await self._effective_agent_name(spec, event)
        profile_agent = spec.to_dict()
        profile_agent["name"] = effective_agent_name
        session_plugin_snapshot = await self.guard.apply_overrides(
            umo, spec.plugin_overrides
        )
        entry_summary = await self.summarizer.summarize_entry(event, goal, brief)
        task = TaskState(
            agent_id=spec.agent_id,
            agent_name=effective_agent_name,
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
                "agent": profile_agent,
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
            f"- agent: {effective_agent_name}\n"
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
        modules_prompt = self._build_task_extensions_prompt(spec)
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
                agent_hooks=AgentLabRunHooks(self.storage, task.umo, task.task_id),
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
        internal_block = {"agent_lab_enter_mode", "agent_lab_tick"}
        essential = {
            "agent_lab_read_state",
            "agent_lab_update_state",
            "agent_lab_request_approval",
            "agent_lab_set_heartbeat",
            "agent_lab_finish",
        }
        disabled_plugins = self._disabled_plugin_names(spec)
        if not spec.enabled_tools:
            toolset = tmgr.get_full_tool_set()
            for name in internal_block:
                try:
                    toolset.remove_tool(name)
                except Exception:
                    pass
            for tool in list(toolset.tools):
                if (
                    tool.name not in essential
                    and not self._tool_available_for_agent(tool, disabled_plugins)
                ):
                    toolset.remove_tool(tool.name)
            for name in essential:
                tool = tmgr.get_func(name)
                if tool:
                    toolset.add_tool(tool)
            return toolset
        from astrbot.core.agent.tool import ToolSet

        toolset = ToolSet()
        for name in spec.enabled_tools:
            if name == NO_EXTERNAL_TOOLS_SENTINEL:
                continue
            if name in internal_block:
                continue
            try:
                tool = tmgr.get_func(name)
            except Exception as exc:
                logger.warning("[AgentLab] cannot resolve tool %s: %s", name, exc)
                continue
            if tool and self._tool_available_for_agent(tool, disabled_plugins):
                toolset.add_tool(tool)
        for name in essential:
            try:
                tool = tmgr.get_func(name)
            except Exception:
                tool = None
            if tool:
                toolset.add_tool(tool)
        return toolset

    def _build_task_extensions_prompt(self, spec: AgentSpec) -> str:
        sections = []
        modules_prompt = self.modules.build_prompt(spec.module_ids, spec.module_settings)
        if modules_prompt.strip():
            sections.append(modules_prompt)
        skills_prompt = self._build_selected_skills_prompt(spec)
        if skills_prompt.strip():
            sections.append(skills_prompt)
        return "\n\n".join(sections)

    def _build_selected_skills_prompt(self, spec: AgentSpec) -> str:
        selected = [name.strip() for name in spec.enabled_skills if str(name).strip()]
        if not selected:
            return ""
        try:
            from astrbot.core.skills.skill_manager import SkillManager, build_skills_prompt

            skills = SkillManager().list_skills(active_only=False)
            by_name = {item.name: item for item in skills}
            chosen = [by_name[name] for name in selected if name in by_name]
            missing = [name for name in selected if name not in by_name]
            parts = [
                "[AgentSpec Selected Skills]",
                "以下 skills 是当前 AgentSpec 为任务模式选择的行为协议。使用前仍需按 Skill 规则读取 SKILL.md；未选择的 skill 不应作为本任务的主要依据。",
            ]
            if chosen:
                parts.append(build_skills_prompt(chosen))
            if missing:
                parts.append("未找到的 selected skills：" + ", ".join(missing))
            return "\n\n".join(parts)
        except Exception as exc:
            logger.warning("[AgentLab] selected skills prompt failed: %s", exc)
            return (
                "[AgentSpec Selected Skills]\n"
                f"当前 AgentSpec 选择了 skills：{', '.join(selected)}，但运行时读取失败：{exc}。"
            )

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

    async def _start_webui_server(self) -> None:
        if not _bool_cfg(self.config, "standalone_webui_enabled", True):
            return
        if self.webui_server:
            return
        if jsonify is None:
            logger.warning("[AgentLab] standalone WebUI skipped: quart is unavailable")
            return
        host = str(_cfg(self.config, "standalone_webui_host", "127.0.0.1") or "127.0.0.1").strip()
        port = int(_cfg(self.config, "standalone_webui_port", 8788) or 8788)
        token = str(_cfg(self.config, "standalone_webui_token", "") or "").strip()
        static_dir = Path(__file__).parent / "webui"
        self.webui_server = StandaloneWebUIServer(
            owner=self,
            static_dir=static_dir,
            host=host,
            port=port,
            token=token,
        )
        try:
            await self.webui_server.start()
            logger.info("[AgentLab] standalone WebUI listening on %s", self.webui_server.url)
            if host not in {"127.0.0.1", "localhost", "::1"} and not token:
                logger.warning(
                    "[AgentLab] standalone WebUI is not local-only and has no token configured."
                )
        except Exception as exc:
            logger.warning("[AgentLab] standalone WebUI failed to start: %s", exc)
            self.webui_server = None

    async def _stop_webui_server(self) -> None:
        if not self.webui_server:
            return
        try:
            await self.webui_server.stop()
        finally:
            self.webui_server = None

    def _register_web_apis(self) -> None:
        if jsonify is None:
            return
        self.context.register_web_api(f"/{PLUGIN_NAME}/state", self.api_state, ["GET"], "Agent Lab state")
        self.context.register_web_api(f"/{PLUGIN_NAME}/agents", self.api_agents, ["GET", "POST"], "Agent specs")
        self.context.register_web_api(f"/{PLUGIN_NAME}/modules", self.api_modules, ["GET", "POST"], "Agent modules")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/start", self.api_task_start, ["POST"], "Start task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/tick", self.api_task_tick, ["POST"], "Tick task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/finish", self.api_task_finish, ["POST"], "Finish task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/cancel", self.api_task_cancel, ["POST"], "Cancel task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/heartbeat", self.api_task_heartbeat, ["POST"], "Toggle heartbeat")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/approval", self.api_task_approval, ["POST"], "Resolve approval")

    async def api_state(self):
        return jsonify(
            {
                "default_agent_id": self.storage.default_agent_id(),
                "agents": [item.to_dict() for item in self.storage.list_agents()],
                "tasks": [item.to_dict() for item in self.storage.list_tasks()],
                "archives": [item.to_dict() for item in self.storage.list_archives()],
                "plugins": self._plugin_rows(),
                "tools": self._tool_rows(),
                "skills": self._skill_rows(),
                "modules": self.modules.list_modules(),
                "integrations": self.modules.list_modules(),
                "metrics": self._metrics_payload(),
                "webui": {
                    "standalone": bool(self.webui_server),
                    "url": self.webui_server.url if self.webui_server else "",
                    "auth": bool(self.webui_server and self.webui_server.token),
                },
                "runtime": {
                    "bot_label": self._current_bot_label(),
                    "default_agent_name": self._agent_name_from_label(
                        self._current_bot_label()
                    ),
                },
            }
        )

    async def api_agents(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            make_default = bool(payload.pop("_make_default", False))
            incoming_agent_id = str(payload.get("agent_id") or "").strip()
            previous_spec = None
            if incoming_agent_id:
                previous_spec = next(
                    (
                        item
                        for item in self.storage.list_agents()
                        if item.agent_id == incoming_agent_id
                    ),
                    None,
                )
            if not str(payload.get("agent_id") or "").strip():
                payload.pop("agent_id", None)
            spec = AgentSpec.from_dict(payload)
            if (
                previous_spec
                and previous_spec.identity_label_source == "astrbot_persona"
                and spec.name != previous_spec.name
            ):
                spec.identity_label_source = "manual"
            self.storage.save_agent(spec)
            if make_default:
                self.storage.set_default_agent(spec.agent_id)
            return jsonify({"ok": True, "agent": spec.to_dict()})
        return jsonify(
            {
                "default_agent_id": self.storage.default_agent_id(),
                "agents": [item.to_dict() for item in self.storage.list_agents()],
            }
        )

    async def api_modules(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            try:
                module = self.modules.save_custom_module(payload)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})
            return jsonify({"ok": True, "module": module.to_dict()})
        return jsonify({"modules": self.modules.list_modules()})

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
            agent_id=str(payload.get("agent_id") or ""),
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

    async def api_task_cancel(self):
        payload = await request.get_json(force=True, silent=True) or {}
        event = self._make_cron_event(str(payload.get("umo") or ""), "Agent Lab WebUI cancel")
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        msg = await self._finish_task(
            event,
            "cancelled",
            str(payload.get("reason") or "WebUI requested cancel."),
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

    async def api_task_approval(self):
        payload = await request.get_json(force=True, silent=True) or {}
        umo = str(payload.get("umo") or "")
        approval_id = str(payload.get("approval_id") or "")
        approved = bool(payload.get("approved", False))
        if not umo or not approval_id:
            return jsonify({"ok": False, "error": "umo and approval_id are required"})
        msg = self._resolve_approval(umo, approval_id, approved, "webui")
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
                    "locked": plugin.name == PLUGIN_NAME,
                    "desc": plugin.desc,
                    "module_path": getattr(plugin, "module_path", "") or "",
                    "root_dir_name": getattr(plugin, "root_dir_name", "") or "",
                }
            )
        return rows

    def _tool_rows(self) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        plugin_rows = {item["name"]: item for item in self._plugin_rows()}
        for tool in self.context.get_llm_tool_manager().func_list:
            seen.add(tool.name)
            plugin_name = self._tool_plugin_name(tool)
            plugin_row = plugin_rows.get(plugin_name or "")
            plugin_enabled = True if plugin_row is None else bool(plugin_row.get("activated", True))
            rows.append(
                {
                    "name": tool.name,
                    "active": getattr(tool, "active", True),
                    "effective_active": bool(getattr(tool, "active", True)) and plugin_enabled,
                    "description": getattr(tool, "description", ""),
                    "handler_module_path": getattr(tool, "handler_module_path", ""),
                    "plugin_name": plugin_name,
                    "plugin_display_name": plugin_row.get("display_name") if plugin_row else "",
                    "plugin_enabled": plugin_enabled,
                    "source": "registered",
                    "risk": "unknown",
                }
            )
        for item in BUILTIN_TOOL_CATALOG:
            if item["name"] in seen:
                continue
            rows.append(
                {
                    "name": item["name"],
                    "active": False,
                    "effective_active": False,
                    "description": item["description"],
                    "handler_module_path": "astrbot.core.tools",
                    "plugin_name": "",
                    "plugin_display_name": "AstrBot 内置工具",
                    "plugin_enabled": True,
                    "source": "builtin_catalog",
                    "risk": item["risk"],
                }
            )
        return rows

    def _skill_rows(self) -> list[dict[str, Any]]:
        try:
            from astrbot.core.skills.skill_manager import SkillManager

            return [item.__dict__ for item in SkillManager().list_skills(active_only=False)]
        except Exception:
            return []

    def _metrics_payload(self) -> dict[str, Any]:
        tasks = self.storage.list_tasks()
        archives = self.storage.list_archives()
        heartbeat_on = sum(1 for task in tasks if task.heartbeat.enabled)
        pending_approvals = sum(len(task.pending_approvals()) for task in tasks)
        return {
            "agents": len(self.storage.list_agents()),
            "active_tasks": len(tasks),
            "archived_tasks": len(archives),
            "heartbeat_online": heartbeat_on,
            "heartbeat_offline": max(len(tasks) - heartbeat_on, 0),
            "pending_approvals": pending_approvals,
            "task_triggers": len(tasks) + len(archives),
            "token_usage": 0,
            "token_usage_note": "当前框架未接入 provider token 统计，保留为汇总接口。",
        }

    def _webui_text(self) -> str:
        if not self.webui_server:
            return "Agent Lab 独立控制台未启动。请检查 standalone_webui_enabled 和端口配置。"
        suffix = "（需要 token）" if self.webui_server.token else ""
        return f"Agent Lab 独立控制台：{self.webui_server.url} {suffix}".strip()

    def _plugin_by_module_path(self, module_path: str | None) -> Any:
        if not module_path:
            return None
        try:
            from astrbot.core.star.star import star_map
        except Exception:
            star_map = {}
        plugin = star_map.get(module_path)
        if plugin:
            return plugin
        for item in self.context.get_all_stars():
            item_module_path = getattr(item, "module_path", None)
            if not item_module_path:
                continue
            if module_path == item_module_path or module_path.startswith(f"{item_module_path}."):
                return item
        return None

    def _tool_plugin_name(self, tool: Any) -> str:
        plugin = self._plugin_by_module_path(getattr(tool, "handler_module_path", None))
        if not plugin:
            return ""
        return str(getattr(plugin, "name", "") or "")

    def _disabled_plugin_names(self, spec: AgentSpec) -> set[str]:
        disabled = {
            item["name"]
            for item in self._plugin_rows()
            if item.get("name") and not bool(item.get("activated", True))
        }
        for plugin_name, enabled in spec.plugin_overrides.items():
            if plugin_name == PLUGIN_NAME:
                disabled.discard(plugin_name)
                continue
            if enabled:
                disabled.discard(plugin_name)
            else:
                disabled.add(plugin_name)
        return disabled

    def _tool_available_for_agent(self, tool: Any, disabled_plugins: set[str]) -> bool:
        if not bool(getattr(tool, "active", True)):
            return False
        plugin_name = self._tool_plugin_name(tool)
        if plugin_name and plugin_name in disabled_plugins:
            return False
        return True

    def _status_text(self, umo: str) -> str:
        task = self.storage.load_active_task(umo)
        webui = f"\n- webui: {self.webui_server.url}" if self.webui_server else ""
        if not task:
            return "Agent Lab：当前没有 active task。" + webui
        return (
            f"Agent Lab active task:\n"
            f"- id: {task.task_id}\n"
            f"- status: {task.status}\n"
            f"- goal: {task.root_goal}\n"
            f"- next: {task.next_step or '-'}\n"
            f"- heartbeat: {'on' if task.heartbeat.enabled else 'off'}\n"
            f"- pending approvals: {len(task.pending_approvals())}\n"
            f"- state: {self.storage.task_markdown_path(umo, task.task_id)}"
            f"{webui}"
        )

    def _agents_text(self) -> str:
        default_id = self.storage.default_agent_id()
        return "\n".join(
            f"- {'* ' if item.agent_id == default_id else ''}{item.agent_id}: {item.name} ({item.trigger_mode})"
            for item in self.storage.list_agents()
        )

    def _set_default_agent_text(self, agent_id: str) -> str:
        agent_id = agent_id.strip()
        if not agent_id:
            return "请提供 AgentSpec ID。可用 /agentlab agents 查看。"
        if not self.storage.set_default_agent(agent_id):
            return f"未找到 AgentSpec：{agent_id}"
        spec = self.storage.get_agent(agent_id)
        return f"已切换默认 Agent：{spec.name} ({spec.agent_id})"

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
            "/agentlab use <agent_id>\n"
            "/agentlab start <目标>\n"
            "/agentlab tick\n"
            "/agentlab heartbeat on|off\n"
            "/agentlab approve <approval_id>\n"
            "/agentlab reject <approval_id>\n"
            "/agentlab finish <总结>\n"
            "/agentlab cancel <原因>\n"
            "/agentlab webui\n"
            "/agentlab agents|plugins|tools|skills|integrations"
        )

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 20] + "\n...[truncated]"

    def _sync_default_agent_identity(self) -> None:
        """Keep the built-in default Agent aligned with AstrBot's current persona."""
        try:
            spec = self.storage.get_agent()
        except Exception:
            return
        if not self._should_sync_agent_identity(spec):
            return
        derived_name = self._agent_name_from_label(self._current_bot_label())
        if spec.name == derived_name and spec.identity_label_source == "astrbot_persona":
            return
        spec.name = derived_name
        spec.identity_label_source = "astrbot_persona"
        self.storage.save_agent(spec)

    async def _effective_agent_name(
        self, spec: AgentSpec, event: AstrMessageEvent
    ) -> str:
        if not self._should_sync_agent_identity(spec):
            return spec.name
        return self._agent_name_from_label(await self._current_bot_label_for_event(event))

    def _should_sync_agent_identity(self, spec: AgentSpec) -> bool:
        if spec.identity_label_source == "astrbot_persona":
            return True
        if spec.name in DEFAULT_AGENT_NAMES:
            return True
        return self._looks_like_default_agent_template(spec)

    @staticmethod
    def _looks_like_default_agent_template(spec: AgentSpec) -> bool:
        if not spec.name.endswith(AGENT_NAME_SUFFIX):
            return False
        base = AgentSpec()
        return (
            spec.description == base.description
            and spec.system_prompt == base.system_prompt
            and spec.task_prompt == base.task_prompt
            and spec.enabled_tools == base.enabled_tools
            and spec.module_ids == base.module_ids
        )

    @staticmethod
    def _agent_name_from_label(bot_label: str) -> str:
        return f"{bot_label or DEFAULT_BOT_LABEL}{AGENT_NAME_SUFFIX}"

    def _current_bot_label(self) -> str:
        persona_name = self._current_persona_name()
        if self._usable_persona_label(persona_name):
            return persona_name
        return DEFAULT_BOT_LABEL

    async def _current_bot_label_for_event(self, event: AstrMessageEvent) -> str:
        persona_name = await self._current_persona_name_for_event(event)
        if self._usable_persona_label(persona_name):
            return persona_name
        return self._current_bot_label()

    async def _current_persona_name_for_event(self, event: AstrMessageEvent) -> str:
        umo = getattr(event, "unified_msg_origin", "")
        config = self._context_config(umo)
        provider_settings = _cfg(config, "provider_settings", {}) or {}
        conversation_persona_id = await self._conversation_persona_id(umo)
        persona_manager = getattr(self.context, "persona_manager", None)

        resolve_selected = getattr(persona_manager, "resolve_selected_persona", None)
        if callable(resolve_selected):
            try:
                _, persona, _, _ = await resolve_selected(
                    umo=umo,
                    conversation_persona_id=conversation_persona_id or None,
                    platform_name=self._event_platform_name(event),
                    provider_settings=provider_settings,
                )
                name = self._persona_name(persona)
                if name:
                    return name
            except Exception:
                pass

        if conversation_persona_id:
            name = self._persona_name_by_id(conversation_persona_id)
            if name:
                return name

        get_default = getattr(persona_manager, "get_default_persona_v3", None)
        if callable(get_default):
            try:
                return self._persona_name(await get_default(umo=umo))
            except Exception:
                pass

        return self._current_persona_name()

    def _current_persona_name(self) -> str:
        persona_manager = getattr(self.context, "persona_manager", None)
        for attr in ("selected_default_persona_v3", "selected_default_persona"):
            persona = getattr(persona_manager, attr, None)
            name = self._persona_name(persona)
            if name:
                return name

        config = self._context_config()
        provider_settings = _cfg(config, "provider_settings", {}) or {}
        default_persona = _cfg(provider_settings, "default_personality", "")
        name = self._persona_name_by_id(default_persona)
        if name:
            return name
        if default_persona:
            return str(default_persona).strip()
        return ""

    @staticmethod
    def _persona_name(persona: Any) -> str:
        if not persona:
            return ""
        if isinstance(persona, dict):
            return str(persona.get("name") or persona.get("persona_id") or "").strip()
        for key in ("name", "persona_id"):
            try:
                value = persona[key]
                if value:
                    return str(value).strip()
            except Exception:
                pass
        return str(
            getattr(persona, "name", "")
            or getattr(persona, "persona_id", "")
            or ""
        ).strip()

    def _persona_name_by_id(self, persona_id: Any) -> str:
        persona_id = str(persona_id or "").strip()
        if not persona_id:
            return ""
        persona_manager = getattr(self.context, "persona_manager", None)
        get_by_id = getattr(persona_manager, "get_persona_v3_by_id", None)
        if callable(get_by_id):
            try:
                return self._persona_name(get_by_id(persona_id))
            except Exception:
                return ""
        return ""

    async def _conversation_persona_id(self, umo: str) -> str:
        if not umo:
            return ""
        conversation_manager = getattr(self.context, "conversation_manager", None)
        get_curr = getattr(conversation_manager, "get_curr_conversation_id", None)
        get_conversation = getattr(conversation_manager, "get_conversation", None)
        if not callable(get_curr) or not callable(get_conversation):
            return ""
        try:
            conversation_id = await get_curr(umo)
            if not conversation_id:
                return ""
            conversation = await get_conversation(umo, conversation_id)
        except Exception:
            return ""
        if isinstance(conversation, dict):
            return str(conversation.get("persona_id") or "").strip()
        return str(getattr(conversation, "persona_id", "") or "").strip()

    @staticmethod
    def _event_platform_name(event: AstrMessageEvent) -> str:
        get_platform_name = getattr(event, "get_platform_name", None)
        if callable(get_platform_name):
            try:
                return str(get_platform_name() or "")
            except Exception:
                pass
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        return umo.split(":", 1)[0] if ":" in umo else ""

    @staticmethod
    def _usable_persona_label(name: str) -> bool:
        normalized = str(name or "").strip()
        return normalized.lower() not in {"", "default", "[%none]", "none"}

    def _context_config(self, umo: str | None = None) -> Any:
        get_config = getattr(self.context, "get_config", None)
        if callable(get_config):
            if umo:
                try:
                    return get_config(umo=umo)
                except Exception:
                    try:
                        return get_config(umo)
                    except Exception:
                        pass
            try:
                return get_config()
            except Exception:
                pass
        return getattr(self.context, "_config", None)
