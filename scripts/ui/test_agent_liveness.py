"""Finite liveness simulations with real tick/storage logic and no live SDK.

Only TemporaryDirectory tasks/files are used. Model, tools and transport are
deterministic adapters; the transport raises if anything tries to send.
"""
from __future__ import annotations

import ast
import asyncio
import hashlib
import importlib
import json
import platform
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
PACKAGE = "liveness_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


Models, Control, Guard = module("models"), module("task_control"), module("progress_guard")
Storage = module("storage").AgentLabStorage
Bridge = module("astrbot_bridge")
with patch.dict(sys.modules, {PACKAGE + ".hooks": S(AgentLabRunHooks=lambda *a, **k: None)}):
    Runtime = module("runtime_runner")
Messages = module("task_messages").TaskMessages


# Use the adapter's actual preflight budgets/leases without importing main.py
# (which starts SDK integrations). The new after_tick must supersede legacy.
METHODS = {"_watchdog_before_tick", "_budget_before_tick", "_configure_task_budget",
           "_total_budget_reason", "_budget_remaining_tools", "_budget_tick_payload",
           "_pause_task_for_budget", "_prepare_resume_anchor", "_acquire_task_lease",
           "_release_task_lease", "_lease_expired", "_task_lease_owner", "_parse_iso_datetime",
           "_progress_hash", "_watchdog_after_tick"}
tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
methods = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in METHODS]
if {n.name for n in methods} != METHODS:
    raise RuntimeError("Actual adapter fixture methods changed; update the extraction explicitly")
namespace = dict(Any=object, TaskState=Models.TaskState, now_iso=Models.now_iso, new_id=Models.new_id,
                 datetime=datetime, timedelta=timedelta, timezone=timezone, json=json, hashlib=hashlib,
                 task_control=Control.control, TaskControl=Control.TaskControl,
                 native_steps=lambda *a: 24, _cfg=lambda config, key, default=None: config.get(key, default))
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="Adapter", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])),
    "<actual-adapter>", "exec"), namespace)
Adapter = namespace["Adapter"]
RESULTS = []


def source_fingerprints():
    paths = ["agent_lab/progress_guard.py", "agent_lab/runtime_runner.py", "scripts/ui/test_agent_liveness.py",
             "main.py", "agent_lab/task_control.py", "agent_lab/astrbot_bridge.py", "agent_lab/task_messages.py",
             "agent_lab/continuity.py", "agent_lab/models.py", "agent_lab/storage.py", "agent_lab/task_permissions.py"]
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in paths}


class LivenessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Storage(Path(self.temp.name) / "data")
        self.owner = Adapter()
        owner = self.owner
        owner.storage, owner.config, owner._running_ticks = self.storage, {}, set()
        owner._require_task_access = lambda event: None
        owner._redact_known_secrets = lambda text: text
        owner.projects = S(cleaning=set())
        owner.task_control = S()
        owner._ensure_workflow_data = lambda task: task.workflow_data
        owner.agent_runtime = module("agent_runtime").AgentRuntime()
        owner._normalize_agent_workflow = lambda *a: None
        owner._sync_agent_runtime = lambda *a, **k: None
        owner._build_task_extensions_prompt = lambda *a, **k: ""
        owner._build_toolset = lambda *a: S(tools=[])
        owner._record_react_trace = lambda *a, **k: None
        owner._record_explicit_observation = lambda *a, **k: None
        owner._compact_text = lambda text, limit: text[:limit]
        self.model_calls, self.prompts, self.sent, self.disabled = 0, [], [], []

        async def send(*args):
            self.sent.append(args)
            raise AssertionError("Simulation must never send a message")

        async def disable(task):
            self.disabled.append(task.task_id)
            task.heartbeat.enabled, task.heartbeat.job_id = False, ""

        async def provider(umo):
            return "deterministic-only"

        async def batch(*args):
            return True

        async def workflow(**kwargs):
            return S(changed=False, needs_react=True, blocked=False, react_node_id="", summary=lambda: "")

        async def run(*args):
            self.model_calls += 1
            self.prompts.append(args[3])
            if self.action:
                await self.action()
            return S(completion_text=f"模拟成功 {self.model_calls}，尚未提供成果")

        owner.context = S(get_current_chat_provider_id=provider)
        owner._disable_heartbeat = disable
        owner._run_workflow_runtime = workflow
        owner.astrbot_bridge = S(resume_batch=batch, run=run)
        owner.task_messages = Messages(owner, send=send)
        task = Models.TaskState(umo="fixture:FriendMessage:123", root_goal="仅测试临时任务")
        Control.control(task).update(owner_id="123", version=1, approved_version=1, workflow="none",
                                     current_step_id="one", automatic=True, human_paused=False,
                                     steps=[dict(id="one", status="pending", title="验证", instruction="验证临时成果", evidence=[])],
                                     journal=[], execution_settings={})
        task.heartbeat.enabled = True
        task.heartbeat.job_id = "fake-job"
        self.storage.save_task(task)
        self.task_id, self.umo = task.task_id, task.umo
        self.event = S(unified_msg_origin=task.umo, set_extra=lambda *a: None, get_sender_id=lambda: "123")
        self.action = None

    def tearDown(self):
        self.assertEqual(self.sent, [])
        self.assertFalse(self.owner._running_ticks)
        self.temp.cleanup()

    def load(self):
        return self.storage.load_active_task(self.umo)

    def save(self, mutate):
        task = self.load()
        mutate(task)
        self.storage.save_task(task)
        return task

    def row(self, task, name="astrbot_execute_shell", arguments=None, status="completed", **extra):
        state = Control.control(task)
        step_id = state["current_step_id"]
        step = next(s for s in state["steps"] if s["id"] == step_id)
        row = dict(id=f"call_{len(state['journal'])}", name=name, arguments=arguments or {"command": "validate fixture"},
                   status=status, step_id=step_id, step_revision=step.get("revision", 0),
                   authorization_version=state.get("authorization_version", state["approved_version"]),
                   result=f"success {len(state['journal'])}", fingerprint=str(len(state['journal'])), **extra)
        state["journal"].append(row)
        return row

    async def tick(self):
        return await Runtime.AgentRuntimeRunner(self.owner).run_tick(self.event, "finite_simulation")

    def record(self, case, **facts):
        task = self.load()
        RESULTS.append(dict(case=case, assertions="passed", model_calls_simulated=self.model_calls,
                            transport_calls=len(self.sent),
                            status=task.status if task else "archived",
                            counters={key: task.workflow_data.get("progress_guard", {}).get(key, 0)
                                      for key in ("no_progress_ticks", "failure_ticks")} if task else {}, **facts))

    async def test_logs_tokens_prose_and_claimed_success_do_not_count(self):
        async def noise():
            def mutate(task):
                task.add_log("success", "仍在工作")
                task.budget.tokens_used += 777
                task.token_usage["total"] += 777
                task.current_summary = f"已成功 {self.model_calls}"
                task.last_observation = f"observation {self.model_calls}"
                task.add_workflow_event("same-node")
            self.save(mutate)
        # Seed the node so noise cannot obtain an initial legitimate visit.
        self.save(lambda task: task.add_workflow_event("same-node"))
        self.action = noise
        for _ in range(2):
            result = await self.tick()
        self.assertIn("卡死预警", result)
        self.assertEqual(self.load().status, "running")
        await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "no_progress"))
        self.assertEqual(task.budget.tokens_used, 2331)
        self.assertFalse(task.heartbeat.enabled)
        stream = self.storage._read_json(self.storage.task_memory_dir(task.umo, task.task_id) / "messages.json")
        self.assertEqual(len(stream["messages"]), 2)
        self.assertTrue(all(r["kind"] == "warning" and r["status"] == "recorded" for r in stream["messages"]))
        for row in stream["messages"]:
            payload = json.loads(row["text"])
            self.assertNotIn("detail", payload)
            self.assertEqual(set(payload), {"reason", "counters"})
            self.assertTrue(all(type(value) is int for value in payload["counters"].values()))
        self.assertEqual(json.loads(stream["messages"][-1]["text"])["counters"]["no_progress_ticks"], 3)
        calls = self.model_calls
        for _ in range(3):
            await self.tick()
        self.assertEqual(self.model_calls, calls)
        self.assertIn("卡死预警", self.prompts[-1])
        self.record("logs_tokens_success_noise", warning_tick=2, pause_tick=3, local_warnings=2, simulated_tokens=2331)

    async def test_repeated_success_with_changing_results_stops(self):
        async def repeat():
            self.save(lambda task: self.row(task))
        self.action = repeat
        for _ in range(4):
            await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 3)
        self.record("same_success_new_ids_and_output", first_novel_call_tick=1, pause_tick=4)

    async def test_repeated_identical_reads_stop(self):
        async def read():
            self.save(lambda task: self.row(task, "astrbot_file_read_tool", {"path": "fixture.txt", "offset": 0, "limit": 10}, read_only=True))
        self.action = read
        for _ in range(4):
            await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.record("repeated_read", pause_tick=4)

    async def test_repeated_same_write_read_cycle_cannot_renew_progress(self):
        async def cycle():
            def work(task):
                self.row(task, "astrbot_file_write_tool", {"path": "fixture.txt", "content": "same content"})
                self.row(task, "astrbot_file_read_tool", {"path": "fixture.txt"}, read_only=True)
            self.save(work)
        self.action = cycle
        for _ in range(4):
            await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.record("repeated_write_read_cycle", pause_tick=4)

    async def test_distinct_read_ranges_continue(self):
        async def read():
            self.save(lambda task: self.row(task, "astrbot_file_read_tool", {"path": "fixture.txt", "offset": self.model_calls * 10, "limit": 10}, read_only=True))
        self.action = read
        for _ in range(8):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 0)
        self.record("legitimate_paged_read", ticks=8, false_stops=0)

    async def test_read_write_read_and_validation_are_progress(self):
        path = Path(self.temp.name) / "fixture.txt"
        path.write_text("initial", encoding="utf-8")
        async def action():
            n = self.model_calls
            def work(task):
                if n in {2, 5}:
                    path.write_text(f"revision {n}", encoding="utf-8")
                    self.row(task, "astrbot_file_write_tool", {"path": str(path), "content": f"revision {n}"})
                elif n in {4, 7}:
                    self.row(task, arguments={"command": f"validate fixture revision {n}"})
                else:
                    self.row(task, "astrbot_file_read_tool", {"path": str(path), "offset": 0}, read_only=True)
            self.save(work)
        self.action = action
        for _ in range(7):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 0)
        self.record("read_write_read_validate", ticks=7, temporary_file_bytes=path.stat().st_size, false_stops=0)

    async def test_valid_completed_checkpoints_and_stage_handoffs_continue(self):
        self.save(lambda task: Control.control(task)["steps"].extend(
            dict(id=f"step{i}", status="pending", title="分段", instruction="验证", evidence=[]) for i in range(2, 7)))
        async def checkpoint():
            def work(task):
                row = self.row(task, "astrbot_file_read_tool", {"path": "fixture.txt"}, read_only=True)
                step = next(s for s in Control.control(task)["steps"] if s["id"] == row["step_id"])
                step.update(status="completed", evidence=[row["id"]])
                Control.control(task).setdefault("continuity", {}).setdefault("lanes", {})[""] = dict(
                    record_id=f"handoff_{self.model_calls}", record_path="handoffs/saved.json", summary="已保存并分段继续")
            self.save(work)
        self.action = checkpoint
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 0)
        self.record("completed_checkpoints_with_handoffs", ticks=6, false_stops=0)

    async def test_handoff_only_has_one_grace_without_reset(self):
        await self.tick()
        async def handoff():
            self.save(lambda task: Control.control(task).setdefault("continuity", {}).setdefault("lanes", {}).update(
                {"": dict(record_id=f"handoff_{self.model_calls}", record_path="saved.json", summary="保存摘要")}))
        self.action = handoff
        await self.tick()
        self.assertEqual(self.load().workflow_data["progress_guard"]["decision"], "handoff_grace")
        await self.tick()
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 2)
        await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.record("handoff_churn_bounded", grace_ticks=1, pause_tick=4)

    async def test_new_work_renews_handoff_grace(self):
        async def alternate():
            def work(task):
                if self.model_calls % 2:
                    self.row(task, arguments={"command": f"validate unit {self.model_calls}"})
                else:
                    Control.control(task).setdefault("continuity", {}).setdefault("lanes", {})[""] = dict(
                        record_id=f"handoff_{self.model_calls}", record_path="saved.json", summary="保存摘要")
            self.save(work)
        self.action = alternate
        for _ in range(8):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.record("work_then_handoff", ticks=8, false_stops=0)

    async def test_repeated_failed_tools_pause_at_three(self):
        async def failed():
            self.save(lambda task: self.row(task, status="failed"))
        self.action = failed
        for _ in range(3):
            await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "blocked_by_error"))
        self.record("repeated_tool_failures", pause_tick=3)

    async def test_new_reads_do_not_mask_consecutive_failed_tools(self):
        async def failed_with_read():
            def work(task):
                self.row(task, "astrbot_file_read_tool", {"path": "fixture.txt", "offset": self.model_calls}, read_only=True)
                self.row(task, status="failed")
            self.save(work)
        self.action = failed_with_read
        for _ in range(3):
            await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "blocked_by_error"))
        self.assertEqual(task.workflow_data["progress_guard"]["failure_ticks"], 3)
        self.record("novel_reads_cannot_hide_failures", pause_tick=3)

    async def test_replay_after_journal_compaction_is_not_new_work(self):
        async def compact_and_repeat():
            def work(task):
                Control.control(task)["journal"] = []
                self.row(task, arguments={"command": "same validation"})
            self.save(work)
        self.action = compact_and_repeat
        await self.tick()
        # A tick with no retained journal must not erase the durable seen set.
        self.action = lambda: self._clear_journal()
        await self.tick()
        self.action = compact_and_repeat
        await self.tick()
        await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.record("compacted_journal_replay", pause_tick=4)

    async def _clear_journal(self):
        self.save(lambda task: Control.control(task).update(journal=[]))

    async def test_recovered_failures_do_not_accumulate_for_later_pause(self):
        async def sometimes():
            if self.model_calls % 2:
                raise OSError("temporary fixture failure")
            self.save(lambda task: self.row(task, arguments={"command": f"fixed unit {self.model_calls}"}))
        self.action = sometimes
        for _ in range(8):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.assertEqual(self.load().repeated_issue_counts["OSError"], 4)
        self.record("intermittent_errors_recovered", ticks=8, historical_same_errors=4, false_stops=0)

    async def test_three_runtime_exceptions_pause(self):
        async def fail():
            raise ValueError("deterministic fixture failure")
        self.action = fail
        for _ in range(3):
            await self.tick()
        self.assertEqual((self.load().status, self.load().wait.wait_reason), ("paused", "blocked_by_error"))
        self.record("runtime_errors", warning_tick=2, pause_tick=3)

    async def test_partial_progress_cannot_hide_consecutive_timeouts(self):
        async def timeout():
            self.save(lambda task: self.row(task, arguments={"command": f"partial work {self.model_calls}"}))
            raise asyncio.TimeoutError()
        self.action = timeout
        for _ in range(3):
            await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "runtime_timeout"))
        self.assertEqual(task.workflow_data["progress_guard"]["failure_ticks"], 3)
        self.record("partial_work_then_timeout", pause_tick=3)

    async def test_all_awaited_phases_share_one_deadline(self):
        observed, elapsed = [], [0.0]
        async def measured(awaitable, timeout):
            observed.append(timeout)
            result = await awaitable
            elapsed[0] += 0.3
            return result
        self.save(lambda task: setattr(task.budget, "max_seconds_per_tick", 1))
        with patch.object(Runtime, "time", S(monotonic=lambda: elapsed[0])), patch.object(Runtime.asyncio, "wait_for", measured):
            await self.tick()
        self.assertEqual(len(observed), 4)
        for actual, expected in zip(observed, [1.0, 0.7, 0.4, 0.1]):
            self.assertAlmostEqual(actual, expected)
        self.record("single_deadline", phase_timeouts_seconds=[round(value, 3) for value in observed])

    async def test_timeout_covers_batch_workflow_provider_and_model(self):
        original_wait_for = asyncio.wait_for
        observed = []
        async def short_wait(awaitable, timeout):
            observed.append(timeout)
            return await original_wait_for(awaitable, min(timeout, 0.02))
        async def hang(*a, **k):
            await asyncio.Event().wait()
        for lane in ("batch", "workflow", "provider", "model"):
            task = self.load()
            task.status = "running"; task.clear_wait()
            task.workflow_data.pop("progress_guard", None)
            self.storage.save_task(task)
            if lane == "batch": target, attribute = self.owner.astrbot_bridge, "resume_batch"
            elif lane == "workflow": target, attribute = self.owner, "_run_workflow_runtime"
            elif lane == "provider": target, attribute = self.owner.context, "get_current_chat_provider_id"
            else: target, attribute = self.owner.astrbot_bridge, "run"
            with patch.object(target, attribute, hang), patch.object(Runtime.asyncio, "wait_for", short_wait):
                for _ in range(3):
                    result = await self.tick()
            self.assertIn("超时", result)
            self.assertEqual((self.load().status, self.load().wait.wait_reason), ("paused", "runtime_timeout"))
            self.assertFalse(self.load().lease.token)
        self.assertTrue(all(0 < value <= 240 for value in observed))
        self.record("timeouts_all_awaited_phases", lanes=4, simulated_timeouts=12, pause_after_each=3,
                    test_deadline_seconds=0.02, production_deadline_seconds=240)

    async def test_round_budget_churn_cannot_run_forever(self):
        async def round_limit():
            raise Bridge.BudgetStopped("本轮预算已用尽，从检查点继续")
        self.action = round_limit
        for _ in range(3):
            await self.tick()
        self.assertEqual(self.load().wait.wait_reason, "no_progress")
        self.record("empty_round_budget_continuation", pause_tick=3)

    async def test_round_budget_with_real_progress_continues(self):
        async def round_limit():
            self.save(lambda task: self.row(task, arguments={"command": f"complete unit {self.model_calls}"}))
            raise Bridge.BudgetStopped("本轮预算已用尽，从检查点继续")
        self.action = round_limit
        for _ in range(6):
            await self.tick()
        self.assertEqual(self.load().status, "running")
        self.record("productive_round_budget_continuation", ticks=6, false_stops=0)

    async def test_total_budgets_block_without_model_dispatch(self):
        for limit, used in (("max_total_ticks", "ticks_used"), ("max_total_tool_calls", "tool_calls_used"), ("max_total_tokens", "tokens_used")):
            task = self.load(); task.status = "running"; task.clear_wait()
            task.budget = Models.TaskBudget()
            setattr(task.budget, limit, 2); setattr(task.budget, used, 2)
            self.storage.save_task(task)
            await self.tick()
            self.assertEqual(self.load().wait.wait_reason, "budget_exhausted")
        self.assertEqual(self.model_calls, 0)
        self.record("total_budgets_preflight", budget_types=3, model_dispatches=0)

    async def test_last_allowed_tick_finishes_before_tick_budget_pause(self):
        self.save(lambda task: setattr(task.budget, "max_total_ticks", 1))
        await self.tick()
        task = self.load()
        self.assertEqual(self.model_calls, 1)
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "budget_exhausted"))
        await self.tick()
        self.assertEqual(self.model_calls, 1)
        self.record("last_admitted_tick_finishes", tick_limit=1, model_dispatches=1)

    async def test_inflight_total_budget_reason_is_preserved(self):
        async def limit():
            def work(task):
                self.owner._pause_task_for_budget(task, "任务 Token 总预算已用尽：2/2")
            self.save(work)
            raise Bridge.BudgetStopped("total budget")
        self.action = limit
        await self.tick()
        self.assertEqual(self.load().wait.wait_reason, "budget_exhausted")
        self.assertNotIn("progress_guard", self.load().workflow_data)
        self.record("inflight_budget_preserved")

    async def test_total_budget_reached_by_success_stops_immediately(self):
        async def consume():
            def work(task):
                task.budget.max_total_tokens = task.budget.tokens_used = 2
            self.save(work)
        self.action = consume
        await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "budget_exhausted"))
        self.assertNotIn("progress_guard", task.workflow_data)
        self.assertFalse(task.heartbeat.enabled)
        self.record("successful_response_hits_total_budget", pause_tick=1)

    def pending_approval(self, task):
        task.approvals.append(Models.ApprovalRequest(operation="fixture approval").__dict__)
        task.set_wait(wait_reason="need_approval", message="fixture approval")

    async def test_pending_approval_freezes_existing_liveness_counters(self):
        await self.tick()
        baseline = self.load().workflow_data["progress_guard"].copy()
        self.save(self.pending_approval)
        for _ in range(4):
            await self.tick()
        self.assertEqual(self.model_calls, 1)
        self.assertEqual(self.load().workflow_data["progress_guard"], baseline)
        self.assertEqual(self.load().wait.wait_reason, "need_approval")
        self.record("approval_wait_does_not_stall", skipped_ticks=4)

    async def test_inflight_approval_is_preserved_on_success_and_handoff_error(self):
        for raises in (False, True):
            self.save(lambda task: (task.approvals.clear(), task.clear_wait()))
            async def approval():
                self.save(self.pending_approval)
                if raises:
                    raise Runtime.HandoffError("late handoff failure")
            self.action = approval
            await self.tick()
            self.assertEqual(self.load().status, "running")
            self.assertEqual(self.load().wait.wait_reason, "need_approval")
            self.assertNotIn("progress_guard", self.load().workflow_data)
        self.record("approval_inflight_preserved", variants=2)

    async def test_provider_wait_rechecks_pause_before_model_dispatch(self):
        async def provider(umo):
            def work(task):
                task.status = "paused"
                Control.control(task)["human_paused"] = True
                task.set_wait(wait_reason="administrator_pause", message="fixture admin stop")
            self.save(work)
            return "deterministic-only"
        self.owner.context.get_current_chat_provider_id = provider
        await self.tick()
        self.assertEqual(self.model_calls, 0)
        self.assertEqual(self.load().wait.wait_reason, "administrator_pause")
        self.assertNotIn("progress_guard", self.load().workflow_data)
        self.record("provider_wait_admin_pause", model_dispatches=0)

    async def test_changed_approved_plan_during_model_rejects_old_result(self):
        async def replan():
            def work(task):
                Control.control(task).update(version=2, approved_version=2, authorization_version=2)
                task.current_summary = "new approved plan"
            self.save(work)
        self.action = replan
        await self.tick()
        self.assertEqual(self.load().current_summary, "new approved plan")
        self.assertNotIn("progress_guard", self.load().workflow_data)
        self.record("new_approved_plan_rejects_old_result")

    async def test_empty_batch_deferral_is_bounded(self):
        async def deferred(*args):
            return False
        self.owner.astrbot_bridge.resume_batch = deferred
        for _ in range(3):
            await self.tick()
        self.assertEqual((self.load().status, self.load().wait.wait_reason), ("paused", "no_progress"))
        self.assertEqual(self.model_calls, 0)
        self.record("empty_batch_deferral", pause_tick=3)

    async def test_admin_pause_during_model_is_not_resurrected(self):
        async def pause():
            def stop(task):
                task.status = "paused"
                Control.control(task)["human_paused"] = True
                task.set_wait(wait_reason="administrator_pause", message="fixture admin stop")
            self.save(stop)
        self.action = pause
        result = await self.tick()
        self.assertIn("停止接收旧执行结果", result)
        self.assertEqual(self.load().wait.wait_reason, "administrator_pause")
        self.assertNotIn("progress_guard", self.load().workflow_data)
        await self.tick()
        self.assertEqual(self.model_calls, 1)
        self.record("admin_pause_inflight", no_resurrection=True)

    async def test_admin_end_during_model_success_and_error(self):
        for raises in (False, True):
            if not self.load():
                # A new temporary task gets a fresh ID; terminal fence stays.
                task = Models.TaskState(umo=self.umo, root_goal="second fixture")
                Control.control(task).update(version=1, approved_version=1, workflow="none", steps=[], journal=[])
                self.storage.save_task(task)
                self.task_id = task.task_id
            async def end():
                task = self.load()
                self.storage.mark_ended(task, "cancelled", "fixture-admin")
                task.status = "cancelled"
                self.storage.archive_task(task, administrator=True)
                if raises:
                    raise OSError("late callback")
            self.action = end
            await self.tick()
            self.assertIsNone(self.load())
            self.assertTrue(self.storage.ended_path(self.task_id).exists())
        self.record("admin_terminal_success_or_exception", variants=2, no_resurrection=True)

    async def test_admin_stop_while_waiting_for_slot_is_rechecked(self):
        gate = asyncio.Semaphore(0)
        self.owner._global_tick_semaphore = gate
        running = asyncio.create_task(self.tick())
        await asyncio.sleep(0)
        self.save(lambda task: (setattr(task, "status", "paused"), Control.control(task).update(human_paused=True)))
        gate.release()
        await running
        self.assertEqual(self.model_calls, 0)
        self.assertEqual(self.load().status, "paused")
        self.assertFalse(self.load().lease.token)
        self.assertEqual(self.load().budget.ticks_used, 0)
        self.assertNotIn("progress_guard", self.load().workflow_data)
        self.record("admin_pause_queued", model_dispatches=0, ticks_charged=0)

    async def test_duplicate_tick_is_skipped_and_lease_released(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def wait():
            entered.set(); await release.wait()
        self.action = wait
        running = asyncio.create_task(self.tick())
        await entered.wait()
        self.assertIn("重入", await self.tick())
        release.set(); await running
        self.assertEqual(self.model_calls, 1)
        self.assertFalse(self.load().lease.token)
        self.record("duplicate_trigger", model_dispatches=1)

    async def test_cancellation_cleans_lease_and_reentry(self):
        entered = asyncio.Event()
        async def wait():
            entered.set(); await asyncio.Event().wait()
        self.action = wait
        running = asyncio.create_task(self.tick())
        await entered.wait(); running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertFalse(self.load().lease.token)
        self.record("external_cancellation_cleanup")

    async def test_heartbeat_cleanup_failure_still_releases_lease_and_reentry(self):
        async def fail(task):
            raise OSError("fixture scheduler offline")
        self.owner._disable_heartbeat = fail
        for _ in range(3):
            await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.assertFalse(self.load().lease.token)
        self.assertFalse(self.owner._running_ticks)
        self.assertTrue(self.load().heartbeat.enabled)  # Host cleanup remains unconfirmed.
        await self.tick()
        self.assertEqual(self.model_calls, 3)
        self.record("scheduler_cleanup_failure", extra_model_dispatches=0, heartbeat_cleanup_confirmed=False)

    async def test_local_warning_storage_error_does_not_disable_guard(self):
        with patch.object(self.owner.task_messages, "record_local", side_effect=OSError("fixture disk offline")):
            for _ in range(3):
                await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.assertFalse(self.load().lease.token)
        self.assertFalse(self.load().heartbeat.enabled)
        self.record("local_warning_storage_error", pause_tick=3, local_warning_write_confirmed=False)

    async def test_hung_heartbeat_cleanup_is_bounded_and_releases_lease(self):
        original_wait_for = asyncio.wait_for
        cleanup_limits = []
        async def short_cleanup(awaitable, timeout):
            if timeout == 2:
                cleanup_limits.append(timeout)
                timeout = 0.02
            return await original_wait_for(awaitable, timeout)
        async def hang(task):
            await asyncio.Event().wait()
        self.owner._disable_heartbeat = hang
        with patch.object(Runtime.asyncio, "wait_for", short_cleanup):
            for _ in range(3):
                await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.assertFalse(self.load().lease.token)
        self.assertFalse(self.owner._running_ticks)
        self.assertEqual(cleanup_limits, [2])
        self.record("scheduler_cleanup_timeout", production_timeout_seconds=2, test_timeout_seconds=0.02)

    async def test_cancelled_gate_wait_releases_reentry_without_stall(self):
        gate = asyncio.Semaphore(0)
        self.owner._global_tick_semaphore = gate
        running = asyncio.create_task(self.tick())
        await asyncio.sleep(0)
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual(self.model_calls, 0)
        self.assertFalse(self.owner._running_ticks)
        self.assertFalse(self.load().lease.token)
        self.assertNotIn("progress_guard", self.load().workflow_data)
        self.assertTrue(gate.locked())
        self.record("cancelled_gate_wait", model_dispatches=0)

    async def test_counters_survive_storage_and_runner_recreation(self):
        await self.tick(); await self.tick(); await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.assertEqual(self.load().workflow_data["progress_guard"]["no_progress_ticks"], 3)
        self.record("counter_persistence", runner_instances=3, pause_tick=3)

    async def test_workflow_node_churn_is_not_progress(self):
        async def cycle():
            self.save(lambda task: task.add_workflow_event("a" if self.model_calls % 2 else "b"))
        self.action = cycle
        for _ in range(5):
            await self.tick()
        self.assertEqual(self.load().status, "paused")
        self.record("workflow_cycle", distinct_nodes=2, pause_tick=5)

    async def test_stale_or_cross_step_evidence_cannot_complete_progress(self):
        task = self.load()
        old = self.row(task)
        old["authorization_version"] = 0
        Control.control(task)["steps"][0].update(status="completed", evidence=[old["id"]])
        self.assertFalse(Guard.snapshot(task).evidence)
        self.assertFalse(Guard.snapshot(task).completed)
        old["authorization_version"] = 1; old["step_id"] = "other"
        self.assertFalse(Guard.snapshot(task).completed)
        self.assertFalse(Guard.snapshot(task).evidence)
        self.record("invalid_completion_evidence", variants=2)


if __name__ == "__main__":
    started = time.monotonic()
    fingerprints = source_fingerprints()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(LivenessTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    output = ROOT / "docs" / "validation" / "v0.3.4-liveness.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(
        schema_version=1, generated_at=datetime.now(timezone.utc).isoformat(), target_release="v0.3.4",
        command="python -B scripts/ui/test_agent_liveness.py", python=platform.python_version(), platform=platform.system(),
        environment="temporary tasks/files; deterministic fake model/tools; transport raises on send; no live SDK/model/network",
        tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        successful=result.wasSuccessful(), skipped=len(result.skipped),
        elapsed_seconds=round(time.monotonic() - started, 3),
        source_sha256_at_start=fingerprints, source_sha256_at_end=source_fingerprints(),
        thresholds=dict(warn_after=Guard.WARN_AFTER, pause_after=Guard.PAUSE_AFTER, handoff_grace=1),
        measurements=dict(scenarios_recorded=len(RESULTS), model_calls_simulated=sum(row["model_calls_simulated"] for row in RESULTS),
                          live_model_calls=0, transport_calls=sum(row["transport_calls"] for row in RESULTS),
                          live_tokens_billed=0, token_counts="fixture increments only; no real usage measurement"),
        limitations=["Novel tool inputs, valid completed checkpoints and first completed nodes are progress proxies; no proof of actual effects or goal completion.",
                     "Novel irrelevant parameters can look productive; total task budgets remain necessary. Durable seen sets grow with distinct evidence.",
                     "No live AstrBot/provider/cron transport integration tested by this liveness suite.",
                     "Timeout uses cooperative asyncio cancellation; blocking native calls or cancellation-suppressing tools need host isolation.",
                     "Counters are per bounded tick, not per tool; one tick remains limited by existing tool/time/token budgets. Global slot waiting is outside that deadline and unbilled.",
                     "A same-input read after external changes is conservative unless a new journalled write/checkpoint supplies evidence.",
                     "Scheduler deletion failure retains its unconfirmed heartbeat fields; paused-state preflight still blocks model dispatch."],
        test_failures=[dict(test=test.id(), detail=detail) for test, detail in [*result.failures, *result.errors]],
        scenarios=RESULTS), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.exit(not result.wasSuccessful())
