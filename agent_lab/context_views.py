"""Small model-facing views; the task journal and raw conversations stay intact."""
from __future__ import annotations

import copy
import json
import re
from itertools import islice

from .task_permissions import read_only_call

LARGE_FIELDS = {"old", "new", "content", "code", "script", "report", "steps_json", "operations_json"}
THOUGHT_FIELDS = {"reasoning_content", "reasoning_signature", "thinking", "signature", "encrypted"}
SIGNATURE_FIELDS = {"reasoning_signature", "signature", "encrypted", "extra_content"}


def arguments_view(arguments, limit=400):
    if not isinstance(arguments, dict):
        return {}
    def bounded(value, depth=0):
        if isinstance(value, str):
            return value[:limit] + f"…（共{len(value)}字符）" if len(value) > limit else value
        if isinstance(value, (dict, list)) and depth >= 2:
            return f"[嵌套参数已存原记录，共{len(value)}项]"
        if isinstance(value, dict):
            return {str(k)[:80]: bounded(v, depth+1) for k, v in islice(value.items(), 12)}
        if isinstance(value, list):
            return [bounded(v, depth+1) for v in value[:6]] + ([f"…共{len(value)}项"] if len(value)>6 else [])
        return value
    result = {str(key)[:80]: (f"[内容已存原记录，{len(value)}字符]" if key in LARGE_FIELDS and isinstance(value, str) and len(value) > limit
                            else bounded(value)) for key, value in islice(arguments.items(), 16)}
    if len(json.dumps(result, ensure_ascii=False, default=str)) > 3500:
        # Do not stringify the raw nested payload just to describe its size.
        result = {str(key)[:80]: (f"[参数见原记录，{len(value)}字符]" if isinstance(value, str)
                  else f"[参数见原记录，共{len(value)}项]" if isinstance(value, (dict, list)) else bounded(value))
                  for key, value in islice(arguments.items(), 16)}
    return result


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
    return ""


def _replace_text(content, value):
    if isinstance(content, list):
        return [{"type": "text", "text": value}, *[part for part in content if isinstance(part, dict) and part.get("type") != "text"]]
    return value


def history_view(history, task=None, *, for_summary=False, read_budget=6000):
    """Keep tool IDs/order. Never change signed assistant calls for a provider.

    Signed reasoning is protocol data, not material for a textual handoff. It
    stays untouched on the provider path and in the archived raw history.
    """
    models = [type(row) if callable(getattr(row, "model_dump", None)) else None for row in history]
    rows = copy.deepcopy([row.model_dump() if model else row for row, model in zip(history, models)])
    calls, results = {}, {}
    journal = (getattr(task, "workflow_data", {}) or {}).get("task_control", {}).get("journal", []) if task else []
    evidence_ids = {}
    for i, row in enumerate(rows):
        for call in row.get("tool_calls") or []:
            fn = call.get("function", {})
            try:
                raw_args = fn.get("arguments")
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args or "{}")
            except (TypeError, ValueError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            name = fn.get("name", "")
            calls[call.get("id")] = (name, args)
            if for_summary:
                fn["arguments"] = json.dumps(arguments_view(args), ensure_ascii=False)
                for target in (call, fn):
                    for key in THOUGHT_FIELDS | {"extra_content"}:
                        target.pop(key, None)
        if row.get("role") == "tool":
            results[row.get("tool_call_id")] = i
        if for_summary:
            for key in THOUGHT_FIELDS | {"extra_content"}:
                row.pop(key, None)
            if isinstance(row.get("content"), list):
                row["content"] = [{k: v for k, v in part.items() if k not in THOUGHT_FIELDS | {"extra_content"}}
                                  if part.get("type") == "text" else {"type": "text", "text": "[媒体内容见原始记录]"}
                                  for part in row["content"] if isinstance(part, dict) and part.get("type") not in {"think", "thinking", "redacted_thinking", "reasoning"}]
    remaining = read_budget
    for identifier, i in reversed(list(results.items())):
        name, args = calls.get(identifier, ("", {}))
        read = read_only_call(name, args)
        managed = read or name in {"agent_lab_read_state", "agent_lab_read_runtime", "agent_lab_read_tool_evidence", "agent_lab_read_handoff", "astrbot_file_edit_tool", "astrbot_file_write_tool"}
        if not managed:
            continue
        row = rows[i]
        body = text_of(row.get("content", ""))
        if len(body) < 500 or body.startswith("[历史工具内容已索引；"):
            continue
        evidence = re.search(r"任务工具证据 ID:\s*([\w-]+)", body)
        evidence_id = evidence.group(1) if evidence else ""
        if not evidence_id:
            signature = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
            if signature not in evidence_ids:
                # Usually the result already carries its ID. Resolve legacy
                # results lazily, without serializing every old file edit.
                evidence_ids[signature] = next((item.get("id", "") for item in reversed(journal)
                    if item.get("name") == name and item.get("arguments", {}) == args), "")
            evidence_id = evidence_ids[signature]
        preview_limit = 240 if for_summary else min(3000, max(160, remaining)) if read else 500
        preview = body[:preview_limit]
        if read:
            remaining = max(0, remaining - len(preview))
        locator = {"tool": name, "arguments": arguments_view(args, 160), "evidence_id": evidence_id or identifier}
        notice = ("[历史工具内容已索引；这是工作视图，原始记录未删除]\n"
                  + json.dumps(locator, ensure_ascii=False) + "\n" + preview
                  + f"\n（原输出{len(body)}字符；按证据ID分页读取，勿重新执行工具补读。）")
        if len(notice) >= len(body):
            continue  # A small output is cheaper and clearer in its original form.
        row["content"] = _replace_text(row.get("content", ""), notice)
    if not for_summary:
        for row in rows:
            parts = row.get("content", [])
            signed = any(row.get(key) for key in SIGNATURE_FIELDS) or isinstance(parts, list) and any(
                any(part.get(key) for key in SIGNATURE_FIELDS) for part in parts if isinstance(part, dict))
            for call in row.get("tool_calls") or []:
                if signed or any(target.get(key) for target in (call, call.get("function", {}))
                    for key in SIGNATURE_FIELDS) or call.get("id") not in results:
                    continue
                name, args = calls.get(call.get("id"), ("", {}))
                if name in {"astrbot_file_write_tool", "astrbot_file_edit_tool"}:
                    call["function"]["arguments"] = json.dumps(arguments_view(args), ensure_ascii=False)
    return [model.model_validate(row) if model and not for_summary else row for row, model in zip(rows, models)]


def state_summary(task):
    state = (task.workflow_data or {}).get("task_control", {})
    current = next((s for s in state.get("steps", []) if s.get("id") == state.get("current_step_id")), {})
    return json.dumps({"task_id": task.task_id, "status": task.status, "goal": task.root_goal[:500],
        "plan_version": state.get("version"), "current_step": {k: current.get(k) for k in ("id", "title", "status", "stage")},
        "completed_steps": sum(s.get("status") == "completed" for s in state.get("steps", [])),
        "step_count": len(state.get("steps", [])), "progress": task.last_confirmed_progress[:700],
        "next": task.next_step[:500], "wait": task.wait.message[:300],
        "recent_evidence": [{"id": r.get("id"), "name": r.get("name"), "status": r.get("status"),
                             "arguments": arguments_view(r.get("arguments", {}), 120), "result_chars": r.get("result_chars", len(r.get("result", "")))}
                            for r in state.get("journal", [])[-4:]],
        "notice": "完整计划已在任务提示词中；此处只返回状态和证据索引，原文用 agent_lab_read_tool_evidence 分页读。"}, ensure_ascii=False)
