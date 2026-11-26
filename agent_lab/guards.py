"""Progress loop guard, delivery verification, host persona/skills helpers, and admin shortcuts for Agent Lab v1.0.0."""
from __future__ import annotations

import hashlib
import inspect
import os
import re
from pathlib import Path
from typing import Any

from .models import TaskMeta
from .permissions import CODE_TOOLS, CONTROL_TOOL_NAMES, READ_TOOLS, WRITE_TOOLS, read_only_call

_COMPLETED_JOURNAL_STATUSES = frozenset({"completed", "ok", "success"})
_PENDING_JOURNAL_STATUSES = frozenset({"started", "unknown"})
_FAILED_JOURNAL_STATUSES = frozenset({"failed", "error", "denied", "rejected", "cancelled"})

_WRAPPER_QUOTES = (
    ('"', '"'),
    ("'", "'"),
    ("“", "”"),
    ("‘", "’"),
    ("`", "`"),
    ("「", "」"),
    ("『", "』"),
)

_APPROVE_RE = re.compile(r"^(?:批准|同意|approve)[!！。.\s]*$", re.IGNORECASE)
_REJECT_RE = re.compile(r"^(?:拒绝|reject)(?:[!！。.\s]*$|[:：\s]+(.*)$)", re.IGNORECASE)
_STOP_RE = re.compile(
    r"^(?:停止任务|取消任务|结束任务|停止当前任务|取消当前任务|结束当前任务|stop(?:\s+task)?|cancel(?:\s+task)?)[!！。.\s]*$",
    re.IGNORECASE,
)
_DELIVER_RE = re.compile(
    r"^(?:按现状交付|直接交付|直接交付当前任务|deliver(?:\s+now)?)[!！。.\s]*$",
    re.IGNORECASE,
)
_PAUSE_RE = re.compile(
    r"^(?:暂停任务|任务暂停|pause(?:\s+task)?)[!！。.\s]*$",
    re.IGNORECASE,
)
_RESUME_RE = re.compile(
    r"^(?:继续任务|任务继续|任务恢复|resume(?:\s+task)?)[!！。.\s]*$",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"^(?:任务状态|task\s+status)[!！。.\s]*$",
    re.IGNORECASE,
)


def _normalize_error_signature(tool_name: str, output: str) -> str:
    text = str(output or "").strip().splitlines()[0] if str(output or "").strip() else "error"
    text = re.sub(r"0x[0-9a-fA-F]+", "0x?", text)
    text = re.sub(r"\b\d+\b", "#", text)
    text = re.sub(r"\s+", " ", text).strip().lower()[:120]
    return f"{tool_name}:{text}"


def _extract_read_target_and_region(
    tool_name: str, arguments: dict[str, Any]
) -> tuple[str, tuple[int, int] | None]:
    args = arguments or {}
    target = ""
    for k in ("path", "file_path", "directory", "target", "command", "cmd", "pattern", "query"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            target = v.strip()
            break
    if target and ("/" in target or "\\" in target):
        target = os.path.normcase(os.path.normpath(target))

    start: int | None = None
    end: int | None = None
    for sk in ("start_line", "StartLine", "offset", "line_start"):
        if args.get(sk) is not None:
            try:
                start = int(args[sk])
                break
            except (TypeError, ValueError):
                pass
    for ek in ("end_line", "EndLine", "line_end"):
        if args.get(ek) is not None:
            try:
                end = int(args[ek])
                break
            except (TypeError, ValueError):
                pass
    if start is not None and end is None and args.get("limit") is not None:
        try:
            end = start + max(0, int(args["limit"]) - 1)
        except (TypeError, ValueError):
            pass

    if start is not None and end is not None and end >= start:
        return target, (start, end)
    return target, None


def _region_overlap_ratio(
    r1: tuple[int, int] | None,
    r2: tuple[int, int] | None,
) -> float:
    if r1 is None and r2 is None:
        return 1.0
    if r1 is None or r2 is None:
        return 0.0
    s1, e1 = r1
    s2, e2 = r2
    inter = max(0, min(e1, e2) - max(s1, s2) + 1)
    len1 = max(1, e1 - s1 + 1)
    len2 = max(1, e2 - s2 + 1)
    return inter / max(len1, len2)


class ProgressGuard:
    """Detects consecutive equivalent error streaks and stagnant read-only loops."""

    ERROR_WARN_AT = 3
    ERROR_PAUSE_AT = 5
    OVERLAP_WARN_AT = 14
    SAME_TARGET_WARN_AT = 18
    READ_PAUSE_AT = 20

    def observe_tool(
        self,
        task: TaskMeta,
        tool_name: str,
        arguments: dict[str, Any],
        ok: bool,
        output: str,
    ) -> dict[str, Any]:
        """Update compact O(1) guard counters on task and return action recommendation."""
        state = dict(task.progress_guard_state or {})
        error_sig = str(state.get("error_sig") or "")
        error_streak = int(state.get("error_streak") or 0)
        read_streak = int(state.get("read_streak") or 0)
        same_target_streak = int(state.get("same_target_streak") or 0)
        overlap_streak = int(state.get("overlap_streak") or 0)
        last_target = str(state.get("last_target") or "")
        last_start = state.get("last_start")
        last_end = state.get("last_end")
        last_out_hash = str(state.get("last_out_hash") or "")

        if not ok:
            sig = _normalize_error_signature(tool_name, output)
            if sig == error_sig:
                error_streak += 1
            else:
                error_sig = sig
                error_streak = 1
        else:
            error_sig = ""
            error_streak = 0

        is_control = tool_name in CONTROL_TOOL_NAMES
        is_readonly = read_only_call(tool_name, arguments or {}) and not is_control

        if is_readonly:
            read_streak += 1
            target, region = _extract_read_target_and_region(tool_name, arguments or {})
            out_hash = (
                hashlib.sha256(str(output or "").encode("utf-8")).hexdigest()[:16]
                if output
                else ""
            )
            prev_region = (
                (int(last_start), int(last_end))
                if last_start is not None and last_end is not None
                else None
            )

            if target and target == last_target:
                same_target_streak += 1
                ratio = _region_overlap_ratio(prev_region, region)
                if ratio >= 0.85 or (out_hash and out_hash == last_out_hash):
                    overlap_streak += 1
                else:
                    overlap_streak = 1
            else:
                same_target_streak = 1 if target else 0
                overlap_streak = 1 if target else 0

            last_target = target
            last_start = region[0] if region is not None else None
            last_end = region[1] if region is not None else None
            last_out_hash = out_hash
        elif not is_control and ok:
            # Successful non-readonly mutation/execution resets read stagnation counters
            read_streak = 0
            same_target_streak = 0
            overlap_streak = 0
            last_target = ""
            last_start = None
            last_end = None
            last_out_hash = ""

        task.progress_guard_state = {
            "error_sig": error_sig,
            "error_streak": error_streak,
            "read_streak": read_streak,
            "same_target_streak": same_target_streak,
            "overlap_streak": overlap_streak,
            "last_target": last_target,
            "last_start": last_start,
            "last_end": last_end,
            "last_out_hash": last_out_hash,
        }

        if error_streak >= self.ERROR_PAUSE_AT:
            return {
                "action": "pause",
                "message": f"工具 {tool_name} 连续出现 {error_streak} 次同类错误，任务已暂停，请人工介入或调整方案。",
            }
        if overlap_streak >= self.READ_PAUSE_AT or same_target_streak >= self.READ_PAUSE_AT:
            return {
                "action": "pause",
                "message": f"检测到连续 {max(overlap_streak, same_target_streak)} 次重复只读同一目标而无推进，任务已暂停。",
            }

        warnings: list[str] = []
        if error_streak >= self.ERROR_WARN_AT:
            warnings.append(f"工具 {tool_name} 已连续 {error_streak} 次同类报错，请切换排查方向")
        if overlap_streak >= self.OVERLAP_WARN_AT:
            warnings.append(f"检测到连续 {overlap_streak} 次高度重叠的重复读取，请避免原地空转")
        elif same_target_streak >= self.SAME_TARGET_WARN_AT:
            warnings.append(f"已连续 {same_target_streak} 次读取同一目标，请尽快整合信息并推进")

        if warnings:
            return {"action": "warn", "message": "；".join(warnings)}
        return {"action": "ok", "message": ""}


def _journal_tool_name(entry: dict[str, Any]) -> str:
    return str(entry.get("tool_name") or entry.get("tool") or "").strip()


def _journal_succeeded(entry: dict[str, Any]) -> bool:
    status = str(entry.get("status") or "").strip().lower()
    if status in _PENDING_JOURNAL_STATUSES or status in _FAILED_JOURNAL_STATUSES:
        return False
    if status in _COMPLETED_JOURNAL_STATUSES:
        return entry.get("ok", True) is not False
    return entry.get("ok") is True


def _written_basenames_from_entry(entry: dict[str, Any]) -> list[str]:
    args = entry.get("arguments")
    if not isinstance(args, dict):
        args = entry.get("args") if isinstance(entry.get("args"), dict) else {}
    names: list[str] = []
    for k in ("path", "file_path", "target", "destination", "dest"):
        v = args.get(k)
        if isinstance(v, str) and v.strip():
            names.append(Path(v.strip()).name)
    for k in ("paths", "files", "targets"):
        v = args.get(k)
        if isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str) and item.strip():
                    names.append(Path(item.strip()).name)
    return names


class DeliveryVerifier:
    """Verifies task readiness before marking a task as finished."""

    def verify_finish(
        self,
        task: TaskMeta,
        journal: list[dict[str, Any]],
        final_summary: str,
        *,
        admin_override: bool = False,
    ) -> tuple[bool, list[str]]:
        """Return (ok, gaps). Always passes when admin_override=True."""
        if admin_override:
            return (True, [])

        gaps: list[str] = []
        summary_text = str(final_summary or "").strip()

        # 1. Reconcile unfinished/unknown tool calls
        unresolved = [
            ev
            for ev in (journal or [])
            if str(ev.get("status") or "").strip().lower() in _PENDING_JOURNAL_STATUSES
        ]
        if unresolved:
            gaps.append(
                f"仍有 {len(unresolved)} 条工具调用处于 started/unknown 状态，请先核对完成状态后再交付。"
            )

        # 2. All plan steps must be completed or skipped
        incomplete_steps = [
            s for s in (task.steps or []) if s.status not in {"completed", "skipped"}
        ]
        if incomplete_steps:
            titles = ", ".join(s.title for s in incomplete_steps[:5])
            gaps.append(f"存在未完成或跳过的计划步骤：{titles}")

        # 3. Post-write verification & summary coverage in executing non-readonly mode
        mode = task.execution_settings.mode if task.execution_settings else "standard"
        if task.phase == "executing" and mode != "readonly":
            written_names: list[str] = []
            last_write_idx = -1
            for idx, ev in enumerate(journal or []):
                tname = _journal_tool_name(ev)
                if tname in WRITE_TOOLS and _journal_succeeded(ev):
                    last_write_idx = idx
                    for bn in _written_basenames_from_entry(ev):
                        if bn and bn not in written_names:
                            written_names.append(bn)

            if last_write_idx >= 0:
                missing_names = [bn for bn in written_names if bn not in summary_text]
                if missing_names:
                    gaps.append(
                        f"最终交付摘要未提及已修改文件：{', '.join(missing_names[:8])}"
                    )

                verified_after_write = False
                for ev in (journal or [])[last_write_idx + 1 :]:
                    tname = _journal_tool_name(ev)
                    if not tname or tname in CONTROL_TOOL_NAMES or tname in WRITE_TOOLS:
                        continue
                    if not _journal_succeeded(ev):
                        continue
                    ev_args = ev.get("arguments")
                    if not isinstance(ev_args, dict):
                        ev_args = ev.get("args") if isinstance(ev.get("args"), dict) else {}
                    if (
                        tname in READ_TOOLS
                        or tname in CODE_TOOLS
                        or read_only_call(tname, ev_args)
                    ):
                        verified_after_write = True
                        break

                if not verified_after_write:
                    gaps.append(
                        "最后一次文件写入后尚未执行读取复核或测试/命令验证，请先验证后再交付。"
                    )

        # 4. Final summary length check
        if len(summary_text) < 10:
            gaps.append("最终交付摘要内容过短（至少需要 10 个字符）。")

        return (len(gaps) == 0, gaps)


def _normalize_persona_obj(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, tuple):
        for item in raw:
            norm = _normalize_persona_obj(item)
            if norm is not None:
                return norm
        return None
    if isinstance(raw, dict):
        name = str(raw.get("name") or raw.get("persona_id") or "").strip()
        prompt = str(raw.get("system_prompt") or raw.get("prompt") or "").strip()
        pid = str(raw.get("persona_id") or name).strip()
        if not name and not prompt:
            return None
        out = dict(raw)
        out["persona_id"] = pid
        out["name"] = name or pid
        out["prompt"] = prompt
        return out

    name = str(getattr(raw, "name", "") or getattr(raw, "persona_id", "") or "").strip()
    prompt = str(
        getattr(raw, "system_prompt", "") or getattr(raw, "prompt", "") or ""
    ).strip()
    pid = str(getattr(raw, "persona_id", "") or name).strip()
    if not name and not prompt:
        return None
    out = {
        "persona_id": pid,
        "name": name or pid,
        "prompt": prompt,
    }
    skills = getattr(raw, "skills", None)
    if skills is not None:
        out["skills"] = list(skills) if isinstance(skills, (list, tuple, set)) else skills
    return out


async def resolve_source_persona(
    context: Any,
    umo: str,
    provider_settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Safely resolve the active source persona for a UMO without loading chat history."""
    if context is None:
        return None
    pm = getattr(context, "persona_manager", None)
    if pm is None:
        return None
    resolver = getattr(pm, "resolve_selected_persona", None)
    if resolver is None or not callable(resolver):
        return None

    platform_name = ""
    platform_id = str(umo or "").split(":", 1)[0] if ":" in str(umo or "") else ""
    plat_mgr = getattr(context, "platform_manager", None)
    for inst in (getattr(plat_mgr, "platform_insts", None) or []):
        try:
            meta = getattr(inst, "meta", None)
            if callable(meta):
                meta = meta()
            if meta is not None and getattr(meta, "id", "") == platform_id:
                platform_name = str(getattr(meta, "name", "") or "")
                break
        except Exception:
            continue

    try:
        sig = inspect.signature(resolver)
        kwargs: dict[str, Any] = {}
        params = sig.parameters
        if "umo" in params:
            kwargs["umo"] = umo
        if "platform_name" in params:
            kwargs["platform_name"] = platform_name
        if "provider_settings" in params:
            kwargs["provider_settings"] = provider_settings or {}
        if "conversation_id" in params:
            kwargs["conversation_id"] = None

        if kwargs:
            result = resolver(**kwargs)
        else:
            # Positional fallback when signature only uses *args or custom param names
            positional = [
                p
                for p in params.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            if len(positional) >= 3:
                result = resolver(umo, platform_name, provider_settings or {})
            elif len(positional) == 2:
                result = resolver(umo, platform_name)
            elif len(positional) == 1:
                result = resolver(umo)
            else:
                result = resolver()

        if inspect.isawaitable(result):
            result = await result
    except Exception:
        return None

    norm = _normalize_persona_obj(result)
    if norm is not None:
        return norm

    # If resolver returned a bare persona_id string (or tuple starting with id string)
    pid = ""
    if isinstance(result, str):
        pid = result.strip()
    elif isinstance(result, tuple) and result and isinstance(result[0], str):
        pid = result[0].strip()
    if pid:
        getter = getattr(pm, "get_persona", None)
        if callable(getter):
            try:
                got = getter(pid)
                if inspect.isawaitable(got):
                    got = await got
                return _normalize_persona_obj(got)
            except Exception:
                return None
    return None


def format_persona_prompt(persona: dict[str, Any] | None) -> str:
    """Format resolved persona into an instruction block."""
    if not persona:
        return ""
    prompt = str(persona.get("prompt") or persona.get("system_prompt") or "").strip()
    if not prompt:
        return ""
    name = str(persona.get("name") or persona.get("persona_id") or "默认人设").strip()
    return (
        f"[当前 Bot 人设：{name}]\n"
        f"{prompt}\n"
        "沿用该人设自然语气与管理员沟通，事实与风险清晰准确。"
    )


def format_host_skills_prompt(
    context: Any,
    cfg: dict[str, Any] | None,
    persona: dict[str, Any] | None,
) -> str:
    """Resolve active host skills excluding legacy `agent-mode` and format prompt lines."""
    if context is None:
        return ""
    skill_mgr = getattr(context, "skill_manager", None) or getattr(
        context, "skills_manager", None
    )
    if skill_mgr is None:
        return ""

    raw_skills: Any = None
    for attr in ("get_active_skills", "active_skills", "list_skills", "get_skills", "skills"):
        member = getattr(skill_mgr, attr, None)
        if member is None:
            continue
        try:
            if callable(member):
                sig = inspect.signature(member)
                kwargs: dict[str, Any] = {}
                if "cfg" in sig.parameters:
                    kwargs["cfg"] = cfg
                if "config" in sig.parameters:
                    kwargs["config"] = cfg
                if "persona" in sig.parameters:
                    kwargs["persona"] = persona
                raw_skills = member(**kwargs) if kwargs else member()
            else:
                raw_skills = member
            if raw_skills is not None:
                break
        except Exception:
            continue

    if not raw_skills:
        return ""
    if isinstance(raw_skills, dict):
        items = list(raw_skills.values())
    elif isinstance(raw_skills, (list, tuple, set)):
        items = list(raw_skills)
    else:
        return ""

    cfg_dict = cfg if isinstance(cfg, dict) else {}
    disabled_cfg = {
        str(s).strip()
        for s in (cfg_dict.get("disabled_skills") or cfg_dict.get("skill_blacklist") or [])
        if str(s).strip()
    }
    enabled_cfg_raw = cfg_dict.get("enabled_skills")
    enabled_cfg = (
        {str(s).strip() for s in enabled_cfg_raw if str(s).strip()}
        if isinstance(enabled_cfg_raw, (list, tuple, set)) and enabled_cfg_raw
        else None
    )

    persona_skills_raw = persona.get("skills") if isinstance(persona, dict) else None
    persona_skills = (
        {str(s).strip() for s in persona_skills_raw if str(s).strip()}
        if isinstance(persona_skills_raw, (list, tuple, set)) and persona_skills_raw
        else None
    )

    lines: list[str] = []
    seen: set[str] = set()
    for sk in items:
        if isinstance(sk, dict):
            name = str(sk.get("name") or "").strip()
            desc = str(sk.get("description") or "").strip()
            active = sk.get("active", sk.get("enabled", True))
        else:
            name = str(getattr(sk, "name", "") or "").strip()
            desc = str(getattr(sk, "description", "") or "").strip()
            active = getattr(sk, "active", getattr(sk, "enabled", True))

        if not name or not active:
            continue
        if name == "agent-mode":
            continue
        if name in disabled_cfg:
            continue
        if enabled_cfg is not None and name not in enabled_cfg:
            continue
        if persona_skills is not None and name not in persona_skills:
            continue
        if name in seen:
            continue
        seen.add(name)
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")

    if not lines:
        return ""
    return "[宿主可用技能]\n" + "\n".join(lines)


def parse_admin_shortcut(text: str) -> tuple[str, str] | None:
    """Parse concise Chinese/English admin control commands; ignore questions and quoted text."""
    s = str(text or "").strip()
    if not s:
        return None
    if s.endswith(("?", "？")):
        return None
    for left, right in _WRAPPER_QUOTES:
        if len(s) >= 2 and s.startswith(left) and s.endswith(right):
            return None

    if _APPROVE_RE.match(s):
        return ("approve", "")

    m_rej = _REJECT_RE.match(s)
    if m_rej:
        reason = str(m_rej.group(1) or "").strip()
        return ("reject", reason)

    if _STOP_RE.match(s):
        return ("stop", "")
    if _DELIVER_RE.match(s):
        return ("deliver", "")
    if _PAUSE_RE.match(s):
        return ("pause", "")
    if _RESUME_RE.match(s):
        return ("resume", "")
    if _STATUS_RE.match(s):
        return ("status", "")
    return None
