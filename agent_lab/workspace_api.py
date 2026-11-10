"""Project UI operations with explicit administrator authority and no model veto."""
import asyncio

from quart import g, jsonify, request

from .task_control import control
from .web_api import admin_api
from .identities import identity_rows, source_platform


class WorkspaceAPI:
    def __init__(self, owner):
        self.owner = owner

    @admin_api
    async def handle(self):
        projects = self.owner.projects
        if request.method == "GET":
            catalog = await asyncio.to_thread(projects.catalog)
            return jsonify({"ok": True, **catalog, "identities": identity_rows(self.owner, catalog["projects"])})
        payload = await request.get_json(silent=True) or {}
        if not isinstance(payload, dict): raise ValueError("请求必须是对象。")
        action = str(payload.get("action") or "")
        project_id, task_id = str(payload.get("project_id") or ""), str(payload.get("task_id") or "")
        actor = str(getattr(g, "username", "standalone-admin"))
        result = {}
        if action == "create_project":
            umo = str(payload.get("umo") or "")
            if umo and self.owner._make_cron_event(umo, "Project create") is None: raise ValueError("会话来源不可用。")
            platform_id = str(payload.get("platform_id") or source_platform(umo))
            known = {row["platform_id"] for row in identity_rows(self.owner, projects.index()["projects"]) if row["known"]}
            if platform_id and platform_id not in known: raise ValueError("机器人实例当前不可用，请在设置中重新选择。")
            if umo and platform_id != source_platform(umo): raise ValueError("会话来源与选择的机器人不一致。")
            result = projects.create(payload.get("title", ""), payload.get("category", "项目"), umo, actor, platform_id)
        elif action == "update_project":
            result = projects.update(project_id, payload)
        elif action == "detail":
            result = await projects.detail(task_id)
        elif action == "read_record":
            task = projects.get_task(task_id)
            relative = str(payload.get("path") or "")
            candidate = projects.storage.root / relative
            allowed = {path.resolve() for path in projects.task_paths(task)}
            if candidate.resolve() not in allowed or not projects.safe_path(candidate):
                raise ValueError("该文件不属于所选任务记录。")
            def read_preview():
                with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                    return handle.read(24001)
            text = await asyncio.to_thread(read_preview)
            result = {"path": relative, "text": self.owner._redact_known_secrets(text[:24000]), "truncated": len(text)>24000}
        elif action in {"stop", "deliver"}:
            task = await projects.administrator_end(task_id, "cancelled" if action == "stop" else "completed",
                                                    str(payload.get("summary") or ""), actor)
            result = {"task_id": task.task_id, "status": task.status, "summary": task.exit_summary}
        elif action == "activate":
            task = projects.get_task(task_id)
            event = self.owner._make_cron_event(task.umo, "Project task switch")
            if not event: raise ValueError("任务来源不可用。")
            switched = await projects.activate(task_id, event)
            result = {"task_id": switched.task_id, "message": "已切换到该任务，保持暂停；确认后可恢复。"}
        elif action == "answer":
            task = projects.get_task(task_id)
            active = self.owner.storage.load_active_task(task.umo)
            if not active or active.task_id != task_id: raise ValueError("先切换到此任务再回答。")
            event = self.owner._make_cron_event(task.umo, "Project task answer")
            if not event: raise ValueError("任务来源不可用。")
            message = self.owner.task_control.answer(event, str(payload.get("question_id") or ""), str(payload.get("answer") or ""))
            if not control(self.owner.task_control.load(task.umo)).get("version"):
                message += "\n" + await self.owner.task_control.propose(event, task_id)
            result = {"message": message}
        elif action == "move_task":
            task = projects.get_task(task_id)
            if task.status == "running": raise ValueError("先暂停任务再整理分类。")
            result = projects.attach(task, project_id)
            self.owner.storage.save_task(task, active=False)
        elif action == "save_summary":
            result = projects.save_summary(task_id, str(payload.get("summary") or ""))
        elif action == "draft_summary":
            task = projects.get_task(task_id)
            event = self.owner._make_cron_event(task.umo, "Project summary")
            if not event: raise ValueError("任务来源不可用。")
            result = {"summary": await self.owner._draft_project_summary(event, task)}
        elif action == "draft_plan":
            task = projects.get_task(task_id)
            active = self.owner.storage.load_active_task(task.umo)
            if not active or active.task_id != task_id:
                raise ValueError("先切换到此任务再制定计划。")
            if task.status == "running": raise ValueError("先暂停运行再制定计划。")
            event = self.owner._make_cron_event(task.umo, "Project plan")
            if not event: raise ValueError("任务来源不可用。")
            if not control(task).get("version"):
                control(task)["human_paused"] = False
                self.owner.storage.save_task(task)
            result = {"message": await self.owner.task_control.propose(event, task_id)}
        elif action == "cleanup_preview":
            result = await projects.cleanup_plan(project_id, task_id, str(payload.get("mode") or "cache"))
        elif action == "cleanup_confirm":
            result = await projects.cleanup(project_id, task_id, str(payload.get("mode") or "cache"), str(payload.get("token") or ""))
        else:
            raise ValueError("未知项目操作。")
        return jsonify({"ok": True, "result": result})
