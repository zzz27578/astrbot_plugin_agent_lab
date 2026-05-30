from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .models import AgentSpec, TaskState, now_iso


def _safe_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class AgentLabStorage:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.agents_dir = self.root / "agents"
        self.sessions_dir = self.root / "sessions"
        self.modules_dir = self.root / "modules"
        self.archives_dir = self.root / "archives"
        self.root.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.modules_dir.mkdir(parents=True, exist_ok=True)
        self.archives_dir.mkdir(parents=True, exist_ok=True)

    def ensure_defaults(self) -> AgentSpec:
        agents = self.list_agents()
        if agents:
            return agents[0]
        spec = AgentSpec()
        self.save_agent(spec)
        return spec

    def list_agents(self) -> list[AgentSpec]:
        agents: list[AgentSpec] = []
        for path in sorted(self.agents_dir.glob("*.json")):
            try:
                agents.append(AgentSpec.from_dict(self._read_json(path)))
            except Exception:
                continue
        return agents

    def get_agent(self, agent_id: str | None = None) -> AgentSpec:
        if agent_id:
            path = self.agents_dir / f"{agent_id}.json"
            if path.exists():
                return AgentSpec.from_dict(self._read_json(path))
        return self.ensure_defaults()

    def save_agent(self, spec: AgentSpec) -> None:
        spec.updated_at = now_iso()
        self._write_json(self.agents_dir / f"{spec.agent_id}.json", spec.to_dict())

    def session_dir(self, umo: str) -> Path:
        path = self.sessions_dir / _safe_hash(umo)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def active_task_path(self, umo: str) -> Path:
        return self.session_dir(umo) / "active_task.json"

    def task_path(self, umo: str, task_id: str) -> Path:
        return self.session_dir(umo) / f"{task_id}.json"

    def task_markdown_path(self, umo: str, task_id: str) -> Path:
        return self.session_dir(umo) / f"{task_id}.md"

    def has_active_task(self, umo: str) -> bool:
        return self.active_task_path(umo).exists()

    def load_active_task(self, umo: str) -> TaskState | None:
        path = self.active_task_path(umo)
        if not path.exists():
            return None
        return TaskState.from_dict(self._read_json(path))

    def save_task(self, task: TaskState, active: bool = True) -> None:
        task.updated_at = now_iso()
        payload = task.to_dict()
        self._write_json(self.task_path(task.umo, task.task_id), payload)
        self._write_text(self.task_markdown_path(task.umo, task.task_id), self.render_markdown(task))
        if active:
            self._write_json(self.active_task_path(task.umo), payload)

    def archive_task(self, task: TaskState) -> Path:
        task.finished_at = task.finished_at or now_iso()
        task.updated_at = now_iso()
        session_archive_dir = self.archives_dir / _safe_hash(task.umo)
        session_archive_dir.mkdir(parents=True, exist_ok=True)
        src_json = self.task_path(task.umo, task.task_id)
        src_md = self.task_markdown_path(task.umo, task.task_id)
        dst_json = session_archive_dir / src_json.name
        dst_md = session_archive_dir / src_md.name
        self._write_json(src_json, task.to_dict())
        self._write_text(src_md, self.render_markdown(task))
        shutil.copy2(src_json, dst_json)
        shutil.copy2(src_md, dst_md)
        task.archive_path = str(dst_md)
        self._write_json(dst_json, task.to_dict())
        self._write_text(dst_md, self.render_markdown(task))
        active = self.active_task_path(task.umo)
        if active.exists():
            active.unlink()
        return dst_md

    def list_tasks(self, umo: str | None = None) -> list[TaskState]:
        roots = [self.session_dir(umo)] if umo else list(self.sessions_dir.glob("*"))
        tasks: list[TaskState] = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("task_*.json")):
                try:
                    tasks.append(TaskState.from_dict(self._read_json(path)))
                except Exception:
                    continue
        return tasks

    def render_markdown(self, task: TaskState) -> str:
        approvals = task.pending_approvals()
        lines = [
            f"# Agent Lab Task {task.task_id}",
            "",
            f"- status: {task.status}",
            f"- agent: {task.agent_name or task.agent_id}",
            f"- created_at: {task.created_at}",
            f"- updated_at: {task.updated_at}",
            f"- finished_at: {task.finished_at or '-'}",
            "",
            "## Root Goal",
            task.root_goal or "-",
            "",
            "## Completion Conditions",
        ]
        lines.extend([f"- {item}" for item in task.completion_conditions] or ["- 未设置"])
        lines.extend(
            [
                "",
                "## Entry Summary",
                task.entry_summary or task.task_brief or "-",
                "",
                "## Current Summary",
                task.current_summary or "-",
                "",
                "## Last Confirmed Progress",
                task.last_confirmed_progress or "-",
                "",
                "## Next Step",
                task.next_step or "-",
                "",
                "## Last Observation",
                task.last_observation or "-",
                "",
                "## Pending Approvals",
            ]
        )
        if approvals:
            lines.extend([f"- {a.approval_id}: {a.operation} | {a.reason}" for a in approvals])
        else:
            lines.append("- none")
        lines.extend(["", "## Progress Log"])
        if task.progress_log:
            for item in task.progress_log[-80:]:
                lines.append(f"- {item.get('time')} [{item.get('kind')}] {item.get('text')}")
        else:
            lines.append("- none")
        lines.extend(["", "## Blockers"])
        if task.blockers:
            for item in task.blockers[-40:]:
                lines.append(
                    f"- {item.get('time')} {item.get('issue')} "
                    f"(count={item.get('count')}): {item.get('detail')}"
                )
        else:
            lines.append("- none")
        lines.extend(["", "## Exit Summary", task.exit_summary or "-"])
        lines.extend(["", "## Memory Candidates"])
        lines.extend([f"- {item}" for item in task.memory_candidates] or ["- none"])
        lines.append("")
        return "\n".join(lines)

    def _read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
