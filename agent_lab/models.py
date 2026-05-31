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
            {"id": "entry", "title": "入口压缩", "kind": "state"},
            {"id": "plan", "title": "计划拆解", "kind": "state"},
            {"id": "execute", "title": "工具执行", "kind": "tool"},
            {"id": "approval", "title": "审批闸门", "kind": "guard"},
            {"id": "checkpoint", "title": "状态快照", "kind": "state"},
            {"id": "heartbeat", "title": "心跳续跑", "kind": "guard"},
            {"id": "archive", "title": "出口归档", "kind": "state"},
        ]
    )
    workflow_edges: list[dict[str, str]] = field(
        default_factory=lambda: [
            {"from": "entry", "to": "plan"},
            {"from": "plan", "to": "execute"},
            {"from": "execute", "to": "approval"},
            {"from": "approval", "to": "checkpoint"},
            {"from": "checkpoint", "to": "heartbeat"},
            {"from": "heartbeat", "to": "execute"},
            {"from": "checkpoint", "to": "archive"},
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
