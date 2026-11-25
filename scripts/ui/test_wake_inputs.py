"""Multiple real bridge wakes must append changes, not repeated task dossiers."""
import copy
import importlib
import json
import sys
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch
from uuid import uuid5, NAMESPACE_URL

import test_project_runtime as F

B = importlib.import_module('review_agent_lab.astrbot_bridge')
W = importlib.import_module('review_agent_lab.wake_context')
R = importlib.import_module('review_agent_lab.runtime_runner')


class WakeInputs(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=F.ProjectRuntime();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.owner,self.storage,self.db=self.f.owner,self.f.storage,self.f.db
        self.task,_=self.f.task(status='running')
        self.state=F.Control.control(self.task)
        self.state.update(workflow='none',current_step_id='one',authorization_version=1)
        self.task.task_brief='IMPORTANT_ORIGINAL_REQUIREMENT\n'+'接口与约束。'*2000
        self.task.entry_summary=self.task.task_brief
        self.task.budget.max_total_tokens=0
        self.storage.save_task(self.task)
        self.owner._cfg_value=lambda key,default:default
        self.owner._context_config=lambda umo:{'provider_settings':{'computer_use_runtime':'none'}}
        self.bridge=B.AstrBotBridge(self.owner);self.bridge.execution_context=lambda event:self.owner.context
        self.event=self.f.event(self.task.umo);self.event._extras={}
        self.event.set_extra=lambda key,value:self.event._extras.__setitem__(key,value)
        self.event.get_extra=lambda key,default=None:self.event._extras.get(key,default)
        self.runtime=R.AgentRuntimeRunner(self.owner)
        self.spec=F.Models.AgentSpec()

    def prompt(self,task=None):
        return self.runtime._task_prompts(task or self.task,self.spec,'continue')[1]

    def test_only_bootstrap_has_full_brief_and_steps_use_field_deltas(self):
        first,metric=W.prepare(self.owner,self.task,[],self.prompt())
        history=[{'role':'user','content':first}];before=copy.deepcopy(history)
        self.assertIn('IMPORTANT_ORIGINAL_REQUIREMENT',first)
        self.assertEqual(metric['kind'],'bootstrap')
        self.state['steps'][0]['status']='completed';self.state['version']=2
        second,metric=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertEqual(metric['kind'],'delta')
        self.assertNotIn('IMPORTANT_ORIGINAL_REQUIREMENT',second)
        self.assertIn('"status":"completed"',second)
        self.assertNotIn('"instruction"',second)
        self.assertLess(len(second),700)
        self.assertEqual(history,before)

    def test_new_guidance_is_delivered_once_and_compaction_cycle_reboots(self):
        first,_=W.prepare(self.owner,self.task,[],self.prompt())
        history=[{'role':'user','content':first}]
        self.state['guidance']=[{'message':'NEW_ADMIN_REQUIREMENT','time':'now'}]
        second,_=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertIn('NEW_ADMIN_REQUIREMENT',second)
        history.append({'role':'user','content':second})
        third,_=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertNotIn('NEW_ADMIN_REQUIREMENT',third)
        clean_cycle=[{'role':'user','content':'[Agent Lab 阶段交接记录]\nSaved work notes'}]
        reboot,metric=W.prepare(self.owner,self.task,clean_cycle,self.prompt())
        self.assertEqual(metric['kind'],'bootstrap')
        self.assertIn('IMPORTANT_ORIGINAL_REQUIREMENT',reboot)
        self.assertIn('NEW_ADMIN_REQUIREMENT',reboot)
        self.state['continuity']={'lanes':{'':{'record_id':'new-cycle'}}}
        retained_marker_bootstrap,metric=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertEqual(metric['kind'],'bootstrap')
        self.assertIn('IMPORTANT_ORIGINAL_REQUIREMENT',retained_marker_bootstrap)

    def test_worker_and_arbitrary_user_prompts_are_not_replaced(self):
        for prompt,lane in [('Explicit worker job',''),(self.prompt(),'worker-a')]:
            returned,metric=W.prepare(self.owner,self.task,[],prompt,lane=lane)
            self.assertEqual(returned,prompt);self.assertIsNone(metric)

    def test_approval_receipts_do_not_repeat_code_or_disappear_on_failed_retry(self):
        first,_=W.prepare(self.owner,self.task,[],self.prompt())
        history=[{'role':'user','content':first}]
        self.state['journal']=[{'id':'call_once','name':'astrbot_execute_python','arguments':{'code':'CODE_BLOB'*5000},
                               'status':'completed','approval_id':'approved_once','result':'CHECK_PASS',
                               'result_path':'receipt.txt'}]
        second,_=W.prepare(self.owner,self.task,history,self.prompt())
        retry,_=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertIn('CHECK_PASS',second);self.assertEqual(retry,second)
        self.assertNotIn('CODE_BLOB',second)
        history.append({'role':'user','content':second})
        third,_=W.prepare(self.owner,self.task,history,self.prompt())
        self.assertNotIn('CHECK_PASS',third)

    async def test_twelve_bridge_wakes_include_one_large_brief_and_immutable_prefixes(self):
        requests=[];failed=False
        async def chat(**kwargs):
            nonlocal failed
            requests.append(copy.deepcopy(kwargs))
            if len(requests)==4 and not failed:
                failed=True;raise RuntimeError('transient provider error')
            return S(completion_text='Continue from the actual recorded state.',usage=None)
        provider=S(provider_config={'max_context_tokens':1000000},text_chat=chat)
        async def get_provider(identifier):return provider
        self.owner.context.provider_manager=S(get_provider_by_id=get_provider)
        async def selected(umo):return 'fixture-provider'
        self.owner.context.get_current_chat_provider_id=selected
        cid=str(uuid5(NAMESPACE_URL,'agent-lab:'+self.task.task_id+':'))
        self.db.rows[cid]=S(user_id=self.task.umo,history='[]')
        manager=self.owner.context.conversation_manager
        async def get(umo,key):return self.db.rows[key]
        async def update(umo,key,**kwargs):self.db.rows[key].history=json.dumps(kwargs['history'],ensure_ascii=False)
        manager.get_conversation=get;manager.update_conversation=update
        class Message:
            def __init__(self,row):self.row=copy.deepcopy(row);self.role=row['role']
            def model_dump(self):return copy.deepcopy(self.row)
            @classmethod
            def model_validate(cls,row):return cls(row)
        class Runner:
            async def reset(inner,**kwargs):
                inner.provider=kwargs['provider'];inner.context=kwargs['run_context'];inner.request=kwargs['request']
                inner.context.messages=[Message({'role':'system','content':inner.request.system_prompt}),
                                        *[Message(row) for row in inner.request.contexts],
                                        Message({'role':'user','content':inner.request.prompt})]
                inner.request_context_manager=S(config=S(max_context_tokens=1000000))
            async def step_until_done(inner,max_steps):
                inner.context.messages=await inner.request_context_manager.process(inner.context.messages)
                await inner.provider.text_chat(system_prompt=inner.request.system_prompt,
                    contexts=[m.model_dump() for m in inner.context.messages if m.role!='system'])
                inner.context.messages.append(Message({'role':'assistant','content':'Progress checked.'}))
                if False:yield None
            def get_final_llm_resp(inner):return S(completion_text='Progress checked.')
        import astrbot.core.provider.entities
        modules={'astrbot.core.astr_agent_context':S(AstrAgentContext=S,AgentContextWrapper=S),
                 'astrbot.core.agent.message':S(Message=Message),
                 'astrbot.core.agent.runners.tool_loop_agent_runner':S(ToolLoopAgentRunner=Runner)}
        original_prompts=[]
        with patch.dict(sys.modules,modules),patch.object(B,'host_skills_prompt',return_value=''):
            for index in range(12):
                task=self.storage.load_active_task(self.task.umo)
                if index==6:
                    F.Control.control(task).setdefault('guidance',[]).append({'message':'DELTA_REQUIREMENT','time':'later'})
                    self.storage.save_task(task)
                system,prompt=self.runtime._task_prompts(task,self.spec,'resume')
                original_prompts.append(prompt)
                try:await self.bridge.run(self.event,task,S(tools=[]),prompt,system,100,None)
                except RuntimeError as exc:self.assertEqual(str(exc),'transient provider error')
        self.assertEqual(len(requests),12)
        for previous,current in zip(requests,requests[1:]):
            self.assertEqual(previous['contexts'],current['contexts'][:len(previous['contexts'])])
            self.assertEqual(previous['system_prompt'],current['system_prompt'])
        users=[r['content'] for r in requests[-1]['contexts'] if r['role']=='user']
        self.assertEqual(sum('IMPORTANT_ORIGINAL_REQUIREMENT' in p for p in users),1)
        self.assertEqual(sum('DELTA_REQUIREMENT' in p for p in users),1)
        self.assertLess(sum(map(len,users)),len(original_prompts[0])*2)
        self.assertTrue(all(len(body)<1000 for body in users[1:]))
        metrics=F.Control.control(self.storage.load_active_task(self.task.umo))
        self.assertFalse(metrics.get('scope_notices'))
        print(json.dumps({'scenario':'12_wakes_one_provider_failure','wake_user_chars':sum(map(len,users)),
                          'previous_full_prompt_chars_sum':sum(map(len,original_prompts)),
                          'max_delta_chars':max(map(len,users[1:])),
                          'prefix_comparisons':len(requests)-1},ensure_ascii=False))


if __name__=='__main__':unittest.main(verbosity=2)
