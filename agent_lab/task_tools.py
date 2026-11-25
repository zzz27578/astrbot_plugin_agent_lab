"""The five model-facing controls; main.py only registers thin wrappers.

Use ``await TaskTools(owner).dispatch(event, name, arguments)``. Schemas are
OpenAI-style function definitions. Administrative legacy APIs stay on owner;
they must not be added to an ordinary background task's model tool set.
"""
from __future__ import annotations

import json


def _schema(name, description, required, **properties):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": {
            key: {"type": "string", "description": value} for key, value in properties.items()
        }, "required": required, "additionalProperties": False}}}


TASK_TOOL_SCHEMAS = (
    _schema("task_plan", "提交初始计划；执行中自由拆改、勾选步骤。目标或权限扩大须重新批准。", ["steps_json"],
            steps_json="JSON数组或含steps的对象；执行中可留空复用计划。每步id/title/instruction/status，可选stage/summary。对象可带scope_roots/goal/completion_conditions/remove_constraints/change_reason。",
            constraints="新增约束，每行一项；省略时保留现有要求。", summary="本次进展或步骤完成说明。",
            completed_step="本次勾选完成的步骤ID；也可在steps中设置status。", message="给管理员的审批原话，最多2000字符。"),
    _schema("task_progress", "以当前Bot人设发送简短真实进展。", ["message"], message="进展正文，1–600字符。"),
    _schema("task_ask", "缺少关键决策时向管理员提出一个问题。", ["question", "options_json"],
            question="具体问题。", options_json="2–4个互斥文本选项的JSON数组。", recommendation="推荐选项及理由。"),
    _schema("task_approve", "真正高危或越界操作前请示；管理员批准后按保存参数执行。",
            ["operation", "reason", "impact", "operations_json"], operation="准备执行的操作。", reason="必要性。", impact="影响范围。",
            operations_json="1–20项JSON数组，每项含tool_name和arguments对象。", rollback="恢复方式。", message="给管理员的审批原话，最多2000字符。"),
    _schema("task_finish", "交付成果并归档；后台校验真实执行、改动文件和验证结果。", ["final_summary"],
            final_summary="成果、改动文件、实际验证结果及遗留项。", memory_candidates="可选稳定记忆候选，每行一项。",
            message="给管理员的交付原话，最多2000字符；详细正文超过2000字符时必填。"),
)
CONTROL_TOOL_NAMES = frozenset(schema["function"]["name"] for schema in TASK_TOOL_SCHEMAS)


class TaskTools:
    def __init__(self, owner):
        self.owner = owner

    async def dispatch(self, event, name: str, arguments: dict) -> str:
        """Validate the compact API and delegate to existing owner controls."""
        if name not in CONTROL_TOOL_NAMES:
            raise ValueError("普通任务仅支持task_plan/task_progress/task_ask/task_approve/task_finish。")
        schema = next(s["function"]["parameters"] for s in TASK_TOOL_SCHEMAS if s["function"]["name"] == name)
        if (not isinstance(arguments, dict) or set(arguments) - set(schema["properties"])
                or set(schema["required"]) - set(arguments) or any(not isinstance(v, str) for v in arguments.values())):
            raise ValueError(f"{name}参数不符合定义；所有参数均为字符串。")
        self.owner._require_task_access(event)
        return await getattr(self, name)(event, **arguments)

    async def task_plan(self, event, steps_json: str, constraints: str = "", summary: str = "",
                        completed_step: str = "", message: str = "") -> str:
        result = await self.owner.task_control.submit_plan(
            event, steps_json, constraints, summary=summary, completed_step=completed_step, message=message)
        task = self.owner.task_control.load(event.unified_msg_origin)
        if task.pending_approvals():
            await self.owner.task_messages.state(event, task.task_id)
        return result

    async def task_progress(self, event, message: str) -> str:
        return await self.owner.agent_lab_progress(event, message=message)

    async def task_ask(self, event, question: str, options_json: str, recommendation: str = "") -> str:
        options = json.loads(options_json)
        if (not isinstance(options, list) or not 2 <= len(options) <= 4
                or any(not isinstance(option, str) or not option.strip() or len(option) > 300 for option in options)
                or len(set(options)) != len(options)):
            raise ValueError("请提供2–4个不同的非空文本选项。")
        return await self.owner.agent_lab_ask_question(event, question, options_json, recommendation)

    async def task_approve(self, event, operation: str, reason: str, impact: str, operations_json: str,
                           rollback: str = "", message: str = "") -> str:
        operations = json.loads(operations_json)
        if (not operation.strip() or not reason.strip() or not impact.strip()
                or not isinstance(operations, list) or not 1 <= len(operations) <= 20
                or any(not isinstance(row, dict) or not isinstance(row.get("tool_name"), str)
                       or not row["tool_name"].strip() or not isinstance(row.get("arguments"), dict)
                       or row["tool_name"] in CONTROL_TOOL_NAMES for row in operations)):
            raise ValueError("审批需要操作、原因、影响及1–20项确切tool_name/arguments，不能执行任务控制工具。")
        return await self.owner.agent_lab_request_approval(
            event, operation=operation, reason=reason, impact=impact, operations_json=operations_json,
            rollback=rollback, message=message)

    async def task_finish(self, event, final_summary: str, memory_candidates: str = "", message: str = "") -> str:
        from .verifier import AgentVerifier
        task = self.owner.task_control.load(event.unified_msg_origin)
        AgentVerifier.link_step_evidence(task)
        self.owner.storage.save_task(task)
        return await self.owner.agent_lab_finish(
            event, final_summary=final_summary, memory_candidates=memory_candidates, message=message)
