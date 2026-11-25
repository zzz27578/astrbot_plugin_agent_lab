"""Numeric, bounded task telemetry. No prompts or file bodies enter this ledger."""
from __future__ import annotations

import hashlib
import json

from .models import now_iso


def encoded(value):
    def default(item):
        if callable(getattr(item, "model_dump", None)):
            return item.model_dump()
        if hasattr(item, "tools"):
            return [{"name": t.name, "description": getattr(t, "description", ""), "parameters": getattr(t, "parameters", {})} for t in item.tools]
        return str(item)
    return json.dumps(value, ensure_ascii=False, default=default)


def estimate_tokens(value):
    return max(1, len(encoded(value).encode("utf-8")) // 3)


def role_chars(messages):
    totals = {}
    for row in messages:
        if callable(getattr(row, "model_dump", None)):
            row = row.model_dump()
        role = row.get("role", "other") if isinstance(row, dict) else "other"
        totals[role] = totals.get(role, 0) + len(encoded(row))
    return totals


def ledger(task):
    return task.workflow_data.setdefault("usage_metrics", {"model_calls": 0, "reported_calls": 0, "unreported_calls": 0,
                                                          "tokens": {"input": 0, "cached": 0, "output": 0, "total": 0},
                                                          "phases": {}, "last_rounds": []})


def request_size(raw, sent):
    fields = ("contexts", "system_prompt", "prompt", "func_tool", "tools")
    raw_payload = {key: raw[key] for key in fields if key in raw}
    sent_payload = {key: sent[key] for key in fields if key in sent}
    return {"raw_chars": len(encoded(raw_payload)), "sent_chars": len(encoded(sent_payload)),
            "estimated_tokens": estimate_tokens(sent_payload), "raw_estimated_tokens": estimate_tokens(raw_payload),
            "messages": len(sent.get("contexts") or []), "tools_chars": len(encoded(sent.get("func_tool", sent.get("tools", [])))),
            "raw_role_chars": role_chars(raw.get("contexts") or []), "view_role_chars": role_chars(sent.get("contexts") or [])}


def record_request(task, sizes, usage=None, *, phase="execution", status="completed", elapsed_ms=0, round_id=""):
    data = ledger(task)
    data["model_calls"] += 1
    reported = usage is not None
    tokens = {"input": int(getattr(usage, "input_other", 0) or 0), "cached": int(getattr(usage, "input_cached", 0) or 0),
              "output": int(getattr(usage, "output", 0) or 0), "total": int(getattr(usage, "total", 0) or 0)} if reported else None
    if tokens and not tokens["total"]:
        tokens["total"] = tokens["input"] + tokens["cached"] + tokens["output"]
    data["reported_calls" if reported else "unreported_calls"] += 1
    if tokens:
        for key, value in tokens.items():
            data["tokens"][key] += value
    entry = {"time": now_iso(), "phase": phase, "round_id": round_id, "status": status,
             "elapsed_ms": int(elapsed_ms), **sizes, "reported_tokens": tokens}
    data["last_request"] = entry
    if phase == "execution":
        data["last_execution_request"] = entry
    data["peak_raw_chars"] = max(data.get("peak_raw_chars", 0), sizes["raw_chars"])
    data["peak_sent_chars"] = max(data.get("peak_sent_chars", 0), sizes["sent_chars"])
    phase_data = data["phases"].setdefault(phase, {"calls": 0, "reported_tokens": 0, "unreported_calls": 0})
    phase_data["calls"] += 1
    phase_data["reported_tokens"] += tokens["total"] if tokens else 0
    phase_data["unreported_calls"] += int(not reported)
    return entry


def record_context(task, raw, view, *, estimated_tokens, capacity_tokens, trigger_tokens):
    row = {"time": now_iso(), "raw_chars": len(encoded(raw)), "sent_chars": len(encoded(view)),
           "messages": len(view), "estimated_tokens": int(estimated_tokens),
           "capacity_tokens": int(capacity_tokens), "trigger_tokens": int(trigger_tokens),
           "raw_role_chars": role_chars(raw), "view_role_chars": role_chars(view)}
    ledger(task)["context"] = row
    return row


def record_handoff(task, record):
    row = {"record_id": record["record_id"], "time": now_iso(), "reason": record["reason"],
           "raw_chars": record.get("raw_history_chars", 0), "source_chars": record.get("source_chars", 0),
           "summary_chars": len(record.get("summary", "")), "summary_limit": record.get("summary_limit", 0),
           "quality": record.get("quality", "normal"), "repairs": len(record.get("summary_issues", [])),
           "model_calls": record.get("model_calls", 0), "reported_tokens": record.get("reported_tokens", 0),
           "unreported_calls": record.get("unreported_calls", 0)}
    ledger(task)["handoff"] = row
    return row


def record_round(task, round_id):
    data = ledger(task)
    current = data.get("last_execution_request") or data.get("last_request", {})
    rows = [r for r in task.workflow_data.get("task_control", {}).get("journal", []) if r.get("round_id") == round_id]
    snapshot = {"id": round_id, "time": now_iso(), "tool_records": len(rows), "latest_context_chars": current.get("sent_chars", 0),
                "estimated_context_tokens": current.get("estimated_tokens", 0), "task_reported_tokens": task.budget.tokens_used,
                "file_read_reused_segments": sum(r.get("file_read", {}).get("reused_segments", 0) for r in rows)}
    data["last_rounds"] = [*data.get("last_rounds", []), snapshot][-12:]
    return snapshot


def write_task_line(owner, task, *, event_id, event="round"):
    """Local task timeline only, no extra model call or unsolicited transport."""
    if task.task_id in owner.projects.cleaning:
        return
    if not owner.storage.task_path(task.umo, task.task_id).exists():
        return
    data = ledger(task)
    current = data.get("context") or data.get("last_request", {})
    handoff = data.get("handoff", {})
    text = ((f"上下文记录：原始 {current.get('raw_chars', 0):,} 字符 → 模型工作视图 {current.get('sent_chars', 0):,} 字符；"
            f"约 {current.get('estimated_tokens', 0):,} Token（估算），不等于累计消耗。\n"
            ) if current else "") + (f"任务累计 {task.budget.tokens_used:,} Token；已计量模型请求报告 {data.get('tokens', {}).get('total', 0):,} Token；"
            f"{data.get('unreported_calls', 0)} 次请求未报告用量。")
    if handoff:
        text += (f"\n最近交接：{handoff['raw_chars']:,} 字符原记录 / {handoff['source_chars']:,} 字符总结材料 → "
                 f"{handoff['summary_chars']:,}/{handoff['summary_limit']:,} 字符摘要；"
                 f"{'降级，需回查证据' if handoff['quality']=='degraded' else '正常'}，修正 {handoff['repairs']} 次。")
    digest = hashlib.sha256(f"metrics:{event}:{event_id}".encode()).hexdigest()[:16]
    path = owner.storage.task_memory_dir(task.umo, task.task_id) / "messages.json"
    stream = owner.storage._read_json(path) if path.exists() else {"messages": [], "delivery": {}}
    stream["messages"] = [*[row for row in stream["messages"] if row.get("id") != digest], {"id": digest, "kind": "metrics", "status": "recorded", "time": now_iso(),
                                             "text": text, "chars": len(text)}][-100:]
    try:
        owner.storage._write_json(path, stream)
    except OSError:
        data["timeline_error"] = "write_failed"
