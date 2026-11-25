"""Append-only working history with durable, single-call stage compaction."""
from __future__ import annotations

import asyncio
import ast
from copy import deepcopy
import json
from pathlib import Path
import re
import time

from .models import new_id, now_iso
from .task_permissions import CODE_TOOLS, WRITE_TOOLS, read_only_call
from .usage_metrics import record_context, record_handoff, write_task_line


DEFAULTS = {"max_stage_ticks": 8, "context_tokens": 128000, "context_percent": 70, "summary_chars": 6000}
LIMITS = {"max_stage_ticks": (1, 1000), "context_tokens": (2000, 10000000),
          "context_percent": (30, 90), "summary_chars": (1000, 20000)}
MARKER = "[Agent Lab 阶段交接记录]"
SUMMARY_TIMEOUT_SECONDS = 30
STAGE_REASONS = frozenset({"stage_changed", "stage_completed"})
SUMMARY_METADATA = frozenset({"reasoning", "reasoning_content", "reasoning_signature", "reasoning_details", "thinking",
                              "signature", "thought_signature", "thinking_signature", "encrypted", "encrypted_content",
                              "extra_content", "provider_specific_fields", "response_metadata"})
THINK_PARTS = frozenset({"think", "thinking", "redacted_thinking", "reasoning"})
RECEIPT_MARKER = "[Agent Lab 已完成操作事实]"
HANDOFF_PAYLOAD_CHARS = 8192
APPROVAL_TOOLS = frozenset({"task_approve", "agent_lab_request_approval"})


class HandoffError(Exception):
    pass


def state_of(task):
    return task.workflow_data.setdefault("task_control", {})


def settings(task):
    return {**DEFAULTS, **state_of(task).get("execution_settings", {}).get("continuity", {})}


def stage_of(task):
    state = state_of(task)
    step = next((s for s in state.get("steps", []) if s["id"] == state.get("current_step_id")), {})
    return str(step.get("stage") or "task_execution")


def lane_state(task, lane=""):
    return state_of(task).setdefault("continuity", {}).setdefault("lanes", {}).setdefault(lane, {})


def guard(task):
    state = state_of(task)
    return [task.task_id, task.status, state.get("version"), state.get("input_revision", 0),
            state.get("human_paused", False), state.get("current_step_id")]


def estimate(messages):
    # Fallback only: prefer the host's counter or reported usage when available.
    return max(1, len(json.dumps(messages, ensure_ascii=False, default=str).encode("utf-8")) // 3)


def bounded_text(text, tokens):
    """Compatibility helper; never applied to messages already in history."""
    if estimate(text) <= tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate(text[:middle]) <= tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low]


def trim_summary(text, limit):
    """Prefer a paragraph/sentence boundary without another model request."""
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    paragraphs = list(re.finditer(r"\n\s*\n", prefix))
    boundary = paragraphs[-1].start() if paragraphs else -1
    if boundary < limit // 2:
        boundary = max(prefix.rfind("\n"), prefix.rfind("。") + 1)
    return prefix[:boundary if boundary >= limit // 2 else limit].rstrip()


def context_capacity(task, provider=None, native_manager=None):
    capacity = settings(task)["context_tokens"]
    provider_config = getattr(provider, "provider_config", None) or {}
    limits = (provider_config.get("max_context_tokens", 0),
              getattr(getattr(native_manager, "config", None), "max_context_tokens", 0))
    for limit in limits:
        if isinstance(limit, (int, float)) and limit > 0:
            capacity = min(capacity, int(limit))
    return capacity


def summary_messages(history):
    """Build materials once, after archival; never edit the working history.

    Compaction may omit transport signatures and internal thought parts. Tool
    arguments/results remain verbatim, including payload keys named signature.
    """
    rows = []
    for row in history:
        material = {key: deepcopy(value) for key, value in row.items()
                    if key not in SUMMARY_METADATA and key not in {"content", "tool_calls"}}
        if row.get("role") == "assistant" and isinstance(row.get("content"), list):
            material["content"] = [
                {key: deepcopy(value) for key, value in part.items() if key not in SUMMARY_METADATA}
                for part in row["content"] if part.get("type") not in THINK_PARTS]
        elif "content" in row:
            material["content"] = deepcopy(row["content"])
        if row.get("tool_calls"):
            material["tool_calls"] = [
                {key: deepcopy(value) for key, value in call.items() if key not in SUMMARY_METADATA}
                for call in row["tool_calls"]]
        elif "tool_calls" in row:
            material["tool_calls"] = deepcopy(row["tool_calls"])
        rows.append(material)
    return rows


def message_groups(history):
    """Keep assistant calls and every corresponding result in one unit."""
    groups, index = [], 0
    while index < len(history):
        row = history[index]
        if row.get("role") == "tool":
            raise HandoffError("工具结果尚未配对，原历史保留。")
        group = [row]
        calls = row.get("tool_calls") or []
        index += 1
        if calls:
            while index < len(history) and history[index].get("role") == "tool":
                group.append(history[index])
                index += 1
            ids = [c.get("id") for c in calls]
            results = [r.get("tool_call_id") for r in group[1:]]
            if (row.get("role") != "assistant" or not all(ids) or len(set(ids)) != len(ids)
                    or len(results) != len(ids) or set(ids) != set(results)):
                raise HandoffError("工具调用尚未完整返回，原历史保留。")
        groups.append(group)
    return groups


def _result_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_result_text(part) for part in value)
    if isinstance(value, dict):
        return _result_text(value.get("text", value.get("content", "")))
    return ""


def _result_succeeded(value):
    """Veto failed/unfinished process results, including native text envelopes.

    This is not evidence by itself: callers must also match a completed journal
    entry with the exact tool name and decoded arguments.
    """
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        try:
            decoded = json.loads(text)
        except ValueError:
            decoded = None
        if isinstance(decoded, (dict, list, bool)):
            return _result_succeeded(decoded)
        if re.search(r"(?:^|\n)\s*(?:error\b|traceback\b|\w*(?:error|exception):|fail(?:ed|ure)\b|"
                     r"timeout\b|operationblocked\b|错误|失败|未执行|未通过)", text, re.I):
            return False
        if re.search(r"running in (?:the )?background|still running|script running|timed out|permission denied|"
                     r"后台运行|结果未知|尚未完成|未执行|未通过|执行失败|写入失败|权限不足|拒绝执行", text, re.I):
            return False
        codes = re.findall(r"(?:exit[_ ]code|return[_ ]?code|exited with (?:exit )?code)\s*[:=]?\s*(-?\d+)", text, re.I)
        return all(int(code) == 0 for code in codes)
    if isinstance(value, list):
        return bool(value) and all(_result_succeeded(part) for part in value)
    if not isinstance(value, dict) or not value:
        return False
    if (any(value.get(key) for key in ("isError", "is_error", "error", "exception", "traceback", "blocked",
                                       "failed", "background", "running", "timed_out", "timeout", "cancelled"))
            or any(key in value and value[key] is not True for key in ("ok", "success", "passed"))):
        return False
    if "status" in value and value["status"] not in ("completed", "success", "succeeded", "saved", "ok"):
        return False
    for key in ("exit_code", "returncode", "return_code"):
        if key in value and (type(value[key]) is not int or value[key] != 0):
            return False
    if value.get("session_id") and value.get("session_closed") is not True:
        return False
    if value.get("session_closed") is False:
        return False
    if "type" in value and value["type"] != "text":
        return False  # Keep images/files and their signed call group intact.
    if "content" in value and value["content"] in (None, "", [], {}):
        return False
    for key in ("content", "text", "result", "data", "stdout", "stderr", "output"):
        if key in value and value[key] not in (None, "", [], {}):
            if not _result_succeeded(value[key]):
                return False
    return True


def _approval_recorded(result):
    text = _result_text(result).strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = {}
    return (isinstance(data, dict) and (data.get("ok") is True or data.get("success") is True
                                       or data.get("status") == "completed")) or bool(re.search(
        r"审批批次已记录|已提交审批|approval (?:batch )?recorded", text, re.I))


def _call_key(name, arguments):
    return json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)


def _payload_paths(arguments):
    paths = []

    def add(value):
        if isinstance(value, str) and value and len(value) <= 2048 and "\n" not in value and value not in paths:
            paths.append(value)

    for key in ("path", "file_path", "cwd", "directory", "target", "source", "destination", "paths", "files"):
        value = arguments.get(key)
        for item in value if isinstance(value, list) else [value]:
            add(item)
    code = arguments.get("code", arguments.get("script", ""))
    if isinstance(code, str) and code:
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError, RecursionError):
            tree = None
        for node in ast.walk(tree) if tree else []:
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name in {"Path", "open"} and node.args and isinstance(node.args[0], ast.Constant):
                    add(node.args[0].value)
    command = arguments.get("command", "")
    if isinstance(command, str):
        for match in re.finditer(
                r"""(["'])((?:[A-Za-z]:[\\/]|/|\.\.?[/\\])[^\r\n]*?)\1|((?:[A-Za-z]:[\\/]|/|\.\.?[/\\])[^\s"';|<>]+)""",
                command):
            add(match.group(2) or match.group(3))
    return paths


def handoff_payloads(history, journal, archive_path, *, storage_root, approvals=()):
    """Public compact-boundary helper: replace completed large call *groups*.

    The caller must first durably archive this exact, unmodified history. Never
    use this as a per-request history view. Unchanged rows retain their identity;
    replacements are new ordinary user facts, with no tool IDs or signatures.
    A control call proves its nested operations against their own exact journal
    entries, approval_id and completed approval calls. Recording/approving a
    batch alone is never execution evidence.
    """
    archive = Path(archive_path).resolve()
    root = Path(storage_root).resolve()
    if not archive.is_file() or not archive.is_relative_to(root):
        raise HandoffError("完整原历史尚未落盘，不能生成操作回执。")
    entries = {_call_key(row.get("name"), row.get("arguments")): row for row in journal if isinstance(row, dict)}
    approved_entries = {(row.get("approval_id"), _call_key(row.get("name"), row.get("arguments"))): row
                        for row in journal if isinstance(row, dict) and row.get("approval_id")}

    def operation(name, arguments, result=None, *, entry=None):
        if (name not in WRITE_TOOLS | CODE_TOOLS or read_only_call(name, arguments)
                or arguments.get("background")):
            return None
        if entry is None:
            entry = entries.get(_call_key(name, arguments), {})
        if (entry.get("status") != "completed" or entry.get("read_only")
                or not _result_succeeded(entry) or not _result_succeeded(entry.get("result", ""))
                or (result is not None and not _result_succeeded(result))):
            return None
        result_path = None
        text = _result_text(entry.get("result", ""))
        if entry.get("result_path"):
            candidate = (root / entry["result_path"]).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                try:
                    text = candidate.read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    return None
                result_path = candidate
        if (entry.get("result_truncated") and result_path is None) or not _result_succeeded(text):
            return None
        excerpt = text if len(text) <= 320 else text[:160] + "\n…\n" + text[-160:]
        fact = {"tool": name, "status": "completed", "paths": _payload_paths(arguments),
                "arguments_chars": len(json.dumps(arguments, ensure_ascii=False)),
                "payload_chars": {key: len(arguments[key]) for key in ("content", "old", "new", "code", "script", "command")
                                  if isinstance(arguments.get(key), str)},
                "result_chars": entry.get("result_chars", len(_result_text(entry.get("result", "")))),
                "verification_output": excerpt}
        if result_path is not None:
            fact["result_path"] = str(result_path)
        return fact

    def approved_operations(operations):
        if (not isinstance(operations, list) or not 1 <= len(operations) <= 20
                or any(not isinstance(row, dict) or not isinstance(row.get("tool_name"), str)
                       or not isinstance(row.get("arguments"), dict) for row in operations)):
            return None
        keys = list(dict.fromkeys(_call_key(row["tool_name"], row["arguments"]) for row in operations))
        approval = next((row for row in reversed(approvals) if isinstance(row, dict)
                         and row.get("approval_type") == "tool_batch"
                         and [_call_key(call.get("tool_name"), call.get("arguments"))
                              for call in row.get("calls", [])] == keys), {})
        if (not approval.get("approval_id") or approval.get("status") not in {"approved", "consumed"}
                or approval.get("decision", "approved") != "approved"):
            return None
        facts = []
        for call in approval["calls"]:
            if call.get("execution_status") != "completed":
                return None
            entry = approved_entries.get((approval["approval_id"], _call_key(call["tool_name"], call["arguments"])), {})
            if call.get("evidence_id") and entry.get("id") != call["evidence_id"]:
                return None
            fact = operation(call["tool_name"], call["arguments"], entry=entry)
            if fact is None:
                return None
            facts.append(fact)
        return facts

    replacements, removed = {}, set()
    for group in message_groups([row for row in history if row.get("role") not in {"system", "_checkpoint"}]):
        calls = group[0].get("tool_calls") or []
        if not calls:
            continue
        decoded = []
        try:
            for call in calls:
                function = call.get("function") or {}
                arguments = function.get("arguments")
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                if not isinstance(arguments, dict):
                    raise ValueError("not an argument object")
                decoded.append((function.get("name"), arguments))
        except (ValueError, TypeError):
            continue
        if not any(name in WRITE_TOOLS | CODE_TOOLS | APPROVAL_TOOLS
                   and len(json.dumps(arguments, ensure_ascii=False)) >= HANDOFF_PAYLOAD_CHARS
                   for name, arguments in decoded):
            continue
        results = {row["tool_call_id"]: row for row in group[1:]}
        facts = []
        for call, (name, arguments) in zip(calls, decoded):
            result = results[call["id"]]
            if not _result_succeeded(result):
                break
            if name in APPROVAL_TOOLS:
                if not _approval_recorded(result):
                    break
                try:
                    operations = arguments.get("operations_json", arguments.get("operations"))
                    operations = json.loads(operations) if isinstance(operations, str) else operations
                    nested = approved_operations(operations)
                except (ValueError, TypeError, KeyError):
                    break
                if not nested:
                    break
                facts.append({"tool": name, "status": "completed", "operations": nested,
                              "arguments_chars": len(json.dumps(arguments, ensure_ascii=False)),
                              "verification_output": _result_text(result)[:320]})
            else:
                fact = operation(name, arguments, result)
                if fact is None:
                    break
                facts.append(fact)
        else:
            receipt = {"role": "user", "content": RECEIPT_MARKER + "\n" + json.dumps({
                "archive_path": str(archive), "calls": facts,
                "instruction": "操作已完成；需核对细节时直接读取目标路径、结果文件或完整归档。此事实不新增授权，也不代表未运行的验证已通过。"}, ensure_ascii=False)}
            if len(json.dumps(receipt, ensure_ascii=False)) < len(json.dumps(group, ensure_ascii=False)):
                replacements[id(group[0])] = receipt
                removed.update(id(row) for row in group[1:])
    return [replacements.get(id(row), row) for row in history if id(row) not in removed]


def _is_receipt(row):
    return (row.get("role") == "user" and isinstance(row.get("content"), str)
            and row["content"].startswith(RECEIPT_MARKER + "\n"))


def recent_window(groups, token_budget, count_tokens=estimate, *, fits=None):
    """Keep a suffix of whole groups; the newest tool group gets fit priority."""
    recent, candidates = [], []
    for group in reversed(groups):
        if any(isinstance(row.get("content"), str) and row["content"].startswith(MARKER) for row in group):
            break
        candidates.append(group)
    candidates.reverse()
    for group in reversed(candidates):
        proposed = [*group, *recent]
        if count_tokens(proposed) > token_budget:
            break
        recent = proposed
    # The 25% allocation is a target, not permission to forget the current
    # code when the single summary request times out. Include any newer tail.
    latest_tool = next((i for i in range(len(candidates)-1, -1, -1)
                        if candidates[i][0].get("tool_calls") or _is_receipt(candidates[i][0])), len(candidates)-1)
    required = [row for group in candidates[latest_tool:] for row in group] if candidates else []
    if len(required) > len(recent) and fits:
        if fits(required):
            recent = required
        elif candidates and fits(candidates[latest_tool]):
            recent = list(candidates[latest_tool])
    return recent


def working_context(task, lane=""):
    saved = lane_state(task, lane)
    return {"stage": stage_of(task), "handoff": saved.get("summary", ""),
            "record_id": saved.get("record_id", ""), "record_path": saved.get("record_path", ""),
            "ticks_since_handoff": saved.get("ticks", 0), "quality": "normal",
            "instruction": "接续工作笔记和最近工作窗口继续执行当前任务；需要此前细节时可读取原始归档。"}


class TaskContinuity:
    def __init__(self, owner):
        self.owner = owner

    def directory(self, task):
        return self.owner.storage.task_memory_dir(task.umo, task.task_id) / "handoffs"

    def begin_round(self, task, lane=""):
        project_id = state_of(task).get("project_id")
        if project_id:
            project = self.owner.projects.project(project_id)
            if project.get("source_umo") == task.umo:
                state_of(task).setdefault("execution_settings", {})["continuity"] = {
                    **DEFAULTS, **project.get("execution_settings", {}).get("continuity", {})}
        saved = lane_state(task, lane)
        stage = stage_of(task)
        if saved.get("stage") and saved["stage"] != stage:
            saved["pending_reason"] = "stage_changed"
            saved.setdefault("previous_stage", saved["stage"])
        saved["stage"] = stage
        saved["ticks"] = int(saved.get("ticks", 0)) + 1
        # max_stage_ticks remains readable for existing settings/UI callers.
        # Ticks and routine plan revisions never initiate compaction.
        if saved.get("pending_reason") not in STAGE_REASONS:
            saved.pop("pending_reason", None)
        self.owner.storage.save_task(task)

    def read(self, task, record_id="", offset=0, limit=12000):
        directory = self.directory(task)
        if not record_id:
            index = directory / "index.json"
            if index.exists() and not self.owner.projects.safe_path(index):
                raise ValueError("交接索引路径无效。")
            return self.owner.storage._read_json(index) if index.exists() else {"records": []}
        if not re.fullmatch(r"handoff_[a-f0-9]+", record_id):
            raise ValueError("交接记录编号无效。")
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or not 500 <= limit <= 24000):
            raise ValueError("offset 需非负，limit 需在 500–24000 之间。")
        path = directory / f"{record_id}.json"
        if not path.exists() or path.is_symlink() or not self.owner.projects.safe_path(path):
            raise ValueError("当前任务没有这份交接记录。")
        record = self.owner.storage._read_json(path)
        text = json.dumps(record, ensure_ascii=False, indent=2)
        return {"record_id": record_id, "offset": offset, "text": text[offset:offset+limit],
                "next_offset": offset+limit if len(text) > offset+limit else None}

    def current_task(self, task, before):
        latest = self.owner.storage.load_active_task(task.umo)
        if not latest or guard(latest) != before or task.task_id in self.owner.projects.cleaning:
            raise HandoffError("整理期间任务状态发生变化，原历史已保留。")
        return latest

    async def summarize_chunk(self, event, task, provider, request, system_prompt, limit, record, path, before):
        """Legacy method signature; one whole-history call, no chunks/retries."""
        started = time.monotonic()
        text, usage, issue = "", None, ""
        record["model_calls"] = record.get("model_calls", 0) + 1
        try:
            response = await asyncio.wait_for(provider.text_chat(
                prompt=request, system_prompt=system_prompt, contexts=[], _agent_lab_handoff=True),
                timeout=SUMMARY_TIMEOUT_SECONDS)
            usage = getattr(response, "usage", None)
            text = self.owner._redact_known_secrets(str(response.completion_text or "").strip())
            issue = "empty" if not text else "too_long" if len(text) > limit else ""
        except asyncio.TimeoutError:
            issue = "timeout"
        except Exception as exc:
            # Keep the bridge's hard budget and stop signals authoritative.
            if type(exc).__name__ in {"BudgetStopped", "ExecutionStopped"}:
                raise
            issue = "provider_error"
        record["reported_tokens"] = int(getattr(usage, "total", 0) or 0)
        record["unreported_calls"] = int(usage is None)
        self.current_task(task, before)
        if issue:
            record["summary_issues"] = [{"reason": issue, "actual_chars": len(text), "limit": limit,
                                         "text": text, "elapsed_ms": int((time.monotonic()-started)*1000)}]
        record["summary_outcome"] = "truncated" if issue == "too_long" else "recent_window" if issue else "normal"
        return trim_summary(text, limit)

    async def compact(self, event, task, history, provider, reason, *, lane="", token_limit=None, count_tokens=None):
        """Archive the unchanged source before summarizing or replacing history."""
        groups = message_groups([row for row in history if row.get("role") not in {"system", "_checkpoint"}])
        if not groups:
            saved = lane_state(task, lane)
            saved.pop("pending_reason", None)
            saved["ticks"] = 1
            self.owner.storage.save_task(task)
            return history
        before = guard(task)
        cfg, saved = settings(task), lane_state(task, lane)
        if token_limit is None:
            token_limit = context_capacity(task, provider) * cfg["context_percent"] // 100
        record_id = new_id("handoff")
        path = self.directory(task) / f"{record_id}.json"
        record = {"record_id": record_id, "task_id": task.task_id, "lane": lane,
                  "stage": saved.get("previous_stage", saved.get("stage", stage_of(task))),
                  "next_stage": stage_of(task), "reason": reason, "created_at": now_iso(),
                  "status": "preparing", "plan_version": state_of(task).get("version"), "guard": before,
                  "previous_handoff": saved.get("summary", ""), "steps": deepcopy(state_of(task).get("steps", [])),
                  "history": deepcopy(history), "summary_limit": cfg["summary_chars"],
                  "raw_history_chars": len(json.dumps(history, ensure_ascii=False)),
                  "recent_budget_tokens": token_limit // 4, "model_calls": 0}
        try:
            # No secret filter or working-view transformation may alter this archive.
            self.owner.storage._write_json(path, record)
            saved.update(draft_record_id=record_id, pending_reason=reason)
            self.owner.storage.save_task(task)
        except OSError as exc:
            raise HandoffError("无法保存阶段原记录，原历史保留。") from exc
        try:
            state = state_of(task)
            materials = handoff_payloads(record["history"], state.get("journal", []), path,
                                         storage_root=self.owner.storage.root, approvals=task.approvals)
            groups = message_groups([row for row in materials if row.get("role") not in {"system", "_checkpoint"}])
            receipts = [row for row in materials if _is_receipt(row)]
            record["payload_receipts"] = deepcopy(receipts)
            record["material_chars"] = len(json.dumps(materials, ensure_ascii=False))
            request = json.dumps({"current_plan": {"goal": task.root_goal,
                                  "brief": "\n\n".join(dict.fromkeys(value for value in (
                                      getattr(task, "task_brief", ""), getattr(task, "entry_summary", "")) if value)),
                                  "completion_conditions": task.completion_conditions,
                                  "constraints": state.get("constraints", []), "steps": record["steps"],
                                  "current_step_id": state.get("current_step_id"), "next_action": task.next_step},
                                  "previous_handoff": record["previous_handoff"],
                                  "messages": summary_messages(materials)}, ensure_ascii=False)
            record["source_chars"] = len(request)
            system_prompt = ("生成接续当前任务的工作笔记，不执行工具。保留已改文件的真实路径、实际验证结果、"
                             "未完成项和下一步动作。用户要求和当前计划优先，不新增授权，不把未验证写成通过。"
                             f"只返回笔记正文，最多 {cfg['summary_chars']} 字符。")
            summary = await self.summarize_chunk(event, task, provider, request, system_prompt,
                                                 cfg["summary_chars"], record, path, before)
            latest = self.current_task(task, before)
            count = count_tokens or estimate
            fixed_cost = count([]) if count_tokens else 0
            context = working_context(latest, lane)
            context.update(record_id=record_id, record_path=str(path.relative_to(self.owner.storage.root)),
                           ticks_since_handoff=1)
            fixed = [row for row in history if row.get("role") == "system"]

            def handoff(note):
                return {"role": "user", "content": MARKER + "\n" + json.dumps({**context, "handoff": note}, ensure_ascii=False)}

            def continued(note, rows):
                return [*fixed, handoff(note), *rows]

            recent = recent_window(groups, record["recent_budget_tokens"],
                                   count_tokens=lambda rows: max(0, count(rows) - fixed_cost),
                                   fits=lambda rows: count(continued("", rows)) < token_limit)
            # Receipts use the same recent-window budget as other facts. Only
            # the latest working group has fit priority; pinning every old
            # receipt would create another ever-growing memory layer.
            # Small models still use the configured summary limit. Only actual
            # context space (including fixed prompts) can shorten the note.
            while recent and count(continued("", recent)) >= token_limit:
                recent = recent[len(message_groups(recent)[0]):]
            if count(continued("", recent)) >= token_limit:
                raise HandoffError("固定提示和操作事实已占满上下文容量，原历史已归档并保留。")
            if count(continued(summary, recent)) >= token_limit:
                record["generated_summary"] = summary
                low, high = 0, len(summary)
                while low < high:
                    middle = (low + high + 1) // 2
                    if count(continued(summary[:middle], recent)) < token_limit:
                        low = middle
                    else:
                        high = middle - 1
                summary = trim_summary(summary, low)
                record["context_summary_trimmed"] = True
            latest_tool = next((group[0] for group in reversed(groups)
                                if group[0].get("tool_calls") or _is_receipt(group[0])), None)
            retained = recent
            if not summary and (not retained or (latest_tool is not None and not any(row is latest_tool for row in retained))):
                record.update(status="blocked", summary="", summary_chars=0, block_reason="latest_group_exceeds_capacity")
                self.owner.storage._write_json(path, record)
                raise HandoffError("摘要为空，最近完整工作组无法放入上下文容量；原历史已归档并保留，未替换上下文。")
            record["recent_tokens"] = max(0, count(retained) - fixed_cost)
            record.update(status="saved", summary=summary, summary_chars=len(summary))
            self.owner.storage._write_json(path, record)
            index_path = self.directory(task) / "index.json"
            index = self.owner.storage._read_json(index_path) if index_path.exists() else {"records": []}
            index["records"].append({key: record[key] for key in ("record_id", "lane", "stage", "next_stage", "reason", "created_at")})
            self.owner.storage._write_json(index_path, index)
            lane_data = lane_state(latest, lane)
            lane_data.update(summary=summary, record_id=record_id, quality="normal",
                             record_path=str(path.relative_to(self.owner.storage.root)), ticks=1,
                             count=int(lane_data.get("count", 0))+1)
            for key in ("pending_reason", "previous_stage", "draft_record_id"):
                lane_data.pop(key, None)
            latest.add_log("stage_handoff", f"{record['stage']} → {record['next_stage']}: {reason}; {record_id}")
            record_handoff(latest, record)
            self.owner.storage.save_task(latest)
            write_task_line(self.owner, latest, event_id=record_id, event="handoff")
        except Exception as exc:
            latest = self.owner.storage.load_active_task(task.umo)
            if latest and latest.task_id == task.task_id and latest.status != "running":
                raise
            if type(exc).__name__ in {"BudgetStopped", "ExecutionStopped"} or isinstance(exc, HandoffError):
                raise
            raise HandoffError("阶段交接未保存成功，原历史已保留。") from exc
        return [handoff(summary), *deepcopy(retained)]


class StageContextManager:
    """Preserve the exact runner history until a capacity/stage boundary."""
    def __init__(self, continuity, event, task_id, provider, native_manager, *, lane="", prompt_tokens=0):
        self.continuity, self.event, self.task_id = continuity, event, task_id
        self.provider, self.native_manager, self.lane = provider, native_manager, lane
        self.prompt_tokens = prompt_tokens

    def __getattr__(self, name):
        return getattr(self.native_manager, name)

    def count_tokens(self, messages, trusted_token_usage=0):
        counter = getattr(self.native_manager, "token_counter", None)
        tokens = counter.count_tokens(messages, trusted_token_usage) if counter else (
            trusted_token_usage if trusted_token_usage > 0 else estimate([m.model_dump() for m in messages]))
        return tokens + self.prompt_tokens

    async def process(self, messages, trusted_token_usage=0):
        from astrbot.core.agent.message import Message

        owner = self.continuity.owner
        task = owner.storage.load_active_task(self.event.unified_msg_origin)
        if not task or task.task_id != self.task_id or task.status != "running":
            raise HandoffError("任务已经暂停、结束或切换，停止整理历史。")
        raw = [m.model_dump() for m in messages]
        cfg = settings(task)
        capacity = context_capacity(task, self.provider, self.native_manager)
        limit = capacity * cfg["context_percent"] // 100
        tokens = self.count_tokens(messages, trusted_token_usage)
        record_context(task, raw, raw, estimated_tokens=tokens, capacity_tokens=capacity, trigger_tokens=limit)
        saved = lane_state(task, self.lane)
        reason = saved.get("pending_reason", "")
        if reason not in STAGE_REASONS:
            reason = ""
            saved.pop("pending_reason", None)
        owner.storage.save_task(task)
        if not reason and tokens < limit:
            return messages
        if not any(row.get("role") not in {"system", "_checkpoint"} for row in raw):
            return messages
        reduced = await self.continuity.compact(self.event, task, raw, self.provider, reason or "context_capacity",
                                                 lane=self.lane, token_limit=limit,
                                                 count_tokens=lambda rows: self.count_tokens([Message.model_validate(row) for row in rows]))
        system = [m for m in messages if m.model_dump().get("role") == "system"]
        result = [*system, *[Message.model_validate(row) for row in reduced]]
        latest = owner.storage.load_active_task(task.umo)
        if latest and latest.task_id == task.task_id:
            record_context(latest, raw, [m.model_dump() for m in result], estimated_tokens=self.count_tokens(result),
                           capacity_tokens=capacity, trigger_tokens=limit)
            owner.storage.save_task(latest)
            write_task_line(owner, latest, event_id=lane_state(latest, self.lane).get("record_id", ""), event="handoff")
        return result
