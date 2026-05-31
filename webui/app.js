const $ = (id) => document.getElementById(id);
const EMPTY_TOOLS_SENTINEL = "__agent_lab_no_external_tools__";

const sections = [
  ["dashboard", "仪表盘与列表", "看大盘"],
  ["canvas", "可视化编排画布", "捏任务模式"],
  ["tasks", "任务与记忆控制台", "管状态"],
  ["monitor", "实例与心跳监控", "搞运维"],
  ["integrations", "插件与集成", "装工具"],
];

let state = null;
let route = "dashboard";
let currentAgent = null;
let selectedAgentId = "";
let selectedTaskId = "";
let selectedIntegrationId = "";
let integrationTab = "plugins";

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function token() {
  return sessionStorage.getItem("agent_lab_token") || $("token").value.trim();
}

function setFeedback(message, tone = "normal") {
  $("feedback").textContent = message;
  $("feedback").dataset.tone = tone;
}

function ensureAgent(agent) {
  agent.memory_policy ||= {};
  agent.approval_policy ||= {};
  agent.heartbeat_policy ||= {};
  agent.plugin_overrides ||= {};
  agent.enabled_tools ||= [];
  agent.enabled_skills ||= [];
  agent.module_ids ||= [];
  agent.module_settings ||= {};
  agent.identity_label_source ||= "manual";
  return agent;
}

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const currentToken = token();
  if (currentToken) headers["X-Agent-Lab-Token"] = currentToken;
  if (options.body && typeof options.body !== "string") {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function load() {
  try {
    state = await api("/api/state");
    const agents = state.agents || [];
    if (!selectedAgentId || !agents.some((item) => item.agent_id === selectedAgentId)) {
      selectedAgentId = state.default_agent_id || agents[0]?.agent_id || "";
    }
    currentAgent = ensureAgent(clone(agents.find((item) => item.agent_id === selectedAgentId) || agents[0] || {}));
    const tasks = state.tasks || [];
    if (!selectedTaskId || !tasks.some((item) => item.task_id === selectedTaskId)) {
      selectedTaskId = tasks[0]?.task_id || "";
    }
    $("bot-label").textContent = state.runtime?.bot_label || "当前 Bot";
    setFeedback("已连接独立控制台。");
    render();
  } catch (error) {
    setFeedback(`连接失败：${error.message}`, "error");
    renderLocked();
  }
}

function renderNav() {
  $("nav").innerHTML = sections
    .map(
      ([id, title, meta]) => `
        <button class="${route === id ? "active" : ""}" data-route="${id}" type="button">
          <strong>${title}</strong><br />
          <span>${meta}</span>
        </button>
      `,
    )
    .join("");
  const found = sections.find(([id]) => id === route) || sections[0];
  $("section-title").textContent = found[1];
  $("section-kicker").textContent = found[2];
}

function render() {
  renderNav();
  if (!state) return;
  if (route === "dashboard") renderDashboard();
  if (route === "canvas") renderCanvas();
  if (route === "tasks") renderTasks();
  if (route === "monitor") renderMonitor();
  if (route === "integrations") renderIntegrations();
}

function renderLocked() {
  renderNav();
  $("view").innerHTML = `
    <section class="panel">
      <h2>需要连接独立控制台</h2>
      <p class="row-meta">如果你配置了 standalone_webui_token，请在右上角填写 Token 后刷新。</p>
    </section>
  `;
}

function metric(label, value, note = "") {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<div class="row-meta">${esc(note)}</div>` : ""}</div>`;
}

function badge(text, tone = "") {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}

function renderDashboard() {
  const m = state.metrics || {};
  $("view").innerHTML = `
    <section class="grid metrics">
      ${metric("Agent 数量", m.agents ?? 0)}
      ${metric("当前任务", m.active_tasks ?? 0)}
      ${metric("归档任务", m.archived_tasks ?? 0)}
      ${metric("心跳在线", m.heartbeat_online ?? 0)}
      ${metric("待审批", m.pending_approvals ?? 0)}
      ${metric("Token 消耗", m.token_usage ?? 0, "待接入 provider 统计")}
    </section>
    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">资产</p><h2>Agent 列表</h2></div></div>
        <div class="list">${agentRows()}</div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">运行</p><h2>当前任务</h2></div></div>
        <div class="list">${taskRows(state.tasks || [])}</div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><p class="card-kicker">历史</p><h2>最近归档</h2></div></div>
      <div class="list">${taskRows((state.archives || []).slice(0, 8), true)}</div>
    </section>
  `;
}

function agentRows() {
  const agents = state.agents || [];
  if (!agents.length) return `<div class="empty">还没有 AgentSpec。</div>`;
  return agents
    .map((agent) => {
      const selected = agent.agent_id === selectedAgentId;
      const def = agent.agent_id === state.default_agent_id ? "默认 · " : "";
      return `
        <button class="list-row ${selected ? "selected" : ""}" data-action="select-agent" data-id="${esc(agent.agent_id)}" type="button">
          <div class="row-title"><span>${esc(def + (agent.name || "未命名 Agent"))}</span>${badge(agent.enabled === false ? "停用" : "启用", agent.enabled === false ? "bad" : "ok")}</div>
          <div class="row-meta">${esc(agent.agent_id)} · 触发：${esc(agent.trigger_mode || "confirm")}</div>
        </button>
      `;
    })
    .join("");
}

function taskRows(tasks, archive = false) {
  if (!tasks.length) return `<div class="empty">${archive ? "暂无归档任务。" : "暂无 active task。"}</div>`;
  return tasks
    .map(
      (task) => `
        <button class="list-row ${task.task_id === selectedTaskId ? "selected" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
          <div class="row-title"><span>${esc(task.root_goal || task.task_id)}</span>${badge(task.status || "-", task.status === "running" ? "ok" : "warn")}</div>
          <div class="row-meta">${esc(task.agent_name || task.agent_id || "-")} · ${esc(task.task_id)} · 心跳：${task.heartbeat?.enabled ? "开" : "关"}</div>
        </button>
      `,
    )
    .join("");
}

function renderCanvas() {
  currentAgent = ensureAgent(currentAgent || {});
  $("view").innerHTML = `
    <section class="grid two">
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">AgentSpec</p><h2>任务模式配置</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="new-agent" type="button">新建</button>
            <button class="button secondary" data-action="duplicate-agent" type="button">复制</button>
            <button class="button secondary" data-action="make-default" type="button">设为默认</button>
            <button class="button" data-action="save-agent" type="button">保存</button>
          </div>
        </div>
        <div class="form-grid">
          <label>Agent 名称<input id="agent-name" value="${esc(currentAgent.name || "")}" /></label>
          <label>触发模式<select id="trigger-mode">${options(["manual", "confirm", "smart", "always"], currentAgent.trigger_mode || "confirm")}</select></label>
          <label>记忆模式<select id="memory-mode">${options(["inherit", "task_filtered", "strict"], currentAgent.memory_policy.mode || "task_filtered")}</select></label>
          <label>审批模式<select id="approval-mode">${options(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work")}</select></label>
          <label>心跳模式<select id="heartbeat-mode">${options(["off", "manual", "auto"], currentAgent.heartbeat_policy.mode || "manual")}</select></label>
          <label>允许心跳<select id="heartbeat-allowed">${options(["true", "false"], String(currentAgent.heartbeat_policy.allowed !== false))}</select></label>
          <label class="span-2">任务模式补充提示词<textarea id="system-prompt" rows="4">${esc(currentAgent.system_prompt || "")}</textarea></label>
          <label class="span-2">每轮执行协议<textarea id="task-prompt" rows="4">${esc(currentAgent.task_prompt || "")}</textarea></label>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">资产列表</p><h2>选择 Agent</h2></div></div>
        <div class="list">${agentRows()}</div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><p class="card-kicker">流程</p><h2>任务模式工作流</h2></div></div>
      <div class="canvas">
        ${node("入口压缩", "把任务前商量出的计划压缩为 task_brief，不重建人格。", "state")}
        ${node("状态快照", "active_task.json 与 markdown 是任务连续性的真实来源。", "state")}
        ${node("插件隔离", "会话级开启/关闭 AstrBot 插件，工具随插件同步可用性。", "tool")}
        ${node("工具执行", "只把 AgentSpec 选中的注册工具交给 AstrBot Agent Runner。", "tool")}
        ${node("审批闸门", "删除、部署、密钥、重启等危险动作前先软审批。", "guard")}
        ${node("心跳续跑", "长任务由 cron 唤醒：读状态、推进一步、写状态。", "guard")}
      </div>
    </section>
  `;
}

function node(title, text, kind) {
  return `<div class="node" data-kind="${kind}"><strong>${esc(title)}</strong><p>${esc(text)}</p></div>`;
}

function options(values, selected) {
  return values.map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`).join("");
}

function readAgentForm() {
  if (!$("agent-name")) return;
  currentAgent.name = $("agent-name").value.trim() || "未命名 Agent";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.memory_policy.mode = $("memory-mode").value;
  currentAgent.approval_policy.mode = $("approval-mode").value;
  currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").value === "true";
  currentAgent.system_prompt = $("system-prompt").value;
  currentAgent.task_prompt = $("task-prompt").value;
}

function renderTasks() {
  const task = activeTask();
  $("view").innerHTML = `
    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">创建</p><h2>新任务</h2></div></div>
        <div class="form-grid">
          <label>会话 UMO<input id="umo" placeholder="aiocqhttp:FriendMessage:123456" /></label>
          <label>完成条件<input id="completion" value="用户验收通过" /></label>
          <label class="span-2">任务目标<textarea id="goal" rows="3">请把当前任务作为 Agent Mode 管理起来。</textarea></label>
          <label class="span-2">入口补充<textarea id="brief" rows="3"></textarea></label>
        </div>
        <div class="button-row"><button class="button" data-action="start-task" type="button">创建任务</button></div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">Active</p><h2>当前任务</h2></div></div>
        <div class="list">${taskRows(state.tasks || [])}</div>
      </div>
    </section>
    <section class="grid two">
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">状态</p><h2>任务快照</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="tick-task" ${task ? "" : "disabled"} type="button">推进一轮</button>
            <button class="button secondary" data-action="toggle-heartbeat" ${task ? "" : "disabled"} type="button">${task?.heartbeat?.enabled ? "关闭心跳" : "开心跳"}</button>
            <button class="button secondary" data-action="finish-task" ${task ? "" : "disabled"} type="button">完成归档</button>
          </div>
        </div>
        ${task ? taskDetail(task) : `<div class="empty">请选择或创建任务。</div>`}
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">记忆候选</p><h2>出口回流</h2></div></div>
        <pre>${esc((task?.memory_candidates || []).join("\\n") || "任务完成时会在这里生成可审查的记忆候选。")}</pre>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><p class="card-kicker">Archive</p><h2>历史异步任务</h2></div></div>
      <div class="list">${taskRows(state.archives || [], true)}</div>
    </section>
  `;
}

function activeTask() {
  const tasks = state.tasks || [];
  return tasks.find((item) => item.task_id === selectedTaskId) || tasks[0] || null;
}

function taskDetail(task) {
  return `
    <div class="detail-box list-row">
      <div class="row-title"><span>${esc(task.root_goal)}</span>${badge(task.status, task.status === "running" ? "ok" : "warn")}</div>
      <div class="row-meta">状态文件：${esc(task.archive_path || task.task_id)} · UMO：${esc(task.umo)}</div>
    </div>
    <pre>${esc(JSON.stringify({
      current_summary: task.current_summary,
      last_confirmed_progress: task.last_confirmed_progress,
      next_step: task.next_step,
      last_observation: task.last_observation,
      pending_approvals: task.approvals?.filter((item) => item.status === "pending") || [],
    }, null, 2))}</pre>
  `;
}

function renderMonitor() {
  const tasks = state.tasks || [];
  const task = activeTask();
  $("view").innerHTML = `
    <section class="grid three">
      ${metric("运行实例", tasks.length)}
      ${metric("心跳中", tasks.filter((item) => item.heartbeat?.enabled).length)}
      ${metric("异常/阻塞", tasks.filter((item) => item.status === "blocked").length)}
    </section>
    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">心跳</p><h2>实例状态</h2></div></div>
        <div class="list">${tasks.map(instanceRow).join("") || `<div class="empty">暂无运行实例。</div>`}</div>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">操作</p><h2>实时控制</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="toggle-heartbeat" ${task ? "" : "disabled"} type="button">重启心跳</button>
            <button class="button danger" data-action="cancel-task" ${task ? "" : "disabled"} type="button">强制停止任务</button>
          </div>
        </div>
        <pre>${esc(JSON.stringify(task?.progress_log?.slice(-18) || [], null, 2))}</pre>
      </div>
    </section>
  `;
}

function instanceRow(task) {
  const online = task.heartbeat?.enabled;
  return `
    <button class="list-row ${task.task_id === selectedTaskId ? "selected" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
      <div class="row-title"><span>${esc(task.agent_name || task.task_id)}</span>${badge(online ? "心跳在线" : "未开心跳", online ? "ok" : "warn")}</div>
      <div class="row-meta">${esc(task.task_id)} · ${esc(task.heartbeat?.last_pulse_at || "尚无心跳记录")}</div>
    </button>
  `;
}

function renderIntegrations() {
  const tabs = [
    ["plugins", "AstrBot 插件隔离"],
    ["tools", "注册工具"],
    ["skills", "Skills 规则"],
    ["blueprints", "外部方案库"],
  ];
  $("view").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <div><p class="card-kicker">能力边界</p><h2>插件与集成页</h2></div>
        <button class="button" data-action="save-agent" type="button">保存当前 Agent</button>
      </div>
      <div class="tabs">${tabs.map(([id, title]) => `<button class="${integrationTab === id ? "active" : ""}" data-action="integration-tab" data-id="${id}" type="button">${title}</button>`).join("")}</div>
      ${integrationBody()}
    </section>
  `;
}

function integrationBody() {
  if (integrationTab === "plugins") return pluginPanel();
  if (integrationTab === "tools") return toolsPanel();
  if (integrationTab === "skills") return skillsPanel();
  return blueprintsPanel();
}

function pluginPanel() {
  return `<div class="capability-list">${(state.plugins || []).map((plugin) => {
    const locked = plugin.locked || plugin.name === "astrbot_plugin_agent_lab";
    const effective = pluginEffective(plugin);
    return `
      <label class="toggle-row ${locked ? "disabled" : ""}">
        <input type="checkbox" data-action="toggle-plugin" data-id="${esc(plugin.name)}" ${effective ? "checked" : ""} ${locked ? "disabled" : ""} />
        <span><strong>${esc(plugin.display_name || plugin.name)}</strong><br /><small>${esc(plugin.name)} · 全局：${plugin.activated ? "启用" : "停用"}</small></span>
        ${badge(locked ? "受保护" : effective ? "Agent 中开启" : "Agent 中关闭", locked ? "ok" : effective ? "ok" : "bad")}
      </label>
    `;
  }).join("")}</div>`;
}

function pluginEffective(plugin) {
  const override = currentAgent?.plugin_overrides?.[plugin.name];
  if (plugin.locked || plugin.name === "astrbot_plugin_agent_lab") return true;
  return typeof override === "boolean" ? override : Boolean(plugin.activated);
}

function toolsPanel() {
  const selected = new Set(currentAgent.enabled_tools || []);
  const rows = (state.tools || []).map((tool) => {
    const plugin = (state.plugins || []).find((item) => item.name === tool.plugin_name);
    const pluginOn = plugin ? pluginEffective(plugin) : true;
    const checked = selected.has(tool.name) && !selected.has(EMPTY_TOOLS_SENTINEL) && pluginOn && tool.active !== false;
    const disabled = !pluginOn || tool.active === false;
    return `
      <label class="toggle-row ${disabled ? "disabled" : ""}">
        <input type="checkbox" data-action="toggle-tool" data-id="${esc(tool.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
        <span><strong>${esc(tool.name)}</strong><br /><small>${esc(tool.plugin_display_name || tool.source)} · ${esc(tool.description || "无描述")}</small></span>
        ${badge(disabled ? "随插件关闭" : checked ? "已选择" : "未选择", disabled ? "bad" : checked ? "ok" : "")}
      </label>
    `;
  }).join("");
  return `
    <div class="button-row">
      <button class="button secondary" data-action="enable-visible-tools" type="button">启用当前可用工具</button>
      <button class="button secondary" data-action="disable-tools" type="button">禁用外部工具</button>
    </div>
    <div class="capability-list">${rows}</div>
  `;
}

function skillsPanel() {
  const selected = new Set(currentAgent.enabled_skills || []);
  return `<div class="capability-list">${(state.skills || []).map((skill) => `
    <label class="toggle-row">
      <input type="checkbox" data-action="toggle-skill" data-id="${esc(skill.name)}" ${selected.has(skill.name) ? "checked" : ""} />
      <span><strong>${esc(skill.name)}</strong><br /><small>${esc(skill.description || skill.path || "AstrBot Skill")}</small></span>
      ${badge(skill.active ? "已安装" : "未激活", skill.active ? "ok" : "warn")}
    </label>
  `).join("") || `<div class="empty">未读取到 Skills。</div>`}</div>`;
}

function blueprintsPanel() {
  const modules = state.integrations || state.modules || [];
  if (!selectedIntegrationId || !modules.some((item) => item.module_id === selectedIntegrationId)) {
    selectedIntegrationId = modules[0]?.module_id || "";
  }
  const selected = modules.find((item) => item.module_id === selectedIntegrationId);
  const enabled = new Set(currentAgent.module_ids || []);
  const settings = currentAgent.module_settings?.[selectedIntegrationId] || selected?.default_settings || {};
  return `
    <section class="grid two">
      <div class="capability-list">${modules.map((module) => `
        <button class="list-row ${module.module_id === selectedIntegrationId ? "selected" : ""}" data-action="select-integration" data-id="${esc(module.module_id)}" type="button">
          <div class="row-title"><span>${esc(module.name)}</span>${badge(enabled.has(module.module_id) ? "启用" : "未启用", enabled.has(module.module_id) ? "ok" : "")}</div>
          <div class="row-meta">${esc(module.source)} · ${esc(module.description)}</div>
        </button>
      `).join("")}</div>
      <div class="panel">
        ${selected ? `
          <div class="panel-head">
            <div><p class="card-kicker">集成蓝图</p><h2>${esc(selected.name)}</h2></div>
            <button class="button secondary" data-action="toggle-integration" data-id="${esc(selected.module_id)}" type="button">${enabled.has(selected.module_id) ? "从 Agent 移除" : "加入 Agent"}</button>
          </div>
          <p class="row-meta">这里不是 AstrBot 内部插件，而是外部 agent 方案的兼容蓝图：把 LangGraph、OpenAI Agents、CrewAI 等概念翻译成 AgentSpec、TaskState、审批、心跳和记忆规则。</p>
          <label>精细设置 JSON<textarea id="integration-settings" rows="8">${esc(JSON.stringify(settings, null, 2))}</textarea></label>
          <div class="button-row"><button class="button" data-action="save-integration-settings" type="button">保存蓝图设置</button></div>
          <pre>${esc(selected.prompt || "")}</pre>
        ` : `<div class="empty">暂无外部方案蓝图。</div>`}
      </div>
    </section>
  `;
}

async function saveAgent(makeDefault = false) {
  readAgentForm();
  const payload = clone(currentAgent);
  if (makeDefault) payload._make_default = true;
  const result = await api("/api/agents", { method: "POST", body: payload });
  selectedAgentId = result.agent?.agent_id || selectedAgentId;
  setFeedback("AgentSpec 已保存。");
  await load();
}

function toggleListValue(listName, value) {
  const next = new Set(currentAgent[listName] || []);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  currentAgent[listName] = Array.from(next).sort();
}

document.addEventListener("click", async (event) => {
  const target = event.target.closest("[data-route], [data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (target.dataset.route) {
    route = target.dataset.route;
    render();
    return;
  }
  try {
    if (action === "select-agent") {
      selectedAgentId = target.dataset.id;
      currentAgent = ensureAgent(clone((state.agents || []).find((item) => item.agent_id === selectedAgentId)));
      render();
    }
    if (action === "select-task") {
      selectedTaskId = target.dataset.id;
      render();
    }
    if (action === "new-agent") {
      readAgentForm();
      currentAgent = ensureAgent(clone(currentAgent));
      delete currentAgent.agent_id;
      delete currentAgent.created_at;
      delete currentAgent.updated_at;
      currentAgent.name = "新 Agent";
      currentAgent.identity_label_source = "manual";
      render();
    }
    if (action === "duplicate-agent") {
      readAgentForm();
      currentAgent = ensureAgent(clone(currentAgent));
      delete currentAgent.agent_id;
      delete currentAgent.created_at;
      delete currentAgent.updated_at;
      currentAgent.name = `${currentAgent.name || "Agent"} 副本`;
      currentAgent.identity_label_source = "manual";
      render();
    }
    if (action === "save-agent") await saveAgent(false);
    if (action === "make-default") await saveAgent(true);
    if (action === "start-task") {
      await api("/api/task/start", {
        method: "POST",
        body: {
          umo: $("umo").value.trim(),
          goal: $("goal").value,
          completion_conditions: $("completion").value,
          brief: $("brief").value,
          agent_id: currentAgent.agent_id,
        },
      });
      setFeedback("任务已创建。");
      await load();
    }
    if (action === "tick-task") {
      const task = activeTask();
      await api("/api/task/tick", { method: "POST", body: { umo: task.umo } });
      setFeedback("已推进一轮。");
      await load();
    }
    if (action === "toggle-heartbeat") {
      const task = activeTask();
      await api("/api/task/heartbeat", { method: "POST", body: { umo: task.umo, enabled: !task.heartbeat?.enabled } });
      setFeedback("心跳状态已更新。");
      await load();
    }
    if (action === "finish-task") {
      const task = activeTask();
      await api("/api/task/finish", { method: "POST", body: { umo: task.umo, summary: "WebUI 标记完成。" } });
      setFeedback("任务已完成归档。");
      await load();
    }
    if (action === "cancel-task") {
      const task = activeTask();
      await api("/api/task/cancel", { method: "POST", body: { umo: task.umo, reason: "WebUI 强制停止任务。" } });
      setFeedback("任务已停止并归档。");
      await load();
    }
    if (action === "integration-tab") {
      integrationTab = target.dataset.id;
      render();
    }
    if (action === "toggle-plugin") {
      const plugin = (state.plugins || []).find((item) => item.name === target.dataset.id);
      if (!plugin || plugin.locked) return;
      currentAgent.plugin_overrides[plugin.name] = !pluginEffective(plugin);
      render();
    }
    if (action === "toggle-tool") {
      const selected = new Set((currentAgent.enabled_tools || []).filter((item) => item !== EMPTY_TOOLS_SENTINEL));
      if (selected.has(target.dataset.id)) selected.delete(target.dataset.id);
      else selected.add(target.dataset.id);
      currentAgent.enabled_tools = Array.from(selected).sort();
      render();
    }
    if (action === "enable-visible-tools") {
      currentAgent.enabled_tools = (state.tools || [])
        .filter((tool) => tool.active !== false)
        .filter((tool) => {
          const plugin = (state.plugins || []).find((item) => item.name === tool.plugin_name);
          return plugin ? pluginEffective(plugin) : true;
        })
        .map((tool) => tool.name)
        .sort();
      render();
    }
    if (action === "disable-tools") {
      currentAgent.enabled_tools = [EMPTY_TOOLS_SENTINEL];
      render();
    }
    if (action === "toggle-skill") {
      toggleListValue("enabled_skills", target.dataset.id);
      render();
    }
    if (action === "select-integration") {
      selectedIntegrationId = target.dataset.id;
      render();
    }
    if (action === "toggle-integration") {
      toggleListValue("module_ids", target.dataset.id);
      render();
    }
    if (action === "save-integration-settings") {
      const raw = $("integration-settings").value.trim() || "{}";
      currentAgent.module_settings[selectedIntegrationId] = JSON.parse(raw);
      setFeedback("蓝图设置已写入当前 Agent 草稿，记得保存 AgentSpec。");
      render();
    }
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

$("refresh").addEventListener("click", load);
$("save-token").addEventListener("click", () => {
  sessionStorage.setItem("agent_lab_token", $("token").value.trim());
  load();
});

const initialToken = new URLSearchParams(location.search).get("token") || sessionStorage.getItem("agent_lab_token") || "";
$("token").value = initialToken;
if (initialToken) sessionStorage.setItem("agent_lab_token", initialToken);

renderNav();
load();
