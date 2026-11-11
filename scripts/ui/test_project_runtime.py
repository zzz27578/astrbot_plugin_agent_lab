"""Execute real project/storage logic against temporary files and a fake DB.

This is deliberately not an AstrBot end-to-end test. No live bot credentials,
model calls, user workspaces or production databases are accessed.
"""
import asyncio
import ast
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
# Avoid the package initializer that imports AstrBot; tested modules are real.
package=types.ModuleType('review_agent_lab');package.__path__=[str(ROOT/'agent_lab')]
sys.modules['review_agent_lab']=package
Models=importlib.import_module('review_agent_lab.models')
Storage=importlib.import_module('review_agent_lab.storage').AgentLabStorage
Projects=importlib.import_module('review_agent_lab.projects').Projects
Control=importlib.import_module('review_agent_lab.task_control')
Identities=importlib.import_module('review_agent_lab.identities')

class Database:
    def __init__(self):self.rows={};self.deleted=[]
    async def get_conversation_by_id(self,cid):return self.rows.get(cid)
    async def delete(self,umo,cid):
        self.deleted.append((umo,cid));self.rows.pop(cid,None)

class ProjectRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.storage=Storage(Path(self.temp.name)/'data')
        self.db=Database()
        async def disable(task):task.heartbeat.enabled=False
        manager=SimpleNamespace(db=self.db,delete_conversation=self.db.delete)
        self.owner=SimpleNamespace(storage=self.storage,context=SimpleNamespace(conversation_manager=manager,platform_manager=SimpleNamespace(platform_insts=[],platforms_config=[])),_running_ticks=set(),
            _disable_heartbeat=disable,_redact_known_secrets=lambda text:text,_require_task_access=lambda event:None,
            _context_config=lambda umo: {'agent_runner':{'config':{'persona':{'persona_id':'persona-'+umo.split(':')[0]}}}})
        self.owner.pattern_library=SimpleNamespace(path=self.storage.registry_dir/'task_patterns.json',list_patterns=lambda **kw:[])
        self.owner.task_control=Control.TaskControl(self.owner);self.projects=Projects(self.owner);self.owner.projects=self.projects
    def tearDown(self):self.temp.cleanup()
    def task(self,bot='qq-a',project='Project',status='paused'):
        task=Models.TaskState(umo=f'{bot}:FriendMessage:123',root_goal='Fix plugin',status=status)
        task.workflow_data['task_control']={'owner_id':'123','version':1,'approved_version':1,'steps':[{'id':'one','title':'Inspect','status':'pending','instruction':'Read code','evidence':[]}],'journal':[],'automatic':True,'human_paused':status=='paused'}
        self.storage.save_task(task);p=self.projects.create(project,'development',task.umo,'123');self.projects.attach(task,p['project_id']);self.storage.save_task(task)
        return task,p
    def event(self,umo):return SimpleNamespace(unified_msg_origin=umo,get_sender_id=lambda:'123')

    async def test_same_adapter_two_instances_remain_separate(self):
        a,pa=self.task('qq-a','Same name');b,pb=self.task('qq-b','Same name')
        self.assertNotEqual(pa['project_id'],pb['project_id'])
        with self.assertRaises(ValueError):self.projects.attach(a,pb['project_id'])
        with self.assertRaises(ValueError):self.projects.select(a.umo,pb['project_id'])
        self.assertEqual({p['platform_id'] for p in self.projects.catalog()['projects']},{'qq-a','qq-b'})
    async def test_unbound_project_robot_constraint(self):
        a,_=self.task();p=self.projects.create('Reserved',platform_id='qq-b')
        with self.assertRaises(ValueError):self.projects.attach(a,p['project_id'])
    async def test_identity_projection_never_exposes_credentials(self):
        a,_=self.task()
        class Platform:
            config={'id':'qq-a','name':'Dev','token':'DO_NOT_EXPOSE','api_key':'SECRET'}
            def meta(self):return SimpleNamespace(id='qq-a',name='aiocqhttp',adapter_display_name='QQ')
            def get_stats(self):return {'status':'running','last_error':{'message':'SECRET'}}
        self.owner.context.platform_manager.platform_insts=[Platform()]
        self.owner.context.platform_manager.platforms_config=[{**Platform.config,'enable':True}]
        rows=Identities.identity_rows(self.owner,self.projects.catalog()['projects'])
        self.assertEqual(rows[0]['platform_id'],'qq-a');self.assertEqual(rows[0]['sessions'][0]['umo'],a.umo)
        self.assertNotIn('SECRET',json.dumps(rows));self.assertNotIn('DO_NOT_EXPOSE',json.dumps(rows))
        historical=Identities.identity_rows(self.owner,[{'source_umo':'qq-old:FriendMessage:123','platform_id':'qq-old'}])
        self.assertEqual([r['platform_id'] for r in historical],['qq-a'])
        self.owner.context.platform_manager.platforms_config=[]
        self.assertEqual(Identities.identity_rows(self.owner,[]),[])
    async def test_admin_delivery_ignores_incomplete_plan_and_pending_approval(self):
        task,_=self.task(status='running');task.approvals=[{'status':'pending','approval_id':'a','operation':'write'}];self.storage.save_task(task)
        ended=await self.projects.administrator_end(task.task_id,'completed','Deliver as is','admin')
        self.assertEqual(ended.status,'completed');self.assertIn('Inspect',ended.exit_summary)
        self.assertIsNone(self.storage.load_active_task(task.umo))
        task.status='running';self.storage.save_task(task)
        self.assertIsNone(self.storage.load_active_task(task.umo))
        self.assertTrue(self.storage.ended_path(task.task_id).exists())
    async def test_ending_parked_task_does_not_stop_current_task(self):
        a,_=self.task();self.storage.active_task_path(a.umo).unlink();b,_=self.task(status='running')
        future=asyncio.create_task(asyncio.sleep(10));self.owner.task_control.running[b.umo]=future
        try:
            await self.projects.administrator_end(a.task_id,'cancelled','Stop old task','admin')
            self.assertFalse(future.cancelled());self.assertEqual(self.storage.load_active_task(b.umo).task_id,b.task_id)
        finally:future.cancel();await asyncio.gather(future,return_exceptions=True);self.owner.task_control.running.clear()
    async def test_filtered_summary_opt_in_and_boundaries(self):
        a,pa=self.task('qq-a');b,pb=self.task('qq-b')
        self.projects.save_summary(a.task_id,'A'*4000)
        self.assertEqual(self.projects.daily_summary(a.umo),'')
        self.projects.update(pa['project_id'],{'share_with_daily':True})
        self.assertEqual(len(self.projects.daily_summary(a.umo)),800)
        self.assertNotIn('AAA',self.projects.filtered_context(b))
        self.assertLess(len(self.projects.filtered_context(a)),3600)
    async def test_cleanup_token_rejects_changed_data(self):
        task,p=self.task();plan=await self.projects.cleanup_plan(p['project_id'],mode='history')
        self.projects.save_summary(task.task_id,'new evidence')
        with self.assertRaises(ValueError):await self.projects.cleanup(p['project_id'],'','history',plan['token'])
        self.assertEqual(self.projects.get_task(task.task_id).task_id,task.task_id)
    async def test_cache_cleanup_preserves_plan_and_source_tree(self):
        task,p=self.task();outside=Path(self.temp.name)/'source.py';outside.write_text('untouched')
        self.projects.save_summary(task.task_id,'verified summary')
        self.storage.append_task_memory_observation(task,{'output':'large log'})
        cid=next(iter(self.projects.conversation_ids(task)))
        self.db.rows[cid]=SimpleNamespace(user_id=task.umo,content=[{'role':'user','content':'private'}])
        self.db.rows['daily']=SimpleNamespace(user_id=task.umo,content=[{'content':'daily'}])
        plan=await self.projects.cleanup_plan(p['project_id'],mode='cache')
        await self.projects.cleanup(p['project_id'],'','cache',plan['token'])
        self.assertEqual(outside.read_text(),'untouched');self.assertIn('daily',self.db.rows);self.assertNotIn(cid,self.db.rows)
        self.assertTrue(self.projects.get_task(task.task_id).workflow_data['task_control']['steps'])
        self.assertIn('verified summary',self.projects.filtered_context(task))
    async def test_history_cleanup_does_not_delete_other_bot(self):
        a,pa=self.task('qq-a');b,pb=self.task('qq-b')
        plan=await self.projects.cleanup_plan(pa['project_id'],mode='history')
        await self.projects.cleanup(pa['project_id'],'','history',plan['token'])
        with self.assertRaises(ValueError):self.projects.get_task(a.task_id)
        self.assertEqual(self.projects.get_task(b.task_id).task_id,b.task_id)
    async def test_question_answer_persists_once(self):
        task,_=self.task(status='running');state=Control.control(task);state['human_paused']=False;self.storage.save_task(task)
        row=self.owner.task_control.ask(self.event(task.umo),'Which target?',['staging','production'],'staging first')
        self.owner.task_control.schedule=lambda e:None
        result=self.owner.task_control.answer(self.event(task.umo),row['id'],'staging')
        latest=self.storage.load_active_task(task.umo)
        self.assertEqual(Control.control(latest)['questions'][0]['status'],'answered');self.assertIn('staging',Control.control(latest)['constraints'][0])
        with self.assertRaises(ValueError):self.owner.task_control.answer(self.event(task.umo),row['id'],'production')
    async def test_workspace_http_auth_and_identity_conflict(self):
        from quart import Quart,g
        API=importlib.import_module('review_agent_lab.workspace_api').WorkspaceAPI
        class Platform:
            config={'id':'qq-a','name':'Dev'}
            def meta(self):return SimpleNamespace(id='qq-a',name='aiocqhttp',adapter_display_name='QQ')
            def get_stats(self):return {'status':'running'}
        self.owner.context.platform_manager.platform_insts=[Platform()]
        self.owner.context.platform_manager.platforms_config=[{**Platform.config,'enable':True}]
        self.owner._make_cron_event=lambda umo,message,actor_id='':SimpleNamespace(unified_msg_origin=umo,get_sender_id=lambda:actor_id or '123')
        app=Quart('project-test');api=API(self.owner)
        app.add_url_rule('/workspace',view_func=api.handle,methods=['GET','POST'])
        @app.before_request
        async def authorize_fixture():
            from quart import request
            if request.headers.get('X-Test-Admin')=='yes':g.username='test-admin'
        client=app.test_client()
        self.assertEqual((await client.get('/workspace')).status_code,403)
        result=await client.get('/workspace',headers={'X-Test-Admin':'yes'})
        self.assertEqual((await result.get_json())['identities'][0]['platform_id'],'qq-a')
        rejected=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'create_project','title':'Mismatch','platform_id':'qq-a','umo':'qq-b:FriendMessage:123'})
        self.assertEqual(rejected.status_code,400)
        accepted=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'create_project','title':'Bound project','platform_id':'qq-a','umo':'qq-a:FriendMessage:123'})
        self.assertEqual(accepted.status_code,200);self.assertEqual((await accepted.get_json())['result']['platform_id'],'qq-a')
        rejected=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'set_default_bot','platform_id':'missing'})
        self.assertEqual(rejected.status_code,400)
        saved=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'set_default_bot','platform_id':'qq-a'})
        self.assertEqual(saved.status_code,200)
        reloaded=await client.get('/workspace',headers={'X-Test-Admin':'yes'})
        self.assertEqual((await reloaded.get_json())['preferences']['default_bot_id'],'qq-a')
        messages=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'set_progress','platform_id':'qq-a','enabled':True,'min_interval_seconds':30})
        self.assertEqual((await messages.get_json())['result']['progress_by_bot']['qq-a']['enabled'],True)
        task,_=self.task(status='running');delivered=[]
        async def send(umo,text):delivered.append((umo,text))
        self.owner.task_messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages(self.owner,send=send)
        response=await client.post('/workspace',headers={'X-Test-Admin':'yes'},json={'action':'deliver','task_id':task.task_id,'summary':'Admin delivery'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(delivered),1);self.assertEqual(delivered[0][0],task.umo)
        self.assertIn(task.task_id,delivered[0][1]);self.assertIn('交付',delivered[0][1])
        self.owner.context.platform_manager.platforms_config=[]
        removed=await client.get('/workspace',headers={'X-Test-Admin':'yes'})
        data=await removed.get_json()
        self.assertEqual(data['identities'],[]);self.assertEqual(data['preferences']['default_bot_id'],'')

    async def test_standalone_serves_every_page_dependency(self):
        Server=importlib.import_module('review_agent_lab.webui_server').StandaloneWebUIServer
        server=Server(owner=self.owner,static_dir=ROOT/'pages'/'agent-lab',host='127.0.0.1',port=0,token='test')
        client=server.app.test_client()
        for path in ['/', '/app.js', '/project-ui.js', '/ui-runtime.js', '/navigation.js','/motion.js','/connections.js',
                     '/style.css', '/workspace.css', '/theme.css', '/vendor/connectors.js']:
            response=await client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertTrue(await response.get_data(),path)
        self.assertEqual((await client.get('/vendor/../index.html')).status_code,404)

    async def test_task_messages_share_stream_and_never_block_control(self):
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        task,_=self.task(status='running');sent=[];clock=[1000]
        async def send(umo,text):sent.append((umo,text))
        messages=Messages(self.owner,send=send,clock=lambda:clock[0])
        await messages.publish(self.event(task.umo),task.task_id,'first')
        self.assertEqual(sent,[])
        await messages.preferences.save('admin','qq-a',progress={'enabled':True,'min_interval_seconds':60})
        await messages.publish(self.event(task.umo),task.task_id,'Inspecting files')
        await messages.publish(self.event(task.umo),task.task_id,'Too soon')
        self.assertEqual(len(sent),1)
        q=self.owner.task_control.ask(self.event(task.umo),'Which scope?',['a','b'])
        await messages.state(self.event(task.umo),task.task_id)
        self.assertIn(q['id'],sent[-1][1]);self.assertIn('需要回答',sent[-1][1])
        await messages.state(self.event(task.umo),task.task_id)
        self.assertEqual(len(sent),2)
        await messages.preferences.save('admin','qq-a',progress={'enabled':False})
        await messages.publish(self.event(task.umo),task.task_id,'Approve this','approval')
        self.assertEqual(len(sent),3)
        approval=Models.ApprovalRequest(operation='Large plan',reason='Review',impact='x'*10000)
        latest=self.storage.load_active_task(task.umo);Control.control(latest)['questions']=[];latest.approvals=[approval.to_dict()];self.storage.save_task(latest)
        await messages.state(self.event(task.umo),task.task_id)
        self.assertIn('/al approve '+approval.approval_id,sent[-1][1]);self.assertIn('完整计划',sent[-1][1])
        with self.assertRaises(PermissionError):await messages.publish(self.event('qq-b:FriendMessage:123'),task.task_id,'wrong')
        detail=await self.projects.detail(task.task_id)
        self.assertEqual([m['kind'] for m in detail['messages']],['progress','question','approval','approval'])
        self.assertEqual(self.storage.load_active_task(task.umo).status,'paused')

    async def test_message_delivery_does_not_overwrite_admin_end(self):
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        task,_=self.task(status='running')
        async def send(umo,text):await self.projects.administrator_end(task.task_id,'cancelled','Stop now','admin')
        messages=Messages(self.owner,send=send)
        await messages.publish(self.event(task.umo),task.task_id,'Waiting for approval','approval')
        self.assertEqual(self.projects.get_task(task.task_id).status,'cancelled')
        self.assertIsNone(self.storage.load_active_task(task.umo))
        await messages.state(self.event(task.umo),task.task_id)
        self.assertEqual((await self.projects.detail(task.task_id))['messages'][-1]['kind'],'delivery')

    async def test_message_unknown_result_is_not_replayed(self):
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        task,_=self.task(status='running');attempts=[]
        async def send(umo,text):attempts.append(text);raise OSError('offline')
        messages=Messages(self.owner,send=send)
        await messages.publish(self.event(task.umo),task.task_id,'Approve once','approval')
        await messages.publish(self.event(task.umo),task.task_id,'Approve once','approval')
        self.assertEqual(len(attempts),1)
        self.assertEqual(self.storage.load_active_task(task.umo).status,'running')

    async def test_message_transport_uses_private_source_without_daily_writes(self):
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        task,_=self.task(status='running');sent=[]
        self.db.rows['daily']=SimpleNamespace(user_id=task.umo,content=[{'role':'user','content':'daily context'}])
        original=json.dumps(self.db.rows['daily'].content)
        class Chain:
            def message(self,text):self.text=text;return self
        async def transport(umo,chain):sent.append((umo,chain.text));return True
        self.owner.context.send_message=transport
        module=types.ModuleType('astrbot.core.message.message_event_result');module.MessageChain=Chain
        with patch.dict(sys.modules,{'astrbot.core.message.message_event_result':module}):
            messages=Messages(self.owner)
            await messages.publish(self.event(task.umo),task.task_id,'Control message','approval')
            group,_=self.task('group-bot');group.umo='group-bot:GroupMessage:456';self.storage.save_task(group)
            await messages.publish(self.event(group.umo),group.task_id,'Private only','approval')
        self.assertEqual(len(sent),1);self.assertEqual(sent[0][0],task.umo)
        self.assertEqual(json.dumps(self.db.rows['daily'].content),original)

    async def test_archived_notification_keeps_explicit_owner_in_web_request(self):
        # Execute the actual factory without importing the entire AstrBot plugin.
        source=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        method=next(n for n in ast.walk(source) if isinstance(n,ast.FunctionDef) and n.name=='_make_cron_event')
        class CronEvent:
            def __init__(self,**kwargs):
                self.unified_msg_origin='qq-a:FriendMessage:123';self.message_obj=SimpleNamespace(sender=SimpleNamespace(user_id=''))
            def set_extra(self,*args):pass
        cron=types.ModuleType('astrbot.core.cron.events');cron.CronMessageEvent=CronEvent
        session=types.ModuleType('astrbot.core.platform.message_session');session.MessageSession=SimpleNamespace(from_str=lambda umo:SimpleNamespace(message_type='FriendMessage'))
        namespace={'task_control':Control.control,'has_request_context':lambda:True,'g':SimpleNamespace(username='web-admin'),'logger':SimpleNamespace(warning=lambda *args:None)}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_event_factory','exec'),namespace)
        with patch.dict(sys.modules,{'astrbot.core.cron.events':cron,'astrbot.core.platform.message_session':session}):
            task,_=self.task();await self.projects.administrator_end(task.task_id,'completed','done','web-admin')
            event=namespace['_make_cron_event'](self.owner,task.umo,'delivery',actor_id='123')
            self.assertEqual(event.message_obj.sender.user_id,'123')
            another,_=self.task();state=Control.control(another);state['owner_id']='another-admin';self.storage.save_task(another)
            event=namespace['_make_cron_event'](self.owner,task.umo,'old delivery',actor_id='123')
            self.assertEqual(event.message_obj.sender.user_id,'123')

    async def test_progress_merge_and_cleanup_during_transport(self):
        Messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages
        task,_=self.task(status='running');clock=[1000];sent=[]
        async def send(umo,text):sent.append(text)
        messages=Messages(self.owner,send=send,clock=lambda:clock[0])
        await messages.preferences.save('admin','qq-a',progress={'enabled':True,'min_interval_seconds':60})
        await messages.publish(self.event(task.umo),task.task_id,'First finding')
        await messages.publish(self.event(task.umo),task.task_id,'Pending finding')
        clock[0]+=61
        await messages.publish(self.event(task.umo),task.task_id,'Next finding')
        self.assertEqual(len(sent),2);self.assertIn('Pending finding',sent[-1]);self.assertIn('Next finding',sent[-1])
        path=self.storage.task_memory_dir(task.umo,task.task_id)/'messages.json'
        async def delete_record(umo,text):path.unlink()
        messages.send=delete_record
        await messages.publish(self.event(task.umo),task.task_id,'Delete while sending','approval')
        self.assertFalse(path.exists())

    async def test_direct_approval_tool_uses_same_task_stream(self):
        source=ast.parse((ROOT/'main.py').read_text(encoding='utf-8'))
        method=next(n for n in ast.walk(source) if isinstance(n,ast.AsyncFunctionDef) and n.name=='agent_lab_request_approval')
        method.decorator_list=[]
        namespace={'AstrMessageEvent':object,'ApprovalRequest':Models.ApprovalRequest}
        exec(compile(ast.Module(body=[method],type_ignores=[]),'actual_approval_tool','exec'),namespace)
        task,_=self.task(status='running');sent=[]
        async def send(umo,text):sent.append((umo,text))
        self.owner.task_messages=importlib.import_module('review_agent_lab.task_messages').TaskMessages(self.owner,send=send)
        self.owner.agent_runtime=SimpleNamespace(record_pause=lambda *args,**kwargs:None)
        result=await namespace[method.name](self.owner,self.event(task.umo),'Write config','Fix issue','One file','Restore backup')
        self.assertEqual(len(sent),1);self.assertIn(task.task_id,sent[0][1]);self.assertIn('回滚：Restore backup',sent[0][1])
        self.assertIn('原任务消息线',result)
        self.assertEqual((await self.projects.detail(task.task_id))['messages'][0]['kind'],'approval')

if __name__=='__main__':unittest.main(verbosity=2)
