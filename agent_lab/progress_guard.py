"""Tick liveness from durable work evidence, independently of logs and usage.

Novel successful tool *inputs* are a conservative progress proxy, not proof of
goal completion. Repeating an input with a fresh call ID, output, timestamp or
token bill is not progress. No filesystem reads or model calls are made here.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .models import now_iso
from .task_permissions import read_only_call


WARN_AFTER = 2
PAUSE_AFTER = 3
_HOUSEKEEPING = {"report", "agent_lab_progress", "agent_lab_checkpoint"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProgressSnapshot:
    evidence: frozenset[str]
    completed: frozenset[str]
    nodes: frozenset[str]
    failed: frozenset[str]
    handoffs: frozenset[str]


def snapshot(task: Any) -> ProgressSnapshot:
    state = task.workflow_data.get("task_control", {})
    evidence, failed, mutations = set(), set(), set()
    valid_ids: dict[str, set[str]] = {}
    steps = {str(s.get("id")): s for s in state.get("steps", [])}
    authority = state.get("authorization_version", state.get("approved_version", 0))
    for row in state.get("journal", []):
        step = steps.get(str(row.get("step_id")))
        if (step is None or row.get("authorization_version", row.get("plan_version", 0)) != authority
                or row.get("step_revision", 0) != step.get("revision", 0)):
            continue
        name, args = str(row.get("name", "")), row.get("arguments") or {}
        intent = _digest([name, args, row.get("step_id"), step.get("revision", 0), authority])
        if row.get("status") in {"failed", "unknown"}:
            failed.add(str(row.get("id") or _digest(row)))
        if row.get("status") != "completed":
            continue
        if name == "report" and row.get("id"):
            # A saved analysis can support a finite approved research step.
            # Rewriting reports alone is still not novel tool progress.
            valid_ids.setdefault(str(row.get("step_id")), set()).add(row["id"])
        if name in _HOUSEKEEPING or name.startswith("agent_lab_"):
            continue
        if row.get("id"):
            valid_ids.setdefault(str(row.get("step_id")), set()).add(row["id"])
        read_only = row.get("read_only") is True or read_only_call(name, args)
        # A read may legitimately be repeated after a new successful write.
        # Deduplicate mutations by intent so repeated writes cannot renew it.
        evidence.add(_digest([intent, sorted(mutations)]) if read_only else intent)
        if not read_only:
            mutations.add(intent)
    completed = {_digest([step.get("id"), step.get("revision", 0),
                          authority])
                 for step in steps.values() if step.get("status") == "completed"
                 and step.get("evidence") and set(step["evidence"]).issubset(valid_ids.get(str(step.get("id")), set()))}
    nodes = {str(row.get("node_id")) for row in task.workflow_events
             if row.get("node_id") and row.get("status") == "completed"}
    lanes = state.get("continuity", {}).get("lanes", {})
    handoffs = {str(lane.get("record_id")) for lane in lanes.values()
                if lane.get("record_id") and lane.get("record_path") and lane.get("summary")}
    return ProgressSnapshot(frozenset(evidence), frozenset(completed), frozenset(nodes),
                            frozenset(failed), frozenset(handoffs))


def after_tick(task: Any, before: ProgressSnapshot, *, reason: str, error: str = "",
               error_reason: str = "blocked_by_error") -> str:
    """Persist separate stall/error counters; never override an external stop."""
    state = task.workflow_data.get("task_control", {})
    if (task.status != "running" or state.get("human_paused") or task.pending_approvals()
            or not state.get("approved_version")
            or state.get("version") != state.get("approved_version")):
        return ""
    after = snapshot(task)
    saved = task.workflow_data.setdefault("progress_guard", {})
    # Journal/event retention may shrink between ticks. Keep deduplication
    # durable so replaying a dropped row cannot manufacture new progress.
    seen_evidence = set(saved.get("seen_evidence", [])) | set(before.evidence)
    seen_nodes = set(saved.get("seen_nodes", [])) | set(before.nodes)
    seen_completed = set(saved.get("seen_completed", [])) | set(before.completed)
    signals = {"tools": len(after.evidence - seen_evidence),
               "steps": len(after.completed - seen_completed),
               "nodes": len(after.nodes - seen_nodes)}
    progressed = any(signals.values())
    failure = error or ("工具执行失败或结果未知" if after.failed - before.failed else "")
    stall = int(saved.get("no_progress_ticks", 0))
    failures = int(saved.get("failure_ticks", 0)) + 1 if failure else 0
    grace_used = bool(saved.get("handoff_grace_used", False))
    grace = not progressed and not failure and bool(after.handoffs - before.handoffs) and not grace_used
    if progressed:
        stall, grace_used = 0, False
    elif grace:
        grace_used = True
    else:
        stall += 1
    decision = ("paused" if max(stall, failures) >= PAUSE_AFTER else
                "warning" if max(stall, failures) >= WARN_AFTER else
                "progress" if progressed else "handoff_grace" if grace else "no_progress")
    message = ""
    if decision in {"warning", "paused"}:
        detail = f"连续失败 {failures} 轮" if failures >= WARN_AFTER else f"连续 {stall} 轮没有新增有效工具证据、已完成步骤或节点"
        message = (f"卡死预警：{detail}；第 {PAUSE_AFTER} 轮将暂停，请更换方法并验证实际成果。"
                   if decision == "warning" else f"空转防护已暂停：{detail}；请核对检查点后明确恢复。")
    saved.update(version=1, no_progress_ticks=stall, failure_ticks=failures,
                 handoff_grace_used=grace_used, decision=decision, message=message,
                 signals=signals, last_error=failure[:1000], updated_at=now_iso(),
                 last_error_reason=error_reason if failure else "",
                 seen_evidence=sorted(seen_evidence | set(after.evidence)),
                 seen_nodes=sorted(seen_nodes | set(after.nodes)),
                 seen_completed=sorted(seen_completed | set(after.completed)))
    task.watchdog.last_tick_at = now_iso()
    task.watchdog.last_tick_reason = reason
    task.watchdog.consecutive_failures = max(stall, failures)
    task.watchdog.last_error = failure or ("no_progress" if stall else "")
    task.watchdog.last_decision = f"liveness_{decision}"
    if progressed:
        task.watchdog.last_progress_at = now_iso()
        task.watchdog.last_progress_hash = _digest(sorted(after.evidence | after.completed | after.nodes))
    if message:
        task.add_log(f"liveness_{decision}", message)
    if decision == "paused":
        task.status = "paused"
        task.set_wait(wait_reason=error_reason if failures >= PAUSE_AFTER else "no_progress",
                      message=message, source="progress_guard", resume_command="任务继续",
                      required_input=["核对实际成果并调整执行方法"])
    return message
