from __future__ import annotations

from typing import Any

from .models import AgentSpec, TaskState


def _lines_or_none(items: list[str]) -> str:
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    if not cleaned:
        return "- none"
    return "\n".join(f"- {item}" for item in cleaned)


def _workflow_text(spec: AgentSpec) -> str:
    nodes = [item for item in spec.workflow_nodes if isinstance(item, dict)]
    edges = [item for item in spec.workflow_edges if isinstance(item, dict)]
    if not nodes:
        return "- 未配置自定义工作流。按读取状态、计划、执行、写回、归档的默认顺序推进。"

    node_lines = []
    for node in nodes[:24]:
        node_id = str(node.get("id") or "").strip() or "node"
        title = str(node.get("title") or node_id).strip()
        kind = str(node.get("kind") or "state").strip()
        stage = str(node.get("stage") or "").strip() or "plan"
        action = str(node.get("action") or "").strip() or "manual"
        instruction = str(
            node.get("instruction") or node.get("description") or ""
        ).strip()
        extras = []
        ref_type = str(node.get("ref_type") or "").strip()
        ref_id = str(
            node.get("ref_id")
            or node.get("api_id")
            or node.get("plugin_name")
            or node.get("tool_name")
            or node.get("skill_name")
            or ""
        ).strip()
        condition = str(node.get("condition") or "").strip()
        parallel_group = str(node.get("parallel_group") or "").strip()
        prompt = str(node.get("prompt") or "").strip()
        if ref_type or ref_id:
            extras.append(f"ref={ref_type or 'module'}:{ref_id or '-'}")
        if condition:
            extras.append(f"condition={condition[:180]}")
        if parallel_group:
            extras.append(f"parallel_group={parallel_group}")
        if prompt:
            extras.append(f"node_prompt={prompt[:260]}")
        suffix = f": {instruction}" if instruction else ""
        if extras:
            suffix += "；" + "；".join(extras)
        node_lines.append(f"- {node_id} [{stage}/{kind}/{action}] {title}{suffix}")

    edge_lines = []
    for edge in edges[:32]:
        start = str(edge.get("from") or "").strip()
        end = str(edge.get("to") or "").strip()
        if start and end:
            edge_lines.append(f"- {start} -> {end}")

    return (
        "节点：\n"
        + "\n".join(node_lines)
        + "\n连线：\n"
        + ("\n".join(edge_lines) if edge_lines else "- 未配置连线")
    )


def _workflow_runtime_text(spec: AgentSpec, task: TaskState) -> str:
    nodes = {
        str(node.get("id") or ""): node
        for node in spec.workflow_nodes
        if isinstance(node, dict)
    }
    outgoing: dict[str, list[str]] = {}
    for edge in spec.workflow_edges:
        if not isinstance(edge, dict):
            continue
        start = str(edge.get("from") or "").strip()
        end = str(edge.get("to") or "").strip()
        if start and end:
            outgoing.setdefault(start, []).append(end)
    current_id = str(task.workflow_current_node_id or "").strip()
    if not current_id and task.workflow_path:
        current_id = str(task.workflow_path[-1] or "").strip()
    current = nodes.get(current_id, {})
    candidates = outgoing.get(current_id, [])
    recent = []
    for item in (task.workflow_events or [])[-8:]:
        if not isinstance(item, dict):
            continue
        recent.append(
            f"- {item.get('time')}: {item.get('node_id')} "
            f"[{item.get('status') or '-'}] -> {item.get('next_node_id') or '-'}; "
            f"{item.get('outcome') or item.get('note') or '-'}"
        )
    return "\n".join(
        [
            f"- current_node：{current_id or '-'}",
            f"- current_title：{current.get('title') or '-'}",
            f"- current_stage/action/kind：{current.get('stage') or '-'} / {current.get('action') or '-'} / {current.get('kind') or '-'}",
            f"- next_candidates：{', '.join(candidates) or '-'}",
            f"- path：{' -> '.join(task.workflow_path or []) or '-'}",
            "- recent_events：",
            "\n".join(recent) if recent else "- none",
        ]
    )


def _agent_runtime_text(task: TaskState) -> str:
    data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
    runtime = data.get("agent_runtime") if isinstance(data.get("agent_runtime"), dict) else {}
    if not runtime:
        return "- agent_runtime 尚未初始化；先调用 agent_lab_read_runtime。"
    plan = runtime.get("plan") if isinstance(runtime.get("plan"), dict) else {}
    steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    capabilities = runtime.get("capabilities") if isinstance(runtime.get("capabilities"), list) else []
    resume = runtime.get("resume") if isinstance(runtime.get("resume"), dict) else {}
    last_verdict = runtime.get("last_verdict") if isinstance(runtime.get("last_verdict"), dict) else {}
    active_steps = [
        step
        for step in steps
        if isinstance(step, dict) and step.get("status") in {"running", "pending", "blocked"}
    ][:8]
    step_lines = [
        f"- {step.get('node_id') or '-'} [{step.get('status') or '-'}] "
        f"capability={step.get('capability') or '-'}; success={step.get('success_condition') or '-'}"
        for step in active_steps
    ]
    capability_lines = [
        f"- {item.get('name') or '-'}: {item.get('capability') or '-'} "
        f"risk={item.get('risk') or '-'} approval={'yes' if item.get('requires_approval') else 'no'}"
        for item in capabilities[:12]
        if isinstance(item, dict)
    ]
    return "\n".join(
        [
            f"- instance：{(runtime.get('agent_instance') or {}).get('instance_id') or '-'}",
            f"- plan：{plan.get('plan_id') or '-'} current={plan.get('current_node_id') or task.workflow_current_node_id or '-'}",
            f"- resume：{resume.get('resume_command') or '/agentlab tick'} waiting={resume.get('waiting') or '-'}",
            f"- last_verdict：{last_verdict.get('status') or '-'} passed={last_verdict.get('passed')} {last_verdict.get('reason') or ''}",
            "- active_plan_steps：",
            "\n".join(step_lines) if step_lines else "- none",
            "- capabilities：",
            "\n".join(capability_lines) if capability_lines else "- none",
        ]
    )


def _confirm_mode_label(entry: Any) -> str:
    if not getattr(entry, "require_confirmation", True):
        return "不确认（命中即进）"
    mode = str(getattr(entry, "confirmation_mode", "fixed") or "fixed")
    if mode == "off":
        return "不确认（命中即进）"
    if mode == "prompt":
        return "按下方提示词动态生成确认语后再征求同意"
    return "发送下方固定确认话术后再征求同意"


def _entry_policy_text(spec: AgentSpec) -> str:
    entry = spec.entry_policy
    return "\n".join(
        [
            "- 开启暗号/命令：",
            _lines_or_none(entry.trigger_phrases),
            "- 任务关键词：",
            _lines_or_none(entry.trigger_keywords),
            f"- 进入前确认方式：{_confirm_mode_label(entry)}",
            f"- 确认话术/提示：{entry.confirmation_text or '-'}",
            "- 默认完成条件：",
            _lines_or_none(entry.default_completion_conditions),
            "- 结束暗号/命令：",
            _lines_or_none(entry.exit_phrases),
        ]
    )


def _isolation_policy_text(spec: AgentSpec) -> str:
    policy = spec.isolation_policy
    return "\n".join(
        [
            f"- 隔离模式：{policy.mode}",
            f"- 工具模式：{policy.tool_mode}",
            f"- 退出时恢复会话快照：{'是' if policy.restore_on_exit else '否'}",
            f"- 保护 Agent Lab 自身：{'是' if policy.protect_self else '否'}",
            f"- 隐藏已禁用插件工具：{'是' if policy.hide_disabled_plugin_tools else '否'}",
            f"- 说明：{policy.notes or '-'}",
        ]
    )


ENTRY_SUMMARY_SYSTEM = """你是 AstrBot Agent Lab 的入口摘要器。
你的任务是把用户和 bot 在进入 Agent Mode 前商量出的计划压缩成可执行的 task_brief。
只保留任务目标、开启方式、完成条件、约束、已确认计划、用户授权、风险、重要上下文和接续语气。
不要保留闲聊、情绪碎片、与任务无关的长期记忆。
如果进入前用户已经设定暗号、关键词、手动命令或需要二次确认，必须写入 task_brief。"""

EXIT_SUMMARY_SYSTEM = """你是 AstrBot Agent Lab 的出口归档器。
你的任务是把一次 Agent Mode 任务压缩成归档摘要和可回流长期记忆候选。
归档要能让后续任务无缝接续；长期记忆候选只包含未来稳定有用的事实。
输出必须覆盖：完成情况、关键改动、验证结果、遗留风险、下次续写入口、可暴露给普通模式读取的任务记忆标签。"""


def build_agent_mode_policy(spec: AgentSpec) -> str:
    return f"""
[Agent Lab 模式协议]
当前 AstrBot 会话支持 Agent Mode。你仍然保持当前 bot 原本的身份、语气与关系，但当任务适合进入 Agent Mode 时，应按用户选择的触发模式行动。

[当前 AgentSpec]
- name：{spec.name}
- application_scope：{spec.application_scope}
- entry_channel：{spec.entry_channel}
- trigger_mode：{spec.trigger_mode}
- memory_mode：{spec.memory_policy.mode}
- approval_mode：{spec.approval_policy.mode}
- heartbeat_mode：{spec.heartbeat_policy.mode}
- entry_policy：
{_entry_policy_text(spec)}
- isolation_policy：
{_isolation_policy_text(spec)}
- preapproved_scopes：
{_lines_or_none(spec.approval_policy.preapproved_scopes)}
- require_approval：
{_lines_or_none(spec.approval_policy.require_approval)}
- enabled_tools：
{_lines_or_none(spec.enabled_tools)}
- enabled_skills：
{_lines_or_none(spec.enabled_skills)}

[当前工作流]
{_workflow_text(spec)}

[自主触发决策]
1. 先判断用户请求是否需要可持续任务状态。普通问答、闲聊、一次性解释不进入 Agent Mode。
2. application_scope=global：把当前 AgentSpec 作为默认任务工作台，所有适合长任务的请求都按 trigger_mode 判断是否进入。
3. application_scope=entry：只有入口命中时才进入。entry_channel=command 表示命令或用户明确说“进入任务模式”；entry_channel=natural 表示自然语言也可触发；entry_channel=webui 表示主要从 WebUI 创建任务。
4. manual：只有命令、WebUI 或用户明确说进入 Agent Mode/任务模式时才进入。
5. confirm：判断适合进入时，先用一句话说明原因并请求确认。
6. smart：低风险资料整理、计划、分析可自动进入；涉及文件写入、命令执行、部署、删除、读取密钥、关闭插件等先确认。
7. always：除简单问答和闲聊外优先进入 Agent Mode；危险动作仍需审批。
8. 如果已有 active task，不要重复进入，先读取 task_state 再继续。
9. 画布中的 entry/entry_gate/context_bridge 节点共同定义“如何开启”：暗号、关键词、命令、WebUI、是否二次确认，都以 AgentSpec 和工作流节点为准。
10. 画布中的 archive/exit_summary 节点定义“如何结束”：只有满足完成条件、用户取消、任务阻塞需归档或用户明确要求退出时，才调用 agent_lab_finish。

可用工具：
- agent_lab_enter_mode：进入 Agent Mode，创建任务状态。
- agent_lab_read_state：读取当前任务状态。
- agent_lab_read_runtime：读取当前 Agent Runtime，包括能力目录、结构化计划、verifier 结论和恢复入口。
- agent_lab_update_state：写回当前进度、观察、下一步和阻塞点。
- agent_lab_advance_workflow：记录当前工作流节点结果并推进到下一节点；多分支、并行分支、审批/校验节点必须用它留下节点轨迹。
- agent_lab_read_task_memory：读取已归档任务记忆，普通模式也可以按标签/关键词查询。
- agent_lab_recommend_task_patterns：查询已完成任务沉淀的 task pattern / 历史 plan 模板；只能作为计划提示，不能当作事实证据。
- agent_lab_update_workflow：检查、增删改工作流节点和连线；当用户要求调整入口、审批、API、插件/工具/skill 模块、并行分支、节点提示词或记忆环节时使用。
- agent_lab_run_parallel_workflow：运行画布中的 parallel_branch 后续工作包；API 节点走已注册 API，提示词/插件/工具节点走受限子工作包，结果写回 task_state。
- agent_lab_tick：推进当前任务一轮。
- agent_lab_request_approval：危险操作前请求审批。
- agent_lab_set_heartbeat：为长任务开启或关闭心跳。
- agent_lab_finish：任务完成时归档并退出。

核心原则：
1. Agent Mode 不是失忆。进入时要把刚才商量的计划压缩成 task_brief。
2. 任务连续性以 task_state 为唯一真实来源，不凭旧上下文脑补进度。
3. 每轮执行必须先用 agent_lab_read_state 和 agent_lab_read_runtime 复盘现状、能力目录、计划游标和最新验证结论，再做有限步骤，再用 agent_lab_update_state 写回状态。
4. 删除、重置、部署、改全局配置、读取密钥等危险动作前，先主动说明影响并请求用户同意。
5. 用户取消时立即停止，不得自行恢复。
6. 心跳只是唤醒机制，不是记忆本身；只有长任务、等待型任务或用户要求时才建议启用。
7. 审批是行为规范：在计划或工具调用前自己判断，不要等工具报错后才补请示。
8. 工作流是任务推进路线图。每轮按节点指令选择下一步，但不得绕过 task_state、审批和工具白名单。
9. 记忆必须分层：普通聊天记忆只在入口压缩后进入任务；任务过程中的时间线、关键改动和成果写入 task_state/任务记忆；出口摘要只回流稳定事实。
10. 调整工作流不是换 bot 身份；只是在当前 AstrBot 身份下改变任务模式的入口、模块、校验、记忆和出口规则。修改后先检查工作流，再继续任务。
11. 工作流模块必须尊重隔离和白名单：插件模块不能复活全局停用插件，API 模块只能调用已注册 API，工具模块必须在 AgentSpec 允许范围内。
12. 遇到 action=parallel_branch 的节点，优先使用 agent_lab_run_parallel_workflow 执行可并行后续工作包；子工作包不能直接结束任务，必须由主 Agent 合并、校验、写回和归档。
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
- application_scope: {spec.application_scope}
- entry_channel: {spec.entry_channel}
- trigger_mode: {spec.trigger_mode}
- memory_mode: {spec.memory_policy.mode}
- approval_mode: {spec.approval_policy.mode}
- heartbeat_mode: {spec.heartbeat_policy.mode}
- entry_policy:
{_entry_policy_text(spec)}
- isolation_policy:
{_isolation_policy_text(spec)}
- preapproved_scopes:
{_lines_or_none(spec.approval_policy.preapproved_scopes)}
- require_approval:
{_lines_or_none(spec.approval_policy.require_approval)}
- enabled_tools:
{_lines_or_none(spec.enabled_tools)}
- enabled_skills:
{_lines_or_none(spec.enabled_skills)}

[Workflow]
{_workflow_text(spec)}

[Workflow Runtime Cursor]
{_workflow_runtime_text(spec, task)}

[Structured Agent Runtime]
{_agent_runtime_text(task)}

[Heartbeat Contract]
如果这是心跳唤醒，第一步必须读取并相信 task_state 和 agent_runtime；本轮只推进有限工作单元；结束时必须用 agent_lab_update_state 总结当前现状、下一步、是否阻塞。

[Agent Runtime Contract]
agent_runtime 是任务的硬控制层：capabilities 决定当前 Agent 被授予什么能力，TaskPlan 决定当前目标实例的结构化步骤，observations 是证据层，verdicts 是验证层，resume 是重启/等待用户后继续的入口，pattern_recommendations 是从已完成任务中抽取的计划模板提示。不要绕过能力目录调用未授权工具；不要在 verifier 未通过或完成条件缺证据时调用 agent_lab_finish。每轮若看不到最新 runtime，请先调用 agent_lab_read_runtime。

[Approval Contract]
普通读取、创建任务记录、小范围明确文件写入、运行测试无需审批。删除、批量覆盖、git reset/clean、部署/重启服务、密钥读取、数据库破坏性变更、全局插件/系统配置修改必须先请求审批。若某项在 preapproved_scopes 中，仍需先确认它确实属于用户已授权范围；若超出范围，必须调用 agent_lab_request_approval。

[Task Memory Contract]
任务过程中的时间线以 task_state.progress_log 和 state_snapshots 为准。每轮写回时必须说明：几点/哪一轮做了什么、关键改动点、验证结果、下一步。退出时必须用 agent_lab_finish 生成出口摘要和 memory_candidates；候选记忆只保存稳定事实、项目约定、后续续写提示，不保存密钥、一次性 token 或临时噪声。完成任务还会沉淀 task pattern，后续任务可以参考其 TaskPlan 和能力需求，但 pattern 只是 planning hint，不能替代当前任务证据或 verifier。

[Workflow Cursor Contract]
每轮至少在完成一个工作流节点或选择分支时调用 agent_lab_advance_workflow，记录 node_id、outcome、next_node_id 和选择原因。多分支节点不能靠猜测自动前进；必须说明选择哪条连线。工作流游标是审计轨迹，不替代 task_state。

[Parallel Workflow Contract]
如果当前节点 action=parallel_branch，且后续节点是互不依赖的 API、提示词、插件或工具工作包，可以调用 agent_lab_run_parallel_workflow。该工具会受限并发运行后续工作包，并把 parallel_runs、workflow_events、last_observation 写回 task_state。并行结果只是证据层，仍需主 Agent 在汇总节点做冲突合并、验收和下一步决策。

{modules_prompt}
""".strip()


def build_tick_prompt(task: TaskState, reason: str = "") -> str:
    return f"""
你正在 Agent Mode 中推进任务。
触发原因：{reason or "manual tick"}

必须按顺序执行：
1. 复盘当前 task_state。
2. 读取 agent_runtime，确认能力目录、TaskPlan、last_verdict 和 resume 入口。
3. 判断是否存在未审批的危险操作；若有，先等待审批。
4. 只推进一个有限工作单元。
5. 调用 agent_lab_update_state 写回本轮完成了什么、关键改动点、观察到什么、下一步是什么、是否需要心跳。
6. 调用 agent_lab_advance_workflow 记录本轮完成或选择的工作流节点；遇到多分支时明确 next_node_id。
7. 若任务完成，调用 agent_lab_finish，并在 final_summary/memory_candidates 中沉淀任务成果、改动摘要、遗留风险和下次续写提示；若需要审批，调用 agent_lab_request_approval。

当前任务 ID：{task.task_id}
根目标：{task.root_goal}
下一步：{task.next_step or "请根据 task_state 判断"}
当前工作流节点：{task.workflow_current_node_id or "-"}
""".strip()
