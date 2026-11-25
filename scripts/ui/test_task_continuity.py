"""Real task/storage transitions with deterministic model and runner adapters."""
import importlib
import json
import sys
import types
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

import test_project_runtime as F
ROOT = F.ROOT

C = importlib.import_module('review_agent_lab.continuity')
Control = importlib.import_module('review_agent_lab.task_control')
Settings = importlib.import_module('review_agent_lab.execution_settings')


class ContinuityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = F.ProjectRuntime()
        self.fixture.setUp()
        for name in ('owner', 'storage', 'projects', 'db', 'task', 'event'):
            setattr(self, name, getattr(self.fixture, name))
        self.summaries = []
        async def provider_id(umo):
            return 'configured-bot-model'
        async def forbidden(**kwargs):
            raise AssertionError('routine plan changes must not call a review model')
        self.owner.context.get_current_chat_provider_id = provider_id
        self.owner.context.llm_generate = forbidden

    def tearDown(self):
        self.fixture.tearDown()

    def running_task(self):
        task, project = self.task(status='running')
        Control.control(task).update(current_step_id='one', constraints=['保留原接口'], human_paused=False)
        task.completion_conditions = ['保留接口并通过测试']
        self.storage.save_task(task)
        return task, project

    def provider(self, fail=False, pause=False):
        async def text_chat(**kwargs):
            self.summaries.append(kwargs)
            if fail:
                raise OSError('model unavailable')
            if pause:
                task = self.storage.load_active_task(self.active_umo)
                task.status = 'paused'
                Control.control(task)['human_paused'] = True
                self.storage.save_task(task)
            return SimpleNamespace(completion_text='原因：旧接口不接受空值。已修改 src/api.py；单测通过。仍需验证兼容性，下一步运行集成测试。')
        return SimpleNamespace(text_chat=text_chat)

    def load(self, task):
        return self.storage.load_active_task(task.umo)

    async def test_stage_summary_is_saved_before_history_reduction(self):
        task, _ = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        continuity.begin_round(task)
        original = [{'role': 'user', 'content': '排查原因'},
                    {'role': 'assistant', 'content': '阅读所得细节' * 2000},
                    {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'call-a', 'type': 'function', 'function': {'name': 'test', 'arguments': '{}'}}]},
                    {'role': 'tool', 'tool_call_id': 'call-a', 'content': 'tests passed'}]
        budget = deepcopy(task.budget.__dict__)
        reduced = await continuity.compact(self.event(task.umo), task, original, self.provider(), 'stage_completed')
        latest = self.load(task)
        saved = C.lane_state(latest)
        record = self.storage._read_json(self.storage.root / saved['record_path'])
        self.assertEqual(record['history'], original)
        self.assertEqual(record['status'], 'saved')
        self.assertIn('src/api.py', reduced[0]['content'])
        self.assertEqual([r['role'] for r in reduced[-2:]], ['assistant', 'tool'])
        self.assertEqual(latest.budget.__dict__, budget)
        self.assertEqual(Control.control(latest)['steps'][0]['status'], 'pending')
        self.assertIn('records', continuity.read(latest))
        first = continuity.read(latest, saved['record_id'], 0, 500)
        self.assertEqual(first['next_offset'], 500)
        second = continuity.read(latest, saved['record_id'], 500, 500)
        self.assertNotEqual(first['text'], second['text'])
        with self.assertRaises(ValueError):
            continuity.read(latest, '../another-task')

    async def test_provider_failure_preserves_archive_and_continues_with_recent_window(self):
        task, _ = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        history = [{'role': 'user', 'content': 'do not forget'}]
        original = deepcopy(history)
        reduced = await continuity.compact(self.event(task.umo), task, history, self.provider(fail=True), 'context_capacity')
        self.assertEqual(history, original)
        saved = self.load(task)
        lane = C.lane_state(saved)
        record = self.storage._read_json(self.storage.root / lane['record_path'])
        self.assertEqual(record['history'], original)
        self.assertEqual(record['summary_outcome'], 'recent_window')
        self.assertEqual(record['model_calls'], 1)
        self.assertEqual(len(self.summaries), 1)
        self.assertEqual(saved.status, 'running')
        self.assertIn(C.MARKER, reduced[0]['content'])
        self.assertEqual(reduced[1:], original)
        self.assertNotIn('必须回查', reduced[0]['content'])
        self.assertNotIn('draft_record_id', lane)

    async def test_disk_failure_and_pause_do_not_authorize_discard(self):
        task, _ = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        history = [{'role': 'user', 'content': 'keep all'}]
        with patch.object(self.storage, '_write_json', side_effect=OSError('disk full')):
            with self.assertRaises(C.HandoffError):
                await continuity.compact(self.event(task.umo), task, history, self.provider(), 'context_capacity')
        self.assertEqual(len(self.summaries), 0)
        self.active_umo = task.umo
        with self.assertRaises(C.HandoffError):
            await continuity.compact(self.event(task.umo), task, history, self.provider(pause=True), 'context_capacity')
        self.assertEqual(self.load(task).status, 'paused')
        self.assertFalse(C.lane_state(self.load(task)).get('record_id'))

    async def test_round_counts_do_not_compact_and_project_capacity_reloads(self):
        task, project = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        self.projects.update(project['project_id'], {'execution_settings': {'continuity': {
            'max_stage_ticks': 2, 'context_tokens': 1000000, 'summary_chars': 4500}}})
        Control.control(task)['steps'].append({'id': 'two', 'title': 'Test', 'instruction': 'test', 'stage': 'development', 'status': 'pending', 'evidence': []})
        Control.control(task)['steps'][0]['stage'] = 'development'
        Control.control(task)['journal'] = [{'id': 'e1', 'status': 'completed', 'plan_version': 1, 'step_id': 'one'}]
        self.storage.save_task(task)
        continuity.begin_round(task)
        self.owner.task_control.checkpoint(self.event(task.umo), 'one', '修改已完成，还需测试', completed=True)
        latest = self.load(task)
        self.assertNotIn('pending_reason', C.lane_state(latest))
        Control.control(latest)['current_step_id'] = 'two'
        for _ in range(30):
            continuity.begin_round(latest)
        self.assertNotIn('pending_reason', C.lane_state(self.load(task)))
        self.assertEqual(self.load(task).status, 'running')
        self.assertFalse(self.summaries)
        self.assertEqual(C.settings(latest)['context_tokens'], 1000000)
        self.assertEqual(C.settings(latest)['summary_chars'], 4500)
        self.projects.update(project['project_id'], {'execution_settings': {'continuity': {
            'context_tokens': 256000, 'summary_chars': 6000}}})
        continuity.begin_round(latest)
        self.assertEqual(C.settings(self.load(task))['context_tokens'], 256000)

    async def test_completed_stage_requests_handoff_without_marking_next_done(self):
        task, _ = self.running_task()
        state = Control.control(task)
        state['steps'][0]['stage'] = 'inspection'
        state['steps'].append({'id': 'two', 'title': 'Next', 'instruction': 'test', 'status': 'pending', 'evidence': []})
        state['journal'] = [{'id': 'e1', 'status': 'completed', 'plan_version': 1, 'step_id': 'one'}]
        self.storage.save_task(task)
        self.owner.task_control.checkpoint(self.event(task.umo), 'one', '已定位原因，src/api.py需兼容修复', completed=True)
        latest = self.load(task)
        self.assertEqual(C.lane_state(latest)['pending_reason'], 'stage_completed')
        self.assertEqual(Control.control(latest)['steps'][1]['status'], 'pending')

    async def test_routine_plan_revision_preserves_summary_and_evidence(self):
        task, _ = self.running_task()
        state = Control.control(task)
        state['steps'][0].update(status='completed', summary='原因和文件已确认', evidence=['old'])
        state['steps'].append({'id': 'two', 'title': 'Fix', 'instruction': 'fix', 'status': 'running', 'evidence': ['e2'], 'summary': '改动已完成，待验证'})
        state['current_step_id'] = 'two'
        state['journal'] = [{'id': 'e2', 'status': 'completed', 'plan_version': 1, 'step_id': 'two'}]
        task.budget.tokens_used = 12345
        self.storage.save_task(task)
        plan = [{'id': 'one', 'title': 'Inspect', 'instruction': 'Read code'},
                {'id': 'two', 'title': 'Fix', 'instruction': 'fix'},
                {'id': 'test', 'title': '测试', 'instruction': '运行兼容测试'}]
        result = await self.owner.task_control.submit_plan(self.event(task.umo), json.dumps({'steps': plan, 'change_reason': '补测试'}))
        latest = self.load(task)
        current = Control.control(latest)
        self.assertIn('已调整并记录', result)
        self.assertEqual(current['approved_version'], current['version'])
        self.assertEqual(current['authorization_version'], 1)
        self.assertEqual(current['steps'][0]['summary'], '原因和文件已确认')
        self.assertEqual(current['steps'][1]['evidence'], ['e2'])
        self.assertEqual(latest.budget.tokens_used, 12345)
        self.assertEqual(latest.status, 'running')
        self.owner.task_control.checkpoint(self.event(task.umo), 'two', '改动核对通过', completed=True)
        self.assertNotIn('pending_reason', C.lane_state(self.load(task)))

    async def test_reopen_retains_old_revision_and_requires_new_evidence(self):
        task, _ = self.running_task()
        state = Control.control(task)
        state['steps'][0].update(status='completed', summary='旧结论', evidence=['e1'])
        state['journal'] = [{'id': 'e1', 'name': 'astrbot_execute_shell', 'status': 'completed', 'plan_version': 1,
                             'step_id': 'one', 'arguments': {'command': 'python -m unittest'}, 'result': '{"exit_code":0}'}]
        self.storage.save_task(task)
        await self.owner.task_control.submit_plan(self.event(task.umo), json.dumps({'steps': [{'id': 'one', 'title': 'Inspect', 'instruction': 'Read code', 'reopen_reason': '发现遗漏空值情况'}]}))
        latest = self.load(task)
        step = Control.control(latest)['steps'][0]
        self.assertEqual(step['status'], 'pending')
        self.assertEqual(step['evidence'], [])
        archive = self.storage._read_json(self.storage.root / Control.control(latest)['plan_changes'][-1]['record_path'])
        self.assertEqual(archive['before'][0]['summary'], '旧结论')
        self.owner.task_control.checkpoint(self.event(task.umo), 'one', '完成返工，尚需重新验证', completed=True)
        Verifier = importlib.import_module('review_agent_lab.verifier').AgentVerifier
        self.assertFalse(Verifier().verify_finish(self.load(task), status='completed', final_summary='测试通过').passed)
        latest = self.load(task)
        Control.control(latest)['journal'].append({'id': 'e2', 'status': 'completed', 'plan_version': 2,
            'authorization_version': 1, 'step_revision': 1, 'step_id': 'one', 'name': 'astrbot_execute_shell',
            'arguments': {'command': 'python -m unittest'}, 'result': '{"exit_code":0}'})
        self.storage.save_task(latest)
        self.owner.task_control.checkpoint(self.event(task.umo), 'one', '新验证通过', completed=True)
        self.assertEqual(Control.control(self.load(task))['steps'][0]['evidence'], ['e2'])
        self.assertTrue(Verifier().verify_finish(self.load(task), status='completed', final_summary='测试通过').passed)

    async def test_material_revision_and_budget_require_human_approval(self):
        task, _ = self.running_task()
        original_conditions = list(task.completion_conditions)
        await self.owner.task_control.submit_plan(self.event(task.umo), json.dumps({
            'steps': [{'id':'one','title':'调整交付','instruction':'整理资料'}],
            'completion_conditions': ['交付整理资料']}))
        latest = self.load(task)
        self.assertEqual(latest.status, 'paused')
        self.assertEqual(Control.control(latest)['approved_version'], 0)
        row = latest.approvals[-1]
        self.assertEqual(row['approval_type'], 'task_plan')
        self.assertEqual(latest.completion_conditions, original_conditions)
        # A budget request cannot modify limits until its exact proposal is approved.
        self.owner.task_control.approval(latest, row, True)
        self.assertEqual(latest.completion_conditions, ['交付整理资料'])
        row['status'] = 'approved'; latest.status = 'running'
        self.storage.save_task(latest)
        old_limit = latest.budget.max_total_tokens
        await self.owner.task_control.submit_plan(self.event(task.umo), json.dumps({'steps': [{'id': 'one', 'title': '直接交付', 'instruction': '跳过测试'}], 'budget': {'max_total_tokens': old_limit + 10000}}))
        latest = self.load(task)
        self.assertEqual(latest.budget.max_total_tokens, old_limit)
        self.owner.task_control.approval(latest, latest.approvals[-1], True)
        self.assertEqual(latest.budget.max_total_tokens, old_limit + 10000)

    async def test_revision_cannot_change_permissions_or_overwrite_user_pause(self):
        task, _ = self.running_task()
        with self.assertRaisesRegex(ValueError, '权限'):
            await self.owner.task_control.submit_plan(self.event(task.umo), '{"steps":["write"],"execution_settings":{"mode":"full"}}')
        latest = self.load(task)
        latest.status = 'paused'
        Control.control(latest)['human_paused'] = True
        self.storage.save_task(latest)
        await self.owner.task_control.submit_plan(self.event(task.umo), '["新增测试"]')
        self.assertEqual(self.load(task).status, 'paused')
        self.assertTrue(Control.control(self.load(task))['human_paused'])
        self.assertFalse(self.owner.task_control.ready(self.load(task)))
        with self.assertRaises(ValueError):
            await self.owner.task_control.submit_plan(self.event(task.umo), '', completed_step='step_1')

    async def test_capacity_wrapper_respects_configured_capacity_and_model_limit(self):
        task, _ = self.running_task()
        class Message:
            def __init__(self, row): self.row = row
            def model_dump(self): return self.row
            @classmethod
            def model_validate(cls, row): return cls(row)
        messages = [Message({'role': 'system', 'content': 'rules'}), Message({'role': 'user', 'content': 'a' * 15000})]
        continuity = C.TaskContinuity(self.owner)
        native = SimpleNamespace(config=SimpleNamespace(max_context_tokens=1000000))
        adapter = C.StageContextManager(continuity, self.event(task.umo), task.task_id, self.provider(), native)
        with patch.dict(sys.modules, {'astrbot.core.agent.message': SimpleNamespace(Message=Message)}):
            self.assertIs(await adapter.process(messages), messages)
            self.assertFalse(self.summaries)
            native.config.max_context_tokens = 4096
            result = await adapter.process(messages)
        self.assertEqual(result[0].row['role'], 'system')
        self.assertIn(C.MARKER, result[1].row['content'])
        self.assertEqual(len(self.summaries), 1)
        self.assertEqual(json.loads(self.summaries[0]['prompt'])['messages'],
                         [message.row for message in messages])
        self.assertLess(adapter.count_tokens(result), 4096 * 70 // 100)
        lane = C.lane_state(self.load(task))
        record = self.storage._read_json(self.storage.root / lane['record_path'])
        self.assertEqual(record['history'], [message.row for message in messages])
        self.assertEqual(record['recent_budget_tokens'], (4096 * 70 // 100) // 4)

    async def test_single_summary_call_preserves_hard_budget_stop_and_source_archive(self):
        task, _ = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        history = [{'role': 'user', 'content': 'logs-' * 1500}]
        original = deepcopy(history)
        class BudgetStopped(Exception): pass
        calls = []
        async def provider(**kwargs):
            calls.append(json.loads(kwargs['prompt']))
            raise BudgetStopped('administrator total token budget exhausted')
        model = SimpleNamespace(text_chat=provider)
        with self.assertRaises(BudgetStopped):
            await continuity.compact(self.event(task.umo), task, history, model, 'context_capacity', token_limit=4000)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['messages'], original)
        self.assertEqual(history, original)
        latest = self.load(task)
        draft = C.lane_state(latest)['draft_record_id']
        self.assertEqual(self.storage._read_json(continuity.directory(latest)/f'{draft}.json')['history'], original)
        self.assertNotIn('record_id', C.lane_state(latest))

    async def test_incomplete_tool_groups_block_but_empty_summary_keeps_recent_window(self):
        task, _ = self.running_task()
        continuity = C.TaskContinuity(self.owner)
        incomplete = [{'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'pending'}]}]
        with self.assertRaises(C.HandoffError):
            await continuity.compact(self.event(task.umo), task, incomplete, self.provider(), 'context_capacity')
        self.assertFalse(self.summaries)
        async def empty(**kwargs): return SimpleNamespace(completion_text='')
        history = [{'role': 'user', 'content': 'important'}]
        reduced = await continuity.compact(self.event(task.umo), task, history, SimpleNamespace(text_chat=empty), 'stage_completed')
        self.assertIn(C.MARKER, reduced[0]['content'])
        self.assertEqual(reduced[1:], history)
        lane = C.lane_state(self.load(task))
        self.assertEqual(lane['quality'], 'normal')
        self.assertEqual(self.load(task).status, 'running')
        record = self.storage._read_json(self.storage.root / lane['record_path'])
        self.assertEqual(record['model_calls'], 1)
        self.assertEqual(record['summary_outcome'], 'recent_window')

    async def test_long_summary_is_trimmed_once_at_configured_limit(self):
        task, project = self.running_task()
        self.projects.update(project['project_id'], {'execution_settings': {'continuity': {'summary_chars': 4000}}})
        continuity = C.TaskContinuity(self.owner)
        continuity.begin_round(task)
        calls = []
        async def long_summary(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(completion_text=('已确认文件 src/a.py；仍需测试。\n\n' * 500))
        history = [{'role': 'user', 'content': 'original material'}]
        await continuity.compact(self.event(task.umo), task, history,
                                 SimpleNamespace(text_chat=long_summary), 'stage_completed')
        lane = C.lane_state(self.load(task))
        record = self.storage._read_json(self.storage.root / lane['record_path'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(record['summary_limit'], 4000)
        self.assertLessEqual(len(lane['summary']), 4000)
        self.assertGreater(len(lane['summary']), 3000)
        self.assertEqual(record['summary_outcome'], 'truncated')
        self.assertEqual(record['history'], history)

    async def test_native_bridge_rounds_keep_history_then_handoff_on_stage_change(self):
        await self._bridge_rounds()

    async def test_installed_astrbot_runner_executes_stage_handoff(self):
        # Import the real plugin too: decorators must accept every tool schema.
        sys.path.insert(0, str(ROOT.parent))
        plugin = importlib.import_module(f'{ROOT.name}.main')
        for name in ('task_plan', 'task_progress', 'task_ask', 'task_approve', 'task_finish'):
            self.assertTrue(hasattr(plugin.AgentLabPlugin, name), name)
        self.assertTrue(hasattr(plugin.AgentLabPlugin, '_workflow_variable'))
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        await self._bridge_rounds(ToolLoopAgentRunner)

    async def _bridge_rounds(self, installed_runner=None):
        # Provider entities depend on the real message classes. Load them before
        # replacing only the runner's message adapter in the deterministic test.
        import astrbot.core.provider.entities
        from uuid import uuid5, NAMESPACE_URL
        Bridge = importlib.import_module('review_agent_lab.astrbot_bridge').AstrBotBridge
        task, _ = self.running_task()
        Control.control(task)['steps'][0]['stage'] = 'inspection'
        Control.control(task)['steps'].append({'id': 'two', 'title': 'Test', 'instruction': 'run tests', 'status': 'pending', 'evidence': []})
        Control.control(task)['journal'] = [{'id': 'e1', 'status': 'completed', 'plan_version': 1, 'step_id': 'one'}]
        self.storage.save_task(task)
        history = [{'role': 'user', 'content': 'original goal'}] + [{'role': 'assistant', 'content': f'finding {i}'} for i in range(55)]
        original = deepcopy(history)
        cid = str(uuid5(NAMESPACE_URL, 'agent-lab:'+task.task_id+':'))
        self.db.rows[cid] = SimpleNamespace(history=json.dumps(history))
        async def current(umo): return 'daily-id'
        daily = SimpleNamespace(persona_id='bot', history='[{"role":"user","content":"daily untouched"}]')
        async def conversation(umo, key): return daily if key == 'daily-id' else self.db.rows[key]
        async def update(umo, key, **kwargs): self.db.rows[key].history = json.dumps(kwargs['history'])
        self.owner.context.conversation_manager.get_curr_conversation_id = current
        self.owner.context.conversation_manager.get_conversation = conversation
        self.owner.context.conversation_manager.update_conversation = update
        async def persona(**kwargs): return None, {'name': '小莫', 'prompt': 'daily chatter should not be copied'}, None, None
        self.owner.context.persona_manager = SimpleNamespace(resolve_selected_persona=persona)
        calls = []
        async def chat(**kwargs):
            from astrbot.core.provider.entities import LLMResponse
            calls.append(kwargs)
            if kwargs.get('system_prompt', '').startswith('生成接续当前任务的工作笔记'):
                return LLMResponse(role='assistant', completion_text='已确认空值错误，文件 src/api.py，决定保持接口，修复已完成，待运行测试。')
            if installed_runner and Control.control(self.load(task))['steps'][0]['status'] != 'completed':
                self.owner.task_control.checkpoint(event, 'one', '定位和文件已确认，待验证', completed=True)
            return LLMResponse(role='assistant', completion_text='本轮结束')
        async def model(key): return SimpleNamespace(text_chat=chat, provider_config={'max_context_tokens': 1000000})
        self.owner.context.provider_manager = SimpleNamespace(get_provider_by_id=model)
        self.owner._cfg_value = lambda key, default: default
        class Message:
            def __init__(self, row): self.row = row; self.role = row['role']
            def model_dump(self): return self.row
            @classmethod
            def model_validate(cls, row): return cls(row)
        owner = self.owner
        class Runner:
            observed = []
            def request_stop(self): self.stopped = True
            async def reset(self, **kwargs):
                self.provider = kwargs['provider']; self.context = kwargs['run_context']; self.executor = kwargs['tool_executor']
                self.context.messages = [Message({'role': 'system', 'content': kwargs['request'].system_prompt}),
                                         *[Message(row) for row in kwargs['request'].contexts],
                                         Message({'role': 'user', 'content': kwargs['request'].prompt})]
                self.request_context_manager = SimpleNamespace(config=SimpleNamespace(max_context_tokens=1000000))
            async def step_until_done(self, max_steps):
                self.context.messages = await self.request_context_manager.process(self.context.messages)
                self.observed.append([m.row for m in self.context.messages])
                await self.provider.text_chat(prompt='continue')
                if len(self.observed) == 1:
                    owner.task_control.checkpoint(self.context.context.event, 'one', '定位和文件已确认，待验证', completed=True)
                self.context.messages.append(Message({'role': 'assistant', 'content': 'saved round'}))
                if False: yield None
            def get_final_llm_resp(self): return SimpleNamespace(completion_text='本轮结束')
        modules = {
            'astrbot.core.astr_agent_context': SimpleNamespace(AstrAgentContext=SimpleNamespace, AgentContextWrapper=SimpleNamespace),
            'astrbot.core.agent.runners.tool_loop_agent_runner': SimpleNamespace(ToolLoopAgentRunner=installed_runner or Runner),
        }
        if not installed_runner:
            modules['astrbot.core.agent.message'] = SimpleNamespace(Message=Message)
        event = self.event(task.umo); event._extras = {}
        event.set_extra = lambda key, value: event._extras.update({key: value})
        event.get_extra = lambda key, default=None: event._extras.get(key, default)
        event.get_platform_name = lambda: 'qq-a'
        bridge = Bridge(self.owner)
        bridge.execution_context = lambda event: self.owner.context
        tools = SimpleNamespace(tools=[])
        hooks = None
        if installed_runner:
            from astrbot.core.agent.hooks import BaseAgentRunHooks
            hooks = BaseAgentRunHooks()
        with patch.dict(sys.modules, modules):
            await bridge.run(event, task, tools, 'continue', Control.prompt(task), 8, hooks)
            if not installed_runner:
                self.assertEqual(Runner.observed[0][1:57], original)
            latest = self.load(task); Control.control(latest)['current_step_id'] = 'two'; self.storage.save_task(latest)
            # The same source event is reused by automatic continuation ticks.
            event.set_extra('agent_lab_boundary_stopped', True)
            await bridge.run(event, latest, tools, 'continue next', Control.prompt(latest), 8, hooks)
            self.assertFalse(event.get_extra('agent_lab_boundary_stopped'))
        self.assertEqual(daily.history, '[{"role":"user","content":"daily untouched"}]')
        self.assertEqual(len(C.TaskContinuity(self.owner).read(self.load(task))['records']), 1)
        if not installed_runner:
            self.assertTrue(any(C.MARKER in str(m.get('content', '')) for m in Runner.observed[1]))
        else:
            stored = json.loads(self.db.rows[cid].history)
            self.assertIn(C.MARKER, stored[0]['content'])
            self.assertIn('finding 54', str(stored))
            # This tiny history fits inside the recent-window allocation.
            self.assertTrue(all(row in stored for row in original))
        self.assertFalse(any('_agent_lab_handoff' in call for call in calls))
        self.assertEqual(Control.control(self.load(task))['steps'][1]['status'], 'pending')
        metrics = self.load(task).workflow_data['usage_metrics']
        self.assertGreaterEqual(metrics['model_calls'], 2)
        trace = self.storage.task_memory_dir(task.umo, task.task_id) / 'usage.jsonl'
        entries = [json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(entries), metrics['model_calls'])
        self.assertTrue(all('prompt' not in entry and 'contexts' not in entry for entry in entries))

    async def test_handoff_failure_pauses_real_tick_without_native_discard(self):
        # Run the real tick coordinator; isolate only AstrBot/provider plumbing.
        task, _ = self.running_task()
        Control.control(task)['workflow'] = 'none'; self.storage.save_task(task)
        owner = self.owner
        Runner = importlib.import_module('review_agent_lab.runtime_runner').AgentRuntimeRunner
        owner.config = {}
        owner._progress_hash = lambda task: 'same'
        owner._acquire_task_lease = lambda task, **kwargs: (True, 'lease')
        owner._release_task_lease = lambda *args: None
        owner._watchdog_before_tick = lambda *args: ''
        owner._normalize_agent_workflow = lambda *args: None
        owner._sync_agent_runtime = lambda *args, **kwargs: None
        owner.agent_runtime = SimpleNamespace(record_decision=lambda *args, **kw: None, update_resume=lambda *args, **kw: None)
        owner._build_task_extensions_prompt = lambda *args, **kwargs: ''
        owner._build_toolset = lambda *args: SimpleNamespace(tools=[])
        owner._budget_remaining_tools = lambda task: 8
        async def workflow(**kwargs): return SimpleNamespace(changed=False, needs_react=True, blocked=False)
        owner._run_workflow_runtime = workflow
        async def batch(*args): return True
        async def failed(*args): raise C.HandoffError('交接保存失败，历史已保留')
        owner.astrbot_bridge = SimpleNamespace(resume_batch=batch, run=failed)
        event = self.event(task.umo); event.set_extra = lambda *args: None
        fake_hooks = SimpleNamespace(AgentLabRunHooks=lambda *args, **kwargs: None)
        with patch.dict(sys.modules, {'review_agent_lab.hooks': fake_hooks}):
            # runtime_runner imports hooks at load time; replace that binding only.
            with patch('review_agent_lab.runtime_runner.AgentLabRunHooks', lambda *args, **kwargs: None):
                result = await Runner(owner).run_tick(event, 'continuation')
        self.assertIn('历史已保留', result)
        latest = self.load(task)
        self.assertEqual(latest.status, 'paused')
        self.assertEqual(latest.wait.wait_reason, 'handoff_failed')
        self.assertFalse(owner._running_ticks)

    def test_continuity_settings_validate_all_limits(self):
        self.assertEqual(Settings.normalize({})['continuity']['context_tokens'], 128000)
        configured = Settings.normalize({'continuity': {'context_tokens': 1000000, 'summary_chars': 6000}})
        self.assertEqual(configured['continuity']['context_tokens'], 1000000)
        self.assertEqual(configured['continuity']['summary_chars'], 6000)
        for values in ({'context_tokens': 0}, {'context_percent': 99}, {'max_stage_ticks': 0}, {'summary_chars': 100}, {'unexpected': 1}):
            with self.assertRaises(ValueError):
                Settings.normalize({'continuity': values})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContinuityTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
