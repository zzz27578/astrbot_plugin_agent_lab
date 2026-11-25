"""Append task input changes, never another full state dump on every wake."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re

PLAN_MARKER = "[本次任务的持久计划，优先于旧对话摘要]"
WAKE_MARKER = "[Agent Lab 任务输入 "
_TOKEN = re.compile(r"^\[Agent Lab 任务输入 ([a-f0-9]{64})\]\n")


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content
                         if isinstance(part, dict) and part.get("type") == "text")
    return ""


def snapshot(task):
    state = task.workflow_data.get("task_control", {})
    from .task_permissions import authorized_roots
    return {"task_id": task.task_id, "goal": task.root_goal,
            "brief": "\n\n".join(dict.fromkeys(v for v in (task.task_brief, task.entry_summary) if v)),
            "completion_conditions": task.completion_conditions,
            "steps": [{k: row[k] for k in ("id", "title", "instruction", "status", "stage", "summary") if k in row}
                      for row in state.get("steps", [])],
            "constraints": state.get("constraints", []), "current_step_id": state.get("current_step_id", ""),
            "next_action": task.next_step, "plan_version": state.get("version", 0),
            "approved_version": state.get("approved_version", 0), "input_revision": state.get("input_revision", 0),
            "scope": {"mode": state.get("execution_settings", {}).get("mode", "standard"),
                      "roots": authorized_roots(state), "session_workspace_root": state.get("session_workspace_root", ""),
                      "warnings": state.get("execution_settings", {}).get("warnings", []) + state.get("risk_lines", []),
                      "approved_cleanup_paths": state.get("approved_cleanup_paths", [])},
            "guidance": state.get("guidance", []), "questions": state.get("questions", []),
            "_handoff_record": state.get("continuity", {}).get("lanes", {}).get("", {}).get("record_id", ""),
            # Acknowledged IDs stay on disk; the model gets ordinary receipts.
            "_approval_records": [approval_version(r) for r in state.get("journal", []) if r.get("approval_id")]}


def approval_version(row):
    return json.dumps([row.get("id"), row.get("status"), row.get("fingerprint"), row.get("result_path")], ensure_ascii=False)


def changes(current, previous):
    delta = {key: deepcopy(value) for key, value in current.items()
             if not key.startswith("_") and key != "steps" and value != previous.get(key)}
    if current["steps"] != previous.get("steps"):
        old = {row["id"]: row for row in previous.get("steps", [])}
        new = {row["id"]: row for row in current["steps"]}
        delta["step_changes"] = [{"id": key, **{field: value for field, value in row.items()
                                               if field != "id" and value != old.get(key, {}).get(field)}}
                                 for key, row in new.items() if row != old.get(key)]
        removed = [key for key in old if key not in new]
        if removed:
            delta["removed_steps"] = removed
        if list(old) != list(new):
            delta["step_order"] = list(new)
    for key in ("guidance", "questions"):
        current_rows, previous_rows = current.get(key, []), previous.get(key, [])
        if key in delta and current_rows[:len(previous_rows)] == previous_rows:
            delta[key + "_added"] = current_rows[len(previous_rows):]
            del delta[key]
    return delta


def prepare(owner, task, history, prompt, *, lane=""):
    """Snapshot only delivered task prompts; arbitrary worker/user prompts pass through.

    The last visible marker selects its immutable on-disk snapshot. If a failed
    attempt saved the input but not a response, that input still reaches the
    provider in history next time; it need not be copied again. Compaction starts
    a new cycle without a marker and receives a new full brief exactly once.
    """
    if lane or PLAN_MARKER not in prompt:
        return prompt, None
    directory = owner.storage.task_memory_dir(task.umo, task.task_id) / "wake_inputs"
    previous = None
    for row in reversed(history):
        if row.get("role") != "user":
            continue
        match = _TOKEN.match(text_content(row.get("content")))
        if match:
            path = directory / (match[1] + ".json")
            try:
                stored = owner.storage._read_json(path)
                if isinstance(stored, dict) and stored.get("task_id") == task.task_id:
                    previous = stored
            except (OSError, ValueError):
                pass
            break
    current = json.loads(owner._redact_known_secrets(json.dumps(snapshot(task), ensure_ascii=False)))
    if previous is not None and previous.get("_handoff_record", "") != current["_handoff_record"]:
        previous = None  # Retained delta markers cannot stand in for a new cycle's full requirements.
    payload = changes(current, previous) if previous is not None else {k: v for k, v in current.items() if not k.startswith("_")}
    acknowledged = set(previous.get("_approval_records", [])) if previous else set()
    receipts = []
    for row in task.workflow_data.get("task_control", {}).get("journal", []):
        if row.get("approval_id") and approval_version(row) not in acknowledged:
            receipts.append({"tool": row.get("name"), "status": row.get("status"),
                             "result": str(row.get("result", ""))[:600],
                             "result_path": str(owner.storage.root / row["result_path"]) if row.get("result_path") else "",
                             "error": row.get("error", "")})
    if receipts:
        payload["approved_operations"] = receipts
    encoded = json.dumps(current, ensure_ascii=False, sort_keys=True)
    identifier = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    owner.storage._write_json(directory / (identifier + ".json"), current)
    instruction = "本周期任务要求与计划：" if previous is None else "以下仅为上次输入以来的变化；沿用已有要求继续执行。"
    if not payload:
        payload = {"continue_step": current["current_step_id"], "state": "无新指令，继续已有计划。"}
    body = (f"{WAKE_MARKER}{identifier}]\n{instruction}\n"
            + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return body, {"kind": "bootstrap" if previous is None else "delta", "chars": len(body),
                  "original_prompt_chars": len(prompt), "snapshot": identifier}
