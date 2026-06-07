from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
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

from .agent_lab import (
    AgentLabService,
    AgentLabStorage,
    AgentSpec,
    AgentRuntime,
    ApprovalRequest,
    AgentMemoryOrchestrator,
    MemoryManager,
    TaskPatternLibrary,
    TaskState,
)
from .agent_lab.api_executor import CustomApiExecutor
from .agent_lab.conditions import (
    evaluate_condition,
    resolve_path,
    schema_compatible,
    schema_validation_errors,
)
from .agent_lab.hooks import AgentLabRunHooks
from .agent_lab.models import new_id, now_iso
from .agent_lab.models import WorkflowScope, WorkflowTrigger
from .agent_lab.modules import ModuleRegistry
from .agent_lab.prompts import (
    build_agent_mode_policy,
    build_task_system_prompt,
    build_tick_prompt,
)
from .agent_lab.policy import PermissionPolicy
from .agent_lab.node_runtime import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
)
from .agent_lab.runtime import WorkflowDecision, WorkflowRuntime, WorkflowRuntimeRun
from .agent_lab.runtime_runner import AgentRuntimeRunner
from .agent_lab.session_guard import SessionPluginGuard
from .agent_lab.summarizer import AgentSummarizer
from .agent_lab.tool_executor import AstrBotToolExecutor
from .agent_lab.verifier import AgentVerifier
from .agent_lab.webui_server import StandaloneWebUIServer
from .agent_lab.workers import normalize_worker_output, worker_spec_for_node


PLUGIN_NAME = "astrbot_plugin_agent_lab"
PLUGIN_VERSION = "v0.1.1"
PLUGIN_AUTHOR = "zzz27578 & Codex"
PLUGIN_DESC = "在 AstrBot 内创建、运行和管理个人 Agent Mode。"
SKILL_NAME = "agent-mode"
ENTRY_SUMMARY_RULE_NAME = "agent-mode-entry-summary"
EXIT_SUMMARY_RULE_NAME = "agent-mode-exit-summary"
NO_EXTERNAL_TOOLS_SENTINEL = "__agent_lab_no_external_tools__"
CUSTOM_API_TOOL_NAME = "agent_lab_call_custom_api"
DEFAULT_BOT_LABEL = "当前 Bot"
AGENT_NAME_SUFFIX = " Agent Mode"
WORKFLOW_KINDS = {
    "state",
    "tool",
    "guard",
    "human",
    "api",
    "memory",
    "branch",
    "loop",
    "transform",
    "retrieval",
    "subflow",
    "notification",
    "validation",
    "trigger",
    "detector",
    "report",
    "rate_limit",
    "error_handler",
}
WORKFLOW_ACTIONS = {
    "listen_message",
    "match_keyword",
    "match_regex",
    "llm_detect",
    "scope_filter",
    "schedule_trigger",
    "plugin_event_trigger",
    "webhook_trigger",
    "confirm_entry",
    "summarize_entry",
    "restore_isolation",
    "variable_set",
    "variable_get",
    "text_template",
    "json_transform",
    "merge",
    "iterator",
    "subflow_call",
    "plan",
    "route_condition",
    "conditional_router",
    "parallel_branch",
    "run_tools",
    "call_api",
    "http_request",
    "file_operation",
    "code_exec",
    "transform_context",
    "retrieve_memory",
    "request_approval",
    "wait_user",
    "handoff",
    "validate_output",
    "debate_validation",
    "retry",
    "limit_rate",
    "catch_error",
    "save_state",
    "save_memory",
    "write_record",
    "generate_report",
    "send_message",
    "send_private_message",
    "send_email",
    "heartbeat",
    "notify",
    "archive",
    "exit_summary",
    "manual",
}
AUTO_IDENTITY_LABEL_SOURCES = {
    "astrbot_runtime",
    "astrbot_persona",  # legacy value kept for existing AgentSpec files.
    "astrbot_config",
}
CONFIG_BOT_LABEL_KEYS = (
    "bot_label",
    "bot_display_name",
    "bot_name",
    "robot_name",
    "assistant_name",
    "wecom_ai_bot_name",
    "app_name",
    "kf_name",
)
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
        "name": "astrbot_sandboxed_shell",
        "description": "Execute shell commands in an Agent Lab sandbox workspace when Docker/Podman is available.",
        "risk": "high",
    },
    {
        "name": "astrbot_sandboxed_python",
        "description": "Execute Python in an Agent Lab sandbox workspace when Docker/Podman is available.",
        "risk": "high",
    },
    {
        "name": "future_task",
        "description": "AstrBot proactive future task tool.",
        "risk": "work",
    },
    {
        "name": CUSTOM_API_TOOL_NAME,
        "description": "Call an Agent Lab registered custom API with managed credentials.",
        "risk": "work",
    },
    {
        "name": "agent_lab_read_task_memory",
        "description": "Read tagged Agent Lab task memories without entering Agent Mode.",
        "risk": "safe",
    },
    {
        "name": "agent_lab_recommend_task_patterns",
        "description": "Recommend reusable plan templates from completed Agent Lab tasks.",
        "risk": "safe",
    },
    {
        "name": "agent_lab_update_workflow",
        "description": "Check or edit Agent Lab workflow nodes and edges.",
        "risk": "work",
    },
    {
        "name": "agent_lab_run_parallel_workflow",
        "description": "Run outgoing workflow nodes from a parallel branch and merge their results.",
        "risk": "work",
    },
    {
        "name": "agent_lab_advance_workflow",
        "description": "Record and advance the current task workflow cursor.",
        "risk": "safe",
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


def _lines_or_none(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return "- none"
    return "\n".join(f"- {item}" for item in cleaned)


@register(PLUGIN_NAME, PLUGIN_AUTHOR, PLUGIN_DESC, PLUGIN_VERSION)
class AgentLabPlugin(Star):
    def __init__(self, context: Context, config: Any = None):
        super().__init__(context)
        self.config = config or {}
        self.storage = AgentLabStorage(StarTools.get_data_dir(PLUGIN_NAME))
        self.memory_manager = MemoryManager(self.storage)
        self.pattern_library = TaskPatternLibrary(self.storage)
        self.memory_orchestrator = AgentMemoryOrchestrator(self.memory_manager, self.pattern_library, self.storage)
        self.service = AgentLabService(self)
        self.modules = ModuleRegistry(self.storage.modules_dir)
        self.guard = SessionPluginGuard(protected_plugins={PLUGIN_NAME})
        self.webui_server: StandaloneWebUIServer | None = None
        self._running_ticks: set[str] = set()
        self.workflow_runtime = WorkflowRuntime(
            max_auto_steps=int(_cfg(self.config, "workflow_auto_steps_per_tick", 6))
        )
        self.runtime_runner = AgentRuntimeRunner(self)
        self.agent_runtime = AgentRuntime()
        self.verifier = AgentVerifier()
        self.api_executor = CustomApiExecutor(self)
        self.tool_executor = AstrBotToolExecutor(self)
        self.node_executors = NodeExecutorRegistry()
        self._register_node_executors()
        self._workflow_schedule_jobs: dict[str, str] = {}
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
        self._refresh_summarizer_rules()
        self._register_web_apis()

    async def initialize(self):
        self._sync_default_agent_identity()
        self._sync_agent_mode_skill()
        await self._rehydrate_heartbeats()
        await self._rehydrate_workflow_schedules()
        await self._start_webui_server()
        # Prune stale memory candidates so the system starts clean.
        try:
            pruned = self.memory_manager.prune_stale_candidates(max_age_days=7)
            if pruned:
                logger.info(f"[AgentLab] pruned {pruned} stale memory candidate(s)")
        except Exception as exc:
            logger.warning(f"[AgentLab] memory prune skipped: {exc}")
        # Log pattern library health.
        try:
            active_patterns = self.pattern_library.count(status="active")
            logger.info(f"[AgentLab] pattern library: {active_patterns} active pattern(s)")
        except Exception:
            pass
        logger.info("[AgentLab] initialized")

    async def terminate(self):
        await self._disable_workflow_schedules()
        await self._stop_webui_server()
        logger.info("[AgentLab] terminated")

    def _cfg_value(self, key: str, default: Any = None) -> Any:
        return _cfg(self.config, key, default)

    @filter.command("agentlab")
    async def agentlab_command(self, event: AstrMessageEvent):
        """Agent Lab 控制台命令：status/start/tick/finish/cancel/heartbeat/approve。"""
        if False and not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            yield event.plain_result("Agent Lab 第一版仅允许私聊使用，避免群聊误触发和权限风险。")
            return
        result = await self._handle_command(event, _message_tail(event, "agentlab"))
        yield event.plain_result(result)

    @filter.command("al")
    async def al_command(self, event: AstrMessageEvent):
        """Agent Lab 短命令。"""
        if False and not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
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
        spec = AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
        )
        self._normalize_agent_workflow(spec)
        self._sync_agent_runtime(task, spec, reason="read_state")
        self.storage.save_task(task)
        if format == "markdown":
            return self.storage.render_markdown(task)
        runtime_summary = self.agent_runtime.summary(task)
        return (
            f"task_id: {task.task_id}\n"
            f"status: {task.status}\n"
            f"root_goal: {task.root_goal}\n"
            f"completion_conditions: {task.completion_conditions}\n"
            f"workflow: {self._workflow_runtime_text(task)}\n"
            f"runtime: current={runtime_summary.get('current_node_id') or '-'} "
            f"capabilities={runtime_summary.get('capability_count', 0)} "
            f"verdicts={runtime_summary.get('verdicts', 0)}\n"
            f"entry_summary: {self._compact_text(task.entry_summary or task.task_brief, 1600)}\n"
            f"current_summary: {task.current_summary or '-'}\n"
            f"last_confirmed_progress: {task.last_confirmed_progress or '-'}\n"
            f"next_step: {task.next_step or '-'}\n"
            f"last_observation: {self._compact_text(task.last_observation, 1200) or '-'}\n"
            f"pending_approvals: {len(task.pending_approvals())}\n"
            f"state_path: {self.storage.task_markdown_path(task.umo, task.task_id)}"
        )

    @filter.llm_tool(name="agent_lab_read_runtime")
    async def agent_lab_read_runtime(self, event: AstrMessageEvent, format: str = "summary") -> str:
        """读取当前 Agent Runtime，包括能力目录、结构化计划、验证结论和恢复入口。

        Args:
            format(string): summary 或 json。summary 给模型快速复盘，json 返回结构化摘要。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        spec = AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
        )
        self._normalize_agent_workflow(spec)
        self._sync_agent_runtime(task, spec, reason="read_runtime")
        self.storage.save_task(task)
        if format == "json":
            return json.dumps(self.agent_runtime.summary(task), ensure_ascii=False, indent=2)
        return self.agent_runtime.summary_text(task)

    @filter.llm_tool(name="agent_lab_advance_workflow")
    async def agent_lab_advance_workflow(
        self,
        event: AstrMessageEvent,
        node_id: str = "",
        outcome: str = "",
        next_node_id: str = "",
        note: str = "",
        status: str = "completed",
    ) -> str:
        """记录当前工作流节点结果，并把任务游标推进到下一节点。

        Args:
            node_id(string): 当前完成或正在记录的节点 ID；为空时使用 task_state 当前节点。
            outcome(string): 该节点本轮产出的结果摘要。
            next_node_id(string): 要进入的下一节点 ID；多分支时必须明确填写。
            note(string): 补充说明，如为什么选择这个分支。
            status(string): completed/running/skipped/blocked。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
        self._normalize_agent_workflow(spec)
        result = self._advance_task_workflow(
            task,
            spec,
            node_id=node_id,
            outcome=outcome,
            next_node_id=next_node_id,
            note=note,
            status=status,
        )
        self.storage.save_task(task)
        return result

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
        task.add_snapshot(
            "update_state",
            {
                "progress": progress.strip(),
                "blocker": blocker.strip(),
                "need_heartbeat": need_heartbeat,
            },
        )
        spec = AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
        )
        self._normalize_agent_workflow(spec)
        self._sync_agent_runtime(task, spec, reason="update_state")
        self.agent_runtime.record_observation(
            task,
            source="update_state",
            node_id=task.workflow_current_node_id,
            payload={
                "current_summary": task.current_summary,
                "progress": progress.strip(),
                "next_step": task.next_step,
                "last_observation": task.last_observation,
                "status": task.status,
                "blocker": blocker.strip(),
            },
            summary=last_observation or progress or current_summary,
        )
        self.agent_runtime.record_verdict(
            task,
            node_id=task.workflow_current_node_id,
            passed=task.status == "running" and not blocker.strip(),
            status=task.status,
            reason=blocker.strip() or last_observation or progress or "state updated",
            missing=[blocker.strip()] if blocker.strip() else [],
            next_action=task.next_step,
        )
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
        task.set_wait(
            wait_reason="need_approval",
            message=f"approval requested: {operation}",
            source="agent_lab_request_approval",
            resume_command=f"/agentlab approve {approval.approval_id}",
            required_input=[operation],
        )
        task.add_log("approval_requested", f"{approval.approval_id}: {operation}")
        self.agent_runtime.record_pause(
            task,
            reason=f"approval requested: {operation}",
            missing=[operation],
        )
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

    @filter.llm_tool(name="agent_lab_read_task_memory")
    async def agent_lab_read_task_memory(
        self,
        event: AstrMessageEvent,
        query: str = "",
        status: str = "accepted",
        limit: str = "8",
    ) -> str:
        """读取 Agent Lab 暴露的任务记忆。普通模式也可以用来按标签或关键词找续写上下文。

        Args:
            query(string): 可选关键词，会匹配记忆正文、标签、来源任务 ID。
            status(string): accepted/candidate/rejected/all，默认只读 accepted。
            limit(string): 返回条数上限，默认 8。
        """
        query = str(query or "").strip().lower()
        status = str(status or "accepted").strip().lower()
        try:
            limit = max(1, min(int(limit or 8), 30))
        except Exception:
            limit = 8
        active_task = self.storage.load_active_task(event.unified_msg_origin)
        allow_private = bool(active_task)
        rows = []
        for item in reversed(self.storage.list_memory_entries()):
            item_status = str(item.get("status") or "candidate").strip().lower()
            layer = str(item.get("layer") or "").strip()
            visible, private_same_scope = self._memory_entry_visible(
                item,
                umo=event.unified_msg_origin,
                active_task=active_task,
                allow_private=allow_private,
            )
            if status != "all":
                if allow_private and layer == "private_task_memory" and status == "accepted":
                    if not private_same_scope or item_status not in {"accepted", "candidate"}:
                        continue
                elif item_status != status:
                    continue
            if status == "all" and not allow_private and item_status != "accepted":
                continue
            if not visible:
                continue
            haystack = "\n".join(
                [
                    str(item.get("text") or ""),
                    str(item.get("source_task_id") or ""),
                    " ".join(str(tag) for tag in item.get("tags") or []),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            rows.append(self._memory_entry_row(item, include_text=True))
            if len(rows) >= limit:
                break
        if not rows:
            return "没有匹配的任务记忆。"
        return json.dumps(rows, ensure_ascii=False, indent=2)

    @filter.llm_tool(name="agent_lab_recommend_task_patterns")
    async def agent_lab_recommend_task_patterns(
        self,
        event: AstrMessageEvent,
        query: str = "",
        limit: str = "5",
    ) -> str:
        """Recommend reusable plan templates mined from completed Agent Lab tasks.

        Args:
            query(string): Current task goal, keywords, or desired outcome.
            limit(string): Maximum number of patterns, default 5.
        """
        query = str(query or "").strip()
        if not query:
            active_task = self.storage.load_active_task(event.unified_msg_origin)
            query = str(getattr(active_task, "root_goal", "") or "").strip()
        try:
            limit_int = max(1, min(int(limit or 5), 20))
        except Exception:
            limit_int = 5
        rows = self.pattern_library.recommend(query, limit=limit_int)
        if not rows:
            return "No matching Agent Lab task patterns."
        return json.dumps(
            [self.pattern_library.compact_for_runtime(row) for row in rows],
            ensure_ascii=False,
            indent=2,
        )

    @filter.llm_tool(name="agent_lab_call_custom_api")
    async def agent_lab_call_custom_api(
        self,
        event: AstrMessageEvent,
        api_id: str,
        query_json: str = "",
        body_json: str = "",
        headers_json: str = "",
    ) -> str:
        """调用 Agent Lab WebUI 中预注册的自定义 API。只能调用已注册 API，密钥不会返回给模型。

        Args:
            api_id(string): 自定义 API 的 api_id 或名称。
            query_json(string): 可选 JSON 对象，追加到 URL 查询参数。
            body_json(string): 可选 JSON 对象或数组，作为非 GET 请求体。
            headers_json(string): 可选 JSON 对象，作为本次调用的额外请求头。
        """
        result, api_spec, message = await self._call_registered_custom_api(
            api_id,
            query_json=query_json,
            body_json=body_json,
            headers_json=headers_json,
        )
        if message:
            return message
        task = self.storage.load_active_task(event.unified_msg_origin)
        if task:
            task.add_log(
                "custom_api",
                f"{api_spec.get('api_id')}: status={result.get('status', '-')}",
            )
            task.add_snapshot(
                "custom_api",
                {
                    "api_id": api_spec.get("api_id"),
                    "status": result.get("status"),
                    "ok": result.get("ok"),
                },
            )
            self.storage.save_task(task)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @filter.llm_tool(name="agent_lab_run_parallel_workflow")
    async def agent_lab_run_parallel_workflow(
        self,
        event: AstrMessageEvent,
        branch_node_id: str = "",
        parallel_group: str = "",
        merge_node_id: str = "",
        shared_instruction: str = "",
        api_payloads_json: str = "",
        max_concurrency: str = "3",
    ) -> str:
        """执行当前工作流中的并行分支，并把 API/提示词/工具/插件工作包结果写回 task_state。

        Args:
            branch_node_id(string): 并行分支节点 ID；为空时使用当前工作流节点或第一个 parallel_branch。
            parallel_group(string): 可选分组名，只运行匹配 parallel_group 的后续工作包。
            merge_node_id(string): 可选汇总节点 ID；为空时自动寻找多个分支共同指向的节点。
            shared_instruction(string): 给所有工作包追加的本轮统一要求。
            api_payloads_json(string): 可选 JSON 对象，按 node_id 配置 API query/body/headers。
            max_concurrency(string): 并发上限，默认 3，最大 6。
        """
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。"
        if task.pending_approvals():
            return "存在待审批操作，先处理审批再运行并行工作流。"
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
        self._normalize_agent_workflow(spec)
        try:
            api_payloads = self._parse_json_object(api_payloads_json, "api_payloads_json") if api_payloads_json else {}
        except ValueError as exc:
            return str(exc)
        try:
            concurrency = max(1, min(int(max_concurrency or 3), 6))
        except Exception:
            concurrency = 3

        run = await self._run_parallel_workflow(
            event=event,
            task=task,
            spec=spec,
            branch_node_id=branch_node_id,
            parallel_group=parallel_group,
            merge_node_id=merge_node_id,
            shared_instruction=shared_instruction,
            api_payloads=api_payloads,
            max_concurrency=concurrency,
        )
        self.storage.save_task(task)
        return json.dumps(run, ensure_ascii=False, indent=2)

    @filter.llm_tool(name="agent_lab_update_workflow")
    async def agent_lab_update_workflow(
        self,
        event: AstrMessageEvent,
        operation: str,
        agent_id: str = "",
        node_id: str = "",
        title: str = "",
        kind: str = "state",
        stage: str = "plan",
        action: str = "manual",
        description: str = "",
        instruction: str = "",
        prompt: str = "",
        condition: str = "",
        parallel_group: str = "",
        from_node: str = "",
        to_node: str = "",
        ref_type: str = "",
        ref_id: str = "",
    ) -> str:
        """修改或检查 AgentSpec 工作流，让 Bot 能按用户要求调整某个环节。

        Args:
            operation(string): check/add_node/update_node/delete_node/add_edge/delete_edge/autolayout。
            agent_id(string): 可选 AgentSpec ID；为空时修改默认 AgentSpec。
            node_id(string): 节点 ID。新增时为空会自动生成。
            title(string): 节点标题。
            kind(string): state/tool/guard/human/api/memory/branch/loop/transform/retrieval/subflow/notification/validation。
            stage(string): entry/plan/execute/guard/checkpoint/archive。
            action(string): 节点动作，如 run_tools、call_api、validate_output。
            description(string): 节点短说明。
            instruction(string): 该环节的执行说明。
            prompt(string): 并行 Agent、子流程或提示词模块的专用提示词。
            condition(string): 分支或连线判断条件说明。
            parallel_group(string): 并行分支分组名。
            from_node(string): 连线起点。
            to_node(string): 连线终点。
            ref_type(string): 可选引用类型：plugin/api/tool/skill。
            ref_id(string): 可选引用 ID，例如 plugin_name、api_id、tool_name、skill_name。
        """
        operation = str(operation or "check").strip().lower()
        spec = self.storage.get_agent(agent_id or None)
        self._normalize_agent_workflow(spec)

        changed = False
        if operation == "check":
            return json.dumps(self._workflow_report(spec), ensure_ascii=False, indent=2)
        if operation == "autolayout":
            self._autolayout_workflow(spec)
            changed = True
        elif operation == "add_node":
            ref_type_clean = str(ref_type or "").strip().lower()
            if not ref_type_clean and ref_id:
                if kind == "api" or action == "call_api":
                    ref_type_clean = "api"
                elif kind == "tool" or action == "run_tools":
                    ref_type_clean = "tool"
                elif kind == "subflow":
                    ref_type_clean = "plugin"
            base = node_id or title or kind or "node"
            new_id = self._unique_workflow_id(
                self._normalize_workflow_id(base),
                {str(item.get("id") or "") for item in spec.workflow_nodes},
            )
            node = {
                "id": new_id,
                "title": str(title or new_id).strip()[:80],
                "kind": kind if kind in WORKFLOW_KINDS else "state",
                "stage": stage if stage in {"entry", "plan", "execute", "guard", "checkpoint", "archive"} else "plan",
                "action": action if action in WORKFLOW_ACTIONS else "manual",
                "description": str(description or "").strip()[:500],
                "instruction": str(instruction or title or new_id).strip()[:1000],
            }
            if prompt:
                node["prompt"] = str(prompt).strip()[:4000]
            if condition:
                node["condition"] = str(condition).strip()[:1000]
            if parallel_group:
                node["parallel_group"] = str(parallel_group).strip()[:80]
            if ref_type_clean:
                node["ref_type"] = ref_type_clean
            if ref_id:
                node["ref_id"] = str(ref_id).strip()
                if node.get("ref_type") == "api":
                    node["api_id"] = str(ref_id).strip()
                if node.get("ref_type") == "plugin":
                    node["plugin_name"] = str(ref_id).strip()
                if node.get("ref_type") == "tool":
                    node["tool_name"] = str(ref_id).strip()
                if node.get("ref_type") == "skill":
                    node["skill_name"] = str(ref_id).strip()
            node["x"], node["y"] = self._workflow_default_position(node["stage"], len(spec.workflow_nodes))
            spec.workflow_nodes.append(node)
            node_id = new_id
            changed = True
        elif operation == "update_node":
            node = next((item for item in spec.workflow_nodes if item.get("id") == node_id), None)
            if not node:
                return f"未找到工作流节点：{node_id}"
            if title:
                node["title"] = str(title).strip()[:80]
            if kind:
                node["kind"] = kind if kind in WORKFLOW_KINDS else node.get("kind", "state")
            if stage:
                node["stage"] = stage if stage in {"entry", "plan", "execute", "guard", "checkpoint", "archive"} else node.get("stage", "plan")
            if action:
                node["action"] = action if action in WORKFLOW_ACTIONS else node.get("action", "manual")
            if description:
                node["description"] = str(description).strip()[:500]
            if instruction:
                node["instruction"] = str(instruction).strip()[:1000]
            if prompt:
                node["prompt"] = str(prompt).strip()[:4000]
            if condition:
                node["condition"] = str(condition).strip()[:1000]
            if parallel_group:
                node["parallel_group"] = str(parallel_group).strip()[:80]
            if ref_type:
                node["ref_type"] = str(ref_type).strip().lower()
            if ref_id:
                node["ref_id"] = str(ref_id).strip()
                if node.get("ref_type") == "api":
                    node["api_id"] = str(ref_id).strip()
                if node.get("ref_type") == "plugin":
                    node["plugin_name"] = str(ref_id).strip()
                if node.get("ref_type") == "tool":
                    node["tool_name"] = str(ref_id).strip()
                if node.get("ref_type") == "skill":
                    node["skill_name"] = str(ref_id).strip()
            changed = True
        elif operation == "delete_node":
            before = len(spec.workflow_nodes)
            spec.workflow_nodes = [item for item in spec.workflow_nodes if item.get("id") != node_id]
            spec.workflow_edges = [
                edge
                for edge in spec.workflow_edges
                if edge.get("from") != node_id and edge.get("to") != node_id
            ]
            changed = before != len(spec.workflow_nodes)
            if not changed:
                return f"未找到工作流节点：{node_id}"
        elif operation == "add_edge":
            if not from_node or not to_node:
                return "add_edge 需要 from_node 和 to_node。"
            ids = {item.get("id") for item in spec.workflow_nodes}
            if from_node not in ids or to_node not in ids or from_node == to_node:
                return "连线起点或终点无效。"
            if not any(edge.get("from") == from_node and edge.get("to") == to_node for edge in spec.workflow_edges):
                spec.workflow_edges.append({"from": from_node, "to": to_node})
                changed = True
        elif operation == "delete_edge":
            before = len(spec.workflow_edges)
            spec.workflow_edges = [
                edge
                for edge in spec.workflow_edges
                if not (edge.get("from") == from_node and edge.get("to") == to_node)
            ]
            changed = before != len(spec.workflow_edges)
            if not changed:
                return f"未找到连线：{from_node} -> {to_node}"
        else:
            return "operation 必须是 check/add_node/update_node/delete_node/add_edge/delete_edge/autolayout。"

        if changed:
            self._prepare_agent_spec_for_save(spec)
            self.storage.save_agent(spec)
        report = self._workflow_report(spec)
        return json.dumps(
            {
                "ok": True,
                "changed": changed,
                "agent_id": spec.agent_id,
                "selected_node_id": node_id,
                "workflow": report,
            },
            ensure_ascii=False,
            indent=2,
        )

    @filter.on_llm_request()
    async def inject_agent_lab_policy(self, event: AstrMessageEvent, req: ProviderRequest):
        if not _bool_cfg(self.config, "inject_agent_mode_policy", True):
            return
        if False and not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            return
        spec = self.storage.get_agent()
        task = self.storage.load_active_task(event.unified_msg_origin)
        if task:
            spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or spec.to_dict())
            modules_prompt = "\n\n".join(
                part
                for part in (
                    self._build_task_extensions_prompt(spec, task=task),
                    self._build_exposed_task_memory_prompt(),
                )
                if part.strip()
            )
            req.system_prompt += "\n\n" + build_task_system_prompt(
                spec, task, modules_prompt
            )
        else:
            if not spec.enabled:
                return
            memory_prompt = self._build_exposed_task_memory_prompt()
            pattern_prompt = self._build_task_pattern_prompt(event.message_str)
            req.system_prompt += "\n\n" + build_agent_mode_policy(spec)
            if pattern_prompt:
                req.system_prompt += "\n\n" + pattern_prompt
            if memory_prompt:
                req.system_prompt += "\n\n" + memory_prompt

    async def _handle_command(self, event: AstrMessageEvent, tail: str) -> str:
        if not tail or tail in ("help", "帮助"):
            return self._help_text()
        cmd, _, rest = tail.partition(" ")
        cmd = cmd.lower().strip()
        rest = rest.strip()

        if cmd in ("status", "状态"):
            return self._status_text(event.unified_msg_origin)
        if cmd in ("runtime", "运行时"):
            return self._runtime_text(event.unified_msg_origin)
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
        if cmd in ("memory", "记忆"):
            return self._memory_command_text(event, rest)
        if cmd in ("patterns", "pattern", "plans", "模板", "模式"):
            return self._patterns_text(rest)
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
        trigger_payload: dict[str, Any] | None = None,
        auto_run: bool = False,
        skip_scope_check: bool = False,
    ) -> str:
        umo = event.unified_msg_origin
        if self.storage.load_active_task(umo):
            return "当前会话已有 active task。请先 /agentlab finish 或 /agentlab cancel。"

        spec = self.storage.get_agent(agent_id or None)
        if not spec.enabled:
            return "当前 AgentSpec 未启用。请先在 Agent Lab WebUI 启用后再进入 Agent Mode。"
        self._normalize_agent_workflow(spec)
        allowed, reason = self._workflow_scope_allows_event(spec, event)
        if not allowed:
            return f"当前工作流未在此会话范围启用：{reason}"
        runtime_identity = await self._current_bot_identity_for_event(event)
        effective_agent_name = (
            self._agent_name_from_label(runtime_identity["label"])
            if self._should_sync_agent_identity(spec)
            else spec.name
        )
        profile_agent = spec.to_dict()
        profile_agent["name"] = effective_agent_name
        profile_agent["runtime_identity"] = runtime_identity
        if spec.isolation_policy.mode == "off":
            session_plugin_snapshot = {}
        else:
            session_plugin_snapshot = await self.guard.apply_overrides(
                umo, self._effective_session_plugin_overrides(spec)
            )
        self._refresh_summarizer_rules()
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
            or list(spec.entry_policy.default_completion_conditions or ["用户验收通过"]),
            task_brief=entry_summary,
            entry_summary=entry_summary,
            current_summary=(
                f"任务由 {source} 创建，风险级别：{risk_level}。"
                f"工作流：{len(spec.workflow_nodes)} 个节点 / {len(spec.workflow_edges)} 条连线。"
            ),
            next_step="根据入口摘要制定第一轮执行计划，并推进一个有限工作单元。",
            profile_snapshot={
                "agent": profile_agent,
                "session_plugin_snapshot": session_plugin_snapshot,
                "restore_session_plugins": bool(spec.isolation_policy.restore_on_exit),
            },
            heartbeat=spec.heartbeat_policy,
        )
        self._initialize_task_workflow(task, spec, source=source)
        if trigger_payload:
            data = self._ensure_workflow_data(task)
            data["trigger_payload"] = trigger_payload
            data.setdefault("variables", {})["trigger_payload"] = trigger_payload
        self._sync_agent_runtime(task, spec, reason="created")
        self.agent_runtime.record_decision(
            task,
            phase="entry",
            action="create_task",
            node_id=task.workflow_current_node_id,
            reason=f"source={source}; risk={risk_level}; goal={goal}",
            capability="task.create",
            confidence="high",
        )
        self.agent_runtime.record_observation(
            task,
            source="entry_summary",
            node_id=task.workflow_current_node_id,
            payload={
                "entry_summary": entry_summary,
                "completion_conditions": task.completion_conditions,
            },
            summary=entry_summary,
        )
        self._sync_agent_runtime(task, spec, reason="created")
        runtime = task.workflow_data.get("agent_runtime") if isinstance(task.workflow_data, dict) else {}
        recommended_patterns = runtime.get("pattern_recommendations") if isinstance(runtime, dict) else []
        if isinstance(recommended_patterns, list) and recommended_patterns:
            self.agent_runtime.record_decision(
                task,
                phase="plan",
                action="recommend_task_patterns",
                node_id=task.workflow_current_node_id,
                reason=(
                    "matched="
                    + ",".join(str(item.get("pattern_id") or "") for item in recommended_patterns[:3] if isinstance(item, dict))
                ),
                capability="memory.pattern",
                confidence="medium",
            )
        task.add_log("created", f"goal={goal}; source={source}; risk={risk_level}")
        task.add_snapshot("created", {"source": source, "risk_level": risk_level})
        self.storage.save_task(task)
        heartbeat_text = ""
        if request_heartbeat and task.heartbeat.allowed:
            heartbeat_text = "\n" + await self._enable_heartbeat(
                event, task, reason="start_request"
            )
        runtime_text = ""
        if auto_run:
            self._budget_before_tick(task, source or "workflow_trigger")
            runtime_run = await self._run_workflow_runtime(
                event=event,
                task=task,
                spec=spec,
                reason=source or "workflow_trigger",
            )
            self.storage.save_task(task)
            if runtime_run.changed:
                runtime_text = f"\n- workflow_runtime: {self._compact_text(runtime_run.summary(), 500)}"
        return (
            f"已进入 Agent Mode。\n"
            f"- task_id: {task.task_id}\n"
            f"- agent: {effective_agent_name}\n"
            f"- 状态文件: {self.storage.task_markdown_path(umo, task.task_id)}\n"
            f"- 下一步: /agentlab tick\n"
            f"{runtime_text}"
            f"{heartbeat_text}"
        )

    async def _tick(self, event: AstrMessageEvent, reason: str) -> str:
        return (await self.service.run_tick(event, reason=reason)).message

    async def _tick_impl(self, event: AstrMessageEvent, reason: str) -> str:
        return await self.runtime_runner.run_tick(event, reason)

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
        finish_verdict = self.verifier.verify_finish(task, status=status, final_summary=final_summary)
        if not finish_verdict.passed:
            task.status = "paused"
            task.set_wait(
                wait_reason=finish_verdict.status or "need_user_decision",
                message=finish_verdict.reason,
                source="verifier_finish",
                required_input=finish_verdict.missing,
            )
            self.agent_runtime.record_verdict(
                task,
                node_id=task.workflow_current_node_id,
                passed=False,
                status=finish_verdict.status,
                reason=finish_verdict.reason,
                missing=finish_verdict.missing,
                next_action=finish_verdict.next_action,
            )
            self.storage.save_task(task)
            missing_text = "、".join(finish_verdict.missing or [])
            suffix = f"；缺少：{missing_text}" if missing_text else ""
            return f"暂不能完成任务：{finish_verdict.reason}{suffix}"
        self._refresh_summarizer_rules()
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
        task.add_snapshot("finished", {"status": status, "final_summary": final_summary})
        spec = AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
        )
        self._normalize_agent_workflow(spec)
        self._sync_agent_runtime(task, spec, reason="finish")
        self.agent_runtime.record_finish(
            task,
            status=status,
            summary=exit_summary or final_summary,
            memory_candidates=task.memory_candidates,
        )
        await self._disable_heartbeat(task)
        snapshot = task.profile_snapshot.get("session_plugin_snapshot")
        if bool(task.profile_snapshot.get("restore_session_plugins", True)):
            await self.guard.restore(task.umo, snapshot)
        task.archive_path = str(self.storage.archive_task_markdown_path(task.umo, task.task_id))
        memory_result = await self.memory_orchestrator.on_task_finish(
            task,
            spec,
            status=status,
            exit_summary=exit_summary,
        )
        if isinstance(task.workflow_data, dict):
            task.workflow_data["archive_evidence"] = memory_result.get("archive_evidence") or {}
            task.workflow_data["memory_orchestrator"] = {
                "candidate_count": memory_result.get("candidate_count", 0),
                "accepted_count": memory_result.get("accepted_count", 0),
                "rejected_count": memory_result.get("rejected_count", 0),
                "errors": memory_result.get("errors", []),
            }
        pattern = memory_result.get("pattern") if isinstance(memory_result, dict) else None
        if pattern:
            task.add_log("task_pattern", f"learned {pattern.get('pattern_id')}")
        for error in (memory_result.get("errors") or [])[:5]:
            task.add_log("memory_orchestrator_error", str(error))
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

    async def _rehydrate_workflow_schedules(self) -> None:
        if not self.context.cron_manager:
            return
        for spec in self.storage.list_agents():
            self._normalize_agent_workflow(spec)
            trigger = WorkflowTrigger.from_dict(self._as_plain_dict(getattr(spec, "workflow_trigger", None)))
            if not spec.enabled or not trigger.enabled:
                continue
            if "schedule" not in set(trigger.types or []) or not trigger.cron:
                continue
            if spec.agent_id in self._workflow_schedule_jobs:
                continue
            try:
                job = await self.context.cron_manager.add_basic_job(
                    name=f"agent_lab_workflow_{spec.agent_id}",
                    cron_expression=trigger.cron,
                    handler=self._workflow_schedule_tick,
                    payload={
                        "agent_id": spec.agent_id,
                        "source": "schedule",
                        "cron": trigger.cron,
                        "description": trigger.description,
                    },
                    persistent=False,
                    description=f"Agent Lab workflow schedule for {spec.name or spec.agent_id}",
                    enabled=True,
                )
                self._workflow_schedule_jobs[spec.agent_id] = job.job_id
                logger.info("[AgentLab] workflow schedule enabled for %s: %s", spec.agent_id, job.job_id)
            except Exception as exc:
                logger.warning("[AgentLab] cannot enable workflow schedule for %s: %s", spec.agent_id, exc)

    async def _disable_workflow_schedules(self) -> None:
        if not self.context.cron_manager:
            self._workflow_schedule_jobs.clear()
            return
        for agent_id, job_id in list(self._workflow_schedule_jobs.items()):
            try:
                await self.context.cron_manager.delete_job(job_id)
            except Exception:
                pass
            self._workflow_schedule_jobs.pop(agent_id, None)

    async def _workflow_schedule_tick(self, **payload) -> None:
        agent_id = str(payload.get("agent_id") or "").strip()
        spec = self.storage.get_agent(agent_id or None)
        trigger = WorkflowTrigger.from_dict(self._as_plain_dict(getattr(spec, "workflow_trigger", None)))
        umo = str(
            payload.get("umo")
            or f"aiocqhttp:FriendMessage:agent_lab_schedule_{agent_id}_{int(time.time() * 1000)}"
        ).strip()
        event = self._make_cron_event(umo, f"Agent Lab workflow schedule: {spec.name or agent_id}")
        if event is None:
            logger.warning("[AgentLab] workflow schedule skipped; cannot create event for %s", agent_id)
            return
        trigger_payload = self._build_trigger_payload(
            source="schedule",
            event=event,
            text=str(payload.get("description") or trigger.description or f"scheduled workflow {agent_id}"),
            data=dict(payload),
        )
        await self._trigger_workflow_from_payload(
            event=event,
            source="schedule",
            payload=trigger_payload,
            agent_id=agent_id,
        )

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
        if approved:
            task.clear_wait()
            if task.status == "paused":
                task.status = "running"
            task.watchdog.last_decision = "approval_approved"
        else:
            task.status = "paused"
            task.watchdog.last_decision = "approval_rejected"
            task.set_wait(
                wait_reason="need_user_decision",
                message=f"Approval rejected: {approval_id}. Revise the plan before continuing.",
                source="approval_resolved",
                required_input=[approval_id],
            )
        task.add_log("approval_resolved", f"{approval_id}: {'approved' if approved else 'rejected'}")
        spec = AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
        )
        self._normalize_agent_workflow(spec)
        self.agent_runtime.record_decision(
            task,
            phase="human",
            action="approval_resolved",
            node_id=task.workflow_current_node_id,
            reason=f"{approval_id}: {'approved' if approved else 'rejected'}",
            capability="human.approval",
            confidence="high",
        )
        self.agent_runtime.record_verdict(
            task,
            node_id=task.workflow_current_node_id,
            passed=approved,
            status="approved" if approved else "rejected",
            reason=f"User {'approved' if approved else 'rejected'} approval {approval_id}.",
            missing=[] if approved else [approval_id],
            next_action="resume_tick" if approved else "revise_plan",
        )
        self._sync_agent_runtime(task, spec, reason="approval_resolved")
        self.storage.save_task(task)
        return f"审批已{'通过' if approved else '拒绝'}：{approval_id}"

    def _build_toolset(self, spec: AgentSpec):
        tmgr = self.context.get_llm_tool_manager()
        internal_block = {"agent_lab_enter_mode", "agent_lab_tick"}
        essential = {
            "agent_lab_read_state",
            "agent_lab_read_runtime",
            "agent_lab_read_task_memory",
            "agent_lab_recommend_task_patterns",
            "agent_lab_update_state",
            "agent_lab_advance_workflow",
            "agent_lab_request_approval",
            "agent_lab_set_heartbeat",
            "agent_lab_finish",
            "agent_lab_update_workflow",
            "agent_lab_run_parallel_workflow",
        }
        disabled_plugins = self._disabled_plugin_names(spec)
        tool_mode = str(getattr(spec.isolation_policy, "tool_mode", "whitelist") or "whitelist")
        if tool_mode == "no_external" or NO_EXTERNAL_TOOLS_SENTINEL in set(spec.enabled_tools or []):
            from astrbot.core.agent.tool import ToolSet

            toolset = ToolSet()
            for name in essential:
                try:
                    tool = tmgr.get_func(name)
                except Exception:
                    tool = None
                if tool:
                    toolset.add_tool(tool)
            return toolset

        if tool_mode == "full" or not spec.enabled_tools:
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

    def _tool_allowed_by_agent_profile(self, spec: AgentSpec, tool_name: str) -> bool:
        return PermissionPolicy.tool_allowed_by_agent_profile(
            spec,
            tool_name,
            NO_EXTERNAL_TOOLS_SENTINEL,
        )

    def _workflow_runtime_view(self, task: TaskState) -> dict[str, Any]:
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
        self._normalize_agent_workflow(spec)
        current_id = task.workflow_current_node_id or self._workflow_entry_id(spec)
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        outgoing = self._workflow_outgoing(spec)
        current = node_map.get(current_id) or {}
        candidates = [node_map[node_id] for node_id in outgoing.get(current_id, []) if node_id in node_map]
        return {
            "current_node_id": current_id,
            "current_node": current,
            "next_candidates": candidates,
            "path": list(task.workflow_path or []),
            "events": list(task.workflow_events or [])[-12:],
        }

    def _workflow_runtime_text(self, task: TaskState) -> str:
        view = self._workflow_runtime_view(task)
        node = view.get("current_node") or {}
        candidates = view.get("next_candidates") or []
        candidate_text = ", ".join(
            f"{item.get('id')}({item.get('title') or item.get('action')})"
            for item in candidates[:6]
        ) or "-"
        return (
            f"current={view.get('current_node_id') or '-'} "
            f"[{node.get('stage') or '-'} / {node.get('action') or '-'} / {node.get('kind') or '-'}] "
            f"{node.get('title') or '-'}; next_candidates={candidate_text}; "
            f"path={' -> '.join(view.get('path') or []) or '-'}"
        )

    def _initialize_task_workflow(self, task: TaskState, spec: AgentSpec, source: str = "") -> None:
        self._normalize_agent_workflow(spec)
        self._ensure_workflow_data(task)
        entry_id = self._workflow_entry_id(spec)
        if not entry_id:
            return
        task.workflow_current_node_id = entry_id
        task.workflow_path = [entry_id]
        task.add_workflow_event(
            entry_id,
            status="entered",
            outcome="任务进入工作流。",
            note=f"source={source}" if source else "",
        )

    def _register_node_executors(self) -> None:
        for action in ("listen_message", "schedule_trigger", "plugin_event_trigger", "webhook_trigger"):
            self.node_executors.register(action, self._execute_trigger_node)
        for action in ("match_keyword", "match_regex", "llm_detect", "scope_filter"):
            self.node_executors.register(action, self._execute_detector_node)
        for action in ("summarize_entry", "confirm_entry", "restore_isolation"):
            self.node_executors.register(action, self._execute_entry_node)
        for action in (
            "save_state",
            "heartbeat",
            "transform_context",
            "variable_set",
            "variable_get",
            "text_template",
            "json_transform",
            "merge",
            "iterator",
            "subflow_call",
        ):
            self.node_executors.register(action, self._execute_state_node)
        self.node_executors.register("retrieve_memory", self._execute_retrieve_memory_node)
        self.node_executors.register("save_memory", self._execute_save_memory_node)
        self.node_executors.register("parallel_branch", self._execute_parallel_branch_node)
        self.node_executors.register("call_api", self._execute_api_node)
        self.node_executors.register("http_request", self._execute_http_request_node)
        self.node_executors.register("run_tools", self._execute_tool_node)
        self.node_executors.register("file_operation", self._execute_file_operation_node)
        self.node_executors.register("code_exec", self._execute_code_exec_node)
        self.node_executors.register("route_condition", self._execute_route_node)
        self.node_executors.register("conditional_router", self._execute_route_node)
        self.node_executors.register("retry", self._execute_retry_node)
        self.node_executors.register("limit_rate", self._execute_rate_limit_node)
        self.node_executors.register("catch_error", self._execute_catch_error_node)
        self.node_executors.register("validate_output", self._execute_validation_node)
        self.node_executors.register("debate_validation", self._execute_debate_validation_node)
        self.node_executors.register("request_approval", self._execute_approval_node)
        self.node_executors.register("wait_user", self._execute_wait_node)
        self.node_executors.register("handoff", self._execute_wait_node)
        self.node_executors.register("notify", self._execute_notify_node)
        self.node_executors.register("write_record", self._execute_record_node)
        self.node_executors.register("generate_report", self._execute_report_node)
        for action in ("send_message", "send_private_message", "send_email"):
            self.node_executors.register(action, self._execute_notify_node)
        self.node_executors.register("archive", self._execute_terminal_node)
        self.node_executors.register("exit_summary", self._execute_terminal_node)

    @staticmethod
    def _single_next(outgoing: list[str]) -> str:
        return outgoing[0] if len(outgoing) == 1 else ""

    def _task_lease_owner(self) -> str:
        return f"agent_lab:{id(self)}"

    def _lease_expired(self, expires_at: str) -> bool:
        stamp = self._parse_iso_datetime(expires_at)
        if stamp is None:
            return True
        return datetime.now(timezone.utc) >= stamp.astimezone(timezone.utc)

    def _acquire_task_lease(
        self,
        task: TaskState,
        *,
        reason: str,
        ttl_seconds: int | None = None,
    ) -> tuple[bool, str]:
        ttl = max(30, int(ttl_seconds or _cfg(self.config, "task_lease_ttl_seconds", 600) or 600))
        current = task.lease
        if current.token and not self._lease_expired(current.expires_at):
            owner = current.owner or "unknown"
            return False, f"任务正在由 {owner} 执行，lease 到期时间：{current.expires_at}"
        acquired = datetime.now(timezone.utc).astimezone()
        task.lease.owner = self._task_lease_owner()
        task.lease.token = new_id("lease")
        task.lease.acquired_at = acquired.isoformat(timespec="seconds")
        task.lease.expires_at = (acquired + timedelta(seconds=ttl)).isoformat(timespec="seconds")
        task.lease.reason = str(reason or "").strip()
        self.storage.save_task(task)
        return True, task.lease.token

    def _release_task_lease(self, task: TaskState, lease_token: str) -> None:
        if not lease_token or task.lease.token != lease_token:
            return
        task.lease.owner = ""
        task.lease.token = ""
        task.lease.acquired_at = ""
        task.lease.expires_at = ""
        task.lease.reason = ""

    def _configure_task_budget(self, task: TaskState) -> None:
        budget = task.budget
        config_defaults = {
            "max_nodes_per_tick": ("workflow_auto_steps_per_tick", 6),
            "max_tools_per_tick": ("max_steps_per_tick", 12),
            "max_seconds_per_tick": ("max_seconds_per_tick", 240),
            "max_tokens_per_tick": ("max_tokens_per_tick", 12000),
            "max_total_ticks": ("max_total_ticks", 120),
            "max_total_tool_calls": ("max_total_tool_calls", 240),
            "max_total_tokens": ("max_total_tokens", 240000),
        }
        for attr, (key, default) in config_defaults.items():
            current = int(getattr(budget, attr, 0) or 0)
            if current <= 0:
                setattr(budget, attr, int(_cfg(self.config, key, default) or default))

    def _budget_before_tick(self, task: TaskState, reason: str) -> str:
        self._configure_task_budget(task)
        budget = task.budget
        if budget.max_total_ticks and budget.ticks_used >= budget.max_total_ticks:
            return f"任务 tick 总预算已用尽：{budget.ticks_used}/{budget.max_total_ticks}"
        if budget.max_total_tool_calls and budget.tool_calls_used >= budget.max_total_tool_calls:
            return f"任务工具调用总预算已用尽：{budget.tool_calls_used}/{budget.max_total_tool_calls}"
        if budget.max_total_tokens and budget.tokens_used >= budget.max_total_tokens:
            return f"任务 token 总预算已用尽：{budget.tokens_used}/{budget.max_total_tokens}"
        budget.ticks_used += 1
        budget.tick_started_at = now_iso()
        data = self._ensure_workflow_data(task)
        data["tick_budget"] = {
            "reason": reason,
            "started_at": budget.tick_started_at,
            "nodes_used": 0,
            "tool_calls_used": 0,
            "tokens_used": 0,
            "max_nodes": max(1, int(budget.max_nodes_per_tick or 1)),
            "max_tools": max(1, int(budget.max_tools_per_tick or 1)),
            "max_seconds": max(1, int(budget.max_seconds_per_tick or 1)),
        }
        return ""

    def _budget_tick_payload(self, task: TaskState) -> dict[str, Any]:
        data = self._ensure_workflow_data(task)
        tick = data.setdefault("tick_budget", {})
        if not isinstance(tick, dict):
            tick = {}
            data["tick_budget"] = tick
        return tick

    def _budget_remaining_tools(self, task: TaskState) -> int:
        self._configure_task_budget(task)
        tick = self._budget_tick_payload(task)
        max_tools = int(tick.get("max_tools") or task.budget.max_tools_per_tick or 1)
        used = int(tick.get("tool_calls_used") or 0)
        total_remaining = max(0, int(task.budget.max_total_tool_calls or 0) - int(task.budget.tool_calls_used or 0))
        if task.budget.max_total_tool_calls <= 0:
            total_remaining = max_tools
        return max(0, min(max_tools - used, total_remaining))

    def _budget_elapsed_seconds(self, task: TaskState) -> int:
        tick = self._budget_tick_payload(task)
        started = self._parse_iso_datetime(str(tick.get("started_at") or task.budget.tick_started_at or ""))
        if started is None:
            return 0
        return max(0, int((datetime.now(timezone.utc) - started.astimezone(timezone.utc)).total_seconds()))

    def _consume_node_budget(self, task: TaskState, node: dict[str, Any]) -> str:
        self._configure_task_budget(task)
        tick = self._budget_tick_payload(task)
        tick["nodes_used"] = int(tick.get("nodes_used") or 0) + 1
        task.budget.nodes_used += 1
        max_nodes = int(tick.get("max_nodes") or task.budget.max_nodes_per_tick or 1)
        if tick["nodes_used"] > max_nodes:
            return f"本轮节点预算已用尽：{tick['nodes_used']}/{max_nodes}"
        max_seconds = int(tick.get("max_seconds") or task.budget.max_seconds_per_tick or 1)
        elapsed = self._budget_elapsed_seconds(task)
        if elapsed > max_seconds:
            return f"本轮时间预算已用尽：{elapsed}/{max_seconds}s"
        return ""

    def _consume_tool_budget(self, task: TaskState, tool_name: str = "") -> str:
        self._configure_task_budget(task)
        tick = self._budget_tick_payload(task)
        tick["tool_calls_used"] = int(tick.get("tool_calls_used") or 0) + 1
        task.budget.tool_calls_used += 1
        max_tools = int(tick.get("max_tools") or task.budget.max_tools_per_tick or 1)
        if tick["tool_calls_used"] > max_tools:
            return f"本轮工具预算已用尽：{tick['tool_calls_used']}/{max_tools}"
        if task.budget.max_total_tool_calls and task.budget.tool_calls_used > task.budget.max_total_tool_calls:
            return f"任务工具调用总预算已用尽：{task.budget.tool_calls_used}/{task.budget.max_total_tool_calls}"
        return ""

    def _consume_token_budget(self, task: TaskState, usage: Any) -> str:
        if not usage:
            return ""
        total = int(getattr(usage, "total", 0) or 0)
        if total <= 0:
            return ""
        tick = self._budget_tick_payload(task)
        tick["tokens_used"] = int(tick.get("tokens_used") or 0) + total
        task.budget.tokens_used += total
        if task.budget.max_tokens_per_tick and tick["tokens_used"] > task.budget.max_tokens_per_tick:
            return f"本轮 token 预算已用尽：{tick['tokens_used']}/{task.budget.max_tokens_per_tick}"
        if task.budget.max_total_tokens and task.budget.tokens_used > task.budget.max_total_tokens:
            return f"任务 token 总预算已用尽：{task.budget.tokens_used}/{task.budget.max_total_tokens}"
        return ""

    def _pause_task_for_budget(self, task: TaskState, reason: str) -> None:
        task.status = "paused"
        task.watchdog.last_decision = "paused_budget"
        task.set_wait(
            wait_reason="budget_exhausted",
            message=reason,
            source="budget",
            required_input=[reason],
        )
        task.add_blocker("budget_exhausted", reason)
        task.add_log("paused", reason)
        task.add_snapshot("budget_pause", {"reason": reason})
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_pause(
                task,
                reason=reason,
                node_id=task.workflow_current_node_id,
                missing=[reason],
            )

    def _watchdog_before_tick(self, task: TaskState, reason: str) -> str:
        task.watchdog.last_tick_at = now_iso()
        task.watchdog.last_tick_reason = str(reason or "").strip()
        if task.watchdog.paused_reason and task.status == "paused":
            return f"任务已暂停：{task.watchdog.paused_reason}"
        if task.pending_approvals():
            task.watchdog.last_decision = "waiting_approval"
            approval = task.pending_approvals()[0]
            task.set_wait(
                wait_reason="need_approval",
                message=f"waiting for approval: {approval.operation}",
                source="watchdog",
                resume_command=f"/agentlab approve {approval.approval_id}",
                required_input=[approval.operation],
            )
            return "任务正在等待审批，不能由心跳继续推进。"
        budget_reason = self._budget_before_tick(task, reason)
        if budget_reason:
            self._pause_task_for_budget(task, budget_reason)
            return budget_reason
        self._prepare_resume_anchor(task, reason=reason)
        return ""

    def _watchdog_after_tick(
        self,
        task: TaskState,
        *,
        before_hash: str,
        reason: str,
        error: str = "",
    ) -> None:
        current_hash = self._progress_hash(task)
        progressed = bool(current_hash and current_hash != before_hash)
        task.watchdog.last_tick_at = now_iso()
        task.watchdog.last_tick_reason = str(reason or "").strip()
        if error:
            task.watchdog.consecutive_failures += 1
            task.watchdog.last_error = error
            task.watchdog.last_decision = "error"
            if task.watchdog.consecutive_failures >= int(task.heartbeat.max_repeated_failures or 3):
                task.status = "paused"
                task.set_wait(
                    wait_reason="blocked_by_error",
                    message=f"连续失败 {task.watchdog.consecutive_failures} 次：{error}",
                    source="watchdog_error",
                    required_input=[error],
                )
            self._prepare_resume_anchor(task, reason=reason)
            return
        if progressed:
            task.watchdog.consecutive_failures = 0
            task.watchdog.last_error = ""
            task.watchdog.last_progress_at = now_iso()
            task.watchdog.last_progress_hash = current_hash
            task.watchdog.last_decision = "continue" if task.status == "running" else task.status
        else:
            task.watchdog.consecutive_failures += 1
            task.watchdog.last_error = "no_progress"
            task.watchdog.last_decision = "no_progress"
            if task.watchdog.consecutive_failures >= int(task.heartbeat.max_repeated_failures or 3):
                task.status = "paused"
                task.set_wait(
                    wait_reason="blocked_by_error",
                    message="连续 tick 没有产生新 observation 或 workflow 进展。",
                    source="watchdog_no_progress",
                    required_input=["new_observation_or_workflow_progress"],
                )
        self._prepare_resume_anchor(task, reason=reason)

    def _prepare_resume_anchor(self, task: TaskState, *, reason: str = "") -> None:
        data = self._ensure_workflow_data(task)
        node_outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        node_output_items = list(node_outputs.items())[-12:] if isinstance(node_outputs, dict) else []
        data["resume"] = {
            "task_id": task.task_id,
            "updated_at": now_iso(),
            "reason": reason,
            "workflow_current_node_id": task.workflow_current_node_id,
            "workflow_path_tail": list(task.workflow_path or [])[-12:],
            "last_observation": task.last_observation,
            "node_outputs": {key: value for key, value in node_output_items},
            "node_output_ids": list((node_outputs or {}).keys())[-40:],
            "variable_names": list((data.get("variables") or {}).keys())[-40:],
        }
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.update_resume(task, reason=reason)

    def _progress_hash(self, task: TaskState) -> str:
        data = self._ensure_workflow_data(task)
        payload = {
            "status": task.status,
            "node": task.workflow_current_node_id,
            "path": list(task.workflow_path or [])[-12:],
            "events": list(task.workflow_events or [])[-8:],
            "observation": task.last_observation,
            "summary": task.current_summary,
            "progress": task.last_confirmed_progress,
            "node_outputs": list((data.get("node_outputs") or {}).keys())[-16:],
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_iso_datetime(raw: str) -> datetime | None:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            stamp = datetime.fromisoformat(text)
        except Exception:
            return None
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp

    def _condition_context(self, task: TaskState) -> dict[str, Any]:
        data = self._ensure_workflow_data(task)
        variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
        node_outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        observations = data.get("observations") if isinstance(data.get("observations"), list) else []
        last_observation: Any = task.last_observation
        if isinstance(last_observation, str) and last_observation.strip().startswith(("{", "[")):
            try:
                last_observation = json.loads(last_observation)
            except Exception:
                pass
        context = {
            "task": task.to_dict(),
            "variables": variables,
            "node_outputs": node_outputs,
            "observations": observations,
            "last_observation": last_observation,
            "memory": variables.get("memory") or variables.get("memory_result") or {},
            "api_result": variables.get("api_result") or {},
            "tool_result": variables.get("tool_result") or {},
            "validation": variables.get("validation") or {},
        }
        for key, value in variables.items():
            context.setdefault(str(key), value)
        return context

    def _node_schema(self, node: dict[str, Any], key: str) -> dict[str, Any]:
        raw = node.get(key)
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _validate_node_input_schema(self, task: TaskState, node: dict[str, Any]) -> str:
        required_inputs = node.get("required_inputs") if isinstance(node.get("required_inputs"), list) else []
        if required_inputs:
            context = self._condition_context(task)
            missing = [
                str(path)
                for path in required_inputs
                if str(path).strip() and resolve_path(context, str(path).strip(), None) is None
            ]
            if missing:
                return f"Node required input missing: {', '.join(missing[:8])}"
        input_schema = self._node_schema(node, "input_schema")
        if not input_schema:
            return ""
        input_variable = str(node.get("input_variable") or "").strip()
        if not input_variable:
            return ""
        value = self._node_payload_from_variable(task, node)
        return self._schema_validation_message(input_schema, value, f"Node input {input_variable}")

    def _validate_node_output_schema(self, node: dict[str, Any], result: NodeExecutionResult) -> str:
        output_schema = self._node_schema(node, "output_schema")
        if not output_schema:
            return ""
        return self._schema_validation_message(output_schema, result.data, f"Node output {node.get('id') or '-'}")

    def _schema_validation_message(
        self,
        schema: dict[str, Any] | None,
        value: Any,
        subject: str,
    ) -> str:
        errors = schema_validation_errors(schema, value)
        if not errors:
            return ""
        details = "; ".join(errors[:6])
        if len(errors) > 6:
            details += f"; ... {len(errors) - 6} more"
        return f"{subject} schema mismatch: {details}"

    def _workflow_edges_from(self, spec: AgentSpec, node_id: str) -> list[dict[str, Any]]:
        start = str(node_id or "").strip()
        return [
            edge
            for edge in (spec.workflow_edges or [])
            if isinstance(edge, dict) and str(edge.get("from") or "").strip() == start
        ]

    def _workflow_success_edges(self, spec: AgentSpec, node_id: str) -> list[dict[str, Any]]:
        return [
            edge
            for edge in self._workflow_edges_from(spec, node_id)
            if str(edge.get("edge_type") or "success").strip().lower() in {"success", "always"}
        ]

    def _workflow_edges_for_result(
        self,
        task: TaskState,
        spec: AgentSpec,
        node_id: str,
        result: NodeExecutionResult | None,
    ) -> list[dict[str, Any]]:
        route = ""
        if result and isinstance(result.data, dict):
            route = str(result.data.get("route") or result.data.get("edge_type") or "").strip().lower()
        if not route and result:
            note = str(result.note or "").strip().lower()
            if note == "node_executor_timeout":
                route = "timeout"
            elif result.blocked or not result.ok or result.status == "blocked":
                route = str(result.status or "error").strip().lower()
            else:
                route = str(result.status or "success").strip().lower()
        if route in {"completed", "complete", "matched", "passed", "ok", "true"}:
            route = "success"
        elif route in {"unmatched", "not_matched", "not_passed", "false"}:
            route = "failed"
        elif route in {"blocked", "exception"}:
            route = "error"
        elif not route:
            route = "success"

        desired = {route, "always"}
        if result and (not result.ok or result.blocked or result.status == "blocked"):
            desired.update({"failed", "error"})
        elif route == "failed":
            desired.add("error")
        elif route == "error":
            desired.add("failed")
        edges: list[dict[str, Any]] = []
        context = self._condition_context(task)
        for edge in self._workflow_edges_from(spec, node_id):
            edge_type = str(edge.get("edge_type") or "success").strip().lower()
            if edge_type not in desired:
                continue
            condition = str(edge.get("condition") or "").strip()
            if condition:
                verdict = evaluate_condition(condition, context)
                if verdict is not True:
                    continue
            edges.append(edge)
        return edges

    def _candidate_nodes_from_edges(
        self,
        nodes: dict[str, dict[str, Any]],
        edges: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        for edge in edges:
            node_id = str(edge.get("to") or "").strip()
            node = nodes.get(node_id)
            if not node:
                continue
            item = dict(node)
            if edge.get("condition") and not item.get("condition"):
                item["condition"] = edge.get("condition")
            if edge.get("condition_visual") is not None:
                item["condition_visual"] = edge.get("condition_visual")
            item["edge_type"] = str(edge.get("edge_type") or "success")
            candidates.append(item)
        return candidates

    def _select_next_node_after_result(
        self,
        task: TaskState,
        spec: AgentSpec,
        node_id: str,
        result: NodeExecutionResult,
    ) -> str:
        nodes = self.workflow_runtime.node_map(spec)
        requested = str(result.next_node_id or "").strip()
        allowed = {str(edge.get("to") or "").strip() for edge in self._workflow_edges_from(spec, node_id)}
        if requested and requested in nodes and (not allowed or requested in allowed):
            return requested
        edges = self._workflow_edges_for_result(task, spec, node_id, result)
        if not edges:
            return ""
        candidates = self._candidate_nodes_from_edges(nodes, edges)
        if len(candidates) == 1:
            return str(candidates[0].get("id") or "")
        return self._route_target_from_node(
            task,
            {"id": node_id, "action": "route_condition"},
            [str(edge.get("to") or "") for edge in edges],
            candidates,
        )

    async def _execute_node_with_policy(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        retry_policy = ctx.node.get("retry_policy") if isinstance(ctx.node.get("retry_policy"), dict) else {}
        try:
            max_attempts = max(1, min(int(retry_policy.get("max_attempts") or 1), 8))
        except Exception:
            max_attempts = 1
        backoff = str(retry_policy.get("backoff") or "none").strip().lower()
        if backoff not in {"none", "linear", "exponential"}:
            backoff = "none"
        try:
            timeout_seconds = int(ctx.node.get("timeout_seconds") or 0)
        except Exception:
            timeout_seconds = 0
        timeout_seconds = max(0, min(timeout_seconds, 600))
        last_result: NodeExecutionResult | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                coro = self.node_executors.execute(ctx)
                result = await asyncio.wait_for(coro, timeout=timeout_seconds) if timeout_seconds else await coro
            except asyncio.TimeoutError:
                result = NodeExecutionResult(
                    node_id=str(ctx.node.get("id") or ""),
                    ok=False,
                    status="blocked",
                    outcome=f"Node timed out after {timeout_seconds}s.",
                    blocked=True,
                    advance=False,
                    note="node_executor_timeout",
                )
            except Exception as exc:
                result = NodeExecutionResult(
                    node_id=str(ctx.node.get("id") or ""),
                    ok=False,
                    status="blocked",
                    outcome=f"{type(exc).__name__}: {exc}",
                    blocked=True,
                    advance=False,
                    note="node_executor_error",
                )
            result.attempts = attempt
            last_result = result
            if result.ok and not result.blocked:
                break
            if attempt >= max_attempts:
                break
            data = self._ensure_workflow_data(ctx.task)
            retries = data.setdefault("node_retries", [])
            if isinstance(retries, list):
                retries.append(
                    {
                        "time": now_iso(),
                        "node_id": str(ctx.node.get("id") or ""),
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "reason": result.outcome or result.note,
                    }
                )
                data["node_retries"] = retries[-80:]
            delay = 0.0
            if backoff == "linear":
                delay = min(2.0, 0.2 * attempt)
            elif backoff == "exponential":
                delay = min(3.0, 0.2 * (2 ** (attempt - 1)))
            if delay:
                await asyncio.sleep(delay)
        return last_result or NodeExecutionResult(
            node_id=str(ctx.node.get("id") or ""),
            ok=False,
            status="blocked",
            outcome="Node executor did not produce a result.",
            blocked=True,
            advance=False,
            note="node_executor_missing_result",
        )

    def _loop_guard_before_node(self, task: TaskState, node: dict[str, Any]) -> str:
        data = self._ensure_workflow_data(task)
        guard = data.setdefault("loop_guard", {})
        if not isinstance(guard, dict):
            guard = {}
            data["loop_guard"] = guard
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            return ""
        counts = data.get("execution_counts") if isinstance(data.get("execution_counts"), dict) else {}
        max_repeats = max(
            2,
            min(int(node.get("max_repeats") or task.heartbeat.max_repeated_failures or 3), 12),
        )
        current = int(counts.get(node_id, 0) or 0)
        if current >= max_repeats and str(node.get("action") or "") not in {"wait_user", "handoff"}:
            reason = f"Loop guard stopped repeated node {node_id}: {current}/{max_repeats}"
            guard["last_stop"] = {"time": now_iso(), "node_id": node_id, "reason": reason}
            task.status = "paused"
            task.set_wait(
                wait_reason="blocked_by_error",
                message=reason,
                source="loop_guard",
                required_input=[reason],
            )
            task.add_blocker("loop_guard", reason)
            return reason
        return ""

    def _loop_guard_after_node(
        self,
        task: TaskState,
        node: dict[str, Any],
        result: NodeExecutionResult,
    ) -> str:
        data = self._ensure_workflow_data(task)
        guard = data.setdefault("loop_guard", {})
        if not isinstance(guard, dict):
            guard = {}
            data["loop_guard"] = guard
        signature = "|".join(
            [
                str(node.get("id") or ""),
                str(node.get("action") or ""),
                str(result.note or ""),
                self._compact_text(result.outcome or "", 160),
            ]
        )
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        repeats = guard.setdefault("result_repeats", {})
        repeats[digest] = int(repeats.get(digest, 0) or 0) + 1
        max_repeats = max(2, min(int(node.get("max_error_repeats") or task.heartbeat.max_repeated_failures or 3), 12))
        if (not result.ok or result.blocked) and repeats[digest] >= max_repeats:
            reason = f"Loop guard stopped repeated result at {node.get('id')}: {result.note or result.outcome}"
            guard["last_stop"] = {"time": now_iso(), "node_id": node.get("id") or "", "reason": reason}
            task.status = "paused"
            task.set_wait(
                wait_reason="blocked_by_error",
                message=reason,
                source="loop_guard",
                required_input=[reason],
            )
            task.add_blocker("loop_guard", reason)
            return reason
        return ""

    def _tool_schema(self, tool: Any = None, name: str = "", description: str = "") -> dict[str, Any]:
        schema = None
        if tool is not None:
            for attr in ("parameters", "parameters_schema", "schema", "args_schema"):
                value = getattr(tool, attr, None)
                if value:
                    if callable(value) and attr == "schema":
                        try:
                            value = value()
                        except Exception:
                            pass
                    schema = value
                    break
        for method_name in ("model_json_schema", "schema"):
            method = getattr(schema, method_name, None)
            if callable(method):
                try:
                    schema = method()
                    break
                except Exception:
                    pass
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except Exception:
                schema = None
        if isinstance(schema, dict):
            return schema
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
            "description": description or (getattr(tool, "description", "") if tool is not None else ""),
        }

    @staticmethod
    def _infer_capability(name: str, description: str = "", module_path: str = "") -> str:
        text = f"{name} {description} {module_path}".lower()
        buckets = [
            ("memory", ("memory", "memo", "note", "diary", "journal", "recall", "remember", "记忆", "日记", "笔记")),
            ("search", ("search", "query", "grok", "grep", "find", "检索", "搜索", "查询")),
            ("file", ("file", "path", "read", "write", "edit", "document", "文件", "目录")),
            ("web", ("web", "http", "url", "browser", "crawl", "网页", "联网")),
            ("database", ("database", "sql", "db", "table", "数据库")),
            ("image", ("image", "photo", "vision", "draw", "图片", "图像")),
            ("code", ("code", "python", "shell", "terminal", "execute", "代码", "命令")),
            ("api", ("api", "post", "request", "endpoint", "接口")),
        ]
        for capability, keywords in buckets:
            if any(keyword in text for keyword in keywords):
                return capability
        return "unknown"

    def _permission_allows_tool(
        self,
        node: dict[str, Any],
        *,
        capability: str,
        risk: str,
    ) -> bool:
        return PermissionPolicy.permission_allows_tool(node, capability=capability, risk=risk)

    @staticmethod
    def _permission_profiles_for(capability: str, risk: str) -> list[str]:
        return PermissionPolicy.permission_profiles_for(capability, risk)

    def _ensure_workflow_data(self, task: TaskState) -> dict[str, Any]:
        data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        data.setdefault("node_outputs", {})
        data.setdefault("variables", {})
        data.setdefault("react_traces", [])
        data.setdefault("execution_counts", {})
        data.setdefault("observations", [])
        data.setdefault("loop_guard", {})
        data.setdefault("resume", {})
        task.workflow_data = data
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.ensure(task)
        return data

    def _runtime_capability_rows(self, spec: AgentSpec) -> list[dict[str, Any]]:
        selected = set(spec.enabled_tools or [])
        rows = []
        for row in self._tool_rows():
            name = str(row.get("name") or "")
            if not name or name == NO_EXTERNAL_TOOLS_SENTINEL:
                continue
            if not self._tool_allowed_by_runtime_profile(spec, name):
                continue
            risk = self._effective_tool_risk(spec, name, str(row.get("risk") or "work"))
            rows.append(
                {
                    "name": name,
                    "capability": row.get("capability") or AgentRuntime.capability_for_tool_name(name),
                    "risk": risk,
                    "source": row.get("source") or row.get("plugin_name") or "registered",
                    "available": bool(row.get("effective_active", row.get("active", True))),
                    "side_effect": risk != "safe",
                    "requires_approval": AgentRuntime.requires_approval_for_tool(name, risk, spec),
                    "retryable": risk != "high",
                    "result_parser": "json_or_text",
                    "input_schema": row.get("input_schema") if isinstance(row.get("input_schema"), dict) else {},
                    "output_schema": row.get("output_schema") if isinstance(row.get("output_schema"), dict) else {},
                }
            )
        for builtin_name, capability, risk, description in (
            ("agent_lab_read_state", "task.read", "safe", "Read task state."),
            ("agent_lab_read_runtime", "runtime.read", "safe", "Read Agent Runtime state."),
            ("agent_lab_update_state", "task.write", "work", "Update task state."),
            ("agent_lab_advance_workflow", "workflow.control", "safe", "Advance workflow cursor."),
            ("agent_lab_request_approval", "human.approval", "safe", "Request user approval."),
            ("agent_lab_read_task_memory", "memory.read", "safe", "Read task memory."),
            ("agent_lab_recommend_task_patterns", "memory.pattern", "safe", "Recommend learned task plan patterns."),
            ("agent_lab_call_custom_api", "api.call", "work", "Call registered custom API."),
            ("agent_lab_run_parallel_workflow", "worker.parallel", "work", "Run parallel workflow workers."),
            ("agent_lab_set_heartbeat", "task.heartbeat", "work", "Toggle heartbeat."),
            ("agent_lab_finish", "task.finish", "work", "Archive task."),
        ):
            effective_risk = self._effective_tool_risk(spec, builtin_name, risk)
            rows.append(
                {
                    "name": builtin_name,
                    "capability": capability,
                    "risk": effective_risk,
                    "source": "agent_lab",
                    "available": builtin_name in selected or builtin_name.startswith("agent_lab_"),
                    "side_effect": effective_risk != "safe",
                    "requires_approval": AgentRuntime.requires_approval_for_tool(builtin_name, effective_risk, spec),
                    "retryable": effective_risk != "high",
                    "result_parser": "json_or_text",
                    "input_schema": {"type": "object", "properties": {}, "additionalProperties": True},
                    "output_schema": {"type": "object", "description": description},
                }
            )
        if self._tool_allowed_by_runtime_profile(spec, CUSTOM_API_TOOL_NAME):
            for api in self.storage.list_custom_apis():
                api_id = str(api.get("api_id") or "").strip()
                if not api_id:
                    continue
                method = str(api.get("method") or "GET").upper()
                auth_type = str(api.get("auth_type") or "none").strip().lower()
                risk = self._effective_tool_risk(spec, CUSTOM_API_TOOL_NAME, "work")
                rows.append(
                    {
                        "name": f"api:{api_id}",
                        "capability": "api.call",
                        "risk": risk,
                        "source": "custom_api_registry",
                        "description": str(api.get("description") or api.get("name") or api_id).strip(),
                        "target": api_id,
                        "available": bool(api.get("url")),
                        "side_effect": method not in {"GET", "HEAD", "OPTIONS"},
                        "requires_approval": AgentRuntime.requires_approval_for_tool(CUSTOM_API_TOOL_NAME, risk, spec),
                        "retryable": method in {"GET", "HEAD", "OPTIONS"},
                        "result_parser": "http_json_or_text",
                        "input_schema": {
                            "type": "object",
                            "properties": {
                                "api_id": {"type": "string", "const": api_id},
                                "query": {"type": "object"},
                                "body": {},
                                "headers": {"type": "object"},
                            },
                            "required": ["api_id"],
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {
                                "ok": {"type": "boolean"},
                                "status": {"type": "integer"},
                                "content_type": {"type": "string"},
                                "body": {},
                                "truncated": {"type": "boolean"},
                            },
                        },
                        "metadata": {
                            "api_id": api_id,
                            "name": str(api.get("name") or api_id),
                            "method": method,
                            "url_host": self._safe_url_host(str(api.get("url") or "")),
                            "auth_type": auth_type if auth_type in {"none", "off", "disabled"} else "configured",
                            "credential_configured": bool(api.get("credential_id")),
                            "timeout_seconds": int(api.get("timeout_seconds") or 30),
                        },
                    }
                )
        return rows

    @staticmethod
    def _safe_url_host(url: str) -> str:
        try:
            from urllib import parse as urlparse

            parsed = urlparse.urlsplit(str(url or ""))
            if not parsed.scheme or not parsed.netloc:
                return ""
            return f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return ""

    def _tool_allowed_by_runtime_profile(self, spec: AgentSpec, tool_name: str) -> bool:
        name = str(tool_name or "").strip()
        if not name or name in {"agent_lab_enter_mode", "agent_lab_tick"}:
            return False
        selected = set(spec.enabled_tools or [])
        tool_mode = str(getattr(spec.isolation_policy, "tool_mode", "whitelist") or "whitelist")
        if name.startswith("agent_lab_"):
            return True
        if tool_mode == "no_external" or NO_EXTERNAL_TOOLS_SENTINEL in selected:
            return False
        return tool_mode == "full" or not selected or name in selected

    def _sync_agent_runtime(self, task: TaskState, spec: AgentSpec, *, reason: str = "sync") -> None:
        self._ensure_workflow_data(task)
        self.agent_runtime.sync(
            task,
            spec,
            capabilities=self._runtime_capability_rows(spec),
            reason=reason,
        )
        self._sync_task_pattern_recommendations(task)

    def _sync_task_pattern_recommendations(self, task: TaskState) -> None:
        runtime = self.agent_runtime.ensure(task)
        rows = self.pattern_library.recommend(
            task.root_goal or task.current_summary or task.next_step,
            limit=3,
            exclude_task_id=task.task_id,
        )
        runtime["pattern_recommendations"] = [
            self.pattern_library.compact_for_runtime(row)
            for row in rows
        ]
        runtime["pattern_recommendations_updated_at"] = now_iso()

    def _workflow_variable(self, task: TaskState, name: str, default: Any = None) -> Any:
        data = self._ensure_workflow_data(task)
        variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
        key = str(name or "").strip()
        if key in variables:
            return variables.get(key, default)
        resolved = resolve_path(variables, key, None)
        return default if resolved is None else resolved

    def _set_workflow_variable(self, task: TaskState, name: str, value: Any) -> None:
        key = str(name or "").strip()
        if not key:
            return
        data = self._ensure_workflow_data(task)
        variables = data.setdefault("variables", {})
        if not isinstance(variables, dict):
            variables = {}
            data["variables"] = variables
        variables[key] = value
        parts = [part.strip() for part in key.split(".") if part.strip()]
        if len(parts) > 1:
            current = variables
            for part in parts[:-1]:
                child = current.get(part)
                if not isinstance(child, dict):
                    child = {}
                    current[part] = child
                current = child
            current[parts[-1]] = value

    def _record_node_execution(
        self,
        task: TaskState,
        node: dict[str, Any],
        result: NodeExecutionResult,
    ) -> None:
        data = self._ensure_workflow_data(task)
        node_id = str(result.node_id or node.get("id") or "").strip()
        if not node_id:
            return
        counts = data.setdefault("execution_counts", {})
        counts[node_id] = int(counts.get(node_id, 0) or 0) + 1
        payload = {
            "time": now_iso(),
            "node_id": node_id,
            "title": node.get("title") or node_id,
            "runtime_type": node.get("runtime_type") or NodeExecutorRegistry.runtime_type(node),
            "action": node.get("action") or "",
            "execution_mode": node.get("execution_mode") or NodeExecutorRegistry.execution_mode(node),
            "status": result.status,
            "ok": result.ok,
            "outcome": result.outcome,
            "note": result.note,
            "next_node_id": result.next_node_id,
            "attempts": result.attempts,
            "data": result.data,
        }
        data.setdefault("node_outputs", {})[node_id] = payload
        tool_outputs = data.setdefault("tool_outputs", {})
        if isinstance(tool_outputs, dict) and (payload.get("runtime_type") in {"tool", "api"} or payload.get("action") in {"run_tools", "call_api", "http_request", "file_operation", "code_exec"}):
            tool_outputs[node_id] = {
                "tool": (result.data or {}).get("tool_name") or (result.data or {}).get("api_id") or payload.get("action"),
                "input": node.get("tool_args") or node.get("api_payload") or node.get("input_variable") or "",
                "output": result.outcome,
                "parsed": result.data,
            }
        output_variable = str(
            node.get("output_variable")
            or node.get("variable")
            or node.get("output")
            or ""
        ).strip()
        if output_variable:
            self._set_workflow_variable(task, output_variable, result.data or result.outcome)
        output_variables = node.get("output_variables") if isinstance(node.get("output_variables"), list) else []
        for name in output_variables:
            self._set_workflow_variable(task, str(name), result.data or result.outcome)
        task.last_observation = self._compact_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            4000,
        )
        try:
            self.storage.upsert_task_memory_artifact(task, node_id, payload)
        except Exception:
            pass
        self._record_explicit_observation(
            task,
            source="node_executor",
            node_id=node_id,
            payload=payload,
        )
        if hasattr(self, "agent_runtime"):
            if result.ok and not result.blocked and result.status == "completed":
                self.agent_runtime.mark_current(task, completed_node_id=node_id)
            verification = self.verifier.verify_node_result(node=node, result=result)
            self.agent_runtime.record_verdict(
                task,
                node_id=node_id,
                passed=verification.passed,
                status=verification.status,
                reason=verification.reason,
                missing=verification.missing,
                next_action=verification.next_action,
            )
        self._prepare_resume_anchor(task, reason=f"node:{node_id}")

    def _record_explicit_observation(
        self,
        task: TaskState,
        *,
        source: str,
        node_id: str = "",
        payload: Any = None,
    ) -> None:
        data = self._ensure_workflow_data(task)
        observations = data.setdefault("observations", [])
        if not isinstance(observations, list):
            observations = []
        observations.append(
            {
                "time": now_iso(),
                "source": str(source or "runtime"),
                "node_id": str(node_id or task.workflow_current_node_id or ""),
                "payload": payload,
            }
        )
        data["observations"] = observations[-160:]
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_observation(
                task,
                source=source,
                node_id=node_id or task.workflow_current_node_id,
                payload=payload,
                summary=payload,
            )

    def _record_react_trace(
        self,
        task: TaskState,
        *,
        node_id: str,
        prompt: str,
        response: str,
        reason: str,
    ) -> None:
        data = self._ensure_workflow_data(task)
        traces = data.setdefault("react_traces", [])
        current_node = str(node_id or task.workflow_current_node_id or "").strip()
        data_snapshot = {
            "node_id": current_node,
            "goal": self._compact_text(task.root_goal, 500),
            "action_summary": self._compact_text(response, 700),
            "observation": self._compact_text(task.last_observation, 700),
            "next_decision": self._compact_text(task.next_step, 500),
        }
        traces.append(
            {
                "time": now_iso(),
                "node_id": current_node,
                "reason": reason,
                "response": data_snapshot["action_summary"],
                **data_snapshot,
            }
        )
        data["react_traces"] = traces[-80:]
        if hasattr(self, "agent_runtime"):
            decision = self.agent_runtime.record_decision(
                task,
                phase="react",
                action="react_handoff",
                node_id=current_node,
                reason=reason,
                capability="llm.reason",
            )
            self.agent_runtime.record_observation(
                task,
                source="react",
                node_id=current_node,
                decision_id=decision.get("decision_id", ""),
                payload=data_snapshot,
                summary=response,
            )
            self.agent_runtime.update_resume(task, reason=f"react:{reason}")

    def _memory_entry_visible(
        self,
        item: dict[str, Any],
        *,
        umo: str = "",
        active_task: TaskState | None = None,
        allow_private: bool = False,
    ) -> tuple[bool, bool]:
        layer = str(item.get("layer") or "").strip()
        exposed = bool(item.get("expose_to_normal", False))
        status = str(item.get("status") or "candidate").strip().lower()
        source_umo = str(item.get("source_umo") or "")
        source_task_id = str(item.get("source_task_id") or "")
        same_scope = bool(
            allow_private
            and (
                (source_umo and source_umo == umo)
                or (active_task is not None and source_task_id == active_task.task_id)
            )
        )
        if layer in {"private_task_memory", "candidate_memory"}:
            return same_scope, same_scope
        if layer in {"accepted_memory", "archive_summary"}:
            return status == "accepted" and exposed, False
        if exposed and status == "accepted":
            return True, False
        return same_scope, same_scope

    def _memory_entry_row(
        self,
        item: dict[str, Any],
        *,
        include_text: bool = True,
        text_limit: int = 0,
    ) -> dict[str, Any]:
        text = str(item.get("text") or "")
        if text_limit > 0:
            text = self._compact_text(text, text_limit)
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        row = {
            "memory_id": item.get("memory_id"),
            "layer": item.get("layer") or "",
            "status": str(item.get("status") or "candidate").strip().lower(),
            "kind": item.get("kind") or "",
            "tags": item.get("tags") or [],
            "source_task_id": item.get("source_task_id") or "",
            "source_umo": item.get("source_umo") or "",
            "updated_at": item.get("updated_at") or "",
            "evidence": {
                "memory_id": evidence.get("memory_id") or item.get("memory_id") or "",
                "source_task_id": evidence.get("source_task_id") or item.get("source_task_id") or "",
                "source_umo": evidence.get("source_umo") or item.get("source_umo") or "",
                "kind": evidence.get("kind") or item.get("kind") or "",
                "layer": evidence.get("layer") or item.get("layer") or "",
            },
        }
        if include_text:
            row["text"] = text
        return row

    @staticmethod
    def _memory_similarity_score(query: str, haystack: str) -> int:
        needle = str(query or "").strip().lower()
        text = str(haystack or "").strip().lower()
        if not needle:
            return 1
        if needle in text:
            return 1000 + len(needle)
        query_terms = {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", needle)
            if len(token) >= 2
        }
        if not query_terms:
            return 0
        text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", text))
        score = sum(3 for token in query_terms if token in text_terms)
        score += sum(1 for token in query_terms if token in text)
        return score

    def _node_result_to_decision(
        self,
        node: dict[str, Any],
        result: NodeExecutionResult,
    ) -> WorkflowDecision:
        return WorkflowDecision(
            node_id=result.node_id or str(node.get("id") or ""),
            node=node,
            next_node_id=result.next_node_id,
            status=result.status,
            outcome=result.outcome,
            note=result.note,
            needs_react=result.needs_react,
            terminal=result.terminal,
            blocked=result.blocked,
        )

    def _resolve_workflow_template(self, task: TaskState, value: Any) -> Any:
        context = self._condition_context(task)
        if isinstance(value, dict):
            return {key: self._resolve_workflow_template(task, item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_workflow_template(task, item) for item in value]
        if not isinstance(value, str):
            return value
        text = value.strip()
        whole = re.fullmatch(r"(?:\{\{\s*([^{}]+?)\s*\}\}|\$\{\s*([^{}]+?)\s*\})", text)
        if whole:
            path = (whole.group(1) or whole.group(2) or "").strip()
            resolved = resolve_path(context, path, None)
            return resolved if resolved is not None else ""

        def replace(match: re.Match[str]) -> str:
            path = (match.group(1) or match.group(2) or "").strip()
            resolved = resolve_path(context, path, None)
            if resolved is None:
                return ""
            if isinstance(resolved, str):
                return resolved
            return json.dumps(resolved, ensure_ascii=False, default=str)

        return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}|\$\{\s*([^{}]+?)\s*\}", replace, value)

    def _node_json_object(self, node: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            raw = node.get(key)
            if raw in (None, ""):
                continue
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {}

    def _node_templated_json_object(self, task: TaskState, node: dict[str, Any], *keys: str) -> dict[str, Any]:
        payload = self._node_json_object(node, *keys)
        resolved = self._resolve_workflow_template(task, payload)
        return resolved if isinstance(resolved, dict) else {}

    def _node_payload_from_variable(self, task: TaskState, node: dict[str, Any]) -> Any:
        input_variable = str(node.get("input_variable") or "").strip()
        if not input_variable:
            return None
        context = self._condition_context(task)
        value = resolve_path(context, input_variable, None)
        if value is not None:
            return value
        return self._workflow_variable(task, input_variable)

    def _node_json_value(self, task: TaskState, node: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key not in node:
                continue
            raw = node.get(key)
            if raw in (None, ""):
                continue
            if isinstance(raw, str):
                text = raw.strip()
                try:
                    raw = json.loads(text)
                except Exception:
                    raw = text
            return self._resolve_workflow_template(task, raw)
        return None

    def _node_string_list(self, task: TaskState, node: dict[str, Any], *keys: str) -> list[str]:
        value = self._node_json_value(task, node, *keys)
        if isinstance(value, str):
            value = value.replace("；", ",").replace(";", ",").split(",")
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _json_transform_value(self, source: Any, expression: str) -> Any:
        path = str(expression or "").strip()
        if not path or path in {".", "$"}:
            return source
        if path.startswith("$."):
            path = path[2:]
        elif path.startswith("."):
            path = path[1:]
        if not path:
            return source
        return resolve_path(source, path, None)

    def _sandbox_node_path(self, task: TaskState, raw_path: Any) -> tuple[Path | None, str]:
        value = self._resolve_workflow_template(task, raw_path)
        text = str(value or "").strip()
        if not text:
            return None, "File node requires path/input_path/output_path."
        candidate = Path(text)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.storage.sandbox_workspace_dir / candidate).resolve()
        root = self.storage.sandbox_workspace_dir.resolve()
        try:
            resolved.relative_to(root)
        except Exception:
            return None, f"File path must stay inside sandbox_workspace: {text}"
        return resolved, ""

    def _node_builtin_tool_allowed(
        self,
        spec: AgentSpec,
        node: dict[str, Any],
        tool_name: str,
        *,
        capability: str,
        risk: str,
    ) -> str:
        if not self._tool_allowed_by_agent_profile(spec, tool_name):
            return f"Tool is outside the Agent tool profile: {tool_name}"
        if not self._permission_allows_tool(node, capability=capability, risk=risk):
            return f"Tool permission profile blocks {tool_name}: capability={capability}, risk={risk}"
        return ""

    @staticmethod
    def _candidate_by_action(candidates: list[dict[str, Any]], actions: set[str]) -> str:
        for item in candidates:
            if str(item.get("action") or "").strip() in actions:
                return str(item.get("id") or "").strip()
        return ""

    @staticmethod
    def _candidate_by_stage(candidates: list[dict[str, Any]], stages: set[str]) -> str:
        for item in candidates:
            if str(item.get("stage") or "").strip() in stages:
                return str(item.get("id") or "").strip()
        return ""

    def _route_target_from_node(
        self,
        task: TaskState,
        node: dict[str, Any],
        outgoing: list[str],
        candidates: list[dict[str, Any]],
    ) -> str:
        if len(outgoing) == 1:
            return outgoing[0]
        for key in ("next_node_id", "target_node_id", "route_to", "default_next"):
            target = str(node.get(key) or "").strip()
            if target in outgoing:
                return target

        route_map = self._node_json_object(node, "route_map", "routes")
        route_variable = str(node.get("route_variable") or node.get("input_variable") or "").strip()
        if route_map and route_variable:
            value = self._workflow_variable(task, route_variable)
            for key in (str(value), str(value).lower()):
                target = str(route_map.get(key) or "").strip()
                if target in outgoing:
                    return target
        context = self._condition_context(task)
        default_target = ""
        for item in candidates:
            target = str(item.get("id") or "").strip()
            condition = str(item.get("condition") or item.get("when") or "").strip()
            if not condition:
                continue
            lowered = condition.lower()
            if lowered in {"default", "else", "otherwise"}:
                default_target = target
                continue
            result = evaluate_condition(condition, context)
            if result is True and target in outgoing:
                return target
        if task.pending_approvals():
            return self._candidate_by_action(candidates, {"wait_user", "handoff"}) or self._candidate_by_stage(candidates, {"guard"})

        state_text = "\n".join(
            [
                task.status or "",
                task.current_summary or "",
                task.last_confirmed_progress or "",
                task.last_observation or "",
                " ".join(item.get("issue", "") for item in task.blockers[-3:]),
            ]
        ).lower()
        failed = any(word in state_text for word in ("fail", "failed", "error", "blocked", "失败", "错误", "阻塞"))
        passed = any(word in state_text for word in ("pass", "passed", "ok", "success", "完成", "通过", "成功")) and not failed
        if failed:
            return self._candidate_by_action(candidates, {"retry", "request_approval", "wait_user", "handoff"})
        if passed:
            return self._candidate_by_action(candidates, {"save_state", "save_memory", "notify", "exit_summary", "archive"})

        default_target = default_target
        for item in candidates:
            condition = str(item.get("condition") or "").strip().lower()
            if condition in {"default", "else", "otherwise"}:
                default_target = str(item.get("id") or "").strip()
        return default_target if default_target in outgoing else ""

    def _workflow_trigger_payload(self, task: TaskState) -> dict[str, Any]:
        data = self._ensure_workflow_data(task)
        payload = data.get("trigger_payload")
        return payload if isinstance(payload, dict) else {}

    def _workflow_text_from_context(self, ctx: NodeExecutionContext) -> str:
        value = self._node_payload_from_variable(ctx.task, ctx.node)
        if value is None:
            value = self._node_json_value(ctx.task, ctx.node, "text", "message", "input", "content")
        if value is None:
            payload = self._workflow_trigger_payload(ctx.task)
            value = payload.get("text") or payload.get("message") or payload.get("content")
        if value is None:
            value = getattr(ctx.event, "message_str", "") or ctx.task.root_goal or ctx.task.last_observation
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value or "")

    def _node_patterns(self, task: TaskState, node: dict[str, Any], *keys: str) -> list[str]:
        patterns = self._node_string_list(task, node, *keys)
        if patterns:
            return patterns
        tags = node.get("tags")
        if isinstance(tags, str):
            return [part.strip() for part in re.split(r"[,;\s]+", tags) if part.strip()]
        if isinstance(tags, list):
            return [str(item).strip() for item in tags if str(item).strip()]
        return []

    async def _execute_trigger_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        payload = dict(self._workflow_trigger_payload(ctx.task))
        action = str(ctx.node.get("action") or "").strip()
        if not payload:
            payload = self._build_trigger_payload(
                source=action or "manual",
                event=ctx.event,
                text=getattr(ctx.event, "message_str", "") or ctx.task.root_goal,
            )
            self._ensure_workflow_data(ctx.task)["trigger_payload"] = payload
        self._set_workflow_variable(ctx.task, "trigger_payload", payload)
        data = {
            "route": "success",
            "source": payload.get("source") or action,
            "text": payload.get("text") or "",
            "payload": payload,
        }
        return NodeExecutionResult(
            outcome=f"Trigger accepted from {data['source'] or 'workflow'}.",
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=False,
            advance=True,
            note="node_executor_trigger",
        )

    async def _execute_detector_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        text = self._workflow_text_from_context(ctx)
        route = "uncertain"
        matched: list[str] = []
        error = ""
        if action == "scope_filter":
            allowed, reason = self._workflow_scope_allows_event(ctx.spec, ctx.event)
            route = "success" if allowed else "failed"
            matched = [reason]
        elif action in {"match_keyword", "llm_detect"}:
            keywords = self._node_patterns(
                ctx.task,
                ctx.node,
                "keywords",
                "keyword",
                "patterns",
                "rules",
                "allow",
                "deny",
            )
            lowered = text.lower()
            matched = [item for item in keywords if item.lower() in lowered]
            if keywords:
                route = "success" if matched else "failed"
            elif action == "llm_detect":
                route = "uncertain"
        elif action == "match_regex":
            patterns = self._node_patterns(ctx.task, ctx.node, "regex", "pattern", "patterns")
            for pattern in patterns:
                try:
                    if re.search(pattern, text, flags=re.IGNORECASE):
                        matched.append(pattern)
                except re.error as exc:
                    error = f"Invalid regex {pattern}: {exc}"
                    route = "error"
                    break
            if not error:
                route = "success" if matched else ("failed" if patterns else "uncertain")

        data = {
            "route": route,
            "matched": matched,
            "text": self._compact_text(text, 1000),
            "action": action,
        }
        if error:
            data["error"] = error
        return NodeExecutionResult(
            ok=route in {"success", "failed", "uncertain"},
            status="completed" if route != "error" else "blocked",
            outcome=f"Detector route={route}; matched={len(matched)}." if not error else error,
            data=data,
            blocked=route == "error",
            note="node_executor_detector",
        )

    async def _execute_rate_limit_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        try:
            window_seconds = max(1, min(int(ctx.node.get("window_seconds") or ctx.node.get("window") or 60), 86400))
        except Exception:
            window_seconds = 60
        try:
            max_hits = max(1, min(int(ctx.node.get("max_hits") or ctx.node.get("limit") or 5), 10000))
        except Exception:
            max_hits = 5
        key_parts = [
            str(ctx.node.get("id") or ""),
            str(ctx.node.get("bucket") or ""),
            str(getattr(ctx.event, "unified_msg_origin", "") or ""),
            str(ctx.event.get_sender_id() if hasattr(ctx.event, "get_sender_id") else ""),
        ]
        bucket_key = hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()[:24]
        data = self._ensure_workflow_data(ctx.task)
        buckets = data.setdefault("rate_limits", {})
        if not isinstance(buckets, dict):
            buckets = {}
            data["rate_limits"] = buckets
        now_ts = time.time()
        hits = [
            float(item)
            for item in buckets.get(bucket_key, [])
            if isinstance(item, (int, float)) and now_ts - float(item) <= window_seconds
        ]
        hits.append(now_ts)
        buckets[bucket_key] = hits[-max_hits * 2 :]
        allowed = len(hits) <= max_hits
        route = "success" if allowed else "failed"
        return NodeExecutionResult(
            ok=True,
            status="completed",
            outcome=f"Rate limit route={route}; hits={len(hits)}/{max_hits}.",
            data={
                "route": route,
                "bucket": bucket_key,
                "hits": len(hits),
                "max_hits": max_hits,
                "window_seconds": window_seconds,
            },
            note="node_executor_rate_limit",
        )

    async def _execute_catch_error_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        latest = next(reversed(outputs.values()), {}) if outputs else {}
        has_error = bool(
            ctx.task.blockers
            or (isinstance(latest, dict) and (latest.get("blocked") or latest.get("ok") is False))
        )
        route = "error" if has_error else "success"
        return NodeExecutionResult(
            ok=True,
            status="completed",
            outcome=f"Catch error route={route}.",
            data={"route": route, "latest": latest, "blockers": list(ctx.task.blockers or [])[-8:]},
            note="node_executor_catch_error",
        )

    async def _execute_record_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if payload is None:
            payload = self._node_templated_json_object(ctx.task, ctx.node, "payload", "record", "data")
        record = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "title": str(ctx.node.get("title") or ""),
            "payload": payload,
        }
        data = self._ensure_workflow_data(ctx.task)
        records = data.setdefault("records", [])
        if not isinstance(records, list):
            records = []
        records.append(record)
        data["records"] = records[-120:]
        ctx.task.add_log("workflow_record", self._compact_text(json.dumps(record, ensure_ascii=False), 800))
        return NodeExecutionResult(
            outcome="Workflow record written.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "record": record},
            needs_react=False,
            advance=True,
            note="node_executor_record",
        )

    async def _execute_report_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        try:
            node_outputs_snapshot = json.loads(
                json.dumps(data.get("node_outputs") or {}, ensure_ascii=False, default=str)
            )
        except Exception:
            node_outputs_snapshot = {}
        payload = {
            "time": now_iso(),
            "task_id": ctx.task.task_id,
            "agent_id": ctx.spec.agent_id,
            "trigger": data.get("trigger_payload") or {},
            "path": list(ctx.task.workflow_path or []),
            "node_outputs": node_outputs_snapshot,
            "blockers": list(ctx.task.blockers or [])[-12:],
        }
        reports = data.setdefault("reports", [])
        if not isinstance(reports, list):
            reports = []
        reports.append(payload)
        data["reports"] = reports[-40:]
        summary = self._compact_text(
            str(ctx.node.get("template") or ctx.node.get("message") or "")
            or f"Workflow report generated for task {ctx.task.task_id}.",
            1200,
        )
        ctx.task.add_log("workflow_report", summary)
        return NodeExecutionResult(
            outcome=summary,
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "report": payload, "summary": summary},
            needs_react=False,
            advance=True,
            note="node_executor_report",
        )

    async def _execute_entry_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        if action == "summarize_entry":
            outcome = f"Entry brief is available for task {ctx.task.task_id}."
        elif action == "confirm_entry":
            outcome = "Entry confirmation is satisfied because the task exists."
        else:
            outcome = "Session isolation snapshot is already applied for this task."
        data = {"action": action, "task_id": ctx.task.task_id}
        # Inject pattern recommendations at entry time so the first planning
        # pass already has relevant past patterns available.
        if action == "summarize_entry" and hasattr(self, "pattern_library"):
            try:
                goal = str(ctx.task.root_goal or "")
                if goal:
                    patterns = self.pattern_library.recommend(
                        goal, limit=3, exclude_task_id=ctx.task.task_id
                    )
                    if patterns:
                        data["pattern_recommendations"] = [
                            self.pattern_library.compact_for_runtime(p)
                            for p in patterns
                        ]
            except Exception:
                pass
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_entry",
        )

    async def _execute_state_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        if action == "heartbeat":
            ctx.task.heartbeat.last_pulse_at = now_iso()
            outcome = "Heartbeat checkpoint recorded."
            data = {"heartbeat_enabled": ctx.task.heartbeat.enabled}
        elif action == "variable_set":
            variable_name = str(
                ctx.node.get("variable_name")
                or ctx.node.get("name")
                or ctx.node.get("output_variable")
                or ctx.node.get("variable")
                or ""
            ).strip()
            if not variable_name:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome="variable_set requires variable_name.",
                    blocked=True,
                    advance=False,
                    note="node_executor_variable_set_missing_name",
                )
            value = self._node_payload_from_variable(ctx.task, ctx.node)
            if value is None:
                value = self._node_json_value(ctx.task, ctx.node, "value", "payload", "data")
            self._set_workflow_variable(ctx.task, variable_name, value)
            outcome = f"Variable {variable_name} set."
            data = {"variable": variable_name, "value": value}
        elif action == "variable_get":
            variable_name = str(
                ctx.node.get("variable_name")
                or ctx.node.get("name")
                or ctx.node.get("input_variable")
                or ctx.node.get("variable")
                or ""
            ).strip()
            if not variable_name:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome="variable_get requires variable_name.",
                    blocked=True,
                    advance=False,
                    note="node_executor_variable_get_missing_name",
                )
            value = resolve_path(self._condition_context(ctx.task), variable_name, None)
            if value is None:
                value = self._workflow_variable(ctx.task, variable_name)
            outcome = f"Variable {variable_name} read."
            data = {"variable": variable_name, "value": value}
        elif action == "text_template":
            template = str(
                ctx.node.get("template")
                or ctx.node.get("text")
                or ctx.node.get("prompt")
                or ctx.node.get("instruction")
                or ""
            )
            rendered = self._resolve_workflow_template(ctx.task, template)
            rendered_text = str(rendered if rendered is not None else "")
            outcome = "Text template rendered."
            data = {"text": rendered_text}
        elif action == "json_transform":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = self._node_json_value(ctx.task, ctx.node, "source", "payload", "data")
            expression = str(
                ctx.node.get("expression")
                or ctx.node.get("path")
                or ctx.node.get("json_path")
                or ctx.node.get("jq")
                or "."
            ).strip()
            transformed = self._json_transform_value(source, expression)
            outcome = f"JSON transform applied: {expression or '.'}."
            data = {"value": transformed, "expression": expression or "."}
        elif action == "merge":
            names = self._node_string_list(ctx.task, ctx.node, "inputs", "input_variables", "sources")
            merged: dict[str, Any] = {}
            if names:
                context = self._condition_context(ctx.task)
                for name in names:
                    value = resolve_path(context, name, None)
                    if value is None:
                        value = self._workflow_variable(ctx.task, name)
                    merged[name] = value
            else:
                node_outputs = (self._ensure_workflow_data(ctx.task).get("node_outputs") or {})
                for candidate in ctx.next_candidates:
                    node_id = str(candidate.get("id") or "")
                    if node_id in node_outputs:
                        merged[node_id] = node_outputs[node_id]
                if not merged:
                    merged = dict(node_outputs)
            outcome = f"Merged {len(merged)} input(s)."
            data = {"merged": merged}
        elif action == "iterator":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = self._node_json_value(ctx.task, ctx.node, "items", "source", "payload")
            if isinstance(source, dict):
                items = [{"key": key, "value": value} for key, value in source.items()]
            elif isinstance(source, list):
                items = list(source)
            else:
                items = []
            outcome = f"Iterator prepared {len(items)} item(s)."
            data = {"items": items, "count": len(items)}
        elif action == "subflow_call":
            template_id = str(ctx.node.get("template_id") or ctx.node.get("ref_id") or "").strip()
            params = self._node_templated_json_object(ctx.task, ctx.node, "params", "arguments", "payload")
            outcome = "Subflow call prepared; nested runner is not enabled yet."
            data = {"template_id": template_id, "params": params, "runner": "pending"}
        elif action == "transform_context":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = ctx.task.last_observation or ctx.task.current_summary or ctx.task.last_confirmed_progress
            text = self._compact_text(
                source if isinstance(source, str) else json.dumps(source, ensure_ascii=False),
                1600,
            )
            if text:
                ctx.task.current_summary = text
            outcome = "Context transformed into compact observation."
            data = {"summary": text}
        else:
            outcome = "Task checkpoint saved."
            data = {
                "current_summary": ctx.task.current_summary,
                "progress": ctx.task.last_confirmed_progress,
                "next_step": ctx.task.next_step,
            }
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_state",
        )

    async def _execute_http_request_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        gate = self._node_builtin_tool_allowed(
            ctx.spec,
            ctx.node,
            CUSTOM_API_TOOL_NAME,
            capability="api",
            risk="work",
        )
        if gate:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=gate,
                blocked=True,
                advance=False,
                note="node_executor_http_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, CUSTOM_API_TOOL_NAME)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_http_budget",
            )
        url = str(self._resolve_workflow_template(ctx.task, ctx.node.get("url") or "") or "").strip()
        if not url:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="http_request requires url.",
                blocked=True,
                advance=False,
                note="node_executor_http_missing_url",
            )
        method = str(ctx.node.get("method") or "GET").strip().upper()
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            method = "GET"
        payload = self._node_templated_json_object(ctx.task, ctx.node, "payload", "request", "api_payload")
        query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
        headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
        body = payload.get("body") if "body" in payload else None
        try:
            timeout_seconds = max(1, min(int(ctx.node.get("timeout_seconds") or 30), 120))
        except Exception:
            timeout_seconds = 30
        result = await asyncio.to_thread(
            self._perform_custom_api_http_call,
            method,
            url,
            query,
            body,
            {str(key): str(value) for key, value in headers.items()},
            timeout_seconds,
        )
        ok = bool(result.get("ok"))
        data = {"ok": ok, "method": method, "url_host": self._safe_url_host(url), **result}
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=f"HTTP {method} {self._safe_url_host(url) or url} status={result.get('status')}",
            next_node_id=self._single_next(ctx.outgoing) if ok else "",
            data=data,
            blocked=not ok,
            note="node_executor_http",
        )

    async def _execute_file_operation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        operation = str(ctx.node.get("operation") or ctx.node.get("edit_mode") or "read").strip().lower()
        tool_name = "astrbot_file_read_tool" if operation == "read" else "astrbot_file_edit_tool"
        risk = "safe" if operation == "read" else "work"
        gate = self._node_builtin_tool_allowed(
            ctx.spec,
            ctx.node,
            tool_name,
            capability="file",
            risk=risk,
        )
        if gate:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=gate,
                blocked=True,
                advance=False,
                note="node_executor_file_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, tool_name)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_file_budget",
            )
        path, reason = self._sandbox_node_path(
            ctx.task,
            ctx.node.get("path") or ctx.node.get("input_path") or ctx.node.get("output_path") or "",
        )
        if reason or path is None:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=reason,
                blocked=True,
                advance=False,
                note="node_executor_file_path_blocked",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        if operation == "read":
            if not path.exists():
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome=f"File does not exist: {path.name}",
                    blocked=True,
                    advance=False,
                    note="node_executor_file_missing",
                )
            text = path.read_text(encoding="utf-8", errors="replace")
            data = {"path": str(path), "content": self._compact_text(text, 12000), "bytes": path.stat().st_size}
            outcome = f"File read: {path.name}"
        elif operation in {"write", "replace"}:
            content = self._node_json_value(ctx.task, ctx.node, "content", "text", "value")
            path.write_text(str(content or ""), encoding="utf-8")
            data = {"path": str(path), "operation": operation, "bytes": path.stat().st_size}
            outcome = f"File written: {path.name}"
        elif operation == "append":
            content = self._node_json_value(ctx.task, ctx.node, "content", "text", "value")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(str(content or ""))
            data = {"path": str(path), "operation": operation, "bytes": path.stat().st_size}
            outcome = f"File appended: {path.name}"
        else:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Unsupported file operation: {operation}",
                blocked=True,
                advance=False,
                note="node_executor_file_operation_blocked",
            )
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_file",
        )

    async def _execute_code_exec_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        language = str(ctx.node.get("language") or "python").strip().lower()
        tool_name = "astrbot_sandboxed_python" if language in {"py", "python"} else "astrbot_sandboxed_shell"
        gate = self._node_builtin_tool_allowed(
            ctx.spec,
            ctx.node,
            tool_name,
            capability="code",
            risk="high",
        )
        if gate:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=gate,
                blocked=True,
                advance=False,
                note="node_executor_code_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, tool_name)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_code_budget",
            )
        code = str(self._node_json_value(ctx.task, ctx.node, "code", "script", "command") or "")
        if not code.strip():
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="code_exec requires code/script/command.",
                blocked=True,
                advance=False,
                note="node_executor_code_missing",
            )
        try:
            timeout_seconds = max(1, min(int(ctx.node.get("timeout_seconds") or 10), 60))
        except Exception:
            timeout_seconds = 10
        workspace = self.storage.sandbox_workspace_dir
        workspace.mkdir(parents=True, exist_ok=True)
        if language in {"py", "python"}:
            cmd = ["python", "-c", code]
        elif language in {"shell", "powershell", "pwsh"}:
            cmd = ["powershell", "-NoProfile", "-Command", code]
        else:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Unsupported code language: {language}",
                blocked=True,
                advance=False,
                note="node_executor_code_language_blocked",
            )
        completed = await asyncio.to_thread(
            subprocess.run,
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        ok = completed.returncode == 0
        data = {
            "language": language,
            "exit_code": completed.returncode,
            "stdout": self._compact_text(completed.stdout or "", 4000),
            "stderr": self._compact_text(completed.stderr or "", 4000),
            "workspace": str(workspace),
        }
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=f"Code execution exit_code={completed.returncode}.",
            next_node_id=self._single_next(ctx.outgoing) if ok else "",
            data=data,
            blocked=not ok,
            note="node_executor_code",
        )

    async def _execute_retrieve_memory_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        query = str(
            ctx.node.get("query")
            or ctx.node.get("memory_query")
            or ctx.node.get("condition")
            or ctx.task.root_goal
            or ""
        ).strip()
        try:
            limit = max(1, min(int(ctx.node.get("limit") or 5), 12))
        except Exception:
            limit = 5
        scored_rows: list[tuple[int, dict[str, Any]]] = []
        for item in reversed(self.storage.list_memory_entries()):
            text = str(item.get("text") or "")
            haystack = "\n".join(
                [
                    text,
                    str(item.get("source_task_id") or ""),
                    " ".join(str(tag) for tag in item.get("tags") or []),
                ]
            )
            score = self._memory_similarity_score(query, haystack)
            if query and score <= 0:
                continue
            visible, _ = self._memory_entry_visible(
                item,
                umo=ctx.task.umo,
                active_task=ctx.task,
                allow_private=True,
            )
            if not visible:
                continue
            scored_rows.append((score, self._memory_entry_row(item, text_limit=900)))
        scored_rows.sort(key=lambda row: row[0], reverse=True)
        rows = [row for _, row in scored_rows[:limit]]

        pattern_rows = []
        try:
            if query and hasattr(self, "pattern_library"):
                raw = self.pattern_library.recommend(
                    query, limit=3, exclude_task_id=ctx.task.task_id
                )
                pattern_rows = [
                    self.pattern_library.compact_for_runtime(p) for p in raw
                ]
        except Exception:
            pattern_rows = []

        outcome = f"Retrieved {len(rows)} task memory item(s)"
        if pattern_rows:
            outcome += f" and {len(pattern_rows)} pattern(s)"
        outcome += "."

        data = {"query": query.lower(), "rows": rows}
        if pattern_rows:
            data["pattern_recommendations"] = pattern_rows

        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_memory_retrieve",
        )

    async def _execute_save_memory_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        outcome = "Private task memory checkpoint saved."
        self._save_workflow_private_memory(ctx.task, ctx.node, outcome)
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"kind": "workflow_private_memory", "expose_to_normal": False},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_memory_save",
        )

    async def _execute_parallel_branch_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        parallel = await self._run_parallel_workflow(
            event=ctx.event,
            task=ctx.task,
            spec=ctx.spec,
            branch_node_id=str(ctx.node.get("id") or ""),
            parallel_group=str(ctx.node.get("parallel_group") or ""),
            shared_instruction=f"tick_reason={ctx.reason}",
            max_concurrency=max(
                1,
                min(int(_cfg(self.config, "workflow_parallel_concurrency", 3) or 3), 6),
            ),
        )
        ok = bool(parallel.get("ok"))
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=str(parallel.get("summary") or parallel.get("error") or "Parallel workflow finished."),
            next_node_id=str(parallel.get("merge_node_id") or ""),
            data=parallel,
            blocked=not ok and not parallel.get("merge_node_id"),
            needs_react=not parallel.get("merge_node_id"),
            advance=False,
            note="node_executor_parallel",
        )

    async def _execute_api_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        if not self._tool_allowed_by_agent_profile(ctx.spec, CUSTOM_API_TOOL_NAME):
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="Custom API execution is outside the Agent tool profile.",
                blocked=True,
                advance=False,
                note="node_executor_api_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, CUSTOM_API_TOOL_NAME)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_api_budget",
            )
        base = {
            "node_id": str(ctx.node.get("id") or ""),
            "title": ctx.node.get("title") or ctx.node.get("id") or "",
            "kind": ctx.node.get("kind") or "api",
            "action": ctx.node.get("action") or "call_api",
            "ok": False,
            "status": "blocked",
            "summary": "",
            "details": "",
        }
        payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if payload is None:
            payload = self._node_templated_json_object(ctx.task, ctx.node, "api_payload", "payload", "params")
        else:
            payload = self._resolve_workflow_template(ctx.task, payload)
        worker = await self._run_parallel_api_worker(ctx.node, base, api_payload=payload)
        ok = bool(worker.get("ok"))
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=str(worker.get("summary") or worker.get("error") or ""),
            next_node_id=self._single_next(ctx.outgoing) if ok else "",
            data=worker,
            blocked=not ok,
            note="node_executor_api",
        )

    async def _execute_tool_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        tool_name = str(
            ctx.node.get("tool_name")
            or (ctx.node.get("ref_id") if ctx.node.get("ref_type") == "tool" else "")
            or ""
        ).strip()
        call_args = self._node_templated_json_object(ctx.task, ctx.node, "tool_args", "arguments", "params")
        variable_payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if isinstance(variable_payload, dict):
            resolved_payload = self._resolve_workflow_template(ctx.task, variable_payload)
            call_args = {**call_args, **(resolved_payload if isinstance(resolved_payload, dict) else {})}
        if not tool_name:
            return NodeExecutionResult(
                outcome="Tool node needs ReAct because no concrete tool_name is bound.",
                needs_react=True,
                advance=False,
                note="node_executor_tool_react_fallback",
            )
        executed = await self.tool_executor.call(
            event=ctx.event,
            task=ctx.task,
            spec=ctx.spec,
            node=ctx.node,
            tool_name=tool_name,
            call_args=call_args,
        )
        if executed.needs_react:
            return NodeExecutionResult(
                outcome=executed.outcome,
                needs_react=True,
                advance=False,
                data=executed.data,
                note=executed.note,
            )
        if executed.blocked or not executed.ok:
            return NodeExecutionResult(
                ok=False,
                status=executed.status,
                outcome=executed.outcome,
                blocked=True,
                advance=False,
                data=executed.data,
                note=executed.note,
            )
        return NodeExecutionResult(
            outcome=executed.outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=executed.data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note=executed.note,
        )

    async def _execute_route_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        target = self._route_target_from_node(ctx.task, ctx.node, ctx.outgoing, ctx.next_candidates)
        if not target:
            return NodeExecutionResult(
                outcome="Decision node has no deterministic route; ReAct must choose a branch.",
                needs_react=True,
                advance=False,
                note="node_executor_route_react",
            )
        return NodeExecutionResult(
            outcome=f"Decision routed to {target}.",
            next_node_id=target,
            data={"selected": target, "candidates": ctx.outgoing},
            note="node_executor_route",
        )

    async def _execute_retry_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        node_id = str(ctx.node.get("id") or "")
        count = int((data.get("execution_counts") or {}).get(node_id, 0) or 0)
        max_retries = max(1, min(int(ctx.node.get("max_retries") or ctx.task.heartbeat.max_repeated_failures or 3), 8))
        if count >= max_retries:
            ctx.task.status = "blocked"
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Retry limit reached ({count}/{max_retries}).",
                blocked=True,
                advance=False,
                data={"count": count, "max_retries": max_retries},
                note="node_executor_retry_limit",
            )
        return NodeExecutionResult(
            outcome=f"Retry allowed ({count + 1}/{max_retries}).",
            next_node_id=self._single_next(ctx.outgoing),
            data={"count": count + 1, "max_retries": max_retries},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_retry",
        )

    async def _execute_validation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        verdict = self.verifier.verify_validation_checkpoint(ctx.task)
        passed = verdict.passed
        if not passed and len(ctx.outgoing) > 1:
            retry_target = self._candidate_by_action(ctx.next_candidates, {"retry"}) or self._candidate_by_stage(
                ctx.next_candidates, {"checkpoint", "execute"}
            )
            if verdict.status == "failed" and retry_target:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome=f"Validation did not pass; routed to {retry_target}.",
                    next_node_id=retry_target,
                    data=verdict.to_dict(),
                    note="node_executor_validation_retry",
                )
            return NodeExecutionResult(
                outcome=verdict.reason,
                needs_react=True,
                advance=False,
                data=verdict.to_dict(),
                note="node_executor_validation_react",
            )
        return NodeExecutionResult(
            outcome="Validation passed." if passed else "Validation checkpoint recorded.",
            next_node_id=self._single_next(ctx.outgoing),
            data=verdict.to_dict(),
            needs_react=len(ctx.outgoing) > 1 and not passed,
            advance=len(ctx.outgoing) <= 1 or passed,
            note="node_executor_validation",
        )

    async def _execute_debate_validation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        perspectives = self._node_string_list(ctx.task, ctx.node, "perspectives", "checks")
        if not perspectives:
            perspectives = ["correctness", "safety", "completion"]
        require_consensus_raw = ctx.node.get("require_consensus", True)
        if isinstance(require_consensus_raw, str):
            require_consensus = require_consensus_raw.strip().lower() not in {"false", "0", "no", "off"}
        else:
            require_consensus = bool(require_consensus_raw)

        base_verdict = self.verifier.verify_validation_checkpoint(ctx.task)
        evidence_text = "\n".join(
            [
                str(ctx.task.current_summary or ""),
                str(ctx.task.last_confirmed_progress or ""),
                str(ctx.task.last_observation or ""),
                json.dumps((ctx.task.workflow_data or {}).get("node_outputs") or {}, ensure_ascii=False, default=str),
            ]
        ).lower()
        failure_markers = ("fail", "failed", "error", "blocked", "unsafe", "risk", "失败", "错误", "阻塞")
        reviews: list[dict[str, Any]] = []
        for perspective in perspectives[:8]:
            name = str(perspective or "review").strip()
            lowered = name.lower()
            passed = bool(base_verdict.passed)
            reason = base_verdict.reason
            missing = list(base_verdict.missing or [])
            if lowered in {"safety", "security", "risk", "安全性", "风险"} and any(marker in evidence_text for marker in failure_markers):
                passed = False
                if "risk_evidence" not in missing:
                    missing.append("risk_evidence")
                reason = "Safety/risk perspective found blocking evidence."
            reviews.append(
                {
                    "perspective": name,
                    "passed": passed,
                    "status": "passed" if passed else "needs_review",
                    "reason": reason,
                    "missing": missing,
                }
            )

        passed_count = sum(1 for item in reviews if item.get("passed"))
        passed = passed_count == len(reviews) if require_consensus else passed_count > 0
        data = {
            "passed": passed,
            "require_consensus": require_consensus,
            "passed_count": passed_count,
            "total": len(reviews),
            "reviews": reviews,
            "base_verdict": base_verdict.to_dict(),
        }
        return NodeExecutionResult(
            ok=passed,
            status="completed" if passed else "blocked",
            outcome=(
                f"Debate validation passed {passed_count}/{len(reviews)} perspective(s)."
                if passed
                else f"Debate validation needs review: {passed_count}/{len(reviews)} perspective(s) passed."
            ),
            next_node_id=self._single_next(ctx.outgoing) if passed else "",
            data=data,
            blocked=not passed,
            note="node_executor_debate_validation",
        )

    async def _execute_approval_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        if ctx.task.pending_approvals():
            ctx.task.status = "paused"
            pending = ctx.task.pending_approvals()[0]
            ctx.task.set_wait(
                wait_reason="need_approval",
                message=f"Waiting for existing approval request: {pending.operation}",
                source="workflow_approval_node",
                resume_command=f"/agentlab approve {pending.approval_id}",
                required_input=[pending.operation],
            )
            return NodeExecutionResult(
                ok=False,
                status="running",
                outcome="Waiting for existing approval request.",
                advance=False,
                data={"pending": [item.approval_id for item in ctx.task.pending_approvals()]},
                note="node_executor_approval_wait",
            )
        operation = str(ctx.node.get("operation") or ctx.node.get("title") or "workflow approval").strip()
        reason = str(ctx.node.get("reason") or ctx.node.get("instruction") or "Workflow guard requires approval.").strip()
        impact = str(ctx.node.get("impact") or "Task execution is paused until the user approves.").strip()
        approval = ApprovalRequest(operation=operation, reason=reason, impact=impact)
        ctx.task.approvals.append(approval.to_dict())
        ctx.task.status = "paused"
        ctx.task.set_wait(
            wait_reason="need_approval",
            message=f"Approval requested: {operation}",
            source="workflow_approval_node",
            resume_command=f"/agentlab approve {approval.approval_id}",
            required_input=[operation],
        )
        ctx.task.add_log("approval_requested", f"{approval.approval_id}: {operation}")
        return NodeExecutionResult(
            ok=False,
            status="running",
            outcome=f"Approval requested: {approval.approval_id}",
            advance=False,
            data=approval.to_dict(),
            note="node_executor_approval",
        )

    async def _execute_wait_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        ctx.task.status = "paused"
        action = str(ctx.node.get("action") or "").strip()
        instruction = str(ctx.node.get("instruction") or "Waiting for user input.").strip()
        lowered = " ".join(
            str(ctx.node.get(key) or "")
            for key in ("wait_reason", "reason", "title", "instruction", "prompt")
        ).lower()
        wait_reason = str(ctx.node.get("wait_reason") or "").strip()
        if not wait_reason:
            if "credential" in lowered or "secret" in lowered or "api key" in lowered:
                wait_reason = "need_credential"
            elif "login" in lowered or "captcha" in lowered or "otp" in lowered:
                wait_reason = "need_login"
            elif "external" in lowered or "webhook" in lowered or "callback" in lowered:
                wait_reason = "waiting_external_result"
            else:
                wait_reason = "need_user_decision" if action == "handoff" else "waiting_user"
        ctx.task.set_wait(
            wait_reason=wait_reason,
            message=instruction,
            source=f"workflow_{action or 'wait'}_node",
            required_input=[instruction],
        )
        return NodeExecutionResult(
            ok=False,
            status="running",
            outcome=instruction,
            advance=False,
            data={"wait": True, "wait_reason": wait_reason},
            note="node_executor_wait",
        )

    async def _execute_notify_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "notify").strip()
        outcome = self._compact_text(
            str(ctx.node.get("message") or ctx.task.current_summary or ctx.task.last_confirmed_progress or "Notification checkpoint."),
            1000,
        )
        channel = {
            "send_message": "message",
            "send_private_message": "private_message",
            "send_email": "email",
        }.get(action, "notify")
        target = str(ctx.node.get("target") or ctx.node.get("to") or ctx.node.get("recipient") or "").strip()
        item = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "action": action,
            "channel": channel,
            "target": target,
            "message": outcome,
            "delivery": "outbox",
        }
        data = self._ensure_workflow_data(ctx.task)
        outbox = data.setdefault("outbox", [])
        if not isinstance(outbox, list):
            outbox = []
        outbox.append(item)
        data["outbox"] = outbox[-120:]
        ctx.task.add_log("notify", outcome)
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "message": outcome, "outbox": item},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_notify",
        )

    async def _execute_terminal_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        return NodeExecutionResult(
            outcome="Terminal node requires final summary and finish decision.",
            needs_react=True,
            terminal=True,
            advance=False,
            note="node_executor_terminal_react",
        )


    async def _run_workflow_runtime(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        reason: str,
    ) -> WorkflowRuntimeRun:
        runtime_run = WorkflowRuntimeRun()
        self._ensure_workflow_data(task)
        for _ in range(self.workflow_runtime.max_auto_steps):
            decision = self.workflow_runtime.inspect(spec, task)
            budget_reason = self._consume_node_budget(task, decision.node)
            if budget_reason:
                self._pause_task_for_budget(task, budget_reason)
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=budget_reason,
                        note="budget_exhausted",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            schema_reason = self._validate_node_input_schema(task, decision.node)
            if schema_reason:
                task.status = "paused"
                task.set_wait(
                    wait_reason="need_user_decision",
                    message=schema_reason,
                    source="schema_validation",
                    required_input=["valid_node_input"],
                )
                task.add_blocker("schema_mismatch", schema_reason)
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=schema_reason,
                        note="schema_mismatch",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            loop_reason = self._loop_guard_before_node(task, decision.node)
            if loop_reason:
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=loop_reason,
                        note="loop_guard",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            if decision.blocked:
                runtime_run.steps.append(decision)
                runtime_run.blocked = True
                task.add_blocker("workflow_runtime", decision.outcome)
                task.status = "blocked"
                task.add_snapshot(
                    "workflow_runtime",
                    {
                        "node_id": decision.node_id,
                        "status": "blocked",
                        "reason": decision.outcome,
                    },
                )
                break

            if self.node_executors.can_execute(decision.node):
                nodes = self.workflow_runtime.node_map(spec)
                context_edges = self._workflow_edges_from(spec, decision.node_id)
                outgoing = [str(edge.get("to") or "") for edge in context_edges if str(edge.get("to") or "") in nodes]
                ctx = NodeExecutionContext(
                    event=event,
                    task=task,
                    spec=spec,
                    node=decision.node,
                    outgoing=outgoing,
                    next_candidates=self._candidate_nodes_from_edges(nodes, context_edges),
                    reason=reason,
                )
                result = await self._execute_node_with_policy(ctx)
                if result.ok and not result.blocked:
                    output_reason = self._validate_node_output_schema(decision.node, result)
                    if output_reason:
                        result.ok = False
                        result.blocked = True
                        result.status = "blocked"
                        result.outcome = output_reason
                        result.note = "node_output_schema_mismatch"
                        result.advance = False
                if not result.next_node_id and not result.needs_react and not result.terminal:
                    target = self._select_next_node_after_result(task, spec, decision.node_id, result)
                    if target:
                        result.next_node_id = target
                        result.advance = True
                self._record_node_execution(task, decision.node, result)
                loop_after_reason = self._loop_guard_after_node(task, decision.node, result)
                executed = self._node_result_to_decision(decision.node, result)
                if loop_after_reason:
                    executed.blocked = True
                    executed.status = "blocked"
                    executed.note = "loop_guard"
                    executed.outcome = loop_after_reason
                    runtime_run.blocked = True
                runtime_run.steps.append(executed)
                if loop_after_reason:
                    break

                if result.terminal:
                    runtime_run.needs_react = True
                    runtime_run.react_node_id = executed.node_id
                    runtime_run.terminal = True
                    break

                if result.needs_react:
                    runtime_run.needs_react = True
                    runtime_run.react_node_id = executed.node_id
                    break

                if result.blocked:
                    if result.next_node_id:
                        self._advance_task_workflow(
                            task,
                            spec,
                            node_id=executed.node_id,
                            outcome=result.outcome,
                            next_node_id=result.next_node_id,
                            note=result.note,
                            status=result.status,
                        )
                        continue
                    runtime_run.blocked = True
                    if result.status == "blocked":
                        task.status = "blocked"
                        task.add_blocker("workflow_runtime", result.outcome)
                    break

                if result.advance:
                    self._advance_task_workflow(
                        task,
                        spec,
                        node_id=executed.node_id,
                        outcome=result.outcome,
                        next_node_id=result.next_node_id,
                        note=result.note,
                        status=result.status,
                    )
                    if not result.next_node_id:
                        runtime_run.needs_react = True
                        runtime_run.react_node_id = executed.node_id
                        break
                else:
                    break
                continue

            if decision.terminal or decision.needs_react:
                runtime_run.needs_react = True
                runtime_run.react_node_id = decision.node_id
                runtime_run.terminal = decision.terminal
                break

            self._advance_task_workflow(
                task,
                spec,
                node_id=decision.node_id,
                outcome=decision.outcome,
                next_node_id=decision.next_node_id,
                note=decision.note,
                status=decision.status,
            )
            runtime_run.steps.append(decision)
            if not decision.next_node_id:
                runtime_run.needs_react = True
                runtime_run.react_node_id = decision.node_id
                break

        if runtime_run.changed:
            task.add_log("workflow_runtime", self._compact_text(runtime_run.summary(), 1000))
            task.add_snapshot(
                "workflow_runtime",
                {
                    "reason": reason,
                    "steps": [
                        {
                            "node_id": step.node_id,
                            "next_node_id": step.next_node_id,
                            "status": step.status,
                            "outcome": step.outcome,
                            "note": step.note,
                        }
                        for step in runtime_run.steps
                    ],
                    "needs_react": runtime_run.needs_react,
                    "react_node_id": runtime_run.react_node_id,
                    "blocked": runtime_run.blocked,
                },
            )
        return runtime_run

    def _save_workflow_private_memory(
        self,
        task: TaskState,
        node: dict[str, Any],
        outcome: str = "",
    ) -> None:
        tags = node.get("tags") or node.get("memory_tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.replace("，", ",").split(",")]
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        tags = ["task", "workflow", "private", *(tags or ["checkpoint"])]
        text = "\n".join(
            part
            for part in (
                f"Task: {task.task_id}",
                f"Goal: {task.root_goal}",
                f"Workflow node: {node.get('id') or '-'} / {node.get('title') or '-'}",
                f"Summary: {task.current_summary or '-'}",
                f"Progress: {task.last_confirmed_progress or '-'}",
                f"Observation: {task.last_observation or outcome or '-'}",
                f"Next step: {task.next_step or '-'}",
            )
            if part.strip()
        )
        self.storage.save_memory_entry(
            {
                "text": text,
                "source_task_id": task.task_id,
                "source_umo": task.umo,
                "status": "candidate",
                "kind": "workflow_private_memory",
                "tags": tags,
                "expose_to_normal": False,
            }
        )
        task.add_log("task_memory", f"workflow_private_memory saved at {node.get('id') or '-'}")

    def _workflow_react_prompt(
        self,
        *,
        task: TaskState,
        spec: AgentSpec,
        reason: str,
    ) -> str:
        nodes = self.workflow_runtime.node_map(spec)
        outgoing = self.workflow_runtime.outgoing(spec)
        current_id = self.workflow_runtime.current_node_id(spec, task)
        node = nodes.get(current_id) or {}
        candidates = [
            nodes[node_id]
            for node_id in outgoing.get(current_id, [])
            if node_id in nodes
        ]
        if not node:
            return build_tick_prompt(task, reason)
        return self.workflow_runtime.build_react_prompt(
            task=task,
            node=node,
            next_candidates=candidates,
            reason=reason,
        )

    @staticmethod
    def _workflow_entry_id(spec: AgentSpec) -> str:
        for node in spec.workflow_nodes:
            if node.get("action") == "summarize_entry":
                return str(node.get("id") or "")
        for node in spec.workflow_nodes:
            if node.get("stage") == "entry":
                return str(node.get("id") or "")
        return str(spec.workflow_nodes[0].get("id") or "") if spec.workflow_nodes else ""

    @staticmethod
    def _workflow_outgoing(spec: AgentSpec) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for edge in spec.workflow_edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if not start or not end:
                continue
            result.setdefault(start, []).append(end)
        return result

    def _advance_task_workflow(
        self,
        task: TaskState,
        spec: AgentSpec,
        *,
        node_id: str = "",
        outcome: str = "",
        next_node_id: str = "",
        note: str = "",
        status: str = "completed",
    ) -> str:
        self._normalize_agent_workflow(spec)
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        if not node_map:
            return "当前 AgentSpec 没有工作流节点。"
        current_id = str(node_id or task.workflow_current_node_id or self._workflow_entry_id(spec)).strip()
        if current_id not in node_map:
            return f"未找到工作流节点：{current_id}"
        outgoing = self._workflow_outgoing(spec)
        candidates = outgoing.get(current_id, [])
        target = str(next_node_id or "").strip()
        if not target and len(candidates) == 1:
            target = candidates[0]
        if target and target not in node_map:
            return f"未找到下一工作流节点：{target}"
        if target and candidates and target not in candidates:
            note = (note + f"\nmanual_jump_from={current_id}").strip()

        task.add_workflow_event(
            current_id,
            outcome=outcome,
            note=note,
            next_node_id=target,
            status=status if status in {"completed", "running", "skipped", "blocked", "entered"} else "completed",
        )
        if target:
            task.workflow_current_node_id = target
            if not task.workflow_path or task.workflow_path[-1] != target:
                task.workflow_path.append(target)
                task.workflow_path = task.workflow_path[-80:]
            task.add_log("workflow", f"{current_id} -> {target}: {self._compact_text(outcome or note, 300)}")
        else:
            task.workflow_current_node_id = current_id
            task.add_log("workflow", f"{current_id}: {self._compact_text(outcome or note, 300)}")
        task.add_snapshot(
            "workflow",
            {
                "node_id": current_id,
                "next_node_id": target,
                "candidates": candidates,
                "outcome": outcome,
                "note": note,
            },
        )
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_decision(
                task,
                phase="workflow",
                action="advance",
                node_id=current_id,
                reason=outcome or note,
                capability="workflow.control",
                next_node_id=target,
                confidence="high" if target else "medium",
            )
            self.agent_runtime.mark_current(task, completed_node_id=current_id)
            self.agent_runtime.update_resume(task, reason="advance_workflow")
        next_candidates = outgoing.get(task.workflow_current_node_id, [])
        next_text = ", ".join(next_candidates) or "-"
        return (
            f"工作流已记录：{current_id}"
            f"{' -> ' + target if target else ''}。\n"
            f"当前节点：{task.workflow_current_node_id or current_id}\n"
            f"下一候选：{next_text}"
        )

    async def _run_parallel_workflow(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        branch_node_id: str = "",
        parallel_group: str = "",
        merge_node_id: str = "",
        shared_instruction: str = "",
        api_payloads: dict[str, Any] | None = None,
        max_concurrency: int = 3,
    ) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        outgoing = self._workflow_outgoing(spec)
        branch_id = self._resolve_parallel_branch_id(spec, task, branch_node_id)
        if not branch_id:
            return {
                "ok": False,
                "error": "未找到 parallel_branch 节点；请先在画布中添加并行分支。",
            }
        branch = node_map.get(branch_id) or {}
        group = str(parallel_group or "").strip()
        worker_ids = [
            node_id
            for node_id in outgoing.get(branch_id, [])
            if node_id in node_map
            and node_id != merge_node_id
            and (not group or str(node_map[node_id].get("parallel_group") or "").strip() == group)
        ]
        if not worker_ids:
            return {
                "ok": False,
                "branch_node_id": branch_id,
                "error": "并行分支没有匹配的后续工作包。",
            }
        api_payloads = api_payloads or {}
        semaphore = asyncio.Semaphore(max(1, max_concurrency))

        async def run_worker(node_id: str) -> dict[str, Any]:
            async with semaphore:
                return await self._run_parallel_worker(
                    event=event,
                    task=task,
                    spec=spec,
                    node=node_map[node_id],
                    shared_instruction=shared_instruction,
                    api_payload=api_payloads.get(node_id) or {},
                )

        workers = [
            normalize_worker_output(item)
            for item in await asyncio.gather(*(run_worker(node_id) for node_id in worker_ids))
        ]
        merge_id = self._resolve_parallel_merge_id(
            spec,
            worker_ids,
            explicit_merge_id=merge_node_id,
        )
        ok_count = sum(1 for item in workers if item.get("ok"))
        summary = (
            f"并行分支 {branch_id} 完成 {ok_count}/{len(workers)} 个工作包。"
            f"{' 汇总到 ' + merge_id if merge_id else ' 未找到自动汇总节点。'}"
        )
        run = {
            "run_id": new_id("parallel"),
            "time": now_iso(),
            "ok": ok_count == len(workers),
            "branch_node_id": branch_id,
            "branch_title": branch.get("title") or branch_id,
            "parallel_group": group,
            "merge_node_id": merge_id,
            "summary": summary,
            "workers": workers,
        }
        task.add_parallel_run(run)
        task.last_observation = self._compact_text(
            json.dumps(run, ensure_ascii=False, indent=2),
            4000,
        )
        task.last_confirmed_progress = summary
        task.current_summary = summary
        task.next_step = (
            f"进入工作流节点 {merge_id}，合并并校验并行结果。"
            if merge_id
            else "检查并行结果，手动选择下一工作流节点。"
        )
        task.add_log("parallel_workflow", summary)
        task.add_snapshot(
            "parallel_workflow",
            {
                "branch_node_id": branch_id,
                "merge_node_id": merge_id,
                "worker_ids": worker_ids,
                "ok": run["ok"],
            },
        )
        for worker in workers:
            task.add_workflow_event(
                str(worker.get("node_id") or ""),
                status="completed" if worker.get("ok") else "blocked",
                outcome=str(worker.get("summary") or worker.get("error") or ""),
                note=str(worker.get("details") or "")[:1000],
                next_node_id=merge_id,
            )
            if hasattr(self, "agent_runtime"):
                node_id = str(worker.get("node_id") or "")
                summary_text = str(worker.get("summary") or worker.get("error") or "worker finished")
                worker_verdict = self.verifier.verify_worker(worker)
                self.agent_runtime.record_observation(
                    task,
                    source="parallel_worker",
                    node_id=node_id,
                    payload=worker,
                    summary=summary_text,
                )
                self.agent_runtime.record_verdict(
                    task,
                    node_id=node_id,
                    passed=worker_verdict.passed,
                    status=worker_verdict.status,
                    reason=worker_verdict.reason,
                    missing=worker_verdict.missing,
                    next_action=worker_verdict.next_action,
                )

        # Merge verification: check that worker results are sufficient.
        merge_verdict = self.verifier.verify_merge(
            workers,
            branch_node_id=branch_id,
            merge_node_id=merge_id,
        )
        run["merge_verdict"] = merge_verdict.to_dict()
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_verdict(
                task,
                node_id=merge_id or branch_id,
                passed=merge_verdict.passed,
                status=merge_verdict.status,
                reason=merge_verdict.reason,
                missing=merge_verdict.missing,
                next_action=merge_verdict.next_action,
            )

        self._advance_task_workflow(
            task,
            spec,
            node_id=branch_id,
            outcome=summary,
            next_node_id=merge_id,
            note="agent_lab_run_parallel_workflow",
            status="completed" if run["ok"] else "blocked",
        )
        return run

    def _resolve_parallel_branch_id(
        self,
        spec: AgentSpec,
        task: TaskState,
        branch_node_id: str = "",
    ) -> str:
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        requested = str(branch_node_id or "").strip()
        if requested and requested in node_map:
            return requested
        current = str(task.workflow_current_node_id or "").strip()
        if current in node_map and node_map[current].get("action") == "parallel_branch":
            return current
        for node in spec.workflow_nodes:
            if node.get("action") == "parallel_branch":
                return str(node.get("id") or "")
        return ""

    def _resolve_parallel_merge_id(
        self,
        spec: AgentSpec,
        worker_ids: list[str],
        *,
        explicit_merge_id: str = "",
    ) -> str:
        node_ids = {str(node.get("id") or "") for node in spec.workflow_nodes}
        explicit = str(explicit_merge_id or "").strip()
        if explicit and explicit in node_ids:
            return explicit
        outgoing = self._workflow_outgoing(spec)
        counts: dict[str, int] = {}
        for worker_id in worker_ids:
            for candidate in outgoing.get(worker_id, []):
                counts[candidate] = counts.get(candidate, 0) + 1
        if not counts:
            return ""
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        best, count = ranked[0]
        return best if count >= 2 or len(worker_ids) == 1 else ""

    async def _run_parallel_worker(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        node: dict[str, Any],
        shared_instruction: str = "",
        api_payload: Any = None,
    ) -> dict[str, Any]:
        node_id = str(node.get("id") or "").strip()
        kind = str(node.get("kind") or "state").strip()
        action = str(node.get("action") or "manual").strip()
        base = {
            "node_id": node_id,
            "title": node.get("title") or node_id,
            "kind": kind,
            "action": action,
            "parallel_group": node.get("parallel_group") or "",
            "worker_spec": worker_spec_for_node(node, allowed_tools=spec.enabled_tools).to_dict(),
            "ok": False,
            "status": "blocked",
            "summary": "",
            "details": "",
        }
        try:
            if kind == "api" or action == "call_api":
                if not self._tool_allowed_by_agent_profile(spec, CUSTOM_API_TOOL_NAME):
                    base["error"] = "Custom API worker is outside the Agent tool profile."
                    base["summary"] = base["error"]
                    return base
                return await self._run_parallel_api_worker(
                    node,
                    base,
                    api_payload=api_payload,
                )
            return await self._run_parallel_agent_worker(
                event=event,
                task=task,
                spec=spec,
                node=node,
                base=base,
                shared_instruction=shared_instruction,
            )
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
            base["summary"] = base["error"]
            return base

    async def _run_parallel_api_worker(
        self,
        node: dict[str, Any],
        base: dict[str, Any],
        *,
        api_payload: Any = None,
    ) -> dict[str, Any]:
        api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
        if not api_id:
            base["error"] = "API 节点未绑定 api_id。"
            base["summary"] = base["error"]
            return base
        query_json, body_json, headers_json = self._parallel_api_payload_json(api_payload)
        result, api_spec, message = await self._call_registered_custom_api(
            api_id,
            query_json=query_json,
            body_json=body_json,
            headers_json=headers_json,
        )
        if message:
            base["error"] = message
            base["summary"] = message
            return base
        base.update(
            {
                "ok": bool(result.get("ok")),
                "status": "completed" if result.get("ok") else "blocked",
                "api_id": api_spec.get("api_id") if api_spec else api_id,
                "summary": f"API {api_spec.get('api_id') if api_spec else api_id} status={result.get('status')}",
                "details": self._compact_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    1600,
                ),
            }
        )
        return base

    async def _run_parallel_agent_worker(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        node: dict[str, Any],
        base: dict[str, Any],
        shared_instruction: str = "",
    ) -> dict[str, Any]:
        plugin_name = str(
            node.get("plugin_name")
            or (node.get("ref_id") if node.get("ref_type") == "plugin" else "")
            or ""
        ).strip()
        if plugin_name and plugin_name in self._disabled_plugin_names(spec):
            base["error"] = f"插件模块被当前隔离策略禁用：{plugin_name}"
            base["summary"] = base["error"]
            return base
        provider_id = spec.provider_id or await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        worker_spec = worker_spec_for_node(node, allowed_tools=spec.enabled_tools)
        system_prompt = (
            f"{spec.system_prompt}\n\n"
            "[Agent Lab Parallel Worker]\n"
            f"worker_type={worker_spec.worker_type}\n"
            "你是当前 AstrBot 身份下的并行工作包执行者，不是新的 bot 人设。"
            "只完成本节点分配的工作；不要调用 agent_lab_finish，不要直接决定任务完成。"
            "如需使用工具，只能使用本节点允许的工具或插件来源工具，并遵守审批/白名单。"
        )
        prompt = self._parallel_worker_prompt(task, node, shared_instruction)
        resp = await self.context.tool_loop_agent(
            event=event,
            chat_provider_id=provider_id,
            prompt=prompt,
            system_prompt=system_prompt,
            tools=self._build_parallel_worker_toolset(spec, node),
            max_steps=max(1, min(int(_cfg(self.config, "parallel_worker_max_steps", 6) or 6), 12)),
            tool_call_timeout=int(_cfg(self.config, "tool_call_timeout", 120)),
            llm_compress_keep_recent=int(_cfg(self.config, "llm_compress_keep_recent", 4)),
            truncate_turns=int(_cfg(self.config, "truncate_turns", 2)),
            agent_hooks=AgentLabRunHooks(
                self.storage,
                task.umo,
                task.task_id,
                budget_max_tools=max(1, min(int(_cfg(self.config, "parallel_worker_max_steps", 6) or 6), 12)),
                progress_mode=str(_cfg(self.config, "agent_mode_progress_notice_mode", "agent_lab")),
                progress_every_tools=int(_cfg(self.config, "agent_mode_progress_every_tools", 3)),
                progress_min_interval_seconds=int(
                    _cfg(self.config, "agent_mode_progress_min_interval_seconds", 45)
                ),
            ),
            show_tool_use=(
                str(_cfg(self.config, "agent_mode_progress_notice_mode", "agent_lab")).strip().lower()
                in {"astrbot", "native"}
            ),
        )
        text = (getattr(resp, "completion_text", "") or "").strip()
        task.add_token_usage(getattr(resp, "usage", None))
        base.update(
            {
                "ok": True,
                "status": "completed",
                "summary": self._compact_text(text, 600) or "工作包已完成。",
                "details": self._compact_text(text, 2200),
            }
        )
        return base

    def _parallel_worker_prompt(
        self,
        task: TaskState,
        node: dict[str, Any],
        shared_instruction: str = "",
    ) -> str:
        worker_spec = worker_spec_for_node(node)
        return "\n".join(
            [
                "执行一个并行工作流节点，输出结构化结果。",
                f"- worker_type: {worker_spec.worker_type}",
                f"- output_schema: {json.dumps(worker_spec.output_schema, ensure_ascii=False)}",
                f"- task_id: {task.task_id}",
                f"- root_goal: {task.root_goal}",
                f"- current_summary: {task.current_summary or '-'}",
                f"- last_progress: {task.last_confirmed_progress or '-'}",
                f"- node_id: {node.get('id') or '-'}",
                f"- title: {node.get('title') or '-'}",
                f"- kind/action: {node.get('kind') or '-'} / {node.get('action') or '-'}",
                f"- instruction: {node.get('instruction') or node.get('description') or '-'}",
                f"- condition: {node.get('condition') or '-'}",
                f"- node_prompt: {node.get('prompt') or '-'}",
                f"- shared_instruction: {shared_instruction or '-'}",
                "",
                "输出必须包含：结论、证据/工具结果、风险、需要主 Agent 合并的字段。",
                "不要修改工作流，不要归档任务；由主 Agent 统一合并、校验和退出。",
            ]
        )

    def _build_parallel_worker_toolset(self, spec: AgentSpec, node: dict[str, Any]):
        from astrbot.core.agent.tool import ToolSet

        tmgr = self.context.get_llm_tool_manager()
        disabled_plugins = self._disabled_plugin_names(spec)
        toolset = ToolSet()
        kind = str(node.get("kind") or "").strip()
        ref_type = str(node.get("ref_type") or "").strip()
        tool_name = str(node.get("tool_name") or (node.get("ref_id") if ref_type == "tool" else "") or "").strip()
        plugin_name = str(node.get("plugin_name") or (node.get("ref_id") if ref_type == "plugin" else "") or "").strip()

        def tool_allowed_by_profile(name: str) -> bool:
            return self._tool_allowed_by_agent_profile(spec, name)

        def add_if_allowed(tool: Any) -> None:
            name = str(getattr(tool, "name", "") or "")
            if (
                tool
                and tool_allowed_by_profile(name)
                and self._tool_available_for_agent(tool, disabled_plugins)
            ):
                toolset.add_tool(tool)

        if kind == "tool" and tool_name:
            try:
                tool = tmgr.get_func(tool_name)
            except Exception:
                tool = None
            add_if_allowed(tool)
            return toolset
        if plugin_name:
            for tool in list(tmgr.func_list):
                if self._tool_plugin_name(tool) == plugin_name:
                    add_if_allowed(tool)
            return toolset
        if kind == "tool":
            allowed = set(spec.enabled_tools or [])
            for name in allowed:
                if name in {
                    NO_EXTERNAL_TOOLS_SENTINEL,
                    "agent_lab_enter_mode",
                    "agent_lab_tick",
                    "agent_lab_finish",
                    "agent_lab_update_workflow",
                    "agent_lab_run_parallel_workflow",
                }:
                    continue
                try:
                    tool = tmgr.get_func(name)
                except Exception:
                    tool = None
                add_if_allowed(tool)
        return toolset

    @staticmethod
    def _parallel_api_payload_json(api_payload: Any) -> tuple[str, str, str]:
        if not isinstance(api_payload, dict):
            return "", "", ""
        query = api_payload.get("query") or api_payload.get("query_json") or {}
        body = api_payload.get("body") if "body" in api_payload else api_payload.get("body_json", None)
        headers = api_payload.get("headers") or api_payload.get("headers_json") or {}
        return (
            query if isinstance(query, str) else json.dumps(query, ensure_ascii=False),
            body if isinstance(body, str) else ("" if body is None else json.dumps(body, ensure_ascii=False)),
            headers if isinstance(headers, str) else json.dumps(headers, ensure_ascii=False),
        )

    def _build_task_extensions_prompt(self, spec: AgentSpec, task: TaskState | None = None) -> str:
        sections = []
        pattern_prompt = self._build_task_pattern_prompt(
            task.root_goal if task else "",
            exclude_task_id=task.task_id if task else "",
        )
        if pattern_prompt.strip():
            sections.append(pattern_prompt)
        modules_prompt = self.modules.build_prompt(spec.module_ids, spec.module_settings)
        if modules_prompt.strip():
            sections.append(modules_prompt)
        skills_prompt = self._build_selected_skills_prompt(spec)
        if skills_prompt.strip():
            sections.append(skills_prompt)
        agent_mode_rule = self._build_agent_mode_skill_rule_prompt()
        if agent_mode_rule.strip():
            sections.append(agent_mode_rule)
        tool_risk_prompt = self._build_tool_risk_prompt(spec)
        if tool_risk_prompt.strip():
            sections.append(tool_risk_prompt)
        custom_api_prompt = self._build_custom_api_prompt(spec)
        if custom_api_prompt.strip():
            sections.append(custom_api_prompt)
        return "\n\n".join(sections)

    def _build_task_pattern_prompt(self, query: str = "", *, exclude_task_id: str = "") -> str:
        query = str(query or "").strip()
        return self.pattern_library.prompt_for(query, limit=3, exclude_task_id=exclude_task_id)

    def _build_exposed_task_memory_prompt(self) -> str:
        rows = []
        for item in reversed(self.storage.list_memory_entries()):
            if str(item.get("status") or "candidate").strip().lower() != "accepted":
                continue
            if not bool(item.get("expose_to_normal", True)):
                continue
            text = self._compact_text(str(item.get("text") or ""), 500)
            if not text:
                continue
            tags = ", ".join(str(tag) for tag in item.get("tags") or [])
            rows.append(
                f"- {item.get('memory_id')}: tags=[{tags or 'task'}]; "
                f"source_task={item.get('source_task_id') or '-'}; {text}"
            )
            if len(rows) >= 8:
                break
        if not rows:
            return ""
        return "\n".join(
            [
                "[Agent Lab Exposed Task Memory]",
                "以下是用户在 Agent Lab 中接受过的任务记忆，可供普通模式或新任务入口参考；不要把 candidate 记忆当作事实，更多条目可用 agent_lab_read_task_memory 查询。",
                *rows,
            ]
        )

    def _build_tool_risk_prompt(self, spec: AgentSpec) -> str:
        selected = set(spec.enabled_tools or [])
        if NO_EXTERNAL_TOOLS_SENTINEL in selected:
            return ""
        rows = []
        for row in self._tool_rows():
            if selected and row["name"] not in selected:
                continue
            risk = self._effective_tool_risk(spec, row["name"], row.get("risk", "work"))
            rows.append(
                f"- {row['name']}: risk={risk}; source={row.get('plugin_display_name') or row.get('source')}; "
                f"available={'yes' if row.get('effective_active') else 'no'}"
            )
        if not rows:
            return ""
        return "\n".join(
            [
                "[Agent Lab Tool Risk Policy]",
                "工具风险由 AgentSpec 配置。safe 通常可直接用；work 需确认当前任务授权；high 或命中 require_approval 的动作必须先向用户说明影响并请求审批。",
                "preapproved_scopes:",
                _lines_or_none(spec.approval_policy.preapproved_scopes),
                "require_approval:",
                _lines_or_none(spec.approval_policy.require_approval),
                "selected_tools:",
                *rows,
            ]
        )

    def _build_agent_mode_skill_rule_prompt(self) -> str:
        rule = self.storage.get_skill_rule(SKILL_NAME)
        content = str((rule or {}).get("content") or "").strip()
        if not content:
            return ""
        return "[Agent Mode Custom Skill Rules]\n" + content

    def _build_custom_api_prompt(self, spec: AgentSpec) -> str:
        if spec.enabled_tools and CUSTOM_API_TOOL_NAME not in spec.enabled_tools:
            return ""
        apis = self.storage.list_custom_apis()
        if not apis:
            return ""
        lines = [
            "[Agent Lab Custom APIs]",
            "以下 API 由管理员在 Agent Lab WebUI 注册。调用时只能使用 agent_lab_call_custom_api，并传入 api_id；不要请求或输出凭证值。",
        ]
        for item in apis:
            lines.append(
                "- "
                f"api_id={item.get('api_id')}; "
                f"name={item.get('name')}; "
                f"method={item.get('method')}; "
                f"auth={item.get('auth_type') or 'none'}; "
                f"description={item.get('description') or '-'}"
            )
        return "\n".join(lines)

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

    def _refresh_summarizer_rules(self) -> None:
        self.summarizer.config["entry_summary_system_prompt"] = self._summary_rule_content(
            ENTRY_SUMMARY_RULE_NAME
        )
        self.summarizer.config["exit_summary_system_prompt"] = self._summary_rule_content(
            EXIT_SUMMARY_RULE_NAME
        )

    def _summary_rule_content(self, rule_name: str) -> str:
        rule = self.storage.get_skill_rule(rule_name)
        return str((rule or {}).get("content") or "").strip()

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
                self._append_agent_mode_skill_rules(dst / "SKILL.md")
            SkillManager().set_skill_active(SKILL_NAME, True)
        except Exception as exc:
            logger.warning("[AgentLab] skill install failed: %s", exc)

    def _append_agent_mode_skill_rules(self, skill_path: Path) -> None:
        if not skill_path.exists():
            return
        sections = []
        for rule_name, title in (
            (SKILL_NAME, "Agent Lab 自定义规则"),
            (ENTRY_SUMMARY_RULE_NAME, "入口摘要规则"),
            (EXIT_SUMMARY_RULE_NAME, "出口归档规则"),
        ):
            rule = self.storage.get_skill_rule(rule_name)
            content = str((rule or {}).get("content") or "").strip()
            if content:
                sections.append(f"## {title}\n\n{content}")
        if not sections:
            return
        text = skill_path.read_text(encoding="utf-8")
        text = text.rstrip() + "\n\n" + "\n\n".join(sections) + "\n"
        skill_path.write_text(text, encoding="utf-8")

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
        static_dir = Path(__file__).resolve().parent / "webui"
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
        self.context.register_web_api(f"/{PLUGIN_NAME}/agents", self.api_agents, ["GET", "POST", "DELETE"], "Agent specs")
        self.context.register_web_api(f"/{PLUGIN_NAME}/workflow/check", self.api_workflow_check, ["GET", "POST"], "Check Agent workflow")
        self.context.register_web_api(f"/{PLUGIN_NAME}/workflow/dry-run", self.api_workflow_dry_run, ["GET", "POST"], "Dry-run Agent workflow")
        self.context.register_web_api(f"/{PLUGIN_NAME}/workflow/trigger", self.api_workflow_trigger, ["POST"], "Trigger workflow automation")
        self.context.register_web_api(f"/{PLUGIN_NAME}/workflow/webhook", self.api_workflow_webhook, ["POST"], "Workflow webhook trigger")
        self.context.register_web_api(f"/{PLUGIN_NAME}/modules", self.api_modules, ["GET", "POST"], "Agent modules")
        self.context.register_web_api(f"/{PLUGIN_NAME}/registry", self.api_registry, ["GET", "POST"], "Agent integrations registry")
        self.context.register_web_api(f"/{PLUGIN_NAME}/memory", self.api_memory, ["GET", "POST", "DELETE"], "Agent memory entries")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/logs", self.api_task_logs, ["GET"], "Task logs")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/start", self.api_task_start, ["POST"], "Start task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/tick", self.api_task_tick, ["POST"], "Tick task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/finish", self.api_task_finish, ["POST"], "Finish task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/cancel", self.api_task_cancel, ["POST"], "Cancel task")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/heartbeat", self.api_task_heartbeat, ["POST"], "Toggle heartbeat")
        self.context.register_web_api(f"/{PLUGIN_NAME}/task/approval", self.api_task_approval, ["POST"], "Resolve approval")

    async def api_state(self):
        self._sync_default_agent_identity()
        return jsonify(
            {
                "default_agent_id": self.storage.default_agent_id(),
                "agents": [item.to_dict() for item in self.storage.list_agents()],
                "tasks": [self._task_payload(item) for item in self.storage.list_tasks()],
                "archives": [
                    self._task_payload(item) for item in self.storage.list_archives()
                ],
                "plugins": self._plugin_rows(),
                "tools": self._tool_rows(),
                "skills": self._skill_rows(),
                "modules": self.modules.list_modules(),
                "integrations": self.modules.list_modules(),
                "custom_apis": self.storage.list_custom_apis(),
                "credentials": self.storage.list_credentials(),
                "skill_rules": self.storage.list_skill_rules(),
                "memories": self.storage.list_memory_entries(),
                "metrics": self._metrics_payload(),
                "webui": {
                    "standalone": bool(self.webui_server),
                    "url": self.webui_server.url if self.webui_server else "",
                    "auth": bool(self.webui_server and self.webui_server.token),
                },
                "runtime": self._runtime_identity_payload(),
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
            self._prepare_agent_spec_for_save(spec, previous_spec)
            self.storage.save_agent(spec)
            if make_default:
                self.storage.set_default_agent(spec.agent_id)
            return jsonify({"ok": True, "agent": spec.to_dict()})
        if request.method == "DELETE":
            payload = await request.get_json(force=True, silent=True) or {}
            agent_id = str(payload.get("agent_id") or request.args.get("agent_id") or "").strip()
            agents = self.storage.list_agents()
            if len(agents) <= 1:
                return jsonify({"ok": False, "error": "cannot delete the last agent"})
            if not any(item.agent_id == agent_id for item in agents):
                return jsonify({"ok": False, "error": "agent not found"})
            ok = self.storage.delete_agent(agent_id)
            next_default = self.storage.default_agent_id()
            if not next_default:
                remaining = self.storage.list_agents()
                if remaining:
                    self.storage.set_default_agent(remaining[0].agent_id)
                    next_default = remaining[0].agent_id
            return jsonify({"ok": ok, "default_agent_id": next_default})
        return jsonify(
            {
                "default_agent_id": self.storage.default_agent_id(),
                "agents": [item.to_dict() for item in self.storage.list_agents()],
            }
        )

    async def api_workflow_check(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            spec_payload = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
            spec = AgentSpec.from_dict(spec_payload)
            self._prepare_agent_spec_for_save(spec)
            return jsonify({"ok": True, "workflow": self._workflow_report(spec)})
        agent_id = str(request.args.get("agent_id") or "")
        spec = self.storage.get_agent(agent_id or None)
        self._normalize_agent_workflow(spec)
        return jsonify({"ok": True, "workflow": self._workflow_report(spec)})

    async def api_workflow_dry_run(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            spec_payload = payload.get("agent") if isinstance(payload.get("agent"), dict) else payload
            spec = AgentSpec.from_dict(spec_payload)
            self._prepare_agent_spec_for_save(spec)
        else:
            agent_id = str(request.args.get("agent_id") or "")
            spec = self.storage.get_agent(agent_id or None)
            self._normalize_agent_workflow(spec)
        workflow = self._workflow_report(spec)
        return jsonify(
            {
                "ok": True,
                "workflow": workflow,
                "dry_run": self._workflow_dry_run_report(spec, workflow),
            }
        )

    async def api_workflow_trigger(self):
        payload = await request.get_json(force=True, silent=True) or {}
        source = str(payload.get("source") or "manual_webui").strip()
        agent_id = str(payload.get("agent_id") or "").strip()
        text = str(payload.get("text") or payload.get("message") or payload.get("event_name") or source).strip()
        umo = str(
            payload.get("umo")
            or f"aiocqhttp:FriendMessage:agent_lab_workflow_{agent_id or 'default'}_{int(time.time() * 1000)}"
        ).strip()
        event = self._make_cron_event(umo, text or "Agent Lab workflow trigger")
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        trigger_payload = self._build_trigger_payload(
            source=source,
            event=event,
            text=text,
            data=payload,
        )
        result = await self._trigger_workflow_from_payload(
            event=event,
            source=source,
            payload=trigger_payload,
            agent_id=agent_id,
        )
        return jsonify(result)

    async def api_workflow_webhook(self):
        payload = await request.get_json(force=True, silent=True) or {}
        view_args = getattr(request, "view_args", None) or {}
        path = str(
            payload.get("webhook_path")
            or payload.get("path")
            or view_args.get("webhook_path")
            or request.args.get("path")
            or ""
        ).strip().strip("/")
        payload["webhook_path"] = path
        payload["source"] = "webhook"
        text = str(payload.get("text") or payload.get("message") or f"webhook:{path}").strip()
        umo = str(
            payload.get("umo")
            or f"aiocqhttp:FriendMessage:agent_lab_webhook_{path or 'default'}_{int(time.time() * 1000)}"
        ).strip()
        event = self._make_cron_event(umo, text)
        if event is None:
            return jsonify({"ok": False, "error": "cannot create event"})
        trigger_payload = self._build_trigger_payload(
            source="webhook",
            event=event,
            text=text,
            data=payload,
        )
        result = await self._trigger_workflow_from_payload(
            event=event,
            source="webhook",
            payload=trigger_payload,
            agent_id=str(payload.get("agent_id") or ""),
        )
        return jsonify(result)

    async def api_modules(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            try:
                module = self.modules.save_custom_module(payload)
            except Exception as exc:
                return jsonify({"ok": False, "error": str(exc)})
            return jsonify({"ok": True, "module": module.to_dict()})
        return jsonify({"modules": self.modules.list_modules()})

    async def api_registry(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            kind = str(payload.get("kind") or "api")
            if kind == "credential":
                return jsonify({"ok": True, "credential": self.storage.save_credential(payload)})
            if kind == "skill_rule":
                rule = self.storage.save_skill_rule(payload)
                self._sync_agent_mode_skill()
                return jsonify({"ok": True, "skill_rule": rule})
            return jsonify({"ok": True, "api": self.storage.save_custom_api(payload)})
        return jsonify(
            {
                "ok": True,
                "custom_apis": self.storage.list_custom_apis(),
                "credentials": self.storage.list_credentials(),
                "skill_rules": self.storage.list_skill_rules(),
            }
        )

    async def api_memory(self):
        if request.method == "POST":
            payload = await request.get_json(force=True, silent=True) or {}
            action = str(payload.get("action") or "").strip().lower()
            if action in {"accept", "approve"}:
                memory_id = str(payload.get("memory_id") or "")
                item = self.memory_manager.accept(
                    memory_id,
                    reviewer=str(payload.get("reviewer") or "webui"),
                    reason=str(payload.get("reason") or "webui accepted memory"),
                )
                return jsonify({"ok": bool(item), "memory": item})
            if action == "reject":
                memory_id = str(payload.get("memory_id") or "")
                item = self.memory_manager.reject(
                    memory_id,
                    reviewer=str(payload.get("reviewer") or "webui"),
                    reason=str(payload.get("reason") or "webui rejected memory"),
                )
                return jsonify({"ok": bool(item), "memory": item})
            return jsonify({"ok": True, "memory": self.storage.save_memory_entry(payload)})
        if request.method == "DELETE":
            payload = await request.get_json(force=True, silent=True) or {}
            memory_id = str(payload.get("memory_id") or request.args.get("memory_id") or "")
            return jsonify({"ok": self.storage.delete_memory_entry(memory_id)})
        return jsonify({"ok": True, "memories": self.storage.list_memory_entries()})

    async def api_task_logs(self):
        umo = str(request.args.get("umo") or "")
        task_id = str(request.args.get("task_id") or "")
        task = self.storage.load_active_task(umo)
        if not task:
            task = next(
                (
                    item
                    for item in self.storage.list_archives(umo or None)
                    if not task_id or item.task_id == task_id
                ),
                None,
            )
        if not task or (task_id and task.task_id != task_id):
            return jsonify({"ok": False, "error": "task not found"})
        return jsonify(
            {
                "ok": True,
                "logs": task.progress_log[-200:],
                "snapshots": task.state_snapshots[-80:],
                "token_usage": task.token_usage,
                "heartbeat_health": self._heartbeat_health(task),
            }
        )

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
        capabilities_by_plugin: dict[str, set[str]] = {}
        tool_count_by_plugin: dict[str, int] = {}
        try:
            tools = list(self.context.get_llm_tool_manager().func_list)
        except Exception:
            tools = []
        for tool in tools:
            plugin_name = self._tool_plugin_name(tool)
            if not plugin_name:
                continue
            capability = self._infer_capability(
                getattr(tool, "name", ""),
                getattr(tool, "description", ""),
                getattr(tool, "handler_module_path", ""),
            )
            capabilities_by_plugin.setdefault(plugin_name, set()).add(capability)
            tool_count_by_plugin[plugin_name] = tool_count_by_plugin.get(plugin_name, 0) + 1
        for plugin in self.context.get_all_stars():
            capabilities = sorted(
                item for item in capabilities_by_plugin.get(plugin.name, set()) if item
            )
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
                    "capabilities": capabilities,
                    "capability_summary": ", ".join(capabilities) if capabilities else "unknown",
                    "tool_count": tool_count_by_plugin.get(plugin.name, 0),
                }
            )
        return rows

    def _tool_rows(self) -> list[dict[str, Any]]:
        rows = []
        seen = set()
        builtin_risks = {item["name"]: item["risk"] for item in BUILTIN_TOOL_CATALOG}
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
                    "risk": builtin_risks.get(tool.name)
                    or self._infer_tool_risk(
                        tool.name,
                        getattr(tool, "description", ""),
                    ),
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
        for row in rows:
            self._hydrate_tool_registry_row(row)
        return rows

    def _hydrate_tool_registry_row(self, row: dict[str, Any]) -> None:
        name = str(row.get("name") or "")
        description = str(row.get("description") or "")
        handler_module_path = str(row.get("handler_module_path") or "")
        capability = self._infer_capability(name, description, handler_module_path)
        risk = str(row.get("risk") or self._infer_tool_risk(name, description))
        tool = None
        if row.get("source") == "registered":
            try:
                tool = self.context.get_llm_tool_manager().get_func(name)
            except Exception:
                tool = None
        parameters_schema = self._tool_schema(
            tool,
            name=name,
            description=description,
        )
        row.setdefault("risk", risk)
        row["capability"] = capability
        row["parameters_schema"] = parameters_schema
        row["input_schema"] = self._normalize_tool_input_schema(parameters_schema)
        row["output_schema"] = self._tool_output_schema(name, capability)
        row["permission_profiles"] = self._permission_profiles_for(capability, risk)

    @staticmethod
    def _normalize_tool_input_schema(parameters_schema: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(parameters_schema, dict):
            return {"type": "object", "properties": {}, "additionalProperties": True}
        if parameters_schema.get("type") == "object":
            return parameters_schema
        if "properties" in parameters_schema:
            return {
                "type": "object",
                "properties": parameters_schema.get("properties") or {},
                "required": parameters_schema.get("required") or [],
                "additionalProperties": parameters_schema.get("additionalProperties", True),
            }
        return {"type": "object", "properties": {}, "additionalProperties": True}

    @staticmethod
    def _tool_output_schema(name: str, capability: str) -> dict[str, Any]:
        if capability == "memory":
            return {
                "type": "object",
                "properties": {
                    "rows": {"type": "array"},
                    "memory_id": {"type": "string"},
                    "source_task_id": {"type": "string"},
                },
            }
        if capability in {"search", "web"}:
            return {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "results": {"type": "array"},
                    "sources": {"type": "array"},
                },
            }
        if capability == "file":
            return {
                "type": "object",
                "properties": {
                    "ok": {"type": "boolean"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            }
        return {
            "type": "object",
            "properties": {
                "ok": {"type": "boolean"},
                "tool_name": {"type": "string"},
                "result": {
                    "type": ["object", "array", "string", "number", "boolean", "null"],
                },
            },
            "description": f"Output produced by {name}.",
        }

    @staticmethod
    def _infer_tool_risk(name: str, description: str = "") -> str:
        text = f"{name} {description}".lower()
        high_keywords = (
            "delete",
            "remove",
            "reset",
            "clean",
            "deploy",
            "restart",
            "secret",
            "credential",
            "token",
            "password",
            "drop",
            "truncate",
            "migration",
            "system config",
        )
        if any(keyword in text for keyword in high_keywords):
            return "high"
        safe_keywords = (
            "read",
            "search",
            "grep",
            "list",
            "status",
            "query",
            "get",
            "fetch",
        )
        if any(keyword in text for keyword in safe_keywords):
            return "safe"
        work_keywords = (
            "write",
            "edit",
            "execute",
            "shell",
            "python",
            "call",
            "post",
            "update",
            "create",
        )
        if any(keyword in text for keyword in work_keywords):
            return "work"
        return "work"

    @staticmethod
    def _effective_tool_risk(
        spec: AgentSpec, tool_name: str, default: str = "work"
    ) -> str:
        risk = str((spec.tool_risk_overrides or {}).get(tool_name) or default or "work").strip()
        return risk if risk in {"safe", "work", "high"} else "work"

    def _skill_rows(self) -> list[dict[str, Any]]:
        try:
            from astrbot.core.skills.skill_manager import SkillManager

            return [item.__dict__ for item in SkillManager().list_skills(active_only=False)]
        except Exception:
            return []

    def _task_payload(self, task: TaskState) -> dict[str, Any]:
        payload = task.to_dict()
        payload["heartbeat_health"] = self._heartbeat_health(task)
        payload["agent_runtime_summary"] = self.agent_runtime.summary(task)
        return payload

    def _heartbeat_health(self, task: TaskState) -> dict[str, Any]:
        stale_after = self._heartbeat_stale_after_seconds(task)
        if task.status == "blocked":
            return {
                "state": "blocked",
                "tone": "bad",
                "message": "任务已阻塞",
                "last_pulse_at": task.heartbeat.last_pulse_at,
                "seconds_since_pulse": self._seconds_since(task.heartbeat.last_pulse_at),
                "stale_after_seconds": stale_after,
            }
        if not task.heartbeat.enabled:
            return {
                "state": "off",
                "tone": "warn",
                "message": "未开心跳",
                "last_pulse_at": task.heartbeat.last_pulse_at,
                "seconds_since_pulse": self._seconds_since(task.heartbeat.last_pulse_at),
                "stale_after_seconds": stale_after,
            }
        seconds = self._seconds_since(task.heartbeat.last_pulse_at)
        if seconds is None:
            return {
                "state": "idle",
                "tone": "warn",
                "message": "等待首次心跳",
                "last_pulse_at": task.heartbeat.last_pulse_at,
                "seconds_since_pulse": None,
                "stale_after_seconds": stale_after,
            }
        if seconds > stale_after:
            return {
                "state": "stale",
                "tone": "bad",
                "message": "心跳超时",
                "last_pulse_at": task.heartbeat.last_pulse_at,
                "seconds_since_pulse": seconds,
                "stale_after_seconds": stale_after,
            }
        return {
            "state": "online",
            "tone": "ok",
            "message": "心跳正常",
            "last_pulse_at": task.heartbeat.last_pulse_at,
            "seconds_since_pulse": seconds,
            "stale_after_seconds": stale_after,
        }

    @staticmethod
    def _heartbeat_stale_after_seconds(task: TaskState) -> int:
        cron = str(task.heartbeat.cron_expression or "*/5 * * * *").strip()
        interval_minutes = 5
        first = cron.split()[0] if cron.split() else ""
        if first.startswith("*/"):
            try:
                interval_minutes = max(1, int(first[2:]))
            except Exception:
                interval_minutes = 5
        return max(interval_minutes * 60 * 2, 120)

    @staticmethod
    def _seconds_since(iso_time: str) -> int | None:
        raw = str(iso_time or "").strip()
        if not raw:
            return None
        try:
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
        except Exception:
            return None
        return max(0, int((datetime.now(timezone.utc) - stamp.astimezone(timezone.utc)).total_seconds()))

    def _metrics_payload(self) -> dict[str, Any]:
        tasks = self.storage.list_tasks()
        archives = self.storage.list_archives()
        all_tasks = [*tasks, *archives]
        health_states = [self._heartbeat_health(task)["state"] for task in tasks]
        heartbeat_online = sum(1 for state in health_states if state == "online")
        heartbeat_stale = sum(1 for state in health_states if state in {"stale", "blocked"})
        heartbeat_offline = sum(1 for state in health_states if state in {"off", "idle"})
        pending_approvals = sum(len(task.pending_approvals()) for task in tasks)
        token_usage = sum(int(task.token_usage.get("total", 0) or 0) for task in all_tasks)
        return {
            "agents": len(self.storage.list_agents()),
            "active_tasks": len(tasks),
            "archived_tasks": len(archives),
            "heartbeat_online": heartbeat_online,
            "heartbeat_offline": heartbeat_offline,
            "heartbeat_stale": heartbeat_stale,
            "pending_approvals": pending_approvals,
            "task_triggers": len(tasks) + len(archives),
            "token_usage": token_usage,
            "token_usage_note": "来自 Agent Lab 捕获到的 provider usage；未上报 usage 的 provider 不计入。",
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
        plugin_rows = {item["name"]: item for item in self._plugin_rows() if item.get("name")}
        effective_overrides = self._effective_session_plugin_overrides(spec)
        disabled = {
            name
            for name, item in plugin_rows.items()
            if not bool(item.get("activated", True))
        }
        for plugin_name, enabled in effective_overrides.items():
            if plugin_name == PLUGIN_NAME:
                disabled.discard(plugin_name)
                continue
            plugin_row = plugin_rows.get(plugin_name)
            if plugin_row and not bool(plugin_row.get("activated", True)):
                disabled.add(plugin_name)
                continue
            if enabled:
                disabled.discard(plugin_name)
            else:
                disabled.add(plugin_name)
        return disabled

    def _effective_session_plugin_overrides(self, spec: AgentSpec) -> dict[str, bool]:
        mode = str(getattr(spec.isolation_policy, "mode", "strict") or "strict").strip()
        if mode == "off":
            return {}

        plugin_rows = {item["name"]: item for item in self._plugin_rows() if item.get("name")}
        overrides: dict[str, bool] = {}

        if mode == "strict":
            for name, row in plugin_rows.items():
                if name == PLUGIN_NAME:
                    overrides[name] = True
                    continue
                if bool(row.get("reserved", False)):
                    overrides[name] = True
                    continue
                if not bool(row.get("activated", True)):
                    overrides[name] = False
                    continue
                overrides[name] = False

        for plugin_name, enabled in (spec.plugin_overrides or {}).items():
            if not plugin_name:
                continue
            row = plugin_rows.get(plugin_name)
            if plugin_name == PLUGIN_NAME:
                overrides[plugin_name] = True
                continue
            if row and bool(row.get("reserved", False)):
                overrides[plugin_name] = True
                continue
            if row and not bool(row.get("activated", True)):
                overrides[plugin_name] = False
                continue
            overrides[plugin_name] = bool(enabled)

        if bool(getattr(spec.isolation_policy, "protect_self", True)):
            overrides[PLUGIN_NAME] = True
        return overrides

    def _tool_available_for_agent(self, tool: Any, disabled_plugins: set[str]) -> bool:
        if not bool(getattr(tool, "active", True)):
            return False
        plugin_name = self._tool_plugin_name(tool)
        if plugin_name and plugin_name in disabled_plugins:
            return False
        return True

    def _prepare_agent_spec_for_save(
        self, spec: AgentSpec, previous_spec: AgentSpec | None = None
    ) -> None:
        self._normalize_agent_identity_for_save(spec, previous_spec)
        self._normalize_agent_entry_settings(spec)
        self._normalize_agent_workflow(spec)
        self._upgrade_default_agent_tools(spec)
        self._sanitize_agent_enabled_tools(spec)

    @staticmethod
    def _normalize_agent_entry_settings(spec: AgentSpec) -> None:
        scope = str(getattr(spec, "application_scope", "") or "entry").strip()
        spec.application_scope = scope if scope in {"entry", "global"} else "entry"
        channel = str(getattr(spec, "entry_channel", "") or "command").strip()
        spec.entry_channel = channel if channel in {"command", "natural", "webui"} else "command"
        if spec.trigger_mode not in {"manual", "confirm", "smart", "always"}:
            spec.trigger_mode = "confirm"
        spec.workflow_trigger = WorkflowTrigger.from_dict(
            AgentLabPlugin._as_plain_dict(getattr(spec, "workflow_trigger", None))
        )
        spec.workflow_scope = WorkflowScope.from_dict(
            AgentLabPlugin._as_plain_dict(getattr(spec, "workflow_scope", None))
        )
        spec.entry_policy.trigger_phrases = AgentLabPlugin._clean_string_list(
            spec.entry_policy.trigger_phrases
        ) or ["进入任务模式", "开启任务模式", "进入 Agent Mode", "/agentlab start"]
        spec.entry_policy.trigger_keywords = AgentLabPlugin._clean_string_list(
            spec.entry_policy.trigger_keywords
        )
        spec.entry_policy.default_completion_conditions = AgentLabPlugin._clean_string_list(
            spec.entry_policy.default_completion_conditions
        ) or ["用户验收通过"]
        spec.entry_policy.exit_phrases = AgentLabPlugin._clean_string_list(
            spec.entry_policy.exit_phrases
        ) or ["完成任务", "结束任务模式", "退出 Agent Mode", "/agentlab finish"]
        spec.entry_policy.confirmation_text = str(
            spec.entry_policy.confirmation_text or ""
        ).strip()
        spec.isolation_policy.mode = (
            spec.isolation_policy.mode
            if spec.isolation_policy.mode in {"off", "session", "strict"}
            else "session"
        )
        spec.isolation_policy.tool_mode = (
            spec.isolation_policy.tool_mode
            if spec.isolation_policy.tool_mode in {"full", "whitelist", "no_external"}
            else "whitelist"
        )
        spec.isolation_policy.notes = str(spec.isolation_policy.notes or "").strip()

    @staticmethod
    def _as_plain_dict(value: Any) -> dict[str, Any] | None:
        if isinstance(value, dict):
            return value
        if hasattr(value, "to_dict"):
            try:
                return value.to_dict()
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            return dict(value.__dict__)
        return None

    def _workflow_scope_allows_event(
        self, spec: AgentSpec, event: AstrMessageEvent
    ) -> tuple[bool, str]:
        scope = WorkflowScope.from_dict(self._as_plain_dict(getattr(spec, "workflow_scope", None)))
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        sender_id = str(event.get_sender_id() or "").strip()
        platform = self._event_platform_name(event)
        is_private = bool(event.is_private_chat())
        chat_type = "private" if is_private else "group"

        if chat_type not in set(scope.chat_types or []):
            return False, f"chat_type={chat_type} not enabled"
        if scope.platforms and platform not in set(scope.platforms):
            return False, f"platform={platform or '-'} not allowed"
        if scope.umo_allowlist and umo not in set(scope.umo_allowlist):
            return False, "UMO not in allowlist"
        if scope.umo_denylist and umo in set(scope.umo_denylist):
            return False, "UMO is denied"
        group_id = self._event_group_id(event)
        if group_id:
            if scope.group_allowlist and group_id not in set(scope.group_allowlist):
                return False, "group not in allowlist"
            if scope.group_denylist and group_id in set(scope.group_denylist):
                return False, "group is denied"
        if scope.user_allowlist and sender_id not in set(scope.user_allowlist):
            return False, "user not in allowlist"
        if scope.user_denylist and sender_id in set(scope.user_denylist):
            return False, "user is denied"
        if scope.admin_only and sender_id not in set(self._workflow_admin_ids()):
            return False, "admin_only workflow"
        return True, "matched"

    def _workflow_admin_ids(self) -> list[str]:
        raw = _cfg(self.config, "workflow_admin_ids", []) or _cfg(self.config, "admin_qq_ids", [])
        return self._clean_string_list(raw)

    def _build_trigger_payload(
        self,
        *,
        source: str,
        event: AstrMessageEvent | None = None,
        text: str = "",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = dict(data or {})
        umo = str(getattr(event, "unified_msg_origin", "") or payload.get("umo") or "")
        sender_id = ""
        if event is not None:
            try:
                sender_id = str(event.get_sender_id() or "")
            except Exception:
                sender_id = ""
        payload.update(
            {
                "source": str(source or "manual").strip(),
                "text": str(text or payload.get("text") or payload.get("message") or ""),
                "umo": umo,
                "sender_id": sender_id or str(payload.get("sender_id") or ""),
                "group_id": self._event_group_id(event) if event is not None else str(payload.get("group_id") or ""),
                "platform": self._event_platform_name(event) if event is not None else str(payload.get("platform") or ""),
                "received_at": now_iso(),
            }
        )
        return payload

    def _workflow_trigger_matches(
        self,
        spec: AgentSpec,
        event: AstrMessageEvent,
        *,
        source: str,
        payload: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        trigger = WorkflowTrigger.from_dict(self._as_plain_dict(getattr(spec, "workflow_trigger", None)))
        if not trigger.enabled:
            return False, "trigger disabled"
        types = set(trigger.types or [])
        source = str(source or "").strip().lower()
        source_type = {
            "message": "message_monitor",
            "message_monitor": "message_monitor",
            "natural": "natural",
            "keyword": "keyword",
            "regex": "regex",
            "schedule": "schedule",
            "plugin_event": "plugin_event",
            "webhook": "webhook",
            "manual_webui": "manual_webui",
            "command": "command",
        }.get(source, source)
        if source_type not in types and source not in types:
            return False, f"source={source or '-'} not enabled"
        payload = payload or {}
        text = str(payload.get("text") or getattr(event, "message_str", "") or "").lower()
        if source_type in {"keyword", "message_monitor", "natural"} and trigger.keywords:
            if not any(keyword.lower() in text for keyword in trigger.keywords):
                return False, "keyword not matched"
        if source_type == "regex" or (source_type in {"message_monitor", "natural"} and trigger.regex):
            if trigger.regex:
                matched = False
                for pattern in trigger.regex:
                    try:
                        if re.search(pattern, text, flags=re.IGNORECASE):
                            matched = True
                            break
                    except re.error:
                        continue
                if not matched:
                    return False, "regex not matched"
        if source_type == "plugin_event" and trigger.plugin_events:
            event_name = str(payload.get("event_name") or payload.get("name") or "").strip()
            if event_name not in set(trigger.plugin_events):
                return False, "plugin event not matched"
        if source_type == "webhook" and trigger.webhook_path:
            requested = str(payload.get("webhook_path") or payload.get("path") or "").strip().strip("/")
            expected = trigger.webhook_path.strip().strip("/")
            if requested != expected:
                return False, "webhook path not matched"
        return True, "matched"

    def _candidate_workflows_for_trigger(
        self,
        event: AstrMessageEvent,
        *,
        source: str,
        payload: dict[str, Any] | None = None,
        agent_id: str = "",
    ) -> list[AgentSpec]:
        candidates: list[AgentSpec] = []
        specs = [self.storage.get_agent(agent_id)] if agent_id else self.storage.list_agents()
        default_id = self.storage.default_agent_id()
        specs = sorted(specs, key=lambda item: 0 if item.agent_id == default_id else 1)
        for spec in specs:
            if not spec.enabled:
                continue
            self._normalize_agent_workflow(spec)
            allowed, _ = self._workflow_scope_allows_event(spec, event)
            if not allowed:
                continue
            matched, _ = self._workflow_trigger_matches(spec, event, source=source, payload=payload)
            if matched:
                candidates.append(spec)
        return candidates

    async def _trigger_workflow_from_payload(
        self,
        *,
        event: AstrMessageEvent,
        source: str,
        payload: dict[str, Any],
        agent_id: str = "",
    ) -> dict[str, Any]:
        specs = self._candidate_workflows_for_trigger(
            event,
            source=source,
            payload=payload,
            agent_id=agent_id,
        )
        if not specs:
            return {"ok": False, "error": "no matching workflow", "source": source}
        spec = specs[0]
        text = str(payload.get("text") or payload.get("message") or source or "workflow trigger").strip()
        message = await self._start_task(
            event,
            goal=text or f"Workflow trigger: {source}",
            completion_conditions="Workflow automation route completed.",
            brief=json.dumps(payload, ensure_ascii=False, default=str),
            request_heartbeat=False,
            source=f"workflow:{source}",
            risk_level=str(payload.get("risk_level") or "work"),
            agent_id=spec.agent_id,
            trigger_payload=payload,
            auto_run=True,
        )
        return {"ok": True, "agent_id": spec.agent_id, "message": message}

    @staticmethod
    def _event_group_id(event: AstrMessageEvent) -> str:
        for name in ("get_group_id", "get_groupid"):
            fn = getattr(event, name, None)
            if callable(fn):
                try:
                    value = str(fn() or "").strip()
                    if value:
                        return value
                except Exception:
                    pass
        for name in ("group_id", "groupid"):
            value = str(getattr(event, name, "") or "").strip()
            if value:
                return value
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        parts = [part for part in re.split(r"[:/]", umo) if part]
        if len(parts) >= 3 and any("group" in part.lower() for part in parts[:2]):
            return parts[-1]
        return ""

    @staticmethod
    def _clean_string_list(items: Any) -> list[str]:
        if isinstance(items, str):
            items = re.split(r"[\r\n,，、]+", items)
        if not isinstance(items, list):
            return []
        cleaned = []
        seen = set()
        for item in items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        return cleaned[:80]

    @classmethod
    def _normalize_agent_workflow(cls, spec: AgentSpec) -> None:
        raw_nodes = spec.workflow_nodes if isinstance(spec.workflow_nodes, list) else []
        if not raw_nodes:
            raw_nodes = AgentSpec().workflow_nodes

        used_ids: set[str] = set()
        id_map: dict[str, str] = {}
        nodes: list[dict[str, Any]] = []
        for index, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                raw_node = {}
            old_id = str(raw_node.get("id") or "").strip()
            node_id = cls._unique_workflow_id(
                cls._normalize_workflow_id(old_id or f"node_{index + 1}"),
                used_ids,
            )
            if old_id:
                id_map[old_id] = node_id
            used_ids.add(node_id)
            title = str(raw_node.get("title") or node_id).strip() or node_id
            kind = str(raw_node.get("kind") or "state").strip()
            if kind not in WORKFLOW_KINDS:
                kind = "state"
            stage = cls._workflow_stage(raw_node, kind)
            action = str(raw_node.get("action") or "manual").strip() or "manual"
            description = str(raw_node.get("description") or "").strip()
            instruction = str(
                raw_node.get("instruction") or description or title
            ).strip()
            normalized = {str(key): value for key, value in raw_node.items()}
            normalized.update(
                {
                    "id": node_id,
                    "title": title[:80],
                    "kind": kind,
                    "stage": stage,
                    "action": action[:80],
                    "description": description[:500],
                    "instruction": instruction[:1000],
                    "x": cls._clamp_int(raw_node.get("x"), -1400, 12000, 70 + index * 260),
                    "y": cls._clamp_int(raw_node.get("y"), -1400, 8000, 120),
                }
            )
            NodeExecutorRegistry.normalize_node_runtime_type(normalized)
            NodeExecutorRegistry.normalize_execution_mode(normalized)
            for schema_key in ("input_schema", "output_schema"):
                schema = cls._workflow_json_object(normalized.get(schema_key))
                if schema:
                    normalized[schema_key] = schema
                elif schema_key in normalized:
                    normalized.pop(schema_key, None)
            required_inputs = cls._clean_string_list(
                normalized.get("required_inputs") or normalized.get("required_input")
            )
            if required_inputs:
                normalized["required_inputs"] = required_inputs
            output_variables = cls._clean_string_list(
                normalized.get("output_variables") or normalized.get("outputs")
            )
            if output_variables:
                normalized["output_variables"] = output_variables
            retry_policy = cls._normalize_retry_policy(normalized.get("retry_policy"))
            if retry_policy:
                normalized["retry_policy"] = retry_policy
            elif "retry_policy" in normalized:
                normalized.pop("retry_policy", None)
            try:
                timeout_seconds = int(normalized.get("timeout_seconds") or 0)
            except Exception:
                timeout_seconds = 0
            if timeout_seconds > 0:
                normalized["timeout_seconds"] = max(1, min(timeout_seconds, 600))
            elif "timeout_seconds" in normalized:
                normalized.pop("timeout_seconds", None)
            for bool_key in ("interrupt_before", "interrupt_after"):
                if bool_key in normalized:
                    normalized[bool_key] = bool(normalized.get(bool_key))
            for key, limit in (
                ("ref_type", 32),
                ("ref_id", 160),
                ("api_id", 160),
                ("plugin_name", 160),
                ("tool_name", 160),
                ("skill_name", 160),
                ("condition", 1000),
                ("route_variable", 160),
                ("variable_name", 160),
                ("template_id", 160),
                ("path", 500),
                ("url", 500),
                ("method", 16),
                ("operation", 80),
                ("edit_mode", 32),
                ("permission_profile", 32),
                ("parallel_group", 80),
                ("prompt", 4000),
            ):
                if key in normalized:
                    normalized[key] = str(normalized.get(key) or "").strip()[:limit]
            nodes.append(normalized)

        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str, str]] = set()
        for raw_edge in spec.workflow_edges if isinstance(spec.workflow_edges, list) else []:
            if not isinstance(raw_edge, dict):
                continue
            start = id_map.get(str(raw_edge.get("from") or "").strip(), str(raw_edge.get("from") or "").strip())
            end = id_map.get(str(raw_edge.get("to") or "").strip(), str(raw_edge.get("to") or "").strip())
            if start not in used_ids or end not in used_ids or start == end:
                continue
            edge_type = cls._normalize_workflow_edge_type(raw_edge.get("edge_type") or raw_edge.get("type"))
            condition = str(raw_edge.get("condition") or raw_edge.get("when") or "").strip()[:1000]
            key = (start, end, edge_type, condition)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge = {"from": start, "to": end, "edge_type": edge_type}
            if condition:
                edge["condition"] = condition
            condition_visual = raw_edge.get("condition_visual")
            if isinstance(condition_visual, dict):
                edge["condition_visual"] = condition_visual
            elif isinstance(condition_visual, str) and condition_visual.strip():
                edge["condition_visual"] = condition_visual.strip()[:1000]
            label = str(raw_edge.get("label") or "").strip()
            if label:
                edge["label"] = label[:120]
            edges.append(edge)
        if not edges and len(nodes) > 1:
            edges = [
                {"from": nodes[index]["id"], "to": nodes[index + 1]["id"], "edge_type": "success"}
                for index in range(len(nodes) - 1)
            ]

        spec.workflow_nodes = nodes
        spec.workflow_edges = edges

    @staticmethod
    def _normalize_workflow_id(value: str) -> str:
        value = re.sub(r"\s+", "_", str(value or "").strip())
        value = re.sub(r"[^A-Za-z0-9_-]", "", value)
        return value[:64] or "node"

    @staticmethod
    def _workflow_json_object(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _normalize_workflow_edge_type(raw: Any) -> str:
        edge_type = str(raw or "success").strip().lower()
        valid = {
            "success",
            "failed",
            "uncertain",
            "error",
            "retry",
            "timeout",
            "approved",
            "rejected",
            "always",
        }
        return edge_type if edge_type in valid else "success"

    @staticmethod
    def _normalize_retry_policy(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str) and raw.strip():
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            return {}
        try:
            max_attempts = max(1, min(int(raw.get("max_attempts") or raw.get("attempts") or 1), 8))
        except Exception:
            max_attempts = 1
        backoff = str(raw.get("backoff") or "none").strip().lower()
        if backoff not in {"none", "linear", "exponential"}:
            backoff = "none"
        retry_on = raw.get("retry_on") if isinstance(raw.get("retry_on"), list) else ["error", "timeout"]
        return {
            "max_attempts": max_attempts,
            "backoff": backoff,
            "retry_on": [str(item).strip() for item in retry_on if str(item).strip()],
        }

    @classmethod
    def _unique_workflow_id(cls, value: str, used_ids: set[str]) -> str:
        root = cls._normalize_workflow_id(value)
        if root not in used_ids:
            return root
        index = 2
        while f"{root}_{index}" in used_ids:
            index += 1
        return f"{root}_{index}"

    @staticmethod
    def _workflow_stage(node: dict[str, Any], kind: str) -> str:
        stage = str(node.get("stage") or "").strip()
        if stage in {"entry", "plan", "execute", "guard", "checkpoint", "archive"}:
            return stage
        text = f"{node.get('id') or ''} {node.get('title') or ''}".lower()
        if "entry" in text or "入口" in text:
            return "entry"
        if "checkpoint" in text or "快照" in text or "状态" in text:
            return "checkpoint"
        if "archive" in text or "归档" in text or "出口" in text:
            return "archive"
        if kind in {"retrieval", "branch"} or "router" in text or "分流" in text:
            return "plan"
        if kind in {"tool", "api", "transform", "subflow"} or "execute" in text or "执行" in text:
            return "execute"
        if kind in {"validation", "loop"} or "校验" in text:
            return "checkpoint"
        if kind in {"notification"}:
            return "archive"
        if kind in {"guard", "human"} or "approval" in text or "heartbeat" in text:
            return "guard"
        return "plan"

    @staticmethod
    def _workflow_default_position(stage: str, index: int) -> tuple[int, int]:
        stage_order = ["entry", "plan", "execute", "guard", "checkpoint", "archive"]
        try:
            stage_index = stage_order.index(stage)
        except ValueError:
            stage_index = 1
        return 70 + stage_index * 560, 110 + (index % 6) * 215

    def _autolayout_workflow(self, spec: AgentSpec) -> None:
        self._normalize_agent_workflow(spec)
        stage_order = ["entry", "plan", "execute", "guard", "checkpoint", "archive"]
        grouped: dict[str, list[dict[str, Any]]] = {stage: [] for stage in stage_order}
        for node in spec.workflow_nodes:
            grouped.setdefault(str(node.get("stage") or "plan"), []).append(node)
        for stage_index, stage in enumerate(stage_order):
            for row_index, node in enumerate(grouped.get(stage, [])):
                node["x"] = 70 + stage_index * 560
                node["y"] = 110 + row_index * 215

    def _workflow_report(self, spec: AgentSpec) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        nodes = [item for item in spec.workflow_nodes if isinstance(item, dict)]
        edges = [item for item in spec.workflow_edges if isinstance(item, dict)]
        node_ids = {str(item.get("id") or "") for item in nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        incoming: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if start in outgoing and end in incoming:
                outgoing[start].append(end)
                incoming[end].append(start)

        issues: list[dict[str, str]] = []

        def add_issue(level: str, code: str, message: str, node_id: str = "") -> None:
            issues.append(
                {
                    "level": level,
                    "code": code,
                    "message": message,
                    "node_id": node_id,
                }
            )

        trigger_actions = {
            "listen_message",
            "schedule_trigger",
            "plugin_event_trigger",
            "webhook_trigger",
        }
        detector_actions = {"match_keyword", "match_regex", "llm_detect", "scope_filter"}
        report_actions = {
            "notify",
            "send_message",
            "send_private_message",
            "send_email",
            "write_record",
            "generate_report",
        }
        entry_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "entry"
            or node.get("kind") == "trigger"
            or node.get("action") in {"summarize_entry", "confirm_entry", *trigger_actions}
        ]
        terminal_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("action") in {"archive", "exit_summary"}
            or (
                node.get("stage") == "archive"
                and node.get("action") not in {"notify", "manual"}
            )
            or node.get("kind") == "report"
            or node.get("action") in report_actions
        ]
        archive_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "archive" or node.get("action") in {"archive", "exit_summary", "notify"}
        ]
        guard_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "guard" or node.get("kind") in {"guard", "human"}
        ]
        has_approval_gate = any(
            node.get("stage") == "guard"
            or node.get("kind") in {"guard", "human"}
            or node.get("action") in {"request_approval", "wait_user", "handoff"}
            for node in nodes
        )
        action_ids: dict[str, list[str]] = {}
        runtime_type_ids: dict[str, list[str]] = {}
        executor_nodes: list[str] = []
        react_handoff_nodes: list[str] = []
        node_runtime: dict[str, dict[str, Any]] = {}
        for node in nodes:
            node_id = str(node.get("id") or "")
            action = str(node.get("action") or "")
            runtime_type = NodeExecutorRegistry.runtime_type(node)
            has_executor = self.node_executors.can_execute(node)
            action_ids.setdefault(action, []).append(node_id)
            runtime_type_ids.setdefault(runtime_type, []).append(node_id)
            if has_executor:
                executor_nodes.append(node_id)
            if not has_executor or action in {"plan", "manual"} or runtime_type in {"react", "terminal"}:
                react_handoff_nodes.append(node_id)
            node_runtime[node_id] = {
                "runtime_type": runtime_type,
                "action": action,
                "has_executor": has_executor,
                "react_handoff": node_id in react_handoff_nodes,
            }
        if not entry_ids:
            add_issue("error", "missing_entry", "工作流缺少入口节点。")
        if not terminal_ids:
            add_issue("error", "missing_archive", "工作流缺少真正的出口/归档节点，需要 archive 或 exit_summary 动作。")
        if not guard_ids:
            add_issue("warn", "missing_guard", "工作流没有审批或人工闸门，高风险任务可能无法停下确认。")
        if not any(action in action_ids for action in {"summarize_entry", *trigger_actions}):
            add_issue("warn", "missing_entry_summary", "工作流没有入口摘要节点，普通聊天上文可能无法干净压缩成 task_brief。")
        if any(action in action_ids for action in trigger_actions) and not any(
            action in action_ids for action in detector_actions
        ):
            add_issue("warn", "trigger_without_detector", "监听、定时或事件触发工作流建议接入检测器、范围过滤或条件分支。")
        if spec.entry_policy.require_confirmation and "confirm_entry" not in action_ids:
            add_issue("warn", "missing_entry_confirmation", "当前 AgentSpec 要求开启确认，但工作流没有 confirm_entry 节点。")
        if spec.isolation_policy.mode != "off" and "restore_isolation" not in action_ids:
            add_issue("warn", "missing_isolation_snapshot", "隔离模式已开启，但工作流没有隔离快照/恢复节点。")
        if "save_memory" not in action_ids:
            add_issue("warn", "missing_task_memory", "工作流没有任务记忆节点，续写信息可能只停留在 task_state。")
        if "exit_summary" not in action_ids:
            add_issue("warn", "missing_exit_summary", "工作流没有出口摘要节点，任务成果和可回流记忆可能不完整。")

        reachable: set[str] = set()
        stack = list(entry_ids)
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(outgoing.get(current, []))
        for node in nodes:
            node_id = str(node.get("id") or "")
            if entry_ids and node_id not in reachable:
                add_issue("warn", "unreachable_node", "入口无法到达该节点。", node_id)
            if node_id not in entry_ids and not incoming.get(node_id):
                add_issue("warn", "missing_input", "节点没有输入连线。", node_id)
            if node_id not in terminal_ids and not outgoing.get(node_id):
                add_issue("warn", "missing_output", "非出口节点没有输出连线。", node_id)
            if node_id in terminal_ids and outgoing.get(node_id):
                add_issue("warn", "terminal_has_output", "出口/归档节点通常不应再连到其他节点。", node_id)
            if node.get("kind") in {"branch", "detector"} and len(outgoing.get(node_id, [])) < 2:
                add_issue("warn", "branch_single_path", "分支节点最好至少有两条输出连线。", node_id)
            if node.get("action") == "parallel_branch":
                workers = outgoing.get(node_id, [])
                if len(workers) < 2:
                    add_issue("warn", "parallel_without_workers", "并行 Agent 分支至少需要两个后续工作包。", node_id)
            if node.get("kind") == "detector":
                edge_types = {
                    str(edge.get("edge_type") or "success")
                    for edge in edges
                    if edge.get("from") == node_id
                }
                if not edge_types.intersection({"success", "failed", "uncertain", "error"}):
                    add_issue("warn", "detector_without_result_routes", "检测模块建议显式配置通过/失败/不确定/错误出口。", node_id)
            if node.get("kind") == "loop" or node.get("action") == "retry":
                edge_types = {
                    str(edge.get("edge_type") or "success")
                    for edge in edges
                    if edge.get("from") == node_id
                }
                if not edge_types.intersection({"retry", "failed", "error"}):
                    add_issue("warn", "retry_without_retry_routes", "循环/重试模块建议配置 retry、failed 或 error 出口。", node_id)
            if node.get("kind") in {"subflow", "tool", "api"} and node.get("action") in {"manual", ""} and not str(node.get("prompt") or "").strip():
                add_issue("warn", "module_without_prompt", "模块节点建议写入节点提示词或明确动作，否则运行时只能依赖泛化说明。", node_id)
            node_text = " ".join(
                str(node.get(key) or "")
                for key in ("title", "description", "instruction", "prompt", "action", "kind")
            ).lower()
            file_like = bool(
                re.search(
                    r"file|path|document|write|delete|remove|\brm\b|patch|edit|文件|文档|路径|删除|写入|改动",
                    node_text,
                )
            )
            dangerous = bool(
                re.search(
                    r"delete|remove|\brm\b|deploy|write|patch|edit|restart|credential|删除|写入|部署|重启|密钥|覆盖",
                    node_text,
                )
            )
            if file_like and not str(
                node.get("path")
                or node.get("url")
                or node.get("input_variable")
                or node.get("ref_id")
                or ""
            ).strip():
                add_issue("warn", "file_node_without_input", "文件/文档类模块需要写清 path、url 或上游变量。", node_id)
            if dangerous and not has_approval_gate and node.get("stage") != "guard":
                add_issue("warn", "danger_without_approval", "高风险写入/删除/部署动作前建议接入审批模块。", node_id)
            if node.get("action") == "save_memory" and not str(
                node.get("tags") or node.get("memory_tags") or node.get("prompt") or node.get("instruction") or ""
            ).strip():
                add_issue("warn", "memory_without_schema", "任务记忆模块需要写清标签、摘要规则或保存字段。", node_id)
            if node.get("kind") == "api" or node.get("action") == "call_api":
                api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
                if api_id:
                    api_spec = self.storage.get_custom_api(api_id)
                    if not api_spec:
                        add_issue("error", "missing_api", f"未找到引用的自定义 API：{api_id}", node_id)
                    elif not api_spec.get("url"):
                        add_issue("error", "api_without_url", f"自定义 API 未配置 URL：{api_id}", node_id)
                else:
                    add_issue("warn", "api_unbound", "API 节点尚未绑定具体自定义 API。", node_id)
            plugin_name = str(node.get("plugin_name") or "").strip()
            if plugin_name:
                plugin = next((item for item in self._plugin_rows() if item.get("name") == plugin_name), None)
                if not plugin:
                    add_issue("warn", "missing_plugin", f"未找到引用的 AstrBot 插件：{plugin_name}", node_id)
                elif not bool(plugin.get("activated", True)):
                    add_issue("warn", "plugin_inactive", f"引用插件当前未启用：{plugin_name}", node_id)
                elif plugin_name in self._disabled_plugin_names(spec):
                    add_issue("warn", "plugin_isolated", f"引用插件会被当前 AgentSpec 隔离策略关闭：{plugin_name}", node_id)
            tool_name = str(node.get("tool_name") or "").strip()
            if tool_name:
                tool = next((item for item in self._tool_rows() if item.get("name") == tool_name), None)
                if not tool:
                    add_issue("warn", "missing_tool", f"未找到引用工具：{tool_name}", node_id)
                elif not bool(tool.get("effective_active", tool.get("active", True))):
                    add_issue("warn", "tool_inactive", f"引用工具当前不可用：{tool_name}", node_id)
                elif (
                    spec.isolation_policy.tool_mode == "whitelist"
                    and spec.enabled_tools
                    and NO_EXTERNAL_TOOLS_SENTINEL not in set(spec.enabled_tools or [])
                    and tool_name not in set(spec.enabled_tools or [])
                ):
                    add_issue("warn", "tool_not_whitelisted", f"引用工具不在当前 AgentSpec 工具白名单中：{tool_name}", node_id)

        node_lookup = {str(item.get("id") or ""): item for item in nodes}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            source_node = node_lookup.get(start) or {}
            target_node = node_lookup.get(end) or {}
            source_schema = self._node_schema(source_node, "output_schema")
            target_schema = self._node_schema(target_node, "input_schema")
            if source_schema and target_schema and not schema_compatible(source_schema, target_schema):
                add_issue(
                    "warn",
                    "schema_incompatible_edge",
                    f"Node schema mismatch: {start} output cannot feed {end} input.",
                    end,
                )

        if entry_ids and terminal_ids and not any(node_id in reachable for node_id in terminal_ids):
            add_issue("error", "archive_unreachable", "入口路径无法到达任何出口/归档节点。")

        errors = sum(1 for item in issues if item["level"] == "error")
        warnings = sum(1 for item in issues if item["level"] == "warn")
        return {
            "valid": errors == 0,
            "errors": errors,
            "warnings": warnings,
            "nodes": len(nodes),
            "edges": len(edges),
            "entry_nodes": entry_ids,
            "archive_nodes": archive_ids,
            "terminal_nodes": terminal_ids,
            "guard_nodes": guard_ids,
            "memory_nodes": action_ids.get("save_memory", []),
            "runtime_types": runtime_type_ids,
            "executor_nodes": executor_nodes,
            "react_handoff_nodes": react_handoff_nodes,
            "node_runtime": node_runtime,
            "issues": issues,
        }

    def _workflow_dry_run_report(
        self, spec: AgentSpec, workflow: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        workflow = workflow or self._workflow_report(spec)
        nodes = [item for item in spec.workflow_nodes if isinstance(item, dict)]
        edges = [item for item in spec.workflow_edges if isinstance(item, dict)]
        node_map = {str(node.get("id") or ""): node for node in nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        incoming: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if start in node_map and end in node_map:
                outgoing.setdefault(start, []).append(end)
                incoming.setdefault(end, []).append(start)

        entry_ids = list(workflow.get("entry_nodes") or []) or [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "entry" or node.get("action") in {"summarize_entry", "confirm_entry"}
        ]
        terminal_ids = set(workflow.get("terminal_nodes") or [])
        current = entry_ids[0] if entry_ids else ""
        primary_path: list[str] = []
        visited: set[str] = set()
        while current and current not in visited and len(primary_path) < 80:
            visited.add(current)
            primary_path.append(current)
            if current in terminal_ids:
                break
            candidates = outgoing.get(current, [])
            if not candidates:
                break
            current = candidates[0]

        branch_nodes = [
            node_id
            for node_id, node in node_map.items()
            if node.get("kind") == "branch" or len(outgoing.get(node_id, [])) > 1
        ]
        parallel_nodes = [
            node_id
            for node_id, node in node_map.items()
            if node.get("action") == "parallel_branch"
        ]
        merge_candidates = [
            node_id
            for node_id, inputs in incoming.items()
            if len(inputs) > 1
        ]
        notes: list[dict[str, str]] = []

        def add_note(level: str, message: str, node_id: str = "") -> None:
            notes.append({"level": level, "message": message, "node_id": node_id})

        if not entry_ids:
            add_note("error", "无法预跑：没有入口节点。")
        if not terminal_ids:
            add_note("error", "无法证明能结束：没有出口/归档节点。")
        if primary_path and primary_path[-1] not in terminal_ids:
            add_note("warn", "主路径没有抵达出口模块，请检查断开的连线。", primary_path[-1])
        if parallel_nodes and not merge_candidates:
            add_note("warn", "发现并行分支，但没有明显的多输入汇总节点。", parallel_nodes[0])
        for node_id in branch_nodes:
            if len(outgoing.get(node_id, [])) < 2:
                add_note("warn", "分支/条件节点输出不足，预跑只能走单路径。", node_id)
        for node_id in primary_path:
            node = node_map.get(node_id, {})
            if node.get("kind") == "api" or node.get("action") == "call_api":
                api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
                add_note("info" if api_id else "warn", f"API 节点绑定：{api_id or '未绑定'}。", node_id)
            if node.get("action") in {"request_approval", "wait_user", "handoff"} or node.get("kind") in {"guard", "human"}:
                add_note("info", "预跑会在这里等待用户确认或审批，不会自动越过。", node_id)
            if node.get("action") == "save_memory":
                add_note("info", "任务记忆节点会写入独立记忆区，退出后可回看/续写。", node_id)

        executable = bool(workflow.get("valid")) and bool(primary_path) and (
            not terminal_ids or primary_path[-1] in terminal_ids
        )
        if not notes:
            add_note("ok", "静态预跑未发现阻塞；真实执行仍会受审批、工具可用性和模型判断影响。")
        return {
            "summary": "静态预跑完成" if executable else "静态预跑发现阻塞",
            "executable": executable,
            "primary_path": primary_path,
            "branch_nodes": branch_nodes,
            "parallel_nodes": parallel_nodes,
            "merge_candidates": merge_candidates,
            "notes": notes,
            "workflow": workflow,
        }

    @staticmethod
    def _clamp_int(value: Any, low: int, high: int, default: int) -> int:
        try:
            number = int(float(value))
        except Exception:
            number = default
        return max(low, min(high, number))

    def _normalize_agent_identity_for_save(
        self, spec: AgentSpec, previous_spec: AgentSpec | None = None
    ) -> None:
        spec.name = str(spec.name or "").strip()
        runtime_name = self._runtime_identity_payload()["default_agent_name"]
        if not spec.name:
            spec.identity_label_source = "astrbot_runtime"
            spec.name = runtime_name
            return

        if (
            previous_spec
            and previous_spec.identity_label_source in AUTO_IDENTITY_LABEL_SOURCES
        ):
            previous_name = str(previous_spec.name or "").strip()
            if spec.name in {previous_name, runtime_name}:
                spec.identity_label_source = "astrbot_runtime"
                spec.name = runtime_name
            else:
                spec.identity_label_source = "manual"
            return

        if spec.identity_label_source in AUTO_IDENTITY_LABEL_SOURCES:
            if spec.name == runtime_name or self._looks_like_default_agent_template(spec):
                spec.identity_label_source = "astrbot_runtime"
                spec.name = runtime_name
            else:
                spec.identity_label_source = "manual"

    def _sanitize_agent_enabled_tools(self, spec: AgentSpec) -> None:
        if spec.isolation_policy.tool_mode == "no_external":
            spec.enabled_tools = [NO_EXTERNAL_TOOLS_SENTINEL]
            return
        names = []
        seen = set()
        for raw_name in spec.enabled_tools or []:
            name = str(raw_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            names.append(name)

        if NO_EXTERNAL_TOOLS_SENTINEL in names:
            spec.enabled_tools = [NO_EXTERNAL_TOOLS_SENTINEL]
            return

        tmgr = self.context.get_llm_tool_manager()
        disabled_plugins = self._disabled_plugin_names(spec)
        internal_block = {"agent_lab_enter_mode", "agent_lab_tick"}
        sanitized = []
        for name in names:
            if name in internal_block:
                continue
            try:
                tool = tmgr.get_func(name)
            except Exception as exc:
                logger.warning("[AgentLab] cannot resolve tool %s: %s", name, exc)
                tool = None
            if tool is not None:
                if self._tool_available_for_agent(tool, disabled_plugins):
                    sanitized.append(name)
                continue
            sanitized.append(name)
        spec.enabled_tools = sanitized

    def _status_text(self, umo: str) -> str:
        task = self.storage.load_active_task(umo)
        webui = f"\n- webui: {self.webui_server.url}" if self.webui_server else ""
        if not task:
            return "Agent Lab：当前没有 active task。" + webui
        runtime = self.agent_runtime.summary(task)
        return (
            f"Agent Lab active task:\n"
            f"- id: {task.task_id}\n"
            f"- status: {task.status}\n"
            f"- goal: {task.root_goal}\n"
            f"- next: {task.next_step or '-'}\n"
            f"- runtime: node={runtime.get('current_node_id') or '-'} "
            f"capabilities={runtime.get('capability_count', 0)} verdicts={runtime.get('verdicts', 0)}\n"
            f"- heartbeat: {'on' if task.heartbeat.enabled else 'off'}\n"
            f"- pending approvals: {len(task.pending_approvals())}\n"
            f"- state: {self.storage.task_markdown_path(umo, task.task_id)}"
            f"{webui}"
        )

    def _runtime_text(self, umo: str) -> str:
        task = self.storage.load_active_task(umo)
        if not task:
            return "当前没有 active task。"
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
        self._normalize_agent_workflow(spec)
        self._sync_agent_runtime(task, spec, reason="runtime_command")
        self.storage.save_task(task)
        return self.agent_runtime.summary_text(task)

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

    def _memory_command_text(self, event: AstrMessageEvent, rest: str) -> str:
        action, _, tail = str(rest or "").strip().partition(" ")
        action = action.lower().strip()
        tail = tail.strip()
        if action in {"accept", "接受", "approve"}:
            memory_id, _, reason = tail.partition(" ")
            item = self.memory_manager.accept(
                memory_id,
                reviewer=event.get_sender_id(),
                reason=reason or "user accepted memory",
            )
            if not item:
                return f"未找到记忆：{memory_id}"
            return f"已接受记忆：{item['memory_id']}，普通模式可读取。"
        if action in {"reject", "拒绝"}:
            memory_id, _, reason = tail.partition(" ")
            item = self.memory_manager.reject(
                memory_id,
                reviewer=event.get_sender_id(),
                reason=reason or "user rejected memory",
            )
            if not item:
                return f"未找到记忆：{memory_id}"
            return f"已拒绝记忆：{item['memory_id']}。"
        rows = self.storage.list_memory_entries()
        lines = []
        for item in reversed(rows[-20:]):
            tags = ",".join(str(tag) for tag in (item.get("tags") or [])[:5])
            lines.append(
                f"- {item.get('memory_id')}: {item.get('status')}/{item.get('layer')} "
                f"tags=[{tags or '-'}] {self._compact_text(item.get('text') or '', 120)}"
            )
        if not lines:
            return "暂无任务记忆。"
        return "任务记忆：\n" + "\n".join(lines)

    def _patterns_text(self, rest: str) -> str:
        action, _, tail = str(rest or "").strip().partition(" ")
        action = action.lower().strip()
        tail = tail.strip()
        if action in {"use", "mark", "used"}:
            pattern_id, _, _reason = tail.partition(" ")
            item = self.pattern_library.mark_used(pattern_id)
            if not item:
                return f"未找到任务模式：{pattern_id}"
            return f"已标记使用任务模式：{item['pattern_id']} usage={item.get('usage_count', 0)}"
        query = tail if action in {"list", "all"} else str(rest or "").strip()
        rows = self.pattern_library.recommend(query, limit=8)
        if not rows:
            return "暂无匹配的任务模式。"
        lines = []
        for item in rows:
            steps = (item.get("plan_template") or {}).get("steps") or []
            step_ids = " -> ".join(
                str(step.get("node_id") or "")
                for step in steps[:8]
                if isinstance(step, dict)
            )
            lines.append(
                f"- {item.get('pattern_id')}: score={item.get('score', 0)} "
                f"success={item.get('success_count', 0)} title={item.get('title') or '-'} "
                f"steps={step_ids or '-'}"
            )
        return "任务模式推荐：\n" + "\n".join(lines)

    def _help_text(self) -> str:
        return (
            "Agent Lab 命令：\n"
            "/agentlab status\n"
            "/agentlab runtime\n"
            "/agentlab use <agent_id>\n"
            "/agentlab start <目标>\n"
            "/agentlab tick\n"
            "/agentlab heartbeat on|off\n"
            "/agentlab approve <approval_id>\n"
            "/agentlab reject <approval_id>\n"
            "/agentlab memory accept|reject <memory_id> [原因]\n"
            "/agentlab patterns [query]\n"
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

    async def _call_registered_custom_api(
        self,
        api_id: str,
        *,
        query_json: str = "",
        body_json: str = "",
        headers_json: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        return await self.api_executor.call_registered(
            api_id,
            query_json=query_json,
            body_json=body_json,
            headers_json=headers_json,
        )

    @staticmethod
    def _parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
        return CustomApiExecutor.parse_json_object(raw, field_name)

    @staticmethod
    def _parse_json_payload(raw: str, field_name: str) -> Any:
        return CustomApiExecutor.parse_json_payload(raw, field_name)

    @staticmethod
    def _apply_custom_api_auth(
        api_spec: dict[str, Any],
        headers: dict[str, str],
        query: dict[str, Any],
        secret: str,
    ) -> None:
        CustomApiExecutor.apply_auth(api_spec, headers, query, secret)

    @staticmethod
    def _perform_custom_api_http_call(
        method: str,
        url: str,
        query: dict[str, Any],
        body: Any,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        return CustomApiExecutor.perform_http_call(
            method,
            url,
            query,
            body,
            headers,
            timeout_seconds,
        )
    def _sync_default_agent_identity(self) -> None:
        """Keep the built-in default Agent aligned with AstrBot's runtime identity."""
        try:
            spec = self.storage.get_agent()
        except Exception:
            return
        if not self._should_sync_agent_identity(spec):
            return
        identity = self._current_bot_identity()
        derived_name = self._agent_name_from_label(identity["label"])
        upgraded = self._upgrade_default_agent_tools(spec)
        if (
            spec.name == derived_name
            and spec.identity_label_source == "astrbot_runtime"
            and not upgraded
        ):
            return
        spec.name = derived_name
        spec.identity_label_source = "astrbot_runtime"
        self.storage.save_agent(spec)

    @staticmethod
    def _upgrade_default_agent_tools(spec: AgentSpec) -> bool:
        legacy_default_tools = {
            "astrbot_file_read_tool",
            "astrbot_grep_tool",
            "astrbot_file_write_tool",
            "astrbot_file_edit_tool",
            "astrbot_execute_shell",
            "astrbot_execute_python",
        }
        if (
            CUSTOM_API_TOOL_NAME not in spec.enabled_tools
            and set(spec.enabled_tools) == legacy_default_tools
        ):
            spec.enabled_tools.append(CUSTOM_API_TOOL_NAME)
            return True
        return False

    async def _effective_agent_name(
        self, spec: AgentSpec, event: AstrMessageEvent
    ) -> str:
        if not self._should_sync_agent_identity(spec):
            return spec.name
        return self._agent_name_from_label(await self._current_bot_label_for_event(event))

    def _should_sync_agent_identity(self, spec: AgentSpec) -> bool:
        if spec.identity_label_source in AUTO_IDENTITY_LABEL_SOURCES:
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
        return self._current_bot_identity()["label"]

    async def _current_bot_label_for_event(self, event: AstrMessageEvent) -> str:
        return (await self._current_bot_identity_for_event(event))["label"]

    def _runtime_identity_payload(self) -> dict[str, str]:
        identity = self._current_bot_identity()
        return {
            "bot_label": identity["label"],
            "bot_label_source": identity["source"],
            "default_agent_name": self._agent_name_from_label(identity["label"]),
        }

    def _current_bot_identity(self) -> dict[str, str]:
        persona_name = self._current_persona_name()
        if self._usable_persona_label(persona_name):
            return {"label": persona_name, "source": "astrbot_persona"}
        config_label = self._config_bot_label(self._context_config())
        if config_label:
            return {"label": config_label, "source": "astrbot_config"}
        return {"label": DEFAULT_BOT_LABEL, "source": "fallback"}

    async def _current_bot_identity_for_event(
        self, event: AstrMessageEvent
    ) -> dict[str, str]:
        persona_name = await self._current_persona_name_for_event(event)
        if self._usable_persona_label(persona_name):
            return {"label": persona_name, "source": "astrbot_persona"}
        config_label = self._config_bot_label(
            self._context_config(getattr(event, "unified_msg_origin", "")),
            self._event_platform_name(event),
        )
        if config_label:
            return {"label": config_label, "source": "astrbot_config"}
        return {"label": DEFAULT_BOT_LABEL, "source": "fallback"}

    async def _current_persona_name_for_event(self, event: AstrMessageEvent) -> str:
        umo = getattr(event, "unified_msg_origin", "")
        config = self._context_config(umo)
        provider_settings = _cfg(config, "provider_settings", {}) or {}
        session_persona_id = await self._session_persona_id(umo)
        conversation_persona_id = await self._conversation_persona_id(umo)
        persona_manager = getattr(self.context, "persona_manager", None)

        resolve_selected = getattr(persona_manager, "resolve_selected_persona", None)
        if callable(resolve_selected):
            try:
                selected_id, persona, force_persona_id, _ = await resolve_selected(
                    umo=umo,
                    conversation_persona_id=conversation_persona_id or None,
                    platform_name=self._event_platform_name(event),
                    provider_settings=provider_settings,
                )
                name = self._persona_name(persona)
                if self._usable_persona_label(name):
                    return name
                if selected_id == "[%None]" or force_persona_id == "[%None]":
                    return ""
                name = self._persona_name_by_id(selected_id)
                if self._usable_persona_label(name):
                    return name
                if self._usable_persona_label(str(selected_id or "")):
                    return str(selected_id).strip()
            except Exception:
                pass

        for persona_id in (session_persona_id, conversation_persona_id):
            if persona_id == "[%None]":
                return ""
            name = self._persona_name_by_id(persona_id)
            if self._usable_persona_label(name):
                return name
            if self._usable_persona_label(persona_id):
                return persona_id

        get_default = getattr(persona_manager, "get_default_persona_v3", None)
        if callable(get_default):
            try:
                name = self._persona_name(await get_default(umo=umo))
                if self._usable_persona_label(name):
                    return name
            except Exception:
                pass

        return self._current_persona_name()

    def _current_persona_name(self) -> str:
        persona_manager = getattr(self.context, "persona_manager", None)
        for attr in ("selected_default_persona_v3", "selected_default_persona"):
            persona = getattr(persona_manager, attr, None)
            name = self._persona_name(persona)
            if self._usable_persona_label(name):
                return name

        config = self._context_config()
        provider_settings = _cfg(config, "provider_settings", {}) or {}
        default_persona = _cfg(provider_settings, "default_personality", "")
        name = self._persona_name_by_id(default_persona)
        if self._usable_persona_label(name):
            return name
        if self._usable_persona_label(default_persona):
            return str(default_persona).strip()
        return ""

    async def _session_persona_id(self, umo: str) -> str:
        if not umo:
            return ""
        try:
            from astrbot.api import sp

            session_service_config = (
                await sp.get_async(
                    scope="umo",
                    scope_id=str(umo),
                    key="session_service_config",
                    default={},
                )
                or {}
            )
        except Exception:
            return ""
        if not isinstance(session_service_config, dict):
            return ""
        return str(session_service_config.get("persona_id") or "").strip()

    def _config_bot_label(
        self, config: Any, platform_name: str | None = None
    ) -> str:
        for key in CONFIG_BOT_LABEL_KEYS:
            label = self._usable_config_label(_cfg(config, key, ""))
            if label:
                return label
        for section_name in ("provider_settings", "platform_settings"):
            section = _cfg(config, section_name, {}) or {}
            for key in CONFIG_BOT_LABEL_KEYS:
                label = self._usable_config_label(_cfg(section, key, ""))
                if label:
                    return label

        platform_name = str(platform_name or "").strip()
        platforms = _cfg(config, "platform", []) or _cfg(config, "platforms", []) or []
        if isinstance(platforms, dict):
            platforms = list(platforms.values())
        if not isinstance(platforms, list):
            platforms = []

        matched: list[Any] = []
        unmatched: list[Any] = []
        for item in platforms:
            item_type = str(_cfg(item, "type", "") or _cfg(item, "id", "")).strip()
            if platform_name and item_type == platform_name:
                matched.append(item)
            else:
                unmatched.append(item)

        for item in matched + unmatched:
            if _cfg(item, "enable", True) is False:
                continue
            for key in CONFIG_BOT_LABEL_KEYS:
                label = self._usable_config_label(_cfg(item, key, ""))
                if label:
                    return label
        return ""

    @staticmethod
    def _usable_config_label(value: Any) -> str:
        label = str(value or "").strip()
        if not label:
            return ""
        if label.lower() in {"default", "[%none]", "none", "unknown"}:
            return ""
        return label

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
