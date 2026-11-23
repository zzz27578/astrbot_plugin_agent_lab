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
            return {"path": str(path), "size": stat.st_size, "mtime": stat.st_mtime_ns,
                    "ctime": stat.st_ctime_ns, "inode": stat.st_ino,
                    "policy": hashlib.sha256(json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()}
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
        index_path = self.directory(task) / "index.json"
        entries = self.owner.storage._read_json(index_path).get("entries", []) if index_path.exists() else []
        entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("version") == version
                   and re.fullmatch(r"[a-f0-9]{24}", str(entry.get("key", "")))
                   and isinstance(entry.get("start"), int) and isinstance(entry.get("end"), int)]
        eof = next((entry["end"] for entry in entries if entry.get("eof")), None)
        if eof is not None:
            end = min(end, max(start, eof))
        pieces, position = [], start
        while position < end:
            covered = [entry for entry in entries if entry["start"] <= position < entry["end"]]
            if covered:
                entry = max(covered, key=lambda e: e["end"])
                path = self.directory(task) / f"{entry['key']}.txt"
                try:
                    if path.is_symlink() or not path.resolve().is_relative_to(self.directory(task).resolve()):
                        entries.remove(entry)
                        continue
                    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
                except OSError:
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
        if self.version(task, plan["arguments"], plan.get("cwd")) != plan["version"]:
            return  # File changed during the read. Never reuse a mixed snapshot.
        directory = self.directory(task)
        index_path = directory / "index.json"
        entries = self.owner.storage._read_json(index_path).get("entries", []) if index_path.exists() else []
        entries = [entry for entry in entries if isinstance(entry, dict) and isinstance(entry.get("version"), dict)
                   and (entry["version"].get("path") != plan["version"]["path"] or entry["version"] == plan["version"])]
        for i, piece in enumerate(plan["new_entries"]):
            text = piece["text"]
            if not text or text.startswith(("Error", "No content found")):
                continue
            key = hashlib.sha256(f"{evidence_id}:{i}".encode()).hexdigest()[:24]
            self.owner.storage._write_text(directory / f"{key}.txt", text)
            count = len(text.splitlines())
            entries.append({"key": key, "version": plan["version"], "start": piece["start"],
                            "end": piece["start"] + count, "eof": count < piece["end"] - piece["start"], "evidence_id": evidence_id})
        self.owner.storage._write_json(index_path, {"entries": entries[-160:]})
