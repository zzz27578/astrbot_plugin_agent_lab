"""v0.4 delivery, native tool output and permission boundaries."""
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


actual_method = F.actual_method


class SchemeFinishTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = F.ProjectRuntime(); self.f.setUp()
        self.owner, self.storage = self.f.owner, self.f.storage

    def tearDown(self):
        self.f.tearDown()

    def test_ast_method_resolution_includes_canvas_mixin_and_shared_constants(self):
        task, _ = self.f.task()
        task.workflow_data['variables'] = {'result': {'value': 42}}
        method = actual_method('_workflow_variable',
                               resolve_path=importlib.import_module('review_agent_lab.conditions').resolve_path)
        self.owner._ensure_workflow_data = lambda task: task.workflow_data
        self.assertEqual(method(self.owner, task, 'result.value'), 42)
        self.assertEqual(method(self.owner, task, 'missing', 'fallback'), 'fallback')
        self.assertEqual(method.__globals__['CUSTOM_API_TOOL_NAME'], 'agent_lab_call_custom_api')

    def finished(self):
        task, _ = self.f.task(status='running')
        task.completion_conditions = ['通过 JSON 与 JS 语法及基础挂载逻辑校验', '生成模块且声明完整']
        state = Control.control(task)
        state.update(current_step_id='one', authorization_version=1)
        state['steps'][0].update(status='completed', summary='模块文件和配置已写入，ESM挂载与node语法检查均正常。', evidence=[])
        state['journal'] = [dict(id='call_ok', name='astrbot_execute_shell', status='completed', step_id='one',
                                authorization_version=1, step_revision=0,
                                arguments={'command':'node --check module.js'}, result='exit_code=0\n全部自检正常')]
        self.storage.save_task(task)
        return task

    def test_finish_uses_real_journal_without_manual_step_citations(self):
        task = self.finished()
        verdict = Verifier().verify_finish(task, status='completed', final_summary='老爸，监工台做好啦，文件和自检都齐了。')
        self.assertTrue(verdict.passed, verdict)
        self.assertTrue(Verifier().verify_validation_checkpoint(task).passed)
        self.assertIn('exit_code=0', Verifier()._finish_evidence_text(task))
        for change in ['failed', 'unknown', 'stale', 'wrong_authority']:
            copy = deepcopy(task); state = Control.control(copy)
            if change in {'failed', 'unknown'}: state['journal'][0]['status'] = change
            elif change == 'stale': state['journal'][0]['step_revision'] = 3
            else: state['journal'][0]['authorization_version'] = 0
            with self.subTest(change=change):
                self.assertFalse(Verifier().verify_finish(copy, status='completed', final_summary='全部完成').passed)
        Control.control(task)['steps'][0]['evidence'] = ['does_not_exist']
        self.assertTrue(Verifier().verify_finish(task, status='completed', final_summary='实际自检正常。').passed)
        Verifier.link_step_evidence(task)
        self.assertEqual(Control.control(task)['steps'][0]['evidence'], ['call_ok'])

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

    def test_plain_tasks_have_no_fragmenting_round_cap_and_canvas_honors_settings(self):
        task, _ = self.f.task(); method = actual_method('_configure_task_budget', native_steps=lambda *args:80)
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,0)
        Control.control(task)['execution_settings'] = {'round_tool_limit':12}
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,0)
        Control.control(task)['workflow'] = 'selected'
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,12)
        Control.control(task)['execution_settings']['round_tool_limit'] = 200
        method(self.owner, task); self.assertEqual(task.budget.max_tools_per_tick,80)
        settings = importlib.import_module('review_agent_lab.execution_settings')
        self.assertEqual(settings.normalize({})['round_tool_limit'],0)

    async def test_native_reads_remain_verbatim_and_large_output_spills_once(self):
        from mcp.types import CallToolResult, TextContent
        task, _ = self.f.task(status='running'); state = Control.control(task)
        state.update(current_step_id='one',execution_settings={'mode':'full','roots':['/project']});self.storage.save_task(task)
        event = self.f.event(task.umo); event.get_extra = lambda key,default=None:'round_test' if key=='agent_lab_round_id' else default
        tools = {name:S(name=name,description='') for name in ['astrbot_grep_tool','astrbot_file_write_tool','astrbot_execute_shell']}
        bridge = Bridge.AstrBotBridge(self.owner);bridge.tool=lambda name,event=None:tools[name]
        bridge.execution_context=lambda event:self.owner.context
        self.owner._tool_allowed_by_agent_profile=self.owner._tool_available_for_agent=lambda *args:True
        self.owner._disabled_plugin_names=lambda *args:[]
        self.owner._effective_tool_risk=self.owner._infer_tool_risk=lambda *args:'work'
        self.owner._budget_remaining_tools=lambda task:1000
        self.owner._consume_tool_budget=lambda *args:''
        self.owner._cfg_value=lambda key,default:default
        calls=[]; output=['body'*3000]
        async def execute(tool,context,**args):
            calls.append(tool.name);yield CallToolResult(content=[TextContent(type='text',text=output[0])])
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute))}
        with patch.dict(sys.modules,modules):
            first=await bridge.invoke(event,tools['astrbot_grep_tool'],{'path':'/project/app.css','pattern':'button'},native=True)
            self.assertEqual(first[0].content[0].text,output[0])
            second=await bridge.invoke(event,tools['astrbot_grep_tool'],{'path':'/project/app.css','pattern':'button'})
            self.assertEqual(second,output[0]);self.assertEqual(len(calls),2)
            await bridge.invoke(event,tools['astrbot_file_write_tool'],{'path':'/project/app.css','content':'changed'})
            await bridge.invoke(event,tools['astrbot_grep_tool'],{'path':'/project/app.css','pattern':'button'})
            self.assertEqual(len(calls),4)
            output[0]='源码内容\n'*10000
            large=await bridge.invoke(event,tools['astrbot_grep_tool'],{'path':'/project/app.css','pattern':'large'})
            self.assertIn('完整原文：',large)
            self.assertNotIn('证据 ID',large)
            saved=self.storage.load_active_task(task.umo)
            row=Control.control(saved)['journal'][-1]
            full_path=self.storage.root/row['result_path']
            self.assertEqual(full_path.read_text(encoding='utf-8'),output[0])
            self.assertIn(str(full_path),large)
            self.assertEqual(first[0].content[0].text,'body'*3000)
            saved=self.storage.load_active_task(task.umo)
            self.assertEqual(saved.status,'running')
            self.assertEqual(saved.pending_approvals(),[])

    async def test_delivery_preserves_original_voice_without_second_model(self):
        task=self.finished();summary='笨蛋老爸，监工台搞定啦，语法和挂载都测过了。'
        Summarizer=importlib.import_module('review_agent_lab.summarizer').AgentSummarizer
        self.assertEqual(await Summarizer(S()).summarize_exit(self.f.event(task.umo),task,summary),summary)

    async def test_approval_summary_keeps_bot_authored_persona_without_extra_model(self):
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
        authored='老爸，我得动一下授权范围外的配置，点头后再做，备份留好了。'
        result=await Messages(self.owner).approval_summary(task,{'approval_id':'a','reason':'需要越界','message':authored})
        self.assertEqual(result,authored);self.assertEqual(request,[])

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
        self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':'find "$MOD_DIR" -type f'},state)[0],'allow')
        self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':'MOD_DIR=/outside; ls "$MOD_DIR"'},state)[0],'review')
        self.assertEqual(permissions.assess('astrbot_execute_shell',{'command':'ls "$MOD_DIR"','env':{'MOD_DIR':'/project'}},state)[0],'allow')

    def test_ungrouped_checkpoints_do_not_force_a_handoff(self):
        continuity=importlib.import_module('review_agent_lab.continuity')
        task=self.finished();state=Control.control(task)
        state['steps'][0]['status']='running'
        state['steps'].append(dict(id='two',title='Next',instruction='next',status='pending',evidence=[]))
        self.storage.save_task(task)
        stage=continuity.stage_of(task)
        self.owner.task_control.checkpoint(self.f.event(task.umo),'one','校验通过',completed=True)
        saved=self.storage.load_active_task(task.umo)
        self.assertNotIn('pending_reason',continuity.lane_state(saved))
        Control.control(saved)['current_step_id']='two'
        self.assertEqual(continuity.stage_of(saved),stage)
        Control.control(saved).setdefault('continuity',{}).setdefault('lanes',{}).setdefault('',{})['summary']='交接记录：配置齐全，ESM自检正常'
        self.assertIn('交接记录',Verifier()._finish_evidence_text(saved))


if __name__=='__main__':unittest.main()
