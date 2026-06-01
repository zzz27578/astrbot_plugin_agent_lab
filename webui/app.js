const $ = (id) => document.getElementById(id);
const EMPTY_TOOLS_SENTINEL = "__agent_lab_no_external_tools__";
const DEFAULT_ENABLED_TOOLS = [
  "astrbot_file_read_tool",
  "astrbot_grep_tool",
  "astrbot_file_write_tool",
  "astrbot_file_edit_tool",
  "astrbot_execute_shell",
  "astrbot_execute_python",
  "agent_lab_read_task_memory",
  "agent_lab_call_custom_api",
];

const WORKFLOW_STAGES = [
  ["entry", "入口", "压缩上下文"],
  ["plan", "计划", "拆解任务"],
  ["execute", "执行", "调用工具"],
  ["guard", "闸门", "审批/人工"],
  ["checkpoint", "快照", "写回状态"],
  ["archive", "出口", "归档回流"],
];

const WORKFLOW_KINDS = ["state", "tool", "guard", "human", "api", "memory"];
const WORKFLOW_ACTIONS = [
  "confirm_entry",
  "summarize_entry",
  "plan",
  "run_tools",
  "call_api",
  "request_approval",
  "wait_user",
  "save_state",
  "save_memory",
  "heartbeat",
  "archive",
  "exit_summary",
  "manual",
];

const WORKFLOW_NODE_TEMPLATES = [
  {
    id: "entry",
    title: "入口识别",
    kind: "state",
    stage: "entry",
    action: "summarize_entry",
    instruction: "识别暗号、命令、关键词或 WebUI 入口，决定是否准备进入任务模式。",
  },
  {
    id: "entry_gate",
    title: "开启确认",
    kind: "human",
    stage: "entry",
    action: "confirm_entry",
    instruction: "说明隔离、摘要、状态文件和审批影响，等待用户明确同意。",
  },
  {
    id: "plan",
    title: "计划确认",
    kind: "state",
    stage: "plan",
    action: "plan",
    instruction: "拆解完成条件、工具范围、风险等级和本轮有限工作单元。",
  },
  {
    id: "tool",
    title: "工具执行",
    kind: "tool",
    stage: "execute",
    action: "run_tools",
    instruction: "调用白名单工具，并把关键输出写回任务状态。",
  },
  {
    id: "api",
    title: "自定义 API",
    kind: "api",
    stage: "execute",
    action: "call_api",
    instruction: "调用已登记的自定义 API，凭证只由 Agent Lab 注入，不回显给模型。",
  },
  {
    id: "approval",
    title: "审批闸门",
    kind: "guard",
    stage: "guard",
    action: "request_approval",
    instruction: "高风险动作前说明影响、回滚方式和等待用户审批。",
  },
  {
    id: "checkpoint",
    title: "状态快照",
    kind: "state",
    stage: "checkpoint",
    action: "save_state",
    instruction: "写回进度、观察、下一步、阻塞点和验证结果。",
  },
  {
    id: "memory",
    title: "任务记忆",
    kind: "memory",
    stage: "checkpoint",
    action: "save_memory",
    instruction: "沉淀时间线、关键改动、成果、风险和下次续写提示。",
  },
  {
    id: "heartbeat",
    title: "心跳续跑",
    kind: "guard",
    stage: "guard",
    action: "heartbeat",
    instruction: "定时唤醒后先读 task_state，再推进一小步，重复阻塞则暂停。",
  },
  {
    id: "exit",
    title: "结束回流",
    kind: "memory",
    stage: "archive",
    action: "exit_summary",
    instruction: "任务完成或取消时归档成果、改动、风险和可回流记忆候选。",
  },
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
let workflowDrag = null;

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

function scopeLabel(scope) {
  return {
    global: "全局应用",
    entry: "进入式应用",
  }[scope] || "进入式应用";
}

function scopeHint(scope) {
  return {
    global: "默认 AgentSpec 持续参与私聊，长任务请求按触发模式判断。",
    entry: "只在入口命中时进入任务模式，普通会话保持原样。",
  }[scope] || "";
}

function entryChannelLabel(channel) {
  return {
    command: "命令入口",
    natural: "自然语言入口",
    webui: "WebUI 入口",
  }[channel] || "命令入口";
}

function entryChannelHint(channel) {
  return {
    command: "/agentlab start 或用户明确说进入任务模式。",
    natural: "用户提出连续任务时，按触发模式判断是否进入。",
    webui: "从控制台创建任务，适合调试和运营。",
  }[channel] || "";
}

function triggerLabel(mode) {
  return {
    manual: "手动",
    confirm: "先确认",
    smart: "智能判断",
    always: "优先进入",
  }[mode] || mode;
}

function memoryModeLabel(mode) {
  return {
    inherit: "继承会话",
    task_filtered: "任务过滤",
    strict: "严格隔离",
  }[mode] || mode;
}

function approvalModeLabel(mode) {
  return {
    observe: "只观察",
    work: "工作审批",
    high_risk_review: "高危必审",
    delegated: "委托策略",
  }[mode] || mode;
}

function heartbeatModeLabel(mode) {
  return {
    off: "关闭",
    manual: "手动",
    auto: "自动建议",
  }[mode] || mode;
}

function isolationModeLabel(mode) {
  return {
    off: "不隔离",
    session: "会话隔离",
    strict: "严格隔离",
  }[mode] || mode;
}

function toolModeLabel(mode) {
  return {
    full: "全部可用工具",
    whitelist: "工具白名单",
    no_external: "仅任务内置工具",
  }[mode] || mode;
}

function workflowKindLabel(kind) {
  return {
    state: "状态",
    tool: "工具",
    guard: "闸门",
    human: "人工",
    api: "API",
    memory: "记忆",
  }[kind] || kind;
}

function workflowStageLabel(stage) {
  return Object.fromEntries(WORKFLOW_STAGES.map(([id, title]) => [id, title]))[stage] || "计划";
}

function workflowActionLabel(action) {
  return {
    summarize_entry: "入口摘要",
    confirm_entry: "开启确认",
    plan: "计划拆解",
    run_tools: "工具执行",
    call_api: "API 调用",
    request_approval: "请求审批",
    wait_user: "等待用户",
    save_state: "写回状态",
    save_memory: "任务记忆",
    heartbeat: "心跳续跑",
    archive: "归档退出",
    exit_summary: "结束回流",
    manual: "人工判断",
  }[action] || action;
}

function labeledOptions(values, selected, labeler) {
  return values
    .map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(labeler(value))}</option>`)
    .join("");
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
  agent.application_scope ||= "entry";
  agent.entry_channel ||= "command";
  agent.entry_policy ||= {};
  agent.entry_policy.trigger_phrases ||= ["进入任务模式", "开启任务模式", "进入 Agent Mode", "/agentlab start"];
  agent.entry_policy.trigger_keywords ||= ["持续推进", "长任务", "排查", "部署", "写插件", "改代码", "整理资料"];
  agent.entry_policy.require_confirmation ??= true;
  agent.entry_policy.confirmation_text ||= "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？";
  agent.entry_policy.default_completion_conditions ||= ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"];
  agent.entry_policy.exit_phrases ||= ["完成任务", "结束任务模式", "退出任务模式", "退出 Agent Mode", "/agentlab finish"];
  agent.isolation_policy ||= {};
  agent.isolation_policy.mode ||= "strict";
  agent.isolation_policy.tool_mode ||= "whitelist";
  agent.isolation_policy.restore_on_exit ??= true;
  agent.isolation_policy.protect_self ??= true;
  agent.isolation_policy.hide_disabled_plugin_tools ??= true;
  agent.isolation_policy.notes ||= "严格隔离会在当前会话默认关闭普通插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件；不改 AstrBot 全局插件开关，退出时恢复会话快照。";
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
    application_scope: "entry",
    entry_channel: "command",
    trigger_mode: "confirm",
    entry_policy: {
      trigger_phrases: ["进入任务模式", "开启任务模式", "进入 Agent Mode", "/agentlab start"],
      trigger_keywords: ["持续推进", "长任务", "排查", "部署", "写插件", "改代码", "整理资料"],
      require_confirmation: true,
      confirmation_text: "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？",
      default_completion_conditions: ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"],
      exit_phrases: ["完成任务", "结束任务模式", "退出任务模式", "退出 Agent Mode", "/agentlab finish"],
    },
    isolation_policy: {
      mode: "strict",
      tool_mode: "whitelist",
      restore_on_exit: true,
      protect_self: true,
      hide_disabled_plugin_tools: true,
      notes: "严格隔离会在当前会话默认关闭普通插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件；不改 AstrBot 全局插件开关，退出时恢复会话快照。",
    },
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

function taskStatusLabel(status) {
  return {
    running: "运行中",
    paused: "已暂停",
    blocked: "已阻塞",
    completed: "已完成",
    cancelled: "已取消",
  }[status] || status || "-";
}

function approvalStatusLabel(status) {
  return {
    pending: "待审批",
    approved: "已通过",
    rejected: "已拒绝",
    expired: "已过期",
  }[status] || status || "-";
}

function eventKindLabel(kind) {
  return {
    created: "已创建",
    tick: "推进一轮",
    finished: "已归档",
    cancelled: "已取消",
    update_state: "状态写回",
    approval_requested: "请求审批",
    approval_resolved: "审批处理",
    heartbeat_on: "开心跳",
    heartbeat_off: "关心跳",
    heartbeat_recommended: "建议心跳",
    custom_api: "自定义 API",
    tool_start: "工具开始",
    tool_end: "工具结束",
    agent_done: "Agent 完成",
    state: "状态",
  }[kind] || kind || "-";
}

function authTypeLabel(value) {
  return {
    bearer: "Bearer 令牌",
    header: "自定义请求头",
    query: "查询参数",
    none: "不鉴权",
  }[value] || value;
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
    {
      id: "entry",
      title: "入口识别",
      kind: "state",
      stage: "entry",
      action: "summarize_entry",
      description: "识别命令、暗号、关键词或 WebUI 入口。",
      instruction: "只在命中 AgentSpec 的入口策略时准备进入任务模式；普通问答和闲聊不要进入。",
      x: 40,
      y: 160,
    },
    {
      id: "entry_gate",
      title: "开启确认",
      kind: "human",
      stage: "entry",
      action: "confirm_entry",
      description: "确认是否真的进入专业任务模式。",
      instruction: "需要确认时，先说明将隔离插件、压缩上下文、创建 task_state，并等待用户明确同意。",
      x: 260,
      y: 300,
    },
    {
      id: "context_bridge",
      title: "上文压缩",
      kind: "memory",
      stage: "entry",
      action: "summarize_entry",
      description: "把普通聊天上文压成任务 brief。",
      instruction: "只保留目标、约束、授权、风险和接续语气；日常记忆不直接灌入专业模式。",
      x: 260,
      y: 80,
    },
    {
      id: "plan",
      title: "计划确认",
      kind: "state",
      stage: "plan",
      action: "plan",
      description: "把目标拆成可验证的小步。",
      instruction: "明确完成条件、风险等级、工具范围、验收方式，并约束每轮只推进一个有限工作单元。",
      x: 500,
      y: 80,
    },
    {
      id: "execute",
      title: "工具执行",
      kind: "tool",
      stage: "execute",
      action: "run_tools",
      description: "调用白名单工具或自定义 API。",
      instruction: "只使用 AgentSpec 已启用的工具，关键输出必须写回状态。",
      x: 740,
      y: 80,
    },
    {
      id: "approval",
      title: "审批闸门",
      kind: "guard",
      stage: "guard",
      action: "request_approval",
      description: "危险动作前请求用户确认。",
      instruction: "删除、部署、密钥、重启、全局配置和破坏性数据库操作前必须先说明影响并等待审批。",
      x: 740,
      y: 300,
    },
    {
      id: "checkpoint",
      title: "状态快照",
      kind: "state",
      stage: "checkpoint",
      action: "save_state",
      description: "把本轮结果写入 task_state。",
      instruction: "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。",
      x: 960,
      y: 160,
    },
    {
      id: "task_memory",
      title: "任务记忆",
      kind: "memory",
      stage: "checkpoint",
      action: "save_memory",
      description: "独立记录任务时间线和关键成果。",
      instruction: "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆；以标签暴露给普通模式读取。",
      x: 1180,
      y: 80,
    },
    {
      id: "heartbeat",
      title: "心跳续跑",
      kind: "guard",
      stage: "guard",
      action: "heartbeat",
      description: "长任务定时唤醒。",
      instruction: "心跳醒来先读 task_state，再推进一小步；同一阻塞重复三次则暂停求助。",
      x: 1180,
      y: 300,
    },
    {
      id: "archive",
      title: "结束回流",
      kind: "memory",
      stage: "archive",
      action: "exit_summary",
      description: "完成或取消后归档。",
      instruction: "只有完成、取消或用户要求退出时结束；输出成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。",
      x: 1400,
      y: 160,
    },
  ];
}

function defaultWorkflowEdges() {
  return [
    { from: "entry", to: "entry_gate" },
    { from: "entry_gate", to: "context_bridge" },
    { from: "context_bridge", to: "plan" },
    { from: "plan", to: "execute" },
    { from: "execute", to: "approval" },
    { from: "approval", to: "checkpoint" },
    { from: "checkpoint", to: "task_memory" },
    { from: "checkpoint", to: "heartbeat" },
    { from: "heartbeat", to: "execute" },
    { from: "task_memory", to: "archive" },
  ];
}

function workflowTemplate(id) {
  if (id === "api_review") {
    return {
      nodes: [
        { id: "entry", title: "入口压缩", kind: "state", stage: "entry", action: "summarize_entry", description: "整理目标与调用约束", instruction: "把用户目标、接口用途、参数边界和授权范围压缩成 task_brief。", x: 40, y: 160 },
        { id: "plan", title: "调用计划", kind: "state", stage: "plan", action: "plan", description: "明确 API 调用方案", instruction: "确认要调用的注册 API、参数、风险级别和成功判定。", x: 270, y: 90 },
        { id: "approval", title: "敏感审批", kind: "human", stage: "guard", action: "request_approval", description: "涉及外部写入或敏感数据时审批", instruction: "如果 API 会写入外部系统、发送消息、产生费用或读取敏感数据，先请求用户审批。", x: 500, y: 300 },
        { id: "call_api", title: "调用 API", kind: "api", stage: "execute", action: "call_api", description: "执行已注册自定义 API", instruction: "使用 agent_lab_call_custom_api 调用已注册 API，隐藏凭证，只保留必要结果摘要。", x: 500, y: 90 },
        { id: "review", title: "结果复核", kind: "state", stage: "checkpoint", action: "save_state", description: "检查结果并写回状态", instruction: "核对 API 返回是否满足完成条件；写回观察、进度和下一步。", x: 750, y: 160 },
        { id: "archive", title: "出口归档", kind: "memory", stage: "archive", action: "archive", description: "沉淀可复用信息", instruction: "完成后只归档稳定有用的事实，避免保存密钥、一次性 token 或临时响应。", x: 980, y: 160 },
      ],
      edges: [
        { from: "entry", to: "plan" },
        { from: "plan", to: "approval" },
        { from: "approval", to: "call_api" },
        { from: "plan", to: "call_api" },
        { from: "call_api", to: "review" },
        { from: "review", to: "archive" },
      ],
    };
  }
  return { nodes: defaultWorkflowNodes(), edges: defaultWorkflowEdges() };
}

function applyWorkflowTemplate(id) {
  const template = workflowTemplate(id);
  currentAgent.workflow_nodes = clone(template.nodes);
  currentAgent.workflow_edges = clone(template.edges);
  selectedWorkflowNodeId = currentAgent.workflow_nodes[0]?.id || "";
  setFeedback(id === "api_review" ? "已套用 API 审批流，保存后会进入任务运行协议。" : "已套用标准工作流，保存后会进入任务运行协议。");
}

function addWorkflowTemplateNode(templateId) {
  readAgentForm();
  ensureWorkflow();
  const template = WORKFLOW_NODE_TEMPLATES.find((item) => item.id === templateId) || WORKFLOW_NODE_TEMPLATES[0];
  const id = uniqueWorkflowNodeId(template.id);
  const pos = defaultWorkflowPosition(template.stage, currentAgent.workflow_nodes.length);
  currentAgent.workflow_nodes.push({
    ...clone(template),
    id,
    description: template.title,
    x: pos.x,
    y: pos.y,
  });
  selectedWorkflowNodeId = id;
  setFeedback(`已添加节点：${template.title}。拖动画布上的节点即可调整位置。`);
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function defaultWorkflowPosition(stage, index = 0) {
  const stageIndex = Math.max(0, WORKFLOW_STAGES.findIndex(([id]) => id === stage));
  return {
    x: 40 + stageIndex * 220,
    y: 80 + (index % 3) * 150,
  };
}

function defaultWorkflowAction(node) {
  const stage = String(node?.stage || "").trim();
  const kind = String(node?.kind || "").trim();
  if (stage === "entry") return "summarize_entry";
  if (stage === "execute" && kind === "api") return "call_api";
  if (stage === "execute") return "run_tools";
  if (stage === "checkpoint" && kind === "memory") return "save_memory";
  if (stage === "guard" && kind === "human") return "wait_user";
  if (stage === "guard") return "request_approval";
  if (stage === "checkpoint") return "save_state";
  if (stage === "archive") return "exit_summary";
  return "plan";
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
    kind: WORKFLOW_KINDS.includes(String(node.kind || "").trim()) ? String(node.kind).trim() : "state",
    stage: workflowStage(node),
    action: String(node.action || defaultWorkflowAction(node)).trim() || "manual",
    description: String(node.description || "").trim(),
    instruction: String(node.instruction || node.prompt || node.description || "").trim(),
    x: clamp(Number(node.x ?? defaultWorkflowPosition(workflowStage(node), index).x), 0, 3000),
    y: clamp(Number(node.y ?? defaultWorkflowPosition(workflowStage(node), index).y), 0, 1800),
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
      ${metric("Token 消耗", m.token_usage ?? 0, "仅统计模型供应商上报的 usage")}
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
          <div class="row-meta">${esc(agent.agent_id)} · 触发：${esc(triggerLabel(agent.trigger_mode || "confirm"))} · 模型供应商：${esc(agent.provider_id || "当前会话")}</div>
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
  if (!tasks.length) return `<div class="empty">${archive ? "暂无归档任务。" : "暂无活跃任务。"}</div>`;
  return tasks
    .map(
      (task) => {
        const health = task.heartbeat_health || {};
        return `
          <button class="list-row ${task.task_id === selectedTaskId ? "selected" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
            <div class="row-title">
              <span>${esc(task.root_goal || task.task_id)}</span>
              <span class="row-badges">
                ${badge(taskStatusLabel(task.status), task.status === "running" ? "ok" : task.status === "blocked" ? "bad" : "warn")}
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
  const currentName = agentDisplayName(currentAgent);
  const stats = agentStats(currentAgent);
  $("view").innerHTML = `
    <section class="panel canvas-hero">
      <div class="canvas-hero-main">
        <div>
          <p class="card-kicker">当前任务模式配置</p>
          <h2>${esc(currentName)}</h2>
          <div class="module-meta">
            ${badge(scopeLabel(currentAgent.application_scope), currentAgent.application_scope === "global" ? "ok" : "warn")}
            ${badge(entryChannelLabel(currentAgent.entry_channel))}
            ${badge(triggerLabel(currentAgent.trigger_mode || "confirm"))}
            ${badge(currentAgent.enabled === false ? "已停用" : "已启用", currentAgent.enabled === false ? "bad" : "ok")}
          </div>
          <div class="row-meta">${esc(currentAgent.agent_id || "新配置尚未保存")} · 运行 ${stats.active} · 触发 ${stats.triggers} · Token ${stats.tokens} · 待审批 ${stats.approvals}</div>
        </div>
        <div class="inline-actions">
          <button class="button secondary" data-action="new-agent" type="button">新建配置</button>
          <button class="button secondary" data-action="duplicate-agent" type="button">复制配置</button>
          <button class="button secondary" data-action="make-default" type="button">设为默认</button>
          <button class="button" data-action="save-agent" type="button">保存配置</button>
        </div>
      </div>
      <div class="choice-grid two-choice">
        ${["entry", "global"].map((scope) => `
          <button class="choice-card ${currentAgent.application_scope === scope ? "active" : ""}" data-action="set-agent-scope" data-id="${scope}" type="button">
            <strong>${esc(scopeLabel(scope))}</strong>
            <span>${esc(scopeHint(scope))}</span>
          </button>
        `).join("")}
      </div>
      <div class="choice-grid three-choice">
        ${["command", "natural", "webui"].map((channel) => `
          <button class="choice-card ${currentAgent.entry_channel === channel ? "active" : ""}" data-action="set-entry-channel" data-id="${channel}" type="button">
            <strong>${esc(entryChannelLabel(channel))}</strong>
            <span>${esc(entryChannelHint(channel))}</span>
          </button>
        `).join("")}
      </div>
    </section>

    <section class="grid two setup-grid">
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">进入入口</p><h2>从 WebUI 进入任务模式</h2></div>
        </div>
        <div class="form-grid">
          <label>会话 UMO<input id="canvas-umo" placeholder="aiocqhttp:FriendMessage:123456" /></label>
          <label>风险级别<select id="canvas-risk-level">${labeledOptions(["low", "work", "high"], "work", (value) => ({ low: "低风险", work: "工作风险", high: "高风险" }[value] || value))}</select></label>
          <label class="span-2">任务目标<textarea id="canvas-goal" rows="3">请把当前任务作为 Agent Mode 管理起来。</textarea></label>
          <label class="span-2">完成条件<input id="canvas-completion" value="${esc((currentAgent.entry_policy.default_completion_conditions || ["用户验收通过"]).join("；"))}" /></label>
          <label class="span-2">入口补充<textarea id="canvas-brief" rows="3" placeholder="可写入刚刚确认过的计划、约束、授权范围。"></textarea></label>
          <label class="check-line span-2"><input id="canvas-start-heartbeat" type="checkbox" />进入后立即开心跳</label>
        </div>
        <div class="button-row">
          <button class="button" data-action="canvas-start-task" type="button">进入任务模式</button>
          <button class="button secondary" data-route="tasks" type="button">查看任务状态</button>
        </div>
      </div>

      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">规则配置</p><h2>触发、记忆、审批、心跳</h2></div></div>
        <div class="form-grid">
          <label>任务模式配置名称<input id="agent-name" value="${esc(currentAgent.name || "")}" placeholder="${esc(runtimeAgentName())}" /></label>
        <label>底层模型供应商 ID<input id="provider-id" value="${esc(currentAgent.provider_id || "")}" placeholder="为空则使用当前会话模型" /></label>
          <label>配置状态<select id="agent-enabled">${labeledOptions(["true", "false"], String(currentAgent.enabled !== false), (value) => value === "true" ? "启用" : "停用")}</select></label>
          <label>触发模式<select id="trigger-mode">${labeledOptions(["manual", "confirm", "smart", "always"], currentAgent.trigger_mode || "confirm", triggerLabel)}</select></label>
          <label>开启确认<select id="entry-require-confirmation">${labeledOptions(["true", "false"], String(currentAgent.entry_policy.require_confirmation !== false), (value) => value === "true" ? "需要确认" : "直接开启")}</select></label>
          <label>隔离模式<select id="isolation-mode">${labeledOptions(["strict", "session", "off"], currentAgent.isolation_policy.mode || "strict", isolationModeLabel)}</select></label>
          <label>工具模式<select id="tool-mode">${labeledOptions(["whitelist", "no_external", "full"], currentAgent.isolation_policy.tool_mode || "whitelist", toolModeLabel)}</select></label>
          <label>退出后恢复<select id="restore-on-exit">${labeledOptions(["true", "false"], String(currentAgent.isolation_policy.restore_on_exit !== false), (value) => value === "true" ? "恢复会话隔离快照" : "保留当前会话状态")}</select></label>
          <label>记忆模式<select id="memory-mode">${labeledOptions(["inherit", "task_filtered", "strict"], currentAgent.memory_policy.mode || "task_filtered", memoryModeLabel)}</select></label>
          <label>审批模式<select id="approval-mode">${labeledOptions(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work", approvalModeLabel)}</select></label>
          <label>心跳模式<select id="heartbeat-mode">${labeledOptions(["off", "manual", "auto"], currentAgent.heartbeat_policy.mode || "manual", heartbeatModeLabel)}</select></label>
          <label>允许心跳<select id="heartbeat-allowed">${labeledOptions(["true", "false"], String(currentAgent.heartbeat_policy.allowed !== false), (value) => value === "true" ? "允许" : "禁止")}</select></label>
          <label>上下文摘要轮数<input id="entry-summary-turns" type="number" min="1" value="${esc(currentAgent.memory_policy.entry_summary_turns || 24)}" /></label>
          <label>心跳 Cron<input id="heartbeat-cron" value="${esc(currentAgent.heartbeat_policy.cron_expression || "*/5 * * * *")}" /></label>
          <label class="span-2">开启暗号/命令<textarea id="entry-trigger-phrases" rows="3" placeholder="每行一个，例如：进入任务模式">${esc(listToLines(currentAgent.entry_policy.trigger_phrases))}</textarea></label>
          <label class="span-2">任务关键词<textarea id="entry-trigger-keywords" rows="3" placeholder="每行一个，例如：排查、部署、持续推进">${esc(listToLines(currentAgent.entry_policy.trigger_keywords))}</textarea></label>
          <label class="span-2">开启确认话术<textarea id="entry-confirmation-text" rows="3">${esc(currentAgent.entry_policy.confirmation_text || "")}</textarea></label>
          <label class="span-2">默认完成条件<textarea id="default-completion-conditions" rows="3">${esc(listToLines(currentAgent.entry_policy.default_completion_conditions))}</textarea></label>
          <label class="span-2">结束暗号/命令<textarea id="exit-phrases" rows="3">${esc(listToLines(currentAgent.entry_policy.exit_phrases))}</textarea></label>
          <label class="span-2">隔离说明<textarea id="isolation-notes" rows="3">${esc(currentAgent.isolation_policy.notes || "")}</textarea></label>
          <div class="span-2 note-line">当前运行时身份：${esc(state.runtime?.bot_label || "等待读取")}；来源：${esc(identitySourceLabel(state.runtime?.bot_label_source))}。这里配置的是任务模式模板名和规则，不会覆盖 AstrBot 当前身份。</div>
        </div>
      </div>
    </section>

    <section class="panel workflow-panel">
      <div class="panel-head">
        <div><p class="card-kicker">画布</p><h2>任务模式工作流</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-action="add-workflow-node" type="button">新增节点</button>
          <button class="button secondary" data-action="apply-workflow-template" data-id="linear" type="button">标准流程</button>
          <button class="button secondary" data-action="apply-workflow-template" data-id="api_review" type="button">API 审批流</button>
          <button class="button secondary" data-action="reset-workflow" type="button">恢复默认流程</button>
        </div>
      </div>
      <div class="workflow-layout">
        <div>
          ${workflowCanvas()}
          ${workflowToolbox()}
        </div>
        <div class="workflow-side">
          ${workflowSummaryPanel()}
          ${workflowInspector()}
          ${workflowEdgesPanel()}
        </div>
      </div>
    </section>

    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">提示词</p><h2>任务运行协议</h2></div></div>
        <label class="span-2">任务模式补充提示词（不是身份替换）<textarea id="system-prompt" rows="5">${esc(currentAgent.system_prompt || "")}</textarea></label>
        <label class="span-2">每轮执行协议<textarea id="task-prompt" rows="5">${esc(currentAgent.task_prompt || "")}</textarea></label>
        <details class="advanced-json">
          <summary>高级：工作流 JSON 导入/导出</summary>
          <textarea id="workflow-json" rows="8" data-original="${esc(JSON.stringify(workflowData(), null, 2))}">${esc(JSON.stringify(workflowData(), null, 2))}</textarea>
        </details>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">资产列表</p><h2>选择任务模式配置</h2></div></div>
        <div class="list">${agentRows()}</div>
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

function workflowStage(item) {
  const explicit = String(item.stage || "").trim();
  if (WORKFLOW_STAGES.some(([stage]) => stage === explicit)) return explicit;
  const id = String(item.id || "").toLowerCase();
  const title = String(item.title || "").toLowerCase();
  if (id.includes("entry") || title.includes("入口")) return "entry";
  if (id.includes("plan") || title.includes("计划")) return "plan";
  if (["tool", "api"].includes(item.kind) || id.includes("execute") || title.includes("执行")) return "execute";
  if (id.includes("checkpoint") || title.includes("快照")) return "checkpoint";
  if (id.includes("archive") || title.includes("归档")) return "archive";
  if (["guard", "human"].includes(item.kind) || id.includes("approval") || id.includes("heartbeat")) return "guard";
  return "plan";
}

function workflowBoard() {
  ensureWorkflow();
  return workflowCanvas();
}

function workflowCanvasSize() {
  ensureWorkflow();
  const nodes = currentAgent.workflow_nodes || [];
  const maxX = nodes.reduce((value, node) => Math.max(value, Number(node.x || 0)), 0);
  const maxY = nodes.reduce((value, node) => Math.max(value, Number(node.y || 0)), 0);
  return {
    width: Math.max(1160, maxX + 230),
    height: Math.max(560, maxY + 150),
  };
}

function workflowCanvas() {
  ensureWorkflow();
  const size = workflowCanvasSize();
  return `
    <div class="workflow-canvas-wrap">
      <div class="workflow-canvas" style="width:${size.width}px;height:${size.height}px">
        <div class="workflow-lanes">
          ${WORKFLOW_STAGES.map(([stage, title, meta], index) => `
            <div class="workflow-lane" data-stage="${stage}" style="left:${index * 220}px">
              <strong>${esc(title)}</strong>
              <span>${esc(meta)}</span>
            </div>
          `).join("")}
        </div>
        <svg class="workflow-links" width="${size.width}" height="${size.height}" viewBox="0 0 ${size.width} ${size.height}" aria-hidden="true">
          ${workflowLinksSvg()}
        </svg>
        ${currentAgent.workflow_nodes.map((item) => node(item)).join("")}
      </div>
    </div>
    ${workflowCompactBoard()}
  `;
}

function workflowToolbox() {
  const selectedTools = materializedToolSelection().slice(0, 12);
  return `
    <div class="workflow-toolbox">
      <div>
        <strong>节点素材</strong>
        <div class="toolbox-buttons">
          ${WORKFLOW_NODE_TEMPLATES.map((item) => `
            <button class="toolbox-chip" data-action="add-template-node" data-id="${esc(item.id)}" type="button">
              <span>${esc(workflowKindLabel(item.kind))}</span>
              ${esc(item.title)}
            </button>
          `).join("")}
        </div>
      </div>
      <div>
        <strong>当前工具白名单</strong>
        <div class="toolbox-tools">
          ${selectedTools.map((name) => `<span>${esc(name)}</span>`).join("") || "<em>仅任务内置工具</em>"}
        </div>
      </div>
    </div>
  `;
}

function workflowCompactBoard() {
  ensureWorkflow();
  const nodesByStage = new Map(WORKFLOW_STAGES.map(([stage]) => [stage, []]));
  for (const item of currentAgent.workflow_nodes || []) {
    const stage = workflowStage(item);
    if (!nodesByStage.has(stage)) nodesByStage.set(stage, []);
    nodesByStage.get(stage).push(item);
  }
  return `
    <div class="workflow-compact-board">
      ${WORKFLOW_STAGES.map(([stage, title, meta]) => {
        const nodes = nodesByStage.get(stage) || [];
        return `
          <section class="workflow-compact-stage" data-stage="${esc(stage)}">
            <div class="workflow-compact-head">
              <strong>${esc(title)}</strong>
              <span>${esc(meta)}</span>
            </div>
            <div class="workflow-compact-stack">
              ${nodes.map((item) => `
                <button class="workflow-compact-node ${item.id === selectedWorkflowNodeId ? "selected" : ""}" data-action="select-workflow-node" data-id="${esc(item.id)}" type="button">
                  <span>${esc(workflowKindLabel(item.kind))} · ${esc(workflowActionLabel(item.action))}</span>
                  <strong>${esc(item.title || item.id)}</strong>
                  <small>${esc(item.instruction || item.description || "点击后在下方编辑这个节点。")}</small>
                </button>
              `).join("") || `<div class="small-empty">暂无节点</div>`}
            </div>
          </section>
        `;
      }).join("")}
    </div>
  `;
}

function workflowLinksSvg() {
  ensureWorkflow();
  const edges = currentAgent.workflow_edges || [];
  const nodes = new Map((currentAgent.workflow_nodes || []).map((item) => [item.id, item]));
  const paths = edges.map((edge) => {
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) return "";
    const x1 = Number(from.x || 0) + 190;
    const y1 = Number(from.y || 0) + 58;
    const x2 = Number(to.x || 0);
    const y2 = Number(to.y || 0) + 58;
    const bend = Math.max(70, Math.abs(x2 - x1) * 0.45);
    const d = `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
    return `<path d="${d}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}"></path>`;
  }).join("");
  return `
    <defs>
      <marker id="workflow-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z"></path>
      </marker>
    </defs>
    ${paths}
  `;
}

function workflowSummaryPanel() {
  ensureWorkflow();
  const nodeCount = currentAgent.workflow_nodes.length;
  const edgeCount = currentAgent.workflow_edges.length;
  const selected = selectedWorkflowNode();
  return `
    <div class="detail-box workflow-summary">
      <div class="panel-head"><div><p class="card-kicker">运行框架</p><h3>${nodeCount} 节点 · ${edgeCount} 连线</h3></div></div>
      <div class="mini-stats">
        <span>${esc(workflowStageLabel(selected?.stage || "plan"))}</span>
        <span>${esc(workflowKindLabel(selected?.kind || "state"))}</span>
        <span>${esc(workflowActionLabel(selected?.action || "manual"))}</span>
        <span>${edgeCount ? "可运行" : "待连线"}</span>
      </div>
    </div>
  `;
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
    <button class="node flow-node ${selected ? "selected" : ""}" style="left:${Number(item.x || 0)}px;top:${Number(item.y || 0)}px" data-action="select-workflow-node" data-id="${esc(item.id)}" data-kind="${esc(item.kind)}" type="button">
      <span class="node-stage">${esc(workflowStageLabel(item.stage || "plan"))} · ${esc(workflowActionLabel(item.action || "manual"))}</span>
      <strong>${esc(item.title || item.id)}</strong>
      <p>${esc(item.instruction || item.description || item.id)}</p>
      <span>${esc(item.id)} · ${esc(workflowKindLabel(item.kind || "state"))}</span>
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
      <div class="form-grid compact">
        <label>阶段<select id="workflow-node-stage">${labeledOptions(WORKFLOW_STAGES.map(([id]) => id), item.stage || "plan", workflowStageLabel)}</select></label>
        <label>类型<select id="workflow-node-kind">${labeledOptions(WORKFLOW_KINDS, item.kind || "state", workflowKindLabel)}</select></label>
        <label>动作<select id="workflow-node-action">${labeledOptions(WORKFLOW_ACTIONS, item.action || "manual", workflowActionLabel)}</select></label>
        <label>位置 X<input id="workflow-node-x" type="number" min="0" value="${esc(item.x || 0)}" /></label>
        <label>位置 Y<input id="workflow-node-y" type="number" min="0" value="${esc(item.y || 0)}" /></label>
      </div>
      <label>说明<input id="workflow-node-description" value="${esc(item.description || "")}" /></label>
      <label>执行指令<textarea id="workflow-node-instruction" rows="5">${esc(item.instruction || "")}</textarea></label>
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
        <label>起点<select id="workflow-edge-from">${workflowNodeOptions(selectedWorkflowNodeId)}</select></label>
        <label>终点<select id="workflow-edge-to">${workflowNodeOptions(currentAgent.workflow_nodes[1]?.id || selectedWorkflowNodeId)}</select></label>
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

function options(values, selected, labeler = (value) => value) {
  return values
    .map((value) => `<option value="${esc(value)}" ${value === selected ? "selected" : ""}>${esc(labeler(value))}</option>`)
    .join("");
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
  currentAgent.application_scope = ["entry", "global"].includes(currentAgent.application_scope) ? currentAgent.application_scope : "entry";
  currentAgent.entry_channel = ["command", "natural", "webui"].includes(currentAgent.entry_channel) ? currentAgent.entry_channel : "command";
  currentAgent.trigger_mode = $("trigger-mode").value;
  currentAgent.entry_policy.trigger_phrases = linesToList($("entry-trigger-phrases").value);
  currentAgent.entry_policy.trigger_keywords = linesToList($("entry-trigger-keywords").value);
  currentAgent.entry_policy.require_confirmation = $("entry-require-confirmation").value === "true";
  currentAgent.entry_policy.confirmation_text = $("entry-confirmation-text").value.trim();
  currentAgent.entry_policy.default_completion_conditions = linesToList($("default-completion-conditions").value);
  currentAgent.entry_policy.exit_phrases = linesToList($("exit-phrases").value);
  currentAgent.isolation_policy.mode = $("isolation-mode").value;
  currentAgent.isolation_policy.tool_mode = $("tool-mode").value;
  currentAgent.isolation_policy.restore_on_exit = $("restore-on-exit").value === "true";
  currentAgent.isolation_policy.notes = $("isolation-notes").value.trim();
  currentAgent.memory_policy.mode = $("memory-mode").value;
  currentAgent.memory_policy.entry_summary_turns = Number($("entry-summary-turns").value || 24);
  currentAgent.approval_policy.mode = $("approval-mode").value;
  currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").value === "true";
  currentAgent.heartbeat_policy.cron_expression = $("heartbeat-cron").value.trim() || "*/5 * * * *";
  currentAgent.system_prompt = $("system-prompt").value;
  currentAgent.task_prompt = $("task-prompt").value;
  const workflowJson = $("workflow-json");
  if (workflowJson && workflowJson.value.trim() !== (workflowJson.dataset.original || "").trim()) {
    const workflow = JSON.parse(workflowJson.value || "{}");
    currentAgent.workflow_nodes = Array.isArray(workflow.nodes) ? workflow.nodes : currentAgent.workflow_nodes;
    currentAgent.workflow_edges = Array.isArray(workflow.edges) ? workflow.edges : currentAgent.workflow_edges;
    ensureWorkflow();
  }
}

function renderTasks() {
  currentAgent = ensureAgent(currentAgent || {});
  const task = selectedTask();
  const runnableTask = activeTask();
  $("view").innerHTML = `
    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">入口</p><h2>进入任务模式</h2></div></div>
        <div class="form-grid">
          <label>会话 UMO<input id="umo" placeholder="aiocqhttp:FriendMessage:123456" /></label>
          <label>风险级别<select id="task-risk-level">${labeledOptions(["low", "work", "high"], "work", (value) => ({ low: "低风险", work: "工作风险", high: "高风险" }[value] || value))}</select></label>
          <label class="span-2">任务目标<textarea id="goal" rows="3">请把当前任务作为 Agent Mode 管理起来。</textarea></label>
          <label class="span-2">完成条件<input id="completion" value="${esc((currentAgent.entry_policy.default_completion_conditions || ["用户验收通过"]).join("；"))}" /></label>
          <label class="span-2">入口补充<textarea id="brief" rows="3"></textarea></label>
          <label class="check-line span-2"><input id="task-start-heartbeat" type="checkbox" />进入后立即开心跳</label>
        </div>
        <div class="button-row"><button class="button" data-action="start-task" type="button">进入任务模式</button></div>
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">当前</p><h2>当前任务</h2></div></div>
        <div class="list">${taskRows(state.tasks || [])}</div>
      </div>
    </section>
    <section class="grid two">
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">状态</p><h2>任务快照</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="tick-task" ${runnableTask ? "" : "disabled"} type="button">推进一轮</button>
            <button class="button secondary" data-action="toggle-heartbeat" ${runnableTask ? "" : "disabled"} type="button">${runnableTask?.heartbeat?.enabled ? "关闭心跳" : "开启心跳"}</button>
            <button class="button secondary" data-action="finish-task" ${runnableTask ? "" : "disabled"} type="button">完成归档</button>
            <button class="button danger" data-action="cancel-task" ${runnableTask ? "" : "disabled"} type="button">取消归档</button>
          </div>
        </div>
        ${task ? taskDetail(task) : `<div class="empty">请选择或创建任务。</div>`}
      </div>
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">记忆候选</p><h2>出口回流</h2></div></div>
        <label>新增/修剪长期记忆<textarea id="memory-text" rows="4" placeholder="只保存稳定事实、项目约定或后续任务需要复用的要点。"></textarea></label>
        <div class="form-grid compact">
          <label>记忆标签<input id="memory-tags" placeholder="任务, 插件, 续写" /></label>
          <label>初始状态<select id="memory-status">${labeledOptions(["candidate", "accepted"], "candidate", memoryFilterLabel)}</select></label>
          <label class="span-2">普通模式可读<select id="memory-expose">${labeledOptions(["true", "false"], "true", (value) => value === "true" ? "允许普通模式读取" : "仅任务模式读取")}</select></label>
        </div>
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
      <div class="panel-head"><div><p class="card-kicker">归档</p><h2>历史异步任务</h2></div></div>
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
          ${badge(taskStatusLabel(task.status), task.status === "running" ? "ok" : task.status === "blocked" ? "bad" : "warn")}
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
    <div class="panel-head"><div><p class="card-kicker">审批</p><h3>待审批</h3></div></div>
    <div class="list">${approvalRows(pendingApprovals)}</div>
    <div class="panel-head"><div><p class="card-kicker">快照</p><h3>状态快照时间线</h3></div></div>
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
  const task = selectedTask();
  return approvals.map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.operation || item.approval_id)}</span>${badge(approvalStatusLabel(item.status || "pending"), "warn")}</div>
      <div class="row-meta">${esc(item.approval_id)} · ${esc(item.reason || "-")}</div>
      <div class="row-meta">影响：${esc(item.impact || "-")} · 回滚：${esc(item.rollback || "-")}</div>
      <div class="inline-actions approval-actions">
        <button class="button secondary" data-action="resolve-approval" data-id="${esc(item.approval_id)}" data-umo="${esc(task?.umo || "")}" data-approved="true" type="button">通过</button>
        <button class="button danger" data-action="resolve-approval" data-id="${esc(item.approval_id)}" data-umo="${esc(task?.umo || "")}" data-approved="false" type="button">拒绝</button>
      </div>
    </div>
  `).join("");
}

function snapshotRows(snapshots) {
  if (!snapshots.length) return `<div class="empty">暂无状态快照。</div>`;
  return snapshots.slice(-12).reverse().map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(eventKindLabel(item.kind || "state"))}</span>${badge(taskStatusLabel(item.status || "-"))}</div>
      <div class="row-meta">${esc(item.time || "")} · ${esc(item.next_step || "无下一步")}</div>
    </div>
  `).join("");
}

function memoryRows() {
  const rows = (state.memories || []).filter((item) => memoryFilter === "all" || item.status === memoryFilter);
  if (!rows.length) return `<div class="empty">暂无可审查记忆。任务结束后会生成候选，也可以手动保存。</div>`;
  return rows.slice(-20).reverse().map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.text)}</span>${badge(memoryFilterLabel(item.status || "candidate"), item.status === "accepted" ? "ok" : "warn")}</div>
      <div class="row-meta">${esc(item.memory_id)} · 来源任务：${esc(item.source_task_id || "-")} · 标签：${esc((item.tags || []).join(", ") || "-")} · ${item.expose_to_normal === false ? "仅任务模式" : "普通模式可读"}</div>
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
        <div class="panel-head"><div><p class="card-kicker">实时</p><h3>实时日志流（5 秒刷新）</h3></div></div>
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
        <button class="button" data-action="save-agent" type="button">保存当前配置</button>
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
        ? ["任务中开启", "ok"]
        : ["任务中关闭", "warn"];
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
        <span><strong>${esc(tool.name)}</strong><br /><small>${esc(tool.plugin_display_name || tool.source || "注册工具")}</small></span>
        <span class="tool-controls">
          ${badge(riskLabel(risk), riskTone(risk))}
          ${badge(disabled ? "随插件关闭" : checked ? "已选择" : "未选择", disabled ? "bad" : checked ? "ok" : "")}
          <select data-action="set-tool-risk" data-id="${esc(tool.name)}">${options(["safe", "work", "high"], risk, riskLabel)}</select>
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
      工具按来源插件分组；保存后会进入任务运行白名单。
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
        <label>审批模式<select id="tool-approval-mode">${options(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work", approvalModeLabel)}</select></label>
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
        <div class="section-note">规则会影响进入、执行与归档。</div>
        <label>agent-mode 行为规则<textarea id="skill-rule-content" rows="8" placeholder="写入任务模式的触发、审批、记忆过滤、工具边界等补充规则。">${esc(agentModeRule.content || "")}</textarea></label>
        <label>入口摘要规则<textarea id="entry-summary-rule-content" rows="7" placeholder="定义进入任务模式时如何把当前上下文压缩成 task_brief。">${esc(entryRule.content || "")}</textarea></label>
        <label>出口归档规则<textarea id="exit-summary-rule-content" rows="7" placeholder="定义退出任务模式时如何归档总结，以及哪些记忆候选可以回流。">${esc(exitRule.content || "")}</textarea></label>
        <div class="button-row"><button class="button" data-action="save-skill-rules" type="button">保存并同步规则</button></div>
      </div>
      <div class="capability-list">${(state.skills || []).map((skill) => `
        <label class="toggle-row">
          <input type="checkbox" data-action="toggle-skill" data-id="${esc(skill.name)}" ${selected.has(skill.name) ? "checked" : ""} />
          <span><strong>${esc(skill.name)}</strong><br /><small>${esc(skill.path || "AstrBot Skill")}</small></span>
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
          <label>鉴权方式<select id="api-auth-type">${options(["bearer", "header", "query", "none"], "bearer", authTypeLabel)}</select></label>
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
          <div class="row-meta">${esc(item.url)} · 凭证：${esc(item.credential_id || "无")} · 鉴权：${esc(authTypeLabel(item.auth_type || "bearer"))}</div>
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
          <label>服务商<input id="cred-provider" placeholder="xai / openai / tavily" /></label>
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
      control = `<select ${attrs}>${options(["true", "false"], String(Boolean(value)), (item) => item === "true" ? "是" : "否")}</select>`;
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
      蓝图是可开关的运行规则；真正调用能力在注册工具和自定义 API 里管理。
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
  return result.agent;
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

function workflowNodeById(id) {
  ensureWorkflow();
  return currentAgent.workflow_nodes.find((item) => item.id === id);
}

function refreshWorkflowCanvasDom() {
  const svg = document.querySelector(".workflow-links");
  if (!svg) return;
  const size = workflowCanvasSize();
  const canvas = document.querySelector(".workflow-canvas");
  if (canvas) {
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
  }
  svg.setAttribute("width", String(size.width));
  svg.setAttribute("height", String(size.height));
  svg.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);
  svg.innerHTML = workflowLinksSvg();
}

document.addEventListener("pointerdown", (event) => {
  const nodeEl = event.target.closest(".flow-node");
  if (!nodeEl || !document.querySelector(".workflow-canvas")?.contains(nodeEl)) return;
  const item = workflowNodeById(nodeEl.dataset.id);
  if (!item) return;
  selectedWorkflowNodeId = item.id;
  document.querySelectorAll(".flow-node.selected").forEach((node) => node.classList.remove("selected"));
  nodeEl.classList.add("selected");
  workflowDrag = {
    id: item.id,
    element: nodeEl,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    baseX: Number(item.x || 0),
    baseY: Number(item.y || 0),
    moved: false,
  };
  nodeEl.setPointerCapture?.(event.pointerId);
});

document.addEventListener("pointermove", (event) => {
  if (!workflowDrag || workflowDrag.pointerId !== event.pointerId) return;
  const item = workflowNodeById(workflowDrag.id);
  if (!item) return;
  const dx = event.clientX - workflowDrag.startX;
  const dy = event.clientY - workflowDrag.startY;
  workflowDrag.moved ||= Math.abs(dx) + Math.abs(dy) > 3;
  item.x = clamp(workflowDrag.baseX + dx, 0, 3000);
  item.y = clamp(workflowDrag.baseY + dy, 0, 1800);
  workflowDrag.element.style.left = `${item.x}px`;
  workflowDrag.element.style.top = `${item.y}px`;
  refreshWorkflowCanvasDom();
});

document.addEventListener("pointerup", (event) => {
  if (!workflowDrag || workflowDrag.pointerId !== event.pointerId) return;
  workflowDrag.element.releasePointerCapture?.(event.pointerId);
  if (workflowDrag.moved) {
    setFeedback("节点位置已更新，保存配置后生效。");
  }
  workflowDrag = null;
});

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
    if (action === "set-agent-scope") {
      readAgentForm();
      currentAgent.application_scope = target.dataset.id === "global" ? "global" : "entry";
      render();
    }
    if (action === "set-entry-channel") {
      readAgentForm();
      const channel = target.dataset.id;
      currentAgent.entry_channel = ["command", "natural", "webui"].includes(channel) ? channel : "command";
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
      const pos = defaultWorkflowPosition("plan", currentAgent.workflow_nodes.length);
      currentAgent.workflow_nodes.push({
        id,
        title: "新节点",
        kind: "state",
        stage: "plan",
        action: "manual",
        description: "自定义流程节点",
        instruction: "写清楚这个节点何时执行、要产出什么、如何写回任务状态。",
        x: pos.x,
        y: pos.y,
      });
      selectedWorkflowNodeId = id;
      render();
    }
    if (action === "add-template-node") {
      addWorkflowTemplateNode(target.dataset.id || "plan");
      render();
    }
    if (action === "apply-workflow-template") {
      readAgentForm();
      applyWorkflowTemplate(target.dataset.id || "linear");
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
      node.stage = $("workflow-node-stage").value;
      node.action = $("workflow-node-action").value;
      node.description = $("workflow-node-description").value.trim();
      node.instruction = $("workflow-node-instruction").value.trim();
      node.x = clamp(Number($("workflow-node-x").value || node.x || 0), 0, 3000);
      node.y = clamp(Number($("workflow-node-y").value || node.y || 0), 0, 1800);
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
    if (action === "canvas-start-task") {
      readAgentForm();
      const payload = {
        umo: $("canvas-umo").value.trim(),
        goal: $("canvas-goal").value,
        completion_conditions: $("canvas-completion").value,
        brief: $("canvas-brief").value,
        heartbeat: $("canvas-start-heartbeat")?.checked || false,
        risk_level: $("canvas-risk-level")?.value || "work",
      };
      const savedAgent = await saveAgent(false);
      payload.agent_id = savedAgent?.agent_id || selectedAgentId;
      await api("/api/task/start", { method: "POST", body: payload });
      setFeedback("已进入任务模式。");
      route = "tasks";
      await load();
    }
    if (action === "start-task") {
      await api("/api/task/start", {
        method: "POST",
        body: {
          umo: $("umo").value.trim(),
          goal: $("goal").value,
          completion_conditions: $("completion").value,
          brief: $("brief").value,
          heartbeat: $("task-start-heartbeat")?.checked || false,
          risk_level: $("task-risk-level")?.value || "work",
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
    if (action === "resolve-approval") {
      const task = selectedTask();
      await api("/api/task/approval", {
        method: "POST",
        body: {
          umo: target.dataset.umo || task?.umo || "",
          approval_id: target.dataset.id,
          approved: target.dataset.approved === "true",
        },
      });
      setFeedback(target.dataset.approved === "true" ? "审批已通过。" : "审批已拒绝。");
      await load();
    }
    if (action === "save-memory") {
      const task = selectedTask();
      await api("/api/memory", {
        method: "POST",
        body: {
          text: $("memory-text").value,
          status: $("memory-status")?.value || "candidate",
          tags: linesToList($("memory-tags")?.value || ""),
          expose_to_normal: ($("memory-expose")?.value || "true") === "true",
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
      currentAgent.isolation_policy.tool_mode = "whitelist";
      render();
    }
    if (action === "enable-visible-tools") {
      currentAgent.isolation_policy.tool_mode = "whitelist";
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
      currentAgent.isolation_policy.tool_mode = "no_external";
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
