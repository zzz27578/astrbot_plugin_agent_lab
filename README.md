# astrbot_plugin_agent_lab

Agent Lab 是一个 AstrBot 插件，用来把普通 bot 会话切换成可持续执行、可审批、可归档、可扩展的 **Agent Mode**。

它不是替代 AstrBot，而是把 AstrBot 已有的 provider、Agent Runner、tools、MCP、Skills、cron、conversation、plugin session config 组织成一个可以手搓个人 Agent 的运行层。你可以把它理解成：当前 bot 仍然保持原本身份、语气和关系，但在写代码、配置项目、排错、部署、整理资料这类长任务里，临时进入一个更稳的任务工作台。

Agent Lab 不内置任何固定 bot 名字。默认 Agent 会按 AstrBot 运行时读取当前身份：优先会话/对话/默认 Persona，其次 AstrBot 配置里的机器人展示名，读不到时才显示通用的“当前 Bot”占位。WebUI 里配置名留空时继续跟随运行时身份；只有用户明确输入自定义配置名时，AgentSpec 才会转成手动名称。

## 新手先看

Agent Lab 主要解决四件事：

1. **防串记忆**：进入任务时压缩当前聊天计划，任务期间用独立 `task_state` 续跑，避免普通记忆插件把旧事注入进工程任务。
2. **可控工具箱**：每个 AgentSpec 都可以配置插件开关、工具白名单、任务专用 skills 和外部集成蓝图。
3. **任务连续性**：任务进度写进 `plugin_data`，手动 tick 或心跳醒来时先读状态、再执行、再保存。
4. **软审批**：删除、重置、部署、读密钥等危险动作前，bot 应先说明影响并请求确认。

最快验收方式：

```text
/agentlab status
/agentlab start 帮我测试 Agent Lab 是否能创建、推进和归档任务
/agentlab tick
/agentlab finish 初步测试完成
```

第一版默认只允许私聊使用，避免群聊误触发和权限扩散。

## WebUI 入口和权限

Agent Lab 现在使用 **独立控制台**，默认监听 `127.0.0.1:8788`，不再暴露 AstrBot Dashboard 插件 Page。

- `standalone_webui_enabled`：是否启动独立控制台。
- `standalone_webui_host`：监听地址，默认只允许本机访问。
- `standalone_webui_port`：监听端口，默认 `8788`。
- `standalone_webui_token`：API 访问 Token；如果监听到局域网或公网，建议必须填写。

打开路径默认是：

```text
http://127.0.0.1:8788
```

WebUI 分为五个区域：仪表盘与列表、可视化编排画布、任务与记忆控制台、实例与心跳监控、插件与集成。它是 Agent Lab 后续扩展的主入口。

## 功能概览

- 创建多个 AgentSpec，并选择默认 Agent。
- 支持自然语言进入 Agent Mode，也支持命令和 WebUI 调试。
- 任务模式不是完全失忆：入口压缩普通上下文，任务期间使用独立 task_state，退出后归档并生成记忆候选。
- 支持会话级插件启用/禁用，不动全局插件开关。
- Agent Lab 插件本体会被锁定，避免任务模式把自己禁用后无法恢复。
- 支持心跳续跑：长任务醒来后先读状态，再执行，再保存。
- 支持审批协议：危险操作前由 bot 主动说明并请求用户确认。
- 把外部优秀 agent 设计收束成集成蓝图，方便后续接入 LangGraph、OpenAI Agents SDK、CrewAI、Microsoft Agent Framework 等方案。

## 安装

把本仓库作为 AstrBot 插件安装，或放入 `data/plugins/astrbot_plugin_agent_lab`。推荐仓库目录名和插件 ID 保持一致：

```bash
git clone https://github.com/zzz27578/astrbot_plugin_agent_lab.git data/plugins/astrbot_plugin_agent_lab
```

```text
data/plugins/astrbot_plugin_agent_lab/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── agent_lab/
├── skills/
└── webui/
```

启动后插件会自动安装 `agent-mode` Skill，并启动独立 Agent Lab 控制台。

## 命令

```text
/agentlab status
/agentlab use <agent_id>
/agentlab start <目标>
/agentlab tick
/agentlab heartbeat on
/agentlab heartbeat off
/agentlab approve <approval_id>
/agentlab reject <approval_id>
/agentlab finish <总结>
/agentlab cancel <原因>
/agentlab agents
/agentlab plugins
/agentlab tools
/agentlab skills
/agentlab integrations
/agentlab webui
```

短命令：

```text
/al status
/al tick
```

第一版默认仅私聊可用，避免群聊误触发和权限风险。

## 自然语言触发

插件会注入 Agent Mode 协议，并安装 `agent-mode` Skill。bot 可以在合适场景调用：

- `agent_lab_enter_mode`
- `agent_lab_read_state`
- `agent_lab_update_state`
- `agent_lab_tick`
- `agent_lab_request_approval`
- `agent_lab_set_heartbeat`
- `agent_lab_finish`
- `agent_lab_call_custom_api`

触发策略由 AgentSpec 控制：

- `manual`：只通过命令或 WebUI 开启。
- `confirm`：判断适合进入时先请求确认。
- `smart`：低风险任务可自动进入，高风险任务确认。
- `always`：尽量使用 Agent Mode，高风险仍审批。

这套判断会同时写入 `agent-mode` Skill 和运行时系统提示词。也就是说，用户在 WebUI 里选择模式后，bot 不需要每次等固定命令，而是会按当前 AgentSpec 自主判断：是否该进入 Agent Mode、是否需要先确认、是否建议心跳、是否必须走审批。

自然语言和命令默认使用当前默认 Agent。可以在 WebUI 里点击 Agent 后设为默认，或用 `/agentlab use <agent_id>` 切换默认 Agent；WebUI 入口会用当前选中的 Agent 启动任务。

## AgentSpec

AgentSpec 是用户手搓 Agent 的核心配置：

```json
{
  "identity_label_source": "astrbot_runtime",
  "trigger_mode": "confirm",
  "entry_policy": {
    "trigger_phrases": ["进入任务模式", "/agentlab start"],
    "trigger_keywords": ["持续推进", "排查", "改代码"],
    "require_confirmation": true,
    "confirmation_text": "我会进入任务模式：隔离当前会话插件、压缩上文、创建 task_state，并在高风险动作前请求审批。是否开启？",
    "default_completion_conditions": ["用户验收通过", "任务成果已归档"],
    "exit_phrases": ["完成任务", "退出任务模式", "/agentlab finish"]
  },
  "isolation_policy": {
    "mode": "strict",
    "tool_mode": "whitelist",
    "restore_on_exit": true,
    "protect_self": true,
    "hide_disabled_plugin_tools": true
  },
  "system_prompt": "...",
  "task_prompt": "...",
  "plugin_overrides": {
    "某记忆注入插件": false,
    "小窝 memo": true
  },
  "enabled_tools": [
    "astrbot_file_read_tool",
    "astrbot_grep_tool",
    "astrbot_file_write_tool",
    "astrbot_file_edit_tool",
    "astrbot_execute_shell",
    "astrbot_execute_python",
    "agent_lab_call_custom_api"
  ],
  "tool_risk_overrides": {
    "astrbot_execute_shell": "work",
    "agent_lab_call_custom_api": "work"
  },
  "enabled_skills": [],
  "module_ids": [
    "checkpoint_state",
    "approval_guard",
    "heartbeat_protocol",
    "memory_gate"
  ],
  "memory_policy": {},
  "approval_policy": {},
  "heartbeat_policy": {}
}
```

默认 AgentSpec 不要求手填 bot 名。`identity_label_source: "astrbot_runtime"` 表示运行时自动读取当前会话/对话/默认 Persona，读不到 Persona 时再读 AstrBot 配置里的机器人展示名；WebUI 的配置名输入框留空时仍按运行时身份生成展示名，只有用户手动输入自定义 `name` 时才会转成 `manual`。

新建 AgentSpec 默认使用 `isolation_policy.mode=strict`。严格隔离会在当前会话默认关闭普通 AstrBot 插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件；它不改全局插件开关，退出任务时按快照恢复。`tool_mode=whitelist` 会把运行时工具收敛到白名单和 Agent Lab 必要内部工具；如果选择 `no_external`，任务只保留读写任务状态、审批、心跳、归档和任务记忆查询这类内置工具。

任务启动时会复制 AgentSpec 快照，运行中的任务不会被后续模板修改突然影响。

## 任务连续性

Agent Lab 的连续性来自插件数据目录中的 task_state：

```text
data/plugin_data/astrbot_plugin_agent_lab/
├── agents/
├── sessions/
│   └── <umo_hash>/
│       ├── active_task.json
│       ├── task_<id>.json
│       └── task_<id>.md
└── archives/
```

每轮执行遵守：

```text
读 task_state
-> 执行有限步骤
-> 记录观察
-> 更新下一步
-> 判断完成/审批/心跳/阻塞
```

默认 Agent 会尝试启用 AstrBot 常用 Computer Use 工具：

```text
astrbot_file_read_tool
astrbot_grep_tool
astrbot_file_write_tool
astrbot_file_edit_tool
astrbot_execute_shell
astrbot_execute_python
```

如果当前 AstrBot 未启用对应 runtime，工具解析会被跳过或由 AstrBot 自身返回权限/运行时错误。

## WebUI

独立控制台是 Agent Lab 的主操作面：

- **仪表盘与列表**：看 Agent 资产、当前任务、任务触发量、心跳在线/异常和 Token 消耗概览；每个任务模式配置会汇总运行数、触发数、Token、待审批和在线/离线/报错状态。
- **可视化编排画布**：配置任务模式补充提示词、触发策略、记忆/审批/心跳策略和流程节点。画布支持大尺寸横向流程、缩放、拖拽节点、节点边缘圆点拉线、点击连线删除、工作流检查、模板切换和 JSON 导入/导出兜底；这里不重建 bot 身份，只继承 AstrBot 运行时解析出的身份。
- **任务与记忆控制台**：用 UMO 创建任务、手动 tick、开心跳、关心跳、完成归档、取消归档；可审查 active 与历史归档任务的结构化状态、待审批、状态快照时间线，并筛选/修剪出口记忆候选。
- **实例与心跳监控**：查看运行中任务的心跳健康状态、超时告警、状态曲线和实时日志，并进行任务级停止/心跳控制。
- **插件与集成**：用页内左侧子导航管理 AstrBot 插件隔离、注册工具白名单、自定义 API、凭证、任务专用 skills，以及外部方案蓝图。

自定义 API 在“插件与集成 -> 自定义 API”里注册，凭证在“凭证库”里加密保存。Agent Mode 中只暴露一个通用工具 `agent_lab_call_custom_api`：它只能调用已注册的 API，并按注册时选择的 bearer/header/query 方式注入凭证；工具结果不会回显密钥。

“插件与集成 -> Skills 规则”可以编辑 `agent-mode` 的自定义规则，也可以编辑入口摘要和出口归档规则。规则会保存到 `plugin_data/astrbot_plugin_agent_lab/registry/skill_rules.json`，并在插件同步 `agent-mode` Skill 时追加到 `SKILL.md`；入口/出口摘要规则会直接参与进入任务模式的 `task_brief` 压缩和退出归档。

“插件与集成 -> AstrBot 插件隔离”只作用于 Agent Mode 会话，不会改 AstrBot 全局插件开关。AstrBot 全局停用的插件固定关闭，Agent Mode 不能绕过原生插件管理把它复活；在 Agent Mode 中关闭某插件时，该插件来源的注册工具会同步从当前 Agent 的工具白名单中移除。后端保存 AgentSpec 时也会再次清理这些工具，防止绕过 WebUI 写回不一致状态。

“插件与集成 -> 注册工具”会按来源插件折叠显示工具，并允许为当前 AgentSpec 覆盖 `safe/work/high` 风险等级。右侧审批策略可编辑预授权范围、必须审批动作和审批备注；这些不会硬性截断工具，而是写入任务模式提示，让 bot 在计划和调用工具前主动判断。

工作流画布的工具箱会把 AstrBot 插件、自定义 API 和当前工具白名单作为可点击模块放进流程节点。插件模块会记录 `plugin_name`，API 模块会记录 `api_id` 并通过 `agent_lab_call_custom_api` 调用，工具模块会记录 `tool_name`；节点还能写入 `prompt`、`condition` 和 `parallel_group`，用于并行 Agent 分支或子流程分工。Bot 也可以通过 `agent_lab_update_workflow` 检查、增删改节点/连线、绑定模块和写入节点提示词。

“插件与集成 -> 外部方案蓝图”可以查看、加入、精细配置或导入/更新蓝图 manifest。用户自定义蓝图会写入 `plugin_data/astrbot_plugin_agent_lab/modules/<module_id>.json`，框架升级时不会覆盖这部分数据；相同 `module_id` 的用户蓝图会覆盖内置蓝图，方便你按自己的工作流改规则。

## 外部方案库

Agent Lab 会加载两类集成蓝图。代码层仍使用 `modules` 命名以保持兼容，但在 WebUI 中统一称为“外部方案蓝图/规则模块”：

```text
modules/*.json
data/plugin_data/astrbot_plugin_agent_lab/modules/*.json
```

也就是说，用户可以把外部 agent 方案写成蓝图 manifest 放进插件数据目录，不用改主框架代码。蓝图只描述协议、能力、设置 schema 和适配要求；真正执行仍通过 AstrBot 插件、注册工具、MCP、skills 或后续 runner adapter。它不是 AstrBot 插件，也不是可直接调用的工具，而是把外部方案的好概念翻译成 Agent Lab 的 TaskState、审批、心跳、记忆和工作流约束。

蓝图的 `settings_schema.properties` 会在 WebUI 里渲染成精细设置表单，当前值写入 AgentSpec 的 `module_settings`。高级 JSON 导入/导出仍保留，用来兼容复杂对象和未来扩展字段。

蓝图 manifest 示例：

```json
{
  "module_id": "my_memory_adapter",
  "name": "My Memory Adapter",
  "source": "custom",
  "description": "把我的记忆系统接入 MemoryGate。",
  "prompt": "模块注入给 Agent 的行为协议。",
  "links": ["https://example.com"],
  "capabilities": ["memory"],
  "requires": ["memory_gate"],
  "settings_schema": {
    "type": "object",
    "properties": {
      "entry_summary_turns": {"type": "integer"}
    }
  },
  "default_settings": {
    "entry_summary_turns": 24
  }
}
```

## 内置蓝图

蓝图不是外部框架的硬依赖，而是 Agent Lab 的兼容层：

- `checkpoint_state`：借鉴 LangGraph persistence，把状态作为续跑根基。
- `approval_guard`：借鉴 OpenAI Agents guardrails / HITL，把危险动作前置审批。
- `heartbeat_protocol`：AstrBot-native 心跳，使用 `cron_manager.add_basic_job` 唤醒插件 runner。
- `memory_gate`：借鉴 Deep Agents long-term memory，把任务记忆和日常记忆分层。
- `handoff_adapter`：兼容 AstrBot 子代理和 OpenAI handoff 思路。
- `flow_adapter`：为 CrewAI/Microsoft 风格 workflow 留接口。
- `langgraph_checkpoint_adapter`：LangGraph checkpoint/thread 接入规范。
- `openai_agents_guardrails_adapter`：OpenAI Agents tools/guardrails/handoffs 接入规范。
- `deepagents_memory_gate_adapter`：长期记忆文件化与回流规范。
- `crewai_flow_adapter`：CrewAI Flow 接入规范。
- `microsoft_agent_framework_adapter`：Microsoft Agent Framework 中间件/工作流接入规范。

调研参考：

- OpenAI Practical Guide to Building Agents: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- AstrBot Agent Runner: https://github.com/AstrBotDevs/AstrBot/blob/master/docs/en/use/agent-runner.md
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph human-in-the-loop: https://docs.langchain.com/oss/python/langgraph/interrupts
- OpenAI Agents: https://openai.github.io/openai-agents-python/agents/
- OpenAI Agents guardrails: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI Agents handoffs: https://openai.github.io/openai-agents-python/handoffs/
- CrewAI Flows: https://docs.crewai.com/en/concepts/flows
- Microsoft Agent Framework: https://learn.microsoft.com/en-us/agent-framework/overview/
- Deep Agents memory: https://docs.langchain.com/oss/python/deepagents/memory

## 当前状态

这是一个可安装、可运行的第一版成熟骨架：

- 插件后端可运行。
- AgentSpec/TaskState 可持久化。
- 默认 Agent 展示名从 AstrBot 运行时身份读取，WebUI 会显示来源是 Persona、配置名称还是兜底占位。
- 自定义 API、加密凭证和 `agent_lab_call_custom_api` 工具已打通。
- `agent-mode` Skill 支持 WebUI 自定义规则同步。
- 可视化编排画布支持节点素材、运行时模块、节点拖拽、圆点拉线、连线删除、缩放、自动布局、工作流检查和多模板切换，不再只能手改 workflow JSON；小屏会自动切成按阶段分组的中文节点卡片，避免在手机上横向拖超宽画布。
- 工具支持风险分组、风险覆盖和可编辑审批策略。
- 外部方案蓝图支持按 `settings_schema` 渲染精细设置表单，并保存到 `module_settings`。
- 仪表盘 Agent 资产列表会按配置聚合心跳健康、任务触发、Token 和待审批数量。
- 任务与记忆控制台支持查看归档任务详情、结构化状态字段、待审批和快照时间线。
- 命令、LLM 工具、独立 WebUI、心跳、审批、入口/出口摘要均已落地。
- Agent 能在 tick 中显式读写 task_state，并通过 hooks 记录工具调用；tick 结束时会重读最新 task，避免覆盖工具已写回的进度或把已归档任务重新写成 active。
- 严格插件隔离已落地：任务会话默认关闭普通插件，只保留显式允许项和必要内部能力。
- 外部方案以集成蓝图形式内置为可扩展收束口。

后续可以继续增强：

- 节点分组折叠、运行态高亮和真正的并行 runner adapter。
- 更完整的 provider token usage 统计；当前只汇总 provider 已上报的 usage。
- 更细的工具危险等级和凭证管理。
- 对接外部 memory store。
- 对接 LangGraph/CrewAI/OpenAI Agents SDK 作为可选 runner adapter。

外部方案接入规范见 [docs/ADAPTER_GUIDE.md](docs/ADAPTER_GUIDE.md)。

## 本地自检

```bash
python -m compileall -q .
python scripts/smoke_test.py
python scripts/runtime_smoke_test.py
```

如果要检查 AstrBot API 兼容性，可把 AstrBot 源码加入 `PYTHONPATH` 后导入：

```bash
PYTHONPATH=/path/to/AstrBot/.. python -c "import astrbot_plugin_agent_lab.main"
```

明早验收步骤见 [docs/ACCEPTANCE.md](docs/ACCEPTANCE.md)。
