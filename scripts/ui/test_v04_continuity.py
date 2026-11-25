"""Offline v0.4 acceptance tests using real task files and executable source.

Run: python -B scripts/ui/test_v04_continuity.py
The provider is a context-driven adapter, not a live LLM. All reads, edits,
archives and verification commands use real files in TemporaryDirectory.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "v04_continuity_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package
C = importlib.import_module(PACKAGE + ".continuity")
Models = importlib.import_module(PACKAGE + ".models")
Storage = importlib.import_module(PACKAGE + ".storage").AgentLabStorage


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class Message:
    """The host's model_dump/model_validate boundary, with no view rewriting."""
    def __init__(self, row):
        self.row = deepcopy(row)

    def model_dump(self):
        return deepcopy(self.row)

    @classmethod
    def model_validate(cls, row):
        return cls(row)


def tool_group(index, content, *, results=1, name="read_file", arguments=None):
    calls = [{"id": f"call_{index}_{n}", "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments or {}, ensure_ascii=False)}} for n in range(results)]
    return [{"role": "assistant", "content": None, "tool_calls": calls}, *[
        {"role": "tool", "tool_call_id": call["id"], "content": content} for call in calls]]


class ContinuityV04Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-lab-v04-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / "data")
        self.project = {"source_umo": "offline:continuity", "execution_settings": {}}
        self.owner = S(storage=self.storage, _redact_known_secrets=lambda text: text,
                       projects=S(cleaning=set(), project=lambda key: self.project,
                                  safe_path=lambda path: Path(path).resolve().is_relative_to(self.storage.root.resolve())))
        self.continuity = C.TaskContinuity(self.owner)
        self.event = S(unified_msg_origin="offline:continuity")
        self.calls = []
        self.new_task()
        stub = patch.dict(sys.modules, {"astrbot.core.agent.message": S(Message=Message)})
        stub.start()
        self.addCleanup(stub.stop)

    def new_task(self):
        self.task = Models.TaskState(umo=self.event.unified_msg_origin, root_goal="修复 normalize 并验证", status="running")
        C.state_of(self.task).update(version=1, input_revision=0, human_paused=False, current_step_id="one",
                                     steps=[{"id": "one", "stage": "inspect", "status": "running", "title": "Inspect"}])
        self.storage.save_task(self.task)
        return self.task

    def load(self):
        return self.storage.load_active_task(self.task.umo)

    def configure(self, **values):
        task = self.load()
        C.state_of(task).setdefault("execution_settings", {}).setdefault("continuity", {}).update(values)
        self.storage.save_task(task)
        self.task = task

    def provider(self, text="继续修复并运行验证。", action=None, limit=0):
        async def chat(**kwargs):
            self.calls.append(deepcopy(kwargs))
            if action:
                result = action(kwargs)
                if hasattr(result, "__await__"):
                    await result
            return S(completion_text=text, usage=S(total=123))
        return S(text_chat=chat, provider_config={"max_context_tokens": limit})

    def manager(self, provider=None, *, limit=1000000, counter=None, lane="", prompt_tokens=0):
        native = S(config=S(max_context_tokens=limit), native_property="delegated")
        if counter:
            native.token_counter = counter
        return C.StageContextManager(self.continuity, self.event, self.task.task_id,
                                     provider or self.provider(), native, lane=lane, prompt_tokens=prompt_tokens)

    def archive(self, lane=""):
        saved = C.lane_state(self.load(), lane)
        return self.storage._read_json(self.storage.root / saved["record_path"])

    async def test_module_import_does_not_require_context_views(self):
        name = "v04_no_context_views"
        package = types.ModuleType(name)
        package.__path__ = [str(ROOT / "agent_lab")]
        with patch.dict(sys.modules, {name: package, name + ".context_views": None}):
            module = importlib.import_module(name + ".continuity")
            self.assertTrue(callable(module.TaskContinuity.compact))

    async def test_history_prefix_stays_byte_identical_before_and_after_compaction(self):
        history = [{"role": "system", "content": "规则保持不变"}, {"role": "user", "content": "继续"},
                   *tool_group(1, "source_line = '完整源码'\n" * 6000)]
        messages = [Message(row) for row in history]
        manager = self.manager()
        sent, snapshots = [], []
        for index in range(4):
            snapshots.append(encoded([m.model_dump() for m in messages]))
            result = await manager.process(messages)
            self.assertIs(result, messages)
            sent.append([m.model_dump() for m in result])
            if index:
                self.assertEqual(encoded(sent[-1][:len(sent[-2])]), encoded(sent[-2]))
            self.assertEqual(encoded([m.model_dump() for m in messages]), snapshots[-1])
            messages.append(Message({"role": "assistant", "content": f"进展 {index}"}))
        self.assertGreater(C.estimate(history), 24000)
        self.assertEqual(self.calls, [])
        self.assertEqual(manager.native_property, "delegated")
        task = self.load()
        C.lane_state(task)["pending_reason"] = "stage_changed"
        self.storage.save_task(task)
        messages = await manager.process(messages)
        self.assertEqual(len(self.calls), 1)
        prefix = [m.model_dump() for m in messages]
        for index in range(3):
            messages.append(Message({"role": "user", "content": f"后续请求 {index}"}))
            self.continuity.begin_round(self.load())
            self.assertIs(await manager.process(messages), messages)
            self.assertEqual(encoded([m.model_dump() for m in messages[:len(prefix)]]), encoded(prefix))
        self.assertEqual(len(self.calls), 1)

    async def test_configured_and_actual_capacity_and_exact_threshold(self):
        for configured, native, provider_limit, expected in ((40000, 100000, 80000, 40000),
                (100000, 60000, 80000, 60000), (100000, 0, 50000, 50000)):
            with self.subTest(configured=configured, native=native, provider=provider_limit):
                self.new_task()
                self.configure(context_tokens=configured, context_percent=80)
                counted = []
                def count(messages, trusted):
                    counted.append(trusted)
                    return trusted or C.estimate([m.model_dump() for m in messages])
                manager = self.manager(self.provider(limit=provider_limit), limit=native,
                                       counter=S(count_tokens=count), prompt_tokens=100)
                messages = [Message({"role": "user", "content": "raw" * 40000})]
                threshold = expected * 80 // 100
                calls_before = len(self.calls)
                self.assertIs(await manager.process(messages, threshold - 101), messages)
                self.assertEqual(len(self.calls), calls_before)
                result = await manager.process(messages, threshold - 100)
                self.assertIn(C.MARKER, result[0].row["content"])
                self.assertEqual(len(self.calls), calls_before + 1)
                self.assertIn(threshold - 100, counted)
                context = self.load().workflow_data["usage_metrics"]["context"]
                self.assertEqual((context["capacity_tokens"], context["trigger_tokens"]), (expected, threshold))

    async def test_unknown_model_defaults_to_128k_and_explicit_admin_capacity_is_respected(self):
        provider = self.provider()
        native = S(config=S(max_context_tokens=0))
        self.assertEqual(C.context_capacity(self.load(), provider, native), 128000)
        manager = self.manager(provider, limit=0)
        messages = [Message({"role": "user", "content": "work"})]
        self.assertIs(await manager.process(messages, 89599), messages)
        await manager.process(messages, 89600)
        self.assertEqual(len(self.calls), 1)
        self.new_task()
        self.configure(context_tokens=1000000)
        manager = self.manager(provider, limit=0)
        self.assertEqual(C.context_capacity(self.load(), provider, native), 1000000)
        self.assertIs(await manager.process(messages, 100000), messages)
        self.assertEqual(len(self.calls), 1)
        provider.provider_config["max_context_tokens"] = 64000
        self.assertEqual(C.context_capacity(self.load(), provider, native), 64000)
        await manager.process(messages, 44800)
        self.assertEqual(len(self.calls), 2)

    async def test_summary_material_omits_only_transport_thoughts_and_preserves_raw_archive(self):
        group = tool_group(1, '{"signature":"business result","reasoning":"task data"}')
        group[0]["content"] = [{"type": "think", "think": "internal" * 20000, "encrypted": "ENC" * 100000},
                               {"type": "text", "text": "Observed src/api.py: verification pending."},
                               {"type": "reasoning", "encrypted_content": "OPAQUE" * 20000}]
        group[0]["reasoning_content"] = "PRIVATE" * 20000
        group[0]["reasoning_signature"] = "SIGNATURE" * 30000
        group[0]["tool_calls"][0]["extra_content"] = {"google": {"thought_signature": "TOOL_SIG" * 30000}}
        arguments = '{"signature":"public API argument","reasoning":"literal payload"}'
        group[0]["tool_calls"][0]["function"]["arguments"] = arguments
        history = [{"role": "user", "content": "Test the signature field; reasoning_signature is an actual field name."},
                   *group, *tool_group(2, "latest source code")]
        original = encoded(history)
        def inspect(kwargs):
            draft = C.lane_state(self.load())["draft_record_id"]
            archived = self.storage._read_json(self.continuity.directory(self.task) / f"{draft}.json")
            self.assertEqual(encoded(archived["history"]), original)
            material = json.loads(kwargs["prompt"])["messages"]
            self.assertEqual(material[0], history[0])
            self.assertEqual(material[1]["content"], [group[0]["content"][1]])
            self.assertNotIn("reasoning_content", material[1])
            self.assertNotIn("reasoning_signature", material[1])
            self.assertNotIn("extra_content", material[1]["tool_calls"][0])
            self.assertEqual(material[1]["tool_calls"][0]["function"]["arguments"], arguments)
            self.assertEqual(material[2], group[1])
            self.assertLess(len(kwargs["prompt"]), len(original) // 100)
        await self.continuity.compact(self.event, self.load(), history, self.provider(action=inspect), "stage_changed")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.archive()["summary"], "继续修复并运行验证。")
        self.assertEqual(encoded(self.archive()["history"]), original)
        self.assertEqual(encoded(history), original)

    async def test_ticks_and_plan_revisions_do_not_trigger_but_stage_changes_do(self):
        self.project["execution_settings"]["continuity"] = {"max_stage_ticks": 1, "context_tokens": 100000, "summary_chars": 5000}
        task = self.load()
        C.state_of(task)["project_id"] = "project"
        C.lane_state(task).update(pending_reason="stage_round_limit")
        self.storage.save_task(task)
        manager = self.manager()
        messages = [Message({"role": "user", "content": "work"})]
        for _ in range(12):
            self.continuity.begin_round(self.load())
            self.assertIs(await manager.process(messages), messages)
        self.assertEqual(C.settings(self.load())["summary_chars"], 5000)
        self.assertEqual(C.lane_state(self.load())["ticks"], 12)
        task = self.load()
        C.lane_state(task)["pending_reason"] = "plan_revised"
        self.storage.save_task(task)
        self.assertIs(await manager.process(messages), messages)
        self.assertEqual(self.calls, [])
        task = self.load()
        C.state_of(task)["steps"][0]["stage"] = "implement"
        self.continuity.begin_round(task)
        await manager.process(messages)
        self.assertEqual(len(self.calls), 1)
        record = self.archive()
        self.assertEqual((record["stage"], record["next_stage"], record["reason"]), ("inspect", "implement", "stage_changed"))
        task = self.load()
        C.lane_state(task)["pending_reason"] = "stage_completed"
        self.storage.save_task(task)
        await manager.process(messages)
        self.assertEqual(len(self.calls), 2)

    async def test_one_full_source_call_archives_verbatim_and_honors_summary_chars(self):
        for summary_chars, size in ((6000, 5500), (20000, 18000)):
            with self.subTest(summary_chars=summary_chars):
                self.new_task()
                self.configure(summary_chars=summary_chars)
                task = self.load()
                C.lane_state(task)["summary"] = "旧工作笔记" * 1200
                C.state_of(task)["checkpoint_handoff"] = {"summary": "现有检查点", "stage": "inspect",
                    "version": 1, "input_revision": 0, "evidence": ["legacy"]}
                self.storage.save_task(task)
                raw = [{"role": "system", "content": "ARCHIVE_LITERAL"},
                       {"role": "_checkpoint", "content": {"id": "checkpoint", "offset": 2}},
                       {"role": "user", "content": "BEGIN" + "日志内容\n" * 16000 + "END"},
                       *tool_group("1234567890123456789", "ARCHIVE_LITERAL\nC:\\real\\source.py")]
                original = encoded(raw)
                def check_archive(kwargs):
                    draft = C.lane_state(self.load())["draft_record_id"]
                    record = self.storage._read_json(self.continuity.directory(task) / f"{draft}.json")
                    self.assertEqual(encoded(record["history"]), original)
                    self.assertEqual(record["status"], "preparing")
                    request = json.loads(kwargs["prompt"])
                    self.assertEqual(request["messages"], raw)
                    self.assertEqual(request["previous_handoff"], "旧工作笔记" * 1200)
                    self.assertIn(str(summary_chars), kwargs["system_prompt"])
                    self.assertEqual(kwargs["contexts"], [])
                    self.assertTrue(kwargs["_agent_lab_handoff"])
                self.owner._redact_known_secrets = lambda text: text.replace("ARCHIVE_LITERAL", "REDACTED")
                before = len(self.calls)
                await self.continuity.compact(self.event, task, raw, self.provider("事" * size, check_archive), "stage_completed")
                self.assertEqual(len(self.calls), before + 1)
                record = self.archive()
                self.assertEqual(record["history"], raw)
                self.assertEqual(record["summary_chars"], size)
                self.assertEqual(record["summary_limit"], summary_chars)
                self.assertEqual(record["model_calls"], 1)
                self.assertEqual(record["reported_tokens"], 123)
                self.assertEqual(encoded(raw), original)

    async def test_recent_window_is_quarter_capacity_and_keeps_complete_multi_tool_groups(self):
        self.configure(context_tokens=100000, context_percent=80)
        history = [{"role": "user", "content": "initial"}]
        for index in range(65):
            history.extend(tool_group(index, f"source {index}\n" + "x" * 2400, results=2))
            if index == 62:
                history.append({"role": "user", "content": "进入下一阶段"})
        task = self.load()
        C.lane_state(task, "other").update(summary="其他分支", count=7)
        self.storage.save_task(task)
        result = await self.continuity.compact(self.event, task, history, self.provider(), "stage_changed")
        retained = result[1:]
        self.assertEqual(retained, history[-len(retained):])
        self.assertGreater(C.estimate(retained), 16000)
        self.assertLessEqual(C.estimate(retained), 20000)
        self.assertEqual(self.archive()["recent_budget_tokens"], 20000)
        self.assertGreater(len(C.message_groups(retained)), 3)
        self.assertEqual(C.lane_state(self.load(), "other"), {"summary": "其他分支", "count": 7})
        # A caller changing its new history must not mutate the old message objects.
        original = deepcopy(history)
        retained[-1]["content"] = "changed later"
        self.assertEqual(history, original)

    async def test_empty_timeout_and_error_smoothly_continue_without_retry(self):
        for failure in ("empty", "timeout", "provider_error"):
            with self.subTest(failure=failure):
                self.new_task()
                cancelled = []
                async def action(kwargs):
                    if failure == "timeout":
                        try:
                            await asyncio.Event().wait()
                        finally:
                            cancelled.append(True)
                    if failure == "provider_error":
                        raise OSError("model unavailable")
                history = [{"role": "user", "content": "old" * 40000}, *tool_group(1, "current code" * 1500)]
                before = len(self.calls)
                with patch.object(C, "SUMMARY_TIMEOUT_SECONDS", 0.01):
                    reduced = await self.continuity.compact(self.event, self.load(), history, self.provider("", action),
                                                             "context_capacity", token_limit=100000)
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(reduced[1:], history[-2:])
                record = self.archive()
                self.assertEqual(record["summary_issues"][0]["reason"], failure)
                self.assertEqual(record["summary_outcome"], "recent_window")
                self.assertEqual(record["model_calls"], 1)
                self.assertEqual(self.load().status, "running")
                self.assertEqual(C.lane_state(self.load())["summary"], "")
                self.assertNotIn("降级", reduced[0]["content"])
                self.assertNotIn("必须回查", reduced[0]["content"])
                if failure == "timeout":
                    self.assertTrue(cancelled)

    async def test_recent_budget_uses_host_counter_instead_of_fallback_estimate(self):
        self.configure(context_tokens=100000, context_percent=80)
        def count(messages, trusted=0):
            return trusted or sum(len(json.dumps(m.model_dump(), ensure_ascii=False)) for m in messages) // 4
        history = [{"role": "user", "content": "old"}]
        for index in range(60):
            history.extend(tool_group(index, "源码" * 1200))
        task = self.load()
        C.lane_state(task)["pending_reason"] = "stage_changed"
        self.storage.save_task(task)
        manager = self.manager(counter=S(count_tokens=count), prompt_tokens=300)
        reduced = await manager.process([Message(row) for row in history])
        retained = reduced[1:]
        self.assertGreater(count(retained), 16000)
        self.assertLessEqual(count(retained), 20000)
        self.assertEqual([m.model_dump() for m in retained], history[-len(retained):])

    async def test_latest_complete_tool_group_over_quarter_budget_survives_empty_or_timeout(self):
        for outcome in ("empty", "timeout"):
            with self.subTest(outcome=outcome):
                self.new_task()
                self.configure(context_tokens=20000, context_percent=80)
                async def action(kwargs):
                    if outcome == "timeout":
                        await asyncio.Event().wait()
                group = tool_group(1, "current exact source\n" + "x" * 8000, results=2)
                tail = {"role": "assistant", "content": "Next apply the fix."}
                raw = [{"role": "system", "content": "fixed rules " * 40},
                       {"role": "user", "content": "old history " * 4000}, *group, tail]
                original = encoded(raw)
                messages = [Message(row) for row in raw]
                manager = self.manager(self.provider("", action), limit=20000, prompt_tokens=400)
                before = len(self.calls)
                with patch.object(C, "SUMMARY_TIMEOUT_SECONDS", 0.01):
                    result = await manager.process(messages)
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual([m.model_dump() for m in result[2:]], [*group, tail])
                self.assertLess(manager.count_tokens(result), 16000)
                self.assertGreater(self.archive()["recent_tokens"], 4000)
                self.assertEqual(self.archive()["summary"], "")
                self.assertEqual(encoded([m.model_dump() for m in messages]), original)
                self.assertIs(await manager.process(result), result)
                self.assertEqual(len(self.calls), before + 1)

    async def test_latest_group_is_kept_even_when_newer_tail_cannot_fit_with_it(self):
        self.configure(context_tokens=10000, context_percent=80)
        group = tool_group(1, "source" * 2500)
        raw = [*group, {"role": "assistant", "content": "new tail" * 2000}]
        result = await self.continuity.compact(self.event, self.load(), raw, self.provider(""), "stage_changed")
        self.assertEqual(result[1:], group)
        self.assertLess(C.estimate(result), 8000)

    async def test_empty_summary_cannot_replace_history_when_latest_group_cannot_fit(self):
        for outcome, fixed in (("empty", ""), ("timeout", ""), ("empty", "fixed" * 2200)):
            with self.subTest(outcome=outcome, fixed=bool(fixed)):
                self.new_task()
                self.configure(context_tokens=10000, context_percent=80)
                async def action(kwargs):
                    if outcome == "timeout":
                        await asyncio.Event().wait()
                group = tool_group(1, "x" * (13000 if fixed else 27000))
                raw = [{"role": "system", "content": fixed}, *group,
                       {"role": "assistant", "content": "small tail must not hide the missing source"}]
                original = encoded(raw)
                messages = [Message(row) for row in raw]
                task = self.load()
                C.lane_state(task)["pending_reason"] = "stage_changed"
                self.storage.save_task(task)
                manager = self.manager(self.provider("", action), limit=10000, prompt_tokens=500)
                before = len(self.calls)
                with patch.object(C, "SUMMARY_TIMEOUT_SECONDS", 0.01), self.assertRaisesRegex(C.HandoffError, "最近完整工作组"):
                    await manager.process(messages)
                self.assertEqual(len(self.calls), before + 1)
                self.assertEqual(encoded([m.model_dump() for m in messages]), original)
                saved = C.lane_state(self.load())
                self.assertNotIn("record_id", saved)
                record = self.storage._read_json(self.continuity.directory(self.task) / f"{saved['draft_record_id']}.json")
                self.assertEqual(record["status"], "blocked")
                self.assertEqual(record["history"], raw)
                self.assertEqual(record["model_calls"], 1)

    async def test_overlong_summary_trims_paragraph_or_single_long_paragraph_once(self):
        for response, expected in (("甲" * 3600 + "\n\n" + "乙" * 5000, "甲" * 3600),
                                   ("甲" * 9000, "甲" * 6000)):
            with self.subTest(length=len(response)):
                self.new_task()
                before = len(self.calls)
                await self.continuity.compact(self.event, self.load(), [{"role": "user", "content": "continue"}],
                                               self.provider(response), "context_capacity")
                self.assertEqual(len(self.calls), before + 1)
                record = self.archive()
                self.assertEqual(record["summary"], expected)
                self.assertEqual(record["summary_issues"][0]["actual_chars"], len(response))
                self.assertEqual(record["summary_outcome"], "truncated")

    async def test_small_model_fits_fixed_prompt_note_and_whole_recent_groups(self):
        self.configure(context_tokens=2000, context_percent=70, summary_chars=6000)
        raw = [{"role": "system", "content": "fixed rules " * 35},
               {"role": "user", "content": "old history " * 1000}, *tool_group(1, "latest code " * 30)]
        messages = [Message(row) for row in raw]
        manager = self.manager(self.provider("事" * 5500), limit=2000, prompt_tokens=150)
        result = await manager.process(messages)
        self.assertLess(manager.count_tokens(result), 1400)
        self.assertIs(result[0], messages[0])
        self.assertEqual([m.model_dump() for m in result[-2:]], raw[-2:])
        self.assertEqual([m.model_dump() for m in messages], raw)
        record = self.archive()
        self.assertEqual(record["summary_limit"], 6000)
        self.assertEqual(record["generated_summary"], "事" * 5500)
        self.assertTrue(record["context_summary_trimmed"])
        self.assertGreater(len(record["summary"]), 0)
        self.assertIs(await manager.process(result), result)
        self.assertEqual(len(self.calls), 1)

    async def test_reported_usage_without_native_counter_triggers_only_its_lane(self):
        self.configure(context_tokens=100000, context_percent=80)
        task = self.load()
        C.lane_state(task).update(summary="main lane", pending_reason="stage_completed")
        self.storage.save_task(task)
        manager = self.manager(lane="worker")
        messages = [Message({"role": "user", "content": "short history"})]
        self.assertIs(await manager.process(messages, 79999), messages)
        self.assertFalse(self.calls)
        await manager.process(messages, 80000)
        self.assertEqual(self.archive("worker")["reason"], "context_capacity")
        self.assertEqual(C.lane_state(self.load()), {"summary": "main lane", "pending_reason": "stage_completed"})

    async def test_archive_failure_and_final_write_failure_preserve_original_history(self):
        history = [{"role": "user", "content": "keep original"}, *tool_group(1, "code")]
        original = encoded(history)
        for fail_after_summary in (False, True):
            with self.subTest(fail_after_summary=fail_after_summary):
                self.new_task()
                write = self.storage._write_json
                def fail(path, value):
                    if Path(path).parent.name == "handoffs" and (not fail_after_summary or value.get("status") == "saved"):
                        raise OSError("disk full")
                    return write(path, value)
                before = len(self.calls)
                with patch.object(self.storage, "_write_json", side_effect=fail):
                    with self.assertRaises(C.HandoffError):
                        await self.continuity.compact(self.event, self.load(), history, self.provider(), "stage_changed")
                self.assertEqual(len(self.calls), before + int(fail_after_summary))
                self.assertEqual(encoded(history), original)
                self.assertNotIn("record_id", C.lane_state(self.load()))
                self.assertEqual(self.continuity.read(self.load()), {"records": []})

    async def test_pause_revision_cleaning_and_replacement_during_summary_are_not_overwritten(self):
        for change in ("pause", "revision", "cleaning", "replacement"):
            with self.subTest(change=change):
                self.owner.projects.cleaning.clear()
                self.new_task()
                task_id = self.task.task_id
                def action(kwargs):
                    latest = self.load()
                    if change == "pause":
                        latest.status = "paused"
                        C.state_of(latest)["human_paused"] = True
                    elif change == "revision":
                        C.state_of(latest)["input_revision"] += 1
                    elif change == "cleaning":
                        self.owner.projects.cleaning.add(task_id)
                    else:
                        latest.task_id = Models.new_id("task")
                    self.storage.save_task(latest)
                history = [{"role": "user", "content": "original"}]
                with self.assertRaises(C.HandoffError):
                    await self.continuity.compact(self.event, self.load(), history, self.provider(action=action), "stage_changed")
                latest = self.load()
                self.assertFalse(C.lane_state(latest).get("record_id"))
                if change == "pause":
                    self.assertEqual(latest.status, "paused")
                if change == "revision":
                    self.assertEqual(C.state_of(latest)["input_revision"], 1)
                if change == "replacement":
                    self.assertNotEqual(latest.task_id, task_id)

    async def test_budget_stop_and_cancellation_keep_control_meaning(self):
        for error in (type("BudgetStopped", (Exception,), {}), type("ExecutionStopped", (Exception,), {}), asyncio.CancelledError):
            with self.subTest(error=error.__name__):
                self.new_task()
                def action(kwargs):
                    raise error("stop")
                before = len(self.calls)
                history = [{"role": "user", "content": "raw"}]
                with self.assertRaises(error):
                    await self.continuity.compact(self.event, self.load(), history, self.provider(action=action), "context_capacity")
                self.assertEqual(len(self.calls), before + 1)
                draft = C.lane_state(self.load())["draft_record_id"]
                record = self.storage._read_json(self.continuity.directory(self.task) / f"{draft}.json")
                self.assertEqual(record["history"], history)
                self.assertEqual(record["status"], "preparing")

    async def test_tool_pairs_are_atomic_and_archive_read_interface_remains_compatible(self):
        good = tool_group(1, "output", results=2)
        for bad in (good[:-1], [good[-1]], [*good, good[-1]],
                    [good[0], good[1], {**good[2], "tool_call_id": "unknown"}]):
            with self.subTest(bad=bad):
                with self.assertRaises(C.HandoffError):
                    await self.continuity.compact(self.event, self.load(), bad, self.provider(), "stage_changed")
        self.assertEqual(self.calls, [])
        history = [{"role": "user", "content": "a" * 3000}, *good]
        await self.continuity.compact(self.event, self.load(), history, self.provider(), "stage_changed")
        record_id = C.lane_state(self.load())["record_id"]
        chunks, offset = [], 0
        while offset is not None:
            page = self.continuity.read(self.load(), record_id, offset, 500)
            chunks.append(page["text"])
            offset = page["next_offset"]
        self.assertEqual(json.loads("".join(chunks))["history"], history)
        self.assertEqual(self.continuity.read(self.load())["records"][0]["record_id"], record_id)
        with self.assertRaises(ValueError):
            self.continuity.read(self.load(), "../escape")
        with self.assertRaises(ValueError):
            self.continuity.read(self.load(), record_id, True, 500)
        oversized = tool_group(2, "z" * 300000)
        result = await self.continuity.compact(self.event, self.load(), oversized, self.provider(), "context_capacity", token_limit=80000)
        self.assertEqual(len(result), 1)
        self.assertEqual(self.archive()["history"], oversized)

    async def test_real_large_source_edit_survives_compaction_and_executes_verification(self):
        """The acting adapter may use only the contexts it actually receives."""
        for summary_mode in ("notes", "empty", "timeout"):
            with self.subTest(summary_mode=summary_mode):
                self.new_task()
                self.configure(context_tokens=128000, context_percent=80)
                source = self.root / "large_source.py"
                lines = [f"SLOT_{i:04d} = {i}\n" for i in range(2000)]
                lines[1541:1543] = ["def normalize(value):\n", "    return str(value).strip().lower()\n"]
                original = "".join(lines)
                source.write_text(original, encoding="utf-8")
                self.assertGreaterEqual(len(original.splitlines()), 1800)
                verifier = self.root / "verify.py"
                verifier.write_text("import runpy, sys\nf = runpy.run_path(sys.argv[1])['normalize']\n"
                                    "assert f(None) == ''\nassert f(' AbC ') == 'abc'\n"
                                    "assert f(0) == '0'\nprint('PASS normalize')\n", encoding="utf-8")
                observed, actions, summary_calls = [], [], []
                async def chat(**kwargs):
                    if kwargs.get("_agent_lab_handoff"):
                        summary_calls.append(deepcopy(kwargs))
                        if summary_mode == "timeout":
                            await asyncio.Event().wait()
                        payload = json.loads(kwargs["prompt"])
                        notes = {"goal": payload["current_plan"]["goal"], "observations": [
                            row["content"][:100] for row in payload["messages"] if row.get("role") == "tool"]}
                        return S(completion_text=json.dumps(notes, ensure_ascii=False) if summary_mode == "notes" else "")
                    contexts = deepcopy(kwargs["contexts"])
                    observed.append(contexts)
                    results = [json.loads(row["content"]) for row in contexts if row.get("role") == "tool"]
                    verified = next((r for r in results if r.get("action") == "verify"), None)
                    if verified:
                        self.assertEqual(verified["returncode"], 0, verified)
                        self.assertIn("PASS normalize", verified["stdout"])
                        return S(action="finish")
                    if any(r.get("action") == "edit" for r in results):
                        return S(action="verify", path=str(source))
                    read = next((r for r in results if r.get("action") == "read"), None)
                    if not read:
                        return S(action="read", path=str(source))
                    received_lines = read["text"].splitlines(keepends=True)
                    index = received_lines.index("def normalize(value):\n")
                    before = "".join(received_lines[index:index+2])
                    self.assertIn("return str(value).strip().lower()", before)
                    after = before.replace("return str(value).strip().lower()", "return '' if value is None else str(value).strip().lower()")
                    return S(action="edit", path=read["path"], before=before, after=after)
                provider = S(text_chat=chat, provider_config={"max_context_tokens": 160000})
                manager = self.manager(provider, limit=160000)
                messages = [Message({"role": "system", "content": "Execute the requested change and verify it."}),
                            Message({"role": "user", "content": f"Fix normalize(None) to return an empty string in {source}. Preserve other cases and run verification."}),
                            Message({"role": "assistant", "content": "old observations\n" * 10000})]
                started = time.perf_counter()
                with patch.object(C, "SUMMARY_TIMEOUT_SECONDS", 0.01):
                    for _ in range(6):
                        messages = await manager.process(messages)
                        reply = await provider.text_chat(contexts=[m.model_dump() for m in messages])
                        if reply.action == "finish":
                            break
                        self.assertEqual(Path(reply.path), source)
                        actions.append(reply.action)
                        if reply.action == "read":
                            result = {"action": "read", "path": str(source), "text": source.read_text(encoding="utf-8")}
                        elif reply.action == "edit":
                            current = source.read_text(encoding="utf-8")
                            self.assertEqual(current.count(reply.before), 1)
                            source.write_text(current.replace(reply.before, reply.after), encoding="utf-8")
                            result = {"action": "edit", "changed": True, "path": str(source)}
                        else:
                            command = subprocess.run([sys.executable, "-B", str(verifier), str(source)],
                                                     capture_output=True, text=True, cwd=self.root, timeout=10)
                            result = {"action": "verify", "returncode": command.returncode,
                                      "stdout": command.stdout, "stderr": command.stderr}
                        messages.extend(Message(row) for row in tool_group(len(actions), json.dumps(result, ensure_ascii=False), name=reply.action))
                        if reply.action == "read":
                            task = self.load()
                            C.lane_state(task)["pending_reason"] = "stage_changed"
                            self.storage.save_task(task)
                    else:
                        self.fail("tool loop did not finish within the call budget")
                self.assertEqual(actions, ["read", "edit", "verify"])
                self.assertEqual(len(observed), 4)
                self.assertEqual(len(summary_calls), 1)
                self.assertIn(C.MARKER, observed[1][1]["content"])
                self.assertEqual(encoded(observed[2][:len(observed[1])]), encoded(observed[1]))
                self.assertEqual(encoded(observed[3][:len(observed[2])]), encoded(observed[2]))
                self.assertEqual(source.read_text(encoding="utf-8"), original.replace(
                    "return str(value).strip().lower()", "return '' if value is None else str(value).strip().lower()"))
                all_requests = [*observed, *[r["prompt"] for r in summary_calls]]
                print(json.dumps({"scenario": "offline_large_source", "summary": summary_mode, "source_lines": 2000,
                    "provider_calls": len(observed) + len(summary_calls), "input_chars": sum(len(encoded(r).decode("utf-8")) for r in all_requests),
                    "estimated_input_tokens": sum(C.estimate(r) for r in all_requests), "repeated_region_reads": actions.count("read") - 1,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)}, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
