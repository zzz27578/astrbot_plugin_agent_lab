"""Core TaskEngine orchestration for Agent Lab v1.0.0.

Implements:
- Two-Phase Lifecycle (planning with read-only tools -> grounded plan -> executing)
- Authority-expansion-only plan re-approval (routine step splits/checks never pause)
- Terminal fence supremacy (`store.mark_ended` written FIRST)
- Startup crash recovery (`started` -> `unknown`, `running` -> `paused`)
- Global concurrency semaphore + fresh re-read after acquiring semaphore
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .bridge import AstrBotBridge, BudgetExceeded, ExecutionStopped
from .guards import DeliveryVerifier, ProgressGuard
from .models import (
    ApprovalRequest,
    BudgetConfig,
    ContinuityConfig,
    ExecutionSettings,
    Profile,
    QuestionItem,
    TaskMeta,
    TaskStep,
    new_id,
    now_iso,
)
from .permissions import call_signature
from .store import AgentLabStore


def _parse_iso_ts(iso_str: str) -> float:
    from datetime import datetime

    try:
        return datetime.fromisoformat(iso_str).timestamp()
    except Exception:
        return time.time()


def _normalize_steps(raw_steps: Any, existing: list[TaskStep] | None = None) -> list[TaskStep]:
    if not isinstance(raw_steps, (list, tuple)):
        return list(existing or [])
    out: list[TaskStep] = []
    for idx, item in enumerate(raw_steps, start=1):
        if isinstance(item, TaskStep):
            out.append(item)
        elif isinstance(item, dict):
            out.append(TaskStep.from_dict(item, idx=idx))
        else:
            title = str(item or "").strip()
            if title:
                out.append(TaskStep(id=f"s{idx}", title=title[:160]))
    return out


class TaskEngine:
    """Orchestrates task lifecycles, approvals, questions, recovery, and background execution."""

    def __init__(
        self,
        store: AgentLabStore,
        context: Any = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.store = store
        self.context = context
        self.config = dict(config or {})
        self.progress_guard = ProgressGuard()
        self.verifier = DeliveryVerifier()
        self.bridge = AstrBotBridge(self)

        max_conc = max(1, int(self.config.get("max_concurrent_tasks", 3) or 3))
        self._semaphore = asyncio.Semaphore(max_conc)
        self._runners: dict[str, asyncio.Task[Any]] = {}
        self._closing = False

    # ── Settings Merge ───────────────────────────────────────────────────────

    def _merge_execution_settings(
        self, profile: Profile, proj_settings: ExecutionSettings
    ) -> ExecutionSettings:
        default_exec = ExecutionSettings()
        mode = (
            proj_settings.mode
            if proj_settings.mode != default_exec.mode
            else profile.permission_mode
        )
        budget = (
            proj_settings.budget
            if proj_settings.budget.to_dict() != BudgetConfig().to_dict()
            else BudgetConfig.from_dict(profile.budget.to_dict())
        )
        continuity = (
            proj_settings.continuity
            if proj_settings.continuity.to_dict() != ContinuityConfig().to_dict()
            else ContinuityConfig.from_dict(profile.continuity.to_dict())
        )
        creds = list(
            dict.fromkeys(
                list(profile.authorized_credentials or [])
                + list(proj_settings.authorized_credentials or [])
            )
        )
        return ExecutionSettings(
            mode=mode,
            roots=list(proj_settings.roots or []),
            warnings=list(proj_settings.warnings or []),
            task_prompt=proj_settings.task_prompt or profile.task_prompt,
            authorized_credentials=creds,
            budget=budget,
            continuity=continuity,
        )

    # ── Lifecycle: Start ─────────────────────────────────────────────────────

    async def start_task(
        self,
        umo: str,
        goal: str,
        *,
        project_id: str = "",
        profile_id: str = "",
        brief: str = "",
        constraints: list[str] | None = None,
        completion_conditions: list[str] | None = None,
        plan_steps: list[Any] | None = None,
        event: Any = None,
    ) -> TaskMeta:
        # Pause any currently running task in the same UMO
        prev = self.store.load_active_task(umo)
        if prev and not prev.is_terminal() and prev.status == "running":
            prev.status = "paused"
            prev.human_paused = True
            prev.wait_reason = "human_paused"
            self.store.save_task(prev, active=False)
            prev_runner = self._runners.pop(prev.task_id, None)
            if prev_runner and not prev_runner.done():
                prev_runner.cancel()

        project = self.store.get_project(project_id) if project_id else None
        if project is None:
            project = self.store.ensure_default_project(umo)

        profile = self.store.get_profile(profile_id or project.profile_id)
        exec_settings = self._merge_execution_settings(profile, project.execution_settings)
        scope_roots = list(exec_settings.roots)

        steps = _normalize_steps(plan_steps) if plan_steps else []
        approvals: list[ApprovalRequest] = []
        if steps:
            status = "paused"
            phase = "planning"
            wait_reason = "need_plan_approval"
            version = 1
            approvals.append(
                ApprovalRequest(
                    approval_id=new_id("apr"),
                    approval_type="task_plan",
                    operation="初始执行计划审批",
                    reason="创建任务时已提供预设执行步骤，等待确认后开始执行。",
                    plan_version=1,
                )
            )
        else:
            status = "running"
            phase = "planning"
            wait_reason = ""
            version = 0

        task = TaskMeta(
            task_id=new_id("task"),
            umo=umo,
            project_id=project.project_id,
            profile_id=profile.profile_id,
            goal=str(goal or "").strip()[:1200],
            brief=str(brief or "").strip()[:3000],
            status=status,
            phase=phase,
            wait_reason=wait_reason,
            completion_conditions=[
                str(c).strip() for c in (completion_conditions or []) if str(c).strip()
            ],
            constraints=[
                str(c).strip() for c in (constraints or []) if str(c).strip()
            ],
            steps=steps,
            version=version,
            scope_roots=scope_roots,
            authorized_scope_roots=list(scope_roots),
            execution_settings=exec_settings,
            approvals=approvals,
        )

        self.store.save_task(task, active=True)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {
                "event": "task_started",
                "phase": task.phase,
                "status": task.status,
                "goal": task.goal,
            },
        )
        if task.status == "paused" and task.wait_reason == "need_plan_approval":
            await self.bridge.send_dm(
                task.umo,
                f"📋 任务 `{task.task_id}` 已创建并提交初始计划，等待审批后执行：{task.goal}",
                kind="approval",
                task_id=task.task_id,
                force=True,
            )
        elif event is not None and task.status == "running":
            self.schedule(event, task.task_id)

        return task

    # ── Planning & Authority Expansion ───────────────────────────────────────

    async def submit_plan(
        self,
        task_id: str,
        steps: Any,
        *,
        goal: str = "",
        completion_conditions: list[str] | None = None,
        scope_roots: list[str] | None = None,
        remove_constraints: list[str] | None = None,
        constraints: list[str] | None = None,
        summary: str = "",
        completed_step: str = "",
        message: str = "",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        parsed_steps = _normalize_steps(steps, existing=task.steps)
        if completed_step:
            for st in parsed_steps:
                if st.id == completed_step or st.title == completed_step:
                    st.status = "completed"
        if not parsed_steps:
            return {"ok": False, "error": "计划步骤不能为空。"}

        is_initial = task.approved_version == 0
        clean_goal = str(goal or "").strip()
        goal_changed = bool(clean_goal and clean_goal != task.goal)
        conds_changed = (
            completion_conditions is not None
            and [str(c).strip() for c in completion_conditions if str(c).strip()]
            != list(task.completion_conditions)
        )
        auth_roots = set(task.authorized_scope_roots or task.scope_roots)
        req_roots = [str(r).strip() for r in (scope_roots or []) if str(r).strip()]
        new_roots = [r for r in req_roots if r not in auth_roots]
        rem_cons = [
            str(c).strip()
            for c in (remove_constraints or [])
            if str(c).strip() in task.constraints
        ]

        needs_approval = (
            is_initial
            or goal_changed
            or conds_changed
            or bool(new_roots)
            or bool(rem_cons)
        )

        task.steps = parsed_steps
        if summary:
            task.current_summary = str(summary).strip()[:2000]
        if not task.current_step_id:
            first_pending = next((s for s in parsed_steps if s.status != "completed"), parsed_steps[0])
            task.current_step_id = first_pending.id

        if constraints is not None:
            merged_cons = list(task.constraints)
            for c in constraints:
                sc = str(c).strip()
                if sc and sc not in merged_cons:
                    merged_cons.append(sc)
            task.constraints = merged_cons

        if needs_approval:
            task.version += 1
            if goal_changed:
                task.goal = clean_goal[:1200]
            if conds_changed and completion_conditions is not None:
                task.completion_conditions = [
                    str(c).strip() for c in completion_conditions if str(c).strip()
                ]
            if new_roots:
                task.scope_roots = list(dict.fromkeys(list(task.scope_roots) + new_roots))

            reasons: list[str] = []
            if is_initial:
                reasons.append("初始执行计划")
            if goal_changed:
                reasons.append("目标变更")
            if conds_changed:
                reasons.append("完成条件变更")
            if new_roots:
                reasons.append(f"新增目录范围: {', '.join(new_roots)}")
            if rem_cons:
                reasons.append(f"申请移除约束: {', '.join(rem_cons)}")

            req = ApprovalRequest(
                approval_id=new_id("apr"),
                approval_type="task_plan",
                operation="初始计划审批" if is_initial else "权限/目标扩展审批",
                reason="；".join(reasons),
                message=str(message or "").strip()[:2000],
                plan_version=task.version,
                workspace_root=task.session_workspace_root,
                calls=[{"remove_constraints": rem_cons}] if rem_cons else [],
            )
            task.approvals.append(req)
            task.status = "paused"
            task.wait_reason = "need_plan_approval"
            self.store.save_task(task)
            self.store.append_event(
                task.umo,
                task.task_id,
                "log",
                {
                    "event": "plan_submitted",
                    "version": task.version,
                    "needs_approval": True,
                    "approval_id": req.approval_id,
                    "reasons": reasons,
                },
            )
            steps_preview = "\n".join(f"- [{s.id}] {s.title}" for s in parsed_steps[:8])
            await self.bridge.send_dm(
                task.umo,
                f"📋 任务 `{task.task_id}` 提交计划 v{task.version}（{req.operation}）：\n{steps_preview}\n\n原因：{req.reason}",
                kind="approval",
                task_id=task.task_id,
                force=True,
            )
            return {
                "ok": True,
                "needs_approval": True,
                "approval_id": req.approval_id,
                "version": task.version,
                "wait_reason": task.wait_reason,
            }

        # Routine plan update (step split/add/reorder/check) -> no pause!
        task.version += 1
        task.approved_version = task.version
        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {
                "event": "plan_updated_routine",
                "version": task.version,
                "completed_step": completed_step,
            },
        )
        return {
            "ok": True,
            "needs_approval": False,
            "version": task.version,
            "approved_version": task.approved_version,
        }

    # ── Approvals ────────────────────────────────────────────────────────────

    async def request_approval(
        self,
        task_id: str,
        *,
        operation: str,
        reason: str = "",
        impact: str = "",
        rollback: str = "",
        calls: list[dict[str, Any]] | None = None,
        operations: list[dict[str, Any]] | None = None,
        message: str = "",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        raw_calls = list(calls or operations or [])
        if not (1 <= len(raw_calls) <= 20):
            raise ValueError("tool_batch 审批必须包含 1 到 20 个操作。")

        norm_calls: list[dict[str, Any]] = []
        ws = task.session_workspace_root or task.execution_cwd or ""
        for c in raw_calls:
            if not isinstance(c, dict):
                continue
            tname = str(c.get("tool_name") or c.get("tool") or c.get("name") or "").strip()
            targs = dict(c.get("arguments") or c.get("args") or {})
            if not tname:
                raise ValueError("待审批操作缺少 tool_name。")
            sig = call_signature(tname, targs, ws, task.version)
            norm_calls.append(
                {
                    "tool_name": tname,
                    "arguments": self.store.redact_secrets(targs),
                    "signature": sig,
                    "call_signature": sig,
                    "execution_status": "pending",
                    "status": "pending",
                }
            )
        if not (1 <= len(norm_calls) <= 20):
            raise ValueError("tool_batch 审批必须包含 1 到 20 个有效操作。")

        req = ApprovalRequest(
            approval_id=new_id("apr"),
            approval_type="tool_batch",
            operation=str(operation or "高风险操作审批").strip()[:240],
            reason=str(reason or "").strip()[:600],
            impact=str(impact or "").strip()[:600],
            rollback=str(rollback or "").strip()[:400],
            message=str(message or "").strip()[:2000],
            plan_version=task.version,
            workspace_root=task.session_workspace_root,
            calls=norm_calls,
        )
        task.approvals.append(req)
        task.status = "paused"
        task.wait_reason = "need_tool_approval"
        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {
                "event": "tool_approval_requested",
                "approval_id": req.approval_id,
                "operation": req.operation,
                "call_count": len(norm_calls),
            },
        )
        await self.bridge.send_dm(
            task.umo,
            f"🔐 任务 `{task.task_id}` 请求操作审批（{len(norm_calls)} 项）：{req.operation}\n原因：{req.reason or '需人工确认'}",
            kind="approval",
            task_id=task.task_id,
            force=True,
        )
        return {
            "ok": True,
            "approval_id": req.approval_id,
            "wait_reason": task.wait_reason,
            "calls": len(norm_calls),
        }

    async def resolve_approval(
        self,
        task_id: str,
        decision: str,
        *,
        approval_id: str = "",
        note: str = "",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        pending = task.pending_approvals()
        target: ApprovalRequest | None = None
        if approval_id:
            target = next((a for a in pending if a.approval_id == approval_id), None)
        elif pending:
            target = pending[-1]
        if target is None:
            return {"ok": False, "error": "当前没有待处理的审批请求。"}

        norm = str(decision or "").strip().lower()
        if norm in {"approved", "approve", "yes", "y", "ok", "同意", "批准"}:
            norm = "approved"
        elif norm in {"rejected", "reject", "no", "n", "deny", "拒绝", "驳回"}:
            norm = "rejected"
        else:
            raise ValueError(f"不支持的审批决定: {decision!r}")

        target.decision = norm
        target.decision_note = str(note or "").strip()[:400]
        target.resolved_at = now_iso()

        if norm == "approved":
            target.status = "approved"
            if target.approval_type == "task_plan":
                # Apply any approved constraint removals
                for c in target.calls:
                    for rc in (c.get("remove_constraints") or []):
                        if rc in task.constraints:
                            task.constraints.remove(rc)
                task.approved_version = task.version
                task.authorization_version = task.version
                task.authorized_scope_roots = list(
                    dict.fromkeys(task.scope_roots or task.execution_settings.roots)
                )
                task.phase = "executing"

            if not task.pending_approvals() and not task.pending_questions() and not self._unknown_calls(task):
                task.status = "running"
                task.wait_reason = ""
                task.human_paused = False

            self.store.save_task(task)
            self.store.append_event(
                task.umo,
                task.task_id,
                "log",
                {
                    "event": "approval_resolved",
                    "approval_id": target.approval_id,
                    "decision": "approved",
                    "note": target.decision_note,
                },
            )
            if event is not None and task.status == "running":
                self.schedule(event, task.task_id)
            return {
                "ok": True,
                "approval_id": target.approval_id,
                "decision": "approved",
                "status": task.status,
                "phase": task.phase,
            }

        # Rejected
        target.status = "rejected"
        guidance_text = (
            f"管理员拒绝了审批 `{target.operation}`"
            + (f"（说明：{target.decision_note}）" if target.decision_note else "")
            + "。请严格遵守决定，切勿微调参数重试被拒绝的操作。"
        )
        task.guidance = (task.guidance + [{"time": now_iso(), "text": guidance_text}])[-30:]
        task.input_revision += 1

        if target.approval_type == "task_plan" and task.approved_version == 0:
            task.phase = "planning"
            task.status = "paused"
            task.wait_reason = "human_paused"
        else:
            if not task.pending_approvals() and not task.pending_questions() and not self._unknown_calls(task):
                if event is not None:
                    task.status = "running"
                    task.wait_reason = ""
                else:
                    task.status = "paused"
                    task.wait_reason = "human_paused"

        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {
                "event": "approval_resolved",
                "approval_id": target.approval_id,
                "decision": "rejected",
                "note": target.decision_note,
            },
        )
        if event is not None and task.status == "running":
            self.schedule(event, task.task_id)
        return {
            "ok": True,
            "approval_id": target.approval_id,
            "decision": "rejected",
            "status": task.status,
            "phase": task.phase,
        }

    # ── Questions ────────────────────────────────────────────────────────────

    async def ask_question(
        self,
        task_id: str,
        question: str,
        *,
        options: list[str] | None = None,
        recommendation: str = "",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        q = QuestionItem(
            question_id=new_id("q"),
            question=str(question or "").strip()[:800],
            options=[str(o).strip() for o in (options or []) if str(o).strip()][:6],
            recommendation=str(recommendation or "").strip()[:400],
        )
        task.questions.append(q)
        task.status = "paused"
        task.wait_reason = "need_answer"
        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "question_asked", "question_id": q.question_id, "question": q.question},
        )
        opt_text = "\n".join(f"  {i+1}. {o}" for i, o in enumerate(q.options))
        body = f"❓ 任务 `{task.task_id}` 需要您的确认：\n{q.question}"
        if opt_text:
            body += f"\n可选项：\n{opt_text}"
        if q.recommendation:
            body += f"\n建议：{q.recommendation}"
        await self.bridge.send_dm(
            task.umo, body, kind="question", task_id=task.task_id, force=True
        )
        return {
            "ok": True,
            "question_id": q.question_id,
            "wait_reason": task.wait_reason,
        }

    async def answer_question(
        self,
        task_id: str,
        answer: str,
        *,
        question_id: str = "",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        pending = task.pending_questions()
        target: QuestionItem | None = None
        if question_id:
            target = next((q for q in pending if q.question_id == question_id), None)
        elif pending:
            target = pending[-1]
        if target is None:
            return {"ok": False, "error": "当前没有待回答的问题。"}

        target.status = "answered"
        target.answer = str(answer or "").strip()[:1500]
        target.answered_at = now_iso()
        task.input_revision += 1

        if not task.pending_questions() and not task.pending_approvals() and not self._unknown_calls(task):
            task.wait_reason = ""
            task.human_paused = False
            task.status = "running"

        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {
                "event": "question_answered",
                "question_id": target.question_id,
                "answer": target.answer,
            },
        )
        if event is not None and task.status == "running":
            self.schedule(event, task.task_id)
        return {
            "ok": True,
            "question_id": target.question_id,
            "status": task.status,
            "wait_reason": task.wait_reason,
        }

    # ── Unknown Call Reconciliation ──────────────────────────────────────────

    def _unknown_calls(self, task: TaskMeta) -> list[dict[str, Any]]:
        journal = self.store.latest_journal_by_call(task.umo, task.task_id)
        return [j for j in journal if j.get("status") in {"started", "unknown"}]

    async def reconcile_unknown_call(
        self,
        task_id: str,
        call_id: str,
        status: str,
        note: str = "",
        *,
        event: Any = None,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed", "not_started"}:
            raise ValueError("status 必须是 completed / failed / not_started 之一。")
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        self.store.append_event(
            task.umo,
            task.task_id,
            "journal",
            {
                "call_id": call_id,
                "status": status,
                "reconciled": True,
                "note": str(note or "").strip()[:400],
            },
        )
        remaining = self._unknown_calls(task)
        if not remaining and task.wait_reason == "unknown_call":
            task.wait_reason = ""
            if not task.human_paused and not task.pending_approvals() and not task.pending_questions():
                task.status = "running"
            self.store.save_task(task)
            if event is not None and task.status == "running":
                self.schedule(event, task.task_id)

        return {
            "ok": True,
            "call_id": call_id,
            "status": status,
            "remaining_unknown": len(remaining),
            "task_status": task.status,
            "wait_reason": task.wait_reason,
        }

    # ── Steering, Pause, Resume ──────────────────────────────────────────────

    async def steer(
        self, task_id: str, guidance: str, *, event: Any = None
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}
        text = str(guidance or "").strip()[:1000]
        if not text:
            return {"ok": False, "error": "引导内容不能为空。"}

        task.guidance = (task.guidance + [{"time": now_iso(), "text": text}])[-30:]
        task.input_revision += 1
        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "steered", "guidance": text, "input_revision": task.input_revision},
        )
        return {"ok": True, "input_revision": task.input_revision}

    async def record_progress(
        self,
        task_id: str,
        message: str,
        *,
        kind: str = "progress",
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        clean_msg = str(self.store.redact_secrets(message or "")).strip()
        if clean_msg:
            task.current_summary = clean_msg[:2000]
            self.store.save_task(task)
            self.store.append_event(
                task.umo,
                task.task_id,
                "log",
                {"event": "progress", "kind": kind, "message": clean_msg},
            )
            delivery = await self.bridge.send_dm(
                task.umo,
                clean_msg,
                kind=kind,
                task_id=task.task_id,
            )
        else:
            delivery = {"delivery": "skipped", "reason": "empty", "text": "", "kind": kind}

        return {
            "ok": True,
            "task_id": task.task_id,
            "current_summary": task.current_summary,
            "delivery": delivery,
        }

    async def pause(
        self,
        task_id: str,
        *,
        reason: str = "human_paused",
        human: bool = True,
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        task.status = "paused"
        task.human_paused = bool(human)
        if not task.wait_reason:
            task.wait_reason = "human_paused" if human else "paused"
        self.store.save_task(task)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "paused", "reason": reason, "human": bool(human)},
        )
        runner = self._runners.pop(task_id, None)
        if runner and not runner.done():
            runner.cancel()
        return {"ok": True, "status": task.status, "wait_reason": task.wait_reason}

    async def resume(self, task_id: str, *, event: Any = None) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        if task.pending_approvals():
            return {"ok": False, "error": "存在待审批操作，请先完成审批。"}
        if task.pending_questions():
            return {"ok": False, "error": "存在待回答问题，请先回答问题。"}
        if self._unknown_calls(task):
            return {"ok": False, "error": "存在未对账的未知调用，请先对账。"}

        task.human_paused = False
        task.wait_reason = ""
        task.status = "running"
        self.store.save_task(task)
        self.store.append_event(task.umo, task.task_id, "log", {"event": "resumed"})
        if event is not None:
            self.schedule(event, task.task_id)
        return {"ok": True, "status": task.status}

    # ── Terminal Transitions (Terminal Fence Written FIRST!) ─────────────────

    async def stop(
        self,
        task_id: str,
        *,
        reason: str = "管理员停止任务",
        actor: str = "admin",
        event: Any = None,
    ) -> dict[str, Any]:
        task = self.store.find_task_by_id(task_id)
        if not task:
            return {"ok": False, "error": "任务不存在。"}

        # CRITICAL: write immutable terminal fence FIRST
        self.store.mark_ended(task, "cancelled", actor)

        for a in task.approvals:
            if a.status == "pending":
                a.status = "cancelled"
        for q in task.questions:
            if q.status == "pending":
                q.status = "cancelled"

        task.status = "cancelled"
        task.phase = "cancelled"
        task.wait_reason = ""
        task.ended_at = now_iso()
        if reason and not task.final_summary:
            task.final_summary = reason

        runner = self._runners.pop(task_id, None)
        if runner and not runner.done():
            runner.cancel()

        self.store.save_task(task, active=False, allow_terminal=True)
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "stopped", "actor": actor, "reason": reason},
            allow_terminal=True,
        )
        await self.bridge.send_dm(
            task.umo,
            f"🛑 任务 `{task.task_id}` 已停止：{reason}",
            kind="status",
            task_id=task.task_id,
            force=True,
        )
        return {"ok": True, "ended": True, "status": "cancelled"}

    async def deliver_as_is(
        self,
        task_id: str,
        *,
        note: str = "",
        actor: str = "admin",
        event: Any = None,
    ) -> dict[str, Any]:
        task = self.store.find_task_by_id(task_id)
        if not task:
            return {"ok": False, "error": "任务不存在。"}

        # CRITICAL: write immutable terminal fence FIRST
        self.store.mark_ended(task, "completed", actor)

        for a in task.approvals:
            if a.status == "pending":
                a.status = "cancelled"
        for q in task.questions:
            if q.status == "pending":
                q.status = "cancelled"

        summary_text = (
            str(note or "").strip()
            or task.final_summary
            or task.current_summary
            or f"任务已按当前进展交付：{task.goal}"
        )
        task.status = "completed"
        task.phase = "completed"
        task.wait_reason = ""
        task.final_summary = summary_text[:8000]
        task.ended_at = now_iso()

        runner = self._runners.pop(task_id, None)
        if runner and not runner.done():
            runner.cancel()

        self.store.save_task(task, active=False, allow_terminal=True)
        try:
            self.store.save_project_summary(
                task.project_id, summary_text, task_id=task.task_id, auto=True
            )
        except ValueError:
            pass
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "delivered_as_is", "actor": actor},
            allow_terminal=True,
        )
        await self.bridge.send_dm(
            task.umo,
            f"✅ 任务 `{task.task_id}` 已按当前成果交付：\n{summary_text}",
            kind="delivery",
            task_id=task.task_id,
            force=True,
        )
        return {"ok": True, "ended": True, "status": "completed", "final_summary": summary_text}

    def _extract_gaps(self, verification: Any) -> list[str]:
        if verification is None:
            return []
        if isinstance(verification, bool):
            return [] if verification else ["交付验证未通过"]
        if isinstance(verification, list):
            return [str(x) for x in verification if str(x).strip()]
        if isinstance(verification, dict):
            if verification.get("ok") is True and not verification.get("gaps"):
                return []
            gaps = verification.get("gaps") or []
            return [str(x) for x in gaps if str(x).strip()] or (
                [] if verification.get("ok", True) else ["交付验证未通过"]
            )
        if isinstance(verification, tuple) and len(verification) >= 2:
            ok, gaps = verification[0], verification[1]
            if ok:
                return []
            return [str(x) for x in (gaps or []) if str(x).strip()] or ["交付验证未通过"]
        gaps = getattr(verification, "gaps", None)
        if gaps is not None:
            return [str(x) for x in gaps if str(x).strip()]
        return []

    async def finish_task(
        self,
        task_id: str,
        final_summary: str,
        *,
        message: str = "",
        admin_override: bool = False,
        event: Any = None,
    ) -> dict[str, Any]:
        if self.store.is_ended(task_id):
            return {"ok": False, "error": "任务已结束。"}
        task = self.store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            return {"ok": False, "error": "任务不存在或已结束。"}

        journal = self.store.latest_journal_by_call(task.umo, task.task_id)
        verification = self.verifier.verify_finish(
            task, journal, final_summary, admin_override=admin_override
        )
        gaps = self._extract_gaps(verification)
        if gaps and not admin_override:
            return {"ok": False, "gaps": gaps}

        # CRITICAL: write immutable terminal fence FIRST
        self.store.mark_ended(task, "completed", "admin" if admin_override else "agent")

        for a in task.approvals:
            if a.status == "pending":
                a.status = "cancelled"
        for q in task.questions:
            if q.status == "pending":
                q.status = "cancelled"

        clean_summary = str(final_summary or message or task.current_summary or "").strip()[:8000]
        task.status = "completed"
        task.phase = "completed"
        task.wait_reason = ""
        task.final_summary = clean_summary
        task.ended_at = now_iso()

        self.store.save_task(task, active=False, allow_terminal=True)
        try:
            self.store.save_project_summary(
                task.project_id, clean_summary, task_id=task.task_id, auto=True
            )
        except ValueError:
            pass
        self.store.append_event(
            task.umo,
            task.task_id,
            "log",
            {"event": "task_finished", "admin_override": admin_override},
            allow_terminal=True,
        )
        delivery_text = str(message or "").strip() or clean_summary
        await self.bridge.send_dm(
            task.umo,
            f"🎉 任务 `{task.task_id}` 已完成交付：\n{delivery_text}",
            kind="delivery",
            task_id=task.task_id,
            force=True,
        )
        return {"ok": True, "ended": True, "status": "completed", "final_summary": clean_summary}

    # ── Startup Recovery ─────────────────────────────────────────────────────

    def recover_on_startup(self) -> dict[str, int]:
        unknown_marked = 0
        paused_count = 0
        for task in self.store.list_tasks():
            if self.store.is_ended(task.task_id) or task.is_terminal():
                continue
            journal = self.store.latest_journal_by_call(task.umo, task.task_id)
            changed = False
            for entry in journal:
                if entry.get("status") == "started":
                    self.store.append_event(
                        task.umo,
                        task.task_id,
                        "journal",
                        {
                            "call_id": entry.get("call_id"),
                            "tool_name": entry.get("tool_name"),
                            "status": "unknown",
                            "recovered": True,
                        },
                    )
                    unknown_marked += 1
                    changed = True
            if task.status == "running":
                task.status = "paused"
                task.human_paused = True
                task.wait_reason = "recovered_pause"
                self.store.save_task(task)
                paused_count += 1
            elif changed and not task.wait_reason:
                task.status = "paused"
                task.wait_reason = "unknown_call"
                self.store.save_task(task)
        return {"unknown_marked": unknown_marked, "paused": paused_count}

    # ── Background Scheduling & Execution Loop ───────────────────────────────

    def schedule(self, event: Any, task_id: str) -> asyncio.Task[Any] | None:
        if self._closing or self.store.is_ended(task_id):
            return None
        existing = self._runners.get(task_id)
        if existing and not existing.done():
            return existing
        runner_task = asyncio.create_task(self._drive(event, task_id))
        self._runners[task_id] = runner_task

        def _cleanup(t: asyncio.Task[Any]) -> None:
            if self._runners.get(task_id) is t:
                self._runners.pop(task_id, None)

        runner_task.add_done_callback(_cleanup)
        return runner_task

    async def close(self) -> None:
        self._closing = True
        tasks = list(self._runners.values())
        for t in tasks:
            if not t.done():
                t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._runners.clear()

    async def stop_all(self) -> None:
        await self.close()

    def _budget_exceeded_reason(self, task: TaskMeta) -> str:
        budget = task.execution_settings.budget
        if budget.max_total_ticks > 0 and task.usage.ticks_used >= budget.max_total_ticks:
            return f"已达到最大运行轮次上限 ({task.usage.ticks_used}/{budget.max_total_ticks})。"
        if budget.max_total_seconds > 0:
            elapsed = time.time() - _parse_iso_ts(task.started_at)
            if elapsed >= budget.max_total_seconds:
                return f"已达到最大运行时间上限 ({int(elapsed)}s/{budget.max_total_seconds}s)。"
        if budget.max_total_tokens > 0 and task.usage.total_tokens >= budget.max_total_tokens:
            return f"已达到总 Token 上限 ({task.usage.total_tokens}/{budget.max_total_tokens})。"
        if budget.max_total_tool_calls > 0 and task.usage.tool_calls >= budget.max_total_tool_calls:
            return f"已达到工具调用次数上限 ({task.usage.tool_calls}/{budget.max_total_tool_calls})。"
        return ""

    async def _drive(self, event: Any, task_id: str) -> None:
        while not self._closing:
            reschedule = False
            async with self._semaphore:
                if self._closing or self.store.is_ended(task_id):
                    return
                task = self.store.find_task_by_id(task_id)
                if not task or task.is_terminal() or task.status != "running" or task.human_paused:
                    return
                if task.pending_approvals() or task.pending_questions() or self._unknown_calls(task):
                    return

                budget_msg = self._budget_exceeded_reason(task)
                if budget_msg:
                    task.status = "paused"
                    task.wait_reason = "budget"
                    self.store.save_task(task)
                    await self.bridge.send_dm(
                        task.umo,
                        f"⏸️ 任务 `{task.task_id}` 已暂停：{budget_msg}",
                        kind="alert",
                        task_id=task.task_id,
                        force=True,
                    )
                    return

                task.usage.ticks_used += 1
                self.store.save_task(task)

                try:
                    await self.bridge.run_task_turn(event, task)
                except BudgetExceeded as exc:
                    fresh = self.store.find_task_by_id(task_id) or task
                    if not self.store.is_ended(task_id):
                        fresh.status = "paused"
                        fresh.wait_reason = "budget"
                        self.store.save_task(fresh)
                        await self.bridge.send_dm(
                            fresh.umo,
                            f"⏸️ 任务 `{fresh.task_id}` 已暂停：{exc}",
                            kind="alert",
                            task_id=fresh.task_id,
                            force=True,
                        )
                    return
                except ExecutionStopped:
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    fresh = self.store.find_task_by_id(task_id) or task
                    if not self.store.is_ended(task_id):
                        self.store.append_event(
                            fresh.umo,
                            fresh.task_id,
                            "log",
                            {"event": "tick_error", "error": str(exc)},
                        )
                        fresh.status = "paused"
                        fresh.wait_reason = "tick_error"
                        self.store.save_task(fresh)
                        await self.bridge.send_dm(
                            fresh.umo,
                            f"⚠️ 任务 `{fresh.task_id}` 本轮执行异常已暂停：{exc}",
                            kind="alert",
                            task_id=fresh.task_id,
                            force=True,
                        )
                    return

                # Re-check after turn whether we should continue to next tick
                after = self.store.find_task_by_id(task_id)
                if (
                    after
                    and not self.store.is_ended(task_id)
                    and not after.is_terminal()
                    and after.status == "running"
                    and not after.human_paused
                    and not after.pending_approvals()
                    and not after.pending_questions()
                    and not self._unknown_calls(after)
                ):
                    reschedule = True

            if not reschedule:
                return
            await asyncio.sleep(0)

    # ── Aggregation for WebUI & Daily Status ─────────────────────────────────

    def task_detail(self, task_id: str) -> dict[str, Any]:
        task = self.store.find_task_by_id(task_id)
        if not task:
            raise ValueError(f"任务不存在: {task_id}")
        journal = self.store.latest_journal_by_call(task.umo, task.task_id)
        unknown_calls = [j for j in journal if j.get("status") in {"started", "unknown"}]
        messages = self.store.read_events(task.umo, task.task_id, kind="message", limit=200)
        usage_events = self.store.read_events(task.umo, task.task_id, kind="usage", limit=200)
        files = self.store.task_files_manifest(task.umo, task.task_id)
        profile = self.store.get_profile(task.profile_id)
        project = self.store.get_project(task.project_id)
        return {
            "meta": task.to_dict(),
            "journal": journal,
            "messages": messages,
            "usage_events": usage_events,
            "files": files,
            "profile": profile.to_dict(),
            "project": project.to_dict() if project else None,
            "unknown_calls": unknown_calls,
        }
