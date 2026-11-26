"""Context engine for Agent Lab v1.0.0.

Core design guarantees:
1. 100% prefix cache stability: immutable static system prompt only; all mutable
   task/project/step/guidance state lives in user-turn wake messages.
2. Compact 5 control tool schemas (< 2.6 KB JSON) for clean per-task cloning.
3. One-shot ingress tool output truncation with disk pointer (never mutate history mid-cycle).
4. Content-addressed SHA-256 incremental wake context (full on first/post-handoff, delta afterwards).
5. Archive-first handoff compaction (`ContextCompactor` + `StageContextManager`).
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable

from .models import CredentialMeta, Profile, TaskMeta, new_id, now_iso
from .store import AgentLabStore

try:
    from astrbot.core.agent.message import Message as AstrMessage
except Exception:  # pragma: no cover - optional outside AstrBot runtime
    AstrMessage = None  # type: ignore[assignment,misc]

logger = logging.getLogger("astrbot_plugin_agent_lab.context_engine")

WAKE_PREFIX = "[Agent Lab 任务输入 "
HANDOFF_MARKER = "[Agent Lab 阶段交接记录]"
RECEIPT_MARKER = "[Agent Lab 已完成操作事实]"

_WAKE_DIGEST_RE = re.compile(re.escape(WAKE_PREFIX) + r"([0-9a-f]{64})\]\n")

_STATIC_TASK_RULESET = (
    "【Agent Lab 执行准则】\n"
    "1. 两阶段：planning阶段只读探索并调用task_plan提交计划待批；审批后进入executing阶段推进。\n"
    "2. 控制工具：task_plan(定计划)、task_progress(报进度)、task_ask(提问)、task_approve(高危审批)、task_finish(收尾)。\n"
    "3. 修改本地文件优先局部精确编辑；严禁输出或泄露凭证值（仅通过环境变量使用）。"
)

TASK_CONTROL_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "task_plan": {
        "description": "提交或更新任务计划与步骤（planning阶段必须调用）。",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "任务目标"},
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "title": {"type": "string"},
                            "instruction": {"type": "string"},
                            "stage": {"type": "string"},
                        },
                        "required": ["title"],
                    },
                },
                "completion_conditions": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "scope_roots": {"type": "array", "items": {"type": "string"}},
                "summary": {"type": "string"},
            },
            "required": ["steps"],
        },
    },
    "task_progress": {
        "description": "汇报当前步骤状态与阶段进度。",
        "parameters": {
            "type": "object",
            "properties": {
                "step_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "running", "completed", "skipped"],
                },
                "summary": {"type": "string"},
                "next_step_id": {"type": "string"},
            },
            "required": ["step_id", "status"],
        },
    },
    "task_ask": {
        "description": "向用户提出关键问题并暂停等待回答。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array", "items": {"type": "string"}},
                "recommendation": {"type": "string"},
            },
            "required": ["question"],
        },
    },
    "task_approve": {
        "description": "为高危或越界操作申请用户审批。",
        "parameters": {
            "type": "object",
            "properties": {
                "operation": {"type": "string"},
                "reason": {"type": "string"},
                "impact": {"type": "string"},
                "rollback": {"type": "string"},
                "operations_json": {
                    "type": "string",
                    "description": "JSON array of {tool_name, arguments}",
                },
            },
            "required": ["operation", "reason"],
        },
    },
    "task_finish": {
        "description": "核对完成条件并提交最终总结结束任务。",
        "parameters": {
            "type": "object",
            "properties": {
                "final_summary": {"type": "string"},
                "verified_conditions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["final_summary"],
        },
    },
}

_THINKING_KEYS = frozenset(
    {
        "reasoning",
        "reasoning_content",
        "reasoning_signature",
        "thought_signature",
        "thinking",
        "signature",
        "encrypted",
        "encrypted_content",
        "provider_specific_fields",
        "response_metadata",
    }
)
_THINKING_BLOCK_TYPES = frozenset({"thinking", "reasoning", "redacted_thinking"})
_WRITE_CODE_APPROVAL_TOKENS = (
    "write",
    "edit",
    "patch",
    "replace",
    "create",
    "delete",
    "remove",
    "append",
    "save",
    "modify",
    "insert",
    "rename",
    "move",
    "mkdir",
    "exec",
    "shell",
    "bash",
    "cmd",
    "powershell",
    "python",
    "run_command",
    "run_shell",
    "code",
    "approve",
    "apply",
)
_SUCCEEDED_STATUSES = frozenset({"completed", "succeeded", "success", "ok", "done", "approved"})
_FAILED_STATUSES = frozenset({"failed", "error", "rejected", "cancelled", "denied", "timeout"})


class HandoffError(RuntimeError):
    """Raised when message history structural invariants or handoff preconditions fail."""


# ── Static Prefix Prompt ─────────────────────────────────────────────────────

def build_static_system_prompt(
    persona_text: str,
    profile: Profile,
    host_skills_text: str = "",
) -> str:
    """Assemble 100% immutable static system prompt for prefix cache stability.

    NEVER includes mutable per-task or per-project fields (`project_summary`,
    `project_task_prompt`, `steps`, `guidance`, or `task_id`).
    """
    sections: list[str] = []
    for part in (
        persona_text,
        _STATIC_TASK_RULESET,
        getattr(profile, "system_prompt", "") or "",
        getattr(profile, "task_prompt", "") or "",
        host_skills_text,
    ):
        cleaned = str(part or "").strip()
        if cleaned:
            sections.append(cleaned)
    return "\n\n".join(sections)


# ── One-Shot Ingress Tool Output Cap ─────────────────────────────────────────

def truncate_tool_output(
    raw_text: str,
    *,
    cap_bytes: int = 14_336,
    saved_path: str = "",
) -> str:
    """Truncate oversized tool output once at ingress, preserving head+tail and disk pointer."""
    text = str(raw_text or "")
    encoded = text.encode("utf-8")
    total_bytes = len(encoded)
    if total_bytes <= cap_bytes:
        return text

    total_lines = max(1, len(text.splitlines()))
    head_budget = max(1, int(cap_bytes * 0.70))
    tail_budget = max(1, int(cap_bytes * 0.20))

    head_raw = encoded[:head_budget].decode("utf-8", errors="ignore")
    last_nl = head_raw.rfind("\n")
    head_text = head_raw[:last_nl] if last_nl > 0 else head_raw

    tail_raw = encoded[-tail_budget:].decode("utf-8", errors="ignore")
    first_nl = tail_raw.find("\n")
    tail_text = tail_raw[first_nl + 1 :] if 0 <= first_nl < len(tail_raw) - 1 else tail_raw

    target_path = saved_path or "未提供路径"
    pointer = f"[输出已截断，完整内容({total_bytes}B/{total_lines}行)已保存至: {target_path}，可按行号分段读取]"
    parts = [p for p in (head_text.rstrip("\n"), pointer, tail_text.lstrip("\n")) if p]
    return "\n\n".join(parts)


# ── Message & Token Helpers ──────────────────────────────────────────────────

def _msg_to_dict(msg: Any) -> dict[str, Any]:
    if isinstance(msg, dict):
        return copy.deepcopy(msg)
    if hasattr(msg, "model_dump"):
        return copy.deepcopy(msg.model_dump())
    out: dict[str, Any] = {
        "role": getattr(msg, "role", "user"),
        "content": getattr(msg, "content", ""),
    }
    tc = getattr(msg, "tool_calls", None)
    if tc is not None:
        out["tool_calls"] = [
            item.model_dump() if hasattr(item, "model_dump") else copy.deepcopy(item)
            for item in tc
        ]
    tc_id = getattr(msg, "tool_call_id", None)
    if tc_id is not None:
        out["tool_call_id"] = tc_id
    return out


def _dict_to_astr_message(msg: dict[str, Any]) -> Any:
    if AstrMessage is None:
        return msg
    return AstrMessage.model_validate(msg)


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict):
                if "text" in part:
                    chunks.append(str(part.get("text") or ""))
                elif "content" in part:
                    chunks.append(str(part.get("content") or ""))
            elif hasattr(part, "text"):
                chunks.append(str(getattr(part, "text") or ""))
        return "\n".join(c for c in chunks if c)
    return str(content)


def estimate_tokens(obj: Any) -> int:
    """Lightweight token estimator (~1 token per 2 CJK chars or 4 ASCII chars)."""
    if obj is None:
        return 0
    if isinstance(obj, str):
        text = obj
    elif isinstance(obj, (dict, list)):
        text = json.dumps(obj, ensure_ascii=False, default=str)
    elif hasattr(obj, "model_dump"):
        text = json.dumps(obj.model_dump(), ensure_ascii=False, default=str)
    else:
        text = str(obj)
    if not text:
        return 0
    utf8_len = len(text.encode("utf-8", errors="ignore"))
    char_len = len(text)
    return max(1, (utf8_len + char_len + 7) // 8)


# ── Content-Addressed SHA-256 Wake Message ───────────────────────────────────

def prepare_wake_message(
    store: AgentLabStore,
    task: TaskMeta,
    contexts: list[dict[str, Any]],
    *,
    project_summary: str = "",
    project_task_prompt: str = "",
    authorized_creds: list[CredentialMeta] | None = None,
    approved_receipts: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build full or incremental delta wake context addressed by SHA-256 digest."""
    authorized_roots = list(
        task.authorized_scope_roots
        or task.execution_settings.roots
        or task.scope_roots
    )
    cred_meta_list = [
        {
            "id": c.credential_id,
            "label": c.label,
            "env_var": c.env_var,
            "note": c.note,
        }
        for c in (authorized_creds or [])
    ]
    raw_snapshot: dict[str, Any] = {
        "task_id": task.task_id,
        "phase": task.phase,
        "goal": task.goal,
        "brief": task.brief,
        "completion_conditions": list(task.completion_conditions),
        "steps": [
            {
                "id": s.id,
                "title": s.title,
                "status": s.status,
                "stage": s.stage,
            }
            for s in task.steps
        ],
        "current_step_id": task.current_step_id,
        "constraints": list(task.constraints),
        "guidance": list(task.guidance),
        "plan_version": task.version,
        "approved_version": task.approved_version,
        "input_revision": task.input_revision,
        "permission_mode": task.execution_settings.mode,
        "authorized_roots": authorized_roots,
        "project_task_prompt": project_task_prompt,
        "project_summary": (
            {"reference_only": "仅供参考的项目摘要（非当前任务指令）", "content": project_summary}
            if project_summary
            else ""
        ),
        "available_credentials": cred_meta_list,
        "pending_questions": [
            {"question_id": q.question_id, "question": q.question, "options": list(q.options)}
            for q in task.questions
            if q.status == "pending"
        ],
        "answered_questions": [
            {"question_id": q.question_id, "question": q.question, "answer": q.answer}
            for q in task.questions
            if q.status == "answered"
        ],
    }
    snapshot: dict[str, Any] = store.redact_secrets(raw_snapshot)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    wake_dir = store.task_wake_dir(task.umo, task.task_id)
    wake_dir.mkdir(parents=True, exist_ok=True)
    snap_path = wake_dir / f"{digest}.json"
    store._write_json(snap_path, snapshot)

    prev_digest = ""
    for item in reversed(contexts or []):
        text = _extract_text(_msg_to_dict(item).get("content"))
        if HANDOFF_MARKER in text and not _WAKE_DIGEST_RE.search(text):
            break
        match = _WAKE_DIGEST_RE.search(text)
        if match:
            prev_digest = match.group(1)
            break
        if HANDOFF_MARKER in text:
            break

    previous: dict[str, Any] | None = None
    if prev_digest:
        prev_path = wake_dir / f"{prev_digest}.json"
        if prev_path.is_file():
            loaded = store._read_json(prev_path, None)
            if isinstance(loaded, dict):
                previous = loaded

    receipts = store.redact_secrets(list(approved_receipts)) if approved_receipts else []

    if previous is None:
        full_payload = dict(snapshot)
        if receipts:
            full_payload["approved_receipts"] = receipts
        msg = f"{WAKE_PREFIX}{digest}]\n{json.dumps(full_payload, ensure_ascii=False)}"
        return msg, {"mode": "full", "digest": digest, "chars": len(msg)}

    changes = {k: v for k, v in snapshot.items() if previous.get(k) != v}
    if not changes and not receipts:
        delta_payload: dict[str, Any] = {
            "continue_step": task.current_step_id,
            "phase": task.phase,
            "state": "无新指令，继续当前阶段推进。",
        }
    else:
        delta_payload = {"changes": changes}
        if receipts:
            delta_payload["approved_receipts"] = receipts

    msg = f"{WAKE_PREFIX}{digest}]\n{json.dumps(delta_payload, ensure_ascii=False)}"
    return msg, {"mode": "delta", "digest": digest, "chars": len(msg)}


# ── History Structural Grouping & Sanitization ───────────────────────────────

def _tool_call_id(tc: Any) -> str:
    if isinstance(tc, dict):
        return str(tc.get("id") or "").strip()
    return str(getattr(tc, "id", "") or "").strip()


def _tool_call_name_and_args(tc: Any) -> tuple[str, str]:
    if isinstance(tc, dict):
        fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
        name = str(fn.get("name") or tc.get("name") or "")
        args = fn.get("arguments") if "arguments" in fn else tc.get("arguments", "")
    else:
        fn = getattr(tc, "function", None)
        name = str(getattr(fn, "name", "") or getattr(tc, "name", "") or "")
        args = getattr(fn, "arguments", getattr(tc, "arguments", ""))
    args_str = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    return name, args_str


def message_groups(history: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group non-tool messages with following tool results, validating 1:1 tool_call IDs."""
    groups: list[list[dict[str, Any]]] = []
    idx = 0
    total = len(history)
    while idx < total:
        msg = _msg_to_dict(history[idx])
        role = str(msg.get("role") or "")
        if role == "tool":
            raise HandoffError(f"Orphaned tool message at index {idx} (tool_call_id={msg.get('tool_call_id')!r})")

        tool_calls = msg.get("tool_calls") or []
        expected_ids: list[str] = []
        if role == "assistant" and tool_calls:
            for tc in tool_calls:
                cid = _tool_call_id(tc)
                if not cid:
                    raise HandoffError(f"Assistant tool_call missing id at index {idx}")
                expected_ids.append(cid)

        group = [msg]
        idx += 1
        actual_ids: list[str] = []
        while idx < total:
            nxt = _msg_to_dict(history[idx])
            if str(nxt.get("role") or "") != "tool":
                break
            if role != "assistant" or not expected_ids:
                raise HandoffError(
                    f"Tool message at index {idx} has no matching assistant tool_calls"
                )
            tid = str(nxt.get("tool_call_id") or "").strip()
            if not tid:
                raise HandoffError(f"Tool message at index {idx} missing tool_call_id")
            actual_ids.append(tid)
            group.append(nxt)
            idx += 1

        if expected_ids:
            if (
                len(expected_ids) != len(actual_ids)
                or len(set(expected_ids)) != len(expected_ids)
                or set(expected_ids) != set(actual_ids)
            ):
                raise HandoffError(
                    f"Mismatched tool_calls and tool_call_ids: expected={expected_ids}, actual={actual_ids}"
                )

        groups.append(group)
    return groups


def _strip_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            if str(k) in _THINKING_KEYS:
                continue
            if k == "content" and isinstance(v, list):
                kept_blocks: list[Any] = []
                for block in v:
                    if isinstance(block, dict):
                        btype = str(block.get("type") or "").lower()
                        if btype in _THINKING_BLOCK_TYPES or block.get("thought") is True:
                            continue
                    kept_blocks.append(_strip_obj(block))
                cleaned[k] = kept_blocks
            else:
                cleaned[k] = _strip_obj(v)
        return cleaned
    if isinstance(obj, list):
        return [_strip_obj(item) for item in obj]
    return copy.deepcopy(obj)


def strip_thinking_metadata(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-copy messages and strip thinking/reasoning metadata for summarizer input."""
    return [_strip_obj(_msg_to_dict(m)) for m in messages]


def _is_write_code_or_approval(tool_name: str, j_entry: dict[str, Any]) -> bool:
    lname = tool_name.lower()
    if any(tok in lname for tok in _WRITE_CODE_APPROVAL_TOKENS):
        return True
    kind = str(j_entry.get("category") or j_entry.get("action_type") or j_entry.get("risk") or "").lower()
    return kind in {"write", "code", "approval", "work", "high"}


def _journal_succeeded(j_entry: dict[str, Any] | None) -> bool:
    if not j_entry:
        return False
    status = str(j_entry.get("status") or "").strip().lower()
    if status in _FAILED_STATUSES:
        return False
    if status in _SUCCEEDED_STATUSES:
        return True
    return bool(j_entry.get("ok") is True or j_entry.get("success") is True)


def fold_large_receipts(
    history: list[dict[str, Any]],
    journal: list[dict[str, Any]],
    archive_path: Path,
    storage_root: Path,
    *,
    threshold_chars: int = 8192,
) -> list[dict[str, Any]]:
    """Replace oversized completed write/code/approval tool groups with compact receipts."""
    resolved_archive = Path(archive_path).resolve()
    resolved_root = Path(storage_root).resolve()
    if not resolved_archive.is_file():
        raise HandoffError(f"Archive file does not exist: {archive_path}")
    try:
        rel_archive = str(resolved_archive.relative_to(resolved_root)).replace("\\", "/")
    except ValueError as exc:
        raise HandoffError(f"Archive path {archive_path} is outside storage root {storage_root}") from exc

    journal_by_id: dict[str, dict[str, Any]] = {}
    for row in journal or []:
        if isinstance(row, dict) and row.get("call_id"):
            journal_by_id[str(row["call_id"])] = row

    groups = message_groups(history)
    result: list[dict[str, Any]] = []
    for group in groups:
        head = group[0]
        tool_calls = head.get("tool_calls") or []
        if head.get("role") != "assistant" or not tool_calls or len(group) <= 1:
            result.extend(group)
            continue

        total_args_chars = 0
        call_summaries: list[dict[str, Any]] = []
        eligible = True
        for tc in tool_calls:
            cid = _tool_call_id(tc)
            tname, args_str = _tool_call_name_and_args(tc)
            total_args_chars += len(args_str)
            j_entry = journal_by_id.get(cid)
            if not _journal_succeeded(j_entry) or not _is_write_code_or_approval(tname, j_entry or {}):
                eligible = False
                break
            summary_txt = str(
                (j_entry or {}).get("summary")
                or (j_entry or {}).get("result_summary")
                or ""
            )[:240]
            call_summaries.append(
                {
                    "call_id": cid,
                    "tool": tname,
                    "status": "completed",
                    "args_chars": len(args_str),
                    "summary": summary_txt,
                }
            )

        if not eligible or total_args_chars < threshold_chars:
            result.extend(group)
            continue

        receipt_payload = {
            "archive": rel_archive,
            "calls": call_summaries,
        }
        receipt_msg = {
            "role": "user",
            "content": f"{RECEIPT_MARKER}\n{json.dumps(receipt_payload, ensure_ascii=False)}",
        }
        orig_len = len(json.dumps(group, ensure_ascii=False, default=str))
        new_len = len(json.dumps([receipt_msg], ensure_ascii=False, default=str))
        if new_len < orig_len:
            result.append(receipt_msg)
        else:
            result.extend(group)
    return result


def _is_tool_or_receipt_group(group: list[dict[str, Any]]) -> bool:
    if len(group) > 1:
        return True
    text = _extract_text(group[0].get("content"))
    return RECEIPT_MARKER in text


def recent_window(
    groups: list[list[dict[str, Any]]],
    token_budget: int,
    count_tokens: Callable[[Any], int] = estimate_tokens,
    *,
    fits: Callable[[list[dict[str, Any]]], bool] | None = None,
) -> list[dict[str, Any]]:
    """Select newest complete atomic groups within token_budget, stopping at HANDOFF_MARKER."""
    eligible_newest_first: list[list[dict[str, Any]]] = []
    for group in reversed(groups):
        if any(HANDOFF_MARKER in _extract_text(m.get("content")) for m in group):
            break
        eligible_newest_first.append(group)

    if not eligible_newest_first or token_budget <= 0:
        return []

    def _ok(msgs: list[dict[str, Any]]) -> bool:
        if count_tokens(msgs) > token_budget:
            return False
        if fits is not None and not fits(msgs):
            return False
        return True

    selected_newest_first: list[list[dict[str, Any]]] = []
    kept_flat: list[dict[str, Any]] = []
    has_tool_or_receipt = False

    for idx, group in enumerate(eligible_newest_first):
        candidate = [*group, *kept_flat]
        if _ok(candidate):
            selected_newest_first.append(group)
            kept_flat = candidate
            if _is_tool_or_receipt_group(group):
                has_tool_or_receipt = True
            continue

        # If nothing kept yet (e.g. newest message alone > budget), still try newest tool/receipt group
        if not kept_flat:
            continue

        # Already have non-tool content; try prioritizing newest tool/receipt group once if missing
        if not has_tool_or_receipt:
            for older_group in eligible_newest_first[idx + 1 :]:
                if _is_tool_or_receipt_group(older_group):
                    cand_with_tool = [*older_group, *kept_flat]
                    if _ok(cand_with_tool):
                        selected_newest_first.append(older_group)
                        kept_flat = cand_with_tool
                        has_tool_or_receipt = True
                    break
        break

    # Fallback: if contiguous scan found nothing (e.g. newest group exceeded budget),
    # check if the newest tool/receipt group fits by itself.
    if not kept_flat:
        for group in eligible_newest_first:
            if _is_tool_or_receipt_group(group) and _ok(group):
                return list(group)

    out: list[dict[str, Any]] = []
    for group in reversed(selected_newest_first):
        out.extend(group)
    return out


# ── Archive-First Handoff Compactor ──────────────────────────────────────────

def _fallback_summary(task: TaskMeta, folded: list[dict[str, Any]], archive_rel: str, reason: str) -> str:
    done_steps = [f"- {s.id}: {s.title} ({s.status})" for s in task.steps[-8:]]
    tail_snippets: list[str] = []
    for m in folded[-6:]:
        txt = _extract_text(m.get("content")).strip()
        if txt:
            tail_snippets.append(f"[{m.get('role')}]: {txt[:260]}")
    lines = [
        f"阶段交接（{reason}），完整历史归档于 `{archive_rel}`。",
        f"目标: {task.goal}",
        f"当前阶段: {task.phase} | 当前步骤: {task.current_step_id or '无'}",
    ]
    if done_steps:
        lines.append("步骤状态:\n" + "\n".join(done_steps))
    if tail_snippets:
        lines.append("近期记录:\n" + "\n".join(tail_snippets))
    return "\n\n".join(lines)


class ContextCompactor:
    """Archive-first context compactor guaranteeing post-compaction size < token_limit."""

    async def compact(
        self,
        store: AgentLabStore,
        task: TaskMeta,
        history: list[dict[str, Any]],
        provider: Any,
        reason: str,
        *,
        token_limit: int,
        count_tokens: Callable[[Any], int] | None = None,
    ) -> list[dict[str, Any]]:
        tok_fn = count_tokens or estimate_tokens
        norm_history = [_msg_to_dict(m) for m in history]
        non_system = [m for m in norm_history if str(m.get("role") or "") != "system"]

        # 1. Validate message_groups on non-system messages before any reduction
        message_groups(non_system)

        # 2. Archive full verbatim history BEFORE reduction
        handoff_id = new_id("hoff")
        handoffs_dir = store.task_handoffs_dir(task.umo, task.task_id)
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        archive_path = handoffs_dir / f"{handoff_id}.json"
        store._write_json(
            archive_path,
            {
                "handoff_id": handoff_id,
                "task_id": task.task_id,
                "reason": reason,
                "created_at": now_iso(),
                "message_count": len(norm_history),
                "messages": store.redact_secrets(norm_history),
            },
        )
        try:
            archive_rel = str(archive_path.resolve().relative_to(store.root.resolve())).replace("\\", "/")
        except ValueError:
            archive_rel = str(archive_path)

        # 3. Fold large completed receipts & strip thinking metadata for summarizer input
        journal = store.latest_journal_by_call(task.umo, task.task_id)
        folded = fold_large_receipts(non_system, journal, archive_path, store.root)
        summary_input = store.redact_secrets(strip_thinking_metadata(folded))

        # 4. Call provider.text_chat with 30s timeout and redact secrets
        summary_cap = int(task.execution_settings.continuity.summary_chars or 5000)
        raw_summary = ""
        if provider is not None and hasattr(provider, "text_chat"):
            sys_inst = (
                "你是任务交接摘要器。请基于历史对话输出简洁、客观的阶段交接摘要，"
                "必须涵盖：已完成事项与已验证结论、关键文件/产物路径、当前步骤与阻塞点、下一步计划及约束。"
                f"禁止编造事实或输出任何密钥。字数严格控制在 {summary_cap} 字符以内。"
            )
            serialized_hist = json.dumps(summary_input, ensure_ascii=False, default=str)
            if len(serialized_hist) > 120_000:
                serialized_hist = (
                    serialized_hist[:30_000]
                    + "\n...[中间历史已归档至 "
                    + archive_rel
                    + "]...\n"
                    + serialized_hist[-85_000:]
                )
            prompt_text = (
                f"交接原因: {reason}\n"
                f"任务目标: {task.goal}\n"
                f"当前阶段: {task.phase} | 当前步骤: {task.current_step_id}\n"
                f"归档路径: {archive_rel}\n\n"
                f"对话历史:\n{serialized_hist}"
            )
            try:
                res = await asyncio.wait_for(
                    provider.text_chat(
                        prompt=prompt_text,
                        system_prompt=sys_inst,
                        contexts=[],
                        _agent_lab_handoff=True,
                    ),
                    timeout=30,
                )
                if isinstance(res, str):
                    raw_summary = res
                else:
                    raw_summary = getattr(res, "completion_text", None) or getattr(res, "text", None) or ""
                    if not raw_summary and res is not None:
                        raw_summary = str(res)
            except Exception as exc:
                logger.warning("Handoff summarizer failed (%s), using fallback summary", exc)
                raw_summary = ""

        if not str(raw_summary).strip():
            raw_summary = _fallback_summary(task, folded, archive_rel, reason)

        clean_summary = str(store.redact_secrets(str(raw_summary))).strip()
        if len(clean_summary) > summary_cap:
            clean_summary = clean_summary[:summary_cap].rstrip()

        def _make_handoff_msg(summary_body: str) -> dict[str, Any]:
            header = f"{HANDOFF_MARKER}\n归档文件: {archive_rel}\n原因: {reason}"
            body = f"{header}\n\n{summary_body}" if summary_body else header
            return {"role": "user", "content": body}

        # 5. Select recent window & guarantee total < token_limit (prevent immediate re-handoff loop)
        recent_budget = max(1000, token_limit // 4) if token_limit >= 2000 else max(64, token_limit // 4)
        folded_groups = message_groups(folded)
        recent = recent_window(folded_groups, token_budget=recent_budget, count_tokens=tok_fn)

        handoff_msg = _make_handoff_msg(clean_summary)
        recent_grp_list = message_groups(recent) if recent else []

        while recent_grp_list and tok_fn([handoff_msg, *recent]) >= token_limit:
            recent_grp_list.pop(0)
            recent = [m for grp in recent_grp_list for m in grp]

        if tok_fn([handoff_msg, *recent]) >= token_limit and clean_summary:
            lo, hi = 0, len(clean_summary)
            best = ""
            while lo <= hi:
                mid = (lo + hi) // 2
                cand = _make_handoff_msg(clean_summary[:mid])
                if tok_fn([cand, *recent]) < token_limit:
                    best = clean_summary[:mid]
                    lo = mid + 1
                else:
                    hi = mid - 1
            clean_summary = best.rstrip()
            handoff_msg = _make_handoff_msg(clean_summary)

        # 6. Update usage & continuity state and persist
        compacted = [handoff_msg, *recent]
        task.usage.handoff_count += 1
        task.usage.last_handoff_chars = len(handoff_msg["content"])
        task.usage.last_handoff_tokens = tok_fn(compacted)
        cstate = dict(task.continuity_state or {})
        cstate.update(
            {
                "last_handoff_id": handoff_id,
                "last_handoff_at": now_iso(),
                "last_handoff_reason": reason,
                "last_archive_path": archive_rel,
                "pending_reason": "",
            }
        )
        task.continuity_state = cstate
        store.save_task(task)
        store.append_event(
            task.umo,
            task.task_id,
            "handoff",
            {
                "handoff_id": handoff_id,
                "reason": reason,
                "archive_path": archive_rel,
                "handoff_chars": task.usage.last_handoff_chars,
                "handoff_tokens": task.usage.last_handoff_tokens,
            },
        )
        return compacted


# ── Stage-Aware Context Manager Wrapper ──────────────────────────────────────

class StageContextManager:
    """Wraps AstrBot runner's context manager to enforce stage & token-limit handoffs."""

    def __init__(
        self,
        store: AgentLabStore,
        task: TaskMeta,
        provider: Any = None,
        *,
        inner: Any = None,
        compactor: ContextCompactor | None = None,
        static_system_prompt: str = "",
        tool_schemas: Any = None,
        prompt_tokens: int | None = None,
        provider_max_ctx: int = 0,
        native_max_ctx: int = 0,
    ) -> None:
        self.store = store
        self.task = task
        self.umo = task.umo
        self.task_id = task.task_id
        self.provider = provider
        self.inner = inner
        self.compactor = compactor or ContextCompactor()
        self.static_system_prompt = static_system_prompt
        self.tool_schemas = tool_schemas
        if prompt_tokens is not None:
            self.prompt_tokens = int(prompt_tokens)
        else:
            self.prompt_tokens = estimate_tokens(static_system_prompt) + estimate_tokens(tool_schemas)

        if provider_max_ctx > 0:
            self.provider_max_ctx = int(provider_max_ctx)
        else:
            pcfg = getattr(provider, "provider_config", None) if provider is not None else None
            self.provider_max_ctx = int((pcfg or {}).get("max_context_tokens") or 0) if isinstance(pcfg, dict) else 0

        if native_max_ctx > 0:
            self.native_max_ctx = int(native_max_ctx)
        else:
            icfg = getattr(inner, "config", None) if inner is not None else None
            self.native_max_ctx = int(getattr(icfg, "max_context_tokens", 0) or 0)

    def __getattr__(self, name: str) -> Any:
        inner = self.__dict__.get("inner")
        if inner is not None:
            return getattr(inner, name)
        raise AttributeError(f"{type(self).__name__} object has no attribute {name!r}")

    def count_tokens(self, messages: list[Any], trusted_token_usage: int = 0) -> int:
        native_counter = getattr(self.inner, "token_counter", None) if self.inner is not None else None
        base: int | None = None
        if native_counter is not None and hasattr(native_counter, "count_tokens"):
            try:
                if AstrMessage is not None:
                    msg_objs = [
                        _dict_to_astr_message(m) if isinstance(m, dict) else m
                        for m in messages
                    ]
                else:
                    msg_objs = list(messages)
                base = int(native_counter.count_tokens(msg_objs, trusted_token_usage))
            except Exception:
                base = None
        if base is None:
            if trusted_token_usage and trusted_token_usage > 0:
                base = int(trusted_token_usage)
            else:
                base = estimate_tokens([_msg_to_dict(m) for m in messages])
        return base + self.prompt_tokens

    def _effective_limit(self, task: TaskMeta) -> int:
        continuity = task.execution_settings.continuity
        candidates = [continuity.context_tokens]
        if self.provider_max_ctx > 0:
            candidates.append(self.provider_max_ctx)
        if self.native_max_ctx > 0:
            candidates.append(self.native_max_ctx)
        capacity = min(candidates)
        return max(1, (capacity * continuity.context_percent) // 100)

    async def process(self, messages: list[Any], trusted_token_usage: int = 0) -> list[Any]:
        reloaded = self.store.load_task(self.umo, self.task_id)
        task = reloaded or self.task
        self.task = task

        limit = self._effective_limit(task)
        tokens = self.count_tokens(messages, trusted_token_usage=trusted_token_usage)
        pending_reason = str((task.continuity_state or {}).get("pending_reason") or "").strip()

        should_compact = tokens >= limit or pending_reason in {"stage_changed", "stage_completed"}
        if not should_compact:
            return messages

        reason = (
            pending_reason
            if pending_reason in {"stage_changed", "stage_completed"}
            else "token_limit"
        )
        had_message_objs = any(not isinstance(m, dict) and hasattr(m, "model_dump") for m in messages)
        dict_msgs = [_msg_to_dict(m) for m in messages]
        system_msgs = [m for m in dict_msgs if str(m.get("role") or "") == "system"]

        compacted = await self.compactor.compact(
            self.store,
            task,
            dict_msgs,
            self.provider,
            reason,
            token_limit=limit,
            count_tokens=lambda ms: self.count_tokens(ms, trusted_token_usage=0),
        )
        merged = [*system_msgs, *compacted]
        if had_message_objs and AstrMessage is not None:
            return [_dict_to_astr_message(m) for m in merged]
        return merged


__all__ = [
    "ContextCompactor",
    "HANDOFF_MARKER",
    "HandoffError",
    "RECEIPT_MARKER",
    "StageContextManager",
    "TASK_CONTROL_TOOL_SCHEMAS",
    "WAKE_PREFIX",
    "build_static_system_prompt",
    "estimate_tokens",
    "fold_large_receipts",
    "message_groups",
    "prepare_wake_message",
    "recent_window",
    "strip_thinking_metadata",
    "truncate_tool_output",
]
