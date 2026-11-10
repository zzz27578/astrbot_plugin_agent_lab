"""Task continuity layered on the existing TaskState and workflow modules.

The bot owns planning. The plugin owns durable checkpoints, approval and waking
the next bounded round. A canvas is optional guidance, never a second bot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

from .models import ApprovalRequest, now_iso


def control(task) -> dict:
    return task.workflow_data.setdefault("task_control", {})


def prompt(task) -> str:
    state = control(task)
    if not state:
        return ""
    return "\n[本次任务的持久计划，优先于旧对话摘要]\n" + json.dumps({
        "task_id": task.task_id, "goal": task.root_goal,
        "version": state.get("version", 0), "approved_version": state.get("approved_version", 0),
        "steps": state.get("steps", []), "constraints": state.get("constraints", []),
        "current_step_id": state.get("current_step_id", ""),
        "workflow": state.get("workflow", "none"), "next_action": task.next_step,
        "guidance": state.get("guidance", [])[-8:],
        "recent_tool_evidence": [{"id": r["id"], "name": r.get("name"), "status": r.get("status"),
                                  "step_id": r.get("step_id"), "result": str(r.get("result", ""))[:1000]}
                                 for r in state.get("journal", [])[-8:]],
        "instruction": "按批准计划执行；工具后使用 agent_lab_checkpoint 记录步骤和证据。分析/汇总步骤可用 agent_lab_record_report 保存真实报告，不得编造测试结果。没有应用画布时不推进画布节点。计划全部完成再调用 agent_lab_finish。修改计划使用 agent_lab_submit_plan，审批由管理员完成。",
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

    def submit_plan(self, event, steps_json: str, constraints: str = "") -> str:
        task = self.load(event.unified_msg_origin)
        state = control(task)
        if not state:
            self.initialize(task, event, "selected")
            state = control(task)
        raw = json.loads(steps_json)
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
            if not title or identifier in ids or len(instruction) > 4000:
                raise ValueError("步骤需有名称、唯一 ID，说明不能超过4000字符。")
            ids.add(identifier)
            previous = old.get(identifier, {})
            if previous.get("status") == "completed" and (title != previous["title"] or instruction != previous["instruction"]):
                raise ValueError("已完成步骤不能改写；请另加修正步骤。")
            steps.append({"id": identifier, "title": title, "instruction": instruction,
                          "status": previous.get("status", "pending"), "evidence": previous.get("evidence", [])})
        if any(step["status"] == "completed" and key not in ids for key, step in old.items()):
            raise ValueError("已完成步骤必须保留。")
        additions = [line.strip() for line in constraints.splitlines() if line.strip()]
        retained = list(dict.fromkeys([*state.get("constraints", []), *additions]))
        if sum(map(len, retained)) > 20000:
            raise ValueError("任务约束过长，请先整理为精简要求。")
        for approval in task.approvals:
            if approval.get("status") in {"pending", "approved"} and approval.get("approval_type") in {"task_plan", "tool_call"}:
                approval["status"] = "expired"
        state.update(version=int(state.get("version", 0)) + 1, approved_version=0,
                     steps=steps, constraints=retained, phase="awaiting_plan", human_paused=False)
        approval = ApprovalRequest(operation=f"批准任务计划 v{state['version']}", reason=task.root_goal,
            impact="\n".join(f"{i+1}. {s['title']}: {s['instruction']}" for i, s in enumerate(steps)),
            approval_type="task_plan")
        from .models import AgentSpec
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent"))
        approval.impact += "\n画布：" + ("不应用" if state.get("workflow") == "none" else (spec.name or spec.agent_id))
        scopes = [value for value in spec.approval_policy.preapproved_scopes if str(value).startswith("tool:")]
        if scopes:
            approval.impact += "\n本计划同时申请以下工具范围免重复审批（覆盖该工具参数，请确认边界）：" + ", ".join(scopes)
        row = approval.to_dict()
        row["plan_version"] = state["version"]
        row["tool_scopes"] = scopes
        task.approvals.append(row)
        task.status = "paused"
        task.next_step = f"/al approve {approval.approval_id}"
        task.set_wait(wait_reason="need_plan_approval", message="等待管理员审阅计划", source="task_control", resume_command=task.next_step)
        task.add_log("plan_submitted", f"version={state['version']}")
        self.owner.storage.save_task(task)
        return f"计划 v{state['version']} 已保存，执行前须管理员批准。\n{approval.impact}\n{task.next_step}"

    async def propose(self, event, task_id: str):
        """Draft using the source bot's already configured model, without tools."""
        task = self.load(event.unified_msg_origin, task_id)
        if control(task).get("version"):
            return "已有计划，未覆盖。"
        provider_id = await self.owner.context.get_current_chat_provider_id(task.umo)
        response = await self.owner.context.llm_generate(chat_provider_id=provider_id,
            prompt=json.dumps({"goal": task.root_goal, "brief": task.task_brief,
                               "completion_conditions": task.completion_conditions}, ensure_ascii=False),
            system_prompt="为当前Bot的任务制定具体计划，不执行操作。只返回JSON数组，2–8步，每步id/title/instruction。最后包含成果核对；不要编造项目结构。用用户语言。")
        latest = self.load(task.umo, task_id)
        if control(latest).get("version") or control(latest).get("human_paused"):
            return "任务状态已变化，未覆盖计划。"
        text = str(response.completion_text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return self.submit_plan(event, text)

    def approval(self, task, row: dict, approved: bool):
        state = control(task)
        if row.get("approval_type") == "task_plan":
            if row.get("plan_version") != state.get("version"):
                raise ValueError("计划已变更，请审阅最新版本。")
            if approved:
                state.update(approved_version=state["version"], approved_tool_scopes=row.get("tool_scopes", []), phase="executing")
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
        evidence = json.loads(evidence_json or "[]")
        if not isinstance(evidence, list):
            raise ValueError("证据必须是工具记录 ID 的 JSON 数组。")
        valid = {row["id"] for row in state.get("journal", []) if row.get("status") == "completed"
                 and row.get("step_id") == step_id and row.get("plan_version") == state["version"]}
        if any(item not in valid for item in evidence) or (completed and (not evidence or not summary.strip())):
            raise ValueError("完成步骤需提供本步骤成功工具记录 ID 及结果说明，不能仅复述目标。")
        step.update(status="completed" if completed else "running", summary=summary[:4000],
                    evidence=list(dict.fromkeys([*step.get("evidence", []), *evidence])))
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
        return bool(state and state.get("automatic") and not state.get("human_paused")
                    and task.status == "running" and not task.pending_approvals()
                    and state.get("approved_version") == state.get("version") and state.get("version")
                    and not any(row.get("status") in {"started", "unknown"} for row in state.get("journal", [])))

    def schedule(self, event):
        if self.closing:
            return
        task = self.owner.storage.load_active_task(event.unified_msg_origin)
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
                    from astrbot.core.message.message_event_result import MessageChain
                    message = str(result)
                    if latest:
                        pending = latest.pending_approvals()
                        message += "\n" + "\n".join(f"{row.operation}\n{row.impact}\n/al approve {row.approval_id}" for row in pending)
                        message += f"\n当前任务：{latest.task_id}\n下一步：{latest.next_step}"
                    self.owner._require_task_access(event)
                    await event.send(MessageChain().message(message[:5000]))
                    break
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            task = self.owner.storage.load_active_task(event.unified_msg_origin)
            if task and task.task_id == task_id:
                task.status = "paused"
                task.add_log("continuation_stopped", str(exc))
                self.owner.storage.save_task(task)
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

    @staticmethod
    def fingerprint(task) -> str:
        state = control(task)
        evidence = sorted({row.get("fingerprint", "") for row in state.get("journal", [])
                           if row.get("status") == "completed" and row.get("name") != "report"})
        visited = sorted({str(row.get("node_id", "")) for row in task.workflow_events if row.get("status") == "completed"})
        payload = [evidence, visited, [(s["id"], s["status"]) for s in state.get("steps", [])]]
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
