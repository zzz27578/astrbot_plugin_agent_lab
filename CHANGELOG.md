# Changelog

## v0.2.0 — 子Agent 泳道 / 多Agent 协同 / 并发治理 + 素材审计

- 子Agent「泳道」：新增 `SubAgentSpec`(模型/角色/工具范围/领地/并发上限/限速)，内嵌 `AgentSpec.sub_agents`；节点新增 `owner` 归属字段；零迁移兼容老方案。
- 并发治理：并行 worker provider/工具/角色按 node.owner 的子Agent 解析；三层并发闸(泳道内按 owner 分桶 / 方案级 / 全局 tick 闸)；心跳错峰 jitter；资源锁(同标签跨泳道串行)；每泳道限速。新增配置 `global_max_concurrent_ticks`/`heartbeat_jitter_seconds`/`workflow_parallel_concurrency`。
- 多Agent 协同：共享黑板(`TaskState.workflow_data["blackboard"]`)+ 5 个协同节点(任务分配/报告整理/意见传达/事项讨论/汇总决策，debate 复用现成校验)。
- 素材体系审计与整改：64 个可见素材逐项过三准则(功能唯一/可配置/插入生效)，整改后 56✅/8🟡/0❌(docs/MATERIAL_AUDIT.md)；补齐协同节点编辑表单、隐藏重复换皮件、修正 memory_filter 元数据。
- n8n 对标补空白：新增 `note`(便签/No-Op) 与 `delay`(延时≤300s) 节点。
- 入口统一：入口节点检查器重构为单一「触发条件表」(暗号/命令/关键词/正则/自然语言/定时/插件事件/Webhook/启用/谁能触发/进入前确认三档)，合并原自动化面板与入口规则两处配置；自动化面板触发段改为摘要+指引，避免重复与覆盖。
- 确认三档：EntryPolicy 新增 confirmation_mode(off/fixed/prompt)，注入提示反映「关闭/固定话术/提示词生成」。
- 前端：子Agent 注册表抽屉(增删改查)、框选「指派」圈地、节点按 owner 上色、领地框渲染、provider free-text；协同/延时节点的画布模板与编辑表单。
- 自检：models/concurrency/orchestration/subagent-ui 四套 smoke + compileall + node --check 全过。可视化交互需在 AstrBot WebUI 实测。


## v0.1.1

- Added `NodeExecutorRegistry` and canonical workflow runtime types so canvas nodes normalize into entry/state/decision/parallel/tool/api/memory/guard/validation/notification/terminal/react categories.
- Added real backend executors for entry checkpoints, state checkpoints, task-memory read/write, registered API calls, deterministic route/retry/validation, approval/wait gates, notifications, terminal handoff, and parallel branches.
- Added `TaskState.workflow_data` with `node_outputs`, `variables`, `react_traces`, and execution counts so node outputs can feed later nodes and ReAct handoffs are auditable.
- Added workflow-report fields for executable nodes vs ReAct handoff nodes, plus archived Markdown visibility for node outputs and ReAct handoff summaries.
- Enforced AgentSpec tool isolation for direct tool nodes, direct API nodes, and parallel API workers so executable canvas nodes cannot bypass whitelist/no-external settings.
- Added `docs/RUNTIME_EXECUTOR.md` as a third-party audit reference for executable nodes, ReAct handoffs, node data flow, and isolation boundaries.
- Added a lightweight `WorkflowRuntime` so `tick` first advances deterministic canvas nodes, executes parallel branches, and hands only open-ended nodes to ReAct/tool-loop execution.
- Tightened task-memory isolation: archive summaries remain reviewable exposure candidates, while workflow/private memory candidates are hidden from normal chat unless explicitly exposed.
- Split task-mode settings, workflow canvas, and task memory into separate WebUI pages so the canvas can occupy the full workspace while settings stay readable.
- Reworked the workflow page into a full-screen background canvas with hidden normal topbar/feedback chrome, floating controls, wheel zoom, blank-canvas panning, a nav expand icon, and modal node editing.
- Added a Dify/n8n-style workflow workbench with collapsible left nav, right module drawer, right node inspector, right-click copy/delete, colored node-matching edges, viewport preservation after drag, and workflow dry-run diagnosis.
- Added workflow node fields for path/URL, upstream variable, output variable, and memory tags, plus fixed modules for document input, task-memory read/write, and rollback/resume entry.
- Added a dedicated task memory page with detail, accept/reject/delete actions, continuation draft, and archived-task rollback entry.
- Enlarged the workflow editor into a full-screen canvas with minimap, blank-canvas panning, wheel zoom, larger node port hit targets, and drag-or-click edge creation.
- Expanded the workflow node library with grouped entry/isolation/memory/planning/parallel/tool/API/safety/validation/exit modules plus code-task and memory-resume templates.
- Added executable parallel workflow branches through `agent_lab_run_parallel_workflow`, including registered API workers, restricted prompt/plugin/tool workers, `parallel_runs` state, and task-detail visibility.
- Rebuilt the Canvas page as the primary task-mode cockpit with explicit global-vs-entry application scope and command/natural/WebUI entry channels.
- Added persisted AgentSpec fields for application scope and entry channel, and injected them into runtime task-mode prompts.
- Added WebUI task-entry controls beside the selected AgentSpec and exposed cancel/archive plus approval approve/reject actions from the Tasks page.
- Reworked workflow visualization into a staged board with editable nodes, edge chips, add/delete controls, and advanced JSON kept as a fallback.
- Added standalone `/api/modules` route compatibility for blueprint import/update.
- Fixed runtime smoke test shutdown when AstrBot SDK import leaves helper threads alive.

## v0.1.0

- Initial Agent Lab plugin.
- Standardized repository identity around `astrbot_plugin_agent_lab`.
- Added beginner-facing README guidance for features, first run, WebUI access, and Dashboard security expectations.
- Added AgentSpec and TaskState persistence in plugin_data.
- Added private-session Agent Mode commands and LLM tools.
- Added entry and exit summarizers using AstrBot providers.
- Added session-level plugin override guard.
- Added manual tick and cron basic heartbeat runner.
- Added soft approval workflow for dangerous operations.
- Added plugin Page for WebUI testing and visualization.
- Added `agent-mode` Skill.
- Added built-in module registry for checkpoint, approval, heartbeat, memory, handoff, and flow adapters.
- Added explicit `agent_lab_read_state` and `agent_lab_update_state` tools.
- Added Agent run hooks to log tool start/end/done events into task_state.
- Added packaged module manifests for LangGraph, OpenAI Agents, Deep Agents, CrewAI, and Microsoft Agent Framework adapters.
- Added AstrBot builtin Computer Use tool catalog and default coding tool profile.
- Added morning acceptance checklist.
- Added mode-aware natural-language decision protocol synchronized through Skill and runtime prompts.
- Added WebUI Task Review, approval resolution, cancel flow, Archives, module toggles, and policy controls.
- Added multi-AgentSpec selection, duplication, creation, default-agent switching, and selected-Agent task starts.
- Added WebUI custom module editor and `/modules` API for saving adapter manifests.
- Reworked the WebUI into a Chinese structured console with separate task runtime, agent rules, capability switches, and module editor areas.
- Added clearer WebUI button feedback, disabled states, and local preview mode for layout testing.
- Removed hardcoded role names from defaults/docs; derived default and task-time Agent labels from AstrBot persona/config when available.
- Made raw AgentSpec defaults runtime-following as well, so plugin configuration no longer carries a baked-in bot display name before AstrBot resolves Persona/config.
- Replaced the Dashboard plugin Page with a standalone WebUI server (`standalone_webui_host`/`port`/`token`) and a five-section Agent Lab console.
- Separated AstrBot plugin isolation, registered tools, skills, and external integration blueprints in the WebUI.
- Added tool filtering so tools from Agent-disabled plugins are removed from Agent Mode runs.
- Added per-blueprint settings support through `module_settings`, `settings_schema`, and `default_settings`.
- Limited WebUI Tasks/state task listing to active tasks; finished and cancelled tasks live under Archives.
- Protected Agent Lab from being disabled by its own session plugin overrides.
- Added runtime identity source reporting so the standalone WebUI shows whether the current Bot label comes from AstrBot Persona, AstrBot config, or fallback.
- Replaced the default identity marker with `astrbot_runtime` while preserving compatibility with existing `astrbot_persona` AgentSpec files.
- Added registries for custom APIs, encrypted credentials, memory entries, task snapshots, workflow JSON, and provider-reported token usage.
- Added `agent_lab_call_custom_api`, a managed tool for calling WebUI-registered custom APIs with encrypted credentials.
- Added WebUI-editable `agent-mode` custom Skill rules saved under plugin_data and synced into the installed Skill.
- Added structured Canvas workflow node and edge editing, with JSON kept as an advanced fallback.
- Added per-AgentSpec tool risk overrides, risk-grouped tool UI, and editable approval scopes/actions.
- Added global-plugin-disabled hard boundary: Agent Mode can further disable plugins but cannot revive AstrBot globally disabled plugins.
- Reworked Plugins & Integrations into a left-subpage console; registered tools are now collapsible by source plugin and plugin-off tools are removed from the current Agent tool selection.
- Clarified external blueprints as rule modules rather than AstrBot plugins or direct tools, with visible settings schema/defaults in the WebUI.
- Added heartbeat health payloads (`online`/`idle`/`stale`/`blocked`/`off`) and monitor-page timeout badges/log rows.
- Added editable entry/exit summary rules in the Skills Rules page; they are saved in plugin_data and appended to the installed `agent-mode` Skill.
- Tightened Canvas wording around Agent Mode configuration so it does not read like a bot identity/persona editor.
- Kept blank WebUI AgentSpec names bound to `astrbot_runtime`, so new configurations inherit the current AstrBot Persona/config label instead of becoming a fixed template name.
- Added save-time AgentSpec sanitation so tools from globally disabled or Agent-disabled plugins cannot be persisted back into the enabled tool list.
- Added a clean WebUI AgentSpec draft flow with an explicit enabled/disabled control, so New is no longer just Duplicate with a blank name.
- Added WebUI import/update for external blueprint manifests, persisted under plugin_data modules for framework-upgrade compatibility.
- Rendered blueprint `settings_schema.properties` as fine-grained WebUI controls while keeping advanced JSON import/export as a compatibility fallback.
- Expanded dashboard Agent rows with per-configuration health, active task count, trigger count, Token total, and pending approval count.
- Reworked Task/Memory details into structured state fields, pending approvals, snapshot timelines, archive selection, and memory status filters.
