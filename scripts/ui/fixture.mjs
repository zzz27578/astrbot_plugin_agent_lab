import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
export function createFixture(){
 const state=JSON.parse(fs.readFileSync(path.join(root,'scripts/preview/mockstate.json'),'utf8'));
 state.runtime={bot_label:'开发助手',bot_label_source:'platform'};
 state.agents[0].name='插件排查与修复';state.agents[0].description='定位复现条件、分析代码、修复并验证。用于插件故障和版本兼容问题。';
 state.agents.push({...structuredClone(state.agents[0]),agent_id:'research',name:'资料研究',description:'检索资料、交叉核对来源，并生成带引用的项目摘要。'});
 state.agents[0].workflow_nodes.forEach((n,i)=>{n.title=['任务入口','范围检查','分析问题','检查文件','调用工具','并行分析','汇总结果','人工确认','交付归档'][i]||n.title;});
 state.plugins=[{name:'astrbot_plugin_agent_lab',display_name:'Agent Lab',activated:true,locked:true},{name:'gitlink',display_name:'GitLink',activated:true}];
 state.tools=[{name:'git_status',description:'读取仓库状态',plugin_name:'gitlink',risk:'safe',active:true,effective_active:true},{name:'astrbot_file_read_tool',description:'读取项目文件',source:'builtin',risk:'safe',active:true,effective_active:true}];
 state.archives=[];state.tasks=[];
 const makeTask=(id,title,status,umo)=>({task_id:id,root_goal:title,status,umo,agent_id:'demo',agent_name:'开发助手',updated_at:'2026-11-11T08:00:00Z',created_at:'2026-11-11T07:00:00Z',current_summary:'已完成接口梳理，下一步检查兼容层的异常处理。',last_confirmed_progress:'检查了工具注册与会话路由。',next_step:'核对执行上下文',completion_conditions:['保留现有行为','验证修改结果'],token_usage:{total:8400},approvals:[],progress_log:[],state_snapshots:[],workflow_events:[],profile_snapshot:{agent:state.agents[0]},workflow_data:{task_control:{version:1,approved_version:1,project_id:'project_a1',current_step_id:'step_2',steps:[{id:'step_1',title:'定位受影响的接口',instruction:'阅读插件与 AstrBot 的调用边界。',status:'completed',evidence:['call_1']},{id:'step_2',title:'修正执行上下文',instruction:'保留原有模块与画布配置。',status:'pending',evidence:[]}],questions:[],journal:[],constraints:['不改变配置格式']}},budget:{},heartbeat:{enabled:false}});
 const a=makeTask('task_a1','排查工具调用后的任务中断','paused','qq-dev:FriendMessage:10001');
 const b=makeTask('task_a2','适配新版插件接口','completed','qq-dev:FriendMessage:10001');b.exit_summary='已整理接口差异和迁移清单。';
 const c=makeTask('task_b1','整理资料并检查来源','paused','qq-work:FriendMessage:10001');c.workflow_data.task_control.project_id='project_b1';
 state.tasks=[a,c];state.archives=[b];
 const identities=[{platform_id:'qq-dev',label:'开发助手',platform_type:'aiocqhttp',status:'running',known:true,account_id:'',sessions:[{umo:a.umo,label:'私聊 · 10001',persona:'代码助手'}]},{platform_id:'qq-work',label:'工作助手',platform_type:'aiocqhttp',status:'running',known:true,account_id:'',sessions:[{umo:c.umo,label:'私聊 · 10001',persona:'研究助手'}]}];
 const row=t=>({task_id:t.task_id,umo:t.umo,title:t.root_goal,status:t.status,updated_at:t.updated_at,summary:t.current_summary,bytes:98304,cache_bytes:24576,selected:t!==b,question_count:0});
 let projects=[{project_id:'project_a1',title:'Agent Lab 插件',category:'插件开发',source_umo:a.umo,platform_id:'qq-dev',summary:'保留原画布和模块，在 AstrBot 原生能力上改善长期任务管理。',share_with_daily:false,workflow_ids:['demo'],tasks:[row(a),row(b)],bytes:196608,cache_bytes:49152,storage_path:'projects/project_a1'},{project_id:'project_a3',title:'部署与运行记录',category:'问题排查',source_umo:a.umo,platform_id:'qq-dev',summary:'检查部署环境、依赖与日志，记录可复用的排查步骤。',workflow_ids:[],tasks:[],bytes:4096,cache_bytes:0,storage_path:'projects/project_a3'},{project_id:'project_b1',title:'研究资料',category:'资料研究',source_umo:c.umo,platform_id:'qq-work',summary:'按主题归档证据、引用和阶段结论。',workflow_ids:['research'],tasks:[row(c)],bytes:98304,cache_bytes:24576,storage_path:'projects/project_b1'}];
 const requests=[];
 const workspace=()=>({ok:true,projects,identities,selected:{},total_bytes:299008,cache_bytes:73728,shared_metadata_bytes:2000});
 const api=async(route,method,body)=>{
   requests.push({route,method,body});
   if(route==='/api/state')return state;
   if(route==='/api/workspace'){
     if(method==='GET')return workspace();
     const p=projects.find(p=>p.project_id===body.project_id);
     const t=[...state.tasks,...state.archives].find(t=>t.task_id===body.task_id);
     let result={};
     if(body.action==='detail')result={task:t,record_bytes:98304,native_history_bytes:15000,files:[{path:`sessions/mock/${t.task_id}.json`,bytes:98304}]};
     else if(body.action==='create_project'){const id='project_'+Date.now().toString(16);result={project_id:id,title:body.title,category:body.category||'项目',source_umo:body.umo||'',platform_id:body.umo?.split(':')[0]||body.platform_id||'',summary:'',tasks:[],bytes:0,cache_bytes:0,workflow_ids:[],storage_path:`projects/${id}`};projects.push(result);}
     else if(body.action==='update_project'){Object.assign(p,body);result=p;}
     else if(body.action==='save_summary'){p.summary=body.summary;result={message:'已保存'};}
     else if(body.action==='draft_summary')result={summary:'接口梳理已完成；异常处理尚未验证。下一步核对任务暂停与恢复。'};
     else if(body.action==='read_record')result={path:body.path,text:'任务记录：计划与证据已保存。',truncated:false};
     else if(['stop','deliver'].includes(body.action)){t.status=body.action==='stop'?'cancelled':'completed';t.exit_summary='管理员按现状结束；未验证项保留。';projects.forEach(p=>p.tasks.forEach(x=>{if(x.task_id===t.task_id)x.status=t.status;}));result={status:t.status,summary:t.exit_summary};}
     else if(body.action==='cleanup_preview')result={task_ids:p.tasks.map(t=>t.task_id),files:[{path:'projects/test/summary.md',bytes:1024}],bytes:1024,native_history_bytes:2000,memory_entries:1,learned_patterns:0,token:'preview-token'};
     else if(body.action==='cleanup_confirm'){if(body.token!=='preview-token')throw Error('Preview mismatch');result={message:'清理完成'};if(body.mode==='project')projects=projects.filter(x=>x!==p);}
     return {ok:true,result};
   }
   if(route==='/api/agents'){
     if(body?.action==='delete'){state.agents=state.agents.filter(a=>a.agent_id!==body.agent_id);return {ok:true};}
     const agent={...body,agent_id:body.agent_id||'new-plan'};const index=state.agents.findIndex(a=>a.agent_id===agent.agent_id);if(index<0)state.agents.push(agent);else state.agents[index]=agent;return {ok:true,agent};
   }
   if(route==='/api/workflow/check')return {ok:true,workflow:{valid:true,errors:0,warnings:0,issues:[]}};
   if(route==='/api/registry')return {ok:true,custom_apis:[],credentials:[],skill_rules:[]};
   if(route==='/api/task/start'){if(!body.umo||!body.goal)throw Error('任务目标和来源不能为空');return {ok:true,message:'计划已创建'};}
   if(route.startsWith('/api/task/'))return {ok:true,message:'操作已保存'};
   throw Error('Fixture does not implement '+route);
 };
 const server=http.createServer(async(req,res)=>{
   const url=new URL(req.url,'http://fixture');
   if(url.pathname==='/host'){
     res.setHeader('Content-Type','text/html; charset=utf-8');
     return res.end(`<!doctype html><html><body style="margin:0;background:#fff"><iframe title="AstrBot plugin view" sandbox="allow-scripts allow-forms allow-downloads" src="/index.html?embedded=1" style="width:100vw;height:100vh;border:0"></iframe><script>window.addEventListener('message',async e=>{if(e.source!==document.querySelector('iframe').contentWindow)return;const m=e.data;if(m.kind==='ready'){e.source.postMessage({kind:'context'},'*');return;}if(m.kind==='request'){try{const r=await fetch('/api/'+m.endpoint,{method:m.method,headers:{'Content-Type':'application/json'},body:m.method==='POST'?JSON.stringify(m.body):undefined});const data=await r.json();e.source.postMessage({kind:'response',id:m.id,data},'*');}catch(error){e.source.postMessage({kind:'response',id:m.id,error:error.message},'*');}}});</script></body></html>`);
   }
   if(url.pathname.startsWith('/api/')){
     let body='';for await(const chunk of req)body+=chunk;
     try {const data=await api(url.pathname,req.method,body?JSON.parse(body):{});res.setHeader('Content-Type','application/json');res.end(JSON.stringify(data));}catch(error){res.writeHead(400,{'Content-Type':'application/json'});res.end(JSON.stringify({ok:false,error:error.message}));}return;
   }
   const fp=path.resolve(root,'pages/agent-lab','.'+(url.pathname==='/'?'/index.html':url.pathname));
   if(!fp.startsWith(path.join(root,'pages/agent-lab')+path.sep)||!fs.existsSync(fp)){res.writeHead(404);res.end('not found');return;}
   let content=fs.readFileSync(fp);
   if(fp.endsWith('.html')&&url.searchParams.has('embedded')){
     const bridge=`<script>(()=>{let id=0;const waiting=new Map();let resolve;const ready=new Promise(r=>resolve=r);window.addEventListener('message',e=>{if(e.source!==parent)return;const m=e.data;if(m.kind==='context')resolve();if(m.kind==='response'){const p=waiting.get(m.id);if(p){waiting.delete(m.id);m.error?p.reject(Error(m.error)):p.resolve(m.data);}}});const call=(endpoint,method,body)=>new Promise((resolve,reject)=>{const key=++id;waiting.set(key,{resolve,reject});parent.postMessage({kind:'request',id:key,endpoint,method,body},'*');});window.AstrBotPluginView=window.AstrBotPluginPage={ready:()=>ready,apiGet:e=>call(e,'GET'),apiPost:(e,b)=>call(e,'POST',b)};parent.postMessage({kind:'ready'},'*');})();</script>`;
     content=Buffer.from(content.toString().replace('</head>',bridge+'</head>'));
   }
   res.setHeader('Content-Type',({'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(fp)]||'application/octet-stream');res.setHeader('Access-Control-Allow-Origin','*');res.end(content);
 });
 return {server,state,workspace,requests};
}
