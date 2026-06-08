# Agent Lab Workflow Automation

Agent Lab is now positioned as an AstrBot visual automation workflow layer, not only as a long-task Agent Mode plugin.

The old long-task goal still matters: heartbeat tasks, agent-like execution, task memory, task isolation and resumable state remain core modules. The change is that they are no longer the only shape of work. A canvas workflow can also be a static or event-driven automation that starts when a message, command, schedule, plugin event or webhook matches its trigger rules.

## Workflow Shape

Workflows are composed from modules. The module graph determines the task shape:

- Trigger modules: command, natural language, message monitor, keyword, regex, schedule, plugin event and webhook.
- Detector modules: keyword detector, regex detector, LLM constrained detector and scope filter.
- Action modules: AstrBot tool calls, custom API calls, plugin capability calls, notification, private message and email.
- State modules: task state, task memory, variable store, record writing and report generation.
- Control modules: retry loop, rate limit, approval, human handoff, error catch and timeout routes.
- Identity/session modules: credential references, cookie jars, browser profiles, login handoff, session checks, refresh and revocation.
- Prompt modules: bounded `llm_prompt` / `prompt_transform` nodes for local LLM transformations with explicit output contracts.
- Agent modules: plan, ReAct handoff, subflow and heartbeat/resume loops.

This means "detect garbage talk and ban", "call QQ manager then reduce favorability", "send a private warning", "generate a moderation report", "run a scheduled digest" and "continue a long coding task with heartbeat" are all first-class workflow variants.

## Trigger And Scope

Each workflow owns its own activation policy:

- Trigger switch: enabled or disabled per workflow.
- Trigger types: command, natural language, silent global monitor, received-message monitor, keyword, regex, schedule, plugin event, webhook and manual WebUI.
- Scope: private chat, group chat, platform allowlist, UMO allow/deny, group allow/deny, user allow/deny.
- Admin-only: uses `workflow_admin_ids` in plugin config.

This replaces the old global/private-only mindset. The legacy `private_only` config remains only as a compatibility fallback and now defaults to `false`.

Backend trigger entrypoints now share one dispatcher:

- AstrBot web API: `POST /astrbot_plugin_agent_lab/workflow/trigger`.
- AstrBot web API: `POST /astrbot_plugin_agent_lab/workflow/webhook`.
- Standalone console API: `POST /api/workflow/trigger`.
- Standalone console API: `POST /api/workflow/webhook` or `POST /api/workflow/webhook/<path>`.
- Schedule workflows are rehydrated at plugin startup from `workflow_trigger.cron` or `workflow_trigger.cron_expressions`.
- Command simulation: `/agentlab trigger <source> [agent=<agent_id>] <text>`.
- Native message monitor: AstrBot `event_message_type(EventMessageType.ALL)` can trigger `silent_global`, `message_monitor`, `keyword`, `regex` and `natural` workflows without requiring an LLM request.
- LLM-request monitor: optional compatibility path controlled by `workflow_message_monitor_on_llm_request_enabled`.
- Duplicate protection: trigger payloads are deduped for a short TTL so native hooks and LLM hooks do not create duplicate runs for the same message.

The trigger payload is written into `task.workflow_data.trigger_payload` and `variables.trigger_payload`, then the deterministic workflow runtime runs immediately for event-style workflows.

## Detectors And Routes

Detector modules should make route decisions explicit:

- `success`: passed or matched.
- `failed`: not passed or not matched.
- `uncertain`: detector cannot decide safely.
- `error`: detector or dependency failed.
- `retry`: retry loop route.
- `approved` / `rejected`: approval routes.
- `timeout`: timed out.
- `always`: unconditional route.

LLM detectors are allowed, but should be constrained by templates, output schema and route labels. They should not freely decide actions. The canvas should guide users to define "passed", "failed" and "uncertain" behavior directly.

Backend detector executors currently implement:

- `match_keyword`: deterministic keyword match against trigger text or node input.
- `match_regex`: deterministic regex match against trigger text or node input.
- `scope_filter`: deterministic workflow scope check.
- `llm_detect`: first honors deterministic keywords when configured; otherwise calls the configured AstrBot provider with a strict JSON-only route contract: `success`, `failed`, `uncertain` or `error`, plus reason/evidence/confidence. Low confidence is downgraded to `uncertain`.

Runtime routing now reads `result.data.route`, so detector/control modules can route to `success`, `failed`, `uncertain`, `error`, `timeout`, `retry` and `always` edges without requiring ReAct.

## Special Module Compilation

The backend now compiles special module contracts instead of treating every node as a generic box:

- Listener modules (`listen_message`, `schedule_trigger`, `plugin_event_trigger`, `webhook_trigger`) have no normal input port and expose trigger result ports such as `success`, `failed` and `error`.
- Detector modules expose `success`, `failed`, `uncertain` and `error` ports.
- Loop/retry modules expose reversed control semantics: inputs include `start`, `retry` and `error`; outputs include `retry`, `success`, `failed` and `error`.
- Edge `from_port` / `to_port` are preserved, and `from_port` can infer `edge_type`, so a `from_port=retry` edge becomes a retry route even if the UI did not set `edge_type` explicitly.

`/workflow/check` returns `special_modules`, `port_schemas` and `node_runtime`, and warns when listener triggers, detector routes or loop exits are incomplete.

## Plugin And Tool Orchestration

The canvas can call tools, custom APIs and other plugin capabilities through modules. This reduces plugin-to-plugin compatibility pressure: other plugins do not need to know each other directly if Agent Lab can act as a small orchestration layer around events, calls, results and reports.

Examples:

- Monitor group messages, detect spam keywords, call a QQ manager ban tool, then send a report.
- Detect a user event from another plugin, call a favorability plugin action, then write a task record.
- Run a scheduled report workflow that queries tools/APIs, summarizes results and emails admins.
- Catch an API/plugin failure, route to retry, then notify an admin if the retry budget is exhausted.

Notification modules (`send_message`, `send_private_message`, `send_email`) currently write structured delivery intents to `task.workflow_data.outbox`. This is deliberate: Agent Lab records what should happen, and a platform/plugin adapter can consume the outbox item to perform the actual QQ/private-message/email delivery without hard-coding one plugin dependency.

`deliver_outbox` prepares same-session delivery items and leaves cross-session/platform-specific items in the outbox for adapter/plugin consumption. This keeps Agent Lab from hard-coding QQ/email adapter internals while still making delivery intent visible to workflow runs.

Report and record modules are also deterministic:

- `write_record` appends structured records to `task.workflow_data.records`.
- `generate_report` appends immutable report snapshots to `task.workflow_data.reports`.
- `limit_rate` stores per-node buckets in `task.workflow_data.rate_limits`.
- `catch_error` routes based on blockers or the latest node output.

Installed AstrBot plugins and registered tools are exposed as discovered workflow modules from `/astrbot_plugin_agent_lab/modules`:

- `plugin:<plugin_name>` modules represent installed/downloaded AstrBot plugins and their inferred capabilities.
- `tool:<tool_name>` modules represent registered LLM tools with input/output schema, risk and source plugin metadata.
- `builtin:<action>` modules represent Agent Lab native actions such as listener, detector, retry, memory, outbox and archive modules.

The backend does not need a fixed template library for cases like moderation, favorability changes or admin notifications. The canvas can scan these discovered modules and bind concrete plugin/tool actions at edit time.

Workflow run management is available at `GET /astrbot_plugin_agent_lab/workflow/runs`. It returns active/archive rows with trigger payload, path, latest events, reports, records, pending outbox and heartbeat health.

## Identity, Cookie And Login Modules

Account maintenance workflows need identity state, but secrets must not become prompt text. Agent Lab therefore exposes identity/session modules as references and checks rather than raw cookie injection:

- `credential_ref`: bind a stored credential ID and expose only masked metadata plus a usable session reference.
- `cookie_jar`: describe a cookie store/domain reference without writing cookie values into node output.
- `browser_profile`: bind a persistent browser profile path or profile name for tools/adapters that can use it.
- `login_flow` and `human_login_handoff`: pause for admin login, captcha, 2FA or risk verification.
- `session_check` and `refresh_session`: verify or refresh a referenced login/session state.
- `credential_scope`: check whether the workflow is allowed to use a requested credential/provider/scope.
- `secret_redaction`: scrub known credentials and token/cookie-looking fields from text before reporting or archiving.
- `revoke_session`: remove the workflow session reference when the flow is done.

For GitHub repository maintenance, prefer GitHub App/PAT/OAuth/API or a registered AstrBot tool first. Browser cookies and profile sessions are a fallback for sites without suitable APIs, and should normally be paired with `human_login_handoff`, `credential_scope` and `secret_redaction`.

## Prompt Modules

`llm_prompt` and `prompt_transform` are the safe version of an empty prompt box. They are useful for classification, extraction, rewriting, report drafting and field normalization between structured nodes. They should not directly receive secrets.

Recommended fields:

- `input_variable` or `input`: where the prompt reads from.
- `system_prompt` and `prompt` / `user_prompt`: local behavior contract.
- `output_mode`: `text`, `json` or `route`.
- `output_schema`: optional JSON schema checked by the runtime.
- explicit `success`, `failed`, `uncertain` and `error` routes when the output is used for branching.

## Long Tasks Still Fit

Long tasks are a specialized workflow style:

- Heartbeat is a module, not the whole product.
- Memory isolation is a module/policy, not a global-only mode.
- Task memory export/reporting/promotion/forgetting can be explicit workflow modules: `summarize_memory`, `export_task_memory`, `promote_memory_candidate`, `forget_task_memory`.
- Resume points and watchdog checks can be ordinary state/control nodes.

Short/long task shape is determined by the workflow graph, not by a hardcoded task type. `archive_task` is the deterministic archive module for event/static workflows. `exit_summary` remains a terminal ReAct handoff for long tasks that need an LLM-written final summary and verifier-style completion evidence.

This keeps the original Agent-like runtime while expanding the product into a broader visual automation platform for AstrBot.
