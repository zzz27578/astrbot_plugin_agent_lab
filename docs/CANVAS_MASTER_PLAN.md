# Agent Lab 画布重构总计划（MASTER PLAN，断点续做用）

> **这份文件是唯一权威计划**，合并了 v1/v2/v3/v4 四轮蓝图 + 插件嵌入新思路。任务中断后，在新会话把本文件发给 Claude，它读完本文件 + 核对一遍代码现状，即可从"未完成"处继续。
> 原则：**不改后端契约的乱来；动代码前先核对锚点行号（代码会变）；每批做完跑 `node --check` + 结构自检；视觉留用户自查。**
> 仓库：`astrbot_plugin_agent_lab/`，前端 `webui/app.js`(~7559行) / `webui/style.css` / `webui/index.html`，后端 `main.py`(~8773行) / `agent_lab/*.py`。

---

## 0. 给接手会话的快速上手

1. 先读本文件全文。
2. 核对锚点：`grep -n "function renderCanvas\|function workflowInspector\|const WORKFLOW_NODE_TEMPLATES\|def _execute_notify_node\|def _maybe_trigger_message_monitor" webui/app.js main.py`（行号会漂，以 grep 为准，不要信本文件里写死的行号）。
3. 看"进度状态表"(第 2 节)确认哪些已 ✅、哪些 ⬜ 待做。
4. 编辑用 python 原子写（temp+fsync+os.replace），每次写完 `cp webui/app.js /tmp/_c.mjs && node --check /tmp/_c.mjs`，确认无 NUL、尾部完整。**不要用会话缓存的行号直接 Edit，先重新 grep。**
5. 不做浏览器验证（环境隔离）；用 jsdom harness 或结构 grep 自检。

---

## 1. 项目定位（背景，别跑偏）

Agent Lab = AstrBot 的**可视化自动化工作流层**。两种形态：①长任务 Agent Mode（心跳续跑）②事件/静态自动化（群管、定时、插件联动）。**画布是核心交互面**，节点=用户定义"机器人怎么干活"的唯一结构化入口。后端是全功能引擎，前端只接了约一半——本计划的核心就是补全 + 让节点编辑真正对应各自职责。

> **总铁律（贯穿全计划）**：节点的前端改造是**全覆盖**的——**每一个节点**都要按"后端真读什么字段→编辑页就放什么"的方向改，用户点名的只是示例方向，不是范围上限。**不允许任何旧节点原样保留**：每个节点要么定制编辑页、要么合并、要么删除、要么明确标成"自动节点"。详见 5.1 的全节点处置总表。

---

## 2. 进度状态表（断点续做看这里）

| 模块 | 状态 | 说明 |
|---|---|---|
| 恢复可运行基线（废弃半成品 app.js，用 HEAD 6906 行版） | ✅ 已完成 | 备份在 `_webui_wip_backup/` |
| 输入框/下拉失焦 bug | ✅ | 根因是半成品；已修 + 加 liveRefresh 编辑保护 |
| 节点编辑器"填空题"框架（WORKFLOW_SIMPLE_FIELDS + 简易/高级切换） | ✅ 已扩展 | 已覆盖发送、记忆运营、变量/转换、账号补全、插件提示词、全局控制、Skill 进化等后端 action |
| 拖拽落点 + 单击编辑 | ✅ | |
| 类型化端口 + 按 edge_type 上色 | ✅ | workflowNodePorts / workflowEdgeColor 已建 |
| 重试端口（重试口在右、其余在左）+ 文案修正 | ✅ | |
| 账号/登录态节点组 | ✅ | credential_ref 等 6 个 |
| 全局规则抽屉（system_prompt/approval/skills/隔离） | ✅ 初版 | 要并入"全局控制节点"扩展（第三批） |
| 方案管理页（删设置页、并入任务控制台） | ✅ | renderCanvas 现在是方案管理页 |
| 画布顶栏精简 + 自动隐藏 + 工具条精简 | ✅ | |
| 生效范围节点（scope_filter 填表） | ✅ | 已并入监听规则/范围控制，支持谁能触发命令 |
| 默认工作流重建（正确 edge_type + 重试逻辑） | ✅ | |
| **发送能力做实（真发消息/图片/表情/提示词回复）** | ✅ 已完成 | 后端 _send_workflow_outbox_item + _workflow_message_chain 已实现；前端 WORKFLOW_SEND_FIELDS 已完整 |
| **监听放开拍一拍/notice 非文字事件** | ✅ 已完成 | _maybe_trigger_message_monitor 已放开 poke/notice（1504行判断） |
| **消息监听入口合并节点 + 谁能触发命令** | ✅ 已完成 | listenerRule 已实现；旧 command_entry/keyword_entry/manual_webui_entry 素材已删除 |
| **outbox/deliver 可视化 + 真投递** | ✅ 已完成 | 真投递已实现；方案管理/任务详情展示 outbox + delivery history |
| 后端未暴露能力全部补前端 | ✅ 已完成 | 运行监控、预算/限制、runtime 审计、模拟触发、任务日志、blockers/watchdog、reports/records、记忆/变量/账号素材、task_patterns、蓝图 schema 设置均已接入 |
| 节点编辑页逐个按职责精修 | ✅ 阶段完成 | 主要后端 action 已进入定制 simple-fields；控制流/记忆/发送/插件/全局控制/Skill 节点已有职责化表单 |
| 记忆夹体系 + 方案级记忆隔离 | ✅ 已完成 | storage/API 已支持 memory_folders；前端可新建/编辑/删除记忆夹，保存记忆会写入 folder_id + agent_id |
| 插件接管/伪装管理员/插件嵌入提示词节点 | ✅ 阶段完成 | 插件隔离、插件提示词节点、发送交给插件、静态冲突提示已接入；伪装管理员仍受适配器能力边界限制 |
| Skill 进化节点 | ✅ 安全版完成 | 节点与表单已接入，默认生成 skill_rules 草稿并走人工审批 |
| 全局控制节点 | ✅ 已完成 | 默认工作流包含 global_control；全局抽屉可配置隔离、技能、预算、工具范围和重复失败阈值 |

---

## 3. 第一批 · 让核心场景真能跑（最高优先）

> 目标验收：**监听到关键词或拍一拍 → 发送固定文本 / 提示词生成的回复 / 图片 / 表情包**。这是群管+互动类工作流的命门，现在完全做不到。

### 3.1 发送能力做实（后端，命门）
- **现状**：`main.py` `_execute_notify_node`(~4962) 和 `_execute_deliver_outbox_node`(~5001) 只把内容塞进 `task.workflow_data.outbox` 并标记 "ready"，**全仓库 0 处 `event.send` / MessageChain**，群里收不到东西。
- **改**：
  - 在 send_message / send_private_message / deliver_outbox 的执行路径接 AstrBot 真实发送 API（`event.send(...)` / 消息链 / `Comp.Plain`、`Comp.Image`）。注意：执行器在 tick 内运行，需拿到当前 event/会话句柄；跨会话的仍留 outbox 给适配器。
  - outbox item 结构（现仅 `message` 字符串）**扩展**：增加 `image`(url/path/base64)、`face`/`emoji`(表情包)、`reply_mode`(fixed/prompt)。
- **锚点**：`def _execute_notify_node`、`def _execute_deliver_outbox_node`、节点字段在 `main.py` 的 ACTION 元数据(~190-395)。

### 3.2 发送支持多形态
- 文本（固定）/ **提示词生成回复**（写 prompt，Bot 生成后发）/ **图片**（URL/路径）/ **表情包**。
- **插件嵌入思路（用户最新）**：AstrBot 已有发表情包等插件；给"发送/扩展"节点一个选项——**中间过程切换为调用某插件**：做一个**纯提示词节点**，把目标插件镶嵌进去（记录 `plugin_name` + 提示词），告诉 Bot "调用这个插件发"。即"自己造轮子发" 和 "调现成插件发" 两条路都给。
- **前端**：send_message 的 simple-fields（`WORKFLOW_SIMPLE_FIELDS` ~4789）增加：发送类型(文本/提示词/图片/表情/调插件)、目标会话、内容/提示词、图片来源、绑定插件。

### 3.3 监听放开非文字事件（后端）
- **现状**：`_maybe_trigger_message_monitor`(~1478) 第 4 行 `text = event.message_str; if not text: return` —— 拍一拍(poke)/notice 无 message_str 被丢弃。
- **改**：识别 notice/poke 等事件类型，作为可触发来源（新增 source 如 `poke`/`notice`）；`agent_lab_native_message_monitor`(~541) 已是 `EventMessageType.ALL`，主要改下游的 text-gate。
- **诚实边界**：拍一拍能否捕获取决于平台适配器是否上报该事件——做不到的标注。

### 3.4 消息监听入口（合并节点，前端）
- 合并 命令/暗号入口、关键词入口、WebUI 手动入口 → 一个"消息监听入口"。
- 编辑页：**监听范围**(被@/对话时=message_monitor、全局静默=silent_global)；**触发条件**多选(命令/关键词/正则/自然语言/拍一拍/定时/插件事件/webhook)，勾了才显示对应输入；**谁能触发命令**(所有人/白名单/非黑名单/仅管理员→写回 workflow_scope 的 user 名单+admin_only)。
- 写回 `workflow_trigger`（已有字段，见 models.py `WorkflowTrigger`）。
- **删素材**：command_entry / keyword_entry / manual_webui_entry / entry(入口识别) → 并入。
- **锚点**：`WORKFLOW_NODE_TEMPLATES`(~316)、`WORKFLOW_NODE_GROUPS`(~288)、simple-fields(~4789)、`readAgentForm`(~5243) 写回。

### 3.5 outbox 可视化
- 方案管理页/运行监控里显示"待发什么、发没发出"（读 `workflow_data.outbox` + `outbox_delivery_history`）。

---

## 4. 第二批 · 后端没暴露的全部暴露（用户："全都做"）

逐项补前端（数据源已存在）：

| # | 能力 | 后端来源/锚点 | 前端要做 |
|---|---|---|---|
| 1 | 运行监控面 | `GET /workflow/runs` = `api_workflow_runs`(~6352)：当前节点/路径/reports/records/outbox/blockers/心跳健康/schedule_jobs/计数 | 新监控视图或方案管理页加块 |
| 2 | 预算/限制 | `models.py` TaskBudget（max_total_tokens/max_total_ticks/max_tools_per_tick/max_seconds_per_tick）+ `repeated_issue_counts`/`max_repeated_failures` | 全局控制节点可设；任务详情可看用量 |
| 3 | agent_runtime 审计轨迹 | `agent_lab/agent_runtime.py`：capability_catalog/task_plan/decisions/observations/verdicts/resume/pattern_recommendations | 任务详情加"Agent 在想什么/做了什么/凭什么判完成" |
| 4 | 模拟触发调试 | `POST /workflow/trigger` = `api_workflow_trigger` | 画布/方案页一个"模拟触发"按钮（填 source+text 测群管/定时流，不进真实群） |
| 5 | 任务日志 | `GET /task/logs` = `api_task_logs`(~6477) | 任务详情加日志面板 |
| 6 | blockers/watchdog 完整展示 | TaskState.blockers / watchdog | 任务详情展示卡住历史、连续失败、needs_user |
| 7 | reports/records | workflow_data.reports/records | 运行监控里展示 |
| 8 | 记忆运营素材 | 执行器已注册：summarize_memory/export_task_memory/promote_memory_candidate/forget_task_memory | 加这些素材卡 + simple-fields |
| 9 | 工作流变量素材 | variable_set/get、text_template、json_transform、merge、iterator、debate_validation（执行器在 `_register_node_executors` ~1956） | 加素材卡 + 编辑页 |
| 10 | 账号补全素材 | refresh_session/browser_profile/credential_scope | 加素材卡（账号组已有 6 个） |
| 11 | task_patterns 历史计划 | pattern_library，完成任务沉淀的可复用计划 | 新任务时展示"历史相似计划建议" |
| 12 | 蓝图精细设置 | module_settings / settings_schema | 插件与集成页渲染表单（现弱） |

---

## 5. 第三批 · 节点重构 + 高级特性

### 5.1 节点编辑页逐个按职责精修（核心 · 强制全覆盖）

**铁律（必须遵守）**：
1. **每一个节点都要按此方向改造**，不只是用户点名的那几个。用户给的（上下文压缩、人工接管、消息监听…）只是示例方向，不是全部范围。
2. **不允许任何旧节点原样保留**。每个节点要么：按职责定制编辑页 ✅、要么合并 🟡、要么删除 🔴、要么明确标成"自动节点/无需配置"并据此简化。没有"先放着不管"的选项。
3. **判断依据 = 后端执行器真读哪些字段**（下方字段事实表）。读不到字段的节点不能再套通用大表单。
4. 改造每个节点前，先 `grep` 该 action 在 `main.py` 的执行器，确认它真正消费的字段，再决定编辑页放什么。

**字段事实表（动手前先核对，行号会漂用 grep）**：
- `summarize_entry`/`confirm_entry`/`restore_isolation`/`save_state`/`heartbeat` → 后端**不读节点字段**（确定性书签）。执行器 `_execute_entry_node`、`_execute_state_node`。
- `match_keyword`→`keywords`；`match_regex`→`regex`；`llm_detect`→keywords+LLM；`scope_filter`→读 spec.workflow_scope。执行器 `_execute_detector_node`。
- `run_tools`→tool_name+tool_args；`call_api`→api_id+api_payload；`http_request`→url+method+payload；`file_operation`→operation+path；`code_exec`→language。
- `handoff`/`wait_user`→instruction+自动推断 wait_reason。执行器 `_execute_wait_node`。
- `notify`/`send_message`/`send_private_message`/`send_email`→message+target。执行器 `_execute_notify_node`；真正投递 `_execute_deliver_outbox_node`。
- `retry`→max_retries（出 retry/failed 边）；`route_condition`→出边 edge_type+condition；`parallel_branch`→parallel_group。
- `retrieve_memory`/`save_memory`→tags(+内容)；`MemoryPolicy`(models.py)：entry_summary_turns/compression_strategy/compression_max_tokens/preserve_keywords。
- 账号系：`credential_ref`/`cookie_jar`/`session_check`/`login_flow`/`revoke_session`→credential_id+provider。

**全节点处置总表（54 个素材，逐个落实，缺一不可）**：

| 处置 | 节点（id） | 编辑页该有什么 / 为什么 |
|---|---|---|
| 🟡 合并→消息监听 | 入口识别 entry、命令暗号入口 command_entry、关键词入口 keyword_entry、WebUI入口 manual_webui_entry | 都是"监听触发"。合并成"消息监听入口"：监听范围(被@/全局静默)+触发条件多选(命令/关键词/正则/自然语言/拍一拍/定时/插件事件/webhook)+谁能触发命令(黑白名单/仅管理员) |
| 🟢 改造 | 开启确认 entry_gate | confirm_entry 无字段→并入监听做"是否需要确认"开关，不单列节点 |
| 🟢 改造 | 上下文压缩 context_bridge | 暴露 最近轮数/压缩策略/最大token/必须保留(提示词)/是否调API |
| 🟢 改造→隔离 | 隔离快照 isolation_gate、授权范围锁定 scope_lock | 并入"全局控制节点"统一配隔离；scope_lock 删 |
| 🟡 合并 | 任务记忆检索 memory_recall、任务记忆读取 memory_read | →"读取任务记忆"(标签) |
| 🟢 改造 | 记忆过滤器 memory_filter | 给真职能：进入任务的记忆准入白/黑名单 + 任务中屏蔽日常记忆开关 + 回流暴露范围（防串联） |
| 🔴 删 | 回档续写入口 memory_rollback（除非改造成 retrieve_memory 带 source_task_id）、记忆标签暴露 memory_expose（并入保存记忆） | summarize_entry 换皮，无字段 |
| 🟢 保留 | 计划确认 plan | 拆解说明(instruction) |
| 🟢 改造 | 风险分流 risk_router（route_condition） | **规则表结构**：一行一条 当[变量][判断][值]→走[出口]，出口只能选真实端口 |
| 🟢 改造 | 并行分支 parallel_branch | **分支清单结构**：每个并行包名字+角色+提示词 |
| 🟡 合并 | 工作包拆分 todo_split、API参数整理 api_payload_builder | →"上下文整理" transform |
| 🟢 改造/改action | 文档/路径输入 document_source | 改成真 variable_set（写入 path/url 供下游） |
| 🟢 保留 | 提示词工作包 prompt_worker、并行资料阅读 parallel_research_worker、并行验收 parallel_verify_worker | 各自提示词 |
| 🟢 保留 | 工具执行 tool、自定义API api | 选工具/API+参数 |
| 🟢 改action | 浏览器QA browser_qa(→run_tools绑定)、文件改动 file_patch→`file_operation`(能填路径)、命令验证 shell_test→`code_exec`(能填命令) | |
| 🟢 改造 | 上下文整理 transform | 整理说明 |
| 🟢 保留 | 审批闸门 approval | 影响说明 |
| 🟡 合并 | API写入审批 api_write_guard、回滚预案 rollback_plan | →审批闸门 |
| 🟢 改造 | 人工接管 human_handoff | **4选项**：等用户回复/私信管理员/当前群提示/等外部回调 |
| 🟢 改造 | 结果校验 validation | 验收标准；验收清单 acceptance_check 并入 |
| 🟢 改造 | 重试循环 retry_loop | **循环盒结构**：次数+间隔+触发情形；端口重试在右、成功/失败在左（已做） |
| 🟢 改造 | 错误捕获 catch_error | **处置选择**：重试/通知/报告/暂停 |
| 🟢 改造/新增 | 限流 limit_rate | 时间窗+次数 |
| 🏷 标自动/隐藏 | 状态快照 checkpoint、心跳续跑 heartbeat | 快照=隐藏(系统书签)；心跳=改造成真节点(间隔/唤醒动作/失败保护/唤醒上限，按正规Agent心跳) |
| 🟢 改造 | 保存任务记忆 memory(save_memory) | 标签+内容+是否日常可读 |
| 🟢 保留/改造 | 完成通知 notify、发送私信 private_message、发送邮件 email_notice | 内容+对象；内容支持模糊提示词 |
| 🆕 新增 | 发群消息 send_message | 目标会话+内容(文本/提示词/图片/表情/调插件) |
| 🟢 保留 | 生成运行报告 workflow_report | 报告范围 |
| 🟢 改造 | 结束回流 exit、取消退出 cancel_exit | 合并成结束节点的"完成/取消"选项 |
| 🟢 保留 | 范围过滤器 scope_filter | 生效范围表单(已做，加"谁能触发命令") |
| 🟢 保留 | 插件事件入口 plugin_event_trigger | 监听哪个插件事件 |
| 🟢 保留 | 账号系6个(credential/login_check/login_flow/human_login/cookie/revoke) | 选凭证/账号 |
| 🆕 新增 | refresh_session / browser_profile / credential_scope 素材 | 账号补全 |
| 🆕 新增 | summarize_memory / forget_task_memory / promote_memory_candidate / export_task_memory 素材 | 记忆运营 |
| 🆕 新增 | variable_set/get / text_template / json_transform / merge / iterator / debate_validation 素材 | 变量与转换 |
| 🆕 新增 | 进入方案记忆存档 节点 | 选归入哪个记忆夹(方案级隔离) |
| 🆕 新增 | 全局控制节点 | 见 5.5 |
| 🆕 新增 | Skill 进化节点 | 见 5.4 |
| 🆕 新增 | 插件嵌入提示词节点 | 纯提示词+镶嵌目标插件，让Bot调该插件 |

**控制流/系统节点必须有独立结构（不能等同普通模块）**：分支=规则表、重试=循环盒、并行=分支清单、错误=处置选择、限流=时间窗+次数；系统挂钩(存/读记忆、状态快照、心跳)=与后端绑定的极简或只读编辑页。

**锚点**：`WORKFLOW_NODE_TEMPLATES`、`WORKFLOW_NODE_GROUPS`、`WORKFLOW_SIMPLE_FIELDS`、`workflowInspector`、`workflowInspectorAdvanced`、`node()`、`defaultWorkflowNodes`（动手前 grep 定位）。

### 5.2 记忆体系（v4 + 用户最新）
- **两层可见性**：日常只暴露标签级索引(时间/做了什么/成果)，不注入细节；Bot 主动回忆时才 retrieve 细节。
- **记忆夹**：不同任务/方案记忆装不同夹、互不串；没指定自动生成。
- **前端记忆管理**：能新建记忆夹；每夹设 时间戳/记哪些细节/是否暴露日常/保留期限。
- **归档素材节点**："进入方案记忆存档"——选归到哪个/哪些记忆夹。
- **方案级隔离**：记忆条目加 `folder` + `agent_id` 归属，读取按夹/方案过滤。
- **要动后端**：`agent_lab/memory_manager.py`(171行)、`agent_lab/storage.py`(748行)、models 的记忆条目结构、`api_memory`。

### 5.3 工作流与插件并行 + 接管 + 伪装管理员（用户最新）
- **原则**：普通插件只在日常聊天跑；进工作流默认不带，除非画布显式引入插件节点。（isolation_policy + plugin_overrides 已有基础。）
- **工作流当插件脚手架**：自定义命令、扩展行为（检测词→降好感度）。
- **冲突提示**：要接管原插件行为时，提示去"插件与集成"关掉原插件，避免双触发（做进静态检查 + 插件页）。
- **伪装管理员**：插件工具需管理员权限时——跑通前测权限/不足走人工提示，或插件节点设"伪装管理员"让指定人执行。**诚实边界**：取决于适配器是否允许覆盖 sender 角色，做不到的标注。`_workflow_scope_allows_event`(~7225) 是权限判断参考点。
- **插件嵌入提示词节点**（用户最新）：纯提示词节点 + 镶嵌目标插件(plugin_name)，让 Bot 调该插件完成中间过程（如发表情包用现成插件）。

### 5.4 Skill 进化节点（Hermes 式）
- 根据 accepted/candidate 记忆总结 → 改进 skill → 写 `skill_rules` 同步进 SKILL.md（钩子：`_sync_agent_mode_skill`(~6093)）→ 可选自主优化工作流(调 agent_lab_update_workflow)。
- **用户选**：低风险(默默优化) / 高风险(人工审批)。自动改流程默认走审批。
- **诚实边界**：`evolve_skills` 后端暂无执行器，需新增；先做"生成草稿+人工确认"安全版。

### 5.5 全局控制节点
- 方案级一个节点：隔离/工具范围/风险等级 + 中途谈话行为(暂停/继续但回复/埋头做) + 暂停继续命令 + 汇报频次(progress_notice_mode/every_tools/min_interval) + 工具是否显示(show_tool_use=否则全局静默) + 预算(token/轮数/工具/时间) + 错误累积阈值。
- 现有"全局规则抽屉"`workflowGlobalEditor`(~3744) 扩展成这个，或并存。

---

## 6. 实施纪律（每次动代码都遵守）

1. 动前 `grep -n` 重新定位锚点，不信缓存行号。
2. python 原子写：写 `.app.js.tmp` → `f.flush()+os.fsync` → `os.replace`；写后校验 `chk==s and not endswith("\x00")`。
3. 每次 `cp webui/app.js /tmp/_c.mjs && node --check /tmp/_c.mjs`（ESM 模式，CJS 会误报）。
4. 后端改完 `python3 -m compileall -q agent_lab main.py`。
5. 结构自检用 grep / jsdom harness（`outputs/harness*.mjs` 可复用）；不跑真实浏览器。
6. 每批完成后更新本文件第 2 节"进度状态表"。

---

## 7. 待用户最终确认（不影响先开工第一批）
1. 实施顺序：第一批(能发能听) → 第二批(暴露后端) → 第三批(重构+高级)。**建议先做第一批**。
2. 诚实边界接受：拍一拍监听 / 表情包发送 / 伪装管理员 三处取决于适配器，尽力做并标注做不到的。
3. 记忆夹无方案时自动生成 + 前端可新建夹 + 归档选夹 + 每夹细节设置：确认按此做。

---
*本计划合并 v1(节点审计)+v2(新要求+控制流结构)+v3(后端未暴露清单)+v4(能力诚实评估+三批计划)+ 最新(插件嵌入/记忆夹/并行/伪装管理员/发图发表情)。要点已全部收纳。*
