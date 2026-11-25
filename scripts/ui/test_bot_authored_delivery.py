"""Bot-authored output is sent once with only an ownership title added."""
import importlib
import json
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import test_project_runtime as F

M=importlib.import_module('review_agent_lab.task_messages')
C=importlib.import_module('review_agent_lab.continuity')
Control=F.Control


class AuthoredDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f=F.ProjectRuntime();self.f.setUp();self.owner=self.f.owner;self.storage=self.f.storage
        self.sent=[];self.clock=[1000]
        async def send(umo,text):self.sent.append((umo,text))
        async def forbidden(**kwargs):raise AssertionError('no second model call for message delivery')
        self.owner.context.llm_generate=forbidden
        self.messages=M.TaskMessages(self.owner,send=send,clock=lambda:self.clock[0]);self.owner.task_messages=self.messages

    def tearDown(self):self.f.tearDown()

    async def test_authored_approval_question_stage_and_delivery(self):
        task,_=self.f.task(status='running');event=self.f.event(task.umo)
        authored='老爸，这次只清掉两个旧临时文件，备份还在；你回复批准或拒绝，我照你的意思来。'
        row=F.Models.ApprovalRequest(operation='两个临时文件',message=authored).to_dict();task.approvals.append(row);task.status='paused';self.storage.save_task(task)
        await self.messages.state(event,task.task_id)
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],authored)
        await self.messages.state(event,task.task_id);self.assertEqual(len(self.sent),1)
        latest=self.storage.load_active_task(task.umo);latest.approvals=[];latest.status='running';self.storage.save_task(latest)
        q=self.owner.task_control.ask(event,'老爸，先做哪一份？',['插件','资料'],'我建议先把插件交完。')
        await self.messages.state(event,task.task_id)
        body=self.sent[-1][1].split('\n',1)[1]
        self.assertTrue(body.startswith(q['question']));self.assertNotIn('/al answer',body)
        latest=self.storage.load_active_task(task.umo);Control.control(latest)['questions']=[];latest.status='running';self.storage.save_task(latest)
        phase='第一段搞定啦，接口已留证，后面接测试。'
        await self.messages.publish(event,task.task_id,phase,'stage')
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],phase)
        latest=self.storage.load_active_task(task.umo);latest.workflow_data['delivery_message']='老爸，东西交齐啦，没跑的真实页面体验我留给你。';self.storage.save_task(latest)
        await self.f.projects.administrator_end(task.task_id,'completed','完整内部报告，不拼入日常上下文','123')
        await self.messages.state(event,task.task_id)
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],latest.workflow_data['delivery_message'])

    async def test_warnings_use_authored_notice_or_title_only_and_keep_diagnostics_local(self):
        task,_=self.f.task(status='running');task.status='paused'
        task.set_wait(wait_reason='no_progress',message='internal diagnostic detail with 80000 token history',source='test')
        Control.control(task)['notifications']={'stalled':'老爸，我这边原地打转了，先停住，等你指个方向。'}
        self.storage.save_task(task);event=self.f.event(task.umo)
        await self.messages.state(event,task.task_id)
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],Control.control(task)['notifications']['stalled'])
        self.assertNotIn('internal diagnostic',self.sent[-1][1])
        latest=self.storage.load_active_task(task.umo);Control.control(latest)['notifications']={};latest.wait.wait_reason='runtime_timeout';self.storage.save_task(latest)
        await self.messages.state(event,task.task_id)
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],'')
        self.assertIn('runtime_timeout',self.sent[-1][1])
        detail=await self.f.projects.detail(task.task_id)
        self.assertTrue(any('internal diagnostic' in row['text'] for row in detail['messages'] if row['kind']=='warning'))

    async def test_progress_queue_and_overlong_message_never_rewrite_or_truncate(self):
        task,_=self.f.task(status='running');event=self.f.event(task.umo)
        await self.messages.preferences.save('admin','qq-a',progress={'enabled':True,'min_interval_seconds':60})
        await self.messages.publish(event,task.task_id,'角色第一句话')
        await self.messages.publish(event,task.task_id,'过时的进度不要拼回来')
        self.clock[0]+=61
        await self.messages.publish(event,task.task_id,'这是我新写的完整进度，不拼接旧话。')
        self.assertEqual(self.sent[-1][1].split('\n',1)[1],'这是我新写的完整进度，不拼接旧话。')
        before=len(self.sent)
        result=await self.messages.publish(event,task.task_id,'超长角色文案'*1000,'stage')
        self.assertIn('过长',result);self.assertEqual(len(self.sent),before)

    async def test_stage_compaction_uses_one_summary_call_and_preserves_authored_checkpoint(self):
        task,_=self.f.task(status='running');state=Control.control(task)
        state['current_step_id']='one';state['steps'][0]['stage']='inspection'
        state['journal']=[{'id':'call_x','name':'astrbot_file_read_tool','arguments':{'path':'/project/a.py'},'status':'completed',
                           'step_id':'one','plan_version':1,'authorization_version':1,'step_revision':0}]
        self.storage.save_task(task)
        authored='原因已确定，src/a.py没有空值保护；下一段补测试。'
        self.owner.task_control.checkpoint(self.f.event(task.umo),'one',authored,completed=True)
        task=self.storage.load_active_task(task.umo)
        calls=[]
        async def summarize(**kwargs):
            calls.append(kwargs)
            request=json.loads(kwargs['prompt'])
            self.assertEqual(request['current_plan']['steps'][0]['summary'],authored)
            return S(completion_text='保留空值保护结论，下一步补测试。')
        history=[{'role':'user','content':'old phase source'}]
        reduced=await C.TaskContinuity(self.owner).compact(self.f.event(task.umo),task,history,S(text_chat=summarize),'stage_completed')
        saved=self.storage.load_active_task(task.umo);lane=C.lane_state(saved)
        self.assertEqual(Control.control(saved)['steps'][0]['summary'],authored)
        self.assertEqual(lane['summary'],'保留空值保护结论，下一步补测试。')
        self.assertEqual(len(calls),1)
        record=self.storage._read_json(self.storage.root/lane['record_path'])
        self.assertEqual(record['model_calls'],1)
        self.assertEqual(record['history'],history)
        self.assertEqual(reduced[-1],history[-1])
        self.assertEqual(self.sent,[])

    async def test_analysis_and_quiet_ticks_do_not_trigger_a_write_based_stall(self):
        Guard=importlib.import_module('review_agent_lab.progress_guard')
        task,_=self.f.task(status='running');state=Control.control(task);state['current_step_id']='one'
        before=Guard.snapshot(task)
        state['journal'].append({'id':'report_one','name':'report','status':'completed','step_id':'one',
                                 'plan_version':1,'authorization_version':1,'step_revision':0,'result':'已完成用户所给材料的分析，未声称运行测试。'})
        self.storage.save_task(task)
        self.owner.task_control.checkpoint(self.f.event(task.umo),'one','分析结论已保存，不代表外部校验。',completed=True)
        saved=self.storage.load_active_task(task.umo)
        self.assertEqual(Control.control(saved)['steps'][0]['status'],'completed')
        self.assertEqual(Guard.after_tick(saved,before,reason='research'),'')
        for _ in range(30):
            again=Guard.snapshot(saved)
            self.assertEqual(Guard.after_tick(saved,again,reason='quiet research'),'')
        self.assertEqual(saved.status,'running')
        self.assertEqual(saved.wait.wait_reason,'')
        self.assertFalse(Guard.take_notice(saved))
        self.assertFalse(saved.workflow_data.get('progress_guard',{}).get('read_window'))

    async def test_new_research_paths_continue_and_equivalent_errors_warn_before_pause(self):
        Guard=importlib.import_module('review_agent_lab.progress_guard')
        task,_=self.f.task(status='running')
        for index in range(30):
            notice=Guard.observe_tool(task,dict(id=f'read_{index}',name='astrbot_file_read_tool',
                arguments={'path':f'/project/research/{index}.md','offset':0,'limit':500},
                status='completed',result=f'new source {index}'))
            self.assertEqual(notice,'')
            self.assertEqual(task.status,'running')
        guard=task.workflow_data['progress_guard']
        self.assertEqual(len(guard['seen_paths']),30)
        self.assertEqual(guard['signals']['writes'],0)
        self.assertEqual(guard['decision'],'progress')
        notices=[]
        for index in range(Guard.ERROR_PAUSE_AFTER):
            notice=Guard.observe_tool(task,dict(id=f'error_{index}',name='astrbot_execute_shell',
                arguments={'command':'python missing.py'},status='failed',result='FileNotFoundError: missing.py'))
            if notice:
                notices.append((task.workflow_data['progress_guard']['decision'],notice))
            if index < Guard.ERROR_PAUSE_AFTER-1:
                self.assertEqual(task.status,'running')
        self.assertEqual([decision for decision,_ in notices],['warning','paused'])
        self.assertEqual(task.status,'paused')
        self.assertEqual(task.wait.wait_reason,'repeated_tool_error')
        self.assertEqual(task.approvals,[])


if __name__=='__main__':unittest.main()
