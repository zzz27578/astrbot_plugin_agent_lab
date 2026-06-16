// Agent Lab WebUI
const $ = (id) => document.getElementById(id);
const AGENT_LAB_WEBUI_BUILD = "20260615-fix7";
try { console.log("[Agent Lab webui] build " + AGENT_LAB_WEBUI_BUILD + " loaded"); } catch (e) {}
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
  pointer: `${GAME_ICON_BASE}/3.Editing%20Tools/select.svg`,
  select: `${GAME_ICON_BASE}/3.Editing%20Tools/select.svg`,
  copy: `${GAME_ICON_BASE}/3.Editing%20Tools/copy.svg`,
  trash: `${GAME_ICON_BASE}/2.Media%20%26%20Technology/trash.svg`,
  undo: `${GAME_ICON_BASE}/3.Editing%20Tools/undo.svg`,
  redo: `${GAME_ICON_BASE}/3.Editing%20Tools/redo.svg`,
  refresh: `${GAME_ICON_BASE}/3.Editing%20Tools/redo.svg`,
  tool: `${GAME_ICON_BASE}/6.Items/tool-kit.svg`,
  book: `${GAME_ICON_BASE}/6.Items/book.svg`,
  memory: `${GAME_ICON_BASE}/2.Media%20%26%20Technology/memory-card.svg`,
};

const WORKFLOW_STAGES = [
  ["entry", "入口", "压缩上下文"],
  ["plan", "计划", "拆解任务"],
  ["execute", "执行", "调用工具"],
  ["guard", "闸门", "审批/人工"],
  ["checkpoint", "记录", "保存进度"],
  ["archive", "出口", "归档回流"],
];

const WORKFLOW_NODE_WIDTH = 340;
const WORKFLOW_NODE_HEIGHT = 208;
const WORKFLOW_NODE_BORDER = 5; // .flow-node 左侧色条边框宽度，用于把左侧连接点锚点与圆点对齐
const WORKFLOW_LANE_WIDTH = 640;
const WORKFLOW_CANVAS_MIN_WIDTH = 24000;
const WORKFLOW_CANVAS_MIN_HEIGHT = 10400;
const WORKFLOW_CANVAS_MIN_X = -32000;
const WORKFLOW_CANVAS_MAX_X = 96000;
const WORKFLOW_CANVAS_MIN_Y = -24000;
const WORKFLOW_CANVAS_MAX_Y = 64000;
const WORKFLOW_WORLD_WIDTH = WORKFLOW_CANVAS_MAX_X - WORKFLOW_CANVAS_MIN_X;
const WORKFLOW_WORLD_HEIGHT = WORKFLOW_CANVAS_MAX_Y - WORKFLOW_CANVAS_MIN_Y;
const WORKFLOW_MINIMAP_MIN_WIDTH = 104;
const WORKFLOW_MINIMAP_MIN_HEIGHT = 84;
const WORKFLOW_MINIMAP_MAX_WIDTH = 360;
const WORKFLOW_MINIMAP_MAX_HEIGHT = 260;
const WORKFLOW_FIELD_SELECTOR = ".workflow-page input, .workflow-page select, .workflow-page textarea";
const WORKFLOW_CANVAS_BLOCKER_SELECTOR = ".workflow-tool-drawer, .workflow-inspector-drawer, .workflow-page-top, .workflow-context-menu, .workflow-report-panel, .workflow-minimap, .workflow-nav-toggle, .workflow-right-dock";
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
  "trigger",
  "detector",
  "report",
  "rate_limit",
  "error_handler",
];
const WORKFLOW_ACTIONS = [
  "listen_message",
  "match_keyword",
  "match_regex",
  "llm_detect",
  "scope_filter",
  "schedule_trigger",
  "plugin_event_trigger",
  "webhook_trigger",
  "limit_rate",
  "catch_error",
  "write_record",
  "generate_report",
  "send_message",
  "send_private_message",
  "send_email",
  "plugin_prompt",
  "confirm_entry",
  "summarize_entry",
  "restore_isolation",
  "variable_set",
  "variable_get",
  "text_template",
  "json_transform",
  "merge",
  "iterator",
  "subflow_call",
  "plan",
  "route_condition",
  "conditional_router",
  "parallel_branch",
  "run_tools",
  "call_api",
  "http_request",
  "file_operation",
  "code_exec",
  "transform_context",
  "retrieve_memory",
  "memory_filter",
  "summarize_memory",
  "export_task_memory",
  "promote_memory_candidate",
  "forget_task_memory",
  "archive_memory_folder",
  "request_approval",
  "wait_user",
  "handoff",
  "validate_output",
  "debate_validation",
  "retry",
  "save_state",
  "save_memory",
  "heartbeat",
  "notify",
  "archive",
  "exit_summary",
  "credential_ref",
  "cookie_jar",
  "browser_profile",
  "login_flow",
  "session_check",
  "refresh_session",
  "credential_scope",
  "human_login_handoff",
  "revoke_session",
  "global_control",
  "skill_evolution",
  "agent_role",
  "api_scope",
  "prompt_inject",
  "manual",
];
const WORKFLOW_PERMISSION_PROFILES = ["ordinary", "work", "code", "web", "danger"];
const WORKFLOW_REF_TYPES = ["", "tool", "api", "plugin", "skill", "module", "workflow", "sub_agent"];
const WORKFLOW_WORKER_TYPES = ["", "GenericWorker", "ResearchWorker", "CodeReaderWorker", "PatchWorker", "TestWorker", "ApiWorker", "ToolWorker"];
const WORKFLOW_TRIGGER_TYPES = ["command", "natural", "silent_global", "message_monitor", "keyword", "regex", "poke", "notice", "schedule", "plugin_event", "webhook", "manual_webui"];
const WORKFLOW_MESSAGE_TRIGGER_TYPES = ["command", "natural", "silent_global", "message_monitor", "keyword", "regex", "poke", "notice", "manual_webui"];
const WORKFLOW_CHAT_TYPES = ["private", "group"];
const WORKFLOW_EDGE_TYPES = ["success", "failed", "uncertain", "retry", "approved", "rejected"];

const WORKFLOW_ACTION_RUNTIME_TYPES = {
  listen_message: "trigger",
  schedule_trigger: "trigger",
  plugin_event_trigger: "trigger",
  webhook_trigger: "trigger",
  match_keyword: "detector",
  match_regex: "detector",
  llm_detect: "detector",
  scope_filter: "detector",
  limit_rate: "guard",
  catch_error: "decision",
  write_record: "report",
  generate_report: "report",
  send_message: "notification",
  send_private_message: "notification",
  send_email: "notification",
  plugin_prompt: "react",
  summarize_entry: "entry",
  confirm_entry: "entry",
  restore_isolation: "entry",
  variable_set: "state",
  variable_get: "state",
  text_template: "state",
  json_transform: "state",
  merge: "state",
  iterator: "state",
  subflow_call: "state",
  retrieve_memory: "memory",
  memory_filter: "memory",
  summarize_memory: "memory",
  export_task_memory: "memory",
  promote_memory_candidate: "memory",
  forget_task_memory: "memory",
  archive_memory_folder: "memory",
  save_memory: "memory",
  save_state: "state",
  heartbeat: "state",
  transform_context: "state",
  route_condition: "decision",
  conditional_router: "decision",
  parallel_branch: "parallel",
  run_tools: "tool",
  call_api: "api",
  http_request: "api",
  file_operation: "tool",
  code_exec: "tool",
  request_approval: "guard",
  wait_user: "guard",
  handoff: "guard",
  validate_output: "validation",
  debate_validation: "validation",
  retry: "decision",
  notify: "notification",
  archive: "terminal",
  exit_summary: "terminal",
  credential_ref: "guard",
  cookie_jar: "guard",
  browser_profile: "guard",
  login_flow: "guard",
  session_check: "guard",
  refresh_session: "guard",
  credential_scope: "guard",
  human_login_handoff: "guard",
  revoke_session: "guard",
  global_control: "guard",
  skill_evolution: "guard",
  agent_role: "state",
  api_scope: "api",
  prompt_inject: "state",
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
  trigger: "trigger",
  detector: "detector",
  report: "report",
  rate_limit: "guard",
  error_handler: "decision",
};
const WORKFLOW_EXECUTABLE_ACTIONS = new Set([
  "listen_message",
  "schedule_trigger",
  "plugin_event_trigger",
  "webhook_trigger",
  "match_keyword",
  "match_regex",
  "llm_detect",
  "scope_filter",
  "limit_rate",
  "catch_error",
  "write_record",
  "generate_report",
  "send_message",
  "send_private_message",
  "send_email",
  "plugin_prompt",
  "summarize_entry",
  "confirm_entry",
  "restore_isolation",
  "save_state",
  "heartbeat",
  "transform_context",
  "variable_set",
  "variable_get",
  "text_template",
  "json_transform",
  "merge",
  "iterator",
  "subflow_call",
  "retrieve_memory",
  "memory_filter",
  "summarize_memory",
  "export_task_memory",
  "promote_memory_candidate",
  "forget_task_memory",
  "archive_memory_folder",
  "save_memory",
  "parallel_branch",
  "call_api",
  "http_request",
  "run_tools",
  "file_operation",
  "code_exec",
  "route_condition",
  "conditional_router",
  "retry",
  "validate_output",
  "debate_validation",
  "request_approval",
  "wait_user",
  "handoff",
  "notify",
  "archive",
  "exit_summary",
  "credential_ref",
  "cookie_jar",
  "browser_profile",
  "login_flow",
  "session_check",
  "refresh_session",
  "credential_scope",
  "human_login_handoff",
  "revoke_session",
  "global_control",
  "skill_evolution",
  "agent_role",
  "api_scope",
  "prompt_inject",
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
  trigger: "触发",
  detector: "检测",
  report: "报告",
};
const WORKFLOW_NODE_GROUPS = [
  { id: "trigger_monitor", title: "触发与监听", hint: "命令、消息监听、关键词、正则、定时、插件事件和 Webhook。", icon: "book", open: true },
  { id: "detect_route", title: "检测与路由", hint: "规则检测、LLM 检测、范围过滤、通过/失败/不确定分流。", icon: "select", open: true },
  { id: "report_control", title: "报告与控制", hint: "限流、错误处理、报告、私信、邮件和记录写入。", icon: "copy", open: false },
  { id: "entry_context", title: "开始与上下文", hint: "入口命令、确认、摘要和任务隔离。", icon: "book", open: true },
  { id: "plan_route", title: "计划与分支", hint: "拆解任务、选择路线、控制重试。", icon: "gridAdd", open: true },
  { id: "tool_exec", title: "执行工具", hint: "绑定 AstrBot 工具并把结果写入状态。", icon: "tool", open: true },
  { id: "api_external", title: "API 与外部系统", hint: "一次 API 调用和 API 作用范围分开管理。", icon: "gridAdd", open: false },
  { id: "data_template", title: "数据与模板", hint: "变量、文本模板、JSON 转换、合并和迭代准备。", icon: "copy", open: false },
  { id: "memory_state", title: "记忆与回写", hint: "读取任务记忆，保存进度和完成记录。", icon: "memory", open: true },
  { id: "safety_human", title: "审批与安全", hint: "高风险动作、人工接管、范围锁定。", icon: "select", open: false },
  { id: "account_identity", title: "账号与登录态", hint: "绑定 GitHub / B站 等账号凭证、检查登录、人工扫码、用完注销。", icon: "select", open: false },
  { id: "validate_exit", title: "校验与出口", hint: "验收、通知、归档和退出回流。", icon: "copy", open: false },
  { id: "parallel_pack", title: "并行工作包", hint: "可拆给并行 Agent 的只读/复核/汇总单元。", icon: "gridAdd", open: false },
  { id: "agent_collab", title: "Agent 编排", hint: "Agent 角色、领地、任务分配、报告整理、意见传达、事项讨论、汇总决策。", icon: "gridAdd", open: false },
  { id: "flow_timing", title: "时序与辅助", hint: "延时/暂停等流程控制素材。", icon: "gridAdd", open: false },
];
const WORKFLOW_LIBRARY_GROUP_ALIASES = {
  "入口": "entry_context",
  "输入": "entry_context",
  "隔离": "entry_context",
  "计划": "plan_route",
  "工具": "tool_exec",
  "API": "api_external",
  "记忆": "memory_state",
  "变量": "data_template",
  "数据": "data_template",
  "模板": "data_template",
  "安全": "safety_human",
  "控制": "report_control",
  "验证": "validate_exit",
  "出口": "validate_exit",
  "并行": "parallel_pack",
  "Agent": "agent_collab",
  "协同": "agent_collab",
};

const WORKFLOW_MERGED_TEMPLATE_IDS = new Set([
  "entry_gate",
  "isolation_gate",
  "scope_lock",
  "memory_read",
  "memory_expose",
  "memory_rollback",
  "todo_split",
  "api_payload_builder",
  "api_write_guard",
  "rollback_plan",
  "acceptance_check",
  "message_listener",
  "merge_results",
  "cancel_exit",
]);

const WORKFLOW_LEGACY_NODE_MIGRATIONS = {
  command_entry: { title: "消息监听入口", kind: "trigger", stage: "entry", action: "listen_message", library_group: "trigger_monitor" },
  keyword_entry: { title: "消息监听入口", kind: "trigger", stage: "entry", action: "listen_message", library_group: "trigger_monitor" },
  manual_webui_entry: { title: "消息监听入口", kind: "trigger", stage: "entry", action: "listen_message", library_group: "trigger_monitor" },
  entry_gate: { title: "消息监听入口", kind: "trigger", stage: "entry", action: "listen_message", library_group: "trigger_monitor", require_confirmation: true },
  isolation_gate: { title: "全局控制", kind: "guard", stage: "guard", action: "global_control", library_group: "控制", isolation_mode: "strict" },
  scope_lock: { title: "全局控制", kind: "guard", stage: "guard", action: "global_control", library_group: "控制", tool_mode: "whitelist" },
  memory_read: { title: "任务记忆读取", kind: "retrieval", stage: "plan", action: "retrieve_memory", library_group: "记忆" },
  memory_expose: { title: "保存任务记忆", kind: "memory", stage: "checkpoint", action: "save_memory", library_group: "记忆", expose_to_normal: true },
  memory_rollback: { title: "任务记忆读取", kind: "retrieval", stage: "plan", action: "retrieve_memory", library_group: "记忆" },
  memory_filter: { title: "记忆过滤器", kind: "memory", stage: "entry", action: "memory_filter", library_group: "记忆" },
  document_source: { title: "文档/路径输入", kind: "transform", stage: "plan", action: "variable_set", library_group: "变量", variable_name: "document.source" },
  todo_split: { title: "上下文整理", kind: "transform", stage: "execute", action: "transform_context", library_group: "计划" },
  api_payload_builder: { title: "上下文整理", kind: "transform", stage: "execute", action: "transform_context", library_group: "API" },
  api_write_guard: { title: "审批闸门", kind: "guard", stage: "guard", action: "request_approval", library_group: "安全" },
  rollback_plan: { title: "审批闸门", kind: "guard", stage: "guard", action: "request_approval", library_group: "安全" },
  acceptance_check: { title: "结果校验", kind: "validation", stage: "checkpoint", action: "validate_output", library_group: "验证" },
  file_patch: { title: "文件操作", kind: "tool", stage: "execute", action: "file_operation", library_group: "工具" },
  shell_test: { title: "命令验证", kind: "tool", stage: "checkpoint", action: "code_exec", library_group: "验证", language: "shell" },
};

const WORKFLOW_NODE_TEMPLATES = [
  {
    id: "agent_role",
    title: "注册新 Agent",
    kind: "state",
    stage: "plan",
    action: "agent_role",
    library_group: "agent_collab",
    instruction: "在画布上声明一个 Agent 角色块，可配置模型、颜色、提示词、工具范围、并发和限速。",
    color: "#5b8def",
    role_prompt: "",
    enabled_tools: [],
    max_concurrency: 2,
    rate_per_minute: 0,
  },
  {
    id: "main_agent",
    title: "主 Agent",
    kind: "state",
    stage: "plan",
    action: "agent_role",
    main_agent: true,
    library_group: "agent_collab",
    instruction: "主 Agent：全局调度、汇总子 Agent 结果。可设模型/颜色/提示词，并圈定自己直管的领地。",
    color: "#7c5cff",
    role_prompt: "",
    enabled_tools: [],
    max_concurrency: 4,
    rate_per_minute: 0,
  },
  {
    id: "api_scope",
    title: "API 作用范围",
    kind: "api",
    stage: "plan",
    action: "api_scope",
    library_group: "api_external",
    instruction: "为一组节点声明默认 API，和一次性 API 调用分开管理。",
    api_id: "",
    scope_mode: "selected",
    scope_node_ids: [],
    output_variable: "workflow.api_scope",
  },
  {
    id: "prompt_inject",
    title: "提示注入",
    kind: "state",
    stage: "plan",
    action: "prompt_inject",
    library_group: "flow_timing",
    instruction: "把局部提示写入后续执行上下文，影响后续节点或 Agent。",
    inject_text: "",
    inject_scope: "downstream",
  },
  {
    id: "delay",
    title: "延时",
    kind: "state",
    stage: "execute",
    action: "delay",
    library_group: "flow_timing",
    instruction: "等待 N 秒再继续，用于错峰 / 限频手动节流。",
    delay_seconds: 5,
  },
  {
    id: "note",
    title: "提示注入",
    kind: "state",
    stage: "plan",
    action: "prompt_inject",
    library_group: "flow_timing",
    instruction: "兼容旧便签素材：现在会把文本注入后续执行上下文。",
    inject_text: "",
    inject_scope: "downstream",
  },
  {
    id: "dispatch_tasks",
    title: "任务分配",
    kind: "branch",
    stage: "execute",
    action: "dispatch_tasks",
    library_group: "agent_collab",
    instruction: "主agent 把任务拆成 assignment，按领地/子Agent 指派，写入共享黑板。",
    assignments: [{ sub_agent_id: "", instruction: "", resource_tags: "" }],
  },
  {
    id: "collect_report",
    title: "报告整理",
    kind: "report",
    stage: "checkpoint",
    action: "collect_report",
    library_group: "agent_collab",
    instruction: "收齐子Agent 并行输出，按 owner 汇成结构化报告写入共享黑板。",
  },
  {
    id: "agent_message",
    title: "意见传达",
    kind: "notification",
    stage: "execute",
    action: "agent_message",
    library_group: "agent_collab",
    instruction: "向某个子Agent 的信箱投递一条意见或指令。",
    target_sub_agent: "",
    message: "",
  },
  {
    id: "agent_debate",
    title: "事项讨论",
    kind: "validation",
    stage: "checkpoint",
    action: "agent_debate",
    library_group: "agent_collab",
    instruction: "让多个子Agent 从不同视角互相质询/校验不确定结论（复用 debate 校验）。",
    perspectives: ["correctness", "safety", "completion"],
  },
  {
    id: "summarize_decision",
    title: "汇总决策",
    kind: "branch",
    stage: "checkpoint",
    action: "summarize_decision",
    library_group: "agent_collab",
    instruction: "主agent 读共享黑板做下一步决策，输出 next_step（决策依据自动汇总）。",
    next_step: "",
  },
  {
    id: "entry",
    title: "消息监听入口",
    kind: "trigger",
    stage: "entry",
    action: "listen_message",
    library_group: "trigger_monitor",
    instruction: "统一承接命令、关键词、自然语言、拍一拍、notice、WebUI、插件事件和 webhook 触发。",
    output_variable: "event.message",
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
    instruction: "只在失败/出错时进入：还有次数就从『重试』出口绕回上一步重试；用尽后从『失败』出口交人工。成功不该走这里。",
    max_retries: 3,
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
    id: "document_source",
    advanced: true,
    title: "文档/路径输入",
    kind: "transform",
    stage: "plan",
    action: "variable_set",
    library_group: "变量",
    instruction: "把文件路径、文档 URL 或上游变量写入工作流变量，供后续工具、API 或记忆节点读取。",
    variable_name: "document.source",
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
    action: "memory_filter",
    library_group: "记忆",
    instruction: "设定进入任务的记忆准入白/黑名单，决定任务中是否屏蔽日常记忆，并限定成果回流的暴露范围（防止记忆串联）。",
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
    id: "variable_set",
    advanced: true,
    title: "设置变量",
    kind: "transform",
    stage: "execute",
    action: "variable_set",
    library_group: "变量",
    instruction: "将数据存入工作流变量，供后续节点读取或作为最终输出。",
  },
  {
    id: "variable_get",
    advanced: true,
    title: "读取变量",
    kind: "transform",
    stage: "execute",
    action: "variable_get",
    library_group: "变量",
    instruction: "从工作流变量中读取之前存储的数据。",
  },
  {
    id: "text_template",
    title: "文本模板",
    kind: "transform",
    stage: "execute",
    action: "text_template",
    library_group: "变量",
    instruction: "使用模板语法将变量插入文本，生成动态内容。",
  },
  {
    id: "json_transform",
    advanced: true,
    title: "JSON转换",
    kind: "transform",
    stage: "execute",
    action: "json_transform",
    library_group: "变量",
    instruction: "解析、提取、转换或重组 JSON 数据结构。",
  },
  {
    id: "merge",
    advanced: true,
    title: "合并数据",
    kind: "transform",
    stage: "execute",
    action: "merge",
    library_group: "变量",
    instruction: "将多个数据源或上游节点输出合并为单一数据结构。",
  },
  {
    id: "iterator",
    advanced: true,
    title: "迭代器",
    kind: "branch",
    stage: "execute",
    action: "iterator",
    library_group: "变量",
    instruction: "对数组或列表中的每个元素执行相同的处理流程。",
  },
  {
    id: "debate_validation",
    title: "辩论验证",
    kind: "validation",
    stage: "execute",
    action: "debate_validation",
    library_group: "变量",
    instruction: "通过多角度辩论验证结果的正确性和完整性。",
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
    title: "文件操作",
    kind: "tool",
    stage: "execute",
    action: "file_operation",
    library_group: "工具",
    instruction: "按受控路径执行读、写、替换或追加，并把结果写回任务状态。",
  },
  {
    id: "shell_test",
    title: "命令验证",
    kind: "tool",
    stage: "checkpoint",
    action: "code_exec",
    library_group: "验证",
    instruction: "运行格式检查、单测、烟测或项目命令，把命令、结果和失败原因写回任务状态。",
    language: "shell",
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
  {
    id: "message_listener",
    title: "消息监听入口",
    kind: "trigger",
    stage: "entry",
    action: "listen_message",
    library_group: "trigger_monitor",
    instruction: "监听私聊或群聊消息，只把命中工作流范围和触发条件的事件送入后续检测器。",
    output_variable: "event.message",
    output_schema: { type: "object", properties: { text: { type: "string" }, sender_id: { type: "string" }, group_id: { type: "string" } } },
  },
  {
    id: "keyword_detector",
    title: "关键词检测器",
    kind: "detector",
    stage: "plan",
    action: "match_keyword",
    library_group: "detect_route",
    instruction: "按关键词命中/未命中分流，建议连 success 到动作，failed 到忽略或报告。",
    params: { keywords: ["广告", "垃圾话", "违禁词"] },
    output_variable: "detector.keyword",
    output_schema: { type: "object", properties: { passed: { type: "boolean" }, matched: { type: "array" } } },
  },
  {
    id: "regex_detector",
    title: "正则检测器",
    kind: "detector",
    stage: "plan",
    action: "match_regex",
    library_group: "detect_route",
    instruction: "用正则表达式识别更复杂的模式，例如链接刷屏、重复字符、编号或命令格式。",
    params: { patterns: ["https?://", "(.)\\1{6,}"] },
    output_variable: "detector.regex",
  },
  {
    id: "llm_detector",
    title: "LLM 约束检测器",
    kind: "detector",
    stage: "plan",
    action: "llm_detect",
    library_group: "detect_route",
    instruction: "让 LLM 按模板判断是否通过，不自由发挥；输出必须含 passed、reason、confidence、route。",
    prompt: "你是受约束的检测器。只判断输入是否符合规则，不执行动作。输出 JSON：{passed:boolean, reason:string, confidence:number, route:'success'|'failed'|'uncertain'}。",
    output_schema: { type: "object", required: ["passed", "reason", "confidence", "route"] },
  },
  {
    id: "scope_filter",
    title: "范围过滤器",
    kind: "detector",
    stage: "entry",
    action: "scope_filter",
    library_group: "detect_route",
    instruction: "按私聊/群聊、白名单、黑名单、管理员限制过滤事件；未通过直接走 failed 或 ignored 路线。",
  },
  {
    id: "plugin_event_trigger",
    title: "插件事件入口",
    kind: "trigger",
    stage: "entry",
    action: "plugin_event_trigger",
    library_group: "trigger_monitor",
    instruction: "把其他 AstrBot 插件的事件作为工作流入口，用于跨插件联动而不是互相硬兼容。",
    ref_type: "plugin",
  },
  {
    id: "schedule_trigger",
    title: "复杂定时入口",
    kind: "trigger",
    stage: "entry",
    action: "schedule_trigger",
    library_group: "trigger_monitor",
    instruction: "按 cron 或外部计划触发工作流，可替代简单定时任务，后续仍能接检测、审批、报告。",
    cron: "*/15 * * * *",
    params: { cron: "*/15 * * * *" },
  },
  {
    id: "webhook_trigger",
    title: "Webhook 入口",
    kind: "trigger",
    stage: "entry",
    action: "webhook_trigger",
    library_group: "trigger_monitor",
    instruction: "外部系统通过 Webhook 调用触发工作流；只承接 Webhook 入口，配置路径与鉴权。",
    webhook_path: "/agent-lab/webhook",
    auth_type: "none",
  },
  {
    id: "rate_limit_guard",
    title: "限流/冷却模块",
    kind: "rate_limit",
    stage: "guard",
    action: "limit_rate",
    library_group: "report_control",
    instruction: "限制同一群、同一用户或同一关键词在时间窗口内重复触发，避免刷屏或循环调用。",
    params: { window_seconds: 60, max_hits: 3 },
  },
  {
    id: "catch_error",
    title: "错误捕获出口",
    kind: "error_handler",
    stage: "checkpoint",
    action: "catch_error",
    library_group: "report_control",
    instruction: "把工具/API/插件调用失败统一收束到 error 路线，可继续重试、通知管理员或生成报告。",
  },
  {
    id: "workflow_report",
    title: "生成运行报告",
    kind: "report",
    stage: "archive",
    action: "generate_report",
    library_group: "report_control",
    instruction: "汇总触发原因、检测结果、调用链、失败重试和最终动作，返回给用户或管理员。",
    output_variable: "report.summary",
  },
  {
    id: "private_message",
    title: "发送私信",
    kind: "notification",
    stage: "archive",
    action: "send_private_message",
    library_group: "report_control",
    instruction: "向触发者、管理员或指定 QQ 发送私信，例如封禁报告、误报说明或人工处理请求。",
  },
  {
    id: "email_notice",
    title: "发送邮件",
    kind: "notification",
    stage: "archive",
    action: "send_email",
    library_group: "report_control",
    instruction: "把工作流报告发送到邮箱，用于值班、审计或跨平台提醒。",
  },
  {
    id: "account_credential",
    title: "账号凭证",
    kind: "guard",
    stage: "guard",
    action: "credential_ref",
    library_group: "安全",
    instruction: "引用一个已保存的账号/凭证（GitHub 令牌、接口密钥等），只引用不显示密钥。",
  },
  {
    id: "account_login_check",
    title: "登录态检查",
    kind: "guard",
    stage: "guard",
    action: "session_check",
    library_group: "安全",
    instruction: "检查某账号当前登录是否有效：有效走成功，失效走失败（可连重新登录或通知）。",
  },
  {
    id: "account_login_flow",
    title: "登录流程",
    kind: "guard",
    stage: "guard",
    action: "login_flow",
    library_group: "安全",
    instruction: "协调某网站的登录；遇验证码/二次验证时配合人工登录交接。",
  },
  {
    id: "account_human_login",
    title: "人工登录交接",
    kind: "human",
    stage: "guard",
    action: "human_login_handoff",
    library_group: "安全",
    instruction: "暂停，等用户完成扫码/验证码/二次验证后再继续。",
    prompt: "请用户在浏览器里完成登录或验证，完成后回复继续。",
  },
  {
    id: "account_cookie",
    title: "Cookie 登录态",
    kind: "guard",
    stage: "guard",
    action: "cookie_jar",
    library_group: "安全",
    instruction: "为需要登录的站点附加一个已保存的 Cookie 引用（如 B站点赞）。",
  },
  {
    id: "account_revoke",
    title: "注销会话",
    kind: "guard",
    stage: "archive",
    action: "revoke_session",
    library_group: "安全",
    instruction: "任务做完后注销/解绑这个账号会话，避免登录态长期挂着。",
  },
  {
    id: "refresh_session",
    title: "刷新会话",
    kind: "guard",
    stage: "guard",
    action: "refresh_session",
    library_group: "安全",
    instruction: "主动刷新账号会话/令牌，避免过期失效；适合长任务开始前预防性刷新。",
  },
  {
    id: "browser_profile",
    title: "浏览器配置",
    kind: "guard",
    stage: "guard",
    action: "browser_profile",
    library_group: "安全",
    instruction: "为浏览器自动化指定 profile（指纹、UA、代理），隔离不同账号或模拟真实用户。",
  },
  {
    id: "credential_scope",
    title: "凭证范围",
    kind: "guard",
    stage: "guard",
    action: "credential_scope",
    library_group: "安全",
    instruction: "限定凭证的作用域（只读、只写、特定资源），防止误操作或权限滥用。",
  },
  {
    id: "summarize_memory",
    title: "总结记忆",
    kind: "memory",
    stage: "checkpoint",
    action: "summarize_memory",
    library_group: "记忆",
    instruction: "对任务执行过程的关键信息进行提炼总结，生成可复用的结构化记忆。",
  },
  {
    id: "forget_task_memory",
    title: "遗忘记忆",
    kind: "memory",
    stage: "checkpoint",
    action: "forget_task_memory",
    library_group: "记忆",
    instruction: "标记并清除已过期、错误或不再需要的任务记忆，保持记忆库整洁。",
  },
  {
    id: "promote_memory_candidate",
    title: "提升候选记忆",
    kind: "memory",
    stage: "checkpoint",
    action: "promote_memory_candidate",
    library_group: "记忆",
    instruction: "将候选记忆（candidate_memory）验证后提升为正式记忆（accepted_memory）。",
  },
  {
    id: "export_task_memory",
    title: "导出记忆",
    kind: "memory",
    stage: "archive",
    action: "export_task_memory",
    library_group: "记忆",
    instruction: "导出任务记忆为外部文档或结构化数据，用于归档、分享或迁移。",
  },
];

const sections = [
  ["dashboard", "仪表盘", "总览"],
  ["workflow", "工作流画布", "拼流程"],
  ["canvas", "方案管理", "管方案"],
  ["monitor", "运行监控", "看运行"],
  ["memory", "任务记忆", "查记忆"],
  ["integrations", "插件与集成", "管工具"],
];

// 全局状态对象
const globalState = {
  currentAgent: null,
  activeTask: null,
  taskRuntime: 0,
  tokenCurrent: 0,
  tokenLimit: 240000,
  status: 'idle', // idle | running | waiting | error
  runtimeTimer: null,
};

// 更新全局状态栏
function updateStatusBar() {
  const agentName = globalState.currentAgent ? agentDisplayName(globalState.currentAgent) : "未选择";
  const statusDot = $('status-dot');
  const statusText = $('status-text');
  const statusTask = $('status-task');
  const tokenCurrent = $('token-current');
  const tokenFill = $('token-progress-fill');
  const pauseBtn = $('status-pause-btn');
  const viewBtn = $('status-view-btn');

  const currentAgentName = $('current-agent-name');
  if (currentAgentName) currentAgentName.textContent = agentName;

  // 更新状态指示
  if (!statusDot || !statusText) return;
  statusDot.className = `status-dot ${globalState.status}`;
  const statusLabels = { idle: '空闲', running: '执行中', waiting: '等待审批', error: '出错' };
  statusText.textContent = statusLabels[globalState.status] || '未知';

  // 更新任务信息
  if (globalState.activeTask && statusTask) {
    statusTask.style.display = '';
    const currentTaskId = $('current-task-id');
    const taskRuntime = $('task-runtime');
    if (currentTaskId) currentTaskId.textContent = shortId(globalState.activeTask.task_id || '-');
    if (taskRuntime) taskRuntime.textContent = formatRuntime(globalState.taskRuntime);
    if (pauseBtn) pauseBtn.style.display = '';
    if (viewBtn) viewBtn.style.display = '';
  } else if (statusTask) {
    statusTask.style.display = 'none';
    if (pauseBtn) pauseBtn.style.display = 'none';
    if (viewBtn) viewBtn.style.display = 'none';
  }

  // 更新 Token 进度
  if (tokenCurrent && tokenFill) {
    const tokenPercent = Math.min(100, (globalState.tokenCurrent / globalState.tokenLimit) * 100);
    tokenCurrent.textContent = formatTokens(globalState.tokenCurrent);
    const tokenLimit = $('token-limit');
    if (tokenLimit) tokenLimit.textContent = formatTokens(globalState.tokenLimit);
    tokenFill.style.width = `${tokenPercent}%`;
    tokenFill.className = 'token-progress-fill';
    if (tokenPercent > 80) tokenFill.classList.add('danger');
    else if (tokenPercent > 60) tokenFill.classList.add('warning');
  }
}

function formatRuntime(seconds) {
  seconds = Math.max(0, Math.floor(Number(seconds || 0)));
  if (seconds < 60) return `${seconds}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h) return `${h}h ${m}m`;
  return `${m}m ${s}s`;
}

function formatTokens(num) {
  num = Number(num || 0);
  if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
  return String(num);
}

function shortId(value, length = 10) {
  const text = String(value || "-");
  if (text.length <= length + 3) return text;
  return `${text.slice(0, length)}...`;
}

function parseTime(value) {
  const stamp = Date.parse(value || "");
  return Number.isFinite(stamp) ? stamp : 0;
}

function activeTaskRuntimeSeconds(task) {
  if (!task) return 0;
  const started = parseTime(task.created_at) || parseTime(task.updated_at);
  const finished = parseTime(task.finished_at);
  if (!started) return 0;
  return Math.max(0, Math.floor(((finished || Date.now()) - started) / 1000));
}

function taskTokenTotal(task) {
  const usage = task?.token_usage;
  if (typeof usage === "number") return usage;
  if (!usage || typeof usage !== "object") return 0;
  return Number(usage.total || 0)
    || Number(usage.input_other || 0) + Number(usage.input_cached || 0) + Number(usage.output || 0);
}

function totalTokenUsage(tasks = []) {
  return tasks.reduce((sum, task) => sum + taskTokenTotal(task), 0);
}

function pendingApprovalCount(task) {
  return (task?.approvals || []).filter((item) => item.status === "pending").length;
}

// 启动运行时计时器
function startRuntimeTimer() {
  if (globalState.runtimeTimer) return;
  globalState.runtimeTimer = setInterval(() => {
    if (globalState.activeTask && globalState.status === 'running') {
      globalState.taskRuntime++;
      updateStatusBar();
    }
  }, 1000);
}

// 停止运行时计时器
function stopRuntimeTimer() {
  if (globalState.runtimeTimer) {
    clearInterval(globalState.runtimeTimer);
    globalState.runtimeTimer = null;
  }
  globalState.taskRuntime = 0;
}

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
let selectedMemoryFolderId = "";
let memoryDetailOpen = false;
let workflowDrag = null;
let workflowPan = null;
let workflowConnection = null;
let workflowPendingPort = null;
let workflowZoom = 1;
let workflowFocusCursor = -1; // 聚焦内容快捷键的循环游标：-1/0=主体内容，1.. 依次聚焦离群节点
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
let workflowLibraryMode = "basic";
let workflowEditorMode = "simple"; // simple | advanced ：节点编辑器默认填空题模式
let workflowSubAgentOpen = false;
let workflowGlobalOpen = false; // 全局规则抽屉是否打开
let workflowToolboxOpenGroups = new Set();
let workflowToolboxSeeded = false; // 首次渲染把默认展开的分类填进上面的集合
let workflowMinimapWidth = 128;
let workflowMinimapHeight = 128;
let workflowMinimapResize = null;
let workflowSelectionMode = false;
let workflowSelectionDrag = null;
let workflowScissorMode = false;
let workflowScissorStroke = null; // 剪刀划线删除连线
let workflowTerritoryPaintAgent = ""; // 正在为哪个子Agent圈地(sub_agent_id)
let workflowApiScopePaint = ""; // 正在为哪个 api_scope 节点选范围(node id)
let workflowGroupDrag = null;     // 框选后整组移动
let workflowSelectionMove = false; // 框选后“移动”开关：开后在画布上拖动即整组移动
let workflowSelectedNodeIds = new Set();
let workflowHistoryPast = [];
let workflowHistoryFuture = [];
let workflowDragGhostEl = null;
let workflowMaterialChipDrag = null; // 指针拖拽素材到画布的状态（比原生 HTML5 drag 更稳）

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
  if (name === "pointer") {
    return `
      <svg class="game-icon workflow-pointer-icon" viewBox="0 0 24 24" role="img" aria-label="${esc(label)}" focusable="false">
        <path d="M5.2 3.8 18.6 12l-6.1 1.4 3.5 5.8-2.8 1.7-3.5-5.8-4.5 4.4V3.8Z" fill="currentColor"/>
      </svg>
    `;
  }
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
  // 1) 直接命中合法分组 id（如 agent_collab / flow_timing / data_template / api_external）优先返回，
  //    避免再走启发式被误判进 plan_route。
  if (group && WORKFLOW_NODE_GROUPS.some((g) => g.id === group)) return group;
  // 2) 中文/历史别名映射。
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
  const IDENTITY_ACTIONS = ["credential_ref", "cookie_jar", "browser_profile", "login_flow", "session_check", "refresh_session", "credential_scope", "human_login_handoff", "revoke_session"];
  if (IDENTITY_ACTIONS.includes(action)) return "account_identity";
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

function workflowObjectJson(value) {
  if (!value) return "";
  if (typeof value === "object") return JSON.stringify(value, null, 2);
  return String(value || "");
}

function parseWorkflowObjectField(id, label, { allowArray = false } = {}) {
  const raw = $(id)?.value.trim() || "";
  if (!raw) return null;
  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`${label} JSON 格式不正确。`);
  }
  if (!parsed || typeof parsed !== "object" || (!allowArray && Array.isArray(parsed))) {
    throw new Error(`${label} JSON 需要是对象。`);
  }
  return parsed;
}

function setNodeStringField(node, field, value) {
  const text = String(value || "").trim();
  if (text) node[field] = text;
  else delete node[field];
}

function setNodeJsonField(node, field, value) {
  if (value === null || value === undefined || value === "") delete node[field];
  else node[field] = value;
}

// 只有当对应输入框真实存在于当前 DOM 时才返回它的值；否则返回 undefined。
function fieldPresent(id) { return Boolean(document.getElementById(id)); }
function fieldVal(id) { const el = document.getElementById(id); return el ? el.value : undefined; }

function token() {
  return (
    new URLSearchParams(location.search).get("token")
    || sessionStorage.getItem("agent_lab_token")
    || ""
  );
}

function setFeedback(message, tone = "normal") {
  const feedback = $("feedback");
  if (feedback) {
    feedback.textContent = message;
    feedback.dataset.tone = tone;
  }
  if (tone === "error" || tone === "warn") showToast(message, tone);
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

// ---- 插件内通用弹窗：替代浏览器 prompt/confirm/alert，统一风格、可校验、防误删 ----
function showAppModal(opts = {}) {
  return new Promise((resolve) => {
    const { title = "", message = "", fields = [], confirmText = "确定", cancelText = "取消", danger = false } = opts;
    document.querySelector(".app-modal-overlay")?.remove();
    const overlay = document.createElement("div");
    overlay.className = "app-modal-overlay";
    const fieldsHtml = fields.map((f, i) => `
      <label class="app-modal-field">
        <span>${esc(f.label || "")}</span>
        <input type="text" data-modal-field="${i}" value="${esc(f.value == null ? "" : f.value)}" placeholder="${esc(f.placeholder || "")}" />
      </label>
    `).join("");
    overlay.innerHTML = `
      <div class="app-modal ${danger ? "is-danger" : ""}" role="dialog" aria-modal="true">
        ${title ? `<div class="app-modal-title">${esc(title)}</div>` : ""}
        ${message ? `<div class="app-modal-message">${esc(message)}</div>` : ""}
        ${fieldsHtml}
        <div class="app-modal-actions">
          <button class="button secondary" data-modal-cancel type="button">${esc(cancelText)}</button>
          <button class="button ${danger ? "danger" : ""}" data-modal-confirm type="button">${esc(confirmText)}</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
    const inputs = Array.from(overlay.querySelectorAll("[data-modal-field]"));
    if (inputs[0]) { try { inputs[0].focus(); inputs[0].select(); } catch (e) {} }
    let done = false;
    const cleanup = () => { document.removeEventListener("keydown", onKey, true); overlay.remove(); };
    const finish = (val) => { if (done) return; done = true; cleanup(); resolve(val); };
    const onConfirm = () => finish(fields.length ? inputs.map((el) => el.value.trim()) : true);
    const onCancel = () => finish(null);
    overlay.querySelector("[data-modal-confirm]").addEventListener("click", onConfirm);
    overlay.querySelector("[data-modal-cancel]").addEventListener("click", onCancel);
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) onCancel(); });
    function onKey(e) {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onCancel(); }
      else if (e.key === "Enter" && e.target && e.target.tagName !== "TEXTAREA") { e.preventDefault(); e.stopPropagation(); onConfirm(); }
    }
    document.addEventListener("keydown", onKey, true);
  });
}
async function promptModal(title, label, defaultValue = "", opts = {}) {
  const res = await showAppModal({ title, fields: [{ label, value: defaultValue, placeholder: opts.placeholder || "" }], confirmText: opts.confirmText || "确定" });
  return res === null ? null : res[0];
}
async function confirmModal(title, message, opts = {}) {
  const res = await showAppModal({ title, message, confirmText: opts.confirmText || "确定", cancelText: opts.cancelText || "取消", danger: opts.danger !== false });
  return res === true;
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

function workflowActiveFieldSnapshot() {
  const active = document.activeElement;
  if (!active?.matches?.(WORKFLOW_FIELD_SELECTOR)) return null;
  return {
    id: active.id || "",
    action: active.dataset?.action || "",
    start: typeof active.selectionStart === "number" ? active.selectionStart : null,
    end: typeof active.selectionEnd === "number" ? active.selectionEnd : null,
  };
}

function workflowFindField(snapshot) {
  if (!snapshot) return null;
  if (snapshot.id) {
    const byId = document.getElementById(snapshot.id);
    if (byId?.matches?.(WORKFLOW_FIELD_SELECTOR)) return byId;
  }
  if (snapshot.action) {
    return Array.from(document.querySelectorAll(WORKFLOW_FIELD_SELECTOR))
      .find((item) => item.dataset?.action === snapshot.action) || null;
  }
  return null;
}

function workflowUiSnapshot() {
  const inspector = document.querySelector(".workflow-inspector-drawer .drawer-scroll");
  const toolbox = document.querySelector(".workflow-tool-drawer .drawer-scroll");
  return {
    viewport: workflowViewportSnapshot(),
    inspectorScrollTop: inspector?.scrollTop ?? workflowInspectorScrollTop ?? 0,
    toolboxScrollTop: toolbox?.scrollTop ?? workflowToolboxScrollTop ?? 0,
    activeField: workflowActiveFieldSnapshot(),
  };
}

function restoreWorkflowUiSnapshot(snapshot = null) {
  if (!snapshot || route !== "workflow") return;
  restoreWorkflowViewport(snapshot.viewport);
  workflowInspectorScrollTop = snapshot.inspectorScrollTop || 0;
  workflowToolboxScrollTop = snapshot.toolboxScrollTop || 0;
  requestAnimationFrame(() => {
    const inspector = document.querySelector(".workflow-inspector-drawer .drawer-scroll");
    if (inspector) inspector.scrollTop = snapshot.inspectorScrollTop || 0;
    const toolbox = document.querySelector(".workflow-tool-drawer .drawer-scroll");
    if (toolbox) toolbox.scrollTop = snapshot.toolboxScrollTop || 0;
    const field = workflowFindField(snapshot.activeField);
    if (field) {
      field.focus({ preventScroll: true });
      if (typeof field.setSelectionRange === "function" && snapshot.activeField.start !== null) {
        const start = snapshot.activeField.start;
        const end = snapshot.activeField.end ?? start;
        field.setSelectionRange(start, end);
      }
      const scroller = field.closest(".drawer-scroll");
      if (scroller) scroller.scrollTop = field.closest(".workflow-inspector-drawer")
        ? snapshot.inspectorScrollTop || 0
        : snapshot.toolboxScrollTop || 0;
    }
  });
}

function renderWorkflowStable() {
  // render() 现在已全局保持焦点与滚动位置，直接复用即可（不再需要单独的 rAF 兜底）。
  render();
}

function workflowCurrentViewCenter() {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  if (!wrap) return null;
  const rect = wrap.getBoundingClientRect();
  return workflowCanvasPoint({
    clientX: rect.left + rect.width / 2,
    clientY: rect.top + rect.height / 2,
  });
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

function workflowTriggerTypeLabel(type) {
  return {
    command: "命令",
    natural: "自然语言",
    silent_global: "全局静默",
    message_monitor: "消息监听",
    keyword: "关键词",
    regex: "正则",
    poke: "拍一拍",
    notice: "Notice",
    schedule: "定时",
    plugin_event: "插件事件",
    webhook: "Webhook",
    manual_webui: "手动",
  }[type] || type;
}

function workflowChatTypeLabel(type) {
  return { private: "私聊", group: "群聊" }[type] || type;
}

function workflowEdgeTypeLabel(type) {
  return {
    success: "通过/成功",
    failed: "失败/未通过",
    uncertain: "不确定",
    error: "错误",
    retry: "重试",
    timeout: "超时",
    approved: "已批准",
    rejected: "已拒绝",
    always: "始终",
  }[type] || type || "通过/成功";
}

// ============ 端口与连线类型：镜像后端 node_runtime.py 的 port_schema ============
// 每条出口连线的颜色按 edge_type 区分，而不是按节点颜色。绿=成功 灰=失败 黄=不确定 红=错误 紫=审批 橙=重试/超时。
const WORKFLOW_EDGE_COLORS = {
  success: "#2f9e5f",
  failed: "#8a9099",
  uncertain: "#c9a227",
  error: "#c8463c",
  retry: "#d97a25",
  timeout: "#d97a25",
  approved: "#6a8f3d",
  rejected: "#b4433a",
  always: "#5a6b86",
};
function workflowEdgeColor(type) {
  return WORKFLOW_EDGE_COLORS[String(type || "success")] || WORKFLOW_EDGE_COLORS.success;
}
// 把旧的冗余出口类型归并到精简集合：错误/超时都并入“失败”。
function workflowNormalizeEdgeType(type) {
  const t = String(type || "success").trim();
  if (t === "error" || t === "timeout") return "failed";
  if (t === "always") return "success";
  return t || "success";
}

// 按节点类型给出的出口端口集合（与后端 NODE_PORT_SCHEMAS 对齐）。
const WORKFLOW_RUNTIME_PORTS = {
  trigger: { inputs: [], outputs: ["success"] },
  entry: { inputs: ["in"], outputs: ["success", "failed"] },
  detector: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  decision: { inputs: ["in"], outputs: ["success", "failed"] },
  parallel: { inputs: ["in"], outputs: ["success", "failed"] },
  guard: { inputs: ["in"], outputs: ["approved", "rejected"] },
  validation: { inputs: ["in"], outputs: ["success", "failed", "retry"] },
  notification: { inputs: ["in"], outputs: ["success", "failed"] },
  report: { inputs: ["in"], outputs: ["success", "failed"] },
  terminal: { inputs: ["in"], outputs: [] },
  state: { inputs: ["in"], outputs: ["success"] },
  tool: { inputs: ["in"], outputs: ["success", "failed"] },
  api: { inputs: ["in"], outputs: ["success", "failed"] },
  memory: { inputs: ["in"], outputs: ["success"] },
  react: { inputs: ["in"], outputs: ["success"] },
};
// 个别 action 的端口覆盖（精简版：错误/超时并入失败，审批只留 批准/拒绝）。
const WORKFLOW_ACTION_PORTS = {
  listen_message: { inputs: [], outputs: ["success", "failed"] },
  schedule_trigger: { inputs: [], outputs: ["success"] },
  plugin_event_trigger: { inputs: [], outputs: ["success", "failed"] },
  webhook_trigger: { inputs: [], outputs: ["success", "failed"] },
  match_keyword: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  match_regex: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  llm_detect: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  scope_filter: { inputs: ["in"], outputs: ["success"] },
  retry: { inputs: ["retry"], outputs: ["success", "failed"] },
  catch_error: { inputs: ["in"], outputs: ["success", "failed"] },
  request_approval: { inputs: ["in"], outputs: ["approved", "rejected"] },
  route_condition: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  conditional_router: { inputs: ["in"], outputs: ["success", "failed", "uncertain"] },
  parallel_branch: { inputs: ["in"], outputs: ["success", "failed"] },
  handoff: { inputs: ["in"], outputs: ["success", "failed"] },
  wait_user: { inputs: ["in"], outputs: ["success", "failed"] },
  validate_output: { inputs: ["in"], outputs: ["success", "failed", "retry"] },
};
// 取某节点的端口集合：先看 action 覆盖，再看 runtime_type。
function workflowNodePorts(node) {
  const action = String(node?.action || "").trim();
  if (WORKFLOW_ACTION_PORTS[action]) return WORKFLOW_ACTION_PORTS[action];
  const rt = workflowRuntimeType(node);
  return WORKFLOW_RUNTIME_PORTS[rt] || { inputs: ["in"], outputs: ["success", "failed"] };
}
// 该节点是否需要展示多个具名出口（>1 个出口才值得拆分显示）。
function workflowNodeHasMultiOut(node) {
  return (workflowNodePorts(node).outputs || []).length > 1
    && ["decision", "detector", "guard", "validation", "parallel"].includes(workflowRuntimeType(node));
}
// 出口端口的简短标签（画在端口旁）。
function workflowPortShortLabel(type) {
  return {
    success: "成功", failed: "失败", uncertain: "存疑", error: "错误",
    retry: "重试", timeout: "超时", approved: "批准", rejected: "拒绝", always: "始终",
  }[type] || type;
}

function checkboxGroupHtml(name, values, selected, labeler) {
  const selectedSet = new Set(selected || []);
  return values.map((value) => `
    <label class="check-line"><input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${selectedSet.has(value) ? "checked" : ""} />${esc(labeler(value))}</label>
  `).join("");
}

function checkedValues(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((item) => item.value);
}

// 这条工作流是"长任务(含心跳)"还是"事件/静态自动化"？由是否有心跳节点或开启心跳决定。
function workflowHasHeartbeatNode(agent) {
  return (agent?.workflow_nodes || []).some((n) => String(n.action || "") === "heartbeat");
}
function workflowHeartbeatOn(agent) {
  const hb = agent?.heartbeat_policy || {};
  return Boolean(hb.enabled) || String(hb.mode || "") === "auto" || workflowHasHeartbeatNode(agent);
}
function workflowKindSummary(agent) {
  return workflowHeartbeatOn(agent) ? "长任务·可续跑" : "事件/静态自动化";
}
function workflowHeartbeatSummary(agent) {
  const hb = agent?.heartbeat_policy || {};
  if (hb.enabled) return `心跳开·${esc(hb.cron_expression || "*/5 * * * *")}`;
  if (String(hb.mode || "") === "auto") return "心跳·自动";
  if (workflowHasHeartbeatNode(agent)) return "含心跳节点";
  return "无心跳·一次性";
}

function workflowTriggerSummary(agent) {
  const trigger = ensureAgent(agent || {}).workflow_trigger || {};
  if (trigger.enabled === false) return "已关闭";
  const types = (trigger.types || []).map(workflowTriggerTypeLabel).join(" / ") || "命令";
  const details = [];
  if ((trigger.keywords || []).length) details.push(`关键词 ${trigger.keywords.length}`);
  if ((trigger.regex || []).length) details.push(`正则 ${trigger.regex.length}`);
  if (trigger.cron) details.push(trigger.cron);
  if ((trigger.plugin_events || []).length) details.push(`插件事件 ${trigger.plugin_events.length}`);
  return [types, ...details].join(" · ");
}

function workflowScopeSummary(agent) {
  const scope = ensureAgent(agent || {}).workflow_scope || {};
  const chat = (scope.chat_types || []).map(workflowChatTypeLabel).join(" / ") || "私聊";
  const parts = [chat];
  if (scope.admin_only) parts.push("仅管理员");
  if ((scope.umo_allowlist || []).length) parts.push(`UMO 白名单 ${scope.umo_allowlist.length}`);
  if ((scope.group_allowlist || []).length) parts.push(`群白名单 ${scope.group_allowlist.length}`);
  if ((scope.user_allowlist || []).length) parts.push(`用户白名单 ${scope.user_allowlist.length}`);
  if ((scope.umo_denylist || []).length || (scope.group_denylist || []).length || (scope.user_denylist || []).length) parts.push("含黑名单");
  return parts.join(" · ");
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
    listen_message: "消息监听",
    match_keyword: "关键词检测",
    match_regex: "正则检测",
    llm_detect: "LLM 检测",
    scope_filter: "范围过滤",
    schedule_trigger: "定时入口",
    plugin_event_trigger: "插件事件入口",
    webhook_trigger: "Webhook 入口",
    limit_rate: "限流冷却",
    catch_error: "错误捕获",
    write_record: "写运行记录",
    generate_report: "生成报告",
    send_message: "发送消息",
    send_private_message: "发送私信",
    send_email: "发送邮件",
    plugin_prompt: "插件嵌入提示词",
    summarize_entry: "入口摘要",
    confirm_entry: "开启确认",
    restore_isolation: "记录进入前状态",
    variable_set: "写入变量",
    variable_get: "读取变量",
    text_template: "文本模板",
    json_transform: "JSON 转换",
    merge: "合并数据",
    iterator: "迭代准备",
    subflow_call: "子流程调用",
    plan: "计划拆解",
    route_condition: "条件分流",
    conditional_router: "条件路由",
    parallel_branch: "并行分支",
    run_tools: "工具执行",
    call_api: "API 调用",
    http_request: "HTTP 请求",
    file_operation: "文件操作",
    code_exec: "代码执行",
    transform_context: "上下文整理",
    retrieve_memory: "记忆检索",
    memory_filter: "记忆过滤器",
    summarize_memory: "总结记忆",
    export_task_memory: "导出记忆",
    promote_memory_candidate: "提升候选记忆",
    forget_task_memory: "遗忘记忆",
    archive_memory_folder: "方案记忆存档",
    request_approval: "请求审批",
    wait_user: "等待用户",
    handoff: "人工接管",
    validate_output: "结果校验",
    debate_validation: "多视角校验",
    retry: "有限重试",
    save_state: "记录进度",
    save_memory: "保存任务记录",
    heartbeat: "心跳续跑",
    notify: "完成通知",
    archive: "归档退出",
    exit_summary: "结束回流",
    credential_ref: "账号凭证",
    cookie_jar: "Cookie 登录态",
    browser_profile: "浏览器配置",
    login_flow: "登录流程",
    session_check: "登录态检查",
    refresh_session: "刷新登录态",
    credential_scope: "凭证使用范围",
    human_login_handoff: "人工登录交接",
    revoke_session: "注销会话",
    global_control: "全局控制",
    skill_evolution: "Skill 进化",
    manual: "人工判断",
  }[action] || action;
}

function workflowPermissionLabel(profile) {
  return {
    ordinary: "普通：只读安全动作",
    work: "工作：常规工具/API",
    code: "代码：文件、搜索、代码工具",
    web: "联网：Web/Search/API",
    danger: "高危：允许高风险工具",
  }[profile] || profile || "工作";
}

function workflowRefTypeLabel(type) {
  return {
    "": "不绑定",
    tool: "AstrBot 工具",
    api: "自定义 API",
    plugin: "AstrBot 插件",
    skill: "Skill",
    module: "模块/蓝图",
    workflow: "子工作流",
  }[type] || type;
}

function workflowWorkerTypeLabel(type) {
  return {
    "": "自动推断",
    GenericWorker: "通用工作包",
    ResearchWorker: "资料检索",
    CodeReaderWorker: "代码阅读",
    PatchWorker: "代码修改",
    TestWorker: "测试验证",
    ApiWorker: "API 调用",
    ToolWorker: "工具调用",
  }[type] || type;
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
  agent.workflow_trigger ||= {};
  agent.workflow_trigger.enabled ??= true;
  agent.workflow_trigger.types ||= ["command"];
  agent.workflow_trigger.command_names ||= ["agentlab", "al"];
  agent.workflow_trigger.keywords ||= [];
  agent.workflow_trigger.regex ||= [];
  agent.workflow_trigger.cron ||= "";
  agent.workflow_trigger.plugin_events ||= [];
  agent.workflow_trigger.webhook_path ||= "";
  agent.workflow_trigger.description ||= "";
  agent.workflow_scope ||= {};
  agent.workflow_scope.chat_types ||= ["private"];
  agent.workflow_scope.platforms ||= [];
  agent.workflow_scope.umo_allowlist ||= [];
  agent.workflow_scope.umo_denylist ||= [];
  agent.workflow_scope.group_allowlist ||= [];
  agent.workflow_scope.group_denylist ||= [];
  agent.workflow_scope.user_allowlist ||= [];
  agent.workflow_scope.user_denylist ||= [];
  agent.workflow_scope.admin_only ??= false;
  agent.entry_policy ||= {};
  agent.entry_policy.trigger_phrases ||= ["进入任务模式", "开启任务模式", "/agentlab start"];
  agent.entry_policy.trigger_keywords ||= ["持续推进", "长任务", "排查", "部署", "写插件", "改代码", "整理资料"];
  agent.entry_policy.require_confirmation ??= true;
  agent.entry_policy.confirmation_text ||= "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？";
  agent.entry_policy.default_completion_conditions ||= ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"];
  agent.entry_policy.exit_phrases ||= ["完成任务", "结束任务模式", "退出任务模式", "/agentlab finish"];
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
  agent.sub_agents ||= [];
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
  agent.heartbeat_policy.max_repeated_failures ??= 3;
  agent.default_task_budget ||= {};
  agent.default_task_budget.max_nodes_per_tick ??= 6;
  agent.default_task_budget.max_tools_per_tick ??= 12;
  agent.default_task_budget.max_seconds_per_tick ??= 240;
  agent.default_task_budget.max_tokens_per_tick ??= 12000;
  agent.default_task_budget.max_total_ticks ??= 120;
  agent.default_task_budget.max_total_tool_calls ??= 240;
  agent.default_task_budget.max_total_tokens ??= 240000;
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
    workflow_trigger: {
      enabled: true,
      types: ["command", "manual_webui"],
      command_names: ["agentlab", "al"],
      keywords: [],
      regex: [],
      cron: "",
      plugin_events: [],
      webhook_path: "",
      description: "Workflow trigger policy for this canvas.",
    },
    workflow_scope: {
      chat_types: ["private"],
      platforms: [],
      umo_allowlist: [],
      umo_denylist: [],
      group_allowlist: [],
      group_denylist: [],
      user_allowlist: [],
      user_denylist: [],
      admin_only: false,
    },
    entry_policy: {
      trigger_phrases: ["进入任务模式", "开启任务模式", "/agentlab start"],
      trigger_keywords: ["持续推进", "长任务", "排查", "部署", "写插件", "改代码", "整理资料"],
      require_confirmation: true,
      confirmation_text: "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？",
      default_completion_conditions: ["用户验收通过", "任务成果已归档", "关键改动和风险已总结"],
      exit_phrases: ["完成任务", "结束任务模式", "退出任务模式", "/agentlab finish"],
    },
    isolation_policy: {
      mode: "strict",
      tool_mode: "whitelist",
      restore_on_exit: true,
      protect_self: true,
      hide_disabled_plugin_tools: true,
      notes: "严格隔离会在当前会话默认关闭普通插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件；不改 AstrBot 全局插件开关，退出时恢复会话快照。",
    },
    system_prompt: "你仍然是当前 AstrBot 里的原本角色，但进入任务模式后必须以任务推进为中心。",
    task_prompt: "你在任务模式中工作。先读取任务状态，再执行一个有限步骤，随后总结并写回状态。",
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
    default_task_budget: {
      max_nodes_per_tick: 6,
      max_tools_per_tick: 12,
      max_seconds_per_tick: 240,
      max_tokens_per_tick: 12000,
      max_total_ticks: 120,
      max_total_tool_calls: 240,
      max_total_tokens: 240000,
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
    agent_done: "模型完成",
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
  input.focus({ preventScroll: true });
  const end = String(value || "").length;
  if (typeof input.setSelectionRange === "function") input.setSelectionRange(end, end);
}

function renderWorkflowFilterInput(action, value) {
  const snapshot = workflowUiSnapshot();
  render();
  restoreWorkflowUiSnapshot(snapshot);
  requestAnimationFrame(() => {
    const input = document.querySelector(`[data-action="${action}"]`);
    if (!input) return;
    input.focus({ preventScroll: true });
    const end = String(value || "").length;
    if (typeof input.setSelectionRange === "function") input.setSelectionRange(end, end);
  });
}

function modernDefaultWorkflowNodes() {
  // 默认「长任务」工作流：入口→全局控制→读记忆→计划→分流→执行/并行→整理→校验→快照→任务记忆→方案记忆隔离→Skill进化→通知→归档。
  // 主干在中间一行，并行/进化在上排，审批/人工/重试/心跳在下排；节点 340×208，列距 480、行距 380，互不重叠、连线清晰。
  return [
    { id: "entry", title: "消息监听入口", kind: "trigger", stage: "entry", action: "listen_message", description: "统一承接命令、关键词、自然语言、拍一拍、notice、WebUI、插件事件和 webhook。", instruction: "只把命中工作流触发策略和范围规则的事件送入后续节点。", output_variable: "event.message", x: 100, y: 900 },
    { id: "global_control", title: "全局控制", kind: "guard", stage: "guard", action: "global_control", description: "方案级隔离、汇报、预算和错误阈值。", instruction: "统一应用隔离、工具范围、汇报频率、预算、暂停策略和错误累积阈值。", x: 580, y: 900 },
    { id: "memory_recall", title: "任务记忆读取", kind: "retrieval", stage: "plan", action: "retrieve_memory", description: "按标签或记忆夹读取任务记忆。", instruction: "按标签、记忆夹或 source_task_id 读取与当前方案相关的任务记忆。", x: 1060, y: 520 },
    { id: "plan", title: "计划确认", kind: "state", stage: "plan", action: "plan", description: "把目标拆成可验证步骤。", instruction: "明确完成条件、风险等级、工具范围、验收方式，并约束每轮只推进一个有限工作单元。", x: 1060, y: 900 },
    { id: "parallel_branch", title: "并行分支", kind: "branch", stage: "plan", action: "parallel_branch", description: "拆分互不依赖的小任务。", instruction: "把资料检索、代码阅读、测试准备等互不依赖的小任务拆成并行工作包。", x: 1540, y: 520 },
    { id: "risk_router", title: "风险分流", kind: "branch", stage: "plan", action: "route_condition", description: "按风险和任务性质分支。", instruction: "低风险直接执行；高风险进入审批；需要外部系统时走 API；需要用户判断时交给人工接管。", x: 1540, y: 900 },
    { id: "parallel_research", title: "并行检索包", kind: "subflow", stage: "execute", action: "manual", description: "只读检索或代码阅读工作包。", instruction: "只读检索资料、接口或代码，输出证据摘要、风险和建议下一步。", prompt: "你是并行只读检索工作包。只收集证据和结论，不做写入动作；输出：发现、证据来源、风险、建议下一步。", parallel_group: "default", x: 2020, y: 520 },
    { id: "execute", title: "工具执行", kind: "tool", stage: "execute", action: "run_tools", description: "调用白名单工具。", instruction: "只调用 AgentSpec 允许的工具，并保留关键输出。", x: 2020, y: 900 },
    { id: "approval", title: "审批闸门", kind: "guard", stage: "guard", action: "request_approval", description: "危险动作前请求用户确认。", instruction: "删除、部署、密钥、重启、全局配置和破坏性数据库操作前必须先说明影响并等待审批。", x: 2020, y: 1280 },
    { id: "parallel_verify", title: "并行验证包", kind: "subflow", stage: "execute", action: "manual", description: "验收条件和测试准备工作包。", instruction: "独立检查完成条件、测试证据、边界情况和可能遗漏。", prompt: "你是并行验证工作包。只围绕完成条件检查证据强度；输出：已验证、未验证、阻塞、需要主 Agent 决策的点。", parallel_group: "default", x: 2500, y: 520 },
    { id: "api_call", title: "API 调用", kind: "api", stage: "execute", action: "call_api", description: "调用注册 API 或外部服务。", instruction: "使用已登记 API，凭证由 Agent Lab 注入，不写入任务记忆。", x: 2500, y: 900 },
    { id: "human_handoff", title: "人工接管", kind: "human", stage: "guard", action: "handoff", description: "等待用户选择或授权。", instruction: "遇到登录、验证码、业务判断、未授权范围或连续阻塞时暂停，给出清晰选项等待用户输入。", x: 2500, y: 1280 },
    { id: "plugin_prompt", title: "插件嵌入提示词", kind: "subflow", stage: "execute", action: "plugin_prompt", description: "把目标插件作为中间能力调用。", instruction: "把目标 AstrBot 插件作为中间能力调用提示词，必要时转人工管理员执行。", x: 2980, y: 520 },
    { id: "transform", title: "上下文整理", kind: "transform", stage: "execute", action: "transform_context", description: "清洗工具/API/插件输出。", instruction: "把工具/API/插件输出整理成结构化观察，压缩噪声并保留证据。", x: 2980, y: 900 },
    { id: "validation", title: "结果校验", kind: "validation", stage: "checkpoint", action: "validate_output", description: "检查是否满足完成条件。", instruction: "对照完成条件、测试结果和副作用判断是否完成；失败时说明原因并进入有限重试。", x: 3460, y: 900 },
    { id: "retry_loop", title: "重试循环", kind: "loop", stage: "checkpoint", action: "retry", description: "失败时有限次重试。", instruction: "只在执行失败或校验不通过时进入；还有次数就绕回执行，用尽后交人工。", max_retries: 3, x: 3460, y: 1280 },
    { id: "checkpoint", title: "状态快照", kind: "state", stage: "checkpoint", action: "save_state", description: "把本轮结果写入 task_state。", instruction: "每轮结束写回 current_summary、progress、next_step、observation 和阻塞点。", x: 3940, y: 900 },
    { id: "heartbeat", title: "心跳续跑", kind: "guard", stage: "guard", action: "heartbeat", description: "长任务定时唤醒、续跑。", instruction: "心跳醒来先读 task_state，再推进一小步；同一阻塞重复三次则暂停求助。", x: 3940, y: 1280 },
    { id: "task_memory", title: "任务记忆", kind: "memory", stage: "checkpoint", action: "save_memory", description: "独立记录任务时间线和关键成果。", instruction: "把时间点、关键修改、成果、风险和下次续写提示写入任务记忆。", x: 4420, y: 900 },
    { id: "skill_evolution", title: "Skill 进化", kind: "guard", stage: "archive", action: "skill_evolution", description: "从已接受记忆生成技能规则草稿。", instruction: "从已接受任务记忆生成 skill_rules 草稿，默认走人工审批。", approval_mode: "review", x: 4900, y: 520 },
    { id: "memory_archive", title: "方案记忆存档", kind: "memory", stage: "archive", action: "archive_memory_folder", description: "归档到方案级记忆夹（按 agent_id + folder_id 隔离，不串记忆）。", instruction: "把本次任务导出到方案级记忆夹，隔离到当前 agent_id 和 folder_id，避免不同方案之间串记忆。", x: 4900, y: 900 },
    { id: "notify", title: "完成通知", kind: "notification", stage: "archive", action: "notify", description: "向当前会话反馈成果。", instruction: "在退出前向用户说明完成情况、验证结果、遗留风险和下次续写入口。", x: 5380, y: 900 },
    { id: "archive", title: "结束回流", kind: "memory", stage: "archive", action: "exit_summary", description: "完成或取消后归档。", instruction: "输出成果、关键改动、遗留问题和可回流记忆候选，然后恢复会话插件隔离。", x: 5860, y: 900 },
  ];
}

function modernDefaultWorkflowEdges() {
  return [
    { from: "entry", to: "global_control", edge_type: "success" },
    { from: "global_control", to: "memory_recall", edge_type: "success" },
    { from: "memory_recall", to: "plan", edge_type: "success" },
    { from: "plan", to: "risk_router", edge_type: "success" },
    { from: "plan", to: "parallel_branch", edge_type: "uncertain" },
    { from: "parallel_branch", to: "parallel_research", edge_type: "success" },
    { from: "parallel_branch", to: "parallel_verify", edge_type: "success" },
    { from: "parallel_research", to: "transform", edge_type: "success" },
    { from: "parallel_verify", to: "transform", edge_type: "success" },
    { from: "risk_router", to: "execute", edge_type: "success" },
    { from: "risk_router", to: "api_call", edge_type: "uncertain" },
    { from: "risk_router", to: "approval", edge_type: "failed" },
    { from: "approval", to: "execute", edge_type: "approved" },
    { from: "approval", to: "human_handoff", edge_type: "rejected" },
    { from: "human_handoff", to: "plan", edge_type: "success" },
    { from: "execute", to: "transform", edge_type: "success" },
    { from: "execute", to: "retry_loop", edge_type: "failed" },
    { from: "api_call", to: "transform", edge_type: "success" },
    { from: "api_call", to: "retry_loop", edge_type: "failed" },
    { from: "plugin_prompt", to: "transform", edge_type: "success" },
    { from: "plugin_prompt", to: "human_handoff", edge_type: "failed" },
    { from: "transform", to: "validation", edge_type: "success" },
    { from: "validation", to: "checkpoint", edge_type: "success" },
    { from: "validation", to: "retry_loop", edge_type: "failed" },
    { from: "retry_loop", to: "execute", edge_type: "retry" },
    { from: "retry_loop", to: "human_handoff", edge_type: "failed" },
    { from: "checkpoint", to: "task_memory", edge_type: "success" },
    { from: "checkpoint", to: "heartbeat", edge_type: "uncertain" },
    { from: "heartbeat", to: "plan", edge_type: "success" },
    { from: "task_memory", to: "memory_archive", edge_type: "success" },
    { from: "memory_archive", to: "skill_evolution", edge_type: "success" },
    { from: "skill_evolution", to: "notify", edge_type: "success" },
    { from: "notify", to: "archive", edge_type: "success" },
  ];
}

function defaultWorkflowNodes() {
  return modernDefaultWorkflowNodes();
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
      description: "失败/出错时有限次重试，用尽后交人工。",
      instruction: "只在执行失败或校验不通过时进入。还有次数就从『重试』出口绕回执行重试；用尽后从『失败』出口交人工，不要在成功后继续循环。",
      max_retries: 3,
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
  return modernDefaultWorkflowEdges();
  return [
    { from: "entry", to: "entry_gate", edge_type: "success" },
    { from: "entry_gate", to: "context_bridge", edge_type: "success" },
    { from: "context_bridge", to: "isolation_gate", edge_type: "success" },
    { from: "isolation_gate", to: "memory_recall", edge_type: "success" },
    { from: "memory_recall", to: "plan", edge_type: "success" },
    { from: "plan", to: "risk_router", edge_type: "success" },
    // 并行分支：把互不依赖的检索/复核拆出去并行，再统一汇总
    { from: "plan", to: "parallel_branch", edge_type: "uncertain" },
    { from: "parallel_branch", to: "parallel_research", edge_type: "success" },
    { from: "parallel_branch", to: "parallel_verify", edge_type: "success" },
    { from: "parallel_research", to: "transform", edge_type: "success" },
    { from: "parallel_verify", to: "transform", edge_type: "success" },
    // 风险分流：低风险直接执行；需要外部系统走 API；高风险先审批
    { from: "risk_router", to: "execute", edge_type: "success" },
    { from: "risk_router", to: "api_call", edge_type: "uncertain" },
    { from: "risk_router", to: "approval", edge_type: "failed" },
    // 审批闸门：批准放行执行；拒绝交人工
    { from: "approval", to: "execute", edge_type: "approved" },
    { from: "approval", to: "human_handoff", edge_type: "rejected" },
    { from: "human_handoff", to: "plan", edge_type: "success" },
    { from: "execute", to: "transform", edge_type: "success" },
    { from: "execute", to: "retry_loop", edge_type: "error" },
    { from: "api_call", to: "transform", edge_type: "success" },
    { from: "api_call", to: "retry_loop", edge_type: "error" },
    { from: "transform", to: "validation", edge_type: "success" },
    // 校验：通过→存档；不通过→重试
    { from: "validation", to: "checkpoint", edge_type: "success" },
    { from: "validation", to: "retry_loop", edge_type: "failed" },
    // 重试循环：还能重试→绕回执行；重试用尽→交人工
    { from: "retry_loop", to: "execute", edge_type: "retry" },
    { from: "retry_loop", to: "human_handoff", edge_type: "failed" },
    { from: "checkpoint", to: "task_memory", edge_type: "success" },
    { from: "checkpoint", to: "heartbeat", edge_type: "uncertain" },
    { from: "heartbeat", to: "plan", edge_type: "success" },
    { from: "task_memory", to: "notify", edge_type: "success" },
    { from: "notify", to: "archive", edge_type: "success" },
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
  if (id === "research_task") {
    return {
      nodes: [
        { id: "entry", title: "明确问题", kind: "state", stage: "entry", action: "summarize_entry", description: "压缩研究目标", instruction: "提取要回答的问题、必须核实的事实、时间范围、来源偏好和不能假设的地方。", x: 80, y: 260 },
        { id: "memory_recall", title: "查相似研究", kind: "retrieval", stage: "plan", action: "retrieve_memory", description: "先查历史任务记忆", instruction: "检索 accepted_memory 和 archive_summary，若命中相似研究，记录 memory_id/source_task_id 并复用已验证结论。", output_variable: "memory", output_schema: { type: "object", properties: { rows: { type: "array" } } }, x: 460, y: 260 },
        { id: "plan", title: "研究步骤", kind: "state", stage: "plan", action: "plan", description: "拆分检索与核验", instruction: "列出需要搜索或抓取的来源、交叉验证策略、成功标准和本轮最多推进的一小步。", x: 840, y: 260 },
        { id: "search", title: "搜索/抓取", kind: "tool", stage: "execute", action: "run_tools", description: "调用搜索或网页工具", instruction: "只调用白名单中的搜索、网页或 API 工具，把结果整理为 sources/results/疑点。", permission_profile: "web", output_variable: "research", output_schema: { type: "object", properties: { results: { type: "array" }, sources: { type: "array" } } }, x: 1220, y: 260 },
        { id: "verify", title: "交叉验证", kind: "validation", stage: "checkpoint", action: "validate_output", description: "核验结论可靠性", instruction: "区分已核实、未核实、冲突来源和需要用户判断的问题。", input_variable: "research", input_schema: { type: "object" }, output_variable: "validation", output_schema: { type: "object", properties: { passed: { type: "boolean" } } }, x: 1600, y: 260 },
        { id: "memory", title: "记忆候选", kind: "memory", stage: "checkpoint", action: "save_memory", description: "沉淀可复用研究结论", instruction: "只保存稳定事实、引用来源和下次续写提示；未核实内容保留为 candidate_memory。", tags: ["research", "source"], x: 1980, y: 260 },
        { id: "archive", title: "研究归档", kind: "memory", stage: "archive", action: "exit_summary", description: "输出结论与引用", instruction: "归档结论、来源、置信度、未解决问题和后续检索入口。", x: 2360, y: 260 },
      ],
      edges: [
        { from: "entry", to: "memory_recall" },
        { from: "memory_recall", to: "plan" },
        { from: "plan", to: "search" },
        { from: "search", to: "verify" },
        { from: "verify", to: "memory" },
        { from: "memory", to: "archive" },
      ],
    };
  }
  if (id === "plugin_call") {
    return {
      nodes: [
        { id: "entry", title: "插件任务入口", kind: "state", stage: "entry", action: "summarize_entry", description: "明确要调用的插件能力", instruction: "提取用户想让插件完成的动作、输入数据、成功标准和权限边界。", x: 80, y: 260 },
        { id: "similar_memory", title: "查相似记忆", kind: "retrieval", stage: "plan", action: "retrieve_memory", description: "先找可复用内容", instruction: "工具创建前先查相似任务或日记/记忆内容；命中则读取、复用或更新，未命中再新建。", output_variable: "memory", output_schema: { type: "object", properties: { rows: { type: "array" } } }, x: 460, y: 260 },
        { id: "choose_plugin", title: "选择插件能力", kind: "branch", stage: "plan", action: "route_condition", description: "按能力选择插件或工具", instruction: "根据 capability 在 memory/search/file/web/database/image/api 中选择对应插件节点；不要让用户猜动作字段。", x: 840, y: 260 },
        { id: "plugin_tool", title: "执行插件工具", kind: "tool", stage: "execute", action: "run_tools", description: "绑定 AstrBot 工具", instruction: "从工具 schema 填写参数；结果必须写成 observation，再交给校验节点。", permission_profile: "work", input_variable: "memory", input_schema: { type: "object" }, output_variable: "tool_result", output_schema: { type: "object" }, x: 1220, y: 260 },
        { id: "validate", title: "校验插件结果", kind: "validation", stage: "checkpoint", action: "validate_output", description: "确认执行结果", instruction: "检查 tool_result.ok、返回内容、是否需要用户确认或重试。", input_variable: "tool_result", input_schema: { type: "object" }, output_variable: "validation", output_schema: { type: "object", properties: { passed: { type: "boolean" } } }, x: 1600, y: 260 },
        { id: "save_state", title: "写回状态", kind: "state", stage: "checkpoint", action: "save_state", description: "保存 observation", instruction: "把插件调用结果、错误、下一步和需要用户补充的信息写回 task_state。", x: 1980, y: 260 },
        { id: "archive", title: "插件调用归档", kind: "memory", stage: "archive", action: "exit_summary", description: "归档结果", instruction: "只归档完成情况、插件名称、关键结果和可复用提示，不保存敏感输入。", x: 2360, y: 260 },
      ],
      edges: [
        { from: "entry", to: "similar_memory" },
        { from: "similar_memory", to: "choose_plugin" },
        { from: "choose_plugin", to: "plugin_tool" },
        { from: "plugin_tool", to: "validate" },
        { from: "validate", to: "save_state" },
        { from: "save_state", to: "archive" },
      ],
    };
  }
  if (id === "long_heartbeat") {
    return {
      nodes: [
        { id: "entry", title: "长任务入口", kind: "state", stage: "entry", action: "summarize_entry", description: "压缩长任务目标", instruction: "明确总目标、完成条件、预算、用户可接受的自动推进范围和需要暂停的条件。", x: 80, y: 260 },
        { id: "resume", title: "读取恢复点", kind: "state", stage: "plan", action: "save_state", description: "恢复 workflow 当前节点", instruction: "每轮先读取 workflow_current_node_id、node_outputs、last_observation 和 watchdog 状态，不依赖上一轮聊天上下文。", output_variable: "resume", output_schema: { type: "object" }, x: 460, y: 260 },
        { id: "watchdog", title: "卡住检查", kind: "guard", stage: "guard", action: "heartbeat", description: "检查是否卡住或超预算", instruction: "检查 lease、预算、连续失败、是否等待审批或用户输入；需要用户时暂停，不继续乱跑。", input_variable: "resume", input_schema: { type: "object" }, output_variable: "watchdog", output_schema: { type: "object", properties: { needs_user: { type: "boolean" } } }, x: 840, y: 260 },
        { id: "step", title: "推进一步", kind: "tool", stage: "execute", action: "run_tools", description: "只推进有限步骤", instruction: "每轮最多执行一个小工作单元，所有工具结果必须写成 observation。", permission_profile: "work", output_variable: "step_result", output_schema: { type: "object" }, x: 1220, y: 260 },
        { id: "checkpoint", title: "写回观察", kind: "state", stage: "checkpoint", action: "save_state", description: "保存 observation 和 next_step", instruction: "写回 last_observation、current_summary、next_step、预算消耗和是否继续。", input_variable: "step_result", input_schema: { type: "object" }, x: 1600, y: 260 },
        { id: "continue_check", title: "继续判断", kind: "branch", stage: "checkpoint", action: "route_condition", description: "决定继续、暂停或归档", instruction: "若 validation.passed == false 且预算允许则回到计划；若需要用户则暂停；若完成则归档。", x: 1980, y: 260 },
        { id: "archive", title: "长任务归档", kind: "memory", stage: "archive", action: "exit_summary", description: "归档长任务结果", instruction: "归档完成内容、暂停原因、剩余工作和下次恢复入口。", x: 2360, y: 260 },
      ],
      edges: [
        { from: "entry", to: "resume" },
        { from: "resume", to: "watchdog" },
        { from: "watchdog", to: "step" },
        { from: "step", to: "checkpoint" },
        { from: "checkpoint", to: "continue_check" },
        { from: "continue_check", to: "resume" },
        { from: "continue_check", to: "archive" },
      ],
    };
  }
  return { nodes: defaultWorkflowNodes(), edges: defaultWorkflowEdges() };
}

function applyWorkflowTemplate(id) {
  const template = workflowTemplate(id);
  currentAgent.workflow_nodes = clone(template.nodes);
  currentAgent.workflow_edges = clone(template.edges);
  autoLayoutWorkflow(); // 套用示例后自动整理成整齐的阶段泳道，保证"给人看"。
  focusWorkflowStart();
  selectedWorkflowNodeId = currentAgent.workflow_nodes[0]?.id || "";
  workflowCheckReport = null;
  const names = { api_review: "API 审批流", code_task: "代码任务流", emergency: "紧急模式", memory_loop: "记忆续写流", parallel_agent: "并行 Agent 流", research_task: "资料研究流", plugin_call: "插件调用流", long_heartbeat: "长任务心跳流", linear: "标准工作流" };
  setFeedback(`已套用${names[id] || "工作流"}，保存后会进入任务运行协议。`);
}

function workflowNodeDropPosition(point, fallbackStage, index = 0) {
  const pos = point || defaultWorkflowPosition(fallbackStage || "plan", index);
  return {
    x: clamp(Number(pos.x || 0) - (point ? WORKFLOW_NODE_WIDTH / 2 : 0), WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X),
    y: clamp(Number(pos.y || 0) - (point ? WORKFLOW_NODE_HEIGHT / 2 : 0), WORKFLOW_CANVAS_MIN_Y, WORKFLOW_CANVAS_MAX_Y),
  };
}

function addWorkflowTemplateNode(templateId, point = null, options = {}) {
  readAgentForm();
  ensureWorkflow();
  const template = WORKFLOW_NODE_TEMPLATES.find((item) => item.id === templateId) || WORKFLOW_NODE_TEMPLATES[0];
  const nodeTemplate = migrateWorkflowNodeShape(clone(template));
  pushWorkflowHistory();
  const id = uniqueWorkflowNodeId(nodeTemplate.id);
  const pos = workflowNodeDropPosition(point, nodeTemplate.stage, currentAgent.workflow_nodes.length);
  currentAgent.workflow_nodes.push({
    ...nodeTemplate,
    id,
    description: nodeTemplate.description || nodeTemplate.title,
    x: pos.x,
    y: pos.y,
  });
  selectedWorkflowNodeId = id;
  workflowInspectorOpen = options.openInspector !== false;
  workflowDryRunReport = null;
  workflowCheckReport = null;
  setFeedback(`已添加节点：${nodeTemplate.title}。拖动画布上的节点即可调整位置。`);
}

function addRuntimeWorkflowNode(refType, refId, point = null, options = {}) {
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
  workflowInspectorOpen = options.openInspector !== false;
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

function migrateWorkflowNodeShape(node = {}) {
  const id = String(node.id || "").trim();
  const action = String(node.action || "").trim();
  const patch = { ...(WORKFLOW_LEGACY_NODE_MIGRATIONS[id] || {}) };
  if (!Object.keys(patch).length && ["command_entry", "keyword_entry", "manual_webui_entry"].includes(action)) {
    Object.assign(patch, WORKFLOW_LEGACY_NODE_MIGRATIONS[action]);
  }
  if (!Object.keys(patch).length) return node;
  const migrated = { ...node, ...patch };
  if (id === "keyword_entry" && !migrated.keywords && node.params?.keywords) migrated.keywords = node.params.keywords;
  if (id === "memory_rollback" && !migrated.source_task_id && node.input_variable) migrated.source_task_id = node.input_variable;
  if (id === "document_source" && !migrated.value) migrated.value = node.input_variable || node.path || node.url || "";
  if (id === "file_patch" && !migrated.operation) migrated.operation = node.operation || "write";
  if (id === "shell_test" && !migrated.command) migrated.command = node.command || node.instruction || "";
  return migrated;
}

function ensureWorkflow() {
  currentAgent = ensureAgent(currentAgent || {});
  if (!Array.isArray(currentAgent.workflow_nodes) || !currentAgent.workflow_nodes.length) {
    currentAgent.workflow_nodes = defaultWorkflowNodes();
  }
  if (!Array.isArray(currentAgent.workflow_edges) || !currentAgent.workflow_edges.length) {
    currentAgent.workflow_edges = defaultWorkflowEdges();
  }
  const legacyIds = new Set(["entry", "entry_gate", "context_bridge", "isolation_gate", "memory_recall", "plan", "risk_router", "parallel_branch", "parallel_research", "parallel_verify", "execute", "api_call", "transform", "approval", "human_handoff", "validation", "retry_loop", "checkpoint", "task_memory", "heartbeat", "notify", "archive"]);
  if (
    currentAgent.workflow_nodes.some((node) => ["entry_gate", "context_bridge", "isolation_gate"].includes(String(node.id || "")))
    && currentAgent.workflow_nodes.length <= legacyIds.size
    && currentAgent.workflow_nodes.every((node) => legacyIds.has(String(node.id || "")))
  ) {
    currentAgent.workflow_nodes = defaultWorkflowNodes();
    currentAgent.workflow_edges = defaultWorkflowEdges();
  }
  currentAgent.workflow_nodes = currentAgent.workflow_nodes.map((rawNode, index) => {
    const node = migrateWorkflowNodeShape(rawNode);
    const stage = workflowStage(node);
    return {
      ...node,
      id: String(node.id || `node_${index + 1}`).trim(),
      title: String(node.title || node.id || `节点 ${index + 1}`).trim(),
      kind: WORKFLOW_KINDS.includes(String(node.kind || "").trim()) ? String(node.kind).trim() : "state",
      stage,
      action: String(node.action || defaultWorkflowAction(node)).trim() || "manual",
      description: String(node.description || "").trim(),
      instruction: String(node.instruction || node.prompt || node.description || "").trim(),
      condition: String(node.condition || "").trim(),
      parallel_group: String(node.parallel_group || "").trim(),
      prompt: String(node.prompt || "").trim(),
      x: clamp(Number(node.x ?? defaultWorkflowPosition(stage, index).x), WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X),
      y: clamp(Number(node.y ?? defaultWorkflowPosition(stage, index).y), WORKFLOW_CANVAS_MIN_Y, WORKFLOW_CANVAS_MAX_Y),
    };
  });
  const ids = new Set(currentAgent.workflow_nodes.map((node) => node.id));
  currentAgent.workflow_edges = currentAgent.workflow_edges
    .map((edge) => ({
      ...edge,
      from: String(edge.from || "").trim(),
      to: String(edge.to || "").trim(),
      edge_type: workflowNormalizeEdgeType(String(edge.edge_type || edge.type || "success").trim() || "success"),
      condition: String(edge.condition || edge.when || "").trim(),
    }))
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

// 本插件自带工具（agent_lab_* / 本插件注册）默认开启；仅当方案里一个都没启用时才补齐，尊重用户后续的手动取舍。
function ensureOwnPluginToolsEnabled() {
  if (!currentAgent || !state) return;
  const mode = currentAgent.isolation_policy && currentAgent.isolation_policy.tool_mode;
  const enabled = currentAgent.enabled_tools || [];
  if (enabled.includes(EMPTY_TOOLS_SENTINEL) || mode === "no_external") return;
  const own = (state.tools || [])
    .filter((t) => t && (t.plugin_name === "astrbot_plugin_agent_lab" || String(t.name || "").startsWith("agent_lab_")))
    .map((t) => t.name)
    .filter(Boolean);
  if (!own.length) return;
  const set = new Set(enabled.filter((x) => x !== EMPTY_TOOLS_SENTINEL));
  if (own.some((n) => set.has(n))) return;
  own.forEach((n) => set.add(n));
  currentAgent.enabled_tools = Array.from(set).sort();
}

async function load(options = {}) {
  try {
    state = await api("/api/state");
    const agents = state.agents || [];
    if (!selectedAgentId || !agents.some((item) => item.agent_id === selectedAgentId)) {
      selectedAgentId = state.default_agent_id || agents[0]?.agent_id || "";
    }
    currentAgent = ensureAgent(clone(agents.find((item) => item.agent_id === selectedAgentId) || agents[0] || defaultAgentDraft()));
    ensureOwnPluginToolsEnabled();
    const tasks = [...(state.tasks || []), ...(state.archives || [])];
    if (!selectedTaskId || !tasks.some((item) => item.task_id === selectedTaskId)) {
      selectedTaskId = tasks[0]?.task_id || "";
    }
    $("bot-label").textContent = state.runtime?.bot_label || "等待读取";
    $("bot-source").textContent = identitySourceLabel(state.runtime?.bot_label_source);

    // 更新全局状态
    globalState.currentAgent = currentAgent;
    const activeTasks = (state.tasks || []).filter((task) => !task.finished_at && !["completed", "cancelled"].includes(task.status));
    globalState.activeTask = activeTasks[0] || null;
    globalState.taskRuntime = activeTaskRuntimeSeconds(globalState.activeTask);
    if (activeTasks.some((task) => pendingApprovalCount(task))) globalState.status = "waiting";
    else globalState.status = globalState.activeTask ? "running" : "idle";
    globalState.tokenCurrent = Number(state.metrics?.token_usage || 0) || totalTokenUsage([...(state.tasks || []), ...(state.archives || [])]);

    updateStatusBar();

    if (!options.silent) setFeedback("已连接独立控制台。");
    render();
  } catch (error) {
    setFeedback(`连接失败：${error.message}`, "error");
    renderLocked();
    throw error;
  }
}

function renderNav() {
  const nav = $("nav");
  if (nav) {
    nav.innerHTML = sections
      .map(
        ([id, title, meta]) => `
          <button class="${route === id ? "active" : ""}" data-route="${id}" type="button">
            <strong>${title}</strong><br />
            <span>${meta}</span>
          </button>
        `,
      )
      .join("");
  }
  const found = sections.find(([id]) => id === route) || sections[0];
  if ($("section-title")) $("section-title").textContent = found[1];
  if ($("section-kicker")) $("section-kicker").textContent = found[2];
}

// 全局焦点/光标保留：任何 render() 重建 DOM 后，把焦点和光标还回原来的输入框，
// 这样无论哪条路径触发了 render，用户都不会掉焦、丢字或被“复原”。
// 统一“重绘保焦/保滚动”：render() 在重建 DOM 前记录当前聚焦的表单控件和关键滚动容器位置，
// 重建后同步恢复。任何重绘都不再丢焦、不再让抽屉滚动条跳回顶端。
const FOCUS_SCROLL_KEYS = [
  ".workflow-inspector-drawer .drawer-scroll",
  ".workflow-tool-drawer .drawer-scroll",
  ".workflow-global-drawer .drawer-scroll",
  ".workflow-report-panel .drawer-scroll",
  ".memory-detail-drawer .drawer-content",
];
function activeFieldSnapshotGlobal() {
  const snap = { scrolls: [], field: null };
  FOCUS_SCROLL_KEYS.forEach((key) => {
    const el = document.querySelector(key);
    if (el && el.scrollTop > 0) snap.scrolls.push({ key, top: el.scrollTop });
  });
  const el = document.activeElement;
  if (el && typeof el.matches === "function" && el.matches("input, textarea, select")) {
    let key = "";
    if (el.id) key = `#${(window.CSS && CSS.escape) ? CSS.escape(el.id) : el.id}`;
    else if (el.dataset && el.dataset.action) key = `[data-action="${el.dataset.action}"]`;
    else if (el.dataset && el.dataset.field) key = `[data-field="${el.dataset.field}"]`;
    if (key) {
      snap.field = { key };
      try {
        if (typeof el.selectionStart === "number") { snap.field.start = el.selectionStart; snap.field.end = el.selectionEnd; }
      } catch (err) {}
    }
  }
  try {
    const winTop = window.scrollY || document.scrollingElement?.scrollTop || 0;
    if (winTop > 0) snap.winScroll = winTop;
  } catch (err) {}
  return (snap.field || snap.scrolls.length || snap.winScroll) ? snap : null;
}
function restoreFieldFocusGlobal(snap) {
  if (!snap) return;
  (snap.scrolls || []).forEach((s) => {
    const el = document.querySelector(s.key);
    if (el) el.scrollTop = s.top;
  });
  if (snap.winScroll) {
    try { window.scrollTo(0, snap.winScroll); } catch (err) {}
  }
  const f = snap.field;
  if (!f || !f.key) return;
  let el = null;
  try { el = document.querySelector(f.key); } catch (err) { return; }
  if (!el || typeof el.matches !== "function" || !el.matches("input, textarea, select")) return;
  if (el.tagName === "SELECT") return; // 不重新聚焦原生下拉：重焦会把刚展开的 <select> 关掉
  if (document.activeElement === el) return;
  try { el.focus({ preventScroll: true }); } catch (err) { try { el.focus(); } catch (err2) {} }
  if (typeof f.start === "number" && typeof el.setSelectionRange === "function") {
    try { el.setSelectionRange(f.start, typeof f.end === "number" ? f.end : f.start); } catch (err) {}
  }
}
function render() {
  const __focusSnap = activeFieldSnapshotGlobal();
  const viewport = route === "workflow" && workflowViewportInitialized ? workflowViewportSnapshot() : null;
  document.body.dataset.route = route;
  document.body.classList.toggle("workflow-nav-collapsed", route === "workflow" && workflowNavCollapsed);
  if (!workflowMaterialChipDrag) { document.querySelectorAll(".workflow-drag-ghost").forEach((el) => el.remove()); workflowDragGhostEl = null; }
  renderNav();
  if (!state) { restoreFieldFocusGlobal(__focusSnap); return; }
  syncLiveRefresh();
  if (route === "dashboard") renderDashboard();
  if (route === "canvas") renderCanvas();
  if (route === "workflow") renderWorkflowPage();
  if (route === "memory") renderMemoryPage();
  if (route === "tasks") renderCanvas();
  if (route === "monitor") renderMonitor();
  if (route === "integrations") renderIntegrations();
  if (route === "settings") renderSettingsPage();
  restoreWorkflowViewport(viewport);
  if (route === "workflow") refreshWorkflowCanvasDom();
  restoreFieldFocusGlobal(__focusSnap);
}

function syncLiveRefresh() {
  if (liveTimer) {
    clearInterval(liveTimer);
    liveTimer = null;
  }
  if (["dashboard", "tasks", "monitor"].includes(route)) {
    liveTimer = setInterval(() => {
      // 任意路由下只要用户正在输入/选择，就跳过这次静默刷新，避免 render() 重建 DOM 把焦点和未保存输入冲掉。
      const editing = document.activeElement?.matches?.("input, textarea, select");
      if (editing) return;
      if (["dashboard", "tasks", "monitor"].includes(route)) load({ silent: true });
    }, 5000);
  }
}

function renderLocked() {
  renderNav();
  $("view").innerHTML = `
    <section class="panel">
      <h2>需要连接独立控制台</h2>
      <p class="row-meta">请确认插件的独立控制台已经启动，然后刷新页面。</p>
    </section>
  `;
}

function metric(label, value, note = "") {
  return `<div class="metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${note ? `<div class="row-meta">${esc(note)}</div>` : ""}</div>`;
}

function badge(text, tone = "") {
  return `<span class="badge ${tone}">${esc(text)}</span>`;
}

function statusTone(status) {
  if (status === "running") return "ok";
  if (status === "blocked" || status === "cancelled") return "bad";
  if (status === "paused" || status === "waiting") return "warn";
  if (status === "completed") return "ok";
  return "";
}

function healthTone(health = {}) {
  const stateValue = health.state || "";
  if (stateValue === "online") return "ok";
  if (["stale", "blocked"].includes(stateValue)) return "bad";
  if (["idle", "off"].includes(stateValue)) return "warn";
  return "";
}

function selectedAgentTasks() {
  const id = currentAgent?.agent_id || selectedAgentId;
  return (state.tasks || []).filter((task) => !id || task.agent_id === id);
}

function activeTasks() {
  return (state.tasks || []).filter((task) => !task.finished_at && !["completed", "cancelled"].includes(task.status));
}

function taskActivityScore(task) {
  return (task.progress_log?.length || 0) + (task.workflow_events?.length || 0) + (task.state_snapshots?.length || 0);
}

function runtimeDistribution() {
  const tasks = [...(state.tasks || []), ...(state.archives || [])];
  const buckets = [
    ["<5m", 0],
    ["5-30m", 0],
    ["30m-2h", 0],
    [">2h", 0],
  ];
  tasks.forEach((task) => {
    const seconds = activeTaskRuntimeSeconds(task);
    if (seconds < 300) buckets[0][1] += 1;
    else if (seconds < 1800) buckets[1][1] += 1;
    else if (seconds < 7200) buckets[2][1] += 1;
    else buckets[3][1] += 1;
  });
  return buckets;
}

function activityBars(task = null, count = 18) {
  const rows = task
    ? [...(task.progress_log || []), ...(task.state_snapshots || []), ...(task.workflow_events || [])]
    : [...(state.tasks || []), ...(state.archives || [])].flatMap((item) => [
        ...(item.progress_log || []),
        ...(item.state_snapshots || []),
        ...(item.workflow_events || []),
      ]);
  const recent = rows.slice(-count);
  if (!recent.length) {
    return Array.from({ length: count }, (_, index) => `<span style="height:${10 + (index % 4) * 5}px"></span>`).join("");
  }
  return Array.from({ length: count }, (_, index) => {
    const item = recent[index - (count - recent.length)];
    const base = item ? 18 + ((index * 13) % 42) : 8;
    const bad = item && ["blocked", "error"].includes(String(item.status || item.kind || "").toLowerCase());
    return `<span class="${bad ? "bad" : ""}" style="height:${base}px" title="${esc(item?.time || "")}"></span>`;
  }).join("");
}

function runOverview() {
  const tasks = activeTasks();
  const task = globalState.activeTask || tasks[0] || null;
  const health = task?.heartbeat_health || {};
  const approvals = tasks.reduce((sum, item) => sum + pendingApprovalCount(item), 0);
  const mode = currentAgent?.trigger_mode || "confirm";
  const liveClass = task ? "live" : "";
  return `
    <section class="run-overview panel ${liveClass}">
      <div class="run-overview-main">
        <div class="live-ring ${task ? "running" : ""}"><span></span></div>
        <div>
          <p class="card-kicker">当前状态</p>
          <h2>${task ? esc(task.root_goal || task.task_id) : "当前没有运行中的任务"}</h2>
          <div class="module-meta">
            ${badge(agentDisplayName(currentAgent), "ok")}
            ${badge(triggerLabel(mode))}
            ${badge(task ? taskStatusLabel(task.status) : "空闲", task ? statusTone(task.status) : "")}
            ${badge(healthLabel(health), healthTone(health))}
          </div>
          <div class="row-meta">
            ${task ? `${esc(shortId(task.task_id, 14))} · 已运行 ${formatRuntime(activeTaskRuntimeSeconds(task))} · 下一步：${esc(task.next_step || "等待下一轮推进")}` : "普通会话保持原状；进入任务后这里会显示运行、心跳、审批和消耗。"}
          </div>
        </div>
      </div>
      <div class="run-overview-side">
        <div class="activity-bars">${activityBars(task)}</div>
        <div class="mini-stats">
          <span>活跃 ${tasks.length}</span>
          <span>审批 ${approvals}</span>
          <span>记忆 ${state.memories?.length || 0}</span>
          <span>日志 ${task?.progress_log?.length || 0}</span>
        </div>
      </div>
    </section>
  `;
}

function systemStatusPanel() {
  const m = state.metrics || {};
  const webui = state.webui || {};
  const pluginCount = state.plugins?.length || 0;
  const toolCount = state.tools?.length || 0;
  const apiCount = state.custom_apis?.length || 0;
  return `
    <section class="panel system-status-panel">
      <div class="panel-head"><div><p class="card-kicker">系统状态</p><h2>心跳、存储、插件</h2></div></div>
      <div class="status-grid">
        ${statusTile("心跳正常", m.heartbeat_online || 0, "ok", `${m.heartbeat_stale || 0} 异常 / ${m.heartbeat_offline || 0} 未开启`)}
        ${statusTile("记忆条目", state.memories?.length || 0, "", `${formatBytes(memoryEstimatedBytes())} 估算`)}
        ${statusTile("插件/工具", `${pluginCount}/${toolCount}`, "ok", `${apiCount} 个自定义接口`)}
        ${statusTile("网页控制台", webui.standalone ? "在线" : "未启动", webui.standalone ? "ok" : "warn", webui.url || "等待启动")}
      </div>
    </section>
  `;
}

function statusTile(label, value, tone = "", note = "") {
  return `
    <div class="status-tile ${tone}">
      <span>${esc(label)}</span>
      <strong>${esc(value)}</strong>
      <small>${esc(note)}</small>
    </div>
  `;
}

function memoryEstimatedBytes() {
  return (state.memories || []).reduce((sum, item) => sum + new Blob([JSON.stringify(item)]).size, 0);
}

function formatBytes(bytes) {
  bytes = Number(bytes || 0);
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function tagCloud(limit = 24) {
  const counts = new Map();
  (state.memories || []).forEach((item) => {
    (item.tags || []).forEach((tag) => {
      const key = String(tag || "").trim();
      if (key) counts.set(key, (counts.get(key) || 0) + 1);
    });
  });
  const tags = Array.from(counts.entries()).sort((a, b) => b[1] - a[1]).slice(0, limit);
  if (!tags.length) return `<div class="empty">暂无标签。</div>`;
  return tags.map(([tag, count]) => `<span class="memory-tag-chip">${esc(tag)} <b>${count}</b></span>`).join("");
}

function memoryStats() {
  const rows = state.memories || [];
  const countBy = (status) => rows.filter((item) => item.status === status).length;
  return `
    <div class="memory-stats">
      ${memoryStatCard("全部记忆", rows.length, formatBytes(memoryEstimatedBytes()))}
      ${memoryStatCard("候选", countBy("candidate"), "等待确认")}
      ${memoryStatCard("已接受", countBy("accepted"), "可复用上下文")}
      ${memoryStatCard("已拒绝", countBy("rejected"), "不会主动带入")}
    </div>
  `;
}

function memoryStatCard(label, value, note) {
  return `
    <div class="memory-stat-card">
      <div class="stat-number">${esc(value)}</div>
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-size">${esc(note)}</div>
    </div>
  `;
}

function taskProgressPercent(task) {
  if (!task) return 0;
  const signals = [
    task.current_summary,
    task.last_confirmed_progress,
    task.next_step,
    task.last_observation,
    ...(task.workflow_path || []),
    ...(task.state_snapshots || []),
  ].filter(Boolean).length;
  if (task.status === "completed") return 100;
  if (task.status === "cancelled") return 100;
  return clamp(Math.round(Math.min(95, signals * 8 + (task.progress_log?.length || 0) * 2)), 4, 95);
}

function taskConsoleRows(tasks, archive = false) {
  if (!tasks.length) return `<div class="empty">${archive ? "暂无归档任务。" : "暂无活跃任务。"}</div>`;
  return tasks.map((task) => {
    const progress = taskProgressPercent(task);
    const selected = task.task_id === selectedTaskId;
    return `
      <button class="task-card ${selected ? "active" : ""}" data-action="select-task" data-id="${esc(task.task_id)}" type="button">
        <div class="row-title">
          <span>${esc(task.root_goal || task.task_id)}</span>
          ${badge(taskStatusLabel(task.status || (archive ? "completed" : "running")), statusTone(task.status))}
        </div>
        <div class="row-meta">${esc(task.agent_name || task.agent_id || "-")} · ${esc(shortId(task.task_id, 12))}</div>
        <div class="task-progress"><div class="task-progress-fill" style="width:${progress}%"></div></div>
      </button>
    `;
  }).join("");
}

function liveConsolePanel(task, canControl = Boolean(task)) {
  const health = task?.heartbeat_health || {};
  const heartbeatPoints = task?.state_snapshots?.slice(-22) || [];
  return `
    <section class="panel live-console-panel">
      <div class="panel-head">
        <div><p class="card-kicker">实时感知</p><h2>${task ? "Agent 正在留下痕迹" : "等待任务启动"}</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-action="restart-heartbeat" ${canControl ? "" : "disabled"} type="button">重启心跳</button>
          <button class="button secondary" data-action="tick-task" ${canControl ? "" : "disabled"} type="button">Tick</button>
        </div>
      </div>
      <div class="live-strip">
        <div class="live-ring ${task ? "running" : ""}"><span></span></div>
        <div>
          <strong>${esc(task?.next_step || task?.last_confirmed_progress || "暂无下一步")}</strong>
          <p>${esc(task ? `${healthLabel(health)} · ${ageText(health.seconds_since_pulse)} · ${taskActivityScore(task)} 个活动信号` : "启动任务后这里会滚动显示日志、心跳和节点事件。")}</p>
        </div>
      </div>
      <div class="heartbeat-chart">${heartbeatPoints.map((point, index) => {
        const bad = point.status === "blocked" || ["stale", "blocked"].includes(health.state);
        return `<span title="${esc(point.time || "")}" class="${bad ? "bad" : ""}" style="height:${18 + (index % 7) * 7}px"></span>`;
      }).join("") || "<em>暂无心跳曲线</em>"}</div>
      <div class="console-log-panel">
        <div class="log-header"><strong>Live Log</strong><span>5s refresh</span></div>
        <div class="log-content">${logRows(task)}</div>
      </div>
    </section>
  `;
}

function taskRuntimeMonitorPanel(task) {
  if (!task) return "";
  const health = task.heartbeat_health || {};
  const currentNode = task.workflow_current_node_id || "-";
  const outbox = task.outbox || [];
  const history = task.outbox_delivery_history || [];
  const blockers = task.blockers || [];
  return `
    <section class="panel">
      <div class="panel-head">
        <div><p class="card-kicker">运行监控</p><h2>实时状态</h2></div>
      </div>
      <div class="detail-box">
        <div class="mini-stats">
          <span>节点 ${esc(currentNode)}</span>
          <span>待发 ${outbox.length}</span>
          <span>已发 ${history.length}</span>
          <span>阻塞 ${blockers.length}</span>
        </div>
        <div class="state-fields">
          ${stateField("心跳状态", healthLabel(health))}
          ${stateField("心跳距离", ageText(health.seconds_since_pulse || 0))}
        </div>
      </div>
      ${outbox.length ? `
        <div class="panel-head"><div><p class="card-kicker">Outbox</p><h3>待发消息</h3></div></div>
        <div class="list">
          ${outbox.map((item) => `
            <div class="list-row">
              <div class="row-title"><span>${esc(item.message || "-")}</span>${badge(item.delivery || "pending", "warn")}</div>
              <div class="row-meta">目标：${esc(item.target || "-")} ${item.image ? "· 含图片" : ""} ${item.face ? `· 表情 ${item.face}` : ""}</div>
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${history.length ? `
        <div class="panel-head"><div><p class="card-kicker">已发历史</p><h3>最近 ${Math.min(history.length, 10)} 条</h3></div></div>
        <div class="list">
          ${history.slice(-10).reverse().map((item) => `
            <div class="list-row">
              <div class="row-title"><span>${esc(item.message || "-")}</span>${badge("已发送", "ok")}</div>
              <div class="row-meta">${esc(item.delivered_at || "-")} · ${esc(item.target || "-")}</div>
            </div>
          `).join("")}
        </div>
      ` : ""}
      ${blockers.length ? `
        <div class="panel-head"><div><p class="card-kicker">阻塞器</p><h3>${blockers.length} 项</h3></div></div>
        <div class="list">
          ${blockers.map((item) => {
            const isResolved = item.resolved_at;
            return `
            <div class="list-row">
              <div class="row-title"><span>${esc(item.reason || item)}</span>${badge(isResolved ? "已解除" : "阻塞中", isResolved ? "ok" : "bad")}</div>
              <div class="row-meta">节点：${esc(item.node_id || "-")} · 创建：${esc(item.created_at || "-")}${isResolved ? ` · 解除：${esc(item.resolved_at)}` : ""}</div>
            </div>
          `}).join("")}
        </div>
      ` : ""}
      ${(() => {
        const wd = task.watchdog || {};
        if (!Object.keys(wd).length) return "";
        const healthStatus = wd.health_status || "unknown";
        const statusColor = healthStatus === "healthy" ? "ok" : healthStatus === "warning" ? "warn" : "bad";
        return `
          <div class="panel-head"><div><p class="card-kicker">Watchdog</p><h3>状态监控</h3></div></div>
          <div class="detail-box">
            <div class="state-fields">
              ${stateField("健康状态", badge(healthStatus, statusColor))}
              ${stateField("需要用户", wd.needs_user ? badge("是", "warn") : badge("否", "ok"))}
              ${stateField("连续失败", `${wd.consecutive_failures || 0} 次`)}
              ${stateField("上次成功", ageText((Date.now() / 1000) - (new Date(wd.last_success_at || 0).getTime() / 1000)))}
            </div>
          </div>
        `;
      })()}
      ${(() => {
        const reports = task.workflow_data?.reports || [];
        return reports.length ? `
          <div class="panel-head"><div><p class="card-kicker">Reports</p><h3>最近 ${Math.min(reports.length, 10)} 条</h3></div></div>
          <div class="list">
            ${reports.slice(-10).reverse().map((r) => `
              <div class="list-row">
                <div class="row-title"><span>${esc(r.report_type || "report")}</span></div>
                <div class="row-meta">${esc(r.content || "-")} · ${esc(r.timestamp || "-")}</div>
              </div>
            `).join("")}
          </div>
        ` : "";
      })()}
      ${(() => {
        const records = task.workflow_data?.records || [];
        return records.length ? `
          <div class="panel-head"><div><p class="card-kicker">Records</p><h3>最近 ${Math.min(records.length, 10)} 条</h3></div></div>
          <div class="list">
            ${records.slice(-10).reverse().map((rec) => `
              <div class="list-row">
                <div class="row-title"><span>${esc(rec.record_type || "record")}</span></div>
                <div class="row-meta">${esc(JSON.stringify(rec.data || {}))}&nbsp;· ${esc(rec.timestamp || "-")}</div>
              </div>
            `).join("")}
          </div>
        ` : "";
      })()}
    </section>
  `;
}

function settingsExportPayload() {
  return {
    agent: currentAgent || {},
    workflow: workflowData(),
    memory_count: state.memories?.length || 0,
    integrations: {
      custom_apis: state.custom_apis?.length || 0,
      credentials: state.credentials?.length || 0,
      modules: (state.integrations || state.modules || []).length,
    },
  };
}

function agentPolicyOverview() {
  const agent = ensureAgent(currentAgent || {});
  const cards = [
    ["触发配置", triggerLabel(agent.trigger_mode || "confirm"), `入口：${entryChannelLabel(agent.entry_channel)} / 确认：${agent.entry_policy.require_confirmation === false ? "关闭" : "开启"}`],
    ["隔离策略", isolationModeLabel(agent.isolation_policy.mode || "strict"), `工具：${toolModeLabel(agent.isolation_policy.tool_mode || "whitelist")} / 退出恢复：${agent.isolation_policy.restore_on_exit === false ? "否" : "是"}`],
    ["记忆策略", memoryModeLabel(agent.memory_policy.mode || "task_filtered"), `摘要 ${agent.memory_policy.entry_summary_turns || 24} 轮 / 长期记忆：${agent.memory_policy.allow_long_memory === false ? "关" : "开"}`],
    ["审批策略", approvalModeLabel(agent.approval_policy.mode || "work"), `必审 ${agent.approval_policy.require_approval?.length || 0} 项 / 预授权 ${agent.approval_policy.preapproved_scopes?.length || 0} 条`],
    ["心跳策略", heartbeatModeLabel(agent.heartbeat_policy.mode || "manual"), `${agent.heartbeat_policy.allowed === false ? "禁止" : "允许"} / ${agent.heartbeat_policy.cron_expression || "*/5 * * * *"}`],
    ["提示词", agent.system_prompt ? "已配置" : "默认协议", `任务协议 ${String(agent.task_prompt || "").length} 字符`],
  ];
  return `
    <section class="policy-overview">
      ${cards.map(([title, value, note]) => `
        <div class="policy-card">
          <span>${esc(title)}</span>
          <strong>${esc(value)}</strong>
          <small>${esc(note)}</small>
        </div>
      `).join("")}
    </section>
  `;
}

function renderSettingsPage() {
  currentAgent = ensureAgent(currentAgent || {});
  const webui = state.webui || {};
  $("view").innerHTML = `
    <section class="settings-page">
      <div class="panel-head">
        <div><p class="card-kicker">设置</p><h2>插件配置、模块状态、导入导出</h2></div>
        <button class="button" data-action="save-agent" type="button">保存当前配置</button>
      </div>
      <section class="grid three">
        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">插件配置</p><h3>网页控制台</h3></div></div>
          <div class="state-fields single">
            ${stateField("控制台地址", webui.url || "-")}
            ${stateField("运行状态", webui.standalone ? "独立控制台在线" : "独立控制台未启动")}
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">模块配置</p><h3>运行能力</h3></div></div>
          <div class="state-fields single">
            ${stateField("工具目录", `${state.tools?.length || 0} 个工具`)}
            ${stateField("多视角/验证", `${(state.integrations || state.modules || []).length} 个蓝图模块`)}
            ${stateField("沙箱/外部接口", `${state.custom_apis?.length || 0} 个接口 / ${state.credentials?.length || 0} 个凭证`)}
          </div>
        </div>
        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">导入/导出</p><h3>当前草稿</h3></div></div>
          <textarea rows="10" readonly>${esc(JSON.stringify(settingsExportPayload(), null, 2))}</textarea>
        </div>
      </section>
    </section>
  `;
}

function renderDashboard() {
  const agents = state.agents || [];
  const tasks = state.tasks || [];
  const archives = state.archives || [];
  const selectedStats = currentAgent ? agentStats(currentAgent) : null;
  const runtimeBuckets = runtimeDistribution();

  $("view").innerHTML = `
    <section class="dashboard-page">
      ${runOverview()}
      <div class="stats-cards">
        <div class="stat-card">
          <div class="stat-icon">${iconImg("book", "Agent")}</div>
          <div class="stat-content">
            <div class="stat-value">${agents.length}</div>
            <div class="stat-label">Agent 配置</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">${iconImg("gridAdd", "任务")}</div>
          <div class="stat-content">
            <div class="stat-value">${tasks.length}</div>
            <div class="stat-label">活跃任务</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">${iconImg("select", "归档")}</div>
          <div class="stat-content">
            <div class="stat-value">${archives.length}</div>
            <div class="stat-label">已完成任务</div>
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-icon">${iconImg("memory", "记忆")}</div>
          <div class="stat-content">
            <div class="stat-value">${state.memories?.length || 0}</div>
            <div class="stat-label">任务记忆</div>
          </div>
        </div>
      </div>

      <section class="dashboard-main-grid">
        <div class="panel">
          <div class="panel-head">
            <div><p class="card-kicker">Agent 配置</p><h2>健康度、触发、消耗</h2></div>
            <button class="button secondary" data-route="canvas" type="button">配置 Agent</button>
          </div>
          <div class="agent-health-grid">
            ${agents.map(agent => {
              const selected = agent.agent_id === selectedAgentId;
              const isDefault = agent.agent_id === state.default_agent_id;
              const stats = agentStats(agent);
              return `
                <button class="agent-health-card ${selected ? 'selected' : ''}" data-action="select-agent" data-id="${esc(agent.agent_id)}" type="button">
                  <div class="agent-health-header">
                    <strong>${esc(agentDisplayName(agent))}</strong>
                    <span class="row-badges">
                      ${isDefault ? badge("默认", "ok") : ""}
                      ${badge(stats.health_label, stats.health_tone)}
                    </span>
                  </div>
                    <div class="agent-health-stats">
                    <div class="health-stat"><span class="health-stat-value">${stats.triggers}</span><span class="health-stat-label">触发</span></div>
                    <div class="health-stat"><span class="health-stat-value">${formatTokens(stats.tokens)}</span><span class="health-stat-label">消耗</span></div>
                    <div class="health-stat"><span class="health-stat-value">${stats.approvals}</span><span class="health-stat-label">审批</span></div>
                  </div>
                </button>
              `;
            }).join('') || `<div class="empty">还没有 Agent 配置。</div>`}
          </div>
        </div>

        <div class="panel">
          <div class="panel-head"><div><p class="card-kicker">运行时间分布</p><h2>${selectedStats ? esc(agentDisplayName(currentAgent)) : "全局"}</h2></div></div>
          <div class="runtime-buckets">
            ${runtimeBuckets.map(([label, count]) => `
              <div class="runtime-bucket">
                <span>${esc(label)}</span>
                <strong>${count}</strong>
                <div><i style="width:${Math.min(100, Math.max(8, count * 18))}%"></i></div>
              </div>
            `).join("")}
          </div>
          <div class="activity-bars dashboard-activity">${activityBars(null, 24)}</div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <div><p class="card-kicker">活跃任务</p><h2>正在运行</h2></div>
            <button class="button secondary" data-route="tasks" type="button">查看全部</button>
          </div>
          <div class="list">${tasks.length === 0 ? '<div class="empty">暂无活跃任务</div>' : taskRows(tasks.slice(0, 6))}</div>
        </div>

        ${systemStatusPanel()}
      </section>

      <section class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">最近归档</p><h2>已结束任务</h2></div>
          <button class="button secondary" data-route="memory" type="button">任务记忆</button>
        </div>
        <div class="list">${archives.length === 0 ? '<div class="empty">暂无归档任务</div>' : taskRows(archives.slice(0, 8), true)}</div>
      </section>
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
            <span>消耗 ${formatTokens(stats.tokens)}</span>
            <span>审批 ${stats.approvals}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function workflowAutomationPanel() {
  const agent = ensureAgent(currentAgent || {});
  const trigger = agent.workflow_trigger || {};
  const scope = agent.workflow_scope || {};
  const stats = agentStats(agent);
  return `
    <section class="panel">
      <div class="panel-head">
        <div><p class="card-kicker">工作流自动化</p><h2>启动方式、生效范围和运行概览</h2></div>
        <button class="button secondary" data-route="workflow" type="button">切到画布编辑</button>
      </div>
      <div class="mini-stats workflow-report-stats">
        <span>${agent.workflow_nodes?.length || 0} 节点</span>
        <span>${agent.workflow_edges?.length || 0} 连线</span>
        <span>运行 ${stats.active}</span>
        <span>历史触发 ${stats.triggers}</span>
      </div>
      <div class="section-note">触发条件已统一到<strong>画布入口节点</strong>配置（暗号 / 命令 / 关键词 / 正则 / 自然语言 / 定时 / 插件事件 / Webhook / 进入前确认 / 启用开关）。当前：${esc(workflowTriggerSummary(agent))}。 <button class="button tiny secondary" data-route="workflow" type="button">去入口节点配置</button></div>
      <div class="form-grid task-mode-form">
        <label class="span-2">生效会话<div class="choice-grid compact-choice">${checkboxGroupHtml("workflow-chat-type", WORKFLOW_CHAT_TYPES, scope.chat_types || ["private"], workflowChatTypeLabel)}</div></label>
        <label>仅管理员<select id="workflow-scope-admin-only">${labeledOptions(["false", "true"], String(scope.admin_only === true), (value) => value === "true" ? "仅管理员 QQ" : "按白名单/黑名单")}</select></label>
        <label>平台白名单<textarea id="workflow-scope-platforms" rows="2" placeholder="aiocqhttp">${esc(listToLines(scope.platforms || []))}</textarea></label>
        <label>UMO 白名单<textarea id="workflow-scope-umo-allow" rows="2">${esc(listToLines(scope.umo_allowlist || []))}</textarea></label>
        <label>UMO 黑名单<textarea id="workflow-scope-umo-deny" rows="2">${esc(listToLines(scope.umo_denylist || []))}</textarea></label>
        <label>群白名单<textarea id="workflow-scope-group-allow" rows="2">${esc(listToLines(scope.group_allowlist || []))}</textarea></label>
        <label>群黑名单<textarea id="workflow-scope-group-deny" rows="2">${esc(listToLines(scope.group_denylist || []))}</textarea></label>
        <label>用户白名单<textarea id="workflow-scope-user-allow" rows="2">${esc(listToLines(scope.user_allowlist || []))}</textarea></label>
        <label>用户黑名单<textarea id="workflow-scope-user-deny" rows="2">${esc(listToLines(scope.user_denylist || []))}</textarea></label>
      </div>
      <div class="note-line">当前：${esc(workflowTriggerSummary(agent))} / ${esc(workflowScopeSummary(agent))}</div>
    </section>
  `;
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

function taskPatternSuggestions() {
  const rows = (state.task_patterns || [])
    .slice()
    .sort((a, b) => Number(b.success_count || 0) - Number(a.success_count || 0) || Number(b.usage_count || 0) - Number(a.usage_count || 0))
    .slice(0, 4);
  if (!rows.length) {
    return `<div class="section-note compact">暂无历史相似计划。完成并归档任务后，这里会出现可复用的计划模板。</div>`;
  }
  return `
    <section class="task-pattern-suggestions">
      <div class="panel-head compact-head"><div><p class="card-kicker">历史计划建议</p><h3>可复用的任务路径</h3></div></div>
      <div class="pattern-grid">
        ${rows.map((pattern) => {
          const steps = (pattern.steps || []).slice(0, 4);
          return `
            <article class="pattern-card">
              <div class="row-title">
                <span>${esc(pattern.title || pattern.pattern_id || "历史计划")}</span>
                ${badge(`成功 ${pattern.success_count || 0}`, "ok")}
              </div>
              <p>${esc(pattern.summary || "这个计划还没有摘要。")}</p>
              <div class="pattern-steps">
                ${steps.map((step) => `<span>${esc(step.title || step.node_id || workflowActionLabel(step.action || "manual"))}</span>`).join("")}
              </div>
              <div class="row-meta">${esc(pattern.pattern_id || "")}${pattern.usage_count ? ` · 使用 ${esc(pattern.usage_count)}` : ""}</div>
              <div class="inline-actions">
                <button class="button secondary tiny" data-action="apply-task-pattern" data-id="${esc(pattern.pattern_id)}" type="button">带入入口补充</button>
                <button class="button secondary tiny" data-action="apply-task-pattern-goal" data-id="${esc(pattern.pattern_id)}" type="button">带入目标</button>
              </div>
            </article>
          `;
        }).join("")}
      </div>
    </section>
  `;
}

function taskPatternBriefText(pattern) {
  const steps = (pattern.steps || [])
    .slice(0, 12)
    .map((step, index) => `${index + 1}. ${step.title || step.node_id || workflowActionLabel(step.action || "manual")}${step.success_condition ? `：${step.success_condition}` : ""}`)
    .join("\n");
  const capabilities = (pattern.required_capabilities || []).slice(0, 10).join(", ");
  return [
    `参考历史计划：${pattern.title || pattern.pattern_id || "未命名计划"}`,
    pattern.source_task_id ? `来源任务：${pattern.source_task_id}` : "",
    pattern.summary ? `摘要：${pattern.summary}` : "",
    capabilities ? `建议能力：${capabilities}` : "",
    steps ? `建议步骤：\n${steps}` : "",
    "请按当前任务目标重新核对差异，不要照搬旧任务的事实结论。",
  ].filter(Boolean).join("\n");
}

function renderCanvas() {
  currentAgent = ensureAgent(currentAgent || {});
  ensureWorkflow();
  const a = currentAgent;
  const agents = state.agents || [];
  const task = selectedTask();
  const runnableTask = activeTask();
  const liveTask = runnableTask || (state.tasks || [])[0] || null;
  const activeRows = state.tasks || [];
  const archivedRows = state.archives || [];
  const longTask = workflowHeartbeatOn(a);
  $("view").innerHTML = `
    <section class="scheme-page">
      <aside class="scheme-sidebar">
        <div class="panel scheme-list-panel">
          <div class="panel-head">
            <div><p class="card-kicker">方案管理</p><h2>流程方案</h2></div>
          </div>
          <div class="button-row scheme-actions">
            <button class="button" data-action="new-agent" type="button">新建方案</button>
            <button class="button secondary" data-action="duplicate-agent" type="button" ${a.agent_id ? "" : "disabled"}>复制</button>
            <button class="button danger" data-action="delete-agent" type="button" ${(agents.length <= 1 || !a.agent_id) ? "disabled" : ""}>删除方案</button>
          </div>
          <div class="list scheme-list">${agentRows()}</div>
        </div>
      </aside>

      <main class="scheme-main">
        <section class="panel scheme-hero">
          <div class="panel-head">
            <div>
              <p class="card-kicker">当前方案</p>
              <h2>${esc(agentDisplayName(a))}</h2>
            </div>
            <div class="inline-actions">
              <button class="button secondary" data-action="rename-agent" type="button" ${a.agent_id ? "" : "disabled"}>重命名</button>
              <button class="button" data-route="workflow" type="button">在画布编辑这个方案</button>
            </div>
          </div>
          <div class="module-meta">
            ${badge(a.enabled === false ? "已停用" : "已启用", a.enabled === false ? "bad" : "ok")}
            ${badge(longTask ? "长任务·可续跑" : "事件/静态自动化", "info")}
            ${badge(triggerLabel(a.trigger_mode || "confirm"))}
            ${badge(`${a.workflow_nodes?.length || 0} 节点 / ${a.workflow_edges?.length || 0} 连线`)}
          </div>
          <p class="setting-hint-line">是否全局应用、入口方式、生效范围（群聊/私聊、黑白名单）等，现在都在<a data-route="workflow" class="inline-link">工作流画布</a>里用节点设置。这里只管方案的新建、切换和运行情况。</p>
        </section>

        <section class="panel task-entry-panel">
          <div class="panel-head">
            <div><p class="card-kicker">手动入口</p><h2>用这个方案进入任务模式</h2></div>
          </div>
          <div class="form-grid task-entry-grid">
            <label>会话 UMO<input id="umo" placeholder="aiocqhttp:FriendMessage:123456" /></label>
            <label>风险级别<select id="task-risk-level">${labeledOptions(["low", "work", "high"], "work", (value) => ({ low: "低风险", work: "工作风险", high: "高风险" }[value] || value))}</select></label>
            <label class="span-2">任务目标<textarea id="goal" rows="2">请把当前任务作为任务模式管理起来。</textarea></label>
            <label class="span-2">完成条件<input id="completion" value="${esc((a.entry_policy.default_completion_conditions || ["用户验收通过"]).join("；"))}" /></label>
            <label class="span-2">入口补充<textarea id="brief" rows="2"></textarea></label>
            <label class="check-line span-2"><input id="task-start-heartbeat" type="checkbox" />进入后立即开心跳</label>
          </div>
          ${taskPatternSuggestions()}
          <div class="button-row">
            <button class="button" data-action="start-task" type="button">进入任务模式</button>
            <button class="button secondary" data-action="simulate-trigger" type="button">模拟触发</button>
          </div>
        </section>

        ${liveConsolePanel(liveTask, Boolean(runnableTask))}

        ${taskRuntimeMonitorPanel(runnableTask)}

        <section class="panel">
          <div class="panel-head">
            <div><p class="card-kicker">运行中的任务</p><h2>活跃 ${activeRows.length} · 归档 ${archivedRows.length}</h2></div>
          </div>
          <div class="task-list scheme-task-list">
            ${taskConsoleRows(activeRows)}
            ${archivedRows.length ? `<p class="card-kicker console-archive-title">归档任务</p>${taskConsoleRows(archivedRows.slice(0, 18), true)}` : ""}
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><p class="card-kicker">任务详情</p><h2>${task ? esc(task.root_goal || task.task_id) : "请选择或创建任务"}</h2></div>
            <div class="inline-actions">
              <button class="button secondary" data-action="tick-task" ${runnableTask ? "" : "disabled"} type="button">Tick</button>
              <button class="button secondary" data-action="toggle-heartbeat" ${runnableTask ? "" : "disabled"} type="button">${runnableTask?.heartbeat?.enabled ? "关闭心跳" : "开启心跳"}</button>
              <button class="button secondary" data-action="finish-task" ${runnableTask ? "" : "disabled"} type="button">完成</button>
              <button class="button danger" data-action="cancel-task" ${runnableTask ? "" : "disabled"} type="button">取消</button>
            </div>
          </div>
          ${task ? taskDetail(task) : `<div class="empty">请选择或创建任务。</div>`}
        </section>
      </main>
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

function workflowAgentOptions() {
  const agents = [...(state.agents || [])];
  if (currentAgent && !agents.some((agent) => agent.agent_id === currentAgent.agent_id)) {
    agents.unshift(currentAgent);
  }
  if (!agents.length) agents.push(currentAgent || defaultAgentDraft());
  return agents.map((agent) => {
    const id = agent.agent_id || "";
    const selected = id ? id === currentAgent.agent_id : !currentAgent.agent_id;
    const suffix = id === state.default_agent_id ? " · 默认" : (!id ? " · 草稿" : "");
    return `
      <option value="${esc(id)}" ${selected ? "selected" : ""}>
        ${esc(agentDisplayName(agent) + suffix)}
      </option>
    `;
  }).join("");
}

function workflowRightDock(report) {
  const selectedCount = workflowSelectedNodeIds.size;
  const valid = report?.valid;
  return `
    <aside class="workflow-right-dock" aria-label="画布工具">
      <div class="workflow-dock-group">
        <button class="workflow-dock-button ${(!workflowSelectionMode && !workflowScissorMode) ? "active" : ""}" data-action="workflow-pointer-mode" title="正常操作（拖动节点 / 平移画布）" aria-label="正常操作" type="button">${iconImg("pointer", "正常操作")}</button>
        <button class="workflow-dock-button ${workflowScissorMode ? "active" : ""}" data-action="workflow-scissor-mode" title="剪刀：按住划过连线即可剪断" aria-label="剪刀剪线" type="button">✂</button>
      </div>
      <div class="workflow-dock-group">
        <button class="workflow-dock-button" data-action="workflow-undo" title="撤销" aria-label="撤销" ${workflowHistoryPast.length ? "" : "disabled"} type="button">${iconImg("undo", "撤销")}</button>
        <button class="workflow-dock-button" data-action="workflow-redo" title="重做" aria-label="重做" ${workflowHistoryFuture.length ? "" : "disabled"} type="button">${iconImg("redo", "重做")}</button>
      </div>
      <div class="workflow-dock-group">
        <button class="workflow-dock-button text ${workflowToolboxOpen ? "active" : ""}" data-action="toggle-workflow-toolbox" title="打开 / 收起节点素材库" aria-label="素材库" type="button">素材</button>
        <button class="workflow-dock-button text ${workflowGlobalOpen ? "active" : ""}" data-action="open-workflow-global" title="全局规则：整套工作流的安全准则 / 参考 / 技能" aria-label="全局规则" type="button">全局</button>
        <button class="workflow-dock-button text" data-action="auto-layout-workflow" title="按连线层级自动整理画布" aria-label="整理" type="button">整理</button>
      </div>
      <div class="workflow-dock-group">
        <button class="workflow-dock-button text" data-action="workflow-zoom-in" title="放大" aria-label="放大" type="button">+</button>
        <button class="workflow-dock-button text" data-action="workflow-focus-content" title="聚焦到内容(快捷键 F)" aria-label="聚焦内容" type="button">FOC</button>
        <button class="workflow-dock-button text" data-action="workflow-zoom-out" title="缩小" aria-label="缩小" type="button">-</button>
      </div>
      <div class="workflow-dock-group workflow-dock-select-group">
        <div class="workflow-dock-flyout ${(workflowSelectionMode || selectedCount) ? "open" : ""}" aria-hidden="${(workflowSelectionMode || selectedCount) ? "false" : "true"}">
          <button class="workflow-dock-button" data-action="move-selected-workflow-nodes" title="移动框选节点（再点一下结束移动）" aria-label="移动" ${selectedCount ? "" : "disabled"} type="button">${iconImg("pointer", "移动")}</button>
          <button class="workflow-dock-button" data-action="copy-selected-workflow-nodes" title="复制框选节点" aria-label="复制" ${selectedCount ? "" : "disabled"} type="button">${iconImg("copy", "复制")}</button>
          <button class="workflow-dock-button danger" data-action="delete-selected-workflow-nodes" title="删除框选节点" aria-label="删除" ${selectedCount ? "" : "disabled"} type="button">${iconImg("trash", "删除")}</button>
          <button class="workflow-dock-button text" data-action="workflow-clear-selection" title="退出框选，回到正常操作" aria-label="完成" type="button">完成</button>
        </div>
        <button class="workflow-dock-button select-toggle ${workflowSelectionMode ? "active" : ""}" data-action="workflow-select-mode" title="框选节点：拖出范围选中多个节点，弹出移动/复制/删除" aria-label="框选节点" type="button">${iconImg("select", "框选节点")}</button>
      </div>
    </aside>
  `;
}


// 统一的节点保存入口：简易模式只写该 action 暴露的字段；高级模式沿用完整表单。
function applyWorkflowNodeFromInspector() {
  readAgentForm();
  ensureWorkflow();
  const oldId = selectedWorkflowNodeId || (currentAgent.workflow_nodes[0] && currentAgent.workflow_nodes[0].id);
  if (!oldId) return;
  pushWorkflowHistory();
  const idEl = document.getElementById("workflow-node-id");
  const requestedId = idEl ? normalizeWorkflowId(idEl.value) : oldId;
  // 先确定新 id（uniqueWorkflowNodeId 内部会调用 ensureWorkflow 重建数组），再按 id 重新取节点，避免引用失效。
  const newId = requestedId === oldId ? oldId : uniqueWorkflowNodeId(requestedId);
  const node = currentAgent.workflow_nodes.find((item) => item.id === oldId) || currentAgent.workflow_nodes[0];
  if (!node) return;
  const titleEl = document.getElementById("workflow-node-title");
  if (titleEl) node.title = titleEl.value.trim() || newId;
  node.id = newId;

  if (workflowEditorMode === "advanced") {
      const parsedParams = parseWorkflowObjectField("workflow-node-params", "参数") || null;
      const inputSchema = parseWorkflowObjectField("workflow-node-input-schema", "输入 Schema") || null;
      const outputSchema = parseWorkflowObjectField("workflow-node-output-schema", "输出 Schema") || null;
      const retryPolicy = parseWorkflowObjectField("workflow-node-retry-policy", "重试策略") || null;
      node.id = newId;
      node.kind = $("workflow-node-kind").value;
      node.stage = $("workflow-node-stage").value;
      node.action = $("workflow-node-action").value;
      node.description = $("workflow-node-description").value.trim();
      node.instruction = $("workflow-node-instruction").value.trim();
      node.prompt = $("workflow-node-prompt").value.trim();
      const refType = $("workflow-node-ref-type")?.value.trim() || "";
      const refId = $("workflow-node-ref-id")?.value.trim() || "";
      const toolName = $("workflow-node-tool-name")?.value.trim() || (refType === "tool" ? refId : "");
      const apiId = $("workflow-node-api-id")?.value.trim() || (refType === "api" ? refId : "");
      const pluginName = $("workflow-node-plugin-name")?.value.trim() || (refType === "plugin" ? refId : "");
      const skillName = $("workflow-node-skill-name")?.value.trim() || (refType === "skill" ? refId : "");
      setNodeStringField(node, "ref_type", refType || (toolName ? "tool" : apiId ? "api" : pluginName ? "plugin" : skillName ? "skill" : ""));
      setNodeStringField(node, "ref_id", refId || toolName || apiId || pluginName || skillName);
      setNodeStringField(node, "tool_name", toolName);
      setNodeStringField(node, "api_id", apiId);
      setNodeStringField(node, "plugin_name", pluginName);
      setNodeStringField(node, "skill_name", skillName);
      setNodeStringField(node, "permission_profile", $("workflow-node-permission-profile")?.value || "work");
      delete node.profile;
      setNodeStringField(node, "condition", $("workflow-node-condition")?.value);
      setNodeStringField(node, "route_variable", $("workflow-node-route-variable")?.value);
      setNodeStringField(node, "parallel_group", $("workflow-node-parallel-group")?.value);
      setNodeStringField(node, "worker_type", $("workflow-node-worker-type")?.value);
      delete node.role;
      setNodeStringField(node, "variable_name", $("workflow-node-variable-name")?.value);
      setNodeStringField(node, "template_id", $("workflow-node-template-id")?.value);
      setNodeStringField(node, "path", $("workflow-node-path")?.value);
      setNodeStringField(node, "url", $("workflow-node-url")?.value);
      setNodeStringField(node, "method", $("workflow-node-method")?.value);
      setNodeStringField(node, "operation", $("workflow-node-operation")?.value);
      delete node.edit_mode;
      setNodeStringField(node, "language", $("workflow-node-language")?.value);
      setNodeStringField(node, "input_variable", $("workflow-node-input-variable")?.value);
      setNodeStringField(node, "output_variable", $("workflow-node-output-variable")?.value);
      node.required_inputs = linesToList($("workflow-node-required-inputs")?.value || "");
      if (!node.required_inputs.length) delete node.required_inputs;
      node.output_variables = linesToList($("workflow-node-output-variables")?.value || "");
      if (!node.output_variables.length) delete node.output_variables;
      node.tags = linesToList($("workflow-node-tags")?.value || "");
      if (!node.tags.length) delete node.tags;
      setNodeJsonField(node, "input_schema", inputSchema);
      setNodeJsonField(node, "output_schema", outputSchema);
      setNodeJsonField(node, "retry_policy", retryPolicy);
      const timeoutSeconds = Number($("workflow-node-timeout-seconds")?.value || 0);
      if (Number.isFinite(timeoutSeconds) && timeoutSeconds > 0) node.timeout_seconds = clamp(Math.round(timeoutSeconds), 1, 600);
      else delete node.timeout_seconds;
      const maxRetries = Number($("workflow-node-max-retries")?.value || 0);
      if (Number.isFinite(maxRetries) && maxRetries > 0) node.max_retries = clamp(Math.round(maxRetries), 1, 8);
      else delete node.max_retries;
      delete node.tool_args;
      delete node.arguments;
      delete node.api_payload;
      delete node.payload;
      delete node.params;
      delete node.request;
      delete node.value;
      delete node.data;
      delete node.content;
      delete node.text;
      delete node.code;
      delete node.script;
      delete node.command;
      if (parsedParams) {
        if (node.action === "call_api" || node.kind === "api") node.api_payload = parsedParams;
        else if (node.action === "http_request") node.payload = parsedParams;
        else if (node.action === "run_tools" || node.kind === "tool") node.tool_args = parsedParams;
        else node.params = parsedParams;
        for (const key of ["value", "payload", "data", "content", "text", "code", "script", "command", "expression", "json_path", "jq", "inputs", "input_variables", "sources", "items", "source", "perspectives", "checks"]) {
          if (Object.prototype.hasOwnProperty.call(parsedParams, key)) node[key] = parsedParams[key];
        }
        if (parsedParams.operation && !node.operation) node.operation = String(parsedParams.operation).trim();
        if (parsedParams.language && !node.language) node.language = String(parsedParams.language).trim();
        if (parsedParams.method && !node.method) node.method = String(parsedParams.method).trim().toUpperCase();
      }

  } else {
    // 简易模式：只写当前 action 暴露的填空字段。
    applySimpleEditorFields(node);
  }

  // 入口/出口规则两种模式都可能存在
  if (document.getElementById("workflow-entry-trigger-phrases")) currentAgent.entry_policy.trigger_phrases = linesToList($("workflow-entry-trigger-phrases").value);
  if (document.getElementById("workflow-entry-trigger-keywords")) currentAgent.entry_policy.trigger_keywords = linesToList($("workflow-entry-trigger-keywords").value);
  if (document.getElementById("workflow-entry-confirmation-text")) currentAgent.entry_policy.confirmation_text = $("workflow-entry-confirmation-text").value.trim();
  if (document.getElementById("workflow-exit-phrases")) currentAgent.entry_policy.exit_phrases = linesToList($("workflow-exit-phrases").value);
  if (document.getElementById("wf-uni-confirm-mode")) {
    const __m = $("wf-uni-confirm-mode").value;
    currentAgent.entry_policy.confirmation_mode = __m;
    currentAgent.entry_policy.require_confirmation = __m !== "off";
  }
  if (document.querySelector('[name="wf-uni-types"]')) {
    currentAgent.workflow_trigger ||= {};
    const __t = checkedValues("wf-uni-types");
    currentAgent.workflow_trigger.types = __t.length ? __t : ["command"];
  }
  if (document.getElementById("wf-uni-commands")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.command_names = linesToList($("wf-uni-commands").value); }
  if (document.getElementById("wf-uni-regex")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.regex = linesToList($("wf-uni-regex").value); }
  if (document.getElementById("wf-uni-cron")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.cron = $("wf-uni-cron").value.trim(); }
  if (document.getElementById("wf-uni-plugin-events")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.plugin_events = linesToList($("wf-uni-plugin-events").value); }
  if (document.getElementById("wf-uni-webhook")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.webhook_path = $("wf-uni-webhook").value.trim(); }
  if (document.getElementById("wf-uni-admin-only")) { currentAgent.workflow_scope ||= {}; currentAgent.workflow_scope.admin_only = $("wf-uni-admin-only").checked; }
  if (document.getElementById("wf-uni-enabled")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.enabled = $("wf-uni-enabled").checked; }
  if (document.getElementById("wf-uni-description")) { currentAgent.workflow_trigger ||= {}; currentAgent.workflow_trigger.description = $("wf-uni-description").value.trim(); }
  if (document.getElementById("scope-global")) {
    currentAgent.application_scope = document.getElementById("scope-global").checked ? "global" : "entry";
    currentAgent.workflow_scope ||= {};
    currentAgent.workflow_scope.chat_types = checkedValues("scope-chat-type");
    if (!currentAgent.workflow_scope.chat_types.length) currentAgent.workflow_scope.chat_types = ["private"];
    currentAgent.workflow_scope.admin_only = document.getElementById("scope-admin-only")?.checked || false;
    currentAgent.workflow_scope.group_allowlist = linesToList($("scope-group-allow")?.value || "");
    currentAgent.workflow_scope.group_denylist = linesToList($("scope-group-deny")?.value || "");
    currentAgent.workflow_scope.user_allowlist = linesToList($("scope-user-allow")?.value || "");
    currentAgent.workflow_scope.user_denylist = linesToList($("scope-user-deny")?.value || "");
  }
  if (document.getElementById("workflow-default-completion-conditions")) currentAgent.entry_policy.default_completion_conditions = linesToList($("workflow-default-completion-conditions").value);
  if (document.getElementById("wf-approval-mode")) {
    currentAgent.approval_policy ||= {};
    currentAgent.approval_policy.mode = $("wf-approval-mode").value;
    currentAgent.approval_policy.require_approval = linesToList($("wf-approval-require").value);
    currentAgent.approval_policy.preapproved_scopes = linesToList($("wf-approval-preapproved").value);
  }

  currentAgent.workflow_edges = currentAgent.workflow_edges.map((edge) => ({
    ...edge,
    from: edge.from === oldId ? newId : edge.from,
    to: edge.to === oldId ? newId : edge.to,
  }));
  selectedWorkflowNodeId = newId;
  workflowCheckReport = null;
  workflowDryRunReport = null;
  setFeedback("节点配置已应用。保存方案后生效。");
  renderWorkflowStable();
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
      <div class="workflow-top-hotzone" aria-hidden="true"></div>
      <header class="workflow-page-top">
        <label class="workflow-agent-picker">
          <span>当前方案</span>
          <select data-action="workflow-agent-select">
            ${workflowAgentOptions()}
          </select>
        </label>
        <div class="workflow-page-status">
          ${badge(`${currentAgent.workflow_nodes.length} 节点 / ${currentAgent.workflow_edges.length} 连线`)}
          ${badge(workflowKindSummary(currentAgent), "info")}
          ${badge(report.valid ? "检查通过" : `${report.errors || 0} 错误 / ${report.warnings || 0} 提醒`, report.valid ? "ok" : "warn")}
        </div>
        <div class="workflow-top-tools">
          <button class="button tiny secondary" data-action="check-workflow" type="button">静态检查</button>
          <button class="button tiny secondary" data-action="dry-run-workflow" type="button">预跑诊断</button>
          <button class="button tiny" data-action="save-agent" type="button">保存</button>
        </div>
      </header>
      ${workflowRightDock(report)}
      <aside class="workflow-tool-drawer">
        <div class="drawer-head">
          <div><p class="card-kicker">模块库</p><h3>拼图素材 <small>可直接拖拽</small></h3></div>
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
      ${workflowGlobalOpen ? `
        <div class="workflow-modal-backdrop" data-action="close-workflow-global"></div>
        <section class="workflow-inspector-drawer workflow-global-drawer" role="dialog" aria-modal="true">
          <div class="drawer-head">
            <div><p class="card-kicker">全局规则</p><h3>整套工作流的准则 / 参考 / 技能</h3></div>
          </div>
          <div class="drawer-scroll">
            ${workflowGlobalEditor()}
          </div>
        </section>
      ` : ""}
      ${workflowSubAgentOpen ? `
        <div class="workflow-modal-backdrop" data-action="close-workflow-subagents"></div>
        <section class="workflow-inspector-drawer workflow-global-drawer" role="dialog" aria-modal="true">
          <div class="drawer-head">
            <div><p class="card-kicker">子Agent 泳道</p><h3>注册 / 领地管理</h3></div>
          </div>
          <div class="drawer-scroll">
            ${subAgentsDrawer()}
          </div>
        </section>
      ` : ""}
      ${workflowReportOpen ? workflowReportPanel() : ""}
    </section>
  `;
}

// 全局规则编辑器：作用于整条工作流，而不是单个节点。映射 AgentSpec 的 system_prompt / approval / skills / isolation。
function workflowGlobalEditor() {
  const a = ensureAgent(currentAgent || {});
  a.heartbeat_policy ||= {};
  a.default_task_budget ||= {};
  a.enabled_skills ||= [];
  a.plugin_blacklist ||= [];
  const skills = state.skills || [];
  const enabledSkills = new Set(a.enabled_skills || []);
  const blacklisted = new Set(a.plugin_blacklist || []);
  const skillRows = skills.length
    ? skills.map((sk) => {
        const name = String(sk.name || sk.id || "").trim();
        return `<label class="check-line"><input type="checkbox" data-global-skill="${esc(name)}" ${enabledSkills.has(name) ? "checked" : ""} /> <span>${esc(name)}</span><small>${esc(sk.path || sk.description || "")}</small></label>`;
      }).join("")
    : `<div class="empty">还没有可用的技能。请确认 AstrBot 已加载技能后刷新。</div>`;
  const pluginList = (state.plugins || []).filter((p) => p.name !== "astrbot_plugin_agent_lab");
  const pluginRows = pluginList.length
    ? pluginList.map((p) => `<label class="check-line"><input type="checkbox" data-global-plugin-blacklist="${esc(p.name)}" ${blacklisted.has(p.name) ? "checked" : ""} /> <span>${esc(p.display_name || p.name)}</span><small>${esc(p.name)}</small></label>`).join("")
    : `<div class="empty">没有检测到第三方插件。</div>`;
  const budget = a.default_task_budget || {};
  return `
    <div class="detail-box workflow-editor">
      <section class="workflow-editor-section simple-editor">
        <p class="simple-editor-lead">这里只放对整条工作流都生效的规则。入口 / 出口 / 审批 / 生效范围已分别改到对应的节点里设置。</p>
        <label class="simple-field">整套安全准则 / 行为基调（系统提示词）
          <textarea id="global-system-prompt" rows="5" placeholder="例如：所有写操作前先说明影响；不碰生产数据库；引用资料要给出处。">${esc(a.system_prompt || "")}</textarea>
          <small class="field-hint">相当于给整个 bot 定的总规矩，每个节点执行时都会带上。</small>
        </label>
        <label class="simple-field">任务执行基调（任务提示词）
          <textarea id="global-task-prompt" rows="3" placeholder="例如：每轮只推进一小步，先读状态再动手，做完写回状态。">${esc(a.task_prompt || "")}</textarea>
        </label>
      </section>
      <section class="workflow-editor-section simple-editor">
        <h4>整条流程启用的技能（参考规则）</h4>
        ${skillRows}
      </section>
      <section class="workflow-editor-section simple-editor">
        <h4>插件黑名单</h4>
        <p class="simple-editor-lead">勾选的插件会被本方案<strong>全程禁用</strong>，绝不会在任务流里被调用；没勾的插件，也只有被画布节点引用时才会启用。</p>
        <div class="capability-list">${pluginRows}</div>
      </section>
      <section class="workflow-editor-section simple-editor">
        <h4>预算与运行控制</h4>
        <div class="form-grid compact">
          <label>总 Token 预算<input id="global-budget-tokens" type="number" min="0" max="50000000" value="${esc(budget.max_total_tokens ?? 240000)}" /></label>
          <label>总 Tick 预算<input id="global-budget-ticks" type="number" min="0" max="100000" value="${esc(budget.max_total_ticks ?? 120)}" /></label>
          <label>每轮最多节点<input id="global-budget-nodes" type="number" min="1" max="200" value="${esc(budget.max_nodes_per_tick ?? 6)}" /></label>
          <label>每轮最多工具<input id="global-budget-tools" type="number" min="0" max="200" value="${esc(budget.max_tools_per_tick ?? 12)}" /></label>
          <label>每轮最多秒数<input id="global-budget-seconds" type="number" min="1" max="3600" value="${esc(budget.max_seconds_per_tick ?? 240)}" /></label>
          <label>每轮 Token 预算<input id="global-budget-tokens-per-tick" type="number" min="0" max="1000000" value="${esc(budget.max_tokens_per_tick ?? 12000)}" /></label>
          <label>总工具调用预算<input id="global-budget-tool-calls" type="number" min="0" max="100000" value="${esc(budget.max_total_tool_calls ?? 240)}" /></label>
          <label>重复失败阈值<input id="global-max-repeated-failures" type="number" min="1" max="100" value="${esc(a.heartbeat_policy.max_repeated_failures ?? 3)}" /></label>
        </div>
      </section>
      <div class="button-row">
        <button class="button" data-action="apply-workflow-global" type="button">应用全局规则</button>
        <button class="button secondary" data-action="close-workflow-global" type="button">关闭</button>
      </div>
    </div>
  `;
}

// 把全局规则抽屉里的字段写回 AgentSpec（整条工作流级别）。
function applyWorkflowGlobalRules() {
  const a = ensureAgent(currentAgent || {});
  const sp = document.getElementById("global-system-prompt");
  const tp = document.getElementById("global-task-prompt");
  if (sp) a.system_prompt = sp.value;
  if (tp) a.task_prompt = tp.value;
  a.default_task_budget ||= {};
  const budgetMap = [
    ["global-budget-tokens", "max_total_tokens"],
    ["global-budget-ticks", "max_total_ticks"],
    ["global-budget-nodes", "max_nodes_per_tick"],
    ["global-budget-tools", "max_tools_per_tick"],
    ["global-budget-seconds", "max_seconds_per_tick"],
    ["global-budget-tokens-per-tick", "max_tokens_per_tick"],
    ["global-budget-tool-calls", "max_total_tool_calls"],
  ];
  budgetMap.forEach(([id, key]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const value = Number(el.value || 0);
    if (Number.isFinite(value)) a.default_task_budget[key] = Math.max(0, Math.round(value));
  });
  a.heartbeat_policy ||= {};
  const repeated = document.getElementById("global-max-repeated-failures");
  if (repeated) a.heartbeat_policy.max_repeated_failures = Math.max(1, Math.round(Number(repeated.value || 3)));
  const skillBoxes = document.querySelectorAll("[data-global-skill]");
  if (skillBoxes.length) {
    a.enabled_skills = Array.from(skillBoxes).filter((b) => b.checked).map((b) => b.dataset.globalSkill);
  }
  const blBoxes = document.querySelectorAll("[data-global-plugin-blacklist]");
  if (blBoxes.length) {
    a.plugin_blacklist = Array.from(blBoxes).filter((b) => b.checked).map((b) => b.dataset.globalPluginBlacklist);
    a.plugin_overrides ||= {};
    a.plugin_blacklist.forEach((name) => { a.plugin_overrides[name] = false; });
  }
}

function renderMemoryPage() {
  currentAgent = ensureAgent(currentAgent || {});
  const rows = filteredMemoryRows();
  if (!selectedMemoryId || !rows.some((item) => item.memory_id === selectedMemoryId)) {
    selectedMemoryId = rows[0]?.memory_id || "";
  }
  const folders = memoryFolderRows();
  if (selectedMemoryFolderId !== "__new__" && (!selectedMemoryFolderId || !folders.some((item) => item.folder_id === selectedMemoryFolderId))) {
    selectedMemoryFolderId = folders[0]?.folder_id || "default";
  }
  const selected = rows.find((item) => item.memory_id === selectedMemoryId) || null;
  $("view").innerHTML = `
    <section class="memory-page">
      <div class="panel-head memory-page-head">
        <div><p class="card-kicker">任务记忆</p><h2>看哪些任务做过、哪些记录要保留</h2></div>
        <div class="inline-actions">
          <button class="button secondary" data-route="tasks" type="button">任务列表</button>
          <button class="button secondary" data-route="workflow" type="button">工作流画布</button>
        </div>
      </div>
      ${memoryStats()}
      <section class="panel memory-toolbar">
        <div class="memory-filters">
          ${["all", "candidate", "accepted", "rejected"].map((item) => `
            <button class="filter-btn ${memoryFilter === item ? "active" : ""}" data-action="memory-filter" data-id="${item}" type="button">${memoryFilterLabel(item)}</button>
          `).join("")}
        </div>
        <div class="tag-cloud">${tagCloud()}</div>
      </section>
      ${memoryFolderPanel()}
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
      ${memoryDetailOpen && selected ? memoryDetailDrawer(selected) : ""}
    </section>
  `;
}

function memoryFolderRows() {
  const folders = state.memory_folders || [];
  if (folders.length) return folders;
  return [{ folder_id: "default", name: "默认记忆夹", agent_id: "", detail_level: "summary", expose_to_normal: false, retention_days: 0 }];
}

function preferredMemoryFolderId() {
  const folders = memoryFolderRows();
  if (selectedMemoryFolderId && folders.some((item) => item.folder_id === selectedMemoryFolderId)) {
    return selectedMemoryFolderId;
  }
  const agentFolder = folders.find((item) => item.agent_id && item.agent_id === currentAgent?.agent_id);
  return agentFolder?.folder_id || folders.find((item) => item.folder_id === "default")?.folder_id || folders[0]?.folder_id || "default";
}

function memoryFolderOptions(selected = "") {
  return memoryFolderRows().map((folder) => {
    const id = folder.folder_id || "default";
    const suffix = folder.agent_id ? ` · ${folder.agent_id}` : "";
    return `<option value="${esc(id)}" ${id === selected ? "selected" : ""}>${esc(folder.name || id)}${esc(suffix)}</option>`;
  }).join("");
}

function memoryFolderLabel(folderId) {
  const folder = memoryFolderRows().find((item) => item.folder_id === folderId);
  return folder?.name || folderId || "默认记忆夹";
}

function memoryFolderPanel() {
  const folders = memoryFolderRows();
  const selected = selectedMemoryFolderId === "__new__"
    ? { folder_id: "", name: "", agent_id: currentAgent.agent_id || "", detail_level: "summary", expose_to_normal: false, retention_days: 0, description: "" }
    : folders.find((item) => item.folder_id === selectedMemoryFolderId) || folders[0] || {};
  const currentId = selected.folder_id || "";
  return `
    <section class="panel memory-folder-panel">
      <div class="panel-head">
        <div><p class="card-kicker">记忆夹</p><h3>方案级记忆隔离</h3></div>
        <div class="inline-actions">
          <button class="button secondary" data-action="new-memory-folder" type="button">新建夹</button>
          <button class="button secondary" data-action="rename-memory-folder" data-id="${esc(currentId)}" ${!currentId || currentId === "default" ? "disabled" : ""} type="button">重命名</button>
          <button class="button danger" data-action="delete-memory-folder" data-id="${esc(currentId)}" ${!currentId || currentId === "default" ? "disabled" : ""} type="button">删除夹</button>
        </div>
      </div>
      <div class="memory-folder-layout">
        <div class="list memory-folder-list">
          ${folders.map((folder) => `
            <button class="list-row ${folder.folder_id === selectedMemoryFolderId ? "selected" : ""}" data-action="select-memory-folder" data-id="${esc(folder.folder_id || "default")}" type="button">
              <div class="row-title"><span>${esc(folder.name || folder.folder_id || "记忆夹")}</span>${badge(folder.expose_to_normal ? "普通可见" : "任务隔离", folder.expose_to_normal ? "ok" : "warn")}</div>
              <div class="row-meta">${esc(folder.folder_id || "default")} · Agent：${esc(folder.agent_id || "不限")} · ${esc(folder.detail_level === "full" ? "保留细节" : "仅摘要")}</div>
            </button>
          `).join("")}
        </div>
        <div class="form-grid compact memory-folder-form">
          <label>记忆夹 ID<input id="memory-folder-id" value="${esc(selected.folder_id || "")}" placeholder="留空自动生成" ${currentId === "default" ? "readonly" : ""} /></label>
          <label>名称<input id="memory-folder-name" value="${esc(selected.name || "")}" placeholder="项目/方案记忆夹" /></label>
          <label>归属 Agent<input id="memory-folder-agent" value="${esc(selected.agent_id || currentAgent.agent_id || "")}" placeholder="留空表示通用" /></label>
          <label>细节级别<select id="memory-folder-detail">${options(["summary", "full"], selected.detail_level || "summary", (value) => value === "full" ? "保存完整细节" : "只保留摘要索引")}</select></label>
          <label>保留天数<input id="memory-folder-retention" type="number" min="0" max="3650" value="${esc(selected.retention_days || 0)}" /></label>
          <label>普通模式可见<select id="memory-folder-expose">${options(["false", "true"], String(Boolean(selected.expose_to_normal)), (value) => value === "true" ? "允许标签级暴露" : "仅任务模式")}</select></label>
          <label class="span-2">说明<textarea id="memory-folder-description" rows="3" placeholder="这个夹保存什么、何时可回忆。">${esc(selected.description || "")}</textarea></label>
        </div>
      </div>
      <div class="button-row"><button class="button" data-action="save-memory-folder" type="button">保存记忆夹</button></div>
    </section>
  `;
}

function memoryMetaItem(label, value, isHtml = false) {
  return `<div class="memory-meta-item"><span>${esc(label)}</span><strong>${isHtml ? value : esc(value)}</strong></div>`;
}
function memoryDetail(item) {
  const tags = item.tags || [];
  const tagHtml = tags.length ? tags.map((t) => `<span class="memory-tag">${esc(t)}</span>`).join("") : "-";
  return `
    <div class="panel-head">
      <div><p class="card-kicker">${esc(item.memory_id)}</p><h3>${esc(item.text || "任务记忆")}</h3></div>
      <div class="inline-actions">
        ${badge(memoryFilterLabel(item.status || "candidate"), item.status === "accepted" ? "ok" : "warn")}
        <button class="button secondary" data-action="open-memory-detail" data-id="${esc(item.memory_id)}" type="button">展开细看</button>
      </div>
    </div>
    <div class="memory-meta-grid">
      ${memoryMetaItem("来源任务", item.source_task_id || "-")}
      ${memoryMetaItem("记忆夹", `${item.folder_name || memoryFolderLabel(item.folder_id)} (${item.folder_id || "default"})`)}
      ${memoryMetaItem("归属 Agent", item.agent_id || "-")}
      ${memoryMetaItem("来源会话", item.source_umo || "-")}
      ${memoryMetaItem("普通模式可读", item.expose_to_normal === false ? "否，仅任务模式" : "是，可按标签读取")}
      ${memoryMetaItem("标签", tagHtml, true)}
    </div>
    <div class="memory-content-block">
      <div class="memory-content-head"><span>记忆内容</span><button class="button tiny secondary" data-action="copy-memory" data-id="${esc(item.memory_id)}" type="button">复制</button></div>
      <div class="memory-content-text">${esc(item.text || "")}</div>
    </div>
    <div class="button-row">
      <button class="button secondary" data-action="use-memory-context" data-id="${esc(item.memory_id)}" type="button">带入新任务</button>
      <button class="button secondary" data-action="accept-memory" data-id="${esc(item.memory_id)}" type="button">保留</button>
      <button class="button secondary" data-action="reject-memory" data-id="${esc(item.memory_id)}" type="button">标记不用</button>
      <button class="button danger" data-action="delete-memory" data-id="${esc(item.memory_id)}" type="button">删除</button>
    </div>
  `;
}
function memoryDetailDrawer(item) {
  const tags = item.tags || [];
  const tagHtml = tags.length ? tags.map((t) => `<span class="memory-tag">${esc(t)}</span>`).join("") : "-";
  return `
    <div class="memory-detail-backdrop" data-action="close-memory-detail"></div>
    <aside class="memory-detail-drawer" role="dialog" aria-modal="true">
      <div class="drawer-header">
        <div><p class="card-kicker">${esc(item.memory_id)}</p><h3 class="memory-drawer-title">${esc(item.text || "任务记忆")}</h3></div>
        <button class="button secondary" data-action="close-memory-detail" type="button">关闭</button>
      </div>
      <div class="drawer-content">
        <div class="memory-meta-grid">
          ${memoryMetaItem("状态", memoryFilterLabel(item.status || "candidate"))}
          ${memoryMetaItem("来源任务", item.source_task_id || "-")}
          ${memoryMetaItem("记忆夹", `${item.folder_name || memoryFolderLabel(item.folder_id)} (${item.folder_id || "default"})`)}
          ${memoryMetaItem("归属 Agent", item.agent_id || "-")}
          ${memoryMetaItem("来源会话", item.source_umo || "-")}
          ${memoryMetaItem("普通模式可读", item.expose_to_normal === false ? "否，仅任务模式" : "是，可按标签读取")}
          ${memoryMetaItem("标签", tagHtml, true)}
        </div>
        <div class="memory-content-block">
          <div class="memory-content-head"><span>记忆内容</span><button class="button tiny secondary" data-action="copy-memory" data-id="${esc(item.memory_id)}" type="button">复制</button></div>
          <div class="memory-content-text large">${esc(item.text || "")}</div>
        </div>
        <div class="memory-content-block">
          <div class="memory-content-head"><span>续写入口草稿</span></div>
          <div class="memory-content-text">${esc(memoryContextText(item))}</div>
        </div>
      </div>
      <div class="drawer-actions">
        <button class="button secondary" data-action="use-memory-context" data-id="${esc(item.memory_id)}" type="button">带入新任务</button>
        <button class="button secondary" data-action="accept-memory" data-id="${esc(item.memory_id)}" type="button">保留</button>
        <button class="button danger" data-action="delete-memory" data-id="${esc(item.memory_id)}" type="button">删除</button>
      </div>
    </aside>
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
            <div class="workflow-check-row ok"><b>OK</b><span>已按入口、计划、执行、闸门、记录、出口重新排布节点，并把视图拉回流程起点。</span></div>
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
  // 固定的世界画布尺寸：等于整个可拖动世界，不随节点位置增减。
  // 这样拖动节点（尤其向上/向负方向）不会改变 offset / size，整张画布是一个稳定的自由移动区域。
  return {
    minX: WORKFLOW_CANVAS_MIN_X,
    minY: WORKFLOW_CANVAS_MIN_Y,
    maxX: WORKFLOW_CANVAS_MAX_X,
    width: WORKFLOW_WORLD_WIDTH,
    height: WORKFLOW_WORLD_HEIGHT,
  };
}

function workflowWorldOffsetX(size = null) {
  // 固定的世界原点偏移：不随节点位置变化，避免拖动节点时整张画布跟着重排（上下分裂感）。
  return -WORKFLOW_CANVAS_MIN_X;
}

function workflowWorldOffsetY(size = null) {
  // 固定的世界原点偏移（同上）。
  return -WORKFLOW_CANVAS_MIN_Y;
}

function workflowCanvas() {
  ensureWorkflow();
  const size = workflowCanvasSize();
  const scaledWidth = Math.ceil(size.width * workflowZoom);
  const scaledHeight = Math.ceil(size.height * workflowZoom);
  const hasPending = Boolean(workflowPendingPort);
  const worldOffsetX = workflowWorldOffsetX(size);
  const worldOffsetY = workflowWorldOffsetY(size);
  return `
    <div class="workflow-canvas-toolbar">
      <div class="workflow-canvas-meta">
        <span>${currentAgent.workflow_nodes.length} 节点</span>
        <span>${currentAgent.workflow_edges.length} 连线</span>
        <span>${Math.round(workflowZoom * 100)}%</span>
      </div>
      ${(workflowTerritoryPaintAgent || workflowApiScopePaint) ? `<div class="workflow-paint-banner">${workflowTerritoryPaintAgent ? "圈地中：拖框选节点划入领地" : "选范围中：拖框把节点纳入 API 范围"} <button class="button tiny" data-action="workflow-exit-paint" type="button">完成</button></div>` : ""}
      <div class="workflow-zoom-controls">
        <button class="button tiny secondary" data-action="workflow-zoom-out" type="button">缩小</button>
        <button class="button tiny secondary" data-action="workflow-zoom-in" type="button">放大</button>
      </div>
    </div>
    <div class="workflow-canvas-wrap">
      <div class="workflow-canvas-space" style="width:${scaledWidth}px;height:${scaledHeight}px">
        <div class="workflow-canvas ${hasPending ? "is-connecting" : ""}" data-zoom="${workflowZoom}" data-world-offset-x="${worldOffsetX}" data-world-offset-y="${worldOffsetY}" style="width:${size.width}px;height:${size.height}px;transform:${workflowCanvasTransform()}">
          <svg class="workflow-links" width="${size.width}" height="${size.height}" viewBox="0 0 ${size.width} ${size.height}" aria-hidden="true">
            ${workflowLinksSvg(worldOffsetX, worldOffsetY)}
          </svg>
          ${workflowTerritoryLayer(worldOffsetX, worldOffsetY)}
          ${currentAgent.workflow_nodes.map((item) => node(item, worldOffsetX, worldOffsetY)).join("")}
        </div>
      </div>
      ${workflowMinimap(size)}
    </div>
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
      draggable="false"
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
  if (!workflowToolboxSeeded) { WORKFLOW_NODE_GROUPS.forEach((g) => { if (g.open) workflowToolboxOpenGroups.add(g.id); }); workflowToolboxSeeded = true; }
  const selectedTools = materializedToolSelection();
  const activePlugins = (state.plugins || []).filter((item) => item.activated !== false);
  const apis = state.custom_apis || [];
  const filter = workflowMaterialFilter.trim();
  const basicGroupIds = new Set(["trigger_monitor", "entry_context", "plan_route", "tool_exec", "memory_state", "safety_human", "validate_exit"]);
  const showAdvanced = workflowLibraryMode === "advanced";
  const templates = WORKFLOW_NODE_TEMPLATES
    .filter((item) => !WORKFLOW_MERGED_TEMPLATE_IDS.has(item.id))
    .filter((item) => showAdvanced || !item.advanced)
    .filter((item) =>
      includesQuery([item.id, item.title, item.kind, item.action, item.stage, item.library_group, item.instruction, item.description], filter)
    );
  const libraryGroups = WORKFLOW_NODE_GROUPS;
  const groupedTemplates = libraryGroups
    .map((group) => ({ group, items: templates.filter((item) => workflowNodeGroupKey(item) === group.id) }))
    .filter(({ items }) => items.length > 0);
  const runtimeSections = [
    {
      id: "runtime_apis",
      title: "已注册 API",
      hint: "像积木一样插入自定义 API，凭证仍由后端注入。",
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
    {
      id: "runtime_plugins",
      title: "插件模块",
      hint: "把已启用 AstrBot 插件作为能力来源。",
      advancedOnly: true,
      items: activePlugins
        .map((plugin) => workflowRuntimeModuleNode("plugin", plugin.name))
        .filter(Boolean)
        .filter((item) => includesQuery([item.title, item.ref_id, item.instruction], filter)),
      empty: "暂无可用插件",
    },
  ];
  return `
    <div class="workflow-toolbox">
      <div class="workflow-toolbox-bar">
        <input class="filter-input workflow-material-filter" data-action="filter-workflow-materials" value="${esc(workflowMaterialFilter)}" placeholder="搜索节点 / 工具 / API / 插件" />
        <div class="workflow-libmode-switch" role="tablist" aria-label="素材层级">
          <button class="libmode-tab ${workflowLibraryMode !== "advanced" ? "active" : ""}" data-action="set-workflow-library-mode" data-id="basic" type="button">基础</button>
          <button class="libmode-tab ${workflowLibraryMode === "advanced" ? "active" : ""}" data-action="set-workflow-library-mode" data-id="advanced" type="button">进阶</button>
        </div>
      </div>
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
      <details class="advanced-json workflow-json-box">
        <summary>工作流 JSON</summary>
        <textarea id="workflow-json" rows="8" data-original="${esc(JSON.stringify(workflowData(), null, 2))}">${esc(JSON.stringify(workflowData(), null, 2))}</textarea>
      </details>
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

function workflowLinksSvg(offsetX = workflowWorldOffsetX(), offsetY = workflowWorldOffsetY()) {
  ensureWorkflow();
  const edges = currentAgent.workflow_edges || [];
  const nodes = new Map((currentAgent.workflow_nodes || []).map((item) => [item.id, item]));
  const paths = edges.map((edge, index) => {
    const from = nodes.get(edge.from);
    const to = nodes.get(edge.to);
    if (!from || !to) return "";
    const edgeType = String(edge.edge_type || "success");
    const fromPort = String(edge.from_port || edgeType);
    const start = workflowNodeOutAnchor(from, fromPort, offsetX, offsetY);
    const end = workflowNodeAnchor(to, "in", offsetX, offsetY);
    const d = workflowLinkPath(start, end);
    const color = workflowEdgeColor(edgeType);
    const marker = `workflow-arrow-${edgeType}`;
    const midX = (start.x + end.x) / 2;
    const midY = (start.y + end.y) / 2;
    const showLabel = edgeType !== "success" && edgeType !== "always";
    const labelHtml = showLabel
      ? `<g class="workflow-link-label" transform="translate(${midX} ${midY})"><rect x="-18" y="-9" width="36" height="18" rx="5" fill="#fff" stroke="${color}"></rect><text x="0" y="3" text-anchor="middle" fill="${color}">${esc(workflowPortShortLabel(edgeType))}</text></g>`
      : "";
    return `
      <path class="workflow-link-hit" d="${d}" data-action="delete-workflow-edge" data-index="${index}"></path>
      <path class="workflow-link" d="${d}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" data-edge-type="${esc(edgeType)}" style="--link-color:${color};marker-end:url(#${marker})"></path>
      ${labelHtml}
    `;
  }).join("");
  const preview = workflowConnection ? `<path class="workflow-link-preview" d="${workflowLinkPath(workflowConnection.anchor, workflowConnection.pointer)}"></path>` : "";
  return `
    ${workflowMarkerDefs()}
    ${paths}
    ${preview}
  `;
}


// ===== 子Agent 泳道：注册表 + 圈地指派 + 领地渲染（批次1）=====
function ensureSubAgents() {
  if (!currentAgent) return [];
  if (!Array.isArray(currentAgent.sub_agents)) currentAgent.sub_agents = [];
  return currentAgent.sub_agents;
}
function subAgentById(id) {
  return ensureSubAgents().find((s) => s && s.sub_agent_id === id) || null;
}
function subAgentHex(s) {
  return s && /^#[0-9a-fA-F]{6}$/.test(String(s.color || "")) ? s.color : "#5b8def";
}
function subAgentColorOf(id) {
  const sa = subAgentById(id);
  return sa ? subAgentHex(sa) : "";
}
function newSubAgentLocalId() {
  return "sa_" + Math.random().toString(16).slice(2, 14);
}
function setNodeOwner(nodeId, subId) {
  ensureWorkflow();
  const node = currentAgent.workflow_nodes.find((n) => n.id === nodeId);
  if (!node) return;
  ensureSubAgents().forEach((s) => {
    if (Array.isArray(s.member_node_ids)) s.member_node_ids = s.member_node_ids.filter((x) => x !== nodeId);
  });
  if (subId) {
    node.owner = subId;
    const sa = subAgentById(subId);
    if (sa) {
      if (!Array.isArray(sa.member_node_ids)) sa.member_node_ids = [];
      if (!sa.member_node_ids.includes(nodeId)) sa.member_node_ids.push(nodeId);
    }
  } else {
    delete node.owner;
  }
}
function removeSubAgentById(id) {
  const list = ensureSubAgents();
  const idx = list.findIndex((s) => s && s.sub_agent_id === id);
  if (idx < 0) return;
  list.splice(idx, 1);
  (currentAgent.workflow_nodes || []).forEach((n) => { if (n.owner === id) delete n.owner; });
}
async function openSubAgentEditor(existing) {
  const sa = existing || {};
  const res = await showAppModal({
    title: existing ? "编辑子Agent" : "新建子Agent",
    fields: [
      { label: "名称", value: sa.name || "", placeholder: "如：检索泳道" },
      { label: "颜色(#hex)", value: sa.color || "#5b8def", placeholder: "#5b8def" },
      { label: "模型供应商 provider_id（留空=继承方案/会话）", value: sa.provider_id || "", placeholder: "如 openai_main" },
      { label: "角色提示词", value: sa.role_prompt || "", placeholder: "这条泳道的职责/风格" },
      { label: "工具范围(逗号分隔，留空=继承方案)", value: (sa.enabled_tools || []).join(","), placeholder: "tool_a,tool_b" },
      { label: "本泳道并发上限(1-6)", value: String(sa.max_concurrency || 2) },
      { label: "每分钟限速(0=不限)", value: String(sa.rate_per_minute || 0) },
    ],
    confirmText: "保存",
  });
  if (res === null) return false;
  const [name, color, provider, role, tools, conc, rate] = res;
  const obj = existing || { sub_agent_id: newSubAgentLocalId(), member_node_ids: [] };
  obj.name = (name || "").slice(0, 80);
  obj.color = /^#[0-9a-fA-F]{6}$/.test(color) ? color : "#5b8def";
  obj.provider_id = (provider || "").slice(0, 120);
  obj.role_prompt = (role || "").slice(0, 4000);
  obj.enabled_tools = (tools || "").split(",").map((t) => t.trim()).filter(Boolean);
  obj.max_concurrency = Math.max(1, Math.min(parseInt(conc, 10) || 2, 6));
  obj.rate_per_minute = Math.max(0, Math.min(parseInt(rate, 10) || 0, 600));
  if (!existing) ensureSubAgents().push(obj);
  setFeedback("子Agent 已保存（记得点『保存』把方案写入后端）。");
  return true;
}
function subAgentsDrawer() {
  const list = ensureSubAgents();
  const rows = list.map((s) => `
    <div class="subagent-row" style="border-left:4px solid ${esc(subAgentHex(s))}">
      <div class="subagent-row-main">
        <strong>${esc(s.name || "(未命名)")}</strong>
        <span class="row-meta">${esc(s.provider_id || "继承模型")} · 领地 ${(s.member_node_ids || []).length} 节点 · 并发 ${s.max_concurrency || 2}${s.rate_per_minute ? (" · " + s.rate_per_minute + "/min") : ""}</span>
      </div>
      <div class="subagent-row-ops">
        <button class="button tiny secondary" data-action="subagent-edit" data-id="${esc(s.sub_agent_id)}" type="button">编辑</button>
        <button class="button tiny danger" data-action="subagent-delete" data-id="${esc(s.sub_agent_id)}" type="button">删除</button>
      </div>
    </div>`).join("");
  return `
    <div class="section-note">子Agent＝独立泳道：自带模型 / 角色 / 工具范围 / 并发，负责画布上你圈给它的节点。框选节点后用右侧工具条「指派」把节点划进某个子Agent 的领地；未圈地的节点归主agent(本体) 调度。</div>
    <div class="button-row"><button class="button" data-action="subagent-new" type="button">+ 新建子Agent</button></div>
    <div class="subagent-list">${rows || '<div class="empty">还没有子Agent。点上面新建，再框选节点指派领地。</div>'}</div>`;
}
function workflowAgentColorFor(key) {
  const n = (currentAgent.workflow_nodes || []).find((x) => x.action === "agent_role" && String(x.sub_agent_id || x.id) === String(key));
  if (n && /^#[0-9a-fA-F]{6}$/.test(String(n.color || ""))) return n.color;
  if (n && n.main_agent) return "#7c5cff";
  const sa = subAgentById(key);
  return sa ? subAgentHex(sa) : "#5b8def";
}
function workflowTerritoryLayer(offsetX, offsetY) {
  const nodes = currentAgent.workflow_nodes || [];
  // 领地所有者 = 画布上的 agent_role 节点（含主Agent）；颜色取节点自身，和卡片一致。
  const owners = [];
  nodes.filter((n) => n.action === "agent_role").forEach((n) => {
    owners.push({ key: String(n.sub_agent_id || n.id), name: n.title || n.name || (n.main_agent ? "主 Agent" : "Agent"), color: workflowAgentColorFor(n.sub_agent_id || n.id), main: !!n.main_agent });
  });
  ensureSubAgents().forEach((sa) => { if (!owners.some((o) => o.key === sa.sub_agent_id)) owners.push({ key: sa.sub_agent_id, name: sa.name || "子Agent", color: subAgentHex(sa), main: false }); });
  if (!owners.length) return "";
  const NODE_W = WORKFLOW_NODE_WIDTH, NODE_H = WORKFLOW_NODE_HEIGHT, PAD = 32;
  return owners.map((o) => {
    const members = nodes.filter((n) => String(n.owner || "") === o.key);
    if (!members.length) return "";
    const xs = members.map((n) => Number(n.x || 0));
    const ys = members.map((n) => Number(n.y || 0));
    const minX = Math.min.apply(null, xs) + offsetX - PAD;
    const minY = Math.min.apply(null, ys) + offsetY - PAD - 18;
    const maxX = Math.max.apply(null, xs) + offsetX + NODE_W + PAD;
    const maxY = Math.max.apply(null, ys) + offsetY + NODE_H + PAD;
    const painting = workflowTerritoryPaintAgent === o.key;
    return `<div class="workflow-territory ${o.main ? "is-main" : ""} ${painting ? "is-painting" : ""}" style="left:${minX}px;top:${minY}px;width:${maxX - minX}px;height:${maxY - minY}px;--terr:${o.color}"><span class="workflow-territory-tag" style="background:${o.color}">${esc(o.name)}${o.main ? " · 主" : ""}</span></div>`;
  }).join("");
}
function workflowAssignBar() {
  const list = ensureSubAgents();
  if (!workflowSelectedNodeIds.size || !list.length) return "";
  const btns = list.map((s) => `<button class="workflow-dock-button text" data-action="assign-subagent" data-id="${esc(s.sub_agent_id)}" title="把框选节点指派给 ${esc(s.name || "")}" type="button" style="border-color:${esc(subAgentHex(s))}">${esc((s.name || "子").slice(0, 4))}</button>`).join("");
  return `<div class="workflow-dock-group"><span class="workflow-dock-label">指派</span>${btns}<button class="workflow-dock-button text" data-action="assign-subagent" data-id="" title="移出领地（归主agent）" type="button">移出</button></div>`;
}

function workflowNodeColor(item) {
  const __ownerCol = item && item.owner ? subAgentColorOf(item.owner) : "";
  if (__ownerCol) return __ownerCol;
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
  // 每种 edge_type 一个同色箭头标记。
  const types = ["success", "failed", "uncertain", "error", "retry", "timeout", "approved", "rejected", "always"];
  return `
    <defs>
      ${types.map((type) => {
        const color = workflowEdgeColor(type);
        return `
          <marker id="workflow-arrow-${type}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="${color}"></path>
          </marker>
        `;
      }).join("")}
    </defs>
  `;
}

// 出口锚点：多出口节点按端口在节点高度上均匀分布；单出口仍在右侧中点。
function workflowNodeOutAnchor(node, port, offsetX = 0, offsetY = 0) {
  const portsObj = workflowNodePorts(node);
  const outs = portsObj.outputs || ["success"];
  const ins = portsObj.inputs || [];
  const leftX = Number(node.x || 0) + offsetX;
  const baseX = leftX + WORKFLOW_NODE_WIDTH;
  const top = Number(node.y || 0) + offsetY;
  const isLoopNode = ins.includes("retry");
  if (isLoopNode) {
    // 重试节点：成功/失败出口都在左侧（补偿左边框宽度，让线从圆点正中出发）。
    let li = outs.indexOf(port);
    if (li < 0) li = 0;
    const lspan = WORKFLOW_NODE_HEIGHT / (outs.length + 1);
    return { x: leftX + WORKFLOW_NODE_BORDER, y: top + lspan * (li + 1), leftExit: true };
  }
  if (!workflowNodeHasMultiOut(node) || outs.length <= 1) {
    return { x: baseX, y: top + WORKFLOW_NODE_HEIGHT / 2 };
  }
  let idx = outs.indexOf(port);
  if (idx < 0) idx = 0;
  const span = WORKFLOW_NODE_HEIGHT / (outs.length + 1);
  return { x: baseX, y: top + span * (idx + 1) };
}

function workflowMinimapBounds(size) {
  const nodes = currentAgent.workflow_nodes || [];
  const viewport = workflowViewportWorldRect();
  const xs = [viewport.x, viewport.x + viewport.width];
  const ys = [viewport.y, viewport.y + viewport.height];
  for (const item of nodes) {
    const x = Number(item.x || 0);
    const y = Number(item.y || 0);
    xs.push(x, x + WORKFLOW_NODE_WIDTH);
    ys.push(y, y + WORKFLOW_NODE_HEIGHT);
  }
  const minX = Math.min(...xs) - 180;
  const minY = Math.min(...ys) - 160;
  const maxX = Math.max(...xs) + 180;
  const maxY = Math.max(...ys) + 160;
  const fallbackMinX = Number(size.minX || 0);
  return {
    minX: Number.isFinite(minX) ? minX : fallbackMinX,
    minY: Number.isFinite(minY) ? Math.min(0, minY) : 0,
    maxX: Number.isFinite(maxX) ? maxX : Number(size.width || 1),
    maxY: Number.isFinite(maxY) ? maxY : Number(size.height || 1),
  };
}

function workflowMinimap(size) {
  const mapWidth = workflowMinimapWidth;
  const mapHeight = workflowMinimapHeight;
  const bounds = workflowMinimapBounds(size);
  const boundsWidth = Math.max(1, bounds.maxX - bounds.minX);
  const boundsHeight = Math.max(1, bounds.maxY - bounds.minY);
  const scale = Math.min((mapWidth - 18) / boundsWidth, (mapHeight - 18) / boundsHeight);
  const offsetX = Math.max(8, (mapWidth - boundsWidth * scale) / 2);
  const offsetY = Math.max(8, (mapHeight - boundsHeight * scale) / 2);
  const viewport = workflowViewportWorldRect();
  const vx = clamp(viewport.x, bounds.minX, bounds.maxX);
  const vy = clamp(viewport.y, bounds.minY, bounds.maxY);
  const vw = clamp(viewport.width, 80, Math.max(80, bounds.maxX - vx));
  const vh = clamp(viewport.height, 60, Math.max(60, bounds.maxY - vy));
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
        <g transform="translate(${offsetX - bounds.minX * scale} ${offsetY - bounds.minY * scale}) scale(${scale})">
          ${edgeLines}
          ${nodeRects}
          <rect class="workflow-minimap-viewport" x="${vx}" y="${vy}" width="${vw}" height="${vh}" rx="10"></rect>
        </g>
      </svg>
      <span class="workflow-minimap-resize is-east" data-edge="e" title="拖动调整小地图宽度"></span>
      <span class="workflow-minimap-resize is-south" data-edge="s" title="拖动调整小地图高度"></span>
      <span class="workflow-minimap-resize is-corner" data-edge="se" title="拖动调整小地图大小"></span>
    </div>
  `;
}

function workflowViewportWorldRect() {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const width = wrap?.clientWidth || window.innerWidth || 1200;
  const height = wrap?.clientHeight || window.innerHeight || 760;
  const zoom = Number(workflowZoom || 1) || 1;
  const offsetX = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  const offsetY = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetY || workflowWorldOffsetY()) || 0;
  return {
    x: -workflowPanX / zoom - offsetX,
    y: -workflowPanY / zoom - offsetY,
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
  const bounds = workflowMinimapBounds(size);
  const worldX = clamp((event.clientX - rect.left - offsetX) / scale + bounds.minX, bounds.minX, bounds.maxX);
  const worldY = clamp((event.clientY - rect.top - offsetY) / scale + bounds.minY, bounds.minY, bounds.maxY);
  const renderOffsetX = workflowWorldOffsetX(size);
  const renderOffsetY = workflowWorldOffsetY(size);
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const width = wrap?.clientWidth || window.innerWidth || 1200;
  const height = wrap?.clientHeight || window.innerHeight || 760;
  workflowPanX = Math.round(width / 2 - (worldX + renderOffsetX) * workflowZoom);
  workflowPanY = Math.round(height / 2 - (worldY + renderOffsetY) * workflowZoom);
  refreshWorkflowCanvasDom();
}

function workflowNodeAnchor(node, port = "out", offsetX = 0, offsetY = 0) {
  const left = Number(node.x || 0) + offsetX;
  const y = Number(node.y || 0) + offsetY + WORKFLOW_NODE_HEIGHT / 2;
  if (port === "out") return { x: left + WORKFLOW_NODE_WIDTH, y };
  // 输入：重试节点的入口在右侧；普通节点在左侧（补偿 5px 左边框，使锚点与圆点正中重合）。
  const isLoop = (workflowNodePorts(node).inputs || []).includes("retry");
  if (isLoop) return { x: left + WORKFLOW_NODE_WIDTH, y, rightEntry: true };
  return { x: left + WORKFLOW_NODE_BORDER, y };
}

function workflowLinkPath(from, to) {
  const x1 = Number(from.x || 0);
  const y1 = Number(from.y || 0);
  const x2 = Number(to.x || 0);
  const y2 = Number(to.y || 0);
  // 出发方向：左侧出口往左甩，其余往右。
  const c1x = from.leftExit ? x1 - clamp(Math.abs(x2 - x1) * 0.4, 70, 200) : x1 + clamp(Math.abs(x2 - x1) * 0.4, 70, 200);
  // 进入方向：右侧入口（重试节点）从右边进，其余从左边进。
  const c2x = to.rightEntry ? x2 + clamp(Math.abs(x2 - x1) * 0.4, 70, 200) : x2 - clamp(Math.abs(x2 - x1) * 0.4, 70, 200);
  return `M ${x1} ${y1} C ${c1x} ${y1}, ${c2x} ${y2}, ${x2} ${y2}`;
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
  const entryNodes = nodes.filter((node) => node.stage === "entry" || ["listen_message", "summarize_entry", "confirm_entry"].includes(node.action));
  const terminalNodes = nodes.filter((node) => ["archive", "exit_summary"].includes(node.action) || (node.stage === "archive" && !["notify", "manual"].includes(node.action)));
  const actions = new Set(nodes.map((node) => node.action));
  const guardNodes = nodes.filter((node) => node.stage === "guard" || ["guard", "human"].includes(node.kind));
  const hasApproval = nodes.some((node) => ["request_approval", "wait_user", "handoff"].includes(node.action) || ["guard", "human"].includes(node.kind));
  if (!entryNodes.length) issues.push({ level: "error", message: "缺少入口节点。" });
  if (!terminalNodes.length) issues.push({ level: "error", message: "缺少真正的出口/归档节点。" });
  if (!guardNodes.length) issues.push({ level: "warn", message: "缺少审批或人工闸门。" });
  if (!actions.has("listen_message")) issues.push({ level: "warn", message: "建议使用统一消息监听入口承接命令、关键词、WebUI、插件事件和 webhook。" });
  if (currentAgent.isolation_policy?.mode !== "off" && !actions.has("global_control")) issues.push({ level: "warn", message: "隔离/预算/汇报策略建议通过全局控制节点统一生效。" });
  if (!actions.has("save_memory")) issues.push({ level: "warn", message: "缺少任务记忆节点。" });
  if (!actions.has("archive_memory_folder")) issues.push({ level: "warn", message: "建议把任务回流到方案级记忆夹，避免不同方案串记忆。" });
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

function node(item, offsetX = workflowWorldOffsetX(), offsetY = workflowWorldOffsetY()) {
  const selected = item.id === selectedWorkflowNodeId;
  const multiSelected = workflowSelectedNodeIds.has(item.id);
  const color = workflowNodeColor(item);
  const runtime = workflowNodeRuntimeInfo(item);
  const executorState = workflowNodeExecutorState(item);
  const ports = workflowNodePorts(item);
  const inputs = ports.inputs || [];
  const outputs = ports.outputs || [];
  const isLoopNode = inputs.includes("retry");
  const hasInput = inputs.length > 0;
  const pendingIn = workflowPendingPort?.nodeId === item.id && workflowPendingPort?.port === "in";
  let inPortHtml = "";
  let outPortsHtml = "";
  if (isLoopNode) {
    // 重试节点：重试“入口”在右侧（别的节点失败/出错时连到这里）；成功/失败“出口”在左侧（处理完回到需要重试的起点）。
    inPortHtml = `<span class="node-port node-port-in node-port-loop-in ${pendingIn ? "pending" : ""}" data-port="in" data-node-id="${esc(item.id)}" style="--port-color:${workflowEdgeColor("retry")}" title="重试入口：其他节点失败/出错时连到这里"><i class="port-tag port-tag-left" style="--port-color:${workflowEdgeColor("retry")}">↺ 重试入口</i></span>`;
    outPortsHtml = outputs.map((type, idx) => {
      const span = 100 / (outputs.length + 1);
      const topPct = span * (idx + 1);
      const pend = workflowPendingPort?.nodeId === item.id && workflowPendingPort?.port === type;
      return `<span class="node-port node-port-out node-port-typed node-port-left ${pend ? "pending" : ""}" data-port="${esc(type)}" data-edge-type="${esc(type)}" data-node-id="${esc(item.id)}" style="top:${topPct}%;--port-color:${workflowEdgeColor(type)}" title="${esc(workflowPortShortLabel(type))}出口：回到需要重试的起点"><i class="port-tag port-tag-left" style="--port-color:${workflowEdgeColor(type)}">${esc(workflowPortShortLabel(type))}</i></span>`;
    }).join("");
  } else {
    inPortHtml = hasInput
      ? `<span class="node-port node-port-in ${pendingIn ? "pending" : ""}" data-port="in" data-node-id="${esc(item.id)}" title="输入连接点"></span>`
      : "";
    if (workflowNodeHasMultiOut(item)) {
      outPortsHtml = outputs.map((type, idx) => {
        const span = 100 / (outputs.length + 1);
        const topPct = span * (idx + 1);
        const pend = workflowPendingPort?.nodeId === item.id && workflowPendingPort?.port === type;
        return `<span class="node-port node-port-out node-port-typed ${pend ? "pending" : ""}" data-port="${esc(type)}" data-edge-type="${esc(type)}" data-node-id="${esc(item.id)}" style="top:${topPct}%;--port-color:${workflowEdgeColor(type)}" title="${esc(workflowPortShortLabel(type))}出口"><i class="port-tag" style="--port-color:${workflowEdgeColor(type)}">${esc(workflowPortShortLabel(type))}</i></span>`;
      }).join("");
    } else {
      const pendingOut = workflowPendingPort?.nodeId === item.id && (workflowPendingPort?.port === "out" || workflowPendingPort?.port === "success");
      outPortsHtml = `<span class="node-port node-port-out ${pendingOut ? "pending" : ""}" data-port="out" data-edge-type="success" data-node-id="${esc(item.id)}" title="输出连接点"></span>`;
    }
  }
  return `
    <article class="node flow-node ${selected ? "selected" : ""} ${multiSelected ? "multi-selected" : ""} ${workflowNodeHasMultiOut(item) ? "has-multi-out" : ""}" style="left:${Number(item.x || 0) + offsetX}px;top:${Number(item.y || 0) + offsetY}px;--node-color:${color}" data-action="select-workflow-node" data-id="${esc(item.id)}" data-kind="${esc(item.kind)}" data-stage="${esc(workflowStage(item))}" role="button" tabindex="0">
      ${inPortHtml}
      ${outPortsHtml}
      ${workflowApiBadge(item)}
      <span class="node-stage">${esc(workflowStageLabel(item.stage || "plan"))} · ${esc(workflowActionLabel(item.action || "manual"))}</span>
      <span class="node-runtime">
        <b class="runtime-badge ${esc(executorState.tone)}">${esc(executorState.label)}</b>
        <em>${esc(WORKFLOW_RUNTIME_LABELS[runtime.runtime_type] || runtime.runtime_type || "ReAct")}</em>
      </span>
      <strong>${esc(item.title || item.id)}</strong>
      <p>${esc(item.instruction || item.description || item.id)}</p>
      ${workflowBlockCardExtra(item)}
      <span>${esc(item.id)} · ${esc(workflowKindLabel(item.kind || "state"))}${item.output_variable ? ` · 输出 ${esc(item.output_variable)}` : ""}${item.prompt ? " · 有提示词" : ""}</span>
    </article>
  `;
}

function workflowBlockCardExtra(item) {
  const act = item.action || "";
  if (act === "agent_role") {
    const subId = item.sub_agent_id || item.id || "";
    const painting = workflowTerritoryPaintAgent && workflowTerritoryPaintAgent === subId;
    const tools = Array.isArray(item.enabled_tools) ? item.enabled_tools.length : 0;
    const owned = (currentAgent.workflow_nodes || []).filter((n) => n.owner === subId && n.action !== "agent_role").length;
    const summary = `${esc(item.provider_id || "继承模型")} · 工具 ${tools ? tools : "继承"} · 并发 ${item.max_concurrency || 2}${item.rate_per_minute ? (" · " + item.rate_per_minute + "/min") : ""} · 领地 ${owned} 节点`;
    return `<div class="node-block-extra"><span class="node-block-summary">${summary}</span><button class="node-block-btn ${painting ? "active" : ""}" data-action="agent-role-territory" data-id="${esc(subId)}" type="button">${painting ? "完成圈地" : "选领地"}</button></div>`;
  }
  if (act === "api_scope") {
    const painting = workflowApiScopePaint && workflowApiScopePaint === item.id;
    const cnt = Array.isArray(item.scope_node_ids) ? item.scope_node_ids.length : 0;
    const scopeLabel = ({ selected: "框选节点", downstream: "下游", all: "整个方案" })[item.scope_mode || "selected"] || (item.scope_mode || "框选节点");
    const summary = `API: ${esc(item.api_id || "未绑定")} · 范围 ${scopeLabel} · ${cnt} 节点`;
    return `<div class="node-block-extra"><span class="node-block-summary">${summary}</span><button class="node-block-btn ${painting ? "active" : ""}" data-action="api-scope-range" data-id="${esc(item.id)}" type="button">${painting ? "完成选范围" : "选范围"}</button></div>`;
  }
  return "";
}

function workflowApiBadge(item) {
  if (!item || item.action === "api_scope") return "";
  const scopes = (currentAgent.workflow_nodes || []).filter((n) => n.action === "api_scope" && Array.isArray(n.scope_node_ids) && n.scope_node_ids.includes(item.id));
  if (!scopes.length) return "";
  const apiNames = scopes.map((n) => n.api_id || "API").join(" / ");
  return `<span class="node-api-badge" title="受 API 范围块覆盖：${esc(apiNames)}">API</span>`;
}

function selectedWorkflowNode() {
  ensureWorkflow();
  return currentAgent.workflow_nodes.find((item) => item.id === selectedWorkflowNodeId) || currentAgent.workflow_nodes[0];
}

function workflowDatalistOptions(items, key = "name", label = "description") {
  return (items || [])
    .map((item) => {
      const value = String(item?.[key] || item?.name || item?.api_id || item?.module_id || "").trim();
      if (!value) return "";
      const text = String(item?.[label] || item?.display_name || item?.path || item?.url || "").trim();
      return `<option value="${esc(value)}">${esc(text || value)}</option>`;
    })
    .join("");
}

// ============ 节点"填空题"字段注册表 ============
// 每个 action 只暴露新手真正需要填的几个字段；高级字段收进"高级"模式。
const WORKFLOW_SIMPLE_FIELDS = {
  agent_role: [
    { field: "_role_lead", label: "Agent 角色块", type: "note", text: "上方『节点名称』就是这个 Agent 的名字；保存方案后会同步成一个子Agent 泳道。" },
    { field: "provider_id", label: "模型 / provider（留空＝继承方案）", type: "text", placeholder: "如：openai-gpt4o" },
    { field: "color", label: "卡片 / 领地颜色", type: "color", default: "#5b8def" },
    { field: "role_prompt", label: "角色提示词", type: "textarea", placeholder: "这个 Agent 的职责、风格与边界。" },
    { field: "enabled_tools", label: "工具范围（每行一个工具名，留空＝继承方案）", type: "lines", placeholder: "web_search" },
    { field: "max_concurrency", label: "并发上限", type: "number", default: 2, min: 1, max: 16 },
    { field: "rate_per_minute", label: "每分钟限速（0＝不限）", type: "number", default: 0, min: 0, max: 1000 },
    { field: "_territory", label: "领地（圈地）", type: "note", text: "点卡片上的『选领地』按钮→直接在画布拖框，框住的节点就归这个 Agent；拖动节点进出方框即增减。未圈的节点归主Agent。" },
  ],
  api_scope: [
    { field: "api_id", label: "绑定哪个已注册 API？", type: "apiPick", required: true },
    { field: "scope_mode", label: "作用范围", type: "select", default: "selected", options: [["selected","只作用于框选的节点"],["downstream","作用于下游所有节点"],["all","作用于整个方案"]] },
    { field: "output_variable", label: "输出变量名", type: "text", placeholder: "workflow.api_scope" },
    { field: "_api_scope", label: "API 作用范围", type: "note", text: "只声明一组节点默认用的 API，和一次性『API 调用』节点区分；范围内节点未显式指定 API 时回退到这里。" },
  ],
  prompt_inject: [
    { field: "inject_text", label: "要注入的提示文本", type: "textarea", required: true, placeholder: "会拼进后续执行上下文的提示，例如：注意目标站点限频，放慢节奏。" },
    { field: "inject_scope", label: "注入范围", type: "select", default: "downstream", options: [["downstream","下游所有节点"],["next","仅下一个节点"],["all","整个任务"]] },
    { field: "_pi", label: "提示注入（原便签升级）", type: "note", text: "和便签不同，这段文本会真正影响后续节点/Agent 的执行，不只是注释。" },
  ],
  note: [
    { field: "inject_text", label: "要注入的提示文本", type: "textarea", required: true,
      placeholder: "会拼进后续执行上下文的提示，例如：注意目标站点限频，放慢节奏。" },
    { field: "inject_scope", label: "注入范围", type: "select", default: "downstream",
      options: [["downstream","下游所有节点"],["next","仅下一个节点"],["all","整个任务"]] },
    { field: "_note_pi", label: "便签＝提示注入", type: "note",
      text: "这张便签会把文本真正注入后续节点/Agent 的执行上下文（不再是纯注释）。需要有输入和输出连线。" },
  ],
  delay: [
    { field: "delay_seconds", label: "延时秒数（0–300）", type: "number", default: 5, min: 0, max: 300,
      hint: "等待指定秒数再继续；长暂停请用心跳，避免长占运行轮。" },
  ],
  dispatch_tasks: [
    { field: "assignments", label: "分派清单（每行：目标子Agent | 指令 | 资源标签,逗号分隔）", type: "lines", required: true,
      placeholder: "检索员 | 查最新文档 | site:docs\n编码员 | 改 main.py | file:main.py" },
    { field: "_disp", label: "主agent 派活", type: "note", text: "每行派给一个子Agent，写进共享黑板。目标填子Agent 名称或 ID（在右侧『子Agent』面板创建）；指令、资源标签可留空。实际由谁执行取决于画布上的『圈地』归属。" },
  ],
  collect_report: [
    { field: "_cr", label: "报告整理", type: "note", text: "自动收齐最近一轮并行 worker 的产出，按子Agent 归集为结构化报告写入共享黑板，无需额外配置。放在并行分支汇总之后。" },
  ],
  agent_message: [
    { field: "target_sub_agent", label: "投递给哪个子Agent？", type: "subAgentPick", required: true },
    { field: "message", label: "意见 / 指令内容", type: "textarea", required: true, placeholder: "如：注意目标站点限频，放慢节奏。" },
  ],
  agent_debate: [
    { field: "perspectives", label: "参与质询的视角（每行一个）", type: "lines", placeholder: "correctness\nsafety\ncompletion" },
    { field: "require_consensus", label: "要求全部视角通过才算过", type: "checkbox" },
    { field: "instruction", label: "讨论议题 / 校验重点", type: "textarea", placeholder: "让各视角围绕哪个结论互相质询。" },
  ],
  debate_validation: [
    { field: "perspectives", label: "校验视角（每行一个）", type: "lines", placeholder: "correctness\nsafety\ncompletion" },
    { field: "require_consensus", label: "要求全部视角通过才算过", type: "checkbox" },
    { field: "instruction", label: "校验重点", type: "textarea" },
  ],
  summarize_decision: [
    { field: "decision", label: "决策依据 / 倾向（留空＝自动汇总黑板）", type: "textarea", placeholder: "如：证据充分则进入执行，否则补充检索。" },
    { field: "next_step", label: "下一步去向说明", type: "text", placeholder: "如：进入执行阶段" },
  ],
  transform_context: [
    { field: "instruction", label: "整理 / 转换目标", type: "textarea", placeholder: "如：把检索结果汇总成要点，去重并标注来源。" },
  ],
  save_state: [
    { field: "instruction", label: "检查点备注（可选）", type: "textarea", placeholder: "记录当前进度要点，便于回档续写。" },
  ],
  generate_report: [
    { field: "instruction", label: "报告范围 / 包含什么", type: "textarea", placeholder: "如：汇总成果、关键改动、遗留风险、下次续写入口。" },
  ],
  plugin_event_trigger: [
    { field: "plugin_sources", label: "来自哪些插件（每行一个，留空＝任意插件）", type: "lines", placeholder: "astrbot_plugin_xxx" },
    { field: "event_names", label: "监听哪些事件名（每行一个，留空＝全部）", type: "lines", placeholder: "qq_guard.ban_requested" },
    { field: "match_mode", label: "匹配方式", type: "select", default: "any", options: [["any","命中任一事件即触发"],["all","全部事件命中才触发"]] },
    { field: "_pet", label: "插件事件入口", type: "note", text: "只承接其它插件广播的事件；保存后自动并入工作流触发的『插件事件』类型。" },
  ],
  listen_message: [
    { field: "monitor_scope", label: "监听时机", type: "select", default: "mentioned",
      options: [["mentioned","被 @ / 对话 / 命令时"],["global","全局监听所有消息"]],
      hint: "全局监听适合群管/刷屏；被对话时更省资源。" },
    { field: "command_names", label: "斜杠命令 / 命令别名（每行一个，可留空）", type: "lines",
      placeholder: "agentlab\nal" },
    { field: "trigger_phrases", label: "暗号 / 精确短语（每行一个，可留空）", type: "lines", syncPath: "entry_policy.trigger_phrases",
      placeholder: "进入任务模式" },
    { field: "keywords", label: "关键词 / 模糊命中（每行一个，可留空）", type: "lines",
      placeholder: "广告\n加群" },
    { field: "regex", label: "正则匹配（每行一个，可留空·进阶）", type: "lines",
      placeholder: "https?://" },
    { field: "require_confirmation", label: "进入任务前需要确认", type: "checkbox", syncPath: "entry_policy.require_confirmation" },
    { field: "confirmation_text", label: "确认话术（可选）", type: "textarea", syncPath: "entry_policy.confirmation_text",
      placeholder: "留空用默认；填了则进入前先发这段确认语。" },
    { field: "_lm", label: "消息监听入口", type: "note",
      text: "命令/暗号/关键词/正则——填了哪项就启用哪项匹配，未填即忽略；不再需要单独勾选触发类型。黑白名单、群聊/私聊范围在『范围过滤器』节点配置；定时 / 插件事件 / Webhook 请用各自专用入口素材。" },
  ],
  match_keyword: [
    { field: "keywords", label: "命中哪些关键词？", type: "lines", required: true,
      placeholder: "每行一个，如：广告\n加微信" },
    { field: "_route", label: "命中后走哪条线？", type: "note",
      text: "命中走『通过/成功』出口，没命中走『未命中/失败』出口——在画布上把两个出口连到不同节点。" },
  ],
  match_regex: [
    { field: "regex", label: "正则规则（高级匹配）", type: "lines", required: true,
      placeholder: "每行一个正则，如：(加|进).{0,3}群" },
  ],
  llm_detect: [
    { field: "instruction", label: "让 AI 判断什么？", type: "textarea", required: true,
      placeholder: "如：判断这条消息是不是广告 / 引战 / 人身攻击" },
    { field: "keywords", label: "（可选）先用这些词快速命中", type: "lines",
      placeholder: "填了就先按关键词判断，省一次模型调用" },
  ],
  scope_filter: [
    { field: "_scope", label: "在下方『生效范围』里填写", type: "note",
      text: "选全局或填群聊/私聊、群和用户的黑白名单；命中走『成功』出口，不命中走『失败』出口。" },
  ],
  schedule_trigger: [
    { field: "cron", label: "定时 Cron 表达式", type: "textarea", required: true, placeholder: "每天9点：0 9 * * *；每15分钟：*/15 * * * *" },
    { field: "timezone", label: "时区（可选）", type: "text", placeholder: "Asia/Shanghai" },
    { field: "jitter_seconds", label: "错峰抖动秒数（0＝不抖动）", type: "number", default: 0, min: 0, max: 86400 },
    { field: "_st", label: "复杂定时入口", type: "note", text: "只承接定时触发；保存后自动并入工作流触发的『定时』类型。" },
  ],
  webhook_trigger: [
    { field: "webhook_path", label: "Webhook 路径", type: "text", required: true, placeholder: "/agent-lab/moderation" },
    { field: "auth_type", label: "鉴权方式", type: "select", default: "none", options: [["none","无鉴权"],["bearer","Bearer Token"],["header","自定义 Header"]] },
    { field: "credential_id", label: "凭证（Bearer/Header 时选）", type: "credPick" },
    { field: "_wt", label: "Webhook 入口", type: "note", text: "只承接外部 Webhook 调用；保存后自动并入『Webhook』类型。路径建议唯一，避免任何请求都命中。" },
  ],
  run_tools: [
    { field: "tool_name", label: "调用哪个工具？", type: "toolPick", required: true },
    { field: "instruction", label: "让它做什么 / 关键参数说明", type: "textarea",
      placeholder: "用一句话说清这一步要用这个工具做什么。" },
  ],
  call_api: [
    { field: "api_id", label: "调用哪个已注册的 API？", type: "apiPick", required: true },
    { field: "instruction", label: "这次调用要拿到什么？", type: "textarea",
      placeholder: "如：查询今天天气，取出温度和天气描述。" },
  ],
  http_request: [
    { field: "url", label: "请求地址 URL", type: "text", required: true, placeholder: "https://..." },
    { field: "method", label: "请求方式", type: "select", default: "GET",
      options: [["GET","GET"],["POST","POST"],["PUT","PUT"],["PATCH","PATCH"],["DELETE","DELETE"]] },
  ],
  send_message: [
    { field: "send_type", label: "发送类型", type: "select", default: "text",
      options: [["text","固定文本"],["prompt","提示词生成回复"],["image","图片"],["emoji","表情"],["plugin","交给插件"]] },
    { field: "message", label: "发送什么内容？", type: "textarea", required: true,
      placeholder: "如：检测到广告，已处理。" },
    { field: "prompt", label: "提示词回复 / 插件调用提示", type: "textarea",
      placeholder: "选择提示词或插件时，写清让 Bot 生成/调用什么。" },
    { field: "image", label: "图片 URL / 路径 / base64", type: "text", placeholder: "https://... 或 C:\\path\\image.png" },
    { field: "face", label: "表情 ID", type: "text", placeholder: "平台支持的表情/emoji ID" },
    { field: "plugin_name", label: "交给哪个插件？", type: "pluginPick" },
    { field: "target", label: "发给谁？（留空＝当前会话）", type: "text", placeholder: "群号 / 用户 ID" },
  ],
  send_private_message: [
    { field: "message", label: "私信内容", type: "textarea", required: true },
    { field: "target", label: "发给谁？", type: "text", required: true, placeholder: "用户 ID / QQ 号" },
  ],
  send_email: [
    { field: "target", label: "收件邮箱", type: "text", required: true, placeholder: "admin@example.com" },
    { field: "message", label: "邮件正文", type: "textarea", required: true },
  ],
  notify: [
    { field: "message", label: "通知内容", type: "textarea", placeholder: "留空则自动汇报当前任务进度。" },
  ],
  request_approval: [
    { field: "instruction", label: "这一步为什么要先审批？", type: "textarea", required: true,
      placeholder: "说清影响范围，如：将删除 3 个文件，不可恢复。" },
  ],
  handoff: [
    { field: "handoff_mode", label: "怎么交接？", type: "select", default: "wait_reply",
      options: [["wait_reply","等用户回复"],["dm_admin","私信管理员处理"],["group_prompt","当前群提示并等待"],["external_callback","等外部回调/回写"]] },
    { field: "instruction", label: "交接说明 / 等用户提供什么？", type: "textarea", required: true,
      placeholder: "如：需要登录 / 验证码 / 业务判断时，停下等用户。" },
  ],
  wait_user: [
    { field: "instruction", label: "等用户提供什么？", type: "textarea", required: true },
  ],
  save_memory: [
    { field: "tags", label: "记忆标签", type: "lines", required: true,
      placeholder: "每行一个，如：部署记录\n踩坑" },
    { field: "folder_id", label: "归入记忆夹", type: "folderPick" },
    { field: "expose_to_normal", label: "普通聊天可按标签看到", type: "checkbox" },
    { field: "instruction", label: "要记住什么？", type: "textarea" },
  ],
  retrieve_memory: [
    { field: "tags", label: "按哪些标签找回记忆？", type: "lines",
      placeholder: "每行一个标签；留空则按任务关键词。" },
    { field: "folder_id", label: "限定记忆夹", type: "folderPick" },
    { field: "source_task_id", label: "限定来源任务 ID", type: "text", placeholder: "可选，用于回档续写" },
  ],
  memory_filter: [
    { field: "admission_allow", label: "记忆准入白名单（标签）", type: "lines",
      placeholder: "每行一个标签；填了则只允许带这些标签的记忆进入任务。" },
    { field: "admission_deny", label: "记忆准入黑名单（标签）", type: "lines",
      placeholder: "每行一个标签；带这些标签的记忆一律不进入任务。" },
    { field: "block_daily_memory", label: "任务中屏蔽日常记忆", type: "checkbox",
      hint: "开启后任务检索只看任务沉淀记忆，不带入普通聊天的日常记忆。" },
    { field: "reflow_scope", label: "成果回流暴露范围", type: "select", default: "tags_only",
      options: [["none","不回流（任务内私有）"],["tags_only","仅暴露标签索引"],["full","完整回流"]],
      hint: "控制本任务记忆对普通模式/其它任务的暴露程度，防止记忆串联。" },
  ],
  summarize_memory: [
    { field: "summary", label: "总结模板 / 摘要重点", type: "textarea",
      placeholder: "留空则按任务目标、摘要、进度和观察自动总结。" },
  ],
  export_task_memory: [
    { field: "instruction", label: "导出范围", type: "textarea",
      placeholder: "说明要导出哪些进度、记录、报告或节点输出。" },
  ],
  promote_memory_candidate: [
    { field: "memory_id", label: "候选记忆 ID（可留空）", type: "text",
      placeholder: "留空则从当前任务观察/摘要生成一条 accepted 记忆。" },
    { field: "folder_id", label: "归入记忆夹", type: "folderPick" },
    { field: "reason", label: "提升理由", type: "textarea" },
  ],
  forget_task_memory: [
    { field: "memory_id", label: "要遗忘的记忆 ID（留空＝当前任务相关）", type: "text" },
  ],
  archive_memory_folder: [
    { field: "folder_id", label: "归档到哪个记忆夹", type: "folderPick" },
    { field: "folder_name", label: "没有记忆夹时新建名称", type: "text", placeholder: "方案记忆夹" },
    { field: "detail_level", label: "保留细节", type: "select", default: "summary",
      options: [["summary","只保留摘要索引"],["full","保留完整任务导出"]] },
    { field: "retention_days", label: "保留天数（0＝长期）", type: "number", default: 0, max: 3650 },
    { field: "expose_to_normal", label: "普通聊天可按标签看到", type: "checkbox" },
    { field: "tags", label: "归档标签", type: "lines", placeholder: "每行一个标签" },
  ],
  retry: [
    { field: "max_retries", label: "最多重试几次？", type: "number", default: 3,
      hint: "超过次数仍失败就走『失败』出口（可连到给管理员发消息）。" },
    { field: "instruction", label: "重试时注意什么？", type: "textarea",
      placeholder: "如：每次重试前换一种参数，并记录失败原因。" },
  ],
  route_condition: [
    { field: "route_variable", label: "读取哪个变量来分流", type: "text", placeholder: "如：risk.level 或 detector.route" },
    { field: "routes", label: "路由表 JSON", type: "textarea",
      placeholder: "{\n  \"low\": \"execute\",\n  \"high\": \"approval\"\n}" },
    { field: "instruction", label: "分流说明", type: "textarea", required: true,
      placeholder: "也可以直接在连线上填写 condition；default/else 作为兜底出口。" },
  ],
  parallel_branch: [
    { field: "parallel_group", label: "并行分组", type: "text", placeholder: "default" },
    { field: "branches", label: "分支清单", type: "lines",
      placeholder: "资料检索 | 只读查证\n代码阅读 | 找入口和风险\n验收复核 | 对照完成条件" },
    { field: "instruction", label: "拆成哪几个并行子任务？", type: "textarea", required: true,
      placeholder: "如：一路查资料、一路读代码，互不依赖，最后汇总。" },
  ],
  limit_rate: [
    { field: "window_seconds", label: "时间窗（秒）", type: "number", default: 60, min: 1, max: 86400 },
    { field: "max_hits", label: "窗口内最多触发次数", type: "number", default: 5, min: 1, max: 10000 },
    { field: "bucket", label: "限流桶（可选）", type: "text", placeholder: "如：group_moderation" },
  ],
  catch_error: [
    { field: "disposition", label: "捕获错误后怎么处置", type: "select", default: "route",
      options: [["route","只按出口分流"],["retry","走重试出口"],["notify","走错误出口并通知"],["report","走错误出口并生成报告"],["pause","暂停等人工"]],
      hint: "retry 会从『重试』出口绕回；pause 会直接暂停任务等你处理；其余都走『错误』出口，按你连的下游节点处理。" },
    { field: "instruction", label: "处置说明", type: "textarea",
      placeholder: "例如：先走重试；仍失败则通知管理员并暂停。" },
  ],
  file_operation: [
    { field: "operation", label: "文件动作", type: "select", default: "read",
      options: [["read","读取"],["write","写入"],["replace","替换"],["append","追加"]] },
    { field: "path", label: "文件路径", type: "text", required: true, placeholder: "相对工作区或沙箱允许路径" },
    { field: "content", label: "写入/追加内容", type: "textarea", placeholder: "读取时可留空" },
  ],
  code_exec: [
    { field: "language", label: "执行语言", type: "select", default: "python",
      options: [["python","Python"],["shell","Shell / 命令"]] },
    { field: "command", label: "代码或命令", type: "textarea", required: true,
      placeholder: "例如：pytest -q 或一段 Python 脚本" },
    { field: "timeout_seconds", label: "超时秒数", type: "number", default: 10, min: 1, max: 60 },
  ],
  variable_set: [
    { field: "variable_name", label: "变量名", type: "text", required: true, placeholder: "variables.input.path" },
    { field: "value", label: "写入值 / JSON", type: "textarea", placeholder: "可写固定文本、JSON 或模板变量。" },
  ],
  variable_get: [
    { field: "variable_name", label: "读取变量名", type: "text", required: true, placeholder: "variables.input.path" },
    { field: "output_variable", label: "输出到", type: "text", placeholder: "variable.result" },
  ],
  text_template: [
    { field: "template", label: "文本模板", type: "textarea", required: true, placeholder: "你好 {{event.sender_name}}，当前状态是 {{task.current_summary}}" },
    { field: "output_variable", label: "输出变量", type: "text", placeholder: "template.text" },
  ],
  json_transform: [
    { field: "input_variable", label: "输入变量", type: "text", placeholder: "api.result" },
    { field: "expression", label: "JSON 路径 / 表达式", type: "text", placeholder: "." },
    { field: "output_variable", label: "输出变量", type: "text", placeholder: "json.value" },
  ],
  merge: [
    { field: "inputs", label: "合并哪些变量", type: "lines", placeholder: "每行一个变量路径" },
    { field: "output_variable", label: "输出变量", type: "text", placeholder: "merged.result" },
  ],
  iterator: [
    { field: "input_variable", label: "要迭代的数组/对象变量", type: "text", placeholder: "items" },
    { field: "output_variable", label: "输出变量", type: "text", placeholder: "iterator.items" },
  ],
  plan: [
    { field: "instruction", label: "怎么拆解这个任务？", type: "textarea",
      placeholder: "把目标拆成可验证的小步骤、完成条件和风险。" },
  ],
  validate_output: [
    { field: "instruction", label: "怎么算做完 / 验收标准？", type: "textarea", required: true },
  ],
  summarize_entry: [
    { field: "entry_summary_turns", label: "最近保留轮数", type: "number", default: 24, min: 1, max: 200, syncPath: "memory_policy.entry_summary_turns" },
    { field: "compression_strategy", label: "压缩策略", type: "select", default: "smart_extract", syncPath: "memory_policy.compression_strategy",
      options: [["recent_turns","只取最近轮次"],["smart_extract","智能抽取"],["full_preserve","尽量完整保留"]] },
    { field: "compression_max_tokens", label: "最大 token", type: "number", default: 4000, min: 256, max: 200000, syncPath: "memory_policy.compression_max_tokens" },
    { field: "preserve_keywords", label: "必须保留关键词", type: "lines", placeholder: "每行一个关键词", syncPath: "memory_policy.preserve_keywords" },
    { field: "instruction", label: "进入任务时保留哪些上下文？", type: "textarea",
      placeholder: "只保留目标、约束、授权、风险和接续语气。" },
  ],
  confirm_entry: [
    { field: "instruction", label: "开启前要跟用户说明什么？", type: "textarea" },
  ],
  restore_isolation: [
    { field: "_iso", label: "隔离策略在工作流设置里统一配置", type: "note",
      text: "这一步会记录当前会话插件状态并应用任务模式隔离，退出时恢复。" },
  ],
  plugin_prompt: [
    { field: "plugin_name", label: "目标插件", type: "pluginPick", required: true },
    { field: "prompt", label: "给插件/模型的调用提示", type: "textarea", required: true,
      placeholder: "例如：调用表情包插件，根据输入生成一个合适表情并发送。" },
    { field: "impersonate_admin", label: "需要管理员身份执行", type: "checkbox" },
    { field: "admin_user_id", label: "指定管理员/操作者 ID", type: "text" },
  ],
  global_control: [
    { field: "isolation_mode", label: "插件隔离", type: "select", default: "strict",
      options: [["off","不隔离"],["session","会话隔离"],["strict","严格隔离"]] },
    { field: "tool_mode", label: "工具范围", type: "select", default: "whitelist",
      options: [["full","全部工具"],["whitelist","工具白名单"],["no_external","仅内置工具"]] },
    { field: "progress_notice_mode", label: "汇报方式", type: "select", default: "agent_lab",
      options: [["silent","静默"],["agent_lab","控制台记录"],["astrbot","AstrBot 原生提示"]] },
    { field: "show_tool_use", label: "显示工具调用", type: "checkbox" },
    { field: "max_total_tokens", label: "总 token 预算", type: "number", default: 240000, max: 50000000 },
    { field: "max_total_ticks", label: "总 Tick 预算", type: "number", default: 120, max: 100000 },
    { field: "max_tools_per_tick", label: "每轮最多工具调用", type: "number", default: 12, max: 200 },
    { field: "max_seconds_per_tick", label: "每轮最多秒数", type: "number", default: 240, max: 3600 },
    { field: "max_repeated_failures", label: "重复失败阈值", type: "number", default: 3, max: 100 },
  ],
  skill_evolution: [
    { field: "rule_name", label: "Skill 规则名", type: "text", placeholder: "agent-mode" },
    { field: "folder_id", label: "只从哪个记忆夹提炼", type: "folderPick" },
    { field: "tags", label: "只使用哪些记忆标签", type: "lines" },
    { field: "approval_mode", label: "风险模式", type: "select", default: "review",
      options: [["review","生成草稿并审批"],["low","低风险自动应用"],["manual","只生成草稿"]] },
    { field: "include_candidates", label: "允许候选记忆参与", type: "checkbox" },
    { field: "instruction", label: "进化说明", type: "textarea",
      placeholder: "说明要从记忆中提炼哪类稳定经验。" },
  ],
  archive: [
    { field: "instruction", label: "结束时要归档/总结什么？", type: "textarea",
      placeholder: "成果、关键改动、遗留风险、下次续写入口。" },
  ],
  exit_summary: [
    { field: "instruction", label: "退出总结要包含什么？", type: "textarea" },
  ],
  credential_ref: [
    { field: "credential_id", label: "用哪个账号/凭证？", type: "credPick", required: true,
      hint: "在『插件与集成 → 凭证库』里先保存 GitHub 令牌、B站 Cookie 等；这里只引用，不显示密钥。" },
    { field: "provider", label: "用于哪个网站/平台？", type: "text", placeholder: "如：github.com / bilibili.com" },
    { field: "account", label: "账号名（可选）", type: "text", placeholder: "如：你的用户名" },
  ],
  cookie_jar: [
    { field: "credential_id", label: "用哪个已保存的 Cookie？", type: "credPick", required: true },
    { field: "provider", label: "对应站点域名", type: "text", required: true, placeholder: "如：bilibili.com" },
  ],
  browser_profile: [
    { field: "credential_id", label: "用哪个浏览器配置/账号？", type: "credPick" },
    { field: "path", label: "浏览器配置路径或名称", type: "text", placeholder: "供能用浏览器的工具/适配器使用" },
  ],
  login_flow: [
    { field: "provider", label: "登录哪个网站？", type: "text", required: true, placeholder: "如：github.com" },
    { field: "credential_id", label: "用哪个账号/凭证登录？", type: "credPick" },
    { field: "_handoff", label: "需要人工时会暂停", type: "note",
      text: "遇到验证码 / 二次验证 / 风控时，建议连一个『人工登录交接』节点，让你手动完成后再继续。" },
  ],
  session_check: [
    { field: "credential_id", label: "检查哪个账号的登录是否有效？", type: "credPick", required: true },
    { field: "_route", label: "结果分流", type: "note",
      text: "有效走『成功』出口继续；失效走『失败』出口（可连到重新登录或通知你）。" },
  ],
  refresh_session: [
    { field: "credential_id", label: "刷新哪个账号的登录态？", type: "credPick", required: true },
  ],
  credential_scope: [
    { field: "provider", label: "限定只能用于哪个站点/范围？", type: "text", required: true, placeholder: "如：github.com" },
    { field: "credential_id", label: "限定哪个凭证", type: "credPick" },
  ],
  human_login_handoff: [
    { field: "instruction", label: "请用户做什么？", type: "textarea", required: true,
      placeholder: "如：请在弹出的浏览器里完成 B站扫码登录，完成后回复继续。" },
    { field: "provider", label: "哪个网站", type: "text", placeholder: "如：bilibili.com" },
  ],
  revoke_session: [
    { field: "credential_id", label: "用完后注销哪个账号会话？", type: "credPick" },
  ],
  heartbeat: [
    { field: "heartbeat_mode", label: "心跳模式", type: "select", default: "manual", syncPath: "heartbeat_policy.mode",
      options: [["off","关闭"],["manual","手动唤醒"],["auto","按计划自动唤醒"]] },
    { field: "heartbeat_cron", label: "唤醒间隔（cron）", type: "text", syncPath: "heartbeat_policy.cron_expression",
      placeholder: "如：*/15 * * * * 表示每 15 分钟唤醒一次" },
    { field: "heartbeat_max_failures", label: "连续失败上限（失败保护）", type: "number", default: 3, min: 1, max: 100, syncPath: "heartbeat_policy.max_repeated_failures",
      hint: "连续失败达到此次数会停下等人工，避免空转烧预算。" },
    { field: "instruction", label: "心跳醒来后做什么？", type: "textarea",
      placeholder: "如：先读任务状态，再推进一小步，重复阻塞就暂停。" },
    { field: "_hb", label: "心跳让长任务定时自己醒来续跑", type: "note",
      text: "模式选『自动』并填 cron 即可定时唤醒；不需要长任务的工作流可以不放这个节点。这里的设置会写回方案级 heartbeat_policy。" },
  ],
  manual: [
    { field: "prompt", label: "这个节点交给 AI 时的提示词", type: "textarea",
      placeholder: "写清这个自定义节点何时执行、要产出什么、如何写回状态。" },
  ],
};

function workflowSimpleFieldsFor(action) {
  return WORKFLOW_SIMPLE_FIELDS[action] || WORKFLOW_SIMPLE_FIELDS.manual;
}
function workflowSimpleFieldHtml(item, f) {
  // syncPath 字段以 AgentSpec 上的路径为准（如 memory_policy.* / heartbeat_policy.*），否则读节点本身。
  const fieldVal = (ff) => { const v = ff.syncPath ? agentFieldByPath(ff.syncPath) : item[ff.field]; if (Array.isArray(v)) return listToLines(v); return v === undefined || v === null ? "" : String(v); };
  const req = f.required ? ` <em class="req">必填</em>` : "";
  const hint = f.hint ? `<small class="field-hint">${esc(f.hint)}</small>` : "";
  const id = `sf-${esc(f.field)}`;
  if (f.type === "note") return `<div class="simple-note"><b>${esc(f.label)}</b><span>${esc(f.text || "")}</span></div>`;
  if (f.type === "lines") return `<label class="simple-field">${esc(f.label)}${req}<textarea id="${id}" rows="3" placeholder="${esc(f.placeholder || "")}">${esc(fieldVal(f))}</textarea>${hint}</label>`;
  if (f.type === "textarea") return `<label class="simple-field">${esc(f.label)}${req}<textarea id="${id}" rows="4" placeholder="${esc(f.placeholder || "")}">${esc(fieldVal(f))}</textarea>${hint}</label>`;
  if (f.type === "number") { const cur = fieldVal(f) || (f.default ?? ""); return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" type="number" min="${esc(f.min ?? 0)}" max="${esc(f.max ?? 1000000)}" value="${esc(cur)}" />${hint}</label>`; }
  if (f.type === "checkbox") { const checked = f.syncPath ? agentFieldByPath(f.syncPath) === true : item[f.field] === true; return `<label class="check-line simple-field"><input id="${id}" type="checkbox" ${checked ? "checked" : ""} />${esc(f.label)}${req}${hint}</label>`; }
  if (f.type === "select") { const cur = fieldVal(f) || f.default || (f.options?.[0]?.[0] ?? ""); const opts = (f.options || []).map(([v,l]) => `<option value="${esc(v)}" ${v === cur ? "selected" : ""}>${esc(l)}</option>`).join(""); return `<label class="simple-field">${esc(f.label)}${req}<select id="${id}">${opts}</select>${hint}</label>`; }
  if (f.type === "color") { const cur = fieldVal(f) || f.default || "#5b8def"; return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" type="color" value="${esc(cur)}" />${hint}</label>`; }
  if (f.type === "toolPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-tool-list" value="${esc(fieldVal(f))}" placeholder="选择 AstrBot 工具" />${hint}</label>`;
  if (f.type === "apiPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-api-list" value="${esc(fieldVal(f))}" placeholder="选择已注册 API" />${hint}</label>`;
  if (f.type === "credPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-cred-list" value="${esc(fieldVal(f))}" placeholder="选择已保存的账号/凭证" />${hint}</label>`;
  if (f.type === "pluginPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-plugin-list" value="${esc(fieldVal(f))}" placeholder="选择已启用插件" />${hint}</label>`;
  if (f.type === "folderPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-folder-list" value="${esc(fieldVal(f))}" placeholder="选择记忆夹 ID" />${hint}</label>`;
  if (f.type === "subAgentPick") return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" list="workflow-subagent-list" value="${esc(fieldVal(f))}" placeholder="选择子Agent（名称或ID）" />${hint}</label>`;
  return `<label class="simple-field">${esc(f.label)}${req}<input id="${id}" value="${esc(fieldVal(f))}" placeholder="${esc(f.placeholder || "")}" />${hint}</label>`;
}
function workflowSimpleEditor(item) {
  const action = item.action || "manual";
  const fields = workflowSimpleFieldsFor(action);
  const rows = fields.map((f) => workflowSimpleFieldHtml(item, f)).join("");
  return `
    <section class="workflow-editor-section simple-editor">
      <label class="simple-field">节点名称<input id="workflow-node-title" value="${esc(item.title || "")}" placeholder="给这个节点起个好认的名字" /></label>
      <p class="simple-editor-lead">${esc(workflowActionLabel(action))} · 只需填下面几项，连线在画布上拖。</p>
      ${rows}
      <datalist id="workflow-tool-list">${workflowDatalistOptions(state.tools || [], "name", "description")}</datalist>
      <datalist id="workflow-api-list">${workflowDatalistOptions(state.custom_apis || [], "api_id", "name")}</datalist>
      <datalist id="workflow-cred-list">${workflowDatalistOptions(state.credentials || [], "credential_id", "name")}</datalist>
      <datalist id="workflow-plugin-list">${workflowDatalistOptions(state.plugins || [], "name", "display_name")}</datalist>
      <datalist id="workflow-folder-list">${workflowDatalistOptions(state.memory_folders || [], "folder_id", "name")}</datalist>
      <datalist id="workflow-subagent-list">${workflowDatalistOptions((currentAgent && currentAgent.sub_agents) || [], "sub_agent_id", "name")}</datalist>
    </section>
  `;
}
// 把 simple-field 的值同步到 AgentSpec 上的指定路径（确认开关并入监听入口后仍写回 entry_policy，保持后端校验一致）。
function agentFieldByPath(path) {
  if (!currentAgent || !path) return undefined;
  return String(path).split(".").reduce((obj, key) => (obj == null ? undefined : obj[key]), currentAgent);
}
function setAgentFieldByPath(path, value) {
  if (!currentAgent || !path) return;
  const keys = String(path).split(".");
  let obj = currentAgent;
  for (let i = 0; i < keys.length - 1; i++) {
    if (obj[keys[i]] == null || typeof obj[keys[i]] !== "object") obj[keys[i]] = {};
    obj = obj[keys[i]];
  }
  obj[keys[keys.length - 1]] = value;
}
// 简易模式保存：把 sf-* 字段写回节点，只动该 action 暴露的字段；带 syncPath 的字段同时写回 AgentSpec 路径。
function applySimpleEditorFields(node) {
  const fields = workflowSimpleFieldsFor(node.action || "manual");
  for (const f of fields) {
    if (f.type === "note") continue;
    const el = document.getElementById(`sf-${f.field}`);
    if (!el) continue;
    const raw = el.value;
    if (f.type === "lines") {
      const arr = linesToList(raw || "");
      if (arr.length) node[f.field] = arr; else delete node[f.field];
      if (f.syncPath) setAgentFieldByPath(f.syncPath, arr);
    } else if (f.type === "number") {
      const hasVal = String(raw || "").trim() !== "";
      const n = Number(raw || 0);
      if (Number.isFinite(n) && hasVal) node[f.field] = Math.max(0, Math.round(n)); else delete node[f.field];
      if (f.syncPath && hasVal && Number.isFinite(n)) setAgentFieldByPath(f.syncPath, Math.max(0, Math.round(n)));
    } else if (f.type === "checkbox") {
      node[f.field] = Boolean(el.checked);
      if (f.syncPath) setAgentFieldByPath(f.syncPath, Boolean(el.checked));
    } else {
      const t = String(raw || "").trim();
      if (t) node[f.field] = t; else delete node[f.field];
      if (f.syncPath) setAgentFieldByPath(f.syncPath, t);
    }
  }
  // 消息监听入口：由填写项自动推导触发类型，不再让用户单独勾选（去重）。
  if ((node.action || "") === "listen_message") deriveListenTriggerTypes(node);
}

// 根据消息监听入口节点填写的内容推导 workflow_trigger 类型集合，并写回节点与 agent。
function deriveListenTriggerTypes(node) {
  const has = (k) => Array.isArray(node[k]) && node[k].length > 0;
  const t = new Set();
  if ((node.monitor_scope || "mentioned") === "global") t.add("message_monitor");
  else { t.add("command"); t.add("natural"); }
  if (has("command_names")) t.add("command");
  if (has("keywords")) t.add("keyword");
  if (has("regex")) t.add("regex");
  if (!t.size) t.add("command");
  node.trigger_types = Array.from(t);
  if (currentAgent) {
    currentAgent.workflow_trigger ||= {};
    currentAgent.workflow_trigger.enabled = true;
    currentAgent.workflow_trigger.types = Array.from(t);
    currentAgent.workflow_trigger.command_names = Array.isArray(node.command_names) ? node.command_names.slice() : [];
    currentAgent.workflow_trigger.keywords = Array.isArray(node.keywords) ? node.keywords.slice() : [];
    currentAgent.workflow_trigger.regex = Array.isArray(node.regex) ? node.regex.slice() : [];
  }
}

function workflowInspectorAdvanced(item) {
  const refValue = item.ref_id || item.api_id || item.tool_name || item.plugin_name || item.skill_name || "";
  const tagsValue = Array.isArray(item.tags) ? item.tags.join(", ") : item.tags || item.memory_tags || "";
  const action = item.action || "manual";
  return `
      <section class="workflow-editor-section">
        <h4>基础</h4>
        <label>节点标识<input id="workflow-node-id" value="${esc(item.id)}" /></label>
        <label>节点名称<input id="workflow-node-title" value="${esc(item.title)}" /></label>
        <div class="form-grid compact">
          <label>阶段<select id="workflow-node-stage">${labeledOptions(WORKFLOW_STAGES.map(([id]) => id), item.stage || "plan", workflowStageLabel)}</select></label>
          <label>类型<select id="workflow-node-kind">${labeledOptions(WORKFLOW_KINDS, item.kind || "state", workflowKindLabel)}</select></label>
          <label>动作<select id="workflow-node-action">${labeledOptions(WORKFLOW_ACTIONS, action, workflowActionLabel)}</select></label>
          <label>权限<select id="workflow-node-permission-profile">${labeledOptions(WORKFLOW_PERMISSION_PROFILES, item.permission_profile || item.profile || "work", workflowPermissionLabel)}</select></label>
        </div>
      </section>

      <section class="workflow-editor-section">
        <h4>能力绑定</h4>
        <div class="form-grid compact">
          <label>引用类型<select id="workflow-node-ref-type">${labeledOptions(WORKFLOW_REF_TYPES, item.ref_type || "", workflowRefTypeLabel)}</select></label>
          <label>引用 ID<input id="workflow-node-ref-id" list="workflow-ref-list" value="${esc(refValue)}" placeholder="工具名、API ID、插件名或 Skill 名" /></label>
          <label>AstrBot 工具<input id="workflow-node-tool-name" list="workflow-tool-list" value="${esc(item.tool_name || "")}" /></label>
          <label>自定义 API<input id="workflow-node-api-id" list="workflow-api-list" value="${esc(item.api_id || "")}" /></label>
          <label>插件名<input id="workflow-node-plugin-name" list="workflow-plugin-list" value="${esc(item.plugin_name || "")}" /></label>
          <label>Skill 名<input id="workflow-node-skill-name" list="workflow-skill-list" value="${esc(item.skill_name || "")}" /></label>
        </div>
        <datalist id="workflow-ref-list">
          ${workflowDatalistOptions(state.tools || [], "name", "description")}
          ${workflowDatalistOptions(state.custom_apis || [], "api_id", "name")}
          ${workflowDatalistOptions(state.plugins || [], "name", "display_name")}
          ${workflowDatalistOptions(state.skills || [], "name", "path")}
        </datalist>
        <datalist id="workflow-tool-list">${workflowDatalistOptions(state.tools || [], "name", "description")}</datalist>
        <datalist id="workflow-api-list">${workflowDatalistOptions(state.custom_apis || [], "api_id", "name")}</datalist>
        <datalist id="workflow-plugin-list">${workflowDatalistOptions(state.plugins || [], "name", "display_name")}</datalist>
        <datalist id="workflow-skill-list">${workflowDatalistOptions(state.skills || [], "name", "path")}</datalist>
        ${(item.ref_type || refValue) ? `
          <div class="workflow-ref-line">
            <span>${esc(item.ref_type || "module")}</span>
            <b>${esc(refValue)}</b>
          </div>
        ` : ""}
      </section>

      <section class="workflow-editor-section">
        <h4>数据流</h4>
        <div class="form-grid compact">
          <label>输入变量<input id="workflow-node-input-variable" value="${esc(item.input_variable || "")}" placeholder="variables.memory 或 tool.result" /></label>
          <label>输出变量<input id="workflow-node-output-variable" value="${esc(item.output_variable || "")}" placeholder="api.search.result" /></label>
          <label>必需输入<textarea id="workflow-node-required-inputs" rows="3" placeholder="每行一个变量路径">${esc(listToLines(item.required_inputs || []))}</textarea></label>
          <label>额外输出<textarea id="workflow-node-output-variables" rows="3" placeholder="每行一个变量名">${esc(listToLines(item.output_variables || []))}</textarea></label>
        </div>
        <label>参数 JSON<textarea id="workflow-node-params" rows="5" placeholder='{"query":{"q":"{{task.root_goal}}"}}'>${esc(workflowNodeParamsJson(item))}</textarea></label>
        <div class="form-grid compact">
          <label>输入 Schema<textarea id="workflow-node-input-schema" rows="5" placeholder='{"type":"object"}'>${esc(workflowObjectJson(item.input_schema))}</textarea></label>
          <label>输出 Schema<textarea id="workflow-node-output-schema" rows="5" placeholder='{"type":"object"}'>${esc(workflowObjectJson(item.output_schema))}</textarea></label>
        </div>
      </section>

      <section class="workflow-editor-section">
        <h4>路由与执行</h4>
        <div class="form-grid compact">
          <label>分支条件<input id="workflow-node-condition" value="${esc(item.condition || "")}" /></label>
          <label>路由变量<input id="workflow-node-route-variable" value="${esc(item.route_variable || "")}" /></label>
          <label>并行分组<input id="workflow-node-parallel-group" value="${esc(item.parallel_group || "")}" /></label>
          <label>Worker 类型<select id="workflow-node-worker-type">${labeledOptions(WORKFLOW_WORKER_TYPES, item.worker_type || item.role || "", workflowWorkerTypeLabel)}</select></label>
          <label>超时秒数<input id="workflow-node-timeout-seconds" type="number" min="0" max="600" value="${esc(item.timeout_seconds || "")}" /></label>
          <label>最大重试<input id="workflow-node-max-retries" type="number" min="0" max="8" value="${esc(item.max_retries || "")}" /></label>
        </div>
        <div class="form-grid compact">
          <label>变量名<input id="workflow-node-variable-name" value="${esc(item.variable_name || item.variable || "")}" placeholder="variable_set / variable_get" /></label>
          <label>模板 ID<input id="workflow-node-template-id" value="${esc(item.template_id || "")}" placeholder="subflow_call" /></label>
          <label>文件路径<input id="workflow-node-path" value="${esc(item.path || "")}" /></label>
          <label>URL<input id="workflow-node-url" value="${esc(item.url || "")}" /></label>
          <label>HTTP 方法<select id="workflow-node-method">${labeledOptions(["", "GET", "POST", "PUT", "PATCH", "DELETE"], item.method || "", (value) => value || "默认")}</select></label>
          <label>文件操作<select id="workflow-node-operation">${labeledOptions(["", "read", "write", "replace", "append"], item.operation || item.edit_mode || "", (value) => value || "默认")}</select></label>
          <label>代码语言<select id="workflow-node-language">${labeledOptions(["", "python", "shell", "powershell"], item.language || "", (value) => value || "默认")}</select></label>
          <label>记忆标签<input id="workflow-node-tags" value="${esc(tagsValue)}" /></label>
        </div>
        <label>重试策略 JSON<textarea id="workflow-node-retry-policy" rows="4" placeholder='{"max_attempts":2,"backoff":"linear"}'>${esc(workflowObjectJson(item.retry_policy))}</textarea></label>
      </section>

      <section class="workflow-editor-section">
        <h4>说明</h4>
        <label>一句话说明<input id="workflow-node-description" value="${esc(item.description || "")}" /></label>
        <label>执行说明<textarea id="workflow-node-instruction" rows="5">${esc(item.instruction || "")}</textarea></label>
        <label>模型兜底提示<textarea id="workflow-node-prompt" rows="5">${esc(item.prompt || "")}</textarea></label>
      </section>

  `;
}

// 节点编辑器分发：简易(填空) / 高级。两种模式共享头部、入口/出口规则和按钮。
function workflowInspector() {
  const item = selectedWorkflowNode();
  if (!item) return `<div class="empty">暂无节点。</div>`;
  const runtime = workflowNodeRuntimeInfo(item);
  const executorState = workflowNodeExecutorState(item);
  const bindingHint = workflowNodeBindingHint(item);
  const stage = workflowStage(item);
  const isListenNode = item.action === "listen_message";
  const isScopeNode = item.action === "scope_filter";
  // 消息监听入口=配置“入口规则/暗号/关键词”；范围过滤器=配置“生效范围/黑白名单”。
  const isDedicatedTrigger = ["schedule_trigger", "plugin_event_trigger", "webhook_trigger"].includes(item.action);
  const isEntryNode = isListenNode || ["summarize_entry", "confirm_entry"].includes(item.action) || (stage === "entry" && !isScopeNode && !isDedicatedTrigger);
  const isExitNode = stage === "archive" || ["archive", "exit_summary"].includes(item.action);
  const isApprovalNode = item.action === "request_approval";
  const mode = workflowEditorMode === "advanced" ? "advanced" : "simple";
  const body = mode === "advanced" ? workflowInspectorAdvanced(item) : workflowSimpleEditor(item);
  const ep = currentAgent.entry_policy || {};
  const sc = currentAgent.workflow_scope || {};
  const ap = currentAgent.approval_policy || {};
  const scopeRule = isScopeNode ? `
    <div class="workflow-node-rule-box">
      <div class="panel-head"><div><p class="card-kicker">生效范围</p><h3>这条入口在哪里生效（可分流）</h3></div></div>
      <label class="check-line"><input type="checkbox" id="scope-global" ${currentAgent.application_scope === "global" ? "checked" : ""} /> 全局应用（所有会话都参与，不只入口命中时）</label>
      <label>生效会话类型<div class="choice-grid compact-choice">${checkboxGroupHtml("scope-chat-type", WORKFLOW_CHAT_TYPES, sc.chat_types || ["private"], workflowChatTypeLabel)}</div></label>
      <label class="check-line"><input type="checkbox" id="scope-admin-only" ${sc.admin_only === true ? "checked" : ""} /> 仅管理员可触发</label>
      <div class="form-grid compact">
        <label>群聊白名单（每行一个群号）<textarea id="scope-group-allow" rows="2" placeholder="留空＝不限">${esc(listToLines(sc.group_allowlist || []))}</textarea></label>
        <label>群聊黑名单<textarea id="scope-group-deny" rows="2">${esc(listToLines(sc.group_denylist || []))}</textarea></label>
        <label>用户白名单（每行一个）<textarea id="scope-user-allow" rows="2" placeholder="留空＝不限">${esc(listToLines(sc.user_allowlist || []))}</textarea></label>
        <label>用户黑名单<textarea id="scope-user-deny" rows="2">${esc(listToLines(sc.user_denylist || []))}</textarea></label>
      </div>
      <small class="field-hint">不同入口节点可设不同范围：让一部分人走这条路、另一部分人走另一条。</small>
    </div>` : "";
  const entryRule = ""; // 触发条件已内聚到「消息监听入口」节点字段，去除统一盒子（去重）。
  const exitRule = isExitNode ? `
    <div class="workflow-node-rule-box">
      <div class="panel-head"><div><p class="card-kicker">出口规则</p><h3>怎么结束、怎么验收</h3></div></div>
      <label>结束暗号 / 命令<textarea id="workflow-exit-phrases" rows="3" placeholder="每行一个，例如：完成任务">${esc(listToLines(ep.exit_phrases))}</textarea></label>
      <label>默认验收条件<textarea id="workflow-default-completion-conditions" rows="3">${esc(listToLines(ep.default_completion_conditions))}</textarea></label>
    </div>` : "";
  const approvalRule = isApprovalNode ? `
    <div class="workflow-node-rule-box">
      <div class="panel-head"><div><p class="card-kicker">审批准则</p><h3>这个审批节点怎么放行</h3></div></div>
      <label>审批力度<select id="wf-approval-mode">${labeledOptions(["observe", "work", "high_risk_review", "delegated"], ap.mode || "work", approvalModeLabel)}</select></label>
      <label>必须先审批的动作（每行一个）<textarea id="wf-approval-require" rows="4" placeholder="file_delete&#10;deployment&#10;secret_read">${esc(listToLines(ap.require_approval || []))}</textarea></label>
      <label>已预授权、无需每次确认（每行一个）<textarea id="wf-approval-preapproved" rows="3" placeholder="read_only&#10;list_files">${esc(listToLines(ap.preapproved_scopes || []))}</textarea></label>
    </div>` : "";
  const idField = mode === "simple" ? `<input type="hidden" id="workflow-node-id" value="${esc(item.id)}" />` : "";
  return `
    <div class="detail-box workflow-editor">
      <div class="panel-head">
        <div><p class="card-kicker">节点协议</p><h3>编辑节点</h3></div>
        <div class="editor-mode-switch">
          <button class="mode-tab ${mode === "simple" ? "active" : ""}" data-action="workflow-editor-mode" data-id="simple" type="button">填空</button>
          <button class="mode-tab ${mode === "advanced" ? "active" : ""}" data-action="workflow-editor-mode" data-id="advanced" type="button">高级</button>
        </div>
      </div>
      <div class="workflow-editor-runtime">
        <span class="runtime-badge ${esc(executorState.tone)}">${esc(executorState.label)}</span>
        <span>${esc(WORKFLOW_RUNTIME_LABELS[runtime.runtime_type] || runtime.runtime_type || "ReAct")}节点</span>
        <small>${esc(executorState.hint || bindingHint || "保存方案后由任务运行时读取。")}</small>
      </div>
      ${idField}
      ${body}
      ${scopeRule}
      ${entryRule}
      ${exitRule}
      ${approvalRule}
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
        <label>出口类型<select id="workflow-edge-type">${labeledOptions(WORKFLOW_EDGE_TYPES, "success", workflowEdgeTypeLabel)}</select></label>
        <label>起点<select id="workflow-edge-from">${workflowNodeOptions(selectedWorkflowNodeId)}</select></label>
        <label>终点<select id="workflow-edge-to">${workflowNodeOptions(currentAgent.workflow_nodes[1]?.id || selectedWorkflowNodeId)}</select></label>
      </div>
      <div class="button-row"><button class="button secondary" data-action="add-workflow-edge" type="button">新增连线</button></div>
      <div class="edge-list">
        ${(currentAgent.workflow_edges || []).map((edge, index) => `
          <div class="edge-row">
            <small>${esc(workflowEdgeTypeLabel(edge.edge_type || "success"))}</small>
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

function readWorkflowJsonDraft() {
  const workflowJson = $("workflow-json");
  if (!workflowJson || workflowJson.value.trim() === (workflowJson.dataset.original || "").trim()) return;
  const workflow = JSON.parse(workflowJson.value || "{}");
  currentAgent.workflow_nodes = Array.isArray(workflow.nodes) ? workflow.nodes : currentAgent.workflow_nodes;
  currentAgent.workflow_edges = Array.isArray(workflow.edges) ? workflow.edges : currentAgent.workflow_edges;
  ensureWorkflow();
}

function readAgentForm() {
  if (!$("agent-name")) {
    readWorkflowJsonDraft();
    return;
  }
  const typedName = $("agent-name").value.trim();
  currentAgent.name = typedName;
  if (!typedName || (isAutoIdentitySource(currentAgent.identity_label_source) && typedName === runtimeAgentName())) {
    currentAgent.identity_label_source = "astrbot_runtime";
  } else if (isAutoIdentitySource(currentAgent.identity_label_source)) {
    currentAgent.identity_label_source = "manual";
  }
  if ($("provider-id")) currentAgent.provider_id = $("provider-id").value.trim();
  if ($("agent-enabled")) currentAgent.enabled = $("agent-enabled").value === "true";
  currentAgent.application_scope = ["entry", "global"].includes(currentAgent.application_scope) ? currentAgent.application_scope : "entry";
  currentAgent.entry_channel = ["command", "natural", "webui"].includes(currentAgent.entry_channel) ? currentAgent.entry_channel : "command";
  if ($("trigger-mode")) currentAgent.trigger_mode = $("trigger-mode").value;
  if ($("workflow-trigger-enabled")) {
    currentAgent.workflow_trigger = {
      enabled: $("workflow-trigger-enabled").value === "true",
      types: checkedValues("workflow-trigger-type"),
      command_names: linesToList($("workflow-trigger-commands")?.value || ""),
      keywords: linesToList($("workflow-trigger-keywords")?.value || ""),
      regex: linesToList($("workflow-trigger-regex")?.value || ""),
      cron: $("workflow-trigger-cron")?.value.trim() || "",
      plugin_events: linesToList($("workflow-trigger-plugin-events")?.value || ""),
      webhook_path: $("workflow-trigger-webhook")?.value.trim() || "",
      description: $("workflow-trigger-description")?.value.trim() || "",
    };
    if (!currentAgent.workflow_trigger.types.length) currentAgent.workflow_trigger.types = ["command"];
  }
  if ($("workflow-scope-admin-only")) {
    currentAgent.workflow_scope = {
      chat_types: checkedValues("workflow-chat-type"),
      platforms: linesToList($("workflow-scope-platforms")?.value || ""),
      umo_allowlist: linesToList($("workflow-scope-umo-allow")?.value || ""),
      umo_denylist: linesToList($("workflow-scope-umo-deny")?.value || ""),
      group_allowlist: linesToList($("workflow-scope-group-allow")?.value || ""),
      group_denylist: linesToList($("workflow-scope-group-deny")?.value || ""),
      user_allowlist: linesToList($("workflow-scope-user-allow")?.value || ""),
      user_denylist: linesToList($("workflow-scope-user-deny")?.value || ""),
      admin_only: $("workflow-scope-admin-only").value === "true",
    };
    if (!currentAgent.workflow_scope.chat_types.length) currentAgent.workflow_scope.chat_types = ["private"];
  }
  if ($("entry-trigger-phrases")) currentAgent.entry_policy.trigger_phrases = linesToList($("entry-trigger-phrases").value);
  if ($("entry-trigger-keywords")) currentAgent.entry_policy.trigger_keywords = linesToList($("entry-trigger-keywords").value);
  if ($("entry-require-confirmation")) currentAgent.entry_policy.require_confirmation = $("entry-require-confirmation").value === "true";
  if ($("entry-confirmation-text")) currentAgent.entry_policy.confirmation_text = $("entry-confirmation-text").value.trim();
  if ($("default-completion-conditions")) currentAgent.entry_policy.default_completion_conditions = linesToList($("default-completion-conditions").value);
  if ($("exit-phrases")) currentAgent.entry_policy.exit_phrases = linesToList($("exit-phrases").value);
  if ($("isolation-mode")) currentAgent.isolation_policy.mode = $("isolation-mode").value;
  if ($("tool-mode")) currentAgent.isolation_policy.tool_mode = $("tool-mode").value;
  if ($("restore-on-exit")) currentAgent.isolation_policy.restore_on_exit = $("restore-on-exit").value === "true";
  if ($("isolation-notes")) currentAgent.isolation_policy.notes = $("isolation-notes").value.trim();
  if ($("memory-mode")) currentAgent.memory_policy.mode = $("memory-mode").value;
  if ($("entry-summary-turns")) currentAgent.memory_policy.entry_summary_turns = Number($("entry-summary-turns").value || 24);
  if ($("approval-mode")) currentAgent.approval_policy.mode = $("approval-mode").value;
  if ($("heartbeat-mode")) currentAgent.heartbeat_policy.mode = $("heartbeat-mode").value;
  if ($("heartbeat-allowed")) currentAgent.heartbeat_policy.allowed = $("heartbeat-allowed").value === "true";
  if ($("heartbeat-cron")) currentAgent.heartbeat_policy.cron_expression = $("heartbeat-cron").value.trim() || "*/5 * * * *";
  if ($("system-prompt")) currentAgent.system_prompt = $("system-prompt").value;
  if ($("task-prompt")) currentAgent.task_prompt = $("task-prompt").value;
  readWorkflowJsonDraft();
}

function renderTasks() {
  currentAgent = ensureAgent(currentAgent || {});
  const task = selectedTask();
  const runnableTask = activeTask();
  const liveTask = runnableTask || (state.tasks || [])[0] || null;
  const activeRows = state.tasks || [];
  const archivedRows = state.archives || [];
  $("view").innerHTML = `
    <section class="console-page">
      <aside class="console-sidebar">
        <div class="console-tabs">
          <button class="tab active" type="button">活跃 ${activeRows.length}</button>
          <button class="tab" type="button">归档 ${archivedRows.length}</button>
        </div>
        <div class="task-list">
          <p class="card-kicker">活跃任务</p>
          ${taskConsoleRows(activeRows)}
          <p class="card-kicker console-archive-title">归档任务</p>
          ${taskConsoleRows(archivedRows.slice(0, 18), true)}
        </div>
      </aside>

      <main class="console-main">
        <section class="panel task-entry-panel">
          <div class="panel-head">
            <div><p class="card-kicker">入口</p><h2>进入任务模式</h2></div>
            <div class="inline-actions">
              <button class="button secondary" data-route="workflow" type="button">画布</button>
              <button class="button secondary" data-route="memory" type="button">记忆</button>
            </div>
          </div>
          <div class="form-grid task-entry-grid">
            <label>会话 UMO<input id="umo" placeholder="aiocqhttp:FriendMessage:123456" /></label>
            <label>风险级别<select id="task-risk-level">${labeledOptions(["low", "work", "high"], "work", (value) => ({ low: "低风险", work: "工作风险", high: "高风险" }[value] || value))}</select></label>
            <label class="span-2">任务目标<textarea id="goal" rows="2">请把当前任务作为任务模式管理起来。</textarea></label>
            <label class="span-2">完成条件<input id="completion" value="${esc((currentAgent.entry_policy.default_completion_conditions || ["用户验收通过"]).join("；"))}" /></label>
            <label class="span-2">入口补充<textarea id="brief" rows="2"></textarea></label>
            <label class="check-line span-2"><input id="task-start-heartbeat" type="checkbox" />进入后立即开心跳</label>
          </div>
          ${taskPatternSuggestions()}
          <div class="button-row">
            <button class="button" data-action="start-task" type="button">进入任务模式</button>
            <button class="button secondary" data-action="simulate-trigger" type="button">模拟触发</button>
          </div>
        </section>

        ${liveConsolePanel(liveTask, Boolean(runnableTask))}

        <section class="panel">
          <div class="panel-head">
            <div><p class="card-kicker">任务详情</p><h2>${task ? esc(task.root_goal || task.task_id) : "请选择或创建任务"}</h2></div>
            <div class="inline-actions">
              <button class="button secondary" data-action="tick-task" ${runnableTask ? "" : "disabled"} type="button">Tick</button>
              <button class="button secondary" data-action="toggle-heartbeat" ${runnableTask ? "" : "disabled"} type="button">${runnableTask?.heartbeat?.enabled ? "关闭心跳" : "开启心跳"}</button>
              <button class="button secondary" data-action="finish-task" ${runnableTask ? "" : "disabled"} type="button">完成</button>
              <button class="button danger" data-action="cancel-task" ${runnableTask ? "" : "disabled"} type="button">取消</button>
            </div>
          </div>
          ${task ? taskDetail(task) : `<div class="empty">请选择或创建任务。</div>`}
        </section>

        <section class="panel">
          <div class="panel-head"><div><p class="card-kicker">出口回流</p><h2>任务记忆候选</h2></div></div>
          <label>新增/修剪长期记忆<textarea id="memory-text" rows="4" placeholder="只保存稳定事实、项目约定或后续任务需要复用的要点。"></textarea></label>
          <div class="form-grid compact">
            <label>记忆标签<input id="memory-tags" placeholder="任务, 插件, 续写" /></label>
            <label>初始状态<select id="memory-status">${labeledOptions(["candidate", "accepted"], "candidate", memoryFilterLabel)}</select></label>
            <label>记忆夹<select id="memory-folder">${memoryFolderOptions(preferredMemoryFolderId())}</select></label>
            <label>归属 Agent<input id="memory-agent" value="${esc(currentAgent.agent_id || task?.agent_id || "")}" placeholder="留空表示通用" /></label>
            <label class="span-2">普通模式可读<select id="memory-expose">${labeledOptions(["true", "false"], "true", (value) => value === "true" ? "允许普通模式读取" : "仅任务模式读取")}</select></label>
          </div>
          <div class="button-row"><button class="button secondary" data-action="save-memory" type="button">保存记忆条目</button></div>
          <div class="list">${memoryRows()}</div>
        </section>
      </main>
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
        <span>消耗 ${formatTokens(task.token_usage?.total || 0)}</span>
        <span>审批 ${pendingApprovals.length}</span>
      </div>
    </div>
    <div class="state-fields">
      ${stateField("当前摘要", task.current_summary)}
      ${stateField("已确认进度", task.last_confirmed_progress)}
      ${stateField("下一步", task.next_step)}
      ${stateField("最近观察", task.last_observation)}
    </div>
    ${taskBudgetDetail(task)}
    ${taskWorkflowDetail(task)}
    ${taskParallelRunsDetail(task)}
    ${taskRuntimeTraceDetail(task)}
    <div class="panel-head"><div><p class="card-kicker">审批</p><h3>待审批</h3></div></div>
    <div class="list">${approvalRows(pendingApprovals)}</div>
    <div class="panel-head"><div><p class="card-kicker">记录</p><h3>状态变化时间线</h3></div></div>
    <div class="list">${snapshotRows(task.state_snapshots || [])}</div>
    <div class="panel-head"><div><p class="card-kicker">日志</p><h3>任务日志</h3></div></div>
    <div class="button-row"><button class="button secondary" data-action="load-task-logs" data-task-id="${esc(task.task_id)}" type="button">加载日志</button></div>
    <div id="task-logs-container" class="log-content" style="max-height: 400px; overflow-y: auto; display: none;"></div>
  `;
}

function taskBudgetDetail(task) {
  const budget = task.budget || {};
  const maxTokens = budget.max_total_tokens;
  const maxTicks = budget.max_total_ticks;
  const maxToolsPerTick = budget.max_tools_per_tick;
  const maxSecondsPerTick = budget.max_seconds_per_tick;
  const tokenCount = budget.tokens_used || taskTokenTotal(task);
  const tickCount = budget.ticks_used || 0;
  const toolCalls = budget.tool_calls_used || 0;
  const repeatedCounts = task.repeated_issue_counts || task.watchdog?.repeated_issue_counts || {};
  const maxRepeatedFailures = task.heartbeat?.max_repeated_failures || task.profile_snapshot?.agent?.heartbeat_policy?.max_repeated_failures || "";
  if (!maxTokens && !maxTicks && !maxToolsPerTick && !maxSecondsPerTick && !maxRepeatedFailures) return "";
  const progress = (current, max) => max ? `${current} / ${max}` : `${current}`;
  const percentage = (current, max) => max ? Math.min(100, (current / max) * 100).toFixed(0) : 0;
  return `
    <div class="detail-box workflow-runtime-card">
      <div class="panel-head"><div><p class="card-kicker">预算与限制</p><h3>资源使用情况</h3></div></div>
      <div class="mini-stats">
        ${maxTokens ? `<span>Token ${progress(tokenCount, maxTokens)}</span>` : ""}
        ${maxTicks ? `<span>Tick ${progress(tickCount, maxTicks)}</span>` : ""}
        ${maxToolsPerTick ? `<span>工具/tick ≤${maxToolsPerTick}</span>` : ""}
        ${maxSecondsPerTick ? `<span>秒/tick ≤${maxSecondsPerTick}</span>` : ""}
        ${budget.max_total_tool_calls ? `<span>工具总量 ${progress(toolCalls, budget.max_total_tool_calls)}</span>` : ""}
        ${maxRepeatedFailures ? `<span>重复失败 ≤${maxRepeatedFailures}</span>` : ""}
      </div>
      ${maxTokens || maxTicks ? `
        <div class="edge-list">
          ${maxTokens ? `<div class="edge-row"><span>Token 使用</span><div class="progress-bar"><div class="progress-fill" style="width:${percentage(tokenCount, maxTokens)}%"></div></div></div>` : ""}
          ${maxTicks ? `<div class="edge-row"><span>Tick 使用</span><div class="progress-bar"><div class="progress-fill" style="width:${percentage(tickCount, maxTicks)}%"></div></div></div>` : ""}
        </div>
      ` : ""}
      ${maxRepeatedFailures && Object.keys(repeatedCounts).length ? `
        <div class="workflow-events">
          <div class="log-row">
            <span>重复失败</span>
            <strong>上限 ${maxRepeatedFailures}</strong>
            <p>${Object.entries(repeatedCounts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</p>
          </div>
        </div>
      ` : ""}
    </div>
  `;
}


function taskRuntimeTraceDetail(task) {
  const rt = task.agent_runtime || task.runtime_trace || {};
  const catalog = rt.capability_catalog || [];
  const plan = rt.task_plan || [];
  const decisions = rt.decisions || [];
  const observations = rt.observations || [];
  const verdicts = rt.verdicts || [];
  const resume = rt.resume || [];
  const patterns = rt.pattern_recommendations || [];
  const hasData = catalog.length || plan.length || decisions.length || observations.length || verdicts.length || resume.length || patterns.length;
  if (!hasData) return "";
  return `
    <div class="detail-box workflow-runtime-card">
      <div class="panel-head"><div><p class="card-kicker">运行轨迹</p><h3>Agent Runtime 审计</h3></div></div>
      ${traceSection("能力目录", catalog)}
      ${traceSection("任务计划", plan)}
      ${traceSection("决策记录", decisions)}
      ${traceSection("观察记录", observations)}
      ${traceSection("判定结果", verdicts)}
      ${traceSection("恢复信息", resume)}
      ${traceSection("模式推荐", patterns)}
    </div>
  `;
}

function traceSection(title, items) {
  if (!items.length) return "";
  return `
    <details class="trace-section">
      <summary>${esc(title)} (${items.length})</summary>
      <div class="workflow-events">
        ${items.map((item) => `
          <div class="log-row">
            <span>${esc(item.timestamp || item.time || "")}</span>
            <strong>${esc(item.summary || item.title || item.content || "-")}</strong>
            <p>${esc(item.details || item.description || item.note || "")}</p>
          </div>
        `).join("")}
      </div>
    </details>
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
      <div class="row-meta">${esc(item.memory_id)} · 夹：${esc(item.folder_name || memoryFolderLabel(item.folder_id))} · Agent：${esc(item.agent_id || "-")} · 来源任务：${esc(item.source_task_id || "-")} · 标签：${esc((item.tags || []).join(", ") || "-")} · ${item.expose_to_normal === false ? "仅任务模式" : "普通模式可读"}</div>
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

function taskLogLineRows(rows) {
  const safeRows = (rows || []).filter((item) => item !== null && item !== undefined);
  if (!safeRows.length) return `<div class="empty">暂无日志。</div>`;
  return safeRows.slice(-120).reverse().map((item) => `
    <div class="log-row">
      <span>${esc(item.time || item.timestamp || item.created_at || "")}</span>
      <strong>${esc(item.kind || item.level || item.type || "log")}</strong>
      <p>${esc(item.text || item.message || item.summary || item.outcome || JSON.stringify(item).slice(0, 260))}</p>
    </div>
  `).join("");
}

function taskLogsHtml(result) {
  const logs = Array.isArray(result) ? result : (result.logs || []);
  const snapshots = Array.isArray(result?.snapshots) ? result.snapshots : [];
  const blockers = Array.isArray(result?.blockers) ? result.blockers : [];
  const workflowEvents = Array.isArray(result?.workflow_events) ? result.workflow_events : [];
  const reports = Array.isArray(result?.reports) ? result.reports : [];
  const records = Array.isArray(result?.records) ? result.records : [];
  if (!logs.length && !snapshots.length && !blockers.length && !workflowEvents.length && !reports.length && !records.length) {
    return `<div class="empty">暂无任务日志、快照或节点事件。</div>`;
  }
  return `
    <details class="trace-section" open>
      <summary>进度日志 (${logs.length})</summary>
      <div class="workflow-events">${taskLogLineRows(logs)}</div>
    </details>
    <details class="trace-section">
      <summary>状态快照 (${snapshots.length})</summary>
      <div class="list">${snapshotRows(snapshots)}</div>
    </details>
    <details class="trace-section">
      <summary>阻塞与 Watchdog (${blockers.length})</summary>
      <div class="list">${blockerRows(blockers, result?.watchdog || {})}</div>
    </details>
    <details class="trace-section">
      <summary>工作流事件 (${workflowEvents.length})</summary>
      <div class="workflow-events">${recordRows(workflowEvents)}</div>
    </details>
    <details class="trace-section">
      <summary>Reports / Records (${reports.length + records.length})</summary>
      <div class="workflow-events">${recordRows([...reports, ...records])}</div>
    </details>
  `;
}

function renderMonitor() {
  const runs = state.workflow_runs || [];
  const activeRuns = runs.filter((item) => item.active);
  const selectedRun = runs.find((item) => item.task_id === selectedTaskId) || activeRuns[0] || runs[0] || null;
  const scheduleJobs = Object.values(state.schedule_jobs || {});
  $("view").innerHTML = `
    <section class="grid three">
      ${metric("运行实例", runs.length, `${activeRuns.length} 活跃`)}
      ${metric("待投递", runs.reduce((sum, item) => sum + Number(item.outbox_pending || 0), 0))}
      ${metric("计划任务", scheduleJobs.length)}
    </section>
    <section class="grid two">
      <div class="panel">
        <div class="panel-head"><div><p class="card-kicker">Workflow Runs</p><h2>运行实例</h2></div></div>
        <div class="list">${workflowRunRows(runs)}</div>
      </div>
      <div class="panel">
        <div class="panel-head">
          <div><p class="card-kicker">操作</p><h2>实时控制</h2></div>
          <div class="inline-actions">
            <button class="button secondary" data-action="restart-heartbeat" ${selectedRun?.active ? "" : "disabled"} type="button">一键重启心跳</button>
            <button class="button danger" data-action="cancel-task" ${selectedRun?.active ? "" : "disabled"} type="button">强制停止任务</button>
          </div>
        </div>
        ${selectedRun ? workflowRunDetail(selectedRun) : `<div class="empty">暂无运行实例。</div>`}
        <div class="panel-head"><div><p class="card-kicker">Schedule</p><h3>定时与心跳任务</h3></div></div>
        <div class="list">${scheduleJobs.map((job) => `
          <div class="list-row">
            <div class="row-title"><span>${esc(job.agent_id || job.task_id || job.job_id || "schedule")}</span>${badge(job.enabled === false ? "暂停" : "启用", job.enabled === false ? "warn" : "ok")}</div>
            <div class="row-meta">${esc(job.cron || job.cron_expression || "-")} · ${esc(job.next_run_at || job.last_run_at || "")}</div>
          </div>
        `).join("") || `<div class="empty">暂无定时任务。</div>`}</div>
      </div>
    </section>
  `;
}

function workflowRunRows(runs) {
  if (!runs.length) return `<div class="empty">暂无运行实例。</div>`;
  return runs.slice(0, 80).map((run) => {
    const health = run.heartbeat || {};
    const selected = run.task_id === selectedTaskId;
    return `
      <button class="list-row ${selected ? "selected" : ""}" data-action="select-task" data-id="${esc(run.task_id)}" type="button">
        <div class="row-title"><span>${esc(run.agent_name || run.task_id)}</span>${badge(run.active ? "活跃" : "归档", run.active ? "ok" : "warn")}${badge(healthLabel(health), health.tone || "warn")}</div>
        <div class="row-meta">${esc(run.task_id)} · 当前节点 ${esc(run.workflow_current_node_id || "-")} · Outbox ${run.outbox_pending || 0}</div>
      </button>
    `;
  }).join("");
}

function workflowRunDetail(run) {
  const health = run.heartbeat || {};
  return `
    <div class="detail-box monitor-summary">
      <div class="row-title"><span>${esc(run.agent_name || run.task_id)}</span>${badge(taskStatusLabel(run.status), run.active ? "ok" : "warn")}${badge(healthLabel(health), health.tone || "warn")}</div>
      <div class="row-meta">当前节点：${esc(run.workflow_current_node_id || "-")} · 来源：${esc(run.source || "-")} · 更新：${esc(run.updated_at || "-")}</div>
      <div class="workflow-path-line">${(run.workflow_path || []).map((id) => `<span>${esc(id)}</span>`).join("") || "<em>暂无路径</em>"}</div>
      <div class="mini-stats">
        <span>报告 ${run.reports?.length || 0}</span>
        <span>记录 ${run.records?.length || 0}</span>
        <span>阻塞 ${run.blockers?.length || 0}</span>
        <span>审批 ${run.pending_approvals?.length || 0}</span>
      </div>
    </div>
    <div class="grid two compact">
      <div>
        <div class="panel-head"><div><p class="card-kicker">Outbox</p><h3>待发与已发</h3></div></div>
        <div class="list">${outboxRows(run.outbox || [], run.outbox_delivery_history || [])}</div>
      </div>
      <div>
        <div class="panel-head"><div><p class="card-kicker">阻塞 / Watchdog</p><h3>卡住原因</h3></div></div>
        <div class="list">${blockerRows(run.blockers || [], run.watchdog || {})}</div>
      </div>
    </div>
    <div class="panel-head"><div><p class="card-kicker">Reports / Records</p><h3>运行产物</h3></div></div>
    <div class="workflow-events">${recordRows([...(run.reports || []), ...(run.records || [])])}</div>
  `;
}

function outboxRows(outbox, history) {
  const rows = [
    ...outbox.map((item) => ({ ...item, _kind: "待发" })),
    ...history.slice(-8).reverse().map((item) => ({ ...item, _kind: "历史" })),
  ];
  if (!rows.length) return `<div class="empty">暂无待发或投递记录。</div>`;
  return rows.map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.message || item.image || item.emoji || "-")}</span>${badge(item.delivery || item._kind, item.delivery === "sent" ? "ok" : "warn")}</div>
      <div class="row-meta">${esc(item._kind)} · ${esc(item.target || "当前会话")} · ${esc(item.send_type || item.channel || "")}${item.plugin_name ? ` · 插件 ${esc(item.plugin_name)}` : ""}</div>
    </div>
  `).join("");
}

function blockerRows(blockers, watchdog) {
  const rows = blockers.length ? blockers : (watchdog.last_issue ? [watchdog] : []);
  if (!rows.length) return `<div class="empty">暂无阻塞记录。</div>`;
  return rows.map((item) => `
    <div class="list-row">
      <div class="row-title"><span>${esc(item.reason || item.message || item.last_issue || item.type || "阻塞")}</span>${badge(item.count ? `x${item.count}` : "watchdog", "warn")}</div>
      <div class="row-meta">${esc(item.time || item.updated_at || item.last_failure_at || "")} · ${esc(item.note || item.last_decision || "")}</div>
    </div>
  `).join("");
}

function recordRows(rows) {
  if (!rows.length) return `<div class="empty">暂无报告或记录。</div>`;
  return rows.slice(-12).reverse().map((item) => `
    <div class="log-row">
      <span>${esc(item.time || item.created_at || "")}</span>
      <strong>${esc(item.title || item.kind || item.node_id || "record")}</strong>
      <p>${esc(item.summary || item.text || item.message || item.outcome || JSON.stringify(item).slice(0, 240))}</p>
    </div>
  `).join("");
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
  const __prevScroll = document.querySelector(".integration-content")?.scrollTop || 0;
  const tabs = [
    ["plugins", "插件管理", "控制任务模式可见的插件", (state.plugins || []).length],
    ["tools", "注册工具", "按来源插件折叠工具白名单", (state.tools || []).length],
    ["apis", "自定义接口", "把外部服务注册为受管工具", (state.custom_apis || []).length],
    ["credentials", "凭证库", "统一加密保存接口密钥", (state.credentials || []).length],
    ["blueprints", "外部方案蓝图", "接入外部任务方案", (state.integrations || state.modules || []).length],
  ];
  $("view").innerHTML = `
    <section class="integration-shell">
      <div class="panel-head">
        <div><p class="card-kicker">能力边界</p><h2>插件与集成</h2></div>
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
  const __sc = document.querySelector(".integration-content");
  if (__sc) __sc.scrollTop = __prevScroll; // 还原滚动，避免切换/勾选后跳回顶部
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
      这里管理 AstrBot 插件在任务模式里的可见性。AstrBot 全局停用的插件会固定关闭；任务模式只能进一步关闭插件，不能绕过 AstrBot 原生插件管理把它重新启用。
    </div>
    <input class="filter-input" data-action="filter-plugins" value="${esc(pluginFilter)}" placeholder="筛选插件名、目录或说明" />
    <details class="collapse-group" open>
      <summary>可用于任务模式的插件 <span>${activeRows.length}</span></summary>
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
  if ((currentAgent?.plugin_blacklist || []).includes(plugin.name)) return false;
  if (!plugin.activated) return false;
  return typeof override === "boolean" ? override : true;
}

function toolsPanel() {
  const selected = new Set(currentAgent.enabled_tools || []);
  const noExternal = selected.has(EMPTY_TOOLS_SENTINEL);
  const rows = (state.tools || []).filter((tool) =>
    includesQuery([tool.name, tool.description, tool.plugin_name, tool.plugin_display_name, tool.source], toolFilter)
  );
  const sourceGroups = new Map();
  let selectableCount = 0;
  let selectedCount = 0;
  rows.forEach((tool) => {
    const plugin = (state.plugins || []).find((item) => item.name === tool.plugin_name);
    const pluginOn = plugin ? pluginEffective(plugin) : true;
    const checked = selected.has(tool.name) && !noExternal && pluginOn && tool.active !== false;
    const disabled = !pluginOn || tool.active === false;
    if (!disabled) selectableCount++;
    if (checked) selectedCount++;
    const risk = currentAgent.tool_risk_overrides?.[tool.name] || tool.risk || "work";
    const row = `
      <label class="tool-card ${disabled ? "is-disabled" : ""} ${checked ? "is-on" : ""}">
        <span class="tool-card-switch"><input type="checkbox" data-action="toggle-tool" data-id="${esc(tool.name)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""} /><i aria-hidden="true"></i></span>
        <span class="tool-card-main">
          <strong>${esc(tool.name)}</strong>
          <small>${esc(tool.description || tool.plugin_display_name || tool.source || "注册工具")}</small>
        </span>
        <span class="tool-card-meta">
          ${badge(disabled ? "随插件关闭" : checked ? "已启用" : "未启用", disabled ? "bad" : checked ? "ok" : "")}
          <select data-action="set-tool-risk" data-id="${esc(tool.name)}" title="风险等级">${options(["safe", "work", "high"], risk, riskLabel)}</select>
        </span>
      </label>
    `;
    const key = tool.plugin_name || tool.plugin_display_name || tool.source || "registered";
    if (!sourceGroups.has(key)) {
      sourceGroups.set(key, {
        title: tool.plugin_display_name || tool.plugin_name || (tool.source === "builtin_catalog" ? "AstrBot 内置工具目录" : "未绑定插件的注册工具"),
        enabled: plugin ? pluginEffective(plugin) : tool.active !== false,
        rows: [],
      });
    }
    sourceGroups.get(key).rows.push(row);
  });
  const groups = Array.from(sourceGroups.values()).sort((a, b) =>
    Number(b.enabled) - Number(a.enabled) || a.title.localeCompare(b.title, "zh-CN")
  );
  const groupHtml = (item) => `
    <details class="tool-source-group" ${item.enabled ? "open" : ""}>
      <summary>
        <span class="tsg-title">${esc(item.title)}</span>
        ${badge(item.enabled ? "可用" : "随插件关闭", item.enabled ? "ok" : "bad")}
        <span class="tsg-count">${item.rows.length}</span>
      </summary>
      <div class="tool-card-list">${item.rows.join("")}</div>
    </details>
  `;
  return `
    <div class="tools-page">
      <div class="tools-intro">
        <strong>注册工具白名单</strong>
        <span>勾选任务模式可调用的工具，按来源插件分组；修改即时生效，保存方案后写入运行时白名单。</span>
      </div>
      <div class="tools-toolbar">
        <input class="filter-input" data-action="filter-tools" value="${esc(toolFilter)}" placeholder="搜索工具名 / 来源插件 / 说明" />
        <div class="tools-toolbar-actions">
          <span class="tools-count">${noExternal ? "已禁用全部外部工具" : `已启用 ${selectedCount} / 可用 ${selectableCount}`}</span>
          <button class="button secondary" data-action="enable-visible-tools" type="button">全选可用</button>
          <button class="button secondary" data-action="disable-tools" type="button">全部禁用</button>
        </div>
      </div>
      ${noExternal ? `<div class="section-note">当前为「无外部工具」模式：任务只用内置能力。点任意工具或「全选可用」即可重新启用。</div>` : ""}
      <div class="tools-groups">${groups.map(groupHtml).join("") || `<div class="empty">没有匹配的注册工具。</div>`}</div>
      <details class="tool-approval-block">
        <summary>工具审批策略</summary>
        <div class="tool-approval-grid">
          <label>审批模式<select id="tool-approval-mode">${options(["observe", "work", "high_risk_review", "delegated"], currentAgent.approval_policy.mode || "work", approvalModeLabel)}</select></label>
          <label>已授权范围（无需每次确认）<textarea id="preapproved-scopes" rows="4" placeholder="例如：读取项目文件&#10;运行测试">${esc(listToLines(currentAgent.approval_policy.preapproved_scopes))}</textarea></label>
          <label>必须审批动作<textarea id="require-approval" rows="4" placeholder="例如：删除文件&#10;部署">${esc(listToLines(currentAgent.approval_policy.require_approval))}</textarea></label>
          <label>审批备注<textarea id="approval-note" rows="3">${esc(currentAgent.approval_policy.note || "")}</textarea></label>
        </div>
        <div class="button-row"><button class="button secondary" data-action="apply-approval-policy" type="button">应用审批策略</button></div>
      </details>
    </div>
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
        <div class="panel-head"><div><p class="card-kicker">规则</p><h3>任务模式技能规则</h3></div></div>
        <div class="section-note">规则会影响进入、执行与归档。</div>
        <label>任务模式行为规则<textarea id="skill-rule-content" rows="8" placeholder="写入任务模式的触发、审批、记忆过滤、工具边界等补充规则。">${esc(agentModeRule.content || "")}</textarea></label>
        <label>入口摘要规则<textarea id="entry-summary-rule-content" rows="7" placeholder="定义进入任务模式时如何把当前上下文压缩成 task_brief。">${esc(entryRule.content || "")}</textarea></label>
        <label>出口归档规则<textarea id="exit-summary-rule-content" rows="7" placeholder="定义退出任务模式时如何归档总结，以及哪些记忆候选可以回流。">${esc(exitRule.content || "")}</textarea></label>
        <div class="button-row"><button class="button" data-action="save-skill-rules" type="button">保存并同步规则</button></div>
      </div>
      <div class="capability-list">${(state.skills || []).map((skill) => `
        <label class="toggle-row">
          <input type="checkbox" data-action="toggle-skill" data-id="${esc(skill.name)}" ${selected.has(skill.name) ? "checked" : ""} />
          <span><strong>${esc(skill.name)}</strong><br /><small>${esc(skill.path || "AstrBot 技能")}</small></span>
          ${badge(skill.active ? "已安装" : "未激活", skill.active ? "ok" : "warn")}
        </label>
      `).join("") || `<div class="empty">未读取到技能。</div>`}</div>
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
    <section>
      <div class="section-note">凭证由后端统一管理；这里仅展示已登记的引用，避免在插件管理页直接输入密钥。</div>
      <div class="capability-list">${(state.credentials || []).map((item) => `
        <div class="list-row">
          <div class="row-title"><span>${esc(item.label || item.credential_id)}</span>${badge(item.has_value ? "已加密" : "空值", item.has_value ? "ok" : "warn")}</div>
          <div class="row-meta">${esc(item.credential_id)} · ${esc(item.provider || "-")} · ${esc(item.scope || "tool")}</div>
        </div>
      `).join("") || `<div class="empty">暂无凭证。</div>`}</div>
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
      外部方案蓝图＝别人写好的一整套任务规则模板，可一键「加入当前方案」后再按需微调；真正调用能力仍在注册工具和自定义 API 里管理。<strong>选中某个蓝图后，右侧标题下会明确显示它是否已加入当前方案。</strong>
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
            <button class="button ${enabled.has(selected.module_id) ? "danger" : ""}" data-action="toggle-integration" data-id="${esc(selected.module_id)}" type="button">${enabled.has(selected.module_id) ? "从当前方案移除" : "加入当前方案"}</button>
          </div>
          <div class="blueprint-attach-banner ${enabled.has(selected.module_id) ? "on" : "off"}">
            ${enabled.has(selected.module_id)
              ? `✓ 已加入当前方案「${esc(agentDisplayName(currentAgent))}」，保存配置后随该方案一起生效。`
              : `○ 尚未加入当前方案「${esc(agentDisplayName(currentAgent))}」。点右上角「加入当前方案」即可启用。`}
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
  const offsetY = workflowWorldOffsetY(size);
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
    canvas.dataset.worldOffsetY = String(offsetY);
    canvas.classList.toggle("is-connecting", Boolean(workflowConnection || workflowPendingPort));
  }
  for (const el of document.querySelectorAll(".flow-node")) {
    const item = workflowNodeById(el.dataset.id);
    if (!item) continue;
    el.style.left = `${Number(item.x || 0) + offsetX}px`;
    el.style.top = `${Number(item.y || 0) + offsetY}px`;
  }
  svg.setAttribute("width", String(size.width));
  svg.setAttribute("height", String(size.height));
  svg.setAttribute("viewBox", `0 0 ${size.width} ${size.height}`);
  svg.innerHTML = workflowLinksSvg(offsetX, offsetY);
  const minimap = document.querySelector(".workflow-minimap");
  if (minimap && !workflowMinimapPan && !workflowMinimapResize) minimap.outerHTML = workflowMinimap(size);
}

// 剪刀工具几何辅助：把 SVG 用户坐标点转成屏幕(client)坐标；判断点到线段的距离。
function workflowSvgPointToClient(pt) {
  const svg = document.querySelector(".workflow-links");
  if (!svg || typeof svg.getScreenCTM !== "function") return null;
  const ctm = svg.getScreenCTM();
  if (!ctm) return null;
  return { x: ctm.a * pt.x + ctm.c * pt.y + ctm.e, y: ctm.b * pt.x + ctm.d * pt.y + ctm.f };
}
function pointNearSegment(px, py, ax, ay, bx, by, tol) {
  const vx = bx - ax, vy = by - ay;
  const wx = px - ax, wy = py - ay;
  const len2 = vx * vx + vy * vy;
  let t = len2 ? (wx * vx + wy * vy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  const cx = ax + t * vx, cy = ay + t * vy;
  const dx = px - cx, dy = py - cy;
  return (dx * dx + dy * dy) <= tol * tol;
}

function workflowCanvasPoint(event) {
  const wrap = document.querySelector(".workflow-canvas-wrap");
  const canvas = document.querySelector(".workflow-canvas");
  if (!wrap || !canvas) return { x: 0, y: 0 };
  const rect = wrap.getBoundingClientRect();
  const zoom = Number(canvas.dataset.zoom || workflowZoom || 1) || 1;
  const offsetX = Number(canvas.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  const offsetY = Number(canvas.dataset.worldOffsetY || workflowWorldOffsetY()) || 0;
  return {
    x: (event.clientX - rect.left - workflowPanX) / zoom - offsetX,
    y: (event.clientY - rect.top - workflowPanY) / zoom - offsetY,
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

function addWorkflowEdge(from, to, edgeType = "success", fromPort = "") {
  ensureWorkflow();
  if (!from || !to || from === to) return false;
  const type = edgeType || "success";
  // 同一对节点 + 同一出口类型只允许一条；不同出口类型（如 success / failed）可并存。
  const exists = currentAgent.workflow_edges.some((edge) => edge.from === from && edge.to === to && String(edge.edge_type || "success") === type);
  if (exists) return false;
  pushWorkflowHistory();
  const edge = { from, to, edge_type: type };
  if (fromPort && fromPort !== "out") edge.from_port = fromPort;
  currentAgent.workflow_edges.push(edge);
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
  next.y = clamp(Number(source.y || 0) + 80, WORKFLOW_CANVAS_MIN_Y, WORKFLOW_CANVAS_MAX_Y);
  currentAgent.workflow_nodes.push(next);
  selectedWorkflowNodeId = next.id;
  workflowInspectorOpen = true;
  workflowCheckReport = null;
  workflowDryRunReport = null;
  return next;
}

// 「整理」：按连线把节点分层，从左到右一层一层排好，让线条结构一目了然。
// 1) 用最长路径给每个节点定层级(列)；2) 每列内按"上一层连进来的节点平均位置"排序，减少交叉。
function autoLayoutWorkflow() {
  ensureWorkflow();
  const nodes = currentAgent.workflow_nodes || [];
  if (!nodes.length) { workflowCheckReport = null; return; }
  const edges = (currentAgent.workflow_edges || []).filter((e) => e && e.from !== e.to);
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const outAdj = new Map(nodes.map((n) => [n.id, []]));
  const inAdj = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e) => {
    if (!byId.has(e.from) || !byId.has(e.to)) return;
    outAdj.get(e.from).push({ to: e.to });
    inAdj.get(e.to).push({ from: e.from });
  });
  // 1) DFS 找回边（指向递归栈内节点的边）；分层时忽略回边，避免 retry / 循环把层级拉乱。
  const backEdges = new Set();
  const color = new Map();
  const dfs = (start) => {
    const stack = [{ id: start, i: 0 }];
    color.set(start, 1);
    while (stack.length) {
      const top = stack[stack.length - 1];
      const outs = outAdj.get(top.id) || [];
      if (top.i < outs.length) {
        const nx = outs[top.i++].to;
        const c = color.get(nx) || 0;
        if (c === 0) { color.set(nx, 1); stack.push({ id: nx, i: 0 }); }
        else if (c === 1) backEdges.add(`${top.id}->${nx}`);
      } else { color.set(top.id, 2); stack.pop(); }
    }
  };
  nodes.forEach((n) => { if (!color.has(n.id)) dfs(n.id); });
  const fwdIn = (id) => (inAdj.get(id) || []).filter((e) => !backEdges.has(`${e.from}->${id}`));
  const fwdOut = (id) => (outAdj.get(id) || []).filter((e) => !backEdges.has(`${id}->${e.to}`));
  let roots = nodes.filter((n) => fwdIn(n.id).length === 0).map((n) => n.id);
  if (!roots.length) { const en = nodes.find((n) => workflowStage(n) === "entry") || nodes[0]; if (en) roots = [en.id]; }
  // 2) 最长路径分层（Kahn 拓扑，rank = max(前驱)+1），保证节点排在所有前驱右侧。
  const rank = new Map();
  const indeg = new Map(nodes.map((n) => [n.id, fwdIn(n.id).length]));
  const q = [];
  nodes.forEach((n) => { if ((indeg.get(n.id) || 0) === 0) { rank.set(n.id, 0); q.push(n.id); } });
  roots.forEach((id) => { if (!rank.has(id)) { rank.set(id, 0); q.push(id); } });
  let head = 0;
  while (head < q.length) {
    const id = q[head++];
    const r = rank.get(id) || 0;
    for (const e of fwdOut(id)) {
      if (!rank.has(e.to) || r + 1 > rank.get(e.to)) rank.set(e.to, r + 1);
      indeg.set(e.to, (indeg.get(e.to) || 1) - 1);
      if ((indeg.get(e.to) || 0) <= 0) q.push(e.to);
    }
  }
  nodes.forEach((n) => { if (!rank.has(n.id)) { const ps = fwdIn(n.id).map((e) => rank.get(e.from)).filter((v) => v != null); rank.set(n.id, ps.length ? Math.max(...ps) + 1 : 0); } });
  // 3) 侧链节点（人工接管 / 重试 / 错误捕获 / 审批）不占主行，下沉到该列底部。
  const SIDE_ACTIONS = new Set(["handoff", "retry", "catch_error", "wait_user", "human_login_handoff", "revoke_session", "request_approval"]);
  const isSide = (n) => SIDE_ACTIONS.has(String(n.action || "")) || String(n.kind || "") === "human";
  // 4) 领地分带：按 owner 分组成水平泳道，main/无主在最上，其余按最小 rank 排序；
  //    agent_role 角色卡作为该带表头置于左上。同一 Agent 的圈地节点因此连成一片，不再东一块西一块。
  const ownerOf = (n) => String(n.owner || "");
  const ownerNodes = new Map();
  nodes.forEach((n) => { const o = ownerOf(n); if (!ownerNodes.has(o)) ownerNodes.set(o, []); ownerNodes.get(o).push(n); });
  const ownerMinRank = (o) => Math.min(...ownerNodes.get(o).map((n) => rank.get(n.id) || 0));
  const owners = Array.from(ownerNodes.keys()).sort((a, b) => {
    if (a === "" && b !== "") return -1;
    if (b === "" && a !== "") return 1;
    return ownerMinRank(a) - ownerMinRank(b);
  });
  const COL = Math.max(WORKFLOW_LANE_WIDTH, WORKFLOW_NODE_WIDTH + 200);
  const ROW = WORKFLOW_NODE_HEIGHT + 110;
  const BAND_GAP = ROW;
  const X0 = 140, Y0 = 140;
  let bandTop = Y0;
  owners.forEach((o) => {
    const list = ownerNodes.get(o);
    const cols = new Map();
    list.forEach((n) => { const r = rank.get(n.id) || 0; if (!cols.has(r)) cols.set(r, []); cols.get(r).push(n); });
    const colKeys = Array.from(cols.keys()).sort((a, b) => a - b);
    const rowIndex = new Map();
    const headFirst = (n) => (String(n.action || "") === "agent_role" ? -1 : 0);
    colKeys.forEach((r) => {
      const col = cols.get(r).slice().sort((a, b) => {
        const sa = isSide(a) ? 1 : 0, sb = isSide(b) ? 1 : 0; if (sa !== sb) return sa - sb;
        const ha = headFirst(a), hb = headFirst(b); if (ha !== hb) return ha - hb;
        return (Number(a.y) || 0) - (Number(b.y) || 0);
      });
      col.forEach((n, i) => rowIndex.set(n.id, i));
    });
    for (let pass = 0; pass < 4; pass++) {
      for (const r of colKeys) {
        const col = cols.get(r);
        const bary = (n) => {
          const neigh = [...fwdIn(n.id).map((e) => e.from), ...fwdOut(n.id).map((e) => e.to)]
            .filter((m) => rowIndex.has(m) && ownerOf(byId.get(m)) === o);
          if (!neigh.length) return rowIndex.get(n.id) || 0;
          return neigh.reduce((acc, m) => acc + (rowIndex.get(m) || 0), 0) / neigh.length;
        };
        col.sort((a, b) => {
          const sa = isSide(a) ? 1 : 0, sb = isSide(b) ? 1 : 0; if (sa !== sb) return sa - sb;
          const ha = headFirst(a), hb = headFirst(b); if (ha !== hb) return ha - hb;
          return bary(a) - bary(b);
        });
        col.forEach((n, i) => rowIndex.set(n.id, i));
      }
    }
    const bandRows = Math.max(1, ...colKeys.map((r) => cols.get(r).length));
    colKeys.forEach((r) => {
      cols.get(r).forEach((n) => { n.x = X0 + r * COL; n.y = bandTop + (rowIndex.get(n.id) || 0) * ROW; });
    });
    bandTop += bandRows * ROW + BAND_GAP;
  });
  workflowCheckReport = null;
}

function focusWorkflowStart() {
  const first = currentAgent.workflow_nodes?.find((item) => workflowStage(item) === "entry") || currentAgent.workflow_nodes?.[0];
  workflowZoom = clamp(workflowZoom || 0.85, 0.55, 1);
  const offsetX = workflowWorldOffsetX();
  const offsetY = workflowWorldOffsetY();
  workflowPanX = first ? Math.round(120 - (Number(first.x || 0) + offsetX) * workflowZoom) : 80;
  workflowPanY = first ? Math.round(180 - (Number(first.y || 0) + offsetY) * workflowZoom) : 120;
}

function portFromPoint(clientX, clientY) {
  return document.elementFromPoint(clientX, clientY)?.closest(".node-port") || null;
}

function workflowPortInfo(portEl) {
  if (!portEl) return null;
  const nodeId = portEl.dataset.nodeId || "";
  const item = workflowNodeById(nodeId);
  if (!item) return null;
  const isIn = portEl.dataset.port === "in";
  const port = isIn ? "in" : (portEl.dataset.port || "out");
  const edgeType = isIn ? "" : (portEl.dataset.edgeType || "success");
  const anchor = isIn
    ? workflowNodeAnchor(item, "in", workflowWorldOffsetX(), workflowWorldOffsetY())
    : workflowNodeOutAnchor(item, port, workflowWorldOffsetX(), workflowWorldOffsetY());
  return { nodeId: item.id, port, isIn, edgeType, anchor };
}

function connectWorkflowPorts(start, target) {
  if (!start || !target || start.nodeId === target.nodeId) return false;
  // 必须一端是输入口、一端是输出口
  if (start.isIn === target.isIn) return false;
  const outSide = start.isIn ? target : start;
  const inSide = start.isIn ? start : target;
  return addWorkflowEdge(outSide.nodeId, inSide.nodeId, outSide.edgeType || "success", outSide.port);
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

function removeWorkflowContextMenuDom() {
  document.querySelector(".workflow-context-menu")?.remove();
}

function removeWorkflowDragGhost() {
  workflowDragGhostEl?.remove();
  workflowDragGhostEl = null;
  // 兜底：清掉任何遗留的拖拽残影和落点高亮，避免切页后残框永久留在页面上。
  document.querySelectorAll(".workflow-drag-ghost").forEach((el) => el.remove());
  document.querySelectorAll(".workflow-canvas-wrap.is-dropping").forEach((el) => el.classList.remove("is-dropping"));
}

function createWorkflowDragGhost(chip) {
  removeWorkflowDragGhost();
  const ghost = document.createElement("div");
  ghost.className = "workflow-drag-ghost";
  const icon = chip.querySelector(".game-icon")?.cloneNode(true);
  if (icon) ghost.appendChild(icon);
  const title = document.createElement("strong");
  title.textContent = chip.dataset.title || chip.querySelector("strong")?.textContent || "节点";
  ghost.appendChild(title);
  const hint = document.createElement("span");
  hint.textContent = "拖到画布添加";
  ghost.appendChild(hint);
  document.body.appendChild(ghost);
  return ghost;
}

document.addEventListener("pointerdown", (event) => {
  if (route === "workflow" && workflowContextMenu && !event.target.closest(".workflow-context-menu")) {
    workflowContextMenu = null;
    removeWorkflowContextMenuDom();
  }
  const workflowField = event.target.closest?.(WORKFLOW_FIELD_SELECTOR);
  if (workflowField && route === "workflow") {
    const scroller = workflowField.closest(".drawer-scroll");
    if (workflowField.closest(".workflow-inspector-drawer")) {
      workflowInspectorFocusScrollTop = scroller?.scrollTop || 0;
      workflowInspectorScrollTop = workflowInspectorFocusScrollTop;
    }
    if (workflowField.closest(".workflow-tool-drawer")) {
      workflowToolboxScrollTop = scroller?.scrollTop || 0;
    }
  }
  // 指针拖拽：从模块库把素材拖到画布。比原生拖拽更稳，落点即鼠标释放处。
  const chipEl = route === "workflow" ? event.target.closest?.(".workflow-material-chip") : null;
  if (chipEl) {
    workflowMaterialChipDrag = {
      pointerId: event.pointerId,
      kind: chipEl.dataset.dragKind || (chipEl.dataset.action === "add-template-node" ? "template" : "runtime"),
      id: chipEl.dataset.dragId || chipEl.dataset.id || "",
      refType: chipEl.dataset.refType || "",
      refId: chipEl.dataset.refId || "",
      title: chipEl.dataset.title || "",
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
      ghost: null,
      chip: chipEl,
    };
    // 不 preventDefault：仍允许把它当普通点击（小位移时打开预览）。
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
      edge: minimapResize.dataset.edge || "se",
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
      if (added) renderWorkflowStable();
      else highlightWorkflowPendingPort();
      return;
    }
    selectedWorkflowNodeId = portInfo.nodeId;
    workflowConnection = {
      nodeId: portInfo.nodeId,
      port: portInfo.port,
      isIn: portInfo.isIn,
      edgeType: portInfo.edgeType,
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
  if (nodeEl && event.target.closest(".node-block-btn")) return;
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
  if (event.target.closest(WORKFLOW_CANVAS_BLOCKER_SELECTOR)) return;
  if (event.target.closest("[data-action='delete-workflow-edge']")) return;
  event.preventDefault();
  if (workflowScissorMode) {
    const stroke = document.createElement("div");
    stroke.className = "workflow-scissor-trail";
    document.body.appendChild(stroke);
    workflowScissorStroke = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      cut: new Set(),
      el: stroke,
    };
    wrapEl.setPointerCapture?.(event.pointerId);
    return;
  }
  if (workflowSelectionMove && workflowSelectedNodeIds.size) {
    const base = new Map();
    Array.from(workflowSelectedNodeIds).forEach((id) => {
      const n = workflowNodeById(id);
      if (n) base.set(id, { x: Number(n.x || 0), y: Number(n.y || 0) });
    });
    workflowGroupDrag = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      base,
      moved: false,
      before: workflowSnapshot(),
    };
    wrapEl.setPointerCapture?.(event.pointerId);
    return;
  }
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

// [已移除] focusin / input(capture) 里的 rAF 滚动兜底。
// 原逻辑会在原生 <select> 展开后用 requestAnimationFrame 改写抽屉 scrollTop，
// 在 Chromium 下会把刚展开的下拉框立刻关掉（“闪一下就收起”）。
// 滚动与焦点的保持现在统一由 render() 中的 activeFieldSnapshotGlobal/restoreFieldFocusGlobal 完成。

document.addEventListener("pointermove", (event) => {
  if (workflowScissorStroke && workflowScissorStroke.pointerId === event.pointerId) {
    const sx = workflowScissorStroke.startX, sy = workflowScissorStroke.startY;
    const left = Math.min(sx, event.clientX), top = Math.min(sy, event.clientY);
    Object.assign(workflowScissorStroke.el.style, {
      left: left + "px", top: top + "px",
      width: Math.abs(event.clientX - sx) + "px",
      height: Math.abs(event.clientY - sy) + "px",
    });
    // 命中检测：剪刀划过的线段与每条连线的可点击粗描边相交即标记剪断
    const segA = { x: workflowScissorStroke.lastX ?? sx, y: workflowScissorStroke.lastY ?? sy };
    const segB = { x: event.clientX, y: event.clientY };
    workflowScissorStroke.lastX = event.clientX;
    workflowScissorStroke.lastY = event.clientY;
    document.querySelectorAll(".workflow-link-hit").forEach((path) => {
      const idx = path.dataset.index;
      if (idx == null || workflowScissorStroke.cut.has(idx)) return;
      try {
        const len = path.getTotalLength();
        const steps = Math.max(8, Math.min(60, Math.round(len / 14)));
        for (let i = 0; i <= steps; i++) {
          const pt = path.getPointAtLength((len * i) / steps);
          const sp = workflowSvgPointToClient(pt);
          if (!sp) continue;
          if (pointNearSegment(sp.x, sp.y, segA.x, segA.y, segB.x, segB.y, 9)) {
            workflowScissorStroke.cut.add(idx);
            path.classList.add("is-cutting");
            break;
          }
        }
      } catch (e) {}
    });
    return;
  }
  if (workflowGroupDrag && workflowGroupDrag.pointerId === event.pointerId) {
    const dx = (event.clientX - workflowGroupDrag.startX) / workflowZoom;
    const dy = (event.clientY - workflowGroupDrag.startY) / workflowZoom;
    workflowGroupDrag.moved ||= Math.abs(event.clientX - workflowGroupDrag.startX) + Math.abs(event.clientY - workflowGroupDrag.startY) > 3;
    workflowGroupDrag.base.forEach((b, id) => {
      const n = workflowNodeById(id);
      if (!n) return;
      n.x = clamp(b.x + dx, WORKFLOW_CANVAS_MIN_X, WORKFLOW_CANVAS_MAX_X);
      n.y = clamp(b.y + dy, WORKFLOW_CANVAS_MIN_Y, WORKFLOW_CANVAS_MAX_Y);
    });
    refreshWorkflowCanvasDom();
    return;
  }
  if (workflowMaterialChipDrag && workflowMaterialChipDrag.pointerId === event.pointerId) {
    const dx = event.clientX - workflowMaterialChipDrag.startX;
    const dy = event.clientY - workflowMaterialChipDrag.startY;
    if (!workflowMaterialChipDrag.moved && Math.abs(dx) + Math.abs(dy) > 6) {
      workflowMaterialChipDrag.moved = true;
      workflowMaterialChipDrag.ghost = createWorkflowDragGhost(workflowMaterialChipDrag.chip);
    }
    if (workflowMaterialChipDrag.ghost) {
      workflowMaterialChipDrag.ghost.style.left = `${event.clientX + 12}px`;
      workflowMaterialChipDrag.ghost.style.top = `${event.clientY + 12}px`;
      const overWrap = !!event.target.closest?.(".workflow-canvas-wrap");
      document.querySelector(".workflow-canvas-wrap")?.classList.toggle("is-dropping", overWrap);
    }
    return;
  }
  if (workflowMinimapResize && workflowMinimapResize.pointerId === event.pointerId) {
    const dx = event.clientX - workflowMinimapResize.startX;
    const dy = event.clientY - workflowMinimapResize.startY;
    const edge = workflowMinimapResize.edge || "se";
    if (edge.includes("e")) {
      workflowMinimapWidth = clamp(workflowMinimapResize.baseWidth + dx, WORKFLOW_MINIMAP_MIN_WIDTH, WORKFLOW_MINIMAP_MAX_WIDTH);
    }
    if (edge.includes("s")) {
      workflowMinimapHeight = clamp(workflowMinimapResize.baseHeight + dy, WORKFLOW_MINIMAP_MIN_HEIGHT, WORKFLOW_MINIMAP_MAX_HEIGHT);
    }
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
    const desiredPanX = workflowPan.baseX + dx;
    const desiredPanY = workflowPan.baseY + dy;
    const wrap = document.querySelector(".workflow-canvas-wrap");
    const viewportWidth = wrap?.clientWidth || window.innerWidth || 1200;
    const viewportHeight = wrap?.clientHeight || window.innerHeight || 760;
    const worldRenderWidth = WORKFLOW_WORLD_WIDTH * workflowZoom;
    const worldRenderHeight = WORKFLOW_WORLD_HEIGHT * workflowZoom;
    const maxPanX = viewportWidth / 2;
    const minPanX = viewportWidth / 2 - worldRenderWidth;
    const maxPanY = viewportHeight / 2;
    const minPanY = viewportHeight / 2 - worldRenderHeight;
    workflowPanX = clamp(desiredPanX, minPanX, maxPanX);
    workflowPanY = clamp(desiredPanY, minPanY, maxPanY);
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
  item.y = clamp(workflowDrag.baseY + dy / workflowZoom, WORKFLOW_CANVAS_MIN_Y, WORKFLOW_CANVAS_MAX_Y);
  const offsetX = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetX || workflowWorldOffsetX()) || 0;
  const offsetY = Number(document.querySelector(".workflow-canvas")?.dataset.worldOffsetY || workflowWorldOffsetY()) || 0;
  workflowDrag.element.style.left = `${item.x + offsetX}px`;
  workflowDrag.element.style.top = `${item.y + offsetY}px`;
  refreshWorkflowCanvasDom();
});

document.addEventListener("pointerup", (event) => {
  if (workflowScissorStroke && workflowScissorStroke.pointerId === event.pointerId) {
    const stroke = workflowScissorStroke;
    workflowScissorStroke = null;
    stroke.el?.remove();
    const cutIdx = Array.from(stroke.cut).map((i) => Number(i)).filter((i) => Number.isFinite(i));
    if (cutIdx.length) {
      pushWorkflowHistory();
      const drop = new Set(cutIdx);
      currentAgent.workflow_edges = (currentAgent.workflow_edges || []).filter((_, i) => !drop.has(i));
      workflowCheckReport = null;
      workflowDryRunReport = null;
      setFeedback(`已剪断 ${cutIdx.length} 条连线。`);
      renderWorkflowStable();
    } else {
      refreshWorkflowCanvasDom();
    }
    return;
  }
  if (workflowGroupDrag && workflowGroupDrag.pointerId === event.pointerId) {
    const drag = workflowGroupDrag;
    workflowGroupDrag = null;
    if (drag.moved) {
      workflowHistoryPast.push(drag.before);
      workflowHistoryFuture.length = 0;
      workflowCheckReport = null;
    }
    renderWorkflowStable();
    return;
  }
  if (workflowMaterialChipDrag && workflowMaterialChipDrag.pointerId === event.pointerId) {
    const drag = workflowMaterialChipDrag;
    workflowMaterialChipDrag = null;
    removeWorkflowDragGhost();
    document.querySelector(".workflow-canvas-wrap")?.classList.remove("is-dropping");
    const overWrap = event.target.closest?.(".workflow-canvas-wrap");
    if (drag.moved && overWrap) {
      const point = workflowCanvasPoint(event);
      if (drag.kind === "template") addWorkflowTemplateNode(drag.id || "plan", point, { openInspector: false });
      else addRuntimeWorkflowNode(drag.refType, drag.refId, point, { openInspector: false });
      renderWorkflowStable();
      setFeedback("已在松手处添加节点，单击节点即可编辑。");
      return;
    }
    // 小位移当作普通点击，交给 click 处理（打开模块预览）。
    if (!drag.moved) return;
  }
  if (workflowMinimapResize && workflowMinimapResize.pointerId === event.pointerId) {
    workflowMinimapResize = null;
    refreshWorkflowCanvasDom();
    return;
  }
  if (workflowSelectionDrag && workflowSelectionDrag.pointerId === event.pointerId) {
    const rect = workflowSelectionDrag.box.getBoundingClientRect();
    workflowSelectionDrag.box.remove();
    workflowSelectionDrag = null;
    const hitIds = [];
    document.querySelectorAll(".flow-node").forEach((node) => {
      const nr = node.getBoundingClientRect();
      const hit = nr.left <= rect.right && nr.right >= rect.left && nr.top <= rect.bottom && nr.bottom >= rect.top;
      if (hit && node.dataset.id) hitIds.push(node.dataset.id);
    });
    if (workflowTerritoryPaintAgent) {
      // 圈地：框住的节点直接划入该 Agent 领地（agent_role 卡本身不被划走）
      pushWorkflowHistory();
      let cnt = 0;
      hitIds.forEach((id) => { const n = currentAgent.workflow_nodes.find((x) => x.id === id); if (n && n.action !== "agent_role") { setNodeOwner(id, workflowTerritoryPaintAgent); cnt++; } });
      setFeedback(`已把 ${cnt} 个节点划入领地（拖动节点出框可移出）。`);
      renderWorkflowStable();
      return;
    }
    if (workflowApiScopePaint) {
      pushWorkflowHistory();
      const sNode = currentAgent.workflow_nodes.find((n) => n.id === workflowApiScopePaint);
      if (sNode) { const set = new Set(Array.isArray(sNode.scope_node_ids) ? sNode.scope_node_ids : []); hitIds.forEach((id) => { if (id !== workflowApiScopePaint) set.add(id); }); sNode.scope_node_ids = Array.from(set); }
      setFeedback(`已把 ${hitIds.length} 个节点纳入 API 范围。`);
      renderWorkflowStable();
      return;
    }
    workflowSelectedNodeIds.clear();
    document.querySelectorAll(".flow-node").forEach((node) => {
      const hit = hitIds.includes(node.dataset.id);
      node.classList.toggle("multi-selected", hit);
      if (hit && node.dataset.id) workflowSelectedNodeIds.add(node.dataset.id);
    });
    renderWorkflowStable();
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
          isIn: start.isIn,
          edgeType: start.edgeType,
          anchor: start.anchor,
        };
        pending = true;
      }
    } else if (!start.moved) {
      workflowPendingPort = {
        nodeId: start.nodeId,
        port: start.port,
        isIn: start.isIn,
        edgeType: start.edgeType,
        anchor: start.anchor,
      };
      pending = true;
    }
    workflowConnection = null;
    setWorkflowConnectingClass(false);
    refreshWorkflowCanvasDom();
    setFeedback(added ? "连线已创建，保存配置后生效。" : pending ? "已选中连线起点，再点另一个节点的相反连接点即可完成。" : "未创建连线：请拖到另一个节点的相反连接点。", added || pending ? "normal" : "error");
    if (added) renderWorkflowStable();
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
  renderWorkflowStable();
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
  const ghost = createWorkflowDragGhost(chip);
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = "copy";
    event.dataTransfer.setDragImage?.(ghost, 22, 22);
  }
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
  if (material.kind === "template") addWorkflowTemplateNode(material.id || "plan", point, { openInspector: false });
  else addRuntimeWorkflowNode(material.refType, material.refId, point, { openInspector: false });
  workflowDraggedMaterial = null;
  removeWorkflowDragGhost();
  renderWorkflowStable();
});

document.addEventListener("dragend", () => {
  workflowDraggedMaterial = null;
  document.querySelector(".workflow-canvas-wrap.is-dropping")?.classList.remove("is-dropping");
  removeWorkflowDragGhost();
});

// 指针拖拽被系统中断（切窗口、触摸取消等）时，也要清理素材拖拽状态与残影。
document.addEventListener("pointercancel", (event) => {
  if (workflowMaterialChipDrag && workflowMaterialChipDrag.pointerId === event.pointerId) workflowMaterialChipDrag = null;
  removeWorkflowDragGhost();
});

document.addEventListener("click", async (event) => {
  if (event.target.closest(".node-port")) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  let target = event.target.closest("[data-route], [data-action]");
  // 根因修复：<body> 上有 data-route（仅供 CSS 布局用）。closest 会让"任意点击"都命中 body，
  // 从而误触发整页 render() —— 这正是点输入框/下拉框就丢焦、下拉闪退、数字光标跳、改字被还原的元凶。
  // 排除 body/html（真正的导航按钮离得更近，仍会被正确命中）。
  if (target === document.body || target === document.documentElement) target = null;
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
    memoryDetailOpen = false;
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
      const inputName = await promptModal("新建方案", "方案名称", "新方案", { placeholder: "给这套流程起个名字" });
      if (inputName === null) return;
      const draft = defaultAgentDraft();
      delete draft.agent_id;
      draft.name = (inputName || "").trim() || "新方案";
      draft.identity_label_source = "manual";
      const result = await api("/api/agents", { method: "POST", body: draft });
      selectedAgentId = result.agent?.agent_id || selectedAgentId;
      selectedWorkflowNodeId = "";
      setFeedback("已创建新方案，可在工作流画布里继续配置。");
      await load();
    }
    if (action === "duplicate-agent") {
      if (!currentAgent.agent_id) throw new Error("请先选择一个已保存的方案再复制。");
      readAgentForm();
      const copy = ensureAgent(clone(currentAgent));
      delete copy.agent_id;
      delete copy.created_at;
      delete copy.updated_at;
      copy.name = `${copy.name || "方案"} 副本`;
      copy.identity_label_source = "manual";
      const result = await api("/api/agents", { method: "POST", body: copy });
      selectedAgentId = result.agent?.agent_id || "";
      setFeedback("已复制方案。");
      await load();
    }
    if (action === "rename-agent") {
      if (!currentAgent.agent_id) throw new Error("请先选择一个已保存的方案。");
      const newName = await promptModal("重命名方案", "新名称", agentDisplayName(currentAgent));
      if (newName === null) return;
      const trimmed = (newName || "").trim();
      if (!trimmed) throw new Error("方案名称不能为空。");
      readAgentForm();
      currentAgent.name = trimmed;
      currentAgent.identity_label_source = "manual";
      const result = await api("/api/agents", { method: "POST", body: clone(currentAgent) });
      selectedAgentId = result.agent?.agent_id || selectedAgentId;
      setFeedback("方案已重命名。");
      await load();
    }
    if (action === "delete-agent") {
      if (!currentAgent.agent_id) throw new Error("当前配置还没有保存，直接新建或切换即可。 ");
      if ((state.agents || []).length <= 1) throw new Error("至少需要保留一个任务模式配置。");
      const name = agentDisplayName(currentAgent);
      if (!(await confirmModal("删除方案", `确定删除方案“${name}”？此操作不会删除归档任务和任务记忆。`, { danger: true, confirmText: "删除" }))) return;
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
    if (action === "workflow-pointer-mode") {
      workflowSelectionMode = false;
      workflowSelectionDrag?.box?.remove();
      workflowSelectionDrag = null;
      renderWorkflowStable();
    }
    if (action === "workflow-select-mode") {
      workflowSelectionMode = !workflowSelectionMode;
      workflowScissorMode = false;
      workflowSelectionMove = null;
      if (!workflowSelectionMode) { workflowSelectedNodeIds.clear(); workflowTerritoryPaintAgent = ""; workflowApiScopePaint = ""; }
      setFeedback(workflowSelectionMode ? "框选模式：拖出范围选中多个节点，右侧弹出移动/复制/删除。" : "已退出框选。");
      renderWorkflowStable();
    }
    if (action === "workflow-scissor-mode") {
      workflowScissorMode = !workflowScissorMode;
      workflowSelectionMode = false;
      workflowSelectionMove = null;
      setFeedback(workflowScissorMode ? "剪刀模式：按住鼠标划过要剪断的连线即可删除。" : "已退出剪刀模式。");
      renderWorkflowStable();
    }
    if (action === "workflow-clear-selection") {
      workflowSelectionMode = false;
      workflowScissorMode = false;
      workflowTerritoryPaintAgent = "";
      workflowApiScopePaint = "";
      workflowSelectionMove = null;
      workflowSelectedNodeIds.clear();
      workflowSelectionDrag?.box?.remove();
      workflowSelectionDrag = null;
      setFeedback("已回到正常操作。");
      renderWorkflowStable();
    }
    if (action === "move-selected-workflow-nodes") {
      if (!workflowSelectedNodeIds.size) return;
      workflowSelectionMove = !workflowSelectionMove ? true : null;
      setFeedback(workflowSelectionMove
        ? "移动模式：在画布上按住拖动，所有选中节点一起移动；完成后再点一下『移动』。"
        : "已结束移动模式。");
      renderWorkflowStable();
    }
    if (action === "workflow-undo") {
      const ok = undoWorkflow();
      setFeedback(ok ? "已回到上一步。" : "没有可撤销的操作。", ok ? "normal" : "warn");
      renderWorkflowStable();
    }
    if (action === "workflow-redo") {
      const ok = redoWorkflow();
      setFeedback(ok ? "已恢复下一步。" : "没有可恢复的操作。", ok ? "normal" : "warn");
      renderWorkflowStable();
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
      renderWorkflowStable();
    }
    if (action === "delete-selected-workflow-nodes") {
      if (!workflowSelectedNodeIds.size) return;
      pushWorkflowHistory();
      const count = workflowSelectedNodeIds.size;
      Array.from(workflowSelectedNodeIds).forEach((id) => deleteWorkflowNodeById(id));
      workflowSelectedNodeIds.clear();
      workflowInspectorOpen = false;
      setFeedback(`已删除 ${count} 个节点。`);
      renderWorkflowStable();
    }
    if (action === "toggle-toolbox-group") {
      event.preventDefault();
      const group = target.dataset.id || "";
      if (workflowToolboxOpenGroups.has(group)) workflowToolboxOpenGroups.delete(group);
      else workflowToolboxOpenGroups.add(group);
      renderWorkflowStable();
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
      const point = workflowCurrentViewCenter();
      if (workflowMaterialDraft.materialKind === "template") addWorkflowTemplateNode(workflowMaterialDraft.id || "plan", point);
      else addRuntimeWorkflowNode(workflowMaterialDraft.refType, workflowMaterialDraft.refId, point);
      renderWorkflowStable();
    }
    if (action === "workflow-zoom-in" || action === "workflow-zoom-out" || action === "workflow-zoom-reset" || action === "workflow-fit" || action === "workflow-focus-content") {
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
      if (action === "workflow-focus-content") {
        ensureWorkflow();
        const nodes = currentAgent.workflow_nodes || [];
        if (!nodes.length) {
          setFeedback("画布中没有节点。", "warn");
          return;
        }
        const edges = currentAgent.workflow_edges || [];
        const connected = new Set();
        edges.forEach((e) => { connected.add(e.from); connected.add(e.to); });
        const orphans = nodes.filter((n) => !connected.has(n.id));
        const mainNodes = nodes.filter((n) => connected.has(n.id));
        // 聚焦目标序列：主体内容 → 依次每个离群节点 → 循环回主体
        const targets = [{ kind: "main", nodes: mainNodes.length ? mainNodes : nodes, label: "主体内容" }];
        orphans.forEach((n) => targets.push({ kind: "orphan", nodes: [n], label: `离群节点「${n.title || n.id}」` }));
        workflowFocusCursor = ((Number.isInteger(workflowFocusCursor) ? workflowFocusCursor : -1) + 1) % targets.length;
        const target = targets[workflowFocusCursor];
        const xs = target.nodes.flatMap((n) => [Number(n.x || 0), Number(n.x || 0) + WORKFLOW_NODE_WIDTH]);
        const ys = target.nodes.flatMap((n) => [Number(n.y || 0), Number(n.y || 0) + WORKFLOW_NODE_HEIGHT]);
        const minX = Math.min(...xs), maxX = Math.max(...xs);
        const minY = Math.min(...ys), maxY = Math.max(...ys);
        const contentWidth = Math.max(1, maxX - minX);
        const contentHeight = Math.max(1, maxY - minY);
        const contentCenterX = (minX + maxX) / 2;
        const contentCenterY = (minY + maxY) / 2;
        const wrap = document.querySelector(".workflow-canvas-wrap");
        const viewportWidth = wrap?.clientWidth || 1200;
        const viewportHeight = wrap?.clientHeight || 760;
        const paddingRatio = target.kind === "orphan" ? 0.7 : 0.9;
        const fitZoom = Math.min(
          (viewportWidth * paddingRatio) / contentWidth,
          (viewportHeight * paddingRatio) / contentHeight,
          1.0
        );
        workflowZoom = clamp(fitZoom, target.kind === "orphan" ? 0.5 : 0.35, 1.0);
        const size = workflowCanvasSize();
        const offsetX = workflowWorldOffsetX(size);
        const offsetY = workflowWorldOffsetY(size);
        workflowPanX = viewportWidth / 2 - (contentCenterX + offsetX) * workflowZoom;
        workflowPanY = viewportHeight / 2 - (contentCenterY + offsetY) * workflowZoom;
        const worldRenderWidth = WORKFLOW_WORLD_WIDTH * workflowZoom;
        const worldRenderHeight = WORKFLOW_WORLD_HEIGHT * workflowZoom;
        workflowPanX = clamp(workflowPanX, viewportWidth / 2 - worldRenderWidth, viewportWidth / 2);
        workflowPanY = clamp(workflowPanY, viewportHeight / 2 - worldRenderHeight, viewportHeight / 2);
        if (target.kind === "orphan") selectedWorkflowNodeId = target.nodes[0].id;
        setFeedback(targets.length > 1
          ? `已聚焦「${target.label}」（再按一次看下一处，共 ${targets.length} 处）`
          : "已聚焦到内容中心。");
      }
      renderWorkflowStable();
    }
    if (action === "toggle-workflow-nav") {
      workflowNavCollapsed = !workflowNavCollapsed;
      renderWorkflowStable();
    }
    if (action === "toggle-workflow-subagents") {
      workflowSubAgentOpen = !workflowSubAgentOpen;
      render();
    }
    if (action === "close-workflow-subagents") {
      workflowSubAgentOpen = false;
      render();
    }
    if (action === "subagent-new") {
      if (await openSubAgentEditor(null)) render();
    }
    if (action === "subagent-edit") {
      const sa = subAgentById(target.dataset.id);
      if (sa && (await openSubAgentEditor(sa))) render();
    }
    if (action === "subagent-delete") {
      const sa = subAgentById(target.dataset.id);
      if (sa && (await confirmModal("删除子Agent", `确定删除「${sa.name || sa.sub_agent_id}」？其领地节点将归还主agent。`))) {
        removeSubAgentById(sa.sub_agent_id);
        render();
      }
    }
    if (action === "agent-role-territory") {
      const __sid = target.dataset.id || "";
      workflowTerritoryPaintAgent = workflowTerritoryPaintAgent === __sid ? "" : __sid;
      workflowApiScopePaint = "";
      workflowScissorMode = false;
      workflowSelectionMode = !!workflowTerritoryPaintAgent; // 选领地即进入框选
      if (!workflowTerritoryPaintAgent) workflowSelectedNodeIds.clear();
      setFeedback(workflowTerritoryPaintAgent ? "圈地中：直接在画布拖出方框，框住的节点就划入这个 Agent 的领地；也可单击节点逐个增减。完成后再点一次按钮。" : "已退出圈地。");
      renderWorkflowStable();
    }
    if (action === "api-scope-range") {
      const __aid = target.dataset.id || "";
      workflowApiScopePaint = workflowApiScopePaint === __aid ? "" : __aid;
      workflowTerritoryPaintAgent = "";
      workflowScissorMode = false;
      workflowSelectionMode = !!workflowApiScopePaint; // 选范围即进入框选
      if (!workflowApiScopePaint) workflowSelectedNodeIds.clear();
      setFeedback(workflowApiScopePaint ? "选范围中：拖框把节点纳入这个 API 范围；也可单击逐个增减。完成后再点一次按钮。" : "已退出选范围。");
      renderWorkflowStable();
    }
    if (action === "workflow-exit-paint") {
      workflowTerritoryPaintAgent = "";
      workflowApiScopePaint = "";
      workflowSelectionMode = false;
      workflowSelectedNodeIds.clear();
      renderWorkflowStable();
    }
    if (action === "assign-subagent") {
      const subId = target.dataset.id || "";
      if (workflowSelectedNodeIds.size) {
        pushWorkflowHistory();
        Array.from(workflowSelectedNodeIds).forEach((nid) => setNodeOwner(nid, subId));
        setFeedback(subId ? "已指派框选节点到子Agent 领地。" : "已把框选节点移出领地（归主agent）。");
        render();
      }
    }

    if (action === "toggle-workflow-toolbox") {
      workflowToolboxOpen = !workflowToolboxOpen;
      renderWorkflowStable();
    }
    if (action === "set-workflow-library-mode") {
      workflowLibraryMode = target.dataset.id === "advanced" ? "advanced" : "basic";
      renderWorkflowStable();
    }
    if (action === "close-workflow-inspector") {
      workflowInspectorOpen = false;
      renderWorkflowStable();
    }
    if (action === "close-workflow-report") {
      workflowReportOpen = false;
      renderWorkflowStable();
    }
    if (action === "close-workflow-menu") {
      workflowContextMenu = null;
      renderWorkflowStable();
    }
    if (action === "copy-workflow-node") {
      readAgentForm();
      pushWorkflowHistory();
      const copied = copyWorkflowNodeById(target.dataset.id || selectedWorkflowNodeId);
      workflowContextMenu = null;
      setFeedback(copied ? "节点已复制，保存配置后生效。" : "未找到要复制的节点。", copied ? "normal" : "error");
      renderWorkflowStable();
    }
    if (action === "delete-workflow-node-menu") {
      readAgentForm();
      pushWorkflowHistory();
      const ok = deleteWorkflowNodeById(target.dataset.id || selectedWorkflowNodeId);
      workflowContextMenu = null;
      workflowInspectorOpen = false;
      setFeedback(ok ? "节点已删除，保存配置后生效。" : "未找到要删除的节点。", ok ? "normal" : "error");
      renderWorkflowStable();
    }
    if (action === "check-workflow") {
      readAgentForm();
      const result = await api("/api/workflow/check", { method: "POST", body: { agent: currentAgent } });
      workflowCheckReport = result.workflow || null;
      workflowReportMode = "check";
      workflowReportOpen = true;
      setFeedback(workflowCheckReport?.valid ? "工作流检查通过。" : "工作流检查发现需要修正的环节。", workflowCheckReport?.valid ? "normal" : "error");
      renderWorkflowStable();
    }
    if (action === "dry-run-workflow") {
      readAgentForm();
      const result = await api("/api/workflow/dry-run", { method: "POST", body: { agent: currentAgent } });
      workflowDryRunReport = result.dry_run || null;
      workflowCheckReport = result.workflow || workflowDryRunReport?.workflow || workflowCheckReport;
      workflowReportMode = "dry_run";
      workflowReportOpen = true;
      setFeedback(workflowDryRunReport?.executable ? "预跑路径可进入，仍需人工确认高风险步骤。" : "预跑发现阻塞，请查看诊断。", workflowDryRunReport?.executable ? "normal" : "error");
      renderWorkflowStable();
    }
    if (action === "auto-layout-workflow") {
      readAgentForm();
      pushWorkflowHistory();
      autoLayoutWorkflow();
      focusWorkflowStart();
      workflowReportMode = "layout";
      workflowReportOpen = true;
      setFeedback("工作流已按阶段自动整理，保存配置后生效。");
      renderWorkflowStable();
    }
    if (action === "select-workflow-node") {
      const __nid = target.dataset.id;
      if (workflowTerritoryPaintAgent) {
        const __n = currentAgent.workflow_nodes.find((n) => n.id === __nid);
        if (__n && __n.action !== "agent_role") { pushWorkflowHistory(); setNodeOwner(__nid, __n.owner === workflowTerritoryPaintAgent ? "" : workflowTerritoryPaintAgent); renderWorkflowStable(); }
        return;
      }
      if (workflowApiScopePaint) {
        const __s = currentAgent.workflow_nodes.find((n) => n.id === workflowApiScopePaint);
        if (__s && __nid !== workflowApiScopePaint) { pushWorkflowHistory(); const arr = Array.isArray(__s.scope_node_ids) ? __s.scope_node_ids.slice() : []; const __i = arr.indexOf(__nid); if (__i >= 0) arr.splice(__i, 1); else arr.push(__nid); __s.scope_node_ids = arr; renderWorkflowStable(); }
        return;
      }
      readAgentForm();
      selectedWorkflowNodeId = __nid;
      workflowInspectorOpen = true;
      workflowContextMenu = null;
      renderWorkflowStable();
    }
    if (action === "workflow-editor-mode") {
      applyWorkflowNodeFromInspector();
      workflowEditorMode = target.dataset.id === "advanced" ? "advanced" : "simple";
      renderWorkflowStable();
    }
    if (action === "open-workflow-global") {
      readAgentForm();
      workflowGlobalOpen = true;
      renderWorkflowStable();
    }
    if (action === "close-workflow-global") {
      applyWorkflowGlobalRules();
      workflowGlobalOpen = false;
      renderWorkflowStable();
    }
    if (action === "apply-workflow-global") {
      applyWorkflowGlobalRules();
      setFeedback("全局规则已应用。记得点 SAVE 保存方案。");
      renderWorkflowStable();
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
      renderWorkflowStable();
    }
    if (action === "add-template-node") {
      addWorkflowTemplateNode(target.dataset.id || "plan");
      renderWorkflowStable();
    }
    if (action === "add-runtime-node") {
      addRuntimeWorkflowNode(target.dataset.refType, target.dataset.refId);
      renderWorkflowStable();
    }
    if (action === "apply-workflow-template") {
      readAgentForm();
      pushWorkflowHistory();
      applyWorkflowTemplate(target.dataset.id || "linear");
      renderWorkflowStable();
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
      renderWorkflowStable();
    }
    if (action === "apply-workflow-node") {
      applyWorkflowNodeFromInspector();
      workflowInspectorOpen = false;
      renderWorkflowStable();
    }
    if (action === "delete-workflow-node") {
      readAgentForm();
      pushWorkflowHistory();
      deleteWorkflowNodeById(selectedWorkflowNodeId);
      workflowInspectorOpen = false;
      renderWorkflowStable();
    }
    if (action === "add-workflow-edge") {
      readAgentForm();
      ensureWorkflow();
      const from = $("workflow-edge-from").value;
      const to = $("workflow-edge-to").value;
      const edgeType = $("workflow-edge-type")?.value || "success";
      addWorkflowEdge(from, to, edgeType);
      workflowDryRunReport = null;
      renderWorkflowStable();
    }
    if (action === "delete-workflow-edge") {
      readAgentForm();
      pushWorkflowHistory();
      currentAgent.workflow_edges.splice(Number(target.dataset.index), 1);
      workflowCheckReport = null;
      workflowDryRunReport = null;
      renderWorkflowStable();
    }
    if (action === "save-agent") await saveAgent(false);
    if (action === "make-default") await saveAgent(true);
    if (action === "apply-task-pattern" || action === "apply-task-pattern-goal") {
      const pattern = (state.task_patterns || []).find((item) => item.pattern_id === target.dataset.id);
      if (!pattern) throw new Error("未找到这条历史计划。");
      const brief = $("brief");
      if (brief) brief.value = taskPatternBriefText(pattern);
      if (action === "apply-task-pattern-goal") {
        const goal = $("goal");
        if (goal) goal.value = pattern.title || pattern.summary || goal.value;
      }
      setFeedback("已带入历史计划建议，请按当前任务再核对一遍。");
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
    if (action === "simulate-trigger") {
      if (!currentAgent.agent_id) throw new Error("请先保存当前方案。");
      const result = await api("/api/workflow/trigger", {
        method: "POST",
        body: {
          agent_id: currentAgent.agent_id,
          source: "manual",
          text: "测试触发",
        },
      });
      if (result.ok === false) throw new Error(result.error || "触发失败。");
      setFeedback(result.triggered ? "触发成功。" : "未触发（可能不满足触发条件）。");
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
    if (action === "load-task-logs") {
      const taskId = target.dataset.taskId;
      if (!taskId) throw new Error("缺少任务 ID。");
      const container = document.getElementById("task-logs-container");
      if (!container) throw new Error("日志容器未找到。");
      container.style.display = "block";
      container.innerHTML = "<div>加载中...</div>";
      try {
        const result = await api(`/api/task/logs?task_id=${encodeURIComponent(taskId)}`);
        if (!result || result.ok === false) {
          container.innerHTML = `<div class='empty'>${esc(result?.error || "无日志数据。")}</div>`;
          return;
        }
        container.innerHTML = taskLogsHtml(result);
      } catch (err) {
        container.innerHTML = `<div class='empty'>加载失败：${esc(err.message)}</div>`;
      }
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
          folder_id: $("memory-folder")?.value || preferredMemoryFolderId(),
          agent_id: $("memory-agent")?.value.trim() || currentAgent.agent_id || task?.agent_id || "",
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
    if (action === "open-memory-detail") {
      selectedMemoryId = target.dataset.id || selectedMemoryId;
      memoryDetailOpen = true;
      render();
    }
    if (action === "close-memory-detail") {
      memoryDetailOpen = false;
      render();
    }
    if (action === "copy-memory") {
      const m = (state.memories || []).find((x) => x.memory_id === target.dataset.id);
      if (!m) throw new Error("未找到这条任务记忆。");
      try {
        await navigator.clipboard.writeText(m.text || "");
        setFeedback("记忆内容已复制到剪贴板。");
      } catch (e) {
        setFeedback("复制失败，请手动选择文本复制。", "warn");
      }
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
    if (action === "select-memory-folder") {
      selectedMemoryFolderId = target.dataset.id || "default";
      render();
    }
    if (action === "new-memory-folder") {
      const folderName = await promptModal("新建记忆夹", "记忆夹名称", "新记忆夹", { placeholder: "如：项目A 记忆 / 客服记忆" });
      if (folderName === null) return;
      const folder = {
        folder_id: "",
        name: (folderName || "").trim() || "新记忆夹",
        agent_id: currentAgent.agent_id || "",
        description: "",
        detail_level: "summary",
        retention_days: 0,
        expose_to_normal: false,
      };
      const result = await api("/api/memory", { method: "POST", body: { action: "save_folder", folder } });
      selectedMemoryFolderId = result.folder?.folder_id || selectedMemoryFolderId || "default";
      setFeedback("已创建新记忆夹。");
      await load();
    }
    if (action === "rename-memory-folder") {
      const folderId = target.dataset.id || selectedMemoryFolderId;
      if (!folderId || folderId === "default") throw new Error("默认记忆夹不能重命名。");
      const folder = memoryFolderRows().find((item) => item.folder_id === folderId);
      if (!folder) throw new Error("找不到这个记忆夹。");
      const newName = await promptModal("重命名记忆夹", "新名称", folder.name || folderId);
      if (newName === null) return;
      const trimmed = (newName || "").trim();
      if (!trimmed) throw new Error("名称不能为空。");
      const result = await api("/api/memory", { method: "POST", body: { action: "save_folder", folder: { ...folder, folder_id: folderId, name: trimmed } } });
      selectedMemoryFolderId = result.folder?.folder_id || folderId;
      setFeedback("记忆夹已重命名。");
      await load();
    }
    if (action === "save-memory-folder") {
      const folder = {
        folder_id: $("memory-folder-id")?.value.trim() || "",
        name: $("memory-folder-name")?.value.trim() || "默认记忆夹",
        agent_id: $("memory-folder-agent")?.value.trim() || "",
        description: $("memory-folder-description")?.value.trim() || "",
        detail_level: $("memory-folder-detail")?.value || "summary",
        retention_days: Number($("memory-folder-retention")?.value || 0),
        expose_to_normal: ($("memory-folder-expose")?.value || "false") === "true",
      };
      const result = await api("/api/memory", { method: "POST", body: { action: "save_folder", folder } });
      selectedMemoryFolderId = result.folder?.folder_id || selectedMemoryFolderId || "default";
      setFeedback("记忆夹已保存。");
      await load();
    }
    if (action === "delete-memory-folder") {
      const folderId = target.dataset.id || selectedMemoryFolderId;
      if (!folderId || folderId === "default") throw new Error("默认记忆夹不能删除。");
      const __fname = memoryFolderLabel(folderId);
      if (!(await confirmModal("删除记忆夹", `确定删除记忆夹“${__fname}”？夹内记忆会回到默认夹，不会被永久删除。`, { danger: true, confirmText: "删除" }))) return;
      await api("/api/memory", { method: "POST", body: { action: "delete_folder", folder_id: folderId } });
      selectedMemoryFolderId = "default";
      setFeedback("记忆夹已删除，相关记忆已回到默认夹。");
      await load();
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
      const nowOn = (currentAgent.module_ids || []).includes(target.dataset.id);
      const mod = (state.integrations || state.modules || []).find((m) => m.module_id === target.dataset.id);
      const nm = mod?.name || target.dataset.id;
      setFeedback(nowOn ? `已把蓝图「${nm}」加入当前方案，记得点保存让它生效。` : `已从当前方案移除蓝图「${nm}」，记得点保存。`);
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
  const action = target.dataset.action;
  // 这些筛选框过去每敲一下就整页 render()+rAF 重新聚焦，会掉焦/丢字（尤其非工作流页根本没还焦点）。
  // 现在统一依赖 render() 内置的同步全局焦点保留，直接 render 即可，焦点和光标都会被保住。
  if (action === "filter-plugins") { pluginFilter = target.value; render(); return; }
  if (action === "filter-tools") { toolFilter = target.value; render(); return; }
  if (action === "filter-blueprints") { blueprintFilter = target.value; render(); return; }
  if (action === "filter-workflow-materials") { workflowMaterialFilter = target.value; render(); return; }
});

function showAuthScreen() {
  const mainApp = $("main-app");
  if (mainApp) mainApp.style.display = "";
}

function showMainApp() {
  const mainApp = $("main-app");
  if (mainApp) mainApp.style.display = "";
}

function isAuthError(error) {
  const message = String(error?.message || "");
  return message.includes("401") || message.includes("403");
}

async function bootWithCurrentToken() {
  showMainApp();
  renderNav();
  await load();
}

function initAuth() {
  const initialToken = new URLSearchParams(location.search).get("token")
    || sessionStorage.getItem("agent_lab_token")
    || "";
  if (initialToken) sessionStorage.setItem("agent_lab_token", initialToken);
  bootWithCurrentToken().catch((error) => {
    setFeedback(isAuthError(error) ? "接口拒绝访问，请检查后端访问配置。" : `连接失败：${error.message}`, "error");
  });
}

document.addEventListener("DOMContentLoaded", () => {
  const refreshBtn = $("refresh");
  if (refreshBtn) refreshBtn.innerHTML = iconImg("refresh", "刷新");
  $("refresh")?.addEventListener("click", load);
  $("agent-switcher")?.addEventListener("click", () => {
    route = "canvas";
    render();
  });
  $("status-view-btn")?.addEventListener("click", () => {
    route = "tasks";
    render();
  });
  $("status-pause-btn")?.addEventListener("click", () => {
    route = "tasks";
    render();
  });
  $("settings-btn")?.addEventListener("click", () => {
    route = "settings";
    render();
  });

  document.addEventListener("keydown", (event) => {
    if (route !== "workflow") return;
    if (document.activeElement?.matches?.(WORKFLOW_FIELD_SELECTOR)) return;
    if (event.key === "f" || event.key === "F") {
      event.preventDefault();
      const btn = document.querySelector('[data-action="workflow-focus-content"]');
      btn?.click();
    }
    if (event.key === "Home") {
      event.preventDefault();
      focusWorkflowStart();
      renderWorkflowStable();
    }
  });

  initAuth();
});

setInterval(() => {
  if (state && globalState.currentAgent) updateStatusBar();
}, 1000);
