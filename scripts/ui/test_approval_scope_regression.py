"""Approval/cwd regressions: real ledger and temporary subprocess validation.

Only the host execution boundary is simulated; no production task is resumed.
"""
import asyncio
import copy
import importlib
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

import test_project_runtime as F

B = importlib.import_module('review_agent_lab.astrbot_bridge')
P = importlib.import_module('review_agent_lab.task_permissions')
Runtime = importlib.import_module('review_agent_lab.agent_runtime').AgentRuntime


class ScopeApprovalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from mcp.types import CallToolResult, TextContent
        self.Result, self.Text = CallToolResult, TextContent
        self.f = F.ProjectRuntime(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.owner, self.storage = self.f.owner, self.f.storage
        root = Path(self.f.temp.name)
        self.project, self.cwd = root/'modules'/'supervisor-desk', root/'session-workspace'
        self.project.mkdir(parents=True); self.cwd.mkdir()
        self.task, _ = self.f.task(status='running')
        state = F.Control.control(self.task)
        state.update(current_step_id='one', workflow='none', authorization_version=1,
                     execution_cwd=str(self.cwd), execution_settings={'mode':'full','roots':[str(self.project)]})
        self.storage.save_task(self.task)
        self.event = self.f.event(self.task.umo)
        self.extras = {}; self.event.get_extra = lambda key, default=None: self.extras.get(key, default)
        self.tools = {name:S(name=name,description='') for name in
                      ('astrbot_execute_python','astrbot_execute_shell','astrbot_file_read_tool')}
        self.bridge = B.AstrBotBridge(self.owner)
        self.bridge.tool = lambda name,event=None:self.tools.get(name)
        self.bridge.execution_context = lambda event:self.owner.context
        self.owner._context_config = lambda umo:{'provider_settings':{'computer_use_runtime':'local'}}
        self.owner._tool_allowed_by_agent_profile = self.owner._tool_available_for_agent = lambda *a:True
        self.owner._disabled_plugin_names = lambda *a:[]
        self.owner._effective_tool_risk = self.owner._infer_tool_risk = lambda *a:'high'
        self.owner._budget_remaining_tools = lambda *a:100
        self.owner._consume_tool_budget = lambda *a:''
        self.owner._cfg_value = lambda key,default:default
        self.calls = []; self.result_mode = 'success'
        async def workspace(context):return self.cwd
        async def execute(tool,context,**args):
            self.calls.append((tool.name,copy.deepcopy(args)))
            if self.result_mode == 'exception':
                raise RuntimeError('host executor unavailable after dispatch')
            if self.result_mode == 'empty':
                return
            if self.result_mode == 'error':
                yield self.Result(content=[self.Text(type='text',text='host: Node executable is missing')],isError=True)
            elif self.result_mode == 'subprocess':
                process = await asyncio.create_subprocess_exec(sys.executable,'-c',args['code'],cwd=str(self.cwd),
                                                               stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                out,err = await asyncio.wait_for(process.communicate(),10)
                yield self.Result(content=[self.Text(type='text',text=json.dumps(
                    {'exit_code':process.returncode,'stdout':out.decode(),'stderr':err.decode()}))],isError=process.returncode != 0)
            else:
                yield self.Result(content=[self.Text(type='text',text='validation passed')])
        self.modules = {
            'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
            'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute)),
            'astrbot.core.tools.computer_tools.util':S(workspace_root_for_context=workspace)}
        self.addCleanup(patch.stopall)
        patch.dict(sys.modules,self.modules).start()

    def current(self):return self.storage.load_active_task(self.task.umo)

    def approve(self,args,name='astrbot_execute_python',second=None):
        operations = [{'tool_name':name,'arguments':args}]
        if second:operations.append({'tool_name':name,'arguments':second})
        self.bridge.request_batch(self.event,operations,'Run explicit validation','Only the saved call','')
        task = self.current(); task.approvals[-1]['status']='approved';task.status='running'
        self.storage.save_task(task)
        return task

    async def test_inherited_cwd_is_resolution_base_not_access_target(self):
        target = str(self.project/'page.js')
        python = {'code':f"import subprocess; subprocess.run(['node','--check',{target!r}],check=True)"}
        shell = {'command':subprocess.list2cmdline(['node','--check',target])}
        self.assertEqual(P.assess('astrbot_execute_python',python,F.Control.control(self.current()))[0],'allow')
        for name,args in [('astrbot_execute_python',python),('astrbot_execute_shell',shell)]:
            result=await self.bridge.invoke(self.event,self.tools[name],args,native=True)
            self.assertFalse(result[0].isError)
        self.assertEqual(len(self.calls),2)
        self.assertFalse(self.current().approvals)

    async def test_explicit_cwd_and_actual_relative_targets_still_checked(self):
        state=F.Control.control(self.current())
        for code in [f"import subprocess; subprocess.run(['node','--check',{str(self.project/'page.js')!r}],cwd={str(self.cwd)!r})",
                     "import subprocess; subprocess.run(['cat','./outside.txt'])",
                     "from pathlib import Path; Path('./outside.txt').write_text('bad')",
                     "import subprocess; subprocess.run(['rm','-rf','.'])"]:
            with self.subTest(code=code):
                self.assertEqual(P.assess('astrbot_execute_python',{'code':code},state)[0],'review')
        task=self.current();F.Control.control(task)['execution_settings']['mode']='standard';self.storage.save_task(task)
        with self.assertRaises(B.OperationBlocked):
            await self.bridge.invoke(self.event,self.tools['astrbot_execute_shell'],{'command':'cat ./outside.txt'})
        self.assertEqual(self.calls,[])

    async def test_approved_exact_call_skips_scope_assessment_and_runs_once(self):
        args={'code':f"open({str(self.cwd/'outside.txt')!r}).read()"}
        approved=self.approve(args)
        with (patch.object(B,'assess',side_effect=AssertionError('approved call assessed twice')),
              patch.object(B,'full_guard',side_effect=AssertionError('approved call guarded twice'))):
            self.assertTrue(await self.bridge.resume_batch(self.event,approved))
            self.assertTrue(await self.bridge.resume_batch(self.event,self.current()))
            result=await self.bridge.invoke(self.event,self.tools['astrbot_execute_python'],args,native=True)
            self.assertFalse(result[0].isError)
        task=self.current();state=F.Control.control(task)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(state['execution_settings']['roots'],[str(self.project)])
        self.assertFalse(state.get('scope_notices'))
        call=task.approvals[-1]['calls'][0]
        self.assertEqual(call['execution_status'],'completed')
        self.assertTrue((self.storage.root/call['result_path']).is_file())
        with self.assertRaises(B.OperationBlocked):
            await self.bridge.invoke(self.event,self.tools['astrbot_execute_python'],
                                     {'code':f"open({str(self.cwd/'different.txt')!r}).read()"})
        self.assertEqual(len(self.calls),1)

    async def test_authority_or_input_changes_expire_saved_grant(self):
        for field in ['input_revision','authorization_version','current_step_id']:
            with self.subTest(field=field):
                task=self.current();task.status='running';task.approvals=[];self.storage.save_task(task)
                approved=self.approve({'code':'print(1)'})
                state=F.Control.control(approved);state[field]='other' if field=='current_step_id' else 20
                self.storage.save_task(approved)
                self.assertFalse(await self.bridge.resume_batch(self.event,approved))
                self.assertEqual(self.current().wait.wait_reason,'approval_changed')
        self.assertEqual(self.calls,[])

    async def test_readonly_budget_disabled_tool_and_admin_pause_still_win(self):
        approved=self.approve({'code':'print(1)'})
        F.Control.control(approved)['execution_settings']['mode']='readonly';self.storage.save_task(approved)
        self.assertFalse(await self.bridge.resume_batch(self.event,approved))
        self.assertIn('只读',self.current().wait.message)
        for kind in ['budget','tool_disabled','pause']:
            task=self.current();task.approvals=[];task.status='running'
            F.Control.control(task)['execution_settings']['mode']='full';self.storage.save_task(task)
            approved=self.approve({'code':'print(1)'})
            if kind=='budget':approved.budget.max_total_tool_calls=approved.budget.tool_calls_used=1
            if kind=='pause':approved.status='paused';F.Control.control(approved)['human_paused']=True
            self.storage.save_task(approved)
            with patch.object(self.owner,'_tool_available_for_agent',return_value=kind!='tool_disabled'):
                with self.assertRaises(B.ExecutionStopped):
                    await self.bridge.resume_batch(self.event,approved)
            self.assertEqual(self.calls,[])
            approved=self.current();approved.budget.max_total_tool_calls=0
            F.Control.control(approved)['human_paused']=False;self.storage.save_task(approved)

    async def test_host_error_is_persisted_and_remaining_batch_is_not_run(self):
        self.result_mode='error';approved=self.approve({'code':'print(1)'},second={'code':'print(2)'})
        self.assertFalse(await self.bridge.resume_batch(self.event,approved))
        task=self.current();failure=F.Control.control(task)['last_batch_failure']
        self.assertEqual(failure['phase'],'tool_result')
        self.assertIn('Node executable is missing',task.wait.message)
        self.assertIn('Node executable is missing',(self.storage.root/failure['result_path']).read_text(encoding='utf-8'))
        self.assertEqual(len(self.calls),1)
        self.assertEqual(task.approvals[-1]['calls'][1]['status'],'queued')

    async def test_context_setup_error_has_a_durable_failure_record(self):
        approved=self.approve({'code':'print(1)'})
        def broken(**kwargs):raise RuntimeError('invalid host execution context')
        with patch.dict(sys.modules,{'astrbot.core.astr_agent_context':S(AstrAgentContext=broken,AgentContextWrapper=S)}):
            self.assertFalse(await self.bridge.resume_batch(self.event,approved))
        task=self.current();row=F.Control.control(task)['journal'][-1]
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['failure_phase'],'context_setup')
        self.assertIn('invalid host execution context',(self.storage.root/row['result_path']).read_text(encoding='utf-8'))
        self.assertEqual(self.calls,[])

    async def test_empty_executor_result_is_reported_without_losing_approval(self):
        self.result_mode='empty';approved=self.approve({'code':'print(1)'})
        self.assertFalse(await self.bridge.resume_batch(self.event,approved))
        task=self.current();failure=F.Control.control(task)['last_batch_failure']
        self.assertEqual(failure['phase'],'no_result')
        self.assertTrue((self.storage.root/failure['result_path']).is_file())
        self.assertEqual(task.approvals[-1]['status'],'consumed')

    async def test_execution_exception_is_unknown_and_never_automatically_replayed(self):
        self.result_mode='exception';approved=self.approve({'code':'print(1)'})
        self.assertFalse(await self.bridge.resume_batch(self.event,approved))
        task=self.current();self.assertEqual(task.wait.wait_reason,'batch_result_unknown')
        self.assertEqual(F.Control.control(task)['journal'][-1]['status'],'unknown')
        task.status='running';self.storage.save_task(task)
        await self.bridge.resume_batch(self.event,task)
        with self.assertRaises(B.ExecutionStopped):
            await self.bridge.invoke(self.event,self.tools['astrbot_execute_python'],{'code':'print(1)'})
        self.assertEqual(len(self.calls),1)

    async def test_real_node_syntax_and_in_memory_mount_run_from_unlisted_workspace(self):
        if not shutil.which('node'):self.skipTest('Node executable unavailable')
        target=self.project/'page.js'
        target.write_text("function mount(root) { root.textContent = 'ready'; }\nmodule.exports = {mount};\n",encoding='utf-8')
        script="const assert=require('node:assert');const {mount}=require("+json.dumps(str(target))+ ");const root={};mount(root);assert.equal(root.textContent,'ready');console.log('MOUNT_PASS');"
        code=("import subprocess\n"+f"subprocess.run(['node','--check',{str(target)!r}],check=True)\n"
              +f"subprocess.run(['node','-e',{script!r}],check=True)\n")
        self.result_mode='subprocess'
        result=await self.bridge.invoke(self.event,self.tools['astrbot_execute_python'],{'code':code},native=True)
        self.assertFalse(result[0].isError,result)
        self.assertIn('MOUNT_PASS',result[0].content[0].text)
        self.assertFalse(self.current().approvals)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(list(self.cwd.iterdir()))

    def test_plain_runtime_is_a_projection_of_real_checklist(self):
        task=self.current();state=F.Control.control(task)
        state['steps']=[{'id':'one','title':'Inspect','status':'completed'},
                        {'id':'two','title':'Edit','status':'completed'},
                        {'id':'three','title':'Verify','status':'running'}]
        state['current_step_id']='three'
        runtime=Runtime();spec=F.Models.AgentSpec();spec.workflow_nodes=[]
        for _ in range(4):runtime.sync(task,spec)
        summary=runtime.summary(task)
        self.assertEqual(summary['step_count'],3)
        self.assertEqual(summary['current_node_id'],'three')
        self.assertEqual([s['status'] for s in summary['steps']],['done','done','running'])
        self.assertFalse(any('initialized with 0' in row.get('message','') for row in task.progress_log))
        state['steps'][2]['status']='completed';runtime.update_resume(task)
        self.assertEqual(runtime.summary(task)['steps'][-1]['status'],'done')
        self.assertEqual(state['steps'][2]['status'],'completed')

    def test_partial_edit_guidance_is_advice_and_preserves_five_tools(self):
        runner = importlib.import_module('review_agent_lab.runtime_runner').AgentRuntimeRunner(self.owner)
        system,_ = runner._task_prompts(self.current(),F.Models.AgentSpec(),'test')
        self.assertIn('astrbot_file_edit_tool',system)
        self.assertIn('新建文件或确需整体重构',system)
        self.assertIn('task_plan',system)
        self.assertNotIn('120行',system)
        self.assertNotIn('read_tool_evidence',system)

    def test_predispatch_error_does_not_borrow_another_calls_result(self):
        task=self.current();state=F.Control.control(task)
        state['journal'].append({'id':'call_earlier','approval_id':'approval_batch',
                                 'name':'astrbot_execute_python','arguments':{'code':'print(1)'},
                                 'status':'completed','result_path':'previous-success.txt'})
        self.bridge.record_batch_failure(task,'approval_batch','astrbot_execute_python',
                                         {'code':'print(2)'},'The second call is disabled')
        failure=F.Control.control(self.current())['last_batch_failure']
        self.assertEqual(failure['result_path'],'')
        self.assertEqual(failure['phase'],'dispatch_check')
        self.assertIn('second call',failure['detail'])

    def test_usage_exposes_large_write_arguments_without_rewriting_history(self):
        metrics=importlib.import_module('review_agent_lab.usage_metrics')
        source='const line = 1;\n'*7000
        arguments=json.dumps({'path':'page.js','content':source})
        payload={'system_prompt':'Persona and task rules','prompt':'Validate the file',
                 'contexts':[{'role':'assistant','tool_calls':[{'id':'native_call',
                              'function':{'name':'astrbot_file_write_tool','arguments':arguments}}]}]}
        before=copy.deepcopy(payload)
        sizes=metrics.request_size(payload,payload)
        self.assertEqual(sizes['file_write_content_chars'],len(source))
        self.assertEqual(sizes['tool_call_argument_chars'],len(arguments))
        self.assertEqual(sizes['system_chars'],len(payload['system_prompt']))
        self.assertEqual(payload,before)


if __name__=='__main__':unittest.main(verbosity=2)
