from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


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
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

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
        payload["entry_policy"] = EntryPolicy.from_dict(payload.get("entry_policy"))
        payload["isolation_policy"] = IsolationPolicy.from_dict(
            payload.get("isolation_policy")
        )
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
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
