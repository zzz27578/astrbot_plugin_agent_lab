# Adapter Guide

Agent Lab 的核心只负责 AstrBot-native 的 Agent Mode：AgentSpec、TaskState、插件过滤、工具白名单、审批、心跳和归档。外部 agent 框架不要直接替换核心，而是作为集成蓝图或适配器接进来。

## Adapter Boundary

外部方案接入时必须遵守这条边界：

```text
External framework
-> integration blueprint
-> Agent Lab task_state / approval / memory gate
-> AstrBot provider/tools/session/plugin runtime
```

也就是说，外部 runner 可以规划、执行或编排，但不能绕过 Agent Lab 的状态、审批和归档。

## Module Manifest

先把外部能力声明成 manifest，放到：

```text
data/plugin_data/astrbot_plugin_agent_lab/modules/<module_id>.json
```

```json
{
  "module_id": "my_runner_adapter",
  "name": "My Runner Adapter",
  "source": "my framework",
  "description": "把外部 runner 接入 Agent Lab。",
  "prompt": "运行时注入给 Agent 的行为协议。",
  "links": ["https://example.com/docs"],
  "capabilities": ["runner", "checkpoint"],
  "requires": ["checkpoint_state", "approval_guard"]
}
```

保存后刷新 WebUI，在“插件与集成 -> 外部方案库”中启用该蓝图并保存 AgentSpec。新任务会复制 AgentSpec 快照，运行中任务不会被后续修改突然影响。

## Runtime Contract

一个成熟 adapter 至少要实现：

- `load(task_state)`: 读取 Agent Lab 的当前状态。
- `step(input)`: 执行一个有限工作单元。
- `observe(result)`: 将外部框架输出压缩成 observation。
- `checkpoint(summary)`: 写回 `current_summary`、`last_confirmed_progress`、`next_step`。
- `interrupt(reason)`: 转成 Agent Lab approval 或 blocker。
- `finish(summary)`: 调用 Agent Lab finish 并归档。

## Recommended Mappings

### LangGraph

适合接入为 checkpoint/runner adapter。

```text
thread_id -> task_id
checkpoint -> TaskState snapshot
interrupt -> pending approval / blocker
resume -> heartbeat tick
```

要求：

- checkpoint 摘要必须同步进 `task_state`。
- interrupt 不允许直接继续执行，必须转成审批或阻塞。
- LangGraph 内部消息不能直接污染普通 AstrBot 会话上下文。

### OpenAI Agents SDK

适合接入 guardrails、handoffs、trace-like run hooks。

```text
instructions -> AgentSpec.system_prompt
tools -> AgentSpec.enabled_tools
guardrails -> approval_guard / blocker
handoffs -> handoff_adapter
session -> TaskState
```

要求：

- tool guardrail 结果必须进入审批或 blocker 日志。
- handoff 返回必须写回 `progress_log`。
- runner 完成后必须生成 exit summary 和 memory candidates。

### CrewAI Flows

适合接入可视化流程和状态化 workflow。

```text
Flow state -> TaskState
@start -> entry_summary
@listen -> node transition
kickoff -> tick
plot -> future WebUI workflow graph
```

要求：

- 每个节点必须能序列化：`node_id`、输入、输出、状态、下一跳。
- 人工节点必须使用 Agent Lab approval。
- Flow 不拥有最终记忆，最终归档仍由 Agent Lab 完成。

### Microsoft Agent Framework

适合接入企业级 session、middleware、workflow 和 MCP 工具管理。

```text
agent session -> TaskState
middleware -> approval/tool/memory guard
workflows -> Agent Lab flow_adapter
context providers -> MemoryGate
MCP clients -> tool catalog
```

要求：

- middleware 不能绕过 Agent Lab 审批。
- context provider 输出必须经过 MemoryGate。
- MCP 工具必须声明危险等级并进入工具白名单。

## Acceptance Checklist

接入一个外部方案后，用这些条件验收：

- WebUI 外部方案库能看到并启用该蓝图。
- 新任务的 AgentSpec 快照包含该蓝图。
- tick 前能读到 task_state。
- adapter 每轮都写回 progress、observation、next_step。
- 危险动作产生 approval，而不是直接执行。
- 连续三次同类失败后任务暂停或 blocked。
- finish/cancel 后归档文件出现在 Archives。

## References

- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- LangGraph durable execution: https://docs.langchain.com/oss/python/langgraph/durable-execution
- OpenAI Agents SDK: https://platform.openai.com/docs/guides/agents-sdk/
- OpenAI Agents guardrails: https://openai.github.io/openai-agents-python/guardrails/
- OpenAI Agents handoffs: https://openai.github.io/openai-agents-python/handoffs/
- CrewAI Flows: https://docs.crewai.com/en/concepts/flows
- Microsoft Agent Framework: https://learn.microsoft.com/en-us/agent-framework/overview/
