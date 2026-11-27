"""Single-Source-of-Truth storage for Agent Lab v1.0.0.

Key guarantees:
1. Compact meta.json (<5KB) + O(1) append-only events.jsonl (journal/messages/usage/logs).
2. Immutable terminal fence `ended/<task_id>.json` outranks all late callbacks.
3. Fernet-encrypted credential vault (`credentials.json` + `secrets.key`); secrets NEVER
   leave plaintext in public views, logs, previews, or LLM prompts.
4. Multi-encoding secret redaction (raw, URL-encoded, Base64-encoded + common token regex).
5. Two-step preview + single-use token confirmation for cache/history/project cleanup.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .models import (
    CredentialMeta,
    Profile,
    Project,
    TaskMeta,
    default_profiles,
    new_id,
    now_iso,
)

TASK_ID_RE = re.compile(r"^task_[a-f0-9]+$")
FALLBACK_SECRET_RE = re.compile(
    r"(?i)(cookie|token|password|passwd|secret|api[_-]?key|authorization|bearer)"
    r"(\s*[:=]\s*|\s+)([^\s;,'\"`]{6,})"
)


def _safe_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


class AgentLabStore:
    """Thread-safe atomic JSON + JSONL storage."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.registry_dir = self.root / "registry"
        self.projects_dir = self.root / "projects"
        self.sessions_dir = self.root / "sessions"
        self.ended_dir = self.root / "ended"
        for d in (self.registry_dir, self.projects_dir, self.sessions_dir, self.ended_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.profiles_path = self.registry_dir / "profiles.json"
        self.projects_index_path = self.registry_dir / "projects.json"
        self.credentials_path = self.registry_dir / "credentials.json"
        self.secrets_key_path = self.registry_dir / "secrets.key"
        self.preferences_path = self.registry_dir / "preferences.json"

        self._lock = threading.RLock()
        self._cleanup_tokens: dict[str, dict[str, Any]] = {}
        self.ensure_defaults()

    # ── Low-level atomic IO ──────────────────────────────────────────────────

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def _write_json(self, path: Path, data: Any) -> None:
        self._write_text(path, json.dumps(data, ensure_ascii=False, indent=2))

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def ensure_defaults(self) -> None:
        with self._lock:
            if not self.profiles_path.exists():
                self._write_json(self.profiles_path, [p.to_dict() for p in default_profiles()])
            if not self.projects_index_path.exists():
                self._write_json(
                    self.projects_index_path,
                    {"projects": [], "tasks": {}, "selected": {}},
                )
            if not self.credentials_path.exists():
                self._write_json(self.credentials_path, [])
            if not self.preferences_path.exists():
                self._write_json(
                    self.preferences_path,
                    {
                        "default_bot": "",
                        "webui_theme": "classic",
                        "progress": {},
                    },
                )

    # ── Preferences ──────────────────────────────────────────────────────────

    def get_preferences(self) -> dict[str, Any]:
        with self._lock:
            prefs = self._read_json(self.preferences_path, {})
            return {
                "default_bot": str(prefs.get("default_bot") or ""),
                "webui_theme": str(prefs.get("webui_theme") or "classic"),
                "progress": dict(prefs.get("progress") or {}),
            }

    def update_preferences(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            prefs = self.get_preferences()
            for k, v in updates.items():
                if k == "progress" and isinstance(v, dict):
                    merged = dict(prefs.get("progress") or {})
                    merged.update(v)
                    prefs["progress"] = merged
                elif k in {"default_bot", "webui_theme"}:
                    prefs[k] = str(v or "")
            self._write_json(self.preferences_path, prefs)
            return prefs

    # ── Profiles (方案) ───────────────────────────────────────────────────────

    def list_profiles(self) -> list[Profile]:
        with self._lock:
            rows = self._read_json(self.profiles_path, [])
            profiles = [Profile.from_dict(r) for r in rows if isinstance(r, dict)]
            if not profiles:
                profiles = default_profiles()
                self._write_json(self.profiles_path, [p.to_dict() for p in profiles])
            return profiles

    def get_profile(self, profile_id: str | None = None, *, strict: bool = False) -> Profile:
        profiles = self.list_profiles()
        if profile_id:
            for p in profiles:
                if p.profile_id == profile_id:
                    return p
            if strict:
                raise ValueError(
                    f"方案 `{profile_id}` 不存在；当前可用方案：{', '.join(p.profile_id for p in profiles)}"
                )
        for p in profiles:
            if p.is_default:
                return p
        return profiles[0]

    def save_profile(self, payload: dict[str, Any]) -> Profile:
        with self._lock:
            profiles = self.list_profiles()
            pid = str(payload.get("profile_id") or "").strip()
            existing = next((p for p in profiles if p.profile_id == pid), None)
            merged = {**(existing.to_dict() if existing else {}), **payload}
            if not merged.get("profile_id"):
                merged["profile_id"] = new_id("prof")
            merged["updated_at"] = now_iso()
            prof = Profile.from_dict(merged)
            if prof.is_default:
                for p in profiles:
                    if p.profile_id != prof.profile_id:
                        p.is_default = False
            replaced = False
            for idx, p in enumerate(profiles):
                if p.profile_id == prof.profile_id:
                    profiles[idx] = prof
                    replaced = True
                    break
            if not replaced:
                profiles.append(prof)
            if not any(p.is_default for p in profiles):
                profiles[0].is_default = True
            self._write_json(self.profiles_path, [p.to_dict() for p in profiles])
            return prof

    def delete_profile(self, profile_id: str) -> bool:
        with self._lock:
            profiles = self.list_profiles()
            kept = [p for p in profiles if p.profile_id != profile_id]
            if len(kept) == len(profiles):
                return False
            if not kept:
                raise ValueError("至少需要保留一个方案，无法删除最后一个方案。")
            if not any(p.is_default for p in kept):
                kept[0].is_default = True
            new_default_id = next((p.profile_id for p in kept if p.is_default), kept[0].profile_id)
            self._write_json(self.profiles_path, [p.to_dict() for p in kept])
            # Rebind any projects referencing the deleted profile to the current default
            idx = self._projects_index()
            changed = False
            for proj in idx["projects"]:
                if proj.get("profile_id") == profile_id:
                    proj["profile_id"] = new_default_id
                    proj["updated_at"] = now_iso()
                    changed = True
            if changed:
                self._write_json(self.projects_index_path, idx)
            return True

    # ── Fernet Encrypted Credential Vault ────────────────────────────────────

    def _fernet(self) -> Fernet:
        if not self.secrets_key_path.exists():
            key = Fernet.generate_key().decode("ascii")
            self._write_text(self.secrets_key_path, key)
            try:
                os.chmod(self.secrets_key_path, 0o600)
            except OSError:
                pass
        raw = self.secrets_key_path.read_text(encoding="utf-8").strip().encode("ascii")
        return Fernet(raw)

    def _encrypt(self, plaintext: str) -> str:
        return self._fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")

    def _decrypt(self, token: str) -> str:
        if not token:
            return ""
        try:
            return self._fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, OSError):
            return ""

    def list_credentials(self) -> list[CredentialMeta]:
        with self._lock:
            rows = self._read_json(self.credentials_path, [])
            out: list[CredentialMeta] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                pub = {k: v for k, v in r.items() if k != "encrypted_value"}
                pub["has_value"] = bool(r.get("encrypted_value"))
                out.append(CredentialMeta.from_dict(pub))
            return out

    def save_credential(self, payload: dict[str, Any]) -> CredentialMeta:
        with self._lock:
            rows = [r for r in self._read_json(self.credentials_path, []) if isinstance(r, dict)]
            cid = str(payload.get("credential_id") or "").strip()
            existing = next((r for r in rows if r.get("credential_id") == cid), None)
            data = dict(payload)
            raw_value = str(data.pop("value", "") or "")
            data.pop("encrypted_value", None)
            data.pop("masked_value", None)
            merged = {**(existing or {}), **data}
            if not merged.get("credential_id"):
                merged["credential_id"] = new_id("cred")
            if raw_value:
                merged["encrypted_value"] = self._encrypt(raw_value)
            elif existing and existing.get("encrypted_value"):
                merged["encrypted_value"] = existing["encrypted_value"]
            merged["created_at"] = str(merged.get("created_at") or now_iso())
            merged["updated_at"] = now_iso()

            pub_check = CredentialMeta.from_dict(
                {**{k: v for k, v in merged.items() if k != "encrypted_value"}, "has_value": bool(merged.get("encrypted_value"))}
            )
            stored = pub_check.to_dict()
            stored.pop("masked_value", None)
            stored["encrypted_value"] = merged.get("encrypted_value", "")

            replaced = False
            for idx, r in enumerate(rows):
                if r.get("credential_id") == stored["credential_id"]:
                    rows[idx] = stored
                    replaced = True
                    break
            if not replaced:
                rows.append(stored)
            self._write_json(self.credentials_path, rows)
            return pub_check

    def delete_credential(self, credential_id: str) -> bool:
        with self._lock:
            rows = [r for r in self._read_json(self.credentials_path, []) if isinstance(r, dict)]
            kept = [r for r in rows if r.get("credential_id") != credential_id]
            if len(kept) == len(rows):
                return False
            self._write_json(self.credentials_path, kept)
            return True

    def get_credential_secret(self, credential_id: str) -> str:
        with self._lock:
            rows = self._read_json(self.credentials_path, [])
            for r in rows:
                if isinstance(r, dict) and r.get("credential_id") == credential_id:
                    return self._decrypt(str(r.get("encrypted_value") or ""))
            return ""

    def resolve_authorized_credentials(
        self,
        project_id: str,
        profile_cred_ids: list[str],
        project_cred_ids: list[str],
    ) -> list[CredentialMeta]:
        """Return public metadata for credentials explicitly authorized for this task."""
        allowed_ids = set(profile_cred_ids or []) | set(project_cred_ids or [])
        if not allowed_ids:
            return []
        result: list[CredentialMeta] = []
        for c in self.list_credentials():
            if c.credential_id not in allowed_ids or not c.has_value:
                continue
            if c.scope == "project" and project_id and project_id not in c.authorized_projects:
                continue
            result.append(c)
        return result

    def build_authorized_env(
        self,
        project_id: str,
        profile_cred_ids: list[str],
        project_cred_ids: list[str],
    ) -> dict[str, str]:
        """Return {ENV_VAR: plaintext_secret} ONLY for subprocess injection; never log!"""
        env: dict[str, str] = {}
        for meta in self.resolve_authorized_credentials(project_id, profile_cred_ids, project_cred_ids):
            if meta.kind != "secret" or not meta.env_var:
                continue
            secret = self.get_credential_secret(meta.credential_id)
            if secret:
                env[meta.env_var] = secret
        return env

    def _all_plaintext_secrets(self) -> list[str]:
        with self._lock:
            rows = self._read_json(self.credentials_path, [])
            vals: list[str] = []
            for r in rows:
                if isinstance(r, dict) and r.get("encrypted_value"):
                    s = self._decrypt(str(r["encrypted_value"]))
                    if s and len(s) >= 4:
                        vals.append(s)
            return vals

    def redact_secrets(self, value: Any) -> Any:
        """Recursively scrub all vault secrets (raw, URL-encoded, Base64) & token patterns."""
        secrets_list = self._all_plaintext_secrets()
        variants: list[str] = []
        for s in secrets_list:
            variants.append(s)
            ue = urllib.parse.quote(s, safe="")
            if ue != s:
                variants.append(ue)
            b64 = base64.b64encode(s.encode("utf-8")).decode("ascii")
            if len(b64) >= 8:
                variants.append(b64)
        variants.sort(key=len, reverse=True)

        def _clean(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: _clean(v)
                    for k, v in obj.items()
                    if str(k) != "encrypted_value"
                }
            if isinstance(obj, list):
                return [_clean(v) for v in obj]
            if isinstance(obj, str):
                text = obj
                for v in variants:
                    if v in text:
                        text = text.replace(v, "********")
                text = FALLBACK_SECRET_RE.sub(r"\1\2********", text)
                return text
            return obj

        return _clean(value)

    # ── Projects & SUMMARY.md ────────────────────────────────────────────────

    def _projects_index(self) -> dict[str, Any]:
        idx = self._read_json(self.projects_index_path, {})
        return {
            "projects": [p for p in (idx.get("projects") or []) if isinstance(p, dict)],
            "tasks": dict(idx.get("tasks") or {}),
            "selected": dict(idx.get("selected") or {}),
        }

    def project_dir(self, project_id: str) -> Path:
        return self.projects_dir / _safe_hash(project_id)

    def project_summary_path(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "SUMMARY.md"

    def list_projects(self, umo: str = "") -> list[Project]:
        with self._lock:
            idx = self._projects_index()
            items = [Project.from_dict(p) for p in idx["projects"]]
            if umo:
                items = [p for p in items if not p.source_umo or p.source_umo == umo]
            return items

    def get_project(self, project_id: str) -> Project | None:
        with self._lock:
            for p in self._projects_index()["projects"]:
                if p.get("project_id") == project_id:
                    return Project.from_dict(p)
            return None

    def ensure_default_project(self, umo: str, platform_id: str = "") -> Project:
        with self._lock:
            idx = self._projects_index()
            sel_id = idx["selected"].get(umo)
            if sel_id:
                for p in idx["projects"]:
                    if p.get("project_id") == sel_id:
                        return Project.from_dict(p)
            for p in idx["projects"]:
                if p.get("source_umo") == umo:
                    idx["selected"][umo] = p["project_id"]
                    self._write_json(self.projects_index_path, idx)
                    return Project.from_dict(p)
            proj = Project(
                project_id=new_id("proj"),
                title="默认工作区",
                category="通用",
                source_umo=umo,
                platform_id=platform_id or (umo.split(":", 1)[0] if ":" in umo else ""),
                profile_id=self.get_profile().profile_id,
            )
            idx["projects"].append(proj.to_dict())
            idx["selected"][umo] = proj.project_id
            self._write_json(self.projects_index_path, idx)
            self.project_dir(proj.project_id).mkdir(parents=True, exist_ok=True)
            return proj

    def save_project(self, payload: dict[str, Any], *, select_for_umo: str = "") -> Project:
        with self._lock:
            idx = self._projects_index()
            pid = str(payload.get("project_id") or "").strip()
            existing = next((p for p in idx["projects"] if p.get("project_id") == pid), None)
            merged = {**(existing or {}), **payload}
            if not merged.get("project_id"):
                merged["project_id"] = new_id("proj")
            merged["updated_at"] = now_iso()
            proj = Project.from_dict(merged)
            replaced = False
            for i, p in enumerate(idx["projects"]):
                if p.get("project_id") == proj.project_id:
                    idx["projects"][i] = proj.to_dict()
                    replaced = True
                    break
            if not replaced:
                idx["projects"].append(proj.to_dict())
            if select_for_umo:
                idx["selected"][select_for_umo] = proj.project_id
            self._write_json(self.projects_index_path, idx)
            self.project_dir(proj.project_id).mkdir(parents=True, exist_ok=True)
            return proj

    def select_project(self, umo: str, project_id: str) -> None:
        with self._lock:
            idx = self._projects_index()
            idx["selected"][umo] = project_id
            self._write_json(self.projects_index_path, idx)

    def selected_project(self, umo: str) -> Project | None:
        with self._lock:
            idx = self._projects_index()
            pid = idx["selected"].get(umo)
            if not pid:
                return None
            return self.get_project(pid)

    def save_project_summary(
        self, project_id: str, text: str, *, task_id: str = "", auto: bool = False
    ) -> dict[str, Any]:
        with self._lock:
            clean = str(self.redact_secrets(text or "")).strip()
            idx = self._projects_index()
            proj_row = next((p for p in idx["projects"] if p.get("project_id") == project_id), None)
            if not proj_row:
                raise ValueError(f"项目不存在: {project_id}")
            proj_row["summary"] = clean[:2000]
            proj_row["summary_source_task_id"] = task_id
            proj_row["summary_kind"] = "automatic_handoff" if auto else "manual"
            proj_row["updated_at"] = now_iso()
            path = self.project_summary_path(project_id)
            self._write_text(path, clean)
            self._write_json(self.projects_index_path, idx)
            return {
                "project_id": project_id,
                "path": str(path.relative_to(self.root)),
                "bytes": path.stat().st_size if path.exists() else 0,
            }

    def read_project_summary(self, project_id: str, limit: int = 4000) -> str:
        path = self.project_summary_path(project_id)
        try:
            return path.read_text(encoding="utf-8-sig")[:limit]
        except FileNotFoundError:
            proj = self.get_project(project_id)
            return (proj.summary[:limit] if proj else "")

    def daily_summary_for_umo(self, umo: str) -> str:
        proj = self.selected_project(umo)
        if not proj or (proj.source_umo and proj.source_umo != umo):
            return ""
        if not proj.sharing.share_with_daily:
            return ""
        return self.read_project_summary(proj.project_id, proj.sharing.daily_summary_chars)

    def task_summary_for_project(self, project_id: str) -> str:
        proj = self.get_project(project_id)
        if not proj or not proj.sharing.share_with_tasks:
            return ""
        return self.read_project_summary(proj.project_id, proj.sharing.task_summary_chars)

    def link_task_to_project(self, task_id: str, project_id: str, umo: str) -> None:
        with self._lock:
            idx = self._projects_index()
            idx["tasks"][task_id] = {"project_id": project_id, "umo": umo, "updated_at": now_iso()}
            self._write_json(self.projects_index_path, idx)

    def tasks_index(self) -> dict[str, dict[str, Any]]:
        return self._projects_index()["tasks"]

    # ── Task Paths & Terminal Fence ──────────────────────────────────────────

    def _validate_task_id(self, task_id: str) -> str:
        if not TASK_ID_RE.fullmatch(str(task_id or "")):
            raise ValueError(f"Invalid task identifier: {task_id!r}")
        return task_id

    def session_dir(self, umo: str) -> Path:
        return self.sessions_dir / _safe_hash(umo)

    def active_task_path(self, umo: str) -> Path:
        return self.session_dir(umo) / "active_task.json"

    def task_dir(self, umo: str, task_id: str) -> Path:
        self._validate_task_id(task_id)
        return self.session_dir(umo) / "tasks" / task_id

    def task_meta_path(self, umo: str, task_id: str) -> Path:
        return self.task_dir(umo, task_id) / "meta.json"

    def task_events_path(self, umo: str, task_id: str) -> Path:
        return self.task_dir(umo, task_id) / "events.jsonl"

    def task_tool_results_dir(self, umo: str, task_id: str) -> Path:
        return self.task_dir(umo, task_id) / "tool_results"

    def task_wake_dir(self, umo: str, task_id: str) -> Path:
        return self.task_dir(umo, task_id) / "wake_inputs"

    def task_handoffs_dir(self, umo: str, task_id: str) -> Path:
        return self.task_dir(umo, task_id) / "handoffs"

    def ended_path(self, task_id: str) -> Path:
        self._validate_task_id(task_id)
        return self.ended_dir / f"{task_id}.json"

    def is_ended(self, task_id: str) -> bool:
        try:
            return self.ended_path(task_id).exists()
        except ValueError:
            return False

    def mark_ended(self, task: TaskMeta, status: str, actor: str) -> None:
        """Write immutable terminal fence. Once written, late async callbacks cannot overwrite."""
        with self._lock:
            ep = self.ended_path(task.task_id)
            if ep.exists():
                return
            self._write_json(
                ep,
                {
                    "task_id": task.task_id,
                    "status": status,
                    "actor": actor,
                    "time": now_iso(),
                },
            )

    # ── Task CRUD & Append-Only JSONL Events ─────────────────────────────────

    def save_task(self, task: TaskMeta, *, active: bool = True, allow_terminal: bool = False) -> bool:
        """Persist compact meta.json (<5KB). Respects terminal fence & active pointer ownership."""
        with self._lock:
            if self.is_ended(task.task_id) and not allow_terminal:
                return False
            task.updated_at = now_iso()
            tdir = self.task_dir(task.umo, task.task_id)
            tdir.mkdir(parents=True, exist_ok=True)
            meta_path = self.task_meta_path(task.umo, task.task_id)
            existed = meta_path.exists()
            self._write_json(meta_path, task.to_dict())
            self.link_task_to_project(task.task_id, task.project_id, task.umo)

            active_path = self.active_task_path(task.umo)
            current_active = self._read_json(active_path, {})
            current_active_id = current_active.get("task_id") if isinstance(current_active, dict) else ""

            if task.is_terminal():
                if current_active_id == task.task_id and active_path.exists():
                    try:
                        active_path.unlink()
                    except OSError:
                        pass
                return True

            if existed and current_active_id and current_active_id != task.task_id:
                # Switched-away task must never reclaim active_task.json silently.
                active = False
            if active:
                self._write_json(active_path, {"task_id": task.task_id, "umo": task.umo, "updated_at": task.updated_at})
            return True

    def set_active_task(self, task: TaskMeta) -> None:
        with self._lock:
            if task.is_terminal() or self.is_ended(task.task_id):
                return
            self._write_json(
                self.active_task_path(task.umo),
                {"task_id": task.task_id, "umo": task.umo, "updated_at": now_iso()},
            )

    def load_task(self, umo: str, task_id: str) -> TaskMeta | None:
        with self._lock:
            try:
                raw = self._read_json(self.task_meta_path(umo, task_id), None)
            except ValueError:
                return None
            return TaskMeta.from_dict(raw) if isinstance(raw, dict) else None

    def find_task_by_id(self, task_id: str) -> TaskMeta | None:
        with self._lock:
            entry = self.tasks_index().get(task_id)
            if isinstance(entry, dict) and entry.get("umo"):
                found = self.load_task(entry["umo"], task_id)
                if found:
                    return found
            for sdir in self.sessions_dir.iterdir():
                if not sdir.is_dir():
                    continue
                mp = sdir / "tasks" / task_id / "meta.json"
                if mp.exists():
                    raw = self._read_json(mp, None)
                    if isinstance(raw, dict):
                        return TaskMeta.from_dict(raw)
            return None

    def load_active_task(self, umo: str) -> TaskMeta | None:
        with self._lock:
            ptr = self._read_json(self.active_task_path(umo), None)
            if not isinstance(ptr, dict) or not ptr.get("task_id"):
                return None
            task = self.load_task(umo, str(ptr["task_id"]))
            if not task or task.is_terminal() or self.is_ended(task.task_id):
                return None
            return task

    def list_tasks(self, *, umo: str = "", project_id: str = "") -> list[TaskMeta]:
        with self._lock:
            tasks: list[TaskMeta] = []
            if umo:
                dirs = [self.session_dir(umo) / "tasks"]
            else:
                dirs = [d / "tasks" for d in self.sessions_dir.iterdir() if d.is_dir()]
            for troot in dirs:
                if not troot.exists():
                    continue
                for td in troot.iterdir():
                    if not td.is_dir():
                        continue
                    raw = self._read_json(td / "meta.json", None)
                    if isinstance(raw, dict):
                        t = TaskMeta.from_dict(raw)
                        if project_id and t.project_id != project_id:
                            continue
                        tasks.append(t)
            tasks.sort(key=lambda x: x.updated_at, reverse=True)
            return tasks

    def append_event(
        self,
        umo: str,
        task_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        allow_terminal: bool = False,
    ) -> dict[str, Any] | None:
        """O(1) append-only JSONL writer for journal/message/usage/log events."""
        with self._lock:
            if self.is_ended(task_id) and not allow_terminal:
                return None
            record = {
                "event_id": new_id("ev"),
                "kind": kind,
                "time": now_iso(),
                **self.redact_secrets(payload),
            }
            path = self.task_events_path(umo, task_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            return record

    def read_events(
        self,
        umo: str,
        task_id: str,
        *,
        kind: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        path = self.task_events_path(umo, task_id)
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8-sig") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if kind and item.get("kind") != kind:
                        continue
                    rows.append(item)
        except OSError:
            return []
        return rows[-limit:] if limit > 0 else rows

    def latest_journal_by_call(self, umo: str, task_id: str) -> list[dict[str, Any]]:
        """Fold append-only journal events by call_id into ordered call states."""
        events = self.read_events(umo, task_id, kind="journal", limit=0)
        ordered_ids: list[str] = []
        by_id: dict[str, dict[str, Any]] = {}
        for ev in events:
            cid = str(ev.get("call_id") or ev.get("event_id"))
            if cid not in by_id:
                ordered_ids.append(cid)
                by_id[cid] = dict(ev)
            else:
                by_id[cid].update(ev)
        return [by_id[cid] for cid in ordered_ids]

    def save_tool_result(self, umo: str, task_id: str, call_id: str, raw_text: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(call_id or new_id("call")))
        path = self.task_tool_results_dir(umo, task_id) / f"{safe_id}.txt"
        clean = str(self.redact_secrets(raw_text or ""))
        self._write_text(path, clean)
        return path

    def task_files_manifest(self, umo: str, task_id: str) -> list[dict[str, Any]]:
        tdir = self.task_dir(umo, task_id)
        if not tdir.exists():
            return []
        out: list[dict[str, Any]] = []
        for p in sorted(tdir.rglob("*")):
            if p.is_file():
                try:
                    st = p.stat()
                    out.append(
                        {
                            "rel_path": str(p.relative_to(self.root)).replace("\\", "/"),
                            "name": p.name,
                            "bytes": st.st_size,
                        }
                    )
                except OSError:
                    pass
        return out[:200]

    def read_task_record_preview(self, rel_path: str, max_bytes: int = 24_576) -> dict[str, Any]:
        clean_rel = str(rel_path or "").strip()
        if not clean_rel or "\x00" in clean_rel or Path(clean_rel).is_absolute():
            raise PermissionError("路径越界。")
        target = (self.root / clean_rel).resolve()
        allowed_roots = (self.sessions_dir.resolve(), self.projects_dir.resolve())
        if not any(target.is_relative_to(ar) for ar in allowed_roots):
            raise PermissionError("路径越界：仅允许预览任务与项目记录文件。")
        if not target.is_file():
            raise FileNotFoundError("文件不存在。")
        raw = target.read_bytes()
        truncated = len(raw) > max_bytes
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        return {
            "rel_path": str(target.relative_to(self.root)).replace("\\", "/"),
            "bytes": len(raw),
            "truncated": truncated,
            "content": self.redact_secrets(text),
        }

    # ── Storage Stats & Two-Step Safe Cleanup ────────────────────────────────

    def storage_stats(self) -> dict[str, Any]:
        projects = self.list_projects()
        per_project: list[dict[str, Any]] = []
        total_bytes = 0
        total_tasks = 0
        for proj in projects:
            ptasks = self.list_tasks(project_id=proj.project_id)
            pbytes = _dir_size(self.project_dir(proj.project_id))
            cache_bytes = 0
            for t in ptasks:
                tdir = self.task_dir(t.umo, t.task_id)
                pbytes += _dir_size(tdir)
                cache_bytes += _dir_size(tdir / "tool_results") + _dir_size(tdir / "wake_inputs") + _dir_size(tdir / "handoffs")
            total_bytes += pbytes
            total_tasks += len(ptasks)
            per_project.append(
                {
                    "project_id": proj.project_id,
                    "title": proj.title,
                    "tasks": len(ptasks),
                    "bytes": pbytes,
                    "cache_bytes": cache_bytes,
                }
            )
        return {
            "total_projects": len(projects),
            "total_tasks": total_tasks,
            "total_bytes": total_bytes,
            "projects": per_project,
        }

    def cleanup_preview(self, scope: str, *, project_id: str = "", task_id: str = "") -> dict[str, Any]:
        """Step 1 of safe cleanup: list affected paths & bytes and issue a 5-min confirm token."""
        paths: list[Path] = []
        if scope == "task_cache" and task_id:
            task = self.find_task_by_id(task_id)
            if not task:
                raise ValueError("任务不存在。")
            tdir = self.task_dir(task.umo, task.task_id)
            paths = [p for p in (tdir / "tool_results", tdir / "wake_inputs", tdir / "handoffs") if p.exists()]
        elif scope == "task_history" and task_id:
            task = self.find_task_by_id(task_id)
            if not task:
                raise ValueError("任务不存在。")
            if task.status == "running":
                raise ValueError("运行中的任务不能删除历史，请先停止。")
            paths = [self.task_dir(task.umo, task.task_id)]
        elif scope == "project_cache" and project_id:
            for t in self.list_tasks(project_id=project_id):
                tdir = self.task_dir(t.umo, t.task_id)
                for sub in ("tool_results", "wake_inputs", "handoffs"):
                    if (tdir / sub).exists():
                        paths.append(tdir / sub)
        elif scope == "project" and project_id:
            for t in self.list_tasks(project_id=project_id):
                if t.status == "running":
                    raise ValueError("项目下存在运行中的任务，请先停止。")
                paths.append(self.task_dir(t.umo, t.task_id))
            paths.append(self.project_dir(project_id))
        else:
            raise ValueError(f"不支持的清理范围: {scope}")

        total_bytes = sum(_dir_size(p) for p in paths)
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._cleanup_tokens[token] = {
                "scope": scope,
                "project_id": project_id,
                "task_id": task_id,
                "paths": [str(p) for p in paths],
                "expires_at": time.time() + 300,
            }
        return {
            "token": token,
            "scope": scope,
            "bytes": total_bytes,
            "path_count": len(paths),
            "paths": [str(p.relative_to(self.root)).replace("\\", "/") for p in paths if p.exists()],
        }

    def cleanup_confirm(self, token: str) -> dict[str, Any]:
        """Step 2 of safe cleanup: verify single-use token and remove target paths."""
        with self._lock:
            entry = self._cleanup_tokens.pop(token, None)
            if not entry or time.time() > entry["expires_at"]:
                raise ValueError("清理确认令牌无效或已过期，请重新预览。")
            removed_bytes = 0
            for sp in entry["paths"]:
                p = Path(sp)
                if not p.exists():
                    continue
                removed_bytes += _dir_size(p)
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    try:
                        p.unlink()
                    except OSError:
                        pass
            scope = entry["scope"]
            if scope == "task_history" and entry.get("task_id"):
                idx = self._projects_index()
                idx["tasks"].pop(entry["task_id"], None)
                self._write_json(self.projects_index_path, idx)
            elif scope == "project" and entry.get("project_id"):
                pid = entry["project_id"]
                idx = self._projects_index()
                idx["projects"] = [p for p in idx["projects"] if p.get("project_id") != pid]
                idx["tasks"] = {tid: info for tid, info in idx["tasks"].items() if info.get("project_id") != pid}
                idx["selected"] = {u: p for u, p in idx["selected"].items() if p != pid}
                self._write_json(self.projects_index_path, idx)
            return {"ok": True, "scope": scope, "removed_bytes": removed_bytes}
