"""Core data models for Agent Lab v1.0.0.

Single Source of Truth:
- No canvas nodes/edges, no workflow_data triplication, no dead legacy fields.
- Clean serialization (`to_dict` / `from_dict`) with strict bounds normalization.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _clamp_int(val: Any, default: int, lo: int, hi: int) -> int:
    try:
        n = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _str_list(val: Any, limit: int = 200) -> list[str]:
    if not isinstance(val, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in val:
        s = str(item or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
            if len(out) >= limit:
                break
    return out


# ── Budget & Continuity ──────────────────────────────────────────────────────

@dataclass
class BudgetConfig:
    max_total_tokens: int = 0            # 0 = unlimited
    max_tokens_per_tick: int = 0         # 0 = unlimited
    max_total_tool_calls: int = 0        # 0 = unlimited
    max_total_ticks: int = 40
    max_total_seconds: int = 1800
    native_steps: int = 24

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> BudgetConfig:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            max_total_tokens=_clamp_int(d.get("max_total_tokens"), 0, 0, 50_000_000),
            max_tokens_per_tick=_clamp_int(d.get("max_tokens_per_tick"), 0, 0, 10_000_000),
            max_total_tool_calls=_clamp_int(d.get("max_total_tool_calls"), 0, 0, 100_000),
            max_total_ticks=_clamp_int(d.get("max_total_ticks"), 40, 1, 1000),
            max_total_seconds=_clamp_int(d.get("max_total_seconds"), 1800, 30, 86400 * 7),
            native_steps=_clamp_int(d.get("native_steps"), 24, 1, 200),
        )


@dataclass
class ContinuityConfig:
    context_tokens: int = 100_000        # soft ceiling used with context_percent
    context_percent: int = 55            # compact at 55% (55k default, safer than old 89.6k)
    summary_chars: int = 5000            # handoff summary hard cap
    ingress_cap_bytes: int = 14_336      # 14 KiB one-shot tool output cap (full saved to disk)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ContinuityConfig:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            context_tokens=_clamp_int(d.get("context_tokens"), 100_000, 4_000, 10_000_000),
            context_percent=_clamp_int(d.get("context_percent"), 55, 30, 85),
            summary_chars=_clamp_int(d.get("summary_chars"), 5000, 1000, 16_000),
            ingress_cap_bytes=_clamp_int(d.get("ingress_cap_bytes"), 14_336, 2048, 65_536),
        )


@dataclass
class SummarySharingConfig:
    share_with_daily: bool = False
    daily_summary_chars: int = 600
    share_with_tasks: bool = True
    task_summary_chars: int = 3000

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> SummarySharingConfig:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            share_with_daily=bool(d.get("share_with_daily", False)),
            daily_summary_chars=_clamp_int(d.get("daily_summary_chars"), 600, 100, 4000),
            share_with_tasks=bool(d.get("share_with_tasks", True)),
            task_summary_chars=_clamp_int(d.get("task_summary_chars"), 3000, 200, 12000),
        )


@dataclass
class ExecutionSettings:
    mode: str = "standard"               # readonly | standard | full
    roots: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    task_prompt: str = ""
    authorized_credentials: list[str] = field(default_factory=list)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    continuity: ContinuityConfig = field(default_factory=ContinuityConfig)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "roots": list(self.roots),
            "warnings": list(self.warnings),
            "task_prompt": self.task_prompt,
            "authorized_credentials": list(self.authorized_credentials),
            "budget": self.budget.to_dict(),
            "continuity": self.continuity.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> ExecutionSettings:
        d = raw if isinstance(raw, dict) else {}
        mode = str(d.get("mode") or "standard").strip().lower()
        if mode not in {"readonly", "standard", "full"}:
            mode = "standard"
        return cls(
            mode=mode,
            roots=_str_list(d.get("roots"), limit=50),
            warnings=_str_list(d.get("warnings"), limit=100),
            task_prompt=str(d.get("task_prompt") or "").strip()[:4000],
            authorized_credentials=_str_list(d.get("authorized_credentials"), limit=50),
            budget=BudgetConfig.from_dict(d.get("budget")),
            continuity=ContinuityConfig.from_dict(d.get("continuity")),
        )


# ── Profile (方案 — clean replacement for Canvas presets) ─────────────────────

@dataclass
class Profile:
    profile_id: str
    name: str
    description: str = ""
    is_default: bool = False
    system_prompt: str = ""
    task_prompt: str = ""
    permission_mode: str = "standard"    # readonly | standard | full
    plugin_blacklist: list[str] = field(default_factory=list)
    enabled_tools: list[str] = field(default_factory=list)    # empty = allow all non-disabled
    disabled_tools: list[str] = field(default_factory=list)   # HARD-blocked even in full mode!
    tool_risk_overrides: dict[str, str] = field(default_factory=dict)  # tool -> safe|work|high
    authorized_credentials: list[str] = field(default_factory=list)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    continuity: ContinuityConfig = field(default_factory=ContinuityConfig)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "description": self.description,
            "is_default": self.is_default,
            "system_prompt": self.system_prompt,
            "task_prompt": self.task_prompt,
            "permission_mode": self.permission_mode,
            "plugin_blacklist": list(self.plugin_blacklist),
            "enabled_tools": list(self.enabled_tools),
            "disabled_tools": list(self.disabled_tools),
            "tool_risk_overrides": dict(self.tool_risk_overrides),
            "authorized_credentials": list(self.authorized_credentials),
            "budget": self.budget.to_dict(),
            "continuity": self.continuity.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Profile:
        d = raw if isinstance(raw, dict) else {}
        mode = str(d.get("permission_mode") or "standard").strip().lower()
        if mode not in {"readonly", "standard", "full"}:
            mode = "standard"
        risks: dict[str, str] = {}
        for k, v in (d.get("tool_risk_overrides") or {}).items():
            rv = str(v or "").strip().lower()
            if k and rv in {"safe", "work", "high"}:
                risks[str(k)] = rv
        return cls(
            profile_id=str(d.get("profile_id") or new_id("prof")),
            name=str(d.get("name") or "未命名方案").strip()[:80],
            description=str(d.get("description") or "").strip()[:300],
            is_default=bool(d.get("is_default", False)),
            system_prompt=str(d.get("system_prompt") or "").strip()[:3000],
            task_prompt=str(d.get("task_prompt") or "").strip()[:3000],
            permission_mode=mode,
            plugin_blacklist=_str_list(d.get("plugin_blacklist"), limit=200),
            enabled_tools=_str_list(d.get("enabled_tools"), limit=500),
            disabled_tools=_str_list(d.get("disabled_tools"), limit=500),
            tool_risk_overrides=risks,
            authorized_credentials=_str_list(d.get("authorized_credentials"), limit=50),
            budget=BudgetConfig.from_dict(d.get("budget")),
            continuity=ContinuityConfig.from_dict(d.get("continuity")),
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
        )


def default_profiles() -> list[Profile]:
    return [
        Profile(
            profile_id="default",
            name="标准开发方案",
            description="常规任务默认方案：先只读探索出计划，审批后在授权目录内读写与测试，高危操作自动请示。",
            is_default=True,
            permission_mode="standard",
            budget=BudgetConfig(max_total_ticks=40, max_total_seconds=1800, native_steps=24),
            continuity=ContinuityConfig(context_tokens=100_000, context_percent=55, summary_chars=5000, ingress_cap_bytes=14_336),
        ),
        Profile(
            profile_id="readonly_research",
            name="只读调研方案",
            description="仅开放读取、搜索与只读命令，严禁写入文件或执行破坏性操作，适合代码审计与资料调研。",
            is_default=False,
            permission_mode="readonly",
            task_prompt="本方案为只读模式：专注信息搜集、代码审计与结构化结论，不做任何文件修改。",
            budget=BudgetConfig(max_total_ticks=25, max_total_seconds=900, native_steps=20),
            continuity=ContinuityConfig(context_tokens=80_000, context_percent=55, summary_chars=4500, ingress_cap_bytes=12_288),
        ),
        Profile(
            profile_id="full_autonomous",
            name="全权限高效方案",
            description="在授权工作区内放宽常规操作限制，保留禁令工具与高危破坏性操作拦截，适合复杂长周期工程。",
            is_default=False,
            permission_mode="full",
            budget=BudgetConfig(max_total_ticks=80, max_total_seconds=3600, native_steps=32),
            continuity=ContinuityConfig(context_tokens=128_000, context_percent=55, summary_chars=6000, ingress_cap_bytes=16_384),
        ),
    ]


# ── Project & Credentials ────────────────────────────────────────────────────

@dataclass
class Project:
    project_id: str
    title: str
    category: str = "通用"
    source_umo: str = ""
    platform_id: str = ""
    profile_id: str = "default"
    summary: str = ""
    summary_kind: str = ""               # automatic_handoff | bot_summary | manual
    summary_source_task_id: str = ""
    sharing: SummarySharingConfig = field(default_factory=SummarySharingConfig)
    execution_settings: ExecutionSettings = field(default_factory=ExecutionSettings)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "title": self.title,
            "category": self.category,
            "source_umo": self.source_umo,
            "platform_id": self.platform_id,
            "profile_id": self.profile_id,
            "summary": self.summary,
            "summary_kind": self.summary_kind,
            "summary_source_task_id": self.summary_source_task_id,
            "sharing": self.sharing.to_dict(),
            "execution_settings": self.execution_settings.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Project:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            project_id=str(d.get("project_id") or new_id("proj")),
            title=str(d.get("title") or "默认项目").strip()[:100],
            category=str(d.get("category") or "通用").strip()[:40],
            source_umo=str(d.get("source_umo") or "").strip(),
            platform_id=str(d.get("platform_id") or "").strip(),
            profile_id=str(d.get("profile_id") or "default").strip() or "default",
            summary=str(d.get("summary") or "")[:2000],
            summary_kind=str(d.get("summary_kind") or ""),
            summary_source_task_id=str(d.get("summary_source_task_id") or ""),
            sharing=SummarySharingConfig.from_dict(d.get("sharing")),
            execution_settings=ExecutionSettings.from_dict(d.get("execution_settings")),
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
        )


@dataclass
class CredentialMeta:
    """Public metadata for an encrypted vault item (secret or personal info). Plaintext NEVER lives here."""
    credential_id: str
    label: str
    kind: str = "secret"                 # secret (env-injected token/ssh) | personal (encrypted personal profile/note)
    provider: str = "generic"            # github | ssh | npm | pypi | personal | generic | ...
    env_var: str = ""                    # e.g. GITHUB_TOKEN, SSH_KEY_PASS (for kind=secret)
    inject_mode: str = "env"             # env (direct subprocess env injection) | reference
    scope: str = "global"                # global | project
    authorized_projects: list[str] = field(default_factory=list)
    share_with_tasks: bool = False       # only for kind=personal when user opts in
    note: str = ""
    has_value: bool = False
    masked_value: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CredentialMeta:
        d = raw if isinstance(raw, dict) else {}
        has_val = bool(d.get("has_value") or d.get("encrypted_value"))
        kind = str(d.get("kind") or "secret").strip().lower()
        if kind not in {"secret", "personal"}:
            kind = "secret"
        return cls(
            credential_id=str(d.get("credential_id") or new_id("cred")),
            label=str(d.get("label") or "未命名条目").strip()[:80],
            kind=kind,
            provider=str(d.get("provider") or ("personal" if kind == "personal" else "generic")).strip()[:40],
            env_var=str(d.get("env_var") or "").strip()[:64],
            inject_mode=str(d.get("inject_mode") or ("reference" if kind == "personal" else "env")).strip()[:20],
            scope=str(d.get("scope") or "global").strip()[:20],
            authorized_projects=_str_list(d.get("authorized_projects"), limit=100),
            share_with_tasks=bool(d.get("share_with_tasks", False)),
            note=str(d.get("note") or "").strip()[:300],
            has_value=has_val,
            masked_value="********" if has_val else "",
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
        )


# ── Task Entities (Lightweight meta.json < 5KB) ──────────────────────────────

@dataclass
class TaskStep:
    id: str
    title: str
    instruction: str = ""
    status: str = "pending"              # pending | running | completed | skipped
    stage: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], idx: int = 1) -> TaskStep:
        d = raw if isinstance(raw, dict) else {}
        status = str(d.get("status") or "pending").strip().lower()
        if status not in {"pending", "running", "completed", "skipped"}:
            status = "pending"
        return cls(
            id=str(d.get("id") or f"s{idx}").strip()[:40],
            title=str(d.get("title") or f"步骤 {idx}").strip()[:160],
            instruction=str(d.get("instruction") or "").strip()[:600],
            status=status,
            stage=str(d.get("stage") or "").strip()[:60],
            summary=str(d.get("summary") or "").strip()[:500],
        )


@dataclass
class QuestionItem:
    question_id: str
    question: str
    options: list[str] = field(default_factory=list)
    recommendation: str = ""
    status: str = "pending"              # pending | answered | cancelled
    answer: str = ""
    created_at: str = field(default_factory=now_iso)
    answered_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> QuestionItem:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            question_id=str(d.get("question_id") or new_id("q")),
            question=str(d.get("question") or "").strip()[:800],
            options=_str_list(d.get("options"), limit=6),
            recommendation=str(d.get("recommendation") or "").strip()[:400],
            status=str(d.get("status") or "pending"),
            answer=str(d.get("answer") or "").strip()[:1500],
            created_at=str(d.get("created_at") or now_iso()),
            answered_at=str(d.get("answered_at") or ""),
        )


@dataclass
class ApprovalRequest:
    approval_id: str
    approval_type: str                   # task_plan | tool_batch
    operation: str
    reason: str = ""
    impact: str = ""
    rollback: str = ""
    message: str = ""
    status: str = "pending"              # pending | approved | rejected | consumed | cancelled
    decision: str = ""
    decision_note: str = ""
    plan_version: int = 0
    workspace_root: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)   # for tool_batch
    created_at: str = field(default_factory=now_iso)
    resolved_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> ApprovalRequest:
        d = raw if isinstance(raw, dict) else {}
        calls = d.get("calls") if isinstance(d.get("calls"), list) else []
        return cls(
            approval_id=str(d.get("approval_id") or new_id("apr")),
            approval_type=str(d.get("approval_type") or "tool_batch"),
            operation=str(d.get("operation") or "").strip()[:240],
            reason=str(d.get("reason") or "").strip()[:600],
            impact=str(d.get("impact") or "").strip()[:600],
            rollback=str(d.get("rollback") or "").strip()[:400],
            message=str(d.get("message") or "").strip()[:2000],
            status=str(d.get("status") or "pending"),
            decision=str(d.get("decision") or ""),
            decision_note=str(d.get("decision_note") or "")[:400],
            plan_version=int(d.get("plan_version") or 0),
            workspace_root=str(d.get("workspace_root") or ""),
            calls=calls[:20],
            created_at=str(d.get("created_at") or now_iso()),
            resolved_at=str(d.get("resolved_at") or ""),
        )


@dataclass
class UsageTotals:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    llm_calls: int = 0
    unreported_calls: int = 0
    tool_calls: int = 0
    ticks_used: int = 0
    last_context_chars: int = 0
    last_estimated_tokens: int = 0
    handoff_count: int = 0
    last_handoff_chars: int = 0
    last_handoff_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> UsageTotals:
        d = raw if isinstance(raw, dict) else {}
        return cls(
            prompt_tokens=int(d.get("prompt_tokens") or 0),
            completion_tokens=int(d.get("completion_tokens") or 0),
            total_tokens=int(d.get("total_tokens") or 0),
            llm_calls=int(d.get("llm_calls") or 0),
            unreported_calls=int(d.get("unreported_calls") or 0),
            tool_calls=int(d.get("tool_calls") or 0),
            ticks_used=int(d.get("ticks_used") or 0),
            last_context_chars=int(d.get("last_context_chars") or 0),
            last_estimated_tokens=int(d.get("last_estimated_tokens") or 0),
            handoff_count=int(d.get("handoff_count") or 0),
            last_handoff_chars=int(d.get("last_handoff_chars") or 0),
            last_handoff_tokens=int(d.get("last_handoff_tokens") or 0),
        )


@dataclass
class TaskMeta:
    """Compact Single-Source-of-Truth task state persisted in meta.json.

    All heavy logs/journal/messages/usage live in append-only events.jsonl,
    keeping meta.json tiny (<5KB) and O(1) to update.
    """
    task_id: str
    umo: str
    project_id: str
    profile_id: str
    goal: str
    brief: str = ""
    status: str = "running"              # running | paused | completed | cancelled
    phase: str = "planning"              # planning | executing | completed | cancelled
    wait_reason: str = ""                # "" | need_plan_approval | need_tool_approval | need_answer | unknown_call | human_paused | budget | guard_paused
    human_paused: bool = False
    completion_conditions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    guidance: list[dict[str, str]] = field(default_factory=list)  # bounded to last 30
    steps: list[TaskStep] = field(default_factory=list)
    current_step_id: str = ""
    current_summary: str = ""
    final_summary: str = ""
    version: int = 0                     # plan version
    approved_version: int = 0
    authorization_version: int = 0
    input_revision: int = 0
    scope_roots: list[str] = field(default_factory=list)
    authorized_scope_roots: list[str] = field(default_factory=list)
    session_workspace_root: str = ""
    execution_cwd: str = ""
    execution_settings: ExecutionSettings = field(default_factory=ExecutionSettings)
    questions: list[QuestionItem] = field(default_factory=list)
    approvals: list[ApprovalRequest] = field(default_factory=list)
    usage: UsageTotals = field(default_factory=UsageTotals)
    continuity_state: dict[str, Any] = field(default_factory=dict)
    progress_guard_state: dict[str, Any] = field(default_factory=dict)
    started_at: str = field(default_factory=now_iso)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    ended_at: str = ""

    def pending_approvals(self) -> list[ApprovalRequest]:
        return [a for a in self.approvals if a.status == "pending"]

    def pending_questions(self) -> list[QuestionItem]:
        return [q for q in self.questions if q.status == "pending"]

    def is_terminal(self) -> bool:
        return self.status in {"completed", "cancelled"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "umo": self.umo,
            "project_id": self.project_id,
            "profile_id": self.profile_id,
            "goal": self.goal,
            "brief": self.brief,
            "status": self.status,
            "phase": self.phase,
            "wait_reason": self.wait_reason,
            "human_paused": self.human_paused,
            "completion_conditions": list(self.completion_conditions),
            "constraints": list(self.constraints),
            "guidance": list(self.guidance[-30:]),
            "steps": [s.to_dict() for s in self.steps],
            "current_step_id": self.current_step_id,
            "current_summary": self.current_summary,
            "final_summary": self.final_summary,
            "version": self.version,
            "approved_version": self.approved_version,
            "authorization_version": self.authorization_version,
            "input_revision": self.input_revision,
            "scope_roots": list(self.scope_roots),
            "authorized_scope_roots": list(self.authorized_scope_roots),
            "session_workspace_root": self.session_workspace_root,
            "execution_cwd": self.execution_cwd,
            "execution_settings": self.execution_settings.to_dict(),
            "questions": [q.to_dict() for q in self.questions[-30:]],
            "approvals": [a.to_dict() for a in self.approvals[-50:]],
            "usage": self.usage.to_dict(),
            "continuity_state": dict(self.continuity_state),
            "progress_guard_state": dict(self.progress_guard_state),
            "started_at": self.started_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "ended_at": self.ended_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TaskMeta:
        d = raw if isinstance(raw, dict) else {}
        steps = [TaskStep.from_dict(s, i + 1) for i, s in enumerate(d.get("steps") or []) if isinstance(s, dict)]
        questions = [QuestionItem.from_dict(q) for q in (d.get("questions") or []) if isinstance(q, dict)]
        approvals = [ApprovalRequest.from_dict(a) for a in (d.get("approvals") or []) if isinstance(a, dict)]
        guidance = [g for g in (d.get("guidance") or []) if isinstance(g, dict)][-30:]
        return cls(
            task_id=str(d.get("task_id") or new_id("task")),
            umo=str(d.get("umo") or ""),
            project_id=str(d.get("project_id") or ""),
            profile_id=str(d.get("profile_id") or "default"),
            goal=str(d.get("goal") or "").strip()[:1200],
            brief=str(d.get("brief") or "").strip()[:3000],
            status=str(d.get("status") or "running"),
            phase=str(d.get("phase") or "planning"),
            wait_reason=str(d.get("wait_reason") or ""),
            human_paused=bool(d.get("human_paused", False)),
            completion_conditions=_str_list(d.get("completion_conditions"), limit=30),
            constraints=_str_list(d.get("constraints"), limit=40),
            guidance=guidance,
            steps=steps,
            current_step_id=str(d.get("current_step_id") or ""),
            current_summary=str(d.get("current_summary") or "")[:2000],
            final_summary=str(d.get("final_summary") or "")[:8000],
            version=int(d.get("version") or 0),
            approved_version=int(d.get("approved_version") or 0),
            authorization_version=int(d.get("authorization_version") or 0),
            input_revision=int(d.get("input_revision") or 0),
            scope_roots=_str_list(d.get("scope_roots"), limit=50),
            authorized_scope_roots=_str_list(d.get("authorized_scope_roots"), limit=50),
            session_workspace_root=str(d.get("session_workspace_root") or ""),
            execution_cwd=str(d.get("execution_cwd") or ""),
            execution_settings=ExecutionSettings.from_dict(d.get("execution_settings")),
            questions=questions[-30:],
            approvals=approvals[-50:],
            usage=UsageTotals.from_dict(d.get("usage")),
            continuity_state=dict(d.get("continuity_state") or {}),
            progress_guard_state=dict(d.get("progress_guard_state") or {}),
            started_at=str(d.get("started_at") or now_iso()),
            created_at=str(d.get("created_at") or now_iso()),
            updated_at=str(d.get("updated_at") or now_iso()),
            ended_at=str(d.get("ended_at") or ""),
        )
