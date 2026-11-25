"""Offline v0.3.4 context/cache benchmarks; no provider, bridge or live bot.

Run: python -B scripts/ui/test_agent_context_benchmark.py
Only this script's authorized JSON report persists; all projects and cache data
use TemporaryDirectory. Token counts are UTF-8 byte estimates, never API usage.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import platform
import socket
import statistics
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/validation/v0.3.4-context-benchmark.json"
# Load real modules without starting the AstrBot package or importing peer tests.
PACKAGE = "context_benchmark_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package
V = importlib.import_module(PACKAGE + ".context_views")
R = importlib.import_module(PACKAGE + ".read_cache")
Storage = importlib.import_module(PACKAGE + ".storage").AgentLabStorage
RESULTS = []


def encoded(value):
    return json.dumps(value, ensure_ascii=False)


def size(value):
    text = encoded(value)
    byte_count = len(text.encode("utf-8"))
    return {"chars": len(text), "utf8_bytes": byte_count,
            "estimated_tokens": max(1, math.ceil(byte_count / 3))}


def measure(operation, repeats=7):
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = operation()
        samples.append((time.perf_counter() - start) * 1000)
    return result, {"repeats": repeats, "min_ms": round(min(samples), 4),
                    "median_ms": round(statistics.median(samples), 4),
                    "max_ms": round(max(samples), 4)}


def source_hashes():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
            for name in ("agent_lab/context_views.py", "agent_lab/read_cache.py",
                         "scripts/ui/test_agent_context_benchmark.py")}


class Message:
    """Small provider message adapter to exercise the real model round trip."""
    def __init__(self, row):
        self.row = row

    def model_dump(self):
        return self.row

    @classmethod
    def model_validate(cls, row):
        return cls(row)


class ContextBenchmark(unittest.TestCase):
    def setUp(self):
        self.started = time.perf_counter()
        self.metrics = {}
        self.temp = tempfile.TemporaryDirectory(prefix="agent-context-benchmark-")
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "projects"
        self.workspace.mkdir()
        self.storage = Storage(Path(self.temp.name) / "data")
        self.config = {"provider_settings": {"computer_use_runtime": "local"}}
        self.owner = S(storage=self.storage, _context_config=lambda umo: self.config)
        self.task = S(umo="offline:benchmark", task_id="task_context_benchmark",
                      workflow_data={"task_control": {"version": 1, "approved_version": 1,
                          "authorization_version": 1, "scope_roots": [str(self.workspace)],
                          "execution_settings": {"mode": "full", "roots": [str(self.workspace)]},
                          "journal": []}})
        self.cache = R.ReadCache(self.owner)
        self.sequence = 0
        for name in ("connect", "connect_ex"):
            guard = patch.object(socket.socket, name, side_effect=AssertionError("offline benchmark forbids network"))
            guard.start()
            self.addCleanup(guard.stop)

    def tearDown(self):
        RESULTS.append({"scenario": self._testMethodName,
                        "elapsed_ms": round((time.perf_counter() - self.started) * 1000, 3),
                        "observations": self.metrics})

    def file(self, name="source.py", lines=1617, newline="\n", final_newline=True):
        path = self.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = newline.join(f"line_{i:04d} = '临时项目第{i}行: 业务逻辑与验证'" for i in range(lines))
        if final_newline:
            text += newline
        path.write_bytes(text.encode("utf-8"))
        return path

    @staticmethod
    def read_lines(path, start, end):
        with path.open(encoding="utf-8", newline="") as handle:
            return "".join(handle.read().splitlines(keepends=True)[start:end])

    def read(self, path, start, limit, *, verify=True):
        """Simulate only the executor contract; plan/commit/storage are real."""
        self.sequence += 1
        arguments = {"path": str(path), "offset": start, "limit": limit}
        cache = R.ReadCache(self.owner)  # New object models a resumed round.
        begun = time.perf_counter()
        plan = cache.plan(self.task, arguments)
        plan_ms = (time.perf_counter() - begun) * 1000
        self.assertIsNotNone(plan)
        selected, ranges = [], []
        fresh_chars = reused_chars = 0
        executor_ms = 0.0
        for piece in plan["pieces"]:
            if piece["text"] is None:
                begun = time.perf_counter()
                text = self.read_lines(path, piece["start"], piece["end"])
                executor_ms += (time.perf_counter() - begun) * 1000
                ranges.append([piece["start"], piece["end"]])
                fresh_chars += len(text)
                plan["new_entries"].append({**piece, "text": text})
            else:
                text = piece["text"]
                reused_chars += len(text)
            selected.append(text)
        begun = time.perf_counter()
        cache.commit(self.task, plan, "call_benchmark_" + str(self.sequence))
        commit_ms = (time.perf_counter() - begun) * 1000
        output = "".join(selected)
        if verify:
            self.assertEqual(output, self.read_lines(path, start, start + min(limit, R.READ_LINES)))
        return output, {"offset": start, "requested_limit": limit,
                        "new_read_ranges": ranges, "executor_calls": len(ranges),
                        "fresh_output_chars": fresh_chars, "reused_output_chars": reused_chars,
                        "output_chars": len(output), "plan_ms": round(plan_ms, 4),
                        "commit_ms": round(commit_ms, 4), "executor_ms": round(executor_ms, 4)}

    def entries(self):
        return self.storage._read_json(self.cache.directory(self.task) / "index.json")["entries"]

    def test_simulated_projects_1617_lines_multiple_rounds(self):
        projects = []
        for label, name, newline, final_newline in (
                ("web_dashboard", "dashboard/src/page.tsx", "\r\n", True),
                ("python_service", "service/app.py", "\n", True),
                ("chinese_documentation", "docs/说明.md", "\r\n", False)):
            path = self.file(name, newline=newline, final_newline=final_newline)
            # Real syntax/content differs by project; all retain exactly 1617 lines.
            lines = self.read_lines(path, 0, 1617).splitlines(keepends=True)
            if label == "web_dashboard":
                lines = [f"export const item{i} = {{label: '界面{i}', enabled: true}};{newline}" for i in range(1617)]
            elif label == "chinese_documentation":
                lines = [f"- 验证项 {i}：记录范围、证据与未完成工作。{newline}" for i in range(1617)]
                lines[-1] = lines[-1].rstrip("\r\n")
            path.write_bytes("".join(lines).encode("utf-8"))
            pages = [(offset, 120) for offset in range(0, 1617, 120)]
            rounds = [[(0, 100), (70, 80), (20, 50)],
                      [(0, 350), *pages[1:]],
                      [*pages, (1580, 100), (1617, 120), (1700, 10), (40, 120)],
                      [(0, 100), (70, 80), (20, 50), (1580, 100), (1617, 120)]]
            history, round_metrics = [{"role": "user", "content": f"模拟{label}，保留原始证据。"}], []
            expected, baseline_chars = [], 0
            baseline_started = time.perf_counter()
            for start, limit in [request for requests in rounds for request in requests]:
                output = self.read_lines(path, start, start + min(limit, 120))
                expected.append(output)
                baseline_chars += len(output)
            baseline_ms = (time.perf_counter() - baseline_started) * 1000
            actual, all_requests = [], []
            for round_number, requests in enumerate(rounds, 1):
                records = []
                for offset, limit in requests:
                    output, row = self.read(path, offset, limit, verify=False)
                    actual.append(output)
                    records.append(row)
                    call_id = f"{label}_{round_number}_{len(records)}"
                    history.extend([
                        {"role": "assistant", "content": "检查当前范围", "tool_calls": [
                            {"id": call_id, "function": {"name": "astrbot_file_read_tool",
                             "arguments": encoded({"path": str(path), "offset": offset, "limit": limit})}}]},
                        {"role": "tool", "tool_call_id": call_id,
                         "content": output + f"\n[任务工具证据 ID: call_{call_id}; status=completed]"}])
                raw_copy = copy.deepcopy(history)
                view, view_time = measure(lambda: V.history_view(history, self.task))
                summary, summary_time = measure(lambda: V.history_view(history, self.task, for_summary=True))
                self.assertEqual(history, raw_copy)
                self.assertEqual([r.get("tool_call_id") for r in view], [r.get("tool_call_id") for r in history])
                self.assertEqual(V.history_view(view, self.task), view)
                self.assertLess(size(summary)["chars"], size(history)["chars"])
                if round_number >= 3:
                    self.assertEqual(sum(r["executor_calls"] for r in records), 0)
                round_metrics.append({"round": round_number, "requests": records,
                                      "raw_context": size(history), "provider_context": size(view),
                                      "summary_context": size(summary), "provider_view_time": view_time,
                                      "summary_view_time": summary_time})
                all_requests.extend(records)
            self.assertEqual(actual, expected)
            self.assertEqual(all_requests[1]["new_read_ranges"], [[100, 150]])
            self.assertEqual(all_requests[2]["executor_calls"], 0)
            fresh = sum(row["fresh_output_chars"] for row in all_requests)
            self.assertEqual(fresh, len("".join(lines)))
            calls = sum(row["executor_calls"] for row in all_requests)
            self.assertLess(calls, len(all_requests))
            projects.append({"project": label, "source_lines": len(lines), "source_chars": len("".join(lines)),
                             "newline": repr(newline), "final_newline": final_newline,
                             "baseline_executor_calls": len(expected), "cached_executor_calls": calls,
                             "avoided_executor_calls": len(expected) - calls,
                             "baseline_output_chars": baseline_chars, "fresh_output_chars": fresh,
                             "avoided_fresh_output_chars": baseline_chars - fresh,
                             "baseline_local_read_ms": round(baseline_ms, 4),
                             "cached_local_total_ms": round(sum(row["plan_ms"] + row["commit_ms"] + row["executor_ms"] for row in all_requests), 4),
                             "rounds": round_metrics})
        self.metrics["simulated_projects"] = projects

    def test_sparse_overlap_reads_only_missing_ranges(self):
        path = self.file()
        self.read(path, 0, 30)
        self.read(path, 60, 30)
        _, row = self.read(path, 10, 90)
        self.assertEqual(row["new_read_ranges"], [[30, 60], [90, 100]])
        self.assertEqual(sum(end - start for start, end in row["new_read_ranges"]), 40)
        self.metrics.update(row)

    def test_nested_arguments_are_bounded_without_stringifying_raw_payload(self):
        class NoStringDict(dict):
            def __str__(self):
                raise AssertionError("raw nested payload must not be stringified")
        arguments = {f"key_{i}": NoStringDict({f"branch_{n}": ["嵌套" * 1000] * 20 for n in range(30)}) for i in range(16)}
        deep = {"leaf": "深层内容" * 1000}
        for _ in range(80):
            deep = {"next": deep}
        arguments["key_0"] = NoStringDict({"deep": deep, **arguments["key_0"]})
        original = copy.deepcopy(arguments)
        view, timing = measure(lambda: V.arguments_view(arguments))
        self.assertEqual(arguments, original)
        self.assertLess(len(encoded(view)), 3500)
        self.assertNotIn("嵌套" * 100, encoded(view))
        self.metrics.update(raw=size(arguments), bounded=size(view), time=timing, nested_depth=80)

    def test_signatures_preserved_for_provider_and_removed_for_summary(self):
        fields = ("reasoning_signature", "signature", "encrypted", "extra_content")
        cases = []
        for position in ("row", "call", "function", "content"):
            for field in fields:
                token = f"PRIVATE_{position}_{field}_" + "签名" * 300
                call = {"id": "signed", "function": {"name": "astrbot_file_edit_tool",
                        "arguments": encoded({"path": "source.py", "old": "a" * 12000, "new": "b" * 14000})}}
                row = {"role": "assistant", "content": [{"type": "text", "text": "保留业务说明"}], "tool_calls": [call]}
                target = {"row": row, "call": call, "function": call["function"], "content": row["content"][0]}[position]
                target[field] = {"provider": token} if field == "extra_content" else token
                history = [row, {"role": "tool", "tool_call_id": "signed", "content": "edited"}]
                original = copy.deepcopy(history)
                with self.subTest(position=position, field=field):
                    provider = V.history_view(history)
                    summary = V.history_view(history, for_summary=True)
                    self.assertEqual(provider[0], original[0])
                    self.assertEqual(history, original)
                    self.assertNotIn(token, encoded(summary))
                    self.assertIn("保留业务说明", encoded(summary))
                cases.append({"position": position, "field": field})
        self.metrics["signature_cases"] = cases

    def test_completed_pending_calls_models_and_multimodal_content(self):
        def assistant(identifier):
            return {"role": "assistant", "tool_calls": [{"id": identifier, "function": {
                "name": "astrbot_file_write_tool", "arguments": encoded({"path": "a.py", "content": "源代码" * 10000})}}],
                "content": [{"type": "thinking", "thinking": "私有思考" * 100},
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                            {"type": "text", "text": "仍有待验证项"}]}
        history = [assistant("completed"), {"role": "tool", "tool_call_id": "completed", "content": "written"}, assistant("pending")]
        models = [Message(row) for row in history]
        provider = V.history_view(models)
        summary = V.history_view(models, for_summary=True)
        self.assertTrue(all(isinstance(row, Message) for row in provider))
        self.assertLess(len(provider[0].row["tool_calls"][0]["function"]["arguments"]), 1000)
        self.assertEqual(provider[-1].row, history[-1])
        self.assertEqual(provider[0].row["content"], history[0]["content"])
        self.assertNotIn("私有思考", encoded(summary))
        self.assertIn("媒体内容见原始记录", encoded(summary))
        self.assertEqual([m.row for m in models], history)
        self.metrics.update(raw=size(history), summary=size(summary), pending_call_preserved=True)

    def test_malformed_and_non_object_tool_arguments(self):
        cases = ["null", "[]", '"text"', "42", "{broken", {"command": "pwd"}]
        for arguments in cases:
            with self.subTest(arguments=arguments):
                history = [{"role": "assistant", "tool_calls": [{"id": "bad", "function": {
                    "name": "astrbot_execute_shell", "arguments": arguments}}]},
                    {"role": "tool", "tool_call_id": "bad", "content": "result\n" * 1000}]
                original = copy.deepcopy(history)
                self.assertEqual(len(V.history_view(history)), 2)
                self.assertEqual(len(V.history_view(history, for_summary=True)), 2)
                self.assertEqual(history, original)
        self.metrics["argument_shapes"] = len(cases)

    def test_evidence_lookup_is_lazy_and_repeated_views_are_stable(self):
        class NoJournalIteration(list):
            def __iter__(self):
                raise AssertionError("embedded IDs must not inspect the full journal")
            def __reversed__(self):
                raise AssertionError("embedded IDs must not inspect the full journal")
        arguments = {"path": "source.py", "offset": 0, "limit": 120}
        history = [{"role": "assistant", "tool_calls": [{"id": "read", "function": {
            "name": "astrbot_file_read_tool", "arguments": encoded(arguments)}}]},
            {"role": "tool", "tool_call_id": "read", "content": "源代码\n" * 4000 + "\n[任务工具证据 ID: call_exact; status=completed]"}]
        self.task.workflow_data["task_control"]["journal"] = NoJournalIteration([{"arguments": {"new": "huge" * 10000}}] * 1000)
        original = copy.deepcopy(history)
        view, timing = measure(lambda: V.history_view(history, self.task))
        self.assertIn('"evidence_id": "call_exact"', view[1]["content"])
        for _ in range(60):
            self.assertEqual(V.history_view(view, self.task), view)
        self.assertEqual(history, original)
        self.task.workflow_data["task_control"]["journal"] = [{"id": "call_legacy", "name": "astrbot_file_read_tool", "arguments": arguments}]
        history[1]["content"] = "legacy\n" * 4000
        self.assertIn('"evidence_id": "call_legacy"', V.history_view(history, self.task)[1]["content"])
        self.metrics.update(raw=size(original), provider=size(view), time=timing, repeated_passes=60)

    def test_short_outputs_never_grow(self):
        for chars in (499, 500, 700, 1200, 3000):
            history = [{"role": "assistant", "tool_calls": [{"id": "read", "function": {
                "name": "astrbot_file_read_tool", "arguments": encoded({"path": "x.py"})}}]},
                {"role": "tool", "tool_call_id": "read", "content": "x" * chars}]
            with self.subTest(chars=chars):
                self.assertLessEqual(size(V.history_view(history))["chars"], size(history)["chars"])
        self.metrics["output_lengths"] = [499, 500, 700, 1200, 3000]

    def test_corrupt_index_shapes_recover_for_plan_and_commit(self):
        path = self.file()
        index_path = self.cache.directory(self.task) / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        cases = [b'{"entries":', b'\xff\xfe', b'[]', b'null', b'{"entries": null}',
                 b'{"entries": 3}', b'{"entries": "oops"}', b'{"entries": {}}']
        for payload in cases:
            with self.subTest(payload=repr(payload)):
                index_path.write_bytes(payload)
                plan = self.cache.plan(self.task, {"path": str(path), "offset": 0, "limit": 10})
                self.assertEqual(plan["pieces"], [{"start": 0, "end": 10, "text": None}])
                plan["new_entries"].append({"start": 0, "end": 10, "text": self.read_lines(path, 0, 10)})
                index_path.write_bytes(payload)  # Also exercise independent commit loading.
                self.cache.commit(self.task, plan, "call_recovery")
                self.assertEqual(len(self.entries()), 1)
        self.metrics["corrupt_index_cases"] = len(cases)

    def test_corrupt_cached_text_is_never_reused(self):
        path = self.file()
        cases = ("same_line_count", "truncated", "invalid_utf8", "missing", "missing_hash")
        for case in cases:
            with self.subTest(case=case):
                self.storage._write_json(self.cache.directory(self.task) / "index.json", {"entries": []})
                self.read(path, 0, 30)
                entry = self.entries()[0]
                cached = self.cache.directory(self.task) / (entry["key"] + ".txt")
                if case == "same_line_count":
                    cached.write_bytes(("poisoned\n" * 30).encode())
                elif case == "truncated":
                    cached.write_bytes(b"truncated\n")
                elif case == "invalid_utf8":
                    cached.write_bytes(b"\xff\xfe")
                elif case == "missing":
                    cached.unlink()
                else:
                    entry.pop("sha256")
                    self.storage._write_json(cached.parent / "index.json", {"entries": [entry]})
                _, row = self.read(path, 5, 20)
                self.assertEqual(row["new_read_ranges"], [[5, 25]])
        self.metrics["corrupt_body_cases"] = list(cases)

    def test_corrupt_eof_cannot_hide_unread_lines(self):
        path = self.file(lines=1617)
        self.read(path, 1580, 100)
        entry = self.entries()[0]
        cached = self.cache.directory(self.task) / (entry["key"] + ".txt")
        # The EOF marker must be validated even for a query outside its range.
        cached.write_bytes(b"damaged\n")
        plan = self.cache.plan(self.task, {"path": str(path), "offset": 1620, "limit": 30})
        self.assertEqual(plan["end"], 1650)
        self.assertEqual(plan["pieces"], [{"start": 1620, "end": 1650, "text": None}])
        entry["end"] = 1581
        self.storage._write_json(cached.parent / "index.json", {"entries": [entry]})
        output, row = self.read(path, 1600, 30)
        self.assertEqual(output, self.read_lines(path, 1600, 1617))
        self.assertEqual(row["new_read_ranges"], [[1600, 1630]])
        self.metrics["untrusted_eof_ignored"] = True

    def test_invalid_entry_metadata_and_oversized_tool_results(self):
        path = self.file()
        self.read(path, 0, 30)
        valid = self.entries()[0]
        cases = [{"start": True}, {"end": True}, {"start": -1}, {"end": 0},
                 {"key": "../escape"}, {"evidence_id": 7}, {"eof": "yes"}, {"end": 3000}]
        for changes in cases:
            with self.subTest(changes=changes):
                entry = {**valid, **changes}
                self.storage._write_json(self.cache.directory(self.task) / "index.json", {"entries": [entry]})
                plan = self.cache.plan(self.task, {"path": str(path), "offset": 0, "limit": 10})
                self.assertTrue(all(piece["text"] is None for piece in plan["pieces"]))
        self.storage._write_json(self.cache.directory(self.task) / "index.json", {"entries": []})
        plan = self.cache.plan(self.task, {"path": str(path), "offset": 0, "limit": 3})
        plan["new_entries"] = [{"start": 0, "end": 3, "text": self.read_lines(path, 0, 8)}]
        self.cache.commit(self.task, plan, "call_oversized")
        self.assertEqual(self.entries(), [])
        self.metrics.update(invalid_metadata_cases=len(cases), oversized_result_not_cached=True)

    def test_policy_file_changes_and_mid_read_race_invalidate(self):
        path = self.file()
        self.read(path, 0, 30)
        state = self.task.workflow_data["task_control"]
        initial = copy.deepcopy(state)
        changes = [(state, "version", 2), (state, "approved_version", 2),
                   (state, "authorization_version", 2), (state, "authorized_scope_roots", []),
                   (state, "scope_roots", []), (state, "risk_lines", ["new guard"])]
        for target, key, value in changes:
            with self.subTest(policy=key):
                state.clear()
                state.update(copy.deepcopy(initial))
                target[key] = value
                self.assertIsNone(self.cache.plan(self.task, {"path": str(path), "limit": 10})["pieces"][0]["text"])
        for key, value in (("mode", "readonly"), ("roots", []), ("warnings", ["changed"])):
            with self.subTest(execution=key):
                state.clear()
                state.update(copy.deepcopy(initial))
                state["execution_settings"][key] = value
                self.assertIsNone(self.cache.plan(self.task, {"path": str(path), "limit": 10})["pieces"][0]["text"])
        state.clear()
        state.update(initial)
        self.config["provider_settings"]["filesystem_scope"] = "none"
        self.assertIsNone(self.cache.plan(self.task, {"path": str(path), "limit": 10})["pieces"][0]["text"])
        self.config["provider_settings"].pop("filesystem_scope")
        plan = self.cache.plan(self.task, {"path": str(path), "offset": 50, "limit": 10})
        plan["new_entries"] = [{"start": 50, "end": 60, "text": self.read_lines(path, 50, 60)}]
        path.write_bytes(b"changed\n" + path.read_bytes())
        before = copy.deepcopy(self.entries())
        self.cache.commit(self.task, plan, "call_stale")
        self.assertEqual(self.entries(), before)
        self.assertIsNone(self.cache.plan(self.task, {"path": str(path), "limit": 10})["pieces"][0]["text"])
        _, row = self.read(path, 0, 10)
        path.unlink()
        self.assertIsNone(self.cache.plan(self.task, {"path": str(path)}))
        self.file(lines=2)
        output, _ = self.read(path, 0, 10)
        self.assertEqual(len(output.splitlines()), 2)
        self.metrics.update(policy_mutations=10, stale_commit_rejected=True, reread=row, deletion_recreation_verified=True)

    def test_task_isolation_remote_runtime_and_invalid_ranges(self):
        path = self.file()
        self.read(path, 0, 30)
        self.assertEqual(self.cache.version(self.task, {"path": path.name}, self.workspace),
                         self.cache.version(self.task, {"path": str(path)}))
        self.assertIsNone(self.cache.plan(self.task, {"path": path.name}))
        for arguments in ({"offset": True}, {"offset": -1}, {"offset": "2"},
                          {"limit": True}, {"limit": 0}, {"limit": -2}, {"limit": 1.5}):
            self.assertIsNone(self.cache.plan(self.task, {"path": str(path), **arguments}))
        for runtime in ("remote", "sandbox", None):
            self.config["provider_settings"]["computer_use_runtime"] = runtime
            self.assertIsNone(self.cache.plan(self.task, {"path": str(path)}))
        self.config["provider_settings"]["computer_use_runtime"] = "local"
        binary = self.workspace / "image.png"
        binary.write_bytes(b"not a text source")
        self.assertIsNone(self.cache.plan(self.task, {"path": str(binary)}))
        self.task.task_id = "task_other_project"
        _, row = self.read(path, 0, 20)
        self.assertEqual(row["executor_calls"], 1)
        self.metrics.update(invalid_range_cases=7, disabled_runtime_cases=3, task_isolation=True)

    def test_valid_eof_crlf_and_entry_retention(self):
        path = self.file(lines=1617, newline="\r\n", final_newline=False)
        output, first = self.read(path, 1580, 120)
        self.assertEqual(len(output.splitlines()), 37)
        self.assertIn("\r\n", output)
        self.assertNotIn("\r\r\n", output)
        output, repeated = self.read(path, 1600, 80)
        self.assertEqual(repeated["executor_calls"], 0)
        self.assertEqual(len(output.splitlines()), 17)
        _, beyond = self.read(path, 1700, 10)
        self.assertEqual(beyond["executor_calls"], 0)
        for _ in range(165):
            plan = self.cache.plan(self.task, {"path": str(path), "offset": 0, "limit": 1})
            self.sequence += 1
            plan["new_entries"] = [{"start": 0, "end": 1, "text": self.read_lines(path, 0, 1)}]
            self.cache.commit(self.task, plan, f"call_retention_{self.sequence}")
        self.assertEqual(len(self.entries()), 160)
        self.metrics.update(initial=first, reused=repeated, beyond_eof=beyond, retained_entries=160)

    def test_full_hits_do_not_rewrite_cache_index(self):
        path = self.file()
        self.read(path, 0, 120)
        index_path = self.cache.directory(self.task) / "index.json"
        before = index_path.read_bytes()
        with patch.object(self.storage, "_write_json", side_effect=AssertionError("cache hit rewrote index")):
            (output, row), timing = measure(lambda: self.read(path, 10, 20), repeats=7)
        self.assertEqual(row["executor_calls"], 0)
        self.assertEqual(output, self.read_lines(path, 10, 30))
        self.assertEqual(index_path.read_bytes(), before)
        self.metrics.update(reused=row, local_reuse_time=timing, cache_index_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-report", action="store_true")
    args, unittest_args = parser.parse_known_args()
    RESULTS.clear()
    start_hashes = source_hashes()
    started = time.perf_counter()
    program = unittest.main(argv=[sys.argv[0], *unittest_args], exit=False, verbosity=2)
    result = program.result
    end_hashes = source_hashes()
    failures = [{"test": str(test), "traceback": trace} for test, trace in [*result.failures, *result.errors]]
    for row in RESULTS:
        row["status"] = "failed" if any(row["scenario"] in failure["test"] for failure in failures) else "passed"
    projects = [project for row in RESULTS for project in row["observations"].get("simulated_projects", [])]
    report = {"schema_version": 1, "target_release": "v0.3.4",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "command": "python -B scripts/ui/test_agent_context_benchmark.py",
              "python": platform.python_version(), "platform": platform.platform(),
              "simulation": True, "real_api_calls": 0,
              "scope": "real context_views, ReadCache and AgentLabStorage; temporary projects; simulated executor contract; no bridge/continuity/task_control execution",
              "measurement_notes": {
                  "time": "time.perf_counter wall time; milliseconds; local disk/cache work only; no model latency or production speed claim",
                  "chars": "Unicode code points of json.dumps(ensure_ascii=False), unless field explicitly names source/output chars",
                  "estimated_tokens": "ceil(serialized UTF-8 bytes / 3), minimum 1; heuristic only; no tokenizer, API usage, billing or monetary costs",
                  "baseline": "same capped line requests read from disk without cache; cached path includes plan, executor and commit; local cache can cost more wall time while avoiding executor calls",
                  "rounds": "scripted requests and synthetic messages, no model-generated decisions; a new ReadCache instance per request tests persistent reuse",
                  "repeat_timing": "seven samples including first call, median/min/max; no brittle absolute speed threshold",
              },
              "summary": {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
                          "passed": sum(row["status"] == "passed" for row in RESULTS),
                          "successful": result.wasSuccessful(), "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                          "simulated_projects": len(projects), "simulated_rounds": sum(len(p["rounds"]) for p in projects),
                          "baseline_executor_calls": sum(p["baseline_executor_calls"] for p in projects),
                          "cached_executor_calls": sum(p["cached_executor_calls"] for p in projects),
                          "baseline_output_chars": sum(p["baseline_output_chars"] for p in projects),
                          "fresh_output_chars": sum(p["fresh_output_chars"] for p in projects)},
              "source_sha256_at_start": start_hashes, "source_sha256_at_end": end_hashes,
              "sources_unchanged_during_run": start_hashes == end_hashes,
              "scenarios": RESULTS, "failures": failures}
    if not args.no_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("Report: " + str(REPORT))
    return 0 if result.wasSuccessful() and start_hashes == end_hashes else 1


if __name__ == "__main__":
    raise SystemExit(main())
