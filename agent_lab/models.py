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
    notes: str = "任务模式不是失忆，而是把普通上下文压缩成可执行 task_brief。"

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MemoryPolicy":
        if not isinstance(payload, dict):
            return cls()
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
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
                "x": 40,
                "y": 160,
            },
            {
                "id": "entry_gate",
                "title": "开启确认",
                "kind": "human",
                "stage": "entry",
                "action": "confirm_entry",
                "instruction": "需要确认的触发模式必须先向用户说明将隔离插件、压缩上下文、创建 task_state，并等待明确同意。",
                "x": 260,
                "y": 300,
            },
            {
                "id": "context_bridge",
                "title": "上文压缩",
                "kind": "memory",
                "stage": "entry",
                "action": "summarize_entry",
                "instruction": "把普通聊天上文压缩为 task_brief；只保留目标、约束、授权、风险和接续语气，避免把日常记忆直接灌入专业模式。",
                "x": 260,
                "y": 80,
            },
            {
                "id": "plan",
                "title": "计划确认",
                "kind": "state",
                "stage": "plan",
                "action": "plan",
                "instruction": "把根目标拆成可验证步骤，明确完成条件、风险等级、工具范围和本轮只推进一个有限工作单元。",
                "x": 500,
                "y": 80,
            },
            {
                "id": "execute",
                "title": "工具执行",
                "kind": "tool",
                "stage": "execute",
                "action": "run_tools",
                "instruction": "只调用 AgentSpec 允许的工具或已注册自定义 API，并保留关键输出。",
                "x": 740,
                "y": 80,
            },
            {
                "id": "approval",
                "title": "审批闸门",
                "kind": "guard",
                "stage": "guard",
                "action": "request_approval",
                "instruction": "涉及删除、部署、重启、密钥、破坏性数据库等危险动作前先请求用户审批。",
                "x": 740,
                "y": 300,
            },
            {
                "id": "checkpoint",
                "title": "状态快照",
                "kind": "state",
                "stage": "checkpoint",
                "action": "save_state",
                "instruction": "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。",
                "x": 960,
                "y": 160,
            },
            {
                "id": "task_memory",
                "title": "任务记忆",
                "kind": "memory",
                "stage": "checkpoint",
                "action": "save_memory",
                "instruction": "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆；任务记忆独立于日常记忆，并以标签暴露给普通模式读取。",
                "x": 1180,
                "y": 80,
            },
            {
                "id": "heartbeat",
                "title": "心跳续跑",
                "kind": "guard",
                "stage": "guard",
                "action": "heartbeat",
                "instruction": "长任务由心跳唤醒，醒来先读 task_state，再推进一小步。",
                "x": 1180,
                "y": 300,
            },
            {
                "id": "archive",
                "title": "结束回流",
                "kind": "memory",
                "stage": "archive",
                "action": "exit_summary",
                "instruction": "只有完成、取消或用户要求退出时结束任务；输出任务成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。",
                "x": 1400,
                "y": 160,
            },
        ]
    )
    workflow_edges: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"from": "entry", "to": "entry_gate"},
            {"from": "entry_gate", "to": "context_bridge"},
            {"from": "context_bridge", "to": "plan"},
            {"from": "plan", "to": "execute"},
            {"from": "execute", "to": "approval"},
            {"from": "approval", "to": "checkpoint"},
            {"from": "checkpoint", "to": "task_memory"},
            {"from": "checkpoint", "to": "heartbeat"},
            {"from": "heartbeat", "to": "execute"},
            {"from": "task_memory", "to": "archive"},
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
    entry_summary: str = ""
    exit_summary: str = ""
    memory_candidates: list[str] = field(default_factory=list)
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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["heartbeat"] = asdict(self.heartbeat)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "TaskState":
        if not isinstance(payload, dict):
            return cls()
        payload = dict(payload)
        payload["heartbeat"] = HeartbeatPolicy.from_dict(payload.get("heartbeat"))
        base = cls()
        for key in asdict(base):
            if key in payload:
                setattr(base, key, payload[key])
        return base
