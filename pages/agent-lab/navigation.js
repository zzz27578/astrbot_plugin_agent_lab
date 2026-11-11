export const settingsIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m9.5 3-.6 2.5-2.2 1.3-2.5-.7-2.5 4.3 1.9 1.8v2.6l-1.9 1.8 2.5 4.3 2.5-.7 2.2 1.3.6 2.5h5l.6-2.5 2.2-1.3 2.5.7 2.5-4.3-1.9-1.8v-2.6l1.9-1.8-2.5-4.3-2.5.7-2.2-1.3-.6-2.5z" transform="translate(1 -1) scale(.92)"/><circle cx="12" cy="12" r="3.2"/></svg>';
export class Navigation {
 constructor({esc,projectUI,render,openWorkflow,newPreset,savePreset,deletePreset,duplicatePreset,renderIntegrations,identityChanged}){
  Object.assign(this,{esc,projectUI,render,openWorkflow,newPreset,savePreset,deletePreset,duplicatePreset,renderIntegrations,identityChanged});
  this.settingsTab='identity';this.presetQuery='';
  document.addEventListener('click',e=>{
   const b=e.target.closest('[data-nav-action]');if(!b)return;e.preventDefault();
   const action=b.dataset.navAction;
   if(action==='settings-tab'){this.settingsTab=b.dataset.tab;this.render();}
   if(action==='select-bot'){
    this.projectUI.selectIdentity(b.dataset.botId);this.identityChanged();
    document.querySelectorAll('.identity-card').forEach(card=>{
      const selected=card.dataset.botId===b.dataset.botId;card.classList.toggle('selected',selected);card.setAttribute('aria-pressed',String(selected));
    });
    const sessions=document.getElementById('identity-session-list');if(sessions)sessions.innerHTML=this.renderSessions();
   }
   if(action==='default-bot')void this.saveIdentity(b.dataset.botId);
   if(action==='save-progress')void this.saveProgress();
   if(action==='open-preset')this.openWorkflow(b.dataset.id);
   if(action==='new-preset')this.newPreset();
   if(action==='edit-preset')void this.savePreset(b.dataset.id);
   if(action==='duplicate-preset')void this.duplicatePreset(b.dataset.id);
   if(action==='delete-preset')void this.deletePreset(b.dataset.id);
  });
  document.addEventListener('dblclick',e=>{const card=e.target.closest('[data-nav-action="select-bot"]');if(card)void this.saveIdentity(card.dataset.botId);});
  document.addEventListener('input',e=>{if(e.target.id==='preset-search'){this.presetQuery=e.target.value;document.querySelectorAll('[data-preset-search]').forEach(el=>el.hidden=!el.dataset.presetSearch.includes(this.presetQuery.toLowerCase()));}});
 }
 header(title,subtitle,actions=''){return `<header class="page-heading"><div><p class="section-label">AGENT LAB</p><h1>${title}</h1><p>${subtitle}</p></div><div class="page-heading-actions">${actions}</div></header>`;}
 renderPresets(container,agents){
  const e=this.esc;
  container.innerHTML=`<section class="presets-page">${this.header('工作流预案','描述适用任务与处理步骤，供 Bot 选择；不适用时可直接略过。','<button class="button" data-nav-action="new-preset">＋ 新建预案</button>')}
   <div class="preset-search-row"><input id="preset-search" aria-label="搜索工作流预案" placeholder="搜索名称、用途…" value="${e(this.presetQuery)}"/><span>${agents.length} 份预案 · 项目可关联常用预案</span></div>
   <div class="preset-list">${agents.map(a=>`<article class="preset-row" ${!((a.name||'')+' '+(a.description||'')).toLowerCase().includes(this.presetQuery.toLowerCase())?'hidden':''} data-preset-search="${e((a.name+' '+a.description).toLowerCase())}"><div class="preset-symbol">↳</div><div class="preset-info"><h2>${e(a.name||a.agent_id)}${a.enabled===false?'<span class="neutral-badge">未启用</span>':''}</h2><p>${e(a.description||'补充简洁用途，让 Bot 更准确地选择这份预案。')}</p><small>${a.workflow_nodes?.length||0} 节点 · ${a.workflow_edges?.length||0} 连线</small></div><div class="preset-actions"><button class="button secondary" data-nav-action="edit-preset" data-id="${e(a.agent_id)}">用途</button><button class="button secondary" data-nav-action="duplicate-preset" data-id="${e(a.agent_id)}">复制</button><button class="button" data-nav-action="open-preset" data-id="${e(a.agent_id)}">编辑画布</button><button class="icon-only danger-text" data-nav-action="delete-preset" data-id="${e(a.agent_id)}" title="删除预案" aria-label="删除 ${e(a.name)}" ${agents.length<=1?'disabled':''}>×</button></div></article>`).join('')}</div></section>`;
 }
 async saveIdentity(id){
  if(this.saving)return;this.saving=true;
  try{
   const response=await this.projectUI.api('/api/workspace',{method:'POST',body:{action:'set_default_bot',platform_id:id}});
   this.projectUI.preferences=response.result;this.projectUI.selectIdentity(id);this.render();this.projectUI.notify('默认机器人已保存，下次打开自动进入。');
  }catch(error){this.projectUI.notify(error.message,'error');}finally{this.saving=false;}
 }
 async saveProgress(){
  if(this.saving)return;this.saving=true;
  const button=document.querySelector('[data-nav-action="save-progress"]');if(button)button.disabled=true;
  try{
   const response=await this.projectUI.api('/api/workspace',{method:'POST',body:{action:'set_progress',platform_id:this.projectUI.identityId,enabled:document.getElementById('progress-enabled').checked,min_interval_seconds:Number(document.getElementById('progress-interval').value)}});
   this.projectUI.preferences=response.result;this.projectUI.notify('进展简报设置已保存。');
  }catch(error){this.projectUI.notify(error.message,'error');}finally{this.saving=false;if(button)button.disabled=false;}
 }
 renderSessions(){
  const e=this.esc,b=this.projectUI.identities.find(b=>b.platform_id===this.projectUI.identityId);
  return (b?.sessions||[]).map(s=>`<div><strong>${e(b.label)} <span>${e(s.label)}</span></strong><code>${e(s.umo)}</code><small>配置 Persona：${e(s.persona||'沿用会话配置')}</small></div>`).join('')||'<div class="empty">暂无已记录来源，从这台 Bot 的管理员私聊立项后会自动出现。</div>';
 }
 renderSettings(container){
  const e=this.esc,identities=this.projectUI.identities||[],selected=this.projectUI.identityId,prefs=this.projectUI.preferences;
  const heading=this.header('设置','选择 AstrBot 中实际启用的机器人，配置任务消息与集成。');
  const tabs=`<nav class="settings-tabs" aria-label="设置分类">${[['identity','机器人身份'],['messages','任务消息'],['integrations','插件与集成']].map(([id,label])=>`<button data-nav-action="settings-tab" data-tab="${id}" class="${this.settingsTab===id?'active':''}">${label}</button>`).join('')}</nav>`;
  if(this.settingsTab==='integrations'){this.renderIntegrations();container.insertAdjacentHTML('afterbegin',heading+tabs);return;}
  if(this.settingsTab==='messages'){
   const config=prefs.progress_by_bot?.[selected]||{enabled:false,min_interval_seconds:60};
   container.innerHTML=`<section class="identity-page">${heading}${tabs}<section class="task-message-settings"><span class="section-label">TASK CHANNEL</span><h2>一条任务线，随时知道做到哪了</h2><p>当前机器人：<strong>${e(this.projectUI.identityLabel())}</strong></p><div class="message-demo"><div><i></i><span>正在排查</span><p>已确认接口变化，接下来检查任务恢复路径。</p></div><div><i></i><span>需要你确认</span><p>反问和审批在同一任务中给出，处理后继续原计划。</p></div><div><i></i><span>交付</span><p>总结已完成的事、未验证项和接续入口。</p></div></div><label class="message-toggle"><input id="progress-enabled" type="checkbox" ${config.enabled?'checked':''} ${!selected?'disabled':''}/><span><strong>向立项管理员发送进展简报</strong><small>开始/完成步骤后按实际进展发送；Bot 也可主动补充。默认关闭。</small></span></label><label class="message-interval">简报最短间隔<select id="progress-interval">${[[30,'30 秒'],[60,'1 分钟'],[120,'2 分钟'],[300,'5 分钟'],[600,'10 分钟']].map(([value,label])=>`<option value="${value}" ${config.min_interval_seconds===value?'selected':''}>${label}</option>`).join('')}</select></label><p class="section-note">仅发往任务原管理员私聊，最多600字，按执行事件去重限频，无定时叫醒。反问、审批和交付属于必要控制消息，不受简报开关限制。完整工具日志留在任务记录。</p><button class="button" data-nav-action="save-progress" ${!selected?'disabled':''}>保存消息设置</button></section></section>`;return;
  }
  const statuses={running:'运行中',pending:'连接中',stopped:'已停止',error:'连接异常',unknown:'状态待确认'};
  container.innerHTML=`<section class="identity-page">${heading}${tabs}<div class="identity-explainer"><strong>单击切换，双击设为默认</strong><p>这里只列出 AstrBot 机器人设置中已启用、已加载的实例。默认选择保存在服务端，下次打开自动恢复；已有任务继续沿用原身份。</p></div><div class="identity-grid">${identities.map(b=>`<article class="identity-option"><button class="identity-card ${selected===b.platform_id?'selected':''}" data-nav-action="select-bot" data-bot-id="${e(b.platform_id)}" aria-pressed="${selected===b.platform_id}"><span class="identity-avatar">${e(b.label.slice(0,1))}</span><span><strong>${e(b.label)}</strong><small>${e(b.platform_type)} · ${e(b.platform_id)}</small><small>${e(statuses[b.status]||'状态待确认')} · ${b.sessions?.length||0} 个已记录会话</small></span><i>${prefs.default_bot_id===b.platform_id?'默认':''}</i></button><button class="identity-default" data-nav-action="default-bot" data-bot-id="${e(b.platform_id)}" ${prefs.default_bot_id===b.platform_id?'disabled':''}>${prefs.default_bot_id===b.platform_id?'默认打开此机器人':'设为默认'}</button></article>`).join('')||'<div class="empty">尚无已启用且加载的机器人，请先在 AstrBot 机器人设置中添加或启用。项目历史仍保留。</div>'}</div><section class="identity-sessions"><h2>当前机器人的会话来源</h2><p>实际执行沿用 AstrBot 会话的人设解析。</p><div id="identity-session-list">${this.renderSessions()}</div></section></section>`;
 }
}
