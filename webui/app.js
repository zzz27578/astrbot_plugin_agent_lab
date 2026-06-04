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
  "agent_lab_run_parallel_workflow",
];
const GAME_ICON_BASE = "https://raw.githubusercontent.com/Nieobie/Game-Icon-Pack/39dcf2b64947071c762395754ee9a5d3c8975906/svg-v1.0.3";
const GAME_ICONS = {
  menu: `${GAME_ICON_BASE}/1.UI/menu-open.svg`,
  gridAdd: `${GAME_ICON_BASE}/1.UI/grid-add.svg`,
  select: `${GAME_ICON_BASE}/3.Editing%20Tools/select.svg`,
  copy: `${GAME_ICON_BASE}/3.Editing%20Tools/copy.svg`,
  trash: `${GAME_ICON_BASE}/2.Media%20%26%20Technology/trash.svg`,
  undo: `${GAME_ICON_BASE}/3.Editing%20Tools/undo.svg`,
  redo: `${GAME_ICON_BASE}/3.Editing%20Tools/redo.svg`,
  tool: `${GAME_ICON_BASE}/6.Items/tool-kit.svg`,
  book: `${GAME_ICON_BASE}/6.Items/book.svg`,
  memory: `${GAME_ICON_BASE}/2.Media%20%26%20Technology/memory-card.svg`,
};

const WORKFLOW_STAGES = [
  ["entry", "入口", "压缩上下文"],
  ["plan", "计划", "拆解任务"],
  ["execute", "执行", "调用工具"],
  ["guard", "闸门", "审批/人工"],
  ["checkpoint", "快照", "写回状态"],
  ["archive", "出口", "归档回流"],
];

const WORKFLOW_NODE_WIDTH = 300;
const WORKFLOW_NODE_HEIGHT = 168;
const WORKFLOW_LANE_WIDTH = 560;
const WORKFLOW_CANVAS_MIN_WIDTH = 7200;
const WORKFLOW_CANVAS_MIN_HEIGHT = 2800;
const WORKFLOW_CANVAS_MIN_X = -1400;
const WORKFLOW_CANVAS_MAX_X = 12000;
const WORKFLOW_CANVAS_MAX_Y = 8000;
const WORKFLOW_KINDS = [
  "state",
  "tool",
  "guard",
  "human",
  "api",
  "memory",
  "branch",
  "loop",
  "transform",
  "retrieval",
  "subflow",
  "notification",
  "validation",
];
const WORKFLOW_ACTIONS = [
  "confirm_entry",
  "summarize_entry",
  "restore_isolation",
  "plan",
  "route_condition",
  "parallel_branch",
  "run_tools",
  "call_api",
  "transform_context",
  "retrieve_memory",
  "request_approval",
  "wait_user",
  "handoff",
  "validate_output",
  "retry",
  "save_state",
  "save_memory",
  "heartbeat",
  "notify",
  "archive",
  "exit_summary",
  "manual",
];

const WORKFLOW_ACTION_RUNTIME_TYPES = {
  summarize_entry: "entry",
  confirm_entry: "entry",
  restore_isolation: "entry",
  retrieve_memory: "memory",
  save_memory: "memory",
  save_state: "state",
  heartbeat: "state",
  transform_context: "state",
  route_condition: "decision",
  parallel_branch: "parallel",
  run_tools: "tool",
  call_api: "api",
  request_approval: "guard",
  wait_user: "guard",
  handoff: "guard",
  validate_output: "validation",
  retry: "decision",
  notify: "notification",
  archive: "terminal",
  exit_summary: "terminal",
  manual: "react",
};
const WORKFLOW_KIND_RUNTIME_TYPES = {
  state: "state",
  tool: "tool",
  guard: "guard",
  human: "guard",
  api: "api",
  memory: "memory",
  branch: "decision",
  loop: "decision",
  transform: "state",
  retrieval: "memory",
  subflow: "react",
  notification: "notification",
  validation: "validation",
};
const WORKFLOW_EXECUTABLE_ACTIONS = new Set([
  "summarize_entry",
  "confirm_entry",
  "restore_isolation",
  "save_state",
  "heartbeat",
  "transform_context",
  "retrieve_memory",
  "save_memory",
  "parallel_branch",
  "call_api",
  "run_tools",
  "route_condition",
  "retry",
  "validate_output",
  "request_approval",
  "wait_user",
  "handoff",
  "notify",
  "archive",
  "exit_summary",
]);
const WORKFLOW_RUNTIME_LABELS = {
  entry: "入口",
  state: "状态",
  decision: "分支",
  parallel: "并行",
  tool: "工具",
  api: "API",
  memory: "记忆",
  guard: "安全",
  validation: "校验",
  notification: "通知",
  terminal: "出口",
  react: "ReAct",
};
const WORKFLOW_NODE_GROUPS = [
  { id: "entry_context", title: "开始与上下文", hint: "入口命令、确认、摘要和任务隔离。", icon: "book", open: true },
  { id: "plan_route", title: "计划与分支", hint: "拆解任务、选择路线、控制重试。", icon: "gridAdd", open: true },
  { id: "tool_exec", title: "执行工具", hint: "绑定 AstrBot 工具并把结果写入状态。", icon: "tool", open: true },
  { id: "api_external", title: "API 与外部系统", hint: "调用已注册 API，凭证由后端注入。", icon: "gridAdd", open: false },
  { id: "memory_state", title: "记忆与回写", hint: "读取任务记忆，保存进度和完成记录。", icon: "memory", open: true },
  { id: "safety_human", title: "审批与安全", hint: "高风险动作、人工接管、范围锁定。", icon: "select", open: false },
  { id: "validate_exit", title: "校验与出口", hint: "验收、通知、归档和退出回流。", icon: "copy", open: false },
  { id: "parallel_pack", title: "并行工作包", hint: "可拆给并行 Agent 的只读/复核/汇总单元。", icon: "gridAdd", open: false },
];
const WORKFLOW_LIBRARY_GROUP_ALIASES = {
  "入口": "entry_context",
  "输入": "entry_context",
  "隔离": "entry_context",
  "计划": "plan_route",
  "工具": "tool_exec",
  "API": "api_external",
  "记忆": "memory_state",
  "安全": "safety_human",
  "验证": "validate_exit",
  "出口": "validate_exit",
  "并行": "parallel_pack",
};

const WORKFLOW_NODE_TEMPLATES = [
  {
    id: "entry",
    title: "入口识别",
    kind: "state",
    stage: "entry",
    action: "summarize_entry",
    instruction: "识别暗号、命令、关键词或 WebUI 入口，决定是否准备进入任务模式。",
    prompt: "只判断是否进入任务模式：命中暗号、命令、关键词或 WebUI 手动入口时继续；普通聊天不进入。",
  },
  {
    id: "entry_gate",
    title: "开启确认",
    kind: "human",
    stage: "entry",
    action: "confirm_entry",
    instruction: "说明隔离、摘要、状态文件和审批影响，等待用户明确同意。",
    prompt: "向用户说明将开启隔离、上文摘要、任务状态、审批和心跳边界；只有明确同意才进入下一节点。",
  },
  {
    id: "context_bridge",
    title: "上下文压缩",
    kind: "memory",
    stage: "entry",
    action: "summarize_entry",
    instruction: "把普通聊天压缩成 task_brief，只保留目标、约束、授权、风险和接续语气。",
  },
  {
    id: "isolation_gate",
    title: "隔离快照",
    kind: "guard",
    stage: "entry",
    action: "restore_isolation",
    instruction: "进入任务前记录当前会话插件状态，并应用任务模式的严格隔离和工具白名单。",
  },
  {
    id: "memory_recall",
    title: "任务记忆检索",
    kind: "retrieval",
    stage: "plan",
    action: "retrieve_memory",
    instruction: "按标签或关键词读取已暴露的任务记忆，为续写任务补齐背景。",
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
    id: "risk_router",
    title: "风险分流",
    kind: "branch",
    stage: "plan",
    action: "route_condition",
    instruction: "根据低风险、工作风险、高风险把流程送往工具执行、API 调用或审批闸门。",
  },
  {
    id: "parallel_branch",
    title: "并行分支",
    kind: "branch",
    stage: "plan",
    action: "parallel_branch",
    instruction: "把互不依赖的检索、测试、整理任务拆成并行分支，再回收到校验节点。",
  },
  {
    id: "prompt_worker",
    title: "提示词工作包",
    kind: "subflow",
    stage: "execute",
    action: "manual",
    instruction: "给这个分支写入独立提示词，让主 Agent 只合并结构化结果。",
    prompt: "你是一个并行工作包执行者。只处理本节点指定的子任务，输出结论、证据、风险和需要主 Agent 合并的字段。",
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
    id: "transform",
    title: "上下文整理",
    kind: "transform",
    stage: "execute",
    action: "transform_context",
    instruction: "把工具输出整理成结构化观察，过滤噪声，再交给校验和状态写回。",
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
    id: "human_handoff",
    title: "人工接管",
    kind: "human",
    stage: "guard",
    action: "handoff",
    instruction: "当任务需要用户选择、登录、验证码、业务判断或风险授权时暂停并等待输入。",
  },
  {
    id: "validation",
    title: "结果校验",
    kind: "validation",
    stage: "checkpoint",
    action: "validate_output",
    instruction: "对照完成条件检查产出、测试结果和副作用，判断继续、重试或归档。",
  },
  {
    id: "retry_loop",
    title: "重试循环",
    kind: "loop",
    stage: "checkpoint",
    action: "retry",
    instruction: "失败时只重试有限次数，并把原因、调整点和阻塞计数写回任务状态。",
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
    id: "notify",
    title: "完成通知",
    kind: "notification",
    stage: "archive",
    action: "notify",
    instruction: "归档前把完成情况、验证结果、遗留风险和下一步提示反馈给当前会话。",
  },
  {
    id: "exit",
    title: "结束回流",
    kind: "memory",
    stage: "archive",
    action: "exit_summary",
    instruction: "任务完成或取消时归档成果、改动、风险和可回流记忆候选。",
    prompt: "退出时必须输出：完成结果、关键改动、验证证据、遗留风险、恢复状态、可沉淀任务记忆和下次续写入口。",
  },
  {
    id: "command_entry",
    title: "命令/暗号入口",
    kind: "state",
    stage: "entry",
    action: "summarize_entry",
    library_group: "入口",
    instruction: "匹配 /agentlab start、暗号或自定义命令，只产出是否准备进入任务模式的判断。",
  },
  {
    id: "keyword_entry",
    title: "关键词入口",
    kind: "branch",
    stage: "entry",
    action: "route_condition",
    library_group: "入口",
    instruction: "按排查、部署、写插件、整理资料等关键词判断是否进入任务模式，避免普通聊天误触发。",
  },
  {
    id: "manual_webui_entry",
    title: "WebUI 手动入口",
    kind: "human",
    stage: "entry",
    action: "confirm_entry",
    library_group: "入口",
    instruction: "从控制台创建任务时锁定目标、完成条件、风险等级和是否立即开心跳。",
  },
  {
    id: "document_source",
    title: "文档/路径输入",
    kind: "retrieval",
    stage: "plan",
    action: "retrieve_memory",
    library_group: "输入",
    instruction: "把文件路径、文档 URL 或上游变量作为工作流输入，供后续工具、API 或记忆节点读取。",
    input_variable: "task.input",
    output_variable: "document.context",
  },
  {
    id: "scope_lock",
    title: "授权范围锁定",
    kind: "guard",
    stage: "entry",
    action: "restore_isolation",
    library_group: "隔离",
    instruction: "进入任务前写清允许读写的目录、外部系统、插件和工具白名单，超出范围必须重新确认。",
  },
  {
    id: "memory_filter",
    title: "记忆过滤器",
    kind: "memory",
    stage: "entry",
    action: "summarize_entry",
    library_group: "记忆",
    instruction: "把普通会话记忆压缩成任务 brief，只带入稳定事实、约束、已授权内容和用户偏好。",
  },
  {
    id: "memory_read",
    title: "任务记忆读取",
    kind: "retrieval",
    stage: "plan",
    action: "retrieve_memory",
    library_group: "记忆",
    instruction: "按标签、source_task_id 或归档路径读取任务记忆，作为续写任务的受控上下文。",
    input_variable: "memory.tags",
    output_variable: "memory.context",
  },
  {
    id: "memory_expose",
    title: "记忆标签暴露",
    kind: "memory",
    stage: "checkpoint",
    action: "save_memory",
    library_group: "记忆",
    instruction: "把可复用成果写成带标签的任务记忆，让普通模式或下一次任务能按标签读取。",
    tags: ["任务", "续写"],
    output_variable: "task_memory.summary",
  },
  {
    id: "memory_rollback",
    title: "回档续写入口",
    kind: "memory",
    stage: "entry",
    action: "summarize_entry",
    library_group: "记忆",
    instruction: "根据归档任务、任务记忆或外部文档地址生成续写 brief，并要求先确认新旧目标差异。",
    input_variable: "archive.task_id",
    output_variable: "resume.brief",
  },
  {
    id: "todo_split",
    title: "工作包拆分",
    kind: "transform",
    stage: "plan",
    action: "transform_context",
    library_group: "计划",
    instruction: "把计划拆成互不依赖、可验收、可回滚的小工作包，再决定串行或并行。",
  },
  {
    id: "parallel_research_worker",
    title: "并行资料/代码阅读",
    kind: "subflow",
    stage: "execute",
    action: "manual",
    library_group: "并行",
    instruction: "只读检索资料、文档或代码路径，输出证据、结论、风险和主 Agent 需要合并的字段。",
    prompt: "你是只读并行研究工作包。不要写入文件或外部系统；输出：结论、证据、风险、建议下一步。",
    parallel_group: "default",
  },
  {
    id: "parallel_verify_worker",
    title: "并行验收复核",
    kind: "subflow",
    stage: "execute",
    action: "manual",
    library_group: "并行",
    instruction: "独立检查完成条件、测试证据、边界情况和可能遗漏，回传结构化复核意见。",
    prompt: "你是并行验收复核工作包。只核对证据强度和遗漏项；输出：通过项、风险项、阻塞项、建议。",
    parallel_group: "default",
  },
  {
    id: "browser_qa",
    title: "浏览器 QA",
    kind: "tool",
    stage: "execute",
    action: "run_tools",
    library_group: "工具",
    instruction: "用浏览器或截图验证本地 WebUI 的布局、交互、移动端和关键流程，结果写回 task_state。",
  },
  {
    id: "file_patch",
    title: "文件改动单元",
    kind: "tool",
    stage: "execute",
    action: "run_tools",
    library_group: "工具",
    instruction: "只改一个边界清晰的代码或文档单元，改动前后记录关键文件、风险和验证方式。",
  },
  {
    id: "shell_test",
    title: "命令验证",
    kind: "tool",
    stage: "checkpoint",
    action: "run_tools",
    library_group: "验证",
    instruction: "运行格式检查、单测、烟测或项目命令，把命令、结果和失败原因写回任务状态。",
  },
  {
    id: "api_payload_builder",
    title: "API 参数整理",
    kind: "transform",
    stage: "execute",
    action: "transform_context",
    library_group: "API",
    instruction: "在调用外部 API 前整理参数、幂等键、敏感字段和成功判定，避免把密钥写进提示词。",
  },
  {
    id: "api_write_guard",
    title: "API 写入审批",
    kind: "guard",
    stage: "guard",
    action: "request_approval",
    library_group: "API",
    instruction: "API 会写入外部系统、发消息、产生费用或读取敏感数据时，先请求用户明确审批。",
  },
  {
    id: "merge_results",
    title: "并行结果汇总",
    kind: "transform",
    stage: "checkpoint",
    action: "transform_context",
    library_group: "并行",
    instruction: "合并并行工作包结果，标注冲突、证据强度、未验证项和主 Agent 的最终决策。",
  },
  {
    id: "acceptance_check",
    title: "验收清单",
    kind: "validation",
    stage: "checkpoint",
    action: "validate_output",
    library_group: "验证",
    instruction: "对照完成条件逐项确认，明确已完成、未完成、需用户验收和残留风险。",
  },
  {
    id: "rollback_plan",
    title: "回滚预案",
    kind: "guard",
    stage: "guard",
    action: "request_approval",
    library_group: "安全",
    instruction: "部署、批量覆盖或破坏性动作前写清影响范围、回滚步骤和停止条件。",
  },
  {
    id: "cancel_exit",
    title: "取消退出",
    kind: "memory",
    stage: "archive",
    action: "exit_summary",
    library_group: "出口",
    instruction: "用户取消或任务终止时，归档已做事项、未完成原因、恢复状态和可续写入口。",
  },
];

const sections = [
  ["dashboard", "仪表盘与列表", "看大盘"],
  ["canvas", "可视化编排画布", "捏任务模式"],
  ["tasks", "任务与记忆控制台", "管状态"],
  ["monitor", "实例与心跳监控", "搞运维"],
  ["integrations", "插件与集成", "装工具"],
];

sections[1] = ["canvas", "任务模式设置", "定规则"];
sections.splice(2, 0, ["workflow", "工作流画布", "拼流程"]);
sections.splice(3, 0, ["memory", "完成记录", "查历史"]);

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
let selectedMemoryId = "";
let workflowDrag = null;
let workflowPan = null;
let workflowConnection = null;
let workflowPendingPort = null;
let workflowZoom = 1;
let workflowPanX = 0;
let workflowPanY = 0;
let workflowCheckReport = null;
let workflowDryRunReport = null;
let workflowToolboxOpen = true;
let workflowInspectorOpen = false;
let workflowNavCollapsed = true;
let workflowContextMenu = null;
let workflowSuppressClick = false;
let workflowReportOpen = false;
let workflowReportMode = "check";
let workflowDraggedMaterial = null;
let workflowMinimapPan = null;
let workflowRibbonOpen = false;
let workflowViewportInitialized = false;
let workflowInspectorScrollTop = 0;
let workflowToolboxScrollTop = 0;
let workflowInspectorFocusScrollTop = 0;
let workflowToastTimer = null;
let workflowMaterialDraft = null;
let workflowMaterialFilter = "";
let workflowToolboxOpenGroups = new Set(["entry_context"]);
let workflowMinimapWidth = 160;
let workflowMinimapHeight = 112;
let workflowMinimapResize = null;
let workflowSelectionMode = false;
let workflowSelectionDrag = null;
let workflowSelectedNodeIds = new Set();
let workflowHistoryPast = [];
let workflowHistoryFuture = [];

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

function iconImg(name, label = "") {
  const src = GAME_ICONS[name];
  if (!src) return "";
  return `<img class="game-icon" src="${esc(src)}" alt="${esc(label)}" loading="lazy" />`;
}

function workflowMaterialIcon(kind, refType = "") {
  if (refType === "plugin" || kind === "subflow") return "gridAdd";
  if (refType === "tool" || kind === "tool") return "tool";
  if (kind === "memory" || kind === "retrieval") return "memory";
  return "book";
}

function workflowRuntimeType(item = {}) {
  const explicit = String(item.runtime_type || "").trim();
  if (explicit && WORKFLOW_RUNTIME_LABELS[explicit]) return explicit;
  const action = String(item.action || "").trim();
  if (WORKFLOW_ACTION_RUNTIME_TYPES[action]) return WORKFLOW_ACTION_RUNTIME_TYPES[action];
  const kind = String(item.kind || "").trim();
  if (WORKFLOW_KIND_RUNTIME_TYPES[kind]) return WORKFLOW_KIND_RUNTIME_TYPES[kind];
  return "react";
}

function workflowRuntimeLabel(item = {}) {
  return WORKFLOW_RUNTIME_LABELS[workflowRuntimeType(item)] || "ReAct";
}

function workflowNodeRuntimeInfo(item = {}) {
  const report = workflowCheckReport?.node_runtime?.[item.id] || null;
  if (report) return report;
  const action = String(item.action || "").trim();
  const runtimeType = workflowRuntimeType(item);
  const hasExecutor = WORKFLOW_EXECUTABLE_ACTIONS.has(action);
  return {
    runtime_type: runtimeType,
    action,
    has_executor: hasExecutor,
    react_handoff: !hasExecutor || action === "manual" || action === "plan" || ["react", "terminal"].includes(runtimeType),
  };
}

function workflowNodeBindingHint(item = {}) {
  const action = String(item.action || "").trim();
  const kind = String(item.kind || "").trim();
  if ((action === "call_api" || kind === "api") && !String(item.api_id || item.ref_id || "").trim()) return "需要先绑定已注册 API";
  if ((action === "run_tools" || kind === "tool") && !String(item.tool_name || item.ref_id || "").trim()) return "需要先绑定 AstrBot 工具";
  if ((action === "run_tools" || kind === "tool") && !String(item.tool_args || item.arguments || item.params || item.input_variable || "").trim()) return "未填参数时会交给 ReAct 调用";
  if (kind === "subflow" || action === "manual") return "由 ReAct 判断和执行";
  return "";
}

function workflowNodeExecutorState(item = {}) {
  const info = workflowNodeRuntimeInfo(item);
  const binding = workflowNodeBindingHint(item);
  if (binding && binding.startsWith("需要")) return { label: "需配置", tone: "warn", hint: binding };
  if (binding) return { label: "半自动", tone: "warn", hint: binding };
  if (info.has_executor && !info.react_handoff) return { label: "可执行", tone: "ok", hint: "后端 executor 可直接推进这个节点" };
  if (info.has_executor && info.react_handoff) return { label: "半自动", tone: "warn", hint: "有 executor，但这里仍可能需要 ReAct 收束" };
  return { label: "ReAct", tone: "react", hint: "需要模型按节点说明判断下一步" };
}

function workflowNodeGroupKey(item = {}) {
  const group = String(item.library_group || "").trim();
  if (WORKFLOW_LIBRARY_GROUP_ALIASES[group]) return WORKFLOW_LIBRARY_GROUP_ALIASES[group];
  const action = String(item.action || "").trim();
  const kind = String(item.kind || "").trim();
  const runtimeType = workflowRuntimeType(item);
  const stage = String(item.stage || "").trim();
  if (["entry"].includes(runtimeType) || stage === "entry") return "entry_context";
  if (["parallel"].includes(runtimeType) || action === "parallel_branch") return "parallel_pack";
  if (["tool"].includes(runtimeType) || kind === "tool") return "tool_exec";
  if (["api"].includes(runtimeType) || kind === "api") return "api_external";
  if (["memory"].includes(runtimeType) || ["memory", "retrieval"].includes(kind)) return "memory_state";
  if (["guard"].includes(runtimeType) || ["guard", "human"].includes(kind)) return "safety_human";
  if (["validation", "notification", "terminal"].includes(runtimeType) || stage === "archive") return "validate_exit";
  if (["decision"].includes(runtimeType) || ["branch", "loop"].includes(kind) || stage === "plan") return "plan_route";
  return "plan_route";
}

function workflowNodeGroupConfig(key) {
  return WORKFLOW_NODE_GROUPS.find((item) => item.id === key) || WORKFLOW_NODE_GROUPS[1];
}

function workflowMaterialHint(item = {}) {
  const binding = workflowNodeBindingHint(item);
  if (binding) return binding;
  return item.config_hint || item.instruction || item.description || "拖到画布，或点“应用节点”添加。";
}

function workflowMaterialMeta(item = {}) {
  const stateInfo = workflowNodeExecutorState(item);
  return [
    `${stateInfo.label}`,
    `${workflowRuntimeLabel(item)}节点`,
    item.output_variable ? `输出 ${item.output_variable}` : "",
    item.input_variable ? `输入 ${item.input_variable}` : "",
  ].filter(Boolean);
}

function workflowNodeParamsJson(item = {}) {
  const raw = item.params ?? item.tool_args ?? item.arguments ?? item.api_payload ?? item.payload ?? "";
  if (raw && typeof raw === "object") return JSON.stringify(raw, null, 2);
  return String(raw || "");
}

function token() {
  return sessionStorage.getItem("agent_lab_token") || $("token").value.trim();
}

function setFeedback(message, tone = "normal") {
  const feedback = $("feedback");
  if (feedback) {
    feedback.textContent = message;
    feedback.dataset.tone = tone;
  }
  showToast(message, tone);
}

function showToast(message, tone = "normal") {
  if (!message) return;
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    document.body.appendChild(stack);
  }
  const toast = document.createElement("div");
  toast.className = `toast ${tone === "error" ? "error" : tone === "warn" ? "warn" : "ok"}`;
  toast.textContent = message;
  stack.appendChild(toast);
  if (workflowToastTimer) clearTimeout(workflowToastTimer);
  workflowToastTimer = setTimeout(() => {
    Array.from(stack.children).forEach((item) => item.classList.add("leaving"));
    setTimeout(() => stack.replaceChildren(), 220);
  }, 2600);
}

function workflowSnapshot() {
  ensureWorkflow();
  return clone({
    nodes: currentAgent.workflow_nodes || [],
    edges: currentAgent.workflow_edges || [],
    selected: selectedWorkflowNodeId,
  });
}

function pushWorkflowHistory() {
  if (!currentAgent) return;
  workflowHistoryPast.push(workflowSnapshot());
  if (workflowHistoryPast.length > 60) workflowHistoryPast.shift();
  workflowHistoryFuture = [];
}

function restoreWorkflowSnapshot(snapshot) {
  if (!snapshot) return;
  currentAgent.workflow_nodes = clone(snapshot.nodes || []);
  currentAgent.workflow_edges = clone(snapshot.edges || []);
  selectedWorkflowNodeId = snapshot.selected || currentAgent.workflow_nodes[0]?.id || "";
  workflowCheckReport = null;
  workflowDryRunReport = null;
}

function undoWorkflow() {
  if (!workflowHistoryPast.length) return false;
  workflowHistoryFuture.push(workflowSnapshot());
  restoreWorkflowSnapshot(workflowHistoryPast.pop());
  return true;
}

function redoWorkflow() {
  if (!workflowHistoryFuture.length) return false;
  workflowHistoryPast.push(workflowSnapshot());
  restoreWorkflowSnapshot(workflowHistoryFuture.pop());
  return true;
}

function rememberWorkflowPanelScroll() {
  workflowInspectorScrollTop = document.querySelector(".workflow-inspector-drawer .drawer-scroll")?.scrollTop || workflowInspectorScrollTop || 0;
  workflowToolboxScrollTop = document.querySelector(".workflow-tool-drawer .drawer-scroll")?.scrollTop || workflowToolboxScrollTop || 0;
}

function restoreWorkflowPanelScroll() {
  requestAnimationFrame(() => {
    const inspector = document.querySelector(".workflow-inspector-drawer .drawer-scroll");
    if (inspector) inspector.scrollTop = workflowInspectorScrollTop || 0;
    const toolbox = document.querySelector(".workflow-tool-drawer .drawer-scroll");
    if (toolbox) toolbox.scrollTop = workflowToolboxScrollTop || 0;
  });
}

function renderWorkflowStable() {
  rememberWorkflowPanelScroll();
  render();
  if (route === "workflow") restoreWorkflowPanelScroll();
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
    manual: "只手动开启",
    confirm: "先问我确认",
    smart: "按关键词判断",
    always: "尽量自动接任务",
  }[mode] || mode;
}

function memoryModeLabel(mode) {
  return {
    inherit: "沿用聊天上下文",
    task_filtered: "只读相关任务记录",
    strict: "任务内单独记忆",
  }[mode] || mode;
}

function approvalModeLabel(mode) {
  return {
    observe: "只提醒不拦截",
    work: "重要操作先问我",
    high_risk_review: "危险操作必须确认",
    delegated: "按规则自动处理",
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
    branch: "分支",
    loop: "循环",
    transform: "整理",
    retrieval: "检索",
    subflow: "子流程",
    notification: "通知",
    validation: "校验",
  }[kind] || kind;
}

function workflowStageLabel(stage) {
  return Object.fromEntries(WORKFLOW_STAGES.map(([id, title]) => [id, title]))[stage] || "计划";
}

function workflowActionLabel(action) {
  return {
    summarize_entry: "入口摘要",
    confirm_entry: "开启确认",
    restore_isolation: "记录进入前状态",
    plan: "计划拆解",
    route_condition: "条件分流",
    parallel_branch: "并行分支",
    run_tools: "工具执行",
    call_api: "API 调用",
    transform_context: "上下文整理",
    retrieve_memory: "记忆检索",
    request_approval: "请求审批",
    wait_user: "等待用户",
    handoff: "人工接管",
    validate_output: "结果校验",
    retry: "有限重试",
    save_state: "记录进度",
    save_memory: "保存任务记录",
    heartbeat: "心跳续跑",
    notify: "完成通知",
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

function renderWorkflowFilterInput(action, value) {
  rememberWorkflowPanelScroll();
  render();
  restoreWorkflowPanelScroll();
  requestAnimationFrame(() => {
    const input = document.querySelector(`[data-action="${action}"]`);
    if (!input) return;
    input.focus();
    const end = String(value || "").length;
    if (typeof input.setSelectionRange === "function") input.setSelectionRange(end, end);
  });
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
      x: 70,
      y: 260,
    },
    {
      id: "entry_gate",
      title: "开启确认",
      kind: "human",
      stage: "entry",
      action: "confirm_entry",
      description: "确认是否真的进入专业任务模式。",
      instruction: "需要确认时，先说明将隔离插件、压缩上下文、创建 task_state，并等待用户明确同意。",
      x: 390,
      y: 420,
    },
    {
      id: "context_bridge",
      title: "上文压缩",
      kind: "memory",
      stage: "entry",
      action: "summarize_entry",
      description: "把普通聊天上文压成任务 brief。",
      instruction: "只保留目标、约束、授权、风险和接续语气；日常记忆不直接灌入专业模式。",
      x: 390,
      y: 100,
    },
    {
      id: "isolation_gate",
      title: "隔离快照",
      kind: "guard",
      stage: "entry",
      action: "restore_isolation",
      description: "应用严格隔离并记录恢复点。",
      instruction: "进入任务前记录当前会话插件状态，只保留 Agent Lab、保留插件和用户允许的插件；退出时恢复快照。",
      x: 710,
      y: 260,
    },
    {
      id: "memory_recall",
      title: "任务记忆检索",
      kind: "retrieval",
      stage: "plan",
      action: "retrieve_memory",
      description: "读取已暴露的任务记忆。",
      instruction: "按标签、关键词或 source_task_id 读取候选任务记忆，只带入与当前目标稳定相关的信息。",
      x: 1040,
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
      x: 1040,
      y: 300,
    },
    {
      id: "risk_router",
      title: "风险分流",
      kind: "branch",
      stage: "plan",
      action: "route_condition",
      description: "按风险和任务性质分支。",
      instruction: "低风险直接执行；高风险进入审批；需要外部系统时走 API；需要用户判断时交给人工接管。",
      x: 1360,
      y: 300,
    },
    {
      id: "parallel_branch",
      title: "并行分支",
      kind: "branch",
      stage: "plan",
      action: "parallel_branch",
      description: "拆分互不依赖的小任务。",
      instruction: "把资料检索、代码阅读、测试准备等互不依赖的步骤拆开推进，再统一进入校验。",
      x: 1360,
      y: 80,
    },
    {
      id: "parallel_research",
      title: "并行检索包",
      kind: "subflow",
      stage: "execute",
      action: "manual",
      description: "只读检索或代码阅读工作包。",
      instruction: "把资料检索、接口查阅或代码阅读这类只读子任务拆出去，输出证据摘要和风险。",
      prompt: "你是并行只读检索工作包。只收集证据和结论，不做写入动作；输出：发现、证据来源、风险、建议下一步。",
      parallel_group: "default",
      x: 1680,
      y: 0,
    },
    {
      id: "parallel_verify",
      title: "并行验证包",
      kind: "subflow",
      stage: "execute",
      action: "manual",
      description: "验收条件和测试准备工作包。",
      instruction: "把测试准备、验收条件核对或结果复核拆成独立工作包，再回收到上下文整理。",
      prompt: "你是并行验证工作包。只围绕完成条件检查证据强度；输出：已验证、未验证、阻塞、需要主 Agent 决策的点。",
      parallel_group: "default",
      x: 1680,
      y: 580,
    },
    {
      id: "execute",
      title: "工具执行",
      kind: "tool",
      stage: "execute",
      action: "run_tools",
      description: "调用白名单工具或自定义 API。",
      instruction: "只使用 AgentSpec 已启用的工具，关键输出必须写回状态。",
      x: 1680,
      y: 160,
    },
    {
      id: "api_call",
      title: "API 调用",
      kind: "api",
      stage: "execute",
      action: "call_api",
      description: "调用注册 API 或外部服务。",
      instruction: "使用 agent_lab_call_custom_api 调用已登记 API，凭证由 Agent Lab 注入，不写入任务记忆。",
      x: 1680,
      y: 420,
    },
    {
      id: "transform",
      title: "上下文整理",
      kind: "transform",
      stage: "execute",
      action: "transform_context",
      description: "清洗工具输出。",
      instruction: "把工具/API 返回整理成结构化观察，压缩噪声，保留证据、失败原因和下一步所需字段。",
      x: 2000,
      y: 260,
    },
    {
      id: "approval",
      title: "审批闸门",
      kind: "guard",
      stage: "guard",
      action: "request_approval",
      description: "危险动作前请求用户确认。",
      instruction: "删除、部署、密钥、重启、全局配置和破坏性数据库操作前必须先说明影响并等待审批。",
      x: 1680,
      y: 660,
    },
    {
      id: "human_handoff",
      title: "人工接管",
      kind: "human",
      stage: "guard",
      action: "handoff",
      description: "等待用户选择或授权。",
      instruction: "遇到登录、验证码、业务判断、未授权范围或连续阻塞时暂停，给出清晰选项等待用户输入。",
      x: 2000,
      y: 660,
    },
    {
      id: "validation",
      title: "结果校验",
      kind: "validation",
      stage: "checkpoint",
      action: "validate_output",
      description: "检查是否满足完成条件。",
      instruction: "对照完成条件、测试结果和副作用判断是否完成；失败时说明原因并进入有限重试。",
      x: 2320,
      y: 180,
    },
    {
      id: "retry_loop",
      title: "重试循环",
      kind: "loop",
      stage: "checkpoint",
      action: "retry",
      description: "失败后有限重试。",
      instruction: "每次重试都写清调整点和观察结果；同一阻塞重复三次后停止并请求用户介入。",
      x: 2320,
      y: 460,
    },
    {
      id: "checkpoint",
      title: "状态快照",
      kind: "state",
      stage: "checkpoint",
      action: "save_state",
      description: "把本轮结果写入 task_state。",
      instruction: "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。",
      x: 2640,
      y: 180,
    },
    {
      id: "task_memory",
      title: "任务记忆",
      kind: "memory",
      stage: "checkpoint",
      action: "save_memory",
      description: "独立记录任务时间线和关键成果。",
      instruction: "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆；以标签暴露给普通模式读取。",
      x: 2960,
      y: 120,
    },
    {
      id: "heartbeat",
      title: "心跳续跑",
      kind: "guard",
      stage: "guard",
      action: "heartbeat",
      description: "长任务定时唤醒。",
      instruction: "心跳醒来先读 task_state，再推进一小步；同一阻塞重复三次则暂停求助。",
      x: 2960,
      y: 420,
    },
    {
      id: "notify",
      title: "完成通知",
      kind: "notification",
      stage: "archive",
      action: "notify",
      description: "向当前会话反馈成果。",
      instruction: "在退出前向用户说明完成情况、验证结果、遗留风险和下次续写入口。",
      x: 3280,
      y: 180,
    },
    {
      id: "archive",
      title: "结束回流",
      kind: "memory",
      stage: "archive",
      action: "exit_summary",
      description: "完成或取消后归档。",
      instruction: "只有完成、取消或用户要求退出时结束；输出成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。",
      x: 3600,
      y: 180,
    },
  ];
}

function defaultWorkflowEdges() {
  return [
    { from: "entry", to: "entry_gate" },
    { from: "entry_gate", to: "context_bridge" },
    { from: "context_bridge", to: "isolation_gate" },
    { from: "isolation_gate", to: "memory_recall" },
    { from: "memory_recall", to: "plan" },
    { from: "plan", to: "risk_router" },
    { from: "plan", to: "parallel_branch" },
    { from: "parallel_branch", to: "parallel_research" },
    { from: "parallel_branch", to: "parallel_verify" },
    { from: "parallel_branch", to: "execute" },
    { from: "risk_router", to: "execute" },
    { from: "risk_router", to: "api_call" },
    { from: "risk_router", to: "approval" },
    { from: "approval", to: "human_handoff" },
    { from: "approval", to: "execute" },
    { from: "human_handoff", to: "plan" },
    { from: "execute", to: "transform" },
    { from: "api_call", to: "transform" },
    { from: "parallel_research", to: "transform" },
    { from: "parallel_verify", to: "transform" },
    { from: "transform", to: "validation" },
    { from: "validation", to: "checkpoint" },
    { from: "validation", to: "retry_loop" },
    { from: "retry_loop", to: "execute" },
    { from: "checkpoint", to: "task_memory" },
    { from: "checkpoint", to: "heartbeat" },
    { from: "heartbeat", to: "plan" },
    { from: "task_memory", to: "notify" },
    { from: "notify", to: "archive" },
  ];
}

function workflowTemplate(id) {
  if (id === "emergency") {
    return {
      nodes: [
        { id: "entry", title: "紧急入口", kind: "state", stage: "entry", action: "summarize_entry", description: "快速压缩当前事故背景", instruction: "只提取故障现象、影响范围、已试步骤、不可触碰边界和回滚要求。", x: 70, y: 220 },
        { id: "confirm", title: "风险确认", kind: "human", stage: "entry", action: "confirm_entry", description: "确认进入紧急任务模式", instruction: "说明会优先排障、保留审批闸门、记录每个改动点，等待用户确认。", x: 410, y: 220 },
        { id: "triage", title: "分诊计划", kind: "branch", stage: "plan", action: "route_condition", description: "按影响和风险分流", instruction: "先判定是否只读排查、是否需要写入修复、是否需要部署/重启。", x: 750, y: 220 },
        { id: "readonly_check", title: "只读排查", kind: "tool", stage: "execute", action: "run_tools", description: "日志、状态、配置只读检查", instruction: "优先读取日志、状态和配置，避免写入。", x: 1090, y: 90 },
        { id: "approval", title: "高危审批", kind: "guard", stage: "guard", action: "request_approval", description: "部署、重启、删除前审批", instruction: "任何部署、重启、批量覆盖、删除或全局配置修改前都要说明影响和回滚方案。", x: 1090, y: 360 },
        { id: "fix", title: "有限修复", kind: "tool", stage: "execute", action: "run_tools", description: "只做一个可回滚修复单元", instruction: "每次只修改一个有限单元，立刻验证并写回状态。", x: 1430, y: 220 },
        { id: "validation", title: "恢复验证", kind: "validation", stage: "checkpoint", action: "validate_output", description: "确认服务恢复和副作用", instruction: "检查测试、日志、错误率或用户指定验收条件，失败则进入重试/回滚。", x: 1770, y: 220 },
        { id: "archive", title: "事故归档", kind: "memory", stage: "archive", action: "exit_summary", description: "沉淀事故、修复和风险", instruction: "归档影响范围、根因线索、实际改动、验证结果、遗留风险和下次接手提示。", x: 2110, y: 220 },
      ],
      edges: [
        { from: "entry", to: "confirm" },
        { from: "confirm", to: "triage" },
        { from: "triage", to: "readonly_check" },
        { from: "triage", to: "approval" },
        { from: "approval", to: "fix" },
        { from: "readonly_check", to: "validation" },
        { from: "fix", to: "validation" },
        { from: "validation", to: "archive" },
      ],
    };
  }
  if (id === "parallel_agent") {
    return {
      nodes: [
        { id: "entry", title: "协作入口", kind: "state", stage: "entry", action: "summarize_entry", description: "压缩目标与分工边界", instruction: "提取目标、约束、可并行子任务和每个子 Agent 的权限边界。", x: 70, y: 220 },
        { id: "plan", title: "主计划", kind: "state", stage: "plan", action: "plan", description: "拆出可并行工作包", instruction: "只把互不依赖的工作分出去，保留主 Agent 的最终集成和验收责任。", x: 410, y: 220 },
        { id: "agent_branch", title: "并行 Agent", kind: "branch", stage: "plan", action: "parallel_branch", description: "并行提示词/API/工具分支", instruction: "每个分支可以绑定提示词、API、插件或工具，要求输出结构化结论。", x: 750, y: 220 },
        { id: "api_worker", title: "API 子任务", kind: "api", stage: "execute", action: "call_api", description: "外部服务或模型 API", instruction: "调用预注册 API，返回摘要和可验证证据，不暴露凭证。", x: 1090, y: 80 },
        { id: "prompt_worker", title: "提示词子任务", kind: "subflow", stage: "execute", action: "manual", description: "独立提示词工作包", instruction: "按节点提示词完成一个边界清晰的子任务，并返回结果、风险和证据。", prompt: "你是并行工作包执行者。只处理分配给你的子任务，输出：结论、证据、风险、需要主 Agent 合并的字段。", parallel_group: "default", x: 1090, y: 280 },
        { id: "tool_worker", title: "工具子任务", kind: "tool", stage: "execute", action: "run_tools", description: "插件/工具工作包", instruction: "只调用本分支允许的工具，关键输出写入任务状态。", x: 1090, y: 480 },
        { id: "merge", title: "结果汇总", kind: "transform", stage: "checkpoint", action: "transform_context", description: "合并并去重并行结果", instruction: "合并子任务结果，标注冲突、证据强度和待验证项。", x: 1430, y: 280 },
        { id: "validation", title: "集成验收", kind: "validation", stage: "checkpoint", action: "validate_output", description: "主 Agent 统一验收", instruction: "主 Agent 对照完成条件验收，不让子 Agent 直接决定完成。", x: 1770, y: 280 },
        { id: "archive", title: "协作归档", kind: "memory", stage: "archive", action: "exit_summary", description: "归档分工、成果和续写入口", instruction: "保存各分支成果、关键决策、遗留风险和下次续写入口。", x: 2110, y: 280 },
      ],
      edges: [
        { from: "entry", to: "plan" },
        { from: "plan", to: "agent_branch" },
        { from: "agent_branch", to: "api_worker" },
        { from: "agent_branch", to: "prompt_worker" },
        { from: "agent_branch", to: "tool_worker" },
        { from: "api_worker", to: "merge" },
        { from: "prompt_worker", to: "merge" },
        { from: "tool_worker", to: "merge" },
        { from: "merge", to: "validation" },
        { from: "validation", to: "archive" },
      ],
    };
  }
  if (id === "api_review") {
    return {
      nodes: [
        { id: "entry", title: "入口压缩", kind: "state", stage: "entry", action: "summarize_entry", description: "整理目标与调用约束", instruction: "把用户目标、接口用途、参数边界和授权范围压缩成 task_brief。", x: 70, y: 260 },
        { id: "plan", title: "调用计划", kind: "state", stage: "plan", action: "plan", description: "明确 API 调用方案", instruction: "确认要调用的注册 API、参数、风险级别和成功判定。", x: 410, y: 220 },
        { id: "approval", title: "敏感审批", kind: "human", stage: "guard", action: "request_approval", description: "涉及外部写入或敏感数据时审批", instruction: "如果 API 会写入外部系统、发送消息、产生费用或读取敏感数据，先请求用户审批。", x: 750, y: 430 },
        { id: "api_call", title: "调用 API", kind: "api", stage: "execute", action: "call_api", description: "执行已注册自定义 API", instruction: "使用 agent_lab_call_custom_api 调用已注册 API，隐藏凭证，只保留必要结果摘要。", x: 750, y: 170 },
        { id: "validation", title: "结果校验", kind: "validation", stage: "checkpoint", action: "validate_output", description: "检查结果并写回状态", instruction: "核对 API 返回是否满足完成条件；写回观察、进度和下一步。", x: 1090, y: 220 },
        { id: "archive", title: "出口归档", kind: "memory", stage: "archive", action: "archive", description: "沉淀可复用信息", instruction: "完成后只归档稳定有用的事实，避免保存密钥、一次性 token 或临时响应。", x: 1430, y: 220 },
      ],
      edges: [
        { from: "entry", to: "plan" },
        { from: "plan", to: "approval" },
        { from: "approval", to: "api_call" },
        { from: "plan", to: "api_call" },
        { from: "api_call", to: "validation" },
        { from: "validation", to: "archive" },
      ],
    };
  }
  if (id === "code_task") {
    return {
      nodes: [
        { id: "entry", title: "开发入口", kind: "state", stage: "entry", action: "summarize_entry", description: "压缩需求和限制", instruction: "提取目标、验收条件、禁止触碰范围、运行环境和用户最新要求。", x: 80, y: 260 },
        { id: "confirm", title: "范围确认", kind: "human", stage: "entry", action: "confirm_entry", description: "确认进入代码任务模式", instruction: "说明会隔离普通插件、只使用白名单工具、关键改动会记录到任务记忆。", x: 500, y: 260 },
        { id: "plan", title: "改动计划", kind: "state", stage: "plan", action: "plan", description: "拆分文件和验证步骤", instruction: "先读代码再定改动；计划必须包含目标文件、风险点和验证命令。", x: 920, y: 260 },
        { id: "read", title: "代码阅读", kind: "subflow", stage: "execute", action: "manual", description: "只读理解代码路径", instruction: "读取相关文件、入口和测试，不做写入；输出改动边界和局部设计。", prompt: "你是代码阅读工作包。只读不写；输出：涉及文件、现有模式、风险、建议修改点。", parallel_group: "code", x: 1340, y: 90 },
        { id: "patch", title: "文件改动", kind: "tool", stage: "execute", action: "run_tools", description: "有限代码修改", instruction: "只做计划内最小改动，避免无关重构，关键改动写回 task_state。", x: 1340, y: 300 },
        { id: "qa", title: "验证命令", kind: "tool", stage: "checkpoint", action: "run_tools", description: "运行语法/测试/烟测", instruction: "运行项目可用验证；失败时记录命令、错误、判断和下一步。", x: 1760, y: 300 },
        { id: "review", title: "结果校验", kind: "validation", stage: "checkpoint", action: "validate_output", description: "核对需求和副作用", instruction: "对照验收条件、测试结果和 diff 风险，决定继续、重试或归档。", x: 2180, y: 300 },
        { id: "memory", title: "改动记忆", kind: "memory", stage: "checkpoint", action: "save_memory", description: "记录改动和续写点", instruction: "保存文件变更、关键决策、验证命令、遗留风险和下次接手提示。", x: 2600, y: 300 },
        { id: "archive", title: "交付退出", kind: "memory", stage: "archive", action: "exit_summary", description: "总结并恢复隔离", instruction: "输出交付内容、验证结果、未完成项和可回流记忆，然后退出任务模式。", x: 3020, y: 300 },
      ],
      edges: [
        { from: "entry", to: "confirm" },
        { from: "confirm", to: "plan" },
        { from: "plan", to: "read" },
        { from: "plan", to: "patch" },
        { from: "read", to: "patch" },
        { from: "patch", to: "qa" },
        { from: "qa", to: "review" },
        { from: "review", to: "memory" },
        { from: "memory", to: "archive" },
      ],
    };
  }
  if (id === "memory_loop") {
    return {
      nodes: [
        { id: "entry", title: "续写入口", kind: "state", stage: "entry", action: "summarize_entry", description: "识别续写目标", instruction: "识别用户要续写的任务、标签或 source_task_id，压缩当前目标。", x: 80, y: 260 },
        { id: "recall", title: "记忆召回", kind: "retrieval", stage: "plan", action: "retrieve_memory", description: "读取任务记忆", instruction: "按标签读取候选记忆，区分稳定事实、候选判断和过期信息。", x: 500, y: 260 },
        { id: "plan", title: "续写计划", kind: "state", stage: "plan", action: "plan", description: "确认接续方案", instruction: "把召回记忆转成新的完成条件、边界和下一步计划，等待必要确认。", x: 920, y: 260 },
        { id: "execute", title: "续写执行", kind: "tool", stage: "execute", action: "run_tools", description: "推进一个小单元", instruction: "只推进当前计划中的一个小单元，并记录和旧记忆的衔接点。", x: 1340, y: 260 },
        { id: "checkpoint", title: "续写快照", kind: "state", stage: "checkpoint", action: "save_state", description: "写回进度", instruction: "记录当前完成度、新发现、下一步和与原任务不同的地方。", x: 1760, y: 260 },
        { id: "memory", title: "更新记忆标签", kind: "memory", stage: "checkpoint", action: "save_memory", description: "暴露新记忆", instruction: "更新任务标签、时间线、成果和下次续写入口，避免保存敏感或短期 token。", x: 2180, y: 260 },
        { id: "archive", title: "续写归档", kind: "memory", stage: "archive", action: "exit_summary", description: "结束或等待下次", instruction: "总结本次续写结果、未解决问题和下次入口。", x: 2600, y: 260 },
      ],
      edges: [
        { from: "entry", to: "recall" },
        { from: "recall", to: "plan" },
        { from: "plan", to: "execute" },
        { from: "execute", to: "checkpoint" },
        { from: "checkpoint", to: "memory" },
        { from: "memory", to: "archive" },
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
  workflowCheckReport = null;
  const names = { api_review: "API 审批流", code_task: "代码任务流", emergency: "紧急模式", memory_loop: "记忆续写流", parallel_agent: "并行 Agent 流", linear: "标准工作流" };
  setFeedback(`已套用${names[id] || "工作流"}，保存后会进入任务运行协议。`);
}

function workflowNodeDropPosition(point, fallbackStage, index = 0) {
  const pos = point || defaultWorkflowPosition(fallbackStage || "plan", index);
  return {
    x: clamp(Number(pos.x || 0) - (point ? WORKFLOW_NODE_WIDTH / 2 : 0), WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X),
    y: clamp(Number(pos.y || 0) - (point ? WORKFLOW_NODE_HEIGHT / 2 : 0), 0, WORKFLOW_CANVAS_MAX_Y),
  };
}

function addWorkflowTemplateNode(templateId, point = null) {
  readAgentForm();
  ensureWorkflow();
  const template = WORKFLOW_NODE_TEMPLATES.find((item) => item.id === templateId) || WORKFLOW_NODE_TEMPLATES[0];
  pushWorkflowHistory();
  const id = uniqueWorkflowNodeId(template.id);
  const pos = workflowNodeDropPosition(point, template.stage, currentAgent.workflow_nodes.length);
  currentAgent.workflow_nodes.push({
    ...clone(template),
    id,
    description: template.description || template.title,
    x: pos.x,
    y: pos.y,
  });
  selectedWorkflowNodeId = id;
  workflowInspectorOpen = true;
  workflowDryRunReport = null;
  workflowCheckReport = null;
  setFeedback(`已添加节点：${template.title}。拖动画布上的节点即可调整位置。`);
}

function addRuntimeWorkflowNode(refType, refId, point = null) {
  readAgentForm();
  ensureWorkflow();
  const ref = String(refType || "").trim();
  const idValue = String(refId || "").trim();
  let node = null;
  if (ref === "plugin") {
    const plugin = (state.plugins || []).find((item) => item.name === idValue);
    node = {
      id: uniqueWorkflowNodeId(`plugin_${idValue || "module"}`),
      title: plugin?.display_name || plugin?.name || idValue || "插件模块",
      kind: "subflow",
      stage: "execute",
      action: "manual",
      description: "AstrBot 插件模块",
      instruction: "把这个 AstrBot 插件视为工作流中的能力模块；若插件关闭或被隔离策略禁用，不要依赖它。",
      prompt: "说明这个插件在当前任务模式中负责什么、什么时候调用、输出要如何写回 task_state。",
      ref_type: "plugin",
      ref_id: idValue,
      plugin_name: idValue,
      output_variable: `plugin.${normalizeWorkflowId(idValue || "module")}.result`,
    };
  }
  if (ref === "api") {
    const item = (state.custom_apis || []).find((api) => api.api_id === idValue);
    node = {
      id: uniqueWorkflowNodeId(`api_${idValue || "call"}`),
      title: item?.name || idValue || "API 模块",
      kind: "api",
      stage: "execute",
      action: "call_api",
      description: item?.description || "自定义 API 模块",
      instruction: "调用 Agent Lab 注册 API；凭证由后端注入，不把密钥写入提示词、日志或任务记忆。",
      prompt: "写清 API 调用目的、参数边界、成功判定和结果字段如何进入后续校验。",
      ref_type: "api",
      ref_id: idValue,
      api_id: idValue,
      output_variable: `api.${normalizeWorkflowId(idValue || "call")}.result`,
    };
  }
  if (ref === "tool") {
    const item = (state.tools || []).find((tool) => tool.name === idValue);
    node = {
      id: uniqueWorkflowNodeId(`tool_${idValue || "step"}`),
      title: idValue || "工具模块",
      kind: "tool",
      stage: "execute",
      action: "run_tools",
      description: item?.description || "工具白名单模块",
      instruction: "调用该白名单工具前先确认风险等级，关键输出必须写回 task_state。",
      prompt: "写清这个工具允许做什么、不允许做什么，以及输出要保存到哪个任务状态字段。",
      ref_type: "tool",
      ref_id: idValue,
      tool_name: idValue,
      output_variable: `tool.${normalizeWorkflowId(idValue || "step")}.result`,
    };
  }
  if (!node) return;
  pushWorkflowHistory();
  const pos = workflowNodeDropPosition(point, node.stage, currentAgent.workflow_nodes.length);
  node.x = pos.x;
  node.y = pos.y;
  currentAgent.workflow_nodes.push(node);
  selectedWorkflowNodeId = node.id;
  workflowInspectorOpen = true;
  workflowCheckReport = null;
  workflowDryRunReport = null;
  setFeedback(`已添加模块节点：${node.title}。`);
}

function clamp(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, value));
}

function defaultWorkflowPosition(stage, index = 0) {
  const stageIndex = Math.max(0, WORKFLOW_STAGES.findIndex(([id]) => id === stage));
  return {
    x: 70 + stageIndex * WORKFLOW_LANE_WIDTH,
    y: 110 + (index % 5) * 215,
  };
}

function defaultWorkflowAction(node) {
  const stage = String(node?.stage || "").trim();
  const kind = String(node?.kind || "").trim();
  if (stage === "entry") return "summarize_entry";
  if (kind === "retrieval") return "retrieve_memory";
  if (kind === "branch") return "route_condition";
  if (kind === "transform") return "transform_context";
  if (kind === "validation") return "validate_output";
  if (kind === "loop") return "retry";
  if (kind === "notification") return "notify";
  if (kind === "subflow") return "manual";
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
  const legacyIds = new Set(["entry", "entry_gate", "context_bridge", "plan", "execute", "approval", "checkpoint", "task_memory", "heartbeat", "archive"]);
  if (
    currentAgent.workflow_nodes.length <= legacyIds.size
    && currentAgent.workflow_nodes.every((node) => legacyIds.has(String(node.id || "")))
  ) {
    currentAgent.workflow_nodes = defaultWorkflowNodes();
    currentAgent.workflow_edges = defaultWorkflowEdges();
  }
  currentAgent.workflow_nodes = currentAgent.workflow_nodes.map((node, index) => ({
    ...node,
    id: String(node.id || `node_${index + 1}`).trim(),
    title: String(node.title || node.id || `节点 ${index + 1}`).trim(),
    kind: WORKFLOW_KINDS.includes(String(node.kind || "").trim()) ? String(node.kind).trim() : "state",
    stage: workflowStage(node),
    action: String(node.action || defaultWorkflowAction(node)).trim() || "manual",
    description: String(node.description || "").trim(),
    instruction: String(node.instruction || node.prompt || node.description || "").trim(),
    condition: String(node.condition || "").trim(),
    parallel_group: String(node.parallel_group || "").trim(),
    prompt: String(node.prompt || "").trim(),
    x: clamp(Number(node.x ?? defaultWorkflowPosition(workflowStage(node), index).x), WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X),
    y: clamp(Number(node.y ?? defaultWorkflowPosition(workflowStage(node), index).y), 0, WORKFLOW_CANVAS_MAX_Y),
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
  const viewport = route === "workflow" ? workflowViewportSnapshot() : null;
  document.body.dataset.route = route;
  document.body.classList.toggle("workflow-nav-collapsed", route === "workflow" && workflowNavCollapsed);
  renderNav();
  if (!state) return;
  syncLiveRefresh();
  if (route === "dashboard") renderDashboard();
  if (route === "canvas") renderCanvas();
  if (route === "workflow") renderWorkflowPage();
  if (route === "memory") renderMemoryPage();
  if (route === "tasks") renderTasks();
  if (route === "monitor") renderMonitor();
  if (route === "integrations") renderIntegrations();
  restoreWorkflowViewport(viewport);
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
          <button class="button danger" data-action="delete-agent" type="button" ${((state.agents || []).length <= 1 || !currentAgent.agent_id) ? "disabled" : ""}>删除配置</button>
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
          <div class="span-2 note-line">开启暗号、任务关键词、确认话术、默认完成条件和结束暗号已迁到工作流画布：点击入口节点或结束回流节点即可编辑。</div>
          <label class="span-2">隔离说明<textarea id="isolation-notes" rows="3">${esc(currentAgent.isolation_policy.notes || "")}</textarea></label>
          <div class="span-2 note-line">当前运行时身份：${esc(state.runtime?.bot_label || "等待读取")}；来源：${esc(identitySourceLabel(state.runtime?.bot_label_source))}。这里配置的是任务模式模板名和规则，不会覆盖 AstrBot 当前身份。</div>
        </div>
      </div>
    </section>

    <section class="panel workflow-card">
      <div class="panel-head">
        <div><p class="card-kicker">工作流</p><h2>独立画布工作台</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-route="workflow" type="button">打开画布</button>
          <button class="button secondary" data-action="check-workflow" type="button">检查工作流</button>
          <button class="button secondary" data-action="dry-run-workflow" type="button">预跑诊断</button>
        </div>
      </div>
      <div class="workflow-card-grid">
        ${metric("节点", currentAgent.workflow_nodes.length)}
        ${metric("连线", currentAgent.workflow_edges.length)}
        ${metric("入口模块", currentAgent.workflow_nodes.filter((node) => workflowStage(node) === "entry").length)}
        ${metric("出口模块", currentAgent.workflow_nodes.filter((node) => workflowStage(node) === "archive").length)}
      </div>
      <div class="section-note">流程图已经移到独立工作台；这里保留基础策略、隔离和提示词配置。入口/出口暗号请在画布对应节点里维护。</div>
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

function workflowViewportSnapshot() {
  return {
    x: workflowPanX,
    y: workflowPanY,
    zoom: workflowZoom,
    nodeId: selectedWorkflowNodeId,
  };
}

function restoreWorkflowViewport(snapshot) {
  if (!snapshot || route !== "workflow") return;
  workflowPanX = Number(snapshot.x || 0);
  workflowPanY = Number(snapshot.y || 0);
  workflowZoom = Number(snapshot.zoom || workflowZoom || 1);
}

function workflowCanvasTransform() {
  return `translate(${workflowPanX}px, ${workflowPanY}px) scale(${workflowZoom})`;
}

function renderWorkflowPage() {
  currentAgent = ensureAgent(currentAgent || {});
  ensureWorkflow();
  if (!workflowViewportInitialized) {
    focusWorkflowStart();
    workflowViewportInitialized = true;
  }
  const report = workflowCheckReport || localWorkflowReport();
  $("view").innerHTML = `
    <section class="workflow-page ${workflowToolboxOpen ? "toolbox-open" : "toolbox-closed"} ${workflowInspectorOpen ? "inspector-open" : ""} ${workflowRibbonOpen ? "ribbon-open" : ""}">
      <button class="workflow-nav-toggle" data-action="toggle-workflow-nav" title="${workflowNavCollapsed ? "展开导航" : "收起导航"}" type="button">${workflowNavCollapsed ? "☰" : "×"}</button>
      <main class="workflow-main-canvas">
        ${workflowCanvas()}
        ${workflowContextMenuHtml()}
      </main>
      <div class="workflow-ribbon-hover-zone" aria-hidden="true"></div>
      <header class="workflow-page-top">
        <div class="workflow-ribbon-handle" aria-hidden="true"></div>
        <label class="workflow-agent-picker">
          <span>当前方案</span>
          <select data-action="workflow-agent-select">
            ${(state.agents || [currentAgent]).map((agent) => `
              <option value="${esc(agent.agent_id || "")}" ${agent.agent_id === currentAgent.agent_id ? "selected" : ""}>
                ${esc(agentDisplayName(agent))}
              </option>
            `).join("")}
          </select>
        </label>
        <div class="workflow-page-status">
          ${badge(`${currentAgent.workflow_nodes.length} 节点`)}
          ${badge(`${currentAgent.workflow_edges.length} 连线`)}
          ${badge(report.valid ? "检查通过" : `${report.errors || 0} 错误 / ${report.warnings || 0} 提醒`, report.valid ? "ok" : "warn")}
        </div>
      <div class="workflow-page-actions">
          <button class="button secondary icon-button" data-action="workflow-select-mode" title="${workflowSelectionMode ? "退出框选" : "框选节点"}" type="button">${iconImg("select", "框选")}</button>
          <button class="button secondary icon-button" data-action="copy-selected-workflow-nodes" title="复制框选节点" ${workflowSelectedNodeIds.size ? "" : "disabled"} type="button">${iconImg("copy", "复制")}</button>
          <button class="button secondary icon-button" data-action="delete-selected-workflow-nodes" title="删除框选节点" ${workflowSelectedNodeIds.size ? "" : "disabled"} type="button">${iconImg("trash", "删除")}</button>
          <button class="button secondary icon-button" data-action="workflow-undo" title="上一步" ${workflowHistoryPast.length ? "" : "disabled"} type="button">${iconImg("undo", "上一步")}</button>
          <button class="button secondary icon-button" data-action="workflow-redo" title="下一步" ${workflowHistoryFuture.length ? "" : "disabled"} type="button">${iconImg("redo", "下一步")}</button>
          <button class="button secondary" data-action="check-workflow" type="button">静态检查</button>
          <button class="button secondary" data-action="dry-run-workflow" type="button">预跑诊断</button>
          <button class="button secondary" data-action="auto-layout-workflow" type="button">自动整理</button>
          <button class="button secondary" data-action="reset-workflow" type="button">恢复默认</button>
          <button class="button" data-action="save-agent" type="button">保存方案</button>
        </div>
      </header>
      <button class="workflow-toolbox-tab" data-action="toggle-workflow-toolbox" title="${workflowToolboxOpen ? "收起素材" : "打开素材"}" type="button" aria-label="${workflowToolboxOpen ? "收起素材" : "打开素材"}">${iconImg("menu", "素材")}</button>
      <aside class="workflow-tool-drawer">
        <div class="drawer-head">
          <div><p class="card-kicker">模块库</p><h3>拼图素材 <small>可直接拖拽</small></h3></div>
          <button class="button tiny secondary" data-action="toggle-workflow-toolbox" type="button">收起</button>
        </div>
        <div class="drawer-scroll">${workflowToolbox()}</div>
      </aside>
      ${workflowInspectorOpen ? `
        <div class="workflow-modal-backdrop" data-action="close-workflow-inspector"></div>
        <section class="workflow-inspector-drawer" role="dialog" aria-modal="true">
          <div class="drawer-head">
            <div><p class="card-kicker">节点编辑</p><h3>${esc(selectedWorkflowNode()?.title || "未选择节点")}</h3></div>
          </div>
          <div class="drawer-scroll">
            ${workflowInspector()}
          </div>
        </section>
      ` : ""}
      ${workflowReportOpen ? workflowReportPanel() : ""}
    </section>
  `;
}

function renderMemoryPage() {
  currentAgent = ensureAgent(currentAgent || {});
  const rows = filteredMemoryRows();
  if (!selectedMemoryId || !rows.some((item) => item.memory_id === selectedMemoryId)) {
    selectedMemoryId = rows[0]?.memory_id || "";
  }
  const selected = rows.find((item) => item.memory_id === selectedMemoryId) || null;
  $("view").innerHTML = `
    <section class="memory-page">
      <div class="panel-head memory-page-head">
        <div><p class="card-kicker">完成记录</p><h2>看哪些任务做过、哪些记录要保留</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-route="tasks" type="button">任务列表</button>
          <button class="button secondary" data-route="workflow" type="button">工作流画布</button>
        </div>
      </div>
      <div class="tabs compact-tabs">
        ${["all", "candidate", "accepted", "rejected"].map((item) => `
          <button class="${memoryFilter === item ? "active" : ""}" data-action="memory-filter" data-id="${item}" type="button">${memoryFilterLabel(item)}</button>
        `).join("")}
      </div>
      <section class="memory-layout">
        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">记录</p><h3>已保存的任务信息</h3></div></div>
          <div class="list">${memoryRows()}</div>
        </div>
        <div class="panel memory-detail">
          ${selected ? memoryDetail(selected) : `<div class="empty">暂无可查看的任务记忆。</div>`}
        </div>
        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">历史</p><h3>已经结束的任务</h3></div></div>
          ${memoryRollbackPanel(selected)}
        </div>
      </section>
    </section>
  `;
}

function memoryDetail(item) {
  return `
    <div class="panel-head">
      <div><p class="card-kicker">${esc(item.memory_id)}</p><h3>${esc(item.text || "任务记忆")}</h3></div>
      ${badge(memoryFilterLabel(item.status || "candidate"), item.status === "accepted" ? "ok" : "warn")}
    </div>
    <div class="state-fields">
      ${stateField("来源任务", item.source_task_id || "-")}
      ${stateField("标签", (item.tags || []).join(", ") || "-")}
      ${stateField("普通模式可读", item.expose_to_normal === false ? "否，仅任务模式" : "是，可按标签读取")}
      ${stateField("来源会话", item.source_umo || "-")}
    </div>
    <label>记忆内容<textarea rows="7" readonly>${esc(item.text || "")}</textarea></label>
    <label>续写入口草稿<textarea rows="7" readonly>${esc(memoryContextText(item))}</textarea></label>
    <div class="button-row">
      <button class="button secondary" data-action="use-memory-context" data-id="${esc(item.memory_id)}" type="button">带入新任务</button>
      <button class="button secondary" data-action="accept-memory" data-id="${esc(item.memory_id)}" type="button">保留</button>
      <button class="button secondary" data-action="reject-memory" data-id="${esc(item.memory_id)}" type="button">标记不用</button>
      <button class="button danger" data-action="delete-memory" data-id="${esc(item.memory_id)}" type="button">删除</button>
    </div>
  `;
}

function memoryContextText(item) {
  return [
    `从任务记忆续写：${item.text || ""}`,
    `来源任务：${item.source_task_id || "-"}`,
    `标签：${(item.tags || []).join(", ") || "-"}`,
    "请先读取相关归档和任务记忆，确认当前目标与旧任务的差异，再进入计划。"
  ].join("\n");
}

function memoryRollbackPanel(selected) {
  const sourceTaskId = selected?.source_task_id || "";
  const related = (state.archives || []).filter((task) => !sourceTaskId || task.task_id === sourceTaskId);
  const rows = related.length ? related : (state.archives || []).slice(-8);
  if (!rows.length) return `<div class="empty">还没有归档任务可回看。</div>`;
  return `
    <div class="list">
      ${rows.slice(-12).reverse().map((task) => `
        <button class="list-row" data-action="open-memory-source" data-id="${esc(task.task_id)}" type="button">
          <div class="row-title"><span>${esc(task.root_goal || task.task_id)}</span>${badge(taskStatusLabel(task.status || "archived"))}</div>
          <div class="row-meta">${esc(task.task_id)} · 记录 ${task.state_snapshots?.length || 0} · 日志 ${task.progress_log?.length || 0}</div>
          <div class="inline-actions rollback-actions">
            <span class="button secondary tiny" data-action="restore-archive-context" data-id="${esc(task.task_id)}">带入新任务</span>
          </div>
        </button>
      `).join("")}
    </div>
  `;
}

function taskRollbackContextText(task, memory) {
  return [
    `从已结束任务继续：${task.root_goal || task.task_id || ""}`,
    `归档任务：${task.task_id || "-"}`,
    `最近进度：${task.last_confirmed_progress || task.current_summary || "-"}`,
    `下一步：${task.next_step || "-"}`,
    memory ? `关联任务记忆：${memory.text || memory.memory_id || "-"}` : "",
    "请先读取该任务的状态、记录和任务记忆，确认新旧目标差异，再进入计划。"
  ].filter(Boolean).join("\n");
}

function filteredMemoryRows() {
  return (state.memories || [])
    .filter((item) => memoryFilter === "all" || item.status === memoryFilter)
    .slice()
    .sort((a, b) => String(b.created_at || b.updated_at || b.memory_id || "").localeCompare(String(a.created_at || a.updated_at || a.memory_id || "")));
}

function workflowDryRunPanel() {
  if (!workflowDryRunReport) {
    return `
      <div class="detail-box workflow-runtime-card">
        <div class="panel-head"><div><p class="card-kicker">预跑</p><h3>尚未运行诊断</h3></div></div>
        <div class="section-note">预跑只做静态路径模拟，不会真的调用工具、API 或写入文件。</div>
      </div>
    `;
  }
  const path = workflowDryRunReport.primary_path || [];
  const notes = workflowDryRunReport.notes || [];
  return `
    <div class="detail-box workflow-runtime-card">
      <div class="panel-head"><div><p class="card-kicker">预跑</p><h3>${esc(workflowDryRunReport.summary || "静态路径诊断")}</h3></div></div>
      <div class="mini-stats">
        <span>路径 ${path.length}</span>
        <span>分支 ${workflowDryRunReport.branch_nodes?.length || 0}</span>
        <span>并行 ${workflowDryRunReport.parallel_nodes?.length || 0}</span>
        <span>${workflowDryRunReport.executable ? "可进入" : "需修正"}</span>
      </div>
      <div class="workflow-path-line">${path.map((id) => `<span>${esc(id)}</span>`).join("") || "<em>暂无可达路径</em>"}</div>
      <div class="workflow-events">
        ${notes.slice(0, 8).map((item) => `
          <div class="log-row">
            <span>${esc(item.level || "info")}</span>
            <strong>${esc(item.node_id || "workflow")}</strong>
            <p>${esc(item.message || "")}</p>
          </div>
        `).join("") || `<div class="empty">没有额外诊断。</div>`}
      </div>
    </div>
  `;
}

function workflowReportPanel() {
  const report = workflowCheckReport || localWorkflowReport();
  const modeLabel = {
    check: "静态检查",
    dry_run: "预跑诊断",
    layout: "自动整理",
  }[workflowReportMode] || "工作流结果";
  const stageCounts = WORKFLOW_STAGES.map(([stage, title]) => {
    const count = (currentAgent.workflow_nodes || []).filter((item) => workflowStage(item) === stage).length;
    return `<span>${esc(title)} ${count}</span>`;
  }).join("");
  const dryRun = workflowDryRunReport;
  return `
    <section class="workflow-report-panel" role="status">
      <div class="drawer-head">
        <div><p class="card-kicker">${esc(modeLabel)}</p><h3>${report.valid ? "工作流可运行" : "工作流需要修正"}</h3></div>
        <button class="button tiny secondary" data-action="close-workflow-report" type="button">关闭</button>
      </div>
      <div class="drawer-scroll">
        <div class="mini-stats workflow-report-stats">
          <span>${currentAgent.workflow_nodes.length} 节点</span>
          <span>${currentAgent.workflow_edges.length} 连线</span>
          <span>${report.errors || 0} 错误</span>
          <span>${report.warnings || 0} 提醒</span>
        </div>
        ${workflowReportMode === "layout" ? `
          <div class="workflow-check">
            <div class="workflow-check-row ok"><b>OK</b><span>已按入口、计划、执行、闸门、快照、出口重新排布节点，并把视图拉回流程起点。</span></div>
            <div class="workflow-path-line">${stageCounts}</div>
          </div>
        ` : ""}
        ${workflowReportMode === "dry_run" && dryRun ? `
          <div class="workflow-runtime-card">
            <div class="mini-stats workflow-report-stats">
              <span>路径 ${dryRun.primary_path?.length || 0}</span>
              <span>分支 ${dryRun.branch_nodes?.length || 0}</span>
              <span>并行 ${dryRun.parallel_nodes?.length || 0}</span>
              <span>${dryRun.executable ? "可进入" : "需修正"}</span>
            </div>
            <div class="workflow-path-line">${(dryRun.primary_path || []).map((id) => `<span>${esc(id)}</span>`).join("") || "<em>暂无可达路径</em>"}</div>
            <div class="workflow-events">
              ${(dryRun.notes || []).slice(0, 10).map((item) => `
                <div class="workflow-check-row ${esc(item.level || "warn")}">
                  <b>${esc((item.level || "info").toUpperCase())}</b>
                  <span>${esc(item.node_id ? `${item.node_id}：${item.message}` : item.message)}</span>
                </div>
              `).join("") || `<div class="workflow-check-row ok"><b>OK</b><span>预跑没有发现额外阻塞。</span></div>`}
            </div>
          </div>
        ` : ""}
        <div class="workflow-check">
          ${(report.issues || []).slice(0, 14).map((item) => `
            <div class="workflow-check-row ${esc(item.level || "warn")}">
              <b>${esc((item.level || "warn").toUpperCase())}</b>
              <span>${esc(item.node_id ? `${item.node_id}：${item.message}` : item.message)}</span>
            </div>
          `).join("") || `<div class="workflow-check-row ok"><b>OK</b><span>入口、出口、连线和关键模块暂未发现阻塞问题。</span></div>`}
        </div>
      </div>
    </section>
  `;
}

function workflowContextMenuHtml() {
  if (!workflowContextMenu) return "";
  return `
    <div class="workflow-context-menu" style="left:${workflowContextMenu.x}px;top:${workflowContextMenu.y}px">
      <button data-action="copy-workflow-node" data-id="${esc(workflowContextMenu.nodeId)}" type="button">复制节点</button>
      <button data-action="delete-workflow-node-menu" data-id="${esc(workflowContextMenu.nodeId)}" type="button">删除节点</button>
    </div>
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
  if (["retrieval", "branch"].includes(item.kind) || id.includes("router") || title.includes("分流")) return "plan";
  if (["tool", "api", "transform", "subflow"].includes(item.kind) || id.includes("execute") || title.includes("执行")) return "execute";
  if (["validation", "loop"].includes(item.kind) || id.includes("checkpoint") || title.includes("快照") || title.includes("校验")) return "checkpoint";
  if (item.kind === "notification" || id.includes("archive") || title.includes("归档")) return "archive";
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
  const minX = Math.min(WORKFLOW_CANVAS_MIN_X, nodes.reduce((value, node) => Math.min(value, Number(node.x || 0)), 0));
  return {
    minX,
    maxX: Math.max(WORKFLOW_CANVAS_MAX_X, maxX + WORKFLOW_NODE_WIDTH),
    width: Math.max(WORKFLOW_CANVAS_MIN_WIDTH, maxX - minX + WORKFLOW_NODE_WIDTH + 260),
    height: Math.max(WORKFLOW_CANVAS_MIN_HEIGHT, maxY + WORKFLOW_NODE_HEIGHT + 180),
  };
}

function workflowWorldOffsetX(size = null) {
  const data = size || workflowCanvasSize();
  return Math.abs(Math.min(0, Number(data.minX || 0))) + 140;
}

function workflowCanvas() {
  ensureWorkflow();
  const size = workflowCanvasSize();
  const scaledWidth = Math.ceil(size.width * workflowZoom);
  const scaledHeight = Math.ceil(size.height * workflowZoom);
  const hasPending = Boolean(workflowPendingPort);
  const worldOffsetX = workflowWorldOffsetX(size);
  return `
    <div class="workflow-canvas-toolbar">
      <div class="workflow-canvas-meta">
        <span>${currentAgent.workflow_nodes.length} 节点</span>
        <span>${currentAgent.workflow_edges.length} 连线</span>
        <span>${Math.round(workflowZoom * 100)}%</span>
      </div>
      <div class="workflow-zoom-controls">
        <button class="button tiny secondary" data-action="workflow-zoom-out" type="button">缩小</button>
        <button class="button tiny secondary" data-action="workflow-fit" type="button">适配</button>
        <button class="button tiny secondary" data-action="workflow-zoom-reset" type="button">100%</button>
        <button class="button tiny secondary" data-action="workflow-zoom-in" type="button">放大</button>
      </div>
    </div>
    <div class="workflow-canvas-wrap">
      <div class="workflow-canvas-space" style="width:${scaledWidth}px;height:${scaledHeight}px">
        <div class="workflow-canvas ${hasPending ? "is-connecting" : ""}" data-zoom="${workflowZoom}" data-world-offset-x="${worldOffsetX}" style="width:${size.width}px;height:${size.height}px;transform:${workflowCanvasTransform()}">
          <div class="workflow-lanes">
            ${WORKFLOW_STAGES.map(([stage, title, meta], index) => `
              <div class="workflow-lane" data-stage="${stage}" style="left:${worldOffsetX + index * WORKFLOW_LANE_WIDTH}px">
                <strong>${esc(title)}</strong>
                <span>${esc(meta)}</span>
              </div>
            `).join("")}
          </div>
          <svg class="workflow-links" width="${size.width}" height="${size.height}" viewBox="0 0 ${size.width} ${size.height}" aria-hidden="true">
            ${workflowLinksSvg(worldOffsetX)}
          </svg>
          ${currentAgent.workflow_nodes.map((item) => node(item, worldOffsetX)).join("")}
        </div>
      </div>
      ${workflowMinimap(size)}
    </div>
    ${workflowCompactBoard()}
  `;
}

function workflowTemplateGroupLabel(item) {
  return item.library_group || workflowStageLabel(item.stage || "plan");
}

function workflowMaterialChip(item, options = {}) {
  const stateInfo = workflowNodeExecutorState(item);
  const meta = workflowMaterialMeta(item);
  const hint = workflowMaterialHint(item);
  const action = options.action || "preview-template-node";
  const icon = options.icon || workflowMaterialIcon(item.kind, item.ref_type);
  const dragKind = options.dragKind || "template";
  const idAttrs = dragKind === "template"
    ? `data-id="${esc(item.id)}" data-drag-id="${esc(item.id)}"`
    : `data-ref-type="${esc(item.ref_type || options.refType || "")}" data-ref-id="${esc(item.ref_id || options.refId || "")}"`;
  return `
    <button class="toolbox-chip workflow-material-chip"
      data-action="${esc(action)}"
      ${idAttrs}
      data-title="${esc(item.title || item.id || "")}"
      data-instruction="${esc(hint)}"
      data-runtime-type="${esc(workflowRuntimeType(item))}"
      draggable="true"
      data-drag-kind="${esc(dragKind)}"
      title="拖到画布添加：${esc(hint)}"
      type="button">
      ${iconImg(icon, item.title || item.id || "节点")}
      <span class="toolbox-chip-main">
        <strong>${esc(item.title || item.id || "节点")}</strong>
        <small>${esc(hint)}</small>
      </span>
      <span class="toolbox-chip-badges">
        <b class="runtime-badge ${esc(stateInfo.tone)}">${esc(stateInfo.label)}</b>
        <em>${esc(meta[1] || workflowRuntimeLabel(item))}</em>
      </span>
    </button>
  `;
}

function workflowRuntimeModuleNode(refType, refId) {
  const ref = String(refType || "").trim();
  const idValue = String(refId || "").trim();
  if (ref === "plugin") {
    const plugin = (state.plugins || []).find((item) => item.name === idValue);
    return {
      id: `plugin_${idValue || "module"}`,
      title: plugin?.display_name || plugin?.name || idValue || "插件模块",
      kind: "subflow",
      stage: "execute",
      action: "manual",
      instruction: "插件作为能力模块接入；需要在节点说明里写清什么时候调用、返回什么、如何写回任务状态。",
      ref_type: "plugin",
      ref_id: idValue,
      output_variable: `plugin.${normalizeWorkflowId(idValue || "module")}.result`,
    };
  }
  if (ref === "api") {
    const item = (state.custom_apis || []).find((api) => api.api_id === idValue);
    return {
      id: `api_${idValue || "call"}`,
      title: item?.name || idValue || "API 模块",
      kind: "api",
      stage: "execute",
      action: "call_api",
      instruction: item?.description || "调用已登记 API；凭证由后端注入，参数和输出字段需要在节点里写清。",
      ref_type: "api",
      ref_id: idValue,
      api_id: idValue,
      output_variable: `api.${normalizeWorkflowId(idValue || "call")}.result`,
    };
  }
  if (ref === "tool") {
    const item = (state.tools || []).find((tool) => tool.name === idValue);
    return {
      id: `tool_${idValue || "step"}`,
      title: idValue || "工具模块",
      kind: "tool",
      stage: "execute",
      action: "run_tools",
      instruction: item?.description || "调用 AstrBot 工具；若未填写工具参数或输入变量，会交给 ReAct 判断调用。",
      ref_type: "tool",
      ref_id: idValue,
      tool_name: idValue,
      output_variable: `tool.${normalizeWorkflowId(idValue || "step")}.result`,
    };
  }
  return null;
}

function workflowToolbox() {
  const selectedTools = materializedToolSelection();
  const activePlugins = (state.plugins || []).filter((item) => item.activated !== false);
  const apis = state.custom_apis || [];
  const filter = workflowMaterialFilter.trim();
  const templates = WORKFLOW_NODE_TEMPLATES.filter((item) =>
    includesQuery([item.id, item.title, item.kind, item.action, item.stage, item.library_group, item.instruction, item.description], filter)
  );
  const groupedTemplates = WORKFLOW_NODE_GROUPS
    .map((group) => ({ group, items: templates.filter((item) => workflowNodeGroupKey(item) === group.id) }))
    .filter(({ items }) => items.length || !filter);
  const runtimeSections = [
    {
      id: "runtime_plugins",
      title: "插件模块",
      hint: "把已启用 AstrBot 插件作为能力来源。",
      items: activePlugins
        .map((plugin) => workflowRuntimeModuleNode("plugin", plugin.name))
        .filter(Boolean)
        .filter((item) => includesQuery([item.title, item.ref_id, item.instruction], filter)),
      empty: "暂无可用插件",
    },
    {
      id: "runtime_apis",
      title: "API 模块",
      hint: "调用 Agent Lab 注册 API，不在节点里暴露密钥。",
      items: apis
        .map((item) => workflowRuntimeModuleNode("api", item.api_id))
        .filter(Boolean)
        .filter((item) => includesQuery([item.title, item.ref_id, item.instruction], filter)),
      empty: "先在“插件与集成”里注册 API",
    },
    {
      id: "runtime_tools",
      title: "工具模块",
      hint: "从当前任务工具白名单里生成可执行工具节点。",
      items: selectedTools
        .map((name) => workflowRuntimeModuleNode("tool", name))
        .filter(Boolean)
        .filter((item) => includesQuery([item.title, item.ref_id, item.instruction], filter)),
      empty: "仅任务内置工具",
    },
  ];
  return `
    <div class="workflow-toolbox">
      <div class="workflow-toolbox-intro">
        <strong>节点素材</strong>
        <span>按任务流分类；点击看配置，拖拽或点应用节点才会加入画布。</span>
      </div>
      <input class="filter-input workflow-material-filter" data-action="filter-workflow-materials" value="${esc(workflowMaterialFilter)}" placeholder="搜索节点、工具、API 或插件" />
      <div class="workflow-template-groups">
        ${groupedTemplates.map(({ group, items }) => {
          const open = workflowToolboxOpenGroups.has(group.id) || Boolean(filter && items.length);
          return `
            <details class="workflow-template-group" data-group="${esc(group.id)}" ${open ? "open" : ""}>
              <summary data-action="toggle-toolbox-group" data-id="${esc(group.id)}">
                <span class="workflow-template-title">${iconImg(group.icon, group.title)}<b>${esc(group.title)}</b></span>
                <span>${items.length}</span>
              </summary>
              <p>${esc(group.hint)}</p>
              <div class="toolbox-buttons">
                ${items.map((item) => workflowMaterialChip(item)).join("") || `<em>暂无匹配节点</em>`}
              </div>
            </details>
          `;
        }).join("")}
      </div>
      ${runtimeSections.map((section) => {
        const open = workflowToolboxOpenGroups.has(section.id) || Boolean(filter && section.items.length);
        return `
          <details class="workflow-toolbox-section" data-group="${esc(section.id)}" ${open ? "open" : ""}>
            <summary data-action="toggle-toolbox-group" data-id="${esc(section.id)}">
              <span>${esc(section.title)}</span>
              <small>${section.items.length}</small>
            </summary>
            <p>${esc(section.hint)}</p>
            <div class="toolbox-buttons">
              ${section.items.map((item) => workflowMaterialChip(item, {
                action: "preview-runtime-node",
                dragKind: "runtime",
                refType: item.ref_type,
                refId: item.ref_id,
                icon: workflowMaterialIcon(item.kind, item.ref_type),
              })).join("") || `<em>${esc(section.empty)}</em>`}
            </div>
          </details>
        `;
      }).join("")}
      ${workflowMaterialDraft ? `
        <div class="workflow-material-preview">
          <div class="workflow-material-preview-head">
            ${iconImg(workflowMaterialIcon(workflowMaterialDraft.kind, workflowMaterialDraft.ref_type || workflowMaterialDraft.refType), workflowMaterialDraft.title || "素材预览")}
            <strong>${esc(workflowMaterialDraft.title || "素材预览")}</strong>
          </div>
          <div class="workflow-material-preview-meta">
            ${workflowMaterialMeta(workflowMaterialDraft).map((item) => `<span>${esc(item)}</span>`).join("")}
          </div>
          <p>${esc(workflowMaterialHint(workflowMaterialDraft))}</p>
          ${workflowMaterialDraft.refType || workflowMaterialDraft.ref_type ? `<small>来源：${esc(workflowMaterialDraft.refType || workflowMaterialDraft.ref_type)} / ${esc(workflowMaterialDraft.refId || workflowMaterialDraft.ref_id || "")}</small>` : ""}
          <button class="button secondary" data-action="apply-material-node" type="button">应用节点</button>
        </div>
      ` : ""}
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

function workflowLinksSvg(offsetX = workflowWorldOffsetX()) {
  ensureWorkflow();
  const edges = currentAgent.workflow_edges || [];
  const nodes = new Map((currentAgent.workflow_nodes || []).map((item) => [item.id, item]));
  const paths = edges.map((edge, index) => {
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) return "";
    const d = workflowLinkPath(workflowNodeAnchor(from, "out", offsetX), workflowNodeAnchor(to, "in", offsetX));
    const color = workflowNodeColor(from);
    const marker = workflowMarkerId(from);
    return `
      <path class="workflow-link-hit" d="${d}" data-action="delete-workflow-edge" data-index="${index}"></path>
      <path class="workflow-link" d="${d}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" style="--link-color:${color};marker-end:url(#${marker})"></path>
    `;
  }).join("");
  const preview = workflowConnection ? `<path class="workflow-link-preview" d="${workflowLinkPath(workflowConnection.anchor, workflowConnection.pointer)}"></path>` : "";
  return `
    ${workflowMarkerDefs()}
    ${paths}
    ${preview}
  `;
}

function workflowNodeColor(item) {
  const kind = String(item?.kind || "state");
  const stage = String(item?.stage || "");
  const colors = {
    state: "#2f7d5b",
    tool: "#315f8f",
    api: "#4f5aa8",
    guard: "#a76f19",
    human: "#b4433a",
    memory: "#2f7d5b",
    branch: "#b66b24",
    loop: "#8d6b1f",
    transform: "#2d6f86",
    retrieval: "#4b7d3a",
    subflow: "#4667a6",
    notification: "#17201d",
    validation: "#8b5a9a",
  };
  if (colors[kind]) return colors[kind];
  if (stage === "archive") return "#17201d";
  if (stage === "guard") return "#a76f19";
  if (stage === "execute") return "#315f8f";
  return "#2f7d5b";
}

function workflowMarkerId(item) {
  return `workflow-arrow-${String(item?.kind || "state").replace(/[^\w-]+/g, "-")}`;
}

function workflowMarkerDefs() {
  const markerItems = Array.from(
    new Map(
      [
        ...WORKFLOW_KINDS.map((kind) => [{ kind }, workflowMarkerId({ kind })]),
        ...(currentAgent.workflow_nodes || []).map((item) => [item, workflowMarkerId(item)]),
      ].map(([item, id]) => [id, item]),
    ).entries(),
  ).map(([id, item]) => ({ id, item }));
  return `
    <defs>
      ${markerItems.map(({ id, item }) => {
        const color = workflowNodeColor(item);
        return `
          <marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"></path>
          </marker>
        `;
      }).join("")}
    </defs>
  `;
}

function workflowMinimap(size) {
  const mapWidth = workflowMinimapWidth;
  const mapHeight = workflowMinimapHeight;
  const minX = Number(size.minX || 0);
  const scale = Math.min((mapWidth - 18) / size.width, (mapHeight - 18) / size.height);
  const offsetX = Math.max(8, (mapWidth - size.width * scale) / 2);
  const offsetY = Math.max(8, (mapHeight - size.height * scale) / 2);
  const viewport = workflowViewportWorldRect();
  const vx = clamp(viewport.x, minX, minX + Math.max(0, size.width - 80));
  const vy = clamp(viewport.y, 0, Math.max(0, size.height - 60));
  const vw = clamp(viewport.width, 80, minX + size.width - vx);
  const vh = clamp(viewport.height, 60, size.height - vy);
  const nodes = new Map((currentAgent.workflow_nodes || []).map((item) => [item.id, item]));
  const edgeLines = (currentAgent.workflow_edges || []).map((edge) => {
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) return "";
    return `<path d="${workflowLinkPath(workflowNodeAnchor(from, "out"), workflowNodeAnchor(to, "in"))}"></path>`;
  }).join("");
  const nodeRects = (currentAgent.workflow_nodes || []).map((item) => `
    <rect
      class="${item.id === selectedWorkflowNodeId ? "selected" : ""}"
      x="${Number(item.x || 0)}"
      y="${Number(item.y || 0)}"
      width="${WORKFLOW_NODE_WIDTH}"
      height="${WORKFLOW_NODE_HEIGHT}"
      rx="14"
    ></rect>
  `).join("");
  return `
    <div class="workflow-minimap" style="width:${mapWidth}px;height:${mapHeight}px" data-scale="${scale}" data-offset-x="${offsetX}" data-offset-y="${offsetY}" data-map-width="${mapWidth}" data-map-height="${mapHeight}" title="点击或拖动定位画布">
      <svg width="${mapWidth}" height="${mapHeight}" viewBox="0 0 ${mapWidth} ${mapHeight}">
        <rect class="workflow-minimap-bg" x="0.5" y="0.5" width="${mapWidth - 1}" height="${mapHeight - 1}" rx="4"></rect>
        <g transform="translate(${offsetX - minX * scale} ${offsetY}) scale(${scale})">
          ${edgeLines}
          ${nodeRects}
          <rect class="workflow-minimap-viewport" x="${vx}" y="${vy}" width="${vw}" height="${vh}" rx="18"></rect>
        </g>
      </svg>
      <span class="workflow-minimap-resize" data-action="resize-workflow-minimap" title="拖动调整小地图大小"></span>
    </div>
  `;
}

function workflowViewportWorldRect() {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const width = wrap?.clientWidth || window.innerWidth || 1200;
  const height = wrap?.clientHeight || window.innerHeight || 760;
  const zoom = Number(workflowZoom || 1) || 1;
  const offsetX = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  return {
    x: -workflowPanX / zoom - offsetX,
    y: -workflowPanY / zoom,
    width: width / zoom,
    height: height / zoom,
  };
}

function centerWorkflowFromMinimap(event, minimap) {
  const scale = Number(minimap?.dataset.scale || 0);
  if (!scale) return;
  const rect = minimap.getBoundingClientRect();
  const offsetX = Number(minimap.dataset.offsetX || 0);
  const offsetY = Number(minimap.dataset.offsetY || 0);
  const size = workflowCanvasSize();
  const minX = Number(size.minX || 0);
  const worldX = clamp((event.clientX - rect.left - offsetX) / scale + minX, minX, minX + size.width);
  const worldY = clamp((event.clientY - rect.top - offsetY) / scale, 0, size.height);
  const renderOffsetX = workflowWorldOffsetX(size);
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const width = wrap?.clientWidth || window.innerWidth || 1200;
  const height = wrap?.clientHeight || window.innerHeight || 760;
  workflowPanX = Math.round(width / 2 - (worldX + renderOffsetX) * workflowZoom);
  workflowPanY = Math.round(height / 2 - worldY * workflowZoom);
  refreshWorkflowCanvasDom();
}

function workflowNodeAnchor(node, port = "out", offsetX = 0) {
  return {
    x: Number(node.x || 0) + offsetX + (port === "out" ? WORKFLOW_NODE_WIDTH : 0),
    y: Number(node.y || 0) + WORKFLOW_NODE_HEIGHT / 2,
  };
}

function workflowLinkPath(from, to) {
  const x1 = Number(from.x || 0);
  const y1 = Number(from.y || 0);
  const x2 = Number(to.x || 0);
  const y2 = Number(to.y || 0);
  const distance = Math.abs(x2 - x1);
  const bend = clamp(distance * 0.48, 90, 260);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

function workflowSummaryPanel() {
  ensureWorkflow();
  const nodeCount = currentAgent.workflow_nodes.length;
  const edgeCount = currentAgent.workflow_edges.length;
  const selected = selectedWorkflowNode();
  const report = workflowCheckReport || localWorkflowReport();
  return `
    <div class="detail-box workflow-summary">
      <div class="panel-head"><div><p class="card-kicker">运行框架</p><h3>${nodeCount} 节点 · ${edgeCount} 连线</h3></div></div>
      <div class="mini-stats">
        <span>${esc(workflowStageLabel(selected?.stage || "plan"))}</span>
        <span>${esc(workflowKindLabel(selected?.kind || "state"))}</span>
        <span>${esc(workflowActionLabel(selected?.action || "manual"))}</span>
        <span>${report.valid ? "检查通过" : "需修正"}</span>
      </div>
      <div class="workflow-check">
        ${(report.issues || []).slice(0, 6).map((item) => `
          <div class="workflow-check-row ${esc(item.level || "warn")}">
            <b>${esc((item.level || "warn").toUpperCase())}</b>
            <span>${esc(item.node_id ? `${item.node_id}：${item.message}` : item.message)}</span>
          </div>
        `).join("") || `<div class="workflow-check-row ok"><b>OK</b><span>入口、出口和连线检查暂未发现问题。</span></div>`}
      </div>
    </div>
  `;
}

function localWorkflowReport() {
  ensureWorkflow();
  const nodes = currentAgent.workflow_nodes || [];
  const edges = currentAgent.workflow_edges || [];
  const ids = new Set(nodes.map((node) => node.id));
  const incoming = new Map(nodes.map((node) => [node.id, 0]));
  const outgoing = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) continue;
    outgoing.set(edge.from, (outgoing.get(edge.from) || 0) + 1);
    incoming.set(edge.to, (incoming.get(edge.to) || 0) + 1);
  }
  const issues = [];
  const entryNodes = nodes.filter((node) => node.stage === "entry" || ["summarize_entry", "confirm_entry"].includes(node.action));
  const terminalNodes = nodes.filter((node) => ["archive", "exit_summary"].includes(node.action) || (node.stage === "archive" && !["notify", "manual"].includes(node.action)));
  const actions = new Set(nodes.map((node) => node.action));
  const guardNodes = nodes.filter((node) => node.stage === "guard" || ["guard", "human"].includes(node.kind));
  const hasApproval = nodes.some((node) => ["request_approval", "wait_user", "handoff"].includes(node.action) || ["guard", "human"].includes(node.kind));
  if (!entryNodes.length) issues.push({ level: "error", message: "缺少入口节点。" });
  if (!terminalNodes.length) issues.push({ level: "error", message: "缺少真正的出口/归档节点。" });
  if (!guardNodes.length) issues.push({ level: "warn", message: "缺少审批或人工闸门。" });
  if (!actions.has("summarize_entry")) issues.push({ level: "warn", message: "缺少入口摘要节点。" });
  if (currentAgent.entry_policy?.require_confirmation !== false && !actions.has("confirm_entry")) issues.push({ level: "warn", message: "当前要求开启确认，但缺少确认节点。" });
  if (currentAgent.isolation_policy?.mode !== "off" && !actions.has("restore_isolation")) issues.push({ level: "warn", message: "隔离模式已开启，但缺少隔离快照节点。" });
  if (!actions.has("save_memory")) issues.push({ level: "warn", message: "缺少任务记忆节点。" });
  if (!actions.has("exit_summary")) issues.push({ level: "warn", message: "缺少出口摘要节点。" });
  for (const node of nodes) {
    if (!entryNodes.some((item) => item.id === node.id) && !(incoming.get(node.id) || 0)) {
      issues.push({ level: "warn", node_id: node.id, message: "没有输入连线。" });
    }
    if (!terminalNodes.some((item) => item.id === node.id) && !(outgoing.get(node.id) || 0)) {
      issues.push({ level: "warn", node_id: node.id, message: "没有输出连线。" });
    }
    if (terminalNodes.some((item) => item.id === node.id) && (outgoing.get(node.id) || 0)) {
      issues.push({ level: "warn", node_id: node.id, message: "出口节点通常不应继续连出。" });
    }
    if (node.kind === "branch" && (outgoing.get(node.id) || 0) < 2) {
      issues.push({ level: "warn", node_id: node.id, message: "分支节点建议至少两条输出。" });
    }
    if (node.action === "parallel_branch" && (outgoing.get(node.id) || 0) < 2) {
      issues.push({ level: "warn", node_id: node.id, message: "并行 Agent 分支至少需要两个后续工作包。" });
    }
    if (["subflow", "tool", "api"].includes(node.kind) && (!node.action || node.action === "manual") && !String(node.prompt || "").trim()) {
      issues.push({ level: "warn", node_id: node.id, message: "模块节点建议写入节点提示词或明确动作。" });
    }
    if ((node.kind === "api" || node.action === "call_api") && !String(node.api_id || node.ref_id || "").trim()) {
      issues.push({ level: "warn", node_id: node.id, message: "API 节点需要绑定已注册 API。" });
    }
    const text = [node.title, node.description, node.instruction, node.prompt, node.action, node.kind].join(" ").toLowerCase();
    const fileLike = /file|path|document|write|delete|remove|rm|patch|edit|文件|文档|路径|删除|写入|改动/.test(text);
    const dangerous = /delete|remove|rm|deploy|write|patch|edit|restart|credential|删除|写入|部署|重启|密钥|覆盖/.test(text);
    if (fileLike && !String(node.path || node.url || node.input_variable || node.ref_id || "").trim()) {
      issues.push({ level: "warn", node_id: node.id, message: "文件/文档类模块需要写清 path、url 或上游变量。" });
    }
    if (dangerous && !hasApproval && node.stage !== "guard") {
      issues.push({ level: "warn", node_id: node.id, message: "高风险写入/删除/部署动作前建议接入审批模块。" });
    }
    if (node.action === "save_memory" && !String(node.tags || node.memory_tags || node.prompt || node.instruction || "").trim()) {
      issues.push({ level: "warn", node_id: node.id, message: "任务记忆模块需要写清标签、摘要规则或保存字段。" });
    }
  }
  const errors = issues.filter((item) => item.level === "error").length;
  const warnings = issues.filter((item) => item.level === "warn").length;
  return {
    valid: errors === 0,
    errors,
    warnings,
    issues,
  };
}

function edgeText() {
  ensureWorkflow();
  const edges = currentAgent.workflow_edges || [];
  if (!edges.length) return "工作流边：尚未配置。";
  return "工作流边：\n" + edges.map((edge) => `${edge.from} -> ${edge.to}`).join("\n");
}

function node(item, offsetX = workflowWorldOffsetX()) {
  const selected = item.id === selectedWorkflowNodeId;
  const multiSelected = workflowSelectedNodeIds.has(item.id);
  const pendingIn = workflowPendingPort?.nodeId === item.id && workflowPendingPort?.port === "in";
  const pendingOut = workflowPendingPort?.nodeId === item.id && workflowPendingPort?.port === "out";
  const color = workflowNodeColor(item);
  const runtime = workflowNodeRuntimeInfo(item);
  const executorState = workflowNodeExecutorState(item);
  return `
    <article class="node flow-node ${selected ? "selected" : ""} ${multiSelected ? "multi-selected" : ""}" style="left:${Number(item.x || 0) + offsetX}px;top:${Number(item.y || 0)}px;--node-color:${color}" data-action="select-workflow-node" data-id="${esc(item.id)}" data-kind="${esc(item.kind)}" data-stage="${esc(workflowStage(item))}" role="button" tabindex="0">
      <span class="node-port node-port-in ${pendingIn ? "pending" : ""}" data-port="in" data-node-id="${esc(item.id)}" title="输入连接点"></span>
      <span class="node-port node-port-out ${pendingOut ? "pending" : ""}" data-port="out" data-node-id="${esc(item.id)}" title="输出连接点"></span>
      <span class="node-stage">${esc(workflowStageLabel(item.stage || "plan"))} · ${esc(workflowActionLabel(item.action || "manual"))}</span>
      <span class="node-runtime">
        <b class="runtime-badge ${esc(executorState.tone)}">${esc(executorState.label)}</b>
        <em>${esc(WORKFLOW_RUNTIME_LABELS[runtime.runtime_type] || runtime.runtime_type || "ReAct")}</em>
      </span>
      <strong>${esc(item.title || item.id)}</strong>
      <p>${esc(item.instruction || item.description || item.id)}</p>
      <span>${esc(item.id)} · ${esc(workflowKindLabel(item.kind || "state"))}${item.output_variable ? ` · 输出 ${esc(item.output_variable)}` : ""}${item.prompt ? " · 有提示词" : ""}</span>
    </article>
  `;
}

function selectedWorkflowNode() {
  ensureWorkflow();
  return currentAgent.workflow_nodes.find((item) => item.id === selectedWorkflowNodeId) || currentAgent.workflow_nodes[0];
}

function workflowInspector() {
  const item = selectedWorkflowNode();
  if (!item) return `<div class="empty">暂无节点。</div>`;
  const stage = workflowStage(item);
  const isEntryNode = stage === "entry" || ["summarize_entry", "confirm_entry"].includes(item.action);
  const isExitNode = stage === "archive" || ["archive", "exit_summary"].includes(item.action);
  const runtime = workflowNodeRuntimeInfo(item);
  const executorState = workflowNodeExecutorState(item);
  const bindingHint = workflowNodeBindingHint(item);
  return `
    <div class="detail-box workflow-editor">
      <div class="panel-head"><div><p class="card-kicker">节点</p><h3>编辑节点</h3></div></div>
      <div class="workflow-editor-runtime">
        <span class="runtime-badge ${esc(executorState.tone)}">${esc(executorState.label)}</span>
        <span>${esc(WORKFLOW_RUNTIME_LABELS[runtime.runtime_type] || runtime.runtime_type || "ReAct")}节点</span>
        <small>${esc(executorState.hint || bindingHint || "保存方案后由任务运行时读取。")}</small>
      </div>
      <label>节点标识<input id="workflow-node-id" value="${esc(item.id)}" /></label>
      <div class="field-hint">用于连线和运行记录，建议用英文或拼音，保存后会同步更新连线。</div>
      <label>节点名称<input id="workflow-node-title" value="${esc(item.title)}" /></label>
      <div class="form-grid compact">
        <label>放在哪一步<select id="workflow-node-stage">${labeledOptions(WORKFLOW_STAGES.map(([id]) => id), item.stage || "plan", workflowStageLabel)}</select></label>
        <label>节点用途<select id="workflow-node-kind">${labeledOptions(WORKFLOW_KINDS, item.kind || "state", workflowKindLabel)}</select></label>
        <label>运行方式<select id="workflow-node-action">${labeledOptions(WORKFLOW_ACTIONS, item.action || "manual", workflowActionLabel)}</select></label>
      </div>
      <div class="section-note compact-note">工具/API 节点要想直接执行，需要绑定工具名或 API，并提供输入变量或 JSON 参数；没有明确参数时会转给 ReAct 判断。</div>
      ${(item.ref_type || item.ref_id || item.plugin_name || item.api_id || item.tool_name || item.skill_name) ? `
        <div class="workflow-ref-line">
          <span>绑定能力：${esc(item.ref_type || "module")}</span>
          <b>${esc(item.ref_id || item.plugin_name || item.api_id || item.tool_name || item.skill_name || "")}</b>
        </div>
      ` : ""}
      <div class="form-grid compact">
        <label>文件或接口地址<input id="workflow-node-path" value="${esc(item.path || item.url || "")}" placeholder="文件路径、文档地址或 API 目标 URL" /></label>
        <label>输入来源<input id="workflow-node-input-variable" value="${esc(item.input_variable || "")}" placeholder="例如 memory.context 或 tool.result" /></label>
        <label>任务记忆标签<input id="workflow-node-tags" value="${esc(Array.isArray(item.tags) ? item.tags.join(", ") : item.tags || item.memory_tags || "")}" placeholder="任务, 续写, 代码改动" /></label>
        <label>结果保存名<input id="workflow-node-output-variable" value="${esc(item.output_variable || "")}" placeholder="例如 search.result 或 node.summary" /></label>
      </div>
      <div class="field-hint">输入来源读取上游节点保存的变量；结果保存名会写入 task_state.workflow_data.variables，后续节点可继续读取。</div>
      <label>分支条件<input id="workflow-node-condition" value="${esc(item.condition || "")}" placeholder="例如：高风险、只读排查、API 写入前审批" /></label>
      <label>一句话说明<input id="workflow-node-description" value="${esc(item.description || "")}" /></label>
      <label>参数 JSON<textarea id="workflow-node-params" rows="4" placeholder='工具参数或 API 参数，例如 {"query":{"q":"关键词"}}'>${esc(workflowNodeParamsJson(item))}</textarea></label>
      <div class="field-hint">工具节点会保存为 tool_args，API 节点会保存为 api_payload；留空时可改用输入来源或交给 ReAct 判断。</div>
      <label>执行说明<textarea id="workflow-node-instruction" rows="5" placeholder="写清这个节点要做什么、成功标准、失败时交给哪个节点。">${esc(item.instruction || "")}</textarea></label>
      <label>需要模型判断时的提示<textarea id="workflow-node-prompt" rows="5" placeholder="并行 Agent、插件/API/工具模块可在这里写专用提示。">${esc(item.prompt || "")}</textarea></label>
      ${isEntryNode ? `
        <div class="workflow-node-rule-box">
          <div class="panel-head"><div><p class="card-kicker">入口规则</p><h3>进入任务模式</h3></div></div>
          <label>开启暗号/命令<textarea id="workflow-entry-trigger-phrases" rows="3" placeholder="每行一个，例如：进入任务模式">${esc(listToLines(currentAgent.entry_policy.trigger_phrases))}</textarea></label>
          <label>任务关键词<textarea id="workflow-entry-trigger-keywords" rows="3" placeholder="每行一个，例如：排查、部署、持续推进">${esc(listToLines(currentAgent.entry_policy.trigger_keywords))}</textarea></label>
          <label>开启确认话术<textarea id="workflow-entry-confirmation-text" rows="3">${esc(currentAgent.entry_policy.confirmation_text || "")}</textarea></label>
        </div>
      ` : ""}
      ${isExitNode ? `
        <div class="workflow-node-rule-box">
          <div class="panel-head"><div><p class="card-kicker">出口规则</p><h3>结束回流</h3></div></div>
          <label>结束暗号/命令<textarea id="workflow-exit-phrases" rows="3" placeholder="每行一个，例如：完成任务">${esc(listToLines(currentAgent.entry_policy.exit_phrases))}</textarea></label>
          <label>默认验收条件<textarea id="workflow-default-completion-conditions" rows="3">${esc(listToLines(currentAgent.entry_policy.default_completion_conditions))}</textarea></label>
        </div>
      ` : ""}
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
  if ($("entry-trigger-phrases")) currentAgent.entry_policy.trigger_phrases = linesToList($("entry-trigger-phrases").value);
  if ($("entry-trigger-keywords")) currentAgent.entry_policy.trigger_keywords = linesToList($("entry-trigger-keywords").value);
  currentAgent.entry_policy.require_confirmation = $("entry-require-confirmation").value === "true";
  if ($("entry-confirmation-text")) currentAgent.entry_policy.confirmation_text = $("entry-confirmation-text").value.trim();
  if ($("default-completion-conditions")) currentAgent.entry_policy.default_completion_conditions = linesToList($("default-completion-conditions").value);
  if ($("exit-phrases")) currentAgent.entry_policy.exit_phrases = linesToList($("exit-phrases").value);
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
          <div><p class="card-kicker">状态</p><h2>任务记录</h2></div>
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
        <span>记录 ${task.state_snapshots?.length || 0}</span>
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
    ${taskWorkflowDetail(task)}
    ${taskParallelRunsDetail(task)}
    <div class="panel-head"><div><p class="card-kicker">审批</p><h3>待审批</h3></div></div>
    <div class="list">${approvalRows(pendingApprovals)}</div>
    <div class="panel-head"><div><p class="card-kicker">记录</p><h3>状态变化时间线</h3></div></div>
    <div class="list">${snapshotRows(task.state_snapshots || [])}</div>
  `;
}

function taskParallelRunsDetail(task) {
  const runs = task.parallel_runs || [];
  if (!runs.length) return "";
  const latest = runs[runs.length - 1] || {};
  return `
    <div class="detail-box workflow-runtime-card">
      <div class="panel-head"><div><p class="card-kicker">并行工作包</p><h3>${esc(latest.summary || "最近并行运行")}</h3></div></div>
      <div class="mini-stats">
        <span>运行 ${runs.length}</span>
        <span>${esc(latest.branch_node_id || "-")}</span>
        <span>${esc(latest.merge_node_id || "未汇总")}</span>
        <span>${latest.ok ? "全部完成" : "需复核"}</span>
      </div>
      <div class="edge-list">
        ${(latest.workers || []).map((item) => `
          <div class="edge-row">
            <span>${esc(item.node_id || "-")} · ${esc(item.title || item.kind || "-")}</span>
            ${badge(item.ok ? "完成" : "阻塞", item.ok ? "ok" : "bad")}
          </div>
        `).join("") || `<div class="empty">暂无工作包结果。</div>`}
      </div>
      <div class="workflow-events">
        ${(latest.workers || []).slice(0, 6).map((item) => `
          <div class="log-row">
            <span>${esc(item.kind || "-")}</span>
            <strong>${esc(item.summary || item.error || "-")}</strong>
            <p>${esc(item.details || "")}</p>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function taskWorkflowDetail(task) {
  const spec = ensureAgent(clone(task.profile_snapshot?.agent || currentAgent || {}));
  const nodes = spec.workflow_nodes || [];
  const edges = spec.workflow_edges || [];
  const nodeMap = new Map(nodes.map((node) => [node.id, node]));
  const currentId = task.workflow_current_node_id || task.workflow_path?.[task.workflow_path.length - 1] || "";
  const current = nodeMap.get(currentId);
  const candidates = edges
    .filter((edge) => edge.from === currentId)
    .map((edge) => nodeMap.get(edge.to))
    .filter(Boolean);
  const events = task.workflow_events || [];
  return `
    <div class="detail-box workflow-runtime-card">
      <div class="panel-head"><div><p class="card-kicker">工作流游标</p><h3>${esc(current?.title || currentId || "尚未进入节点")}</h3></div></div>
      <div class="mini-stats">
        <span>${esc(currentId || "-")}</span>
        <span>${esc(workflowStageLabel(current?.stage || "plan"))}</span>
        <span>${esc(workflowActionLabel(current?.action || "manual"))}</span>
        <span>路径 ${task.workflow_path?.length || 0}</span>
      </div>
      <div class="workflow-path-line">${(task.workflow_path || []).map((id) => `<span>${esc(id)}</span>`).join("") || "<em>暂无路径</em>"}</div>
      <div class="edge-list">
        ${candidates.map((node) => `
          <div class="edge-row">
            <span>${esc(node.id)} · ${esc(node.title || workflowActionLabel(node.action || "manual"))}</span>
            ${badge(workflowStageLabel(node.stage || "plan"))}
          </div>
        `).join("") || `<div class="empty">当前节点暂无候选下一步。</div>`}
      </div>
      <div class="workflow-events">
        ${events.slice(-6).reverse().map((item) => `
          <div class="log-row">
            <span>${esc(item.time || "")}</span>
            <strong>${esc(item.node_id || "-")} -> ${esc(item.next_node_id || "-")}</strong>
            <p>${esc(item.outcome || item.note || item.status || "-")}</p>
          </div>
        `).join("") || `<div class="empty">暂无节点事件。</div>`}
      </div>
    </div>
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
  if (!snapshots.length) return `<div class="empty">暂无状态记录。</div>`;
  return snapshots.slice(-12).reverse().map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(eventKindLabel(item.kind || "state"))}</span>${badge(taskStatusLabel(item.status || "-"))}</div>
      <div class="row-meta">${esc(item.time || "")} · ${esc(item.next_step || "无下一步")}</div>
    </div>
  `).join("");
}

function memoryRows() {
  const rows = filteredMemoryRows();
  if (!rows.length) return `<div class="empty">暂无可审查记忆。任务结束后会生成候选，也可以手动保存。</div>`;
  return rows.slice(0, 30).map((item) => `
    <div class="list-row ${item.memory_id === selectedMemoryId ? "selected" : ""}" data-action="select-memory" data-id="${esc(item.memory_id)}" role="button" tabindex="0">
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
  const offsetX = workflowWorldOffsetX(size);
  const space = document.querySelector(".workflow-canvas-space");
  const canvas = document.querySelector(".workflow-canvas");
  if (space) {
    space.style.width = `${Math.ceil(size.width * workflowZoom)}px`;
    space.style.height = `${Math.ceil(size.height * workflowZoom)}px`;
  }
  if (canvas) {
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;
    canvas.style.transform = workflowCanvasTransform();
    canvas.dataset.zoom = String(workflowZoom);
    canvas.dataset.worldOffsetX = String(offsetX);
    canvas.classList.toggle("is-connecting", Boolean(workflowConnection || workflowPendingPort));
  }
  svg.setAttribute("width", String(size.width));
  svg.setAttribute("height", String(size.height));
  svg.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);
  svg.innerHTML = workflowLinksSvg(offsetX);
  const minimap = document.querySelector(".workflow-minimap");
  if (minimap && !workflowMinimapPan) minimap.outerHTML = workflowMinimap(size);
}

function workflowCanvasPoint(event) {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const canvas = document.querySelector(".workflow-canvas");
  if (!wrap || !canvas) return { x: 0, y: 0 };
  const rect = wrap.getBoundingClientRect();
  const zoom = Number(canvas.dataset.zoom || workflowZoom || 1) || 1;
  const offsetX = Number(canvas.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  return {
    x: (event.clientX - rect.left - workflowPanX) / zoom - offsetX,
    y: (event.clientY - rect.top - workflowPanY) / zoom,
  };
}

function workflowCanvasRenderPoint(event) {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const canvas = document.querySelector(".workflow-canvas");
  if (!wrap || !canvas) return { x: 0, y: 0 };
  const rect = wrap.getBoundingClientRect();
  const zoom = Number(canvas.dataset.zoom || workflowZoom || 1) || 1;
  return {
    x: (event.clientX - rect.left - workflowPanX) / zoom,
    y: (event.clientY - rect.top - workflowPanY) / zoom,
  };
}

function addWorkflowEdge(from, to) {
  ensureWorkflow();
  if (!from || !to || from === to) return false;
  const exists = currentAgent.workflow_edges.some((edge) => edge.from === from && edge.to === to);
  if (exists) return false;
  pushWorkflowHistory();
  currentAgent.workflow_edges.push({ from, to });
  workflowCheckReport = null;
  return true;
}

function deleteWorkflowNodeById(id) {
  ensureWorkflow();
  if (!id) return false;
  const before = currentAgent.workflow_nodes.length;
  currentAgent.workflow_nodes = currentAgent.workflow_nodes.filter((node) => node.id !== id);
  currentAgent.workflow_edges = currentAgent.workflow_edges.filter((edge) => edge.from !== id && edge.to !== id);
  if (selectedWorkflowNodeId === id) selectedWorkflowNodeId = currentAgent.workflow_nodes[0]?.id || "";
  workflowCheckReport = null;
  workflowDryRunReport = null;
  return before !== currentAgent.workflow_nodes.length;
}

function copyWorkflowNodeById(id) {
  ensureWorkflow();
  const source = workflowNodeById(id);
  if (!source) return null;
  const next = clone(source);
  next.id = uniqueWorkflowNodeId(`${source.id || "node"}_copy`);
  next.title = `${source.title || source.id || "节点"} 副本`;
  next.x = clamp(Number(source.x || 0) + 80, WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X);
  next.y = clamp(Number(source.y || 0) + 80, 0, WORKFLOW_CANVAS_MAX_Y);
  currentAgent.workflow_nodes.push(next);
  selectedWorkflowNodeId = next.id;
  workflowInspectorOpen = true;
  workflowCheckReport = null;
  workflowDryRunReport = null;
  return next;
}

function autoLayoutWorkflow() {
  ensureWorkflow();
  const stageOrder = WORKFLOW_STAGES.map(([id]) => id);
  const rows = new Map(stageOrder.map((stage) => [stage, 0]));
  for (const stage of stageOrder) {
    for (const node of currentAgent.workflow_nodes.filter((item) => workflowStage(item) === stage)) {
      const row = rows.get(stage) || 0;
      node.stage = stage;
      node.x = 70 + stageOrder.indexOf(stage) * WORKFLOW_LANE_WIDTH;
      node.y = 110 + row * 215;
      rows.set(stage, row + 1);
    }
  }
  workflowCheckReport = null;
}

function focusWorkflowStart() {
  const first = currentAgent.workflow_nodes?.find((item) => workflowStage(item) === "entry") || currentAgent.workflow_nodes?.[0];
  workflowZoom = clamp(workflowZoom || 0.85, 0.55, 1);
  const offsetX = workflowWorldOffsetX();
  workflowPanX = first ? Math.round(120 - (Number(first.x || 0) + offsetX) * workflowZoom) : 80;
  workflowPanY = first ? Math.round(180 - Number(first.y || 0) * workflowZoom) : 120;
}

function portFromPoint(clientX, clientY) {
  return document.elementFromPoint(clientX, clientY)?.closest(".node-port") || null;
}

function workflowPortInfo(portEl) {
  if (!portEl) return null;
  const nodeId = portEl.dataset.nodeId || "";
  const item = workflowNodeById(nodeId);
  if (!item) return null;
  const port = portEl.dataset.port === "in" ? "in" : "out";
  return {
    nodeId: item.id,
    port,
    anchor: workflowNodeAnchor(item, port, workflowWorldOffsetX()),
  };
}

function connectWorkflowPorts(start, target) {
  if (!start || !target || start.nodeId === target.nodeId || start.port === target.port) return false;
  const from = start.port === "out" ? start.nodeId : target.nodeId;
  const to = start.port === "out" ? target.nodeId : start.nodeId;
  return addWorkflowEdge(from, to);
}

function setWorkflowConnectingClass(active) {
  document.querySelector(".workflow-canvas")?.classList.toggle("is-connecting", active || Boolean(workflowPendingPort));
}

function setWorkflowRibbonOpen(open) {
  workflowRibbonOpen = Boolean(open);
  document.querySelector(".workflow-page")?.classList.toggle("ribbon-open", workflowRibbonOpen);
}

function highlightWorkflowPendingPort() {
  document.querySelectorAll(".node-port.pending").forEach((item) => item.classList.remove("pending"));
  if (!workflowPendingPort) {
    setWorkflowConnectingClass(false);
    return;
  }
  Array.from(document.querySelectorAll(`.node-port-${workflowPendingPort.port}`))
    .find((item) => item.dataset.nodeId === workflowPendingPort.nodeId)
    ?.classList.add("pending");
  setWorkflowConnectingClass(false);
}

document.addEventListener("pointerdown", (event) => {
  workflowContextMenu = null;
  const inspectorField = event.target.closest?.(".workflow-inspector-drawer input, .workflow-inspector-drawer select, .workflow-inspector-drawer textarea");
  if (inspectorField && route === "workflow") {
    workflowInspectorFocusScrollTop = inspectorField.closest(".drawer-scroll")?.scrollTop || 0;
  }
  if (route === "workflow" && event.target.closest(".workflow-ribbon-hover-zone")) {
    event.preventDefault();
    setWorkflowRibbonOpen(true);
    return;
  }
  const minimapResize = event.target.closest(".workflow-minimap-resize");
  if (minimapResize && route === "workflow") {
    const minimap = minimapResize.closest(".workflow-minimap");
    event.preventDefault();
    workflowMinimapResize = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      baseWidth: workflowMinimapWidth,
      baseHeight: workflowMinimapHeight,
      element: minimap,
    };
    minimapResize.setPointerCapture?.(event.pointerId);
    return;
  }
  const minimap = event.target.closest(".workflow-minimap");
  if (minimap && route === "workflow") {
    event.preventDefault();
    workflowMinimapPan = { pointerId: event.pointerId, element: minimap };
    minimap.setPointerCapture?.(event.pointerId);
    centerWorkflowFromMinimap(event, minimap);
    return;
  }
  const portEl = event.target.closest(".node-port");
  if (portEl && document.querySelector(".workflow-canvas")?.contains(portEl)) {
    const portInfo = workflowPortInfo(portEl);
    if (!portInfo) return;
    event.preventDefault();
    event.stopPropagation();
    if (workflowPendingPort) {
      const samePort = workflowPendingPort.nodeId === portInfo.nodeId && workflowPendingPort.port === portInfo.port;
      const added = !samePort && connectWorkflowPorts(workflowPendingPort, portInfo);
      workflowPendingPort = added || samePort ? null : portInfo;
      refreshWorkflowCanvasDom();
      setFeedback(added ? "连线已创建，保存配置后生效。" : samePort ? "已取消连线起点。" : "已切换连线起点。");
      if (added) render();
      else highlightWorkflowPendingPort();
      return;
    }
    selectedWorkflowNodeId = portInfo.nodeId;
    workflowConnection = {
      nodeId: portInfo.nodeId,
      port: portInfo.port,
      pointerId: event.pointerId,
      anchor: portInfo.anchor,
      pointer: workflowCanvasRenderPoint(event),
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    setWorkflowConnectingClass(true);
    portEl.setPointerCapture?.(event.pointerId);
    refreshWorkflowCanvasDom();
    return;
  }
  const canvasEl = document.querySelector(".workflow-canvas");
  const nodeEl = event.target.closest(".flow-node");
  if (nodeEl && canvasEl?.contains(nodeEl)) {
    const item = workflowNodeById(nodeEl.dataset.id);
    if (!item) return;
    const before = workflowSnapshot();
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
      before,
    };
    nodeEl.setPointerCapture?.(event.pointerId);
    return;
  }
  const wrapEl = event.target.closest(".workflow-canvas-wrap");
  if (!wrapEl || !document.querySelector(".workflow-main-canvas")?.contains(wrapEl)) return;
  if (event.target.closest("[data-action='delete-workflow-edge']")) return;
  event.preventDefault();
  if (workflowSelectionMode) {
    workflowSelectedNodeIds.clear();
    const box = document.createElement("div");
    box.className = "workflow-selection-box";
    document.body.appendChild(box);
    workflowSelectionDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      box,
    };
    wrapEl.setPointerCapture?.(event.pointerId);
    return;
  }
  workflowPan = {
    element: wrapEl,
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    baseX: workflowPanX,
    baseY: workflowPanY,
    moved: false,
  };
  wrapEl.classList.add("is-panning");
  wrapEl.setPointerCapture?.(event.pointerId);
});

document.addEventListener("pointerover", (event) => {
  if (route !== "workflow") return;
  if (event.target.closest(".workflow-ribbon-hover-zone") || event.target.closest(".workflow-page-top")) {
    setWorkflowRibbonOpen(true);
  }
});

document.addEventListener("focusin", (event) => {
  const field = event.target.closest?.(".workflow-inspector-drawer input, .workflow-inspector-drawer select, .workflow-inspector-drawer textarea");
  if (!field || route !== "workflow") return;
  const scroller = field.closest(".drawer-scroll");
  if (!scroller) return;
  const before = scroller.scrollTop;
  const expected = Math.max(before, workflowInspectorFocusScrollTop || 0);
  workflowInspectorScrollTop = before;
  requestAnimationFrame(() => {
    const current = scroller.scrollTop;
    if (document.activeElement === field && expected > 80 && current < expected - 80) {
      scroller.scrollTop = expected;
    }
  });
});

document.addEventListener("input", (event) => {
  const field = event.target.closest?.(".workflow-inspector-drawer input, .workflow-inspector-drawer select, .workflow-inspector-drawer textarea");
  if (!field || route !== "workflow") return;
  workflowInspectorScrollTop = field.closest(".drawer-scroll")?.scrollTop || workflowInspectorScrollTop;
}, true);

document.addEventListener("pointerout", (event) => {
  if (route !== "workflow") return;
  const fromRibbon = event.target.closest(".workflow-ribbon-hover-zone, .workflow-page-top");
  if (!fromRibbon) return;
  const next = event.relatedTarget;
  if (next && document.querySelector(".workflow-page-top")?.contains(next)) return;
  if (next && document.querySelector(".workflow-ribbon-hover-zone")?.contains(next)) return;
  setWorkflowRibbonOpen(false);
});

document.addEventListener("pointermove", (event) => {
  if (workflowMinimapResize && workflowMinimapResize.pointerId === event.pointerId) {
    workflowMinimapWidth = clamp(workflowMinimapResize.baseWidth + event.clientX - workflowMinimapResize.startX, 96, 360);
    workflowMinimapHeight = clamp(workflowMinimapResize.baseHeight + event.clientY - workflowMinimapResize.startY, 72, 260);
    const size = workflowCanvasSize();
    const minimap = document.querySelector(".workflow-minimap");
    if (minimap) minimap.outerHTML = workflowMinimap(size);
    return;
  }
  if (workflowSelectionDrag && workflowSelectionDrag.pointerId === event.pointerId) {
    const left = Math.min(workflowSelectionDrag.startX, event.clientX);
    const top = Math.min(workflowSelectionDrag.startY, event.clientY);
    const width = Math.abs(event.clientX - workflowSelectionDrag.startX);
    const height = Math.abs(event.clientY - workflowSelectionDrag.startY);
    Object.assign(workflowSelectionDrag.box.style, {
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`,
    });
    return;
  }
  if (workflowMinimapPan && workflowMinimapPan.pointerId === event.pointerId) {
    centerWorkflowFromMinimap(event, workflowMinimapPan.element);
    return;
  }
  if (workflowConnection && workflowConnection.pointerId === event.pointerId) {
    const dx = event.clientX - workflowConnection.startX;
    const dy = event.clientY - workflowConnection.startY;
    workflowConnection.moved ||= Math.abs(dx) + Math.abs(dy) > 5;
    workflowConnection.pointer = workflowCanvasRenderPoint(event);
    refreshWorkflowCanvasDom();
    return;
  }
  if (workflowPan && workflowPan.pointerId === event.pointerId) {
    const dx = event.clientX - workflowPan.startX;
    const dy = event.clientY - workflowPan.startY;
    workflowPan.moved ||= Math.abs(dx) + Math.abs(dy) > 5;
    workflowPanX = workflowPan.baseX + dx;
    workflowPanY = workflowPan.baseY + dy;
    refreshWorkflowCanvasDom();
    return;
  }
  if (!workflowDrag || workflowDrag.pointerId !== event.pointerId) return;
  const item = workflowNodeById(workflowDrag.id);
  if (!item) return;
  const dx = event.clientX - workflowDrag.startX;
  const dy = event.clientY - workflowDrag.startY;
  workflowDrag.moved ||= Math.abs(dx) + Math.abs(dy) > 3;
  item.x = clamp(workflowDrag.baseX + dx / workflowZoom, WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X);
  item.y = clamp(workflowDrag.baseY + dy / workflowZoom, 0, WORKFLOW_CANVAS_MAX_Y);
  const offsetX = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  workflowDrag.element.style.left = `${item.x + offsetX}px`;
  workflowDrag.element.style.top = `${item.y}px`;
  refreshWorkflowCanvasDom();
});

document.addEventListener("pointerup", (event) => {
  if (workflowMinimapResize && workflowMinimapResize.pointerId === event.pointerId) {
    workflowMinimapResize = null;
    refreshWorkflowCanvasDom();
    return;
  }
  if (workflowSelectionDrag && workflowSelectionDrag.pointerId === event.pointerId) {
    const rect = workflowSelectionDrag.box.getBoundingClientRect();
    workflowSelectionDrag.box.remove();
    workflowSelectionDrag = null;
    workflowSelectedNodeIds.clear();
    document.querySelectorAll(".flow-node").forEach((node) => {
      const nr = node.getBoundingClientRect();
      const hit = nr.left <= rect.right && nr.right >= rect.left && nr.top <= rect.bottom && nr.bottom >= rect.top;
      node.classList.toggle("multi-selected", hit);
      if (hit && node.dataset.id) workflowSelectedNodeIds.add(node.dataset.id);
    });
    setFeedback(workflowSelectedNodeIds.size ? `已框选 ${workflowSelectedNodeIds.size} 个节点，可复制或删除。` : "没有框选到节点。", workflowSelectedNodeIds.size ? "normal" : "warn");
    return;
  }
  if (workflowMinimapPan && workflowMinimapPan.pointerId === event.pointerId) {
    workflowMinimapPan.element.releasePointerCapture?.(event.pointerId);
    workflowMinimapPan = null;
    refreshWorkflowCanvasDom();
    return;
  }
  if (workflowConnection && workflowConnection.pointerId === event.pointerId) {
    const start = workflowConnection;
    const targetPort = portFromPoint(event.clientX, event.clientY);
    const target = workflowPortInfo(targetPort);
    let added = false;
    let pending = false;
    if (target) {
      added = connectWorkflowPorts(start, target);
      if (!added && !start.moved && target.nodeId === start.nodeId && target.port === start.port) {
        workflowPendingPort = {
          nodeId: start.nodeId,
          port: start.port,
          anchor: start.anchor,
        };
        pending = true;
      }
    } else if (!start.moved) {
      workflowPendingPort = {
        nodeId: start.nodeId,
        port: start.port,
        anchor: start.anchor,
      };
      pending = true;
    }
    workflowConnection = null;
    setWorkflowConnectingClass(false);
    refreshWorkflowCanvasDom();
    setFeedback(added ? "连线已创建，保存配置后生效。" : pending ? "已选中连线起点，再点另一个节点的相反连接点即可完成。" : "未创建连线：请拖到另一个节点的相反连接点。", added || pending ? "normal" : "error");
    if (added) render();
    else if (pending) highlightWorkflowPendingPort();
    return;
  }
  if (workflowPan && workflowPan.pointerId === event.pointerId) {
    workflowPan.element.releasePointerCapture?.(event.pointerId);
    workflowPan.element.classList.remove("is-panning");
    workflowPan = null;
    return;
  }
  if (!workflowDrag || workflowDrag.pointerId !== event.pointerId) return;
  workflowDrag.element.releasePointerCapture?.(event.pointerId);
  if (workflowDrag.moved) {
    if (workflowDrag.before) {
      workflowHistoryPast.push(workflowDrag.before);
      if (workflowHistoryPast.length > 60) workflowHistoryPast.shift();
      workflowHistoryFuture = [];
    }
    workflowSuppressClick = true;
    setFeedback("节点位置已更新，保存配置后生效。");
  }
  workflowDrag = null;
});

document.addEventListener("wheel", (event) => {
  const wrapEl = event.target.closest(".workflow-canvas-wrap");
  if (!wrapEl || route !== "workflow") return;
  event.preventDefault();
  const oldZoom = workflowZoom;
  const delta = event.deltaY > 0 ? -0.08 : 0.08;
  const nextZoom = clamp(oldZoom + delta, 0.35, 1.8);
  if (nextZoom === oldZoom) return;
  const rect = wrapEl.getBoundingClientRect();
  const localX = event.clientX - rect.left;
  const localY = event.clientY - rect.top;
  const worldX = (localX - workflowPanX) / oldZoom;
  const worldY = (localY - workflowPanY) / oldZoom;
  workflowZoom = nextZoom;
  workflowPanX = localX - worldX * nextZoom;
  workflowPanY = localY - worldY * nextZoom;
  refreshWorkflowCanvasDom();
}, { passive: false });

document.addEventListener("contextmenu", (event) => {
  const nodeEl = event.target.closest(".flow-node");
  const canvasEl = document.querySelector(".workflow-main-canvas");
  if (!nodeEl || !canvasEl?.contains(nodeEl)) return;
  event.preventDefault();
  selectedWorkflowNodeId = nodeEl.dataset.id || selectedWorkflowNodeId;
  workflowContextMenu = {
    nodeId: selectedWorkflowNodeId,
    x: event.clientX,
    y: event.clientY,
  };
  render();
});

document.addEventListener("dragstart", (event) => {
  const chip = event.target.closest(".toolbox-chip[draggable='true']");
  if (!chip) return;
  workflowDraggedMaterial = {
    kind: chip.dataset.dragKind || (chip.dataset.action === "add-template-node" ? "template" : "runtime"),
    id: chip.dataset.dragId || chip.dataset.id || "",
    refType: chip.dataset.refType || "",
    refId: chip.dataset.refId || "",
  };
  event.dataTransfer?.setData("application/x-agent-lab-node", JSON.stringify(workflowDraggedMaterial));
  if (event.dataTransfer) event.dataTransfer.effectAllowed = "copy";
});

document.addEventListener("dragover", (event) => {
  const wrap = event.target.closest(".workflow-canvas-wrap");
  if (!wrap || route !== "workflow") return;
  event.preventDefault();
  wrap.classList.add("is-dropping");
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
});

document.addEventListener("dragleave", (event) => {
  const wrap = event.target.closest(".workflow-canvas-wrap");
  if (!wrap) return;
  const related = event.relatedTarget;
  if (related && wrap.contains(related)) return;
  wrap.classList.remove("is-dropping");
});

document.addEventListener("drop", (event) => {
  const wrap = event.target.closest(".workflow-canvas-wrap");
  if (!wrap || route !== "workflow") return;
  event.preventDefault();
  wrap.classList.remove("is-dropping");
  let material = workflowDraggedMaterial;
  const raw = event.dataTransfer?.getData("application/x-agent-lab-node");
  if (raw) {
    try { material = JSON.parse(raw); } catch (_) { material = workflowDraggedMaterial; }
  }
  if (!material) return;
  const point = workflowCanvasPoint(event);
  if (material.kind === "template") addWorkflowTemplateNode(material.id || "plan", point);
  else addRuntimeWorkflowNode(material.refType, material.refId, point);
  workflowDraggedMaterial = null;
  render();
});

document.addEventListener("click", async (event) => {
  if (event.target.closest(".node-port")) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  const target = event.target.closest("[data-route], [data-action]");
  if (!target) return;
  const action = target.dataset.action;
  if (workflowSuppressClick && target.closest(".flow-node")) {
    workflowSuppressClick = false;
    event.preventDefault();
    return;
  }
  workflowSuppressClick = false;
  if (target.dataset.route) {
    if (target.dataset.route === "workflow") workflowNavCollapsed = true;
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
    if (action === "delete-agent") {
      if (!currentAgent.agent_id) throw new Error("当前配置还没有保存，直接新建或切换即可。 ");
      if ((state.agents || []).length <= 1) throw new Error("至少需要保留一个任务模式配置。");
      const name = agentDisplayName(currentAgent);
      if (!confirm(`删除任务模式配置“${name}”？此操作不会删除归档任务和任务记忆。`)) return;
      const result = await api("/api/agents", { method: "DELETE", body: { agent_id: currentAgent.agent_id } });
      if (result.ok === false) throw new Error(result.error || "删除配置失败。");
      selectedAgentId = result.default_agent_id || "";
      setFeedback("任务模式配置已删除。");
      await load();
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
    if (action === "workflow-select-mode") {
      workflowSelectionMode = !workflowSelectionMode;
      setFeedback(workflowSelectionMode ? "框选已开启：在画布空白处拖出选择框。" : "框选已关闭。");
      render();
    }
    if (action === "workflow-undo") {
      const ok = undoWorkflow();
      setFeedback(ok ? "已回到上一步。" : "没有可撤销的操作。", ok ? "normal" : "warn");
      render();
    }
    if (action === "workflow-redo") {
      const ok = redoWorkflow();
      setFeedback(ok ? "已恢复下一步。" : "没有可恢复的操作。", ok ? "normal" : "warn");
      render();
    }
    if (action === "copy-selected-workflow-nodes") {
      if (!workflowSelectedNodeIds.size) return;
      pushWorkflowHistory();
      const ids = Array.from(workflowSelectedNodeIds);
      workflowSelectedNodeIds.clear();
      ids.forEach((id) => {
        const copied = copyWorkflowNodeById(id);
        if (copied) workflowSelectedNodeIds.add(copied.id);
      });
      setFeedback(`已复制 ${workflowSelectedNodeIds.size} 个节点。`);
      render();
    }
    if (action === "delete-selected-workflow-nodes") {
      if (!workflowSelectedNodeIds.size) return;
      pushWorkflowHistory();
      const count = workflowSelectedNodeIds.size;
      Array.from(workflowSelectedNodeIds).forEach((id) => deleteWorkflowNodeById(id));
      workflowSelectedNodeIds.clear();
      workflowInspectorOpen = false;
      setFeedback(`已删除 ${count} 个节点。`);
      render();
    }
    if (action === "toggle-toolbox-group") {
      const group = target.dataset.id || "";
      if (workflowToolboxOpenGroups.has(group)) workflowToolboxOpenGroups.delete(group);
      else workflowToolboxOpenGroups.add(group);
      return;
    }
    if (action === "preview-template-node") {
      const template = WORKFLOW_NODE_TEMPLATES.find((item) => item.id === target.dataset.id) || null;
      workflowMaterialDraft = template ? { ...template, materialKind: "template" } : null;
      setFeedback(template ? "已打开素材预览，拖到画布或点应用节点添加。" : "未找到这个素材。", template ? "normal" : "error");
      renderWorkflowStable();
    }
    if (action === "preview-runtime-node") {
      const runtimeNode = workflowRuntimeModuleNode(target.dataset.refType || "", target.dataset.refId || "");
      workflowMaterialDraft = runtimeNode
        ? { ...runtimeNode, materialKind: "runtime", refType: runtimeNode.ref_type, refId: runtimeNode.ref_id }
        : {
            title: target.dataset.title || target.textContent.trim(),
            instruction: target.dataset.instruction || "这是运行时模块。拖到画布添加，或点应用节点添加到当前视图。",
            materialKind: "runtime",
            refType: target.dataset.refType || "",
            refId: target.dataset.refId || "",
          };
      setFeedback("已打开模块预览，拖到画布或点应用节点添加。");
      renderWorkflowStable();
    }
    if (action === "apply-material-node") {
      if (!workflowMaterialDraft) return;
      if (workflowMaterialDraft.materialKind === "template") addWorkflowTemplateNode(workflowMaterialDraft.id || "plan");
      else addRuntimeWorkflowNode(workflowMaterialDraft.refType, workflowMaterialDraft.refId);
      renderWorkflowStable();
    }
    if (action === "workflow-zoom-in" || action === "workflow-zoom-out" || action === "workflow-zoom-reset" || action === "workflow-fit") {
      readAgentForm();
      if (action === "workflow-zoom-in") workflowZoom = clamp(workflowZoom + 0.1, 0.35, 1.6);
      if (action === "workflow-zoom-out") workflowZoom = clamp(workflowZoom - 0.1, 0.35, 1.6);
      if (action === "workflow-zoom-reset") {
        workflowZoom = 1;
        workflowPanX = 0;
        workflowPanY = 0;
      }
      if (action === "workflow-fit") {
        const size = workflowCanvasSize();
        const wrap = document.querySelector(".workflow-canvas-wrap");
        const widthFit = wrap ? (wrap.clientWidth - 160) / Math.max(size.width, 1) : 0.9;
        workflowZoom = clamp(widthFit, 0.35, 1);
        workflowPanX = 80;
        workflowPanY = 90;
      }
      render();
    }
    if (action === "toggle-workflow-nav") {
      workflowNavCollapsed = !workflowNavCollapsed;
      render();
    }
    if (action === "toggle-workflow-toolbox") {
      workflowToolboxOpen = !workflowToolboxOpen;
      render();
    }
    if (action === "close-workflow-inspector") {
      workflowInspectorOpen = false;
      render();
    }
    if (action === "close-workflow-report") {
      workflowReportOpen = false;
      render();
    }
    if (action === "close-workflow-menu") {
      workflowContextMenu = null;
      render();
    }
    if (action === "copy-workflow-node") {
      readAgentForm();
      pushWorkflowHistory();
      const copied = copyWorkflowNodeById(target.dataset.id || selectedWorkflowNodeId);
      workflowContextMenu = null;
      setFeedback(copied ? "节点已复制，保存配置后生效。" : "未找到要复制的节点。", copied ? "normal" : "error");
      render();
    }
    if (action === "delete-workflow-node-menu") {
      readAgentForm();
      pushWorkflowHistory();
      const ok = deleteWorkflowNodeById(target.dataset.id || selectedWorkflowNodeId);
      workflowContextMenu = null;
      workflowInspectorOpen = false;
      setFeedback(ok ? "节点已删除，保存配置后生效。" : "未找到要删除的节点。", ok ? "normal" : "error");
      render();
    }
    if (action === "check-workflow") {
      readAgentForm();
      const result = await api("/api/workflow/check", { method: "POST", body: { agent: currentAgent } });
      workflowCheckReport = result.workflow || null;
      workflowReportMode = "check";
      workflowReportOpen = true;
      setFeedback(workflowCheckReport?.valid ? "工作流检查通过。" : "工作流检查发现需要修正的环节。", workflowCheckReport?.valid ? "normal" : "error");
      render();
    }
    if (action === "dry-run-workflow") {
      readAgentForm();
      const result = await api("/api/workflow/dry-run", { method: "POST", body: { agent: currentAgent } });
      workflowDryRunReport = result.dry_run || null;
      workflowCheckReport = result.workflow || workflowDryRunReport?.workflow || workflowCheckReport;
      workflowReportMode = "dry_run";
      workflowReportOpen = true;
      setFeedback(workflowDryRunReport?.executable ? "预跑路径可进入，仍需人工确认高风险步骤。" : "预跑发现阻塞，请查看诊断。", workflowDryRunReport?.executable ? "normal" : "error");
      render();
    }
    if (action === "auto-layout-workflow") {
      readAgentForm();
      pushWorkflowHistory();
      autoLayoutWorkflow();
      focusWorkflowStart();
      workflowReportMode = "layout";
      workflowReportOpen = true;
      setFeedback("工作流已按阶段自动整理，保存配置后生效。");
      render();
    }
    if (action === "select-workflow-node") {
      readAgentForm();
      selectedWorkflowNodeId = target.dataset.id;
      workflowInspectorOpen = true;
      workflowContextMenu = null;
      render();
    }
    if (action === "add-workflow-node") {
      readAgentForm();
      ensureWorkflow();
      pushWorkflowHistory();
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
      workflowInspectorOpen = true;
      workflowCheckReport = null;
      workflowDryRunReport = null;
      render();
    }
    if (action === "add-template-node") {
      addWorkflowTemplateNode(target.dataset.id || "plan");
      render();
    }
    if (action === "add-runtime-node") {
      addRuntimeWorkflowNode(target.dataset.refType, target.dataset.refId);
      render();
    }
    if (action === "apply-workflow-template") {
      readAgentForm();
      pushWorkflowHistory();
      applyWorkflowTemplate(target.dataset.id || "linear");
      render();
    }
    if (action === "reset-workflow") {
      readAgentForm();
      pushWorkflowHistory();
      currentAgent.workflow_nodes = defaultWorkflowNodes();
      currentAgent.workflow_edges = defaultWorkflowEdges();
      selectedWorkflowNodeId = "entry";
      workflowCheckReport = null;
      workflowDryRunReport = null;
      setFeedback("已恢复默认工作流。保存方案后生效。");
      focusWorkflowStart();
      render();
    }
    if (action === "apply-workflow-node") {
      readAgentForm();
      ensureWorkflow();
      const node = selectedWorkflowNode();
      pushWorkflowHistory();
      const oldId = node.id;
      const requestedId = normalizeWorkflowId($("workflow-node-id").value);
      const newId = requestedId === oldId ? oldId : uniqueWorkflowNodeId(requestedId);
      const paramsValue = $("workflow-node-params")?.value.trim() || "";
      let parsedParams = null;
      if (paramsValue) {
        try {
          parsedParams = JSON.parse(paramsValue);
        } catch (error) {
          throw new Error("参数 JSON 格式不正确，请检查括号、逗号和引号。");
        }
        if (!parsedParams || typeof parsedParams !== "object" || Array.isArray(parsedParams)) {
          throw new Error("参数 JSON 需要是对象，例如 {\"query\":{\"q\":\"关键词\"}}。");
        }
      }
      node.id = newId;
      node.title = $("workflow-node-title").value.trim() || newId;
      node.kind = $("workflow-node-kind").value;
      node.stage = $("workflow-node-stage").value;
      node.action = $("workflow-node-action").value;
      node.condition = $("workflow-node-condition").value.trim();
      node.description = $("workflow-node-description").value.trim();
      node.instruction = $("workflow-node-instruction").value.trim();
      node.prompt = $("workflow-node-prompt").value.trim();
      const pathValue = $("workflow-node-path")?.value.trim() || "";
      if (/^https?:\/\//i.test(pathValue)) {
        node.url = pathValue;
        delete node.path;
      } else {
        node.path = pathValue;
        delete node.url;
      }
      node.input_variable = $("workflow-node-input-variable")?.value.trim() || "";
      node.output_variable = $("workflow-node-output-variable")?.value.trim() || "";
      node.tags = linesToList($("workflow-node-tags")?.value || "");
      delete node.tool_args;
      delete node.arguments;
      delete node.api_payload;
      delete node.payload;
      delete node.params;
      if (parsedParams) {
        const serializedParams = JSON.stringify(parsedParams);
        if (node.action === "call_api" || node.kind === "api") node.api_payload = serializedParams;
        else if (node.action === "run_tools" || node.kind === "tool") node.tool_args = serializedParams;
        else node.params = serializedParams;
      }
      if ($("workflow-entry-trigger-phrases")) currentAgent.entry_policy.trigger_phrases = linesToList($("workflow-entry-trigger-phrases").value);
      if ($("workflow-entry-trigger-keywords")) currentAgent.entry_policy.trigger_keywords = linesToList($("workflow-entry-trigger-keywords").value);
      if ($("workflow-entry-confirmation-text")) currentAgent.entry_policy.confirmation_text = $("workflow-entry-confirmation-text").value.trim();
      if ($("workflow-exit-phrases")) currentAgent.entry_policy.exit_phrases = linesToList($("workflow-exit-phrases").value);
      if ($("workflow-default-completion-conditions")) currentAgent.entry_policy.default_completion_conditions = linesToList($("workflow-default-completion-conditions").value);
      node.x = clamp(Number($("workflow-node-x")?.value || node.x || 0), WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X);
      node.y = clamp(Number($("workflow-node-y")?.value || node.y || 0), 0, WORKFLOW_CANVAS_MAX_Y);
      currentAgent.workflow_edges = currentAgent.workflow_edges.map((edge) => ({
        from: edge.from === oldId ? newId : edge.from,
        to: edge.to === oldId ? newId : edge.to,
      }));
      selectedWorkflowNodeId = newId;
      workflowCheckReport = null;
      workflowDryRunReport = null;
      setFeedback("节点配置已应用。保存方案后生效。");
      render();
    }
    if (action === "delete-workflow-node") {
      readAgentForm();
      pushWorkflowHistory();
      deleteWorkflowNodeById(selectedWorkflowNodeId);
      workflowInspectorOpen = false;
      render();
    }
    if (action === "add-workflow-edge") {
      readAgentForm();
      ensureWorkflow();
      const from = $("workflow-edge-from").value;
      const to = $("workflow-edge-to").value;
      addWorkflowEdge(from, to);
      workflowDryRunReport = null;
      render();
    }
    if (action === "delete-workflow-edge") {
      readAgentForm();
      pushWorkflowHistory();
      currentAgent.workflow_edges.splice(Number(target.dataset.index), 1);
      workflowCheckReport = null;
      workflowDryRunReport = null;
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
    if (action === "select-memory") {
      selectedMemoryId = target.dataset.id || "";
      render();
    }
    if (action === "use-memory-context") {
      const item = (state.memories || []).find((row) => row.memory_id === target.dataset.id);
      if (!item) throw new Error("未找到这条任务记忆。");
      route = "tasks";
      render();
      requestAnimationFrame(() => {
        const brief = $("brief");
        if (brief) brief.value = memoryContextText(item);
      });
      setFeedback("已把任务记忆带入新任务入口。");
    }
    if (action === "open-memory-source") {
      selectedTaskId = target.dataset.id || selectedTaskId;
      route = "tasks";
      render();
    }
    if (action === "restore-archive-context") {
      const task = [...(state.tasks || []), ...(state.archives || [])].find((item) => item.task_id === target.dataset.id);
      if (!task) throw new Error("未找到这条归档任务。");
      const memory = (state.memories || []).find((item) => item.memory_id === selectedMemoryId) || null;
      route = "tasks";
      render();
      requestAnimationFrame(() => {
        const brief = $("brief");
        if (brief) brief.value = taskRollbackContextText(task, memory);
      });
      setFeedback("已把归档任务回档信息带入新任务入口。");
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
    if (target.dataset.action === "workflow-agent-select") {
    readAgentForm();
    selectedAgentId = target.value;
    currentAgent = ensureAgent(clone((state.agents || []).find((item) => item.agent_id === selectedAgentId) || currentAgent));
    selectedWorkflowNodeId = currentAgent.workflow_nodes?.[0]?.id || "";
    workflowCheckReport = null;
    workflowDryRunReport = null;
    workflowViewportInitialized = false;
    render();
  }
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
  if (target.dataset.action === "filter-workflow-materials") {
    workflowMaterialFilter = target.value;
    renderWorkflowFilterInput("filter-workflow-materials", workflowMaterialFilter);
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
