"""Independent task/day conversations and overlap using a deterministic provider."""
from __future__ import annotations
import ast
import asyncio
import importlib
import json
import sys
import time
import unittest
from copy import deepcopy
from types import SimpleNamespace as S
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

import test_project_runtime as F

B=importlib.import_module('review_agent_lab.astrbot_bridge')
I=importlib.import_module('review_agent_lab.bot_identity')
G=importlib.import_module('review_agent_lab.session_guard')
Control=F.Control
RESULTS=[]


class IsolationConcurrency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=F.ProjectRuntime();self.f.setUp()
        self.owner,self.storage,self.db=self.f.owner,self.f.storage,self.f.db

    def tearDown(self):self.f.tearDown()

    async def test_tasks_and_daily_overlap_without_switching_or_copying_history(self):
        tasks=[];pointer={};daily_original={};resolutions=[];calls=[];active=0;peak=0
        for bot,marker in [('qq-code','PRIVATE_PROJECT_A'),('qq-research','PRIVATE_PROJECT_B')]:
            task,_=self.f.task(bot=bot,project=marker,status='running')
            Control.control(task).update(current_step_id='one',workflow='none')
            task.root_goal=marker;self.storage.save_task(task);tasks.append(task)
            daily_id=bot+'-daily';pointer[task.umo]=daily_id
            history=json.dumps([{'role':'user','content':'DAILY_CONTINUITY_'+bot+' '+('daily only '*10000)},
                                {'role':'assistant','content':'日常保持原话'}],ensure_ascii=False)
            self.db.rows[daily_id]=S(user_id=task.umo,persona_id=bot+'-persona',history=history)
            daily_original[daily_id]=history
            cid=str(uuid5(NAMESPACE_URL,'agent-lab:'+task.task_id+':'))
            self.db.rows[cid]=S(user_id=task.umo,history=json.dumps([{'role':'user','content':marker+' task-only state'}]))
        manager=self.owner.context.conversation_manager
        async def current(umo):return pointer[umo]
        async def conversation(umo,key):
            if key in daily_original:raise AssertionError('task must not serialize daily history')
            return self.db.rows[key]
        async def update(umo,key,**kwargs):
            self.assertNotIn(key,daily_original)
            self.db.rows[key].history=json.dumps(kwargs['history'],ensure_ascii=False)
        manager.get_curr_conversation_id=current;manager.get_conversation=conversation;manager.update_conversation=update
        async def persona(**kwargs):
            resolutions.append(kwargs)
            name=kwargs['conversation_persona_id'];return name,{'name':name,'prompt':'keep '+name},None,False
        self.owner.context.persona_manager=S(resolve_selected_persona=persona)
        async def provider_id(umo):return 'shared-model'
        self.owner.context.get_current_chat_provider_id=provider_id
        async def chat(**kwargs):
            nonlocal active,peak
            active+=1;peak=max(peak,active)
            calls.append(deepcopy(kwargs))
            await asyncio.sleep(.08)
            active-=1
            return S(completion_text='沿用当前身份完成一个有限工作单元。',usage=None)
        provider=S(text_chat=chat)
        async def get_provider(identifier):return provider
        self.owner.context.provider_manager=S(get_provider_by_id=get_provider)
        self.owner._cfg_value=lambda key,default:default
        class Message:
            def __init__(self,row):self.row=row;self.role=row['role']
            def model_dump(self):return self.row
            @classmethod
            def model_validate(cls,row):return cls(row)
        class Runner:
            async def reset(self,**kwargs):
                self.provider=kwargs['provider'];self.context=kwargs['run_context'];self.request=kwargs['request']
                self.context.messages=[Message({'role':'system','content':self.request.system_prompt}),
                                       *[Message(row) for row in self.request.contexts],Message({'role':'user','content':self.request.prompt})]
                self.request_context_manager=S(config=S(max_context_tokens=1000000))
            async def step_until_done(self,max_steps):
                self.context.messages=await self.request_context_manager.process(self.context.messages)
                await self.provider.text_chat(prompt=self.request.prompt,system_prompt=self.request.system_prompt,
                                              contexts=[m.model_dump() for m in self.context.messages if m.role!='system'])
                self.context.messages.append(Message({'role':'assistant','content':'task result stays here'}))
                if False:yield None
            def get_final_llm_resp(self):return S(completion_text='阶段完成，继续下一步。')
        # Load host entities before replacing a minimal message adapter.
        import astrbot.core.provider.entities
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.agent.message':S(Message=Message),
                 'astrbot.core.agent.runners.tool_loop_agent_runner':S(ToolLoopAgentRunner=Runner)}
        bridge=B.AstrBotBridge(self.owner);bridge.execution_context=lambda event:self.owner.context
        events=[]
        class Event:
            def __init__(self,umo):self.unified_msg_origin=umo;self._extras={}
            def get_sender_id(self):return '123'
            def set_extra(self,key,value):self._extras[key]=value
            def get_extra(self,key,default=None):return self._extras.get(key,default)
            def get_platform_name(self):return 'aiocqhttp'
        for task in tasks:
            events.append(Event(task.umo))
        method=next(n for n in ast.walk(ast.parse((F.ROOT/'main.py').read_text(encoding='utf-8')))
                    if isinstance(n,ast.AsyncFunctionDef) and n.name=='inject_agent_lab_policy')
        method.decorator_list=[]
        ns={'AstrMessageEvent':object,'ProviderRequest':object,'_bool_cfg':lambda cfg,key,default:default}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'<daily-policy>','exec'),ns)
        async def daily():
            # Run the actual daily injection policy, then append an ordinary
            # turn to the same source conversation while both tasks are active.
            self.owner.config={}
            req=S(system_prompt='daily persona',func_tool=None)
            await ns[method.name](self.owner,events[0],req)
            self.assertNotIn('PRIVATE_PROJECT_A',req.system_prompt)
            self.assertNotIn('PRIVATE_PROJECT_B',req.system_prompt)
            await provider.text_chat(prompt='DAILY_ONLY_FOLLOWUP',system_prompt=req.system_prompt,contexts=[])
            key=pointer[tasks[0].umo]
            rows=json.loads(self.db.rows[key].history);rows.append({'role':'user','content':'day follows continuously'})
            self.db.rows[key].history=json.dumps(rows,ensure_ascii=False)
        before=time.perf_counter()
        with patch.dict(sys.modules,modules), patch.object(B,'host_skills_prompt',lambda *args:''):
            await asyncio.gather(*[bridge.run(event,task,S(tools=[]),task.root_goal,'task policy',4,None)
                                  for event,task in zip(events,tasks)],daily())
        elapsed=(time.perf_counter()-before)*1000
        self.assertGreaterEqual(peak,2)
        for task,event in zip(tasks,events):
            self.assertEqual(pointer[task.umo],task.umo.split(':')[0]+'-daily')
            self.assertFalse(event.get_extra('agent_lab_runtime'))
            cid=next(iter(self.f.projects.conversation_ids(task)))
            self.assertIn('task result stays here',self.db.rows[cid].history)
            self.assertNotIn('DAILY_CONTINUITY',self.db.rows[cid].history)
        for key,original in daily_original.items():
            if key==pointer[tasks[0].umo]:self.assertEqual(json.loads(self.db.rows[key].history)[:-1],json.loads(original))
            else:self.assertEqual(self.db.rows[key].history,original)
            self.assertNotIn('PRIVATE_PROJECT_',self.db.rows[key].history)
        for call in calls:
            if call['prompt']=='PRIVATE_PROJECT_A':self.assertNotIn('PRIVATE_PROJECT_B',json.dumps(call))
            if call['prompt']=='PRIVATE_PROJECT_B':self.assertNotIn('PRIVATE_PROJECT_A',json.dumps(call))
        RESULTS.append({'scenario':'two_tasks_and_daily_on_shared_provider','provider_peak_inflight':peak,
                        'scripted_request_ms':80,'serial_delay_baseline_ms':240,'observed_overlap_ms':round(elapsed,2),
                        'daily_pointer_unchanged':True,'daily_history_preserved':True,'task_histories_isolated':True,
                        'boundary':'fake asynchronous provider; real API TPM/rate limits not measured'})

    async def test_legacy_plugin_snapshots_never_overwrite_daily_preferences(self):
        data={'qq:FriendMessage:123':{'enabled_plugins':['daily-memory'],'disabled_plugins':[]}}
        writes=[]
        async def get(**kwargs):return deepcopy(data)
        async def put(*args,**kwargs):writes.append((args,kwargs))
        guard=G.SessionPluginGuard(protected_plugins={'astrbot_plugin_agent_lab'});guard._sp=S(get_async=get,put_async=put)
        snapshot=await guard.apply_overrides('qq:FriendMessage:123',{'daily-memory':False})
        data['qq:FriendMessage:123']['enabled_plugins'].append('new-daily-setting')
        await guard.restore('qq:FriendMessage:123',snapshot)
        self.assertEqual(writes,[]);self.assertIn('new-daily-setting',data['qq:FriendMessage:123']['enabled_plugins'])
        RESULTS.append({'scenario':'legacy_plugin_snapshot_restore','shared_preference_writes':0,'new_daily_setting_preserved':True})

    async def test_metadata_persona_resolution_is_owned_and_uses_platform_type(self):
        seen=[];umo='instance-a:FriendMessage:123'
        async def current(umo):return 'daily'
        async def lookup(cid):return S(user_id=umo,persona_id='mo')
        async def forbidden(*args):raise AssertionError('must not load full daily history')
        async def resolve(**kwargs):seen.append(kwargs);return 'mo',{'name':'Mo','prompt':'角色原文'},None,False
        context=S(conversation_manager=S(get_curr_conversation_id=current,get_conversation=forbidden,db=S(get_conversation_by_id=lookup)),
                  persona_manager=S(resolve_selected_persona=resolve),platform_manager=S(platform_insts=[S(meta=lambda:S(id='instance-a',name='aiocqhttp'))]))
        result=await I.source_persona(context,umo,{})
        self.assertEqual(seen[0]['platform_name'],'aiocqhttp');self.assertEqual(result['prompt'],'角色原文')
        async def wrong(cid):return S(user_id='another:FriendMessage:123',persona_id='mo')
        context.conversation_manager.db.get_conversation_by_id=wrong
        self.assertIsNone(await I.source_persona(context,umo,{}))
        RESULTS.append({'scenario':'persona_metadata_only','daily_history_serializations':0,'foreign_conversation_rejected':True})


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IsolationConcurrency))
    if result.wasSuccessful():
        out=F.ROOT/'docs/validation/v0.3.4-isolation-concurrency.json';out.parent.mkdir(parents=True,exist_ok=True)
        out.write_text(json.dumps({'tests':result.testsRun,'scope':'temporary task DB; actual bridge, metadata and daily injection; fake asynchronous provider',
                                   'scenarios':RESULTS},ensure_ascii=False,indent=2),encoding='utf-8')
    sys.exit(not result.wasSuccessful())
