# Changelog

## v0.3.3 — 2026-11-23

- 上下文统计写入任务线与独立逐请求数字日志，区分原始/工作视图字符、估算Token、模型报告Token和未报告请求。
- 任务、项目存储和每份记录显示字符数；计数按文件版本缓存，原生对话字符另列，不混作模型上下文。
- 自查修复大容量下最近历史带回过多的问题：工作历史约24k估算Token提前交接，保留最近组最多约4k估算Token，检查下次不会立刻再交接。
- 摘要30秒单次超时，最多两次尝试，超时/空/超长分别记录；管理员停止和工具结果未知仍优先。
- 文件删除后不再落入同轮无版本的旧缓存；嵌套参数摘要有界、历史工作视图幂等、交接续传校验源前缀。
- 用临时文件/模拟模型覆盖创建、修改续写、删除重建、清理、超时、超字数、缺用量、预算中断和终止；无生产调用。


## v0.3.2 — 2026-11-23

- 核实 task_8fcc2a7056c0 中途交接失败：保留日志能确认的事实，不将上一份4837字符草稿误当作失败响应。
- 新增本地文本行范围缓存，检查文件版本与宿主配置；同参数或重叠范围跨轮复用，文件变化后重新读，单次最多120行。
- 模型调用使用临时工作视图：工具正文与未签名的旧编辑参数转证据索引，原始历史不删除；协议要求的签名保持完整。
- read_state(summary) 与持久计划仅注入短索引，移除反复携带整段old/new代码和工具全文的放大路径。
- 交接以去除思考/签名、媒体和重复代码后的材料总结；按下一步所需事实控制工作摘要至800–1600字符，并保存原始完整历史。
- 空/超长摘要有限重试一次，记录错误类型、实际字符、上限、游标和异常原文；仍异常时标明降级与回查入口，预算或用户停止不被兜底吞掉。


## v0.3.1 — 2026-11-23

- 全宽方案能力图，插件/内置工具节点展开、单工具开关、全组开关及批量操作；disabled_tools 在完全权限下也作为硬限制生效。
- 删除方案技能选择，运行时沿用 AstrBot 启用技能和人设筛选；任务提示词带上真实人设，保留 Bot 写出的交付正文。
- 收尾与验证节点读取全部已完成步骤对应的成功日志；无效/旧版/未知证据仍需补齐，缺证据不再自动创建结束审批。
- 已批准计划与收尾授权归档为已使用，原批准决定单独保留；未执行的操作记录取消原因。
- 独立任务单轮工具上限默认24；同轮无中间写入的重复读取复用证据，工具长输出明确分页，原始结果完整保存。
- 无stage小步骤不再逐项强制交接；显式stage、轮数/容量上限仍先存原记录再交接。
- Shell同命令声明变量及显式env先解析再核范围；未解析变量只提示修正，不计危险重试；find只核查目标路径。


## v0.3.0 — 2026-11-23

- 完全权限单独使用自主执行策略；目录、搜索、普通文件改动和少量清理不再因工具类型或连接符要求批准。
- 后端对越界、清空/破坏性操作、敏感路径及管理员审批线只拒绝本次动作，由主 Agent 主动申请精确审批。
- 同一步骤累计3次被兜底拒绝后暂停并说明原因，拒绝计入工具预算；不自动创建审批，管理员可明确恢复。
- 授权路径与计划范围分离；管理员设置同步当前任务，旧版完全权限自动审批卡迁移作废，主动申请保留。
- 工具结果保存完整脱敏文本，续跑包含参数与证据，支持分页读回并复用刚执行的审批结果。
- 常见中文停止/结束/暂停指令容忍标点；提供受当前管理员消息约束的日常控制工具。
- 画布「全局」迁至独立方案设置页；插件禁用只使用持久字段，取消勾选不再残留。
- 完成精简代码与状态验证；真实 Bot 体验由使用者验收，不宣称新增操作系统沙箱。


## v0.2.9 — 2026-11-22

- 任务详情占满内容区，移除与左侧项目树重复的任务选择列，保留返回完整任务列表的入口。
- 任务清单前置，显示步骤编号、完成数量和状态；任务消息线移到下方，支持限高滚动、键盘展开/收起，刷新时保留展开状态和阅读位置。
- 「途中引导」与「调整本任务预算」集中在消息线下方的「途中设置」，按原有任务状态显示可用操作。
- 开发保护表单统一间距与对齐；权限档位选择框与相邻路径、风险输入框均为80px高、等列宽，数字输入框保持44px高，保存按钮统一图标与样式。
- 新增1440/1100/820/390四种宽度的任务布局回归，覆盖消息滚轮、折叠、任务切换和表单尺寸。

## v0.2.8 — 2026-11-22

- 项目运行设置移入「开发保护」页，直接编辑权限、范围与预算，保留 AstrBot 原生工具上限同步。
- 「摘要与存储」新增按项目自动保存的互通设置。日常聊天与同项目任务分别配置开关和字数上限，已有项目沿用原默认值。
- 长任务按实际阶段保存完整原记录和模型交接摘要，保存成功后才整理活跃历史；移除超过40条消息直接裁剪的旧逻辑，接管任务执行器的上下文整理。
- 开发保护开放任务上下文容量、整理触发比例、阶段连续轮数和摘要字数。默认 1,000,000 Token、70%、8轮、6000字；模型容量较小时取较小值，摘要请求也预留输出空间。
- 普通拆分、重排、补测试和保留目标的返工，经模型核对实际差异后记录并继续；目标、验收、预算和解除用户约束仍需批准。计划修订保存旧成果与证据，返工要求新验证，不重置累计预算或扩大权限。
- 新增按任务分页回查交接原记录的工具；交接失败保留历史并暂停。兼容两种 AstrBot 上下文管理接口，阶段边界停止后下一轮清除旧停止标记。

## v0.2.7 — 2026-11-21

- 项目运行设置独立于画布，原生工具上限与 AstrBot 配置档对齐，现有暂停任务可以单独调整总预算。
- 默认标准开发，另有只读与完全访问。记录普通范围外操作；高危操作可在执行前成批申请，拒绝后停止该批次。
- 审批消息使用中文摘要，聊天支持直接回复「批准」「拒绝」与中文任务控制命令；批准按持久参数续接。
- 修复预算停机原因被旧步骤遮挡、每轮超限判定丢失、工具证据与正文分开发送的问题。任务人格与近期历史缩减。

## v0.2.6 — 2026-11-11

- 机器人身份只来自 AstrBot 中已启用且已加载的平台实例；历史项目不会制造虚假可选 Bot。单击切换、双击或“设为默认”写入服务端偏好，下次打开自动恢复。
- 新增可选任务进展简报。Bot 可用 `agent_lab_progress` 主动说清已确认结果、当前动作和下一步；开始、检查点、反问、审批、交付共用同一任务消息线和 task_id。简报按机器人开关、最短间隔、合并待发内容和80条上限控制；必要的反问/审批/交付不受简报开关阻挡。
- 任务消息单独写入任务记忆目录，发送失败标记为未知且不自动重发；管理员在发送期间停止任务时，终态优先，消息回写不会复活或覆盖任务。
- 画布素材库从后端 NodeExecutorRegistry 能力表读取执行类型、端口和可用状态，补齐 HTTP、插件提示、脱敏、经验草稿、任务记录、待发消息和记忆归档素材；停用的心跳/定时/未实现嵌套工作流明确隐藏或标记。
- 连接路径使用独立的圆角正交路由模块，有限候选车道避开节点；移除拖动节点时强制写死自动路径为手工 route_hint 的旧逻辑，保留用户明确设置的手工路径。线条增加对比度、统一箭头和选中反馈。
- 画布页复用项目侧栏的宽度、字体和内边距；增加可打断的波纹、指针局部光晕和轻量弹性波纹，尊重减少动态效果，不使用常驻动画循环或 WebGL。
- 修复节点编辑后直接点击顶部保存漏存字段，补齐任务记录的变量/JSON字段，非法JSON明确报错；修复 WebUI 归档后交付消息丢失立项管理员身份、超长审批内容挤掉批准/拒绝命令的问题。
- 对照 AstrBot 4.29.4 的 `context.send_message` 源码核对私聊发送边界；19项后端行为测试、56项浏览器交互检查、6种路由场景及10项静态契约通过。没有进行真实平台/模型联调。

## v0.2.5 — 2026-11-11

- WebUI 改为黑白灰主体、绿色点缀；项目/预案/设置采用统一铺满边界，去掉根页面反复入场动画，统一旧集成页和节点按钮样式。
- 简化导航：移除底部身份块；存储固定底端；机器人身份与插件集成集中到齿轮设置。“全部方案”整理为用途明确的可选工作流预案库。
- 新增平台实例身份投影与项目绑定，兼容旧来源 UMO；同类型多 Bot 不混淆。跨实例选择/移入项目在后端拒绝，前端只切换查看范围。修正项目身份与顶部任务状态不一致、查看按钮不定位任务的问题。
- 恢复原画布右侧竖工具栏与素材窗几何，删除上版换边/拖宽代码；保持72%初始缩放。素材滚动内容避开窄窗换行顶栏，抽屉关闭不再因 transform 覆盖跳位。
- 使用 @xyflow/system 0.0.74 的圆角连线路径和贝塞尔预览；保留手工线路提示，增加15px端口吸附。离线随包分发4,268字节路径代码，无React/Svelte/D3运行时。
- 项目自动刷新改为10秒轻量目录请求，内容未变不重绘，编辑时跳过；减少目录计算中重复读取索引与活动任务，普通连线不再重复跑障碍绕行算法。
- 修复项目/预案搜索在页面切换后显示结果失配，预案编辑/复制/删除增加重复点击保护，补齐独立控制台新静态资源路由。
- 新增真实Edge沙箱iframe的36项交互检查、三种宽度截图检查，以及12项真实后端模块/临时文件/Quart测试；全部通过。生产AstrBot、真实模型和大规模任务负载未实测，报告明确列出边界。

## v0.2.4 — 2026-11-11

- 新增项目目录、任务分类/切换、项目方案关联、Bot 项目工具及项目摘要；保留原画布模块、绿色配色和子代理配置。
- 默认72%画布比例，素材面板在iframe可用空间内布局，支持左右换边、拖动/键盘调宽及平滑收起；顶栏常驻，窄窗口自适应。
- 项目树采用真实展开过渡；目录卡片、选项、任务面板、画布抽屉提供轻量动效，支持减少动态效果；后台刷新不覆盖草稿。
- 管理员停止/按现状交付先写终态标记，再收尾归档，跳过模型验收；阻止旧回调和旧自动交付覆盖管理员决定。
- 新增结构化反问、选项/推荐/自由回答和恢复；回答写入任务约束。未明确的问题不会被默认选项自动批准。
- 取消日常自动载入完整方案/全局历史模板，任务通过独立conversation保存；同项目摘要按限额读取，日常共享需明确开启，工具过程不逐条刷日常聊天。
- 显示项目/任务文件和缓存大小、只读记录预览、原生对话内容大小；清理范围带摘要校验，删除关联任务记忆/历史而不触碰开发源码目录。
- 移除心跳/定时前端及旧自动调度恢复；开发保护页发现已有Git/回滚类工具，明确不同回滚范围。
- 更新项目使用技能、静态检查和交付报告。未运行AstrBot、模型、浏览器交互或实际回滚/删除测试。

## v0.2.3 — 2026-11-10

- 在 v0.2.2 原设计上增量修改；保留全部模块 JSON、原布局/配色、全屏画布、循环、并行、子代理和高级配置，没有迁移 React 工作台。
- Bot 可按标题/简介选择画布方案，也可不应用画布。具体任务计划独立于画布节点，支持版本审批、步骤证据、途中引导和事件续轮。
- 主任务沿用来源 Bot 模型与 Persona，详细任务对话使用独立原生 conversation；不切换日常当前对话，不停用日常会话插件。
- 新版工具上下文和执行器集中到 AstrBotBridge，保留框架权限包装；高风险工具精确审批、预算与暂停检查置于执行前，工具结果未知时等待核对。
- 提取 TaskControl、node_policy、web_api，减少 main 中重复生命周期/执行规则；服务状态不再依靠中文提示词猜测。
- 修复旧归档误删新任务、归档后复活、API 假成功、模拟触发实际执行、任务草稿丢失、空图/空连线自动补默认、节点访问被误判完成等问题。
- 原画布按帧合并刷新、缓存节点索引与路径、平移缩放仅更新视口、拖线独立预览；保留绿色配色并补选中/悬停/抽屉/忙碌反馈，连线先选中再删除。
- 修复原生沙盒 iframe 存储访问与 URL 构造兼容；原生 bridge 和独立 fetch 统一检查业务失败。
- 归档摘要不再自动共享，任务资料按来源读取；API 提供商选项支持真实模型集成调用。
- 定时使用真实来源与管理员身份；主循环不靠心跳。明确报告部分未接执行能力的登录态节点，不再假称远端刷新成功。
- 仅静态检查，未运行 AstrBot、真实工具/模型或浏览器手感验证。详见更新报告。

## v0.2.2 — 2026-07-20

- 修复 AstrBot 最新版无法发现插件 UI：将页面从已废弃的 `_dashboard/` 迁移到最新规范 `pages/agent-lab/index.html`。
- 接入 `window.AstrBotPluginPage` bridge：GET 使用 `apiGet`、POST 使用 `apiPost`，查询参数从 URL 中解析后通过 bridge 传递。
- 保留独立 8788 控制台的 fetch 模式，原生页面和独立页面继续共用同一套前端资源。
- 新增 `scripts/plugin_page_bridge_smoke.js`，验证 state GET、带 query 的 logs GET 和 finish POST 均通过 AstrBot bridge。
- 更新插件页面入口说明：在 Dashboard 插件管理的 Agent Lab 插件详情中打开 `agent-lab` 页面。

## v0.2.1 — 2026-07-20

- 统一任务结束协议：普通完成、Bot 主动完成、WebUI 完成和工作流 `archive_task` 现在共用完成校验，不再一边过严、一边绕过 verifier。
- 新增 `finish_override` 管理员结束审批。证据或报告不足时自动生成审批；批准后自动归档，并记录批准人、缺口、最终总结和结构化报告。
- 审批权限接入 `workflow_admin_ids`：配置管理员后，非管理员不能通过聊天命令处理审批。
- 修复 WebUI 假成功：完成被阻止时 API 返回 `ok: false`、缺口和审批信息，前端不再错误显示“任务已完成归档”。
- 增加任务暂停、恢复、完成、停止并归档、彻底删除操作；彻底删除会先执行安全 teardown，再删除归档和关联任务记忆。
- 修复任务页路由误调用方案页的问题。
- 修复超长任务记忆撑破布局：列表摘要截断、详情独立滚动、正文最大高度、抽屉滚动和响应式布局。
- 将前端迁移到 AstrBot 原生 `_dashboard` 插件页面，独立 8788 控制台复用同一套资源并自动切换 API Base。
- 独立控制台支持 `standalone_webui_token`；非本机监听未配置 Token 时拒绝启动。
- 删除 Agent 和任务记忆改用 POST action，兼容 Dashboard 旧版插件 API 路由。
- 修正并扩充 smoke tests：覆盖管理员结束覆盖、权限拒绝、结构化归档报告、关联记忆删除和 `_dashboard` 发现。

## v0.2.0 — 子Agent 泳道 / 多Agent 协同 / 并发治理 + 素材审计

- 子Agent「泳道」：新增 `SubAgentSpec`(模型/角色/工具范围/领地/并发上限/限速)，内嵌 `AgentSpec.sub_agents`；节点新增 `owner` 归属字段；零迁移兼容老方案。
- 并发治理：并行 worker provider/工具/角色按 node.owner 的子Agent 解析；三层并发闸(泳道内按 owner 分桶 / 方案级 / 全局 tick 闸)；心跳错峰 jitter；资源锁(同标签跨泳道串行)；每泳道限速。新增配置 `global_max_concurrent_ticks`/`heartbeat_jitter_seconds`/`workflow_parallel_concurrency`。
- 多Agent 协同：共享黑板(`TaskState.workflow_data["blackboard"]`)+ 5 个协同节点(任务分配/报告整理/意见传达/事项讨论/汇总决策，debate 复用现成校验)。
- 素材体系审计与整改：64 个可见素材逐项过三准则(功能唯一/可配置/插入生效)，整改后 56✅/8🟡/0❌(docs/MATERIAL_AUDIT.md)；补齐协同节点编辑表单、隐藏重复换皮件、修正 memory_filter 元数据。
- n8n 对标补空白：新增 `note`(便签/No-Op) 与 `delay`(延时≤300s) 节点。
- 入口统一：入口节点检查器重构为单一「触发条件表」(暗号/命令/关键词/正则/自然语言/定时/插件事件/Webhook/启用/谁能触发/进入前确认三档)，合并原自动化面板与入口规则两处配置；自动化面板触发段改为摘要+指引，避免重复与覆盖。
- 确认三档：EntryPolicy 新增 confirmation_mode(off/fixed/prompt)，注入提示反映「关闭/固定话术/提示词生成」。
- 前端：子Agent 注册表抽屉(增删改查)、框选「指派」圈地、节点按 owner 上色、领地框渲染、provider free-text；协同/延时节点的画布模板与编辑表单。
- 自检：models/concurrency/orchestration/subagent-ui 四套 smoke + compileall + node --check 全过。可视化交互需在 AstrBot WebUI 实测。


## v0.1.1

- Added `NodeExecutorRegistry` and canonical workflow runtime types so canvas nodes normalize into entry/state/decision/parallel/tool/api/memory/guard/validation/notification/terminal/react categories.
- Added real backend executors for entry checkpoints, state checkpoints, task-memory read/write, registered API calls, deterministic route/retry/validation, approval/wait gates, notifications, terminal handoff, and parallel branches.
- Added `TaskState.workflow_data` with `node_outputs`, `variables`, `react_traces`, and execution counts so node outputs can feed later nodes and ReAct handoffs are auditable.
- Added workflow-report fields for executable nodes vs ReAct handoff nodes, plus archived Markdown visibility for node outputs and ReAct handoff summaries.
- Enforced AgentSpec tool isolation for direct tool nodes, direct API nodes, and parallel API workers so executable canvas nodes cannot bypass whitelist/no-external settings.
- Added `docs/RUNTIME_EXECUTOR.md` as a third-party audit reference for executable nodes, ReAct handoffs, node data flow, and isolation boundaries.
- Added a lightweight `WorkflowRuntime` so `tick` first advances deterministic canvas nodes, executes parallel branches, and hands only open-ended nodes to ReAct/tool-loop execution.
- Tightened task-memory isolation: archive summaries remain reviewable exposure candidates, while workflow/private memory candidates are hidden from normal chat unless explicitly exposed.
- Split task-mode settings, workflow canvas, and task memory into separate WebUI pages so the canvas can occupy the full workspace while settings stay readable.
- Reworked the workflow page into a full-screen background canvas with hidden normal topbar/feedback chrome, floating controls, wheel zoom, blank-canvas panning, a nav expand icon, and modal node editing.
- Added a Dify/n8n-style workflow workbench with collapsible left nav, right module drawer, right node inspector, right-click copy/delete, colored node-matching edges, viewport preservation after drag, and workflow dry-run diagnosis.
- Added workflow node fields for path/URL, upstream variable, output variable, and memory tags, plus fixed modules for document input, task-memory read/write, and rollback/resume entry.
- Added a dedicated task memory page with detail, accept/reject/delete actions, continuation draft, and archived-task rollback entry.
- Enlarged the workflow editor into a full-screen canvas with minimap, blank-canvas panning, wheel zoom, larger node port hit targets, and drag-or-click edge creation.
- Expanded the workflow node library with grouped entry/isolation/memory/planning/parallel/tool/API/safety/validation/exit modules plus code-task and memory-resume templates.
- Added executable parallel workflow branches through `agent_lab_run_parallel_workflow`, including registered API workers, restricted prompt/plugin/tool workers, `parallel_runs` state, and task-detail visibility.
- Rebuilt the Canvas page as the primary task-mode cockpit with explicit global-vs-entry application scope and command/natural/WebUI entry channels.
- Added persisted AgentSpec fields for application scope and entry channel, and injected them into runtime task-mode prompts.
- Added WebUI task-entry controls beside the selected AgentSpec and exposed cancel/archive plus approval approve/reject actions from the Tasks page.
- Reworked workflow visualization into a staged board with editable nodes, edge chips, add/delete controls, and advanced JSON kept as a fallback.
- Added standalone `/api/modules` route compatibility for blueprint import/update.
- Fixed runtime smoke test shutdown when AstrBot SDK import leaves helper threads alive.

## v0.1.0

- Initial Agent Lab plugin.
- Standardized repository identity around `astrbot_plugin_agent_lab`.
- Added beginner-facing README guidance for features, first run, WebUI access, and Dashboard security expectations.
- Added AgentSpec and TaskState persistence in plugin_data.
- Added private-session Agent Mode commands and LLM tools.
- Added entry and exit summarizers using AstrBot providers.
- Added session-level plugin override guard.
- Added manual tick and cron basic heartbeat runner.
- Added soft approval workflow for dangerous operations.
- Added plugin Page for WebUI testing and visualization.
- Added `agent-mode` Skill.
- Added built-in module registry for checkpoint, approval, heartbeat, memory, handoff, and flow adapters.
- Added explicit `agent_lab_read_state` and `agent_lab_update_state` tools.
- Added Agent run hooks to log tool start/end/done events into task_state.
- Added packaged module manifests for LangGraph, OpenAI Agents, Deep Agents, CrewAI, and Microsoft Agent Framework adapters.
- Added AstrBot builtin Computer Use tool catalog and default coding tool profile.
- Added morning acceptance checklist.
- Added mode-aware natural-language decision protocol synchronized through Skill and runtime prompts.
- Added WebUI Task Review, approval resolution, cancel flow, Archives, module toggles, and policy controls.
- Added multi-AgentSpec selection, duplication, creation, default-agent switching, and selected-Agent task starts.
- Added WebUI custom module editor and `/modules` API for saving adapter manifests.
- Reworked the WebUI into a Chinese structured console with separate task runtime, agent rules, capability switches, and module editor areas.
- Added clearer WebUI button feedback, disabled states, and local preview mode for layout testing.
- Removed hardcoded role names from defaults/docs; derived default and task-time Agent labels from AstrBot persona/config when available.
- Made raw AgentSpec defaults runtime-following as well, so plugin configuration no longer carries a baked-in bot display name before AstrBot resolves Persona/config.
- Replaced the Dashboard plugin Page with a standalone WebUI server (`standalone_webui_host`/`port`/`token`) and a five-section Agent Lab console.
- Separated AstrBot plugin isolation, registered tools, skills, and external integration blueprints in the WebUI.
- Added tool filtering so tools from Agent-disabled plugins are removed from Agent Mode runs.
- Added per-blueprint settings support through `module_settings`, `settings_schema`, and `default_settings`.
- Limited WebUI Tasks/state task listing to active tasks; finished and cancelled tasks live under Archives.
- Protected Agent Lab from being disabled by its own session plugin overrides.
- Added runtime identity source reporting so the standalone WebUI shows whether the current Bot label comes from AstrBot Persona, AstrBot config, or fallback.
- Replaced the default identity marker with `astrbot_runtime` while preserving compatibility with existing `astrbot_persona` AgentSpec files.
- Added registries for custom APIs, encrypted credentials, memory entries, task snapshots, workflow JSON, and provider-reported token usage.
- Added `agent_lab_call_custom_api`, a managed tool for calling WebUI-registered custom APIs with encrypted credentials.
- Added WebUI-editable `agent-mode` custom Skill rules saved under plugin_data and synced into the installed Skill.
- Added structured Canvas workflow node and edge editing, with JSON kept as an advanced fallback.
- Added per-AgentSpec tool risk overrides, risk-grouped tool UI, and editable approval scopes/actions.
- Added global-plugin-disabled hard boundary: Agent Mode can further disable plugins but cannot revive AstrBot globally disabled plugins.
- Reworked Plugins & Integrations into a left-subpage console; registered tools are now collapsible by source plugin and plugin-off tools are removed from the current Agent tool selection.
- Clarified external blueprints as rule modules rather than AstrBot plugins or direct tools, with visible settings schema/defaults in the WebUI.
- Added heartbeat health payloads (`online`/`idle`/`stale`/`blocked`/`off`) and monitor-page timeout badges/log rows.
- Added editable entry/exit summary rules in the Skills Rules page; they are saved in plugin_data and appended to the installed `agent-mode` Skill.
- Tightened Canvas wording around Agent Mode configuration so it does not read like a bot identity/persona editor.
- Kept blank WebUI AgentSpec names bound to `astrbot_runtime`, so new configurations inherit the current AstrBot Persona/config label instead of becoming a fixed template name.
- Added save-time AgentSpec sanitation so tools from globally disabled or Agent-disabled plugins cannot be persisted back into the enabled tool list.
- Added a clean WebUI AgentSpec draft flow with an explicit enabled/disabled control, so New is no longer just Duplicate with a blank name.
- Added WebUI import/update for external blueprint manifests, persisted under plugin_data modules for framework-upgrade compatibility.
- Rendered blueprint `settings_schema.properties` as fine-grained WebUI controls while keeping advanced JSON import/export as a compatibility fallback.
- Expanded dashboard Agent rows with per-configuration health, active task count, trigger count, Token total, and pending approval count.
- Reworked Task/Memory details into structured state fields, pending approvals, snapshot timelines, archive selection, and memory status filters.
