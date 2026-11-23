"""Root regressions: overlap reads, model-facing history and bounded handoffs."""
import ast
import asyncio
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

import test_project_runtime as F

V = importlib.import_module('review_agent_lab.context_views')
C = importlib.import_module('review_agent_lab.continuity')
B = importlib.import_module('review_agent_lab.astrbot_bridge')
R = importlib.import_module('review_agent_lab.read_cache')
Control = F.Control


def big_history():
    history = [{'role':'user', 'content':'优化监工台，不修改官方模块。'}]
    for i in range(15):
        history.extend([{'role':'assistant', 'content':[{'type':'think','think':'private '*700,'encrypted':'signature '*500}],
                         'tool_calls':[{'id':f't{i}', 'function':{'name':'astrbot_file_read_tool','arguments':json.dumps({'path':'/project/page.js','offset':i*60,'limit':350})}}]},
                        {'role':'tool','tool_call_id':f't{i}', 'content':('function source() { return true; }\n'*240)+f'\n[任务工具证据 ID: call_{i}; status=completed]'}])
    history.extend([{'role':'assistant','content':'修改文件', 'tool_calls':[{'id':'edit','function':{'name':'astrbot_file_edit_tool','arguments':json.dumps({'path':'/project/page.js','old':'a'*10000,'new':'b'*12000})}}]},
                    {'role':'tool','tool_call_id':'edit','content':'文件已修改，证据call_edit'}])
    return history


class ContextEconomyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=F.ProjectRuntime();self.f.setUp()
        self.owner,self.storage=self.f.owner,self.f.storage

    def tearDown(self):self.f.tearDown()

    def task(self):
        task,_=self.f.task(status='running');Control.control(task)['current_step_id']='one';self.storage.save_task(task);return task

    def test_views_remove_source_bloat_and_preserve_signed_protocol(self):
        history=big_history();original=deepcopy(history)
        summary=V.history_view(history,for_summary=True)
        provider=V.history_view(history)
        self.assertEqual(history,original)
        self.assertNotIn('signature ',json.dumps(summary))
        self.assertNotIn('private ',json.dumps(summary))
        self.assertLess(len(json.dumps(summary)),len(json.dumps(history))*.12)
        self.assertEqual(provider[1]['content'][0],history[1]['content'][0])
        self.assertEqual(provider[1]['tool_calls'],history[1]['tool_calls'])
        self.assertLess(len(json.dumps(provider)),len(json.dumps(history))*.7)
        self.assertLess(len(provider[-2]['tool_calls'][0]['function']['arguments']),1000)
        self.assertEqual([r.get('tool_call_id') for r in provider if r['role']=='tool'],[r.get('tool_call_id') for r in history if r['role']=='tool'])
        signed=deepcopy(history[-2]);signed['content']=[{'type':'think','think':'preserve','encrypted':'sig'}]
        self.assertEqual(V.history_view([signed,history[-1]])[0]['tool_calls'],signed['tool_calls'])

    def test_state_and_plan_never_repeat_full_edit_arguments(self):
        task=self.task();state=Control.control(task)
        state['journal']=[dict(id=f'call_{i}',name='astrbot_file_edit_tool',arguments={'path':'/project/page.js','old':'X'*20000,'new':'Y'*20000},status='completed',result='edited') for i in range(8)]
        state['steps'][0]['summary']='已修改一部分，未验证'
        text=V.state_summary(task)
        self.assertLess(len(text),4000)
        self.assertLess(len(Control.prompt(task)),10000)
        self.assertNotIn('X'*100,text)
        self.assertEqual(state['journal'][0]['arguments']['old'],'X'*20000)

    async def test_overlapping_and_cross_round_reads_only_execute_missing_lines(self):
        from mcp.types import CallToolResult,TextContent
        task=self.task();directory=Path(self.f.temp.name);file=directory/'page.js'
        file.write_text(''.join(f'line {i}\n' for i in range(400)),encoding='utf-8')
        cfg={'provider_settings':{'computer_use_runtime':'local'}}
        self.owner._context_config=lambda *args:cfg
        Control.control(task)['execution_settings']={'mode':'full','roots':[str(directory)]};self.storage.save_task(task)
        extras={'agent_lab_round_id':'r1'};event=self.f.event(task.umo);event.get_extra=lambda key,default=None:extras.get(key,default)
        bridge=B.AstrBotBridge(self.owner);tool=S(name='astrbot_file_read_tool',description='read file')
        bridge.tool=lambda *args:tool;bridge.execution_context=lambda event:self.owner.context
        self.owner._tool_allowed_by_agent_profile=self.owner._tool_available_for_agent=lambda *args:True
        self.owner._disabled_plugin_names=lambda *args:[]
        self.owner._effective_tool_risk=self.owner._infer_tool_risk=lambda *args:'work'
        self.owner._budget_remaining_tools=lambda task:24;self.owner._consume_tool_budget=lambda *args:''
        self.owner._cfg_value=lambda key,default:default
        calls=[]
        async def workspace(context):return directory
        async def execute(tool,context,**args):
            calls.append(args)
            lines=file.read_text(encoding='utf-8').splitlines(keepends=True)
            yield CallToolResult(content=[TextContent(type='text',text=''.join(lines[args['offset']:args['offset']+args['limit']]))])
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute)),
                 'astrbot.core.tools.computer_tools.util':S(workspace_root_for_context=workspace)}
        with patch.dict(sys.modules,modules):
            await bridge.invoke(event,tool,{'path':str(file),'offset':0,'limit':100})
            result=await bridge.invoke(event,tool,{'path':str(file),'offset':70,'limit':50})
            self.assertEqual([(r['offset'],r['limit']) for r in calls],[(0,100),(100,20)])
            self.assertIn('line 70\n',result);self.assertIn('line 119\n',result)
            extras['agent_lab_round_id']='r2'
            await bridge.invoke(event,tool,{'path':str(file),'offset':10,'limit':20})
            self.assertEqual(len(calls),2)
            file.write_text('changed\n'+file.read_text(encoding='utf-8'),encoding='utf-8')
            await bridge.invoke(event,tool,{'path':str(file),'offset':10,'limit':20})
            self.assertEqual(len(calls),3)
            await bridge.invoke(event,tool,{'path':str(file),'offset':0,'limit':350})
            self.assertLessEqual(max(call['limit'] for call in calls),120)
            saved=self.storage.load_active_task(task.umo)
            self.assertEqual(Control.control(saved)['journal'][-1]['status'],'completed')

    def test_cache_never_uses_host_metadata_for_remote_or_changed_permissions(self):
        task=self.task();file=Path(self.f.temp.name)/'a.py';file.write_text('ok',encoding='utf-8')
        cache=R.ReadCache(self.owner)
        self.assertIsNone(cache.plan(task,{'path':str(file)}))
        cfg={'provider_settings':{'computer_use_runtime':'local','filesystem_scope':'workspace'}}
        self.owner._context_config=lambda *args:cfg
        version=cache.version(task,{'path':str(file)})
        cfg['provider_settings']['filesystem_scope']='none'
        self.assertNotEqual(version,cache.version(task,{'path':str(file)}))

    async def test_handoff_summarizes_index_once_and_keeps_raw_source(self):
        task=self.task();history=big_history();original=deepcopy(history);requests=[]
        async def chat(**kwargs):requests.append(kwargs);return S(completion_text='已改page.js三处。未接完功能，未自检；先接完事件，再node检查。原代码按证据回查。')
        reduced=await C.TaskContinuity(self.owner).compact(self.f.event(task.umo),task,history,S(text_chat=chat),'context_capacity',token_limit=100000)
        self.assertEqual(len(requests),1)
        self.assertNotIn('signature ',requests[0]['prompt'])
        self.assertNotIn('private ',requests[0]['prompt'])
        self.assertIn(C.MARKER,reduced[0]['content'])
        saved=self.storage.load_active_task(task.umo);record=self.storage._read_json(C.TaskContinuity(self.owner).directory(task)/(C.lane_state(saved)['record_id']+'.json'))
        self.assertEqual(record['history'],original)
        self.assertLess(record['source_chars'],record['raw_history_chars']*.15)

    async def test_empty_and_oversize_summary_retry_once_without_freezing(self):
        for responses,quality in [(['','有效简短摘要'],'normal'),(['x'*6001,'有效短摘要'],'normal'),(['',''],'degraded'),(['x'*8000,'y'*9000],'degraded')]:
            with self.subTest(lengths=list(map(len,responses))):
                task=self.task();calls=[];pending=list(responses)
                async def chat(**kwargs):calls.append(kwargs);return S(completion_text=pending.pop(0))
                continuity=C.TaskContinuity(self.owner)
                await continuity.compact(self.f.event(task.umo),task,[{'role':'user','content':'继续开发'}],S(text_chat=chat),'context_capacity',token_limit=100000)
                saved=self.storage.load_active_task(task.umo);lane=C.lane_state(saved)
                self.assertEqual(saved.status,'running');self.assertEqual(len(calls),2)
                self.assertEqual(lane.get('quality','normal'),quality)
                record=self.storage._read_json(continuity.directory(task)/(lane['record_id']+'.json'))
                self.assertLessEqual(len(record['summary']),record['summary_limit'])
                self.assertEqual(record['summary_issues'][0]['actual_chars'],len(responses[0]))
                self.assertEqual(record['status'],'saved')

    async def test_retry_never_overrides_admin_stop_or_budget_control(self):
        for stop in [True,False]:
            task=self.task();count=0
            class BudgetStopped(Exception):pass
            async def chat(**kwargs):
                nonlocal count
                count+=1
                if count==1:return S(completion_text='')
                if stop:
                    current=self.storage.load_active_task(task.umo);current.status='paused';self.storage.save_task(current)
                    return S(completion_text='无法覆盖暂停')
                raise BudgetStopped('budget')
            expected=C.HandoffError if stop else BudgetStopped
            with self.assertRaises(expected):
                await C.TaskContinuity(self.owner).compact(self.f.event(task.umo),task,[{'role':'user','content':'source'}],S(text_chat=chat),'context_capacity')
            self.assertFalse(C.lane_state(self.storage.load_active_task(task.umo)).get('record_id'))


if __name__=='__main__':unittest.main()
