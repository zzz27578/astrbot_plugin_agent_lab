# Runtime Executor Layer

This document is the implementation-level check for whether Agent Lab is acting as a task runtime instead of only rendering a large visual prompt.

## References Adapted

- LangGraph: graph/state/nodes/edges/checkpoint ideas. Agent Lab does not import LangGraph; it adapts the same separation between state, executable nodes, and routing.
- OpenAI Agents SDK: tools, handoffs, guardrails, and traces. Agent Lab adapts those ideas into AstrBot-native tool profiles, session plugin isolation, workflow handoffs, and task logs.
- ReAct: interleaved reasoning, action, and observation. Agent Lab uses ReAct only where deterministic execution is not possible, then records the handoff.

References:

- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://platform.openai.com/docs/guides/agents-sdk/
- https://platform.openai.com/docs/guides/agents
- https://openai.github.io/openai-agents-js/guides/handoffs/
- https://openai.github.io/openai-agents-js/guides/guardrails
- https://arxiv.org/abs/2210.03629

## What Is Executable Now

`agent_lab/node_runtime.py` introduces `NodeExecutorRegistry`. Canvas nodes are normalized into these runtime types:

```text
entry, state, decision, parallel, tool, api, memory, guard,
validation, notification, terminal, react
```

Registered executors now cover:

- `summarize_entry`, `confirm_entry`, `restore_isolation`
- `save_state`, `heartbeat`, `transform_context`
- `retrieve_memory`, `save_memory`
- `parallel_branch`
- `call_api`
- `run_tools`
- `route_condition`, `retry`, `validate_output`
- `request_approval`, `wait_user`, `handoff`
- `notify`
- `archive`, `exit_summary` as terminal ReAct handoff nodes

This means API nodes, tool nodes, memory checkpoints, approval/wait gates, validation gates, routing, and parallel branches have backend runtime semantics. They are no longer only text in the system prompt.

`agent_lab/agent_runtime.py` adds the task-level agent contract around that executor. It persists an `agent_instance`, a capability catalog, a workflow-derived `TaskPlan`, decision records, observation records, verifier-style verdicts, and a resume anchor under `TaskState.workflow_data.agent_runtime`.

`agent_lab/verifier.py` now owns the deterministic verifier checks used by finish, validation nodes, node execution, and parallel workers. It returns structured `passed/status/reason/missing/next_action` results, so finish requests can be denied when approvals are unresolved or runtime evidence is missing.

`agent_lab/workers.py` defines role-style worker specs for parallel branches (`ResearchWorker`, `CodeReaderWorker`, `PatchWorker`, `TestWorker`, `ReviewerWorker`, `SummarizerWorker`, plus API/tool/generic workers). Worker outputs are normalized with evidence, risks, and next recommendations before the main Agent merges them.

`agent_lab/policy.py` and `agent_lab/tool_executor.py` are the first extraction of tool governance from `main.py`: policy owns profile/capability/risk checks, while the tool executor owns direct AstrBot tool-node calls, schema validation, budget enforcement, isolation checks, and ReAct fallback decisions.

`agent_lab/memory_manager.py` owns long-term memory transitions. Archive summaries are accepted evidence, but `memory_candidates` stay private candidates until a user or WebUI action accepts them. Accepted memories keep evidence history and become visible to normal mode; rejected memories stay private and non-authoritative.

`agent_lab/service.py` introduces the service boundary for runtime operations. `AgentLabService.run_tick()` is now the command/tool/WebUI entrypoint for task ticks. `agent_lab/runtime_runner.py` owns the main tick loop beneath that service, while `main.py` keeps AstrBot command/tool/cron/WebUI adapter methods.

## What Still Uses ReAct

ReAct is still used intentionally for open-ended work:

- Planning nodes.
- Manual nodes.
- Ambiguous branch choices.
- Tool nodes without both `tool_name` and concrete JSON `tool_args` or upstream `input_variable`.
- Terminal summary/archive nodes.
- Any unknown or unsupported node action.

Those handoffs are recorded in `TaskState.workflow_data.react_traces` with the node id, prompt, response, and reason.

## Node Data Flow

`TaskState.workflow_data` stores:

- `agent_runtime`: structured AgentInstance / capabilities / TaskPlan / decisions / observations / verdicts / resume.
- `node_outputs`: last structured output for each executed node.
- `variables`: named outputs available to later nodes.
- `react_traces`: ReAct/tool-loop handoff audit trail.
- `execution_counts`: retry and loop guard support.

If a node defines `output_variable`, its result is saved into `variables`. Later nodes can read it with `input_variable`.

Archived Markdown now includes `Agent Runtime`, `Workflow Node Outputs`, and `ReAct Handoffs`, so runtime behavior is visible after task completion.

## Isolation Boundary

Executable nodes obey the same isolation intent as the LLM tool loop:

- Direct `run_tools` nodes require the bound tool to be allowed by the AgentSpec tool profile.
- Direct `call_api` nodes require `agent_lab_call_custom_api` to be allowed by the AgentSpec tool profile.
- Parallel API workers also require `agent_lab_call_custom_api`.
- Plugin-sourced tools are filtered by session plugin isolation and global plugin activation.
- `no_external` blocks external tool and Custom API execution.

This prevents the canvas executor from bypassing plugin/tool isolation.

## Inspection Contract

`agent_lab_update_workflow check` now reports:

- `runtime_types`
- `executor_nodes`
- `react_handoff_nodes`
- `node_runtime`

Use those fields to check which nodes are real executors and which nodes will be handed to ReAct.

Use `/agentlab runtime` or `agent_lab_read_runtime` to inspect the live task runtime: current plan node, granted capabilities, last verifier verdict, pending steps, and resume command.

## Honest Boundary

This is now an AstrBot-native task runtime layer with executable workflow nodes, state persistence, ReAct handoff traces, capability catalogs, structured task plans, verifier verdicts with denial paths, typed parallel worker specs, policy-backed tool execution, evidence-linked memory acceptance, memory isolation, plugin/tool filtering, and heartbeat support.

It is not yet a complete mature external framework runner. Missing future work includes richer tool argument schemas, expression evaluation for variables, a stronger watchdog/lease heartbeat model, and optional adapters for external runtimes such as LangGraph or OpenAI Agents SDK.
