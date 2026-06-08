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
trigger, entry, detector, state, decision, parallel, tool, api, memory,
guard, validation, notification, report, terminal, react
```

Workflow compilation also normalizes backend module contracts:

- `port_schema.inputs` / `port_schema.outputs` declare legal connection ports.
- `special_module` marks listener, detector, loop and control modules.
- Edge `from_port` / `to_port` are preserved; `from_port` can infer `edge_type` when the edge type is omitted.
- `/workflow/check` returns `special_modules`, `port_schemas` and per-node `node_runtime` for inspection.

Registered executors now cover:

- `summarize_entry`, `confirm_entry`, `restore_isolation`
- `save_state`, `heartbeat`, `transform_context`
- `variable_set`, `variable_get`, `text_template`, `json_transform`
- `merge`, `iterator`, `subflow_call`
- `retrieve_memory`, `save_memory`, `summarize_memory`, `export_task_memory`, `promote_memory_candidate`, `forget_task_memory`
- `parallel_branch`
- `call_api`, `http_request`
- `run_tools`, `file_operation`, `code_exec`
- `route_condition`, `conditional_router`, `retry`
- `listen_message`, `schedule_trigger`, `plugin_event_trigger`, `webhook_trigger`
- `match_keyword`, `match_regex`, `llm_detect`, `scope_filter`
- `limit_rate`, `catch_error`, `write_record`, `generate_report`
- `send_message`, `send_private_message`, `send_email`, `deliver_outbox`
- `validate_output`, `debate_validation`
- `request_approval`, `wait_user`, `handoff`
- `notify`
- `archive_task` as deterministic workflow archive
- `archive`, `exit_summary` as terminal ReAct handoff nodes

This means state mutation, variable reads, template rendering, simple JSON path extraction, merges, iterator preparation, API/HTTP calls, tool calls, sandbox-scoped file operations, guarded code execution, memory checkpoints, approval/wait gates, validation gates, routing, and parallel branches have backend runtime semantics. They are no longer only text in the system prompt.

`subflow_call` is currently a deterministic preparation node: it resolves the template id and parameters and records them for the parent workflow. A nested subflow runner is still future work.

`/modules` now returns discovered module catalogs in addition to user-defined module manifests: installed AstrBot plugins, registered tools, and Agent Lab builtin actions. This lets the future canvas become a scanner/orchestrator for downloaded plugins and their tools instead of depending on a fixed template pack.

`/workflow/runs` returns workflow-centric active/archive rows with trigger payloads, latest path events, reports, records, outbox status and heartbeat health. It is the backend contract for a future workflow run management UI.

`agent_lab/agent_runtime.py` adds the task-level agent contract around that executor. It persists an `agent_instance`, a capability catalog, a workflow-derived `TaskPlan`, decision records, observation records, verifier-style verdicts, and a resume anchor under `TaskState.workflow_data.agent_runtime`.

`agent_lab/verifier.py` now owns the deterministic verifier checks used by finish, validation nodes, node execution, and parallel workers. It returns structured `passed/status/reason/missing/next_action` results, so finish requests can be denied when approvals are unresolved or runtime evidence is missing.

`agent_lab/workers.py` defines role-style worker specs for parallel branches (`ResearchWorker`, `CodeReaderWorker`, `PatchWorker`, `TestWorker`, `ReviewerWorker`, `SummarizerWorker`, plus API/tool/generic workers). Worker outputs are normalized with evidence, risks, and next recommendations before the main Agent merges them.

`agent_lab/policy.py` and `agent_lab/tool_executor.py` are the first extraction of tool governance from `main.py`: policy owns profile/capability/risk checks, while the tool executor owns direct AstrBot tool-node calls, schema validation, budget enforcement, isolation checks, and ReAct fallback decisions.

`agent_lab/api_executor.py` owns registered Custom API execution: registry lookup, JSON argument parsing, static header merging, credential injection, HTTP transport, response truncation, and the compatibility test hook used by node and worker runtimes. API execution still goes through the same tool-profile permission checks before this executor is reached.

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
- `tool_outputs`: normalized audit rows for tool-like nodes, including `run_tools`, `call_api`, `http_request`, `file_operation`, and `code_exec`.
- `records`, `reports`, `outbox`, `outbox_delivery_history`, `memory_exports`, `memory_summary`: deterministic outputs for static/event workflows.

If a node defines `output_variable`, its result is saved into `variables`. Later nodes can read it with `input_variable`.

Nodes may also define `required_inputs`, `input_schema`, and `output_schema`. Required inputs are resolved against the workflow condition context before execution; input/output schemas use the local schema validator and block the node before downstream execution if the contract is not satisfied.

Nodes may define `timeout_seconds` and `retry_policy`. Runtime execution wraps registered executors with bounded timeout/retry handling and records the final `attempts` count in `node_outputs`.

Archived Markdown now includes `Agent Runtime`, `Workflow Node Outputs`, and `ReAct Handoffs`, so runtime behavior is visible after task completion.

## Edge Routing

Workflow edges are normalized with an `edge_type`:

- `success`: follows completed node results.
- `failed`: follows explicit failed detector/control results.
- `uncertain`: follows detector results that cannot safely decide.
- `error`: follows blocked or failed node results.
- `retry`: follows loop/retry modules back to a body node.
- `timeout`: follows timeout results.
- `approved` / `rejected`: follows approval guard results.
- `always`: eligible for either result.

Edge `condition` expressions are evaluated against the same workflow context used by variables. `condition_visual` is preserved for WebUI round-tripping. When a registered executor returns `ok=False` or `blocked=True`, the runtime first looks for matching `error`/`always` edges before globally blocking the task.

Retry/loop modules are special route producers. While under budget they emit `route=retry`; once exhausted they emit `route=failed`, so the canvas can connect a retry body and a separate failure/report path.

LLM detector nodes are constrained route producers. If no deterministic keyword rule is present, `llm_detect` asks the AstrBot provider for a JSON object containing only `route`, `reason`, `evidence` and `confidence`; unsupported routes or low confidence become `uncertain`.

`archive_task` is deterministic and can close short/static workflows without pretending they are long Agent Mode tasks. It still runs the archive side effects: heartbeat disable, session plugin restore, archive evidence, memory orchestrator, markdown/json archive, and task pattern capture. `archive` and `exit_summary` remain ReAct handoff terminal nodes for workflows that need a final LLM summary/verifier pass.

## Isolation Boundary

Executable nodes obey the same isolation intent as the LLM tool loop:

- Direct `run_tools` nodes require the bound tool to be allowed by the AgentSpec tool profile.
- Direct `call_api` nodes require `agent_lab_call_custom_api` to be allowed by the AgentSpec tool profile.
- Direct `http_request` nodes also require `agent_lab_call_custom_api` and the node permission profile must allow API work.
- `file_operation` nodes require `astrbot_file_read_tool` or `astrbot_file_edit_tool`, and paths must stay under `plugin_data/.../sandbox_workspace`.
- `code_exec` nodes require the corresponding sandbox tool name and a `danger` permission profile because they are high-risk. The current implementation runs a bounded local subprocess in the sandbox workspace; it is gated and timed out, but it is not a container runtime.
- Parallel API workers also require `agent_lab_call_custom_api`.
- Plugin-sourced tools are filtered by session plugin isolation and global plugin activation.
- `no_external` blocks external tool and Custom API execution.

This prevents the canvas executor from bypassing plugin/tool isolation.

## Inspection Contract

`agent_lab_update_workflow check` now reports:

- `runtime_types`
- `special_modules`
- `port_schemas`
- `executor_nodes`
- `react_handoff_nodes`
- `node_runtime`

Use those fields to check which nodes are real executors and which nodes will be handed to ReAct.

Use `/agentlab runtime` or `agent_lab_read_runtime` to inspect the live task runtime: current plan node, granted capabilities, last verifier verdict, pending steps, and resume command.

## Honest Boundary

This is now an AstrBot-native task runtime layer with executable workflow nodes, state persistence, ReAct handoff traces, capability catalogs, structured task plans, verifier verdicts with denial paths, typed parallel worker specs, policy-backed tool execution, evidence-linked memory acceptance, memory isolation, plugin/tool filtering, and heartbeat support.

It is not yet a complete mature external framework runner. Missing future work includes richer tool argument schemas, expression evaluation for variables, a stronger watchdog/lease heartbeat model, and optional adapters for external runtimes such as LangGraph or OpenAI Agents SDK.
