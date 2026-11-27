# Agent Lab v2.0.0 更新规划与架构路线图（Roadmap）

> **状态**：规划定稿（Architecture & Implementation Roadmap）  
> **前置基线**：`v1.0.0`（已发布） → `v1.0.1`（前置热修复） → **`v2.0.0`（双层主从协作架构）**

---

## 1. 版本目标与架构定位

`v2.0.0` 旨在将 **Agent Lab** 从 `v1.0.x` 的「单代理隔离长任务工具箱」平滑演进为 **「双层主从式 · 按需子代理协作架构（Two-Layer Lead + On-Demand Subagent Architecture）」**。

本次升级不是推倒重写，而是在**严格保留 `v1.0.0` 全部核心工程优势**的前提下，补齐多模型专长分工、大规模探索卸载与非技术用户友好交互能力：

- **隐藏式工具箱与日常零污染**：空闲态日常聊天仅保留极简入口 `agent_lab_start_task`（活跃时动态浮现 `agent_lab_control_task`），绝不向全局注入冗余工具或子代理上下文。
- **静态前缀缓存稳定性**：继续严格执行 `build_static_system_prompt` 纯静态前缀与 SHA-256 内容寻址增量唤醒（`WAKE_PREFIX`），子代理调度状态不污染主会话前缀缓存。
- **先归档后压缩（Archive-First Compaction）**：沿用 `ContextCompactor` 与 `StageContextManager`，先落盘完整归档再做阶段交接压缩，单次工具输出入站一次性截断，全量落盘并给出独立路径指针。
- **不可逆终态围栏（Terminal Fence）**：任务一旦进入 `completed` / `cancelled` 终态，主 Bot 与所有在途/待命子代理同步受终态围栏阻断，杜绝并发竞态写回。
- **零暴露加密保险箱**：继续由本地 Fernet Vault 托管密钥与个人资料，子进程环境变量按方案/项目授权注入并对多编码输出统一脱敏，**子代理同样受同级密钥防渗漏守卫约束**。
- **冷淡极简经典风 WebUI**：继续维持 `pages/agent-lab/classic-view.js` 的三栏克制控制台（`项目与任务` / `方案管理` / `系统设置`），不引入重型画布或无关弹窗。

---

## 2. 四大核心支柱

### 2.1 支柱一：跨日常与隔离会话的统一 Bot 身份（坦诚透明的后台协作）

- **唯一人格延续**：无论是日常私聊还是后台隔离任务会话（`planning` / `executing`），始终由同一位 **主 Bot（来源 Bot）** 面向用户发声，通过 `resolve_source_persona` 延续一致的声线、语气与陪伴感。
- **透明承认后台协作**：主 Bot 不必伪装成“独自手搓一切”，可以在回复中自然、坦诚地提及后台子代理的协助（例如：*“我让后台子代理去扫了一遍代码并跑了单测，结果回来了……”*）。
- **单一对外交互出口**：**所有面向用户的进度播报、人话审批说明、关键提问（`task_ask`）与最终成果交付，必须且只能通过主 Bot 统一完成**。
- **静默后台工人定位**：子代理不具备独立聊天人设，严禁直接向用户发送私信，也不得直接向用户弹出审批单或提问框。

### 2.2 支柱二：双层项目空间（主 Bot 筹备立项 → 审批确立 → 授权执行）

```text
[日常会话]
   │  仅调用 agent_lab_start_task(goal, project_id?, profile_id?, constraints?, scope_roots?, brief?)
   ▼
[Layer 1 · 隔离规划空间 (planning)]
   │  • 主 Bot 拥有高只读自主权：允许跨目录只读探索全貌（无繁琐 [REVIEW] 拦截墙）
   │  • 硬安全底线仍强制生效：阻断 .env / .ssh / secrets.key 等敏感凭证与检索资源炸弹
   │  • 产出完整项目骨架：scope_roots / steps / constraints / completion_conditions / handoff_brief
   │  • 面向用户输出「通俗人话立项提案」，申请一次性确认
   ▼  （管理员批准：批准 / /al approve / WebUI）
[Layer 2 · 授权执行空间 (executing)]
   │  • 项目正式确立，authorized_scope_roots 即刻生效激活
   │  • 按绑定 Profile 的 delegation_mode（off / hybrid / architect_only）推进执行与核验
   ▼
[终态归档交付 (completed / cancelled)]
```

- **第一层（Planning & Project Setup）**：
  - 日常对话仅触发 `agent_lab_start_task`，将目标及可选的项目/方案绑定、约束、`scope_roots` 与 `brief` 传入隔离空间，保证日常聊天上下文极度轻量。
  - 在隔离规划期内，主 Bot 先充分做只读侦察再定计划，避免“盲猜立项、批完返工”；同时依靠硬编码安全底线防住敏感凭证泄露与 OOM 级检索炸弹。
  - 主 Bot 整理完毕后，向用户提交一份人类一眼能看懂的立项提案（目标、涉及目录、拟定步骤、预期风险与验证手段），等待一次性拍板。
- **第二层（Approved Execution）**：
  - 审批通过即代表项目边界正式确立，`authorized_scope_roots` 立即激活锁定。
  - 执行期严格按所选方案（`Profile`）的协作模式决定由主 Bot 亲自实施还是按需分派给子代理。

### 2.3 支柱三：按需子代理模型池与三种协作模式

#### A. 子代理模型池（`系统设置` → `子代理模型池`）

- **零重复密钥配置**：模型下拉列表直接读取 AstrBot 宿主已配置的 Chat Providers（`context.provider_manager`），不重复存储任何 API Key 或 Base URL；未显式指定时默认跟随来源 Bot 所用模型。
- **工具调用前置提示**：WebUI 明确提示所选 Provider/模型**必须支持原生 Tool Calling / Function Calling**，否则无法承担带工具的子代理执行任务。
- **极简规格条目（`SubagentSpec`）**：每条子代理配置仅保留 4 项核心信息：
  1. **显示名称**（如 `代码审计手`、`测试执行手`、`文档检索手`）
  2. **绑定 AstrBot Chat Provider**（下拉选择或“跟随来源 Bot”）
  3. **一句话能力/专长描述**（供主 Bot 根据任务性质与模型能力按需选派）
  4. **可选纪律提示词**（附加于该子代理的极简行为约束）

#### B. 三种方案协作模式（`方案管理` → `执行协作与提示词`）

| 模式值 | 中文名称 | 适用场景与行为约束 |
|---|---|---|
| `off` | **关闭（纯主 Bot 单核模式）** | **默认安全值**。全部步骤由主 Bot 在单一隔离会话完成，不注入 `dispatch_subagent`，零多代理开销，完全兼容 `v1.0.x`。 |
| `hybrid` | **混合协作模式** | **启用子代理时的推荐模式**。小范围快速编辑/轻量检查可由主 Bot 顺手完成；大体积代码检索、批量重复修改、耗时测试运行按需派发子代理。 |
| `architect_only` | **总工程师模式（只动脑不动手）** | 专为「高智商旗舰模型担任主 Bot + 性价比/专用模型担任子代理」设计。主 Bot 严格负责架构拆解、派发 `dispatch_subagent`、核验交付物与对用户沟通；**在 `executing` 阶段限制主 Bot 直接调用写文件与代码/命令执行工具**，迫使其将具体落地工作委托给子代理。 |

#### C. 子代理硬安全与防失控护栏

1. **严格扁平单层调度**：子代理**绝对禁止**再次派生子代理（`dispatch_subagent` 绝不暴露给子代理）。
2. **控制与外联工具剥夺**：子代理不注入 `task_plan`、`task_progress`、`task_ask`、`task_approve`、`task_finish`，彻底杜绝子代理越过主 Bot 篡改主计划或直连用户。
3. **WebUI 可配防失控上限**：
   - `max_subagent_calls`：单任务最大子代理调用总次数（例如默认 `6`）。
   - `max_subagent_concurrency`：单任务最大并发子代理数（例如默认 `1–2`，硬上限锁死 `3`）。
4. **并发读写隔离纪律**：
   - **只读类子代理**（`mode="readonly"`）：允许在并发上限内并行执行（如多模块并行调研）。
   - **写入/执行类子代理**（`mode="write"`）：强制**串行执行**（或受严格路径互斥锁保护），防止多代理同时改写同一工作区造成覆盖冲突，同时避免低内存宿主机因并发多进程测试/编译而发生 OOM。
5. **统一预算记账**：所有子代理产生的 `prompt_tokens`、`completion_tokens`、`total_tokens`、`llm_calls`、`tool_calls` 与耗时统一汇总计入父任务的 `UsageTotals`（`usage`），共同受 `BudgetConfig` 硬上限约束。

### 2.4 支柱四：人话沟通原则与分级代审机制（非技术用户友好）

AstrBot 的核心用户群体中有大量非程序员用户——他们依赖主 Bot 的专业判断，而非原始工具参数 JSON。`v2.0.0` 将沟通层与安全层做如下清晰分层：

#### A. 可编辑人话引导词与不可变安全底线分离

- **可编辑引导提示词**：在 `方案管理` 详情页提供可编辑的 `editable_guidance_prompt`（附带**「恢复默认」**按钮），引导主 Bot：
  - 用符合自身人设的通俗中文向用户说明「为什么要批、改了什么、有什么影响、出问题怎么回退」，并给出明确建议（*推荐批准 / 建议谨慎*）。
  - 原始参数细节与调用明细留存在 WebUI 审计面板，不在私聊中用大段原始 JSON 淹没用户。
- **不可变硬安全底线**：所有涉及权限边界、高危操作拦截、密钥脱敏、终态围栏与人类审批红线的代码逻辑**完全硬编码于 `permissions.py` / `engine.py`**，任何提示词编辑均无法绕过或削弱。

#### B. 分级审批与升级流（按方案可选开关 `lead_auto_review_low_risk`）

- 子代理在运行中被守卫拦截时，**绝不直接向用户发起审批**，而是生成结构化受阻报告返回主 Bot，由主 Bot 决策下一步。
- **绝对红线（无论是否开启代审，必须由主 Bot 翻译成人话请示管理员）**：
  1. 首次立项计划审批与项目边界确立（`task_plan`）；
  2. 扩大已授权的写入目录边界（`authorized_scope_roots`）；
  3. 变更任务最终目标（`goal`）或核心完成条件；
  4. 破坏性文件系统、数据库或 Git 不可逆操作（删除、强推、重置等）；
  5. 敏感凭证路径访问或超出方案授权范围的密钥调用；
  6. 用户在规则或方案中显式标注 `审批:` 的自定义强制审批项；
  7. 涉及产品取舍或主观偏好的决策提问（`task_ask`）。
- **中低风险主 Bot 复核通道（仅当 Profile 开启 `lead_auto_review_low_risk` 时生效）**：
  - 例如：子代理请求补充读取项目外关联只读参考文件，或执行严格服务于已批准目标的非破坏性校验检查。
  - 主 Bot 可依据「是否严格服务于已批准目标、是否无副作用」进行复核并签发一次性受控放行；**所有代审记录全量写入 `events.jsonl` 审计日志并在 WebUI 可查**。
  - 只要主 Bot 判断存在任何不确定性或有偏离既定目标的风险，一律**保守升级**为向人类管理员发起人话审批。

---

## 3. 数据模型、内部工具与 WebUI 集成草案

> 以下结构基于 `v1.0.0` 的 `agent_lab/models.py`、`agent_lab/context_engine.py`、`agent_lab/webui_api.py` 与 `pages/agent-lab/classic-view.js` 增量扩展，保持 `meta.json` 单一事实源轻量特性（`< 5 KB`）与向后兼容反序列化。

### 3.1 新增与扩展数据模型（`agent_lab/models.py`）

```python
@dataclass
class SubagentSpec:
    agent_id: str                        # e.g. "sub_code_auditor"
    display_name: str                    # 显示名称，如 "代码检索与审计"
    provider_id: str = ""                # "" = 跟随来源 Bot 当前 Chat Provider
    capability_summary: str = ""         # 一句话能力/专长描述（供主 Bot 选派）
    discipline_prompt: str = ""          # 可选纪律提示词
    enabled: bool = True
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
```

**`Profile` 增量字段**（旧配置缺失字段时自动回落至安全默认值）：

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `delegation_mode` | `str` | `"off"` | `off` \| `hybrid` \| `architect_only` |
| `max_subagent_calls` | `int` | `6` | 单任务子代理累计调用次数上限（范围 `1–30`） |
| `max_subagent_concurrency` | `int` | `1` | 单任务并发子代理数上限（硬上限 `3`） |
| `lead_auto_review_low_risk` | `bool` | `False` | 是否允许主 Bot 对非红线中低风险只读/校验请求做复核放行 |
| `editable_guidance_prompt` | `str` | 预设人话模板 | 可编辑的人话沟通与协作引导词（支持一键恢复默认） |

**`UsageTotals` / `TaskMeta` 增量审计字段**：
- `UsageTotals.subagent_calls: int = 0`：记录本任务实际派发的子代理次数，并继续将子代理的 `tokens`、`tool_calls` 合并计入父任务总额。
- `events.jsonl` 新增事件类型：`subagent_dispatched`、`subagent_completed`、`subagent_blocked`、`lead_auto_reviewed`，使 WebUI 时间线可完整追溯每次派发与代审依据。

### 3.2 唯一新增内部工具：`dispatch_subagent`

- **可见性与阶段准入铁律**：
  - `dispatch_subagent` **严禁出现在日常聊天上下文中**，且**严禁出现在子代理自身工具集中**（子代理同时剔除全部 `TASK_CONTROL_TOOL_SCHEMAS`）。
  - 仅在隔离后台任务且 `Profile.delegation_mode != "off"` 时按阶段注入给主 Bot：
    - **`planning` 阶段**：主 Bot 仅允许以 `mode="readonly"` 调用 `dispatch_subagent`（用于并行只读探索）；`mode="write"` 在计划获批前硬性拒绝。
    - **`executing` 阶段**：`mode="readonly"` 与 `mode="write"` 均开放（其中 `write` 强制串行或受严格路径互斥锁保护）。
- **Schema 草案**：

```json
{
  "name": "dispatch_subagent",
  "description": "将明确的子任务按需派发给后台子代理执行，并返回结构化结果报告。",
  "parameters": {
    "type": "object",
    "properties": {
      "agent_id": {
        "type": "string",
        "description": "子代理模型池中的 agent_id（不指定或不可用时报错提示可用列表）"
      },
      "task": {
        "type": "string",
        "description": "清晰、自包含的子任务说明、上下文背景与预期输出格式"
      },
      "mode": {
        "type": "string",
        "enum": ["readonly", "write"],
        "description": "readonly=仅只读调研/审计（可并发）；write=涉及写文件或执行变更（强制串行或路径互斥）"
      },
      "target_paths": {
        "type": "array",
        "items": { "type": "string" },
        "description": "可选：本次子任务拟访问或修改的目标路径提示（必须在已授权 scope_roots 内）"
      }
    },
    "required": ["agent_id", "task", "mode"]
  }
}
```

### 3.3 WebUI 极简落位（严守现有 3 分区架构）

不新增顶层导航项，沿用 `classic-view.js` 现有三大分区平滑嵌入：

1. **`系统设置` → 新增第 4 个标签页 `子代理模型池`**：
   - 与现有 `机器人与通知`、`私人保险箱`、`连接与存储` 并列。
   - 展示子代理列表卡片（名称、绑定 Provider 下拉框——直连 `context.provider_manager`、支持“跟随来源 Bot”、Tool Calling 能力提示徽标、一句话专长描述、可选纪律提示词、启用开关与增删改操作）。
2. **`方案管理` → 详情页第 4 节升级为 `4. 执行协作与提示词`**：
   - 保留现有 `system_prompt`、`task_prompt` 与默认授权密钥勾选。
   - 新增「执行协作模式」选择器（`关闭 off` / `混合协作 hybrid` / `总工程师 architect_only`）。
   - 当模式非 `off` 时展开协作参数：`最大子代理调用次数`、`最大并发数（≤3）`、`启用低风险主 Bot 代审` 复选框。
   - 新增「人话沟通引导词 (`editable_guidance_prompt`)」编辑框与 **「恢复默认」** 按钮，旁附说明标注硬安全底线不可通过提示词覆盖。
3. **`项目与任务` → 任务详情时间线微调**：
   - 在现有步骤列表与事件流中以轻量标签标注子代理调用记录及主 Bot 代审记录，原始 JSON 折叠置于审计详情内，保持界面克制整洁。

---

## 4. 前置修复与分阶段里程碑

### Phase 0（硬性前置条件）：`v1.0.1` Hotfix 先行落地

在启动 `v2.0.0` 开发前，必须先合入并验证 `v1.0.1` 稳定性热修复，确保单核基座坚固可靠：

1. **崩溃 / OOM 级检索防护**：对正则检索（`grep`）与目录扫描增加深度、文件数、单文件体积与匹配行数硬上限，杜绝超大目录/二进制文件拖垮进程或撑爆上下文。
2. **`planning` 阶段只读探索边界修复**：修正规划阶段合理只读探索的权限判定，减少合法侦察被误拦，同时保持敏感凭证与资源炸弹硬阻断。
3. **`wake_inputs` 零信任路径上下文对齐**：确保 `prepare_wake_message()` 调用 `execution_roots(task)` 填充 `authorized_roots`，并显式下发 `session_workspace_root`、`execution_cwd` 及（规划期）未批准的 `candidate_scope_roots`，消除模型目录盲区且不误把待审批 `scope_roots` 当作已授权写目录。
4. **`[REVIEW]` 拦截提示文案修复**：修正权限守卫返回给模型的 `[REVIEW]` 引导提示，确保模型能准确区分「不可越权」与「应通过 `task_approve` 走人话审批」。
5. **`profile_id` 静默升级修复**：禁止任务运行或切换配置时未授权静默切换/升级至更高权限的 `profile_id`，保障方案边界可预期。

### `v2.0.0` 实施阶段与验收标准

| 阶段 | 核心交付内容 | 验收标准（Verification Criteria） |
|---|---|---|
| **Phase 1：模型池与数据契约** | 扩展 `models.py`（`SubagentSpec`、`Profile` 新字段、`UsageTotals.subagent_calls`）；`webui_api.py` 暴露读取 `context.provider_manager` 与子代理池 CRUD 接口；全量向后兼容旧 `v1.0.x` JSON。 | 旧版配置与历史任务无迁移报错正常加载；WebUI 仅显示 AstrBot 已配置 Provider，无明文密钥冗余持久化。 |
| **Phase 2：子代理运行时与调度工具** | 实现子代理独立隔离会话执行器（复用 `bridge.py` / `MeteredProvider`）、`dispatch_subagent` 分阶段注入（`planning` 仅 `readonly`、`executing` 开放 `readonly`/`write`）与预算合并记账、单层防嵌套与控制/私信工具剥离。 | 日常对话零泄露 `dispatch_subagent`；`planning` 阶段调用 `mode="write"` 硬拒绝；子代理无法调用 `task_*`、无法再派发子代理、无法私信用户；父任务 `usage` 精确累加子代理消耗与触发预算熔断。 |
| **Phase 3：三种模式与并发互斥** | 落地 `off` / `hybrid` / `architect_only` 运行时工具集裁剪；实现只读并发信号量与写入串行/路径互斥锁；接入终态围栏联动取消机制。 | `architect_only` 在 `executing` 阶段成功阻断主 Bot 直接写/执行工具；并发写入自动串行无文件踩踏；任务停止/交付时在途子代理立即中止写回。 |
| **Phase 4：人话沟通与分级代审** | 落地 `editable_guidance_prompt` 默认模板与不可变安全底线分层；实现子代理受阻退回主 Bot、红线强制人类审批、`lead_auto_review_low_risk` 审计记账。 | 红线操作（扩权/改目标/删库/`审批:`规则等）100% 转化为通俗中文请示用户；子代理任何场景均不直连弹窗；代审放行均有 `events.jsonl` 完整记录。 |
| **Phase 5：WebUI 集成与对抗测试** | 完成 `classic-view.js`（`子代理模型池` 标签页 + `执行协作与提示词` 卡片 + 审计微调）与 `scripts/preview_webui.py` 仿真支持；补充 `tests/` 多场景自动化对抗测试。 | 全量 `python -m pytest -v tests` 通过（覆盖三模式切换、越权嵌套拦截、并发写互斥、代审红线守卫、预算耗尽与终态竞态）；无 AstrBot 依赖下本地预览控制台全交互正常。 |
