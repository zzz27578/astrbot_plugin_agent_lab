// Scheme -> plugin -> tool. The persisted deny list also applies to full access.
const sentinel='__agent_lab_no_external_tools__';
const aliases={astrbot_sandboxed_shell:'astrbot_execute_shell',astrbot_sandboxed_python:'astrbot_execute_ipython'};
const canonical=name=>aliases[name]||name;
const controllable=tool=>!tool.name.startsWith('agent_lab_')||tool.name==='agent_lab_call_custom_api';
const icons={
  hub:'<path d="M12 3v5m-7 8v5m14-5v5M5 16v-4h14v4M12 8v4"/><rect x="8" y="2" width="8" height="6" rx="2"/><rect x="2" y="16" width="6" height="6" rx="2"/><rect x="16" y="16" width="6" height="6" rx="2"/>',
  plugin:'<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M9 4v16M4 10h16"/>',
  core:'<path d="m8 6-5 6 5 6m8-12 5 6-5 6m-3-14-2 16"/>',
  arrow:'<path d="m9 5 7 7-7 7"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
};
const icon=name=>`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name]||icons.plugin}</svg>`;

export function pluginEnabled(agent,group){
  if(group.hostOff)return false;
  if(group.protected||group.core)return true;
  const override=agent.plugin_overrides?.[group.id];
  return typeof override==='boolean'?override:agent.isolation_policy?.mode!=='strict';
}
export function toolEnabled(agent,tool,group){
  if(tool.active===false||group.hostOff||!pluginEnabled(agent,group))return false;
  if(group.protected)return true;
  if(agent.isolation_policy?.tool_mode==='no_external'||agent.enabled_tools?.includes(sentinel))return false;
  if((agent.disabled_tools||[]).some(name=>canonical(name)===canonical(tool.name)))return false;
  const selected=agent.enabled_tools||[];
  return agent.isolation_policy?.tool_mode==='full'||!selected.length||selected.some(name=>canonical(name)===canonical(tool.name));
}
export function capabilityGroups(agent,state){
  const groups=[{id:'__core__',name:'内置工具',description:'文件、终端与搜索等基础能力',core:true,tools:[]}];
  const byId=new Map(groups.map(g=>[g.id,g]));
  for(const plugin of state.plugins||[]){
    const group={id:plugin.name,name:plugin.display_name||plugin.name,
      description:plugin.description||plugin.desc||'展开查看插件提供的工具',
      hostOff:plugin.activated===false,protected:plugin.name==='astrbot_plugin_agent_lab'||Boolean(plugin.reserved||plugin.locked),tools:[]};
    groups.push(group);byId.set(group.id,group);
  }
  const seen=new Set();
  for(const tool of state.tools||[]){
    if(!tool.name||!controllable(tool)||seen.has(canonical(tool.name)))continue;
    seen.add(canonical(tool.name));
    const id=tool.name==='agent_lab_call_custom_api'?'__core__':tool.plugin_name||'__core__';
    if(!byId.has(id)){
      const group={id,name:id,description:'已注册的扩展能力',tools:[]};groups.push(group);byId.set(id,group);
    }
    byId.get(id).tools.push(tool);
  }
  return groups.sort((a,b)=>Number(Boolean(b.core))-Number(Boolean(a.core))||Number(Boolean(a.protected))-Number(Boolean(b.protected)));
}

function setTool(agent,tool,enabled){
  const name=canonical(tool.name);
  const denied=new Set((agent.disabled_tools||[]).map(canonical));
  if(enabled)denied.delete(name);else denied.add(name);
  agent.disabled_tools=[...denied];
  const previous=(agent.enabled_tools||[]).filter(value=>value!==sentinel);
  const unlimited=!agent.enabled_tools?.length&&agent.isolation_policy?.tool_mode!=='no_external';
  agent.enabled_tools=previous;
  if(enabled&&agent.isolation_policy?.tool_mode==='no_external')agent.isolation_policy.tool_mode='whitelist';
  if(enabled&&!unlimited&&agent.isolation_policy?.tool_mode!=='full'&&!agent.enabled_tools.includes(name))agent.enabled_tools.push(name);
}
export function toggleCapability(agent,state,action,id,enabled){
  agent.isolation_policy||={mode:'strict',tool_mode:'whitelist'};
  agent.plugin_overrides||={};
  const groups=capabilityGroups(agent,state);
  if(action==='all'){
    // Controls remain available even when all external capabilities are off.
    agent.isolation_policy.tool_mode=enabled?'full':'no_external';
    agent.enabled_tools=enabled?[]:[sentinel];
    for(const group of groups){
      if(group.protected||group.hostOff)continue;
      if(!group.core)agent.plugin_overrides[group.id]=enabled;
      const denied=new Set((agent.disabled_tools||[]).map(canonical));
      for(const tool of group.tools){if(enabled)denied.delete(canonical(tool.name));else denied.add(canonical(tool.name));}
      agent.disabled_tools=[...denied];
    }
    return;
  }
  const group=groups.find(group=>action==='group'?group.id===id:group.tools.some(tool=>tool.name===id));
  if(!group||group.protected||group.hostOff)return;
  if(action==='group'){
    if(!group.core)agent.plugin_overrides[group.id]=enabled;
    for(const tool of group.tools){if(tool.active!==false)setTool(agent,tool,enabled);}
  }else{
    const tool=group.tools.find(tool=>tool.name===id);
    if(tool.active===false)return;
    if(enabled&&!group.core)agent.plugin_overrides[group.id]=true;
    setTool(agent,tool,enabled);
  }
}

export function renderCapabilityGraph(agent,state,esc,expanded=new Set()){
  const groups=capabilityGroups(agent,state);
  const total=groups.reduce((n,g)=>n+g.tools.length,0);
  const enabled=groups.reduce((n,g)=>n+g.tools.filter(t=>toolEnabled(agent,t,g)).length,0);
  const editable=groups.filter(g=>!g.protected).length;
  const toggle=(action,id,on,disabled,label)=>`<button type="button" class="capability-switch" role="switch" aria-checked="${on}" aria-label="${esc(label)}" data-capability-action="${action}" data-capability-id="${esc(id)}" ${disabled?'disabled':''}><span></span></button>`;
  return `<section class="scheme-capabilities" aria-label="方案能力连接图">
    <div class="scheme-graph-toolbar"><div><span class="section-label">CAPABILITY MAP</span><h2>把能力接入你的方案</h2><p>插件是一个节点，工具收在节点里。展开后，可以单独调整。</p></div><div class="scheme-bulk-actions"><button class="button secondary" type="button" data-capability-action="disable-all">全部禁用</button><button class="button" type="button" data-capability-action="enable-all">全部启用</button></div></div>
    <div class="scheme-graph-surface"><div class="scheme-root-node"><span class="scheme-node-icon">${icon('hub')}</span><div><strong>${esc(agent.name||'当前方案')}</strong><span>${editable} 个能力分组 · ${enabled} / ${total} 个工具已接入</span></div><span class="scheme-root-status">${enabled?'能力已连接':'外部能力已关闭'}</span></div>
    <div class="scheme-graph-trunk" aria-hidden="true"></div><div class="scheme-node-grid">${groups.map((group,index)=>{
      const count=group.tools.filter(t=>toolEnabled(agent,t,group)).length;
      const on=group.core?count>0:pluginEnabled(agent,group)&&agent.isolation_policy?.tool_mode!=='no_external';
      const stateLabel=group.hostOff?'宿主已停用':group.protected?'任务控制 · 受保护':on?'已接入':'未接入';
      return `<details class="scheme-capability-node ${on?'is-on':''} ${group.protected?'is-protected':''}" data-capability-group="${esc(group.id)}" ${expanded.has(group.id)?'open':''}><summary><span class="scheme-node-icon">${icon(group.core?'core':'plugin')}</span><span class="scheme-node-title"><strong>${esc(group.name)}</strong><small>${esc(stateLabel)}${group.tools.length?` · ${count}/${group.tools.length} 工具`:''}</small></span>${toggle('group',group.id,on,group.hostOff||group.protected,`${group.name}整组启用或禁用`)}<span class="scheme-expand-icon">${icon('arrow')}</span></summary>
      <div class="scheme-node-content"><p>${esc(group.description)}</p>${group.tools.length?`<div class="scheme-tool-branches">${group.tools.map(tool=>`<div class="scheme-tool-node ${toolEnabled(agent,tool,group)?'is-on':''}"><span class="scheme-tool-status" aria-hidden="true"></span><div><strong>${esc(tool.display_name||tool.name)}</strong><small title="${esc(tool.description||'')}">${esc((tool.description||'').slice(0,140))}</small></div>${toggle('tool',tool.name,toolEnabled(agent,tool,group),group.protected||group.hostOff||tool.active===false,`${tool.name}启用或禁用`)}</div>`).join('')}</div>`:`<div class="scheme-node-empty">${group.protected?'计划、审批和停止等任务控制始终保留。':'这个插件没有注册模型工具，开关作用于插件本身。'}</div>`}</div></details>`;
    }).join('')}</div></div><p class="scheme-graph-note">宿主停用的能力不能在这里开启。全部禁用仍保留任务控制；技能直接沿用 AstrBot 和当前人设配置。</p>
  </section>`;
}
