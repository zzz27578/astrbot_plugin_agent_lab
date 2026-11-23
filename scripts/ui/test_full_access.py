"""Small regression batch for full-access policy and approval continuation."""
import ast
import asyncio
import importlib
import json
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
        for mode, expected in [('standard', 'review'), ('readonly', 'deny'), ('full', 'allow')]:
            self.assertEqual(Permissions.assess('astrbot_execute_shell', {'command': 'ls /project && ls /project/modules'},
                             {'execution_settings': {'mode': mode, 'roots': ['/project']}})[0], expected)
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

    async def test_guard_does_not_send_card_and_approval_results_are_readable_once(self):
        from mcp.types import CallToolResult, TextContent
        task, _ = self.fixture.task(status='running')
        Control.control(task).update(current_step_id='one', execution_settings={'mode': 'full', 'roots': ['/project']})
        self.storage.save_task(task)
        event = self.fixture.event(task.umo)
        event.get_extra = lambda k, default=None: default
        tool = S(name='astrbot_execute_shell', description='')
        bridge = Bridge.AstrBotBridge(self.owner)
        bridge.tool = lambda *args: tool
        bridge.execution_context = lambda event: self.owner.context
        self.owner._tool_allowed_by_agent_profile = self.owner._tool_available_for_agent = lambda *args: True
        self.owner._disabled_plugin_names = lambda *args: []
        self.owner._effective_tool_risk = self.owner._infer_tool_risk = lambda *args: 'high'
        self.owner._cfg_value = lambda k, default: default
        self.owner._budget_remaining_tools = lambda task: 8
        self.owner._consume_tool_budget = lambda *args: ''
        calls = []
        output = 'first\n' + 'a' * 13000 + '\nlast directory'
        async def execute(tool, context, **args):
            calls.append(args)
            yield CallToolResult(content=[TextContent(type='text', text=output)])
        modules = {'astrbot.core.astr_agent_context': S(AstrAgentContext=S, AgentContextWrapper=S),
                   'astrbot.core.astr_agent_tool_exec': S(FunctionToolExecutor=S(execute=execute))}
        with patch.dict(__import__('sys').modules, modules):
            await bridge.invoke(event, tool, {'command': 'ls /project && ls /project/modules'})
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
            await bridge.invoke(event, tool, args)
            self.assertEqual(len(calls), 3)
            task = self.storage.load_active_task(task.umo)
            journal = Control.control(task)['journal'][-1]
            self.assertEqual(journal['status'], 'completed')
            self.assertEqual(journal['result_chars'], len(output))
            evidence = json.loads(Control.prompt(task).split(']\n', 1)[1])['recent_tool_evidence'][-1]
            self.assertEqual(evidence['arguments'], args)
            self.assertTrue(evidence['result_truncated'])
            self.assertLessEqual(len(evidence['result']), 600)
            tail = json.loads(bridge.read_evidence(event, journal['id'], 12000))
            self.assertIn('last directory', tail['result'])
            self.assertEqual(tail['total_chars'], len(output))
            self.assertEqual(task.approvals[-1]['status'], 'consumed')
            # Refusals count attempts, not identical strings. An intervening
            # harmless query cannot keep a stubborn model running forever.
            for i, command in enumerate(['rm -rf /project', 'ls /outside/changed', 'rm /project/*']):
                expected = Bridge.ExecutionStopped if i == 2 else Bridge.OperationBlocked
                with self.assertRaises(expected):
                    await bridge.invoke(event, tool, {'command': command})
                if i == 0:
                    await bridge.invoke(event, tool, {'command': 'ls /project'})
            task = self.storage.load_active_task(task.umo)
            self.assertEqual(task.status, 'paused')
            self.assertEqual(task.wait.wait_reason, 'guard_retry_limit')
            self.assertEqual(Control.control(task)['guard_refusals']['count'], 3)
            self.assertFalse(task.pending_approvals())
            self.assertFalse(self.owner.task_control.ready(task))
            # Execute the actual administrator resume branch, without starting
            # a background model loop. It must release this pause and counter.
            tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
            method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == '_handle_command')
            ns = {'AstrMessageEvent': object, 'task_control': Control.control, 'now_iso': Models.now_iso}
            exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-resume>', 'exec'), ns)
            self.owner._total_budget_reason = lambda task: ''
            with patch.object(self.owner.task_control, 'schedule', lambda event: None):
                await ns[method.name](self.owner, event, 'resume')
            resumed = self.storage.load_active_task(task.umo)
            self.assertEqual(resumed.status, 'running')
            self.assertNotIn('guard_refusals', Control.control(resumed))

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
