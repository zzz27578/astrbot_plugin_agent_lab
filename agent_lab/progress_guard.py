"""Tool-result loop detection; quiet research and tick counts are not stalls.

Bridge contract: observe_tool(task, record) -> str after each external result,
including refusals. Append a nonempty return to the new tool result, then save
task. This module never rewrites history, performs IO, or invokes a model.
"""
from __future__ import annotations

import ast
import hashlib
import json
import ntpath
import posixpath
import re
from dataclasses import dataclass, field
from typing import Any

from .models import now_iso
from .task_permissions import READ_TOOLS, WRITE_TOOLS, _tokens, read_only_call


ERROR_WARN_AFTER = 3
ERROR_PAUSE_AFTER = 5
READ_WARN_AFTER = 18
READ_PAUSE_AFTER = 6  # Further overlapping reads after the single warning.
READ_WINDOW = 20
OVERLAP = 0.85
_HOUSEKEEPING = {"report", "task_plan", "task_progress", "task_ask", "task_approve", "task_finish"}

__all__ = ["observe_tool", "snapshot", "after_tick", "take_notice", "ProgressSnapshot"]


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def _path(value: str, cwd: str = "") -> str:
    windows = bool(ntpath.splitdrive(value)[0] or ntpath.splitdrive(cwd)[0])
    module = ntpath if windows else posixpath
    return module.normcase(module.normpath(module.join(cwd, value))).replace("\\", "/")


def _python_reads(code: str) -> list[dict]:
    """Recognise common Python reads, including direct line/character slices.
    Unknown code is never evidence of a write or of read-only execution.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    bindings, rows = {}, []
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    def path(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return bindings.get(node.id)
        if isinstance(node, ast.Call):
            func = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if func == "open" and isinstance(node.func, ast.Attribute):
                return path(node.func.value)
            if func in {"Path", "open"} and node.args:
                return path(node.args[0])
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = path(node.value)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name):
                    bindings[item.optional_vars.id] = path(item.context_expr)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"read", "readline", "readlines", "read_text", "read_bytes"}:
            continue
        target = path(node.func.value)
        if not target:
            continue
        row = {"path": target, "start": None, "end": None, "unit": "lines"}
        parent, splitlines = node, node.func.attr == "readlines"
        while parent in parents and isinstance(parents[parent], (ast.Attribute, ast.Call, ast.Subscript)):
            parent = parents[parent]
            splitlines |= isinstance(parent, ast.Attribute) and parent.attr == "splitlines"
            if isinstance(parent, ast.Subscript) and isinstance(parent.slice, ast.Slice):
                try:
                    start = ast.literal_eval(parent.slice.lower) if parent.slice.lower else 0
                    end = ast.literal_eval(parent.slice.upper)
                    if isinstance(start, int) and isinstance(end, int) and end > start >= 0:
                        row.update(start=start, end=end, unit="lines" if splitlines else "chars")
                except (ValueError, TypeError):
                    pass
                break
        rows.append(row)
    return rows


def _code(args: dict) -> str:
    tokens = _tokens(args.get("command", "")) if isinstance(args.get("command", ""), str) else []
    if "-c" in tokens and any("python" in t.lower() for t in tokens[:tokens.index("-c")]):
        return tokens[tokens.index("-c") + 1] if tokens.index("-c") + 1 < len(tokens) else ""
    value = args.get("code", args.get("script", ""))
    return value if isinstance(value, str) else ""


def _writes(record: dict) -> bool:
    if record.get("changed_paths") or record.get("name") in WRITE_TOOLS:
        return True
    args = record.get("arguments") or {}
    try:
        tree = ast.parse(_code(args))
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr in {"write_text", "write_bytes", "writelines"}:
            return True
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+"):
                return True
    return False


def _regions(record: dict, state: dict) -> list[dict]:
    """Prefer measured regions; otherwise recognise common native read tools.

    read_regions: [{path, start, end, unit?}], with exclusive end. Omit bounds
    only for a whole-file read. Search selectors stay separate from file reads.
    """
    args = record.get("arguments") or {}
    name = str(record.get("name", ""))
    supplied = record.get("read_regions")
    if isinstance(supplied, list):
        rows = [dict(r) for r in supplied if isinstance(r, dict) and isinstance(r.get("path"), str)]
    else:
        paths = [args[k] for k in ("path", "file_path", "directory") if isinstance(args.get(k), str)]
        command = args.get("command", "")
        tokens = _tokens(command) if isinstance(command, str) else []
        python_reads = _python_reads(_code(args))
        if not python_reads and name not in READ_TOOLS and not record.get("read_only") and not read_only_call(name, args):
            return []
        selector = ""
        if name == "astrbot_grep_tool":
            selector = _digest([args.get("pattern", args.get("query")), args.get("include"), args.get("glob")])
        if tokens and not python_reads:
            exe = ntpath.basename(tokens[0]).lower().removesuffix(".exe")
            operands = [t for t in tokens[1:] if not t.startswith("-") and t not in {";", "|", "&&", "||"}]
            if exe in {"rg", "grep", "select-string"}:
                selector = _digest(tokens[1:])
                operands = operands[1:]  # The search expression is not a path.
            paths.extend(t for t in operands if not t.isdecimal())
        start = args.get("offset", args.get("start_line", 0 if "limit" in args else None))
        end = args.get("end_line")
        if start is not None and args.get("limit") is not None:
            try:
                end = int(start) + int(args["limit"])
            except (TypeError, ValueError):
                start = end = None
        rows = python_reads or [{"path": p, "start": start, "end": end, "selector": selector} for p in paths]
    cwd = str(args.get("cwd") or record.get("cwd") or state.get("execution_cwd") or "")
    for row in rows:
        row["path"] = _path(row["path"], cwd)
        row["unit"] = row.get("unit", "lines")
        try:
            row["start"], row["end"] = int(row["start"]), int(row["end"])
            if row["end"] <= row["start"]:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            row["start"] = row["end"] = None
    return rows


def _overlap(row: dict, previous: list[dict]) -> bool:
    same = [r for r in previous if r.get("unit") == row["unit"]
            and r.get("selector", "") == row.get("selector", "")]
    if not same:
        return False
    if any(r["start"] is None for r in same):
        return True
    if row["start"] is None:
        return False  # A full file may contain much more than prior slices.
    start, end = row["start"], row["end"]
    intervals = sorted((max(start, r["start"]), min(end, r["end"])) for r in same)
    covered, cursor = 0, start
    for lo, hi in intervals:
        covered += max(0, hi - max(cursor, lo))
        cursor = max(cursor, hi)
    return covered / (end - start) >= OVERLAP


def _error(record: dict) -> str:
    value = record.get("error") or record.get("result", "")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            pass
    if isinstance(value, dict):
        value = value.get("error") or value.get("stderr") or value.get("message") or value
    text = str(value).strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    exceptions = [line for line in lines if re.match(r"(?:\w+\.)*\w*(?:Error|Exception):", line)]
    text = exceptions[-1] if exceptions else " ".join(lines)
    text = re.sub(r"\b\d{4}-\d\d-\d\d[T ][\d:.+Z-]+|0x[0-9a-f]+|\b(?:call|request)[_-][\w-]+", "<id>", text, flags=re.I)
    text = re.sub(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", "<id>", text, flags=re.I)
    text = re.sub(r"\b(line|attempt|retry|pid)\s*[=: #]?\s*\d+", r"\1 #", text, flags=re.I)
    text = re.sub(r"已拒绝\s*\d+\s*次", "已拒绝 # 次", text)
    return re.sub(r"\s+", " ", text).casefold()[:2000]


def _active(task: Any) -> bool:
    state = task.workflow_data.get("task_control", {})
    return (task.status == "running" and not state.get("human_paused") and not task.pending_approvals()
            and (not state.get("version") or state.get("version") == state.get("approved_version")))


def observe_tool(task: Any, record: dict) -> str:
    """Observe one terminal external result; return a warning/pause notice once.

    Required: name, arguments, status ('completed'/'failed'); error or result on
    failure. A unique id deduplicates bridge callbacks and after_tick fallback.
    Optional measured changed_paths/explored_paths and read_regions improve
    detection for opaque Python/shell programs. These must come from execution,
    not unverified model claims. The caller persists task after this call.
    """
    name, status = str(record.get("name", "")), record.get("status")
    if (not _active(task) or name in _HOUSEKEEPING or name.startswith("agent_lab_")
            or status not in {"completed", "failed", "error"}):
        return ""
    saved = task.workflow_data.get("progress_guard", {})
    if saved.get("version") != 2:
        saved = {"version": 2, "seen_paths": [], "coverage": {}, "seen_records": [],
                 "read_window": [], "failure_ticks": 0, "no_progress_ticks": 0}
        task.workflow_data["progress_guard"] = saved
    identifier = record.get("id")
    if identifier and identifier in saved["seen_records"]:
        return ""
    if identifier:
        saved["seen_records"] = [*saved["seen_records"], identifier][-2048:]

    failed = status in {"failed", "error"}
    error = _error(record) if failed else ""
    key = _digest([name, error]) if error else ""
    failures = saved["failure_ticks"] + 1 if key and key == saved.get("error_key") else int(bool(key))
    if key != saved.get("error_key") or not failed:
        saved.pop("error_warned", None)
    saved.update(error_key=key, failure_ticks=failures, last_error=error)

    regions = [] if failed else _regions(record, task.workflow_data.get("task_control", {}))
    paths = {r["path"] for r in regions}
    if not failed:
        paths.update(_path(p, str(record.get("cwd") or task.workflow_data.get("task_control", {}).get("execution_cwd", "")))
                     for p in record.get("explored_paths", []) if isinstance(p, str))
    novel = paths - set(saved["seen_paths"]) if not failed else set()
    args = record.get("arguments") or {}
    mutation = ""
    if not failed and _writes(record):
        mutation = _digest([name, args, record.get("content_hash"), record.get("changed_paths")])
    changed = bool(mutation and mutation != saved.get("last_mutation"))
    if changed:
        saved["last_mutation"] = mutation
        saved["coverage"] = {}  # A write invalidates prior read coverage.
    progressed = bool(novel or changed)
    overlap = bool(regions) and all(_overlap(r, saved["coverage"].get(r["path"], [])) for r in regions)
    for row in regions:
        coverage = saved["coverage"].setdefault(row["path"], [])
        if row not in coverage:
            coverage.append(row)
            del coverage[:-128]
    saved["seen_paths"] = sorted(set(saved["seen_paths"]) | paths)
    if progressed:
        saved["read_window"] = []
        saved.pop("read_warned", None)
        saved["reads_after_warning"] = 0
        task.watchdog.last_progress_at = now_iso()
        task.watchdog.last_progress_hash = _digest([saved["seen_paths"], mutation])
    else:
        saved["read_window"] = [*saved["read_window"], int(overlap)][-READ_WINDOW:]
    repeats = sum(saved["read_window"])
    if saved.get("read_warned") and overlap:
        saved["reads_after_warning"] = saved.get("reads_after_warning", 0) + 1
    if repeats < READ_WARN_AFTER:
        saved.pop("read_warned", None)
        saved["reads_after_warning"] = 0

    decision, message, cause = "progress" if progressed else "observed", "", ""
    if failures >= ERROR_WARN_AFTER:
        cause = "repeated_tool_error"
        if not saved.get("error_warned"):
            saved["error_warned"] = True
            decision, message = "warning", "同一工具已连续返回相同或等价错误，请调整参数或换一种方法后继续。"
        elif failures >= ERROR_PAUSE_AFTER:
            decision, message = "paused", "同一工具在提醒后仍连续返回等价错误，已暂停，请调整执行方法后继续。"
    elif repeats >= READ_WARN_AFTER:
        cause = "repeated_reads"
        if not saved.get("read_warned"):
            saved["read_warned"] = True
            decision, message = "warning", "最近多次读取高度重叠的同一区域，尚无新路径或实际改动；建议整理已有发现或换个方向继续。"
        elif saved.get("reads_after_warning", 0) >= READ_PAUSE_AFTER:
            decision, message = "paused", "提醒后仍反复读取同一区域且无实际推进，已暂停，请核对已有发现后继续。"
    saved.update(decision=decision, message=message, repeated_reads=repeats,
                 signals={"tools": int(progressed), "paths": len(novel), "writes": int(changed)}, updated_at=now_iso())
    task.watchdog.consecutive_failures = failures
    task.watchdog.last_decision = f"liveness_{decision}"
    task.watchdog.last_error = error
    if message:
        task.add_log(f"liveness_{decision}", message)
    if decision == "paused":
        task.status = "paused"
        task.watchdog.paused_reason = message
        task.set_wait(wait_reason=cause, message=message, source="progress_guard", resume_command="任务继续",
                      required_input=["调整执行方法或确认已有发现"])
    return message


@dataclass(frozen=True)
class ProgressSnapshot:
    # Compatibility for callers taking snapshots around a tick. No tick counter
    # influences liveness; fallback only observes new terminal journal rows.
    evidence: frozenset[str] = field(default_factory=frozenset)
    completed: frozenset[str] = field(default_factory=frozenset)
    nodes: frozenset[str] = field(default_factory=frozenset)
    failed: frozenset[str] = field(default_factory=frozenset)
    handoffs: frozenset[str] = field(default_factory=frozenset)


def snapshot(task: Any) -> ProgressSnapshot:
    rows = task.workflow_data.get("task_control", {}).get("journal", [])
    return ProgressSnapshot(evidence=frozenset(str(r.get("id") or _digest(r)) for r in rows
                                             if r.get("status") in {"completed", "failed", "error"}))


def after_tick(task: Any, before: ProgressSnapshot, *, reason: str, error: str = "",
               error_reason: str = "blocked_by_error") -> str:
    """Legacy fallback only. Provider/tick errors alone never imply a tool loop."""
    if not _active(task):
        return ""
    notices = []
    for row in task.workflow_data.get("task_control", {}).get("journal", []):
        identifier = str(row.get("id") or _digest(row))
        if identifier not in before.evidence:
            message = observe_tool(task, dict(row, id=identifier))
            if message:
                notices.append(message)
            if task.status != "running":
                break
    task.watchdog.last_tick_at = now_iso()
    task.watchdog.last_tick_reason = reason
    if notices:
        # Live bridge calls already inject the returned warning in the result.
        task.workflow_data["progress_guard"]["pending_notice"] = notices[-1]
    return "\n".join(notices)


def take_notice(task: Any) -> str:
    """Consume the fallback warning once, without editing existing history."""
    return task.workflow_data.get("progress_guard", {}).pop("pending_notice", "")
