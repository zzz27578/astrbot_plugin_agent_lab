const $ = (id) => document.getElementById(id);
const qa = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const ICON_BASE = "https://raw.githubusercontent.com/Nieobie/Game-Icon-Pack/39dcf2b64947071c762395754ee9a5d3c8975906/svg-v1.0.3";
const ICONS = {
  brand: `${ICON_BASE}/6.Items/tool-kit.svg`,
  dashboard: `${ICON_BASE}/1.UI/grid-add.svg`,
  settings: `${ICON_BASE}/3.Editing%20Tools/select.svg`,
  workflow: `${ICON_BASE}/1.UI/grid-add.svg`,
  tasks: `${ICON_BASE}/6.Items/book.svg`,
  memory: `${ICON_BASE}/2.Media%20%26%20Technology/memory-card.svg`,
  monitor: `${ICON_BASE}/2.Media%20%26%20Technology/memory-card.svg`,
  integrations: `${ICON_BASE}/6.Items/tool-kit.svg`,
  registry: `${ICON_BASE}/6.Items/book.svg`,
  refresh: `${ICON_BASE}/3.Editing%20Tools/redo.svg`,
  menu: `${ICON_BASE}/1.UI/menu-open.svg`,
  add: `${ICON_BASE}/1.UI/grid-add.svg`,
  copy: `${ICON_BASE}/3.Editing%20Tools/copy.svg`,
  trash: `${ICON_BASE}/2.Media%20%26%20Technology/trash.svg`,
  play: `${ICON_BASE}/3.Editing%20Tools/select.svg`,
  check: `${ICON_BASE}/3.Editing%20Tools/select.svg`,
  save: `${ICON_BASE}/3.Editing%20Tools/copy.svg`,
  search: `${ICON_BASE}/3.Editing%20Tools/select.svg`,
};

const NAV = [
  ["dashboard", "总览", "看状态"],
  ["settings", "任务模式", "配置任务模板"],
  ["workflow", "工作流画布", "搭流程"],
  ["tasks", "任务控制", "启动与推进"],
  ["memory", "任务记忆", "筛选与回流"],
  ["monitor", "运行监控", "心跳与运行"],
  ["integrations", "插件与集成", "工具/接口/蓝图"],
  ["registry", "规则与凭证", "接口与技能"],
];

const STAGES = [
  ["entry", "入口", "触发、确认、上下文压缩"],
  ["plan", "计划", "拆解、路由、并行"],
  ["execute", "执行", "工具、插件、接口"],
  ["guard", "安全", "审批、人工接管、心跳"],
  ["checkpoint", "记录", "校验、状态、记忆"],
  ["archive", "出口", "通知、归档、回流"],
];

const NODE_TEMPLATES = [
  { id: "entry", title: "入口识别", kind: "trigger", stage: "entry", action: "summarize_entry", instruction: "识别命令、关键词、自然语言或控制台手动入口。" },
  { id: "entry_gate", title: "开启确认", kind: "human", stage: "entry", action: "confirm_entry", instruction: "需要确认时向用户说明隔离、记忆和审批边界。" },
  { id: "context_bridge", title: "上下文压缩", kind: "memory", stage: "entry", action: "summarize_entry", instruction: "把普通聊天压缩成 task_brief，只保留目标、约束、授权和风险。" },
  { id: "isolation_gate", title: "隔离快照", kind: "guard", stage: "entry", action: "restore_isolation", instruction: "进入任务前记录会话插件状态，并应用工具白名单。" },
  { id: "memory_recall", title: "任务记忆检索", kind: "retrieval", stage: "plan", action: "retrieve_memory", instruction: "按标签、任务或关键词读取可用任务记忆。" },
  { id: "plan", title: "计划确认", kind: "state", stage: "plan", action: "plan", instruction: "拆解完成条件、工具范围、风险等级和本轮有限步骤。" },
  { id: "risk_router", title: "风险分流", kind: "branch", stage: "plan", action: "route_condition", instruction: "把低风险、工作风险、高风险动作路由到不同节点。" },
  { id: "parallel_branch", title: "并行分支", kind: "branch", stage: "plan", action: "parallel_branch", instruction: "把互不依赖的检索、复核、测试任务拆给并行工作包。" },
  { id: "parallel_research", title: "并行检索包", kind: "subflow", stage: "execute", action: "manual", instruction: "只读收集证据、结论、风险和下一步建议。" },
  { id: "execute", title: "工具执行", kind: "tool", stage: "execute", action: "run_tools", instruction: "调用当前任务配置允许的 AstrBot 工具并写回关键结果。" },
  { id: "api_call", title: "自定义接口", kind: "api", stage: "execute", action: "call_api", instruction: "调用已注册接口；凭证由后端注入，不写入提示词。" },
  { id: "transform", title: "上下文整理", kind: "transform", stage: "execute", action: "transform_context", instruction: "把工具和接口输出整理成结构化观察。" },
  { id: "approval", title: "审批闸门", kind: "guard", stage: "guard", action: "request_approval", instruction: "危险动作前请求用户审批。" },
  { id: "human_handoff", title: "人工接管", kind: "human", stage: "guard", action: "handoff", instruction: "遇到登录、验证码、业务判断或重复阻塞时暂停等待输入。" },
  { id: "validation", title: "结果校验", kind: "validation", stage: "checkpoint", action: "validate_output", instruction: "对照完成条件、测试结果和副作用判断继续、重试或归档。" },
  { id: "retry_loop", title: "重试循环", kind: "loop", stage: "checkpoint", action: "retry", instruction: "有限重试，并记录失败原因、调整点和阻塞计数。" },
  { id: "checkpoint", title: "状态快照", kind: "state", stage: "checkpoint", action: "save_state", instruction: "写回进度、观察、下一步、阻塞点和验证结论。" },
  { id: "task_memory", title: "任务记忆", kind: "memory", stage: "checkpoint", action: "save_memory", instruction: "沉淀时间线、关键改动、成果、风险和续写入口。" },
  { id: "heartbeat", title: "心跳续跑", kind: "guard", stage: "guard", action: "heartbeat", instruction: "定时唤醒后先读 task_state，再推进一小步。" },
  { id: "notify", title: "完成通知", kind: "notification", stage: "archive", action: "notify", instruction: "归档前说明完成情况、验证结果和遗留风险。" },
  { id: "archive", title: "结束回流", kind: "memory", stage: "archive", action: "exit_summary", instruction: "完成或取消时归档成果、改动、风险和可回流记忆候选。" },
];

const DEFAULT_EDGES = [
  ["entry", "entry_gate"], ["entry_gate", "context_bridge"], ["context_bridge", "isolation_gate"], ["isolation_gate", "memory_recall"],
  ["memory_recall", "plan"], ["plan", "risk_router"], ["plan", "parallel_branch"], ["parallel_branch", "parallel_research"],
  ["parallel_branch", "execute"], ["risk_router", "execute"], ["risk_router", "api_call"], ["risk_router", "approval"],
  ["approval", "human_handoff"], ["approval", "execute"], ["human_handoff", "plan"], ["execute", "transform"], ["api_call", "transform"],
  ["parallel_research", "transform"], ["transform", "validation"], ["validation", "checkpoint"], ["validation", "retry_loop"],
  ["retry_loop", "execute"], ["checkpoint", "task_memory"], ["checkpoint", "heartbeat"], ["heartbeat", "plan"], ["task_memory", "notify"], ["notify", "archive"],
].map(([from, to]) => ({ from, to, edge_type: "success" }));

const KINDS = ["trigger", "state", "branch", "tool", "api", "guard", "human", "memory", "retrieval", "transform", "validation", "loop", "subflow", "notification", "detector", "report", "rate_limit", "error_handler"];
const ACTIONS = ["summarize_entry", "confirm_entry", "restore_isolation", "retrieve_memory", "plan", "route_condition", "parallel_branch", "manual", "run_tools", "call_api", "transform_context", "request_approval", "handoff", "validate_output", "retry", "save_state", "save_memory", "heartbeat", "notify", "archive", "exit_summary", "match_keyword", "match_regex", "llm_detect", "scope_filter", "schedule_trigger", "plugin_event_trigger", "webhook_trigger", "listen_message", "write_record", "generate_report", "send_message", "limit_rate", "catch_error"];
const WEBUI_VERSION = "20260609-loginfix2";
const API_TIMEOUT_MS = 7000;

const STATUS_LABELS = {
  all: "全部", active: "运行中", archived: "已归档", pending: "待处理", candidate: "候选", accepted: "已接受", rejected: "已拒绝",
  completed: "已完成", failed: "失败", cancelled: "已取消", canceled: "已取消", blocked: "已暂停", running: "运行中", idle: "空闲", ok: "正常",
};
const RISK_LABELS = { safe: "低风险", work: "工作风险", high: "高风险" };
const TRIGGER_LABELS = { manual: "手动", confirm: "先确认", smart: "低风险自动", always: "尽量使用" };
const ISOLATION_LABELS = { strict: "严格隔离", session: "会话隔离", off: "关闭隔离" };
const TOOL_MODE_LABELS = { whitelist: "白名单", no_external: "仅内置工具", full: "全部工具" };
const MEMORY_MODE_LABELS = { task_filtered: "任务过滤", inherit: "继承会话", strict: "严格任务记忆" };
const APPROVAL_LABELS = { observe: "仅观察", work: "工作审批", high_risk_review: "高风险复核", delegated: "委托执行" };
const HEARTBEAT_LABELS = { off: "关闭", manual: "手动", auto: "自动" };
const KIND_LABELS = {
  trigger: "触发", state: "状态", branch: "分支", tool: "工具", api: "接口", guard: "安全", human: "人工", memory: "记忆",
  retrieval: "检索", transform: "整理", validation: "校验", loop: "循环", subflow: "子流程", notification: "通知", detector: "检测", report: "报告",
  rate_limit: "限速", error_handler: "错误处理",
};
const ACTION_LABELS = {
  summarize_entry: "入口摘要", confirm_entry: "入口确认", restore_isolation: "恢复隔离", retrieve_memory: "检索记忆", plan: "制定计划",
  route_condition: "条件路由", parallel_branch: "并行分支", manual: "人工步骤", run_tools: "执行工具", call_api: "调用接口",
  transform_context: "整理上下文", request_approval: "请求审批", handoff: "人工接管", validate_output: "校验结果", retry: "重试",
  save_state: "保存状态", save_memory: "保存记忆", heartbeat: "心跳续跑", notify: "发送通知", archive: "归档", exit_summary: "出口摘要",
  match_keyword: "匹配关键词", match_regex: "匹配正则", llm_detect: "模型检测", scope_filter: "范围过滤", schedule_trigger: "定时触发",
  plugin_event_trigger: "插件事件触发", webhook_trigger: "外部回调触发", listen_message: "监听消息", write_record: "写入记录",
  generate_report: "生成报告", send_message: "发送消息", limit_rate: "限制频率", catch_error: "捕获错误",
};
const SOURCE_LABELS = { astrbot_runtime: "AstrBot 运行时", persona: "人格配置", config: "AstrBot 配置", fallback: "默认占位", webui: "控制台", manual_webui: "控制台手动" };

const app = {
  route: localStorage.getItem("agent_lab_route") || "dashboard",
  state: null,
  currentAgent: null,
  selectedAgentId: "",
  selectedTaskId: "",
  selectedMemoryId: "",
  selectedModuleId: "",
  memoryFilter: "all",
  taskLogs: {},
  integrationTab: "plugins",
  registryTab: "apis",
  bootId: 0,
  loadId: 0,
  authToken: "",
  workflow: { zoom: 0.82, x: 60, y: 70, selectedNodeId: "", linkingFrom: "", report: null, dryRun: null, dragging: null, panning: null, materialFilter: "", contextMenu: null },
};

function esc(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[ch]));
}
function attr(value) { return esc(value).replace(/\n/g, " "); }
function clone(value) { return JSON.parse(JSON.stringify(value ?? null)); }
function lines(value) { return Array.isArray(value) ? value.map(String).map((x) => x.trim()).filter(Boolean) : String(value || "").split(/[\n,，]+/).map((x) => x.trim()).filter(Boolean); }
function listText(value) { return Array.isArray(value) ? value.join("\n") : String(value || ""); }
function icon(name, label = "") { return `<img class="game-icon" src="${ICONS[name] || ICONS.brand}" alt="${attr(label)}" />`; }
function badge(text, tone = "") { return `<span class="badge ${tone}">${esc(text)}</span>`; }
function compactId(value) { const text = String(value || ""); return text.length > 18 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text || "-"; }
function token() {
  try {
    return sessionStorage.getItem("agent_lab_token") || app.authToken || "";
  } catch {
    return app.authToken || "";
  }
}
function saveToken(value) {
  app.authToken = String(value || "").trim();
  try {
    if (app.authToken) sessionStorage.setItem("agent_lab_token", app.authToken);
    else sessionStorage.removeItem("agent_lab_token");
  } catch {
    // Some embedded browsers can deny sessionStorage; keep the token in memory for this page load.
  }
}
function clearToken() { saveToken(""); }
function labelOf(map, value) { return map[String(value || "")] || value || "-"; }
function statusLabel(value) { return labelOf(STATUS_LABELS, value); }
function riskLabel(value) { return labelOf(RISK_LABELS, value); }
function sourceLabel(value) { return labelOf(SOURCE_LABELS, value); }
function selectOptions(map, values) { return values.map((id) => [id, map[id] || id]); }

function safeAuthHeaders() {
  const value = token();
  if (!value) return {};
  try {
    new Headers({ Authorization: `Bearer ${value}`, "X-Agent-Lab-Token": value });
    return { Authorization: `Bearer ${value}`, "X-Agent-Lab-Token": value };
  } catch {
    return {};
  }
}

function addTokenToPath(path) {
  if (!token()) return path;
  const text = String(path || "");
  const [base, hash = ""] = text.split("#", 2);
  const [pathname, search = ""] = base.split("?", 2);
  const params = new URLSearchParams(search);
  params.set("token", token());
  return `${pathname}?${params.toString()}${hash ? `#${hash}` : ""}`;
}

async function fetchWithTimeout(path, options = {}) {
  const controller = new AbortController();
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      const error = new Error(`请求超时：${path}`);
      error.name = "AbortError";
      reject(error);
    }, API_TIMEOUT_MS);
  });
  try {
    return await Promise.race([fetch(path, { ...options, signal: controller.signal }), timeout]);
  } finally {
    clearTimeout(timer);
  }
}

function toast(message, tone = "ok") {
  const item = document.createElement("div");
  item.className = `toast ${tone}`;
  item.textContent = message;
  $("toast-host").appendChild(item);
  setTimeout(() => item.remove(), 4200);
}

function setAuthStatus(message, tone = "") {
  const el = $("auth-status");
  if (!el) return;
  el.textContent = message;
  el.dataset.tone = tone;
}

function updateAuthVersion() {
  const el = $("auth-version");
  if (el) el.textContent = `前端版本：${WEBUI_VERSION}`;
}

function showAuth(message = "请输入插件配置 standalone_webui_token 中的访问密码。", tone = "") {
  $("auth").hidden = false;
  $("app").hidden = true;
  setAuthStatus(message, tone);
  setTimeout(() => $("token-input")?.focus(), 0);
}

function showApp() {
  $("auth").hidden = true;
  $("app").hidden = false;
}

function renderLoadError(error) {
  document.body.dataset.route = app.route;
  $("brand-icon").src = ICONS.brand;
  $("auth-icon").src = ICONS.brand;
  $("refresh").innerHTML = icon("refresh", "刷新");
  $("collapse-nav").innerHTML = icon("menu", "侧栏");
  $("page-title").textContent = "连接失败";
  $("page-subtitle").textContent = "访问密码已提交，但控制台数据暂时没有加载成功";
  $("nav").innerHTML = NAV.map(([id, title, sub]) => `<button class="${app.route === id ? "active" : ""}" data-route="${id}" type="button">${icon(id)}<span><strong>${title}</strong><small>${sub}</small></span></button>`).join("");
  $("identity-name").textContent = "未连接";
  $("identity-source").textContent = "等待数据";
  $("agent-select").innerHTML = `<option>暂无任务配置</option>`;
  $("view").innerHTML = `<section class="panel load-error"><h2>控制台数据加载失败</h2><p>${esc(error.message || "后端接口没有返回可用数据。")}</p>${error.endpoint ? `<p>失败接口：${esc(error.endpoint)}</p>` : ""}<p>前端版本：${WEBUI_VERSION}</p><div class="row"><button class="button primary" id="retry-load" type="button">重新加载</button><button class="button" id="reenter-token" type="button">重新输入访问密码</button></div></section>`;
  $("retry-load")?.addEventListener("click", () => boot().catch((err) => toast(err.message, "error")));
  $("reenter-token")?.addEventListener("click", () => { clearToken(); showAuth("请重新输入插件配置 standalone_webui_token 中的访问密码。"); });
}

function renderLoading(message = "正在加载控制台数据...") {
  document.body.dataset.route = app.route;
  $("brand-icon").src = ICONS.brand;
  $("auth-icon").src = ICONS.brand;
  $("refresh").innerHTML = icon("refresh", "刷新");
  $("collapse-nav").innerHTML = icon("menu", "侧栏");
  $("page-title").textContent = "正在连接";
  $("page-subtitle").textContent = message;
  $("nav").innerHTML = NAV.map(([id, title, sub]) => `<button class="${app.route === id ? "active" : ""}" data-route="${id}" type="button">${icon(id)}<span><strong>${title}</strong><small>${sub}</small></span></button>`).join("");
  $("identity-name").textContent = "正在读取";
  $("identity-source").textContent = "控制台数据";
  $("agent-select").innerHTML = `<option>正在加载任务配置</option>`;
  $("view").innerHTML = `<section class="panel load-error"><h2>正在加载控制台</h2><p id="load-step">${esc(message)}</p><p>前端版本：${WEBUI_VERSION}</p></section>`;
}

function setLoadingStep(message) {
  const subtitle = $("page-subtitle");
  if (subtitle) subtitle.textContent = message;
  const el = $("load-step");
  if (el) el.textContent = message;
}

async function api(path, options = {}) {
  const headers = { ...safeAuthHeaders(), ...(options.headers || {}) };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  const endpoint = token() ? addTokenToPath(path) : path;
  const response = await fetchWithTimeout(endpoint, { ...options, headers });
  let payload = {};
  try { payload = await response.json(); } catch { payload = {}; }
  if (!response.ok) {
    const error = new Error(payload.error || `${response.status} ${response.statusText}：${endpoint}`);
    error.status = response.status;
    error.endpoint = endpoint;
    throw error;
  }
  if (payload.ok === false) {
    const error = new Error(payload.error || "请求失败");
    error.endpoint = path;
    throw error;
  }
  return payload;
}

function defaultNodes() {
  return NODE_TEMPLATES.map((node, index) => ({ ...clone(node), x: 80 + Math.floor(index / 4) * 360, y: 80 + (index % 4) * 190 }));
}

function ensureAgent(agent = {}) {
  const base = {
    agent_id: agent.agent_id || "",
    name: agent.name || "",
    identity_label_source: agent.identity_label_source || "astrbot_runtime",
    description: agent.description || "把 AstrBot 会话切换为可持续推进、可审批、可归档的任务模式。",
    enabled: agent.enabled !== false,
    trigger_mode: agent.trigger_mode || "confirm",
    application_scope: agent.application_scope || "entry",
    entry_channel: agent.entry_channel || "command",
    workflow_trigger: agent.workflow_trigger || {},
    workflow_scope: agent.workflow_scope || {},
    entry_policy: agent.entry_policy || {},
    isolation_policy: agent.isolation_policy || {},
    memory_policy: agent.memory_policy || {},
    approval_policy: agent.approval_policy || {},
    heartbeat_policy: agent.heartbeat_policy || {},
    system_prompt: agent.system_prompt || "你仍然是当前 AstrBot 的原本角色，但进入任务模式后以任务推进为中心。",
    task_prompt: agent.task_prompt || "先读取任务状态，再执行一个有限步骤，随后总结并写回状态。",
    plugin_overrides: agent.plugin_overrides || {},
    tool_risk_overrides: agent.tool_risk_overrides || {},
    enabled_tools: Array.isArray(agent.enabled_tools) ? agent.enabled_tools : [],
    enabled_skills: Array.isArray(agent.enabled_skills) ? agent.enabled_skills : [],
    module_ids: Array.isArray(agent.module_ids) ? agent.module_ids : ["checkpoint_state", "approval_guard", "heartbeat_protocol", "memory_gate"],
    module_settings: agent.module_settings || {},
    workflow_nodes: Array.isArray(agent.workflow_nodes) && agent.workflow_nodes.length ? agent.workflow_nodes : defaultNodes(),
    workflow_edges: Array.isArray(agent.workflow_edges) && agent.workflow_edges.length ? agent.workflow_edges : clone(DEFAULT_EDGES),
  };
  base.workflow_trigger = {
    enabled: base.workflow_trigger.enabled !== false,
    types: Array.isArray(base.workflow_trigger.types) ? base.workflow_trigger.types : ["command", "manual_webui"],
    command_names: Array.isArray(base.workflow_trigger.command_names) ? base.workflow_trigger.command_names : ["agentlab", "al"],
    keywords: Array.isArray(base.workflow_trigger.keywords) ? base.workflow_trigger.keywords : [],
    regex: Array.isArray(base.workflow_trigger.regex) ? base.workflow_trigger.regex : [],
    cron: base.workflow_trigger.cron || "",
    cron_expressions: Array.isArray(base.workflow_trigger.cron_expressions) ? base.workflow_trigger.cron_expressions : [],
    plugin_events: Array.isArray(base.workflow_trigger.plugin_events) ? base.workflow_trigger.plugin_events : [],
    webhook_path: base.workflow_trigger.webhook_path || "",
  };
  base.workflow_scope = {
    chat_types: Array.isArray(base.workflow_scope.chat_types) ? base.workflow_scope.chat_types : ["private"],
    platforms: Array.isArray(base.workflow_scope.platforms) ? base.workflow_scope.platforms : [],
    umo_allowlist: Array.isArray(base.workflow_scope.umo_allowlist) ? base.workflow_scope.umo_allowlist : [],
    umo_denylist: Array.isArray(base.workflow_scope.umo_denylist) ? base.workflow_scope.umo_denylist : [],
    group_allowlist: Array.isArray(base.workflow_scope.group_allowlist) ? base.workflow_scope.group_allowlist : [],
    group_denylist: Array.isArray(base.workflow_scope.group_denylist) ? base.workflow_scope.group_denylist : [],
    user_allowlist: Array.isArray(base.workflow_scope.user_allowlist) ? base.workflow_scope.user_allowlist : [],
    user_denylist: Array.isArray(base.workflow_scope.user_denylist) ? base.workflow_scope.user_denylist : [],
    admin_only: !!base.workflow_scope.admin_only,
  };
  base.entry_policy = {
    trigger_phrases: Array.isArray(base.entry_policy.trigger_phrases) ? base.entry_policy.trigger_phrases : ["进入任务模式", "/agentlab start", "/al start"],
    trigger_keywords: Array.isArray(base.entry_policy.trigger_keywords) ? base.entry_policy.trigger_keywords : ["持续推进", "排查", "部署", "写插件", "改代码"],
    require_confirmation: base.entry_policy.require_confirmation !== false,
    confirmation_text: base.entry_policy.confirmation_text || "我会进入任务模式：隔离当前会话插件、压缩上下文、创建 task_state，并在高风险动作前请求审批。是否开启？",
    default_completion_conditions: Array.isArray(base.entry_policy.default_completion_conditions) ? base.entry_policy.default_completion_conditions : ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"],
    exit_phrases: Array.isArray(base.entry_policy.exit_phrases) ? base.entry_policy.exit_phrases : ["完成任务", "退出任务模式", "/agentlab finish", "/agentlab cancel"],
  };
  base.isolation_policy = { mode: base.isolation_policy.mode || "strict", tool_mode: base.isolation_policy.tool_mode || "whitelist", restore_on_exit: base.isolation_policy.restore_on_exit !== false, protect_self: base.isolation_policy.protect_self !== false, hide_disabled_plugin_tools: base.isolation_policy.hide_disabled_plugin_tools !== false };
  base.memory_policy = { mode: base.memory_policy.mode || "task_filtered", entry_summary_turns: Number(base.memory_policy.entry_summary_turns || 24), keep_identity: base.memory_policy.keep_identity !== false, allow_long_memory: base.memory_policy.allow_long_memory !== false, exit_memory_candidates: base.memory_policy.exit_memory_candidates !== false, compression_enabled: base.memory_policy.compression_enabled !== false, compression_strategy: base.memory_policy.compression_strategy || "smart_extract", compression_max_tokens: Number(base.memory_policy.compression_max_tokens || 6000), preserve_keywords: Array.isArray(base.memory_policy.preserve_keywords) ? base.memory_policy.preserve_keywords : [] };
  base.approval_policy = { mode: base.approval_policy.mode || "work", preapproved_scopes: Array.isArray(base.approval_policy.preapproved_scopes) ? base.approval_policy.preapproved_scopes : [], require_approval: Array.isArray(base.approval_policy.require_approval) ? base.approval_policy.require_approval : ["file_delete", "bulk_overwrite", "git_reset", "deployment", "secret_read"], note: base.approval_policy.note || "高风险动作前主动说明影响和回滚方式。" };
  base.heartbeat_policy = { allowed: base.heartbeat_policy.allowed !== false, mode: base.heartbeat_policy.mode || "manual", enabled: !!base.heartbeat_policy.enabled, cron_expression: base.heartbeat_policy.cron_expression || "*/5 * * * *", max_repeated_failures: Number(base.heartbeat_policy.max_repeated_failures || 3) };
  return base;
}

function prepareState(rawState) {
  const previous = app.state || {};
  app.state = {
    ...rawState,
    modules: rawState.modules || previous.modules || [],
    discovered_modules: rawState.discovered_modules || previous.discovered_modules || [],
    plugin_modules: rawState.plugin_modules || previous.plugin_modules || [],
    tool_modules: rawState.tool_modules || previous.tool_modules || [],
    builtin_modules: rawState.builtin_modules || previous.builtin_modules || [],
    workflow_runs: rawState.workflow_runs || previous.workflow_runs || { counts: {}, runs: [] },
  };
  const agents = app.state.agents || [];
  app.selectedAgentId = app.selectedAgentId || app.state.default_agent_id || agents[0]?.agent_id || "";
  if (!agents.some((agent) => agent.agent_id === app.selectedAgentId)) app.selectedAgentId = agents[0]?.agent_id || "";
  app.currentAgent = ensureAgent(clone(agents.find((agent) => agent.agent_id === app.selectedAgentId) || agents[0] || {}));
}

async function hydrateOptionalState(loadId) {
  let changed = false;
  try {
    const modules = await api("/api/modules");
    if (loadId !== app.loadId) return;
    Object.assign(app.state, {
      modules: modules.modules || app.state.modules || [],
      discovered_modules: modules.discovered_modules || [],
      plugin_modules: modules.plugin_modules || [],
      tool_modules: modules.tool_modules || [],
      builtin_modules: modules.builtin_modules || [],
    });
    changed = true;
  } catch (error) {
    console.warn("module discovery failed", error);
  }
  try {
    const runs = await api("/api/workflow/runs?limit=80");
    if (loadId !== app.loadId) return;
    app.state.workflow_runs = runs;
    changed = true;
  } catch (error) {
    console.warn("workflow runs failed", error);
  }
  if (changed && loadId === app.loadId) {
    updateChrome();
    render();
  }
}

async function load() {
  const loadId = ++app.loadId;
  setLoadingStep("正在读取控制台状态");
  const state = await api("/api/state");
  if (loadId !== app.loadId) return;
  prepareState(state);
  updateChrome();
  render();
  hydrateOptionalState(loadId).catch((error) => console.warn("optional state failed", error));
}

function updateChrome() {
  document.body.dataset.route = app.route;
  $("brand-icon").src = ICONS.brand;
  $("auth-icon").src = ICONS.brand;
  $("refresh").innerHTML = icon("refresh", "刷新");
  $("collapse-nav").innerHTML = icon("menu", "侧栏");
  $("nav").innerHTML = NAV.map(([id, title, sub]) => `<button class="${app.route === id ? "active" : ""}" data-route="${id}" type="button">${icon(id)}<span><strong>${title}</strong><small>${sub}</small></span></button>`).join("");
  const runtime = app.state?.runtime || {};
  $("identity-name").textContent = runtime.display_name || runtime.name || app.currentAgent?.name || "当前机器人";
  $("identity-source").textContent = sourceLabel(runtime.source || app.currentAgent?.identity_label_source || "astrbot_runtime");
  const selected = NAV.find(([id]) => id === app.route) || NAV[0];
  $("page-title").textContent = selected[1];
  $("page-subtitle").textContent = selected[2];
  const agents = app.state?.agents || [];
  $("agent-select").innerHTML = agents.map((agent) => `<option value="${attr(agent.agent_id)}" ${agent.agent_id === app.selectedAgentId ? "selected" : ""}>${esc(agent.name || app.state?.runtime?.display_name || "未命名配置")} · ${compactId(agent.agent_id)}</option>`).join("");
}

function setRoute(route) {
  app.route = route;
  localStorage.setItem("agent_lab_route", route);
  updateChrome();
  render();
}

function render() {
  if (!app.state || !app.currentAgent) return;
  const view = $("view");
  const renderers = { dashboard: renderDashboard, settings: renderSettings, workflow: renderWorkflow, tasks: renderTasks, memory: renderMemoryV2, monitor: renderMonitor, integrations: renderIntegrationsV2, registry: renderRegistry };
  view.innerHTML = (renderers[app.route] || renderDashboard)();
  if (app.route === "workflow") mountWorkflow();
}

function metrics() {
  const tasks = app.state.tasks || [];
  const archives = app.state.archives || [];
  const memories = app.state.memories || [];
  const pending = [...tasks, ...archives].flatMap((task) => task.approvals || []).filter((item) => item.status === "pending").length;
  const tokens = [...tasks, ...archives].reduce((sum, task) => sum + Number(task.token_usage?.total || 0), 0);
  const runs = app.state.workflow_runs?.counts || {};
  return { agents: (app.state.agents || []).length, tasks: tasks.length, archives: archives.length, memories: memories.length, pending, tokens, runs: runs.total || 0, activeRuns: runs.active || 0 };
}

function renderDashboard() {
  const m = metrics();
  const active = app.state.tasks || [];
  const agents = app.state.agents || [];
  return `<div class="stack">
    <section class="hero panel"><div><p class="eyebrow">Agent Lab</p><h1>把长任务和自动化流程放到一张清楚的控制台里。</h1><p>先选一个任务配置，设置触发、隔离和审批，再在画布里组合节点。后端负责持久化、心跳、任务记忆、插件工具和自定义接口。</p></div><div class="hero-actions"><button class="button primary" data-route="workflow">打开画布</button><button class="button" data-route="tasks">启动任务</button><button class="button danger" data-action="delete-agent">删除当前配置</button></div></section>
    <section class="metric-grid">${stat("任务配置", m.agents, "配置数量")}${stat("运行中", m.tasks, "当前任务")}${stat("工作流运行", m.runs, `${m.activeRuns} 个活跃`)}${stat("待审批", m.pending, "等待处理")}${stat("任务记忆", m.memories, "记忆条目")}${stat("用量", m.tokens, "累计令牌")}</section>
    <section class="split"><div class="panel"><div class="panel-head"><h2>任务配置</h2><button class="button small" data-action="new-agent">新建</button></div><div class="list">${agents.map(agentCard).join("") || empty("没有任务配置")}</div></div>
    <div class="panel"><div class="panel-head"><h2>运行中任务</h2><button class="button small" data-route="tasks">查看</button></div><div class="list">${active.slice(0, 6).map(taskCard).join("") || empty("当前没有运行中的任务")}</div></div></section>
  </div>`;
}

function stat(label, value, hint) { return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(hint)}</small></div>`; }
function empty(text) { return `<div class="empty">${esc(text)}</div>`; }
function agentTitle(agent) { return agent.name || app.state?.runtime?.display_name || "跟随 AstrBot 身份"; }
function agentCard(agent) {
  const active = agent.agent_id === app.selectedAgentId;
  return `<button class="list-row ${active ? "selected" : ""}" data-action="select-agent" data-id="${attr(agent.agent_id)}" type="button"><strong>${esc(agentTitle(agent))}</strong><span>${compactId(agent.agent_id)} · ${esc(labelOf(TRIGGER_LABELS, agent.trigger_mode || "confirm"))} · ${esc(labelOf(ISOLATION_LABELS, agent.isolation_policy?.mode || "strict"))}</span></button>`;
}
function taskCard(task) {
  const pending = (task.approvals || []).filter((item) => item.status === "pending").length;
  return `<button class="list-row" data-action="select-task" data-id="${attr(task.task_id)}" type="button"><strong>${esc(task.root_goal || task.agent_name || task.task_id)}</strong><span>${esc(statusLabel(task.status))} · ${compactId(task.umo)} ${pending ? `· ${pending} 个审批` : ""}</span></button>`;
}

function field(label, id, value = "", type = "text", extra = "") { return `<label><span>${esc(label)}</span><input id="${id}" type="${type}" value="${attr(value)}" ${extra} /></label>`; }
function area(label, id, value = "", rows = 4) { return `<label class="span-2"><span>${esc(label)}</span><textarea id="${id}" rows="${rows}">${esc(value)}</textarea></label>`; }
function selectField(label, id, value, options) { return `<label><span>${esc(label)}</span><select id="${id}">${options.map((item) => `<option value="${attr(item[0])}" ${item[0] === value ? "selected" : ""}>${esc(item[1])}</option>`).join("")}</select></label>`; }
function checkField(label, id, checked) { return `<label class="check"><input id="${id}" type="checkbox" ${checked ? "checked" : ""} /><span>${esc(label)}</span></label>`; }

function renderSettings() {
  const a = app.currentAgent;
  return `<div class="stack"><section class="panel"><div class="panel-head"><div><h2>任务模式配置</h2><p>名称留空时继续跟随 AstrBot 当前人格或配置名。</p></div><div class="row"><button class="button" data-action="duplicate-agent">复制</button><button class="button primary" data-action="save-agent">保存</button><button class="button" data-action="make-default">设为默认</button></div></div>
    <div class="form-grid">
      ${field("配置名称", "agent-name", a.name)}${selectField("触发模式", "trigger-mode", a.trigger_mode, selectOptions(TRIGGER_LABELS, ["manual", "confirm", "smart", "always"]))}
      ${selectField("应用范围", "application-scope", a.application_scope, [["entry", "入口触发"], ["global", "全局监控"]])}${selectField("入口渠道", "entry-channel", a.entry_channel, [["command", "命令"], ["natural", "自然语言"], ["webui", "控制台"]])}
      ${area("说明", "agent-description", a.description, 3)}${area("系统提示补充", "system-prompt", a.system_prompt, 5)}${area("任务提示补充", "task-prompt", a.task_prompt, 5)}
    </div></section>
    <section class="split"><div class="panel"><h2>触发与范围</h2><div class="form-grid single">
      ${checkField("启用工作流触发", "workflow-trigger-enabled", a.workflow_trigger.enabled)}${area("触发类型", "workflow-trigger-types", listText(a.workflow_trigger.types), 3)}${area("命令名", "command-names", listText(a.workflow_trigger.command_names), 3)}${area("关键词", "trigger-keywords", listText(a.workflow_trigger.keywords), 3)}${area("正则", "trigger-regex", listText(a.workflow_trigger.regex), 3)}${field("定时表达式", "trigger-cron", a.workflow_trigger.cron)}${field("外部回调路径", "webhook-path", a.workflow_trigger.webhook_path)}${checkField("仅管理员", "admin-only", a.workflow_scope.admin_only)}${area("会话类型", "chat-types", listText(a.workflow_scope.chat_types), 2)}${area("会话白名单", "umo-allow", listText(a.workflow_scope.umo_allowlist), 3)}${area("入口短语", "entry-phrases", listText(a.entry_policy.trigger_phrases), 4)}${area("入口关键词", "entry-keywords", listText(a.entry_policy.trigger_keywords), 4)}${area("确认文案", "entry-confirmation", a.entry_policy.confirmation_text, 4)}${area("退出短语", "exit-phrases", listText(a.entry_policy.exit_phrases), 3)}${area("默认完成条件", "completion-conditions", listText(a.entry_policy.default_completion_conditions), 3)}
    </div></div><div class="panel"><h2>记忆 / 审批 / 心跳</h2><div class="form-grid single">
      ${selectField("隔离模式", "isolation-mode", a.isolation_policy.mode, selectOptions(ISOLATION_LABELS, ["strict", "session", "off"]))}${selectField("工具模式", "tool-mode", a.isolation_policy.tool_mode, selectOptions(TOOL_MODE_LABELS, ["whitelist", "no_external", "full"]))}${selectField("记忆模式", "memory-mode", a.memory_policy.mode, selectOptions(MEMORY_MODE_LABELS, ["task_filtered", "inherit", "strict"]))}${field("压缩上限", "compression-max", a.memory_policy.compression_max_tokens, "number")}${area("保留关键词", "preserve-keywords", listText(a.memory_policy.preserve_keywords), 3)}${selectField("审批模式", "approval-mode", a.approval_policy.mode, selectOptions(APPROVAL_LABELS, ["observe", "work", "high_risk_review", "delegated"]))}${area("预授权范围", "preapproved-scopes", listText(a.approval_policy.preapproved_scopes), 3)}${area("必须审批动作", "require-approval", listText(a.approval_policy.require_approval), 3)}${area("审批备注", "approval-note", a.approval_policy.note, 3)}${selectField("心跳模式", "heartbeat-mode", a.heartbeat_policy.mode, selectOptions(HEARTBEAT_LABELS, ["off", "manual", "auto"]))}${field("心跳定时", "heartbeat-cron", a.heartbeat_policy.cron_expression)}
    </div></div></section></div>`;
}

function readAgentForm() {
  const a = app.currentAgent;
  if ($("agent-name")) {
    a.name = $("agent-name").value.trim();
    a.identity_label_source = a.name ? "manual" : "astrbot_runtime";
    a.trigger_mode = $("trigger-mode").value;
    a.application_scope = $("application-scope").value;
    a.entry_channel = $("entry-channel").value;
    a.description = $("agent-description").value;
    a.system_prompt = $("system-prompt").value;
    a.task_prompt = $("task-prompt").value;
  }
  if ($("workflow-trigger-enabled")) {
    a.workflow_trigger.enabled = $("workflow-trigger-enabled").checked;
    a.workflow_trigger.types = lines($("workflow-trigger-types").value);
    a.workflow_trigger.command_names = lines($("command-names").value);
    a.workflow_trigger.keywords = lines($("trigger-keywords").value);
    a.workflow_trigger.regex = lines($("trigger-regex").value);
    a.workflow_trigger.cron = $("trigger-cron").value.trim();
    a.workflow_trigger.webhook_path = $("webhook-path").value.trim();
    a.workflow_scope.admin_only = $("admin-only").checked;
    a.workflow_scope.chat_types = lines($("chat-types").value);
    a.workflow_scope.umo_allowlist = lines($("umo-allow").value);
    a.entry_policy.trigger_phrases = lines($("entry-phrases").value);
    a.entry_policy.trigger_keywords = lines($("entry-keywords").value);
    a.entry_policy.confirmation_text = $("entry-confirmation").value;
    a.entry_policy.exit_phrases = lines($("exit-phrases").value);
    a.entry_policy.default_completion_conditions = lines($("completion-conditions").value);
  }
  if ($("isolation-mode")) {
    a.isolation_policy.mode = $("isolation-mode").value;
    a.isolation_policy.tool_mode = $("tool-mode").value;
    a.memory_policy.mode = $("memory-mode").value;
    a.memory_policy.compression_max_tokens = Number($("compression-max").value || 6000);
    a.memory_policy.preserve_keywords = lines($("preserve-keywords").value);
    a.approval_policy.mode = $("approval-mode").value;
    a.approval_policy.preapproved_scopes = lines($("preapproved-scopes").value);
    a.approval_policy.require_approval = lines($("require-approval").value);
    a.approval_policy.note = $("approval-note").value;
    a.heartbeat_policy.mode = $("heartbeat-mode").value;
    a.heartbeat_policy.cron_expression = $("heartbeat-cron").value.trim();
  }
  return a;
}

async function saveAgent(makeDefault = false) {
  const payload = readAgentForm();
  const result = await api("/api/agents", { method: "POST", body: { ...payload, _make_default: makeDefault } });
  app.selectedAgentId = result.agent.agent_id;
  toast(makeDefault ? "已保存并设为默认任务配置" : "任务配置已保存");
  await load();
  return result.agent;
}

function nodeById(id) { return (app.currentAgent.workflow_nodes || []).find((node) => node.id === id); }
function stageIndex(stage) { return Math.max(0, STAGES.findIndex(([id]) => id === stage)); }

function renderWorkflow() {
  const a = app.currentAgent;
  const selected = nodeById(app.workflow.selectedNodeId) || a.workflow_nodes[0];
  if (selected && !app.workflow.selectedNodeId) app.workflow.selectedNodeId = selected.id;
  const report = app.workflow.report || app.workflow.dryRun?.workflow || null;
  return `<div class="workflow-page">
    <aside class="toolbox">
      <div class="toolbox-head"><h2>节点素材</h2><button class="icon-btn" data-action="auto-layout" title="自动布局">${icon("workflow")}</button></div>
      <input class="search" id="node-search" data-action="node-search" placeholder="搜索节点、插件、工具、接口" value="${attr(app.workflow.materialFilter)}" />
      <div class="tool-list">${materialGroupsHtml()}</div>
    </aside>
    <section class="canvas-shell">
      <div class="canvas-toolbar">
        <button class="button primary" data-action="save-agent">${icon("save")}保存</button>
        <button class="button" data-action="workflow-check">${icon("check")}检查</button>
        <button class="button" data-action="workflow-dry-run">${icon("play")}预跑</button>
        <button class="button" data-action="add-edge" ${selected ? "" : "disabled"}>${icon("workflow")}从选中连线</button>
        <button class="button" data-action="reset-workflow">重置</button>
        <input class="toolbar-input" id="workflow-trigger-text" placeholder="手动触发文本" />
        <button class="button" data-action="trigger-workflow">${icon("play")}触发</button>
        <span class="zoom-pill">${Math.round(app.workflow.zoom * 100)}%</span>
      </div>
      <div id="canvas" class="canvas" tabindex="0"><div id="world" class="world"></div><svg id="edges" class="edges"></svg><div id="minimap" class="minimap"></div></div>
      ${workflowContextMenu()}
    </section>
    <aside class="inspector">
      ${selected ? nodeEditor(selected) : empty("选择一个节点后编辑")}
      ${report ? workflowReport(report, app.workflow.dryRun?.dry_run) : ""}
    </aside>
  </div>`;
}

function nodeMaterials() {
  const native = NODE_TEMPLATES.map((item) => ({ type: "template", group: stageLabel(item.stage), label: item.title, ref: item.id, hint: `${stageLabel(item.stage)} · ${labelOf(ACTION_LABELS, item.action)}`, payload: item }));
  const modules = (app.state.discovered_modules || app.state.builtin_modules || []).slice(0, 80).map((item) => ({ type: "module", group: item.kind === "plugin" ? "插件模块" : item.kind === "tool" ? "工具模块" : "内置模块", label: item.name || item.module_id || item.id, ref: item.module_id || item.id || item.name, hint: labelOf(KIND_LABELS, item.kind) || labelOf(ACTION_LABELS, item.action) || "模块", payload: item }));
  const tools = (app.state.tools || []).slice(0, 100).map((item) => ({ type: "tool", group: item.plugin_display_name || item.plugin_name || "注册工具", label: item.name, ref: item.name, hint: riskLabel(item.risk) || "工具", payload: item }));
  const apis = (app.state.custom_apis || []).map((item) => ({ type: "api", group: "自定义接口", label: item.name || item.api_id, ref: item.api_id || item.name, hint: item.method || "自定义接口", payload: item }));
  const filter = app.workflow.materialFilter.trim().toLowerCase();
  return [...native, ...modules, ...tools, ...apis].filter((item) => !filter || `${item.group} ${item.label} ${item.ref} ${item.hint}`.toLowerCase().includes(filter));
}

function materialButton(item) {
  return `<button class="material" data-action="add-node" data-type="${attr(item.type)}" data-name="${attr(item.label)}" data-ref="${attr(item.ref || item.label)}" type="button"><strong>${esc(item.label || "未命名")}</strong><span>${esc(item.hint || "")}</span></button>`;
}

function stageLabel(stage) {
  return (STAGES.find(([id]) => id === stage) || [stage, stage || "节点"])[1];
}

function materialGroupsHtml() {
  const groups = new Map();
  for (const item of nodeMaterials()) {
    if (!groups.has(item.group)) groups.set(item.group, []);
    groups.get(item.group).push(item);
  }
  return Array.from(groups, ([group, items]) => `<section class="material-group"><h3>${esc(group)}</h3>${items.map(materialButton).join("")}</section>`).join("") || empty("没有匹配的节点素材");
}

function workflowContextMenu() {
  const menu = app.workflow.contextMenu;
  if (!menu) return "";
  return `<div class="workflow-menu" style="left:${menu.x}px;top:${menu.y}px"><button data-action="copy-context-node" data-id="${attr(menu.id)}">复制节点</button><button data-action="delete-context-node" data-id="${attr(menu.id)}">删除节点</button></div>`;
}

function nodeEditor(node) {
  return `<div class="panel flat"><div class="panel-head"><div><h2>节点编辑</h2><p>${esc(node.id)}</p></div><button class="icon-btn danger" data-action="delete-node" title="删除">${icon("trash")}</button></div>
    <div class="form-grid single compact">
      ${field("节点标识", "node-id", node.id)}${field("标题", "node-title", node.title)}
      ${selectField("阶段", "node-stage", node.stage || "execute", STAGES.map(([id, label]) => [id, label]))}
      ${selectField("类型", "node-kind", node.kind || "state", KINDS.map((id) => [id, labelOf(KIND_LABELS, id)]))}
      ${selectField("动作", "node-action", node.action || "manual", ACTIONS.map((id) => [id, labelOf(ACTION_LABELS, id)]))}
      ${field("工具名", "node-tool", node.tool_name || node.ref_id || "")}${field("接口标识", "node-api", node.api_id || "")}
      ${field("输入变量", "node-input", node.input_variable || "")}${field("输出变量", "node-output", node.output_variable || "")}
      ${field("路径或地址", "node-path", node.path || node.url || "")}${field("并行组", "node-parallel", node.parallel_group || "")}
      ${area("说明", "node-instruction", node.instruction || "", 4)}${area("节点提示词", "node-prompt", node.prompt || "", 5)}${area("标签", "node-tags", listText(node.tags), 3)}
      <button class="button primary span-2" data-action="apply-node">应用节点修改</button>
    </div></div>`;
}

function workflowReport(report, dryRun) {
  const issues = report.issues || report.workflow?.issues || [];
  const dry = dryRun?.steps || dryRun?.path || [];
  return `<div class="panel flat report"><h2>诊断</h2><div class="list small-list">${issues.slice(0, 12).map((item) => `<div class="issue ${esc(item.severity || item.tone || "warn")}"><strong>${esc(item.code || item.kind || "问题")}</strong><span>${esc(item.message || item.detail || JSON.stringify(item))}</span></div>`).join("") || empty("暂无检查问题")}</div>${dry.length ? `<h3>预跑路径</h3><ol>${dry.slice(0, 12).map((item) => `<li>${esc(item.node_id || item.id || item)}</li>`).join("")}</ol>` : ""}</div>`;
}

function mountWorkflow() {
  const canvas = $("canvas");
  const world = $("world");
  const svg = $("edges");
  if (!canvas || !world || !svg) return;
  drawWorkflow();
  canvas.onwheel = (event) => {
    event.preventDefault();
    const old = app.workflow.zoom;
    const next = Math.min(1.6, Math.max(0.35, old + (event.deltaY > 0 ? -0.06 : 0.06)));
    const rect = canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const worldX = (px - app.workflow.x) / old;
    const worldY = (py - app.workflow.y) / old;
    app.workflow.zoom = next;
    app.workflow.x = px - worldX * next;
    app.workflow.y = py - worldY * next;
    drawWorkflow();
  };
  canvas.onpointerdown = (event) => {
    if (event.target.closest(".workflow-node")) return;
    app.workflow.contextMenu = null;
    app.workflow.panning = { sx: event.clientX, sy: event.clientY, x: app.workflow.x, y: app.workflow.y };
    canvas.setPointerCapture(event.pointerId);
  };
  canvas.onpointermove = (event) => {
    if (app.workflow.panning) {
      app.workflow.x = app.workflow.panning.x + event.clientX - app.workflow.panning.sx;
      app.workflow.y = app.workflow.panning.y + event.clientY - app.workflow.panning.sy;
      drawWorkflow();
    }
    if (app.workflow.dragging) {
      const node = nodeById(app.workflow.dragging.id);
      if (!node) return;
      node.x = Math.round(app.workflow.dragging.x + (event.clientX - app.workflow.dragging.sx) / app.workflow.zoom);
      node.y = Math.round(app.workflow.dragging.y + (event.clientY - app.workflow.dragging.sy) / app.workflow.zoom);
      drawWorkflow();
    }
  };
  canvas.onpointerup = () => {
    const changedSelection = !!app.workflow.dragging;
    app.workflow.panning = null;
    app.workflow.dragging = null;
    if (changedSelection) render();
  };
}

function drawWorkflow() {
  const world = $("world");
  const svg = $("edges");
  const minimap = $("minimap");
  const a = app.currentAgent;
  const zoom = app.workflow.zoom;
  world.style.transform = `translate(${app.workflow.x}px, ${app.workflow.y}px) scale(${zoom})`;
  svg.style.transform = `translate(${app.workflow.x}px, ${app.workflow.y}px) scale(${zoom})`;
  world.innerHTML = `${STAGES.map((stage, index) => `<div class="lane" style="left:${index * 360}px"><strong>${stage[1]}</strong><span>${stage[2]}</span></div>`).join("")}${a.workflow_nodes.map(nodeHtml).join("")}`;
  svg.setAttribute("viewBox", "0 0 2600 1400");
  svg.innerHTML = (a.workflow_edges || []).map(edgePath).join("");
  minimap.innerHTML = `<svg viewBox="0 0 2600 1400">${(a.workflow_edges || []).map((edge) => edgePath(edge, -1)).join("")}${a.workflow_nodes.map((node) => `<rect x="${node.x || 0}" y="${node.y || 0}" width="220" height="92" class="${node.id === app.workflow.selectedNodeId ? "selected" : ""}" />`).join("")}</svg>`;
  qa(".workflow-node", world).forEach((el) => {
    el.addEventListener("pointerdown", (event) => {
      if (event.target.closest(".port")) return;
      event.stopPropagation();
      const id = el.dataset.id;
      app.workflow.selectedNodeId = id;
      const node = nodeById(id);
      app.workflow.dragging = { id, sx: event.clientX, sy: event.clientY, x: node.x || 0, y: node.y || 0 };
      drawWorkflow();
    });
    el.addEventListener("dblclick", (event) => { event.stopPropagation(); render(); });
    el.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      app.workflow.selectedNodeId = el.dataset.id;
      const rect = canvas.getBoundingClientRect();
      app.workflow.contextMenu = { id: el.dataset.id, x: event.clientX - rect.left, y: event.clientY - rect.top };
      render();
    });
  });
}

function nodeHtml(node) {
  const selected = node.id === app.workflow.selectedNodeId;
  const left = Number(node.x ?? stageIndex(node.stage) * 360 + 80);
  const top = Number(node.y ?? 80);
  return `<div class="workflow-node ${selected ? "selected" : ""}" data-id="${attr(node.id)}" style="left:${left}px;top:${top}px"><div class="node-top"><span>${esc(labelOf(KIND_LABELS, node.kind || "state"))}</span>${badge(stageLabel(node.stage || "execute"))}</div><strong>${esc(node.title || node.id)}</strong><p>${esc(node.instruction || labelOf(ACTION_LABELS, node.action) || "")}</p><button class="port" data-action="port" data-id="${attr(node.id)}" title="连线"></button></div>`;
}

function edgePath(edge, index = 0) {
  const from = nodeById(edge.from);
  const to = nodeById(edge.to);
  if (!from || !to) return "";
  const x1 = Number(from.x || 0) + 220;
  const y1 = Number(from.y || 0) + 46;
  const x2 = Number(to.x || 0);
  const y2 = Number(to.y || 0) + 46;
  const mid = Math.max(80, Math.abs(x2 - x1) / 2);
  const path = `M ${x1} ${y1} C ${x1 + mid} ${y1}, ${x2 - mid} ${y2}, ${x2} ${y2}`;
  const hit = index >= 0 ? `<path class="edge-hit" data-action="delete-edge" data-index="${index}" d="${path}" />` : "";
  return `${hit}<path class="edge" d="${path}" /><text x="${(x1 + x2) / 2}" y="${(y1 + y2) / 2 - 6}">${esc(edge.edge_type || "")}</text>`;
}

function applyNodeEditor() {
  const node = nodeById(app.workflow.selectedNodeId);
  if (!node) return;
  const oldId = node.id;
  node.id = $("node-id").value.trim() || oldId;
  node.title = $("node-title").value.trim();
  node.stage = $("node-stage").value;
  node.kind = $("node-kind").value;
  node.action = $("node-action").value;
  node.tool_name = $("node-tool").value.trim();
  node.ref_id = node.tool_name;
  node.api_id = $("node-api").value.trim();
  node.input_variable = $("node-input").value.trim();
  node.output_variable = $("node-output").value.trim();
  const path = $("node-path").value.trim();
  node.path = path; node.url = path;
  node.parallel_group = $("node-parallel").value.trim();
  node.instruction = $("node-instruction").value;
  node.prompt = $("node-prompt").value;
  node.tags = lines($("node-tags").value);
  if (node.id !== oldId) {
    app.currentAgent.workflow_edges.forEach((edge) => { if (edge.from === oldId) edge.from = node.id; if (edge.to === oldId) edge.to = node.id; });
    app.workflow.selectedNodeId = node.id;
  }
  toast("节点已应用");
  render();
}

function addNodeFrom(type, name, ref = name) {
  const index = app.currentAgent.workflow_nodes.length;
  let node = clone(NODE_TEMPLATES.find((item) => item.title === name || item.id === name) || NODE_TEMPLATES[0]);
  if (type === "tool") node = { id: `tool_${Date.now()}`, title: name, kind: "tool", stage: "execute", action: "run_tools", tool_name: ref, ref_id: ref, instruction: "调用这个 AstrBot 工具并整理结果。" };
  if (type === "api") node = { id: `api_${Date.now()}`, title: name, kind: "api", stage: "execute", action: "call_api", api_id: ref, ref_id: ref, instruction: "调用这个自定义接口。" };
  if (type === "module") node = { id: `module_${Date.now()}`, title: name, kind: "state", stage: "execute", action: "manual", ref_id: ref, module_id: ref, instruction: "绑定发现模块，按节点提示执行。" };
  node.id = uniqueNodeId(node.id || `node_${Date.now()}`);
  node.x = 120 + stageIndex(node.stage) * 360;
  node.y = 90 + (index % 5) * 150;
  app.currentAgent.workflow_nodes.push(node);
  app.workflow.selectedNodeId = node.id;
  render();
}

function uniqueNodeId(base) {
  const clean = String(base || "node").replace(/[^a-zA-Z0-9_\-]/g, "_");
  let id = clean;
  let i = 2;
  while (nodeById(id)) id = `${clean}_${i++}`;
  return id;
}

function duplicateNode(id) {
  const node = nodeById(id);
  if (!node) return;
  const copy = { ...clone(node), id: uniqueNodeId(`${node.id}_copy`), title: `${node.title || node.id} 副本`, x: Number(node.x || 0) + 40, y: Number(node.y || 0) + 40 };
  app.currentAgent.workflow_nodes.push(copy);
  app.workflow.selectedNodeId = copy.id;
}

function autoLayout() {
  const buckets = Object.fromEntries(STAGES.map(([id]) => [id, 0]));
  app.currentAgent.workflow_nodes.forEach((node) => {
    const stage = STAGES.some(([id]) => id === node.stage) ? node.stage : "execute";
    const row = buckets[stage]++;
    node.x = 90 + stageIndex(stage) * 360;
    node.y = 90 + row * 150;
  });
  render();
}

async function workflowCheck(dryRun = false) {
  readAgentForm();
  const path = dryRun ? "/api/workflow/dry-run" : "/api/workflow/check";
  const result = await api(path, { method: "POST", body: { agent: app.currentAgent } });
  if (dryRun) app.workflow.dryRun = result;
  else app.workflow.report = result.workflow;
  toast(dryRun ? "预跑诊断完成" : "工作流检查完成");
  render();
}

function renderTasks() {
  const tasks = app.state.tasks || [];
  const archives = app.state.archives || [];
  const selected = [...tasks, ...archives].find((task) => task.task_id === app.selectedTaskId) || tasks[0] || archives[0];
  if (selected) app.selectedTaskId = selected.task_id;
  return `<div class="task-layout"><aside class="panel task-list-panel"><h2>任务</h2><div class="list">${tasks.map(taskCard).join("") || empty("没有运行中任务")}</div><h3>归档</h3><div class="list">${archives.slice(0, 30).map(taskCard).join("") || empty("暂无归档")}</div></aside><section class="stack"><div class="panel"><h2>启动新任务</h2><div class="form-grid task-start">${field("会话标识", "task-umo", "aiocqhttp:FriendMessage:agent_lab_webui")} ${selectField("风险", "task-risk", "work", selectOptions(RISK_LABELS, ["safe", "work", "high"]))}${area("目标", "task-goal", "", 3)}${area("完成条件", "task-completion", listText(app.currentAgent.entry_policy.default_completion_conditions), 3)}${area("补充说明", "task-brief", "", 4)}${checkField("启动后开心跳", "task-heartbeat", false)}<button class="button primary span-2" data-action="start-task">启动任务</button></div></div>${selected ? taskDetail(selected) : empty("选择任务查看详情")}</section></div>`;
}

function taskDetail(task) {
  const approvals = (task.approvals || []).filter((item) => item.status === "pending");
  const liveLogs = app.taskLogs[task.task_id]?.logs || task.progress_log || [];
  const snapshots = app.taskLogs[task.task_id]?.snapshots || task.state_snapshots || [];
  return `<div class="panel"><div class="panel-head"><div><h2>${esc(task.root_goal || task.task_id)}</h2><p>${esc(statusLabel(task.status))} · ${esc(task.heartbeat_health?.message || "")}</p></div><div class="row"><button class="button" data-action="tick-task">推进一轮</button><button class="button" data-action="toggle-heartbeat">${task.heartbeat?.enabled ? "关闭心跳" : "开心跳"}</button><button class="button" data-action="load-task-logs">刷新日志</button><button class="button" data-action="finish-task">完成</button><button class="button danger" data-action="cancel-task">取消</button></div></div><div class="state-grid">${stateTile("当前摘要", task.current_summary)}${stateTile("已确认进度", task.last_confirmed_progress)}${stateTile("下一步", task.next_step)}${stateTile("最后观察", task.last_observation)}</div>${parallelRunSummary(task)}${approvals.length ? `<h3>待审批</h3><div class="list">${approvals.map((item) => `<div class="approval"><strong>${esc(item.operation || item.approval_id)}</strong><p>${esc(item.reason || item.impact || "")}</p><button class="button primary" data-action="resolve-approval" data-id="${attr(item.approval_id)}" data-approved="true">通过</button><button class="button danger" data-action="resolve-approval" data-id="${attr(item.approval_id)}" data-approved="false">拒绝</button></div>`).join("")}</div>` : ""}<h3>时间线</h3><div class="timeline">${liveLogs.slice(-14).reverse().map((item) => `<div><span>${esc(item.time || "")}</span><p>${esc(item.text || labelOf(ACTION_LABELS, item.kind) || statusLabel(item.kind) || "")}</p></div>`).join("") || empty("暂无日志")}</div><h3>状态快照</h3><div class="timeline compact-line">${snapshots.slice(-8).reverse().map((item) => `<div><span>${esc(item.time || "")}</span><p>${esc(labelOf(ACTION_LABELS, item.kind) || statusLabel(item.status) || "状态")} · ${esc(item.next_step || item.current_summary || "")}</p></div>`).join("") || empty("暂无快照")}</div></div>`;
}
function stateTile(label, value) { return `<div class="state-tile"><span>${esc(label)}</span><p>${esc(value || "-")}</p></div>`; }

function parallelRunSummary(task) {
  const runs = task.parallel_runs || [];
  if (!runs.length) return "";
  return `<h3>并行工作包</h3><div class="tool-grid compact-tools">${runs.slice(-4).reverse().map((run) => `<div class="tool-card"><strong>${esc(run.node_id || run.parallel_group || run.time || "并行")}</strong><span>${esc(statusLabel(run.status || (run.ok === false ? "failed" : "completed")))}</span><small>${esc(run.summary || run.message || JSON.stringify(run).slice(0, 180))}</small></div>`).join("")}</div>`;
}

function renderMemory() {
  const memories = app.state.memories || [];
  const selected = memories.find((item) => item.memory_id === app.selectedMemoryId) || memories[0];
  if (selected) app.selectedMemoryId = selected.memory_id;
  const counts = ["candidate", "accepted", "rejected"].map((status) => [status, memories.filter((item) => item.status === status).length]);
  return `<div class="memory-layout"><section class="stack"><div class="metric-grid compact-metrics">${counts.map(([status, count]) => stat(statusLabel(status), count, "记忆")).join("")}${stat("全部", memories.length, "条目")}</div><div class="panel"><div class="panel-head"><h2>任务记忆</h2><button class="button" data-action="new-memory-draft">写入记忆</button></div><div class="list memory-list">${memories.map(memoryCard).join("") || empty("还没有任务记忆")}</div></div></section><aside class="panel detail-sticky">${selected ? memoryDetail(selected) : empty("选择记忆查看详情")}</aside></div>`;
}

function memoryCard(item) {
  return `<button class="memory-row ${item.memory_id === app.selectedMemoryId ? "selected" : ""}" data-action="select-memory" data-id="${attr(item.memory_id)}" type="button"><strong>${esc(item.brief || item.text || item.memory_id)}</strong><span>${esc(statusLabel(item.status || "candidate"))} · ${esc((item.tags || []).join(", "))}</span></button>`;
}

function memoryDetail(item) {
  return `<div class="memory-detail"><h2>${esc(item.brief || "记忆详情")}</h2>${badge(statusLabel(item.status || "candidate"))}<p>${esc(item.text || "")}</p><dl><dt>来源任务</dt><dd>${compactId(item.source_task_id)}</dd><dt>来源会话</dt><dd>${compactId(item.source_umo)}</dd><dt>普通模式可读</dt><dd>${item.expose_to_normal ? "是" : "否"}</dd></dl><div class="row"><button class="button primary" data-action="accept-memory" data-id="${attr(item.memory_id)}">接受</button><button class="button" data-action="reject-memory" data-id="${attr(item.memory_id)}">拒绝</button><button class="button" data-action="use-memory-context" data-id="${attr(item.memory_id)}">带入新任务</button><button class="button danger" data-action="delete-memory" data-id="${attr(item.memory_id)}">删除</button></div><h3>续写草稿</h3><textarea rows="8" readonly>${esc(memoryContextText(item))}</textarea></div>`;
}

function memoryContextText(item) {
  return `从任务记忆继续：\n- 记忆：${item.text || item.brief || ""}\n- 标签：${(item.tags || []).join(", ")}\n- 来源任务：${item.source_task_id || ""}\n请先核对这条记忆是否仍然适用，再继续推进。`;
}

function archiveContextText(task, memory = null) {
  return `从归档任务继续：\n- 原任务：${task.root_goal || task.task_id || ""}\n- 当前摘要：${task.current_summary || task.exit_summary || ""}\n- 已确认进度：${task.last_confirmed_progress || ""}\n- 下一步：${task.next_step || ""}\n- 归档路径：${task.archive_path || ""}${memory ? `\n- 参考记忆：${memory.text || memory.brief || ""}` : ""}\n请先确认旧任务结论是否仍然成立，再生成新的执行计划。`;
}

function renderMemoryV2() {
  const all = app.state.memories || [];
  const memories = app.memoryFilter === "all" ? all : all.filter((item) => (item.status || "candidate") === app.memoryFilter);
  const selected = app.selectedMemoryId === "__new__" ? null : (all.find((item) => item.memory_id === app.selectedMemoryId) || memories[0] || all[0]);
  if (selected) app.selectedMemoryId = selected.memory_id;
  const counts = ["candidate", "accepted", "rejected"].map((status) => [status, all.filter((item) => item.status === status).length]);
  const archives = (app.state.archives || []).slice(0, 8);
  return `<div class="memory-layout"><section class="stack"><div class="metric-grid compact-metrics">${counts.map(([status, count]) => stat(statusLabel(status), count, "记忆")).join("")}${stat("全部", all.length, "条目")}</div><div class="panel"><div class="panel-head"><h2>任务记忆</h2><div class="row"><div class="tabs mini-tabs">${["all", "candidate", "accepted", "rejected"].map((id) => `<button class="${app.memoryFilter === id ? "active" : ""}" data-action="memory-filter" data-id="${id}">${esc(statusLabel(id))}</button>`).join("")}</div><button class="button" data-action="new-memory-draft">写入记忆</button></div></div><div class="list memory-list">${memories.map(memoryCard).join("") || empty("当前筛选没有任务记忆")}</div></div><div class="panel"><h2>归档回流</h2><div class="list">${archives.map((archive) => `<div class="list-row static"><strong>${esc(archive.root_goal || archive.task_id)}</strong><span>${esc(statusLabel(archive.status || "archived"))} · ${compactId(archive.task_id)}</span><button class="button small" data-action="use-archive-context" data-id="${attr(archive.task_id)}">带入新任务</button></div>`).join("") || empty("暂无归档任务")}</div></div></section><aside class="panel detail-sticky">${selected ? memoryDetail(selected) : memoryDraftForm()}</aside></div>`;
}

function memoryDraftForm() {
  return `<div class="memory-detail"><h2>写入任务记忆</h2><div class="form-grid single">${area("记忆内容", "memory-text", "", 6)}${selectField("状态", "memory-status", "candidate", selectOptions(STATUS_LABELS, ["candidate", "accepted", "rejected"]))}${area("标签", "memory-tags", "任务\n手动", 3)}${checkField("普通模式可读取", "memory-expose", false)}<button class="button primary span-2" data-action="save-memory">保存记忆</button></div></div>`;
}

function renderIntegrations() {
  const tabs = [["plugins", "AstrBot 插件"], ["tools", "注册工具"], ["blueprints", "外部蓝图"], ["skills", "技能"]];
  return `<div class="stack"><section class="panel"><div class="panel-head"><div><h2>插件与集成</h2><p>这些数据来自后端扫描：插件、工具、技能、内置和外部蓝图。当前任务配置只保存会话级覆盖，不改 AstrBot 全局开关。</p></div><button class="button primary" data-action="save-agent">保存配置</button></div><div class="tabs">${tabs.map(([id, label]) => `<button class="${app.integrationTab === id ? "active" : ""}" data-action="integration-tab" data-id="${id}">${esc(label)}</button>`).join("")}</div></section>${integrationBody()}</div>`;
}

function renderIntegrationsV2() {
  const tabs = [["plugins", "AstrBot 插件"], ["tools", "注册工具"], ["blueprints", "外部蓝图"], ["skills", "技能"]];
  return `<div class="stack"><section class="panel"><div class="panel-head"><div><h2>插件与集成</h2><p>插件隔离、工具白名单、风险覆盖、技能和外部蓝图都会保存到当前任务配置。</p></div><button class="button primary" data-action="save-agent">保存配置</button></div><div class="tabs">${tabs.map(([id, label]) => `<button class="${app.integrationTab === id ? "active" : ""}" data-action="integration-tab" data-id="${id}">${esc(label)}</button>`).join("")}</div></section>${integrationBodyV2()}</div>`;
}

function integrationBodyV2() {
  if (app.integrationTab === "tools") return `<section class="panel"><h2>注册工具</h2><div class="tool-grid">${(app.state.tools || []).map(toolRowV2).join("") || empty("没有工具数据")}</div></section>`;
  if (app.integrationTab === "blueprints") return blueprintPanel();
  if (app.integrationTab === "skills") return `<section class="panel"><h2>任务技能</h2><div class="tool-grid">${(app.state.skills || []).map(skillRow).join("") || empty("没有技能数据")}</div></section>`;
  return `<section class="panel"><h2>AstrBot 插件隔离</h2><div class="tool-grid">${(app.state.plugins || []).map(pluginRow).join("") || empty("没有插件数据")}</div></section>`;
}

function toolRowV2(tool) {
  const enabled = (app.currentAgent.enabled_tools || []).includes(tool.name);
  const risk = app.currentAgent.tool_risk_overrides?.[tool.name] || tool.risk || "work";
  return `<div class="tool-card ${enabled ? "on" : ""}"><div><strong>${esc(tool.name)}</strong><span>${esc(tool.description || tool.plugin_display_name || tool.source || "")}</span></div><div class="row">${badge(riskLabel(risk))}<select class="inline-select" data-action="tool-risk" data-id="${attr(tool.name)}"><option value="safe" ${risk === "safe" ? "selected" : ""}>低风险</option><option value="work" ${risk === "work" ? "selected" : ""}>工作风险</option><option value="high" ${risk === "high" ? "selected" : ""}>高风险</option></select><button class="button small" data-action="toggle-tool" data-id="${attr(tool.name)}">${enabled ? "移除" : "允许"}</button></div></div>`;
}

function blueprintPanel() {
  const modules = app.state.modules || app.state.integrations || [];
  const selected = modules.find((item) => (item.module_id || item.id || item.name) === app.selectedModuleId) || modules[0];
  if (selected) app.selectedModuleId = selected.module_id || selected.id || selected.name;
  const settings = selected ? (app.currentAgent.module_settings?.[app.selectedModuleId] || selected.default_settings || {}) : {};
  return `<section class="split"><div class="panel"><h2>集成蓝图</h2><div class="list">${modules.map(moduleRow).join("") || empty("没有蓝图")}</div></div><div class="panel"><h2>蓝图设置</h2>${selected ? `<p>${esc(selected.description || selected.source || app.selectedModuleId)}</p><div class="row">${badge((app.currentAgent.module_ids || []).includes(app.selectedModuleId) ? "已启用" : "未启用")}</div>${schemaSettingsForm(selected, settings)}${area("高级配置", "module-settings-json", JSON.stringify(settings, null, 2), 10)}<button class="button primary" data-action="save-module-settings">保存到任务配置</button>` : empty("选择蓝图后编辑设置")}<h3>导入或更新清单</h3>${area("清单内容", "blueprint-json", "{}", 10)}<button class="button" data-action="save-blueprint">保存蓝图</button></div></section>`;
}

function schemaSettingsForm(module, settings) {
  const properties = module.settings_schema?.properties || {};
  const rows = Object.entries(properties).map(([key, schema]) => {
    const value = settings[key] ?? schema.default ?? "";
    const label = schema.title || key;
    if (schema.type === "boolean") return checkField(label, `module-setting-${key}`, !!value);
    if (schema.enum) return selectField(label, `module-setting-${key}`, String(value), schema.enum.map((item) => [String(item), String(item)]));
    if (schema.type === "integer" || schema.type === "number") return field(label, `module-setting-${key}`, value, "number");
    return field(label, `module-setting-${key}`, value);
  }).join("");
  return rows ? `<div class="form-grid single schema-form"><h3>精细设置</h3>${rows}</div>` : "";
}

function readSchemaSettings(module, fallback) {
  const next = { ...(fallback || {}) };
  const properties = module?.settings_schema?.properties || {};
  for (const [key, schema] of Object.entries(properties)) {
    const input = $(`module-setting-${key}`);
    if (!input) continue;
    if (schema.type === "boolean") next[key] = input.checked;
    else if (schema.type === "integer") next[key] = Number.parseInt(input.value || "0", 10);
    else if (schema.type === "number") next[key] = Number(input.value || 0);
    else next[key] = input.value;
  }
  return next;
}

function renderMonitor() {
  const rows = app.state.workflow_runs?.runs || [];
  const active = app.state.tasks || [];
  return `<div class="stack"><section class="metric-grid">${stat("运行中任务", active.length, "当前")}${stat("工作流运行", app.state.workflow_runs?.counts?.total || rows.length, "总次数")}${stat("活跃工作流", app.state.workflow_runs?.counts?.active || 0, "正在运行")}${stat("归档工作流", app.state.workflow_runs?.counts?.archived || 0, "已归档")}</section><section class="split"><div class="panel"><h2>心跳健康</h2><div class="list">${active.map((task) => `<div class="list-row static"><strong>${esc(task.root_goal || task.task_id)}</strong><span>${esc(task.heartbeat_health?.message || "")} · ${esc(statusLabel(task.heartbeat_health?.state || ""))}</span></div>`).join("") || empty("没有运行中任务")}</div></div><div class="panel"><h2>工作流运行</h2><div class="list">${rows.slice(0, 40).map((run) => `<button class="list-row" data-action="select-task" data-id="${attr(run.task_id)}"><strong>${esc(run.agent_name || run.task_id)}</strong><span>${esc(statusLabel(run.status || ""))} · ${esc(sourceLabel(run.source || "manual_webui"))} · ${esc(run.workflow_current_node_id || "")}</span></button>`).join("") || empty("暂无运行记录")}</div></div></section></div>`;
}

function integrationBody() {
  if (app.integrationTab === "tools") return `<section class="panel"><h2>注册工具</h2><div class="tool-grid">${(app.state.tools || []).map(toolRow).join("") || empty("没有工具数据")}</div></section>`;
  if (app.integrationTab === "blueprints") return `<section class="split"><div class="panel"><h2>集成蓝图</h2><div class="list">${(app.state.modules || app.state.integrations || []).map(moduleRow).join("") || empty("没有蓝图")}</div></div><div class="panel"><h2>导入或更新清单</h2>${area("清单内容", "blueprint-json", "{}", 12)}<button class="button primary" data-action="save-blueprint">保存蓝图</button></div></section>`;
  if (app.integrationTab === "skills") return `<section class="panel"><h2>任务技能</h2><div class="tool-grid">${(app.state.skills || []).map(skillRow).join("") || empty("没有技能数据")}</div></section>`;
  return `<section class="panel"><h2>AstrBot 插件隔离</h2><div class="tool-grid">${(app.state.plugins || []).map(pluginRow).join("") || empty("没有插件数据")}</div></section>`;
}

function pluginEffective(plugin) {
  if (plugin.locked) return true;
  if (plugin.activated === false) return false;
  const override = app.currentAgent.plugin_overrides?.[plugin.name];
  return override === undefined ? true : !!override;
}

function pluginRow(plugin) {
  const effective = pluginEffective(plugin);
  const disabled = plugin.locked || plugin.activated === false;
  return `<div class="tool-card ${effective ? "on" : "off"}"><div><strong>${esc(plugin.display_name || plugin.name)}</strong><span>${esc(plugin.desc || plugin.capability_summary || "")}</span></div><div class="row">${plugin.locked ? badge("Agent Lab 锁定", "ok") : plugin.activated === false ? badge("全局不可用", "bad") : badge(effective ? "任务中启用" : "任务中关闭", effective ? "ok" : "warn")}<button class="button small" data-action="toggle-plugin" data-id="${attr(plugin.name)}" ${disabled ? "disabled" : ""}>切换</button></div></div>`;
}

function toolRow(tool) {
  const enabled = (app.currentAgent.enabled_tools || []).includes(tool.name);
  return `<div class="tool-card ${enabled ? "on" : ""}"><div><strong>${esc(tool.name)}</strong><span>${esc(tool.description || tool.plugin_display_name || tool.source || "")}</span></div><div class="row">${badge(riskLabel(tool.risk || "work"))}<button class="button small" data-action="toggle-tool" data-id="${attr(tool.name)}">${enabled ? "移除" : "允许"}</button></div></div>`;
}

function moduleRow(module) {
  const id = module.module_id || module.id || module.name;
  const enabled = (app.currentAgent.module_ids || []).includes(id);
  return `<div class="list-row static ${id === app.selectedModuleId ? "selected" : ""}"><strong>${esc(module.name || id)}</strong><span>${esc(module.description || module.source || "")}</span><div class="row"><button class="button small" data-action="select-module" data-id="${attr(id)}">设置</button><button class="button small" data-action="toggle-module" data-id="${attr(id)}">${enabled ? "已启用" : "启用"}</button></div></div>`;
}

function skillRow(skill) {
  const id = skill.name || skill.skill_name || skill.id;
  const enabled = (app.currentAgent.enabled_skills || []).includes(id);
  return `<div class="tool-card ${enabled ? "on" : ""}"><div><strong>${esc(id)}</strong><span>${esc(skill.description || skill.path || "")}</span></div><button class="button small" data-action="toggle-skill" data-id="${attr(id)}">${enabled ? "移除" : "启用"}</button></div>`;
}

function renderRegistry() {
  const tabs = [["apis", "自定义接口"], ["credentials", "凭证"], ["rules", "技能规则"]];
  return `<div class="stack"><section class="panel"><div class="panel-head"><div><h2>规则与凭证</h2><p>凭证只保存在后端；任务模式通过接口标识和凭证标识引用，不把密钥写进提示词。</p></div></div><div class="tabs">${tabs.map(([id, label]) => `<button class="${app.registryTab === id ? "active" : ""}" data-action="registry-tab" data-id="${id}">${esc(label)}</button>`).join("")}</div></section>${registryBody()}</div>`;
}

function registryBody() {
  if (app.registryTab === "credentials") return `<section class="split"><div class="panel"><h2>已保存凭证</h2><div class="list">${(app.state.credentials || []).map((item) => `<div class="list-row static"><strong>${esc(item.label || item.credential_id)}</strong><span>${esc(item.provider || item.scope || "")}</span></div>`).join("") || empty("没有凭证")}</div></div><div class="panel"><h2>新增凭证</h2><div class="form-grid single">${field("标签", "cred-label")}${field("服务商", "cred-provider")}${field("使用范围", "cred-scope")}${area("密钥值", "cred-value", "", 4)}<button class="button primary span-2" data-action="save-credential">保存凭证</button></div></div></section>`;
  if (app.registryTab === "rules") {
    const rules = Object.fromEntries((app.state.skill_rules || []).map((item) => [item.skill_name || item.name, item.content || ""]));
    return `<section class="panel"><h2>任务模式规则</h2><div class="form-grid single">${area("主规则", "rule-agent-mode", rules["agent-mode"] || "", 10)}${area("入口摘要规则", "rule-entry", rules["agent-mode-entry-summary"] || "", 6)}${area("出口归档规则", "rule-exit", rules["agent-mode-exit-summary"] || "", 6)}<button class="button primary span-2" data-action="save-rules">保存规则</button></div></section>`;
  }
  return `<section class="split"><div class="panel"><h2>已注册接口</h2><div class="list">${(app.state.custom_apis || []).map((item) => `<div class="list-row static"><strong>${esc(item.name || item.api_id)}</strong><span>${esc(item.method || "GET")} · ${esc(item.url || "")}</span></div>`).join("") || empty("没有接口")}</div></div><div class="panel"><h2>注册接口</h2><div class="form-grid single">${field("名称", "api-name")}${selectField("请求方法", "api-method", "GET", [["GET", "GET"], ["POST", "POST"], ["PUT", "PUT"], ["PATCH", "PATCH"], ["DELETE", "DELETE"]])}${field("地址", "api-url")}${field("凭证标识", "api-credential")}${selectField("认证方式", "api-auth-type", "none", [["none", "不认证"], ["bearer", "Bearer 令牌"], ["header", "请求头"], ["query", "查询参数"]])}${field("认证请求头", "api-auth-header", "Authorization")}${field("认证查询参数", "api-auth-query")}${area("请求头配置", "api-headers", "{}", 4)}${area("说明", "api-description", "", 4)}<button class="button primary span-2" data-action="save-api">注册接口</button></div></div></section>`;
}

function selectedTask() {
  return [...(app.state.tasks || []), ...(app.state.archives || [])].find((task) => task.task_id === app.selectedTaskId) || (app.state.tasks || [])[0];
}

function toggleList(listName, id) {
  const set = new Set(app.currentAgent[listName] || []);
  if (set.has(id)) set.delete(id); else set.add(id);
  app.currentAgent[listName] = Array.from(set).sort();
}

async function handleAction(target) {
  const action = target.dataset.action;
  if (target.dataset.route) return setRoute(target.dataset.route);
  if (action === "select-agent") { app.selectedAgentId = target.dataset.id; app.currentAgent = ensureAgent(clone((app.state.agents || []).find((agent) => agent.agent_id === app.selectedAgentId))); updateChrome(); return render(); }
  if (action === "new-agent") { app.currentAgent = ensureAgent({ workflow_nodes: defaultNodes(), workflow_edges: clone(DEFAULT_EDGES) }); app.selectedAgentId = ""; setRoute("settings"); return; }
  if (action === "duplicate-agent") { readAgentForm(); app.currentAgent.agent_id = ""; app.currentAgent.name = `${app.currentAgent.name || "任务配置"} 副本`; toast("已生成副本草稿，保存后生效"); return render(); }
  if (action === "delete-agent") { if (!app.currentAgent.agent_id) return toast("当前是未保存草稿"); if (!confirm("删除当前任务配置？")) return; await api("/api/agents", { method: "DELETE", body: { agent_id: app.currentAgent.agent_id } }); toast("任务配置已删除"); app.selectedAgentId = ""; return load(); }
  if (action === "save-agent") return saveAgent(false);
  if (action === "make-default") return saveAgent(true);
  if (action === "workflow-check") return workflowCheck(false);
  if (action === "workflow-dry-run") return workflowCheck(true);
  if (action === "auto-layout") return autoLayout();
  if (action === "reset-workflow") { app.currentAgent.workflow_nodes = defaultNodes(); app.currentAgent.workflow_edges = clone(DEFAULT_EDGES); app.workflow.selectedNodeId = "entry"; return render(); }
  if (action === "node-search") { app.workflow.materialFilter = target.value; return render(); }
  if (action === "add-node") return addNodeFrom(target.dataset.type, target.dataset.name, target.dataset.ref);
  if (action === "copy-context-node") { duplicateNode(target.dataset.id); app.workflow.contextMenu = null; toast("节点已复制"); return render(); }
  if (action === "delete-context-node") { const id = target.dataset.id; app.currentAgent.workflow_nodes = app.currentAgent.workflow_nodes.filter((node) => node.id !== id); app.currentAgent.workflow_edges = app.currentAgent.workflow_edges.filter((edge) => edge.from !== id && edge.to !== id); if (app.workflow.selectedNodeId === id) app.workflow.selectedNodeId = app.currentAgent.workflow_nodes[0]?.id || ""; app.workflow.contextMenu = null; toast("节点已删除"); return render(); }
  if (action === "port") {
    const id = target.dataset.id;
    if (!app.workflow.linkingFrom) {
      app.workflow.linkingFrom = id;
      toast(`从 ${id} 开始连线`);
    } else if (app.workflow.linkingFrom !== id) {
      app.currentAgent.workflow_edges.push({ from: app.workflow.linkingFrom, to: id, edge_type: "success" });
      app.workflow.linkingFrom = "";
      toast("连线已创建");
      render();
    }
    return;
  }
  if (action === "delete-edge") {
    const index = Number(target.dataset.index);
    if (Number.isInteger(index) && index >= 0) app.currentAgent.workflow_edges.splice(index, 1);
    toast("连线已删除");
    return render();
  }
  if (action === "delete-node") { const id = app.workflow.selectedNodeId; app.currentAgent.workflow_nodes = app.currentAgent.workflow_nodes.filter((node) => node.id !== id); app.currentAgent.workflow_edges = app.currentAgent.workflow_edges.filter((edge) => edge.from !== id && edge.to !== id); app.workflow.selectedNodeId = app.currentAgent.workflow_nodes[0]?.id || ""; return render(); }
  if (action === "apply-node") return applyNodeEditor();
  if (action === "add-edge") { const from = app.workflow.selectedNodeId; const to = prompt("连接到哪个节点 ID？"); if (from && to) app.currentAgent.workflow_edges.push({ from, to, edge_type: "success" }); return render(); }
  if (action === "trigger-workflow") { const text = $("workflow-trigger-text")?.value || "控制台手动触发工作流"; const saved = await saveAgent(false); await api("/api/workflow/trigger", { method: "POST", body: { source: "manual_webui", agent_id: saved.agent_id, text } }); toast("工作流已触发"); return load(); }
  if (action === "select-task") { app.selectedTaskId = target.dataset.id; return setRoute("tasks"); }
  if (action === "start-task") { await api("/api/task/start", { method: "POST", body: { umo: $("task-umo").value.trim(), goal: $("task-goal").value, completion_conditions: $("task-completion").value, brief: $("task-brief").value, heartbeat: $("task-heartbeat").checked, risk_level: $("task-risk").value, agent_id: app.currentAgent.agent_id } }); toast("任务已启动"); return load(); }
  if (action === "tick-task") { const task = selectedTask(); await api("/api/task/tick", { method: "POST", body: { umo: task.umo } }); toast("已推进一轮"); return load(); }
  if (action === "toggle-heartbeat") { const task = selectedTask(); await api("/api/task/heartbeat", { method: "POST", body: { umo: task.umo, enabled: !task.heartbeat?.enabled } }); toast("心跳状态已更新"); return load(); }
  if (action === "load-task-logs") { const task = selectedTask(); const query = new URLSearchParams({ umo: task.umo || "", task_id: task.task_id || "" }); app.taskLogs[task.task_id] = await api(`/api/task/logs?${query}`); toast("日志已刷新"); return render(); }
  if (action === "finish-task") { const task = selectedTask(); await api("/api/task/finish", { method: "POST", body: { umo: task.umo, summary: "控制台标记完成。" } }); toast("任务已归档"); return load(); }
  if (action === "cancel-task") { const task = selectedTask(); await api("/api/task/cancel", { method: "POST", body: { umo: task.umo, reason: "控制台取消任务。" } }); toast("任务已取消"); return load(); }
  if (action === "resolve-approval") { const task = selectedTask(); await api("/api/task/approval", { method: "POST", body: { umo: task.umo, approval_id: target.dataset.id, approved: target.dataset.approved === "true" } }); toast("审批已处理"); return load(); }
  if (action === "select-memory") { app.selectedMemoryId = target.dataset.id; return render(); }
  if (action === "memory-filter") { app.memoryFilter = target.dataset.id || "all"; return render(); }
  if (action === "new-memory-draft") { app.selectedMemoryId = "__new__"; return render(); }
  if (action === "save-memory") { const task = selectedTask() || {}; await api("/api/memory", { method: "POST", body: { text: $("memory-text").value, status: $("memory-status").value, tags: lines($("memory-tags").value), expose_to_normal: $("memory-expose").checked, source_task_id: task.task_id || "", source_umo: task.umo || "" } }); toast("记忆已保存"); return load(); }
  if (action === "accept-memory" || action === "reject-memory") { await api("/api/memory", { method: "POST", body: { action: action === "accept-memory" ? "accept" : "reject", memory_id: target.dataset.id } }); toast("记忆状态已更新"); return load(); }
  if (action === "delete-memory") { await api("/api/memory", { method: "DELETE", body: { memory_id: target.dataset.id } }); toast("记忆已删除"); return load(); }
  if (action === "use-memory-context") { const item = (app.state.memories || []).find((row) => row.memory_id === target.dataset.id); setRoute("tasks"); setTimeout(() => { if ($("task-brief")) $("task-brief").value = memoryContextText(item); }, 0); return; }
  if (action === "use-archive-context") { const task = (app.state.archives || []).find((row) => row.task_id === target.dataset.id); const memory = (app.state.memories || []).find((row) => row.memory_id === app.selectedMemoryId); setRoute("tasks"); setTimeout(() => { if ($("task-brief")) $("task-brief").value = archiveContextText(task || {}, memory); }, 0); return; }
  if (action === "integration-tab") { app.integrationTab = target.dataset.id; return render(); }
  if (action === "registry-tab") { app.registryTab = target.dataset.id; return render(); }
  if (action === "toggle-plugin") { const plugin = (app.state.plugins || []).find((item) => item.name === target.dataset.id); if (plugin) app.currentAgent.plugin_overrides[plugin.name] = !pluginEffective(plugin); return render(); }
  if (action === "toggle-tool") { toggleList("enabled_tools", target.dataset.id); return render(); }
  if (action === "tool-risk") { app.currentAgent.tool_risk_overrides ||= {}; app.currentAgent.tool_risk_overrides[target.dataset.id] = target.value; return render(); }
  if (action === "select-module") { app.selectedModuleId = target.dataset.id; return render(); }
  if (action === "toggle-module") { toggleList("module_ids", target.dataset.id); return render(); }
  if (action === "toggle-skill") { toggleList("enabled_skills", target.dataset.id); return render(); }
  if (action === "save-module-settings") { const module = (app.state.modules || app.state.integrations || []).find((item) => (item.module_id || item.id || item.name) === app.selectedModuleId); app.currentAgent.module_settings ||= {}; const advanced = JSON.parse($("module-settings-json").value || "{}"); app.currentAgent.module_settings[app.selectedModuleId] = readSchemaSettings(module, advanced); toast("蓝图设置已写入任务配置草稿"); return render(); }
  if (action === "save-blueprint") { const result = await api("/api/modules", { method: "POST", body: JSON.parse($("blueprint-json").value || "{}") }); toast(`蓝图已保存：${result.module?.name || result.module?.module_id || "ok"}`); return load(); }
  if (action === "save-credential") { await api("/api/registry", { method: "POST", body: { kind: "credential", label: $("cred-label").value, provider: $("cred-provider").value, scope: $("cred-scope").value, value: $("cred-value").value } }); toast("凭证已保存"); return load(); }
  if (action === "save-api") { await api("/api/registry", { method: "POST", body: { kind: "api", name: $("api-name").value, method: $("api-method").value, url: $("api-url").value, credential_id: $("api-credential").value, auth_type: $("api-auth-type").value, auth_header: $("api-auth-header").value, auth_query_param: $("api-auth-query").value, headers: $("api-headers").value, description: $("api-description").value } }); toast("接口已注册"); return load(); }
  if (action === "save-rules") { for (const [skill_name, content] of [["agent-mode", $("rule-agent-mode").value], ["agent-mode-entry-summary", $("rule-entry").value], ["agent-mode-exit-summary", $("rule-exit").value]]) await api("/api/registry", { method: "POST", body: { kind: "skill_rule", skill_name, content } }); toast("规则已保存"); return load(); }
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action], [data-route]");
  if (!target) return;
  if (target.matches("select")) return;
  event.preventDefault();
  handleAction(target).catch((error) => toast(error.message, "error"));
});

document.addEventListener("change", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  handleAction(target).catch((error) => toast(error.message, "error"));
});

document.addEventListener("input", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target || target.dataset.action !== "node-search") return;
  app.workflow.materialFilter = target.value;
  const list = document.querySelector(".tool-list");
  if (list) list.innerHTML = materialGroupsHtml();
});

$("agent-select").addEventListener("change", (event) => {
  app.selectedAgentId = event.target.value;
  app.currentAgent = ensureAgent(clone((app.state.agents || []).find((agent) => agent.agent_id === app.selectedAgentId)));
  render();
});

$("refresh").addEventListener("click", () => load().catch((error) => toast(error.message, "error")));
$("collapse-nav").addEventListener("click", () => document.body.classList.toggle("nav-collapsed"));

async function submitLogin(event) {
  if (event) event.preventDefault();
  const form = $("auth-form");
  const button = $("login-submit") || form?.querySelector("button");
  const value = $("token-input").value.trim();
  if (!value) {
    showAuth("请输入插件配置 standalone_webui_token 中的访问密码。", "error");
    return;
  }
  saveToken(value);
  if (button) button.disabled = true;
  setAuthStatus("正在验证访问密码...");
  try {
    await boot();
  } catch (error) {
    if (error.status === 401) {
      clearToken();
      showAuth("访问密码不正确，请检查 AstrBot 插件管理里的 standalone_webui_token。", "error");
    } else {
      showApp();
      renderLoadError(error);
    }
  } finally {
    if (button) button.disabled = false;
  }
}

$("auth-form").addEventListener("submit", submitLogin);
$("login-submit")?.addEventListener("click", submitLogin);
$("token-input")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") submitLogin(event).catch((error) => toast(error.message, "error"));
});
window.AgentLabFullAppReady = true;

async function boot() {
  const bootId = ++app.bootId;
  setAuthStatus(token() ? "正在验证访问密码..." : "正在检查控制台访问状态...");
  updateAuthVersion();
  showApp();
  renderLoading(token() ? "正在读取控制台数据..." : "正在尝试无密码访问控制台...");
  try {
    await load();
    if (bootId !== app.bootId) return;
    setAuthStatus("控制台已连接");
  } catch (error) {
    if (bootId !== app.bootId) return;
    if (error.status === 401) {
      const hadToken = !!token();
      clearToken();
      showAuth(hadToken ? "访问密码不正确，请检查 AstrBot 插件管理里的 standalone_webui_token。" : "请输入插件配置 standalone_webui_token 中的访问密码。", hadToken ? "error" : "");
      return;
    }
    showApp();
    renderLoadError(error);
    toast("访问密码已通过，但控制台数据加载失败。", "error");
  }
}

const queryToken = new URLSearchParams(location.search).get("token");
if (queryToken) saveToken(queryToken);
updateAuthVersion();
boot().catch((error) => toast(error.message, "error"));
