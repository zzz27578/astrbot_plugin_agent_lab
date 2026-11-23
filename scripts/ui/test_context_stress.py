"""Deterministic lifecycle/extreme simulations. Only temporary workspaces are touched."""
import asyncio
import importlib
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import test_project_runtime as F
from test_context_economy import big_history

C=importlib.import_module('review_agent_lab.continuity')
V=importlib.import_module('review_agent_lab.context_views')
B=importlib.import_module('review_agent_lab.astrbot_bridge')
U=importlib.import_module('review_agent_lab.usage_metrics')
Control=F.Control
RESULTS=[]


class ContextStressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=F.ProjectRuntime();self.f.setUp()
        self.owner,self.storage=self.f.owner,self.f.storage
        self.workspace=Path(self.f.temp.name)/'source';self.workspace.mkdir()

    def tearDown(self):self.f.tearDown()

    def task(self):
        task,project=self.f.task(status='running')
        Control.control(task).update(current_step_id='one',execution_settings={'mode':'full','roots':[str(self.workspace)]})
        self.storage.save_task(task)
        return task,project

    async def test_new_update_continue_delete_recreate_and_history_cleanup(self):
        from mcp.types import CallToolResult,TextContent
        task,project=self.task();event=self.f.event(task.umo);extras={'agent_lab_round_id':'create'}
        event.get_extra=lambda k,default=None:extras.get(k,default)
        self.owner._context_config=lambda *args:{'provider_settings':{'computer_use_runtime':'local'}}
        tools={name:S(name=name,description='') for name in ['astrbot_file_read_tool','astrbot_file_write_tool','astrbot_file_edit_tool','astrbot_execute_shell']}
        bridge=B.AstrBotBridge(self.owner);bridge.tool=lambda name,event=None:tools[name];bridge.execution_context=lambda event:self.owner.context
        self.owner._tool_allowed_by_agent_profile=self.owner._tool_available_for_agent=lambda *args:True
        self.owner._disabled_plugin_names=lambda *args:[]
        self.owner._effective_tool_risk=self.owner._infer_tool_risk=lambda *args:'work'
        self.owner._cfg_value=lambda key,default:default
        self.owner._budget_remaining_tools=lambda task:24;self.owner._consume_tool_budget=lambda *args:''
        reads=[]
        async def workspace(context):return self.workspace
        async def execute(tool,context,**args):
            path=Path(args.get('path',str(self.workspace/'page.js'))).resolve()
            assert path.is_relative_to(self.workspace.resolve())
            if tool.name=='astrbot_file_write_tool':path.write_text(args['content'],encoding='utf-8');text='written'
            elif tool.name=='astrbot_file_edit_tool':path.write_text(path.read_text(encoding='utf-8').replace(args['old'],args['new']),encoding='utf-8');text='edited'
            elif tool.name=='astrbot_execute_shell':path.unlink();text='removed'
            else:
                reads.append((args.get('offset',0),args.get('limit')))
                if path.exists():
                    lines=path.read_text(encoding='utf-8').splitlines(keepends=True);start=args.get('offset',0)
                    text=''.join(lines[start:start+args.get('limit',len(lines))])
                else:
                    yield CallToolResult(content=[TextContent(type='text',text='Error: file missing')],isError=True);return
            yield CallToolResult(content=[TextContent(type='text',text=text)])
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute)),
                 'astrbot.core.tools.computer_tools.util':S(workspace_root_for_context=workspace)}
        file=self.workspace/'page.js';body=''.join(f'const line{i} = "第{i}行";\n' for i in range(1617))
        with patch.dict(sys.modules,modules):
            await bridge.invoke(event,tools['astrbot_file_write_tool'],{'path':str(file),'content':body})
            await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':0,'limit':100})
            await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':70,'limit':80})
            self.assertEqual(reads,[(0,100),(100,50)])
            extras['agent_lab_round_id']='continue'
            await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':20,'limit':50})
            self.assertEqual(len(reads),2)
            await bridge.invoke(event,tools['astrbot_file_edit_tool'],{'path':str(file),'old':'line0 =','new':'newLine0 ='})
            updated=await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':0,'limit':30})
            self.assertIn('newLine0',updated);self.assertEqual(len(reads),3)
            # External deletion is intentionally not journalled. Even then an
            # identical same-round query must not return the deleted file cache.
            file.unlink()
            missing=await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':0,'limit':30},native=True)
            self.assertTrue(missing[0].isError)
            await bridge.invoke(event,tools['astrbot_file_write_tool'],{'path':str(file),'content':'export const recreated = true;\n'})
            fresh=await bridge.invoke(event,tools['astrbot_file_read_tool'],{'path':str(file),'offset':0,'limit':30})
            self.assertIn('recreated',fresh)
            await bridge.invoke(event,tools['astrbot_execute_shell'],{'command':f'rm {file}'})
            self.assertFalse(file.exists())
        saved=self.storage.load_active_task(task.umo)
        U.record_context(saved,[{'role':'tool','content':body}],[{'role':'tool','content':'文件证据索引'}],estimated_tokens=12,capacity_tokens=1000000,trigger_tokens=700000)
        U.record_round(saved,'continue');self.storage.save_task(saved);U.write_task_line(self.owner,saved,event_id='continue')
        detail=await self.f.projects.detail(task.task_id)
        self.assertGreater(detail['record_chars'],0)
        self.assertTrue(all(row['chars'] is not None for row in detail['files']))
        self.assertTrue(any(row['kind']=='metrics' and row['status']=='recorded' for row in detail['messages']))
        for row in detail['files']:
            self.assertEqual(row['chars'],len((self.storage.root/row['path']).read_text(encoding='utf-8')))
        ended=await self.f.projects.administrator_end(task.task_id,'cancelled','模拟停止并核对部分成果','tester')
        self.assertEqual(ended.status,'cancelled')
        plan=await self.f.projects.cleanup_plan(project['project_id'],task.task_id,'history')
        with self.assertRaises(ValueError):await self.f.projects.cleanup(project['project_id'],task.task_id,'history','invalid-token')
        result=await self.f.projects.cleanup(project['project_id'],task.task_id,'history',plan['token'])
        self.assertNotIn(task.task_id,self.f.projects.index()['tasks'])
        self.assertFalse(self.storage.task_path(task.umo,task.task_id).exists())
        RESULTS.append({'case':'new_update_continue_delete_recreate_cleanup','source_lines':1617,'actual_read_calls':len(reads),
                        'overlap_new_read':[100,50],'stored_chars_before_delete':detail['record_chars'],'assertions':'passed'})

    async def test_huge_context_handoffs_before_nominal_capacity_and_records_metrics(self):
        task,_=self.task();history=big_history()
        while len(history)<44:history.append({'role':'assistant','content':'还有未接完的逻辑，下一步先核对。'})
        # Signed protocol data stays in provider history, so it must trigger an
        # early source-backed handoff rather than wait for 70% of a 1M model.
        history[1]['content'][0]['encrypted']='signed-'*18000
        original=deepcopy(history);calls=[]
        class Message:
            def __init__(self,row):self.row=row
            def model_dump(self):return self.row
            @classmethod
            def model_validate(cls,row):return cls(row)
        async def chat(**kwargs):
            calls.append(kwargs)
            usage=S(input_other=U.estimate_tokens([kwargs['prompt'],kwargs['system_prompt']]),input_cached=0,output=40)
            usage.total=usage.input_other+usage.output
            current=self.storage.load_active_task(task.umo)
            U.record_request(current,U.request_size(kwargs,kwargs),usage,phase='handoff')
            current.add_token_usage(usage);current.budget.tokens_used+=usage.total;self.storage.save_task(current)
            return S(completion_text='已改page.js三处，未完成事件接线，未跑自检。先读关键证据补齐交互，再跑语法与挂载测试。',usage=usage)
        adapter=C.StageContextManager(C.TaskContinuity(self.owner),self.f.event(task.umo),task.task_id,S(text_chat=chat),S(config=S(max_context_tokens=1000000)))
        with patch.dict(sys.modules,{'astrbot.core.agent.message':S(Message=Message)}):
            reduced=await adapter.process([Message({'role':'system','content':'source persona'}),*[Message(row) for row in history]])
            await adapter.process(reduced)
            self.assertEqual(len(calls),1,'the next pass must not immediately compact again')
        saved=self.storage.load_active_task(task.umo);lane=C.lane_state(saved)
        record=self.storage._read_json(C.TaskContinuity(self.owner).directory(task)/(lane['record_id']+'.json'))
        self.assertEqual(record['reason'],'working_history_limit');self.assertEqual(record['history'],original)
        self.assertEqual(len(calls),1);self.assertLess(record['source_chars'],24000)
        self.assertLessEqual(len(lane['summary']),record['summary_limit'])
        after=len(U.encoded([row.model_dump() for row in reduced]));before=len(U.encoded(history))
        self.assertLess(after,before*.2)
        detail=await self.f.projects.detail(task.task_id)
        self.assertTrue(any(row['kind']=='metrics' and '字符摘要' in row['text'] for row in detail['messages']))
        self.assertEqual(detail['usage_metrics']['phases']['handoff']['calls'],1)
        RESULTS.append({'case':'44_messages_signed_large_context','raw_history_chars':before,'handoff_source_chars':record['source_chars'],
                        'post_handoff_chars':after,'summary_chars':len(lane['summary']),'summary_limit':record['summary_limit'],
                        'handoff_requests':len(calls),'simulated_reported_tokens':saved.budget.tokens_used,
                        'token_source':'deterministic_fake_provider_usage_not_a_real_bill','assertions':'passed'})

    async def test_timeouts_empty_oversize_and_retry_are_bounded(self):
        for scenario,sequence in [('timeout_then_ok',['timeout','ok']),('timeout_twice',['timeout','timeout']),
                                  ('empty_then_ok',['empty','ok']),('empty_twice',['empty','empty']),
                                  ('oversize_twice',['long','long']),('oversize_then_ok',['long','ok'])]:
            task,_=self.task();remaining=list(sequence);calls=[]
            async def chat(**kwargs):
                action=remaining.pop(0);calls.append(action)
                if action=='timeout':await asyncio.sleep(10)
                return S(completion_text='' if action=='empty' else 'x'*50000 if action=='long' else '继续补齐代码与自检，尚未完成。')
            with patch.object(C,'SUMMARY_TIMEOUT_SECONDS',.01):
                await C.TaskContinuity(self.owner).compact(self.f.event(task.umo),task,[{'role':'user','content':'继续'}],S(text_chat=chat),'context_capacity')
            saved=self.storage.load_active_task(task.umo);lane=C.lane_state(saved)
            record=self.storage._read_json(C.TaskContinuity(self.owner).directory(task)/(lane['record_id']+'.json'))
            self.assertEqual(len(calls),2);self.assertEqual(saved.status,'running')
            self.assertEqual(record['status'],'saved');self.assertLessEqual(record['summary_chars'],record['summary_limit'])
            self.assertEqual(record['summary_issues'][0]['reason'],'too_long' if scenario.startswith('oversize') else 'timeout' if scenario.startswith('timeout') else 'empty')
            self.assertEqual(record['unreported_calls'],2)
            RESULTS.append({'case':scenario,'calls':len(calls),'summary_chars':record['summary_chars'],'limit':record['summary_limit'],
                            'quality':lane['quality'],'issue':record['summary_issues'][0]['reason'],'reported_tokens':None,'assertions':'passed'})

    async def test_tool_timeout_keeps_unknown_side_effect_and_prevents_replay(self):
        from mcp.types import CallToolResult,TextContent
        task,_=self.task();event=self.f.event(task.umo);event.get_extra=lambda k,default=None:default
        tool=S(name='astrbot_file_write_tool',description='write');bridge=B.AstrBotBridge(self.owner)
        bridge.tool=lambda *args:tool;bridge.execution_context=lambda event:self.owner.context
        self.owner._tool_allowed_by_agent_profile=self.owner._tool_available_for_agent=lambda *args:True
        self.owner._disabled_plugin_names=lambda *args:[];self.owner._effective_tool_risk=self.owner._infer_tool_risk=lambda *args:'work'
        self.owner._budget_remaining_tools=lambda task:24;self.owner._consume_tool_budget=lambda *args:''
        self.owner._cfg_value=lambda key,default:1 if key=='tool_call_timeout' else default
        file=self.workspace/'partial.js';executions=[]
        async def execute(tool,context,**args):
            executions.append(args);file.write_text('partial change',encoding='utf-8');await asyncio.sleep(10)
            yield CallToolResult(content=[TextContent(type='text',text='done')])
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.astr_agent_tool_exec':S(FunctionToolExecutor=S(execute=execute))}
        with patch.dict(sys.modules,modules):
            with self.assertRaises(asyncio.TimeoutError):await bridge.invoke(event,tool,{'path':str(file),'content':'full'})
            saved=self.storage.load_active_task(task.umo)
            self.assertEqual(Control.control(saved)['journal'][-1]['status'],'unknown');self.assertEqual(saved.status,'paused')
            with self.assertRaises(B.ExecutionStopped):await bridge.invoke(event,tool,{'path':str(file),'content':'full'})
        self.assertEqual(len(executions),1);self.assertEqual(file.read_text(encoding='utf-8'),'partial change')
        RESULTS.append({'case':'tool_timeout_after_partial_write','executions':1,'journal_status':'unknown','task_status':'paused','assertions':'passed'})

    async def test_model_working_views_do_not_nest_and_metrics_stay_small(self):
        task,_=self.task();history=big_history();view=V.history_view(history,task);initial=len(U.encoded(view))
        for _ in range(60):
            view=V.history_view(view,task)
            self.assertLessEqual(len(U.encoded(view)),initial)
            self.assertNotIn('[历史工具内容已索引；这是工作视图，原始记录未删除]\n[历史工具内容已索引',U.encoded(view))
        huge={'body':{'nested':[{'content':'x'*50000} for _ in range(80)]}}
        self.assertLess(len(U.encoded(V.arguments_view(huge))),3500)
        sizes=U.request_size({'contexts':history},{'contexts':view})
        for i in range(100):
            U.record_request(task,sizes,S(input_other=100,input_cached=20,output=10,total=130) if i%2 else None,round_id=str(i))
            U.record_round(task,str(i))
        self.assertEqual(len(U.ledger(task)['last_rounds']),12)
        self.assertLess(len(U.encoded(U.ledger(task))),10000)
        self.assertEqual(U.ledger(task)['tokens']['total'],6500)
        self.assertEqual(U.ledger(task)['unreported_calls'],50)
        RESULTS.append({'case':'60_working_view_passes_100_metric_updates','initial_working_chars':initial,'final_working_chars':len(U.encoded(view)),
                        'metrics_chars':len(U.encoded(U.ledger(task))),'reported_tokens_simulated':6500,'unreported_calls':50,'assertions':'passed'})

    async def test_resume_from_partial_handoff_and_cancelled_task_never_returns(self):
        task,_=self.task();history=[{'role':'user','content':'保留原约束与未完成项。'*6000}];seen=[]
        class BudgetStopped(Exception):pass
        async def partial(**kwargs):
            seen.append(json.loads(kwargs['prompt'])['source_chunk'])
            if len(seen)==2:raise BudgetStopped('per tick budget')
            return S(completion_text='仍未完成，下一步补测试。')
        continuity=C.TaskContinuity(self.owner)
        with self.assertRaises(BudgetStopped):await continuity.compact(self.f.event(task.umo),task,history,S(text_chat=partial),'context_capacity',token_limit=100000)
        draft=self.storage.load_active_task(task.umo);record_id=C.lane_state(draft)['draft_record_id']
        async def resume(**kwargs):seen.append(json.loads(kwargs['prompt'])['source_chunk']);return S(completion_text='保留约束，继续验证，未完成。')
        await continuity.compact(self.f.event(task.umo),draft,history,S(text_chat=resume),'context_capacity',token_limit=100000)
        self.assertEqual(seen[1],seen[2]);self.assertNotEqual(seen[0],seen[2])
        saved=self.storage.load_active_task(task.umo);self.assertEqual(C.lane_state(saved)['record_id'],record_id)
        await self.f.projects.administrator_end(task.task_id,'cancelled','stop','tester')
        self.storage.save_task(saved)
        self.assertIsNone(self.storage.load_active_task(task.umo))
        RESULTS.append({'case':'budget_interruption_resume_then_admin_cancel','handoff_record_reused':True,'first_chunk_not_replayed':True,'task_not_resurrected':True,'assertions':'passed'})

    async def test_changed_source_cursor_restarts_instead_of_skipping_content(self):
        task,_=self.task();history=[{'role':'user','content':'保留全部约束。'*9000}];seen=[]
        class BudgetStopped(Exception):pass
        async def partial(**kwargs):
            seen.append(json.loads(kwargs['prompt'])['source_chunk'])
            if len(seen)==2:raise BudgetStopped('pause between chunks')
            return S(completion_text='保留事实。')
        continuity=C.TaskContinuity(self.owner)
        with self.assertRaises(BudgetStopped):await continuity.compact(self.f.event(task.umo),task,history,S(text_chat=partial),'context_capacity',token_limit=100000)
        current=self.storage.load_active_task(task.umo);record_id=C.lane_state(current)['draft_record_id'];path=continuity.directory(current)/(record_id+'.json')
        record=self.storage._read_json(path);record['source_prefix_sha256']='stale';self.storage._write_json(path,record)
        resumed=[]
        async def resume(**kwargs):resumed.append(json.loads(kwargs['prompt'])['source_chunk']);return S(completion_text='约束与未完成保留，继续测试。')
        await continuity.compact(self.f.event(task.umo),current,history,S(text_chat=resume),'context_capacity',token_limit=100000)
        self.assertEqual(resumed[0],seen[0]);self.assertIn('source_restart_reason',self.storage._read_json(path))
        RESULTS.append({'case':'stale_source_cursor_restart','first_chunk_reprocessed_for_changed_source':True,'assertions':'passed'})


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ContextStressTests)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        out=F.ROOT/'docs/validation/v0.3.3-context-stress.json';out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'environment':'temporary files, deterministic fake tools/providers; no production calls',
                                   'tests':result.testsRun,'scenarios':RESULTS},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
