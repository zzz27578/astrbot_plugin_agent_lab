"""Stage handoffs owned by Agent Lab, before any conversation is discarded.

The task ledger remains authoritative. Summaries are a bounded working view;
the original messages and stage evidence stay in independently readable files.
"""
from __future__ import annotations

import json
import re
import asyncio
import time
import hashlib

from .models import new_id, now_iso
from .context_views import history_view, state_summary
from .usage_metrics import record_context, record_handoff, write_task_line


DEFAULTS = {"max_stage_ticks": 8, "context_tokens": 1000000, "context_percent": 70, "summary_chars": 6000}
LIMITS = {"max_stage_ticks": (1, 1000), "context_tokens": (2000, 10000000),
          "context_percent": (30, 90), "summary_chars": (1000, 20000)}
MARKER = "[Agent Lab 阶段交接记录]"
SUMMARY_TIMEOUT_SECONDS = 30
MAX_WORKING_HISTORY_TOKENS = 24000


class HandoffError(Exception):
    pass


def state_of(task):
    return task.workflow_data.setdefault("task_control", {})


def settings(task):
    return {**DEFAULTS, **state_of(task).get("execution_settings", {}).get("continuity", {})}


def stage_of(task):
    state = state_of(task)
    step = next((s for s in state.get("steps", []) if s["id"] == state.get("current_step_id")), {})
    # Ungrouped checklist items share one execution stage. A two-call item is
    # a checkpoint, not automatically an expensive context handoff.
    return str(step.get("stage") or "task_execution")


def lane_state(task, lane=""):
    return state_of(task).setdefault("continuity", {}).setdefault("lanes", {}).setdefault(lane, {})


def guard(task):
    state = state_of(task)
    return [task.task_id, task.status, state.get("version"), state.get("input_revision", 0),
            state.get("human_paused", False), state.get("current_step_id")]


def estimate(messages):
    # Conservative fallback when a provider has no tokenizer/context limit.
    return max(1, len(json.dumps(messages, ensure_ascii=False, default=str).encode("utf-8")) // 3)


def bounded_text(text, tokens):
    """Bound a working view; the complete source stays in its archive."""
    if estimate(text) <= tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate(text[:middle]) <= tokens:
            low = middle
        else:
            high = middle - 1
    return text[:low] + "\n（完整计划保存在任务记录中。）"


def message_groups(history):
    """Keep assistant calls and *all* their results in the same unit."""
    groups, index = [], 0
    while index < len(history):
        row = history[index]
        if row.get("role") == "tool":
            raise HandoffError("发现未配对工具结果，请先核对任务记录，历史未整理。")
        group = [row]
        calls = row.get("tool_calls") or []
        index += 1
        if calls:
            while index < len(history) and history[index].get("role") == "tool":
                group.append(history[index])
                index += 1
            if {c["id"] for c in calls} != {r.get("tool_call_id") for r in group[1:]}:
                raise HandoffError("工具调用尚未完整返回，历史未整理。")
        groups.append(group)
    return groups


def working_context(task, lane=""):
    saved = lane_state(task, lane)
    return {"stage": stage_of(task), "handoff": saved.get("summary", ""),
            "record_id": saved.get("record_id", ""), "record_path": saved.get("record_path", ""),
            "ticks_since_handoff": saved.get("ticks", 0),
            "quality": saved.get("quality", "normal"),
            "instruction": ("交接摘要是线索，用户要求、当前计划和工具证据优先。需要细节时用 agent_lab_read_handoff 回查原记录，修改过的成果须重新验证。"
                            + ("本摘要降级，请先回查交接记录与相关证据再执行，不得据此宣称完成。" if saved.get("quality") == "degraded" else ""))}


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
            saved["previous_stage"] = saved["stage"]
        saved["stage"] = stage
        saved["ticks"] = int(saved.get("ticks", 0)) + 1
        if saved["ticks"] > settings(task)["max_stage_ticks"]:
            saved.setdefault("pending_reason", "stage_round_limit")
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

    async def summarize_chunk(self, event, task, provider, request, system_prompt, limit, record, path, before):
        """One correction only; an output length issue must not freeze a task."""
        original = request
        text = ""
        for attempt in range(2):
            started = time.monotonic()
            timed_out = False
            try:
                response = await asyncio.wait_for(provider.text_chat(prompt=request, system_prompt=system_prompt,
                                                 contexts=[], _agent_lab_handoff=True), timeout=SUMMARY_TIMEOUT_SECONDS)
                text = self.owner._redact_known_secrets(str(response.completion_text or "").strip())
                usage = getattr(response, "usage", None)
            except asyncio.TimeoutError:
                timed_out, text, usage = True, "", None
            record["model_calls"] = record.get("model_calls", 0)+1
            record["reported_tokens"] = record.get("reported_tokens", 0)+int(getattr(usage, "total", 0) or 0)
            record["unreported_calls"] = record.get("unreported_calls", 0)+int(usage is None)
            latest = self.owner.storage.load_active_task(task.umo)
            if not latest or guard(latest) != before or task.task_id in self.owner.projects.cleaning:
                raise HandoffError("总结期间任务状态发生变化，原记录已保留。")
            if text and len(text) <= limit:
                return text
            issue = "timeout" if timed_out else "empty" if not text else "too_long"
            record.setdefault("summary_issues", []).append({"cursor": record.get("cursor", 0), "attempt": attempt+1,
                "reason": issue, "actual_chars": len(text), "limit": limit, "text": text,
                "elapsed_ms": int((time.monotonic()-started)*1000)})
            record["last_invalid_summary"] = text
            self.owner.storage._write_json(path, record)
            if attempt == 0:
                if text:
                    # Previous calls were already bounded. Keep repair requests
                    # no larger than that source request, even for a bad model.
                    candidate = text[:max(limit, len(original)//2)]
                    request = json.dumps({"candidate": candidate,
                                          "instruction": f"上一摘要共{len(text)}字符，超过{limit}。只保留下一步所需的成果、未完成项、文件/证据ID，删除代码、历史复述和重复红线；压到{limit}字符内。"}, ensure_ascii=False)
                else:
                    request = original
                    system_prompt += "\n上次返回空正文。请直接给出简短交接事实，不要只输出思考或空内容。"
        # The complete source AND rejected output are already durable. Clearly
        # mark this working view as degraded, never invent completion or passes.
        record["quality"] = "degraded"
        candidate = text or record.get("summary") or state_summary(task)
        marker = "\n[摘要降级；完整原文见本交接记录。先按证据核对再继续，不视作验证通过。]"
        available = max(0, limit-len(marker))
        boundary = max(candidate.rfind("\n", available//2, available), candidate.rfind("。", available//2, available))
        return candidate[:boundary if boundary > 0 else available] + marker

    async def compact(self, event, task, history, provider, reason, *, lane="", token_limit=24000):
        """Commit raw history, then its model handoff, before returning less history."""
        from .task_control import prompt as plan_prompt

        groups = message_groups(history)
        if not groups:
            saved = lane_state(task, lane)
            saved.pop("pending_reason", None)
            saved["ticks"] = 1
            self.owner.storage.save_task(task)
            return history
        before = guard(task)
        cfg = settings(task)
        saved = lane_state(task, lane)
        draft_id = saved.get("draft_record_id", "")
        draft_path = self.directory(task) / f"{draft_id}.json"
        record = self.owner.storage._read_json(draft_path) if (re.fullmatch(r"handoff_[a-f0-9]+", draft_id)
                  and draft_path.exists() and self.owner.projects.safe_path(draft_path)) else {}
        previous_history = record.get("history", [])
        reusable = bool(record.get("status") == "preparing" and record.get("guard") == before
                        and history[:len(previous_history)] == previous_history)
        if not reusable:
            record = {"record_id": new_id("handoff"), "task_id": task.task_id, "lane": lane,
                      "stage": saved.get("previous_stage", saved.get("stage", stage_of(task))),
                      "next_stage": stage_of(task), "reason": reason, "created_at": now_iso(),
                      "status": "preparing", "plan_version": state_of(task).get("version"), "guard": before,
                      "previous_handoff": saved.get("summary", ""), "cursor": 0,
                      "steps": state_of(task).get("steps", [])}
        record_id = record["record_id"]
        path = self.directory(task) / f"{record_id}.json"
        record["history"] = history
        if record.get("source_format") != "evidence_index_v1":
            # A legacy cursor addressed raw JSON, not this new evidence view.
            if record.get("cursor") or record.get("summary"):
                record["legacy_progress"] = {"cursor": record.get("cursor", 0), "summary": record.get("summary", "")}
            record.update(cursor=0, summary="", source_format="evidence_index_v1")
        # The full source is durable even when the model or a later write fails.
        record = json.loads(self.owner._redact_known_secrets(json.dumps(record, ensure_ascii=False)))
        try:
            self.owner.storage._write_json(path, record)
            saved["draft_record_id"] = record_id
            saved["pending_reason"] = reason
            self.owner.storage.save_task(task)
        except OSError as exc:
            raise HandoffError("无法保存阶段原记录，历史未整理；请检查存储后恢复。") from exc
        try:
            # Summarize in bounded chunks instead of dropping the start of a big log.
            target = min(1600, 600 + 200*len(state_of(task).get("steps", [])))
            summary_chars = min(cfg["summary_chars"], max(256, token_limit // 6), max(800, target))
            source = json.dumps({"previous_handoff": record["previous_handoff"][:summary_chars],
                                 "messages": history_view(history, task, for_summary=True)}, ensure_ascii=False)
            record.update(source_chars=len(source), raw_history_chars=len(json.dumps(history, ensure_ascii=False)),
                          summary_limit=summary_chars)
            summary = record.get("summary", "")
            ledger = bounded_text(plan_prompt(task), max(128, token_limit // 4))
            start = record.get("cursor", 0)
            if start and record.get("source_prefix_sha256") != hashlib.sha256(source[:start].encode()).hexdigest():
                record["previous_progress"] = {"cursor": start, "summary": summary}
                record["source_restart_reason"] = "工作视图源发生变化，重新汇总，避免沿用旧游标跳过内容。"
                start, summary = 0, ""
                record.update(cursor=0, summary="")
            while start < len(source):
                system_prompt = ("你是 Agent Lab 的阶段交接记录员，不执行工具。只服务本任务的下一步，不写全程报告。当前计划和用户要求优先。"
                        "保留已改文件/证据ID、实际验证、尚未完成和接下来的具体动作；丢弃已过时细节与重复约束，代码和完整日志从原记录回查。"
                        "合并而不是追加旧摘要；不复述思考、加密签名和大段代码。不能把未完成写成完成，不能新增授权。"
                        f"仅返回交接正文，最多 {summary_chars} 字；不要写密钥或大段日志。")
                chunk_limit = min(24000, len(source) - start)
                while True:
                    request = json.dumps({"current_plan": ledger, "previous_chunk_summary": summary,
                                          "source_chunk": source[start:start+chunk_limit],
                                          "more_chunks": start+chunk_limit < len(source)}, ensure_ascii=False)
                    # Reserve space for the summary as well as the full request.
                    if estimate([system_prompt, request]) + summary_chars * 4 // 3 + 128 < token_limit:
                        break
                    if chunk_limit <= 1:
                        raise HandoffError("交接材料仍超过模型容量，原历史已保留；请提高容量或缩短摘要后继续。")
                    chunk_limit = max(1, chunk_limit // 2)
                summary = await self.summarize_chunk(event, task, provider, request, system_prompt,
                                                     summary_chars, record, path, before)
                latest = self.owner.storage.load_active_task(task.umo)
                if not latest or guard(latest) != before or latest.task_id in self.owner.projects.cleaning:
                    raise HandoffError("总结期间任务状态发生变化，已保留原历史，请从最新状态继续。")
                start = min(len(source), start+chunk_limit)
                record.update(summary=summary, cursor=start, source_prefix_sha256=hashlib.sha256(source[:start].encode()).hexdigest())
                self.owner.storage._write_json(path, record)
            record.update(status="saved", summary=summary, summary_chars=len(summary))
            self.owner.storage._write_json(path, record)
            index_path = self.directory(task) / "index.json"
            index = self.owner.storage._read_json(index_path) if index_path.exists() else {"records": []}
            index["records"].append({key: record[key] for key in ("record_id", "lane", "stage", "next_stage", "reason", "created_at")})
            self.owner.storage._write_json(index_path, index)
            latest = self.owner.storage.load_active_task(task.umo)
            if not latest or guard(latest) != before:
                raise HandoffError("任务已变化，原历史未整理。")
            lane_data = lane_state(latest, lane)
            lane_data.update(summary=summary, record_id=record_id,
                             quality=record.get("quality", "normal"),
                             record_path=str(path.relative_to(self.owner.storage.root)), ticks=1,
                             count=int(lane_data.get("count", 0))+1)
            lane_data.pop("pending_reason", None)
            lane_data.pop("previous_stage", None)
            lane_data.pop("draft_record_id", None)
            latest.add_log("stage_handoff", f"{record['stage']} → {record['next_stage']}: {reason}; {record_id}")
            record_handoff(latest, record)
            self.owner.storage.save_task(latest)
            write_task_line(self.owner, latest, event_id=record_id, event="handoff")
        except Exception as exc:
            # Budget/pause exceptions keep their original control meaning.
            latest = self.owner.storage.load_active_task(task.umo)
            if latest and latest.task_id == task.task_id and latest.status != "running":
                raise
            if type(exc).__name__ in {"BudgetStopped", "ExecutionStopped"}:
                raise
            if isinstance(exc, HandoffError):
                raise
            raise HandoffError("阶段交接未保存成功，原历史已保留；核对模型或存储后恢复任务。") from exc
        # Retain exact recent tool groups within a capacity budget, never by a
        # fixed number of messages. A single oversize group is in the archive.
        recent, used = [], 0
        recent_budget = max(256, min(token_limit // 6, MAX_WORKING_HISTORY_TOKENS // 6))
        candidates = groups
        if reason in {"stage_completed", "stage_changed", "plan_revised"}:
            # A new stage carries its current request, rather than replaying
            # the previous stage just because the model has ample capacity.
            start = next((i for i in range(len(groups)-1, -1, -1) if groups[i][0].get("role") == "user"), len(groups)-1)
            candidates = groups[start:]
        for group in reversed(candidates):
            if any(str(row.get("content", "")).startswith(MARKER) for row in group):
                break
            size = estimate(group)
            if used + size > recent_budget:
                break
            recent[0:0] = group
            used += size
        handoff = {"role": "user", "content": MARKER + "\n" + json.dumps(working_context(latest, lane), ensure_ascii=False)}
        return [handoff, *recent]


class StageContextManager:
    """Runner context manager with no native fallback that silently drops turns."""
    def __init__(self, continuity, event, task_id, provider, native_manager, *, lane="", prompt_tokens=0):
        self.continuity, self.event, self.task_id = continuity, event, task_id
        self.provider, self.native_manager, self.lane = provider, native_manager, lane
        self.prompt_tokens = prompt_tokens

    def __getattr__(self, name):
        return getattr(self.native_manager, name)

    async def process(self, messages, trusted_token_usage=0):
        from astrbot.core.agent.message import Message

        owner = self.continuity.owner
        task = owner.storage.load_active_task(self.event.unified_msg_origin)
        if not task or task.task_id != self.task_id or task.status != "running":
            raise HandoffError("任务已经暂停、结束或切换，停止整理历史。")
        raw = [m.model_dump() for m in messages]
        body = [m for m in raw if m.get("role") not in {"system", "_checkpoint"}]
        system = [m for m in raw if m.get("role") == "system"]
        native_limit = getattr(getattr(self.native_manager, "config", None), "max_context_tokens", 0)
        cfg = settings(task)
        capacity = cfg["context_tokens"]
        if native_limit and native_limit > 0:
            capacity = min(capacity, native_limit)
        limit = max(512, capacity * cfg["context_percent"] // 100)
        counter = getattr(self.native_manager, "token_counter", None)
        view = history_view(raw, task)
        view_messages = [Message.model_validate(row) for row in view]
        tokens = max(estimate(view), counter.count_tokens(view_messages, 0) if counter else 0) + self.prompt_tokens
        record_context(task, raw, view, estimated_tokens=tokens, capacity_tokens=capacity, trigger_tokens=limit)
        self.continuity.owner.storage.save_task(task)
        reason = lane_state(task, self.lane).get("pending_reason", "")
        body_view = [row for row in view if row.get("role") not in {"system", "_checkpoint"}]
        if not reason and estimate(body_view) >= max(2048, min(MAX_WORKING_HISTORY_TOKENS, limit//2)):
            reason = "working_history_limit"
        if not reason and tokens < limit:
            # Model-facing views are ephemeral. Keep raw messages in the runner
            # until a full source-backed handoff is committed.
            return messages
        reduced = await self.continuity.compact(self.event, task, body, self.provider, reason or "context_capacity",
                                                 lane=self.lane, token_limit=limit)
        if native_limit and estimate([*system, *reduced]) + self.prompt_tokens >= native_limit:
            raise HandoffError("交接已保存，但固定提示或最近结果仍超过模型上下文容量，请调整配置后继续。")
        latest = owner.storage.load_active_task(task.umo)
        if latest and latest.task_id == task.task_id:
            final_view = history_view([*system, *reduced], latest)
            record_context(latest, raw, final_view, estimated_tokens=estimate(final_view)+self.prompt_tokens,
                           capacity_tokens=capacity, trigger_tokens=limit)
            owner.storage.save_task(latest)
            write_task_line(owner, latest, event_id=lane_state(latest, self.lane).get("record_id", ""), event="handoff")
        return [Message.model_validate(row) for row in [*system, *reduced]]
