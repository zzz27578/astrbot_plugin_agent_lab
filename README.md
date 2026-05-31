# astrbot_plugin_agent_lab

Agent Lab 是一个 AstrBot 插件，用来把普通 bot 会话切换成可持续执行、可审批、可归档、可扩展的 **Agent Mode**。

它不是替代 AstrBot，而是把 AstrBot 已有的 provider、Agent Runner、tools、MCP、Skills、cron、conversation、plugin session config 组织成一个可以手搓个人 Agent 的运行层。你可以把它理解成：当前 bot 仍然保持原本的人设和关系，但在写代码、配置项目、排错、部署、整理资料这类长任务里，临时进入一个更稳的任务工作台。

Agent Lab 不内置任何固定 bot 名字。默认 Agent 会优先读取 AstrBot 当前会话/默认人格名称来生成展示名；读不到时才显示通用的“当前 Bot”占位。用户自己创建或改名的 AgentSpec 会保持手动名称。

## 新手先看

Agent Lab 主要解决四件事：

1. **防串记忆**：进入任务时压缩当前聊天计划，任务期间用独立 `task_state` 续跑，避免普通记忆插件把旧事注入进工程任务。
2. **可控工具箱**：每个 AgentSpec 都可以配置插件开关、工具白名单、任务专用 skills 和模块。
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

Agent Lab 的 WebUI 是 **AstrBot Dashboard 插件 Page**，不是一个独立 Web 服务。

- 不需要 Agent Lab 自己开放端口。
- 不需要 Agent Lab 自己再设置一套管理员密码。
- 访问控制继承 AstrBot Dashboard：能登录 Dashboard 的管理员，就能打开插件 Page。
- 如果你的 AstrBot Dashboard 暴露到公网，请按 AstrBot 本体要求配置管理员密码、监听地址、反向代理或访问控制；这不是插件单独处理的。

打开路径：

```text
AstrBot Dashboard -> 插件 -> Agent Lab -> 打开 Page
```

WebUI 第一版主要是功能测试和可视化审查台：可以创建/复制 AgentSpec，切插件、工具、skills、modules，查看 active task 和 archive，手动 tick，开心跳/关心跳，处理审批。

## 功能概览

- 创建多个 AgentSpec，并选择默认 Agent。
- 支持自然语言进入 Agent Mode，也支持命令和 WebUI 调试。
- 任务模式不是完全失忆：入口压缩普通上下文，任务期间使用独立 task_state，退出后归档并生成记忆候选。
- 支持会话级插件启用/禁用，不动全局插件开关。
- Agent Lab 插件本体会被锁定，避免任务模式把自己禁用后无法恢复。
- 支持心跳续跑：长任务醒来后先读状态，再执行，再保存。
- 支持审批协议：危险操作前由 bot 主动说明并请求用户确认。
- 把外部优秀 agent 设计收束成模块，方便后续接入 LangGraph、OpenAI Agents SDK、CrewAI、Microsoft Agent Framework 等方案。

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
└── pages/
```

启动后插件会自动安装 `agent-mode` Skill，并在 AstrBot Dashboard 的插件页面暴露 `Agent Lab` Page。

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
/agentlab modules
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

触发策略由 AgentSpec 控制：

- `manual`：只通过命令或 WebUI 开启。
- `confirm`：判断适合进入时先请求确认。
- `smart`：低风险任务可自动进入，高风险任务确认。
- `always`：尽量使用 Agent Mode，高风险仍审批。

这套判断会同时写入 `agent-mode` Skill 和运行时系统提示词。也就是说，用户在 WebUI 里选择模式后，bot 不需要每次等固定命令，而是会按当前 AgentSpec 自主判断：是否该进入 Agent Mode、是否需要先确认、是否建议心跳、是否必须走审批。

自然语言和命令默认使用当前默认 Agent。可以在 WebUI 里点击 Agent 后设为默认，或用 `/agentlab use <agent_id>` 切换默认 Agent；WebUI 测试入口会用当前选中的 Agent 启动任务。

## AgentSpec

AgentSpec 是用户手搓 Agent 的核心配置：

```json
{
  "name": "当前 Bot Agent Mode",
  "identity_label_source": "astrbot_persona",
  "trigger_mode": "confirm",
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
    "astrbot_execute_python"
  ],
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

插件 Page 用于第一版功能测试和可视化验收：

- 查看 Agents、Active Tasks、Archives、Plugins、Tools、Skills、Modules。
- 用 UMO 创建任务、手动 tick、开心跳、关心跳、完成归档、取消归档。
- 在 Task Review 中查看当前任务状态、处理审批、直接推进/结束任务。
- 查看 Archives，确认任务退出后已经归档。
- 新建、复制、选择 AgentSpec，并设置默认 Agent。
- 编辑触发模式、记忆/审批/心跳策略、任务提示词、插件开关、工具白名单、任务专用 skills 和模块协议。
- 审查、复制、新建并保存自定义模块 manifest 到 `plugin_data/modules`。
- 后续可扩展成完整可视化 workflow builder。

## 模块系统

Agent Lab 会加载两类模块：

```text
modules/*.json
data/plugin_data/astrbot_plugin_agent_lab/modules/*.json
```

也就是说，用户可以把外部 agent 方案写成模块 manifest 放进插件数据目录，不用改主框架代码。WebUI 的 Modules 面板也可以直接复制内置模块、编辑字段并保存为自定义模块。

模块 manifest 示例：

```json
{
  "module_id": "my_memory_adapter",
  "name": "My Memory Adapter",
  "source": "custom",
  "description": "把我的记忆系统接入 MemoryGate。",
  "prompt": "模块注入给 Agent 的行为协议。",
  "links": ["https://example.com"],
  "capabilities": ["memory"],
  "requires": ["memory_gate"]
}
```

## 内置模块

模块不是外部框架的硬依赖，而是 Agent Lab 的兼容层：

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

参考：

- AstrBot Agent Runner: https://github.com/AstrBotDevs/AstrBot/blob/master/docs/en/use/agent-runner.md
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
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
- 命令、LLM 工具、WebUI Page、心跳、审批、入口/出口摘要均已落地。
- Agent 能在 tick 中显式读写 task_state，并通过 hooks 记录工具调用。
- 外部方案以模块形式内置为可扩展收束口。

后续可以继续增强：

- 更强的 WebUI 编辑器。
- workflow 可视化图。
- 更细的工具权限守卫。
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
