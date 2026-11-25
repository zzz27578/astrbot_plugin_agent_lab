"""Small regression batch for full-access policy and approval continuation."""
import ast
import asyncio
import importlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import test_project_runtime as Fixture
from test_project_runtime import Control, Models, ROOT

Permissions = importlib.import_module('review_agent_lab.task_permissions')
Commands = importlib.import_module('review_agent_lab.task_commands')
Bridge = importlib.import_module('review_agent_lab.astrbot_bridge')


class FullPolicyTests(unittest.TestCase):
    def test_regular_work_and_small_cleanup_need_no_review(self):
        state = {'execution_settings': {'mode': 'full', 'roots': ['/project']}}
        for name, args in [
            ('astrbot_execute_shell', {'command': 'ls /project && ls /project/modules 2>/dev/null || true'}),
            ('astrbot_execute_shell', {'command': 'find /project -maxdepth 2 -type f'}),
            ('astrbot_execute_shell', {'command': 'mkdir /project/modules/new && printf ok > /project/modules/new/page.js'}),
            ('astrbot_execute_shell', {'command': 'rm -f /project/a.tmp /project/b.tmp'}),
            ('astrbot_execute_shell', {'command': 'echo "DROP DATABASE is documentation" > /project/readme.md'}),
            ('astrbot_execute_shell', {'command': 'rm /project/*.tmp'}),
            ('astrbot_execute_shell', {'command': "find /project -name '*.tmp' -delete"}),
            ('astrbot_execute_python', {'code': "from pathlib import Path; Path('/project/page.js').write_text('https://example.com')"}),
            ('astrbot_file_write_tool', {'path': '/project/page.js', 'content': 'DROP DATABASE is documentation'}),
        ]:
            with self.subTest(args=args):
                self.assertEqual(Permissions.assess(name, args, state, risk='high')[0], 'allow')

    def test_guard_refuses_explicit_escape_and_catastrophic_actions(self):
        state = {'execution_settings': {'mode': 'full', 'roots': ['/project']}, 'execution_cwd': '/project'}
        for command in ['ls /outside', 'cat ../secret.txt', 'rm -rf /project', 'rm -rf /project/modules',
                        'rm -f /project/*', 'rm -rf .', 'find /project -delete',
                        'git reset --hard', 'mysql -e "DROP DATABASE prod"',
                        'pwd\nrm -rf /project', "python -c \"import os; os.system('rm -rf /project')\""]:
            with self.subTest(command=command):
                self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': command}, state)[0], 'review')
        for args in [{'code': "import shutil; shutil.rmtree('/project/modules')"},
                     {'code': "from pathlib import Path\nfor p in Path('/project').glob('*'): p.unlink()"},
                     {'code': "from pathlib import Path; Path('/outside/x').write_text('a')"}]:
            self.assertEqual(Permissions.assess('astrbot_execute_python', args, state)[0], 'review')
        self.assertEqual(Permissions.assess('astrbot_file_read_tool', {'path': '/dev/null'}, state)[0], 'review')
        windows = {'execution_settings': {'mode': 'full', 'roots': ['C:\\project']}}
        self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': r'del /q C:\project\one.tmp'}, windows)[0], 'allow')
        self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': r'rd /s /q C:\project'}, windows)[0], 'review')

    def test_authority_and_other_modes_stay_distinct(self):
        state = {'execution_settings': {'mode': 'full'}, 'approved_version': 2, 'version': 2,
                 'authorized_scope_roots': ['/project'], 'scope_roots': ['/project', '/outside']}
        self.assertEqual(Permissions.authorized_roots(state), ['/project'])
        self.assertEqual(Permissions.assess('astrbot_file_write_tool', {'path': '/outside/x'}, state)[0], 'review')
        for mode, expected in [('standard', 'allow'), ('readonly', 'allow'), ('full', 'allow')]:
            self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': 'ls /project && ls /project/modules'},
                             {'execution_settings': {'mode': mode, 'roots': ['/project']}})[0], expected)
        self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': 'python -m pytest'},
                         {'execution_settings': {'mode': 'readonly', 'roots': ['/project']}})[0], 'deny')
        settings = importlib.import_module('review_agent_lab.execution_settings')
        for root in ['relative/path', '/project/*']:
            with self.assertRaises(ValueError):
                settings.normalize({'mode': 'full', 'roots': [root]})

    def test_direct_stop_commands_and_quoted_discussions(self):
        for text in ['停止任务', '停止当前任务！', '请立即停止任务。', '结束任务', '任务终止']:
            self.assertEqual(Commands.task_command(text), 'stop')
        for text in ['不要停止任务', '停止任务是什么意思？', '文档里写“停止任务”', '如果出错就停止任务']:
            self.assertEqual(Commands.task_command(text), '')
        self.assertEqual(Commands.task_command('按现状交付'), 'deliver')


class FullRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = Fixture.ProjectRuntime()
        self.fixture.setUp()
        self.owner = self.fixture.owner
        self.storage = self.fixture.storage

    def tearDown(self):
        self.fixture.tearDown()

    def bridge_fixture(self, output='command completed'):
        from mcp.types import CallToolResult, TextContent
        task, _ = self.fixture.task(status='running')
        Control.control(task).update(current_step_id='one', execution_settings={'mode': 'full', 'roots': ['/project']})
        self.storage.save_task(task)
        event = self.fixture.event(task.umo)
        event.get_extra = lambda k, default=None: default
        tools = {name: S(name=name, description='') for name in ('astrbot_execute_shell', 'astrbot_file_read_tool')}
        tool = tools['astrbot_execute_shell']
        bridge = Bridge.AstrBotBridge(self.owner)
        bridge.tool = lambda name, event=None: tools.get(name)
        bridge.execution_context = lambda event: self.owner.context
        self.owner._tool_allowed_by_agent_profile = self.owner._tool_available_for_agent = lambda *args: True
        self.owner._disabled_plugin_names = lambda *args: []
        self.owner._effective_tool_risk = self.owner._infer_tool_risk = lambda *args: 'high'
        self.owner._cfg_value = lambda k, default: default
        self.owner._budget_remaining_tools = lambda task: 8
        self.owner._consume_tool_budget = lambda *args: ''
        calls = []
        async def execute(tool, context, **args):
            calls.append(args)
            result = Path(args['path']).read_text(encoding='utf-8') if tool.name == 'astrbot_file_read_tool' else output
            yield CallToolResult(content=[TextContent(type='text', text=result)])
        modules = {'astrbot.core.astr_agent_context': S(AstrAgentContext=S, AgentContextWrapper=S),
                   'astrbot.core.astr_agent_tool_exec': S(FunctionToolExecutor=S(execute=execute))}
        return task, event, tools, bridge, calls, modules

    async def test_guard_does_not_send_card_and_approved_result_is_reused_without_execution(self):
        output = 'first\n' + 'a' * 40000 + '\nlast directory'
        task, event, tools, bridge, calls, modules = self.bridge_fixture(output)
        tool = tools['astrbot_execute_shell']
        with patch.dict(__import__('sys').modules, modules):
            visible = await bridge.invoke(event, tool, {'command': 'ls /project && ls /project/modules'})
            first = Control.control(self.storage.load_active_task(task.umo))['journal'][-1]
            first_path = (self.storage.root / first['result_path']).resolve()
            self.assertTrue(first_path.is_file())
            self.assertEqual(first_path.read_text(encoding='utf-8'), output)
            self.assertIn(str(first_path), visible)
            await bridge.invoke(event, tool, {'command': 'rm /project/a.tmp /project/b.tmp'})
            with self.assertRaises(Bridge.OperationBlocked):
                await bridge.invoke(event, tool, {'command': 'rm -rf /project'})
            task = self.storage.load_active_task(task.umo)
            self.assertEqual(task.status, 'running')
            self.assertEqual(task.approvals, [])
            args = {'command': 'ls /outside'}
            bridge.request_batch(event, [{'tool_name': tool.name, 'arguments': args}], '需要外部目录', '只读查看', '')
            task = self.storage.load_active_task(task.umo)
            task.status = 'running'; task.approvals[-1]['status'] = 'approved'
            self.storage.save_task(task)
            self.assertTrue(await bridge.resume_batch(event, task))
            reused = await bridge.invoke(event, tool, args)
            self.assertEqual(len(calls), 3)
            self.assertIn('last directory', reused)
            task = self.storage.load_active_task(task.umo)
            journal = Control.control(task)['journal'][-1]
            self.assertEqual(journal['status'], 'completed')
            self.assertEqual(journal['result_chars'], len(output))
            plan_prompt = Control.prompt(task)
            plan = json.loads(plan_prompt.split(']\n', 1)[1])
            self.assertNotIn('recent_tool_evidence', plan)
            self.assertNotIn('agent_lab_read_tool_evidence', plan_prompt)
            recent = plan['recent_tools'][-1]
            self.assertEqual(recent['arguments'], args)
            self.assertEqual(recent['result_path'], journal['result_path'])
            self.assertLessEqual(len(recent['result']), 600)
            archived_path = (self.storage.root / journal['result_path']).resolve()
            self.assertTrue(archived_path.is_relative_to(self.storage.task_memory_dir(task.umo, task.task_id).resolve()))
            self.assertEqual(archived_path.read_text(encoding='utf-8'), output)
            self.assertEqual(task.approvals[-1]['status'], 'consumed')
            # The same native file tool used for source files reads the archive.
            await bridge.invoke(event, tools['astrbot_file_read_tool'], {'path': str(archived_path)})
            self.assertEqual(calls[-1], {'path': str(archived_path)})
            self.assertEqual(len(calls), 4)
            archive_read = Control.control(self.storage.load_active_task(task.umo))['journal'][-1]
            self.assertEqual(archive_read['status'], 'completed')
            self.assertEqual((self.storage.root / archive_read['result_path']).read_text(encoding='utf-8'), output)

    async def test_three_different_dangerous_refusals_do_not_pause_or_execute(self):
        task, event, tools, bridge, calls, modules = self.bridge_fixture()
        with patch.dict(__import__('sys').modules, modules):
            for command in ['rm -rf /project', 'ls /outside/changed', 'cat /project/.env']:
                with self.assertRaises(Bridge.OperationBlocked):
                    await bridge.invoke(event, tools['astrbot_execute_shell'], {'command': command})
                current = self.storage.load_active_task(task.umo)
                self.assertEqual(current.status, 'running')
                self.assertFalse(current.pending_approvals())
                self.assertEqual(Control.control(current)['journal'][-1]['status'], 'failed')
            current = self.storage.load_active_task(task.umo)
            self.assertEqual(Control.control(current)['guard_refusals']['count'], 3)
            self.assertEqual(current.workflow_data['progress_guard']['failure_ticks'], 1)
            self.assertEqual(calls, [])

    async def test_equivalent_refusals_warn_before_pausing_and_administrator_can_resume(self):
        task, event, tools, bridge, calls, modules = self.bridge_fixture()
        tool = tools['astrbot_execute_shell']
        with patch.dict(__import__('sys').modules, modules):
            for attempt in range(1, 6):
                expected = Bridge.ExecutionStopped if attempt == 5 else Bridge.OperationBlocked
                with self.assertRaises(expected) as caught:
                    await bridge.invoke(event, tool, {'command': 'rm -rf /project'})
                current = self.storage.load_active_task(task.umo)
                self.assertEqual(current.status, 'paused' if attempt == 5 else 'running')
                self.assertFalse(current.pending_approvals())
                if attempt == 3:
                    self.assertEqual(current.workflow_data['progress_guard']['decision'], 'warning')
                    self.assertIn('调整参数或换一种方法', str(caught.exception))
                if attempt == 4:
                    self.assertEqual(current.workflow_data['progress_guard']['decision'], 'observed')
                    self.assertNotIn('调整参数或换一种方法', str(caught.exception))
            task = self.storage.load_active_task(task.umo)
            self.assertEqual(task.wait.wait_reason, 'repeated_tool_error')
            self.assertEqual(Control.control(task)['guard_refusals']['count'], 5)
            self.assertEqual(len([log for log in task.progress_log if log['kind'] == 'liveness_warning']), 1)
            self.assertEqual(calls, [])
            self.assertFalse(self.owner.task_control.ready(task))
            # A further dispatch is stopped before it can execute.
            with self.assertRaises(Bridge.ExecutionStopped):
                await bridge.invoke(event, tool, {'command': 'ls /project'})
            self.assertEqual(calls, [])
            resume = Fixture.actual_method('_handle_command')
            self.owner._total_budget_reason = lambda task: ''
            with patch.object(self.owner.task_control, 'schedule', lambda event: None):
                await resume(self.owner, event, 'resume')
            resumed = self.storage.load_active_task(task.umo)
            self.assertEqual(resumed.status, 'running')
            self.assertNotIn('guard_refusals', Control.control(resumed))
            self.assertNotIn('progress_guard', resumed.workflow_data)

    async def test_successful_tool_interrupts_equivalent_refusal_streak(self):
        task, event, tools, bridge, calls, modules = self.bridge_fixture()
        tool = tools['astrbot_execute_shell']
        with patch.dict(__import__('sys').modules, modules):
            for _ in range(2):
                for _ in range(3):
                    with self.assertRaises(Bridge.OperationBlocked):
                        await bridge.invoke(event, tool, {'command': 'rm -rf /project'})
                current = self.storage.load_active_task(task.umo)
                self.assertEqual(current.status, 'running')
                self.assertEqual(current.workflow_data['progress_guard']['decision'], 'warning')
                await bridge.invoke(event, tool, {'command': 'ls /project'})
                current = self.storage.load_active_task(task.umo)
                self.assertEqual(current.workflow_data['progress_guard']['failure_ticks'], 0)
                self.assertEqual(current.status, 'running')
            with self.assertRaises(Bridge.OperationBlocked):
                await bridge.invoke(event, tool, {'command': 'rm -rf /project'})
            current = self.storage.load_active_task(task.umo)
            self.assertEqual(current.workflow_data['progress_guard']['failure_ticks'], 1)
            self.assertEqual(Control.control(current)['guard_refusals']['count'], 7)
            self.assertEqual(current.status, 'running')
            self.assertEqual(len(calls), 2)

    async def test_project_policy_refresh_clears_only_legacy_auto_cards(self):
        task, project = self.fixture.task(status='running')
        task.status = 'paused'
        task.set_wait(wait_reason='need_approval', source='tool_dispatch', message='old')
        row = Models.ApprovalRequest(operation='old', reason='执行前风险检查', approval_type='tool_batch').to_dict()
        task.approvals.append(row)
        task.budget.tokens_used = 999
        self.storage.save_task(task)
        self.fixture.projects.update(project['project_id'], {'execution_settings': {'mode': 'full', 'roots': ['/project']}})
        self.assertTrue(self.owner.task_control.refresh_execution_settings(task))
        self.assertEqual(task.status, 'running')
        self.assertEqual(task.approvals[-1]['status'], 'expired')
        self.assertEqual(task.budget.tokens_used, 999)
        task.approvals.append(Models.ApprovalRequest(operation='user', reason='AI主动申请', approval_type='tool_batch').to_dict())
        self.owner.task_control.refresh_execution_settings(task)
        self.assertEqual(task.approvals[-1]['status'], 'pending')

    async def test_canvas_external_work_uses_full_policy_without_auto_card(self):
        policy = importlib.import_module('review_agent_lab.node_policy')
        NodeResult = importlib.import_module('review_agent_lab.node_runtime').NodeExecutionResult
        task, _ = self.fixture.task(status='running')
        Control.control(task)['execution_settings'] = {'mode': 'full', 'roots': ['/project']}
        self.storage.save_task(task)
        async def execute(ctx): return NodeResult(outcome='done')
        self.owner.node_executors = S(execute=execute)
        ctx = S(task=task, event=self.fixture.event(task.umo), node={'action': 'call_api', 'title': 'registered API'})
        result = await policy.execute_with_policy(self.owner, ctx)
        self.assertTrue(result.ok)
        self.assertEqual(task.approvals, [])

    async def test_control_tool_requires_current_administrator_instruction(self):
        tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
        method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == 'agent_lab_control_task')
        method.decorator_list = []
        ns = {'AstrMessageEvent': object, 'task_command': Commands.task_command}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-control-tool>', 'exec'), ns)
        calls = []
        async def act(event, action): calls.append(action); return 'done'
        self.owner._administrator_task_control = act
        event = S(message_str='停止当前任务！', get_extra=lambda k, default=None: default)
        self.assertEqual(await ns[method.name](self.owner, event, 'stop'), 'done')
        event.get_extra = lambda k, default=None: True
        await ns[method.name](self.owner, event, 'stop')
        event.get_extra = lambda k, default=None: default
        event.message_str = '请写代码'
        await ns[method.name](self.owner, event, 'stop')
        self.assertEqual(calls, ['stop'])


if __name__ == '__main__':
    unittest.main()
