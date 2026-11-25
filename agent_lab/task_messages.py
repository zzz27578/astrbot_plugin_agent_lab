"""One bounded task stream for progress, questions, approvals and delivery."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

from .identities import source_platform
from .models import now_iso
from .workspace_preferences import WorkspacePreferences
from .usage_metrics import write_task_line


class TaskMessages:
    def __init__(self, owner, send=None, clock=time.time):
        self.owner, self.clock = owner, clock
        self.send = send or self._send
        self.preferences = WorkspacePreferences(owner.storage)
        self.locks = {}

    async def _send(self, umo, text):
        from astrbot.core.message.message_event_result import MessageChain
        # AstrBot 4.29.4 only persists proactive GROUP messages in history.
        # publish() restricts this channel to the original private admin UMO;
        # no event.request_llm or conversation-manager write is performed.
        delivered = await self.owner.context.send_message(umo, MessageChain().message(text))
        if delivered is False:
            raise RuntimeError("Platform delivery not confirmed")

    async def state(self, event, task_id, fallback=""):
        try:
            return await self._state(event, task_id, fallback)
        except (OSError, ValueError, PermissionError):
            return "消息来源或任务记录不可用，执行控制不受简报影响。"

    async def _state(self, event, task_id, fallback=""):
        task = self.task(event, task_id)
        state = task.workflow_data.get("task_control", {})
        if task.status in {"completed", "cancelled"}:
            if task.workflow_data.get("usage_metrics"):
                write_task_line(self.owner, task, event_id="terminal", event="archive")
            return await self.publish(event, task_id, task.workflow_data.get("delivery_message") or task.exit_summary or "", "delivery")
        pending = task.pending_approvals()
        questions = [q for q in state.get("questions", []) if q.get("status") == "pending"]
        if questions:
            q = questions[0]
            body = q["question"] + "\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(q["options"]))
            if q.get("recommendation"):
                body += "\n" + q["recommendation"]
            return await self.publish(event, task_id, body, "question")
        if pending:
            r = pending[0]
            row = next(a for a in task.approvals if a["approval_id"] == r.approval_id)
            body = await self.approval_summary(task, row)
            latest = self.owner.storage.load_active_task(task.umo)
            if not latest or latest.task_id != task_id or not any(a.approval_id == r.approval_id for a in latest.pending_approvals()):
                return "审批已经结束或变化。"
            return await self.publish(event, task_id, body, "approval")
        if task.status != "running":
            self.record_local(task, {"reason": task.wait.wait_reason or "paused", "detail": task.wait.message or task.watchdog.paused_reason or fallback,
                                     "resume_command": task.wait.resume_command}, "warning")
            key = "stalled" if task.wait.wait_reason in {"guard_retry_limit","blocked_by_error","no_progress","stalled"} else "budget" if task.wait.wait_reason=="budget_exhausted" else "error" if task.wait.wait_reason in {"handoff_failed","tool_timeout","runtime_timeout"} else "paused"
            notice=state.get("notifications",{}).get(key) or state.get("notifications",{}).get("paused")
            if notice:
                return await self.publish(event,task_id,notice,"status")
            return await self.publish(event,task_id,"","status")
        notices = [n for n in state.get("scope_notices", []) if not n.get("sent")]
        if notices:
            self.record_local(task, {"reason": "scope_notice", "paths": [n["path"] for n in notices[:5]]}, "warning")
            latest = self.owner.storage.load_active_task(task.umo)
            if latest and latest.task_id == task_id:
                for n in latest.workflow_data.get("task_control", {}).get("scope_notices", []):
                    if n in notices:n["sent"] = True
                self.owner.storage.save_task(latest)
        cap = task.budget.max_total_tokens
        if cap and task.budget.tokens_used * 100 >= cap * 80:
            self.record_local(task, {"reason":"budget_warning", "used_tokens":task.budget.tokens_used,"limit":cap}, "warning")
            if state.get("notifications",{}).get("budget"):
                await self.publish(event,task_id,state["notifications"]["budget"],"budget")
        # Optional progress comes directly from agent_lab_progress/checkpoint.
        # Repeated status checks must not manufacture more text or API requests.
        return "状态已记录；阶段交付或进展由 Bot 主动提交。"

    async def approval_summary(self, task, row):
        """The acting Bot is the author. Never rewrite or call another model."""
        message = str(row.get("message") or "").strip()
        if message:
            return self.owner._redact_known_secrets(message)
        # Legacy records have separate Bot-authored fields. Join their exact
        # values; do not generate a persona, boilerplate or approval by inference.
        parts = []
        keys=("impact",) if row.get("approval_type")=="task_plan" else ("operation", "reason", "impact", "rollback")
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value and value not in parts:parts.append(value)
        return self.owner._redact_known_secrets("\n".join(parts))

    def record_local(self, task, payload, kind="warning"):
        if task.task_id in self.owner.projects.cleaning or not self.owner.storage.task_path(task.umo,task.task_id).exists():
            return
        body=self.owner._redact_known_secrets(json.dumps(payload,ensure_ascii=False,default=str))[:3000]
        path=self.owner.storage.task_memory_dir(task.umo,task.task_id)/"messages.json"
        stream=self.owner.storage._read_json(path) if path.exists() else {"messages":[],"delivery":{}}
        digest=hashlib.sha256((kind+body).encode()).hexdigest()[:16]
        if any(row.get("id")==digest for row in stream["messages"]):return
        stream["messages"]=[*stream["messages"],{"kind":kind,"status":"recorded","text":body,"chars":len(body),"time":now_iso(),"id":digest}][-100:]
        self.owner.storage._write_json(path,stream)

    def task(self, event, task_id):
        active = self.owner.storage.load_active_task(event.unified_msg_origin)
        return active if active and active.task_id == task_id else self.owner.projects.get_task(task_id)

    async def publish(self, event, task_id, text, kind="progress"):
        if kind not in {"progress", "question", "approval", "delivery", "status", "scope", "budget", "stage"}:
            raise ValueError("未知任务消息类型。")
        self.owner._require_task_access(event)
        if ":FriendMessage:" not in event.unified_msg_origin:
            return "该来源不支持管理员私聊简报。"
        async with self.locks.setdefault(task_id, asyncio.Lock()):
            task = self.task(event, task_id)
            if task.umo != event.unified_msg_origin:
                raise PermissionError("任务消息只能发送到原管理员会话。")
            state = task.workflow_data.setdefault("task_control", {})
            if state.get("owner_id") and str(event.get_sender_id()) != str(state["owner_id"]):
                raise PermissionError("任务消息接收者必须是立项管理员。")
            settings = self.preferences.progress(source_platform(task.umo))
            optional = kind == "progress"
            if optional and not settings["enabled"]:
                return "进展简报未开启；任务内记录照常保存。"
            if optional and task.status in {"completed", "cancelled"}:
                return "任务已结束，不再发送进展简报。"
            body = self.owner._redact_known_secrets(str(text or "").strip())
            if len(body) > (600 if optional else 2000):
                self.record_local(task, {"reason":"message_too_long", "kind":kind,"chars":len(body),"limit":600 if optional else 2000}, "warning")
                return "正文过长，已保留任务原记录；请 Bot 自拟2000字符以内的对外文案。未截断或改写发送。"
            if not body and kind != "status":
                raise ValueError("任务消息不能为空。")
            path = self.owner.storage.task_memory_dir(task.umo, task_id) / "messages.json"
            stream = self.owner.storage._read_json(path) if path.exists() else {"messages": [], "delivery": {}}
            delivery = stream["delivery"]
            digest = hashlib.sha256((kind + body + (task.wait.wait_reason if kind=="status" else "")).encode()).hexdigest()
            if delivery.get("fingerprint") == digest:
                return "相同消息已处理，未重复发送。"
            if kind == "budget" and delivery.get("budget_warned") == task.budget.max_total_tokens:
                return "当前预算已提醒。"
            now = self.clock()
            if optional and (now - delivery.get("last_progress_at", 0) < settings["min_interval_seconds"]
                             or delivery.get("progress_count", 0) >= 80):
                stream["pending_progress"] = body
                self.owner.storage._write_json(path, stream)
                return "简报已合并到任务进度，等待下一执行事件满足发送间隔。"
            if optional:
                pending = stream.pop("pending_progress", "")
                # New Bot prose supersedes earlier deferred progress. Never
                # splice/truncate two separately authored messages into one.
            label = {"progress": "进展", "question": "需要回答", "approval": "需要审批",
                     "delivery": "交付", "stage": "阶段交付", "status": "状态", "scope": "范围提醒", "budget": "预算"}[kind]
            if kind=="status" and not body:
                label="需处理 · "+str(task.wait.wait_reason or task.status)
            row = {"kind": kind, "text": body, "chars": len(body), "time": now_iso(), "status": "sending", "id": digest[:16]}
            stream["messages"].append(row)
            stream["messages"] = stream["messages"][-80:]
            delivery["fingerprint"] = digest
            if kind == "budget":
                delivery["budget_warned"] = task.budget.max_total_tokens
            if optional:
                delivery["last_progress_at"] = now
                delivery["progress_count"] = delivery.get("progress_count", 0) + 1
            self.owner.storage._write_json(path, stream)
            error = ""
            try:
                await asyncio.wait_for(self.send(task.umo, f"[任务 {task.task_id} · {label}]\n{body}"), 3 if optional else 10)
            except Exception as exc:
                error = type(exc).__name__
            # Separate journal: never overwrite task checkpoints/terminal state.
            # Cleanup may have removed the task while transport was pending.
            if not path.exists():
                return "消息已处理，记录已被管理员清理。"
            stream = self.owner.storage._read_json(path)
            current = next((r for r in reversed(stream["messages"]) if r["id"] == row["id"] and r["time"] == row["time"]), None)
            if current:
                current["status"] = "failed" if error else "sent"
                if error:
                    current["error"] = error
                self.owner.storage._write_json(path, stream)
            return "发送未确认，已记录；不会自动重发未知结果。" if error else "已发送任务消息。"
