"""Offline compact-boundary receipts; all archives and source reads are real.

Run: python -B scripts/ui/test_handoff_payloads.py
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
import types
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "handoff_payload_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package
C = importlib.import_module(PACKAGE + ".continuity")
Models = importlib.import_module(PACKAGE + ".models")
Storage = importlib.import_module(PACKAGE + ".storage").AgentLabStorage


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def group(*operations):
    calls = [{"id": f"original_call_{index}", "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
        "extra_content": {"google": {"thought_signature": f"SIGNED_CALL_{index}"}}}
        for index, (name, arguments, result) in enumerate(operations)]
    return [{"role": "assistant", "content": [
        {"type": "think", "think": "original thinking", "encrypted": "SIGNED_THINK"},
        {"type": "text", "text": "execute the exact operations"}],
        "reasoning_signature": "SIGNED_MESSAGE", "response_metadata": {"signature": "OPAQUE"},
        "tool_calls": calls}, *[
        {"role": "tool", "tool_call_id": call["id"], "content": result}
        for call, (_, _, result) in zip(calls, operations)]]


def receipt_data(history):
    return [json.loads(row["content"].split("\n", 1)[1]) for row in history
            if row.get("role") == "user" and isinstance(row.get("content"), str)
            and row["content"].startswith(C.RECEIPT_MARKER + "\n")]


class Message:
    def __init__(self, row):
        self.row = deepcopy(row)

    def model_dump(self):
        return deepcopy(self.row)

    @classmethod
    def model_validate(cls, row):
        return cls(row)


class HandoffPayloadTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-lab-payloads-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = Storage(self.root / "data")
        self.owner = S(storage=self.storage, _redact_known_secrets=lambda text: text,
                       projects=S(cleaning=set(), project=lambda key: {},
                                  safe_path=lambda path: Path(path).resolve().is_relative_to(self.storage.root.resolve())))
        self.continuity = C.TaskContinuity(self.owner)
        self.event = S(unified_msg_origin="offline:payloads")
        self.task = Models.TaskState(umo=self.event.unified_msg_origin, root_goal="核对文件并继续验证", status="running")
        C.state_of(self.task).update(version=1, current_step_id="one", input_revision=0, human_paused=False,
                                     constraints=["必须保留接口"], steps=[{
                                         "id": "one", "stage": "implementation", "status": "running"}])
        self.storage.save_task(self.task)
        self.requests = []
        stub = patch.dict(sys.modules, {"astrbot.core.agent.message": S(Message=Message)})
        stub.start()
        self.addCleanup(stub.stop)

    def load(self):
        return self.storage.load_active_task(self.task.umo)

    def journal(self, name, arguments, result, **extra):
        task = self.load()
        rows = C.state_of(task).setdefault("journal", [])
        identifier = f"journal_{len(rows)}"
        result_path = self.storage.task_memory_dir(task.umo, task.task_id) / "tool_results" / f"{identifier}.txt"
        self.storage._write_text(result_path, result)
        row = {"id": identifier, "name": name, "arguments": deepcopy(arguments),
               "status": "completed", "result": result, "result_chars": len(result),
               "result_path": str(result_path.relative_to(self.storage.root)), **extra}
        rows.append(row)
        self.storage.save_task(task)
        return row

    def provider(self, mode="notes", inspect=None):
        async def text_chat(**kwargs):
            self.requests.append(deepcopy(kwargs))
            if inspect:
                inspect(kwargs)
            if mode == "timeout":
                await asyncio.Event().wait()
            if mode == "error":
                raise OSError("summary unavailable")
            return S(completion_text="继续读取实际文件并运行核验。" if mode == "notes" else "")
        return S(text_chat=text_chat, provider_config={})

    async def compact(self, history, mode="notes", *, limit=80000, inspect=None):
        with patch.object(C, "SUMMARY_TIMEOUT_SECONDS", 0.01):
            return await self.continuity.compact(self.event, self.load(), history,
                                                  self.provider(mode, inspect), "stage_completed", token_limit=limit)

    def archive(self):
        lane = C.lane_state(self.load())
        return self.storage._read_json(self.storage.root / lane["record_path"])

    def payload_view(self, history, *, journal=None, approvals=None):
        # Exercise the public helper only after a real, unchanged archive write.
        archive = self.continuity.directory(self.task) / "helper_source.json"
        self.storage._write_json(archive, {"history": deepcopy(history)})
        task = self.load()
        return C.handoff_payloads(history, C.state_of(task).get("journal", []) if journal is None else journal,
                                  archive, storage_root=self.storage.root,
                                  approvals=task.approvals if approvals is None else approvals)

    def write_operation(self):
        source = self.root / "written.py"
        content = "# WRITE_PAYLOAD_DO_NOT_CARRY\n" * 1800 + "VALUE = 42\n"
        source.write_text(content, encoding="utf-8")
        arguments = {"path": str(source), "content": content, "signature": "business payload signature"}
        result = f"File written successfully: {source}"
        return source, arguments, result

    async def test_signed_history_stays_identical_until_stage_boundary_then_receipt_is_pinned(self):
        source, arguments, result = self.write_operation()
        self.journal("astrbot_file_write_tool", arguments, result)
        history = [{"role": "system", "content": "fixed signed protocol rules"},
                   {"role": "user", "content": "继续核对实际源码"},
                   *group(("astrbot_file_write_tool", arguments, result))]
        task = self.load()
        task.task_brief = task.entry_summary = "入口事实：核对 VALUE，保留接口"
        C.state_of(task).setdefault("execution_settings", {})["continuity"] = {
            "context_tokens": 1000000, "context_percent": 80, "max_stage_ticks": 1}
        self.storage.save_task(task)
        manager = C.StageContextManager(self.continuity, self.event, task.task_id, self.provider(),
                                       S(config=S(max_context_tokens=1000000)))
        messages = [Message(row) for row in history]
        for index in range(4):
            original = encoded([m.model_dump() for m in messages])
            self.continuity.begin_round(self.load())
            self.assertIs(await manager.process(messages), messages)
            self.assertEqual(encoded([m.model_dump() for m in messages]), original)
            messages.append(Message({"role": "user", "content": f"继续 {index}"}))
        self.assertFalse(self.requests)
        original_rows = [m.model_dump() for m in messages]
        task = self.load()
        C.lane_state(task)["pending_reason"] = "stage_changed"
        self.storage.save_task(task)
        reduced_messages = await manager.process(messages)
        reduced = [m.model_dump() for m in reduced_messages]
        self.assertEqual(encoded([m.model_dump() for m in messages]), encoded(original_rows))
        self.assertEqual(encoded(self.archive()["history"]), encoded(original_rows))
        request = json.loads(self.requests[0]["prompt"])
        self.assertEqual(request["current_plan"]["brief"], task.task_brief)
        self.assertEqual(request["current_plan"]["constraints"], ["必须保留接口"])
        self.assertEqual(len(receipt_data(reduced)), 1)
        receipt = receipt_data(reduced)[0]
        archive_path = Path(receipt["archive_path"])
        self.assertTrue(archive_path.is_absolute())
        self.assertEqual(encoded(json.loads(archive_path.read_text(encoding="utf-8"))["history"]), encoded(original_rows))
        fact = receipt["calls"][0]
        self.assertEqual(fact["tool"], "astrbot_file_write_tool")
        self.assertEqual(fact["status"], "completed")
        self.assertIn(str(source), fact["paths"])
        self.assertEqual(fact["payload_chars"]["content"], len(arguments["content"]))
        self.assertEqual(Path(fact["result_path"]).read_text(encoding="utf-8"), result)
        self.assertIn("File written successfully", fact["verification_output"])
        for serialized in (json.dumps(reduced), self.requests[0]["prompt"]):
            self.assertNotIn("WRITE_PAYLOAD_DO_NOT_CARRY", serialized)
            self.assertNotIn("original_call_0", serialized)
            self.assertNotIn("SIGNED_MESSAGE", serialized)
        for row in reduced:
            if row.get("content", "").startswith(C.RECEIPT_MARKER):
                self.assertEqual(set(row), {"role", "content"})
        # A receipt outside the next 25% suffix survives another compact, once.
        prefix = deepcopy(reduced)
        reduced_messages.append(Message({"role": "assistant", "content": "new observation"}))
        self.assertIs(await manager.process(reduced_messages), reduced_messages)
        self.assertEqual([m.model_dump() for m in reduced_messages[:len(prefix)]], prefix)
        tail = {"role": "assistant", "content": "NEW_TAIL " * 5000}
        again = await self.compact([*reduced, tail], "empty", limit=40000)
        self.assertEqual(receipt_data(again), [receipt])
        self.assertNotIn("WRITE_PAYLOAD_DO_NOT_CARRY", json.dumps(again))
        self.assertEqual(json.loads(self.requests[-1]["prompt"])["current_plan"]["brief"], task.task_brief)

    async def test_latest_fit_priority_cannot_restore_large_write_or_code(self):
        _, arguments, output = self.write_operation()
        self.journal("astrbot_file_write_tool", arguments, output)
        code = "# CODE_PAYLOAD_DO_NOT_CARRY\n" * 800 + "print('PASS real verification')\n"
        code_args = {"code": code}
        self.journal("astrbot_execute_python", code_args, "PASS real verification")
        # The preceding read would fit the whole capacity but not the 25% suffix.
        read = group(("astrbot_file_read_tool", {"path": str(self.root / "read.py")}, "SOURCE\n" * 7000))
        history = [*read, *group(("astrbot_file_write_tool", arguments, output)),
                   *group(("astrbot_execute_python", code_args, "PASS real verification"))]
        original = encoded(history)
        self.assertLess(C.estimate(history[-2:]), 40000)
        reduced = await self.compact(history, "empty", limit=40000)
        self.assertEqual(len(receipt_data(reduced)), 2)
        self.assertFalse(any(row.get("tool_calls") for row in reduced))
        self.assertNotIn("CODE_PAYLOAD_DO_NOT_CARRY", json.dumps(reduced))
        self.assertNotIn("WRITE_PAYLOAD_DO_NOT_CARRY", self.requests[0]["prompt"])
        self.assertLess(self.archive()["source_chars"], self.archive()["raw_history_chars"] // 2)
        self.assertEqual(encoded(history), original)

    async def test_read_unexecuted_failed_unknown_and_missing_journal_remain_verbatim(self):
        _, arguments, output = self.write_operation()
        history = group(("astrbot_file_write_tool", arguments, output))
        good = self.journal("astrbot_file_write_tool", arguments, output)
        cases = [
            [], [{**good, "name": "different_tool"}],
            [{**good, "arguments": {**arguments, "content": arguments["content"] + "# different"}}],
            *[[{**good, "status": status}] for status in ("started", "unknown", "failed")],
            [{**good, "read_only": True}], [{**good, "result": '{"ok":false}'}],
            [good, {**good, "status": "failed"}],
        ]
        for journal in cases:
            with self.subTest(journal=[row.get("status") for row in journal]):
                view = self.payload_view(history, journal=journal)
                self.assertEqual(encoded(view), encoded(history))
                self.assertTrue(all(left is right for left, right in zip(view, history)))
        # Long pure reads and read-only shell calls are never eligible.
        for name, args, result in (
                ("astrbot_file_read_tool", {"path": "source.py"}, "source\n" * 6000),
                ("astrbot_execute_shell", {"command": "cat ./source.py " + " " * 9000}, "source")):
            read = group((name, args, result))
            self.journal(name, args, result)
            self.assertEqual(self.payload_view(read), read)
        # Legacy v04 has no journal: actual compact still keeps the signed pair.
        task = self.load()
        C.state_of(task)["journal"] = []
        self.storage.save_task(task)
        reduced = await self.compact(history, limit=250000)
        self.assertEqual(encoded(reduced[1:]), encoded(history))
        self.assertFalse(receipt_data(reduced))

    async def test_current_result_and_journal_cannot_claim_false_process_success(self):
        _, arguments, output = self.write_operation()
        good = self.journal("astrbot_file_write_tool", arguments, output)
        bad_results = [
            '{"ok":false}', '{"success":false}', '{"isError":true}', '{"error":"denied"}',
            '{"exit_code":1,"stdout":"PASS"}', '{"returncode":2}', '{"exit_code":null}',
            '{"status":"unknown"}', '{"status":"running","exit_code":0}',
            '{"status":"completed","session_id":"live","session_closed":false,"exit_code":0}',
            '{"ok":true,"data":{"status":"failed"}}', '{"ok":true,"background":true}',
            "Command completed with exit code 1 (wall time: 0.1s).\nOutput:\nPASS",
            "Command is running in the background.", "Error writing file: denied",
            "Traceback (most recent call last):\nValueError: broken", "", "写入失败：无权限",
            [{"type": "text", "text": output}, {"type": "image", "data": "media"}],
        ]
        for result in bad_results:
            with self.subTest(result=result):
                raw = group(("astrbot_file_write_tool", arguments, result))
                self.assertEqual(self.payload_view(raw), raw)
                # A stale 'completed' status cannot override a failed journal output.
                if isinstance(result, str):
                    raw = group(("astrbot_file_write_tool", arguments, output))
                    self.assertEqual(self.payload_view(raw, journal=[{**good, "result": result}]), raw)
        raw = group(("astrbot_file_write_tool", arguments, output))
        raw[-1]["isError"] = True
        self.assertEqual(self.payload_view(raw), raw)
        code_args = {"code": "# code\n" * 2000, "background": True}
        self.journal("astrbot_execute_python", code_args, '{"exit_code":0}')
        raw = group(("astrbot_execute_python", code_args, '{"exit_code":0}'))
        self.assertEqual(self.payload_view(raw), raw)

    async def test_parallel_group_is_atomic_if_either_result_or_journal_fails(self):
        _, arguments, output = self.write_operation()
        code_args = {"code": "print('PASS')"}
        self.journal("astrbot_file_write_tool", arguments, output)
        code_entry = self.journal("astrbot_execute_python", code_args, "PASS")
        raw = group(("astrbot_file_write_tool", arguments, output), ("astrbot_execute_python", code_args, "PASS"))
        original = encoded(raw)
        for failure in ("result", "journal", "none"):
            with self.subTest(failure=failure):
                history = deepcopy(raw)
                task = self.load()
                C.state_of(task)["journal"][-1] = {**code_entry, "status": "failed" if failure == "journal" else "completed"}
                self.storage.save_task(task)
                if failure == "result":
                    history[-1]["content"] = '{"exit_code":1,"stdout":"PASS"}'
                reduced = await self.compact(history, limit=250000)
                if failure == "none":
                    self.assertEqual(len(receipt_data(reduced)[0]["calls"]), 2)
                    self.assertFalse(any(row.get("tool_call_id") or row.get("tool_calls") for row in reduced))
                else:
                    self.assertEqual(encoded(reduced[1:]), encoded(history))
                    material = json.loads(self.requests[-1]["prompt"])["messages"]
                    self.assertEqual(material[0]["tool_calls"][0]["function"]["arguments"],
                                     history[0]["tool_calls"][0]["function"]["arguments"])
                self.assertEqual(encoded(self.archive()["history"]), encoded(history))
                self.assertEqual(encoded(raw), original)

    def approval_fixture(self):
        code = "# APPROVAL_SCRIPT_DO_NOT_CARRY\n" * 400 + "print('PASS approved operation')"
        arguments = {"code": code}
        operations = [{"tool_name": "astrbot_execute_python", "arguments": arguments}]
        approve_args = {"operation": "核对文件", "reason": "任务需要", "impact": "临时目录",
                        "operations_json": json.dumps(operations, ensure_ascii=False)}
        result = "任务 offline 审批批次已记录：已发送；等待处理，不重复发送。"
        history = group(("task_approve", approve_args, result))
        executed = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=10)
        self.assertEqual(executed.returncode, 0, executed.stderr)
        entry = self.journal("astrbot_execute_python", arguments, executed.stdout.strip(),
                             approval_id="approval_exact")
        approval = {"approval_id": "approval_exact", "approval_type": "tool_batch",
                    "status": "consumed", "decision": "approved", "calls": [{
                        "tool_name": "astrbot_execute_python", "arguments": deepcopy(arguments),
                        "status": "dispatched", "execution_status": "completed", "evidence_id": entry["id"]}]}
        return history, approval, entry

    async def test_internal_task_approve_requires_exact_approved_executed_batch_and_journal(self):
        history, approval, entry = self.approval_fixture()
        cases = [[], [{**approval, "status": "pending"}], [{**approval, "status": "rejected"}],
                 [{**approval, "decision": "rejected"}]]
        for execution_status in ("queued", "started", "unknown", "failed"):
            modified = deepcopy(approval)
            modified["calls"][0]["execution_status"] = execution_status
            cases.append([modified])
        mismatch = deepcopy(approval)
        mismatch["calls"][0]["arguments"]["code"] += "\n# different"
        cases.append([mismatch])
        for approvals in cases:
            with self.subTest(approvals=approvals):
                self.assertEqual(self.payload_view(history, approvals=approvals), history)
        for change in ({"approval_id": "other_approval"}, {"status": "unknown"},
                       {"result": '{"exit_code":1}'}, {"id": "different_evidence"}):
            with self.subTest(journal_change=change):
                self.assertEqual(self.payload_view(history, approvals=[approval], journal=[{**entry, **change}]), history)
        task = self.load()
        task.approvals = [approval]
        self.storage.save_task(task)
        original = encoded(history)
        reduced = await self.compact(history, "timeout")
        receipt = receipt_data(reduced)[0]
        self.assertEqual(receipt["calls"][0]["tool"], "task_approve")
        self.assertEqual(receipt["calls"][0]["operations"][0]["tool"], "astrbot_execute_python")
        self.assertEqual(receipt["calls"][0]["operations"][0]["verification_output"], "PASS approved operation")
        self.assertNotIn("APPROVAL_SCRIPT_DO_NOT_CARRY", json.dumps(reduced))
        self.assertNotIn("APPROVAL_SCRIPT_DO_NOT_CARRY", self.requests[-1]["prompt"])
        self.assertFalse(any(row.get("tool_call_id") or row.get("tool_calls") for row in reduced))
        self.assertEqual(encoded(self.archive()["history"]), original)
        self.assertFalse(any(row["name"] == "task_approve" for row in C.state_of(self.load())["journal"]))
        # No direct task_approve journal is needed or invented.
        for current_result in ("Error: approval rejected", "请把批次缩小到可完整审阅的范围。", ""):
            raw = deepcopy(history)
            raw[-1]["content"] = current_result
            self.assertEqual(self.payload_view(raw), raw)

    async def test_timeout_continuation_reads_real_source_from_receipts_and_executes_verifier(self):
        source = self.root / "source with spaces.py"
        content = "# REAL_WRITTEN_SOURCE\n" * 2000 + (
            "def normalize(value):\n    return '' if value is None else str(value).strip().lower()\n")
        source.write_text(content, encoding="utf-8")
        write_args = {"path": str(source), "content": content}
        write_output = f"File written successfully: {source}"
        self.journal("astrbot_file_write_tool", write_args, write_output)
        script = "# REAL_EXECUTED_CODE\n" * 500 + (
            f"from pathlib import Path\nassert Path({str(source)!r}).is_file()\nprint('PASS source exists')\n")
        execution = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(execution.returncode, 0, execution.stderr)
        exec_output = json.dumps({"exit_code": execution.returncode, "stdout": execution.stdout, "stderr": execution.stderr})
        self.journal("astrbot_execute_python", {"code": script}, exec_output)
        history = [*group(("astrbot_file_write_tool", write_args, write_output)),
                   *group(("astrbot_execute_python", {"code": script}, exec_output)),
                   {"role": "user", "content": "从实际文件验证 normalize(None)、字符串和数字"}]
        for mode in ("empty", "timeout", "error"):
            with self.subTest(summary=mode):
                before = len(self.requests)

                def inspect(kwargs):
                    # The full signed history is already on disk before the only summary call.
                    draft = C.lane_state(self.load())["draft_record_id"]
                    archive = self.continuity.directory(self.task) / f"{draft}.json"
                    self.assertEqual(encoded(json.loads(archive.read_text(encoding="utf-8"))["history"]), encoded(history))

                reduced = await self.compact(history, mode, limit=16000, inspect=inspect)
                self.assertEqual(len(self.requests), before + 1)
                self.assertEqual(self.archive()["summary"], "")
                facts = [fact for receipt in receipt_data(reduced) for fact in receipt["calls"]]
                self.assertEqual(len(facts), 2)
                self.assertIn("PASS source exists", facts[-1]["verification_output"])
                # An acting adapter uses only the delivered facts, not a journal ID lookup.
                received_path = next(path for fact in facts for path in fact["paths"] if path.endswith(".py"))
                current_source = Path(received_path).read_text(encoding="utf-8")
                self.assertIn("def normalize(value):", current_source)
                verification = self.root / "verify.py"
                verification.write_text(
                    "import runpy, sys\nf = runpy.run_path(sys.argv[1])['normalize']\n"
                    "assert f(None) == ''\nassert f(' AbC ') == 'abc'\nassert f(0) == '0'\n"
                    "print('PASS normalize receipt continuation')\n", encoding="utf-8")
                checked = subprocess.run([sys.executable, "-B", str(verification), received_path],
                                         capture_output=True, text=True, timeout=10)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIn("PASS normalize receipt continuation", checked.stdout)
                for receipt in receipt_data(reduced):
                    self.assertTrue(Path(receipt["archive_path"]).is_file())
                    archived = json.loads(Path(receipt["archive_path"]).read_text(encoding="utf-8"))
                    self.assertEqual(encoded(archived["history"]), encoded(history))
                self.assertNotIn("REAL_WRITTEN_SOURCE", json.dumps(reduced))
                self.assertNotIn("REAL_EXECUTED_CODE", self.requests[-1]["prompt"])

    async def test_helper_refuses_missing_archive_and_brief_retains_distinct_entry_facts(self):
        source, arguments, output = self.write_operation()
        self.journal("astrbot_file_write_tool", arguments, output)
        history = group(("astrbot_file_write_tool", arguments, output))
        with self.assertRaises(C.HandoffError):
            C.handoff_payloads(history, C.state_of(self.load())["journal"], self.root / "missing.json",
                               storage_root=self.storage.root)
        task = self.load()
        task.task_brief, task.entry_summary = "任务计划：保留接口", "入口事实：收到确认后再发布"
        self.storage.save_task(task)
        await self.compact(history)
        plan = json.loads(self.requests[-1]["prompt"])["current_plan"]
        self.assertEqual(plan["brief"], task.task_brief + "\n\n" + task.entry_summary)
        self.assertEqual(plan["constraints"], ["必须保留接口"])
        self.assertTrue(source.is_file())

    async def test_old_receipts_share_recent_budget_instead_of_accumulating_forever(self):
        rows=[{"role":"user","content":C.RECEIPT_MARKER+'\n'+json.dumps({
            'archive_path':str(self.root/'old.json'),'calls':[{'tool':'astrbot_file_write_tool',
            'paths':[str(self.root/f'file_{index}.py')],'status':'completed','verification_output':'ok '*200}]})}
              for index in range(150)]
        result=await self.compact(rows,'empty',limit=12000)
        self.assertGreater(len(receipt_data(result)),0)
        self.assertLess(len(receipt_data(result)),len(rows))
        self.assertLess(C.estimate(result),12000)
        self.assertEqual(encoded(self.archive()['history']),encoded(rows))
        self.assertIn('file_149.py',json.dumps(result))


if __name__ == "__main__":
    unittest.main(verbosity=2)
