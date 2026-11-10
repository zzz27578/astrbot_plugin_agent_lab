"""Execute real project/storage logic against temporary files and a fake DB.

This is deliberately not an AstrBot end-to-end test. No live bot credentials,
model calls, user workspaces or production databases are accessed.
"""
import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

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
        self.owner=SimpleNamespace(storage=self.storage,context=SimpleNamespace(conversation_manager=manager,platform_manager=SimpleNamespace(platform_insts=[])),_running_ticks=set(),
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
        rows=Identities.identity_rows(self.owner,self.projects.catalog()['projects'])
        self.assertEqual(rows[0]['platform_id'],'qq-a');self.assertEqual(rows[0]['sessions'][0]['umo'],a.umo)
        self.assertNotIn('SECRET',json.dumps(rows));self.assertNotIn('DO_NOT_EXPOSE',json.dumps(rows))
        historical=Identities.identity_rows(self.owner,[{'source_umo':'broken:value','platform_id':'qq-old'}])
        self.assertEqual(next(r for r in historical if r['platform_id']=='qq-old')['sessions'],[])
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
        self.owner._make_cron_event=lambda umo,message:self.event(umo)
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

    async def test_standalone_serves_every_page_dependency(self):
        Server=importlib.import_module('review_agent_lab.webui_server').StandaloneWebUIServer
        server=Server(owner=self.owner,static_dir=ROOT/'pages'/'agent-lab',host='127.0.0.1',port=0,token='test')
        client=server.app.test_client()
        for path in ['/', '/app.js', '/project-ui.js', '/ui-runtime.js', '/navigation.js',
                     '/style.css', '/workspace.css', '/theme.css', '/vendor/connectors.js']:
            response=await client.get(path)
            self.assertEqual(response.status_code,200,path)
            self.assertTrue(await response.get_data(),path)
        self.assertEqual((await client.get('/vendor/../index.html')).status_code,404)

if __name__=='__main__':unittest.main(verbosity=2)
