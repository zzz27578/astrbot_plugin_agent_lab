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
- Agent modules: plan, ReAct handoff, subflow and heartbeat/resume loops.

This means "detect garbage talk and ban", "call QQ manager then reduce favorability", "send a private warning", "generate a moderation report", "run a scheduled digest" and "continue a long coding task with heartbeat" are all first-class workflow variants.

## Trigger And Scope

Each workflow owns its own activation policy:

- Trigger switch: enabled or disabled per workflow.
- Trigger types: command, natural language, message monitor, keyword, regex, schedule, plugin event, webhook and manual WebUI.
- Scope: private chat, group chat, platform allowlist, UMO allow/deny, group allow/deny, user allow/deny.
- Admin-only: uses `workflow_admin_ids` in plugin config.

This replaces the old global/private-only mindset. The legacy `private_only` config remains only as a compatibility fallback and now defaults to `false`.

Backend trigger entrypoints now share one dispatcher:

- AstrBot web API: `POST /astrbot_plugin_agent_lab/workflow/trigger`.
- AstrBot web API: `POST /astrbot_plugin_agent_lab/workflow/webhook`.
- Standalone console API: `POST /api/workflow/trigger`.
- Standalone console API: `POST /api/workflow/webhook` or `POST /api/workflow/webhook/<path>`.
- Schedule workflows are rehydrated at plugin startup from `workflow_trigger.cron`.

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
- `llm_detect`: constrained fallback that returns `success` or `failed` when keywords are configured, otherwise `uncertain` instead of inventing an action.

Runtime routing now reads `result.data.route`, so detector/control modules can route to `success`, `failed`, `uncertain`, `error`, `timeout`, `retry` and `always` edges without requiring ReAct.

## Plugin And Tool Orchestration

The canvas can call tools, custom APIs and other plugin capabilities through modules. This reduces plugin-to-plugin compatibility pressure: other plugins do not need to know each other directly if Agent Lab can act as a small orchestration layer around events, calls, results and reports.

Examples:

- Monitor group messages, detect spam keywords, call a QQ manager ban tool, then send a report.
- Detect a user event from another plugin, call a favorability plugin action, then write a task record.
- Run a scheduled report workflow that queries tools/APIs, summarizes results and emails admins.
- Catch an API/plugin failure, route to retry, then notify an admin if the retry budget is exhausted.

Notification modules (`send_message`, `send_private_message`, `send_email`) currently write structured delivery intents to `task.workflow_data.outbox`. This is deliberate: Agent Lab records what should happen, and a platform/plugin adapter can consume the outbox item to perform the actual QQ/private-message/email delivery without hard-coding one plugin dependency.

Report and record modules are also deterministic:

- `write_record` appends structured records to `task.workflow_data.records`.
- `generate_report` appends immutable report snapshots to `task.workflow_data.reports`.
- `limit_rate` stores per-node buckets in `task.workflow_data.rate_limits`.
- `catch_error` routes based on blockers or the latest node output.

## Long Tasks Still Fit

Long tasks are a specialized workflow style:

- Heartbeat is a module, not the whole product.
- Memory isolation is a module/policy, not a global-only mode.
- Task memory export/reporting can be explicit workflow modules.
- Resume points and watchdog checks can be ordinary state/control nodes.

This keeps the original Agent-like runtime while expanding the product into a broader visual automation platform for AstrBot.
