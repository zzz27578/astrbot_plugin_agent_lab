"""v0.4 controls against real storage, TaskControl, files and subprocess checks.

No model is called. Owner legacy endpoints are extracted from main.py; only
message transport and terminal orchestration are replaced in adapter tests.
Run: python -B scripts/ui/test_v04_task_tools.py
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import MethodType, SimpleNamespace as S
from unittest.mock import AsyncMock

sys.dont_write_bytecode = True
import test_project_runtime as F

Tools = importlib.import_module('review_agent_lab.task_tools')
Verifier = importlib.import_module('review_agent_lab.verifier').AgentVerifier
Control = F.Control


def legacy(name):
    tree = ast.parse((F.ROOT / 'main.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)
    method.decorator_list = []
    namespace = dict(AstrMessageEvent=object, json=json, ApprovalRequest=F.Models.ApprovalRequest,
                     task_control=Control.control, now_iso=F.Models.now_iso)
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<legacy-owner>', 'exec'), namespace)
    return namespace[name]


class TaskToolsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = F.ProjectRuntime()
        self.fixture.setUp()
        self.owner, self.storage = self.fixture.owner, self.fixture.storage
        self.task, _ = self.fixture.task(status='running')
        state = Control.control(self.task)
        self.workspace = Path(self.fixture.temp.name) / 'workspace'
        self.workspace.mkdir()
        state.update(current_step_id='one', workflow='none', authorization_version=1,
                     scope_roots=[str(self.workspace)], authorized_scope_roots=[str(self.workspace)],
                     constraints=['保留接口'])
        self.storage.save_task(self.task)
        self.event = self.fixture.event(self.task.umo)
        extras = {'agent_lab_plan_version': 1, 'agent_lab_input_revision': 0}
        self.event.get_extra = lambda key, default=None: extras.get(key, default)
        self.event.set_extra = lambda key, value: extras.__setitem__(key, value)
        self.event.role = 'admin'
        self.owner.context.llm_generate = AsyncMock(side_effect=AssertionError('no review model'))
        self.owner.task_messages = S(state=AsyncMock(return_value='已发送任务消息。'),
                                     publish=AsyncMock(return_value='已发送任务消息。'))
        self.owner.astrbot_bridge = S(check=lambda event: self.load(), request_batch=self.request_batch)
        for name in ('agent_lab_progress', 'agent_lab_ask_question', 'agent_lab_request_approval', 'agent_lab_finish'):
            setattr(self.owner, name, MethodType(legacy(name), self.owner))
        self.owner._finish_task = AsyncMock(return_value='archived by owner')
        self.tools = Tools.TaskTools(self.owner)

    def tearDown(self):
        self.fixture.tearDown()

    def load(self):
        return self.storage.load_active_task(self.task.umo)

    def request_batch(self, event, operations, reason, impact, rollback, operation, message):
        task = self.load()
        row = F.Models.ApprovalRequest(operation=operation, reason=reason, impact=impact,
                                      rollback=rollback, message=message, approval_type='tool_batch').to_dict()
        row['calls'] = deepcopy(operations)
        task.approvals.append(row)
        task.status = 'paused'
        self.storage.save_task(task)
        return task.task_id

    async def plan(self, steps, **kwargs):
        return await self.tools.dispatch(self.event, 'task_plan', dict(steps_json=json.dumps(steps, ensure_ascii=False), **kwargs))

    def record(self, name, arguments, result, status='completed', **extra):
        task = self.load()
        state = Control.control(task)
        row = dict(id=f"call_{len(state['journal'])+1}", name=name, arguments=arguments, result=result,
                   status=status, authorization_version=state['authorization_version'],
                   plan_version=state['version'], step_id=state.get('current_step_id', ''), step_revision=0)
        row.update(extra)
        state['journal'].append(row)
        self.storage.save_task(task)
        return row

    def verdict(self, summary='已完成资料核对，说明已整理。'):
        return Verifier().verify_finish(self.load(), status='completed', final_summary=summary)

    async def complete(self):
        await self.plan([{'id': 'one', 'title': '完成实际工作'}], completed_step='one', summary='已整理成果')

    def run_check(self, passed=True):
        marker = self.workspace / 'force-failure'
        if passed:
            marker.unlink(missing_ok=True)
        else:
            marker.write_text('reproduce a failed check', encoding='utf-8')
        command = [sys.executable, '-B', '-c',
                   "from pathlib import Path; assert not Path('force-failure').exists(); assert Path('answer.py').read_text() == 'answer = 42\\n'; print('check passed')"]
        result = subprocess.run(command, cwd=self.workspace, capture_output=True, text=True, timeout=15)
        self.record('astrbot_execute_shell', {'command': subprocess.list2cmdline(command)},
                    json.dumps(dict(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)),
                    'completed' if result.returncode == 0 else 'failed')
        return result

    def write_file(self):
        path = self.workspace / 'answer.py'
        path.write_text('answer = 42\n', encoding='utf-8')
        self.record('astrbot_file_write_tool', {'path': str(path), 'content': path.read_text()}, 'written')
        return path

    def test_five_schemas_match_dispatch_signatures(self):
        self.assertEqual(Tools.CONTROL_TOOL_NAMES,
                         {'task_plan', 'task_progress', 'task_ask', 'task_approve', 'task_finish'})
        self.assertEqual(len(Tools.TASK_TOOL_SCHEMAS), 5)
        for definition in Tools.TASK_TOOL_SCHEMAS:
            schema = definition['function']
            params = inspect.signature(getattr(Tools.TaskTools, schema['name'])).parameters
            visible = {key for key in params if key not in {'self', 'event'}}
            self.assertEqual(set(schema['parameters']['properties']), visible)
            self.assertEqual(set(schema['parameters']['required']),
                             {key for key in visible if params[key].default is inspect.Parameter.empty})
        self.assertNotIn('evidence', json.dumps(Tools.TASK_TOOL_SCHEMAS))
        self.assertLess(len(json.dumps(Tools.TASK_TOOL_SCHEMAS, ensure_ascii=False).encode()), 6000)

    async def test_dispatch_rejects_hidden_tools_and_wrong_arguments(self):
        before = self.load().to_dict()
        for name, args in [('agent_lab_checkpoint', {}), ('task_progress', {}),
                           ('task_progress', {'message': 1}), ('task_plan', {'steps_json': '[]', 'goal': 'changed'})]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                await self.tools.dispatch(self.event, name, args)
        self.assertEqual(self.load().to_dict(), before)

    async def test_initial_plan_requires_administrator_without_calling_model(self):
        task = self.load()
        state = Control.control(task)
        state.update(version=0, approved_version=0, steps=[])
        task.status = 'paused'
        self.storage.save_task(task)
        result = await self.plan(['核对接口', '完成交付'], message='请确认这个计划。')
        current = self.load()
        self.assertIn('等待批准', result)
        self.assertEqual(current.status, 'paused')
        self.assertEqual(current.approvals[-1]['message'], '请确认这个计划。')
        self.assertEqual(current.approvals[-1]['approval_type'], 'task_plan')
        self.owner.context.llm_generate.assert_not_awaited()

    async def test_routine_split_edit_reorder_remove_and_check_do_not_pause(self):
        task = self.load()
        task.budget.tokens_used = 12345
        self.storage.save_task(task)
        await self.complete()
        await self.plan([{'id': 'new', 'title': '补充检查'},
                         {'id': 'one', 'title': '重写已完成项说明', 'status': 'completed'}])
        await self.plan([{'id': 'new', 'title': '合并后的工作', 'status': 'completed'}])
        current = self.load()
        state = Control.control(current)
        self.assertEqual(current.status, 'running')
        self.assertEqual(current.approvals, [])
        self.assertEqual(state['approved_version'], state['version'])
        self.assertEqual(state['authorization_version'], 1)
        self.assertEqual(self.event.get_extra('agent_lab_plan_version'), state['version'])
        self.assertEqual(self.event.get_extra('agent_lab_input_revision'), 0)
        self.assertEqual(current.budget.tokens_used, 12345)
        self.assertNotIn('continuity', state)
        self.assertEqual(state['current_step_id'], '')
        self.assertFalse(self.verdict().passed)
        self.owner.context.llm_generate.assert_not_awaited()

    async def test_goal_scope_constraint_and_budget_expansion_need_approval(self):
        base = self.load()
        proposals = [{'goal': '扩大最终目标'}, {'scope_roots': [str(self.workspace.parent)]},
                     {'scope_roots': [str(self.workspace) + '-other']}, {'scope_roots': [str(self.workspace / '..' / 'outside')]},
                     {'remove_constraints': ['保留接口']}, {'completion_conditions': ['换一个验收条件']},
                     {'budget': {'max_total_tokens': base.budget.max_total_tokens + 10000}}]
        for change in proposals:
            with self.subTest(change=change):
                self.storage.save_task(deepcopy(base))
                await self.plan({'steps': ['继续工作'], **change})
                task = self.load()
                self.assertEqual(task.status, 'paused')
                self.assertEqual(Control.control(task)['approved_version'], 0)
                self.assertEqual(Control.control(task)['authorized_scope_roots'], [str(self.workspace)])
                self.assertEqual(task.root_goal, base.root_goal)
                self.assertEqual(task.budget.max_total_tokens, base.budget.max_total_tokens)
                self.assertEqual(task.approvals[-1]['approval_type'], 'task_plan')
        self.owner.context.llm_generate.assert_not_awaited()

    async def test_scope_narrowing_and_windows_case_do_not_need_approval(self):
        await self.plan({'steps': ['继续工作'], 'scope_roots': [str(self.workspace / 'child')]})
        self.assertEqual(self.load().status, 'running')
        task = self.load()
        state = Control.control(task)
        state.update(scope_roots=['D:\\Project'], authorized_scope_roots=['D:\\Project'])
        self.storage.save_task(task)
        await self.plan({'steps': ['子目录工作'], 'scope_roots': ['d:\\project\\src']})
        self.assertEqual(self.load().status, 'running')

    async def test_human_pause_is_not_cleared_and_cannot_check_steps(self):
        task = self.load()
        task.status = 'paused'
        Control.control(task)['human_paused'] = True
        self.storage.save_task(task)
        with self.assertRaises(ValueError):
            await self.complete()
        self.assertEqual(self.load().status, 'paused')
        self.assertTrue(Control.control(self.load())['human_paused'])

    async def test_legacy_checkpoint_auto_links_without_required_ids(self):
        self.record('astrbot_file_read_tool', {'path': 'source.py'}, 'actual source')
        self.owner.task_control.checkpoint(self.event, 'one', '核对了源码', completed=True)
        self.assertEqual(Control.control(self.load())['steps'][0]['evidence'], ['call_1'])
        self.assertTrue(self.verdict().passed)
        with self.assertRaises(ValueError):
            self.owner.task_control.checkpoint(self.event, 'one', '无效引用', '["invented"]', True)

    async def test_reading_failure_logs_is_a_successful_read(self):
        self.record('astrbot_file_read_tool', {'path': 'error.log'},
                    'Traceback (most recent call last)\nexit_code=1\n{"ok":false}')
        await self.complete()
        self.assertTrue(self.verdict('已分析error.log，错误原因已确认。').passed)

    async def test_final_checks_real_write_and_subprocess_after_last_change(self):
        self.write_file()
        await self.complete()
        summary = '已修改answer.py，实际断言测试通过，无遗留项。'
        self.assertFalse(self.verdict(summary).passed)
        self.assertEqual(self.run_check().returncode, 0)
        self.assertTrue(self.verdict(summary).passed, self.verdict(summary))
        self.assertFalse(self.verdict('测试通过，无遗留项。').passed)
        self.write_file()
        self.assertFalse(self.verdict(summary).passed)
        self.run_check(passed=False)
        self.assertFalse(self.verdict(summary).passed)
        # A real retry of the same command succeeds once the failure is removed.
        successful = self.run_check()
        self.assertEqual(successful.returncode, 0)
        self.assertTrue(self.verdict(summary).passed, self.verdict(summary))

    async def test_empty_steps_reuses_existing_plan_for_completion(self):
        await self.tools.dispatch(self.event, 'task_plan',
                                  {'steps_json': '', 'completed_step': 'one', 'summary': '按现有计划完成此项'})
        self.assertEqual(Control.control(self.load())['steps'][0]['status'], 'completed')
        self.assertEqual(self.load().last_confirmed_progress, '按现有计划完成此项')

    async def test_reused_plan_does_not_reopen_the_step_a_second_time(self):
        await self.plan([{'id': 'one', 'title': '返工检查', 'reopen_reason': '补充情况'}])
        await self.tools.dispatch(self.event, 'task_plan', {'steps_json': '', 'completed_step': 'one'})
        self.assertEqual(Control.control(self.load())['steps'][0]['revision'], 1)

    async def test_checklist_or_report_cannot_forge_execution(self):
        await self.complete()
        self.record('report', {}, '全部通过')
        task = self.load()
        Control.control(task)['steps'][0]['evidence'] = ['fabricated']
        self.storage.save_task(task)
        self.assertFalse(self.verdict('测试通过').passed)
        self.record('astrbot_execute_shell', {'command': 'python -m unittest'}, '{"exit_code": 7}', status='completed')
        self.assertFalse(self.verdict('测试通过').passed)

    async def test_unknown_stale_and_false_test_claims_block_finish(self):
        self.record('astrbot_file_read_tool', {'path': 'source.py'}, 'actual source')
        await self.complete()
        self.assertTrue(self.verdict().passed)
        self.assertFalse(self.verdict('测试已经通过').passed)
        row = self.record('astrbot_execute_shell', {'command': 'python -m unittest'}, '', status='unknown')
        self.assertFalse(self.verdict().passed)
        task = self.load()
        Control.control(task)['journal'][-1]['status'] = 'failed'
        Control.control(task)['journal'][0]['authorization_version'] = 0
        self.storage.save_task(task)
        self.assertFalse(self.verdict().passed)
        self.assertTrue(row['id'])

    async def test_restructured_research_uses_real_journal_without_step_citations(self):
        self.record('astrbot_file_read_tool', {'path': 'research.txt'}, '实际检索结果')
        await self.plan([{'id': 'merged', 'title': '合并研究整理', 'status': 'completed'}])
        self.assertTrue(self.verdict().passed, self.verdict())
        self.assertEqual(Control.control(self.load())['steps'][0]['evidence'], [])

    async def test_progress_question_and_approval_delegate_to_existing_owner(self):
        await self.tools.dispatch(self.event, 'task_progress', {'message': '已经找到原因，正在修复。'})
        self.owner.task_messages.publish.assert_awaited_once_with(
            self.event, self.task.task_id, '已经找到原因，正在修复。', 'progress')
        with self.assertRaises(ValueError):
            await self.tools.dispatch(self.event, 'task_ask', {'question': '选哪种？', 'options_json': '["相同", "相同"]'})
        await self.tools.dispatch(self.event, 'task_ask',
                                  {'question': '先做哪部分？', 'options_json': '["接口", "页面"]', 'recommendation': '建议接口'})
        self.assertEqual(self.load().status, 'paused')
        self.assertEqual(Control.control(self.load())['questions'][0]['recommendation'], '建议接口')
        task = self.load()
        task.status = 'running'
        Control.control(task)['questions'] = []
        self.storage.save_task(task)
        arguments = dict(operation='清理指定目录', reason='移除废弃缓存', impact='指定缓存目录',
                         operations_json='[{"tool_name":"astrbot_execute_shell","arguments":{"command":"remove-cache"}}]',
                         message='请确认这一次清理。')
        await self.tools.dispatch(self.event, 'task_approve', arguments)
        approval = self.load().approvals[-1]
        self.assertEqual(approval['message'], arguments['message'])
        self.assertEqual(approval['calls'][0]['arguments'], {'command': 'remove-cache'})
        self.assertEqual(Control.control(self.load())['journal'], [])

    async def test_finish_delegates_payload_and_persists_automatic_links(self):
        self.record('astrbot_file_read_tool', {'path': 'source.py'}, 'actual source')
        await self.complete()
        payload = dict(final_summary='已核对source.py并整理结果。', memory_candidates='稳定结论', message='工作完成。')
        result = await self.tools.dispatch(self.event, 'task_finish', payload)
        self.assertEqual(result, 'archived by owner')
        self.owner._finish_task.assert_awaited_once_with(self.event, status='completed',
            final_summary=payload['final_summary'], memory_candidates=payload['memory_candidates'])
        self.assertEqual(Control.control(self.load())['steps'][0]['evidence'], ['call_1'])
        self.assertEqual(self.load().workflow_data['delivery_message'], '工作完成。')

    def test_prompt_and_skill_have_one_compact_authority(self):
        text = Control.prompt(self.load())
        for obsolete in ('agent_lab_read_tool_evidence', '24次', '120行', 'agent_lab_checkpoint'):
            self.assertNotIn(obsolete, text)
        self.assertFalse(hasattr(Control.TaskControl, '_review_revision'))
        skill = (F.ROOT / 'skills/agent-mode/SKILL.md').read_text(encoding='utf-8-sig')
        self.assertLessEqual(len(skill.splitlines()), 50)
        self.assertNotIn('优先于旧章节', skill)
        for name in Tools.CONTROL_TOOL_NAMES:
            self.assertIn(name, skill)


if __name__ == '__main__':
    unittest.main(verbosity=2)
