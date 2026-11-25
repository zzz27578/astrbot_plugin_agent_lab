"""Compact UI/ledger display only. Never transforms provider history."""
import json
from itertools import islice

LARGE_FIELDS = {"old", "new", "content", "code", "script", "report", "steps_json", "operations_json"}

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
        "notice": "完整计划与原始工具结果保存在任务归档中。"}, ensure_ascii=False)
