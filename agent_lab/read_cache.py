"""Versioned, line-range cache for host-local text reads; no extra file access."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

TEXT_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".html", ".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh", ".ps1", ".csv", ".xml", ".sql"}
READ_LINES = 120


class ReadCache:
    def __init__(self, owner):
        self.owner = owner

    def directory(self, task):
        return self.owner.storage.task_memory_dir(task.umo, task.task_id) / "read_cache"

    def _entries(self, task):
        try:
            payload = self.owner.storage._read_json(self.directory(task) / "index.json")
        except (OSError, ValueError):
            return []
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        return [entry for entry in entries[-160:] if isinstance(entry, dict)
                and isinstance(entry.get("version"), dict)
                and isinstance(entry.get("key"), str) and re.fullmatch(r"[a-f0-9]{24}", entry["key"])
                and type(entry.get("start")) is int and type(entry.get("end")) is int
                and 0 <= entry["start"] < entry["end"] <= entry["start"] + READ_LINES
                and type(entry.get("eof")) is bool
                and isinstance(entry.get("evidence_id"), str) and entry["evidence_id"]
                and isinstance(entry.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", entry["sha256"])]

    def _lines(self, task, entry):
        directory = self.directory(task)
        path = directory / f"{entry['key']}.txt"
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                return None
            with path.open(encoding="utf-8", newline="") as handle:
                text = handle.read()
            lines = text.splitlines(keepends=True)
            if (len(lines) != entry["end"] - entry["start"]
                    or entry["sha256"] != hashlib.sha256(text.encode("utf-8")).hexdigest()):
                return None
            return lines
        except (OSError, ValueError):
            return None

    def version(self, task, arguments, cwd=None):
        cfg = self.owner._context_config(task.umo) or {}
        if cfg.get("provider_settings", {}).get("computer_use_runtime") != "local":
            return None
        path = Path(str(arguments.get("path", "")))
        if not path.is_absolute():
            if not cwd:
                return None
            path = Path(cwd) / path
        try:
            path = path.resolve()
            if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                return None
            stat = path.stat()
            state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
            settings = state.get("execution_settings", {})
            policy = {"context": cfg, "task": {key: state.get(key) for key in (
                "version", "approved_version", "authorization_version", "authorized_scope_roots", "scope_roots", "risk_lines")},
                "execution": {key: settings.get(key) for key in ("mode", "roots", "warnings")}}
            return {"format": 2, "path": str(path), "size": stat.st_size, "mtime": stat.st_mtime_ns,
                    "ctime": stat.st_ctime_ns, "inode": stat.st_ino,
                    "policy": hashlib.sha256(json.dumps(policy, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()}
        except OSError:
            return None

    def plan(self, task, arguments, cwd=None):
        version = self.version(task, arguments, cwd)
        start, requested = arguments.get("offset", 0), arguments.get("limit")
        if (version is None or not isinstance(start, int) or isinstance(start, bool) or start < 0
                or requested is not None and (not isinstance(requested, int) or isinstance(requested, bool) or requested < 1)):
            return None
        count = min(requested or READ_LINES, READ_LINES)
        end = start + count
        entries = [entry for entry in self._entries(task) if entry["version"] == version]
        loaded = {}
        for entry in list(entries):
            if entry["eof"] and entry["end"] < end:
                # EOF metadata must not suppress a fresh read unless its cached
                # body is valid, even when that body is outside this request.
                lines = self._lines(task, entry)
                if lines is None:
                    entries.remove(entry)
                else:
                    loaded[entry["key"]] = lines
                    end = min(end, max(start, entry["end"]))
        pieces, position = [], start
        while position < end:
            covered = [entry for entry in entries if entry["start"] <= position < entry["end"]]
            if covered:
                entry = max(covered, key=lambda e: e["end"])
                lines = loaded.get(entry["key"])
                if lines is None:
                    lines = self._lines(task, entry)
                if lines is None:
                    entries.remove(entry)
                    continue
                stop = min(end, entry["end"])
                pieces.append({"start": position, "end": stop, "text": "".join(lines[position-entry["start"]:stop-entry["start"]]), "source": entry["evidence_id"]})
            else:
                stop = min([entry["start"] for entry in entries if position < entry["start"] < end] or [end])
                pieces.append({"start": position, "end": stop, "text": None})
            position = stop
        return {"version": version, "arguments": arguments, "cwd": cwd, "start": start, "end": end,
                "pieces": pieces, "limited": requested is None or requested > count, "new_entries": []}

    def commit(self, task, plan, evidence_id):
        if not plan["new_entries"]:
            return  # A full cache hit should not rewrite its on-disk index.
        if self.version(task, plan["arguments"], plan.get("cwd")) != plan["version"]:
            return  # File changed during the read. Never reuse a mixed snapshot.
        directory = self.directory(task)
        index_path = directory / "index.json"
        entries = [entry for entry in self._entries(task)
                   if entry["version"].get("path") != plan["version"]["path"] or entry["version"] == plan["version"]]
        for i, piece in enumerate(plan["new_entries"]):
            text = piece["text"]
            if not text or text.startswith(("Error", "No content found")):
                continue
            count = len(text.splitlines())
            if not (plan["start"] <= piece["start"] < piece["end"] <= plan["end"]
                    and 0 < count <= piece["end"] - piece["start"] <= READ_LINES):
                continue  # Never extend a cached range beyond the requested read.
            key = hashlib.sha256(f"{evidence_id}:{i}".encode()).hexdigest()[:24]
            # Cache exactly the authorized tool output, including CRLF. The
            # generic text writer translates newlines on Windows.
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"{key}.txt"
            temporary = path.with_suffix(".txt.tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            temporary.replace(path)
            entries.append({"key": key, "version": plan["version"], "start": piece["start"],
                            "end": piece["start"] + count, "eof": count < piece["end"] - piece["start"], "evidence_id": evidence_id,
                            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        self.owner.storage._write_json(index_path, {"entries": entries[-160:]})
