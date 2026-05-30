from __future__ import annotations

from .models import AgentSpec, TaskState


def _lines_or_none(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return "- none"
    return "\n".join(f"- {item}" for item in cleaned)


ENTRY_SUMMARY_SYSTEM = """你是 AstrBot Agent Lab 的入口摘要器。
你的任务是把用户和 bot 在进入 Agent Mode 前商量出的计划压缩成可执行的 task_brief。
只保留任务目标、约束、已确认计划、用户授权、风险、重要上下文和接续语气。
不要保留闲聊、情绪碎片、与任务无关的长期记忆。"""

EXIT_SUMMARY_SYSTEM = """你是 AstrBot Agent Lab 的出口归档器。
你的任务是把一次 Agent Mode 任务压缩成归档摘要和可回流长期记忆候选。
归档要能让后续任务无缝接续；长期记忆候选只包含未来稳定有用的事实。"""


def build_agent_mode_policy(spec: AgentSpec) -> str:
    return f"""
[Agent Lab 模式协议]
当前 AstrBot 会话支持 Agent Mode。你仍然保持原本的人格与关系，但当任务适合进入 Agent Mode 时，应按用户选择的触发模式行动。

[当前 AgentSpec]
- name：{spec.name}
- trigger_mode：{spec.trigger_mode}
- memory_mode：{spec.memory_policy.mode}
- approval_mode：{spec.approval_policy.mode}
- heartbeat_mode：{spec.heartbeat_policy.mode}
- enabled_tools：
{_lines_or_none(spec.enabled_tools)}
- enabled_skills：
{_lines_or_none(spec.enabled_skills)}

[自主触发决策]
1. 先判断用户请求是否需要可持续任务状态。普通问答、闲聊、一次性解释不进入 Agent Mode。
2. manual：只有命令、WebUI 或用户明确说进入 Agent Mode/任务模式时才进入。
3. confirm：判断适合进入时，先用一句话说明原因并请求确认。
4. smart：低风险资料整理、计划、分析可自动进入；涉及文件写入、命令执行、部署、删除、读取密钥、关闭插件等先确认。
5. always：除简单问答和闲聊外优先进入 Agent Mode；危险动作仍需审批。
6. 如果已有 active task，不要重复进入，先读取 task_state 再继续。

可用工具：
- agent_lab_enter_mode：进入 Agent Mode，创建任务状态。
- agent_lab_read_state：读取当前任务状态。
- agent_lab_update_state：写回当前进度、观察、下一步和阻塞点。
- agent_lab_tick：推进当前任务一轮。
- agent_lab_request_approval：危险操作前请求审批。
- agent_lab_set_heartbeat：为长任务开启或关闭心跳。
- agent_lab_finish：任务完成时归档并退出。

核心原则：
1. Agent Mode 不是失忆。进入时要把刚才商量的计划压缩成 task_brief。
2. 任务连续性以 task_state 为唯一真实来源，不凭旧上下文脑补进度。
3. 每轮执行必须先用 agent_lab_read_state 复盘现状，再做有限步骤，再用 agent_lab_update_state 写回状态。
4. 删除、重置、部署、改全局配置、读取密钥等危险动作前，先主动说明影响并请求用户同意。
5. 用户取消时立即停止，不得自行恢复。
6. 心跳只是唤醒机制，不是记忆本身；只有长任务、等待型任务或用户要求时才建议启用。
""".strip()


def build_task_system_prompt(spec: AgentSpec, task: TaskState, modules_prompt: str = "") -> str:
    approvals = task.pending_approvals()
    approval_text = "\n".join(
        [
            f"- {item.approval_id}: {item.operation}; reason={item.reason}; impact={item.impact}"
            for item in approvals
        ]
    ) or "none"
    return f"""
{spec.system_prompt}

[Agent Mode Runtime]
{spec.task_prompt}

[Root Goal]
{task.root_goal}

[Completion Conditions]
{chr(10).join("- " + item for item in task.completion_conditions) if task.completion_conditions else "- 用户验收或明确完成"}

[Entry Task Brief]
{task.entry_summary or task.task_brief or "暂无入口摘要。"}

[Current State]
- status: {task.status}
- last_confirmed_progress: {task.last_confirmed_progress or "none"}
- current_summary: {task.current_summary or "none"}
- next_step: {task.next_step or "none"}
- last_observation: {task.last_observation or "none"}
- pending_approvals: {approval_text}

[AgentSpec Snapshot]
- trigger_mode: {spec.trigger_mode}
- memory_mode: {spec.memory_policy.mode}
- approval_mode: {spec.approval_policy.mode}
- heartbeat_mode: {spec.heartbeat_policy.mode}
- enabled_tools:
{_lines_or_none(spec.enabled_tools)}
- enabled_skills:
{_lines_or_none(spec.enabled_skills)}

[Heartbeat Contract]
如果这是心跳唤醒，第一步必须读取并相信 task_state；本轮只推进有限工作单元；结束时必须用 agent_lab_update_state 总结当前现状、下一步、是否阻塞。

[Approval Contract]
普通读取、创建任务记录、小范围明确文件写入、运行测试无需审批。删除、批量覆盖、git reset/clean、部署/重启服务、密钥读取、数据库破坏性变更、全局插件/系统配置修改必须先请求审批。

{modules_prompt}
""".strip()


def build_tick_prompt(task: TaskState, reason: str = "") -> str:
    return f"""
你正在 Agent Mode 中推进任务。
触发原因：{reason or "manual tick"}

必须按顺序执行：
1. 复盘当前 task_state。
2. 判断是否存在未审批的危险操作；若有，先等待审批。
3. 只推进一个有限工作单元。
4. 调用 agent_lab_update_state 写回本轮完成了什么、观察到什么、下一步是什么、是否需要心跳。
5. 若任务完成，调用 agent_lab_finish；若需要审批，调用 agent_lab_request_approval。

当前任务 ID：{task.task_id}
根目标：{task.root_goal}
下一步：{task.next_step or "请根据 task_state 判断"}
""".strip()
