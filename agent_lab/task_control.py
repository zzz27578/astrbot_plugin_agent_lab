"""Task continuity layered on the existing TaskState and workflow modules.

The bot owns planning. The plugin owns durable checkpoints, approval and waking
the next bounded round. A canvas is optional guidance, never a second bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from typing import Any

from .models import ApprovalRequest, now_iso
from .execution_settings import BUDGET_LIMITS, integer, lines, normalize
from .continuity import working_context
from .task_permissions import authorized_roots, execution_guidance


def control(task) -> dict:
    return task.workflow_data.setdefault("task_control", {})


def prompt(task) -> str:
    state = control(task)
    if not state:
        return ""
    evidence = []
    # Reserve the prompt budget for recent results instead of silently clipping
    # every result at 1000 characters. Older/longer evidence remains readable.
    remaining = 24000
    for row in reversed(state.get("journal", [])[-8:]):
        result = str(row.get("result", ""))
        shown = result[:max(0, remaining)]
        remaining -= len(shown)
        evidence.append({"id": row["id"], "name": row.get("name"), "arguments": row.get("arguments", {}),
                         "status": row.get("status"), "step_id": row.get("step_id"), "result": shown,
                         "approval_id": row.get("approval_id", ""),
                         "result_chars": row.get("result_chars", len(result)),
                         "result_truncated": bool(row.get("result_truncated") or len(shown) < len(result)),
                         "read_more": "agent_lab_read_tool_evidence"})
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
        "recent_tool_evidence": list(reversed(evidence)),
        "permission_policy": execution_guidance(state),
        "guard_refusals": state.get("guard_refusals", {}),
        "instruction": "按当前有效计划执行，阶段按实际任务划分，不必凑固定数量。优先使用已有工具结果，不重复执行已经批准且完成的操作；结果不全时调用 agent_lab_read_tool_evidence 读取，不要重新申请或执行。普通拆分、重排、补测试可用 agent_lab_submit_plan 修订并说明原因，涉及目标、验收条件、预算或解除用户约束才重新审批。返工已完成步骤需提供 reopen_reason。危险操作先汇总成一批，用 agent_lab_request_approval 的 operations_json 提交确切工具与参数，中文说明影响和恢复方式。不要先调用危险工具撞审批，也不要改写已拒绝的同一动作后重试。阶段内及时用 agent_lab_checkpoint 保存实际成果、决定原因、文件位置、验证和遗留事项；完成阶段后自动交接。无画布时不调用流程推进。只有缺少关键答案时反问。",
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
        task.next_step = "Bot 调用 agent_lab_submit_plan 提交具体步骤，管理员批准后自动推进。"
        task.set_wait(wait_reason="need_plan", message=task.next_step, source="task_control")

    async def submit_plan(self, event, steps_json: str, constraints: str = "") -> str:
        task = self.load(event.unified_msg_origin)
        state = control(task)
        if not state or "owner_id" not in state:
            project_id = state.get("project_id", "")
            self.initialize(task, event, "selected")
            state = control(task)
            state["project_id"] = project_id
        raw = json.loads(steps_json)
        proposal = raw if isinstance(raw, dict) else {}
        if set(proposal) - {"steps", "scope_roots", "risk_lines", "cleanup_paths", "change_reason",
                            "goal", "completion_conditions", "budget", "remove_constraints"}:
            raise ValueError("计划不能修改权限或运行配置；请通过项目设置由管理员调整。")
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
            stage = str(item.get("stage") or previous.get("stage") or identifier).strip()
            if not stage or len(stage) > 120 or len(reopen) > 2000:
                raise ValueError("阶段名称需在120字以内，返工说明需在2000字以内。")
            changed = bool(previous and (title != previous["title"] or instruction != previous["instruction"]))
            if previous.get("status") == "completed" and changed and not reopen:
                raise ValueError("已完成步骤不能改写；请另加修正步骤。")
            step = {**deepcopy(previous), "id": identifier, "title": title, "instruction": instruction, "stage": stage,
                    "status": "pending" if reopen or changed else previous.get("status", "pending"),
                    "evidence": [] if reopen or changed else previous.get("evidence", []),
                    "revision": int(previous.get("revision", 0)) + int(bool(reopen or changed))}
            if reopen:
                step["reopen_reason"] = reopen
                step.pop("completed_at", None)
            steps.append(step)
        if any(step["status"] == "completed" and key not in ids for key, step in old.items()):
            raise ValueError("已完成步骤必须保留。")
        additions = [line.strip() for line in constraints.splitlines() if line.strip()]
        retained = list(dict.fromkeys([*state.get("constraints", []), *additions]))
        if sum(map(len, retained)) > 20000:
            raise ValueError("任务约束过长，请先整理为精简要求。")
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
                return "计划内容未变，继续当前步骤。"
            if not changes and not cleanup_paths and scope_roots == state.get("scope_roots", []):
                routine, review_reason = await self._review_revision(event, task, steps, retained, review_reason)
                current = self.load(task.umo, task.task_id)
                if control(current) != previous_snapshot or current.status != task.status:
                    raise ValueError("审阅期间任务记录已变化，请读取最新计划后重试。")
                task, state = current, control(current)
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
            if approval.get("status") in {"pending", "approved"} and approval.get("approval_type") in {"task_plan", "tool_call", "tool_batch"}:
                approval["status"] = "expired"
        previous_authority = state.get("authorization_version", state.get("approved_version", 0))
        state.update(version=int(state.get("version", 0)) + 1, approved_version=0,
                     steps=steps, constraints=retained, scope_roots=scope_roots,
                     risk_lines=risk_lines, phase="awaiting_plan")
        state.setdefault("plan_changes", []).append({"version": state["version"], "reason": review_reason,
            "routine": routine, "record_path": str(revision_path.relative_to(self.owner.storage.root)), "time": now_iso()})
        state["plan_changes"] = state["plan_changes"][-8:]
        if routine:
            state.update(approved_version=state["version"], authorization_version=previous_authority, phase="executing")
            state.setdefault("continuity", {}).setdefault("lanes", {}).setdefault("", {})["pending_reason"] = "plan_revised"
            task.next_step = next((s["instruction"] for s in steps if s["status"] != "completed"), "核对全部成果并结束归档")
            task.add_log("plan_revised", f"v{state['version']}: {review_reason}")
            self.owner.storage.save_task(task)
            return f"计划 v{state['version']} 已调整并记录：{review_reason}。继续当前任务，原权限和累计预算保留。"
        state["approved_cleanup_paths"] = []
        approval = ApprovalRequest(operation=f"批准任务计划 v{state['version']}", reason=task.root_goal,
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
        return f"计划 v{state['version']} 已保存，执行前须管理员批准。\n{approval.impact}\n{task.next_step}"

    async def _review_revision(self, event, task, steps, constraints, reason):
        """Compare actual plans with the immutable request using a tool-free review."""
        if task.budget.max_total_tokens and task.budget.tokens_used >= task.budget.max_total_tokens:
            raise ValueError("任务总预算已用尽，请先由管理员调整额度。")
        provider_id = await self.owner.context.get_current_chat_provider_id(task.umo)
        response = await self.owner.context.llm_generate(chat_provider_id=provider_id,
            prompt=json.dumps({"goal": task.root_goal, "acceptance": task.completion_conditions,
                "constraints": constraints, "old_steps": control(task).get("steps", []), "new_steps": steps,
                "stated_reason": reason}, ensure_ascii=False),
            system_prompt="审阅任务清单修改，不执行操作，也不批准权限。比较实际前后差异与用户目标、验收和约束，不能只相信修改者声称普通调整。仅拆分、重排、补充排查/测试、保留原目标的返工是普通调整；改变交付目标、取消必要验收、引入费用或放宽用户要求须确认。不确定也须确认。返回JSON：routine布尔值、reason中文简述实际差异。")
        # Persist model accounting without replacing concurrently updated state.
        latest = self.load(task.umo, task.task_id)
        usage = getattr(response, "usage", None)
        if usage:
            latest.add_token_usage(usage)
            consume = getattr(self.owner, "_consume_token_budget", None)
            exhausted = consume(latest, usage) if consume else ""
            if latest.budget.max_total_tokens and latest.budget.tokens_used >= latest.budget.max_total_tokens:
                exhausted = f"任务 Token 总预算已用尽：{latest.budget.tokens_used}/{latest.budget.max_total_tokens}"
                pause = getattr(self.owner, "_pause_task_for_budget", None)
                if pause:
                    pause(latest, exhausted)
            self.owner.storage.save_task(latest)
            if exhausted:
                raise ValueError(exhausted)
        text = str(response.completion_text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            result = json.loads(text)
            if not isinstance(result, dict) or not isinstance(result.get("routine"), bool) or not str(result.get("reason") or "").strip():
                raise ValueError("invalid review")
            return result["routine"], self.owner._redact_known_secrets(str(result["reason"]))[:1000]
        except (ValueError, TypeError):
            return False, "无法自动确认此次修改是否保留全部交付要求，请管理员核对。"

    async def propose(self, event, task_id: str):
        """Draft using the source bot's already configured model, without tools."""
        task = self.load(event.unified_msg_origin, task_id)
        if control(task).get("version"):
            return "已有计划，未覆盖。"
        provider_id = await self.owner.context.get_current_chat_provider_id(task.umo)
        response = await self.owner.context.llm_generate(chat_provider_id=provider_id,
            prompt=json.dumps({"goal": task.root_goal, "brief": task.task_brief,
                               "completion_conditions": task.completion_conditions,
                               "projects": [{"id": p["project_id"], "title": p["title"], "category": p["category"]}
                                            for p in self.owner.projects.index()["projects"] if p.get("source_umo") == task.umo],
                               "clarifications": control(task).get("questions", [])[-4:]}, ensure_ascii=False),
            system_prompt="为当前Bot的任务制定具体计划，不执行操作。按实际工作划分阶段，不凑固定数量。返回JSON对象：steps数组(id/title/instruction，可用相同stage名称将几个步骤归入一个阶段)、scope_roots（已知的预计绝对路径）、risk_lines（额外风险线，需审批用 审批:工具名或路径通配，其余作说明）、cleanup_paths（预计清理的具体文件绝对路径，可省略）、project_id、project_title、category。仅关键目标缺失到无法规划时返回question、options、recommendation。不编造路径，最后包含成果核对，用中文。")
        latest = self.load(task.umo, task_id)
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
            text = json.dumps({key: proposal[key] for key in ("steps", "scope_roots", "risk_lines", "cleanup_paths") if key in proposal}, ensure_ascii=False)
        return await self.submit_plan(event, text)

    def approval(self, task, row: dict, approved: bool):
        state = control(task)
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

    def checkpoint(self, event, step_id: str, summary: str, evidence_json: str, completed: bool) -> str:
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
        authority = state.get("authorization_version", state["approved_version"])
        valid = {row["id"] for row in state.get("journal", []) if row.get("status") == "completed"
                 and row.get("step_id") == step_id
                 and row.get("step_revision", 0) == step.get("revision", 0)
                 and row.get("authorization_version", row.get("plan_version")) == authority}
        if any(item not in valid for item in evidence) or (completed and (not evidence or not summary.strip())):
            raise ValueError("完成步骤需提供本步骤成功工具记录 ID 及结果说明，不能仅复述目标。")
        step.update(status="completed" if completed else "running", summary=summary[:4000],
                    evidence=list(dict.fromkeys([*step.get("evidence", []), *evidence])))
        if completed:
            step["completed_at"] = now_iso()
            stage = step.get("stage") or step_id
            if all(s.get("status") == "completed" for s in state["steps"] if (s.get("stage") or s["id"]) == stage):
                state.setdefault("continuity", {}).setdefault("lanes", {}).setdefault("", {})["pending_reason"] = "stage_completed"
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
