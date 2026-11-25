"""v0.4 boundary regressions: actual files/processes, result-driven loop guards.

Run: python -B scripts/ui/test_v04_guards.py -v
Runtime adapters exercise deadlines/prompts only; they do not simulate an LLM
or claim to validate a model's ability to edit a project end to end.
"""
from __future__ import annotations

import asyncio
import ast
import importlib
import json
import subprocess
import sys
import tempfile
import time
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "v04_guards_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


Models, Permissions, Guard, Settings = [module(n) for n in
                                      ("models", "task_permissions", "progress_guard", "execution_settings")]
with patch.dict(sys.modules, {PACKAGE + ".hooks": S(AgentLabRunHooks=lambda *a, **k: None)}):
    Runtime = module("runtime_runner")
Storage = module("storage").AgentLabStorage
Metrics = module("usage_metrics")


def task_fixture():
    task = Models.TaskState(umo="test:FriendMessage:1", root_goal="研究并验证代码")
    task.status = "running"
    task.workflow_data["task_control"] = dict(version=1, approved_version=1, workflow="none", journal=[],
        execution_cwd="/project", current_step_id="one",
        steps=[dict(id="one", title="定位问题", instruction="定位问题", status="running")])
    return task


def row(name="astrbot_file_read_tool", arguments=None, status="completed", **extra):
    return dict(name=name, arguments=arguments or {"path": "/project/a.py"}, status=status, **extra)


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.state = {"execution_settings": {"mode": "standard", "roots": ["/project"]},
                      "execution_cwd": "/project"}

    def test_routine_development_ignores_generic_high_risk_labels(self):
        calls = [row("astrbot_execute_shell", {"command": "python -m pytest -q && npm test > result.txt"}),
                 row("astrbot_execute_python", {"code": "from pathlib import Path; Path('a.py').write_text('ok')"}),
                 row("astrbot_execute_shell", {"command": "rg needle src | head -20"}),
                 row("astrbot_execute_shell", {"command": "git diff && python scripts/check.py"}),
                 row("astrbot_execute_shell", {"command": "rm -f /project/a.tmp /project/b.tmp"}),
                 row("astrbot_execute_shell", {"command": "rm /project/*.tmp"}),
                 row("astrbot_execute_shell", {"command": "cat $SOURCE"}),
                 row("astrbot_execute_shell", {"command": "printf /outside/example.txt > /project/docs.md"}),
                 row("astrbot_execute_shell", {"command": "cd /project/sub && cat ../a.py && cd /project"}),
                 row("astrbot_execute_shell", {"command": "git clean --dry-run"}),
                 row("astrbot_execute_python", {"code": "print('DROP DATABASE is documentation')"}),
                 row("astrbot_execute_python", {"code": "db.delete_many({'test': True})"}),
                 row("astrbot_file_write_tool", {"path": "/project/README.md", "content": "DROP DATABASE prod"})]
        for mode in ("standard", "full"):
            self.state["execution_settings"]["mode"] = mode
            for call in calls:
                with self.subTest(mode=mode, call=call):
                    self.assertEqual(Permissions.assess(call["name"], call["arguments"], self.state, "high")[0], "allow")

    def test_explicit_escape_secrets_and_destructive_actions_require_review(self):
        calls = [row(arguments={"path": "/outside/a.py"}), row(arguments={"path": "../secret.txt"}),
                 row(arguments={"path": "/project/.env"}), row(arguments={"path": "/project/id_ed25519"}),
                 row(arguments={"path": "/project/key.pem"}),
                 row("astrbot_execute_shell", {"command": "cat $SOURCE/.env"}),
                 row("astrbot_execute_shell", {"command": "rm -rf /project/cache.v1"}),
                 row("astrbot_execute_shell", {"command": "rm /project/*"}),
                 row("astrbot_execute_shell", {"command": "git reset --hard"}),
                 row("astrbot_execute_shell", {"command": 'mysql -e "DROP DATABASE prod"'}),
                 row("astrbot_execute_shell", {"command": "mkfs.ext4 /dev/sda"}),
                 row("astrbot_execute_shell", {"command": "redis-cli FLUSHALL"}),
                 row("astrbot_execute_shell", {"command": "Stop-Computer -Force"}),
                 row("astrbot_delete_directory", {"path": "/project/cache", "recursive": True}),
                 row("astrbot_execute_python", {"code": "import shutil; shutil.rmtree('/project/cache.v1')"}),
                 row("astrbot_execute_python", {"code": "import subprocess; subprocess.run(['rm', '-rf', '/project'])"}),
                 row("astrbot_execute_python", {"code": "connection.execute('DELETE FROM users; SELECT 1 WHERE 1=1')"})]
        for mode in ("standard", "full"):
            self.state["execution_settings"]["mode"] = mode
            for call in calls:
                with self.subTest(mode=mode, call=call):
                    self.assertEqual(Permissions.assess(call["name"], call["arguments"], self.state)[0], "review")

    def test_readonly_stays_conservative_and_compound_queries_are_allowed(self):
        self.state["execution_settings"]["mode"] = "readonly"
        self.assertEqual(Permissions.assess("astrbot_execute_shell", {"command": "ls /project && git status"}, self.state)[0], "allow")
        for call in (row("astrbot_file_write_tool"), row("astrbot_execute_shell", {"command": "python -m pytest"}),
                     row("astrbot_execute_python", {"code": "print('hello')"})):
            self.assertEqual(Permissions.assess(call["name"], call["arguments"], self.state)[0], "deny")
        self.assertFalse(Permissions.read_only_call("astrbot_execute_shell", {"command": "rg --pre script.py needle"}))

    def test_administrator_roots_and_explicit_rules_stay_authoritative(self):
        self.state.update(scope_roots=["/outside"], authorized_scope_roots=["/project"])
        self.assertEqual(Permissions.assess("astrbot_file_read_tool", {"path": "/outside/a.py"}, self.state)[0], "review")
        self.state["execution_settings"]["warnings"] = ["审批:*/deploy.py"]
        self.assertEqual(Permissions.assess("astrbot_file_write_tool", {"path": "/project/deploy.py"}, self.state)[0], "review")

    def test_refusals_never_change_lifecycle_or_return_legacy_stop_text(self):
        task = task_fixture()
        for _ in range(12):
            self.assertEqual(Permissions.record_guard_refusal(task, "明确越界"), "")
        self.assertEqual(task.status, "running")
        self.assertFalse(task.workflow_data["task_control"].get("human_paused"))
        self.assertNotEqual(task.wait.wait_reason, "guard_retry_limit")

    def test_archive_root_allows_only_text_reads_and_no_escapes(self):
        self.state["task_data_root"] = "/task-data/task-1"
        for name in Permissions.READ_TOOLS:
            self.assertEqual(Permissions.assess(name, {"path": "/task-data/task-1/results/full.txt"}, self.state)[0], "allow")
        for path in ("/task-data/task-1/../task-2/full.txt", "/task-data/task-1/.env.txt", "/task-data/task-1/key.pem", "/task-data/task-1/blob.bin"):
            self.assertEqual(Permissions.assess("astrbot_file_read_tool", {"path": path}, self.state)[0], "review")
        for name in ("astrbot_file_write_tool", "astrbot_file_edit_tool"):
            self.assertEqual(Permissions.assess(name, {"path": "/task-data/task-1/results/full.txt"}, self.state)[0], "review")
        self.assertEqual(Permissions.assess("astrbot_execute_shell", {"command": "cat /task-data/task-1/results/full.txt"}, self.state)[0], "review")

    def test_real_symlink_cannot_escape_scope_or_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project, outside = base / "project", base / "outside"
            project.mkdir(); outside.mkdir()
            (outside / "private.txt").write_text("private", encoding="utf-8")
            try:
                (project / "shortcut.txt").symlink_to(outside / "private.txt")
            except OSError as exc:
                self.skipTest(f"Host cannot create symlinks: {exc}")
            self.state["execution_settings"]["roots"] = [str(project)]
            self.state["task_data_root"] = str(project)
            self.assertEqual(Permissions.assess("astrbot_file_read_tool", {"path": str(project / "shortcut.txt")}, self.state)[0], "review")

    def test_windows_roots_traversal_and_recursive_delete(self):
        state = {"execution_settings": {"mode": "standard", "roots": [r"C:\project"]},
                 "execution_cwd": r"C:\project", "task_data_root": r"C:\tasks\one"}
        for path, expected in [(r"C:\PROJECT\src\a.py", "allow"), (r"C:\project-other\a.py", "review"),
                               (r"..\private\a.py", "review"), (r"C:\tasks\one\output.txt", "allow")]:
            self.assertEqual(Permissions.assess("astrbot_file_read_tool", {"path": path}, state)[0], expected)
        self.assertEqual(Permissions.assess("astrbot_execute_shell", {"command": r"del /q C:\project\one.tmp"}, state)[0], "allow")
        self.assertEqual(Permissions.assess("astrbot_execute_shell", {"command": r"rd /s /q C:\project\cache.v1"}, state)[0], "review")


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.task = task_fixture()

    def observe(self, record):
        return Guard.observe_tool(self.task, record)

    def failure(self, **kw):
        return row("astrbot_execute_shell", {"command": "pytest"}, "failed", error="FileNotFoundError: missing config", **kw)

    def test_three_equivalent_errors_warn_once_then_continued_errors_pause(self):
        notices = []
        for i in range(5):
            record = self.failure(id=f"call-{i}")
            record["error"] += f" at line {10 + i} attempt {i} request_{i}"
            notices.append(self.observe(record))
            self.assertEqual(self.task.status, "paused" if i == 4 else "running")
        self.assertEqual([bool(n) for n in notices], [False, False, True, False, True])
        self.assertEqual(self.task.wait.wait_reason, "repeated_tool_error")

    def test_other_tool_or_success_or_different_error_breaks_error_streak(self):
        for i in range(40):
            record = self.failure()
            record["name"] = "tool_a" if i % 2 else "tool_b"
            self.assertEqual(self.observe(record), "")
        for _ in range(20):
            self.observe(self.failure())
            self.observe(row("astrbot_execute_shell", {"command": "pwd"}))
            record = self.failure(); record["error"] = "PermissionError: denied"
            self.observe(record)
            self.observe(row())
        self.assertEqual(self.task.status, "running")

    def test_callback_and_tick_fallback_count_each_record_once(self):
        before = Guard.snapshot(self.task)
        record = self.failure(id="unique")
        self.task.workflow_data["task_control"]["journal"].append(record)
        for _ in range(10):
            self.observe(record)
            Guard.after_tick(self.task, before, reason="fallback")
        self.assertEqual(self.task.workflow_data["progress_guard"]["failure_ticks"], 1)

    def test_many_quiet_ticks_or_provider_errors_never_pause(self):
        for _ in range(80):
            self.assertEqual(Guard.after_tick(self.task, Guard.snapshot(self.task), reason="analysis", error="TimeoutError"), "")
        self.assertEqual(self.task.status, "running")
        self.assertNotIn("progress_guard", self.task.workflow_data)

    def test_research_on_new_paths_is_progress_without_writes(self):
        for i in range(60):
            self.assertEqual(self.observe(row(arguments={"path": f"/project/module-{i}.py"})), "")
            self.assertEqual(self.task.workflow_data["progress_guard"]["decision"], "progress")
        self.assertEqual(self.task.status, "running")

    def test_high_overlap_offsets_and_python_wrappers_cannot_manufacture_progress(self):
        self.observe(row(arguments={"path": "/project/a.py", "offset": 0, "limit": 800}))
        notices = []
        for i in range(26):
            record = row(arguments={"path": "/project/a.py", "offset": i % 4, "limit": 700})
            if i % 2:
                record = row("astrbot_execute_python", {"code": "from pathlib import Path; print(Path('/project/a.py').read_text())"})
            notices.append(self.observe(record))
        self.assertEqual(self.task.status, "paused")
        self.assertEqual(self.task.wait.wait_reason, "repeated_reads")
        self.assertEqual(sum(bool(n) for n in notices), 2)

    def test_disjoint_read_regions_are_never_classified_as_overlap(self):
        for i in range(60):
            self.assertEqual(self.observe(row(arguments={"path": "/project/a.py", "offset": 100 * i, "limit": 100})), "")
        self.assertEqual(self.task.status, "running")
        self.assertEqual(self.task.workflow_data["progress_guard"]["signals"]["paths"], 0)

    def test_python_disjoint_slices_and_literal_variable_paths_are_not_false_stalls(self):
        for i in range(40):
            code = f"from pathlib import Path; p = Path('/project/a.py'); print(p.read_text().splitlines()[{i * 100}:{(i + 1) * 100}])"
            self.assertEqual(self.observe(row("astrbot_execute_python", {"code": code})), "")
        self.assertEqual(self.task.status, "running")
        self.assertEqual(self.task.workflow_data["progress_guard"]["signals"]["paths"], 0)

    def test_python_open_wrappers_and_new_offsets_do_not_hide_repeated_reads(self):
        for i in range(30):
            code = "with open('/project/a.py') as f: print(f.read())"
            record = row("astrbot_execute_python", {"code": code}) if i % 2 else row(arguments={"path": "/project/a.py", "offset": i % 4, "limit": 700})
            self.observe(record)
        self.assertEqual(self.task.status, "paused")

    def test_successful_python_edits_count_as_progress_but_replaying_them_does_not(self):
        record = row("astrbot_execute_python", {"code": "from pathlib import Path; Path('/project/a.py').write_text('ok')"})
        self.observe(record)
        self.assertEqual(self.task.workflow_data["progress_guard"]["signals"]["writes"], 1)
        self.observe(record)
        self.assertEqual(self.task.workflow_data["progress_guard"]["signals"]["writes"], 0)

    def test_windows_path_aliases_share_read_coverage(self):
        self.task.workflow_data["task_control"]["execution_cwd"] = r"C:\project"
        for i in range(26):
            path = r"C:\PROJECT\src\a.py" if i % 2 else "src/a.py"
            self.observe(row(arguments={"path": path}))
        self.assertEqual(self.task.status, "paused")
        self.assertEqual(len(self.task.workflow_data["progress_guard"]["seen_paths"]), 1)

    def test_warning_is_cleared_by_new_path_or_a_real_edit(self):
        self.observe(row())
        for _ in range(18):
            self.observe(row())
        self.assertTrue(self.task.workflow_data["progress_guard"].get("read_warned"))
        self.observe(row(arguments={"path": "/project/another.py"}))
        self.assertFalse(self.task.workflow_data["progress_guard"].get("read_warned"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "big.py"
            path.write_text("# source\n" * 1800, encoding="utf-8")
            process = subprocess.run([sys.executable, "-c", "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text(p.read_text() + 'value = 42\\n')", str(path)], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(path.read_text().endswith("value = 42\n"))
            self.observe(row("astrbot_execute_shell", {"command": "python edit.py"}, changed_paths=[str(path)]))
            self.assertEqual(self.task.workflow_data["progress_guard"]["signals"]["writes"], 1)

    def test_pause_and_unapproved_plan_are_never_overwritten(self):
        for status in ("paused", "stopped", "completed"):
            self.task.status = status
            for _ in range(10):
                self.assertEqual(self.observe(self.failure()), "")
            self.assertEqual(self.task.status, status)
        self.task.status = "running"
        self.task.workflow_data["task_control"]["human_paused"] = True
        self.assertEqual(self.observe(self.failure()), "")
        self.assertNotIn("progress_guard", self.task.workflow_data)

    def test_persisted_warning_survives_reload_and_fallback_notice_is_consumed_once(self):
        before = Guard.snapshot(self.task)
        journal = self.task.workflow_data["task_control"]["journal"]
        journal.extend(self.failure(id=f"f{i}") for i in range(3))
        self.assertTrue(Guard.after_tick(self.task, before, reason="legacy"))
        self.assertTrue(Guard.take_notice(self.task))
        self.assertEqual(Guard.take_notice(self.task), "")
        restored = Models.TaskState.from_dict(json.loads(json.dumps(self.task.to_dict())))
        self.task = restored
        self.assertEqual(self.observe(self.failure(id="f3")), "")
        self.assertTrue(self.observe(self.failure(id="f4")))
        self.assertEqual(self.task.status, "paused")


class SettingsTests(unittest.TestCase):
    def test_unfragmented_default_and_explicit_total_seconds(self):
        self.assertEqual(Settings.normalize({})["round_tool_limit"], 0)
        self.assertEqual(Settings.normalize({"round_tool_limit": 0})["round_tool_limit"], 0)
        self.assertEqual(Settings.normalize({"round_tool_limit": 32})["round_tool_limit"], 32)
        self.assertEqual(Settings.normalize({"budget": {"max_total_seconds": 604800}})["budget"]["max_total_seconds"], 604800)
        for key, value in (("round_tool_limit", -1), ("round_tool_limit", 10001)):
            with self.assertRaises(ValueError): Settings.normalize({key: value})
        with self.assertRaises(ValueError): Settings.normalize({"budget": {"max_total_seconds": 604801}})

    def test_total_clock_includes_waiting_and_supports_legacy_budget(self):
        task = task_fixture()
        task.budget = S()
        self.assertIsNone(Runtime.total_remaining_seconds(task))
        task.workflow_data["task_control"]["execution_settings"] = {"budget": {"max_total_seconds": 10}}
        task.created_at = (datetime.now(timezone.utc) - timedelta(seconds=11)).isoformat()
        self.assertEqual(Runtime.total_remaining_seconds(task), 0)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "data")
        task = task_fixture()
        task.budget.max_total_ticks = task.budget.max_total_tokens = task.budget.max_total_tool_calls = 0
        self.storage.save_task(task)
        self.task = task
        self.calls = []
        self.delay = 0
        async def run(*args):
            self.calls.append(args)
            await asyncio.sleep(self.delay)
            return S(completion_text="已执行验证")
        async def true(*a, **kw): return True
        async def workflow(**kw):
            return S(changed=False, needs_react=True, blocked=False, react_node_id="", summary=lambda: "")
        def pause(task, message):
            task.status = "paused"; task.watchdog.paused_reason = message
            task.set_wait(wait_reason="budget_exhausted", message=message, source="budget")
        def noop(*a, **kw): pass
        self.owner = S(storage=self.storage, config={}, _running_ticks=set(), task_messages=None, task_control=S(),
            _global_tick_semaphore=None, _require_task_access=noop,
            _acquire_task_lease=lambda *a, **kw: (True, "lease"), _release_task_lease=noop,
            _watchdog_before_tick=lambda *a: "", _pause_task_for_budget=pause,
            _prepare_resume_anchor=noop, _normalize_agent_workflow=noop, _sync_agent_runtime=noop,
            _run_workflow_runtime=workflow, _budget_remaining_tools=lambda task: sys.maxsize,
            _build_toolset=lambda *a: S(tools=[]), _record_react_trace=noop, _record_explicit_observation=noop,
            _compact_text=lambda text, limit: text[:limit], _disable_heartbeat=true,
            astrbot_bridge=S(resume_batch=true, run=run), context=S(get_current_chat_provider_id=true),
            agent_runtime=S(record_decision=noop, record_verdict=noop, record_pause=noop, update_resume=noop))
        self.owner._build_task_extensions_prompt = lambda *a, **kw: self.fail("Plain tasks must not load canvas prompts")
        self.runner = Runtime.AgentRuntimeRunner(self.owner)
        self.event = S(unified_msg_origin=task.umo, set_extra=noop)

    async def asyncTearDown(self):
        self.assertFalse(self.owner._running_ticks)
        self.temp.cleanup()

    async def test_plain_task_has_no_round_deadline_and_system_plan_is_stable(self):
        self.task.budget.max_seconds_per_tick = 1
        self.storage.save_task(self.task)
        self.delay = 1.05
        text = await self.runner.run_tick(self.event, "test")
        self.assertIn("tick 完成", text)
        system, prompt = self.calls[0][4], self.calls[0][3]
        self.assertIn("task_finish", system)
        self.assertNotIn("agent_lab_", system + prompt)
        self.assertNotIn("定位问题", system)
        self.assertIn("定位问题", prompt)
        self.task.workflow_data["task_control"]["steps"][0]["instruction"] = "执行新的验证"
        other_system, other_prompt = self.runner._task_prompts(self.task, Models.AgentSpec.from_dict(self.task.profile_snapshot.get("agent")), "later")
        self.assertEqual(system, other_system)
        self.assertIn("执行新的验证", other_prompt)

    def test_plain_user_plan_retains_handoff_brief_without_changing_system_prefix(self):
        original_system, _ = self.runner._task_prompts(self.task, None, "test")
        cases = [("接口 submit_job(payload)，不可修改签名", "仅写入授权目录，不触碰凭据"),
                 ("", "旧任务入口摘要：保留 callback_id"),
                 ("相同交接说明", "相同交接说明"), ("", "")]
        for brief, summary in cases:
            with self.subTest(brief=brief, summary=summary):
                self.task.task_brief, self.task.entry_summary = brief, summary
                restored = Models.TaskState.from_dict(json.loads(json.dumps(self.task.to_dict())))
                system, prompt = self.runner._task_prompts(restored, None, "handoff")
                plan = json.loads(prompt.partition("]\n")[2])
                self.assertEqual(system, original_system)
                self.assertEqual(plan["brief"], "\n\n".join(dict.fromkeys(v for v in (brief, summary) if v)))
                self.assertIn("task_finish", system)
                self.assertNotIn("agent_lab_", system + prompt)

    def test_execution_revision_tracks_authority_and_input_but_retains_approval_checks(self):
        state = self.task.workflow_data["task_control"]
        before = self.runner._execution_revision(self.task)
        state.update(version=2, approved_version=2, authorization_version=1)
        self.assertEqual(before, self.runner._execution_revision(self.task))
        self.assertFalse(self.runner._execution_stopped(self.task, before))
        for change in ({"authorization_version": 2}, {"input_revision": 1}, {"approved_version": 0},
                       {"version": 3}, {"human_paused": True}):
            with self.subTest(change=change):
                changed = Models.TaskState.from_dict(self.task.to_dict())
                changed.workflow_data["task_control"] = dict(state, **change)
                self.assertTrue(self.runner._execution_stopped(changed, before))

    async def test_real_plan_revision_during_loop_does_not_discard_final_response(self):
        Control = module("task_control")
        self.owner.task_control = Control.TaskControl(self.owner)
        self.owner._redact_known_secrets = lambda value: value
        self.task.workflow_data["task_control"]["owner_id"] = "1"
        self.storage.save_task(self.task)
        traces = []
        self.owner._record_react_trace = lambda task, **kw: traces.append(kw)
        async def run(*args):
            self.calls.append(args)
            # Execute the real task_plan implementation, including its persisted
            # version/approval changes and the legacy authority fallback.
            result = await self.owner.task_control.submit_plan(self.event, json.dumps({"steps": [
                {"id": "one", "title": "定位问题", "instruction": "保留接口，补充边界验证", "status": "running"},
                {"id": "two", "title": "执行测试", "instruction": "运行验证命令"}]}))
            self.assertIn("已调整", result)
            return S(completion_text="计划已更新，真实执行结果仍应记录")
        self.owner.astrbot_bridge.run = run
        text = await self.runner.run_tick(self.event, "routine_plan_revision")
        self.assertIn("tick 完成", text)
        self.assertNotIn("停止接收旧执行结果", text)
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0]["response"], "计划已更新，真实执行结果仍应记录")
        latest = self.storage.load_active_task(self.task.umo)
        state = latest.workflow_data["task_control"]
        self.assertEqual((state["version"], state["approved_version"], state["authorization_version"]), (2, 2, 1))
        self.assertEqual(latest.status, "running")
        self.assertTrue(any(log["kind"] == "tick" for log in latest.progress_log))

    async def test_total_deadline_cancels_long_loop_and_pauses_for_budget(self):
        self.task.budget.max_total_seconds = 1
        self.task.created_at = (datetime.now(timezone.utc) - timedelta(seconds=0.8)).isoformat()
        self.storage.save_task(self.task)
        self.delay = 0.5
        text = await self.runner.run_tick(self.event, "test")
        latest = self.storage.load_active_task(self.task.umo)
        self.assertEqual(latest.status, "paused", text)
        self.assertEqual(latest.wait.wait_reason, "budget_exhausted")
        self.assertIn("总耗时", text)

    async def test_total_tokens_still_stop_before_model_dispatch(self):
        self.task.budget.max_total_tokens = self.task.budget.tokens_used = 10
        self.storage.save_task(self.task)
        self.assertIn("token", await self.runner.run_tick(self.event, "test"))
        self.assertEqual(self.calls, [])

    async def test_unreported_token_estimates_exhaust_total_budget_before_dispatch(self):
        self.task.budget.tokens_used = 17
        payload = {"prompt": "actual request content " * 30, "contexts": [], "system_prompt": "test"}
        sizes = Metrics.request_size(payload, payload)
        estimated = sizes["estimated_tokens"]
        self.task.budget.max_total_tokens = 17 + 2 * estimated
        Metrics.record_request(self.task, sizes, usage=None)
        self.assertEqual(Metrics.budget_tokens(self.task), 17 + estimated)
        self.assertEqual(self.runner._pause_for_total_budget(self.task, tick_finished=False), "")
        Metrics.record_request(self.task, sizes, usage=None)
        self.assertEqual(self.task.budget.tokens_used, 17, "Estimates must not become reported usage")
        self.assertEqual(Metrics.budget_tokens(self.task), self.task.budget.max_total_tokens)
        self.storage.save_task(self.task)
        result = await self.runner.run_tick(self.event, "estimated_hard_budget")
        latest = self.storage.load_active_task(self.task.umo)
        self.assertEqual(latest.status, "paused", result)
        self.assertEqual(latest.wait.wait_reason, "budget_exhausted")
        self.assertIn("token", result)
        self.assertEqual(self.calls, [], "No model request may start at the estimated hard limit")

    async def test_real_bridge_metering_pauses_when_an_unreported_response_crosses_hard_budget(self):
        # Execute the production nested provider wrapper without starting a host
        # runner. Its real check/storage/telemetry/stop logic remains intact;
        # only the external provider returns an ordinary response with no usage.
        Bridge = module("astrbot_bridge")
        self.owner.projects = S(cleaning=set())
        bridge = Bridge.AstrBotBridge(self.owner)
        task = self.storage.load_active_task(self.task.umo)
        task.budget.tokens_used = 11
        task.budget.max_total_tokens = 100
        self.storage.save_task(task)
        event = S(unified_msg_origin=task.umo, get_extra=lambda key, default=None: default)
        requests = []
        async def text_chat(**kwargs):
            requests.append(kwargs)
            return S(completion_text="provider returned without usage", usage=None)
        tree = ast.parse((ROOT / "agent_lab/astrbot_bridge.py").read_text(encoding="utf-8"))
        wrapper = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "MeteredProvider")
        namespace = dict(vars(Bridge), bridge=bridge, provider=S(text_chat=text_chat),
                         task=task, event=event, boundary_stopped=False, time=time, wake_metric=None)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[])),
                     str(ROOT / "agent_lab/astrbot_bridge.py"), "exec"), namespace)
        metered = namespace["MeteredProvider"]()
        payload = {"prompt": "request without reported usage " * 100, "contexts": [], "system_prompt": "test"}
        estimate = Metrics.request_size(payload, payload)["estimated_tokens"]
        self.assertGreater(11 + estimate, task.budget.max_total_tokens)
        with self.assertRaises(Bridge.BudgetStopped):
            await metered.text_chat(**payload)
        latest = self.storage.load_active_task(task.umo)
        self.assertEqual(len(requests), 1)
        self.assertEqual(latest.status, "paused")
        self.assertEqual(latest.wait.wait_reason, "budget_exhausted")
        self.assertEqual(latest.budget.tokens_used, 11)
        self.assertEqual(Metrics.budget_tokens(latest), 11 + estimate)
        telemetry = latest.workflow_data["usage_metrics"]
        self.assertEqual(telemetry["unreported_calls"], 1)
        self.assertEqual(telemetry["reported_calls"], 0)
        self.assertIsNone(telemetry["last_request"]["reported_tokens"])
        usage_path = self.storage.task_memory_dir(task.umo, task.task_id) / "usage.jsonl"
        self.assertEqual(json.loads(usage_path.read_text(encoding="utf-8"))["estimated_tokens"], estimate)
        with self.assertRaises(Bridge.ExecutionStopped):
            await metered.text_chat(**payload)
        self.assertEqual(len(requests), 1, "The hard stop must prevent a further provider request")

    async def test_fallback_warning_consumption_survives_storage_reload(self):
        latest = self.storage.load_active_task(self.task.umo)
        latest.workflow_data["progress_guard"] = {"version": 2, "pending_notice": "一次温和提示"}
        self.storage.save_task(latest)
        self.assertIn("一次温和提示", self.runner._liveness_notice(latest))
        reloaded = self.storage.load_active_task(self.task.umo)
        self.assertEqual(self.runner._liveness_notice(reloaded), "")


if __name__ == "__main__":
    unittest.main()
