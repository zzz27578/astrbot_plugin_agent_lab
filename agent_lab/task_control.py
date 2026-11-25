"""Task continuity layered on the existing TaskState and workflow modules.

The bot owns planning. The plugin owns durable checkpoints, approval and waking
the next bounded round. A canvas is optional guidance, never a second bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import ntpath
import posixpath
from copy import deepcopy
from typing import Any

from .models import ApprovalRequest, now_iso
from .execution_settings import BUDGET_LIMITS, integer, lines, normalize
from .continuity import working_context
from .task_permissions import authorized_roots
from .ledger_views import arguments_view
from .bot_identity import source_persona, persona_prompt
from .usage_metrics import record_request, request_size


def control(task) -> dict:
    return task.workflow_data.setdefault("task_control", {})


def prompt(task) -> str:
    state = control(task)
    if not state:
        return ""
    recent = []
    for row in reversed(state.get("journal", [])[-8:]):
        result = str(row.get("result", ""))
        recent.append({"name": row.get("name"), "arguments": arguments_view(row.get("arguments", {}), 240),
                       "status": row.get("status"), "step_id": row.get("step_id"),
                       "result": result[:600], "result_path": row.get("result_path", "")})
    return "\n[本次任务的持久计划，优先于旧对话摘要]\n" + json.dumps({
        "task_id": task.task_id, "goal": task.root_goal,
        "version": state.get("version", 0), "approved_version": state.get("approved_version", 0),
        "steps": [{"id": row["id"], "title": row["title"], "status": row["status"]} for row in state.get("steps", [])],
        "current_step": next((row for row in state.get("steps", []) if row["id"] == state.get("current_step_id")), None),
        "constraints": state.get("constraints", []),
        "current_step_id": state.get("current_step_id", ""),
        "workflow": state.get("workflow", "none"), "next_action": task.next_step,
        "stage_memory": working_context(task),
        "recent_plan_changes": state.get("plan_changes", [])[-4:],
        "execution_scope": {"mode": state.get("execution_settings", {}).get("mode", "standard"),
                            "roots": authorized_roots(state),
                            "warnings": state.get("execution_settings", {}).get("warnings", []) + state.get("risk_lines", []),
                            "approved_cleanup_paths": state.get("approved_cleanup_paths", [])},
        "guidance": state.get("guidance", [])[-8:],
        "questions": state.get("questions", [])[-5:],
        "recent_tools": list(reversed(recent)),
        "instruction": "按当前目标自主使用宿主工具读写、搜索和测试。task_plan 提交初始计划，执行中自由拆改、重排和勾选步骤，不中断执行或再次审阅；改变目标、验收、预算、解除约束或扩大授权路径须重新批准。task_progress 发简短进展；task_ask 提关键问题和选项；真正高危或越界操作先 task_approve 提交确切参数。过程自动记账，不需传内部记录ID；工具输出有完整文件路径时可用宿主读取工具查看。task_finish 说明成果、改动文件、实际验证结果和遗留问题，交付时核对真实记录。保持当前Bot人设；管理员暂停、停止和按现状交付始终优先。无画布直接按计划工作。",
    }, ensure_ascii=False)


class TaskControl:
    def __init__(self, owner):
        self.owner = owner
        self.running: dict[str, asyncio.Task] = {}
        self.closing = False

    def load(self, umo: str, task_id: str = ""):
        task = self.owner.storage.load_active_task(umo)
        if not task or (task_id and task.task_id != task_id):
            raise ValueError("任务已结束或已切换，请重新读取任务状态。")
        return task

    def refresh_execution_settings(self, task):
        """Reload administrator policy at a boundary; keep per-task budgets."""
        state = control(task)
        project_id = state.get("project_id")
        if not project_id:
            return False
        # Seed the legacy approved scope once, before a later plan can change it.
        if ("authorized_scope_roots" not in state and state.get("approved_version")
                and state.get("approved_version") == state.get("version")):
            state["authorized_scope_roots"] = list(state.get("scope_roots", []))
        project = self.owner.projects.project(project_id)
        if "execution_settings" not in project:
            return False
        settings = normalize(project["execution_settings"])
        previous = state.get("execution_settings", {})
        settings["budget"] = previous.get("budget", settings["budget"])
        changed = settings != previous
        if changed:
            state["execution_settings"] = settings
            state["input_revision"] = state.get("input_revision", 0) + 1
            state.pop("guard_refusals", None)
            for row in task.approvals:
                if row.get("status") == "approved" and row.get("approval_type") in {"tool_call", "tool_batch"}:
                    row["status"] = "expired"
            task.add_log("execution_settings", "已载入管理员最新权限规则；任务累计预算保持不变。")
        # Old versions automatically froze full-access tasks on harmless tools.
        # Discard only those generated cards, never an AI/user-requested review.
        expired = False
        if settings["mode"] == "full":
            for row in task.approvals:
                if (row.get("approval_type") == "tool_batch" and row.get("status") == "pending"
                        and row.get("reason") == "执行前风险检查"):
                    row["status"] = "expired"
                    expired = True
            if expired:
                task.add_log("approval_migrated", "旧版自动审批已撤销；按完全权限规则继续，必要审批由 AI 主动提出。")
                if (not state.get("human_paused") and not task.pending_approvals()
                        and state.get("approved_version") == state.get("version")
                        and not any(r.get("status") in {"started", "unknown"} for r in state.get("journal", []))
                        and task.status == "paused" and task.wait.wait_reason == "need_approval"):
                    task.status = "running"
                    task.clear_wait()
        if changed or expired:
            self.owner.storage.save_task(task)
        return changed or expired

    def initialize(self, task, event, workflow: str):
        task.workflow_data["task_control"] = {
            "version": 0, "approved_version": 0, "steps": [], "constraints": [],
            "workflow": workflow, "current_step_id": "", "journal": [], "guidance": [],
            "owner_id": str(event.get_sender_id()), "owner_admin": event.role == "admin",
            "web_admin": bool(event.get_extra("agent_lab_web_admin", False)),
            "automatic": True, "human_paused": False, "phase": "needs_plan",
        }
        task.status = "paused"
        task.next_step = "Bot 调用 task_plan 提交具体步骤，管理员批准后自动推进。"
        task.set_wait(wait_reason="need_plan", message=task.next_step, source="task_control")

    async def submit_plan(self, event, steps_json: str, constraints: str = "", *,
                          summary: str = "", completed_step: str = "", message: str = "") -> str:
        task = self.load(event.unified_msg_origin)
        state = control(task)
        if not state or "owner_id" not in state:
            project_id = state.get("project_id", "")
            self.initialize(task, event, "selected")
            state = control(task)
            state["project_id"] = project_id
        raw = json.loads(steps_json) if steps_json.strip() else deepcopy(state.get("steps", []))
        if not steps_json.strip():
            for item in raw:
                item.pop("reopen_reason", None)
        proposal = raw if isinstance(raw, dict) else {}
        if set(proposal) - {"steps", "scope_roots", "risk_lines", "cleanup_paths", "change_reason",
                            "goal", "completion_conditions", "budget", "remove_constraints", "message", "notifications"}:
            raise ValueError("计划不能修改权限或运行配置；请通过项目设置由管理员调整。")
        if len(summary) > 4000:
            raise ValueError("进展说明最多4000字符。")
        approval_message = str(message or proposal.get("message") or "").strip()
        if len(approval_message)>2000:
            raise ValueError("审批文案最多2000字符，请用当前Bot的自然表达简洁说明。")
        notifications=proposal.get("notifications",state.get("notifications",{}))
        if (not isinstance(notifications,dict) or set(notifications)-{"paused","error","budget","stalled"}
                or any(not isinstance(value,str) or not 1<=len(value.strip())<=800 for value in notifications.values())):
            raise ValueError("notifications仅支持paused/error/budget/stalled的Bot自拟正文，每条1–800字符。")
        scope_roots = state.get("scope_roots", [])
        risk_lines = state.get("risk_lines", [])
        cleanup_paths = []
        if isinstance(raw, dict):
            scope_roots = lines(raw.get("scope_roots", scope_roots))
            risk_lines = lines(list(dict.fromkeys(risk_lines + lines(raw.get("risk_lines", [])))))
            cleanup_paths = [p for p in lines(raw.get("cleanup_paths", [])) if p.startswith("/") and not p.endswith("/")]
            raw = raw.get("steps")
        if not isinstance(raw, list) or not 1 <= len(raw) <= 50:
            raise ValueError("计划必须是 1–50 个步骤的 JSON 数组。")
        old = {step["id"]: step for step in state.get("steps", [])}
        steps, ids = [], set()
        for index, item in enumerate(raw):
            item = {"title": item} if isinstance(item, str) else item
            if not isinstance(item, dict):
                raise ValueError("步骤应是字符串或对象。")
            identifier = str(item.get("id") or f"step_{index+1}")
            title = str(item.get("title") or "").strip()
            instruction = str(item.get("instruction") or title).strip()
            if not title or len(title) > 300 or not identifier or len(identifier) > 80 or identifier in ids or len(instruction) > 4000:
                raise ValueError("步骤需有名称、唯一 ID，说明不能超过4000字符。")
            ids.add(identifier)
            previous = old.get(identifier, {})
            reopen = str(item.get("reopen_reason") or "").strip()
            stage = str(item.get("stage") or previous.get("stage") or "task_execution").strip()
            if not stage or len(stage) > 120 or len(reopen) > 2000:
                raise ValueError("阶段名称需在120字以内，返工说明需在2000字以内。")
            status = item.get("status", "pending" if reopen else previous.get("status", "pending"))
            if status not in {"pending", "running", "completed"}:
                raise ValueError("步骤状态仅支持pending/running/completed。")
            step = {**deepcopy(previous), "id": identifier, "title": title, "instruction": instruction, "stage": stage,
                    "status": status, "evidence": [] if reopen else previous.get("evidence", []),
                    "revision": int(previous.get("revision", 0)) + int(bool(reopen))}
            if "summary" in item:
                if not isinstance(item["summary"], str) or len(item["summary"]) > 4000:
                    raise ValueError("步骤说明最多4000字符。")
                step["summary"] = item["summary"].strip()
            if reopen:
                step["reopen_reason"] = reopen
                step.pop("completed_at", None)
            steps.append(step)
        if completed_step:
            step = next((s for s in steps if s["id"] == completed_step), None)
            if step is None:
                raise ValueError("completed_step必须是计划中的步骤ID。")
            step["status"] = "completed"
        summary_step = completed_step or state.get("current_step_id")
        for step in steps:
            if summary and step["id"] == summary_step:
                step["summary"] = summary.strip()
            if step["status"] == "completed":
                step.setdefault("completed_at", now_iso())
            else:
                step.pop("completed_at", None)
        additions = [line.strip() for line in constraints.splitlines() if line.strip()]
        retained = list(dict.fromkeys([*state.get("constraints", []), *additions]))
        if sum(map(len, retained)) > 20000:
            raise ValueError("任务约束过长，请先整理为精简要求。")
        if completed_step or any(s["status"] in {"running", "completed"}
                                 and s["status"] != old.get(s["id"], {}).get("status") for s in steps):
            if task.status != "running" or state.get("human_paused") or state.get("approved_version") != state.get("version") or not state.get("approved_version"):
                raise ValueError("只有正在执行的已批准计划可以勾选步骤。")
        changes = {}
        if "goal" in proposal:
            goal = str(proposal["goal"]).strip()
            if not goal or len(goal) > 8000:
                raise ValueError("修改后的目标需在1–8000字之间。")
            if goal != task.root_goal:
                changes["goal"] = goal
        if "completion_conditions" in proposal:
            conditions = lines(proposal["completion_conditions"], 50)
            if not conditions:
                raise ValueError("验收条件不能为空。")
            if conditions != task.completion_conditions:
                changes["completion_conditions"] = conditions
        if "budget" in proposal:
            budget = proposal["budget"]
            if not isinstance(budget, dict) or set(budget) - set(BUDGET_LIMITS):
                raise ValueError("计划包含无效预算字段。")
            values = {k: integer(v, *BUDGET_LIMITS[k]) for k, v in budget.items()}
            if any(getattr(task.budget, k) != v for k, v in values.items()):
                changes["budget"] = values
        removed = lines(proposal.get("remove_constraints", []), 50)
        if any(value not in state.get("constraints", []) for value in removed):
            raise ValueError("只能申请解除当前已有的用户约束。")
        if removed:
            changes["constraints"] = [c for c in retained if c not in removed]
        authorized = bool(state.get("version") and state.get("approved_version") == state.get("version"))
        routine, review_reason = False, str(proposal.get("change_reason") or "提交任务计划")[:2000]
        previous_snapshot = deepcopy(state)
        if authorized:
            if task.pending_approvals() or any(r.get("status") in {"started", "unknown"} for r in state.get("journal", [])):
                raise ValueError("请先处理待审批操作或未知结果，再修订计划。")
            if (steps == state.get("steps", []) and retained == state.get("constraints", [])
                    and scope_roots == state.get("scope_roots", []) and risk_lines == state.get("risk_lines", [])
                    and not cleanup_paths and not changes):
                if notifications != state.get("notifications",{}):
                    state["notifications"]=notifications
                    self.owner.storage.save_task(task)
                if summary:
                    task.last_confirmed_progress = summary.strip()
                    self.owner.storage.save_task(task)
                return "计划内容未变，继续当前步骤。"
            def within(root, parent):
                paths = ntpath if ntpath.splitdrive(root)[0] or ntpath.splitdrive(parent)[0] or "\\" in root + parent else posixpath
                try:
                    return paths.isabs(root) and paths.isabs(parent) and paths.commonpath(
                        [paths.normcase(paths.normpath(root)), paths.normcase(paths.normpath(parent))]) == paths.normcase(paths.normpath(parent))
                except ValueError:
                    return False
            approved_roots = authorized_roots(state)
            expanded = any(not any(within(root, parent) for parent in approved_roots) for root in scope_roots)
            routine = not changes and not cleanup_paths and not expanded
        if authorized and "authorized_scope_roots" not in state:
            state["authorized_scope_roots"] = list(state.get("scope_roots", []))
        # Full revisions, including old summaries/evidence, are stored outside
        # the injected prompt. Routine edits do not expand execution authority.
        revision_id = f"plan_{int(state.get('version', 0))+1}"
        revision_path = self.owner.storage.task_memory_dir(task.umo, task.task_id) / "plans" / f"{revision_id}.json"
        self.owner.storage._write_json(revision_path, json.loads(self.owner._redact_known_secrets(json.dumps({
            "before": previous_snapshot.get("steps", []), "after": steps, "changes": changes,
            "reason": review_reason, "routine": routine, "created_at": now_iso()}, ensure_ascii=False))))
        for approval in task.approvals:
            if not routine and approval.get("status") in {"pending", "approved"} and approval.get("approval_type") in {"task_plan", "tool_call", "tool_batch"}:
                approval["status"] = "expired"
        previous_authority = state.get("authorization_version", state.get("approved_version", 0))
        state.update(version=int(state.get("version", 0)) + 1, approved_version=0,
                     notifications=notifications,
                     steps=steps, constraints=retained, scope_roots=scope_roots,
                     risk_lines=risk_lines, phase="awaiting_plan")
        state.setdefault("plan_changes", []).append({"version": state["version"], "reason": review_reason,
            "routine": routine, "record_path": str(revision_path.relative_to(self.owner.storage.root)), "time": now_iso()})
        state["plan_changes"] = state["plan_changes"][-8:]
        if routine:
            state.update(approved_version=state["version"], authorization_version=previous_authority, phase="executing")
            from .verifier import AgentVerifier
            AgentVerifier.link_step_evidence(task)
            current = next((s for s in steps if s["id"] == state.get("current_step_id") and s["status"] != "completed"), None)
            current = current or next((s for s in steps if s["status"] != "completed"), None)
            state["current_step_id"] = current["id"] if current else ""
            if summary:
                task.last_confirmed_progress = summary.strip()
            task.next_step = next((s["instruction"] for s in steps if s["status"] != "completed"), "核对全部成果并结束归档")
            task.add_log("plan_revised", f"v{state['version']}: {review_reason}")
            self.owner.storage.save_task(task)
            if callable(getattr(event, "set_extra", None)):
                event.set_extra("agent_lab_plan_version", state["version"])
            return f"计划 v{state['version']} 已调整并记录：{review_reason}。继续当前任务，原权限和累计预算保留。"
        state["approved_cleanup_paths"] = []
        approval = ApprovalRequest(operation=f"批准任务计划 v{state['version']}", reason=task.root_goal,
            message=approval_message,
            impact="\n".join(f"{i+1}. {s['title']}: {s['instruction']}" for i, s in enumerate(steps)),
            approval_type="task_plan")
        from .models import AgentSpec
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent"))
        approval.impact += "\n画布：" + ("不应用" if state.get("workflow") == "none" else (spec.name or spec.agent_id))
        if scope_roots:
            approval.impact += "\n预计操作范围：" + "、".join(scope_roots)
        if risk_lines:
            approval.impact += "\n风险警告线：" + "、".join(risk_lines)
        if cleanup_paths:
            approval.impact += "\n同时申请清理这些明确文件（不含递归删除）：\n" + "\n".join(cleanup_paths)
        if authorized:
            approval.impact += "\n调整原因：" + review_reason
        if changes:
            approval.impact += "\n需要确认的变化：" + json.dumps(changes, ensure_ascii=False)
        row = approval.to_dict()
        row["plan_version"] = state["version"]
        row["cleanup_paths"] = cleanup_paths
        row["changes"] = changes
        task.approvals.append(row)
        task.status = "paused"
        task.next_step = f"/al approve {approval.approval_id}"
        task.set_wait(wait_reason="need_plan_approval", message="等待管理员审阅计划", source="task_control", resume_command=task.next_step)
        task.add_log("plan_submitted", f"version={state['version']}")
        self.owner.storage.save_task(task)
        return f"计划 v{state['version']} 已保存，等待批准。审批ID {approval.approval_id}；不要在日常再复述完整计划。"

    async def propose(self, event, task_id: str):
        """Draft using the source bot's already configured model, without tools."""
        task = self.load(event.unified_msg_origin, task_id)
        if control(task).get("version"):
            return "已有计划，未覆盖。"
        provider_id = await self.owner.context.get_current_chat_provider_id(task.umo)
        cfg=(self.owner._context_config(task.umo) or {}).get("provider_settings",{})
        persona=await source_persona(self.owner.context,task.umo,cfg)
        request={"prompt":json.dumps({"goal": task.root_goal, "brief": task.task_brief,
                               "completion_conditions": task.completion_conditions,
                               "projects": [{"id": p["project_id"], "title": p["title"], "category": p["category"]}
                                            for p in self.owner.projects.index()["projects"] if p.get("source_umo") == task.umo],
                               "clarifications": control(task).get("questions", [])[-4:]}, ensure_ascii=False),
            "system_prompt":persona_prompt(persona)+"\n为当前Bot的任务制定具体计划，不执行操作。按实际工作划分阶段，不凑固定数量。返回JSON对象：steps数组(id/title/instruction，可用相同stage归组)、message（你的角色向管理员请示的完整短正文，需说清范围和验收，可回复批准或拒绝）、notifications（可选paused/error/budget/stalled四种场景下预先自拟的提示，不猜具体错误）、scope_roots、risk_lines、cleanup_paths、project_id、project_title、category。仅关键目标缺失时返回question/options/recommendation。不编造路径，最后包含成果核对。"}
        response = await asyncio.wait_for(self.owner.context.llm_generate(chat_provider_id=provider_id,**request),60)
        latest = self.load(task.umo, task_id)
        record_request(latest,request_size(request,request),getattr(response,"usage",None),phase="planning")
        if getattr(response,"usage",None):
            latest.add_token_usage(response.usage)
            consume=getattr(self.owner,"_consume_token_budget",None)
            if consume:consume(latest,response.usage)
        self.owner.storage.save_task(latest)
        if control(latest).get("version") or control(latest).get("human_paused"):
            return "任务状态已变化，未覆盖计划。"
        text = str(response.completion_text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        proposal = json.loads(text)
        if isinstance(proposal, dict):
            if proposal.get("question"):
                row = self.ask(event, str(proposal["question"]), proposal.get("options", []), str(proposal.get("recommendation") or ""))
                return json.dumps(row, ensure_ascii=False) + f"\n/al answer {row['id']} <回答>"
            project_id = control(latest).get("project_id")
            project = self.owner.projects.project(project_id) if project_id else None
            if not project or project.get("title") == "未分类":
                selected = str(proposal.get("project_id") or "")
                valid = {p["project_id"] for p in self.owner.projects.index()["projects"] if p.get("source_umo") == task.umo}
                if selected in valid:
                    self.owner.projects.attach(latest, selected)
                elif proposal.get("project_title"):
                    self.owner.projects.attach(latest, title=str(proposal["project_title"])[:100], category=str(proposal.get("category") or "项目"))
                self.owner.storage.save_task(latest)
            text = json.dumps({key: proposal[key] for key in ("steps", "scope_roots", "risk_lines", "cleanup_paths", "message", "notifications") if key in proposal}, ensure_ascii=False)
        return await self.submit_plan(event, text)

    def approval(self, task, row: dict, approved: bool):
        state = control(task)
        row["decision"] = "approved" if approved else "rejected"
        if row.get("approval_type") == "task_plan":
            if row.get("plan_version") != state.get("version"):
                raise ValueError("计划已变更，请审阅最新版本。")
            if approved:
                state.update(approved_version=state["version"], authorization_version=state["version"],
                             authorized_scope_roots=list(state.get("scope_roots", [])),
                             approved_cleanup_paths=row.get("cleanup_paths", []), phase="executing")
                changes = row.get("changes", {})
                if "goal" in changes:
                    task.root_goal = changes["goal"]
                if "completion_conditions" in changes:
                    task.completion_conditions = changes["completion_conditions"]
                if "constraints" in changes:
                    state["constraints"] = changes["constraints"]
                for key, value in changes.get("budget", {}).items():
                    setattr(task.budget, key, value)
        if not approved:
            state["human_paused"] = True

    def checkpoint(self, event, step_id: str, summary: str, evidence_json: str = "[]", completed: bool = False) -> str:
        task = self.load(event.unified_msg_origin)
        state = control(task)
        if task.status != "running" or not state.get("approved_version") or state.get("approved_version") != state.get("version"):
            raise ValueError("任务未在执行已批准计划。")
        step = next((row for row in state["steps"] if row["id"] == step_id), None)
        if not step or step_id != state.get("current_step_id"):
            raise ValueError("只能更新当前未完成步骤，请先读取任务状态。")
        if not summary.strip() or len(summary) > 4000:
            raise ValueError("检查点说明需在1–4000字之间，请保留可继续执行的关键事实。")
        evidence = json.loads(evidence_json or "[]")
        if not isinstance(evidence, list):
            raise ValueError("证据必须是工具记录 ID 的 JSON 数组。")
        from .verifier import AgentVerifier
        valid = {row["id"] for row in AgentVerifier.journal_records(task) if row.get("id")
                 and row.get("step_id") == step_id}
        if any(not isinstance(item, str) or item not in valid for item in evidence):
            raise ValueError("手动提供的记录不属于当前步骤的成功工具记录。")
        step.update(status="completed" if completed else "running", summary=summary[:4000],
                    evidence=sorted(valid))
        if completed:
            step["completed_at"] = now_iso()
            stage = step.get("stage")
            if stage and all(s.get("status") == "completed" for s in state["steps"] if s.get("stage") == stage):
                state.setdefault("continuity", {}).setdefault("lanes", {}).setdefault("", {})["pending_reason"] = "stage_completed"
                stage_steps=[s for s in state["steps"] if s.get("stage")==stage]
                state["checkpoint_handoff"]={"stage":stage,"version":state.get("version"),"input_revision":state.get("input_revision",0),
                                             "summary":"\n".join(s.get("summary","") for s in stage_steps),"evidence":[e for s in stage_steps for e in s.get("evidence",[])]}
        task.last_confirmed_progress = summary[:4000]
        task.next_step = next((s["instruction"] for s in state["steps"] if s["status"] != "completed"), "核对全部成果并结束归档")
        task.add_log("plan_checkpoint", f"{step_id}: {summary[:1000]}")
        self.owner.storage.save_task(task)
        return "步骤检查点已保存。"

    def steer(self, umo: str, message: str, task_id: str = "") -> str:
        task = self.load(umo, task_id)
        state = control(task)
        if not message.strip() or len(message) > 4000:
            raise ValueError("引导内容应为 1–4000 字符。")
        constraints = list(dict.fromkeys([*state.get("constraints", []), message.strip()]))
        if sum(map(len, constraints)) > 20000:
            raise ValueError("累计约束过长，请精简后再添加。")
        state["constraints"] = constraints
        state.setdefault("guidance", []).append({"message": message.strip(), "time": now_iso()})
        state["input_revision"] = int(state.get("input_revision", 0)) + 1
        self.owner.storage.save_task(task)
        return "引导已存入本任务，将在下一次决策前读取；不会另起任务。"

    def ready(self, task) -> bool:
        state = control(task)
        return bool(task.task_id not in self.owner.projects.cleaning
                    and not self.owner.storage.ended_path(task.task_id).exists()
                    and state and state.get("automatic") and not state.get("human_paused")
                    and task.status == "running" and not task.pending_approvals()
                    and state.get("approved_version") == state.get("version") and state.get("version")
                    and not any(row.get("status") in {"started", "unknown"} for row in state.get("journal", [])))

    def schedule(self, event):
        if self.closing:
            return
        task = self.owner.storage.load_active_task(event.unified_msg_origin)
        if task:
            self.refresh_execution_settings(task)
        if not task or not self.ready(task) or task.umo in self.running:
            return
        self.running[task.umo] = asyncio.create_task(self._drive(event, task.task_id))

    async def _drive(self, event, task_id: str):
        try:
            # Let the entry command/tool response finish before background work.
            await asyncio.sleep(0)
            while not self.closing:
                task = self.load(event.unified_msg_origin, task_id)
                if not self.ready(task):
                    break
                if f"{task.umo}:{task.task_id}" in self.owner._running_ticks:
                    await asyncio.sleep(0.2)
                    continue
                self.owner._require_task_access(event)
                result = await self.owner._tick(event, "continuation")
                latest = self.owner.storage.load_active_task(event.unified_msg_origin)
                if latest is None or not self.ready(latest):
                    await self.owner.task_messages.state(event, task_id, str(result))
                    break
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            task = self.owner.storage.load_active_task(event.unified_msg_origin)
            if task and task.task_id == task_id:
                task.status = "paused"
                task.next_step = "执行已中断。请核对本任务检查点和未知工具结果后，用 /al resume 恢复。"
                task.add_log("continuation_stopped", str(exc))
                self.owner.storage.save_task(task)
                await self.owner.task_messages.state(event, task_id)
        finally:
            self.running.pop(event.unified_msg_origin, None)

    async def stop(self):
        self.closing = True
        for operation in list(self.running.values()):
            operation.cancel()
        await asyncio.gather(*list(self.running.values()), return_exceptions=True)
        self.recover()

    def recover(self):
        for task in self.owner.storage.list_tasks():
            state = control(task)
            if not state:
                continue
            for row in state.get("journal", []):
                if row.get("status") == "started":
                    row["status"] = "unknown"
            if task.status == "running":
                task.status = "paused"
                state["human_paused"] = True
                task.next_step = "服务已重载。核对检查点及未知工具结果后，用 /al resume 恢复。"
            self.owner.storage.save_task(task)

    def ask(self, event, question: str, options: list, recommendation: str = ""):
        task = self.load(event.unified_msg_origin)
        state = control(task)
        if not question.strip() or len(question) > 1200 or not isinstance(options, list) or not 2 <= len(options) <= 4:
            raise ValueError("反问需要明确问题和2–4个选项。")
        if any(q.get("status") == "pending" for q in state.get("questions", [])):
            raise ValueError("已有待回答问题，请等待管理员回答。")
        row = {"id": "question_" + hashlib.sha256((question + now_iso()).encode()).hexdigest()[:12],
               "question": question.strip(), "options": [str(option)[:300] for option in options],
               "recommendation": recommendation[:600], "status": "pending", "created_at": now_iso()}
        state.setdefault("questions", []).append(row)
        task.status = "paused"
        task.set_wait(wait_reason="need_answer", message=question, source="task_question",
                      resume_command=f"/al answer {row['id']} <选项或自由回答>")
        self.owner.storage.save_task(task)
        return row

    def answer(self, event, question_id: str, answer: str):
        task = self.load(event.unified_msg_origin)
        row = next((q for q in control(task).get("questions", []) if q["id"] == question_id), None)
        if not row or row.get("status") != "pending": raise ValueError("问题已经回答或不存在。")
        if not answer.strip() or len(answer) > 4000: raise ValueError("回答需要1–4000字符。")
        message = f"管理员对“{row['question']}”的回答：{answer}"
        state = control(task)
        constraints = list(dict.fromkeys([*state.get("constraints", []), message]))
        if sum(map(len, constraints)) > 20000:
            raise ValueError("约束记录过长，请先整理任务要求再回答。")
        row.update(status="answered", answer=answer.strip(), answered_at=now_iso(), answered_by=event.get_sender_id())
        state["constraints"] = constraints
        state.setdefault("guidance", []).append({"message": message, "time": now_iso()})
        state["input_revision"] = int(state.get("input_revision", 0)) + 1
        task.clear_wait()
        if not control(task).get("human_paused") and not task.pending_approvals():
            task.status = "running" if control(task).get("approved_version") else "paused"
        self.owner.storage.save_task(task)
        self.schedule(event)
        return "回答已记录，继续条件满足时将自动接续。"

    @staticmethod
    def fingerprint(task) -> str:
        state = control(task)
        evidence = sorted({row.get("fingerprint", "") for row in state.get("journal", [])
                            if row.get("status") == "completed" and row.get("name") not in {
                                "report", "agent_lab_progress", "astrbot_file_read_tool", "astrbot_grep_tool", "astrbot_list_directory"}})
        visited = sorted({str(row.get("node_id", "")) for row in task.workflow_events if row.get("status") == "completed"})
        payload = [evidence, visited, [(s["id"], s["status"]) for s in state.get("steps", [])]]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
