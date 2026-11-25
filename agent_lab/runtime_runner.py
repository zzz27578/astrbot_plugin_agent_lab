from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any

from .hooks import AgentLabRunHooks
from .usage_metrics import budget_tokens
from .models import AgentSpec
from .prompts import build_task_system_prompt
from .task_control import control, prompt as plan_prompt
from .astrbot_bridge import BudgetStopped, ExecutionStopped
from .task_permissions import apply_mode
from .continuity import HandoffError
from .progress_guard import ProgressSnapshot, after_tick, snapshot, take_notice


def total_remaining_seconds(task: Any) -> float | None:
    """Wall-clock task budget from created_at, including administrator waits.

    None means unlimited. getattr keeps legacy/simple adapter budgets usable.
    Invalid timestamps cannot safely grant a fresh budget; treat as exhausted.
    """
    settings = task.workflow_data.get("task_control", {}).get("execution_settings", {})
    limit = getattr(task.budget, "max_total_seconds", None)
    if limit is None:
        limit = settings.get("budget", {}).get("max_total_seconds", 0)
    if not limit:
        return None
    try:
        stamp = datetime.fromisoformat(str(task.created_at).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        elapsed = max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
        return max(0, float(limit) - elapsed)
    except (AttributeError, TypeError, ValueError):
        return 0.0


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

    def owner_access(self, event):
        self.adapter._require_task_access(event)

    def _watchdog_after_tick(self, task: Any, *, before_hash: ProgressSnapshot,
                             reason: str, error: str = "", error_reason: str = "blocked_by_error") -> None:
        # Bridge observes results in the live loop. This fallback deduplicates
        # journal rows and never treats quiet ticks as a lack of progress.
        if self._execution_stopped(task) or self._pause_for_total_budget(task):
            return
        message = after_tick(task, before_hash, reason=reason, error=error, error_reason=error_reason)
        messages = getattr(self.adapter, "task_messages", None)
        if message and messages:
            try:
                guard = task.workflow_data["progress_guard"]
                messages.record_local(task, {"reason": task.wait.wait_reason if task.status == "paused" else "liveness_warning",
                                            "counters": {**guard["signals"],
                                                         "no_progress_ticks": guard["no_progress_ticks"],
                                                         "failure_ticks": guard["failure_ticks"]}}, "warning")
            except (OSError, ValueError):
                task.add_log("liveness_warning_storage", "预警消息未写入，任务进展防护状态已保留。")
        prepare = getattr(self.adapter, "_prepare_resume_anchor", None)
        if prepare:
            prepare(task, reason=reason)

    def _liveness_notice(self, task: Any) -> str:
        message = take_notice(task)
        if message:
            # A provider lookup or the next tick reloads from storage. Persist
            # only notice consumption, preserving newer administrator state.
            latest = self.storage.load_active_task(task.umo)
            if latest and latest.task_id == task.task_id:
                guard = latest.workflow_data.get("progress_guard", {})
                if guard.get("pending_notice") == message:
                    guard.pop("pending_notice", None)
                    self.storage.save_task(latest)
        return f"\n\n{message}" if message else ""

    def _task_prompts(self, task: Any, spec: Any, reason: str) -> tuple[str, str]:
        state = control(task)
        if state.get("workflow") == "none":
            system = ("你正在 Agent Lab 任务模式中执行任务，保持来源 Bot 的人设与自然语气。"
                      "使用宿主工具完成读取、编辑和测试。控制工具只有 task_plan、task_progress、task_ask、task_approve、task_finish。"
                      "初始计划需批准；授权内自由调整步骤，高危或扩大授权先请示。"
                      "缺少关键决策时提问，及时报告重要进展，最终交付说明实际成果和真实验证结果。")
            system += "\n项目任务指引：" + state.get("execution_settings", {}).get("task_prompt", "")
            header, separator, payload = plan_prompt(task).partition("]\n")
            plan = json.loads(payload)
            # Preserve both handoff sources if they differ, without duplicating
            # the usual identical entry summary and task brief. Keep them in the
            # user plan so mutable task context cannot change the system prefix.
            plan["brief"] = "\n\n".join(dict.fromkeys(value for value in
                (getattr(task, "task_brief", ""), getattr(task, "entry_summary", "")) if value))
            return system, "继续推进当前任务。" + header + separator + json.dumps(plan, ensure_ascii=False)
        modules = self._build_task_extensions_prompt(spec, task=task)
        system = build_task_system_prompt(spec, task, modules)
        system += "\n项目任务指引：" + state.get("execution_settings", {}).get("task_prompt", "")
        return system, self._workflow_react_prompt(task=task, spec=spec, reason=reason) + plan_prompt(task)

    @staticmethod
    def _execution_revision(task: Any) -> tuple:
        state = control(task)
        # Routine task_plan revisions advance both plan versions while retaining
        # authority. Only new authority or administrator input invalidates work.
        return (state.get("authorization_version", state.get("approved_version")), state.get("input_revision", 0))

    @staticmethod
    def _execution_stopped(task: Any, revision: tuple | None = None) -> bool:
        state = control(task)
        return (task.status != "running" or bool(state.get("human_paused"))
                or bool(task.pending_approvals())
                or not state.get("approved_version")
                or state.get("version") != state.get("approved_version")
                or (revision is not None and AgentRuntimeRunner._execution_revision(task) != revision))

    def _pause_for_total_budget(self, task: Any, *, tick_finished: bool = True) -> str:
        # ticks_used includes the current admitted tick. It must be allowed to
        # finish, while exhausted tool/token totals forbid another dispatch.
        budget = task.budget
        remaining = total_remaining_seconds(task)
        if remaining is not None and remaining <= 0:
            limit = getattr(budget, "max_total_seconds", None)
            if limit is None:
                limit = control(task).get("execution_settings", {}).get("budget", {}).get("max_total_seconds", 0)
            message = f"任务总耗时预算已用尽：{limit}s（从任务创建起计算，含等待时间）"
            self._pause_task_for_budget(task, message)
            return message
        limits = [(budget.max_total_tool_calls, budget.tool_calls_used, "工具调用"),
                  (budget.max_total_tokens, budget_tokens(task), "token（含未报告估算）")]
        if tick_finished:
            limits.insert(0, (budget.max_total_ticks, budget.ticks_used, "tick"))
        for limit, used, label in limits:
            if limit and used >= limit:
                message = f"任务 {label} 总预算已用尽：{used}/{limit}"
                self._pause_task_for_budget(task, message)
                return message
        return ""

    async def run_tick(self, event: Any, reason: str) -> str:
        task = self.storage.load_active_task(event.unified_msg_origin)
        if not task:
            return "当前没有 active task。可以先 /agentlab start <目标>。"
        self.owner_access(event)
        refresh = getattr(self.task_control, "refresh_execution_settings", None)
        if refresh:
            refresh(task)
        state = control(task)
        if not state:
            self.task_control.initialize(task, event, "selected")
            self.storage.save_task(task)
            return "旧任务记录已保留，请先补充并批准具体计划，再继续执行。"
        if state and (not state.get("approved_version") or state.get("approved_version") != state.get("version")):
            return "请 Bot 先提交具体计划，管理员批准后自动推进。"
        if state.get("human_paused"):
            return "任务已由管理员暂停，请明确恢复。"
        if task.status not in ("running",):
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
        execution_revision = None
        before_hash = snapshot(task)
        _gate = getattr(self, "_global_tick_semaphore", None)
        _gate_held = False
        canvas = control(task).get("workflow") != "none"
        try:
            if _gate is not None:
                remaining = total_remaining_seconds(task)
                if remaining is None:
                    await _gate.acquire()
                else:
                    await asyncio.wait_for(_gate.acquire(), timeout=remaining)
                _gate_held = True
            # Waiting for a global slot must not revive a paused/replaced task
            # through the lease writer's older snapshot.
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if not latest or latest.task_id != task.task_id:
                return "任务已结束或切换。"
            task = latest
            if self._execution_stopped(task):
                return "任务状态或计划已变化，停止本轮执行。"
            lease_ok, lease_message = self._acquire_task_lease(task, reason=reason)
            if not lease_ok:
                return lease_message
            lease_token = lease_message
            task = self.storage.load_active_task(event.unified_msg_origin) or task
            execution_revision = self._execution_revision(task)
            before_hash = snapshot(task)
            remaining = total_remaining_seconds(task)
            deadline = time.monotonic() + remaining if remaining is not None else None
            canvas = control(task).get("workflow") != "none"
            if canvas:
                tick_deadline = time.monotonic() + max(1, float(task.budget.max_seconds_per_tick or 240))
                deadline = min(deadline, tick_deadline) if deadline is not None else tick_deadline

            async def bounded(awaitable):
                # Plain tasks have no round deadline. Individual provider/tool
                # timeouts remain the host's responsibility.
                if deadline is None:
                    return await awaitable
                return await asyncio.wait_for(awaitable, timeout=max(0, deadline - time.monotonic()))

            if budget_message := self._pause_for_total_budget(task, tick_finished=False):
                self.storage.save_task(task)
                return budget_message
            watchdog_message = self._watchdog_before_tick(task, reason)
            if watchdog_message:
                self.storage.save_task(task)
                return watchdog_message

            spec = AgentSpec.from_dict(
                task.profile_snapshot.get("agent") or self.storage.get_agent().to_dict()
            )
            state = control(task)
            apply_mode(spec, state)
            current = next((step for step in state.get("steps", []) if step.get("status") != "completed"), None)
            if current:
                state["current_step_id"] = current["id"]
                current["status"] = "running"
                task.next_step = current["instruction"]
            self.storage.save_task(task)
            event.set_extra("agent_lab_input_revision", state.get("input_revision", 0))
            if not await bounded(self.astrbot_bridge.resume_batch(event, task)):
                latest = self.storage.load_active_task(event.unified_msg_origin)
                if latest and latest.task_id == task.task_id and not self._execution_stopped(latest, execution_revision):
                    self._watchdog_after_tick(latest, before_hash=before_hash, reason=reason)
                    self.storage.save_task(latest)
                    return "已保存审批批次进度；未派发动作仍在队列中。" + self._liveness_notice(latest)
                return "任务已暂停、结束或审批已变化，停止审批批次。"
            current_task = self.storage.load_active_task(event.unified_msg_origin)
            if not current_task or current_task.task_id != task.task_id:
                return "任务已结束或切换。"
            task = current_task
            if self._execution_stopped(task, execution_revision):
                return "任务已暂停或计划已变化，停止本轮执行。"
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
            runtime_run = await bounded(self._run_workflow_runtime(
                event=event,
                task=task,
                spec=spec,
                reason=reason,
            ))
            active = self.storage.load_active_task(event.unified_msg_origin)
            if not active or active.task_id != task.task_id:
                return "任务已在工作流阶段结束。"
            # Node dispatch may save newer approval/checkpoint data. Never replace
            # it with the outer tick snapshot.
            if self._execution_stopped(active, execution_revision):
                task = active
            elif runtime_run.changed:
                self.storage.save_task(task)

            latest_task = self.storage.load_active_task(event.unified_msg_origin)
            if not latest_task or latest_task.task_id != task.task_id:
                return "tick 完成，任务已在工作流运行时阶段结束或切换。"
            task = latest_task
            if self._execution_stopped(task, execution_revision) and task.status not in {"blocked", "paused"}:
                return "任务已终止或计划已变化，停止本轮执行。"
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
            if runtime_run.changed and not runtime_run.needs_react and not control(task).get("version"):
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
            system_prompt, prompt = self._task_prompts(task, spec, reason)
            notice = self._liveness_notice(task)
            if notice:
                prompt += notice
            provider_id = await bounded(self.context.get_current_chat_provider_id(event.unified_msg_origin))
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if not latest or latest.task_id != task.task_id or self._execution_stopped(latest, execution_revision):
                return "任务已暂停、结束或计划已变化，停止模型派发。"
            task = latest
            if budget_message := self._pause_for_total_budget(task, tick_finished=False):
                self.storage.save_task(task)
                return budget_message
            remaining_tool_steps = self._budget_remaining_tools(task)
            if remaining_tool_steps <= 0:
                self._watchdog_after_tick(task, before_hash=before_hash, reason=reason)
                self.storage.save_task(task)
                return "本轮工具预算已用尽，下轮从检查点继续。" + self._liveness_notice(task)
            resp = await bounded(self.astrbot_bridge.run(
                event, task, self._build_toolset(spec, event), prompt, system_prompt, remaining_tool_steps,
                AgentLabRunHooks(self.storage, task.umo, task.task_id, budget_max_tools=0,
                                progress_mode=str(_cfg(self.config, "agent_mode_progress_notice_mode", "agent_lab")))))
            text = (getattr(resp, "completion_text", "") or "").strip()
            latest_task = self.storage.load_active_task(event.unified_msg_origin)
            if not latest_task or latest_task.task_id != task.task_id:
                return f"tick 完成，任务已在本轮结束或切换。\n\n{self._compact_text(text, 1800)}"
            task = latest_task
            if self._execution_stopped(task, execution_revision):
                return "任务已暂停、终止或计划已变化，已停止接收旧执行结果。"
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
            return f"tick 完成。\n\n{self._compact_text(text, 1800)}" + self._liveness_notice(task)
        except BudgetStopped as exc:
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if latest and latest.task_id == task.task_id and not self._execution_stopped(latest, execution_revision):
                self._watchdog_after_tick(latest, before_hash=before_hash, reason=reason)
                self.storage.save_task(latest)
            return str(exc) + (self._liveness_notice(latest) if latest and latest.task_id == task.task_id else "")
        except ExecutionStopped as exc:
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if latest and latest.task_id == task.task_id and not self._execution_stopped(latest, execution_revision):
                self._watchdog_after_tick(latest, before_hash=before_hash, reason=reason)
                self.storage.save_task(latest)
            return str(exc) + (self._liveness_notice(latest) if latest and latest.task_id == task.task_id else "")
        except HandoffError as exc:
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if latest and latest.task_id == task.task_id and not self._execution_stopped(latest, execution_revision):
                latest.status = "paused"
                latest.set_wait(wait_reason="handoff_failed", message=str(exc), source="continuity", resume_command="任务继续")
                latest.add_log("handoff_failed", str(exc))
                self.storage.save_task(latest)
            return str(exc)
        except Exception as exc:
            latest = self.storage.load_active_task(event.unified_msg_origin)
            if latest is None or latest.task_id != task.task_id:
                return "任务已结束；停止保存旧执行结果。"
            task = latest
            if self._execution_stopped(task, execution_revision):
                return "任务已暂停、终止或计划已变化，已停止保存旧执行异常。"
            if isinstance(exc, asyncio.TimeoutError) and self._pause_for_total_budget(task, tick_finished=False):
                self.storage.save_task(task)
                return task.watchdog.paused_reason
            detail = ((f"画布轮次超时（上限 {task.budget.max_seconds_per_tick}s）" if canvas else "单次模型或工具调用超时")
                      if isinstance(exc, asyncio.TimeoutError) else f"{type(exc).__name__}: {exc}")
            error_reason = "runtime_timeout" if isinstance(exc, asyncio.TimeoutError) else "blocked_by_error"
            count = task.add_blocker(type(exc).__name__, str(exc))
            self._watchdog_after_tick(
                task,
                before_hash=before_hash,
                reason=reason,
                error=detail,
                error_reason=error_reason,
            )
            self.agent_runtime.record_pause(
                task,
                reason=detail,
                missing=[detail],
            )
            self.storage.save_task(task)
            return (
                f"tick 失败：{detail}\n"
                f"同类问题计数：{count}。"
                f"{' 已暂停任务并关闭心跳。' if task.status == 'paused' else ''}"
            ) + self._liveness_notice(task)
        finally:
            try:
                if _gate_held:
                    _gate.release()
                latest = self.storage.load_active_task(event.unified_msg_origin)
                if (latest and latest.task_id == task.task_id and latest.status != "running"
                        and (latest.heartbeat.enabled or latest.heartbeat.job_id)):
                    try:
                        await asyncio.wait_for(self._disable_heartbeat(latest), timeout=2)
                    except Exception as exc:
                        current = self.storage.load_active_task(event.unified_msg_origin)
                        if current and current.task_id == task.task_id:
                            current.add_log("heartbeat_cleanup_failed", type(exc).__name__)
                            self.storage.save_task(current)
                    else:
                        # Scheduler cleanup may yield. Merge only heartbeat
                        # fields and preserve a newer administrator decision.
                        current = self.storage.load_active_task(event.unified_msg_origin)
                        if current and current.task_id == task.task_id and current.status != "running":
                            current.heartbeat.enabled = False
                            current.heartbeat.job_id = ""
                            self.storage.save_task(current)
            finally:
                try:
                    latest = self.storage.load_active_task(event.unified_msg_origin)
                    if latest and latest.task_id == task.task_id and lease_token:
                        self._release_task_lease(latest, lease_token)
                        self.agent_runtime.update_resume(latest, reason=f"lease_released:{reason}")
                        self.storage.save_task(latest)
                finally:
                    self._running_ticks.discard(tick_key)

