# Agent Lab 工作流画布重设计：定位、对比、错位与新编辑页方案

> 面向对象：非技术向 AstrBot 玩家（装插件、搭机器人、不写代码）。
> 目标：解释「现在的画布连线 + 节点编辑」为什么对新手不友好、为什么和后端真实代码没有对齐，并给出一份可落地的新编辑页设计。
> 证据基于当前仓库代码（`webui/app.js` 取自 git `HEAD`，即真正在跑的 6906 行版本；`agent_lab/*.py`、`main.py`）。

---

## 0. 一句话结论

后端早已是一个**有类型端口、有路由语义（success / failed / uncertain / error / approved / rejected / timeout / retry）、区分「确定性节点」与「ReAct 节点」**的执行引擎；但前端画布把每个节点画成**只有一进一出两个圆点**、把每条手拉的连线**硬编码成 `edge_type:"success"`**、还把连线颜色取成**起点节点的颜色**而不是路由类型。结果就是：**画布画出来的图，根本表达不了后端真正会执行的分支**，而新手看到的又是一堆 `kind·action·runtime_type` 这种内部术语。所以「不友好」和「没对齐」其实是同一个病根——**画布是按「给节点摆位置 + 写大提示词」设计的，后端却是按「按端口和路由跑状态机」设计的。**

---

## 1. 插件定位：Agent Lab 到底是什么

读 `README.md` / `docs/WORKFLOW_AUTOMATION.md` / `metadata.yaml` 后，定位很清晰：

**Agent Lab 是 AstrBot 的「可视化自动化工作流层」。** 它不替代 AstrBot，而是把 AstrBot 已有的 provider、Agent Runner、tools、MCP、Skills、cron、会话插件配置，组织成一个可编排的运行层。它有两种形态：

1. **长任务 Agent Mode**（最初定位）：进入任务模式 → 隔离会话插件 → 压缩上文成 `task_brief` → 用独立 `task_state` 续跑 → 危险动作前审批 → 心跳唤醒 → 归档回流。
2. **事件驱动 / 静态自动化**（新定位）：一条画布也可以是「监听群消息 → 检测刷屏关键词 → 调用封禁工具 → 发报告」这类 trigger→detector→action→report 的自动化，由命令 / 消息 / 关键词 / 正则 / 定时 / 插件事件 / webhook 触发。

**关键点**：任务形态由「画布的节点图」决定，不是写死的类型。也就是说——**画布是这个产品的核心交互面**，它既要能搭长任务 Agent，又要能搭事件自动化。画布的好坏，直接决定这个插件好不好用。

这也解释了为什么画布问题这么关键：它不是一个可有可无的可视化装饰，**它是用户定义「机器人到底会怎么干活」的唯一结构化入口**。

---

## 2. 后端真实的节点契约（这才是「源真相」）

要判断前端「有没有对齐」，必须先看后端到底吃什么。证据集中在三处：`agent_lab/node_runtime.py`、`agent_lab/runtime.py`、`main.py`。

### 2.1 节点有「规范类型 / 执行模式 / 端口表」三层结构

`node_runtime.py` 定义了一套**规范节点类型**（`CANONICAL_NODE_TYPES`）：`trigger / entry / detector / state / decision / parallel / tool / api / memory / guard / validation / notification / report / terminal / react`。

每个 `action` 还映射到一个**执行模式**（`ACTION_EXECUTION_MODES`）：

- `deterministic`：后端直接跑，不需要模型（如 `match_keyword`、`scope_filter`、`save_state`、`retrieve_memory`、`restore_isolation`）。
- `llm_guided`：要模型判断（如 `plan`、`llm_detect`、`exit_summary`）。
- `hybrid`：混合（如 `run_tools`、`parallel_branch`、`generate_report`）。

并且每类节点有**明确的端口表**（`NODE_PORT_SCHEMAS` / `ACTION_PORT_SCHEMAS`），例如：

| 节点类型 | inputs | outputs |
|---|---|---|
| `detector`（检测器） | `input` | `success` / `failed` / `uncertain` / `error` |
| `decision`（分支） | `input` | `success` / `failed` / `retry` / `error` / `always` |
| `guard`（审批/人工） | `input` | `success` / `failed` / `approved` / `rejected` / `error` / `timeout` |
| `retry`（重试循环） | `start` / `retry` / `error` | `retry` / `success` / `failed` / `error` |
| `trigger`（监听器） | （无输入） | `success` / `error` |
| `terminal`（归档） | `input` | （无输出） |

也就是说，**后端心里每个节点有好几个不同语义的出口**，监听器节点甚至**没有输入口**，重试节点的端口语义是「反过来」的。

### 2.2 连线是带类型和条件的，路由真的会按它走

`main.py` 里 `_workflow_edges_for_result()`（约 2396–2444 行）是真正的路由核心。它做的事：

1. 从节点执行结果里取 `route`（`result.data.route` 或 `result.data.edge_type`）；
2. 把各种别名归一化（`matched/passed/ok/true → success`，`unmatched/false → failed`，`exception → error`…）；
3. 在该节点的出边里，**只选 `edge.edge_type` 命中目标路由的边**；
4. 如果边上还写了 `condition`，用 `agent_lab/conditions.py` 的 `evaluate_condition()` 求值，不为真就跳过。

`_candidate_nodes_from_edges()` 还会把 `edge.condition` 和 `edge.condition_visual` 透传给候选节点。换句话说：**后端的「下一步去哪」= 节点出口路由类型 × 边上的 edge_type × 边上的 condition**。这是一个标准的「带类型端口 + 条件路由」的状态机，和 n8n 的 Switch / Dify 的 IF-ELSE 是同一个量级的东西。

### 2.3 tick 里还有个「轻量确定性 runtime」

`agent_lab/runtime.py` 的 `WorkflowRuntime` 是 tick 主循环用的简化版：它的 `outgoing()` **只读 `from`/`to`**，遇到「一个节点有多条出边」时（`len(outgoing) > 1`）直接 `needs_react=True`，把分支决策丢给模型（`runtime_runner.py` 再调 `tool_loop_agent` + `agent_lab_advance_workflow`）。

**这里就埋了第一个隐患**：后端存在「两套对边的理解」——事件驱动 runtime（`main.py`）严格按 `edge_type` 路由，tick 内的轻量 runtime（`runtime.py`）只看 `from/to` 拓扑、多出边就交给 ReAct。前端如果连「给边标类型」都做不到，这两套都没法稳定工作。

---

## 3. n8n / Dify 是怎么做的（联网核对后的最新结论）

> 来源：n8n 官方文档 docs.n8n.io、Dify 官方文档 docs.dify.ai（见文末）。下面每条都附「可迁移的设计原则」。

### 3.1 节点发现与添加

- **n8n**：搜索优先，400+ 节点按 Triggers / AI / App Actions / Data Transformation / Flow / Core 分类；**强制要有一个 Trigger 节点**作为起点；有模板市场。
- **Dify**：不强制 start 节点；节点类别更少更聚焦（LLM / Tools / Knowledge / Code / IF-ELSE / Question Classifier / HTTP / Iteration…）；**模板优先**，有「Dify 101」按难度标注的新手模板。

> **原则**：新手不该面对空白画布。**先给可运行模板，让人「改」而不是「从零搭」**；节点面板要按「用户想干的事」分组，而不是按内部 kind 分组。

### 3.2 端口与连线语义（最关键的对比）

- **n8n**：IF 节点 = True/False 两个口；Switch = 多个具名输出口（可改名成「approved」「rejected」）；多数节点有独立的 **Error 输出口**；连线颜色/端口可视区分不同语义。
- **Dify**：IF-ELSE 节点显式给出 IF / ELIF / ELSE 多条分支；Question Classifier 让 LLM 分类后走多分支；知识检索节点带 fail 分支。**分支是「节点自带的多个命名出口」，用户把不同出口连到不同下游**。

> **原则**：**分支必须在「节点上长出多个有标签的出口」**（success/failed/approved/rejected…），用户用眼睛就能看出「失败走哪、通过走哪」。连线颜色 = 出口语义，而不是节点颜色。

### 3.3 节点配置面板

- **n8n**：右侧抽屉；每个字段有 Fixed/Expression 切换；表达式编辑器里有「上游变量树」可点选插入（`{{ $json.x }}`）。
- **Dify**：右侧抽屉；字段强类型；任意文本框输入 `/` 唤起**变量选择器**插入上游变量（`{{#node.var#}}`）；**渐进式展开**——可选字段默认收起。

> **原则**：配置面板要**强类型 + 行内变量选择器 + 渐进式展开**。不要把 30 个原始字段一次性全摊给用户；用下拉、开关、带 placeholder 的输入替代「自己填 JSON」。

### 3.4 校验与测试

- **n8n**：必填项红框、节点跑完打勾/打叉、底部执行面板看每个节点的输入输出数据；改了配置的节点标记「需重跑」。
- **Dify**（1.5+）：保存前阻止缺必填；**可单节点重跑**、看中间产物，不必跑完整条流。

> **原则**：**错误要在跑之前就显示在对应节点上**；要能**单节点试跑**看输出，给新手快速反馈闭环。

### 3.5 降低门槛的具体手法

默认值、行内提示「这个节点是干嘛的」、便利贴注释、模板起步、高级选项折叠、变量选择器代替手敲路径。

---

## 4. 现在的画布连线 + 节点编辑，为什么对新手不友好

下面每条都对应 `webui/app.js`（HEAD 版）的真实代码。

### 4.1 每个节点只有「一进一出」两个圆点，分支只能靠脑补

`node()`（约 4287–4309 行）渲染节点时，**写死了两个口**：

```js
<span class="node-port node-port-in"  data-port="in"  ...></span>
<span class="node-port node-port-out" data-port="out" ...></span>
```

不管这个节点是「风险分流（decision）」「检测器（detector）」还是「审批闸门（guard）」，画布上都只有一个 `out` 圆点。可后端 `detector` 有 4 个出口、`guard` 有 6 个出口。**新手在画布上根本看不到「失败往哪走、审批被拒往哪走」**——这些语义全藏在看不见的地方。

### 4.2 手拉的连线一律是「success」，颜色还骗人

`connectWorkflowPorts()`（5549 行）→ `addWorkflowEdge()`（5467 行）：

```js
currentAgent.workflow_edges.push({ from, to, edge_type: edgeType || "success" });
```

从圆点拖出来的所有连线，`edge_type` **永远是 `success`**（拖拽路径不传第三参）。想建一条「失败」或「审批被拒」的边，**只能去右侧那个不起眼的「连线」面板里用下拉手选 `edge_type` 再「新增连线」**（`workflowEdgesPanel`，4463 行），等于绕开画布、回到「填表连线」。

更误导的是连线颜色：`workflowEdgesHtml`（约 3990 行）里 `const color = workflowNodeColor(from)`——**连线颜色取自「起点节点的颜色」，不是路由类型**。于是 success / failed / error 三条边长得一模一样，新手以为颜色有意义，其实没有。README 自己也写「彩色节点与同色连线」，恰恰说明连线颜色被设计成「跟随节点」而非「表达路由」。

### 4.3 节点卡片和编辑器全是内部术语

节点卡片底部一行长这样（`node()`，4299 + 4306 行）：

```
计划 · 计划拆解        ← stage · action
[半自动] state         ← 执行态徽章 · runtime_type
plan · 状态            ← id · kind
```

`kind / stage / action / runtime_type / 半自动 / ReAct` 这些都是**给开发者看的内部分类**。非技术玩家看到「state / guard / branch / subflow」「半自动 / ReAct」完全无感。

点开节点编辑器（`workflowInspector`，4327–4454 行）更劝退：**6 个分区、约 30 个字段**一次性全摊开——

- 基础：节点标识、名称、阶段、**类型(kind)**、**动作(action)**、权限
- 能力绑定：引用类型、引用 ID、AstrBot 工具、自定义 API、插件名、Skill 名
- 数据流：输入变量、输出变量、必需输入、额外输出、**参数 JSON**、**输入 Schema(JSON)**、**输出 Schema(JSON)**
- 路由与执行：分支条件、路由变量、并行分组、Worker 类型、超时、最大重试、变量名、模板 ID、文件路径、URL、HTTP 方法、文件操作、代码语言、记忆标签、**重试策略 JSON**
- 说明：一句话说明、执行说明、**模型兜底提示**

一个新手想加「检测到刷屏就封禁」，却要在「kind 选 state 还是 guard」「action 选哪个」「要不要填 input_schema JSON」之间懵掉。**这是典型的「把后端数据结构直接 1:1 摊成表单」**，而不是「按用户意图设计表单」。

### 4.4 「检查 / 预跑」给的是术语化告警，不是新手能懂的修复指引

静态检查（`workflowCheck`，约 4209–4278 行）产出的是「缺少入口节点」「分支节点建议至少两条输出」「没有输入连线」这类**结构化术语告警**。方向对（确实在帮忙），但措辞是给懂工作流的人看的，没有「点这里修」的引导。

### 4.5 小结：新手门槛来自三件事叠加

1. **看不见分支**：画布只有一进一出，多出口语义不可见。
2. **术语轰炸**：kind/action/runtime_type/schema 直接暴露。
3. **填表式连线 + JSON 字段**：真正的分支要回到面板填，复杂节点要手写 JSON。

---

## 5. 为什么和后端实际代码没有对齐（逐条对照）

| # | 后端真实契约（证据） | 前端画布实际行为（证据） | 错位后果 |
|---|---|---|---|
| 1 | 节点按类型有多个具名出口：detector 4 个、decision 5 个、guard 6 个（`node_runtime.py` `NODE_PORT_SCHEMAS`/`ACTION_PORT_SCHEMAS`） | 每个节点只渲染 1 个 `out` 圆点（`app.js` `node()` 4297–4298） | 画布**画不出**后端支持的分支；多出口能力等于隐身 |
| 2 | 路由 = `edge.edge_type` 命中 + `edge.condition` 求值（`main.py` `_workflow_edges_for_result` 2396–2444） | 拖拽连线 `edge_type` 恒为 `success`（`addWorkflowEdge` 5473）；拖拽不带类型 | 画布上拖出的图**只表达 happy path**；failed/error/timeout 路径只能靠面板补，或干脆缺失 |
| 3 | 连线类型有 9 种语义（`WORKFLOW_EDGE_TYPES`：success/failed/uncertain/error/retry/timeout/approved/rejected/always） | 连线颜色 = 起点节点颜色（`workflowEdgesHtml` `workflowNodeColor(from)` ~3990），不体现类型 | 用户**看不出**一条边是「成功」还是「失败」路径；视觉语义错配 |
| 4 | 节点区分 `execution_mode`：deterministic / llm_guided / hybrid（`node_runtime.py` `ACTION_EXECUTION_MODES`） | 用「半自动 / 可执行 / ReAct」徽章近似（`workflowNodeExecutorState` 1056）但**没有引导用户「确定性节点该填结构化字段、ReAct 节点才靠提示词」** | 新手在「确定性节点」里也只会写大段提示词，触发后端「该走确定性却跑去 ReAct」的浪费 |
| 5 | `from_port`/`to_port` 是后端端口契约的一部分（`node_runtime.py` `edge_type_from_port` 395，文档「Special Module Compilation」称 `from_port` 可推断 `edge_type`） | 前端边对象**完全没有 `from_port`/`to_port`**（全仓库 0 处），连线只有 `{from, to, edge_type}` | 监听器（无输入口）、retry（反向端口语义）这些**特殊模块在画布上无法正确连线** |
| 6 | tick 内 `WorkflowRuntime.outgoing()` 只看 `from/to`，多出边即 `needs_react`（`runtime.py` 106–115、180–199） | 画布也只能可靠产出 `success` 边 | 多分支永远落到 ReAct，**画布的「结构化降跑偏」价值在 tick 路径里几乎没兑现** |
| 7 | 事件 runtime 已实现确定性 detector/route（`WORKFLOW_AUTOMATION.md`「Runtime routing now reads `result.data.route`」） | 画布没有「测试这个检测器会走哪条边」的预览 | 用户**无法验证**自己连的 success/failed 分支是否如预期 |

> 还有一个工程层面的红旗：**当前工作区里部署的 `webui/app.js`（2349 行）是一个没写完的重写版**——它调用了 `render()` 却没有定义，`workflowConnection`/`workflowPendingPort` 变成死变量，`workflow-link`/`lane` 等画布 DOM 全部缺失。真正能跑的是 git `HEAD` 的 6906 行版本（也是 QA 截图对应的版本）。**做新编辑页前，必须先确认以哪个版本为基线**，否则会在半成品上继续叠错。

---

## 6. 新编辑页设计方案（面向非技术 AstrBot 玩家）

设计主线只有一句：**让画布能 1:1 表达后端的「类型化端口 + 路由」，同时把内部术语翻译成玩家语言、用模板和向导兜住新手。**

### 6.1 信息架构：三层渐进，新手停在第一层

```
第 1 层  模板库（默认入口）
        └─ 选场景：群管刷屏处理 / 定时日报 / 长任务写代码 / 关键词自动回复 …
           选完直接得到一张可运行的图，只需改几个高亮空（如"封禁哪个群""发给谁"）

第 2 层  画布（可视编排）
        └─ 拖节点、连有颜色的分支线、看实时校验
           节点用"人话"标题 + 图标，分支出口有标签

第 3 层  节点抽屉（按需展开）
        └─ 简易模式：3–5 个该节点真正必填的字段（带下拉/变量选择器）
           高级模式：才出现 JSON / schema / 超时 / 重试策略
```

非技术玩家 80% 的需求应在「第 1 层改空 + 第 2 层连线」内闭环，**永远不必看到 `input_schema` JSON**。

### 6.2 节点：从「一进一出」改成「按类型长出命名出口」

把后端的 `port_schema` 搬到画布上。每个节点根据类型渲染**多个有标签、有颜色的出口圆点**：

```
        ┌─────────────────────────┐
 (输入)─◉  🔍 检测刷屏              │
        │  规则检测器              │
        │           通过 success ◉─→（绿）
        │           未中 failed  ◉─→（灰）
        │           拿不准 uncertain ◉─→（黄）
        │           出错 error   ◉─→（红）
        └─────────────────────────┘
```

要点：
- **出口数量和标签直接来自后端 `NODE_PORT_SCHEMAS`/`ACTION_PORT_SCHEMAS`**（前端做一份镜像常量并加显示名映射），保证「画布画得出的 = 后端跑得通的」。
- 从某个**具名出口**拖线，自动写入 `edge.edge_type = 该出口类型` 和 `edge.from_port`，**彻底干掉「拖线一律 success」**。
- **连线颜色 = edge_type**（绿=success、灰=failed、黄=uncertain、红=error、紫=approved/rejected、橙=retry/timeout），并在线中段放一个小标签。改 `workflowEdgesHtml` 把 `workflowNodeColor(from)` 换成 `workflowEdgeColor(edge.edge_type)`。
- 监听器节点**不渲染输入口**；retry 节点按后端反向端口语义渲染（`start/retry/error` 入、`retry/success/failed/error` 出）。

### 6.3 节点语言：内部术语 → 玩家话术 + 图标

卡片正面不再出现 `kind·action·runtime_type`。改成：

- **大图标 + 人话标题**（如「🔍 检测刷屏」「🚫 封禁用户」「📤 发报告」「⏰ 定时触发」）。
- 一行**人话说明**（「命中关键词就往『通过』走」）。
- 右下角一个**小徽章表达执行性质**，但用玩家词：`自动`（deterministic）/ `智能`（llm_guided/ReAct）/ `混合`（hybrid），hover 才显示技术解释。

`kind/action/runtime_type` 仍存在于数据里，但只在「高级模式」可见可改。

### 6.4 节点抽屉：简易模式按 action 定制字段

抛弃「30 个字段一把梭」。改成**按节点 action 决定显示哪几个字段**的简易表单。示例：

| 节点（action） | 简易模式只显示 | 高级模式才出现 |
|---|---|---|
| 关键词检测 `match_keyword` | 关键词列表（每行一个）、命中走哪条出口 | 正则、大小写、input 变量 |
| 调用工具 `run_tools` | 选工具（下拉，来自 `state.tools`）、关键参数（按工具 schema 生成的表单） | 原始参数 JSON、超时、重试 |
| 调 API `call_api` | 选已注册 API（下拉，来自 `state.custom_apis`） | payload JSON、输出变量 |
| 审批 `request_approval` | 一句话说明影响、回滚怎么做 | 预授权范围、必审动作 |
| 保存记忆 `save_memory` | 记忆标签、要存什么（一句话） | 输出变量、schema |
| LLM 检测 `llm_detect` | 判断标准（一句话）、通过/失败/拿不准各走哪 | 输出 schema、置信度阈值 |

实现上：把 `workflowInspector` 的「一个大模板」拆成 **`fieldsFor(action)` 注册表**——每个 action 声明自己的简易字段列表；高级字段统一收进 `<details>` 折叠区。

**变量引用学 Dify**：输入框输入 `/` 唤起上游节点输出选择器，插入 `{{node.output}}`，而不是让玩家手敲 `variables.memory`。

### 6.5 确定性 vs 智能：把后端的 execution_mode 显性化

后端已经知道每个节点是 `deterministic / llm_guided / hybrid`。新编辑页要据此**引导填写方式**：

- `自动`（deterministic）节点：抽屉里**主推结构化字段**，把「模型兜底提示」折到最底下并标注「通常不需要填」。
- `智能`（ReAct）节点：抽屉里**主推提示词**，结构化字段次要。

这样能减少「确定性节点被塞大提示词 → 后端本可不调模型却被迫 ReAct」的浪费（对应错位 #4、#6）。

### 6.6 校验与单节点试跑：把现有能力包装成新手语言

后端已有 `/api/workflow/check` 和 `/api/workflow/dry-run`，能力够，缺的是「翻译」和「定位」：

- **错误就地显示**：把 `workflowCheck` 的 issue 直接渲染成**节点角标**（红点=error、黄点=warn），点角标弹出「这是什么问题 + 一键修」。如「分支节点建议至少两条输出」→ 改成「这个『风险分流』只连了 1 条路，失败的情况会没人接，要不要加一条『失败』分支？[添加]」。
- **单节点试跑**：对 detector/route 类节点提供「试一句话看走哪条边」——调用 dry-run，把命中的出口高亮。对应错位 #7，让玩家敢用分支。
- **保存前体检**：有 error 时保存按钮旁给出「还有 2 处会导致跑不通」的提示，而不是默默存下去。

### 6.7 模板优先：新手默认不见空白画布

进入画布默认落在**模板库**（复用现有 `WORKFLOW_NODE_TEMPLATES` 的思路，但升级成「整图模板」）。每个模板：

- 一句话场景描述 + 缩略图；
- 打开后**高亮 2–3 个必填空**（用 AstrBot 运行时已有的群号、工具、API 下拉），其余预连好；
- 「标准流程 / 紧急模式 / 并行 Agent / API 审批流 / 代码任务流 / 记忆续写流」这些现成模板（截图顶部那排按钮）保留，但从「重置整张图的危险按钮」改成「带预览的模板卡」。

### 6.8 关键改动清单（落地锚点）

| 优先级 | 改动 | 触碰的代码 |
|---|---|---|
| P0 | 节点按 `port_schema` 渲染多出口；前端镜像后端端口常量 | `node()` 4287；新增端口常量（镜像 `node_runtime.py`） |
| P0 | 从具名出口拖线写入 `edge_type`+`from_port` | `connectWorkflowPorts` 5549、`addWorkflowEdge` 5467 |
| P0 | 连线颜色/标签 = `edge_type` | `workflowEdgesHtml` ~3990、新增 `workflowEdgeColor()` |
| P0 | 先定基线：以 `HEAD` 6906 行版为准，废弃半成品 2349 行 `app.js` | `webui/app.js` 工作区版本 |
| P1 | 节点抽屉拆成 `fieldsFor(action)` 简易/高级两档 | `workflowInspector` 4327 |
| P1 | 卡片术语→人话+图标+玩家徽章 | `node()` 4299/4306、`workflow*Label` 系列 |
| P1 | 输入框 `/` 变量选择器 | 抽屉字段渲染 |
| P2 | 校验 issue → 节点角标 + 一键修 | `workflowCheck` 4209、节点渲染 |
| P2 | detector/route 单节点试跑 | 接 `/api/workflow/dry-run` |
| P2 | 模板库作为默认入口（整图模板 + 高亮必填空） | `WORKFLOW_NODE_TEMPLATES`/模板区 |
| P3 | 后端两套 runtime 对边的理解统一（tick 内也按 `edge_type` 路由，而非多出边即 ReAct） | `runtime.py` `outgoing/inspect` |

> P3 是后端项，但建议同步推进：否则前端把分支画对了，tick 路径仍可能把它丢给 ReAct，玩家会觉得「我连的分支没生效」。

---

## 7. 验证建议（做完怎么确认对齐）

1. **契约一致性测试**：写个脚本/单测，断言「前端端口常量」与 `node_runtime.py` 的 `NODE_PORT_SCHEMAS`/`ACTION_PORT_SCHEMAS` 完全一致（防未来再漂移）。
2. **图→执行往返测试**：在画布连一条 `detector --failed--> notify` 的边，保存后用 `/api/workflow/dry-run` 喂一条「不命中」的消息，断言确实走到 notify。
3. **新手可用性走查**：找一个没看过文档的人，限时 5 分钟用模板搭出「群里有人发广告就私信管理员」，记录卡点。
4. **回归**：确认废弃半成品 `app.js` 后，截图里的 9 节点默认流仍能加载、缩放、连线、检查、预跑。

---

## 附：信息来源

- 仓库代码：`webui/app.js`（git HEAD）、`webui/index.html`、`webui/style.css`、`agent_lab/node_runtime.py`、`agent_lab/runtime.py`、`agent_lab/runtime_runner.py`、`agent_lab/models.py`、`main.py`、`docs/WORKFLOW_AUTOMATION.md`、`README.md`
- n8n 官方文档：https://docs.n8n.io/
- n8n Switch 节点：https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.switch
- Dify 官方文档：https://docs.dify.ai/
- Dify IF-ELSE 节点：https://docs.dify.ai/en/use-dify/nodes/ifelse
- Dify 关键概念：https://docs.dify.ai/en/use-dify/getting-started/key-concepts
- React Flow Handles（画布端口交互参考）：https://reactflow.dev/learn/customization/handles
