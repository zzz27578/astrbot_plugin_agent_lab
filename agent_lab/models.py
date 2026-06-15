from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _clean_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        items = re.split(r"[\n,，、;；]+", value)
    elif isinstance(value, list):
        items = value
    else:
        items = []
    return [str(item).strip() for item in items if str(item).strip()]


@dataclass
class HeartbeatPolicy:
    allowed: bool = True
    mode: str = "manual"  # off | manual | auto
    enabled: bool = False
    cron_expression: str = "*/5 * * * *"
    job_id: str = ""
    max_repeated_failures: int = 3
    last_pulse_at: str = ""
    next_pulse_hint: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "HeartbeatPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base


@dataclass
class TaskLease:
    owner: str = ""
    token: str = ""
    acquired_at: str = ""
    expires_at: str = ""
    reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TaskLease":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base


@dataclass
class WatchdogState:
    last_tick_at: str = ""
    last_tick_reason: str = ""
    last_progress_at: str = ""
    last_progress_hash: str = ""
    consecutive_failures: int = 0
    last_error: str = ""
    last_decision: str = ""
    paused_reason: str = ""
    needs_user: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WatchdogState":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        try:
            base.consecutive_failures = int(base.consecutive_failures or 0)
        except Exception:
            base.consecutive_failures = 0
        base.needs_user = bool(base.needs_user)
        return base


@dataclass
class WaitState:
    active: bool = False
    wait_reason: str = ""
    message: str = ""
    source: str = ""
    resume_command: str = "/agentlab tick"
    resume_node: str = ""
    required_input: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WaitState":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        base.active = bool(base.active)
        if isinstance(base.required_input, str):
            base.required_input = [base.required_input] if base.required_input else []
        elif not isinstance(base.required_input, list):
            base.required_input = []
        base.required_input = [str(item).strip() for item in base.required_input if str(item).strip()]
        return base


@dataclass
class TaskBudget:
    max_nodes_per_tick: int = 6
    max_tools_per_tick: int = 12
    max_seconds_per_tick: int = 240
    max_tokens_per_tick: int = 12000
    max_total_ticks: int = 120
    max_total_tool_calls: int = 240
    max_total_tokens: int = 240000
    ticks_used: int = 0
    nodes_used: int = 0
    tool_calls_used: int = 0
    tokens_used: int = 0
    tick_started_at: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TaskBudget":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        for key in (
            "max_nodes_per_tick",
            "max_tools_per_tick",
            "max_seconds_per_tick",
            "max_tokens_per_tick",
            "max_total_ticks",
            "max_total_tool_calls",
            "max_total_tokens",
            "ticks_used",
            "nodes_used",
            "tool_calls_used",
            "tokens_used",
        ):
            try:
                setattr(base, key, int(getattr(base, key) or 0))
            except Exception:
                setattr(base, key, int(getattr(cls(), key)))
        return base


@dataclass
class ApprovalPolicy:
    mode: str = "work"  # observe | work | high_risk_review | delegated
    preapproved_scopes: list[str] = field(default_factory=list)
    require_approval: list[str] = field(
        default_factory=lambda: [
            "file_delete",
            "bulk_overwrite",
            "git_reset",
            "git_clean",
            "deployment",
            "service_restart",
            "secret_read",
            "system_config",
            "database_destructive",
        ]
    )
    note: str = (
        "审批优先由 Agent 在危险动作前主动提出；工具层只作为灾难性操作兜底。"
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ApprovalPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base


@dataclass
class MemoryPolicy:
    mode: str = "task_filtered"  # inherit | task_filtered | strict
    entry_summary_turns: int = 24
    keep_identity: bool = True
    allow_long_memory: bool = True
    exit_memory_candidates: bool = True
    compression_enabled: bool = True
    compression_strategy: str = "smart_extract"  # recent_turns | smart_extract | full_preserve
    compression_max_tokens: int = 6000
    preserve_keywords: list[str] = field(default_factory=list)
    notes: str = "任务模式不是失忆，而是把普通上下文压缩成可执行 task_brief。"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MemoryPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        if base.compression_strategy not in {"recent_turns", "smart_extract", "full_preserve"}:
            base.compression_strategy = "smart_extract"
        try:
            base.compression_max_tokens = max(500, min(int(base.compression_max_tokens or 6000), 64000))
        except Exception:
            base.compression_max_tokens = 6000
        if isinstance(base.preserve_keywords, str):
            base.preserve_keywords = [base.preserve_keywords] if base.preserve_keywords else []
        elif not isinstance(base.preserve_keywords, list):
            base.preserve_keywords = []
        base.preserve_keywords = [str(item).strip() for item in base.preserve_keywords if str(item).strip()]
        return base


@dataclass
class MemoryFolder:
    folder_id: str = field(default_factory=lambda: new_id("mf"))
    name: str = "默认记忆夹"
    agent_id: str = ""
    description: str = ""
    expose_to_normal: bool = False
    detail_level: str = "summary"  # summary | full
    retention_days: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MemoryFolder":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        base.folder_id = str(base.folder_id or "").strip() or new_id("mf")
        base.name = str(base.name or "默认记忆夹").strip()[:80] or "默认记忆夹"
        base.agent_id = str(base.agent_id or "").strip()[:120]
        base.description = str(base.description or "").strip()[:500]
        base.expose_to_normal = bool(base.expose_to_normal)
        if base.detail_level not in {"summary", "full"}:
            base.detail_level = "summary"
        try:
            base.retention_days = max(0, min(int(base.retention_days or 0), 3650))
        except Exception:
            base.retention_days = 0
        return base


@dataclass
class SubAgentSpec:
    """一条子Agent「泳道」：自带模型/API、角色、工具范围、领地与并发上限。

    内嵌在 AgentSpec.sub_agents（方案级），领地(member_node_ids) 只在该方案的
    workflow_nodes 范围内有意义。复用 save_agent 持久化，无需新存储文件。
    """

    sub_agent_id: str = field(default_factory=lambda: new_id("sa"))
    name: str = ""
    color: str = "#5b8def"          # 领地框 + 节点上色
    role_prompt: str = ""           # 角色/职责提示词，拼进该泳道 worker 的 system_prompt
    provider_id: str = ""           # 本泳道独立模型/API；空=继承方案=继承当前会话
    enabled_tools: list[str] = field(default_factory=list)  # 工具范围(子集，空=继承方案)
    max_concurrency: int = 2        # 本泳道并发上限(per-lane semaphore)
    rate_per_minute: int = 0        # 0=不限；>0 本泳道每分钟调用上限
    member_node_ids: list[str] = field(default_factory=list)  # 领地：归属节点 id（缓存，node.owner 为权威）
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SubAgentSpec":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        base.sub_agent_id = str(base.sub_agent_id or "").strip() or new_id("sa")
        base.name = str(base.name or "").strip()[:80]
        color = str(base.color or "").strip()
        base.color = color if re.match(r"^#[0-9a-fA-F]{6}$", color) else "#5b8def"
        base.role_prompt = str(base.role_prompt or "").strip()[:4000]
        base.provider_id = str(base.provider_id or "").strip()[:120]
        base.enabled_tools = list(dict.fromkeys(_clean_string_list(base.enabled_tools)))
        try:
            base.max_concurrency = max(1, min(int(base.max_concurrency or 2), 6))
        except Exception:
            base.max_concurrency = 2
        try:
            base.rate_per_minute = max(0, min(int(base.rate_per_minute or 0), 600))
        except Exception:
            base.rate_per_minute = 0
        base.member_node_ids = list(dict.fromkeys(_clean_string_list(base.member_node_ids)))
        base.notes = str(base.notes or "").strip()[:500]
        return base


def default_workflow_nodes() -> list[dict[str, Any]]:
    return [
        {
            "id": "entry",
            "title": "消息监听入口",
            "kind": "trigger",
            "stage": "entry",
            "action": "listen_message",
            "instruction": "统一承接命令、关键词、自然语言、拍一拍、notice、WebUI、插件事件和 webhook 触发。",
            "output_variable": "event.message",
            "x": 70,
            "y": 240,
        },
        {
            "id": "global_control",
            "title": "全局控制",
            "kind": "guard",
            "stage": "guard",
            "action": "global_control",
            "instruction": "统一应用隔离、工具范围、汇报频率、预算、暂停策略和错误累积阈值。",
            "x": 390,
            "y": 240,
        },
        {
            "id": "memory_recall",
            "title": "任务记忆读取",
            "kind": "retrieval",
            "stage": "plan",
            "action": "retrieve_memory",
            "instruction": "按标签、记忆夹或 source_task_id 读取与当前方案相关的任务记忆。",
            "x": 710,
            "y": 80,
        },
        {
            "id": "plan",
            "title": "计划确认",
            "kind": "state",
            "stage": "plan",
            "action": "plan",
            "instruction": "把根目标拆成可验证步骤，明确完成条件、风险等级、工具范围和本轮有限工作单元。",
            "x": 710,
            "y": 320,
        },
        {
            "id": "risk_router",
            "title": "风险分流",
            "kind": "branch",
            "stage": "plan",
            "action": "route_condition",
            "instruction": "按低风险、外部系统、高风险或需要人工判断分流到执行、API、审批或人工接管。",
            "x": 1040,
            "y": 320,
        },
        {
            "id": "parallel_branch",
            "title": "并行分支",
            "kind": "branch",
            "stage": "plan",
            "action": "parallel_branch",
            "instruction": "把资料检索、代码阅读、测试准备等互不依赖的小任务拆成并行工作包。",
            "x": 1040,
            "y": 80,
        },
        {
            "id": "parallel_research",
            "title": "并行检索包",
            "kind": "subflow",
            "stage": "execute",
            "action": "manual",
            "instruction": "只读检索资料、接口或代码，输出证据摘要、风险和建议下一步。",
            "prompt": "你是并行只读检索工作包。只收集证据和结论，不做写入动作；输出：发现、证据来源、风险、建议下一步。",
            "parallel_group": "default",
            "x": 1360,
            "y": 0,
        },
        {
            "id": "parallel_verify",
            "title": "并行验证包",
            "kind": "subflow",
            "stage": "execute",
            "action": "manual",
            "instruction": "独立检查完成条件、测试证据、边界情况和可能遗漏。",
            "prompt": "你是并行验证工作包。只围绕完成条件检查证据强度；输出：已验证、未验证、阻塞、需要主 Agent 决策的点。",
            "parallel_group": "default",
            "x": 1360,
            "y": 580,
        },
        {
            "id": "execute",
            "title": "工具执行",
            "kind": "tool",
            "stage": "execute",
            "action": "run_tools",
            "instruction": "只调用 AgentSpec 允许的工具或已注册自定义 API，并保留关键输出。",
            "x": 1360,
            "y": 180,
        },
        {
            "id": "api_call",
            "title": "API 调用",
            "kind": "api",
            "stage": "execute",
            "action": "call_api",
            "instruction": "使用 agent_lab_call_custom_api 调用已登记 API，凭证由 Agent Lab 注入，不写入任务记忆。",
            "x": 1360,
            "y": 420,
        },
        {
            "id": "plugin_prompt",
            "title": "插件嵌入提示词",
            "kind": "subflow",
            "stage": "execute",
            "action": "plugin_prompt",
            "instruction": "把目标 AstrBot 插件作为中间能力调用提示词，必要时转人工管理员执行。",
            "x": 1680,
            "y": 580,
        },
        {
            "id": "transform",
            "title": "上下文整理",
            "kind": "transform",
            "stage": "execute",
            "action": "transform_context",
            "instruction": "把工具/API/插件输出整理成结构化观察，压缩噪声并保留证据。",
            "x": 1680,
            "y": 300,
        },
        {
            "id": "approval",
            "title": "审批闸门",
            "kind": "guard",
            "stage": "guard",
            "action": "request_approval",
            "instruction": "涉及删除、部署、重启、密钥、破坏性数据库等危险动作前先请求用户审批。",
            "x": 1360,
            "y": 760,
        },
        {
            "id": "human_handoff",
            "title": "人工接管",
            "kind": "human",
            "stage": "guard",
            "action": "handoff",
            "instruction": "遇到登录、验证码、业务判断、未授权范围或连续阻塞时暂停并等待用户输入。",
            "x": 1680,
            "y": 760,
        },
        {
            "id": "validation",
            "title": "结果校验",
            "kind": "validation",
            "stage": "checkpoint",
            "action": "validate_output",
            "instruction": "对照完成条件、测试结果和副作用判断是否完成；失败时说明原因并进入有限重试。",
            "x": 2000,
            "y": 260,
        },
        {
            "id": "retry_loop",
            "title": "重试循环",
            "kind": "loop",
            "stage": "checkpoint",
            "action": "retry",
            "instruction": "只在执行失败或校验不通过时进入；还有次数就绕回执行，用尽后交人工。",
            "max_retries": 3,
            "x": 2000,
            "y": 540,
        },
        {
            "id": "checkpoint",
            "title": "状态快照",
            "kind": "state",
            "stage": "checkpoint",
            "action": "save_state",
            "instruction": "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。",
            "x": 2320,
            "y": 260,
        },
        {
            "id": "task_memory",
            "title": "任务记忆",
            "kind": "memory",
            "stage": "checkpoint",
            "action": "save_memory",
            "instruction": "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆。",
            "x": 2640,
            "y": 160,
        },
        {
            "id": "heartbeat",
            "title": "心跳续跑",
            "kind": "guard",
            "stage": "guard",
            "action": "heartbeat",
            "instruction": "长任务由心跳唤醒，醒来先读 task_state，再推进一小步。",
            "x": 2640,
            "y": 460,
        },
        {
            "id": "memory_archive",
            "title": "方案记忆存档",
            "kind": "memory",
            "stage": "archive",
            "action": "archive_memory_folder",
            "instruction": "把本次任务导出到方案级记忆夹，隔离到当前 agent_id 和 folder_id。",
            "x": 2960,
            "y": 160,
        },
        {
            "id": "skill_evolution",
            "title": "Skill 进化",
            "kind": "guard",
            "stage": "archive",
            "action": "skill_evolution",
            "instruction": "从已接受任务记忆生成 skill_rules 草稿，默认走人工审批。",
            "approval_mode": "review",
            "x": 2960,
            "y": 460,
        },
        {
            "id": "notify",
            "title": "完成通知",
            "kind": "notification",
            "stage": "archive",
            "action": "notify",
            "instruction": "在退出前向用户说明完成情况、验证结果、遗留风险和下次续写入口。",
            "x": 3280,
            "y": 260,
        },
        {
            "id": "archive",
            "title": "结束回流",
            "kind": "memory",
            "stage": "archive",
            "action": "exit_summary",
            "instruction": "输出任务成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。",
            "x": 3600,
            "y": 260,
        },
    ]


def default_workflow_edges() -> list[dict[str, Any]]:
    return [
        {"from": "entry", "to": "global_control", "edge_type": "success"},
        {"from": "global_control", "to": "memory_recall", "edge_type": "success"},
        {"from": "memory_recall", "to": "plan", "edge_type": "success"},
        {"from": "plan", "to": "risk_router", "edge_type": "success"},
        {"from": "plan", "to": "parallel_branch", "edge_type": "uncertain"},
        {"from": "parallel_branch", "to": "parallel_research", "edge_type": "always"},
        {"from": "parallel_branch", "to": "parallel_verify", "edge_type": "always"},
        {"from": "parallel_research", "to": "transform", "edge_type": "success"},
        {"from": "parallel_verify", "to": "transform", "edge_type": "success"},
        {"from": "risk_router", "to": "execute", "edge_type": "success"},
        {"from": "risk_router", "to": "api_call", "edge_type": "uncertain"},
        {"from": "risk_router", "to": "approval", "edge_type": "failed"},
        {"from": "approval", "to": "execute", "edge_type": "approved"},
        {"from": "approval", "to": "human_handoff", "edge_type": "rejected"},
        {"from": "human_handoff", "to": "plan", "edge_type": "success"},
        {"from": "execute", "to": "transform", "edge_type": "success"},
        {"from": "execute", "to": "retry_loop", "edge_type": "error"},
        {"from": "api_call", "to": "transform", "edge_type": "success"},
        {"from": "api_call", "to": "retry_loop", "edge_type": "error"},
        {"from": "plugin_prompt", "to": "transform", "edge_type": "success"},
        {"from": "plugin_prompt", "to": "human_handoff", "edge_type": "failed"},
        {"from": "transform", "to": "validation", "edge_type": "success"},
        {"from": "validation", "to": "checkpoint", "edge_type": "success"},
        {"from": "validation", "to": "retry_loop", "edge_type": "failed"},
        {"from": "retry_loop", "to": "execute", "edge_type": "retry"},
        {"from": "retry_loop", "to": "human_handoff", "edge_type": "failed"},
        {"from": "checkpoint", "to": "task_memory", "edge_type": "success"},
        {"from": "checkpoint", "to": "heartbeat", "edge_type": "uncertain"},
        {"from": "heartbeat", "to": "plan", "edge_type": "success"},
        {"from": "task_memory", "to": "memory_archive", "edge_type": "success"},
        {"from": "memory_archive", "to": "skill_evolution", "edge_type": "success"},
        {"from": "skill_evolution", "to": "notify", "edge_type": "success"},
        {"from": "skill_evolution", "to": "human_handoff", "edge_type": "approved"},
        {"from": "notify", "to": "archive", "edge_type": "success"},
    ]


@dataclass
class EntryPolicy:
    trigger_phrases: list[str] = field(
        default_factory=lambda: [
            "进入任务模式",
            "开启任务模式",
            "进入专业模式",
            "进入 Agent Mode",
            "/agentlab start",
            "/al start",
        ]
    )
    trigger_keywords: list[str] = field(
        default_factory=lambda: [
            "持续推进",
            "长任务",
            "排查",
            "部署",
            "写插件",
            "改代码",
            "整理资料",
        ]
    )
    require_confirmation: bool = True
    confirmation_text: str = (
        "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？"
    )
    confirmation_mode: str = "fixed"  # off | fixed | prompt（require_confirmation=False 时等价 off）
    default_completion_conditions: list[str] = field(
        default_factory=lambda: ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"]
    )
    exit_phrases: list[str] = field(
        default_factory=lambda: [
            "完成任务",
            "结束任务模式",
            "退出任务模式",
            "退出 Agent Mode",
            "/agentlab finish",
            "/agentlab cancel",
        ]
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "EntryPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base


@dataclass
class IsolationPolicy:
    mode: str = "strict"  # off | session | strict
    tool_mode: str = "whitelist"  # full | whitelist | no_external
    restore_on_exit: bool = True
    protect_self: bool = True
    hide_disabled_plugin_tools: bool = True
    notes: str = (
        "严格隔离会在当前会话默认关闭普通插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件；不改 AstrBot 全局插件开关，退出时恢复会话快照。"
    )

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "IsolationPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base


@dataclass
class WorkflowTrigger:
    enabled: bool = True
    types: list[str] = field(default_factory=lambda: ["command"])
    command_names: list[str] = field(default_factory=lambda: ["agentlab", "al"])
    keywords: list[str] = field(default_factory=list)
    regex: list[str] = field(default_factory=list)
    cron: str = ""
    cron_expressions: list[str] = field(default_factory=list)
    plugin_events: list[str] = field(default_factory=list)
    webhook_path: str = ""
    description: str = ""

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkflowTrigger":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        base.enabled = bool(base.enabled)
        valid_types = {
            "command",
            "natural",
            "silent_global",
            "message_monitor",
            "keyword",
            "regex",
            "poke",
            "notice",
            "schedule",
            "plugin_event",
            "webhook",
            "manual_webui",
        }
        if isinstance(base.types, str):
            base.types = [base.types]
        elif not isinstance(base.types, list):
            base.types = []
        base.types = [
            str(item).strip()
            for item in base.types
            if str(item).strip() in valid_types
        ] or ["command"]
        for key in ("command_names", "keywords", "regex", "cron_expressions", "plugin_events"):
            value = getattr(base, key)
            if isinstance(value, str):
                value = [part.strip() for part in value.replace("；", ",").split(",")]
            elif not isinstance(value, list):
                value = []
            setattr(base, key, [str(item).strip() for item in value if str(item).strip()])
        for key in ("command_names", "keywords", "regex", "cron_expressions", "plugin_events"):
            setattr(base, key, _clean_string_list(getattr(base, key)))
        base.cron = str(base.cron or "").strip()[:120]
        if base.cron and base.cron not in base.cron_expressions:
            base.cron_expressions.insert(0, base.cron)
        base.cron_expressions = [item[:120] for item in base.cron_expressions if item.strip()][:12]
        if not base.cron and base.cron_expressions:
            base.cron = base.cron_expressions[0]
        base.webhook_path = str(base.webhook_path or "").strip()[:200]
        base.description = str(base.description or "").strip()[:500]
        return base


@dataclass
class WorkflowScope:
    chat_types: list[str] = field(default_factory=lambda: ["private"])
    platforms: list[str] = field(default_factory=list)
    umo_allowlist: list[str] = field(default_factory=list)
    umo_denylist: list[str] = field(default_factory=list)
    group_allowlist: list[str] = field(default_factory=list)
    group_denylist: list[str] = field(default_factory=list)
    user_allowlist: list[str] = field(default_factory=list)
    user_denylist: list[str] = field(default_factory=list)
    admin_only: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "WorkflowScope":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        valid_chat_types = {"private", "group"}
        for key in (
            "chat_types",
            "platforms",
            "umo_allowlist",
            "umo_denylist",
            "group_allowlist",
            "group_denylist",
            "user_allowlist",
            "user_denylist",
        ):
            value = getattr(base, key)
            if isinstance(value, str):
                value = [part.strip() for part in value.replace("；", ",").split(",")]
            elif not isinstance(value, list):
                value = []
            cleaned = [str(item).strip() for item in value if str(item).strip()]
            if key == "chat_types":
                cleaned = [item for item in cleaned if item in valid_chat_types]
            setattr(base, key, cleaned)
        for key in (
            "chat_types",
            "platforms",
            "umo_allowlist",
            "umo_denylist",
            "group_allowlist",
            "group_denylist",
            "user_allowlist",
            "user_denylist",
        ):
            cleaned = _clean_string_list(getattr(base, key))
            if key == "chat_types":
                cleaned = [item for item in cleaned if item in valid_chat_types]
            setattr(base, key, cleaned)
        if not base.chat_types:
            base.chat_types = ["private"]
        base.admin_only = bool(base.admin_only)
        return base


@dataclass
class AgentSpec:
    agent_id: str = field(default_factory=lambda: new_id("agent"))
    name: str = ""
    # manual | astrbot_runtime | astrbot_persona(legacy) | astrbot_config(legacy)
    identity_label_source: str = "astrbot_runtime"
    description: str = "把 AstrBot 会话切换为可持续执行、可审批、可归档的 Agent 模式。"
    enabled: bool = True
    provider_id: str = ""
    application_scope: str = "entry"  # entry | global
    entry_channel: str = "command"  # command | natural | webui
    trigger_mode: str = "confirm"  # manual | confirm | smart | always
    workflow_trigger: WorkflowTrigger = field(default_factory=WorkflowTrigger)
    workflow_scope: WorkflowScope = field(default_factory=WorkflowScope)
    entry_policy: EntryPolicy = field(default_factory=EntryPolicy)
    isolation_policy: IsolationPolicy = field(default_factory=IsolationPolicy)
    system_prompt: str = (
        "你仍然是当前 AstrBot 里的原本角色，但进入 Agent Mode 后必须以任务推进为中心。"
    )
    task_prompt: str = (
        "你在 Agent Mode 中工作。先读取任务状态，再执行一个有限步骤，随后总结并写回状态。"
    )
    plugin_overrides: dict[str, bool] = field(default_factory=dict)
    enabled_tools: list[str] = field(
        default_factory=lambda: [
            "astrbot_file_read_tool",
            "astrbot_grep_tool",
            "astrbot_file_write_tool",
            "astrbot_file_edit_tool",
            "astrbot_execute_shell",
            "astrbot_execute_python",
            "agent_lab_read_task_memory",
            "agent_lab_call_custom_api",
            "agent_lab_run_parallel_workflow",
        ]
    )
    tool_risk_overrides: dict[str, str] = field(default_factory=dict)
    enabled_skills: list[str] = field(default_factory=list)
    module_ids: list[str] = field(
        default_factory=lambda: [
            "checkpoint_state",
            "approval_guard",
            "heartbeat_protocol",
            "memory_gate",
        ]
    )
    module_settings: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_task_budget: TaskBudget = field(default_factory=TaskBudget)
    workflow_nodes: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "entry",
                "title": "入口识别",
                "kind": "state",
                "stage": "entry",
                "action": "summarize_entry",
                "instruction": "识别暗号、命令、关键词或 WebUI 入口；只在命中 AgentSpec 触发策略时准备进入任务模式。",
                "x": 70,
                "y": 260,
            },
            {
                "id": "entry_gate",
                "title": "开启确认",
                "kind": "human",
                "stage": "entry",
                "action": "confirm_entry",
                "instruction": "需要确认的触发模式必须先向用户说明将隔离插件、压缩上下文、创建 task_state，并等待明确同意。",
                "x": 390,
                "y": 420,
            },
            {
                "id": "context_bridge",
                "title": "上文压缩",
                "kind": "memory",
                "stage": "entry",
                "action": "summarize_entry",
                "instruction": "把普通聊天上文压缩为 task_brief；只保留目标、约束、授权、风险和接续语气，避免把日常记忆直接灌入专业模式。",
                "x": 390,
                "y": 100,
            },
            {
                "id": "isolation_gate",
                "title": "隔离快照",
                "kind": "guard",
                "stage": "entry",
                "action": "restore_isolation",
                "instruction": "进入任务前记录当前会话插件状态，只保留 Agent Lab、保留插件和用户允许的插件；退出时恢复快照。",
                "x": 710,
                "y": 260,
            },
            {
                "id": "memory_recall",
                "title": "任务记忆检索",
                "kind": "retrieval",
                "stage": "plan",
                "action": "retrieve_memory",
                "instruction": "按标签、关键词或 source_task_id 读取候选任务记忆，只带入与当前目标稳定相关的信息。",
                "x": 1040,
                "y": 80,
            },
            {
                "id": "plan",
                "title": "计划确认",
                "kind": "state",
                "stage": "plan",
                "action": "plan",
                "instruction": "把根目标拆成可验证步骤，明确完成条件、风险等级、工具范围和本轮只推进一个有限工作单元。",
                "x": 1040,
                "y": 300,
            },
            {
                "id": "risk_router",
                "title": "风险分流",
                "kind": "branch",
                "stage": "plan",
                "action": "route_condition",
                "instruction": "低风险直接执行；高风险进入审批；需要外部系统时走 API；需要用户判断时交给人工接管。",
                "x": 1360,
                "y": 300,
            },
            {
                "id": "parallel_branch",
                "title": "并行分支",
                "kind": "branch",
                "stage": "plan",
                "action": "parallel_branch",
                "instruction": "把资料检索、代码阅读、测试准备等互不依赖的步骤拆开推进，再统一进入校验。",
                "x": 1360,
                "y": 80,
            },
            {
                "id": "parallel_research",
                "title": "并行检索包",
                "kind": "subflow",
                "stage": "execute",
                "action": "manual",
                "instruction": "把资料检索、接口查阅或代码阅读这类只读子任务拆出去，输出证据摘要和风险。",
                "prompt": "你是并行只读检索工作包。只收集证据和结论，不做写入动作；输出：发现、证据来源、风险、建议下一步。",
                "parallel_group": "default",
                "x": 1680,
                "y": 0,
            },
            {
                "id": "parallel_verify",
                "title": "并行验证包",
                "kind": "subflow",
                "stage": "execute",
                "action": "manual",
                "instruction": "把测试准备、验收条件核对或结果复核拆成独立工作包，再回收到上下文整理。",
                "prompt": "你是并行验证工作包。只围绕完成条件检查证据强度；输出：已验证、未验证、阻塞、需要主 Agent 决策的点。",
                "parallel_group": "default",
                "x": 1680,
                "y": 580,
            },
            {
                "id": "execute",
                "title": "工具执行",
                "kind": "tool",
                "stage": "execute",
                "action": "run_tools",
                "instruction": "只调用 AgentSpec 允许的工具或已注册自定义 API，并保留关键输出。",
                "x": 1680,
                "y": 160,
            },
            {
                "id": "api_call",
                "title": "API 调用",
                "kind": "api",
                "stage": "execute",
                "action": "call_api",
                "instruction": "使用 agent_lab_call_custom_api 调用已登记 API，凭证由 Agent Lab 注入，不写入任务记忆。",
                "x": 1680,
                "y": 420,
            },
            {
                "id": "transform",
                "title": "上下文整理",
                "kind": "transform",
                "stage": "execute",
                "action": "transform_context",
                "instruction": "把工具/API 返回整理成结构化观察，压缩噪声，保留证据、失败原因和下一步所需字段。",
                "x": 2000,
                "y": 260,
            },
            {
                "id": "approval",
                "title": "审批闸门",
                "kind": "guard",
                "stage": "guard",
                "action": "request_approval",
                "instruction": "涉及删除、部署、重启、密钥、破坏性数据库等危险动作前先请求用户审批。",
                "x": 1680,
                "y": 660,
            },
            {
                "id": "human_handoff",
                "title": "人工接管",
                "kind": "human",
                "stage": "guard",
                "action": "handoff",
                "instruction": "遇到登录、验证码、业务判断、未授权范围或连续阻塞时暂停，给出清晰选项等待用户输入。",
                "x": 2000,
                "y": 660,
            },
            {
                "id": "validation",
                "title": "结果校验",
                "kind": "validation",
                "stage": "checkpoint",
                "action": "validate_output",
                "instruction": "对照完成条件、测试结果和副作用判断是否完成；失败时说明原因并进入有限重试。",
                "x": 2320,
                "y": 180,
            },
            {
                "id": "retry_loop",
                "title": "重试循环",
                "kind": "loop",
                "stage": "checkpoint",
                "action": "retry",
                "instruction": "每次重试都写清调整点和观察结果；同一阻塞重复三次后停止并请求用户介入。",
                "x": 2320,
                "y": 460,
            },
            {
                "id": "checkpoint",
                "title": "状态快照",
                "kind": "state",
                "stage": "checkpoint",
                "action": "save_state",
                "instruction": "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。",
                "x": 2640,
                "y": 180,
            },
            {
                "id": "task_memory",
                "title": "任务记忆",
                "kind": "memory",
                "stage": "checkpoint",
                "action": "save_memory",
                "instruction": "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆；任务记忆独立于日常记忆，并以标签暴露给普通模式读取。",
                "x": 2960,
                "y": 120,
            },
            {
                "id": "heartbeat",
                "title": "心跳续跑",
                "kind": "guard",
                "stage": "guard",
                "action": "heartbeat",
                "instruction": "长任务由心跳唤醒，醒来先读 task_state，再推进一小步。",
                "x": 2960,
                "y": 420,
            },
            {
                "id": "notify",
                "title": "完成通知",
                "kind": "notification",
                "stage": "archive",
                "action": "notify",
                "instruction": "在退出前向用户说明完成情况、验证结果、遗留风险和下次续写入口。",
                "x": 3280,
                "y": 180,
            },
            {
                "id": "archive",
                "title": "结束回流",
                "kind": "memory",
                "stage": "archive",
                "action": "exit_summary",
                "instruction": "只有完成、取消或用户要求退出时结束任务；输出任务成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。",
                "x": 3600,
                "y": 180,
            },
        ]
    )
    workflow_edges: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"from": "entry", "to": "entry_gate"},
            {"from": "entry_gate", "to": "context_bridge"},
            {"from": "context_bridge", "to": "isolation_gate"},
            {"from": "isolation_gate", "to": "memory_recall"},
            {"from": "memory_recall", "to": "plan"},
            {"from": "plan", "to": "risk_router"},
            {"from": "plan", "to": "parallel_branch"},
            {"from": "parallel_branch", "to": "parallel_research"},
            {"from": "parallel_branch", "to": "parallel_verify"},
            {"from": "parallel_branch", "to": "execute"},
            {"from": "risk_router", "to": "execute"},
            {"from": "risk_router", "to": "api_call"},
            {"from": "risk_router", "to": "approval"},
            {"from": "approval", "to": "human_handoff"},
            {"from": "approval", "to": "execute"},
            {"from": "human_handoff", "to": "plan"},
            {"from": "execute", "to": "transform"},
            {"from": "api_call", "to": "transform"},
            {"from": "parallel_research", "to": "transform"},
            {"from": "parallel_verify", "to": "transform"},
            {"from": "transform", "to": "validation"},
            {"from": "validation", "to": "checkpoint"},
            {"from": "validation", "to": "retry_loop"},
            {"from": "retry_loop", "to": "execute"},
            {"from": "checkpoint", "to": "task_memory"},
            {"from": "checkpoint", "to": "heartbeat"},
            {"from": "heartbeat", "to": "plan"},
            {"from": "task_memory", "to": "notify"},
            {"from": "notify", "to": "archive"},
        ]
    )
    memory_policy: MemoryPolicy = field(default_factory=MemoryPolicy)
    approval_policy: ApprovalPolicy = field(default_factory=ApprovalPolicy)
    heartbeat_policy: HeartbeatPolicy = field(default_factory=HeartbeatPolicy)
    sub_agents: list[SubAgentSpec] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def __post_init__(self) -> None:
        legacy_ids = {
            "entry",
            "entry_gate",
            "context_bridge",
            "isolation_gate",
            "memory_recall",
            "plan",
            "risk_router",
            "parallel_branch",
            "parallel_research",
            "parallel_verify",
            "execute",
            "api_call",
            "transform",
            "approval",
            "human_handoff",
            "validation",
            "retry_loop",
            "checkpoint",
            "task_memory",
            "heartbeat",
            "notify",
            "archive",
        }
        current_ids = {str(item.get("id") or "") for item in self.workflow_nodes or [] if isinstance(item, dict)}
        if current_ids and current_ids.issubset(legacy_ids) and {
            "entry_gate",
            "context_bridge",
            "isolation_gate",
        }.intersection(current_ids):
            self.workflow_nodes = default_workflow_nodes()
            self.workflow_edges = default_workflow_edges()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AgentSpec":
        if not isinstance(payload, dict):
            return cls()
        payload = dict(payload)
        payload["memory_policy"] = MemoryPolicy.from_dict(payload.get("memory_policy"))
        payload["approval_policy"] = ApprovalPolicy.from_dict(
            payload.get("approval_policy")
        )
        payload["heartbeat_policy"] = HeartbeatPolicy.from_dict(
            payload.get("heartbeat_policy")
        )
        payload["default_task_budget"] = TaskBudget.from_dict(
            payload.get("default_task_budget")
        )
        payload["workflow_trigger"] = WorkflowTrigger.from_dict(
            payload.get("workflow_trigger")
        )
        payload["workflow_scope"] = WorkflowScope.from_dict(
            payload.get("workflow_scope")
        )
        payload["entry_policy"] = EntryPolicy.from_dict(payload.get("entry_policy"))
        payload["isolation_policy"] = IsolationPolicy.from_dict(
            payload.get("isolation_policy")
        )
        payload["sub_agents"] = [
            SubAgentSpec.from_dict(x) for x in (payload.get("sub_agents") or [])
        ]
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        base.__post_init__()
        return base


@dataclass
class ApprovalRequest:
    approval_id: str = field(default_factory=lambda: new_id("approval"))
    status: str = "pending"  # pending | approved | rejected | expired
    operation: str = ""
    reason: str = ""
    impact: str = ""
    rollback: str = ""
    created_at: str = field(default_factory=now_iso)
    resolved_at: str = ""
    resolved_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ApprovalRequest":
        base = cls()
        if isinstance(payload, dict):
            for key in asdict(base):
                if key in payload:
                    setattr(base, key, payload[key])
        return base


@dataclass
class TaskState:
    task_id: str = field(default_factory=lambda: new_id("task"))
    agent_id: str = ""
    agent_name: str = ""
    umo: str = ""
    status: str = "running"  # running | paused | blocked | completed | cancelled
    root_goal: str = ""
    completion_conditions: list[str] = field(default_factory=list)
    task_brief: str = ""
    profile_snapshot: dict[str, Any] = field(default_factory=dict)
    current_summary: str = ""
    last_confirmed_progress: str = ""
    next_step: str = ""
    last_observation: str = ""
    progress_log: list[dict[str, str]] = field(default_factory=list)
    state_snapshots: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[dict[str, str]] = field(default_factory=list)
    repeated_issue_counts: dict[str, int] = field(default_factory=dict)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    heartbeat: HeartbeatPolicy = field(default_factory=HeartbeatPolicy)
    lease: TaskLease = field(default_factory=TaskLease)
    watchdog: WatchdogState = field(default_factory=WatchdogState)
    wait: WaitState = field(default_factory=WaitState)
    budget: TaskBudget = field(default_factory=TaskBudget)
    entry_summary: str = ""
    exit_summary: str = ""
    memory_candidates: list[str] = field(default_factory=list)
    workflow_current_node_id: str = ""
    workflow_path: list[str] = field(default_factory=list)
    workflow_events: list[dict[str, Any]] = field(default_factory=list)
    workflow_data: dict[str, Any] = field(
        default_factory=lambda: {
            "node_outputs": {},
            "variables": {},
            "react_traces": [],
            "execution_counts": {},
            "blackboard": {
                "assignments": [],
                "reports": [],
                "mailbox": {},
                "decisions": [],
            },
        }
    )
    parallel_runs: list[dict[str, Any]] = field(default_factory=list)
    token_usage: dict[str, int] = field(
        default_factory=lambda: {
            "input_other": 0,
            "input_cached": 0,
            "output": 0,
            "total": 0,
        }
    )
    archive_path: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    finished_at: str = ""

    def add_log(self, kind: str, text: str) -> None:
        self.progress_log.append(
            {"time": now_iso(), "kind": kind, "text": str(text).strip()}
        )
        self.updated_at = now_iso()

    def add_snapshot(self, kind: str, data: dict[str, Any] | None = None) -> None:
        self.state_snapshots.append(
            {
                "time": now_iso(),
                "kind": str(kind or "state"),
                "status": self.status,
                "current_summary": self.current_summary,
                "last_confirmed_progress": self.last_confirmed_progress,
                "next_step": self.next_step,
                "last_observation": self.last_observation,
                "data": data or {},
            }
        )
        self.state_snapshots = self.state_snapshots[-120:]
        self.updated_at = now_iso()

    def add_workflow_event(
        self,
        node_id: str,
        *,
        outcome: str = "",
        note: str = "",
        next_node_id: str = "",
        status: str = "completed",
    ) -> None:
        self.workflow_events.append(
            {
                "time": now_iso(),
                "node_id": str(node_id or "").strip(),
                "status": str(status or "completed").strip(),
                "outcome": str(outcome or "").strip(),
                "note": str(note or "").strip(),
                "next_node_id": str(next_node_id or "").strip(),
            }
        )
        self.workflow_events = self.workflow_events[-120:]
        self.updated_at = now_iso()

    def add_parallel_run(self, run: dict[str, Any]) -> None:
        payload = dict(run or {})
        payload.setdefault("time", now_iso())
        self.parallel_runs.append(payload)
        self.parallel_runs = self.parallel_runs[-40:]
        self.updated_at = now_iso()

    # --- 共享黑板（多Agent 协同）：主agent 派活 / 子agent 汇报 / 意见传达 / 决策 ---
    def _blackboard(self) -> dict[str, Any]:
        """惰性返回 blackboard；老任务（无此 key）也能安全使用。"""
        bb = self.workflow_data.get("blackboard")
        if not isinstance(bb, dict):
            bb = {}
            self.workflow_data["blackboard"] = bb
        if not isinstance(bb.get("assignments"), list):
            bb["assignments"] = []
        if not isinstance(bb.get("reports"), list):
            bb["reports"] = []
        if not isinstance(bb.get("mailbox"), dict):
            bb["mailbox"] = {}
        if not isinstance(bb.get("decisions"), list):
            bb["decisions"] = []
        return bb

    def post_assignment(
        self,
        sub_agent_id: str,
        instruction: str,
        *,
        resource_tags: list[str] | None = None,
        status: str = "pending",
    ) -> str:
        bb = self._blackboard()
        assign_id = new_id("asg")
        bb["assignments"].append(
            {
                "assign_id": assign_id,
                "sub_agent_id": str(sub_agent_id or "").strip(),
                "instruction": str(instruction or "").strip(),
                "resource_tags": [
                    str(t).strip() for t in (resource_tags or []) if str(t).strip()
                ],
                "status": str(status or "pending").strip(),
                "created_at": now_iso(),
            }
        )
        bb["assignments"] = bb["assignments"][-80:]
        self.updated_at = now_iso()
        return assign_id

    def post_report(
        self,
        sub_agent_id: str,
        summary: str,
        *,
        assign_id: str = "",
        evidence: str = "",
        risks: str = "",
        next_step: str = "",
    ) -> None:
        bb = self._blackboard()
        bb["reports"].append(
            {
                "sub_agent_id": str(sub_agent_id or "").strip(),
                "assign_id": str(assign_id or "").strip(),
                "summary": str(summary or "").strip(),
                "evidence": str(evidence or "").strip(),
                "risks": str(risks or "").strip(),
                "next": str(next_step or "").strip(),
                "time": now_iso(),
            }
        )
        bb["reports"] = bb["reports"][-80:]
        self.updated_at = now_iso()

    def post_message(
        self, sub_agent_id: str, text: str, *, sender: str = "orchestrator"
    ) -> None:
        target = str(sub_agent_id or "").strip()
        if not target:
            return
        bb = self._blackboard()
        box = bb["mailbox"].get(target)
        if not isinstance(box, list):
            box = []
        box.append(
            {
                "from": str(sender or "orchestrator").strip(),
                "text": str(text or "").strip(),
                "time": now_iso(),
            }
        )
        bb["mailbox"][target] = box[-40:]
        self.updated_at = now_iso()

    def post_decision(
        self, summary: str, *, basis: str = "", next_step: str = ""
    ) -> None:
        bb = self._blackboard()
        bb["decisions"].append(
            {
                "summary": str(summary or "").strip(),
                "basis": str(basis or "").strip(),
                "next": str(next_step or "").strip(),
                "time": now_iso(),
            }
        )
        bb["decisions"] = bb["decisions"][-80:]
        self.updated_at = now_iso()

    def add_token_usage(self, usage: Any) -> None:
        if not usage:
            return
        input_other = int(getattr(usage, "input_other", 0) or 0)
        input_cached = int(getattr(usage, "input_cached", 0) or 0)
        output = int(getattr(usage, "output", 0) or 0)
        total = int(getattr(usage, "total", input_other + input_cached + output) or 0)
        self.token_usage["input_other"] = self.token_usage.get("input_other", 0) + input_other
        self.token_usage["input_cached"] = self.token_usage.get("input_cached", 0) + input_cached
        self.token_usage["output"] = self.token_usage.get("output", 0) + output
        self.token_usage["total"] = self.token_usage.get("total", 0) + total
        self.updated_at = now_iso()

    def add_blocker(self, issue: str, detail: str = "") -> int:
        key = issue.strip() or "unknown"
        count = self.repeated_issue_counts.get(key, 0) + 1
        self.repeated_issue_counts[key] = count
        self.blockers.append(
            {
                "time": now_iso(),
                "issue": key,
                "detail": detail.strip(),
                "count": str(count),
            }
        )
        self.updated_at = now_iso()
        return count

    def pending_approvals(self) -> list[ApprovalRequest]:
        return [
            ApprovalRequest.from_dict(item)
            for item in self.approvals
            if isinstance(item, dict) and item.get("status") == "pending"
        ]

    def set_wait(
        self,
        *,
        wait_reason: str,
        message: str = "",
        source: str = "",
        resume_command: str = "/agentlab tick",
        resume_node: str = "",
        required_input: list[str] | None = None,
    ) -> None:
        now = now_iso()
        self.wait = WaitState(
            active=True,
            wait_reason=str(wait_reason or "need_user_decision").strip(),
            message=str(message or wait_reason or "").strip(),
            source=str(source or "").strip(),
            resume_command=str(resume_command or "/agentlab tick").strip(),
            resume_node=str(resume_node or self.workflow_current_node_id or "").strip(),
            required_input=[str(item).strip() for item in (required_input or []) if str(item).strip()],
            created_at=self.wait.created_at or now,
            updated_at=now,
        )
        self.watchdog.needs_user = True
        self.watchdog.paused_reason = self.wait.message or self.wait.wait_reason
        self.updated_at = now

    def clear_wait(self) -> None:
        if self.wait.active or self.watchdog.needs_user or self.watchdog.paused_reason:
            self.wait = WaitState(updated_at=now_iso())
            self.watchdog.needs_user = False
            self.watchdog.paused_reason = ""
            self.updated_at = now_iso()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["heartbeat"] = asdict(self.heartbeat)
        payload["lease"] = asdict(self.lease)
        payload["watchdog"] = asdict(self.watchdog)
        payload["wait"] = asdict(self.wait)
        payload["budget"] = asdict(self.budget)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TaskState":
        if not isinstance(payload, dict):
            return cls()
        payload = dict(payload)
        payload["heartbeat"] = HeartbeatPolicy.from_dict(payload.get("heartbeat"))
        payload["lease"] = TaskLease.from_dict(payload.get("lease"))
        payload["watchdog"] = WatchdogState.from_dict(payload.get("watchdog"))
        payload["wait"] = WaitState.from_dict(payload.get("wait"))
        payload["budget"] = TaskBudget.from_dict(payload.get("budget"))
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base
