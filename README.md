# AstrBot Agent Lab

Agent Lab 是一个 AstrBot 插件，用来把普通 bot 会话切换成可持续执行、可审批、可归档、可扩展的 **Agent Mode**。

它不是替代 AstrBot，而是把 AstrBot 已有的 provider、Agent Runner、tools、MCP、Skills、cron、conversation、plugin session config 组织成一个可以手搓个人 Agent 的运行层。

## 目标

- 让用户在 AstrBot 里创建自己的 Agent。
- 支持自然语言进入 Agent Mode，也支持命令和 WebUI 调试。
- 任务模式不是完全失忆：入口压缩普通上下文，任务期间使用独立 task_state，退出后归档并生成记忆候选。
- 支持会话级插件启用/禁用，不动全局插件开关。
- 支持心跳续跑：长任务醒来后先读状态，再执行，再保存。
- 支持审批协议：危险操作前由 bot 主动说明并请求用户确认。
- 把外部优秀 agent 设计收束成模块，方便后续接入 LangGraph、OpenAI Agents SDK、CrewAI、Microsoft Agent Framework 等方案。

## 安装

把本仓库作为 AstrBot 插件安装，或放入 `data/plugins/astrbot_plugin_agent_lab`。

```text
data/plugins/astrbot_plugin_agent_lab/
├── main.py
├── metadata.yaml
├── _conf_schema.json
├── agent_lab/
├── skills/
└── pages/
```

启动后插件会自动安装 `agent-mode` Skill，并在 AstrBot WebUI 的插件页面暴露 `Agent Lab` Page。

## 命令

```text
/agentlab status
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

## AgentSpec

AgentSpec 是用户手搓 Agent 的核心配置：

```json
{
  "name": "小莫 Agent Mode",
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

- 查看 Agents、Tasks、Plugins、Tools、Skills、Modules。
- 用 UMO 创建任务、手动 tick、开心跳、关心跳、完成归档。
- 后续可扩展成完整可视化 workflow builder。

## 模块系统

Agent Lab 会加载两类模块：

```text
modules/*.json
data/plugin_data/astrbot_plugin_agent_lab/modules/*.json
```

也就是说，用户可以把外部 agent 方案写成模块 manifest 放进插件数据目录，不用改主框架代码。

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

## 本地自检

```bash
python -m compileall -q .
python scripts/smoke_test.py
```

如果要检查 AstrBot API 兼容性，可把 AstrBot 源码加入 `PYTHONPATH` 后导入：

```bash
PYTHONPATH=/path/to/AstrBot/.. python -c "import astrbot_plugin_agent_lab.main"
```
