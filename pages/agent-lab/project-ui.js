import {safeSession} from './ui-runtime.js?v=026';
const icon = (name, size = 18) => {
  const shapes = {
    folder: '<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    task: '<rect x="5" y="3" width="14" height="18" rx="3"/><path d="m8 10 2 2 5-5M8 16h8"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    arrow: '<path d="m9 5 7 7-7 7"/>',
    storage: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7"/>',
    pause: '<path d="M8 5v14M16 5v14"/>',
    play: '<path d="m7 4 13 8-13 8z"/>',
    check: '<path d="m4 12 5 5L20 6"/>',
    chat: '<path d="M21 11a9 9 0 0 1-9 9H3l2-5a9 9 0 1 1 16-4z"/>',
    search: '<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
    flow: '<rect x="3" y="3" width="6" height="6" rx="2"/><rect x="15" y="15" width="6" height="6" rx="2"/><path d="M9 6h9v9M6 9v9h9"/>',
  };
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[name] || shapes.task}</svg>`;
};
const labels = {running:"执行中",paused:"已暂停",blocked:"待处理",completed:"已交付",cancelled:"已停止",pending:"待审批",approved:"已批准",consumed:"已使用",rejected:"已拒绝",expired:"已失效"};
const budgetFields = [["max_total_tokens","总 Token 预算",0,50000000],["max_tokens_per_tick","每轮 Token 预算",0,1000000],["max_total_tool_calls","任务工具总上限",0,100000],["max_total_ticks","总轮数",0,100000],["max_nodes_per_tick","每轮节点上限",1,200],["max_seconds_per_tick","每轮秒数",1,3600]];
const continuityFields = [["context_tokens","任务上下文容量（Token）",2000,10000000,1000000],["context_percent","整理触发比例（%）",30,90,70],["max_stage_ticks","阶段连续轮数上限",1,1000,8],["summary_chars","交接摘要最多字数",1000,20000,6000]];
const splitLines = value => value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean);
export const bytes = value => {const n=Number(value)||0;return n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(1)} KB` : `${(n/1048576).toFixed(1)} MB`;};

export class ProjectUI {
  constructor({api, esc, open, refresh, modal, notify, workflow}) {
    Object.assign(this, {api, esc, open, refresh, modal, notify, workflow});
    this.data = {projects:[]}; this.projectId = ""; this.taskId = ""; this.detail = null;
    this.allData={projects:[]};this.identities=[];this.identityId='';this.identityInitialized=false;
    this.preferences={default_bot_id:'',progress_by_bot:{}};
    this.expanded = new Set(); this.tab = "tasks"; this.search = ""; this.busy = false;
    this.drafts = new Map();
    this.execution = new Map();
    this.summarySaves = new Map();
    this.summaryStatus = new Map();
    this.selectionVersion = 0;
    document.addEventListener("click", e => {
      const button = e.target.closest("[data-project-action]");
      if (!button || button.disabled) return;
      e.preventDefault(); e.stopPropagation();
      void this.action(button).catch(error => this.notify(error.message, "error"));
    });
    document.addEventListener("input", e => {
      if (e.target.closest(".project-workspace") && e.target.id && !e.target.matches("[data-summary-setting]")) {
        this.drafts.set(`${this.projectId}:${this.taskId}:${e.target.id}`, e.target.type === "checkbox" ? e.target.checked : e.target.value);
      }
      if (e.target.id === "project-search") {
        this.search = e.target.value;
        const cards = document.querySelectorAll("[data-search-text]");
        cards.forEach(card => { card.hidden = !card.dataset.searchText.includes(this.search.toLowerCase()); });
      }
    });
    document.addEventListener("change", e => {
      if (e.target.matches("[data-summary-setting]")) this.saveSummarySetting(e.target);
      if (e.target.matches("#execution-mode")) this.drafts.set(`${this.projectId}:${this.taskId}:${e.target.id}`, e.target.value);
    });
    document.addEventListener("submit", e => {
      if (!e.target.matches("#project-execution-form")) return;
      e.preventDefault();
      void this.action(e.submitter || e.target.querySelector('[data-project-action="save-execution"]')).catch(error => this.notify(error.message, "error"));
    });
  }
  setData(data) {
    this.allData=data||{projects:[]};this.identities=this.allData.identities||[];
    this.preferences=this.allData.preferences||{default_bot_id:'',progress_by_bot:{}};
    if(!this.identityInitialized||!this.identities.some(b=>b.platform_id===this.identityId)){
      this.identityId=this.identities.find(b=>b.platform_id===this.preferences.default_bot_id)?.platform_id||this.identities[0]?.platform_id||'';
      this.identityInitialized=true;
    }
    this.filterIdentity();
  }
  filterIdentity(){
    const projects=(this.allData.projects||[]).filter(p=>this.identityId&&p.platform_id===this.identityId);
    this.data={...this.allData,projects,total_bytes:projects.reduce((n,p)=>n+(p.bytes||0),0),cache_bytes:projects.reduce((n,p)=>n+(p.cache_bytes||0),0)};
    if (this.projectId && !this.data.projects.some(p => p.project_id === this.projectId)) {
      this.projectId = ""; this.taskId = ""; this.detail = null;
    }
  }
  selectIdentity(id){this.identityId=id;this.projectId='';this.taskId='';this.detail=null;this.tab='tasks';++this.selectionVersion;this.filterIdentity();}
  identityLabel(){return this.identities.find(b=>b.platform_id===this.identityId)?.label||'尚未配置机器人';}
  projectBotName(project){return this.identities.find(b=>b.platform_id===project.platform_id)?.label||project.platform_id||'未分配来源';}
  sidebar() {
    const e = this.esc;
    return `<div class="project-tree-head"><span>项目</span><button data-project-action="create" title="新建项目" aria-label="新建项目">${icon("plus",16)}</button></div>
      <div class="project-tree" role="tree" aria-label="项目与任务">
      ${this.data.projects.map(p => `<div class="project-tree-group" role="treeitem" aria-expanded="${this.expanded.has(p.project_id)}">
        <div class="project-tree-row ${this.projectId===p.project_id?"selected":""}">
          <button class="project-chevron ${this.expanded.has(p.project_id)?"open":""}" data-project-action="expand" data-project-id="${e(p.project_id)}" aria-label="展开或收起 ${e(p.title)}">${icon("arrow",13)}</button>
          <button class="project-tree-title" data-project-action="select" data-project-id="${e(p.project_id)}" title="${e(this.projectBotName(p))} · ${e(p.platform_id||'未绑定')} · ${e(p.title)}">${icon("folder",16)}<span>${e(p.title)}</span><small>${p.tasks.length}</small></button>
        </div><div class="project-tree-children ${this.expanded.has(p.project_id)?"open":""}" role="group"><div>
          ${p.tasks.slice(0,30).map(t => `<button class="project-tree-task ${this.taskId===t.task_id?"selected":""}" data-project-action="task" data-project-id="${e(p.project_id)}" data-task-id="${e(t.task_id)}"><span class="project-dot ${e(t.status)}"></span><span>${e(t.title)}</span>${t.question_count?'<span class="project-needs-input">?</span>':""}</button>`).join("")}
          ${p.tasks.length>30?`<button data-project-action="select" data-project-id="${e(p.project_id)}">查看全部 ${p.tasks.length} 个任务</button>`:""}
        </div></div></div>`).join("") || `<p class="project-tree-empty">让 Bot 创建项目，相关任务会在这里归档。</p>`}</div>
        `;
  }
  footer(){return `<button class="project-storage-link" data-project-action="storage">${icon('storage',16)}<span>存储与清理</span><strong>${bytes(this.data.total_bytes)}</strong></button>`;}
  render(container) {
    this.container = container;
    const p = this.data.projects.find(p => p.project_id===this.projectId);
    const e = this.esc;
    container.innerHTML = `<div class="project-workspace">
      <header class="project-header"><div><p class="project-eyebrow">AGENT LAB / PROJECTS</p>
        <h1>${p?e(p.title):this.tab==='storage'?'存储与清理':"项目"}</h1><p>${p?`${e(this.projectBotName(p))} · ${e(p.category)} · ${p.tasks.length} 个任务 · 记录 ${bytes(p.bytes)}`:`${e(this.identityLabel())} · 计划、记录和项目记忆，一处整理。`}</p></div>
        <div class="project-header-actions"><button class="button secondary" data-project-action="refresh">刷新</button><button class="button" data-project-action="${p?"new-task":"create"}" data-project-id="${e(p?.project_id||"")}">${icon("plus",16)}${p?"新建任务":"新建项目"}</button></div></header>
      ${p?this.renderProject(p):this.tab==='storage'?this.renderStorage():this.renderOverview()}
    </div>`;
    if (this.busy) container.querySelectorAll("button").forEach(b => { b.disabled = true; });
    container.querySelectorAll("input[id],textarea[id],select[id]").forEach(el=>{
      const key=`${this.projectId}:${this.taskId}:${el.id}`;
      if(this.drafts.has(key)) { if(el.type==="checkbox")el.checked=this.drafts.get(key);else el.value=this.drafts.get(key); }
    });
  }
  renderOverview() {
    const e=this.esc, projects=this.data.projects;
    return `<div class="project-hero-strip"><div><strong>${projects.length}</strong><span>项目</span></div><div><strong>${projects.reduce((n,p)=>n+p.tasks.length,0)}</strong><span>任务记录</span></div><div><strong>${bytes(this.data.cache_bytes)}</strong><span>日志缓存</span></div></div>
      <label class="project-search">${icon("search")}<input id="project-search" placeholder="查找项目或分类…" value="${e(this.search)}" /></label>
      <div class="project-folder-grid">${projects.map((p,i)=>`<article class="project-folder-card" ${!(p.title+" "+p.category).toLowerCase().includes(this.search.toLowerCase())?"hidden":""} data-search-text="${e((p.title+" "+p.category).toLowerCase())}" style="--entry-delay:${Math.min(i*35,210)}ms">
        <button class="project-folder-open" data-project-action="select" data-project-id="${e(p.project_id)}"><span class="project-folder-icon">${icon("folder",28)}</span><span class="project-category">${e(p.category)}</span><h2>${e(p.title)}</h2><p>${e(p.summary||"还没有项目摘要。Bot 完成工作后会写交接记录。")}</p><footer><span>${e(this.projectBotName(p))} · ${p.tasks.length} 个任务</span><span>${bytes(p.bytes)} ${icon("arrow",14)}</span></footer></button>
        </article>`).join("") || `<div class="project-empty"><span>${icon("folder",40)}</span><h2>从一件具体的事开始</h2><p>对 Bot 说“为这个插件建一个项目”，或手动创建目录。</p><button class="button" data-project-action="create">创建第一个项目</button></div>`}</div>`;
  }
  renderStorage(){const e=this.esc;return `<section class="storage-overview"><div class="storage-explanation"><h2>${bytes(this.data.total_bytes)}</h2><p>当前机器人范围内的项目记录文件。任务对话的内容大小在清理预览中另列，数据库文件不会按此数值立刻收缩。</p></div><div class="storage-project-list">${this.data.projects.map(p=>`<button data-project-action="storage-project" data-project-id="${e(p.project_id)}"><span>${icon('folder')}<strong>${e(p.title)}</strong></span><span>${p.tasks.length} 个任务</span><span>${bytes(p.bytes)}</span><span>查看与清理 ${icon('arrow',14)}</span></button>`).join('')||'<div class="empty">当前范围没有项目记录。</div>'}</div></section>`;}
  renderProject(p) {
    const e=this.esc, task = this.detail?.task;
    const tabs=[["tasks","任务"],["memory","摘要与存储"],["workflows","预案"],["tools","开发保护"]];
    return `<div class="project-toolbar"><nav>${tabs.map(([id,label])=>`<button class="${this.tab===id?"active":""}" data-project-action="tab" data-tab="${id}">${label}</button>`).join("")}</nav><button class="project-text-button" data-project-action="rename" data-project-id="${e(p.project_id)}">编辑分类</button></div>
      ${this.tab==="tasks"?`<div class="project-task-layout"><section class="project-task-list">${p.tasks.map(t=>`<button class="project-task-row ${t.task_id===this.taskId?"selected":""}" data-project-action="task" data-task-id="${e(t.task_id)}" data-project-id="${e(p.project_id)}"><span class="project-dot ${e(t.status)}"></span><div><strong>${e(t.title)}</strong><p>${e(t.summary||"等待 Bot 记录进展")}</p><small>${e(labels[t.status]||t.status)} · ${bytes(t.bytes)}${t.question_count?" · 等待回答":""}</small></div>${icon("arrow",15)}</button>`).join("")||'<div class="project-empty"><h3>这个项目还没有任务</h3><p>新任务与以往记录分开，交接时只引用摘要。</p></div>'}</section>
      <section class="project-task-detail">${task&&p.tasks.some(t=>t.task_id===task.task_id)?this.renderTask(task):'<div class="project-empty"><h3>选择一个任务</h3><p>查看计划、待回答问题、记录和存储明细。</p></div>'}</section></div>`:""}
      ${this.tab==="memory"?`<section class="project-memory-panel"><div class="project-memory-heading">${icon("storage",24)}<div><h2>存储透明，清理有范围</h2><p>${e(p.storage_path)} · 文件 ${bytes(p.bytes)} · 日志缓存 ${bytes(p.cache_bytes)}</p></div></div>
        <div class="project-summary"><span class="project-eyebrow">项目摘要</span><p>${e(p.summary||"暂无摘要。选中任务后可让 Bot 草拟，或直接写入项目交接说明。")}</p></div>
        ${this.renderSummarySettings(p)}
        <div class="project-clean-actions"><button class="button secondary" data-project-action="cleanup" data-mode="cache">${icon("storage",16)}预览清理缓存</button><button class="button secondary" data-project-action="cleanup" data-mode="history">删除项目任务历史…</button><button class="button danger" data-project-action="cleanup" data-mode="project">删除项目…</button></div>
        <p class="project-hint">缓存清理保留计划、证据编号和摘要。历史/项目删除会删除对应记录、记忆与任务对话；不会删除开发源码目录。原生对话大小在清理预览中单独计算。所有项目共用的索引与历史记忆文件共 ${bytes(this.data.shared_metadata_bytes)}，不重复分摊到每个项目。</p></section>`:""}
      ${this.tab==="workflows"?`<section class="project-memory-panel"><h2>这个项目的常用预案</h2><p class="project-hint">Bot 按标题和简介选择。没有合适预案可以略过，不影响任务立项。</p><div class="project-workflow-list">${(this.agents||[]).map(a=>`<label><input type="checkbox" name="project-workflow" value="${e(a.agent_id)}" ${(p.workflow_ids||[]).includes(a.agent_id)?"checked":""}/><span><strong>${e(a.name||a.agent_id)}</strong><small>${e(a.description||"暂无简介")}</small></span><button type="button" class="project-text-button" data-project-action="workflow" data-agent-id="${e(a.agent_id)}">${icon("flow",16)}打开画布</button></label>`).join("")}</div><button class="button" data-project-action="save-workflows">保存项目预案关联</button></section>`:""}
      ${this.tab==="tools"?this.renderExecutionSettings(p)+this.renderDeveloperTools():""}`;
  }
  renderSummarySettings(p) {
    const e=this.esc;
    const rows=[
      ["share_with_daily","daily_summary_chars","日常聊天引用当前项目摘要",false,800,4000],
      ["share_with_tasks","task_summary_chars","同项目任务引用交接摘要",true,3500,12000],
    ];
    return `<section class="project-settings" aria-labelledby="project-summary-settings-title">
      <div class="project-settings-heading"><h3 id="project-summary-settings-title">摘要互通</h3><span id="project-summary-settings-status" role="status">${e(this.summaryStatus.get(p.project_id)||"自动保存")}</span></div>
      ${rows.map(([toggle,limit,label,enabled,defaultValue,max])=>`<div class="project-settings-row">
        <label class="project-check"><input type="checkbox" data-summary-setting="${toggle}" ${(p[toggle]??enabled)?"checked":""}/> ${label}</label>
        <label class="project-summary-limit"><span>最多字数</span><input type="number" aria-label="${label}最多字数" data-summary-setting="${limit}" value="${e(p[limit]??defaultValue)}" min="1" max="${max}" step="1" required/><span>字</span></label>
      </div>`).join("")}
    </section>`;
  }
  saveSummarySetting(field) {
    const key=field.dataset.summarySetting, projectId=this.projectId;
    const status=(text, error=false)=>{
      this.summaryStatus.set(projectId,text);
      const node=this.projectId===projectId&&this.container?.querySelector("#project-summary-settings-status");
      if(node){node.textContent=text;node.classList.toggle("danger-text",error);}
    };
    if(!field.reportValidity()){status(`请输入 ${field.min}–${field.max} 之间的整数。`,true);return;}
    const value=field.type==="checkbox"?field.checked:field.value;
    status("保存中…");
    const save=(this.summarySaves.get(projectId)||Promise.resolve()).then(async()=>{
      const result=await this.request("update_project",{project_id:projectId,[key]:value});
      const project=this.allData.projects.find(p=>p.project_id===projectId);
      if(project)project[key]=result[key];
    });
    const pending=save.then(()=>{
      if(this.summarySaves.get(projectId)===pending) status("已保存");
    }, error=>{
      if(this.summarySaves.get(projectId)===pending) status(`未保存：${error.message}`,true);
      else this.notify(error.message,"error");
      const node=this.projectId===projectId&&this.container?.querySelector(`[data-summary-setting="${key}"]`);
      const project=this.allData.projects.find(p=>p.project_id===projectId);
      if(node&&project&&(node.type==="checkbox"?node.checked:node.value)===value){
        if(node.type==="checkbox") node.checked=project[key]??(key==="share_with_tasks");
        else node.value=project[key]??(key==="daily_summary_chars"?800:3500);
      }
    }).finally(()=>{if(this.summarySaves.get(projectId)===pending)this.summarySaves.delete(projectId);});
    this.summarySaves.set(projectId,pending);
  }
  renderExecutionSettings(p) {
    const e=this.esc, current=this.execution.get(p.project_id);
    const number=(key,title,min,max,value)=>`<label>${title}<input id="execution-${key}" name="${key}" type="number" min="${min}" max="${max}" step="1" required value="${e(value)}" /></label>`;
    return `<section id="project-execution-settings" class="project-settings project-execution-settings" aria-labelledby="project-execution-title">
      <div class="project-settings-heading"><h2 id="project-execution-title">运行设置</h2></div>
      ${!current?'<p role="status">正在读取运行设置…</p>':current.error?`<p class="danger-text">${e(current.error)}</p><button type="button" class="button secondary" data-project-action="reload-execution">重试</button>`:`
      <form id="project-execution-form">
        <fieldset><legend>权限与范围</legend>
          <div class="project-settings-grid">
            <label>权限档位<select id="execution-mode" name="mode">${[["readonly","只读"],["standard","标准开发"],["full","完全访问 · 保留高危审批"]].map(([id,label])=>`<option value="${id}" ${current.mode===id?"selected":""}>${label}</option>`).join("")}</select></label>
            <label>预计绝对路径（每行一项）<textarea id="execution-roots" name="roots" rows="2">${e(current.roots.join("\n"))}</textarea></label>
            <label>风险警告线（每行一项）<textarea id="execution-warnings" name="warnings" rows="2" placeholder="审批:工具名或路径通配">${e(current.warnings.join("\n"))}</textarea></label>
            <label>任务指引<textarea id="execution-task_prompt" name="task_prompt" rows="2" maxlength="4000">${e(current.task_prompt)}</textarea></label>
          </div>
        </fieldset>
        <fieldset><legend>长任务与上下文</legend>
          <div class="project-settings-grid">
            ${continuityFields.map(([key,label,min,max,fallback])=>number(key,label,min,max,current.continuity?.[key]??fallback)).join("")}
          </div>
          <p class="project-hint">默认上下文容量为 1M Token；模型配置容量更小时取较小值。阶段结束、达到连续轮数或容量比例时，先保存交接再整理历史，阶段未完成会接着执行。此组设置下轮生效，累计预算不会重置。</p>
        </fieldset>
        <fieldset><legend>预算与上限</legend>
          <div class="project-settings-grid">
            ${number("native_steps","AstrBot 原生每轮工具上限",1,10000,current.native_steps)}
            ${budgetFields.map(([key,label,min,max])=>number(key,label+(min===0?"（0 不限）":""),min,max,current.budget[key])).join("")}
          </div>
          <p class="project-hint">原生上限写入${current.bound_session?"项目会话使用的 AstrBot 配置档":" AstrBot 默认配置档"}，影响共用此档的会话。其余设置由新任务继承。</p>
        </fieldset>
        <div class="project-settings-footer"><button type="submit" class="button secondary" data-project-action="save-execution">保存运行设置</button></div>
      </form>`}
    </section>`;
  }
  async loadExecution(projectId) {
    this.execution.delete(projectId);
    const renderSection=()=>{
      const section=this.projectId===projectId&&this.tab==="tools"&&this.container?.querySelector("#project-execution-settings");
      const project=this.data.projects.find(p=>p.project_id===projectId);
      if(section&&project) section.outerHTML=this.renderExecutionSettings(project);
    };
    renderSection();
    try {
      this.execution.set(projectId,await this.request("execution_settings",{project_id:projectId}));
    } catch(error) {
      this.execution.set(projectId,{error:error.message});
    }
    renderSection();
  }
  renderDeveloperTools() {
    const e=this.esc;
    const tools=(this.tools||[]).filter(t=>/git|rollback|snapshot|回滚|快照/i.test([t.name,t.plugin_name,t.description].join(" ")));
    return `<section class="project-memory-panel"><h2>沿用 Bot 已有的开发工具</h2><p class="project-hint">修改前先留 Git 差异或快照，恢复前核对范围。工具只有在当前方案启用后才可执行，管理员审批仍有效。</p>
      <div class="project-workflow-list">${tools.map(t=>`<div class="project-tool-row"><strong>${e(t.name)}</strong><small>${e(t.plugin_name||t.source||"AstrBot工具")} · ${t.active===false||t.effective_active===false?"未启用":"已发现"}</small><p>${e(t.description||"")}</p></div>`).join("")||'<p>当前没有发现已注册的 Git/快照工具。可在原“插件与集成”页配置已安装插件。</p>'}</div>
      <div class="project-reference-grid"><a href="https://github.com/SGSxingchen/astrbot_plugin_gitlink" target="_blank" rel="noopener noreferrer"><strong>Git & GitHub 工具</strong><span>仓库读取、差异、分支与提交；按原插件配置接入。</span></a><a href="https://github.com/xuanbaon/astrbot_plugin_snapshot_guard" target="_blank" rel="noopener noreferrer"><strong>AstrBot 快照守卫</strong><span>配置与状态快照；回档前再备份，不等于撤销所有外部动作。</span></a></div>
      <p class="project-hint">上下文 rollback 插件只回退聊天记录。代码、数据库、已发送的消息和 API 请求有各自的恢复边界；这里不会执行隐式 git reset 或自动安装外部插件。</p></section>`;
  }
  renderTask(task) {
    const e=this.esc, c=task.workflow_data?.task_control||{}, ended=["completed","cancelled"].includes(task.status);
    const summary=task.exit_summary||task.current_summary||"", pending=(task.approvals||[]).filter(a=>a.status==="pending");
    const questions=(c.questions||[]).filter(q=>q.status==="pending");
    const unknown=(c.journal||[]).filter(row=>["unknown","started"].includes(row.status));
    const selected=this.data.projects.flatMap(p=>p.tasks).find(t=>t.task_id===task.task_id)?.selected;
    return `<div class="project-detail-top"><span class="project-pill ${e(task.status)}">${e(labels[task.status]||task.status)}</span><code>${e(task.task_id)}</code></div><h2>${e(task.root_goal)}</h2>
      <div class="project-task-actions">${!ended?`${!selected?'<button class="button secondary" data-project-action="activate">切换到此任务</button>':`<button class="button secondary" data-project-action="${task.status==="running"?"pause":"resume"}">${icon(task.status==="running"?"pause":"play",15)}${task.status==="running"?"暂停":"继续"}</button>`}<button class="button" data-project-action="deliver">${icon("check",15)}按现状交付</button><button class="project-text-button danger-text" data-project-action="stop">停止任务</button>`:""}<button class="project-text-button" data-project-action="move">归入项目…</button></div>
      ${(this.detail?.messages||[]).length?`<section class="task-message-timeline"><h3>任务消息线</h3>${this.detail.messages.slice(-8).map(m=>`<article><span>${e({progress:'进展',question:'需要回答',approval:'需要审批',delivery:'交付',status:'状态'}[m.kind]||m.kind)} · ${e(m.status==='sent'?'已发送':m.status==='failed'?'发送未确认':'发送中')}</span><p>${e(m.text)}</p></article>`).join('')}</section>`:''}
      ${questions.map(q=>`<section class="project-question"><div class="project-question-title">${icon("chat")}<strong>Bot 需要你确认</strong></div><h3>${e(q.question)}</h3><p>${e(q.recommendation||"")}</p><div class="project-options">${q.options.map((option,i)=>`<button data-project-action="answer-option" data-question-id="${e(q.id)}" data-option-index="${i}">${e(option)}</button>`).join("")}</div><label>也可以自由回答<input id="answer-${e(q.id)}" placeholder="补充你希望的处理方式…"/></label><button class="button secondary" data-project-action="answer" data-question-id="${e(q.id)}">提交回答</button></section>`).join("")}
      <p class="project-hint">Token：${e(task.budget?.tokens_used ?? 0)} / ${e(task.budget?.max_total_tokens || "不限")} · 每轮工具上限：${e(this.detail.native_steps ?? task.budget?.max_tools_per_tick ?? "—")}</p>
      ${task.wait?.message?`<p class="project-detail-summary">${e(task.wait.message)}</p>`:""}
      ${selected&&task.status==="paused"?'<button class="button secondary" data-project-action="task-budget">调整本任务预算</button>':""}
      ${pending.map(a=>`<details class="project-approval" open><summary>${e(a.operation)}</summary><p>${e(a.reason)}</p><pre>${e(a.impact)}</pre>${a.rollback?`<p>恢复方式：${e(a.rollback)}</p>`:""}${a.calls?.length?`<details><summary>核对 ${a.calls.length} 个操作的参数</summary><pre>${e(JSON.stringify(a.calls.map(c=>({tool:c.tool_name,arguments:c.arguments})),null,2))}</pre></details>`:""}<div class="project-task-actions"><button class="button" data-project-action="approval" data-approval-id="${e(a.approval_id)}" data-approved="true">批准</button><button class="button secondary" data-project-action="approval" data-approval-id="${e(a.approval_id)}" data-approved="false">拒绝</button></div></details>`).join("")}
      ${unknown.length?`<section class="project-question"><h3>有 ${unknown.length} 个操作的结果需要核对</h3><p>中断不代表外部操作没有发生。核对后可以继续；管理员也可以直接停止或按现状交付。</p>${unknown.map(row=>`<details><summary>${e(row.name||"工具")} · ${e(row.id)}</summary><pre>${e(JSON.stringify(row.arguments||{},null,2))}</pre><button class="button secondary" data-project-action="reconcile" data-call-id="${e(row.id)}">记录实际结果</button></details>`).join("")}</section>`:""}
      <p class="project-detail-summary">${e(summary)}</p><ol class="project-steps">${(c.steps||[]).map(step=>`<li class="${step.id===c.current_step_id?"current":""}"><span>${step.status==="completed"?icon("check",13):""}</span><div><strong>${e(step.title)}</strong><p>${e(step.summary||step.instruction)}</p></div></li>`).join("")||"<li>尚未形成具体计划。</li>"}</ol>
      ${c.continuity?.lanes?.[""]?.summary?`<details class="project-storage-details"><summary>阶段交接 · ${e(c.continuity.lanes[""].stage||"")}</summary><p class="project-detail-summary">${e(c.continuity.lanes[""].summary)}</p><p class="project-hint">完整阶段历史可在记录与存储中回查。</p></details>`:""}
      ${!ended&&!c.version?'<button class="button secondary" data-project-action="draft-plan">让 Bot 制定具体计划</button>':""}
      ${!ended?`<label>途中引导<textarea id="project-guidance" rows="2" placeholder="例如：不要修改数据库，先检查配置。"></textarea></label><button class="button secondary" data-project-action="steer">发送引导</button>`:""}
      <details class="project-storage-details"><summary>${icon("storage",15)}记录与存储 <span>${bytes(this.detail.record_bytes)} 文件 + ${bytes(this.detail.native_history_bytes)} 对话内容</span></summary>
        <div class="project-file-list">${(this.detail.files||[]).map(file=>`<div><button class="project-text-button" data-project-action="read-record" data-path="${e(file.path)}"><code>${e(file.path)}</code></button><span>${bytes(file.bytes)}</span></div>`).join("")}</div>
        <div class="project-clean-actions"><button class="button secondary" data-project-action="task-cleanup" data-mode="cache">清理此任务缓存…</button><button class="button danger" data-project-action="task-cleanup" data-mode="history">删除此任务历史…</button></div></details>
      <details class="project-summary-editor"><summary>项目交接摘要</summary><p class="project-hint">只保存已确认发现、未验证项、文件引用和下一步；不把完整日志放进日常聊天。</p><textarea id="project-summary-draft" rows="6">${e(task.exit_summary||task.last_confirmed_progress||"")}</textarea><div class="project-task-actions"><button class="button secondary" data-project-action="draft-summary">让 Bot 草拟</button><button class="button" data-project-action="save-summary">保存到项目</button></div></details>`;
  }
  async request(action, extra={}) {
    const response=await this.api("/api/workspace", {method:"POST",body:{action,project_id:this.projectId,task_id:this.taskId,...extra}});
    return response.result;
  }
  async showTask(id) {
    this.taskId=id; this.tab="tasks"; const version=++this.selectionVersion;
    const detail=await this.request("detail",{task_id:id});
    if(version!==this.selectionVersion)return;
    this.detail=detail; this.open();
  }
  async action(button) {
    const action=button.dataset.projectAction;
    if(this.busy)return;
    if(action==="home"){this.projectId="";this.taskId="";this.tab='tasks';this.open();return;}
    if(action==='storage'){this.projectId='';this.taskId='';this.tab='storage';this.open();return;}
    if(action==='storage-project'){this.projectId=button.dataset.projectId;this.taskId='';this.tab='memory';this.open();return;}
    if(["create","new-task"].includes(action)&&!this.identityId){this.notify("请先在 AstrBot 配置并启用机器人。","error");return;}
    if(action==="expand"){
      const id=button.dataset.projectId;
      this.expanded.has(id)?this.expanded.delete(id):this.expanded.add(id);
      const group=button.closest(".project-tree-group"),open=this.expanded.has(id);
      group?.setAttribute("aria-expanded",String(open));
      group?.querySelector(".project-tree-children")?.classList.toggle("open",open);
      button.classList.toggle("open",open);return;
    }
    if(action==="select"){this.projectId=button.dataset.projectId;this.taskId="";this.detail=null;this.tab="tasks";this.expanded.add(this.projectId);this.open();return;}
    if(action==="tab"){this.tab=button.dataset.tab;this.open();if(this.tab==="tools")await this.loadExecution(this.projectId);return;}
    if(action==="reload-execution"){await this.loadExecution(this.projectId);return;}
    if(action==="workflow"){this.workflow(button.dataset.agentId);return;}
    this.busy=true;button.disabled=true;button.setAttribute("aria-busy","true");
    let rerender=true;
    try {
      if(action==="task"){this.projectId=button.dataset.projectId;await this.showTask(button.dataset.taskId);}
      else if(action==="refresh"){await this.refresh();if(this.tab==="tools")await this.loadExecution(this.projectId);else if(this.taskId)await this.showTask(this.taskId);}
      else if(action==="create") {
        const selected=this.identities.find(b=>b.platform_id===this.identityId);
        const values=await this.modal({title:"新建项目",message:`当前查看身份：${this.identityLabel()}。项目会绑定来源中的平台实例；留空可稍后由 Bot 立项时绑定。`,fields:[{label:"项目名称",value:"",placeholder:"例如：Agent Lab 插件"},{label:"类型",value:"插件开发"},{label:"来源 UMO",value:selected?.sessions?.[0]?.umo||""}]});
        if(!values)return;
        const p=await this.request("create_project",{title:values[0],category:values[1],umo:values[2],platform_id:selected?.platform_id||''});
        this.projectId=p.project_id;this.expanded.add(p.project_id);this.taskId="";await this.refresh();
      } else if(action==="rename") {
        const p=this.data.projects.find(p=>p.project_id===this.projectId);
        const values=await this.modal({title:"整理项目",fields:[{label:"名称",value:p.title},{label:"类型",value:p.category}]});
        if(!values)return;await this.request("update_project",{title:values[0],category:values[1]});await this.refresh();
      } else if(action==="move") {
        const choices=this.data.projects.filter(p=>(!p.source_umo||p.source_umo===this.detail.task.umo)&&(!p.platform_id||p.platform_id===this.detail.task.umo.split(":")[0])).map(p=>[p.project_id,p.title]);
        const values=await this.modal({title:"整理任务归属",fields:[{label:"目标项目",type:"select",value:this.projectId,options:choices}]});
        if(!values)return;await this.request("move_task",{project_id:values[0]});this.projectId=values[0];this.expanded.add(this.projectId);await this.refresh();await this.showTask(this.taskId);
      } else if(action==="new-task") {
        const p=this.data.projects.find(p=>p.project_id===this.projectId);
        const values=await this.modal({title:"在项目中立项",fields:[{label:"任务目标",value:""},{label:"Bot会话来源UMO",value:p.source_umo||""}]});
        if(!values)return;
        await this.api("/api/task/start",{method:"POST",body:{goal:values[0],umo:values[1],project_id:p.project_id,workflow_mode:"none"}});
        await this.refresh();this.notify("已立项，Bot将草拟计划；批准后继续。");
      } else if(action==="save-workflows") {await this.request("update_project",{workflow_ids:[...document.querySelectorAll('[name="project-workflow"]:checked')].map(el=>el.value)});await this.refresh();}
      else if(action==="activate"){await this.request("activate");await this.refresh();await this.showTask(this.taskId);}
      else if(["pause","resume"].includes(action)) {
        const t=this.detail.task;await this.api(`/api/task/${action}`,{method:"POST",body:{umo:t.umo,task_id:t.task_id}});await this.refresh();await this.showTask(t.task_id);
      } else if(["stop","deliver"].includes(action)) {
        const answer=await this.modal({title:action==="stop"?"停止此任务":"按现状交付",message:"管理员指令立即生效。未完成和未验证事项会写入交付说明，不会因计划检查拒绝结束。",fields:[{label:"说明（可选）",value:""}],confirmText:action==="stop"?"停止并归档":"交付并归档",danger:action==="stop"});
        if(!answer)return;await this.request(action,{summary:answer[0]});await this.refresh();await this.showTask(this.taskId);
      } else if(action==="steer") {
        const t=this.detail.task;await this.api("/api/task/control",{method:"POST",body:{umo:t.umo,task_id:t.task_id,action:"steer",message:document.getElementById("project-guidance").value}});await this.showTask(t.task_id);
      } else if(action==="save-execution") {
        const form=button.closest("form"), projectId=this.projectId, taskId=this.taskId;
        if(!form.reportValidity()) {rerender=false;return;}
        const fields=new FormData(form), current=this.execution.get(projectId), native=fields.get("native_steps");
        await this.request("save_execution_settings",{project_id:projectId,...(String(current.native_steps)!==native?{native_steps:native}:{}),settings:{mode:fields.get("mode"),roots:splitLines(fields.get("roots")),warnings:splitLines(fields.get("warnings")),task_prompt:fields.get("task_prompt"),continuity:Object.fromEntries(continuityFields.map(([key])=>[key,fields.get(key)])),budget:Object.fromEntries(budgetFields.map(([key])=>[key,fields.get(key)]))}});
        form.querySelectorAll("[id]").forEach(el=>this.drafts.delete(`${projectId}:${taskId}:${el.id}`));
        await this.loadExecution(projectId);this.notify("项目运行设置已保存。");
      } else if(action==="task-budget") {
        const t=this.detail.task, limits=t.budget||{};
        const fields=[["max_total_tokens","总 Token 预算",50000000],["max_total_tool_calls","工具总上限",100000],["max_total_ticks","总轮数",100000]];
        const values=await this.modal({title:"调整本任务预算",message:`已用 ${limits.tokens_used||0} Token、${limits.tool_calls_used||0} 次工具、${limits.ticks_used||0} 轮。`,fields:fields.map(([key,label,max])=>({label:`${label}（0 不限）`,type:"number",min:0,max,value:limits[key]})),confirmText:"保存额度"});
        if(!values)return;
        await this.request("task_budget",{budget:Object.fromEntries(fields.map(([key],i)=>[key,values[i]]))});await this.showTask(t.task_id);
      } else if(action==="approval") {
        const t=this.detail.task;await this.api("/api/task/approval",{method:"POST",body:{umo:t.umo,task_id:t.task_id,approval_id:button.dataset.approvalId,approved:button.dataset.approved==="true"}});await this.refresh();await this.showTask(t.task_id);
      } else if(action==="reconcile") {
        const values=await this.modal({title:"核对操作结果",fields:[{label:"实际状态",type:"select",value:"failed",options:[["completed","已完成"],["failed","已失败"],["not_started","确认未执行"]]},{label:"核对依据",value:"",placeholder:"文件、返回结果或外部系统记录"}]});
        if(!values)return;const t=this.detail.task;
        await this.api("/api/task/control",{method:"POST",body:{umo:t.umo,task_id:t.task_id,action:"reconcile",call_id:button.dataset.callId,outcome:values[0],message:values[1]}});await this.showTask(t.task_id);
      } else if(action==="answer"||action==="answer-option") {
        const q=(this.detail.task.workflow_data.task_control.questions||[]).find(q=>q.id===button.dataset.questionId);
        const answer=action==="answer-option"?q.options[Number(button.dataset.optionIndex)]:document.getElementById(`answer-${q.id}`).value;
        await this.request("answer",{question_id:q.id,answer});await this.refresh();await this.showTask(this.taskId);
      } else if(action==="draft-summary") {
        const result=await this.request("draft_summary");document.getElementById("project-summary-draft").value=result.summary;this.drafts.set(`${this.projectId}:${this.taskId}:project-summary-draft`,result.summary);rerender=false;this.notify("摘要草稿已生成，核对后保存。");
      } else if(action==="draft-plan") {
        const result=await this.request("draft_plan");await this.refresh();await this.showTask(this.taskId);this.notify(result.message||"计划已更新，请审阅。");
      } else if(action==="save-summary") {await this.request("save_summary",{summary:document.getElementById("project-summary-draft").value});await this.refresh();}
      else if(action==="read-record") {
        const result=await this.request("read_record",{path:button.dataset.path});
        await this.modal({title:"任务记录 · 只读",message:result.path+"\n\n"+result.text+(result.truncated?"\n\n[预览截断，完整内容仍保存在列出的文件中]":""),confirmText:"关闭"});
      }
      else if(action==="cleanup"||action==="task-cleanup") {
        const taskId=action==="task-cleanup"?this.taskId:"", mode=button.dataset.mode;
        const plan=await this.request("cleanup_preview",{task_id:taskId,mode});
        const confirmed=await this.modal({title:mode==="cache"?"清理缓存预览":"删除记录预览",message:`范围：${plan.task_ids.length} 个任务，${plan.files.length} 个文件（${bytes(plan.bytes)}），原生任务对话内容 ${bytes(plan.native_history_bytes)}。\n关联记忆 ${plan.memory_entries} 条，历史模板来源 ${plan.learned_patterns} 项（仅历史/项目删除处理）。\n${mode==="cache"?"保留计划与项目摘要。":"将删除所选任务历史、记忆和对应对话。"}\n不删除开发源码目录。\n\n${plan.files.slice(0,18).map(f=>`${f.path} · ${bytes(f.bytes)}`).join("\n")}${plan.files.length>18?"\n其余文件属于同一预览范围。":""}`,confirmText:"确认清理所列范围",danger:true});
        if(!confirmed)return;
        const result=await this.request("cleanup_confirm",{task_id:taskId,mode,token:plan.token});
        this.taskId="";this.detail=null;if(mode==="project")this.projectId="";await this.refresh();this.notify(result.message);
      }
    } finally {
      this.busy=false;button.disabled=false;button.removeAttribute("aria-busy");
      if(rerender)this.open();
    }
  }
}
