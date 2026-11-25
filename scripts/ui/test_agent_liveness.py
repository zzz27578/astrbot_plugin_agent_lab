"""v0.4 runtime control regressions with real storage, budgets and leases.

Run: python -B scripts/ui/test_agent_liveness.py
Only temporary files are written. Host/model/transport boundaries are adapters;
loop detection and production timeout behavior belong to test_v04_guards.py.
Every test-owned asynchronous wait is bounded so a failed assertion cannot hang
this suite. Those bounds are test safeguards, not task round deadlines.
"""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
from pathlib import Path
import sys
import tempfile
import types
from types import SimpleNamespace as S
from typing import Any
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "liveness_agent_lab"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "agent_lab")]
sys.modules[PACKAGE] = package


def module(name):
    return importlib.import_module(PACKAGE + "." + name)


Models, Control, Metrics = [module(name) for name in ("models", "task_control", "usage_metrics")]
Storage = module("storage").AgentLabStorage
Bridge = module("astrbot_bridge")
with patch.dict(sys.modules, {PACKAGE + ".hooks": S(AgentLabRunHooks=lambda *args, **kwargs: None)}):
    Runtime = module("runtime_runner")

# Exercise the actual adapter methods without importing the AstrBot SDK/plugin
# initializer. In particular, never bind main.py's legacy after_tick watchdog:
# AgentRuntimeRunner owns the v0.4 result-based fallback.
METHODS = {"_watchdog_before_tick", "_budget_before_tick", "_configure_task_budget",
           "_total_budget_reason", "_budget_remaining_tools", "_budget_tick_payload",
           "_consume_token_budget", "_pause_task_for_budget",
           "_prepare_resume_anchor", "_acquire_task_lease", "_release_task_lease",
           "_lease_expired", "_task_lease_owner", "_parse_iso_datetime", "_seconds_since"}
tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8-sig"))
plugin_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AgentLabPlugin")
methods = [node for node in plugin_class.body
           if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in METHODS]
if {node.name for node in methods} != METHODS:
    raise RuntimeError("Actual adapter methods changed; update this fixture explicitly")
namespace = dict(Any=Any, TaskState=Models.TaskState, now_iso=Models.now_iso, new_id=Models.new_id,
                 datetime=datetime, timedelta=timedelta, timezone=timezone,
                 task_control=Control.control, budget_tokens=Metrics.budget_tokens,
                 native_steps=lambda *args: 128, _cfg=lambda config, key, default=None: config.get(key, default))
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ClassDef(
    name="Adapter", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])),
    "<actual-adapter>", "exec"), namespace)
Adapter = namespace["Adapter"]
TEST_WAIT_SECONDS = 5


class ObservableSemaphore(asyncio.BoundedSemaphore):
    """Expose entry into a real semaphore wait without scheduler sleeps."""
    def __init__(self):
        super().__init__(1)
        self.waiting = asyncio.Event()
        self.releases = 0

    async def acquire(self):
        if self.locked():
            self.waiting.set()
        return await super().acquire()

    def release(self):
        self.releases += 1
        return super().release()


class LivenessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-lab-controls-")
        self.addCleanup(self.temp.cleanup)
        self.storage = Storage(Path(self.temp.name) / "data")
        self.owner = owner = Adapter()
        owner.storage, owner.config, owner._running_ticks = self.storage, {}, set()
        owner._require_task_access = lambda event: None
        owner._redact_known_secrets = lambda text: text
        owner.projects = S(cleaning=set())
        owner.task_control = S()
        owner._ensure_workflow_data = lambda task: task.workflow_data
        owner.agent_runtime = module("agent_runtime").AgentRuntime()
        owner._normalize_agent_workflow = lambda *args: None
        owner._sync_agent_runtime = lambda *args, **kwargs: None
        owner._build_toolset = lambda *args: S(tools=[])
        owner._compact_text = lambda text, limit: text[:limit]
        self.calls, self.traces, self.sent, self.disabled, self.operations = [], [], [], [], []
        self.action = None
        self.batch_calls = self.workflow_calls = self.provider_calls = 0
        owner._record_react_trace = lambda *args, **kwargs: self.traces.append(kwargs)
        owner._record_explicit_observation = lambda *args, **kwargs: None
        owner._build_task_extensions_prompt = lambda *args, **kwargs: self.fail("Plain tasks must not load canvas prompts")

        async def send(*args):
            self.sent.append(args)
            raise AssertionError("This suite must never send a message")

        async def disable(task):
            self.disabled.append(task.task_id)
            task.heartbeat.enabled, task.heartbeat.job_id = False, ""

        async def provider(umo):
            self.provider_calls += 1
            return "offline-control-adapter"

        async def batch(*args):
            self.batch_calls += 1
            return True

        async def workflow(**kwargs):
            self.workflow_calls += 1
            return S(changed=False, needs_react=True, blocked=False, react_node_id="", summary=lambda: "")

        async def run(event, task, tools, prompt, system, max_steps, hooks):
            self.calls.append(dict(task_id=task.task_id, umo=task.umo, prompt=prompt, max_steps=max_steps))
            if self.action:
                await self.action(task)
            return S(completion_text="OLD_MODEL_RESULT")

        owner.context = S(get_current_chat_provider_id=provider)
        owner._disable_heartbeat = disable
        owner._run_workflow_runtime = workflow
        owner.astrbot_bridge = S(resume_batch=batch, run=run)
        owner.task_messages = module("task_messages").TaskMessages(owner, send=send)
        self.task = self.new_task("fixture:FriendMessage:123")
        self.umo = self.task.umo
        self.event = self.event_for(self.umo)

    async def asyncTearDown(self):
        # Cancel fixture work even when a synchronization assertion fails.
        for operation in self.operations:
            if not operation.done():
                operation.cancel()
        if self.operations:
            await asyncio.wait_for(asyncio.gather(*self.operations, return_exceptions=True), TEST_WAIT_SECONDS)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.owner._running_ticks)

    def new_task(self, umo):
        task = Models.TaskState(umo=umo, root_goal="临时任务控制回归", status="running")
        Control.control(task).update(owner_id="123", version=1, approved_version=1, authorization_version=1,
            input_revision=0, workflow="none", current_step_id="one", automatic=True, human_paused=False,
            steps=[dict(id="one", status="pending", title="验证", instruction="验证临时成果", evidence=[])],
            journal=[], execution_settings={})
        task.heartbeat.enabled, task.heartbeat.job_id = True, "fixture-job"
        self.storage.save_task(task)
        return task

    @staticmethod
    def event_for(umo):
        extras = {}
        return S(unified_msg_origin=umo, get_sender_id=lambda: "123",
                 set_extra=lambda key, value: extras.update({key: value}),
                 get_extra=lambda key, default=None: extras.get(key, default))

    def load(self, umo=None):
        return self.storage.load_active_task(umo or self.umo)

    def save(self, mutate, umo=None):
        task = self.load(umo)
        mutate(task)
        self.storage.save_task(task)
        return task

    async def wait(self, awaitable):
        return await asyncio.wait_for(awaitable, TEST_WAIT_SECONDS)

    async def tick(self, event=None):
        return await self.wait(Runtime.AgentRuntimeRunner(self.owner).run_tick(event or self.event, "control_regression"))

    def start_tick(self, event=None):
        operation = asyncio.create_task(self.tick(event))
        self.operations.append(operation)
        return operation

    async def gate(self, *, occupied=True):
        gate = ObservableSemaphore()
        if occupied:
            await gate.acquire()
        self.owner._global_tick_semaphore = gate
        return gate

    def assert_released(self, umo=None):
        task = self.load(umo)
        if task:
            self.assertEqual(task.lease.token, "")
            self.assertEqual(task.lease.owner, "")
        self.assertFalse(self.owner._running_ticks)

    @staticmethod
    def pause(task):
        task.status = "paused"
        task.current_summary = "ADMINISTRATOR_STATE"
        Control.control(task)["human_paused"] = True
        task.set_wait(wait_reason="administrator_pause", message="管理员明确暂停", source="administrator")

    @staticmethod
    def pending_approval(task):
        task.approvals.append(Models.ApprovalRequest(operation="fixture approval").to_dict())
        task.set_wait(wait_reason="need_approval", message="fixture approval")

    def end_task(self):
        task = self.load()
        self.storage.mark_ended(task, "cancelled", "fixture-admin")
        task.status = "cancelled"
        self.storage.archive_task(task, administrator=True)
        return task

    def assert_budget_pause(self, *, calls):
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "budget_exhausted"))
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(task.heartbeat.enabled)
        self.assertEqual(task.heartbeat.job_id, "")
        self.assert_released()

    async def test_preflight_respects_administrator_pause_and_unapproved_plan(self):
        for cause in ("human_paused", "paused_status", "unapproved_plan"):
            with self.subTest(cause=cause):
                self.new_task(self.umo)
                def mutate(task):
                    if cause == "human_paused":
                        Control.control(task)["human_paused"] = True
                    elif cause == "paused_status":
                        task.status = "paused"
                    else:
                        Control.control(task)["approved_version"] = 0
                self.save(mutate)
                await self.tick()
                self.assertEqual(self.load().budget.ticks_used, 0)
                self.assertEqual(self.calls, [])
                self.assertEqual(self.batch_calls, 0)
                self.assert_released()

    async def test_pending_approval_prevents_dispatch_and_preserves_guard_state(self):
        task = self.save(self.pending_approval)
        baseline = {"version": 2, "pending_notice": "existing notice", "decision": "warning"}
        task.workflow_data["progress_guard"] = deepcopy(baseline)
        self.storage.save_task(task)
        for _ in range(3):
            await self.tick()
        task = self.load()
        self.assertEqual(task.wait.wait_reason, "need_approval")
        self.assertEqual(task.workflow_data["progress_guard"], baseline)
        self.assertEqual(task.budget.ticks_used, 0)
        self.assertFalse(self.calls)
        self.assert_released()

    async def test_pause_during_provider_lookup_prevents_dispatch(self):
        async def provider(umo):
            self.save(self.pause)
            return "offline-provider"
        self.owner.context.get_current_chat_provider_id = provider
        result = await self.tick()
        self.assertIn("停止模型派发", result)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.load().current_summary, "ADMINISTRATOR_STATE")
        self.assertEqual(self.load().wait.wait_reason, "administrator_pause")
        self.assertFalse(self.load().heartbeat.enabled)
        self.assert_released()

    async def test_pause_during_batch_prevents_workflow_and_model(self):
        async def batch(*args):
            self.save(self.pause)
            return True
        self.owner.astrbot_bridge.resume_batch = batch
        await self.tick()
        self.assertEqual((self.workflow_calls, self.provider_calls, len(self.calls)), (0, 0, 0))
        self.assertEqual(self.load().wait.wait_reason, "administrator_pause")
        self.assert_released()

    async def test_pause_during_model_preserves_admin_state_on_success_or_error(self):
        for error in (None, OSError, Runtime.HandoffError, Bridge.ExecutionStopped):
            with self.subTest(error=error):
                self.new_task(self.umo)
                before = len(self.calls)
                async def pause(task):
                    self.save(self.pause)
                    if error:
                        raise error("late callback")
                self.action = pause
                await self.tick()
                task = self.load()
                self.assertEqual((task.status, task.wait.wait_reason), ("paused", "administrator_pause"))
                self.assertTrue(Control.control(task)["human_paused"])
                self.assertEqual(task.current_summary, "ADMINISTRATOR_STATE")
                self.assertFalse(self.traces, "An old response must not be accepted after admin pause")
                self.assertNotIn("progress_guard", task.workflow_data)
                self.assertFalse(task.heartbeat.enabled)
                await self.tick()
                self.assertEqual(len(self.calls), before + 1)
                self.assert_released()

    async def test_administrator_stop_during_model_fences_success_and_error_callbacks(self):
        for error in (None, OSError, Runtime.HandoffError):
            with self.subTest(error=error):
                task = self.new_task(self.umo)
                stale = deepcopy(task)
                async def stop(current):
                    self.end_task()
                    if error:
                        raise error("late callback")
                self.action = stop
                await self.tick()
                self.assertIsNone(self.load())
                self.assertTrue(self.storage.ended_path(task.task_id).exists())
                archive = self.storage._read_json(self.storage.archive_task_json_path(self.umo, task.task_id))
                self.assertEqual(archive["status"], "cancelled")
                stale.status, stale.current_summary = "running", "late write"
                self.storage.save_task(stale)
                self.assertIsNone(self.load())
                self.assertEqual(self.storage._read_json(self.storage.archive_task_json_path(self.umo, task.task_id)), archive)
                self.assertFalse(self.owner._running_ticks)
        self.assertEqual(self.traces, [])

    async def test_plan_or_input_revision_during_model_rejects_old_result_and_error(self):
        for field in ("plan", "input_revision"):
            for raises in (False, True):
                with self.subTest(field=field, raises=raises):
                    self.new_task(self.umo)
                    async def revise(task):
                        def mutate(current):
                            state = Control.control(current)
                            if field == "plan":
                                state.update(version=2, approved_version=2, authorization_version=2)
                            else:
                                state["input_revision"] = 1
                            current.current_summary = "NEW_APPROVED_STATE"
                        self.save(mutate)
                        if raises:
                            raise OSError("obsolete provider exception")
                    self.action = revise
                    await self.tick()
                    task = self.load()
                    self.assertEqual(task.status, "running")
                    self.assertEqual(task.current_summary, "NEW_APPROVED_STATE")
                    self.assertEqual(Control.control(task).get("input_revision"), int(field == "input_revision"))
                    self.assertEqual(Control.control(task)["version"], 2 if field == "plan" else 1)
                    self.assertEqual(self.traces, [])
                    self.assertNotIn("progress_guard", task.workflow_data)
                    self.assert_released()

    async def test_input_revision_during_provider_lookup_prevents_stale_dispatch(self):
        async def provider(umo):
            self.save(lambda task: Control.control(task).update(input_revision=1))
            return "offline-provider"
        self.owner.context.get_current_chat_provider_id = provider
        await self.tick()
        self.assertFalse(self.calls)
        self.assertEqual(Control.control(self.load())["input_revision"], 1)
        self.assert_released()

    async def test_inflight_approval_is_preserved_after_success_and_handoff_error(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                self.new_task(self.umo)
                async def approval(task):
                    self.save(self.pending_approval)
                    if raises:
                        raise Runtime.HandoffError("late handoff error")
                self.action = approval
                await self.tick()
                task = self.load()
                self.assertEqual((task.status, task.wait.wait_reason), ("running", "need_approval"))
                self.assertEqual(len(task.pending_approvals()), 1)
                self.assertNotIn("progress_guard", task.workflow_data)
                self.assertFalse(self.traces)
                before = len(self.calls)
                await self.tick()
                self.assertEqual(len(self.calls), before)
                self.assert_released()

    async def test_queued_pause_does_not_dispatch_or_charge_or_claim_lease(self):
        gate = await self.gate()
        operation = self.start_tick()
        await self.wait(gate.waiting.wait())
        self.assertEqual(self.load().budget.ticks_used, 0)
        self.assertEqual(self.load().lease.token, "")
        self.save(self.pause)
        gate.release()
        await self.wait(operation)
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "administrator_pause"))
        self.assertEqual(task.budget.ticks_used, 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(gate.locked())
        self.assertEqual(gate.releases, 2)
        self.assert_released()

    async def test_queued_stop_or_task_replacement_never_revives_old_task(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                task = self.new_task(self.umo)
                gate = await self.gate()
                operation = self.start_tick()
                await self.wait(gate.waiting.wait())
                self.end_task()
                replacement = self.new_task(self.umo) if replace else None
                gate.release()
                await self.wait(operation)
                self.assertTrue(self.storage.ended_path(task.task_id).exists())
                if replacement:
                    latest = self.load()
                    self.assertEqual(latest.task_id, replacement.task_id)
                    self.assertEqual(latest.budget.ticks_used, 0)
                    self.assertEqual(latest.lease.token, "")
                else:
                    self.assertIsNone(self.load())
                self.assertFalse(self.calls)
                self.assertFalse(gate.locked())
                self.assertFalse(self.owner._running_ticks)

    async def test_queued_approved_revision_is_reloaded_before_execution(self):
        gate = await self.gate()
        operation = self.start_tick()
        await self.wait(gate.waiting.wait())
        def revise(task):
            state = Control.control(task)
            state.update(version=2, approved_version=2, authorization_version=2, input_revision=3)
            state["steps"][0].update(title="LATEST_APPROVED_STEP", instruction="LATEST_APPROVED_INSTRUCTION")
        self.save(revise)
        gate.release()
        await self.wait(operation)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("LATEST_APPROVED_INSTRUCTION", self.calls[0]["prompt"])
        self.assertEqual(Control.control(self.load())["version"], 2)
        self.assertEqual(Control.control(self.load())["input_revision"], 3)
        self.assert_released()

    async def test_cancelled_global_wait_is_uncharged_and_does_not_release_other_slot(self):
        gate = await self.gate()
        operation = self.start_tick()
        await self.wait(gate.waiting.wait())
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.wait(operation)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.load().budget.ticks_used, 0)
        self.assertEqual(gate.releases, 0)
        self.assertTrue(gate.locked())
        self.assert_released()
        gate.release()
        await self.tick()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(gate.locked())
        self.assert_released()

    async def test_global_slot_serializes_different_tasks_and_leaves_waiter_uncharged(self):
        other = self.new_task("fixture:FriendMessage:456")
        gate = await self.gate(occupied=False)
        entered, other_entered, release, other_release = [asyncio.Event() for _ in range(4)]
        active = peak = 0
        async def work(task):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                if task.umo == self.umo:
                    entered.set()
                    await release.wait()
                else:
                    other_entered.set()
                    await other_release.wait()
            finally:
                active -= 1
        self.action = work
        first = self.start_tick()
        await self.wait(entered.wait())
        second = self.start_tick(self.event_for(other.umo))
        await self.wait(gate.waiting.wait())
        self.assertEqual(self.load(other.umo).budget.ticks_used, 0)
        self.assertEqual(self.load(other.umo).lease.token, "")
        self.assertFalse(other_entered.is_set())
        release.set()
        await self.wait(first)
        await self.wait(other_entered.wait())
        other_release.set()
        await self.wait(second)
        self.assertEqual((active, peak, len(self.calls)), (0, 1, 2))
        self.assertEqual([self.load(umo).budget.ticks_used for umo in (self.umo, other.umo)], [1, 1])
        self.assertEqual(gate.releases, 2)
        self.assertFalse(gate.locked())
        self.assert_released()
        self.assert_released(other.umo)

    async def test_duplicate_tick_does_not_dispatch_and_reentry_works_after_completion(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def work(task):
            entered.set()
            await release.wait()
        self.action = work
        operation = self.start_tick()
        await self.wait(entered.wait())
        self.assertTrue(self.load().lease.token)
        self.assertIn("重入", await self.tick())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.load().budget.ticks_used, 1)
        release.set()
        await self.wait(operation)
        self.assert_released()
        self.action = None
        await self.tick()
        self.assertEqual(len(self.calls), 2)
        self.assert_released()

    async def test_foreign_lease_is_preserved_and_expired_lease_allows_execution(self):
        def foreign(task):
            task.lease.owner, task.lease.token = "other-worker", "foreign-token"
            task.lease.expires_at = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        self.save(foreign)
        gate = await self.gate(occupied=False)
        self.assertIn("other-worker", await self.tick())
        self.assertEqual(self.load().lease.token, "foreign-token")
        self.assertEqual(self.load().budget.ticks_used, 0)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.owner._running_ticks)
        self.assertFalse(gate.locked())
        self.save(lambda task: setattr(task.lease, "expires_at", (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()))
        await self.tick()
        self.assertEqual(len(self.calls), 1)
        self.assert_released()

    async def test_lease_cleanup_cannot_clear_a_newer_owner_token(self):
        async def changed_lease(task):
            def mutate(latest):
                latest.lease.owner, latest.lease.token = "replacement-worker", "replacement-token"
            self.save(mutate)
        self.action = changed_lease
        await self.tick()
        self.assertEqual(self.load().lease.token, "replacement-token")
        self.assertEqual(self.load().lease.owner, "replacement-worker")
        self.assertFalse(self.owner._running_ticks)

    async def test_model_cancellation_releases_global_slot_lease_and_reentry(self):
        gate = await self.gate(occupied=False)
        entered, release = asyncio.Event(), asyncio.Event()
        async def work(task):
            entered.set()
            await release.wait()
        self.action = work
        operation = self.start_tick()
        await self.wait(entered.wait())
        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await self.wait(operation)
        self.assertFalse(gate.locked())
        self.assert_released()
        self.action = None
        await self.tick()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.load().budget.ticks_used, 2)
        self.assert_released()

    async def test_scheduler_cleanup_failure_preserves_pause_and_releases_resources(self):
        async def fail(task):
            raise OSError("fixture scheduler unavailable")
        async def pause(task):
            self.save(self.pause)
        self.owner._disable_heartbeat = fail
        self.action = pause
        gate = await self.gate(occupied=False)
        await self.tick()
        task = self.load()
        self.assertEqual((task.status, task.wait.wait_reason), ("paused", "administrator_pause"))
        self.assertTrue(task.heartbeat.enabled, "Cleanup failure must not claim scheduler deletion succeeded")
        self.assertTrue(any(row["kind"] == "heartbeat_cleanup_failed" for row in task.progress_log))
        self.assertFalse(gate.locked())
        self.assert_released()
        await self.tick()
        self.assertEqual(len(self.calls), 1)

    async def test_total_budgets_block_dispatch_without_charging_a_new_tick(self):
        for kind in ("ticks", "tools", "tokens", "seconds", "estimated_tokens"):
            with self.subTest(kind=kind):
                self.new_task(self.umo)
                def exhaust(task):
                    if kind == "ticks":
                        task.budget.max_total_ticks = task.budget.ticks_used = 2
                    elif kind == "tools":
                        task.budget.max_total_tool_calls = task.budget.tool_calls_used = 2
                    elif kind == "tokens":
                        task.budget.max_total_tokens = task.budget.tokens_used = 2
                    elif kind == "seconds":
                        task.budget.max_total_seconds = 10
                        task.created_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
                    else:
                        payload = {"prompt": "actual fixture request " * 10}
                        sizes = Metrics.request_size(payload, payload)
                        Metrics.record_request(task, sizes, usage=None)
                        task.budget.max_total_tokens = Metrics.budget_tokens(task)
                task = self.save(exhaust)
                self.assertTrue(self.owner._total_budget_reason(task), "Extracted adapter budget helpers must work too")
                before = task.budget.ticks_used
                await self.tick()
                self.assert_budget_pause(calls=0)
                self.assertEqual(self.load().budget.ticks_used, before)

    async def test_last_admitted_tick_finishes_before_total_tick_budget_pause(self):
        self.save(lambda task: setattr(task.budget, "max_total_ticks", 1))
        await self.tick()
        self.assert_budget_pause(calls=1)
        self.assertEqual(self.load().budget.ticks_used, 1)
        self.assertEqual(len(self.traces), 1)
        self.assertTrue(any(row["kind"] == "tick" for row in self.load().progress_log))
        await self.tick()
        self.assertEqual(len(self.calls), 1)

    async def test_tokens_consumed_by_success_pause_immediately_at_total_limit(self):
        self.save(lambda task: setattr(task.budget, "max_total_tokens", 20))
        async def consume(task):
            def update(latest):
                self.assertEqual(self.owner._consume_token_budget(latest, S(total=20)), "")
            self.save(update)
        self.action = consume
        await self.tick()
        self.assertEqual(self.load().budget.tokens_used, 20)
        self.assert_budget_pause(calls=1)
        self.assertNotIn("progress_guard", self.load().workflow_data)
        await self.tick()
        self.assertEqual(len(self.calls), 1)

    async def test_inflight_total_budget_pause_keeps_its_reason(self):
        async def consume(task):
            self.save(lambda latest: self.owner._pause_task_for_budget(latest, "任务 Token 总预算已用尽：2/2"))
            raise Bridge.BudgetStopped("provider budget stop")
        self.action = consume
        await self.tick()
        self.assert_budget_pause(calls=1)
        self.assertEqual(self.load().wait.message, "任务 Token 总预算已用尽：2/2")
        self.assertNotIn("progress_guard", self.load().workflow_data)

    async def test_budget_exhausted_during_provider_lookup_prevents_model(self):
        async def provider(umo):
            self.save(lambda task: (setattr(task.budget, "max_total_tokens", 3), setattr(task.budget, "tokens_used", 3)))
            return "offline-provider"
        self.owner.context.get_current_chat_provider_id = provider
        await self.tick()
        self.assert_budget_pause(calls=0)
        self.assertEqual(self.load().budget.ticks_used, 1)

    async def test_total_budget_exhausted_in_global_queue_is_rechecked_before_dispatch(self):
        for kind in ("tokens", "seconds"):
            with self.subTest(kind=kind):
                self.new_task(self.umo)
                gate = await self.gate()
                operation = self.start_tick()
                await self.wait(gate.waiting.wait())
                def exhaust(task):
                    if kind == "tokens":
                        task.budget.max_total_tokens = task.budget.tokens_used = 2
                    else:
                        task.budget.max_total_seconds = 10
                        task.created_at = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
                self.save(exhaust)
                gate.release()
                await self.wait(operation)
                self.assert_budget_pause(calls=0)
                self.assertEqual(self.load().budget.ticks_used, 0)
                self.assertFalse(gate.locked())


if __name__ == "__main__":
    unittest.main(verbosity=2)
