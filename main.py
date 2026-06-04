from __future__ import annotations

import json
import shutil
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

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
from .agent_lab.models import new_id, now_iso
from .agent_lab.modules import ModuleRegistry
from .agent_lab.prompts import (
    build_agent_mode_policy,
    build_task_system_prompt,
    build_tick_prompt,
)
from .agent_lab.node_runtime import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
)
from .agent_lab.runtime import WorkflowDecision, WorkflowRuntime, WorkflowRuntimeRun
from .agent_lab.session_guard import SessionPluginGuard
from .agent_lab.summarizer import AgentSummarizer
from .agent_lab.webui_server import StandaloneWebUIServer


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
}
WORKFLOW_ACTIONS = {
    "confirm_entry",
    "summarize_entry",
    "restore_isolation",
    "plan",
    "route_condition",
    "parallel_branch",
    "run_tools",
    "call_api",
    "transform_context",
    "retrieve_memory",
    "request_approval",
    "wait_user",
    "handoff",
    "validate_output",
    "retry",
    "save_state",
    "save_memory",
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
        self.modules = ModuleRegistry(self.storage.modules_dir)
        self.guard = SessionPluginGuard(protected_plugins={PLUGIN_NAME})
        self.webui_server: StandaloneWebUIServer | None = None
        self._running_ticks: set[str] = set()
        self.workflow_runtime = WorkflowRuntime(
            max_auto_steps=int(_cfg(self.config, "workflow_auto_steps_per_tick", 6))
        )
        self.node_executors = NodeExecutorRegistry()
        self._register_node_executors()
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
            f"workflow: {self._workflow_runtime_text(task)}\n"
            f"entry_summary: {self._compact_text(task.entry_summary or task.task_brief, 1600)}\n"
            f"current_summary: {task.current_summary or '-'}\n"
            f"last_confirmed_progress: {task.last_confirmed_progress or '-'}\n"
            f"next_step: {task.next_step or '-'}\n"
            f"last_observation: {self._compact_text(task.last_observation, 1200) or '-'}\n"
            f"pending_approvals: {len(task.pending_approvals())}\n"
            f"state_path: {self.storage.task_markdown_path(task.umo, task.task_id)}"
        )

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
            exposed = bool(item.get("expose_to_normal", False))
            private_same_scope = False
            if allow_private and not exposed:
                source_umo = str(item.get("source_umo") or "")
                source_task_id = str(item.get("source_task_id") or "")
                private_same_scope = (
                    (source_umo and source_umo == event.unified_msg_origin)
                    or (active_task is not None and source_task_id == active_task.task_id)
                )
            if status != "all":
                if allow_private and not exposed and status == "accepted":
                    if not private_same_scope or item_status not in {"accepted", "candidate"}:
                        continue
                elif item_status != status:
                    continue
            if status == "all" and not allow_private and item_status != "accepted":
                continue
            if not allow_private and not exposed:
                continue
            if allow_private and not exposed:
                if not private_same_scope:
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
            rows.append(
                {
                    "memory_id": item.get("memory_id"),
                    "status": item_status,
                    "tags": item.get("tags") or [],
                    "source_task_id": item.get("source_task_id") or "",
                    "updated_at": item.get("updated_at") or "",
                    "text": item.get("text") or "",
                }
            )
            if len(rows) >= limit:
                break
        if not rows:
            return "没有匹配的任务记忆。"
        return json.dumps(rows, ensure_ascii=False, indent=2)

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
        if not event.is_private_chat() and _bool_cfg(self.config, "private_only", True):
            return
        spec = self.storage.get_agent()
        task = self.storage.load_active_task(event.unified_msg_origin)
        if task:
            spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or spec.to_dict())
            modules_prompt = "\n\n".join(
                part
                for part in (
                    self._build_task_extensions_prompt(spec),
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
            req.system_prompt += "\n\n" + build_agent_mode_policy(spec)
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
        self._normalize_agent_workflow(spec)
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
        task.add_log("created", f"goal={goal}; source={source}; risk={risk_level}")
        task.add_snapshot("created", {"source": source, "risk_level": risk_level})
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

        tick_key = f"{task.umo}:{task.task_id}"
        if tick_key in self._running_ticks:
            return "当前任务已有一轮 tick 正在执行，已跳过本次触发，避免心跳或手动操作重入。"
        self._running_ticks.add(tick_key)
        task_updated_at_before_tick = task.updated_at
        task_log_count_before_tick = len(task.progress_log)
        try:
            spec = AgentSpec.from_dict(task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict())
            self._normalize_agent_workflow(spec)
            runtime_run = await self._run_workflow_runtime(
                event=event,
                task=task,
                spec=spec,
                reason=reason,
            )
            if runtime_run.changed:
                self.storage.save_task(task)
            latest_task = self.storage.load_active_task(event.unified_msg_origin)
            if not latest_task or latest_task.task_id != task.task_id:
                return "tick 完成，任务已在工作流运行时阶段结束或切换。"
            task = latest_task
            if task.status == "blocked" or runtime_run.blocked:
                self.storage.save_task(task)
                return f"tick 已暂停：工作流运行时阻塞。\n\n{self._compact_text(runtime_run.summary(), 1800)}"
            if runtime_run.changed and not runtime_run.needs_react:
                self.storage.save_task(task)
                return f"tick 完成：工作流运行时已推进。\n\n{self._compact_text(runtime_run.summary(), 1800)}"
            task_updated_at_before_tick = task.updated_at
            task_log_count_before_tick = len(task.progress_log)
            modules_prompt = self._build_task_extensions_prompt(spec)
            system_prompt = build_task_system_prompt(spec, task, modules_prompt)
            prompt = self._workflow_react_prompt(task=task, spec=spec, reason=reason)
            provider_id = spec.provider_id or await self.context.get_current_chat_provider_id(event.unified_msg_origin)
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
            latest_task = self.storage.load_active_task(event.unified_msg_origin)
            if not latest_task or latest_task.task_id != task.task_id:
                return f"tick 完成，任务已在本轮结束或切换。\n\n{self._compact_text(text, 1800)}"
            task = latest_task
            self._record_react_trace(
                task,
                node_id=runtime_run.react_node_id or task.workflow_current_node_id,
                prompt=prompt,
                response=text,
                reason=reason,
            )
            changed_by_tools = (
                task.updated_at != task_updated_at_before_tick
                or len(task.progress_log) != task_log_count_before_tick
                or task.status not in {"running", "paused"}
            )
            if not changed_by_tools:
                task.last_observation = text[-4000:] if text else "本轮没有返回文本。"
                task.last_confirmed_progress = text[:1200] if text else task.last_confirmed_progress
                task.current_summary = self._compact_text(text, 1200) if text else task.current_summary
                task.next_step = "根据上一轮观察继续推进；若涉及危险操作，先请求审批。"
                task.status = "running"
            task.add_token_usage(getattr(resp, "usage", None))
            task.add_log("tick", f"reason={reason}; response={self._compact_text(text, 1200)}")
            task.add_snapshot(
                "tick",
                {
                    "reason": reason,
                    "provider_id": provider_id,
                    "token_usage": task.token_usage,
                },
            )
            self.storage.save_task(task)
            return f"tick 完成。\n\n{self._compact_text(text, 1800)}"
        except Exception as exc:
            task = self.storage.load_active_task(event.unified_msg_origin) or task
            count = task.add_blocker(type(exc).__name__, str(exc))
            if count >= task.heartbeat.max_repeated_failures:
                task.status = "blocked"
                await self._disable_heartbeat(task)
            self.storage.save_task(task)
            self._running_ticks.discard(tick_key)
            return (
                f"tick 失败：{exc}\n"
                f"同类问题计数：{count}。"
                f"{' 已暂停任务并关闭心跳。' if task.status == 'blocked' else ''}"
            )
        finally:
            self._running_ticks.discard(tick_key)

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
        await self._disable_heartbeat(task)
        snapshot = task.profile_snapshot.get("session_plugin_snapshot")
        if bool(task.profile_snapshot.get("restore_session_plugins", True)):
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
            "agent_lab_read_task_memory",
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
        name = str(tool_name or "").strip()
        if not name:
            return False
        if name in {
            NO_EXTERNAL_TOOLS_SENTINEL,
            "agent_lab_enter_mode",
            "agent_lab_tick",
            "agent_lab_finish",
            "agent_lab_update_workflow",
            "agent_lab_run_parallel_workflow",
        }:
            return False
        tool_mode = str(getattr(spec.isolation_policy, "tool_mode", "whitelist") or "whitelist")
        selected_tools = set(spec.enabled_tools or [])
        if tool_mode == "no_external" or NO_EXTERNAL_TOOLS_SENTINEL in selected_tools:
            return False
        return tool_mode == "full" or not selected_tools or name in selected_tools

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
        for action in ("summarize_entry", "confirm_entry", "restore_isolation"):
            self.node_executors.register(action, self._execute_entry_node)
        for action in ("save_state", "heartbeat", "transform_context"):
            self.node_executors.register(action, self._execute_state_node)
        self.node_executors.register("retrieve_memory", self._execute_retrieve_memory_node)
        self.node_executors.register("save_memory", self._execute_save_memory_node)
        self.node_executors.register("parallel_branch", self._execute_parallel_branch_node)
        self.node_executors.register("call_api", self._execute_api_node)
        self.node_executors.register("run_tools", self._execute_tool_node)
        self.node_executors.register("route_condition", self._execute_route_node)
        self.node_executors.register("retry", self._execute_retry_node)
        self.node_executors.register("validate_output", self._execute_validation_node)
        self.node_executors.register("request_approval", self._execute_approval_node)
        self.node_executors.register("wait_user", self._execute_wait_node)
        self.node_executors.register("handoff", self._execute_wait_node)
        self.node_executors.register("notify", self._execute_notify_node)
        self.node_executors.register("archive", self._execute_terminal_node)
        self.node_executors.register("exit_summary", self._execute_terminal_node)

    @staticmethod
    def _single_next(outgoing: list[str]) -> str:
        return outgoing[0] if len(outgoing) == 1 else ""

    def _ensure_workflow_data(self, task: TaskState) -> dict[str, Any]:
        data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        data.setdefault("node_outputs", {})
        data.setdefault("variables", {})
        data.setdefault("react_traces", [])
        data.setdefault("execution_counts", {})
        task.workflow_data = data
        return data

    def _workflow_variable(self, task: TaskState, name: str, default: Any = None) -> Any:
        data = self._ensure_workflow_data(task)
        return (data.get("variables") or {}).get(str(name or "").strip(), default)

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
            "status": result.status,
            "ok": result.ok,
            "outcome": result.outcome,
            "note": result.note,
            "next_node_id": result.next_node_id,
            "data": result.data,
        }
        data.setdefault("node_outputs", {})[node_id] = payload
        output_variable = str(
            node.get("output_variable")
            or node.get("variable")
            or node.get("output")
            or ""
        ).strip()
        if output_variable:
            data.setdefault("variables", {})[output_variable] = result.data or result.outcome
        task.last_observation = self._compact_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            4000,
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
        traces.append(
            {
                "time": now_iso(),
                "node_id": node_id,
                "reason": reason,
                "prompt": self._compact_text(prompt, 1200),
                "response": self._compact_text(response, 1600),
            }
        )
        data["react_traces"] = traces[-80:]

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

    def _node_payload_from_variable(self, task: TaskState, node: dict[str, Any]) -> Any:
        input_variable = str(node.get("input_variable") or "").strip()
        if not input_variable:
            return None
        return self._workflow_variable(task, input_variable)

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

        default_target = ""
        for item in candidates:
            condition = str(item.get("condition") or "").strip().lower()
            if condition in {"default", "else", "otherwise"}:
                default_target = str(item.get("id") or "").strip()
        return default_target if default_target in outgoing else ""

    async def _execute_entry_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        if action == "summarize_entry":
            outcome = f"Entry brief is available for task {ctx.task.task_id}."
        elif action == "confirm_entry":
            outcome = "Entry confirmation is satisfied because the task exists."
        else:
            outcome = "Session isolation snapshot is already applied for this task."
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"action": action, "task_id": ctx.task.task_id},
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

    async def _execute_retrieve_memory_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        query = str(
            ctx.node.get("query")
            or ctx.node.get("memory_query")
            or ctx.node.get("condition")
            or ctx.task.root_goal
            or ""
        ).strip().lower()
        try:
            limit = max(1, min(int(ctx.node.get("limit") or 5), 12))
        except Exception:
            limit = 5
        rows = []
        for item in reversed(self.storage.list_memory_entries()):
            text = str(item.get("text") or "")
            haystack = "\n".join(
                [
                    text,
                    str(item.get("source_task_id") or ""),
                    " ".join(str(tag) for tag in item.get("tags") or []),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            exposed = bool(item.get("expose_to_normal", False))
            same_scope = (
                str(item.get("source_umo") or "") == ctx.task.umo
                or str(item.get("source_task_id") or "") == ctx.task.task_id
            )
            if not exposed and not same_scope:
                continue
            rows.append(
                {
                    "memory_id": item.get("memory_id"),
                    "status": item.get("status") or "candidate",
                    "kind": item.get("kind") or "",
                    "tags": item.get("tags") or [],
                    "source_task_id": item.get("source_task_id") or "",
                    "text": self._compact_text(text, 900),
                }
            )
            if len(rows) >= limit:
                break
        outcome = f"Retrieved {len(rows)} task memory item(s)."
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"query": query, "rows": rows},
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
            payload = self._node_json_object(ctx.node, "api_payload", "payload", "params")
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
        call_args = self._node_json_object(ctx.node, "tool_args", "arguments", "params")
        variable_payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if isinstance(variable_payload, dict):
            call_args = {**call_args, **variable_payload}
        if not tool_name or not call_args:
            return NodeExecutionResult(
                outcome="Tool node needs ReAct because no concrete tool_name/tool_args are bound.",
                needs_react=True,
                advance=False,
                note="node_executor_tool_react_fallback",
            )
        if not self._tool_allowed_by_agent_profile(ctx.spec, tool_name):
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Tool is outside the Agent tool profile: {tool_name}",
                blocked=True,
                advance=False,
                note="node_executor_tool_not_allowed",
            )
        tmgr = self.context.get_llm_tool_manager()
        try:
            tool = tmgr.get_func(tool_name)
        except Exception:
            tool = None
        if not tool or not self._tool_available_for_agent(tool, self._disabled_plugin_names(ctx.spec)):
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"Tool is unavailable or isolated: {tool_name}",
                blocked=True,
                advance=False,
                note="node_executor_tool_unavailable",
            )
        try:
            from astrbot.core.agent.run_context import ContextWrapper

            result = await tool.call(
                ContextWrapper(context=ctx.event, tool_call_timeout=int(_cfg(self.config, "tool_call_timeout", 120))),
                **call_args,
            )
        except NotImplementedError:
            return NodeExecutionResult(
                outcome=f"Tool {tool_name} has no direct callable executor; ReAct/tool-loop is required.",
                needs_react=True,
                advance=False,
                note="node_executor_tool_react_fallback",
            )
        except Exception as exc:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"{type(exc).__name__}: {exc}",
                blocked=True,
                advance=False,
                note="node_executor_tool_error",
            )
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
        return NodeExecutionResult(
            outcome=self._compact_text(text, 1000) or f"Tool {tool_name} completed.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"tool_name": tool_name, "args": call_args, "result": self._compact_text(text, 2400)},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_tool",
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
        text = "\n".join(
            [
                ctx.task.current_summary or "",
                ctx.task.last_confirmed_progress or "",
                ctx.task.last_observation or "",
            ]
        ).lower()
        fail_words = ("fail", "failed", "error", "blocked", "失败", "错误", "阻塞", "未通过")
        pass_words = ("pass", "passed", "ok", "success", "完成", "通过", "成功")
        failed = any(word in text for word in fail_words)
        passed = any(word in text for word in pass_words) and not failed
        if not passed and len(ctx.outgoing) > 1:
            retry_target = self._candidate_by_action(ctx.next_candidates, {"retry"}) or self._candidate_by_stage(
                ctx.next_candidates, {"checkpoint", "execute"}
            )
            if failed and retry_target:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome=f"Validation did not pass; routed to {retry_target}.",
                    next_node_id=retry_target,
                    data={"passed": False},
                    note="node_executor_validation_retry",
                )
            return NodeExecutionResult(
                outcome="Validation requires ReAct because pass/fail is unclear.",
                needs_react=True,
                advance=False,
                data={"passed": False, "ambiguous": True},
                note="node_executor_validation_react",
            )
        return NodeExecutionResult(
            outcome="Validation passed." if passed else "Validation checkpoint recorded.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"passed": passed, "ambiguous": not passed},
            needs_react=len(ctx.outgoing) > 1 and not passed,
            advance=len(ctx.outgoing) <= 1 or passed,
            note="node_executor_validation",
        )

    async def _execute_approval_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        if ctx.task.pending_approvals():
            ctx.task.status = "paused"
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
        return NodeExecutionResult(
            ok=False,
            status="running",
            outcome=str(ctx.node.get("instruction") or "Waiting for user input."),
            advance=False,
            data={"wait": True},
            note="node_executor_wait",
        )

    async def _execute_notify_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        outcome = self._compact_text(
            str(ctx.node.get("message") or ctx.task.current_summary or ctx.task.last_confirmed_progress or "Notification checkpoint."),
            1000,
        )
        ctx.task.add_log("notify", outcome)
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"message": outcome},
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
                outgoing = [
                    node_id
                    for node_id in self.workflow_runtime.outgoing(spec).get(decision.node_id, [])
                    if node_id in nodes
                ]
                ctx = NodeExecutionContext(
                    event=event,
                    task=task,
                    spec=spec,
                    node=decision.node,
                    outgoing=outgoing,
                    next_candidates=[nodes[node_id] for node_id in outgoing],
                    reason=reason,
                )
                result = await self.node_executors.execute(ctx)
                self._record_node_execution(task, decision.node, result)
                executed = self._node_result_to_decision(decision.node, result)
                runtime_run.steps.append(executed)

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

        workers = await asyncio.gather(*(run_worker(node_id) for node_id in worker_ids))
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
        system_prompt = (
            f"{spec.system_prompt}\n\n"
            "[Agent Lab Parallel Worker]\n"
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
        return "\n".join(
            [
                "执行一个并行工作流节点，输出结构化结果。",
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

    def _build_task_extensions_prompt(self, spec: AgentSpec) -> str:
        sections = []
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
        return rows

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
                    "x": cls._clamp_int(raw_node.get("x"), 0, 6200, 70 + index * 260),
                    "y": cls._clamp_int(raw_node.get("y"), 0, 3600, 120),
                }
            )
            NodeExecutorRegistry.normalize_node_runtime_type(normalized)
            for key, limit in (
                ("ref_type", 32),
                ("ref_id", 160),
                ("api_id", 160),
                ("plugin_name", 160),
                ("tool_name", 160),
                ("skill_name", 160),
                ("condition", 1000),
                ("parallel_group", 80),
                ("prompt", 4000),
            ):
                if key in normalized:
                    normalized[key] = str(normalized.get(key) or "").strip()[:limit]
            nodes.append(normalized)

        edges: list[dict[str, str]] = []
        seen_edges: set[tuple[str, str]] = set()
        for raw_edge in spec.workflow_edges if isinstance(spec.workflow_edges, list) else []:
            if not isinstance(raw_edge, dict):
                continue
            start = id_map.get(str(raw_edge.get("from") or "").strip(), str(raw_edge.get("from") or "").strip())
            end = id_map.get(str(raw_edge.get("to") or "").strip(), str(raw_edge.get("to") or "").strip())
            if start not in used_ids or end not in used_ids or start == end:
                continue
            key = (start, end)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append({"from": start, "to": end})
        if not edges and len(nodes) > 1:
            edges = [
                {"from": nodes[index]["id"], "to": nodes[index + 1]["id"]}
                for index in range(len(nodes) - 1)
            ]

        spec.workflow_nodes = nodes
        spec.workflow_edges = edges

    @staticmethod
    def _normalize_workflow_id(value: str) -> str:
        value = re.sub(r"\s+", "_", str(value or "").strip())
        value = re.sub(r"[^A-Za-z0-9_-]", "", value)
        return value[:64] or "node"

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

        entry_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "entry" or node.get("action") in {"summarize_entry", "confirm_entry"}
        ]
        terminal_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("action") in {"archive", "exit_summary"}
            or (
                node.get("stage") == "archive"
                and node.get("action") not in {"notify", "manual"}
            )
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
        if "summarize_entry" not in action_ids:
            add_issue("warn", "missing_entry_summary", "工作流没有入口摘要节点，普通聊天上文可能无法干净压缩成 task_brief。")
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
            if node.get("kind") == "branch" and len(outgoing.get(node_id, [])) < 2:
                add_issue("warn", "branch_single_path", "分支节点最好至少有两条输出连线。", node_id)
            if node.get("action") == "parallel_branch":
                workers = outgoing.get(node_id, [])
                if len(workers) < 2:
                    add_issue("warn", "parallel_without_workers", "并行 Agent 分支至少需要两个后续工作包。", node_id)
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

    async def _call_registered_custom_api(
        self,
        api_id: str,
        *,
        query_json: str = "",
        body_json: str = "",
        headers_json: str = "",
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        api_spec = self.storage.get_custom_api(api_id)
        if not api_spec:
            return {}, {}, f"未找到已注册自定义 API：{api_id}"
        if not api_spec.get("url"):
            return {}, api_spec, f"自定义 API {api_id} 未配置 URL。"

        try:
            query = self._parse_json_object(query_json, "query_json")
            headers = self._parse_json_object(headers_json, "headers_json")
            body = self._parse_json_payload(body_json, "body_json")
        except ValueError as exc:
            return {}, api_spec, str(exc)

        headers = {str(k): str(v) for k, v in headers.items()}
        for key, value in (api_spec.get("headers") or {}).items():
            headers.setdefault(str(key), str(value))

        credential_id = str(api_spec.get("credential_id") or "").strip()
        if credential_id:
            secret = self.storage.get_credential_secret(credential_id)
            if not secret:
                return {}, api_spec, f"自定义 API {api_spec.get('name') or api_id} 绑定的凭证为空或无法解密。"
            self._apply_custom_api_auth(api_spec, headers, query, secret)

        result = await asyncio.to_thread(
            self._perform_custom_api_http_call,
            str(api_spec.get("method") or "GET").upper(),
            str(api_spec.get("url") or ""),
            query,
            body,
            headers,
            int(api_spec.get("timeout_seconds") or 30),
        )
        return result, api_spec, ""

    @staticmethod
    def _parse_json_object(raw: str, field_name: str) -> dict[str, Any]:
        raw = str(raw or "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} 不是合法 JSON：{exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{field_name} 必须是 JSON 对象。")
        return payload

    @staticmethod
    def _parse_json_payload(raw: str, field_name: str) -> Any:
        raw = str(raw or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} 不是合法 JSON：{exc}") from exc

    @staticmethod
    def _apply_custom_api_auth(
        api_spec: dict[str, Any],
        headers: dict[str, str],
        query: dict[str, Any],
        secret: str,
    ) -> None:
        auth_type = str(api_spec.get("auth_type") or "bearer").strip().lower()
        if auth_type in {"none", "off", "disabled"}:
            return
        if auth_type == "query":
            param = str(api_spec.get("auth_query_param") or "api_key").strip()
            if param:
                query[param] = secret
            return
        header = str(api_spec.get("auth_header") or "Authorization").strip()
        if not header:
            return
        if auth_type == "header":
            headers[header] = secret
        else:
            headers[header] = f"Bearer {secret}"

    @staticmethod
    def _perform_custom_api_http_call(
        method: str,
        url: str,
        query: dict[str, Any],
        body: Any,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict[str, Any]:
        parsed = urlparse.urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return {
                "ok": False,
                "status": 0,
                "error": "Only http/https custom APIs are supported.",
            }
        existing_query = dict(urlparse.parse_qsl(parsed.query, keep_blank_values=True))
        existing_query.update({str(k): str(v) for k, v in query.items()})
        final_url = urlparse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlparse.urlencode(existing_query),
                parsed.fragment,
            )
        )
        method = method.upper()
        request_body = None
        safe_headers = dict(headers)
        if method not in {"GET", "HEAD"} and body is not None:
            request_body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            safe_headers.setdefault("Content-Type", "application/json")
        req = urlrequest.Request(
            final_url,
            data=request_body,
            headers=safe_headers,
            method=method,
        )
        try:
            with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
                raw = resp.read(256_000)
                text = raw.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                return {
                    "ok": 200 <= resp.status < 300,
                    "status": resp.status,
                    "content_type": resp.headers.get("Content-Type", ""),
                    "body": text[:12000],
                    "truncated": len(text) > 12000,
                }
        except urlerror.HTTPError as exc:
            raw = exc.read(64_000)
            text = raw.decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status": exc.code,
                "content_type": exc.headers.get("Content-Type", ""),
                "body": text[:8000],
                "truncated": len(text) > 8000,
            }
        except Exception as exc:
            return {
                "ok": False,
                "status": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }

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
