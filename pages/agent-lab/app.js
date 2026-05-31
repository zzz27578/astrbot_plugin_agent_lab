const EMPTY_TOOLS_SENTINEL = "__agent_lab_no_external_tools__";
const $ = (id) => document.getElementById(id);
const bridge = window.AstrBotPluginPage || createPreviewBridge();

let state = null;
let currentAgent = null;
let selectedAgentId = "";
let selectedTaskId = "";
let selectedModuleId = "";
let draftAgent = null;
let draftModule = null;

const label = {
  trigger: { manual: "手动", confirm: "确认", smart: "智能", always: "总是" },
  memory: { inherit: "继承", task_filtered: "任务过滤", strict: "严格" },
  approval: {
    observe: "观察",
    work: "工作",
    high_risk_review: "高风险审查",
    delegated: "委托",
  },
  heartbeat: { off: "关闭", manual: "手动", auto: "自动" },
};

function clone(value) {
  return JSON.parse(JSON.stringify(value || {}));
}

function escapeHtml(input) {
  return String(input ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setFeedback(message, tone = "normal") {
  const el = $("feedback");
  el.textContent = message;
  el.dataset.tone = tone;
}

function setResult(value) {
  $("result").textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function ensurePolicies(agent) {
  agent.identity_label_source ||= "manual";
  agent.memory_policy ||= {};
  agent.approval_policy ||= {};
  agent.heartbeat_policy ||= {};
  agent.plugin_overrides ||= {};
  agent.enabled_tools ||= [];
  agent.enabled_skills ||= [];
  agent.module_ids ||= [];
  return agent;
}

function getAgents() {
  return state?.agents || [];
}

function getTasks() {
  return state?.tasks || [];
}

function activeTask() {
  const tasks = getTasks();
  return tasks.find((task) => task.task_id === selectedTaskId) || tasks[0] || null;
}

function selectedModule() {
  const modules = state?.modules || [];
  return (
    draftModule ||
    modules.find((module) => module.module_id === selectedModuleId) ||
    modules[0] ||
    {}
  );
}

function readAgentForm() {
  if (!currentAgent) return null;
  ensurePolicies(currentAgent);
  currentAgent.enabled = $("agent-enabled").checked;
  currentAgent.name = $("agent-name").value.trim() || "未命名 Agent";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.memory_policy.mode = $("memory-mode").value;
  currentAgent.approval_policy.mode = $("approval-mode").value;
  currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").checked;
  currentAgent.system_prompt = $("system-prompt").value;
  currentAgent.task_prompt = $("task-prompt").value;
  return currentAgent;
}

function render() {
  if (!state) return;
  const agents = getAgents();
  const defaultAgentId = state.default_agent_id || agents[0]?.agent_id || "";

  if (agents.length && !agents.some((agent) => agent.agent_id === selectedAgentId)) {
    selectedAgentId = defaultAgentId;
  }

  currentAgent = ensurePolicies(
    clone(
      draftAgent ||
        agents.find((agent) => agent.agent_id === selectedAgentId) ||
        agents.find((agent) => agent.agent_id === defaultAgentId) ||
        agents[0] ||
        {},
    ),
  );

  const tasks = getTasks();
  if (tasks.length && !tasks.some((task) => task.task_id === selectedTaskId)) {
    selectedTaskId = tasks[0].task_id;
  }
  if (!tasks.length) selectedTaskId = "";

  const modules = state.modules || [];
  if (modules.length && !modules.some((module) => module.module_id === selectedModuleId)) {
    selectedModuleId = modules[0].module_id;
  }

  renderStats(defaultAgentId);
  renderAgentForm();
  renderAgentList(defaultAgentId);
  renderTaskList();
  renderArchiveList();
  renderTaskConsole();
  renderCapabilityLists();
  renderModuleList();
  renderModuleEditor();
  refreshButtonState();
}

function renderStats(defaultAgentId) {
  const defaultAgent = getAgents().find((agent) => agent.agent_id === defaultAgentId);
  $("stat-default").textContent = defaultAgent?.name || "-";
  $("stat-bot-label").textContent = state.runtime?.bot_label || "当前 Bot";
  $("stat-agents").textContent = String(getAgents().length);
  $("stat-active").textContent = String(getTasks().length);
  $("stat-archives").textContent = String((state.archives || []).length);
}

function renderAgentForm() {
  $("agent-enabled").checked = currentAgent.enabled !== false;
  $("agent-name").value = currentAgent.name || "";
  $("trigger-mode").value = currentAgent.trigger_mode || "confirm";
  $("memory-mode").value = currentAgent.memory_policy.mode || "task_filtered";
  $("approval-mode").value = currentAgent.approval_policy.mode || "work";
  $("heartbeat-mode").value = currentAgent.heartbeat_policy.mode || "manual";
  $("heartbeat-allowed").checked = currentAgent.heartbeat_policy.allowed !== false;
  $("system-prompt").value = currentAgent.system_prompt || "";
  $("task-prompt").value = currentAgent.task_prompt || "";
}

function itemButton(title, meta, selected = false, extra = "") {
  const el = document.createElement("button");
  el.type = "button";
  el.className = `list-item ${selected ? "selected" : ""}`;
  el.innerHTML = `
    <strong>${escapeHtml(title)}</strong>
    <span>${escapeHtml(meta)}</span>
    ${extra ? `<em>${escapeHtml(extra)}</em>` : ""}
  `;
  return el;
}

function renderAgentList(defaultAgentId) {
  const rows = getAgents().map((agent) => {
    const isDefault = agent.agent_id === defaultAgentId;
    const selected = !draftAgent && agent.agent_id === currentAgent.agent_id;
    const row = itemButton(
      `${isDefault ? "默认 · " : ""}${agent.name || "未命名 Agent"}`,
      `${agent.agent_id} · ${label.trigger[agent.trigger_mode] || agent.trigger_mode}`,
      selected,
      agent.enabled === false ? "停用" : "启用",
    );
    row.addEventListener("click", () => {
      draftAgent = null;
      selectedAgentId = agent.agent_id;
      render();
    });
    return row;
  });

  if (draftAgent) {
    const draft = itemButton("草稿 · " + (draftAgent.name || "新 Agent"), "保存后生成 ID", true);
    rows.unshift(draft);
  }

  $("agent-list").replaceChildren(...rows);
}

function renderTaskList() {
  const rows = getTasks().map((task) => {
    const selected = task.task_id === selectedTaskId;
    const row = itemButton(
      task.root_goal || task.task_id,
      `${task.status} · ${task.task_id}`,
      selected,
      task.heartbeat?.enabled ? "心跳中" : "",
    );
    row.addEventListener("click", () => {
      selectedTaskId = task.task_id;
      render();
    });
    return row;
  });
  $("task-list").replaceChildren(
    ...(rows.length ? rows : [emptyLine("暂无 active task")]),
  );
}

function renderArchiveList() {
  const archives = (state.archives || []).slice(0, 12);
  $("archive-list").replaceChildren(
    ...(archives.length
      ? archives.map((task) =>
          itemButton(
            task.root_goal || task.task_id,
            `${task.status} · ${task.finished_at || task.task_id}`,
          ),
        )
      : [emptyLine("暂无归档")]),
  );
}

function renderTaskConsole() {
  const task = activeTask();
  $("active-task-badge").textContent = task
    ? `${task.status}${task.heartbeat?.enabled ? " · 心跳中" : ""}`
    : "无任务";
  $("active-task-badge").className = `badge ${task ? "live" : "muted"}`;

  if (!task) {
    $("task-review").innerHTML = `<div class="empty-state">当前没有任务。可以在私聊使用 /agentlab start，也可以在这里填 UMO 后创建测试任务。</div>`;
    $("approvals").replaceChildren();
    $("heartbeat-toggle").textContent = "开心跳";
    return;
  }

  if (!$("umo").value.trim()) {
    $("umo").value = task.umo || "";
  }

  $("task-review").innerHTML = `
    <div class="task-grid">
      <div><span>任务 ID</span><strong>${escapeHtml(task.task_id)}</strong></div>
      <div><span>状态</span><strong>${escapeHtml(task.status)}</strong></div>
      <div><span>目标</span><strong>${escapeHtml(task.root_goal || "-")}</strong></div>
      <div><span>下一步</span><strong>${escapeHtml(task.next_step || "-")}</strong></div>
      <div><span>最近进展</span><strong>${escapeHtml(task.last_confirmed_progress || "-")}</strong></div>
      <div><span>状态文件</span><strong>${escapeHtml(task.archive_path || task.task_id + ".md")}</strong></div>
    </div>
  `;

  $("heartbeat-toggle").textContent = task.heartbeat?.enabled ? "关心跳" : "开心跳";
  renderApprovals(task);
}

function renderApprovals(task) {
  const pending = (task.approvals || []).filter((item) => item.status === "pending");
  if (!pending.length) {
    $("approvals").replaceChildren(emptyLine("暂无待审批操作"));
    return;
  }

  $("approvals").replaceChildren(
    ...pending.map((approval) => {
      const el = document.createElement("article");
      el.className = "approval";
      el.innerHTML = `
        <div>
          <strong>${escapeHtml(approval.operation)}</strong>
          <p>${escapeHtml(approval.reason || "未填写原因")}</p>
          <small>${escapeHtml(approval.impact || "未填写影响范围")}</small>
        </div>
        <div class="button-row">
          <button class="button" type="button" data-action="approve" data-id="${escapeHtml(approval.approval_id)}">通过</button>
          <button class="button secondary" type="button" data-action="reject" data-id="${escapeHtml(approval.approval_id)}">拒绝</button>
        </div>
      `;
      return el;
    }),
  );
}

function renderCapabilityLists() {
  renderPlugins();
  renderTools();
  renderSkills();
}

function renderPlugins() {
  const rows = (state.plugins || []).map((plugin) => {
    const override = currentAgent.plugin_overrides?.[plugin.name];
    const enabled = override === undefined ? Boolean(plugin.activated) : Boolean(override);
    const source = override === undefined ? "继承全局" : "任务覆盖";
    const locked = Boolean(plugin.locked);
    const el = toggleRow({
      title: plugin.display_name || plugin.name,
      meta: `${plugin.name} · ${source}`,
      enabled,
      locked,
      action: "toggle-plugin",
      resetAction: "reset-plugin",
      key: plugin.name,
    });
    return el;
  });
  $("plugins").replaceChildren(...rows);
}

function renderTools() {
  const rawList = currentAgent.enabled_tools || [];
  const inherit = rawList.length === 0;
  const whitelist = new Set(rawList.filter((name) => name !== EMPTY_TOOLS_SENTINEL));
  const rows = (state.tools || []).map((tool) => {
    const enabled = inherit ? Boolean(tool.active) : whitelist.has(tool.name);
    const source = inherit ? "继承全部" : "白名单";
    return toggleRow({
      title: tool.name,
      meta: `${source}${tool.risk ? " · " + tool.risk : ""}`,
      enabled,
      action: "toggle-tool",
      key: tool.name,
    });
  });
  $("tools").replaceChildren(...rows);
}

function renderSkills() {
  const selected = new Set(currentAgent.enabled_skills || []);
  const rows = (state.skills || []).map((skill) =>
    toggleRow({
      title: skill.name,
      meta: skill.active ? "AstrBot 中已启用" : "AstrBot 中未启用",
      enabled: selected.has(skill.name),
      action: "toggle-skill",
      key: skill.name,
    }),
  );
  $("skills").replaceChildren(...(rows.length ? rows : [emptyLine("未读取到 Skills")]));
}

function toggleRow({ title, meta, enabled, locked = false, action, resetAction = "", key }) {
  const row = document.createElement("div");
  row.className = `toggle-row ${enabled ? "enabled" : ""} ${locked ? "locked" : ""}`;
  row.innerHTML = `
    <div>
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(meta)}</span>
    </div>
    <div class="row-actions">
      ${locked ? `<em>已锁定</em>` : `<button class="button tiny" type="button" data-action="${action}" data-key="${escapeHtml(key)}">${enabled ? "停用" : "启用"}</button>`}
      ${resetAction && !locked ? `<button class="button tiny ghost" type="button" data-action="${resetAction}" data-key="${escapeHtml(key)}">继承</button>` : ""}
    </div>
  `;
  return row;
}

function renderModuleList() {
  const selected = new Set(currentAgent.module_ids || []);
  $("modules").replaceChildren(
    ...((state.modules || []).map((module) => {
      const active = selected.has(module.module_id);
      const item = document.createElement("article");
      item.className = `module-item ${active ? "enabled" : ""} ${module.module_id === selectedModuleId ? "selected" : ""}`;
      item.innerHTML = `
        <div>
          <strong>${escapeHtml(module.name)}</strong>
          <span>${escapeHtml(module.module_id)} · ${escapeHtml(module.source)}</span>
          <p>${escapeHtml(module.description || "")}</p>
        </div>
        <div class="button-row">
          <button class="button tiny secondary" type="button" data-action="select-module" data-key="${escapeHtml(module.module_id)}">查看</button>
          <button class="button tiny" type="button" data-action="toggle-module" data-key="${escapeHtml(module.module_id)}">${active ? "停用" : "启用"}</button>
        </div>
      `;
      return item;
    }) || []),
  );
}

function renderModuleEditor() {
  const module = selectedModule();
  $("module-id").value = module.module_id || "";
  $("module-name").value = module.name || "";
  $("module-source").value = module.source || "";
  $("module-description").value = module.description || "";
  $("module-prompt").value = module.prompt || "";
  $("module-links").value = (module.links || []).join("\n");
  $("module-capabilities").value = (module.capabilities || []).join(", ");
  $("module-requires").value = (module.requires || []).join(", ");

  const active = new Set(currentAgent.module_ids || []).has(module.module_id);
  $("toggle-selected-module").textContent = active ? "停用模块" : "启用模块";
}

function emptyLine(text) {
  const el = document.createElement("div");
  el.className = "empty-state";
  el.textContent = text;
  return el;
}

function refreshButtonState() {
  const hasAgent = Boolean(currentAgent?.agent_id || draftAgent);
  const task = activeTask();
  $("make-default").disabled = !currentAgent?.agent_id || Boolean(draftAgent);
  $("save-agent").disabled = !hasAgent;
  $("tick").disabled = !task;
  $("heartbeat-toggle").disabled = !task;
  $("finish").disabled = !task;
  $("cancel").disabled = !task;
  $("toggle-selected-module").disabled = !($("module-id").value.trim() || selectedModuleId);
}

async function load(options = {}) {
  try {
    state = await bridge.apiGet("state");
    render();
    if (!options.keepFeedback) {
      setFeedback(window.AstrBotPluginPage ? "已连接 AstrBot Dashboard。" : "本地预览模式：按钮只更新模拟数据。");
    }
  } catch (error) {
    setFeedback(`加载失败：${error?.message || error}`, "error");
    setResult(error?.stack || String(error));
  }
}

async function post(endpoint, body, okMessage = "操作完成。") {
  setFeedback("正在执行...");
  try {
    const result = await bridge.apiPost(endpoint, body);
    setResult(result);
    if (result?.ok === false) {
      setFeedback(result.error || "操作失败。", "error");
    } else {
      setFeedback(okMessage, "success");
    }
    await load({ keepFeedback: true });
    if (result?.ok !== false) {
      setFeedback(okMessage, "success");
    }
    return result;
  } catch (error) {
    setFeedback(`操作失败：${error?.message || error}`, "error");
    setResult(error?.stack || String(error));
    return null;
  }
}

function taskUmo() {
  return $("umo").value.trim() || activeTask()?.umo || "";
}

function requireUmo() {
  const value = taskUmo();
  if (!value) {
    setFeedback("请先填写 UMO，或选择一个当前任务。", "error");
    return "";
  }
  return value;
}

function readModuleEditor() {
  return {
    module_id: $("module-id").value.trim(),
    name: $("module-name").value.trim(),
    source: $("module-source").value.trim(),
    description: $("module-description").value.trim(),
    prompt: $("module-prompt").value.trim(),
    links: $("module-links").value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
    capabilities: $("module-capabilities").value.split(",").map((item) => item.trim()).filter(Boolean),
    requires: $("module-requires").value.split(",").map((item) => item.trim()).filter(Boolean),
  };
}

function persistAgentDraft() {
  readAgentForm();
  if (draftAgent) {
    draftAgent = clone(currentAgent);
    return;
  }
  const agents = [...getAgents()];
  const index = agents.findIndex((agent) => agent.agent_id === currentAgent.agent_id);
  if (index >= 0) {
    agents[index] = clone(currentAgent);
    state = { ...state, agents };
  }
}

function togglePlugin(name) {
  readAgentForm();
  const plugin = (state.plugins || []).find((item) => item.name === name);
  if (!plugin || plugin.locked) return;
  const override = currentAgent.plugin_overrides?.[name];
  const current = override === undefined ? Boolean(plugin.activated) : Boolean(override);
  currentAgent.plugin_overrides[name] = !current;
  persistAgentDraft();
  render();
  setFeedback("插件开关已修改，保存 Agent 后生效。");
}

function resetPlugin(name) {
  readAgentForm();
  delete currentAgent.plugin_overrides[name];
  persistAgentDraft();
  render();
  setFeedback("插件开关已恢复继承，保存 Agent 后生效。");
}

function knownToolNames() {
  return (state.tools || []).map((tool) => tool.name).filter(Boolean);
}

function setToolList(next) {
  currentAgent.enabled_tools =
    next.size === 0 ? [EMPTY_TOOLS_SENTINEL] : Array.from(next).sort();
}

function toggleTool(name) {
  readAgentForm();
  const rawList = currentAgent.enabled_tools || [];
  const inherit = rawList.length === 0;
  const next = inherit
    ? new Set(knownToolNames())
    : new Set(rawList.filter((item) => item !== EMPTY_TOOLS_SENTINEL));
  if (next.has(name)) next.delete(name);
  else next.add(name);
  setToolList(next);
  persistAgentDraft();
  render();
  setFeedback("工具白名单已修改，保存 Agent 后生效。");
}

function toggleSkill(name) {
  readAgentForm();
  const next = new Set(currentAgent.enabled_skills || []);
  if (next.has(name)) next.delete(name);
  else next.add(name);
  currentAgent.enabled_skills = Array.from(next).sort();
  persistAgentDraft();
  render();
  setFeedback("任务 Skills 已修改，保存 Agent 后生效。");
}

function toggleModule(moduleId) {
  readAgentForm();
  const next = new Set(currentAgent.module_ids || []);
  if (next.has(moduleId)) next.delete(moduleId);
  else next.add(moduleId);
  currentAgent.module_ids = Array.from(next).sort();
  selectedModuleId = moduleId;
  persistAgentDraft();
  render();
  setFeedback("模块启用状态已修改，保存 Agent 后生效。");
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const action = button.dataset.action;
  const key = button.dataset.key || "";
  const task = activeTask();

  if (action === "toggle-plugin") togglePlugin(key);
  if (action === "reset-plugin") resetPlugin(key);
  if (action === "toggle-tool") toggleTool(key);
  if (action === "toggle-skill") toggleSkill(key);
  if (action === "select-module") {
    draftModule = null;
    selectedModuleId = key;
    render();
  }
  if (action === "toggle-module") toggleModule(key);
  if (action === "approve" && task) {
    await post("task/approval", { umo: task.umo, approval_id: button.dataset.id, approved: true }, "审批已通过。");
  }
  if (action === "reject" && task) {
    await post("task/approval", { umo: task.umo, approval_id: button.dataset.id, approved: false }, "审批已拒绝。");
  }
});

$("refresh").addEventListener("click", load);
$("new-agent").addEventListener("click", () => {
  readAgentForm();
  draftAgent = ensurePolicies(clone(currentAgent || {}));
  delete draftAgent.agent_id;
  delete draftAgent.created_at;
  delete draftAgent.updated_at;
  draftAgent.name = "新 Agent";
  draftAgent.identity_label_source = "manual";
  draftAgent.enabled = true;
  render();
  setFeedback("已创建 Agent 草稿，保存后生效。");
});
$("duplicate-agent").addEventListener("click", () => {
  readAgentForm();
  draftAgent = ensurePolicies(clone(currentAgent || {}));
  delete draftAgent.agent_id;
  delete draftAgent.created_at;
  delete draftAgent.updated_at;
  draftAgent.name = `${currentAgent.name || "Agent"} 副本`;
  draftAgent.identity_label_source = "manual";
  render();
  setFeedback("已复制为草稿，保存后生效。");
});
$("make-default").addEventListener("click", async () => {
  if (!currentAgent?.agent_id || draftAgent) {
    setFeedback("请先保存草稿 Agent，再设为默认。", "error");
    return;
  }
  readAgentForm();
  const payload = clone(currentAgent);
  payload._make_default = true;
  const result = await post("agents", payload, "默认 Agent 已更新。");
  if (result?.agent?.agent_id) selectedAgentId = result.agent.agent_id;
});
$("save-agent").addEventListener("click", async () => {
  readAgentForm();
  const payload = clone(currentAgent);
  if (!payload.agent_id) delete payload.agent_id;
  const result = await post("agents", payload, "Agent 已保存。");
  if (result?.agent?.agent_id) {
    draftAgent = null;
    selectedAgentId = result.agent.agent_id;
  }
});
$("inherit-tools").addEventListener("click", () => {
  readAgentForm();
  currentAgent.enabled_tools = [];
  persistAgentDraft();
  render();
  setFeedback("工具白名单已恢复为继承全部。");
});
$("start").addEventListener("click", async () => {
  const umo = requireUmo();
  if (!umo) return;
  if (!currentAgent?.agent_id) {
    setFeedback("请先保存当前 Agent，再用它启动任务。", "error");
    return;
  }
  await post(
    "task/start",
    {
      umo,
      agent_id: currentAgent.agent_id,
      goal: $("goal").value.trim() || "WebUI 创建的任务",
      completion_conditions: "用户验收通过",
    },
    "任务已创建。",
  );
});
$("tick").addEventListener("click", async () => {
  const umo = requireUmo();
  if (umo) await post("task/tick", { umo }, "已推进一轮。");
});
$("heartbeat-toggle").addEventListener("click", async () => {
  const task = activeTask();
  const umo = requireUmo();
  if (!task || !umo) return;
  await post(
    "task/heartbeat",
    { umo, enabled: !task.heartbeat?.enabled },
    task.heartbeat?.enabled ? "心跳已关闭。" : "心跳已开启。",
  );
});
$("finish").addEventListener("click", async () => {
  const umo = requireUmo();
  if (umo) {
    await post("task/finish", { umo, status: "completed", summary: "WebUI 手动完成。" }, "任务已完成并归档。");
  }
});
$("cancel").addEventListener("click", async () => {
  const umo = requireUmo();
  if (umo) {
    await post("task/cancel", { umo, reason: "WebUI 手动取消。" }, "任务已取消并归档。");
  }
});
$("toggle-selected-module").addEventListener("click", () => {
  const moduleId = $("module-id").value.trim() || selectedModuleId;
  if (!moduleId) {
    setFeedback("请先选择或填写模块 ID。", "error");
    return;
  }
  toggleModule(moduleId);
});
$("new-module").addEventListener("click", () => {
  draftModule = {
    module_id: "my_agent_module",
    name: "我的 Agent 模块",
    source: "custom",
    description: "自定义 Agent Lab 模块。",
    prompt: "模块：我的 Agent 模块。请在这里写入任务模式行为协议。",
    links: [],
    capabilities: [],
    requires: [],
  };
  selectedModuleId = "";
  render();
  setFeedback("已创建模块草稿。");
});
$("duplicate-module").addEventListener("click", () => {
  draftModule = clone(selectedModule());
  draftModule.module_id = `${draftModule.module_id || "module"}_custom`;
  draftModule.name = `${draftModule.name || "模块"} 副本`;
  draftModule.source = `custom from ${draftModule.source || "module"}`;
  selectedModuleId = "";
  render();
  setFeedback("已复制为自定义模块草稿。");
});
$("save-module").addEventListener("click", async () => {
  const payload = readModuleEditor();
  if (!payload.module_id) {
    setFeedback("模块 ID 不能为空。", "error");
    return;
  }
  const result = await post("modules", payload, "模块已保存。");
  if (result?.module?.module_id) {
    draftModule = null;
    selectedModuleId = result.module.module_id;
  }
});

await bridge.ready();
await load();

function createPreviewBridge() {
  const previewState = {
    default_agent_id: "agent_preview",
    agents: [
      {
        agent_id: "agent_preview",
        name: "当前 Bot Agent Mode",
        identity_label_source: "astrbot_persona",
        enabled: true,
        trigger_mode: "confirm",
        system_prompt: "你仍然是当前 AstrBot 里的原本角色。",
        task_prompt: "先读取任务状态，再执行有限步骤，随后写回状态。",
        plugin_overrides: { memory_noise: false },
        enabled_tools: ["astrbot_file_read_tool", "astrbot_grep_tool", "astrbot_execute_python"],
        enabled_skills: ["agent-mode"],
        module_ids: ["checkpoint_state", "approval_guard", "heartbeat_protocol", "memory_gate"],
        memory_policy: { mode: "task_filtered" },
        approval_policy: { mode: "work" },
        heartbeat_policy: { mode: "manual", allowed: true },
      },
    ],
    tasks: [],
    archives: [],
    runtime: { bot_label: "当前 Bot", default_agent_name: "当前 Bot Agent Mode" },
    plugins: [
      { name: "astrbot_plugin_agent_lab", display_name: "Agent Lab", activated: true, locked: true },
      { name: "memory_noise", display_name: "记忆注入插件", activated: true, locked: false },
      { name: "memo", display_name: "小窝 Memo", activated: true, locked: false },
    ],
    tools: [
      { name: "astrbot_file_read_tool", active: true, risk: "safe" },
      { name: "astrbot_grep_tool", active: true, risk: "safe" },
      { name: "astrbot_execute_shell", active: true, risk: "work" },
      { name: "astrbot_execute_python", active: true, risk: "work" },
    ],
    skills: [
      { name: "agent-mode", active: true },
      { name: "heartbeat-protocol", active: true },
    ],
    modules: [
      {
        module_id: "checkpoint_state",
        name: "Checkpoint State",
        source: "LangGraph",
        description: "每轮任务落盘，支持恢复。",
        prompt: "任务状态是唯一真实来源。",
        links: ["https://docs.langchain.com/oss/python/langgraph/persistence"],
        capabilities: ["checkpoint"],
        requires: [],
      },
      {
        module_id: "approval_guard",
        name: "Approval Guard",
        source: "OpenAI Agents",
        description: "危险操作前置审批。",
        prompt: "危险操作前先说明影响并请求批准。",
        links: ["https://openai.github.io/openai-agents-python/guardrails/"],
        capabilities: ["approval"],
        requires: [],
      },
      {
        module_id: "memory_gate",
        name: "Memory Gate",
        source: "Deep Agents",
        description: "任务记忆和日常记忆分层。",
        prompt: "长期记忆不得覆盖 task_state。",
        links: ["https://docs.langchain.com/oss/python/deepagents/memory"],
        capabilities: ["memory"],
        requires: [],
      },
    ],
  };

  return {
    async ready() {},
    async apiGet() {
      return clone(previewState);
    },
    async apiPost(endpoint, body) {
      if (endpoint === "agents") {
        const payload = clone(body);
        const makeDefault = Boolean(payload._make_default);
        delete payload._make_default;
        payload.agent_id ||= `agent_${Date.now()}`;
        const index = previewState.agents.findIndex((agent) => agent.agent_id === payload.agent_id);
        if (index >= 0) previewState.agents[index] = payload;
        else previewState.agents.push(payload);
        if (makeDefault) previewState.default_agent_id = payload.agent_id;
        return { ok: true, agent: payload };
      }
      if (endpoint === "modules") {
        const payload = clone(body);
        const index = previewState.modules.findIndex((module) => module.module_id === payload.module_id);
        if (index >= 0) previewState.modules[index] = payload;
        else previewState.modules.push(payload);
        return { ok: true, module: payload };
      }
      if (endpoint === "task/start") {
        const task = {
          task_id: `task_${Date.now()}`,
          status: "running",
          umo: body.umo,
          root_goal: body.goal,
          next_step: "根据入口摘要制定第一轮计划。",
          last_confirmed_progress: "",
          heartbeat: { enabled: false },
          approvals: [],
        };
        previewState.tasks = [task];
        return { ok: true, message: "preview task created" };
      }
      const task = previewState.tasks[0];
      if (endpoint === "task/tick" && task) {
        task.last_confirmed_progress = "预览模式：已模拟推进一轮。";
        task.next_step = "继续验证任务归档。";
        return { ok: true, message: "preview tick" };
      }
      if (endpoint === "task/heartbeat" && task) {
        task.heartbeat.enabled = Boolean(body.enabled);
        return { ok: true, message: "preview heartbeat" };
      }
      if ((endpoint === "task/finish" || endpoint === "task/cancel") && task) {
        task.status = endpoint === "task/finish" ? "completed" : "cancelled";
        task.finished_at = new Date().toISOString();
        previewState.archives.unshift(task);
        previewState.tasks = [];
        return { ok: true, message: "preview archived" };
      }
      return { ok: true, message: "preview ok" };
    },
  };
}
