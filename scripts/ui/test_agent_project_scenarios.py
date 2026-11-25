"""Offline project/Bot lifecycle scenarios against real Agent Lab functions.

Run: python scripts/ui/test_agent_project_scenarios.py
Only this script and its JSON report are repository outputs. All task records,
workspaces, conversations and tool side effects live in TemporaryDirectory.
The AstrBot executor, provider, transport and budget callbacks are explicit
fakes; project/control/bridge/continuity/storage/message implementations are real.
No network, live credentials, AstrBot process or production database is used.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import hashlib
import importlib
import inspect
import json
import platform
import shlex
import socket
import sys
import time
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

sys.dont_write_bytecode = True
import test_project_runtime as F

B = importlib.import_module('review_agent_lab.astrbot_bridge')
C = importlib.import_module('review_agent_lab.continuity')
M = importlib.import_module('review_agent_lab.task_messages')
U = importlib.import_module('review_agent_lab.usage_metrics')
Control = F.Control
RESULTS = []
REPORT = F.ROOT / 'docs/validation/v0.4.0-project-scenarios.json'


def fingerprint_sources():
    paths = [F.ROOT / 'main.py', F.ROOT / 'metadata.yaml', *sorted((F.ROOT / 'agent_lab').glob('*.py'))]
    return {str(p.relative_to(F.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def file_snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def actual_checkpoint_method():
    """Execute the saved main.py method without importing the AstrBot plugin."""
    tree = ast.parse((F.ROOT / 'main.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == 'agent_lab_checkpoint')
    method.decorator_list = []
    namespace = {'AstrMessageEvent': object, 'task_control': Control.control, 'now_iso': F.Models.now_iso}
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<real-main-checkpoint>', 'exec'), namespace)
    return namespace[method.name]


class FakeProvider:
    def __init__(self):
        self.responses = []
        self.calls = []

    async def text_chat(self, **kwargs):
        started = time.perf_counter()
        handoff = kwargs.get('_agent_lab_handoff', False)
        text = ('已保留原始记录和工具证据；当前步骤已核对，后续验证仍需继续。'
                if handoff else self.responses.pop(0))
        self.calls.append({'phase': 'handoff' if handoff else 'plan_or_review',
                           **U.request_size(kwargs, kwargs), 'response_chars': len(text),
                           'elapsed_ms': round((time.perf_counter() - started) * 1000, 3),
                           'usage_source': 'estimated_request_only_no_provider_usage'})
        return S(completion_text=text)


class AgentProjectScenarios(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.started = time.perf_counter()
        self.fixture = F.ProjectRuntime()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.owner, self.storage = self.fixture.owner, self.fixture.storage
        self.projects = self.fixture.projects
        self.workspace = Path(self.fixture.temp.name) / 'workspace'
        self.workspace.mkdir()
        self.provider = FakeProvider()
        self.metrics = {}
        self.tasks = []
        self.events = {}
        self.calls = []
        self.invocations = 0
        self.sent = []
        self.tool_hook = None
        self.concurrent = self.peak_concurrent = 0
        self.bridge = B.AstrBotBridge(self.owner)
        names = ['astrbot_file_read_tool', 'astrbot_file_write_tool',
                 'astrbot_file_edit_tool', 'astrbot_execute_shell', 'astrbot_execute_python']
        self.tools = {name: S(name=name, description='offline scenario fixture') for name in names}
        self.bridge.tool = lambda name, event=None: self.tools.get(name)
        self.bridge.execution_context = lambda event: self.owner.context
        self.owner._tool_allowed_by_agent_profile = self.owner._tool_available_for_agent = lambda *a: True
        self.owner._disabled_plugin_names = lambda *a: []
        self.owner._effective_tool_risk = self.owner._infer_tool_risk = lambda *a: 'work'
        self.owner._cfg_value = lambda key, default: default
        self.owner._context_config = lambda *a: {'provider_settings': {'computer_use_runtime': 'local'}}
        self.owner._budget_remaining_tools = lambda task: 1000 - task.budget.tool_calls_used
        def consume(task, name):
            task.budget.tool_calls_used += 1
            return ''
        self.owner._consume_tool_budget = consume
        self.owner.context.llm_generate = self.provider.text_chat
        async def provider_id(umo):
            return 'offline-provider-' + umo.split(':')[0]
        self.owner.context.get_current_chat_provider_id = provider_id
        async def send(umo, text):
            self.sent.append({'umo': umo, 'text': text})
        self.owner.task_messages = M.TaskMessages(self.owner, send=send)
        async def workspace(context):
            return self.workspace
        modules = {
            'astrbot.core.astr_agent_context': S(AstrAgentContext=S, AgentContextWrapper=S),
            'astrbot.core.astr_agent_tool_exec': S(FunctionToolExecutor=S(execute=self.execute)),
            'astrbot.core.tools.computer_tools.util': S(workspace_root_for_context=workspace),
        }
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        for name in ('connect', 'connect_ex'):
            block = patch.object(socket.socket, name, side_effect=AssertionError('network forbidden in offline scenarios'))
            block.start()
            self.addCleanup(block.stop)
        self.addCleanup(self.collect)

    def collect(self):
        records = {}
        for task in self.tasks:
            try:
                current = self.projects.get_task(task.task_id)
                paths = self.projects.task_paths(current)
                records[task.task_id] = {
                    'status': current.status, 'files': len(paths),
                    'stored_chars': sum(len(p.read_text(encoding='utf-8')) for p in paths),
                    'stored_bytes': sum(p.stat().st_size for p in paths),
                    'journal_rows': len(Control.control(current).get('journal', [])),
                    'budget_tool_calls': current.budget.tool_calls_used,
                    'plan_prompt_chars': len(Control.prompt(current)),
                    'project_context_chars': len(self.projects.filtered_context(current)),
                }
            except ValueError:
                records[task.task_id] = {'deleted': True}
        RESULTS.append({'scenario': self._testMethodName, 'elapsed_ms': round((time.perf_counter()-self.started)*1000, 3),
                        'bridge_invocations': self.invocations, 'executor_calls': len(self.calls),
                        'executor_calls_by_tool': {name: sum(r['tool'] == name for r in self.calls)
                                                   for name in self.tools},
                        'tool_elapsed_ms': round(sum(r['elapsed_ms'] for r in self.calls), 3),
                        'tool_argument_chars': sum(r['argument_chars'] for r in self.calls),
                        'tool_output_chars': sum(r.get('output_chars', 0) for r in self.calls),
                        'fake_provider_calls': self.provider.calls, 'fake_transport_messages': len(self.sent),
                        'peak_concurrent_executor_calls': self.peak_concurrent,
                        'tasks': records, 'observations': self.metrics})

    def event(self, task):
        if task.task_id not in self.events:
            extras = {'agent_lab_round_id': 'scenario-round'}
            event = self.fixture.event(task.umo)
            event.role = 'admin'
            event.get_extra = lambda key, default=None: extras.get(key, default)
            event.set_extra = lambda key, value: extras.__setitem__(key, value)
            event.message_str = '继续当前临时模拟任务'
            self.events[task.task_id] = event
        return self.events[task.task_id]

    def create(self, title='Scenario', bot='qq-a', mode='full'):
        task, project = self.fixture.task(bot=bot, project=title)
        self.owner.task_control.initialize(task, self.event(task), 'none')
        Control.control(task)['project_id'] = project['project_id']
        task.root_goal = title
        self.projects.update(project['project_id'], {'execution_settings': {'mode': mode, 'roots': [str(self.workspace)]}})
        self.storage.save_task(task)
        self.owner.task_control.refresh_execution_settings(task)
        self.tasks.append(task)
        return task, project

    def latest(self, task):
        return self.projects.get_task(task.task_id)

    def resume(self, task, step=''):
        current = self.latest(task)
        current.status = 'running'
        current.clear_wait()
        Control.control(current)['human_paused'] = False
        if step:
            Control.control(current)['current_step_id'] = step
        self.storage.save_task(current)
        return current

    def decision(self, task, approved):
        current = self.latest(task)
        row = next(r for r in current.approvals if r['status'] == 'pending')
        self.owner.task_control.approval(current, row, approved)
        row['status'] = 'approved' if approved else 'rejected'
        if approved:
            current.status = 'running'
            current.clear_wait()
        self.storage.save_task(current)
        return row

    async def plan(self, task, steps=None, *, propose=False):
        steps = steps or [{'id': 'one', 'title': '核对', 'instruction': '检查临时成果'}]
        proposal = {'steps': steps, 'scope_roots': [str(self.workspace)]}
        if propose:
            self.provider.responses.append(json.dumps(proposal, ensure_ascii=False))
            await self.owner.task_control.propose(self.event(task), task.task_id)
        else:
            await self.owner.task_control.submit_plan(self.event(task), json.dumps(proposal, ensure_ascii=False))
        self.decision(task, True)
        return self.resume(task, steps[0]['id'])

    async def invoke(self, task, name, args, *, native=False):
        self.invocations += 1
        return await self.bridge.invoke(self.event(task), self.tools[name], args, task.task_id, native=native)

    async def execute(self, tool, context, **args):
        from mcp.types import CallToolResult, TextContent
        started = time.perf_counter()
        event = context.context.event
        row = {'tool': tool.name, 'umo': event.unified_msg_origin,
               'argument_chars': len(json.dumps(args, ensure_ascii=False)), 'elapsed_ms': 0}
        self.calls.append(row)
        self.concurrent += 1
        self.peak_concurrent = max(self.peak_concurrent, self.concurrent)
        try:
            if self.tool_hook:
                await self.tool_hook(tool, context, args)
            def checked(value):
                path = Path(value).resolve()
                if not path.is_relative_to(self.workspace.resolve()):
                    raise AssertionError('fake executor escaped temporary workspace')
                return path
            if tool.name == 'astrbot_file_read_tool':
                path = checked(args['path'])
                lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
                start = args.get('offset', 0)
                output = ''.join(lines[start:start+args.get('limit', len(lines))])
            elif tool.name == 'astrbot_file_write_tool':
                path = checked(args['path'])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(args['content'], encoding='utf-8')
                output = 'written ' + path.name
            elif tool.name == 'astrbot_file_edit_tool':
                path = checked(args['path'])
                body = path.read_text(encoding='utf-8')
                if args['old'] not in body:
                    raise AssertionError('edit fixture target absent')
                path.write_text(body.replace(args['old'], args['new']), encoding='utf-8')
                output = 'edited ' + path.name
            elif tool.name == 'astrbot_execute_shell':
                argv = shlex.split(args['command'])
                if argv[0] != 'rm' or not 1 <= len(argv[1:]) <= 2:
                    raise AssertionError('fake shell accepts only one/two explicit temporary files')
                paths = [checked(value) for value in argv[1:]]
                if any(not path.is_file() for path in paths):
                    raise AssertionError('small cleanup requires existing regular files')
                for path in paths:
                    path.unlink()
                output = 'removed ' + str(len(paths)) + ' named temporary files'
            else:
                raise AssertionError('unimplemented fake tool: ' + tool.name)
            row['output_chars'] = len(output)
            yield CallToolResult(content=[TextContent(type='text', text=output)])
        finally:
            row['elapsed_ms'] = round((time.perf_counter()-started)*1000, 3)
            self.concurrent -= 1

    def checkpoint(self, task, step, summary, *, completed=True):
        current = self.latest(task)
        state = Control.control(current)
        revision = next(r.get('revision', 0) for r in state['steps'] if r['id'] == step)
        authority = state.get('authorization_version', state['approved_version'])
        evidence = [r['id'] for r in Control.control(current)['journal']
                    if r['step_id'] == step and r['status'] == 'completed'
                    and r.get('step_revision', 0) == revision
                    and r.get('authorization_version', r.get('plan_version')) == authority]
        return self.owner.task_control.checkpoint(self.event(task), step, summary, json.dumps(evidence), completed)

    async def test_document_research_without_workspace_writes(self):
        document = self.workspace / 'reference.md'
        document.write_text(''.join(f'第{i}条：离线接口研究材料。\n' for i in range(180)), encoding='utf-8')
        before = file_snapshot(self.workspace)
        task, _ = self.create('文档研究，只读', mode='readonly')
        await self.plan(task, propose=True)
        first = await self.invoke(task, 'astrbot_file_read_tool', {'path': str(document), 'offset': 0, 'limit': 80})
        second = await self.invoke(task, 'astrbot_file_read_tool', {'path': str(document), 'offset': 0, 'limit': 80})
        self.assertIn('第0条', first)
        self.assertIn('第0条', second)
        expected = ''.join(document.read_text(encoding='utf-8').splitlines(keepends=True)[:80])
        self.assertEqual(first, expected)
        self.assertEqual(second, expected)
        self.assertEqual(len(self.calls), 2, 'each requested source read must reach the host executor')
        reads = Control.control(self.latest(task))['journal']
        self.assertEqual([row['arguments'] for row in reads],
                         [{'path': str(document), 'offset': 0, 'limit': 80}] * 2)
        self.assertTrue(all(row['status'] == 'completed' for row in reads))
        self.assertEqual(self.latest(task).status, 'running', 'two research reads are not a read loop')
        with self.assertRaisesRegex(ValueError, '只读'):
            await self.invoke(task, 'astrbot_file_write_tool', {'path': str(self.workspace/'forbidden.md'), 'content': 'no'})
        self.checkpoint(task, 'one', '已读取离线文档；结论保留于任务记录，不生成工作目录文件。')
        ended = await self.projects.administrator_end(task.task_id, 'completed', '研究完成，无工作目录文件写入。', 'offline-admin')
        self.assertEqual(ended.status, 'completed')
        self.assertEqual(file_snapshot(self.workspace), before)
        self.metrics.update(workspace_files_unchanged=True, workspace_write_calls=0,
                            provider_plan_calls=len(self.provider.calls), repeated_read_executor_calls=len(self.calls))

    async def test_repeated_reads_warn_once_then_pause_without_suppressing_host_reads(self):
        document = self.workspace / 'repeated.md'
        document.write_text(''.join(f'line {i}: research material\n' for i in range(180)), encoding='utf-8')
        before = file_snapshot(self.workspace)
        task, _ = self.create('重复研究读取保护', mode='readonly')
        await self.plan(task)
        args = {'path': str(document), 'offset': 0, 'limit': 80}
        expected = ''.join(document.read_text(encoding='utf-8').splitlines(keepends=True)[:80])
        notices = []
        for number in range(1, 41):
            output = await self.invoke(task, 'astrbot_file_read_tool', args)
            self.assertTrue(output.startswith(expected))
            self.assertEqual(len(self.calls), number, 'admitted reads must not be served from a cache')
            current = self.latest(task)
            guard = current.workflow_data.get('progress_guard', {})
            if guard.get('decision') in {'warning', 'paused'}:
                notices.append((number, guard['decision']))
                self.assertIn(guard['message'], output)
                if guard['decision'] == 'warning':
                    self.assertEqual(current.status, 'running')
            if current.status == 'paused':
                break
        self.assertEqual([decision for _, decision in notices], ['warning', 'paused'])
        self.assertGreater(notices[0][0], 2, 'ordinary research repeats must be allowed')
        self.assertGreater(notices[1][0], notices[0][0], 'the first warning must allow a correction')
        self.assertEqual(self.latest(task).wait.wait_reason, 'repeated_reads')
        dispatched = len(self.calls)
        with self.assertRaises(B.ExecutionStopped):
            await self.invoke(task, 'astrbot_file_read_tool', args)
        self.assertEqual(len(self.calls), dispatched, 'paused tasks must not dispatch another read')
        self.assertEqual(file_snapshot(self.workspace), before)
        self.metrics.update(repeated_read_executor_calls=dispatched, read_loop_notices=notices,
                            workspace_files_unchanged=True, dispatch_blocked_after_pause=True)

    async def test_plugin_create_update_and_two_named_file_cleanup(self):
        task, _ = self.create('小插件创建更新')
        await self.plan(task)
        main = self.workspace/'sample_plugin'/'main.py'
        metadata = main.with_name('metadata.yaml')
        for path, content in [(main, 'def reply():\n    return "v1"\n'), (metadata, 'name: offline_sample\nversion: 1\n')]:
            await self.invoke(task, 'astrbot_file_write_tool', {'path': str(path), 'content': content})
        await self.invoke(task, 'astrbot_file_read_tool', {'path': str(main), 'limit': 30})
        await self.invoke(task, 'astrbot_file_edit_tool', {'path': str(main), 'old': '"v1"', 'new': '"v2"'})
        updated = await self.invoke(task, 'astrbot_file_read_tool', {'path': str(main), 'limit': 30})
        self.assertIn('v2', updated)
        namespace = {}
        exec(compile(main.read_text(encoding='utf-8'), '<temporary-sample-plugin>', 'exec'), namespace)
        self.assertEqual(namespace['reply'](), 'v2')
        obsolete = [main.with_name(name) for name in ('one.tmp', 'two.tmp')]
        for path in obsolete:
            await self.invoke(task, 'astrbot_file_write_tool', {'path': str(path), 'content': 'temporary'})
        await self.invoke(task, 'astrbot_execute_shell', {'command': 'rm ' + ' '.join(shlex.quote(str(p)) for p in obsolete)})
        self.assertTrue(main.exists() and metadata.exists())
        self.assertTrue(all(not p.exists() for p in obsolete))
        self.assertEqual(self.latest(task).approvals[-1]['approval_type'], 'task_plan')
        self.assertFalse(any(r['approval_type'] == 'tool_batch' for r in self.latest(task).approvals))
        self.checkpoint(task, 'one', '临时插件创建、v2更新、函数执行及两个明确临时文件清理通过。')
        self.metrics.update(named_files_removed=2, plugin_function_result='v2', automatic_tool_approvals=0)

    async def test_parallel_projects_from_distinct_bot_sources(self):
        a, pa = self.create('相同项目名', 'qq-a')
        await self.plan(a)
        b, pb = self.create('相同项目名', 'qq-b')
        await self.plan(b)
        all_entered = asyncio.Event()
        arrived = set()
        async def barrier(tool, context, args):
            arrived.add(context.context.event.unified_msg_origin)
            if len(arrived) == 2:
                all_entered.set()
            await asyncio.wait_for(all_entered.wait(), 2)
        self.tool_hook = barrier
        await asyncio.gather(self.invoke(a, 'astrbot_file_write_tool', {'path': str(self.workspace/'a.txt'), 'content': 'ONLY_A'}),
                             self.invoke(b, 'astrbot_file_write_tool', {'path': str(self.workspace/'b.txt'), 'content': 'ONLY_B'}))
        self.assertEqual(self.peak_concurrent, 2)
        self.assertNotEqual(pa['project_id'], pb['project_id'])
        self.projects.save_summary(a.task_id, 'ONLY_A_SUMMARY')
        self.projects.save_summary(b.task_id, 'ONLY_B_SUMMARY')
        self.assertNotIn('ONLY_A', self.projects.filtered_context(self.latest(b)))
        self.assertEqual(self.projects.daily_summary(a.umo), '')
        self.projects.update(pa['project_id'], {'share_with_daily': True})
        self.assertEqual(self.projects.daily_summary(a.umo), 'ONLY_A_SUMMARY')
        self.assertEqual(self.projects.daily_summary(b.umo), '')
        with self.assertRaises(ValueError):
            await self.projects.activate(a.task_id, self.event(b))
        with self.assertRaises(ValueError):
            self.projects.attach(self.latest(a), pb['project_id'])
        self.metrics.update(distinct_projects=True, source_context_isolation=True, daily_summary_opt_in=True)

    async def test_same_source_switch_resume_and_stale_round(self):
        a, pa = self.create('同来源A')
        await self.plan(a)
        await self.invoke(a, 'astrbot_file_write_tool', {'path': str(self.workspace/'a.txt'), 'content': 'A evidence'})
        self.checkpoint(a, 'one', 'A核对已完成，保留证据', completed=False)
        stale = deepcopy(self.latest(a))
        b, pb = self.create('同来源B')
        await self.plan(b)
        await self.projects.activate(a.task_id, self.event(a))
        self.assertEqual(self.latest(b).status, 'paused')
        self.resume(a)
        self.assertEqual(self.latest(a).last_confirmed_progress, 'A核对已完成，保留证据')
        await self.projects.activate(b.task_id, self.event(b))
        self.resume(b)
        self.storage.save_task(stale)
        self.assertEqual(self.storage.load_active_task(a.umo).task_id, b.task_id)
        with self.assertRaises(B.ExecutionStopped):
            await self.invoke(a, 'astrbot_file_write_tool', {'path': str(self.workspace/'stale.txt'), 'content': 'wrong task'})
        self.assertFalse((self.workspace/'stale.txt').exists())
        await self.projects.activate(a.task_id, self.event(a))
        self.resume(a)
        self.assertEqual(Control.control(self.latest(a))['journal'][0]['status'], 'completed')
        self.assertEqual(self.projects.index()['selected'][a.umo], pa['project_id'])
        self.assertNotEqual(pa['project_id'], pb['project_id'])
        self.metrics.update(pointer_not_reclaimed_by_stale_save=True, stale_tool_callback_rejected=True,
                            retained_checkpoint=True, selected_project_matches_resumed_task=True)

    async def test_same_project_archived_task_handoff_and_targeted_cleanup(self):
        first, project = self.create('同项目后续任务')
        await self.plan(first)
        await self.invoke(first, 'astrbot_file_write_tool', {'path': str(self.workspace/'first.txt'), 'content': 'first result'})
        self.checkpoint(first, 'one', '首轮成果已核对，下一轮补兼容性测试。')
        await self.projects.administrator_end(first.task_id, 'completed', 'FIRST_HANDOFF：成果已写入first.txt，仍需兼容测试。', 'offline-admin')
        second, same = self.create('同项目后续任务')
        await self.plan(second)
        self.assertEqual(same['project_id'], project['project_id'])
        context = self.projects.filtered_context(self.latest(second))
        self.assertIn('FIRST_HANDOFF', context)
        self.assertNotEqual(first.task_id, second.task_id)
        self.assertNotEqual(self.projects.conversation_ids(first), self.projects.conversation_ids(second))
        self.assertEqual(Control.control(self.latest(second))['journal'], [])
        await self.invoke(second, 'astrbot_file_write_tool', {'path': str(self.workspace/'second.txt'), 'content': 'second result'})
        self.projects.save_summary(second.task_id, 'SECOND_HANDOFF：兼容性工作仍在进行。')
        second_paths = self.projects.task_paths(self.latest(second))
        before = {str(p): p.read_bytes() for p in second_paths}
        # An archived sibling may be cleaned while a different task in the same
        # project is running, provided the preview targets the exact old task.
        plan = await self.projects.cleanup_plan(project['project_id'], first.task_id, 'history')
        self.assertEqual(plan['task_ids'], [first.task_id])
        await self.projects.cleanup(project['project_id'], first.task_id, 'history', plan['token'])
        self.assertEqual(self.storage.load_active_task(second.umo).task_id, second.task_id)
        self.assertEqual(self.latest(second).status, 'running')
        self.assertTrue(all(Path(path).read_bytes() == body for path, body in before.items()))
        self.assertIn('SECOND_HANDOFF', self.projects.filtered_context(self.latest(second)))
        self.assertNotIn('FIRST_HANDOFF', self.projects.filtered_context(self.latest(second)))
        self.assertTrue((self.workspace/'first.txt').exists())
        self.assertTrue((self.workspace/'second.txt').exists())
        with self.assertRaises(ValueError):
            self.projects.get_task(first.task_id)
        self.metrics.update(project_reused=True, prior_context_chars=len(context),
                            task_conversations_disjoint=True, evidence_not_copied_as_new_authority=True,
                            running_sibling_files_unchanged=True, targeted_cleanup_keeps_new_summary=True)

    async def test_same_source_switch_waits_for_inflight_tick(self):
        a, _ = self.create('切换前等待调用收尾A')
        await self.plan(a)
        b, _ = self.create('切换前等待调用收尾B')
        await self.plan(b)
        await self.projects.activate(a.task_id, self.event(a))
        self.resume(a)
        entered, release = asyncio.Event(), asyncio.Event()
        async def delay(tool, context, args):
            entered.set()
            await release.wait()
        self.tool_hook = delay
        tick_key = f'{a.umo}:{a.task_id}'
        self.owner._running_ticks.add(tick_key)
        pending = asyncio.create_task(self.invoke(a, 'astrbot_file_write_tool',
                                     {'path': str(self.workspace/'inflight.txt'), 'content': 'retained effect'}))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            with self.assertRaisesRegex(ValueError, '收尾'):
                await self.projects.activate(b.task_id, self.event(b))
            self.assertEqual(self.storage.load_active_task(a.umo).task_id, a.task_id)
            self.assertEqual(self.latest(a).status, 'paused')
            release.set()
            await asyncio.wait_for(pending, 2)
            self.owner._running_ticks.discard(tick_key)
            await self.projects.activate(b.task_id, self.event(b))
            self.assertEqual(self.storage.load_active_task(a.umo).task_id, b.task_id)
            await self.projects.activate(a.task_id, self.event(a))
            self.resume(a)
            self.assertEqual(Control.control(self.latest(a))['journal'][-1]['status'], 'completed')
            self.assertEqual(len(self.calls), 1)
            self.metrics.update(switch_refused_until_tick_finished=True, completed_evidence_retained=True,
                                dispatched_action_not_replayed=True)
        finally:
            release.set()
            self.owner._running_ticks.discard(tick_key)
            await asyncio.gather(pending, return_exceptions=True)

    async def test_real_submit_plan_default_stage_checkpoint_and_archive(self):
        task, _ = self.create('默认阶段从真实submit_plan生成')
        steps = [{'id': 'read', 'title': '研究', 'instruction': '读离线资料'},
                 {'id': 'verify', 'title': '核对', 'instruction': '核对资料结论'}]
        await self.plan(task, steps, propose=True)
        stages = [r['stage'] for r in Control.control(self.latest(task))['steps']]
        self.metrics['submitted_default_stages'] = stages
        self.metrics['expected_default_stages'] = ['task_execution', 'task_execution']
        checkpoint = actual_checkpoint_method()
        source = self.workspace/'readme.md'
        source.write_text(('offline stage evidence，离线资料。'*80+'\n')*30, encoding='utf-8')
        read_result = await self.invoke(task, 'astrbot_file_read_tool', {'path': str(source), 'limit': 20})
        evidence = [r['id'] for r in Control.control(self.latest(task))['journal']]
        await checkpoint(self.owner, self.event(task), 'read', '第一步研究已完成，下一步核对。', json.dumps(evidence), True)
        first_reason = C.lane_state(self.latest(task)).get('pending_reason')
        self.metrics['handoff_reason_after_first_step'] = first_reason
        with self.subTest(check='real_submit_plan_defaults'):
            self.assertEqual(stages, ['task_execution', 'task_execution'])
        with self.subTest(check='no_per_step_handoff'):
            self.assertIsNone(first_reason)
        task = self.resume(task, 'verify')
        await self.invoke(task, 'astrbot_file_read_tool', {'path': str(source), 'offset': 0, 'limit': 20})
        evidence = [r['id'] for r in Control.control(self.latest(task))['journal'] if r['step_id'] == 'verify']
        authored_message = '资料已核对，原始证据保留在本任务中；下一步归档。'
        optional = {'message': authored_message} if 'message' in inspect.signature(checkpoint).parameters else {}
        before_provider = len(self.provider.calls)
        await checkpoint(self.owner, self.event(task), 'verify', '阶段核对已完成，原证据可回查。', json.dumps(evidence), True, **optional)
        self.metrics['checkpoint_message_supported'] = bool(optional)
        if optional:
            self.assertEqual(Control.control(self.latest(task))['stage_deliveries'][-1]['text'], authored_message)
            self.assertTrue(any(authored_message in message['text'] for message in self.sent))
            self.assertEqual(len(self.provider.calls), before_provider, 'stage delivery should not generate another model request')
            self.metrics['stage_delivery_extra_model_calls'] = 0
        latest = self.latest(task)
        self.assertEqual(C.lane_state(latest)['pending_reason'], 'stage_completed')
        history = [{'role': 'user', 'content': '请研究离线资料并核对'},
                   {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'offline-read', 'type': 'function',
                     'function': {'name': 'astrbot_file_read_tool', 'arguments': json.dumps({'path': str(source), 'limit': 20})}}]},
                   {'role': 'tool', 'tool_call_id': 'offline-read', 'content': read_result},
                   {'role': 'user', 'content': '下一阶段确认归档'}]
        reduced = await C.TaskContinuity(self.owner).compact(self.event(task), latest, history, self.provider, 'stage_completed')
        lane = C.lane_state(self.latest(task))
        saved = self.storage._read_json(self.storage.root/lane['record_path'])
        self.assertEqual(saved['history'], history)
        self.assertEqual(saved['status'], 'saved')
        self.assertTrue(reduced[0]['content'].startswith(C.MARKER))
        self.assertEqual(reduced[-len(history):], history, 'the recent working window must remain intact')
        C.message_groups(reduced)  # Retained calls and results must still form complete groups.
        self.assertLessEqual(len(lane['summary']), saved['summary_limit'])
        self.assertLess(C.estimate(reduced),
                        C.context_capacity(latest, self.provider) * C.settings(latest)['context_percent'] // 100)
        handoff_calls = [r for r in self.provider.calls if r['phase'] == 'handoff']
        self.assertEqual(len(handoff_calls), 1, 'compaction uses one summary request, not checkpoint text as a substitute')
        self.assertEqual(saved['model_calls'], 1)
        self.assertEqual(saved['summary'], lane['summary'])
        self.assertFalse(any(r['status'] != 'completed' for r in Control.control(self.latest(task))['steps']))
        detail = await self.projects.detail(task.task_id)
        for row in detail['files']:
            self.assertEqual(row['chars'], len((self.storage.root/row['path']).read_text(encoding='utf-8')))
        self.metrics.update(raw_context_chars=len(U.encoded(history)), reduced_context_chars=len(U.encoded(reduced)),
                            summary_chars=len(lane['summary']), handoff_source_chars=saved['source_chars'],
                            summary_limit=saved['summary_limit'], handoff_model_calls=len(handoff_calls),
                            reported_record_chars=detail['record_chars'], message_kinds=[r.get('kind') for r in detail['messages']])
        ended = await self.projects.administrator_end(task.task_id, 'completed', '全部离线阶段完成，原记录与证据已归档。', 'offline-admin')
        self.assertIsNone(self.storage.load_active_task(task.umo))
        self.assertTrue(Path(ended.archive_path).exists())
        with self.assertRaises(ValueError):
            await self.projects.activate(task.task_id, self.event(task))

    async def test_rejected_approval_then_revised_plan(self):
        task, _ = self.create('审批拒绝后改方案')
        await self.plan(task)
        target = self.workspace/'keep.txt'
        await self.invoke(task, 'astrbot_file_write_tool', {'path': str(target), 'content': 'keep original'})
        arguments = {'command': 'rm ' + shlex.quote(str(target))}
        self.bridge.request_batch(self.event(task), [{'tool_name': 'astrbot_execute_shell', 'arguments': arguments}],
                                  '主动申请删除旧成果', '一个明确文件', '保留原文件副本')
        self.assertEqual(len(self.calls), 1)
        row = self.decision(task, False)
        self.assertEqual(row['decision'], 'rejected')
        self.resume(task)
        before = len(self.calls)
        with self.assertRaisesRegex(ValueError, '已经被拒绝'):
            await self.invoke(task, 'astrbot_execute_shell', arguments)
        self.assertEqual(len(self.calls), before)
        self.provider.responses.append(json.dumps({'routine': True, 'reason': '保留原文件，改为生成新文件并核对，不扩大范围。'}, ensure_ascii=False))
        await self.owner.task_control.submit_plan(self.event(task), json.dumps({'steps': [
            {'id': 'one', 'title': '保留原件另建副本', 'instruction': '保留keep.txt，生成替代成果'}],
            'change_reason': '管理员拒绝删除，改为保留原件'}, ensure_ascii=False))
        task = self.resume(task, 'one')
        alternative = self.workspace/'alternative.txt'
        await self.invoke(task, 'astrbot_file_write_tool', {'path': str(alternative), 'content': 'new approach'})
        self.checkpoint(task, 'one', '原文件保留，替代方案已写入独立成果。')
        self.assertEqual(target.read_text(encoding='utf-8'), 'keep original')
        self.assertEqual(alternative.read_text(encoding='utf-8'), 'new approach')
        self.assertEqual(Control.control(self.latest(task))['version'], 2)
        self.assertEqual(self.latest(task).approvals[-1]['status'], 'rejected')
        self.metrics.update(rejected_action_executor_calls=0, revised_plan_version=2, original_file_preserved=True)

    async def test_approved_batch_executes_once_and_results_reusable(self):
        task, _ = self.create('审批批次只执行一次')
        await self.plan(task)
        target = self.workspace/'approved.txt'
        args = {'path': str(target), 'content': 'approved content'}
        self.bridge.request_batch(self.event(task), [{'tool_name': 'astrbot_file_write_tool', 'arguments': args}],
                                  '明确批次模拟', '一个临时文件', '删除临时文件')
        self.decision(task, True)
        self.assertTrue(await self.bridge.resume_batch(self.event(task), self.latest(task)))
        self.assertEqual(target.read_text(encoding='utf-8'), 'approved content')
        target.write_text('administrator edit after approved execution', encoding='utf-8')
        after_approved = file_snapshot(self.workspace)
        journal = deepcopy(Control.control(self.latest(task))['journal'])
        self.assertTrue(await self.bridge.resume_batch(self.event(task), self.latest(task)))
        result = await self.invoke(task, 'astrbot_file_write_tool', args)
        self.assertIn('written approved.txt', result)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(file_snapshot(self.workspace), after_approved, 'replay must preserve later administrator edits')
        self.assertEqual(Control.control(self.latest(task))['journal'], journal)
        self.assertEqual(self.latest(task).approvals[-1]['status'], 'consumed')
        self.metrics.update(batch_replays=0, consumed_approvals=1, administrator_edit_retained=True)

    async def test_stop_before_late_tool_and_summary_callbacks(self):
        task, _ = self.create('停止后晚工具回调')
        await self.plan(task)
        entered, release = asyncio.Event(), asyncio.Event()
        async def delayed(tool, context, args):
            entered.set()
            await release.wait()
        self.tool_hook = delayed
        late = asyncio.create_task(self.invoke(task, 'astrbot_file_write_tool',
                                  {'path': str(self.workspace/'already_dispatched.txt'), 'content': 'inflight side effect'}))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            stale = deepcopy(self.latest(task))
            ended = await self.projects.administrator_end(task.task_id, 'cancelled', '管理员已停止；在途动作需核对。', 'offline-admin')
            archived_before = file_snapshot(self.storage.archives_dir)
            release.set()
            await asyncio.wait_for(late, 2)
            stale.status = 'running'
            self.storage.save_task(stale)
            self.storage.archive_task(stale)
            self.assertEqual(file_snapshot(self.storage.archives_dir), archived_before)
            self.assertEqual(self.latest(task).status, 'cancelled')
            self.assertIsNone(self.storage.load_active_task(task.umo))
            with self.assertRaises(B.ExecutionStopped):
                await self.invoke(task, 'astrbot_file_write_tool', {'path': str(self.workspace/'post_stop.txt'), 'content': 'blocked'})
            self.assertFalse((self.workspace/'post_stop.txt').exists())
            self.assertTrue(Path(ended.archive_path).exists())
            self.metrics.update(terminal_archive_unchanged=True, terminal_pointer_absent=True,
                                dispatched_side_effect_exists=(self.workspace/'already_dispatched.txt').exists(),
                                archived_journal_statuses=[r['status'] for r in Control.control(self.latest(task))['journal']])
        finally:
            release.set()
            await asyncio.gather(late, return_exceptions=True)
        # A summary request stopped while awaiting a provider must retain its
        # durable source and may not attach a late summary to a terminal task.
        other, _ = self.create('停止后晚总结回调', 'qq-b')
        await self.plan(other)
        async def stopped_summary(**kwargs):
            await self.projects.administrator_end(other.task_id, 'cancelled', '总结期间停止', 'offline-admin')
            return S(completion_text='晚到总结不应重新激活任务')
        history = [{'role': 'user', 'content': 'retain source after cancellation'}]
        with self.assertRaises(C.HandoffError):
            await C.TaskContinuity(self.owner).compact(self.event(other), self.latest(other), history,
                                                       S(text_chat=stopped_summary), 'context_capacity')
        self.assertEqual(self.latest(other).status, 'cancelled')
        self.assertFalse(C.lane_state(self.latest(other)).get('record_id'))
        drafts = list(C.TaskContinuity(self.owner).directory(other).glob('handoff_*.json'))
        self.assertEqual(len(drafts), 1)
        self.assertEqual(self.storage._read_json(drafts[0])['history'], history)
        self.metrics['late_summary_source_retained'] = True

    async def test_cleanup_preview_tokens_all_scopes_and_source_isolation(self):
        a, pa = self.create('清理A')
        await self.plan(a)
        b, pb = self.create('清理B', 'qq-b')
        await self.plan(b)
        source = self.workspace/'preserved.py'
        source.write_text('VALUE = 1\n', encoding='utf-8')
        before_source = file_snapshot(self.workspace)
        for task in (a, b):
            self.storage.append_task_memory_observation(task, {'output': '离线临时日志'*300})
            self.projects.save_summary(task.task_id, 'SUMMARY_' + task.umo)
            cid = next(iter(self.projects.conversation_ids(task)))
            self.fixture.db.rows[cid] = S(user_id=task.umo, content=[{'role': 'user', 'content': task.root_goal}])
        self.fixture.db.rows['ordinary-daily'] = S(user_id=a.umo, content=[{'content': 'daily untouched'}])
        with self.assertRaises(ValueError):
            await self.projects.cleanup_plan(pa['project_id'], mode='cache')
        for task in (a, b):
            await self.projects.pause_execution(task)
        plan = await self.projects.cleanup_plan(pa['project_id'], a.task_id, 'cache')
        for invalid in ('', 'invalid', (await self.projects.cleanup_plan(pb['project_id'], mode='cache'))['token']):
            with self.assertRaises(ValueError):
                await self.projects.cleanup(pa['project_id'], a.task_id, 'cache', invalid)
        self.assertEqual(self.fixture.db.deleted, [])
        self.storage.append_task_memory_observation(a, {'output': 'added after preview'})
        with self.assertRaises(ValueError):
            await self.projects.cleanup(pa['project_id'], a.task_id, 'cache', plan['token'])
        fresh = await self.projects.cleanup_plan(pa['project_id'], a.task_id, 'cache')
        cache = await self.projects.cleanup(pa['project_id'], a.task_id, 'cache', fresh['token'])
        self.assertTrue(Control.control(self.latest(a))['steps'])
        self.assertIn('SUMMARY_', self.projects.filtered_context(self.latest(a)))
        self.assertIn('ordinary-daily', self.fixture.db.rows)
        self.assertIn(next(iter(self.projects.conversation_ids(b))), self.fixture.db.rows)
        self.assertEqual(cache['native_conversations'], 1)
        history = await self.projects.cleanup_plan(pa['project_id'], a.task_id, 'history')
        with self.assertRaises(ValueError):
            await self.projects.cleanup(pa['project_id'], a.task_id, 'history', fresh['token'])
        result = await self.projects.cleanup(pa['project_id'], a.task_id, 'history', history['token'])
        with self.assertRaises(ValueError):
            self.projects.get_task(a.task_id)
        self.assertEqual(self.latest(b).task_id, b.task_id)
        self.assertEqual(self.projects.project(pa['project_id'])['project_id'], pa['project_id'])
        # Replaying a cleanup token against the new state must fail.
        with self.assertRaises(ValueError):
            await self.projects.cleanup(pa['project_id'], a.task_id, 'history', history['token'])
        empty = await self.projects.cleanup_plan(pa['project_id'], mode='project')
        await self.projects.cleanup(pa['project_id'], '', 'project', empty['token'])
        with self.assertRaises(ValueError):
            self.projects.project(pa['project_id'])
        self.assertEqual(file_snapshot(self.workspace), before_source)
        self.metrics.update(invalid_or_stale_tokens_rejected=7, cache_cleanup=cache, history_cleanup=result,
                            project_record_removed=True, other_source_and_daily_preserved=True,
                            source_tree_preserved=True)

    async def test_cleanup_preview_invalidates_on_native_history_and_project_changes(self):
        task, project = self.create('清理预览变更检测')
        await self.plan(task)
        await self.projects.pause_execution(task)
        cid = next(iter(self.projects.conversation_ids(task)))
        self.fixture.db.rows[cid] = S(user_id=task.umo, content=[{'content': 'version one'}])
        rejected = []
        for mutation in ('native_history', 'project_settings', 'task_state'):
            plan = await self.projects.cleanup_plan(project['project_id'], mode='history')
            if mutation == 'native_history':
                self.fixture.db.rows[cid].content.append({'content': 'late history'})
            elif mutation == 'project_settings':
                self.projects.update(project['project_id'], {'share_with_daily': True})
            else:
                latest = self.latest(task)
                latest.current_summary = 'checkpoint changed after preview'
                self.storage.save_task(latest)
            with self.assertRaises(ValueError):
                await self.projects.cleanup(project['project_id'], '', 'history', plan['token'])
            rejected.append(mutation)
        self.assertEqual(self.fixture.db.deleted, [])
        self.assertTrue(self.storage.task_path(task.umo, task.task_id).exists())
        self.metrics['token_invalidated_by'] = rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, default=REPORT)
    parser.add_argument('--no-report', action='store_true')
    args, unittest_args = parser.parse_known_args()
    # Restrict the only persistent output to the file authorized for this task.
    if args.report.resolve() != REPORT.resolve():
        parser.error('report output is restricted to docs/validation/v0.4.0-project-scenarios.json')
    RESULTS.clear()
    start_hashes = fingerprint_sources()
    started = time.perf_counter()
    program = unittest.main(argv=[sys.argv[0], *unittest_args], exit=False, verbosity=2)
    result = program.result
    end_hashes = fingerprint_sources()
    failures = [{'test': str(test), 'traceback': trace} for test, trace in [*result.failures, *result.errors]]
    for row in RESULTS:
        matches = [f for f in failures if row['scenario'] in f['test']]
        row['status'] = 'failed' if matches else 'passed'
        if matches:
            row['failures'] = matches
    report = {
        'schema_version': 1, 'generated_at': datetime.now(timezone.utc).isoformat(),
        'target_release': 'v0.4.0', 'metadata_at_run': (F.ROOT/'metadata.yaml').read_text(encoding='utf-8'),
        'command': 'python scripts/ui/test_agent_project_scenarios.py',
        'python': platform.python_version(), 'platform': platform.system(),
        'scope': 'offline end-to-end simulation of real functions; not a running AstrBot or real model test',
        'fakes': ['AstrBot executor (temporary files)', 'provider (scripted responses)', 'conversation DB (memory)',
                  'message transport (memory)', 'tool budget callbacks (counting only)'],
        'measurement_notes': {
            'chars': 'Python Unicode code points; task storage files include duplicated canonical/active/archive representations',
            'tokens': 'request byte-length estimates only; no real provider usage, cost or billing claimed',
            'time': 'perf_counter wall time on this machine; deterministic fixtures, not production performance',
            'document_no_writes': 'workspace contents unchanged; lifecycle metadata and evidence are intentionally stored in temporary task data',
            'stop': 'already-dispatched fake tool may finish its side effect; terminal archive and pointer must stay fenced',
            'plan_approval': 'real TaskControl.approval with synthetic administrator status transition; no live main._resolve_approval',
        },
        'summary': {'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                    'passed': sum(r['status'] == 'passed' for r in RESULTS), 'successful': result.wasSuccessful(),
                    'elapsed_ms': round((time.perf_counter()-started)*1000, 3)},
        'source_sha256_at_start': start_hashes, 'source_sha256_at_end': end_hashes,
        'concurrent_source_changes': [p for p in start_hashes if start_hashes[p] != end_hashes.get(p)],
        'scenarios': RESULTS, 'failures': failures,
    }
    if not args.no_report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        print('Report: ' + str(args.report))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
