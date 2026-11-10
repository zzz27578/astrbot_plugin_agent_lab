"""Durable, task-scoped storage for the lightweight Agent Lab harness.

This module deliberately has no AstrBot imports. A committed SQLite transaction
is the boundary between a proposed operation and an operation the runner owns.
Tool intentions must be committed before dispatch; an unfinished intention is
never silently treated as safe to replay after a restart.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TERMINAL_STATUSES = frozenset({"completed", "cancelled", "failed"})
TASK_STATUSES = TERMINAL_STATUSES | {
    "queued", "planning", "awaiting_plan_approval", "running", "paused",
    "waiting_approval", "blocked", "awaiting_acceptance",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def new_identifier(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class HarnessConflict(ValueError):
    """The requested mutation no longer matches the durable task state."""


class HarnessStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "harness.sqlite3"
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS harness_tasks (
                task_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                revision INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0,
                payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS harness_task_status ON harness_tasks(deleted,status);
            CREATE TABLE IF NOT EXISTS harness_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                type TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS harness_event_task ON harness_events(task_id,id);
            CREATE TABLE IF NOT EXISTS harness_approvals (
                approval_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                status TEXT NOT NULL, payload TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES harness_tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS harness_tools (
                intent_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(task_id,idempotency_key),
                FOREIGN KEY(task_id) REFERENCES harness_tasks(task_id)
            );
            CREATE TABLE IF NOT EXISTS harness_templates (
                template_id TEXT PRIMARY KEY, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS harness_memories (
                memory_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL,
                FOREIGN KEY(task_id) REFERENCES harness_tasks(task_id)
            );
            PRAGMA user_version=1;
        """)
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> int:
        cursor = self._db.execute(
            "INSERT INTO harness_events(task_id,type,created_at,payload) VALUES(?,?,?,?)",
            (task_id, event_type, utc_now(), _dump(payload)),
        )
        return int(cursor.lastrowid)

    def append_event(self, task_id: str, event_type: str, payload: dict[str, Any]) -> int:
        with self._lock, self._db:
            self._require(task_id)
            return self._event(task_id, event_type, payload)

    def _require(self, task_id: str) -> dict[str, Any]:
        row = self._db.execute(
            "SELECT payload FROM harness_tasks WHERE task_id=? AND deleted=0", (task_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Task not found: {task_id}")
        return json.loads(row["payload"])

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            try:
                return self._require(task_id)
            except KeyError:
                return None

    def create_task(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = json.loads(_dump(task))
        payload.setdefault("task_id", new_identifier("task"))
        payload.setdefault("created_at", utc_now())
        payload["updated_at"] = utc_now()
        payload["revision"] = 1
        if payload.get("status") not in TASK_STATUSES:
            raise ValueError("Invalid task status")
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO harness_tasks(task_id,status,revision,payload) VALUES(?,?,?,?)",
                (payload["task_id"], payload["status"], 1, _dump(payload)),
            )
            self._event(payload["task_id"], "task.created", {"status": payload["status"]})
        return payload

    def _write_task(self, current: dict[str, Any], changes: dict[str, Any], event_type: str) -> dict[str, Any]:
        if current["status"] in TERMINAL_STATUSES:
            raise HarnessConflict("A finished task cannot be changed or restarted")
        for key in ("task_id", "created_at", "owner_id", "owner_platform", "actor_kind"):
            if key in changes and changes[key] != current.get(key):
                raise HarnessConflict(f"Task identity field cannot change: {key}")
        updated = {**current, **changes}
        if updated.get("status") not in TASK_STATUSES:
            raise ValueError("Invalid task status")
        updated["revision"] = int(current["revision"]) + 1
        updated["updated_at"] = utc_now()
        serialized = _dump(updated)
        result = self._db.execute(
            "UPDATE harness_tasks SET status=?,revision=?,payload=? WHERE task_id=? AND revision=? AND deleted=0",
            (updated["status"], updated["revision"], serialized, current["task_id"], current["revision"]),
        )
        if result.rowcount != 1:
            raise HarnessConflict("Task changed concurrently; read it again")
        self._event(current["task_id"], event_type, {
            "revision": updated["revision"], "status": updated["status"],
            "changed_fields": sorted(changes),
        })
        return updated

    def update_task(self, task_id: str, changes: dict[str, Any], expected_revision: int | None = None,
                    event_type: str = "task.updated") -> dict[str, Any]:
        with self._lock, self._db:
            current = self._require(task_id)
            if expected_revision is not None and current["revision"] != expected_revision:
                raise HarnessConflict("Task revision changed; refresh before applying this change")
            return self._write_task(current, changes, event_type)

    def list_tasks(self, source_umo: str = "", owner_id: str = "", include_terminal: bool = True,
                   limit: int = 500) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT payload FROM harness_tasks WHERE deleted=0"
            args: list[Any] = []
            if not include_terminal:
                query += " AND status IN (?,?,?,?,?,?,?,?)"
                args.extend(["queued", "planning", "awaiting_plan_approval", "running", "paused", "waiting_approval", "blocked", "awaiting_acceptance"])
            query += " ORDER BY rowid DESC"
            if not source_umo and not owner_id:
                query += " LIMIT ?"
                args.append(max(1, min(int(limit), 10000)))
            rows = self._db.execute(query, args)
            result = []
            for row in rows:
                task = json.loads(row["payload"])
                if source_umo and task.get("source_umo") != source_umo:
                    continue
                if owner_id and task.get("owner_id") != owner_id:
                    continue
                if not include_terminal and task["status"] in TERMINAL_STATUSES:
                    continue
                result.append(task)
                if len(result) >= max(1, min(int(limit), 10000)):
                    break
            return result

    def delete_task(self, task_id: str) -> bool:
        with self._lock, self._db:
            task = self.get_task(task_id)
            if task is None:
                return False
            if task["status"] not in TERMINAL_STATUSES:
                raise HarnessConflict("Cancel or finish the task before deleting it")
            self._db.execute("UPDATE harness_tasks SET deleted=1 WHERE task_id=?", (task_id,))
            self._event(task_id, "task.deleted", {})
            return True

    def events(self, after_id: int = 0, task_id: str = "", limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM harness_events WHERE id>?"
            args: list[Any] = [max(0, int(after_id))]
            if task_id:
                query += " AND task_id=?"
                args.append(task_id)
            query += " ORDER BY id LIMIT ?"
            args.append(max(1, min(int(limit), 1000)))
            return [{**dict(row), "payload": json.loads(row["payload"])} for row in self._db.execute(query, args)]

    def task_recent_events(self, task_id: str, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            self._require(task_id)
            rows = self._db.execute("SELECT * FROM harness_events WHERE task_id=? ORDER BY id DESC LIMIT ?",
                                    (task_id, max(1, min(int(limit), 1000))))
            return list(reversed([{**dict(row), "payload": json.loads(row["payload"])} for row in rows]))

    def request_approval(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            task = self._require(task_id)
            if task["status"] != "running":
                raise HarnessConflict("Only a running task can request an operation approval")
            if (not payload.get("tool_name") or not isinstance(payload.get("arguments"), dict)
                    or payload.get("step_id") != task.get("current_step_id")):
                raise HarnessConflict("An approval must name the exact tool, arguments and active step")
            approval = {**payload, "approval_id": new_identifier("approval"), "task_id": task_id,
                        "plan_version": task["plan_version"], "status": "pending", "created_at": utc_now()}
            self._db.execute("INSERT INTO harness_approvals VALUES(?,?,?,?)", (
                approval["approval_id"], task_id, "pending", _dump(approval),
            ))
            self._write_task(task, {"status": "waiting_approval", "next_action": "Review the pending operation approval"}, "approval.requested")
            self._event(task_id, "approval.detail", approval)
            return approval

    def list_approvals(self, task_id: str, status: str = "") -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT payload FROM harness_approvals WHERE task_id=? ORDER BY rowid", (task_id,))
            return [item for row in rows if (item := json.loads(row["payload"])) and (not status or item["status"] == status)]

    def resolve_approval(self, task_id: str, approval_id: str, approved: bool,
                         actor: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            task = self._require(task_id)
            if task["status"] in TERMINAL_STATUSES:
                raise HarnessConflict("Task has already ended")
            row = self._db.execute("SELECT payload FROM harness_approvals WHERE task_id=? AND approval_id=?", (task_id, approval_id)).fetchone()
            if row is None:
                raise KeyError("Approval not found")
            approval = json.loads(row["payload"])
            if approval["status"] != "pending":
                raise HarnessConflict("Approval was already resolved")
            if approval["plan_version"] != task["plan_version"]:
                raise HarnessConflict("Approval belongs to an outdated plan")
            approval.update(status="approved" if approved else "rejected", resolved_at=utc_now(), resolved_by=actor or {})
            self._db.execute("UPDATE harness_approvals SET status=?,payload=? WHERE approval_id=?", (approval["status"], _dump(approval), approval_id))
            self._event(task_id, "approval.resolved", approval)
            return approval

    def invalidate_approvals(self, task_id: str, reason: str) -> None:
        with self._lock, self._db:
            for approval in self.list_approvals(task_id):
                if approval["status"] not in {"pending", "approved"}:
                    continue
                approval.update(status="expired", resolved_at=utc_now(), reason=reason)
                self._db.execute("UPDATE harness_approvals SET status=?,payload=? WHERE approval_id=?", ("expired", _dump(approval), approval["approval_id"]))
            self._event(task_id, "approval.invalidated", {"reason": reason})

    def record_tool_intent(self, task_id: str, tool_name: str, arguments: dict[str, Any],
                           step_id: str = "", idempotency_key: str = "", approval_id: str = "",
                           resource_fingerprint: str = "") -> dict[str, Any]:
        """Commit before dispatch. Existing keys return existing calls, never replay them."""
        with self._lock, self._db:
            # sqlite3's context manager alone does not begin a transaction for
            # SELECTs. Acquire the write transaction before checking authority.
            self._db.execute("BEGIN IMMEDIATE")
            task = self._require(task_id)
            if task["status"] != "running" or task.get("approved_version") != task.get("plan_version"):
                raise HarnessConflict("Task is not running an approved plan")
            if not step_id or task.get("current_step_id") != step_id:
                raise HarnessConflict("Tool invocation does not belong to the active step")
            if self.list_approvals(task_id, "pending"):
                raise HarnessConflict("A pending approval prevents tool dispatch")
            key = idempotency_key or new_identifier("call")
            row = self._db.execute("SELECT payload FROM harness_tools WHERE task_id=? AND idempotency_key=?", (task_id, key)).fetchone()
            if row:
                existing = json.loads(row["payload"])
                if (existing["tool_name"] != tool_name or existing["arguments"] != arguments
                        or existing.get("step_id") != step_id or existing.get("plan_version") != task["plan_version"]
                        or existing.get("resource_fingerprint", "") != resource_fingerprint):
                    raise HarnessConflict("Idempotency key is already bound to another operation")
                if existing["status"] != "not_started":
                    return {**existing, "reused": True}
                # A human verified that nothing started. Preserve that record
                # while releasing this operation key for an explicitly resumed attempt.
                self._db.execute("UPDATE harness_tools SET idempotency_key=? WHERE intent_id=?", (
                    f"reconciled:{existing['intent_id']}", existing["intent_id"],
                ))
            approval = None
            if approval_id:
                row = self._db.execute("SELECT payload FROM harness_approvals WHERE task_id=? AND approval_id=?", (task_id, approval_id)).fetchone()
                if row is None:
                    raise HarnessConflict("Approval was not found for this task")
                approval = json.loads(row["payload"])
                expected = {"plan_version": task["plan_version"], "step_id": step_id, "tool_name": tool_name,
                            "arguments": arguments, "resource_fingerprint": resource_fingerprint}
                if approval.get("status") != "approved" or any(approval.get(name, "") != value for name, value in expected.items()):
                    raise HarnessConflict("Approval is consumed, stale or does not match this exact operation")
            elif tool_name not in set(task.get("preapproved_tools") or []):
                raise HarnessConflict("This operation needs an exact approval before dispatch")
            if any(call["status"] in {"started", "unknown"} for call in self.list_tool_calls(task_id)):
                raise HarnessConflict("Reconcile unfinished operations before dispatching another tool")
            budgets = dict(task.get("budgets") or {})
            used = int(budgets.get("tool_calls_used") or 0)
            cap = max(1, int(budgets.get("max_tool_calls") or 240))
            if used >= cap:
                raise HarnessConflict("Task tool-call budget exhausted")
            intent = {"intent_id": new_identifier("intent"), "task_id": task_id, "step_id": step_id,
                      "plan_version": task["plan_version"], "tool_name": str(tool_name), "arguments": arguments,
                      "approval_id": approval_id, "resource_fingerprint": resource_fingerprint,
                      "idempotency_key": key, "status": "started", "created_at": utc_now(), "reused": False}
            self._db.execute("INSERT INTO harness_tools VALUES(?,?,?,?,?)", (intent["intent_id"], task_id, key, "started", _dump(intent)))
            if approval is not None:
                approval.update(status="consumed", consumed_at=utc_now(), intent_id=intent["intent_id"])
                self._db.execute("UPDATE harness_approvals SET status='consumed',payload=? WHERE approval_id=?", (_dump(approval), approval_id))
                self._event(task_id, "approval.consumed", {"approval_id": approval_id, "intent_id": intent["intent_id"]})
            budgets["tool_calls_used"] = used + 1
            self._write_task(task, {"budgets": budgets}, "tool.intent_recorded")
            self._event(task_id, "tool.started", intent)
            return intent

    def record_tool_result(self, task_id: str, intent_id: str, result: Any,
                           status: str = "completed") -> dict[str, Any]:
        if status not in {"completed", "failed", "unknown", "not_started"}:
            raise ValueError("Invalid tool result status")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT payload FROM harness_tools WHERE task_id=? AND intent_id=?", (task_id, intent_id)).fetchone()
            if row is None:
                raise KeyError("Tool intention not found")
            intent = json.loads(row["payload"])
            if intent["status"] in {"completed", "failed", "not_started"}:
                raise HarnessConflict("Tool already has a final result")
            intent.update(status=status, result=result, finished_at=utc_now())
            self._db.execute("UPDATE harness_tools SET status=?,payload=? WHERE intent_id=?", (status, _dump(intent), intent_id))
            self._event(task_id, "tool.result", intent)
            return intent

    def list_tool_calls(self, task_id: str, status: str = "") -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT payload FROM harness_tools WHERE task_id=? ORDER BY rowid", (task_id,))
            return [item for row in rows if (item := json.loads(row["payload"])) and (not status or item["status"] == status)]

    def mark_interrupted_tools(self, task_id: str, reason: str) -> None:
        for intent in self.list_tool_calls(task_id, "started"):
            self.record_tool_result(task_id, intent["intent_id"], {"error": reason, "requires_reconciliation": True}, "unknown")

    def reconcile_tool(self, task_id: str, intent_id: str, outcome: str, summary: str,
                       actor: dict[str, Any] | None = None) -> dict[str, Any]:
        if outcome not in {"completed", "failed", "not_started"}:
            raise ValueError("Reconciled outcome must be completed, failed or not_started")
        if not str(summary).strip():
            raise ValueError("Describe the external evidence used to reconcile this operation")
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            task = self._require(task_id)
            if task["status"] in {"running", "planning", "queued"}:
                raise HarnessConflict("Pause the task before reconciling an operation")
            row = self._db.execute("SELECT payload FROM harness_tools WHERE task_id=? AND intent_id=?", (task_id, intent_id)).fetchone()
            if row is None:
                raise KeyError("Tool intention not found")
            intent = json.loads(row["payload"])
            if intent["status"] != "unknown":
                raise HarnessConflict("Only an unknown tool result can be manually reconciled")
            intent.update(status=outcome, finished_at=utc_now(), result={"reconciled": True,
                "summary": str(summary).strip(), "actor": actor or {}, "outcome": outcome})
            self._db.execute("UPDATE harness_tools SET status=?,payload=? WHERE intent_id=?", (outcome, _dump(intent), intent_id))
            self._event(task_id, "tool.reconciled", intent)
            return intent

    def recover_interrupted(self) -> list[dict[str, Any]]:
        recovered = []
        for task in self.list_tasks(include_terminal=False, limit=10000):
            self.mark_interrupted_tools(task["task_id"], "Execution stopped before a durable tool result")
            if task["status"] in {"queued", "running", "planning"}:
                steps = [{**step, "status": "pending"} if step.get("status") == "running" else step for step in task.get("steps", [])]
                recovered.append(self.update_task(task["task_id"], {
                    "status": "paused", "steps": steps, "pause_reason": "restart",
                    "schedule_armed": False,
                    "next_action": "Review the checkpoint and uncertain tool outcomes, then explicitly resume",
                }, event_type="task.recovered"))
            elif task.get("schedule_armed"):
                recovered.append(self.update_task(task["task_id"], {
                    "status": "paused", "schedule_armed": False, "pause_reason": "schedule_restart",
                    "next_action": "The saved one-time schedule is disarmed after restart; review and schedule again",
                }, event_type="schedule.recovered"))
        return recovered

    def save_template(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = json.loads(_dump(payload))
        item["template_id"] = str(item.get("template_id") or new_identifier("template"))
        item["updated_at"] = utc_now()
        item.setdefault("created_at", item["updated_at"])
        with self._lock, self._db:
            self._db.execute("INSERT INTO harness_templates VALUES(?,?) ON CONFLICT(template_id) DO UPDATE SET payload=excluded.payload", (item["template_id"], _dump(item)))
        return item

    def list_templates(self) -> list[dict[str, Any]]:
        with self._lock:
            return [json.loads(row[0]) for row in self._db.execute("SELECT payload FROM harness_templates ORDER BY rowid DESC")]

    def delete_template(self, template_id: str) -> bool:
        with self._lock, self._db:
            return self._db.execute("DELETE FROM harness_templates WHERE template_id=?", (template_id,)).rowcount == 1

    def save_memory(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock, self._db:
            task = self._require(task_id)
            item = {**payload, "memory_id": str(payload.get("memory_id") or new_identifier("memory")),
                    "task_id": task_id, "owner_id": task.get("owner_id", ""),
                    "source_umo": task.get("source_umo", ""), "updated_at": utc_now(),
                    "project_key": str(task.get("project_key") or "").strip()}
            item.setdefault("visibility", "task")
            item.setdefault("status", "candidate")
            if item["status"] not in {"candidate", "accepted", "rejected"}:
                raise ValueError("Memory status must be candidate, accepted or rejected")
            share = payload.get("share_with_project", False)
            if not isinstance(share, bool):
                raise ValueError("share_with_project must be a boolean")
            if share and not item["project_key"]:
                raise HarnessConflict("A task without a project cannot share project memory")
            item["share_with_project"] = share
            existing = self._db.execute("SELECT task_id FROM harness_memories WHERE memory_id=?", (item["memory_id"],)).fetchone()
            if existing and existing[0] != task_id:
                raise HarnessConflict("A memory cannot move between tasks")
            self._db.execute("INSERT INTO harness_memories VALUES(?,?,?) ON CONFLICT(memory_id) DO UPDATE SET payload=excluded.payload", (item["memory_id"], task_id, _dump(item)))
            self._event(task_id, "memory.saved", {"memory_id": item["memory_id"], "visibility": item["visibility"]})
            return item

    def list_memories(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            self._require(task_id)
            return [json.loads(row[0]) for row in self._db.execute("SELECT payload FROM harness_memories WHERE task_id=? ORDER BY rowid", (task_id,))]

    def list_project_memories(self, project_key: str) -> list[dict[str, Any]]:
        """Only explicit acceptance AND explicit sharing expose task memory."""
        project_key = str(project_key or "").strip()
        if not project_key:
            return []
        with self._lock:
            rows = self._db.execute("SELECT m.payload FROM harness_memories m JOIN harness_tasks t ON m.task_id=t.task_id WHERE t.deleted=0 ORDER BY m.rowid")
            return [item for row in rows if (item := json.loads(row[0]))
                    and item.get("project_key") == project_key
                    and item.get("status") == "accepted" and item.get("share_with_project") is True]
