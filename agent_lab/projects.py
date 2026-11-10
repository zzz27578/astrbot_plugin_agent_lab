"""Project/task catalog, filtered summaries and transparent managed storage.

This module never deletes development workspaces. Cleanup is a two-phase plan
over plugin-owned files and exact native task conversation IDs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .models import TaskState, new_id, now_iso
from .task_control import control
from .identities import source_platform


TERMINAL = {"completed", "cancelled"}


def file_size(path):
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


class Projects:
    def __init__(self, owner):
        self.owner, self.storage = owner, owner.storage
        self.root = self.storage.root / "projects"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root / "index.json"
        self.lock = asyncio.Lock()
        self.selection = {}
        self.cleaning = set()
        self.cleaning_projects = set()
        self.creation_locks = {}

    def index(self):
        if not self.index_path.exists():
            return {"version": 1, "projects": [], "tasks": {}, "selected": {}}
        return self.storage._read_json(self.index_path)

    def write(self, data):
        self.storage._write_json(self.index_path, data)

    def project(self, project_id):
        row = next((p for p in self.index()["projects"] if p["project_id"] == project_id), None)
        if row is None:
            raise ValueError("项目不存在或已删除。")
        return row

    def summary_path(self, project_id):
        if not re.fullmatch(r"project_[a-f0-9]+", project_id):
            raise ValueError("项目编号无效。")
        return self.root / project_id / "SUMMARY.md"

    def create(self, title, category="项目", source_umo="", owner_id="", platform_id=""):
        title = str(title).strip()
        if not title or len(title) > 100:
            raise ValueError("项目名称需要1–100字符。")
        data = self.index()
        platform_id = source_platform(source_umo) or str(platform_id or "")
        existing = next((p for p in data["projects"] if p["title"] == title and p.get("source_umo") == source_umo
                         and (source_platform(p.get("source_umo")) or p.get("platform_id", "")) == platform_id), None)
        if existing:
            return existing
        row = {"project_id": new_id("project"), "title": title, "category": str(category or "项目")[:40],
               "source_umo": source_umo, "platform_id": platform_id, "owner_id": owner_id, "created_at": now_iso(), "updated_at": now_iso(),
               "summary": "", "share_with_daily": False, "workflow_ids": []}
        data["projects"].append(row)
        self.write(data)
        self.summary_path(row["project_id"]).parent.mkdir(parents=True, exist_ok=True)
        return row

    def update(self, project_id, payload):
        if project_id in self.cleaning_projects: raise ValueError("项目正在清理，请稍后修改。")
        data = self.index()
        row = next((p for p in data["projects"] if p["project_id"] == project_id), None)
        if not row:
            raise ValueError("项目不存在。")
        for key in ("title", "category"):
            if key in payload:
                text = str(payload[key]).strip()
                if not text: raise ValueError("名称和分类不能为空。")
                row[key] = text[:100]
        if "workflow_ids" in payload:
            valid = {spec.agent_id for spec in self.storage.list_agents()}
            ids = payload["workflow_ids"]
            if not isinstance(ids, list) or any(value not in valid for value in ids):
                raise ValueError("请选择存在的方案。")
            row["workflow_ids"] = list(dict.fromkeys(ids))
        if "share_with_daily" in payload:
            row["share_with_daily"] = bool(payload["share_with_daily"])
        row["updated_at"] = now_iso()
        self.write(data)
        return row

    def select(self, umo, project_id):
        row = self.project(project_id)
        if row.get("source_umo") and row["source_umo"] != umo:
            raise ValueError("该项目属于其他会话来源，请在对应会话中选择。")
        if row.get("platform_id") and row["platform_id"] != source_platform(umo):
            raise ValueError("该项目属于另一机器人实例，不能从当前 Bot 选择。")
        data = self.index()
        data["selected"][umo] = project_id
        self.write(data)
        return row

    def attach(self, task, project_id="", title="", category="项目"):
        if task.task_id in self.cleaning: raise ValueError("任务正在清理，请稍后整理归属。")
        data = self.index()
        project_id = project_id or data.get("selected", {}).get(task.umo, "")
        if title:
            row = self.create(title, category, task.umo, control(task).get("owner_id", ""))
            project_id = row["project_id"]
        if not project_id:
            row = self.create("未分类", "待整理", task.umo, control(task).get("owner_id", ""))
            project_id = row["project_id"]
        row = self.project(project_id)
        if project_id in self.cleaning_projects: raise ValueError("项目正在清理，请稍后添加任务。")
        if row.get("platform_id") and row["platform_id"] != source_platform(task.umo):
            raise ValueError("项目的机器人实例与任务来源不一致。")
        if row.get("source_umo") and row["source_umo"] != task.umo:
            raise ValueError("项目和任务来源不一致。")
        data = self.index()
        prior_project_id = data["tasks"].get(task.task_id, {}).get("project_id")
        if not row.get("source_umo"):
            for project in data["projects"]:
                if project["project_id"] == project_id:
                    project.update(source_umo=task.umo, platform_id=source_platform(task.umo), owner_id=control(task).get("owner_id", ""), updated_at=now_iso())
        control(task)["project_id"] = project_id
        data["tasks"][task.task_id] = {"project_id": project_id, "umo": task.umo}
        data["selected"][task.umo] = project_id
        self.write(data)
        if prior_project_id and prior_project_id != project_id:
            old_summary = self.summary_path(prior_project_id).parent / f"{task.task_id}.summary.md"
            if old_summary.exists() and self.safe_path(old_summary):
                self.storage._write_text(self.summary_path(project_id).parent / old_summary.name, old_summary.read_text(encoding="utf-8"))
                old_summary.unlink()
            data = self.index()
            for old in data["projects"]:
                if old["project_id"] == prior_project_id and old.get("summary_source_task_id") == task.task_id:
                    old.update(summary="", summary_source_task_id="", updated_at=now_iso())
                    self.summary_path(prior_project_id).unlink(missing_ok=True)
            self.write(data)
        return row

    def all_tasks(self):
        rows = {}
        # Canonical task files include paused tasks switched away from active.
        for base in (self.storage.sessions_dir, self.storage.archives_dir):
            for path in base.glob("*/task_*.json"):
                if path.is_symlink(): continue
                try:
                    task = TaskState.from_dict(self.storage._read_json(path))
                    if re.fullmatch(r"task_[a-f0-9]+", task.task_id):
                        rows[task.task_id] = task
                except (ValueError, OSError, TypeError):
                    continue
        for task in self.storage.list_tasks():
            rows[task.task_id] = task
        return rows

    def get_task(self, task_id):
        task = self.all_tasks().get(task_id)
        if not task:
            raise ValueError("任务不存在或已删除。")
        return task

    def import_legacy(self):
        # One-time cataloging only; original files, plans and workflows stay put.
        for task in self.all_tasks().values():
            if self.storage.ended_path(task.task_id).exists() and task.status not in TERMINAL:
                fence = self.storage._read_json(self.storage.ended_path(task.task_id))
                task.status = fence.get("status", "cancelled")
                task.finished_at = fence.get("time") or now_iso()
                task.exit_summary = task.exit_summary or "管理员已结束该任务，重启后补全归档；未验证事项保留原记录。"
                control(task).update(automatic=False, human_paused=True)
                self.storage.archive_task(task, administrator=True)
            if task.task_id not in self.index()["tasks"]:
                self.attach(task)
                self.storage.save_task(task, active=False)

    def assert_source(self, task, event):
        self.owner._require_task_access(event)
        if task.umo != event.unified_msg_origin:
            raise ValueError("请在任务的原会话中操作，避免把其他会话资料带入当前聊天。")

    async def pause_execution(self, task):
        current = self.storage.load_active_task(task.umo)
        if current and current.task_id == task.task_id:
            current.status = "paused"
            control(current)["human_paused"] = True
            self.storage.save_task(current)
        operation = self.owner.task_control.running.get(task.umo) if current and current.task_id == task.task_id else None
        if operation and operation is not asyncio.current_task():
            operation.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(operation), 5)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
        task = self.get_task(task.task_id)
        task.status = "paused" if task.status not in TERMINAL else task.status
        control(task)["human_paused"] = True
        for row in control(task).get("journal", []):
            if row.get("status") == "started": row["status"] = "unknown"
        self.storage.save_task(task, active=bool(current and current.task_id == task.task_id))
        return task

    async def activate(self, task_id, event):
        async with self.lock:
            task = self.get_task(task_id)
            self.assert_source(task, event)
            if task.status in TERMINAL:
                raise ValueError("已结束任务只读；请在同一项目新建任务。")
            current = self.storage.load_active_task(task.umo)
            if current and current.task_id != task.task_id:
                await self.pause_execution(current)
                if f"{current.umo}:{current.task_id}" in self.owner._running_ticks:
                    raise ValueError("上一任务正在收尾，已暂停派发。请稍后再切换。")
            task = self.get_task(task_id)
            task.status = "paused"
            control(task)["human_paused"] = True
            # Explicit selection is the only path allowed to replace the pointer.
            self.storage.save_task(task, active=False)
            self.storage._write_json(self.storage.active_task_path(task.umo), task.to_dict())
            self.select(task.umo, control(task).get("project_id") or self.index()["tasks"][task_id]["project_id"])
            return task

    async def administrator_end(self, task_id, status, summary, actor):
        if status not in TERMINAL: raise ValueError("请选择交付或停止。")
        task = self.get_task(task_id)
        if task.status in TERMINAL:
            return task
        # The stop fence is written before waiting for any task/cleanup lock.
        self.storage.mark_ended(task, status, actor)
        async with self.lock:
            task = await self.pause_execution(task)
            missing = [step.get("title") for step in control(task).get("steps", []) if step.get("status") != "completed"]
            for item in task.approvals:
                if item.get("status") in {"pending", "approved"}: item["status"] = "expired"
            state = control(task)
            state.update(human_paused=True, automatic=False, phase="ended",
                         administrator_decision={"actor": actor, "status": status, "time": now_iso(), "unfinished_steps": missing})
            task.status, task.finished_at = status, now_iso()
            task.exit_summary = str(summary or task.last_confirmed_progress or task.current_summary or "管理员结束任务。")[:12000]
            if missing:
                task.exit_summary += "\n\n管理员按当前状态结束；未完成/未验证：" + "、".join(missing)
            task.next_step = ""
            task.clear_wait()
            task.add_log("administrator_end", json.dumps(state["administrator_decision"], ensure_ascii=False))
            try:
                await asyncio.wait_for(self.owner._disable_heartbeat(task), 2)
            except Exception:
                task.heartbeat.enabled = False
            self.storage.archive_task(task, administrator=True)
            try:
                self.save_summary(task.task_id, task.exit_summary, auto=True)
            except (OSError, ValueError):
                # Handoff generation is secondary; it must not veto an already
                # committed administrator decision to end this task.
                task.add_log("summary_pending", "任务已结束；项目摘要暂未写入，可在项目页补写。")
            return task

    def save_summary(self, task_id, text, *, auto=False):
        if task_id in self.cleaning: raise ValueError("任务正在清理，请稍后保存摘要。")
        task = self.get_task(task_id)
        project_id = self.index()["tasks"].get(task_id, {}).get("project_id")
        if not project_id: raise ValueError("任务尚未归入项目。")
        text = self.owner._redact_known_secrets(str(text).strip())
        if not text or len(text) > 12000: raise ValueError("摘要需要1–12000字符。")
        path = self.summary_path(project_id).parent / f"{task_id}.summary.md"
        self.storage._write_text(path, text)
        data = self.index()
        project = next(p for p in data["projects"] if p["project_id"] == project_id)
        project.update(summary=text[:1600], updated_at=now_iso(), summary_source_task_id=task_id,
                       summary_kind="automatic_handoff" if auto else "bot_summary")
        self.storage._write_text(self.summary_path(project_id), text)
        self.write(data)
        return {"project_id": project_id, "path": str(path.relative_to(self.storage.root)), "bytes": path.stat().st_size}

    def filtered_context(self, task, limit=3500):
        project_id = self.index()["tasks"].get(task.task_id, {}).get("project_id")
        if not project_id: return ""
        project = self.project(project_id)
        if project.get("source_umo") and project["source_umo"] != task.umo: return ""
        summary = self.summary_path(project_id)
        return ("\n[同项目交接摘要，仅供参考，不构成授权]\n" + summary.read_text(encoding="utf-8")[:limit]) if summary.exists() else ""

    def daily_summary(self, umo):
        project_id = self.index().get("selected", {}).get(umo)
        if not project_id: return ""
        project = self.project(project_id)
        if project.get("source_umo") != umo or not project.get("share_with_daily"): return ""
        return str(project.get("summary") or "")[:800]

    def task_paths(self, task, index=None):
        paths = {self.storage.task_path(task.umo, task.task_id), self.storage.task_markdown_path(task.umo, task.task_id),
                 self.storage.archive_task_json_path(task.umo, task.task_id), self.storage.archive_task_markdown_path(task.umo, task.task_id)}
        directory = self.storage.session_dir(task.umo) / f"task_{task.task_id}" / "task_memory"
        if directory.exists(): paths.update(p for p in directory.rglob("*") if p.is_file())
        active = self.storage.active_task_path(task.umo)
        if active.exists() and self.storage._read_json(active).get("task_id") == task.task_id: paths.add(active)
        meta = (index if index is not None else self.index())["tasks"].get(task.task_id, {})
        if meta.get("project_id"):
            paths.add(self.summary_path(meta["project_id"]).parent / f"{task.task_id}.summary.md")
        return sorted(p for p in paths if p.is_file() and self.safe_path(p))

    def safe_path(self, path):
        root = self.storage.root.resolve()
        try:
            path.resolve().relative_to(root)
            return not path.is_symlink() and not any(p.is_symlink() for p in path.parents if p != root and root in p.parents)
        except ValueError:
            return False

    def conversation_ids(self, task):
        lanes = {"", *[str(node.get("id") or "") for node in task.profile_snapshot.get("agent", {}).get("workflow_nodes", [])]}
        return {str(uuid5(NAMESPACE_URL, "agent-lab:" + task.task_id + ":" + lane)) for lane in lanes}

    def catalog(self):
        data = self.index()
        tasks = self.all_tasks()
        active_ids = {umo: (active.task_id if (active := self.storage.load_active_task(umo)) else "") for umo in {t.umo for t in tasks.values()}}
        rows = []
        for project in data["projects"]:
            children = []
            for task_id, meta in data["tasks"].items():
                if meta["project_id"] != project["project_id"] or task_id not in tasks: continue
                task = tasks[task_id]
                paths = self.task_paths(task, data)
                cache = sum(file_size(p) for p in paths if p.suffix == ".jsonl")
                children.append({"task_id": task_id, "umo": task.umo, "title": task.root_goal[:160], "status": task.status,
                    "updated_at": task.updated_at, "summary": (task.exit_summary or task.current_summary)[:350],
                    "bytes": sum(file_size(p) for p in paths), "cache_bytes": cache,
                    "selected": active_ids.get(task.umo) == task_id,
                    "question_count": len([q for q in control(task).get("questions", []) if q.get("status") == "pending"])})
            summary = self.summary_path(project["project_id"])
            summary_bytes = file_size(summary)
            rows.append({**project, "platform_id": source_platform(project.get("source_umo")) or project.get("platform_id", ""),
                "tasks": sorted(children, key=lambda t:t["updated_at"], reverse=True),
                "bytes": sum(t["bytes"] for t in children) + summary_bytes, "cache_bytes": sum(t["cache_bytes"] for t in children),
                "summary_bytes": summary_bytes, "storage_path": str(summary.parent.relative_to(self.storage.root))})
        fence_bytes = sum(file_size(p) for p in (self.storage.root / "ended").glob("*.json"))
        shared_bytes = sum(file_size(p) for p in [self.index_path, self.storage.memory_entries_path, self.owner.pattern_library.path]) + fence_bytes
        return {"projects": rows, "selected": data.get("selected", {}), "total_bytes": sum(p["bytes"] for p in rows) + shared_bytes,
                "shared_metadata_bytes": shared_bytes,
                "terminal_marker_bytes": fence_bytes,
                "cache_bytes": sum(p["cache_bytes"] for p in rows), "native_history_accounting": "在任务详情和清理预览中按UTF-8内容计算；不代表数据库文件可收缩字节数"}

    async def detail(self, task_id):
        task = self.get_task(task_id)
        native_bytes = 0
        for cid in self.conversation_ids(task):
            conversation = await self.owner.context.conversation_manager.db.get_conversation_by_id(cid)
            if conversation and conversation.user_id == task.umo:
                raw = json.dumps(conversation.content, ensure_ascii=False, default=str) if hasattr(conversation, "content") else str(conversation.history or "")
                native_bytes += len(raw.encode("utf-8"))
        # Existing manager serializes DB content reliably; storage size is content,
        # not SQLite allocated pages (which cannot be attributed per conversation).
        paths = self.task_paths(task)
        return {"task": task.to_dict(), "native_history_bytes": native_bytes,
                "files": [{"path": str(p.relative_to(self.storage.root)), "bytes": file_size(p)} for p in paths],
                "record_bytes": sum(file_size(p) for p in paths)}

    async def cleanup_plan(self, project_id, task_id="", mode="cache"):
        if mode not in {"cache", "history", "project"}: raise ValueError("未知清理类型。")
        self.project(project_id)
        index = self.index()
        ids = [key for key, meta in index["tasks"].items() if meta["project_id"] == project_id and (not task_id or key == task_id)]
        tasks = self.all_tasks()
        affected = [tasks[key] for key in ids if key in tasks]
        if task_id and not affected: raise ValueError("所选任务不属于此项目。")
        if any(t.status == "running" or f"{t.umo}:{t.task_id}" in self.owner._running_ticks or
               (t.umo in self.owner.task_control.running and (active := self.storage.load_active_task(t.umo)) and active.task_id == t.task_id)
               for t in affected):
            raise ValueError("请先暂停此项目的运行任务，等待当前调用收尾后再清理。")
        paths, native, state_versions = [], [], []
        for task in affected:
            state_versions.append([task.task_id, task.updated_at, task.status,
                hashlib.sha256(json.dumps(task.to_dict(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()])
            candidates = self.task_paths(task)
            paths.extend(p for p in candidates if mode != "cache" or p.suffix == ".jsonl")
            for cid in self.conversation_ids(task):
                conv = await self.owner.context.conversation_manager.db.get_conversation_by_id(cid)
                if conv and conv.user_id == task.umo:
                    raw = json.dumps(conv.content, ensure_ascii=False, default=str) if hasattr(conv, "content") else str(conv.history or "")
                    native.append({"cid": cid, "umo": task.umo, "bytes": len(raw.encode()), "digest": hashlib.sha256(raw.encode()).hexdigest()})
        if mode == "project":
            summary = self.summary_path(project_id)
            if summary.exists(): paths.append(summary)
        files = [{"path": str(p.relative_to(self.storage.root)), "bytes": p.stat().st_size, "mtime": p.stat().st_mtime_ns} for p in sorted(set(paths))]
        legacy_memory = [item for item in self.storage.list_memory_entries() if item.get("source_task_id") in ids]
        related_patterns = [item for item in self.owner.pattern_library.list_patterns(status="all")
                            if item.get("source_task_id") in ids or any(source.get("task_id") in ids for source in (item.get("evidence") or {}).get("source_tasks", []))]
        plan = {"project_id": project_id, "task_id": task_id, "mode": mode, "task_ids": ids,
                "files": files, "native": native, "state_versions": state_versions,
                "bytes": sum(p["bytes"] for p in files), "native_history_bytes": sum(p["bytes"] for p in native),
                "memory_entries": len(legacy_memory), "memory_digest": hashlib.sha256(json.dumps(legacy_memory, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "learned_patterns": len(related_patterns), "pattern_digest": hashlib.sha256(json.dumps(related_patterns, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "project_revision": hashlib.sha256(json.dumps(self.project(project_id), sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                "keeps_plan_and_summary": mode == "cache"}
        plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return plan

    async def cleanup(self, project_id, task_id, mode, token):
        async with self.lock:
            plan = await self.cleanup_plan(project_id, task_id, mode)
            if not token or token != plan["token"]: raise ValueError("清理范围发生变化，请重新预览后确认。")
            self.cleaning.update(plan["task_ids"])
            self.cleaning_projects.add(project_id)
            operation_path = self.root / "last_cleanup.json"
            operation = {"project_id": project_id, "mode": mode, "task_ids": plan["task_ids"],
                         "started_at": now_iso(), "status": "running", "files": [f["path"] for f in plan["files"]]}
            self.storage._write_json(operation_path, operation)
            try:
                result = await self._cleanup_confirmed(plan)
                operation.update(status="completed", completed_at=now_iso(), result=result)
                self.storage._write_json(operation_path, operation)
                return result
            except BaseException:
                operation.update(status="interrupted", note="可能部分完成。请重新预览现存记录后再清理，不会重放外部任务。")
                self.storage._write_json(operation_path, operation)
                raise
            finally:
                self.cleaning.difference_update(plan["task_ids"])
                self.cleaning_projects.discard(project_id)

    async def _cleanup_confirmed(self, plan):
        project_id, mode = plan["project_id"], plan["mode"]
        tasks = self.all_tasks()
        # Native history is deleted by exact task-derived IDs, never by source UMO.
        for item in plan["native"]:
            await self.owner.context.conversation_manager.delete_conversation(item["umo"], item["cid"])
        for task_key in plan["task_ids"]:
            task = tasks.get(task_key)
            if not task: continue
            if mode == "cache":
                task.workflow_data["react_traces"] = []
                task.progress_log = task.progress_log[-30:]
                task.state_snapshots = task.state_snapshots[-10:]
                for row in control(task).get("journal", []):
                    if row.get("status") in {"completed", "failed"}: row["result"] = "[缓存已清理；保留证据编号和状态]"
                self.storage.save_task(task, active=False)
                if task.archive_path:
                    archive = self.storage.archive_task_json_path(task.umo, task.task_id)
                    if archive.exists():
                        self.storage._write_json(archive, task.to_dict())
                        self.storage._write_text(self.storage.archive_task_markdown_path(task.umo, task.task_id), self.storage.render_markdown(task))
                    self.storage._write_json(self.storage.task_path(task.umo, task.task_id), task.to_dict())
                    self.storage._write_text(self.storage.task_markdown_path(task.umo, task.task_id), self.storage.render_markdown(task))
                active = self.storage.load_active_task(task.umo)
                if active and active.task_id == task_key:
                    self.storage._write_json(self.storage.active_task_path(task.umo), task.to_dict())
            else:
                self.storage.mark_ended(task, "cancelled", "administrator_cleanup")
                self.storage.delete_memory_entries_for_task(task_key)
        if mode != "cache":
            # A learned pattern can contain text from several task histories.
            # Remove only the deleted provenance; retire the aggregate when its
            # primary source was deleted rather than retaining a stale summary.
            library = self.owner.pattern_library
            patterns = library.list_patterns(status="all")
            deleted = set(plan["task_ids"])
            kept = []
            for row in patterns:
                if row.get("source_task_id") in deleted:
                    continue
                evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
                if isinstance(evidence.get("source_tasks"), list):
                    evidence["source_tasks"] = [item for item in evidence["source_tasks"] if item.get("task_id") not in deleted]
                kept.append(row)
            self.storage._write_json(library.path, kept)
        for file in plan["files"]:
            path = self.storage.root / file["path"]
            if not self.safe_path(path): raise ValueError("清理路径校验失败。")
            path.unlink(missing_ok=True)
        if mode != "cache":
            data = self.index()
            for key in plan["task_ids"]: data["tasks"].pop(key, None)
            if mode == "project":
                data["projects"] = [row for row in data["projects"] if row["project_id"] != project_id]
                data["selected"] = {umo: pid for umo, pid in data["selected"].items() if pid != project_id}
            else:
                project = next(p for p in data["projects"] if p["project_id"] == project_id)
                if project.get("summary_source_task_id") in plan["task_ids"]:
                    project.update(summary="", summary_source_task_id="", updated_at=now_iso())
                    self.summary_path(project_id).unlink(missing_ok=True)
            self.write(data)
        return {"deleted_files": len(plan["files"]), "file_bytes": plan["bytes"], "native_conversations": len(plan["native"]),
                "message": "清理完成；源码工作目录未被删除。"}
