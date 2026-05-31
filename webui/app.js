const $ = (id) => document.getElementById(id);
const EMPTY_TOOLS_SENTINEL = "__agent_lab_no_external_tools__";
const DEFAULT_ENABLED_TOOLS = [
  "astrbot_file_read_tool",
  "astrbot_grep_tool",
  "astrbot_file_write_tool",
  "astrbot_file_edit_tool",
  "astrbot_execute_shell",
  "astrbot_execute_python",
  "agent_lab_call_custom_api",
];

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
let selectedWorkflowNodeId = "";
let integrationTab = "plugins";
let liveTimer = null;
let pluginFilter = "";
let toolFilter = "";
let blueprintFilter = "";
let memoryFilter = "all";

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

function identitySourceLabel(source) {
  return {
    astrbot_persona: "AstrBot 会话/默认 Persona",
    astrbot_config: "AstrBot 配置名称",
    fallback: "通用占位",
  }[source] || "AstrBot 运行时";
}

function runtimeAgentName() {
  return state?.runtime?.default_agent_name || "按当前 AstrBot 身份自动生成";
}

function isAutoIdentitySource(source) {
  return ["astrbot_runtime", "astrbot_persona", "astrbot_config"].includes(source);
}

function agentDisplayName(agent) {
  if (agent?.name) return agent.name;
  if (isAutoIdentitySource(agent?.identity_label_source)) return runtimeAgentName();
  return "未命名配置";
}

function ensureAgent(agent) {
  agent.memory_policy ||= {};
  agent.approval_policy ||= {};
  agent.approval_policy.preapproved_scopes ||= [];
  agent.approval_policy.require_approval ||= [
    "file_delete",
    "bulk_overwrite",
    "git_reset",
    "git_clean",
    "deployment",
    "service_restart",
    "secret_read",
    "system_config",
    "database_destructive",
  ];
  agent.approval_policy.note ||= "审批优先由 Agent 在危险动作前主动提出；工具层只作为灾难性操作兜底。";
  agent.heartbeat_policy ||= {};
  agent.plugin_overrides ||= {};
  agent.enabled_tools ||= [];
  agent.tool_risk_overrides ||= {};
  agent.enabled_skills ||= [];
  agent.module_ids ||= [];
  agent.module_settings ||= {};
  agent.workflow_nodes ||= [];
  agent.workflow_edges ||= [];
  agent.identity_label_source ||= agent.name ? "manual" : "astrbot_runtime";
  return agent;
}

function defaultAgentDraft() {
  return ensureAgent({
    name: "",
    identity_label_source: "astrbot_runtime",
    description: "把 AstrBot 会话切换为可持续执行、可审批、可归档的 Agent 模式。",
    enabled: true,
    provider_id: "",
    trigger_mode: "confirm",
    system_prompt: "你仍然是当前 AstrBot 里的原本角色，但进入 Agent Mode 后必须以任务推进为中心。",
    task_prompt: "你在 Agent Mode 中工作。先读取任务状态，再执行一个有限步骤，随后总结并写回状态。",
    plugin_overrides: {},
    enabled_tools: [...DEFAULT_ENABLED_TOOLS],
    tool_risk_overrides: {},
    enabled_skills: [],
    module_ids: ["checkpoint_state", "approval_guard", "heartbeat_protocol", "memory_gate"],
    module_settings: {},
    workflow_nodes: defaultWorkflowNodes(),
    workflow_edges: defaultWorkflowEdges(),
    memory_policy: {
      mode: "task_filtered",
      entry_summary_turns: 24,
      keep_identity: true,
      allow_long_memory: true,
      exit_memory_candidates: true,
    },
    approval_policy: {
      mode: "work",
      preapproved_scopes: [],
      require_approval: [
        "file_delete",
        "bulk_overwrite",
        "git_reset",
        "git_clean",
        "deployment",
        "service_restart",
        "secret_read",
        "system_config",
        "database_destructive",
      ],
      note: "审批优先由 Agent 在危险动作前主动提出；工具层只作为灾难性操作兜底。",
    },
    heartbeat_policy: {
      allowed: true,
      mode: "manual",
      enabled: false,
      cron_expression: "*/5 * * * *",
      max_repeated_failures: 3,
    },
  });
}

function linesToList(value) {
  return String(value || "")
    .split(/\r?\n|[,，、]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function listToLines(value) {
  return (value || []).map((item) => String(item).trim()).filter(Boolean).join("\n");
}

function riskLabel(risk) {
  return { safe: "安全", work: "工作", high: "高危" }[risk] || "工作";
}

function riskTone(risk) {
  return { safe: "ok", work: "warn", high: "bad" }[risk] || "warn";
}

function includesQuery(values, query) {
  const needle = String(query || "").trim().toLowerCase();
  if (!needle) return true;
  return values.some((value) => String(value || "").toLowerCase().includes(needle));
}

function renderAndRestoreInput(action, value) {
  render();
  const input = document.querySelector(`[data-action="${action}"]`);
  if (!input) return;
  input.focus();
  const end = String(value || "").length;
  if (typeof input.setSelectionRange === "function") input.setSelectionRange(end, end);
}

function defaultWorkflowNodes() {
  return [
    { id: "entry", title: "入口压缩", kind: "state", description: "把任务前商量出的计划压缩为 task_brief，不重建当前运行时身份。" },
    { id: "plan", title: "计划拆解", kind: "state", description: "把根目标拆成可验证的小步，并记录完成条件。" },
    { id: "execute", title: "工具执行", kind: "tool", description: "只把 AgentSpec 选中的注册工具交给 AstrBot Agent Runner。" },
    { id: "approval", title: "审批闸门", kind: "guard", description: "删除、部署、密钥、重启等危险动作前先软审批。" },
    { id: "checkpoint", title: "状态快照", kind: "state", description: "active_task.json 与 markdown 是任务连续性的真实来源。" },
    { id: "heartbeat", title: "心跳续跑", kind: "guard", description: "长任务由 cron 唤醒：读状态、推进一步、写状态。" },
    { id: "archive", title: "出口归档", kind: "state", description: "完成或取消时生成出口摘要和可审查记忆候选。" },
  ];
}

function defaultWorkflowEdges() {
  return [
    { from: "entry", to: "plan" },
    { from: "plan", to: "execute" },
    { from: "execute", to: "approval" },
    { from: "approval", to: "checkpoint" },
    { from: "checkpoint", to: "heartbeat" },
    { from: "heartbeat", to: "execute" },
    { from: "checkpoint", to: "archive" },
  ];
}

function ensureWorkflow() {
  currentAgent = ensureAgent(currentAgent || {});
  if (!Array.isArray(currentAgent.workflow_nodes) || !currentAgent.workflow_nodes.length) {
    currentAgent.workflow_nodes = defaultWorkflowNodes();
  }
  if (!Array.isArray(currentAgent.workflow_edges) || !currentAgent.workflow_edges.length) {
    currentAgent.workflow_edges = defaultWorkflowEdges();
  }
  currentAgent.workflow_nodes = currentAgent.workflow_nodes.map((node, index) => ({
    id: String(node.id || `node_${index + 1}`).trim(),
    title: String(node.title || node.id || `节点 ${index + 1}`).trim(),
    kind: String(node.kind || "state").trim(),
    description: String(node.description || "").trim(),
  }));
  const ids = new Set(currentAgent.workflow_nodes.map((node) => node.id));
  currentAgent.workflow_edges = currentAgent.workflow_edges
    .map((edge) => ({ from: String(edge.from || "").trim(), to: String(edge.to || "").trim() }))
    .filter((edge) => ids.has(edge.from) && ids.has(edge.to));
  if (!selectedWorkflowNodeId || !ids.has(selectedWorkflowNodeId)) {
    selectedWorkflowNodeId = currentAgent.workflow_nodes[0]?.id || "";
  }
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
    currentAgent = ensureAgent(clone(agents.find((item) => item.agent_id === selectedAgentId) || agents[0] || defaultAgentDraft()));
    const tasks = [...(state.tasks || []), ...(state.archives || [])];
    if (!selectedTaskId || !tasks.some((item) => item.task_id === selectedTaskId)) {
      selectedTaskId = tasks[0]?.task_id || "";
    }
    $("bot-label").textContent = state.runtime?.bot_label || "等待读取";
    $("bot-source").textContent = identitySourceLabel(state.runtime?.bot_label_source);
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
  syncLiveRefresh();
  if (route === "dashboard") renderDashboard();
  if (route === "canvas") renderCanvas();
  if (route === "tasks") renderTasks();
  if (route === "monitor") renderMonitor();
  if (route === "integrations") renderIntegrations();
}

function syncLiveRefresh() {
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
  if (route === "monitor") {
    liveTimer = setInterval(() => {
      if (route === "monitor") load();
    }, 5000);
  }
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
      ${metric("任务触发", m.task_triggers ?? 0)}
      ${metric("心跳在线", m.heartbeat_online ?? 0)}
      ${metric("心跳异常", m.heartbeat_stale ?? 0)}
      ${metric("Token 消耗", m.token_usage ?? 0, "仅统计 provider 上报的 usage")}
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
  if (!agents.length) return `<div class="empty">还没有任务模式配置。</div>`;
  return agents
    .map((agent) => {
      const selected = agent.agent_id === selectedAgentId;
      const def = agent.agent_id === state.default_agent_id ? "默认 · " : "";
      const stats = agentStats(agent);
      return `
        <button class="list-row ${selected ? "selected" : ""}" data-action="select-agent" data-id="${esc(agent.agent_id)}" type="button">
          <div class="row-title">
            <span>${esc(def + agentDisplayName(agent))}</span>
            <span class="row-badges">
              ${badge(stats.health_label, stats.health_tone)}
              ${badge(agent.enabled === false ? "停用" : "启用", agent.enabled === false ? "bad" : "ok")}
            </span>
          </div>
          <div class="row-meta">${esc(agent.agent_id)} · 触发：${esc(agent.trigger_mode || "confirm")} · Provider：${esc(agent.provider_id || "当前会话")}</div>
          <div class="mini-stats">
            <span>运行 ${stats.active}</span>
            <span>触发 ${stats.triggers}</span>
            <span>Token ${stats.tokens}</span>
            <span>审批 ${stats.approvals}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function agentStats(agent) {
  const active = (state.tasks || []).filter((task) => task.agent_id === agent.agent_id);
  const archived = (state.archives || []).filter((task) => task.agent_id === agent.agent_id);
  const all = [...active, ...archived];
  const tokens = all.reduce((sum, task) => sum + Number(task.token_usage?.total || 0), 0);
  const approvals = active.reduce(
    (sum, task) => sum + (task.approvals || []).filter((item) => item.status === "pending").length,
    0,
  );
  const healthStates = active.map((task) => task.heartbeat_health?.state || "off");
  let health_label = "离线";
  let health_tone = "warn";
  if (!agent.enabled) {
    health_label = "已停用";
    health_tone = "bad";
  } else if (!active.length) {
    health_label = "空闲";
    health_tone = "";
  } else if (healthStates.some((item) => ["stale", "blocked"].includes(item))) {
    health_label = "报错";
    health_tone = "bad";
  } else if (healthStates.some((item) => item === "online")) {
    health_label = "在线";
    health_tone = "ok";
  } else {
    health_label = "待心跳";
    health_tone = "warn";
  }
  return {
    active: active.length,
    triggers: all.length,
    tokens,
    approvals,
    health_label,
    health_tone,
  };
}

function taskRows(tasks, archive = false) {
  if (!tasks.length) return `<div class="empty">${archive ? "暂无归档任务。" : "暂无 active task。"}</div>`;
  return tasks
    .map(
      (task) => {
        const health = task.heartbeat_health || {};
        return `
          <button class="list-row ${task.task_id === selectedTaskId ? "selected" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
            <div class="row-title">
              <span>${esc(task.root_goal || task.task_id)}</span>
              <span class="row-badges">
                ${badge(task.status || "-", task.status === "running" ? "ok" : "warn")}
                ${badge(healthLabel(health), health.tone || "warn")}
              </span>
            </div>
            <div class="row-meta">${esc(task.agent_name || task.agent_id || "-")} · ${esc(task.task_id)} · ${esc(healthLabel(health))}</div>
          </button>
        `;
      },
    )
    .join("");
}

function renderCanvas() {
  currentAgent = ensureAgent(currentAgent || {});
  ensureWorkflow();
  $("view").innerHTML = `
    <section class="grid two">
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">配置模板</p><h2>Agent Mode 生产车间</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="new-agent" type="button">新建</button>
            <button class="button secondary" data-action="duplicate-agent" type="button">复制</button>
            <button class="button secondary" data-action="make-default" type="button">设为默认</button>
            <button class="button" data-action="save-agent" type="button">保存</button>
          </div>
        </div>
        <div class="form-grid">
          <label>任务模式配置名称<input id="agent-name" value="${esc(currentAgent.name || "")}" placeholder="${esc(runtimeAgentName())}" /></label>
          <label>底层模型 Provider ID<input id="provider-id" value="${esc(currentAgent.provider_id || "")}" placeholder="为空则使用当前会话模型" /></label>
          <label>配置状态<select id="agent-enabled">${options(["true", "false"], String(currentAgent.enabled !== false))}</select></label>
          <label>触发模式<select id="trigger-mode">${options(["manual", "confirm", "smart", "always"], currentAgent.trigger_mode || "confirm")}</select></label>
          <label>记忆模式<select id="memory-mode">${options(["inherit", "task_filtered", "strict"], currentAgent.memory_policy.mode || "task_filtered")}</select></label>
          <label>审批模式<select id="approval-mode">${options(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work")}</select></label>
          <label>心跳模式<select id="heartbeat-mode">${options(["off", "manual", "auto"], currentAgent.heartbeat_policy.mode || "manual")}</select></label>
          <label>允许心跳<select id="heartbeat-allowed">${options(["true", "false"], String(currentAgent.heartbeat_policy.allowed !== false))}</select></label>
          <label>上下文摘要轮数<input id="entry-summary-turns" type="number" min="1" value="${esc(currentAgent.memory_policy.entry_summary_turns || 24)}" /></label>
          <label>心跳 Cron<input id="heartbeat-cron" value="${esc(currentAgent.heartbeat_policy.cron_expression || "*/5 * * * *")}" /></label>
          <div class="span-2 note-line">当前运行时身份：${esc(state.runtime?.bot_label || "等待读取")}；来源：${esc(identitySourceLabel(state.runtime?.bot_label_source))}。这里配置的是任务模式模板名和规则，不会覆盖 AstrBot 当前身份。</div>
          <label class="span-2">任务模式补充提示词（不是身份替换）<textarea id="system-prompt" rows="4">${esc(currentAgent.system_prompt || "")}</textarea></label>
          <label class="span-2">每轮执行协议<textarea id="task-prompt" rows="4">${esc(currentAgent.task_prompt || "")}</textarea></label>
          <details class="span-2 advanced-json">
            <summary>高级：工作流 JSON 导入/导出</summary>
            <textarea id="workflow-json" rows="8">${esc(JSON.stringify(workflowData(), null, 2))}</textarea>
          </details>
        </div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">资产列表</p><h2>选择任务模式配置</h2></div></div>
        <div class="list">${agentRows()}</div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <div><p class="card-kicker">流程</p><h2>任务模式工作流</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-action="add-workflow-node" type="button">新增节点</button>
          <button class="button secondary" data-action="reset-workflow" type="button">恢复默认流程</button>
        </div>
      </div>
      <div class="workflow-layout">
        <div>
          <div class="canvas">
            ${workflowNodes()}
          </div>
          <pre>${esc(edgeText())}</pre>
        </div>
        <div class="workflow-side">
          ${workflowInspector()}
          ${workflowEdgesPanel()}
        </div>
      </div>
    </section>
  `;
}

function workflowData() {
  ensureWorkflow();
  return {
    nodes: currentAgent.workflow_nodes || [],
    edges: currentAgent.workflow_edges || [],
  };
}

function workflowNodes() {
  ensureWorkflow();
  return currentAgent.workflow_nodes
    .map((item) => node(item))
    .join("");
}

function edgeText() {
  ensureWorkflow();
  const edges = currentAgent.workflow_edges || [];
  if (!edges.length) return "工作流边：尚未配置。";
  return "工作流边：\n" + edges.map((edge) => `${edge.from} -> ${edge.to}`).join("\n");
}

function node(item) {
  const selected = item.id === selectedWorkflowNodeId;
  return `
    <button class="node ${selected ? "selected" : ""}" data-action="select-workflow-node" data-id="${esc(item.id)}" data-kind="${esc(item.kind)}" type="button">
      <strong>${esc(item.title || item.id)}</strong>
      <p>${esc(item.description || item.id)}</p>
      <span>${esc(item.id)} · ${esc(item.kind || "state")}</span>
    </button>
  `;
}

function selectedWorkflowNode() {
  ensureWorkflow();
  return currentAgent.workflow_nodes.find((item) => item.id === selectedWorkflowNodeId) || currentAgent.workflow_nodes[0];
}

function workflowInspector() {
  const item = selectedWorkflowNode();
  if (!item) return `<div class="empty">暂无节点。</div>`;
  return `
    <div class="detail-box workflow-editor">
      <div class="panel-head"><div><p class="card-kicker">节点</p><h3>编辑节点</h3></div></div>
      <label>节点 ID<input id="workflow-node-id" value="${esc(item.id)}" /></label>
      <label>标题<input id="workflow-node-title" value="${esc(item.title)}" /></label>
      <label>类型<select id="workflow-node-kind">${options(["state", "tool", "guard"], item.kind || "state")}</select></label>
      <label>说明<textarea id="workflow-node-description" rows="4">${esc(item.description || "")}</textarea></label>
      <div class="button-row">
        <button class="button" data-action="apply-workflow-node" type="button">应用节点</button>
        <button class="button danger" data-action="delete-workflow-node" type="button">删除节点</button>
      </div>
    </div>
  `;
}

function workflowNodeOptions(selected = "") {
  ensureWorkflow();
  return currentAgent.workflow_nodes
    .map((item) => `<option value="${esc(item.id)}" ${item.id === selected ? "selected" : ""}>${esc(item.title || item.id)} (${esc(item.id)})</option>`)
    .join("");
}

function workflowEdgesPanel() {
  ensureWorkflow();
  return `
    <div class="detail-box workflow-editor">
      <div class="panel-head"><div><p class="card-kicker">连线</p><h3>流程连接</h3></div></div>
      <div class="form-grid compact">
        <label>From<select id="workflow-edge-from">${workflowNodeOptions(selectedWorkflowNodeId)}</select></label>
        <label>To<select id="workflow-edge-to">${workflowNodeOptions(currentAgent.workflow_nodes[1]?.id || selectedWorkflowNodeId)}</select></label>
      </div>
      <div class="button-row"><button class="button secondary" data-action="add-workflow-edge" type="button">新增连线</button></div>
      <div class="edge-list">
        ${(currentAgent.workflow_edges || []).map((edge, index) => `
          <div class="edge-row">
            <span>${esc(edge.from)} -> ${esc(edge.to)}</span>
            <button class="button danger tiny" data-action="delete-workflow-edge" data-index="${index}" type="button">删除</button>
          </div>
        `).join("") || `<div class="empty">暂无连线。</div>`}
      </div>
    </div>
  `;
}

function normalizeWorkflowId(value) {
  return String(value || "")
    .trim()
    .replace(/[^\w-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    || "node";
}

function uniqueWorkflowNodeId(base = "node") {
  ensureWorkflow();
  const ids = new Set(currentAgent.workflow_nodes.map((item) => item.id));
  const root = normalizeWorkflowId(base);
  if (!ids.has(root)) return root;
  let index = 2;
  while (ids.has(`${root}_${index}`)) index += 1;
  return `${root}_${index}`;
}

function options(values, selected) {
  return values.map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(value)}</option>`).join("");
}

function readAgentForm() {
  if (!$("agent-name")) return;
  const typedName = $("agent-name").value.trim();
  currentAgent.name = typedName;
  if (!typedName || (isAutoIdentitySource(currentAgent.identity_label_source) && typedName === runtimeAgentName())) {
    currentAgent.identity_label_source = "astrbot_runtime";
  } else if (isAutoIdentitySource(currentAgent.identity_label_source)) {
    currentAgent.identity_label_source = "manual";
  }
  currentAgent.provider_id = $("provider-id").value.trim();
  currentAgent.enabled = $("agent-enabled").value === "true";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.memory_policy.mode = $("memory-mode").value;
  currentAgent.memory_policy.entry_summary_turns = Number($("entry-summary-turns").value || 24);
  currentAgent.approval_policy.mode = $("approval-mode").value;
  currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").value === "true";
  currentAgent.heartbeat_policy.cron_expression = $("heartbeat-cron").value.trim() || "*/5 * * * *";
  currentAgent.system_prompt = $("system-prompt").value;
  currentAgent.task_prompt = $("task-prompt").value;
  if ($("workflow-json")) {
    const workflow = JSON.parse($("workflow-json").value || "{}");
    currentAgent.workflow_nodes = Array.isArray(workflow.nodes) ? workflow.nodes : currentAgent.workflow_nodes;
    currentAgent.workflow_edges = Array.isArray(workflow.edges) ? workflow.edges : currentAgent.workflow_edges;
    ensureWorkflow();
  }
}

function renderTasks() {
  const task = selectedTask();
  const runnableTask = activeTask();
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
            <button class="button secondary" data-action="tick-task" ${runnableTask ? "" : "disabled"} type="button">推进一轮</button>
            <button class="button secondary" data-action="toggle-heartbeat" ${runnableTask ? "" : "disabled"} type="button">${runnableTask?.heartbeat?.enabled ? "关闭心跳" : "开心跳"}</button>
            <button class="button secondary" data-action="finish-task" ${runnableTask ? "" : "disabled"} type="button">完成归档</button>
          </div>
        </div>
        ${task ? taskDetail(task) : `<div class="empty">请选择或创建任务。</div>`}
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">记忆候选</p><h2>出口回流</h2></div></div>
        <label>新增/修剪长期记忆<textarea id="memory-text" rows="4" placeholder="只保存稳定事实、项目约定或后续任务需要复用的要点。"></textarea></label>
        <div class="button-row"><button class="button secondary" data-action="save-memory" type="button">保存记忆条目</button></div>
        <div class="tabs compact-tabs">
          ${["all", "candidate", "accepted", "rejected"].map((item) => `
            <button class="${memoryFilter === item ? "active" : ""}" data-action="memory-filter" data-id="${item}" type="button">${memoryFilterLabel(item)}</button>
          `).join("")}
        </div>
        <div class="list">${memoryRows()}</div>
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
  return tasks.find((item) => item.task_id === selectedTaskId) || null;
}

function selectedTask() {
  const tasks = [...(state.tasks || []), ...(state.archives || [])];
  return tasks.find((item) => item.task_id === selectedTaskId) || tasks[0] || null;
}

function runnableTask() {
  return activeTask() || (route === "monitor" ? (state.tasks || [])[0] || null : null);
}

function taskDetail(task) {
  const health = task.heartbeat_health || {};
  const pendingApprovals = (task.approvals || []).filter((item) => item.status === "pending");
  return `
    <div class="detail-box task-state-card">
      <div class="row-title">
        <span>${esc(task.root_goal || task.task_id)}</span>
        <span class="row-badges">
          ${badge(task.status, task.status === "running" ? "ok" : task.status === "blocked" ? "bad" : "warn")}
          ${badge(healthLabel(health), health.tone || "warn")}
        </span>
      </div>
      <div class="row-meta">UMO：${esc(task.umo)} · 状态文件：${esc(task.archive_path || task.task_id)}</div>
      <div class="mini-stats">
        <span>快照 ${task.state_snapshots?.length || 0}</span>
        <span>日志 ${task.progress_log?.length || 0}</span>
        <span>Token ${task.token_usage?.total || 0}</span>
        <span>审批 ${pendingApprovals.length}</span>
      </div>
    </div>
    <div class="state-fields">
      ${stateField("当前摘要", task.current_summary)}
      ${stateField("已确认进度", task.last_confirmed_progress)}
      ${stateField("下一步", task.next_step)}
      ${stateField("最近观察", task.last_observation)}
    </div>
    <div class="panel-head"><div><p class="card-kicker">Approvals</p><h3>待审批</h3></div></div>
    <div class="list">${approvalRows(pendingApprovals)}</div>
    <div class="panel-head"><div><p class="card-kicker">Snapshots</p><h3>状态快照时间线</h3></div></div>
    <div class="list">${snapshotRows(task.state_snapshots || [])}</div>
  `;
}

function stateField(label, value) {
  return `
    <div class="state-field">
      <span>${esc(label)}</span>
      <p>${esc(value || "-")}</p>
    </div>
  `;
}

function approvalRows(approvals) {
  if (!approvals.length) return `<div class="empty">暂无待审批事项。</div>`;
  return approvals.map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.operation || item.approval_id)}</span>${badge(item.status || "pending", "warn")}</div>
      <div class="row-meta">${esc(item.approval_id)} · ${esc(item.reason || "-")}</div>
      <div class="row-meta">影响：${esc(item.impact || "-")} · 回滚：${esc(item.rollback || "-")}</div>
    </div>
  `).join("");
}

function snapshotRows(snapshots) {
  if (!snapshots.length) return `<div class="empty">暂无状态快照。</div>`;
  return snapshots.slice(-12).reverse().map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.kind || "state")}</span>${badge(item.status || "-")}</div>
      <div class="row-meta">${esc(item.time || "")} · ${esc(item.next_step || "无下一步")}</div>
    </div>
  `).join("");
}

function memoryRows() {
  const rows = (state.memories || []).filter((item) => memoryFilter === "all" || item.status === memoryFilter);
  if (!rows.length) return `<div class="empty">暂无可审查记忆。任务结束后会生成候选，也可以手动保存。</div>`;
  return rows.slice(-20).reverse().map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.text)}</span>${badge(item.status || "candidate", item.status === "accepted" ? "ok" : "warn")}</div>
      <div class="row-meta">${esc(item.memory_id)} · 来源任务：${esc(item.source_task_id || "-")}</div>
      <div class="inline-actions">
        <button class="button secondary" data-action="accept-memory" data-id="${esc(item.memory_id)}" type="button">保留</button>
        <button class="button secondary" data-action="reject-memory" data-id="${esc(item.memory_id)}" type="button">标记不用</button>
        <button class="button danger" data-action="delete-memory" data-id="${esc(item.memory_id)}" type="button">删除</button>
      </div>
    </div>
  `).join("");
}

function memoryFilterLabel(value) {
  return {
    all: "全部",
    candidate: "候选",
    accepted: "已保留",
    rejected: "已标记不用",
  }[value] || value;
}

function healthLabel(health) {
  return {
    online: "心跳正常",
    idle: "等待首跳",
    stale: "心跳超时",
    blocked: "任务阻塞",
    off: "未开心跳",
  }[health?.state] || "未知";
}

function ageText(seconds) {
  if (seconds === null || seconds === undefined) return "尚无记录";
  if (seconds < 60) return `${seconds} 秒前`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} 分钟前`;
  return `${Math.floor(minutes / 60)} 小时前`;
}

function logRows(task) {
  const logs = task?.progress_log?.slice(-28).reverse() || [];
  if (!logs.length) return `<div class="empty">暂无实时日志。心跳或 tick 执行后会在这里出现。</div>`;
  return logs.map((item) => `
    <div class="log-row">
      <span>${esc(item.time || "")}</span>
      <strong>${esc(item.kind || "log")}</strong>
      <p>${esc(item.text || "")}</p>
    </div>
  `).join("");
}

function renderMonitor() {
  const tasks = state.tasks || [];
  const task = activeTask() || tasks[0] || null;
  const health = task?.heartbeat_health || {};
  const heartbeatPoints = task?.state_snapshots?.slice(-18) || [];
  $("view").innerHTML = `
    <section class="grid three">
      ${metric("运行实例", tasks.length)}
      ${metric("心跳正常", tasks.filter((item) => item.heartbeat_health?.state === "online").length)}
      ${metric("异常/超时", tasks.filter((item) => ["stale", "blocked"].includes(item.heartbeat_health?.state)).length)}
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
            <button class="button secondary" data-action="restart-heartbeat" ${task ? "" : "disabled"} type="button">一键重启心跳</button>
            <button class="button danger" data-action="cancel-task" ${task ? "" : "disabled"} type="button">强制停止任务</button>
          </div>
        </div>
        ${task ? `
          <div class="detail-box monitor-summary">
            <div class="row-title"><span>${esc(task.root_goal || task.task_id)}</span>${badge(healthLabel(health), health.tone || "warn")}</div>
            <div class="row-meta">
              最后心跳：${esc(health.last_pulse_at || "尚无")} · ${esc(ageText(health.seconds_since_pulse))}
              · 超时阈值：${esc(health.stale_after_seconds || "-")} 秒
            </div>
            <div class="row-meta">下一步：${esc(task.next_step || "等待 Agent 根据 task_state 判断")}</div>
          </div>
        ` : `<div class="empty">请选择一个运行实例。</div>`}
        <div class="heartbeat-chart">${heartbeatPoints.map((point) => {
          const bad = point.status === "blocked" || ["stale", "blocked"].includes(health.state);
          return `<span title="${esc(point.time || "")}" class="${bad ? "bad" : ""}"></span>`;
        }).join("") || "<em>暂无心跳曲线</em>"}</div>
        <div class="panel-head"><div><p class="card-kicker">Live</p><h3>实时日志流（5 秒刷新）</h3></div></div>
        <div class="log-list">${logRows(task)}</div>
      </div>
    </section>
  `;
}

function instanceRow(task) {
  const health = task.heartbeat_health || {};
  return `
    <button class="list-row ${task.task_id === selectedTaskId ? "selected" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
      <div class="row-title"><span>${esc(task.agent_name || task.task_id)}</span>${badge(healthLabel(health), health.tone || "warn")}</div>
      <div class="row-meta">${esc(task.task_id)} · ${esc(health.message || "-")} · ${esc(health.last_pulse_at || "尚无心跳记录")}</div>
    </button>
  `;
}

function renderIntegrations() {
  const tabs = [
    ["plugins", "AstrBot 插件隔离", "禁用会注入上下文的插件", (state.plugins || []).length],
    ["tools", "注册工具", "按来源插件折叠工具白名单", (state.tools || []).length],
    ["apis", "自定义 API", "把外部服务注册为受管工具", (state.custom_apis || []).length],
    ["credentials", "凭证库", "统一加密保存 API Key", (state.credentials || []).length],
    ["skills", "Skills 规则", "编辑任务模式补充约束", (state.skills || []).length],
    ["blueprints", "外部方案蓝图", "接入外部 agent 方法论", (state.integrations || state.modules || []).length],
  ];
  $("view").innerHTML = `
    <section class="integration-shell">
      <div class="panel-head">
        <div><p class="card-kicker">能力边界</p><h2>插件与集成页</h2></div>
        <button class="button" data-action="save-agent" type="button">保存当前 Agent</button>
      </div>
      <div class="integration-layout">
        <aside class="subnav">
          ${tabs.map(([id, title, desc, count]) => `
            <button class="${integrationTab === id ? "active" : ""}" data-action="integration-tab" data-id="${id}" type="button">
              <strong>${title}</strong>
              <span>${desc}</span>
              <small>${count}</small>
            </button>
          `).join("")}
        </aside>
        <div class="integration-content">${integrationBody()}</div>
      </div>
    </section>
  `;
}

function integrationBody() {
  if (integrationTab === "plugins") return pluginPanel();
  if (integrationTab === "tools") return toolsPanel();
  if (integrationTab === "apis") return apisPanel();
  if (integrationTab === "credentials") return credentialsPanel();
  if (integrationTab === "skills") return skillsPanel();
  return blueprintsPanel();
}

function pluginPanel() {
  const rows = (state.plugins || []).filter((plugin) =>
    includesQuery(
      [plugin.name, plugin.display_name, plugin.desc, plugin.root_dir_name],
      pluginFilter,
    )
  );
  const activeRows = rows.filter((plugin) => plugin.activated || plugin.locked);
  const globalOffRows = rows.filter((plugin) => !plugin.activated && !plugin.locked);
  const renderPlugin = (plugin) => {
    const self = plugin.locked || plugin.name === "astrbot_plugin_agent_lab";
    const globallyOff = !plugin.activated && !self;
    const locked = self || globallyOff;
    const effective = pluginEffective(plugin);
    const status = self
      ? ["受保护", "ok"]
      : globallyOff
        ? ["全局停用", "bad"]
        : effective
          ? ["Agent 中开启", "ok"]
          : ["Agent 中关闭", "warn"];
    return `
      <label class="toggle-row ${locked ? "disabled" : ""}">
        <input type="checkbox" data-action="toggle-plugin" data-id="${esc(plugin.name)}" ${effective ? "checked" : ""} ${locked ? "disabled" : ""} />
        <span><strong>${esc(plugin.display_name || plugin.name)}</strong><br /><small>${esc(plugin.name)} · AstrBot 全局：${plugin.activated ? "启用" : "停用"}</small></span>
        ${badge(status[0], status[1])}
      </label>
    `;
  };
  return `
    <div class="section-note">
      这里管理 AstrBot 内部插件在 Agent Mode 里的可见性。AstrBot 全局停用的插件会固定关闭；Agent Mode 只能进一步关闭插件，不能绕过 AstrBot 原生插件管理把它复活。
    </div>
    <input class="filter-input" data-action="filter-plugins" value="${esc(pluginFilter)}" placeholder="筛选插件名、目录或说明" />
    <details class="collapse-group" open>
      <summary>可用于 Agent Mode 的插件 <span>${activeRows.length}</span></summary>
      <div class="capability-list">${activeRows.map(renderPlugin).join("") || `<div class="empty">没有匹配的启用插件。</div>`}</div>
    </details>
    <details class="collapse-group">
      <summary>AstrBot 全局停用的插件 <span>${globalOffRows.length}</span></summary>
      <div class="capability-list">${globalOffRows.map(renderPlugin).join("") || `<div class="empty">没有匹配的全局停用插件。</div>`}</div>
    </details>
  `;
}

function pluginEffective(plugin) {
  const override = currentAgent?.plugin_overrides?.[plugin.name];
  if (plugin.locked || plugin.name === "astrbot_plugin_agent_lab") return true;
  if (!plugin.activated) return false;
  return typeof override === "boolean" ? override : true;
}

function toolsPanel() {
  const selected = new Set(currentAgent.enabled_tools || []);
  const rows = (state.tools || []).filter((tool) =>
    includesQuery(
      [tool.name, tool.description, tool.plugin_name, tool.plugin_display_name, tool.source],
      toolFilter,
    )
  );
  const sourceGroups = new Map();
  rows.forEach((tool) => {
    const plugin = (state.plugins || []).find((item) => item.name === tool.plugin_name);
    const pluginOn = plugin ? pluginEffective(plugin) : true;
    const checked = selected.has(tool.name) && !selected.has(EMPTY_TOOLS_SENTINEL) && pluginOn && tool.active !== false;
    const disabled = !pluginOn || tool.active === false;
    const risk = currentAgent.tool_risk_overrides?.[tool.name] || tool.risk || "work";
    const row = `
      <div class="toggle-row ${disabled ? "disabled" : ""}">
        <input type="checkbox" data-action="toggle-tool" data-id="${esc(tool.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} />
        <span><strong>${esc(tool.name)}</strong><br /><small>${esc(tool.plugin_display_name || tool.source)} · ${esc(tool.description || "无描述")}</small></span>
        <span class="tool-controls">
          ${badge(riskLabel(risk), riskTone(risk))}
          ${badge(disabled ? "随插件关闭" : checked ? "已选择" : "未选择", disabled ? "bad" : checked ? "ok" : "")}
          <select data-action="set-tool-risk" data-id="${esc(tool.name)}">${options(["safe", "work", "high"], risk)}</select>
        </span>
      </div>
    `;
    const key = tool.plugin_name || tool.plugin_display_name || tool.source || "registered";
    if (!sourceGroups.has(key)) {
      sourceGroups.set(key, {
        title: tool.plugin_display_name || tool.plugin_name || (tool.source === "builtin_catalog" ? "AstrBot 内置工具目录" : "未绑定插件的注册工具"),
        pluginName: tool.plugin_name || "",
        enabled: plugin ? pluginEffective(plugin) : tool.active !== false,
        rows: [],
      });
    }
    sourceGroups.get(key).rows.push(row);
  });
  const groups = Array.from(sourceGroups.values()).sort((a, b) =>
    Number(b.enabled) - Number(a.enabled) || a.title.localeCompare(b.title, "zh-CN")
  );
  const group = (item) => `
    <details class="collapse-group" ${item.enabled ? "open" : ""}>
      <summary>
        <span>${esc(item.title)}</span>
        ${badge(item.enabled ? "来源可用" : "随插件关闭", item.enabled ? "ok" : "bad")}
        <small>${item.rows.length}</small>
      </summary>
      <div class="capability-list">${item.rows.join("")}</div>
    </details>
  `;
  return `
    <div class="section-note">
      注册工具来自 AstrBot 内部工具管理器。来源插件在 AstrBot 全局停用或在 Agent Mode 中关闭时，本组工具会同步关闭；保存后后端构建 ToolSet 时也会再次过滤。
    </div>
    <section class="grid two">
      <div>
        <div class="button-row">
          <button class="button secondary" data-action="enable-visible-tools" type="button">启用当前可用工具</button>
          <button class="button secondary" data-action="disable-tools" type="button">禁用外部工具</button>
        </div>
        <input class="filter-input" data-action="filter-tools" value="${esc(toolFilter)}" placeholder="筛选工具名、来源插件或说明" />
        ${groups.map(group).join("") || `<div class="empty">没有匹配的注册工具。</div>`}
      </div>
      <div class="detail-box approval-editor">
        <div class="panel-head"><div><p class="card-kicker">审批</p><h3>工具审批策略</h3></div></div>
        <label>审批模式<select id="tool-approval-mode">${options(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work")}</select></label>
        <label>已授权范围<textarea id="preapproved-scopes" rows="5" placeholder="例如：读取项目文件&#10;运行测试&#10;小范围明确文件编辑">${esc(listToLines(currentAgent.approval_policy.preapproved_scopes))}</textarea></label>
        <label>必须审批动作<textarea id="require-approval" rows="8">${esc(listToLines(currentAgent.approval_policy.require_approval))}</textarea></label>
        <label>审批备注<textarea id="approval-note" rows="4">${esc(currentAgent.approval_policy.note || "")}</textarea></label>
        <div class="button-row"><button class="button secondary" data-action="apply-approval-policy" type="button">应用审批策略</button></div>
      </div>
    </section>
  `;
}

function skillsPanel() {
  const selected = new Set(currentAgent.enabled_skills || []);
  const agentModeRule = (state.skill_rules || []).find((item) => item.skill_name === "agent-mode") || {};
  const entryRule = (state.skill_rules || []).find((item) => item.skill_name === "agent-mode-entry-summary") || {};
  const exitRule = (state.skill_rules || []).find((item) => item.skill_name === "agent-mode-exit-summary") || {};
  return `
    <section class="grid two">
      <div class="panel-lite">
        <div class="panel-head"><div><p class="card-kicker">规则</p><h3>任务模式 Skills 规则</h3></div></div>
        <div class="section-note">这里编辑的是任务模式行为规则和进出摘要规则，会保存到 plugin_data/registry/skill_rules.json，并同步追加到 agent-mode Skill。入口/出口摘要会直接影响进出任务模式时的压缩与归档。</div>
        <label>agent-mode 行为规则<textarea id="skill-rule-content" rows="8" placeholder="写入任务模式的触发、审批、记忆过滤、工具边界等补充规则。">${esc(agentModeRule.content || "")}</textarea></label>
        <label>入口摘要规则<textarea id="entry-summary-rule-content" rows="7" placeholder="定义进入任务模式时如何把当前上下文压缩成 task_brief。">${esc(entryRule.content || "")}</textarea></label>
        <label>出口归档规则<textarea id="exit-summary-rule-content" rows="7" placeholder="定义退出任务模式时如何归档总结，以及哪些记忆候选可以回流。">${esc(exitRule.content || "")}</textarea></label>
        <div class="button-row"><button class="button" data-action="save-skill-rules" type="button">保存并同步规则</button></div>
      </div>
      <div class="capability-list">${(state.skills || []).map((skill) => `
        <label class="toggle-row">
          <input type="checkbox" data-action="toggle-skill" data-id="${esc(skill.name)}" ${selected.has(skill.name) ? "checked" : ""} />
          <span><strong>${esc(skill.name)}</strong><br /><small>${esc(skill.description || skill.path || "AstrBot Skill")}</small></span>
          ${badge(skill.active ? "已安装" : "未激活", skill.active ? "ok" : "warn")}
        </label>
      `).join("") || `<div class="empty">未读取到 Skills。</div>`}</div>
    </section>
  `;
}

function apisPanel() {
  const credentials = state.credentials || [];
  return `
    <section class="grid two">
      <div>
        <div class="form-grid">
          <label>API 名称<input id="api-name" placeholder="grok_search_proxy" /></label>
          <label>HTTP 方法<select id="api-method">${options(["GET", "POST", "PUT", "DELETE"], "GET")}</select></label>
          <label class="span-2">URL<input id="api-url" placeholder="https://api.example.com/v1/search" /></label>
          <label>凭证引用<select id="api-credential"><option value="">无</option>${credentials.map((item) => `<option value="${esc(item.credential_id)}">${esc(item.label || item.credential_id)}</option>`).join("")}</select></label>
          <label>鉴权方式<select id="api-auth-type">${options(["bearer", "header", "query", "none"], "bearer")}</select></label>
          <label>鉴权 Header<input id="api-auth-header" value="Authorization" /></label>
          <label>Query 参数<input id="api-auth-query" value="api_key" /></label>
          <label>超时秒数<input id="api-timeout" type="number" min="1" max="120" value="30" /></label>
          <label class="span-2">固定 Headers JSON<textarea id="api-headers" rows="3" placeholder='{"X-App": "agent-lab"}'></textarea></label>
          <label class="span-2">说明<input id="api-description" placeholder="用于联网搜索、代码沙箱或内部系统调用" /></label>
        </div>
        <div class="button-row"><button class="button" data-action="save-api" type="button">注册 API</button></div>
      </div>
      <div class="capability-list">${(state.custom_apis || []).map((item) => `
        <div class="list-row">
          <div class="row-title"><span>${esc(item.name)}</span>${badge(item.method || "GET")}</div>
          <div class="row-meta">${esc(item.url)} · 凭证：${esc(item.credential_id || "无")} · 鉴权：${esc(item.auth_type || "bearer")}</div>
        </div>
      `).join("") || `<div class="empty">暂无自定义 API。</div>`}</div>
    </section>
  `;
}

function credentialsPanel() {
  return `
    <section class="grid two">
      <div>
        <div class="form-grid">
          <label>凭证标签<input id="cred-label" placeholder="Grok Search Key" /></label>
          <label>Provider<input id="cred-provider" placeholder="xai / openai / tavily" /></label>
          <label>作用域<input id="cred-scope" value="tool" /></label>
          <label>Secret Value<input id="cred-value" type="password" placeholder="保存后只显示掩码" /></label>
        </div>
        <div class="button-row"><button class="button" data-action="save-credential" type="button">保存加密凭证</button></div>
      </div>
      <div class="capability-list">${(state.credentials || []).map((item) => `
        <div class="list-row">
          <div class="row-title"><span>${esc(item.label || item.credential_id)}</span>${badge(item.has_value ? "已加密" : "空值", item.has_value ? "ok" : "warn")}</div>
          <div class="row-meta">${esc(item.credential_id)} · ${esc(item.provider || "-")} · ${esc(item.scope || "tool")}</div>
        </div>
      `).join("") || `<div class="empty">暂无凭证。密钥会加密写入 plugin_data/registry。</div>`}</div>
    </section>
  `;
}

function blueprintGroup(module) {
  const id = String(module.module_id || "");
  if (["checkpoint_state", "approval_guard", "heartbeat_protocol", "memory_gate"].includes(id)) {
    return "基础运行模块";
  }
  if (["handoff_adapter", "flow_adapter"].includes(id)) {
    return "编排预留模块";
  }
  return "外部方案蓝图";
}

function blueprintSettingRows(module, settings) {
  const properties = module?.settings_schema?.properties || {};
  const entries = Object.entries(properties);
  if (!entries.length) {
    return `<div class="empty">这个蓝图还没有声明可视化设置项，可使用下方高级 JSON 编辑。</div>`;
  }
  return entries.map(([key, schema]) => {
    const type = schema?.type || "string";
    const value = settings?.[key] ?? module?.default_settings?.[key] ?? "";
    const label = schema?.title || key;
    const desc = schema?.description || "";
    const attrs = `data-action="blueprint-setting" data-key="${esc(key)}" data-type="${esc(type)}"`;
    let control = "";
    if (Array.isArray(schema?.enum) && schema.enum.length) {
      control = `<select ${attrs}>${options(schema.enum.map(String), String(value))}</select>`;
    } else if (type === "boolean") {
      control = `<select ${attrs}>${options(["true", "false"], String(Boolean(value)))}</select>`;
    } else if (type === "integer" || type === "number") {
      control = `<input ${attrs} type="number" value="${esc(value)}" />`;
    } else if (type === "array") {
      const items = Array.isArray(value) ? value.join("\n") : String(value || "");
      control = `<textarea ${attrs} rows="4" placeholder="每行一个值">${esc(items)}</textarea>`;
    } else if (type === "object") {
      control = `<textarea ${attrs} rows="5" placeholder='{"key": "value"}'>${esc(JSON.stringify(value || {}, null, 2))}</textarea>`;
    } else {
      control = `<input ${attrs} value="${esc(value)}" />`;
    }
    return `
      <label>
        ${esc(label)}
        ${control}
        ${desc ? `<small>${esc(desc)}</small>` : ""}
      </label>
    `;
  }).join("");
}

function readBlueprintSettingsFromForm(fallbackRaw = "{}") {
  const fields = Array.from(document.querySelectorAll('[data-action="blueprint-setting"]'));
  if (!fields.length) return JSON.parse(fallbackRaw || "{}");
  const result = {};
  fields.forEach((field) => {
    const key = field.dataset.key;
    const type = field.dataset.type || "string";
    if (!key) return;
    const raw = field.value;
    if (type === "boolean") {
      result[key] = raw === "true";
    } else if (type === "integer") {
      result[key] = Number.parseInt(raw || "0", 10);
    } else if (type === "number") {
      result[key] = Number(raw || 0);
    } else if (type === "array") {
      result[key] = linesToList(raw);
    } else if (type === "object") {
      result[key] = JSON.parse(raw || "{}");
    } else {
      result[key] = raw;
    }
  });
  return result;
}

function blueprintManifestTemplate() {
  return JSON.stringify(
    {
      module_id: "my_agent_blueprint",
      name: "My Agent Blueprint",
      source: "custom",
      description: "把一个外部方案翻译成 Agent Lab 的运行规则。",
      prompt: "这里写入任务模式运行时要遵守的规则。",
      links: [],
      capabilities: ["workflow"],
      requires: [],
      settings_schema: {
        type: "object",
        properties: {
          enabled: { type: "boolean", description: "是否启用该规则" },
        },
      },
      default_settings: {
        enabled: true,
      },
    },
    null,
    2,
  );
}

function blueprintsPanel() {
  const modules = (state.integrations || state.modules || []).filter((module) =>
    includesQuery(
      [module.module_id, module.name, module.source, module.description],
      blueprintFilter,
    )
  );
  if (!selectedIntegrationId || !modules.some((item) => item.module_id === selectedIntegrationId)) {
    selectedIntegrationId = modules[0]?.module_id || "";
  }
  const selected = modules.find((item) => item.module_id === selectedIntegrationId);
  const enabled = new Set(currentAgent.module_ids || []);
  const settings = currentAgent.module_settings?.[selectedIntegrationId] || selected?.default_settings || {};
  const grouped = modules.reduce((acc, module) => {
    const group = blueprintGroup(module);
    acc[group] ||= [];
    acc[group].push(module);
    return acc;
  }, {});
  const list = Object.entries(grouped).map(([group, items]) => `
    <details class="collapse-group" open>
      <summary>${esc(group)} <span>${items.length}</span></summary>
      <div class="capability-list">${items.map((module) => `
        <button class="list-row ${module.module_id === selectedIntegrationId ? "selected" : ""}" data-action="select-integration" data-id="${esc(module.module_id)}" type="button">
          <div class="row-title"><span>${esc(module.name)}</span>${badge(enabled.has(module.module_id) ? "已加入" : "未加入", enabled.has(module.module_id) ? "ok" : "")}</div>
          <div class="row-meta">${esc(module.module_id)} · ${esc(module.source)} · ${esc(module.description)}</div>
        </button>
      `).join("")}</div>
    </details>
  `).join("");
  return `
    <div class="section-note">
      外部方案蓝图不是 AstrBot 插件，也不是会立刻执行的工具。它是一组可开关、可配置的运行规则：把 LangGraph、OpenAI Agents、CrewAI 等方案的好用概念翻译成 Agent Lab 的 TaskState、审批、心跳、记忆和工作流约束。真正的可调用能力仍在“注册工具”和“自定义 API”里管理。
    </div>
    <section class="grid two">
      <div>
        <input class="filter-input" data-action="filter-blueprints" value="${esc(blueprintFilter)}" placeholder="筛选蓝图、模块 ID 或来源" />
        ${list || `<div class="empty">没有匹配的外部方案蓝图。</div>`}
        <details class="collapse-group">
          <summary>导入/更新外部方案蓝图 <span>JSON</span></summary>
          <div class="blueprint-import">
            <label>蓝图 Manifest<textarea id="blueprint-manifest" rows="12">${esc(blueprintManifestTemplate())}</textarea></label>
            <div class="button-row"><button class="button secondary" data-action="save-blueprint-manifest" type="button">保存蓝图到 plugin_data</button></div>
          </div>
        </details>
      </div>
      <div class="panel">
        ${selected ? `
          <div class="panel-head">
            <div><p class="card-kicker">${esc(blueprintGroup(selected))}</p><h2>${esc(selected.name)}</h2></div>
            <button class="button secondary" data-action="toggle-integration" data-id="${esc(selected.module_id)}" type="button">${enabled.has(selected.module_id) ? "从 Agent 移除" : "加入 Agent"}</button>
          </div>
          <div class="module-meta">
            ${badge(selected.module_id)}
            ${badge(selected.source || "本地模块")}
            ${(selected.capabilities || []).map((item) => badge(item, "ok")).join("")}
          </div>
          <p class="row-meta">${esc(selected.description || "")}</p>
          <div class="blueprint-settings">
            <div class="panel-head"><div><p class="card-kicker">精细设置</p><h3>当前配置</h3></div></div>
            ${blueprintSettingRows(selected, settings)}
          </div>
          <details class="advanced-json">
            <summary>高级：蓝图设置 JSON 导入/导出</summary>
            <textarea id="integration-settings" rows="8">${esc(JSON.stringify(settings, null, 2))}</textarea>
          </details>
          <div class="button-row"><button class="button" data-action="save-integration-settings" type="button">保存蓝图设置</button></div>
          <details class="advanced-json">
            <summary>查看默认设置与设置结构</summary>
            <pre>${esc(JSON.stringify({
              default_settings: selected.default_settings || {},
              settings_schema: selected.settings_schema || {},
              requires: selected.requires || [],
              links: selected.links || [],
            }, null, 2))}</pre>
          </details>
          <details class="advanced-json">
            <summary>查看运行时提示预览</summary>
            <pre>${esc(selected.prompt || "")}</pre>
          </details>
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
  setFeedback("任务模式配置已保存。");
  await load();
}

function toggleListValue(listName, value) {
  const next = new Set(currentAgent[listName] || []);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  currentAgent[listName] = Array.from(next).sort();
}

function materializedToolSelection() {
  const raw = (currentAgent.enabled_tools || []).filter((item) => item !== EMPTY_TOOLS_SENTINEL);
  if (raw.length) return raw;
  return (state.tools || [])
    .filter((tool) => tool.active !== false)
    .filter((tool) => {
      const plugin = (state.plugins || []).find((item) => item.name === tool.plugin_name);
      return plugin ? pluginEffective(plugin) : true;
    })
    .map((tool) => tool.name);
}

function removeToolsForPlugin(pluginName) {
  const blocked = new Set(
    (state.tools || [])
      .filter((tool) => tool.plugin_name === pluginName)
      .map((tool) => tool.name),
  );
  if (!blocked.size) return;
  const kept = materializedToolSelection().filter((name) => !blocked.has(name));
  currentAgent.enabled_tools = kept.length ? Array.from(new Set(kept)).sort() : [EMPTY_TOOLS_SENTINEL];
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
      currentAgent = defaultAgentDraft();
      selectedWorkflowNodeId = currentAgent.workflow_nodes?.[0]?.id || "";
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
    if (action === "select-workflow-node") {
      readAgentForm();
      selectedWorkflowNodeId = target.dataset.id;
      render();
    }
    if (action === "add-workflow-node") {
      readAgentForm();
      ensureWorkflow();
      const id = uniqueWorkflowNodeId("step");
      currentAgent.workflow_nodes.push({
        id,
        title: "新步骤",
        kind: "state",
        description: "描述这个步骤在任务模式中的作用。",
      });
      selectedWorkflowNodeId = id;
      render();
    }
    if (action === "reset-workflow") {
      readAgentForm();
      currentAgent.workflow_nodes = defaultWorkflowNodes();
      currentAgent.workflow_edges = defaultWorkflowEdges();
      selectedWorkflowNodeId = "entry";
      render();
    }
    if (action === "apply-workflow-node") {
      readAgentForm();
      ensureWorkflow();
      const node = selectedWorkflowNode();
      const oldId = node.id;
      const requestedId = normalizeWorkflowId($("workflow-node-id").value);
      const newId = requestedId === oldId ? oldId : uniqueWorkflowNodeId(requestedId);
      node.id = newId;
      node.title = $("workflow-node-title").value.trim() || newId;
      node.kind = $("workflow-node-kind").value;
      node.description = $("workflow-node-description").value.trim();
      currentAgent.workflow_edges = currentAgent.workflow_edges.map((edge) => ({
        from: edge.from === oldId ? newId : edge.from,
        to: edge.to === oldId ? newId : edge.to,
      }));
      selectedWorkflowNodeId = newId;
      render();
    }
    if (action === "delete-workflow-node") {
      readAgentForm();
      ensureWorkflow();
      const id = selectedWorkflowNodeId;
      currentAgent.workflow_nodes = currentAgent.workflow_nodes.filter((node) => node.id !== id);
      currentAgent.workflow_edges = currentAgent.workflow_edges.filter((edge) => edge.from !== id && edge.to !== id);
      selectedWorkflowNodeId = currentAgent.workflow_nodes[0]?.id || "";
      render();
    }
    if (action === "add-workflow-edge") {
      readAgentForm();
      ensureWorkflow();
      const from = $("workflow-edge-from").value;
      const to = $("workflow-edge-to").value;
      const exists = currentAgent.workflow_edges.some((edge) => edge.from === from && edge.to === to);
      if (from && to && from !== to && !exists) {
        currentAgent.workflow_edges.push({ from, to });
      }
      render();
    }
    if (action === "delete-workflow-edge") {
      readAgentForm();
      currentAgent.workflow_edges.splice(Number(target.dataset.index), 1);
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
      const task = runnableTask();
      if (!task) throw new Error("请选择一个正在运行的任务。");
      await api("/api/task/tick", { method: "POST", body: { umo: task.umo } });
      setFeedback("已推进一轮。");
      await load();
    }
    if (action === "toggle-heartbeat") {
      const task = runnableTask();
      if (!task) throw new Error("请选择一个正在运行的任务。");
      await api("/api/task/heartbeat", { method: "POST", body: { umo: task.umo, enabled: !task.heartbeat?.enabled } });
      setFeedback("心跳状态已更新。");
      await load();
    }
    if (action === "restart-heartbeat") {
      const task = runnableTask();
      if (!task) throw new Error("请选择一个正在运行的任务。");
      if (task.heartbeat?.enabled) {
        await api("/api/task/heartbeat", { method: "POST", body: { umo: task.umo, enabled: false } });
      }
      await api("/api/task/heartbeat", { method: "POST", body: { umo: task.umo, enabled: true } });
      setFeedback("心跳已重启。");
      await load();
    }
    if (action === "finish-task") {
      const task = runnableTask();
      if (!task) throw new Error("请选择一个正在运行的任务。");
      await api("/api/task/finish", { method: "POST", body: { umo: task.umo, summary: "WebUI 标记完成。" } });
      setFeedback("任务已完成归档。");
      await load();
    }
    if (action === "cancel-task") {
      const task = runnableTask();
      if (!task) throw new Error("请选择一个正在运行的任务。");
      await api("/api/task/cancel", { method: "POST", body: { umo: task.umo, reason: "WebUI 强制停止任务。" } });
      setFeedback("任务已停止并归档。");
      await load();
    }
    if (action === "save-memory") {
      const task = selectedTask();
      await api("/api/memory", {
        method: "POST",
        body: {
          text: $("memory-text").value,
          status: "accepted",
          source_task_id: task?.task_id || "",
          source_umo: task?.umo || "",
        },
      });
      setFeedback("记忆条目已保存。");
      await load();
    }
    if (action === "accept-memory" || action === "reject-memory") {
      const item = (state.memories || []).find((row) => row.memory_id === target.dataset.id);
      if (!item) throw new Error("未找到这条记忆候选，请刷新后重试。");
      await api("/api/memory", {
        method: "POST",
        body: { ...item, status: action === "accept-memory" ? "accepted" : "rejected" },
      });
      setFeedback("记忆状态已更新。");
      await load();
    }
    if (action === "delete-memory") {
      await api("/api/memory", { method: "DELETE", body: { memory_id: target.dataset.id } });
      setFeedback("记忆条目已删除。");
      await load();
    }
    if (action === "integration-tab") {
      integrationTab = target.dataset.id;
      render();
    }
    if (action === "memory-filter") {
      memoryFilter = target.dataset.id || "all";
      render();
    }
    if (action === "save-api") {
      await api("/api/registry", {
        method: "POST",
        body: {
          kind: "api",
          name: $("api-name").value,
          method: $("api-method").value,
          url: $("api-url").value,
          credential_id: $("api-credential").value,
          auth_type: $("api-auth-type").value,
          auth_header: $("api-auth-header").value,
          auth_query_param: $("api-auth-query").value,
          timeout_seconds: Number($("api-timeout").value || 30),
          headers: $("api-headers").value,
          description: $("api-description").value,
        },
      });
      setFeedback("自定义 API 已注册。");
      await load();
    }
    if (action === "save-credential") {
      await api("/api/registry", {
        method: "POST",
        body: {
          kind: "credential",
          label: $("cred-label").value,
          provider: $("cred-provider").value,
          scope: $("cred-scope").value,
          value: $("cred-value").value,
        },
      });
      setFeedback("凭证已加密保存。");
      await load();
    }
    if (action === "save-skill-rules") {
      const rules = [
        ["agent-mode", $("skill-rule-content").value],
        ["agent-mode-entry-summary", $("entry-summary-rule-content").value],
        ["agent-mode-exit-summary", $("exit-summary-rule-content").value],
      ];
      for (const [skillName, content] of rules) {
        await api("/api/registry", {
          method: "POST",
          body: {
            kind: "skill_rule",
            skill_name: skillName,
            content,
          },
        });
      }
      setFeedback("任务模式规则与进出摘要规则已同步。");
      await load();
    }
    if (action === "apply-approval-policy") {
      currentAgent.approval_policy.mode = $("tool-approval-mode").value;
      currentAgent.approval_policy.preapproved_scopes = linesToList($("preapproved-scopes").value);
      currentAgent.approval_policy.require_approval = linesToList($("require-approval").value);
      currentAgent.approval_policy.note = $("approval-note").value.trim();
      setFeedback("审批策略已写入当前配置草稿，记得保存任务模式配置。");
    }
    if (action === "toggle-plugin") {
      const plugin = (state.plugins || []).find((item) => item.name === target.dataset.id);
      if (!plugin || plugin.locked || !plugin.activated) return;
      const nextEnabled = !pluginEffective(plugin);
      currentAgent.plugin_overrides[plugin.name] = nextEnabled;
      if (!nextEnabled) removeToolsForPlugin(plugin.name);
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
    if (action === "save-blueprint-manifest") {
      const manifest = JSON.parse($("blueprint-manifest").value || "{}");
      const result = await api("/api/modules", { method: "POST", body: manifest });
      selectedIntegrationId = result.module?.module_id || selectedIntegrationId;
      setFeedback("外部方案蓝图已保存到 plugin_data。");
      await load();
    }
    if (action === "save-integration-settings") {
      const raw = $("integration-settings")?.value.trim() || "{}";
      currentAgent.module_settings[selectedIntegrationId] = readBlueprintSettingsFromForm(raw);
      setFeedback("蓝图设置已写入当前配置草稿，记得保存任务模式配置。");
      render();
    }
  } catch (error) {
    setFeedback(error.message, "error");
  }
});

document.addEventListener("change", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  if (target.dataset.action === "set-tool-risk") {
    currentAgent.tool_risk_overrides ||= {};
    currentAgent.tool_risk_overrides[target.dataset.id] = target.value;
    setFeedback("工具风险已写入当前配置草稿，记得保存任务模式配置。");
    render();
  }
});

document.addEventListener("input", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  if (target.dataset.action === "filter-plugins") {
    pluginFilter = target.value;
    renderAndRestoreInput("filter-plugins", pluginFilter);
  }
  if (target.dataset.action === "filter-tools") {
    toolFilter = target.value;
    renderAndRestoreInput("filter-tools", toolFilter);
  }
  if (target.dataset.action === "filter-blueprints") {
    blueprintFilter = target.value;
    renderAndRestoreInput("filter-blueprints", blueprintFilter);
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
