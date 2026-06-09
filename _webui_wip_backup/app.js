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

const WORKFLOW_NODE_WIDTH = 300;
const WORKFLOW_NODE_HEIGHT = 168;
const WORKFLOW_LANE_WIDTH = 560;
const WORKFLOW_CANVAS_MIN_WIDTH = 7200;
const WORKFLOW_CANVAS_MIN_HEIGHT = 2800;
const WORKFLOW_CANVAS_MIN_X = -8000;
const WORKFLOW_CANVAS_MAX_X = 24000;
const WORKFLOW_CANVAS_MIN_Y = -6000;
const WORKFLOW_CANVAS_MAX_Y = 16000;
const WORKFLOW_WORLD_WIDTH = WORKFLOW_CANVAS_MAX_X - WORKFLOW_CANVAS_MIN_X;
const WORKFLOW_WORLD_HEIGHT = WORKFLOW_CANVAS_MAX_Y - WORKFLOW_CANVAS_MIN_Y;
const WORKFLOW_MINIMAP_MIN_WIDTH = 104;
const WORKFLOW_MINIMAP_MIN_HEIGHT = 84;
const WORKFLOW_MINIMAP_MAX_WIDTH = 360;
const WORKFLOW_MINIMAP_MAX_HEIGHT = 260;
const WORKFLOW_FIELD_SELECTOR = ".workflow-inspector-drawer input, .workflow-inspector-drawer select, .workflow-inspector-drawer textarea, .workflow-tool-drawer input";
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
  "manual",
];
const WORKFLOW_PERMISSION_PROFILES = ["ordinary", "work", "code", "web", "danger"];
const WORKFLOW_REF_TYPES = ["", "tool", "api", "plugin", "skill", "module", "workflow"];
const WORKFLOW_WORKER_TYPES = ["", "GenericWorker", "ResearchWorker", "CodeReaderWorker", "PatchWorker", "TestWorker", "ApiWorker", "ToolWorker"];
const WORKFLOW_TRIGGER_TYPES = ["command", "natural", "message_monitor", "keyword", "regex", "schedule", "plugin_event", "webhook", "manual_webui"];
const WORKFLOW_CHAT_TYPES = ["private", "group"];
const WORKFLOW_EDGE_TYPES = ["success", "failed", "uncertain", "error", "retry", "timeout", "approved", "rejected", "always"];

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
    params: { cron: "*/15 * * * *" },
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
];

const sections = [
  ["dashboard", "仪表盘", "总览"],
  ["canvas", "任务模式设置", "定规则"],
  ["workflow", "工作流画布", "拼流程"],
  ["memory", "任务记忆", "查记忆"],
  ["tasks", "任务控制台", "看进度"],
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
let workflowLibraryMode = "basic";
let workflowToolboxOpenGroups = new Set();
let workflowMinimapWidth = 128;
let workflowMinimapHeight = 128;
let workflowMinimapResize = null;
let workflowSelectionMode = false;
let workflowSelectionDrag = null;
let workflowSelectedNodeIds = new Set();
let workflowHistoryPast = [];
let workflowHistoryFuture = [];
let workflowDragGhostEl = null;

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

function token() {
  return (
    sessionStorage.getItem("agent_lab_token")
    || $("token")?.value.trim()
    || $("auth-token-input")?.value.trim()
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
  const snapshot = workflowUiSnapshot();
  render();
  restoreWorkflowUiSnapshot(snapshot);
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
    message_monitor: "消息监听",
    keyword: "关键词",
    regex: "正则",
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

function checkboxGroupHtml(name, values, selected, labeler) {
  const selectedSet = new Set(selected || []);
  return values.map((value) => `
    <label class="check-line"><input type="checkbox" name="${esc(name)}" value="${esc(value)}" ${selectedSet.has(value) ? "checked" : ""} />${esc(labeler(value))}</label>
  `).join("");
}

function checkedValues(name) {
  return Array.from(document.querySelectorAll(`input[name="${name}"]:checked`)).map((item) => item.value);
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
      id: uniqueWorkflo