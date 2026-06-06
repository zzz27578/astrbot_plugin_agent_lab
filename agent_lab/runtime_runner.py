from __future__ import annotations

from typing import Any

from .hooks import AgentLabRunHooks
from .models import AgentSpec
from .prompts import build_task_system_prompt


def _cfg(config: Any, key: str, default: Any = None) -> Any:
    try:
        if isinstance(config, dict):
            return config.get(key, default)
    except Exception:
        return default
    try:
        return config.get(key, default)
    except Exception:
        return getattr(config, key, default)


class AgentRuntimeRunner:
    """Owns the task tick loop beneath the AstrBot plugin adapter."""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def __getattr__(self, name: str) -> Any:
        return getattr(self.adapter, name)

    async def run_tick(self, event: Any, reason: str) -> str:
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。可以先 /agentlab start <目标>。"
        if task.status not in ("running", "paused"):
            return f"当前任务状态为 {task.status}，不执行 tick。"
        if task.pending_approvals():
            pending = "\n".join(
                f"- {item.approval_id}: {item.operation}" for item in task.pending_approvals()
            )
            task.watchdog.needs_user = True
            task.watchdog.last_decision = "waiting_approval"
            self.agent_runtime.record_pause(
                task,
                reason="waiting for approval before continuing tick",
                missing=[item.operation for item in task.pending_approvals()],
            )
            self.storage.save_task(task)
            return f"存在待审批操作，先处理审批再继续：\n{pending}"

        tick_key = f"{task.umo}:{task.task_id}"
        if tick_key in self._running_ticks:
            return "当前任务已有一轮 tick 正在执行，已跳过本次触发，避免心跳或手动操作重入。"
        self._running_ticks.add(tick_key)
        lease_token = ""
        before_hash = self._progress_hash(task)
        try:
            lease_ok, lease_message = self._acquire_task_lease(task, reason=reason)
            if not lease_ok:
                return lease_message
            lease_token = lease_message
            task = self.storage.load_active_task(event.unified_msg_origin) or task
            watchdog_message = self._watchdog_before_tick(task, reason)
            if watchdog_message:
                self.storage.save_task(task)
                return watchdog_message

            spec = AgentSpec.from_dict(
                task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
            )
            self._normalize_agent_workflow(spec)
            self._sync_agent_runtime(task, spec, reason=f"tick:{reason}")
            self.agent_runtime.record_decision(
                task,
                phase="tick",
                action="start_tick",
                node_id=task.workflow_current_node_id,
                reason=reason,
                capability="control.tick",
                confidence="high",
            )
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
            if task.status in {"blocked", "paused"} or runtime_run.blocked:
                self._watchdog_after_tick(task, before_hash=before_hash, reason=reason)
                self.agent_runtime.record_verdict(
                    task,
                    node_id=runtime_run.react_node_id or task.workflow_current_node_id,
                    passed=False,
                    status=task.status,
                    reason=runtime_run.summary() or task.watchdog.paused_reason or "workflow runtime blocked",
                    missing=[task.watchdog.paused_reason or "workflow_runtime_blocked"],
                    next_action=task.next_step or "resume_after_user_input",
                )
                self.storage.save_task(task)
                return f"tick 已暂停：工作流运行时阻塞或等待。\n\n{self._compact_text(runtime_run.summary(), 1800)}"
            if runtime_run.changed and not runtime_run.needs_react:
                self._watchdog_after_tick(task, before_hash=before_hash, reason=reason)
                self.agent_runtime.record_verdict(
                    task,
                    node_id=task.workflow_current_node_id,
                    passed=True,
                    status=task.status,
                    reason=runtime_run.summary() or "workflow runtime advanced",
                    next_action=task.next_step,
                )
                self.storage.save_task(task)
                return f"tick 完成：工作流运行时已推进。\n\n{self._compact_text(runtime_run.summary(), 1800)}"

            task_updated_at_before_tick = task.updated_at
            task_log_count_before_tick = len(task.progress_log)
            modules_prompt = self._build_task_extensions_prompt(spec, task=task)
            system_prompt = build_task_system_prompt(spec, task, modules_prompt)
            prompt = self._workflow_react_prompt(task=task, spec=spec, reason=reason)
            provider_id = spec.provider_id or await self.context.get_current_chat_provider_id(
                event.unified_msg_origin
            )
            remaining_tool_steps = self._budget_remaining_tools(task)
            if remaining_tool_steps <= 0:
                self._pause_task_for_budget(task, "本轮工具预算已用尽，未进入 LLM 工具循环。")
                self.storage.save_task(task)
                return "tick 已暂停：本轮工具预算已用尽。"
            resp = await self.context.tool_loop_agent(
                event=event,
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=system_prompt,
                tools=self._build_toolset(spec),
                max_steps=remaining_tool_steps,
                tool_call_timeout=int(_cfg(self.config, "tool_call_timeout", 120)),
                llm_compress_keep_recent=int(_cfg(self.config, "llm_compress_keep_recent", 6)),
                truncate_turns=int(_cfg(self.config, "truncate_turns", 2)),
                agent_hooks=AgentLabRunHooks(
                    self.storage,
                    task.umo,
                    task.task_id,
                    budget_max_tools=remaining_tool_steps,
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
                task.next_step = "根据上一轮 observation 继续推进；如果涉及危险操作，先请求审批。"
                task.status = "running"
                self._record_explicit_observation(
                    task,
                    source="react",
                    node_id=runtime_run.react_node_id or task.workflow_current_node_id,
                    payload={"text": task.last_observation},
                )
            budget_message = self._consume_token_budget(task, getattr(resp, "usage", None))
            task.add_token_usage(getattr(resp, "usage", None))
            task.add_log("tick", f"reason={reason}; response={self._compact_text(text, 1200)}")
            task.add_snapshot(
                "tick",
                {
                    "reason": reason,
                    "provider_id": provider_id,
                    "token_usage": task.token_usage,
                    "budget": {
                        "ticks_used": task.budget.ticks_used,
                        "nodes_used": task.budget.nodes_used,
                        "tool_calls_used": task.budget.tool_calls_used,
                        "tokens_used": task.budget.tokens_used,
                    },
                },
            )
            if budget_message:
                self._pause_task_for_budget(task, budget_message)
            self._watchdog_after_tick(task, before_hash=before_hash, reason=reason)
            self.agent_runtime.record_verdict(
                task,
                node_id=runtime_run.react_node_id or task.workflow_current_node_id,
                passed=task.status == "running",
                status=task.status,
                reason=task.last_observation or text or "tick finished",
                missing=[] if task.status == "running" else [task.watchdog.paused_reason or task.status],
                next_action=task.next_step,
            )
            self.agent_runtime.update_resume(task, reason=f"tick:{reason}")
            self.storage.save_task(task)
            if task.status == "paused" and task.watchdog.paused_reason:
                return f"tick 已暂停：{task.watchdog.paused_reason}\n\n{self._compact_text(text, 1800)}"
            return f"tick 完成。\n\n{self._compact_text(text, 1800)}"
        except Exception as exc:
            task = self.storage.load_active_task(event.unified_msg_origin) or task
            count = task.add_blocker(type(exc).__name__, str(exc))
            self._watchdog_after_tick(
                task,
                before_hash=before_hash,
                reason=reason,
                error=f"{type(exc).__name__}: {exc}",
            )
            if count >= task.heartbeat.max_repeated_failures or task.status == "paused":
                task.status = "paused"
                await self._disable_heartbeat(task)
            self.agent_runtime.record_pause(
                task,
                reason=f"{type(exc).__name__}: {exc}",
                missing=[str(exc)],
            )
            self.storage.save_task(task)
            return (
                f"tick 失败：{exc}\n"
                f"同类问题计数：{count}。"
                f"{' 已暂停任务并关闭心跳。' if task.status == 'paused' else ''}"
            )
        finally:
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if latest and latest.task_id == task.task_id:
                self._release_task_lease(latest, lease_token)
                self.agent_runtime.update_resume(latest, reason=f"lease_released:{reason}")
                self.storage.save_task(latest)
            self._running_ticks.discard(tick_key)

