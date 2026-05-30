# Agent Lab Module Spec

Agent Lab 模块是把外部 agent 能力接入 AstrBot Agent Mode 的兼容层。

模块可以是三种形态：

1. **Prompt Module**：只注入协议和行为规范。
2. **Tool Module**：注册 AstrBot LLM tools 或 MCP tools。
3. **Runner Adapter**：把外部框架作为可选执行器，但仍回写 Agent Lab task_state。

## 最小模块字段

```json
{
  "module_id": "checkpoint_state",
  "name": "Checkpoint State",
  "source": "LangGraph persistence",
  "description": "每轮任务都落盘，支持恢复。",
  "prompt": "模块注入给 Agent 的行为协议。",
  "links": ["https://..."],
  "capabilities": ["state", "resume"],
  "requires": []
}
```

## 接入原则

- 外部模块不能绕过 Agent Lab task_state。
- 外部 runner 的每轮结果必须回写 `progress_log`、`last_observation`、`next_step`。
- 外部 memory store 只能通过 MemoryGate 进入任务上下文。
- 外部工具必须声明危险等级。
- 高危工具调用前优先由 Agent 自主请求审批，工具层只兜底。

## 推荐适配方向

### LangGraph Adapter

映射：

```text
LangGraph thread_id -> task_id
checkpoint -> progress_log/task_state
interrupt -> approval pending
resume -> heartbeat tick
```

### OpenAI Agents Adapter

映射：

```text
Agent instructions -> AgentSpec.system_prompt
tools -> AgentSpec.enabled_tools
handoffs -> handoff_adapter
guardrails -> approval_guard
sessions -> TaskState
```

### CrewAI Flow Adapter

映射：

```text
Flow state -> task_state
@start -> entry_summary
@listen -> workflow node transition
kickoff -> tick
plot -> WebUI workflow visualization
```

### Microsoft Agent Framework Adapter

映射：

```text
agent session -> TaskState
middleware -> approval/tool/memory guards
workflows -> future visual workflow
context providers -> MemoryGate
```

