"""One bounded task stream for progress, questions, approvals and delivery."""
from __future__ import annotations

import asyncio
import hashlib
import time

from .identities import source_platform
from .models import now_iso
from .workspace_preferences import WorkspacePreferences


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
            return await self.publish(event, task_id, task.exit_summary or "任务已结束，记录已归档。", "delivery")
        pending = task.pending_approvals()
        questions = [q for q in state.get("questions", []) if q.get("status") == "pending"]
        if questions:
            q = questions[0]
            body = q["question"] + "\n" + "\n".join(f"{i+1}. {v}" for i, v in enumerate(q["options"]))
            body += f"\n建议：{q.get('recommendation') or '可自由回答'}\n/al answer {q['id']} <选项或自由回答>"
            return await self.publish(event, task_id, body, "question")
        if pending:
            # Keep actionable commands visible even for very large plans.
            r = pending[0]
            body = f"{r.operation[:300]}\n/al approve {r.approval_id}\n/al reject {r.approval_id}\n{r.reason[:700]}\n{r.impact[:2600]}"
            if len(r.impact) > 2600:
                body += "\n完整计划和影响请在任务详情中查看。"
            if r.rollback:
                body += "\n回滚：" + r.rollback[:500]
            if len(pending) > 1:
                body += f"\n另有{len(pending)-1}项待审批，处理后继续显示。"
            return await self.publish(event, task_id, body, "approval")
        if task.status != "running":
            return await self.publish(event, task_id, task.next_step or fallback or "任务已暂停，请核对记录后继续。", "status")
        steps = state.get("steps", [])
        step = next((s for s in steps if s.get("status") != "completed"), None)
        body = ("正在处理：" + step["title"]) if step else "正在核对成果与交付条件。"
        if task.last_confirmed_progress:
            body = "已确认：" + task.last_confirmed_progress[:240] + "\n" + body
        return await self.publish(event, task_id, body, "progress")

    def task(self, event, task_id):
        active = self.owner.storage.load_active_task(event.unified_msg_origin)
        return active if active and active.task_id == task_id else self.owner.projects.get_task(task_id)

    async def publish(self, event, task_id, text, kind="progress"):
        if kind not in {"progress", "question", "approval", "delivery", "status"}:
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
            body = self.owner._redact_known_secrets(str(text or "").strip())[:600 if optional else 4500]
            if not body:
                raise ValueError("任务消息不能为空。")
            path = self.owner.storage.task_memory_dir(task.umo, task_id) / "messages.json"
            stream = self.owner.storage._read_json(path) if path.exists() else {"messages": [], "delivery": {}}
            delivery = stream["delivery"]
            digest = hashlib.sha256((kind + body).encode()).hexdigest()
            if delivery.get("fingerprint") == digest:
                return "相同消息已处理，未重复发送。"
            now = self.clock()
            if optional and (now - delivery.get("last_progress_at", 0) < settings["min_interval_seconds"]
                             or delivery.get("progress_count", 0) >= 80):
                stream["pending_progress"] = body
                self.owner.storage._write_json(path, stream)
                return "简报已合并到任务进度，等待下一执行事件满足发送间隔。"
            if optional:
                pending = stream.pop("pending_progress", "")
                if pending and pending != body:
                    body = (pending[:260] + "\n" + body)[:600]
                    digest = hashlib.sha256((kind + body).encode()).hexdigest()
            label = {"progress": "进展", "question": "需要回答", "approval": "需要审批",
                     "delivery": "交付", "status": "状态"}[kind]
            row = {"kind": kind, "text": body, "time": now_iso(), "status": "sending", "id": digest[:16]}
            stream["messages"].append(row)
            stream["messages"] = stream["messages"][-80:]
            delivery["fingerprint"] = digest
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
