"""Focused regressions for visual controls, evidence-based finish and cheaper rounds."""
import ast
import importlib
import json
import sys
import unittest
from copy import deepcopy
from types import SimpleNamespace as S
from unittest.mock import patch

import test_project_runtime as F

Control, Models, ROOT = F.Control, F.Models, F.ROOT
Verifier = importlib.import_module('review_agent_lab.verifier').AgentVerifier
Bridge = importlib.import_module('review_agent_lab.astrbot_bridge')
Policy = importlib.import_module('review_agent_lab.policy').PermissionPolicy
Identity = importlib.import_module('review_agent_lab.bot_identity')


def actual_method(name, **namespace):
    tree = ast.parse((ROOT / 'main.py').read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    method.decorator_list = []
    namespace.update(TaskState=Models.TaskState, AgentSpec=Models.AgentSpec, AstrMessageEvent=object,
                     task_control=Control.control, now_iso=Models.now_iso)
    exec(compile(ast.Module(body=[method], type_ignores=[]), '<actual-method>', 'exec'), namespace)
    return namespace[name]


class SchemeFinishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = F.ProjectRuntime(); self.f.setUp()
        self.owner, self.storage = self.f.owner, self.f.storage

    def tearDown(self):
        self.f.tearDown()

    def finished(self):
        task, _ = self.f.task(status='running')
        task.completion_conditions = ['通过 JSON 与 JS 语法及基础挂载逻辑校验', '生成模块且声明完整']
        state = Control.control(task)
        state.update(current_step_id='one', authorization_version=1)
        state['steps'][0].update(status='completed', summary='模块文件和配置已写入，ESM挂载与node语法检查均正常。', evidence=['call_ok'])
        state['journal'] = [dict(id='call_ok', name='astrbot_execute_shell', status='completed', step_id='one',
                                authorization_version=1, step_revision=0, result='exit_code=0\n全部自检正常')]
        self.storage.save_task(task)
        return task

    def test_finish_uses_valid_all_step_evidence_not_chinese_phrase_match(self):
        task = self.finished()
        verdict = Verifier().verify_finish(task, status='completed', final_summary='老爸，监工台做好啦，文件和自检都齐了。')
        self.assertTrue(verdict.passed, verdict)
        self.assertTrue(Verifier().verify_validation_checkpoint(task).passed)
        self.assertIn('exit_code=0', Verifier()._finish_evidence_text(task))
        for change in ['failed', 'unknown', 'stale', 'unlinked']:
            copy = deepcopy(task); state = Control.control(copy)
            if change in {'failed', 'unknown'}: state['journal'][0]['status'] = change
            elif change == 'stale': state['journal'][0]['step_revision'] = 3
            else: state['steps'][0]['evidence'] = ['does_not_exist']
            with self.subTest(change=change):
                self.assertFalse(Verifier().verify_finish(copy, status='completed', final_summary='全部完成').passed)

    async def test_missing_evidence_returns_to_ai_without_auto_approval(self):
        task = self.finished(); Control.control(task)['journal'][0]['status'] = 'failed'; self.storage.save_task(task)
        self.owner._approved_finish_override = lambda *args: None
        self.owner.verifier = Verifier()
        self.owner.agent_runtime = S(record_verdict=lambda *args, **kwargs: None)
        result = await actual_method('_finish_task')(self.owner, self.f.event(task.umo), 'completed', '做好了', '')
        self.assertIn('补齐证据', result)
        saved = self.storage.load_active_task(task.umo)
        self.assertEqual(saved.status, 'running'); self.assertEqual(saved.approvals, [])
        self.owner._normalize_agent_workflow = lambda spec:None
        self.owner._ensure_workflow_data = lambda task:task.workflow_data
        direct = await actual_method('_archive_task_direct')(self.owner, saved, Models.AgentSpec(),
                        status='completed', final_summary='做完了')
        self.assertIn('补齐证据',direct)
        self.assertEqual(self.storage.load_active_task(task.umo).approvals,[])

    async def test_approval_decision_is_not_erased_by_archive(self):
        task = self.finished()
        task.approvals = [dict(approval_id='plan', status='approved', approval_type='task_plan', resolved_by='123'),
                          dict(approval_id='finish', status='approved', approval_type='finish_override'),
                          dict(approval_id='queued', status='approved', approval_type='tool_batch', calls=[{'status':'queued'}]),
                          dict(approval_id='pending', status='pending', approval_type='operation')]
        self.storage.save_task(task)
        ended = await self.f.projects.administrator_end(task.task_id, 'completed', '按现状交付', '123')
        rows = {r['approval_id']:r for r in ended.approvals}
        self.assertEqual(rows['plan']['status'], 'consumed'); self.assertEqual(rows['finish']['status'], 'consumed')
        self.assertEqual(rows['plan']['decision'], 'approved'); self.assertEqual(rows['queued']['decision'], 'approved')
        self.assertEqual(rows['queued']['calls'][0]['status'], 'cancelled')
        self.assertEqual(rows['pending']['status'], 'expired')

    def test_disabled_tool_survives_full_access_and_model_round_trip(self):
        spec = Models.AgentSpec.from_dict({'disabled_tools':['astrbot_sandboxed_shell'], 'isolation_policy':{'tool_mode':'full'}})
        spec = Models.AgentSpec.from_dict(spec.to_dict())
        self.assertFalse(Policy.tool_allowed_by_agent_profile(spec, 'astrbot_execute_shell', '__none__'))
        self.assertTrue(Policy.tool_allowed_by_agent_profile(spec, 'astrbot_file_read_tool', '__none__'))

    def test_round_limit_is_separate_from_host_steps(self):
        task, _ = self.f.task(); method = actual_method('_configure_task_budget', native_steps=lambda *args:80)
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,24)
        Control.control(task)['execution_settings'] = {'round_tool_limit':12}
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,12)
        settings = importlib.import_module('review_agent_lab.execution_settings')
        self.assertEqual(settings.normalize({})['round_tool_limit'],24)

    async def test_duplicate_reads_reuse_until_a_write_and_outputs_are_bounded(self):
        from mcp.types import CallToolResult, TextContent
        task, _ = self.f.task(status='running'); state = Control.control(task)
        state.update(current_step_id='one',execution_settings={'mode':'full','roots':['/project']});self.storage.save_task(task)
        event = self.f.event(task.umo); event.get_extra = lambda key,default=None:'round_test' if key=='agent_lab_round_id' else default
        tools = {name:S(name=name,description='') for name in ['astrbot_file_read_tool','astrbot_file_write_tool','astrbot_execute_shell']}
        bridge = Bridge.AstrBotBridge(self.owner);bridge.tool=lambda name,event=None:tools[name]
        bridge.execution_context=lambda event:self.owner.context
        self.owner._tool_allowed_by_agent_profile=self.owner._tool_available_for_agent=lambda *args:True
        self.owner._disabled_plugin_names=lambda *args:[]
        self.owner._effective_tool_risk=self.owner._infer_tool_risk=lambda *args:'work'
        self.owner._budget_remaining_tools=lambda task:24
        self.owner._consume_tool_budget=lambda *args:''
        self.owner._cfg_value=lambda key,default:default
        calls=[]
        async def execute(tool,context,**args):
            calls.append(tool.name);yield CallToolResult(content=[TextContent(type='text',text='body'*3000)])
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute))}
        with patch.dict(sys.modules,modules):
            first=await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':'/project/app.css'},native=True)
            self.assertLess(len(first[0].content[0].text),8500)
            second=await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':'/project/app.css'})
            self.assertIn('没有再次执行',second);self.assertLess(len(second),1800)
            self.assertEqual(len(calls),1)
            await bridge.invoke(event,tools['astrbot_file_write_tool'],{'path':'/project/app.css','content':'changed'})
            await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':'/project/app.css'})
            self.assertEqual(len(calls),3)
            for _ in range(3):
                with self.assertRaises(Bridge.OperationBlocked):
                    await bridge.invoke(event,tools['astrbot_execute_shell'],{'command':'ls "$MOD_DIR"'})
            saved=self.storage.load_active_task(task.umo)
            self.assertEqual(saved.status,'running')
            self.assertNotIn('guard_refusals',Control.control(saved))

    async def test_delivery_preserves_original_voice_without_second_model(self):
        task=self.finished();summary='笨蛋老爸，监工台搞定啦，语法和挂载都测过了。'
        Summarizer=importlib.import_module('review_agent_lab.summarizer').AgentSummarizer
        self.assertEqual(await Summarizer(S()).summarize_exit(self.f.event(task.umo),task,summary),summary)

    async def test_approval_summary_inherits_source_persona(self):
        task=self.finished();request=[]
        async def cid(umo):return 'daily'
        async def conv(*args):return S(persona_id='mo')
        async def persona(**kwargs):return 'mo',{'name':'小莫','prompt':'亲昵地叫管理员老爸，直接说人话。'},None,False
        async def provider(umo):return 'model'
        async def generate(**kwargs):request.append(kwargs);return S(completion_text='老爸，我得动一下授权范围外的配置，点头后再做，备份留好了。')
        self.owner.context.conversation_manager.get_curr_conversation_id=cid
        self.owner.context.conversation_manager.get_conversation=conv
        self.owner.context.persona_manager=S(resolve_selected_persona=persona)
        self.owner.context.get_current_chat_provider_id=provider
        self.owner.context.llm_generate=generate
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        result=await Messages(self.owner).approval_summary(task,{'approval_id':'a','reason':'需要越界'})
        self.assertIn('老爸',result);self.assertIn('亲昵',request[0]['system_prompt']);self.assertIn('不要求动作/对象',request[0]['system_prompt'])

    def test_host_skills_ignore_legacy_scheme_switch(self):
        modules={'astrbot.core.skills.skill_manager':S(SkillManager=lambda:S(list_skills=lambda **kw:[S(name='active'),S(name='other')]),build_skills_prompt=lambda rows:','.join(s.name for s in rows)),
                 'astrbot.core.astr_main_agent':S(_filter_skills_for_current_config=lambda rows,cfg:rows)}
        with patch.dict(sys.modules,modules):
            self.assertEqual(Identity.host_skills_prompt(S(),{}, {'skills':['active']}),'active')
            self.assertEqual(Identity.host_skills_prompt(S(),{}, {'skills':[]}),'')

    def test_shell_variables_are_expanded_before_scope_checks(self):
        permissions=importlib.import_module('review_agent_lab.task_permissions')
        state={'execution_settings':{'mode':'full','roots':['/project']},'execution_cwd':'/host/workspace'}
        for command in ['MOD_DIR=/project/modules; ls "$MOD_DIR"',
                        'export MOD_DIR=/project/modules && find "${MOD_DIR}" -maxdepth 2 -type f',
                        'MOD_DIR=/project; cat "$MOD_DIR/page.js"',
                        'find /project/modules -name "*.json" -maxdepth 2']:
            with self.subTest(command=command):
                self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':command},state)[0],'allow')
        reason,_=permissions.full_guard('astrbot_execute_shell',{'command':'find "$MOD_DIR" -type f'},state)
        self.assertTrue(reason.startswith(permissions.UNRESOLVED_PATH_REASON),reason)
        self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':'MOD_DIR=/outside; ls "$MOD_DIR"'},state)[0],'review')
        self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':'ls "$MOD_DIR"','env':{'MOD_DIR':'/project'}},state)[0],'allow')

    def test_ungrouped_checkpoints_do_not_force_a_handoff(self):
        continuity=importlib.import_module('review_agent_lab.continuity')
        task=self.finished();state=Control.control(task)
        state['steps'][0]['status']='running'
        state['steps'].append(dict(id='two',title='Next',instruction='next',status='pending',evidence=[]))
        self.storage.save_task(task)
        stage=continuity.stage_of(task)
        self.owner.task_control.checkpoint(self.f.event(task.umo),'one','校验通过','["call_ok"]',True)
        saved=self.storage.load_active_task(task.umo)
        self.assertNotIn('pending_reason',continuity.lane_state(saved))
        Control.control(saved)['current_step_id']='two'
        self.assertEqual(continuity.stage_of(saved),stage)
        Control.control(saved).setdefault('continuity',{}).setdefault('lanes',{}).setdefault('',{})['summary']='交接记录：配置齐全，ESM自检正常'
        self.assertIn('交接记录',Verifier()._finish_evidence_text(saved))


if __name__=='__main__':unittest.main()
