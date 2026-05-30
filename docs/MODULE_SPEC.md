# Agent Lab Module Spec

Agent Lab 模块是把外部 agent 能力接入 AstrBot Agent Mode 的兼容层。

模块可以是三种形态：

1. **Prompt Module**：只注入协议和行为规范。
2. **Tool Module**：注册 AstrBot LLM tools 或 MCP tools。
3. **Runner Adapter**：把外部框架作为可选执行器，但仍回写 Agent Lab task_state。

## 加载位置

Agent Lab 会自动加载：

```text
modules/*.json
data/plugin_data/astrbot_plugin_agent_lab/modules/*.json
```

前者用于插件内置模块，后者用于用户本地扩展。相同 `module_id` 后加载者会覆盖前者。

WebUI 的 Modules 面板可以直接新建模块，或把内置模块复制为自定义模块后保存。保存结果会写入：

```text
data/plugin_data/astrbot_plugin_agent_lab/modules/<module_id>.json
```

`module_id` 会被规范化为字母、数字、下划线、点和连字符组成的短 ID。

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

模块只负责声明协议、能力和适配要求。真正执行可以通过 AstrBot tools、MCP、skills、外部服务或 runner adapter 完成。

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

验收标准：

- 不直接把 LangGraph 内部上下文塞进普通 AstrBot prompt。
- 每次 checkpoint 摘要必须同步到 Agent Lab task_state。
- interrupt 必须转为 Agent Lab approval 或 blocked 状态。

### OpenAI Agents Adapter

映射：

```text
Agent instructions -> AgentSpec.system_prompt
tools -> AgentSpec.enabled_tools
handoffs -> handoff_adapter
guardrails -> approval_guard
sessions -> TaskState
```

验收标准：

- guardrails 结果必须进入 approval/blocker 日志。
- handoff 返回必须进入 progress_log。
- runner 结束后必须生成 exit_summary。

### CrewAI Flow Adapter

映射：

```text
Flow state -> task_state
@start -> entry_summary
@listen -> workflow node transition
kickoff -> tick
plot -> WebUI workflow visualization
```

验收标准：

- 每个 flow 节点必须有 node_id、输入、输出、状态。
- 节点状态必须能序列化进 task_state。
- 人工审批节点必须使用 Agent Lab approval。

### Microsoft Agent Framework Adapter

映射：

```text
agent session -> TaskState
middleware -> approval/tool/memory guards
workflows -> future visual workflow
context providers -> MemoryGate
```

验收标准：

- middleware 不得绕过 Agent Lab 审批。
- context provider 输出必须经过 MemoryGate 过滤。
- MCP 工具必须声明危险等级。
