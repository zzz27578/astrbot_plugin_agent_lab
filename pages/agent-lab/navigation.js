import {safeSession} from './ui-runtime.js?v=025';
export const settingsIcon='<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><path d="m9.5 3-.6 2.5-2.2 1.3-2.5-.7-2.5 4.3 1.9 1.8v2.6l-1.9 1.8 2.5 4.3 2.5-.7 2.2 1.3.6 2.5h5l.6-2.5 2.2-1.3 2.5.7 2.5-4.3-1.9-1.8v-2.6l1.9-1.8-2.5-4.3-2.5.7-2.2-1.3-.6-2.5z" transform="translate(1 -1) scale(.92)"/><circle cx="12" cy="12" r="3.2"/></svg>';
export class Navigation {
 constructor({esc,projectUI,render,openWorkflow,newPreset,savePreset,deletePreset,duplicatePreset,renderIntegrations}){
  Object.assign(this,{esc,projectUI,render,openWorkflow,newPreset,savePreset,deletePreset,duplicatePreset,renderIntegrations});
  this.settingsTab='identity';this.presetQuery='';
  document.addEventListener('click',e=>{
   const b=e.target.closest('[data-nav-action]');if(!b)return;e.preventDefault();
   const action=b.dataset.navAction;
   if(action==='settings-tab'){this.settingsTab=b.dataset.tab;this.render();}
   if(action==='select-bot'){this.projectUI.selectIdentity(b.dataset.botId);safeSession.setItem('agent_lab_bot_scope',b.dataset.botId);this.render();}
   if(action==='open-preset')this.openWorkflow(b.dataset.id);
   if(action==='new-preset')this.newPreset();
   if(action==='edit-preset')void this.savePreset(b.dataset.id);
   if(action==='duplicate-preset')void this.duplicatePreset(b.dataset.id);
   if(action==='delete-preset')void this.deletePreset(b.dataset.id);
  });
  document.addEventListener('input',e=>{if(e.target.id==='preset-search'){this.presetQuery=e.target.value;document.querySelectorAll('[data-preset-search]').forEach(el=>el.hidden=!el.dataset.presetSearch.includes(this.presetQuery.toLowerCase()));}});
 }
 header(title,subtitle,actions=''){return `<header class="page-heading"><div><p class="section-label">AGENT LAB</p><h1>${title}</h1><p>${subtitle}</p></div><div class="page-heading-actions">${actions}</div></header>`;}
 renderPresets(container,agents){
  const e=this.esc;
  container.innerHTML=`<section class="presets-page">${this.header('工作流预案','描述适用任务与处理步骤，供 Bot 选择；不适用时可直接略过。','<button class="button" data-nav-action="new-preset">＋ 新建预案</button>')}
   <div class="preset-search-row"><input id="preset-search" aria-label="搜索工作流预案" placeholder="搜索名称、用途…" value="${e(this.presetQuery)}"/><span>${agents.length} 份预案 · 项目可关联常用预案</span></div>
   <div class="preset-list">${agents.map(a=>`<article class="preset-row" ${!((a.name||'')+' '+(a.description||'')).toLowerCase().includes(this.presetQuery.toLowerCase())?'hidden':''} data-preset-search="${e((a.name+' '+a.description).toLowerCase())}"><div class="preset-symbol">↳</div><div class="preset-info"><h2>${e(a.name||a.agent_id)}${a.enabled===false?'<span class="neutral-badge">未启用</span>':''}</h2><p>${e(a.description||'补充简洁用途，让 Bot 更准确地选择这份预案。')}</p><small>${a.workflow_nodes?.length||0} 节点 · ${a.workflow_edges?.length||0} 连线</small></div><div class="preset-actions"><button class="button secondary" data-nav-action="edit-preset" data-id="${e(a.agent_id)}">用途</button><button class="button secondary" data-nav-action="duplicate-preset" data-id="${e(a.agent_id)}">复制</button><button class="button" data-nav-action="open-preset" data-id="${e(a.agent_id)}">编辑画布</button><button class="icon-only danger-text" data-nav-action="delete-preset" data-id="${e(a.agent_id)}" title="删除预案" aria-label="删除 ${e(a.name)}" ${agents.length<=1?'disabled':''}>×</button></div></article>`).join('')}</div></section>`;
 }
 renderSettings(container){
  const e=this.esc, identities=this.projectUI.identities||[], selected=this.projectUI.identityId;
  const heading=this.header('设置','机器人身份、工具与集成。选择查看范围，不改动 Bot 的模型或运行配置。');
  const tabs=`<nav class="settings-tabs" aria-label="设置分类"><button data-nav-action="settings-tab" data-tab="identity" class="${this.settingsTab==='identity'?'active':''}">机器人身份</button><button data-nav-action="settings-tab" data-tab="integrations" class="${this.settingsTab==='integrations'?'active':''}">插件与集成</button></nav>`;
  if(this.settingsTab==='integrations'){
   this.renderIntegrations();container.insertAdjacentHTML('afterbegin',heading+tabs);return;
  }
  container.innerHTML=`<section class="identity-page">${heading}${tabs}<div class="identity-explainer"><strong>按实例区分，而不是按平台类型</strong><p>同为 QQ 的两个 Bot 也拥有不同平台实例 ID。项目和任务按来源绑定；切换这里只过滤当前工作台，已有任务仍在原 Bot 身份下运行。</p></div>
    <div class="identity-grid"><button class="identity-card ${selected==='*'?'selected':''}" data-nav-action="select-bot" data-bot-id="*"><span class="identity-avatar">∷</span><span><strong>全部机器人</strong><small>跨实例查看项目，创建时仍需明确来源</small></span><i>${selected==='*'?'✓':''}</i></button>
    ${identities.map(b=>`<button class="identity-card ${selected===b.platform_id?'selected':''}" data-nav-action="select-bot" data-bot-id="${e(b.platform_id)}"><span class="identity-avatar">${e(b.label.slice(0,1))}</span><span><strong>${e(b.label)}</strong><small>${e(b.platform_type||'历史来源')} · ${e(b.platform_id)}</small><small>${b.known?'已加载平台实例':'历史实例，当前未加载'} · ${b.sessions?.length||0} 个已记录会话</small></span><i>${selected===b.platform_id?'✓':''}</i></button>`).join('')}
    <button class="identity-card ${selected==='unbound'?'selected':''}" data-nav-action="select-bot" data-bot-id="unbound"><span class="identity-avatar">?</span><span><strong>未分配来源</strong><small>在首次立项时绑定明确的 Bot 会话</small></span><i>${selected==='unbound'?'✓':''}</i></button></div>
    <section class="identity-sessions"><h2>当前范围的会话来源</h2><p>会话内 Persona 可以不同。此处显示来源配置；实际执行沿用 AstrBot 会话的人设解析。</p>${identities.filter(b=>selected==='*'||b.platform_id===selected).flatMap(b=>(b.sessions||[]).map(session=>`<div><strong>${e(b.label)} <span>${e(session.label)}</span></strong><code>${e(session.umo)}</code><small>配置 Persona：${e(session.persona||'沿用会话配置')}</small></div>`)).join('')||'<div class="empty">暂无已记录来源。可从对应 Bot 的管理员私聊中建立第一个项目。</div>'}</section></section>`;
 }
}
