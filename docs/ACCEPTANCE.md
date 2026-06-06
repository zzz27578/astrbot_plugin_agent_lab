# 验收清单

用这份清单在真实 AstrBot 实例里验收 Agent Lab。

## Repository Checks

```text
python -m compileall -q .
python scripts/smoke_test.py
python scripts/runtime_smoke_test.py
```

Expected:

- Python compile succeeds.
- Smoke test prints `Agent Lab smoke test passed.`
- Runtime smoke test prints `Agent Lab runtime smoke test passed.` when AstrBot SDK/source is importable.
- Runtime executor behavior is documented in `docs/RUNTIME_EXECUTOR.md`, and workflow checks expose `runtime_types`, `executor_nodes`, `react_handoff_nodes`, and `node_runtime`.
- Runtime smoke verifies `agent_runtime` contains an AgentInstance, capability catalog, TaskPlan, observations, verifier verdicts, resume anchor, and archived Markdown section.
- Runtime smoke verifies deterministic canvas nodes execute without ReAct handoff: variable set/get, text template, JSON transform, merge, iterator, HTTP request, direct tool/API calls, memory save, validation, and debate validation.
- Runtime smoke verifies failed node results can advance through `edge_type=error` instead of immediately blocking the whole workflow.
- Runtime smoke verifies premature finish is denied without runtime evidence, and parallel workers expose worker specs, evidence, risks, and next recommendations.
- Runtime smoke verifies archived memory candidates stay private until accepted, then become accepted evidence-linked memory visible to normal reads.

## Install Checks

1. Install this repo as an AstrBot plugin.
2. Reload plugins or restart AstrBot.
3. Confirm plugin appears as `Agent Lab`.
4. Confirm `agent-mode` Skill is active.
5. Open standalone console, default `http://127.0.0.1:8788`.

Note:

- Agent Lab WebUI is no longer an AstrBot Dashboard plugin Page.
- Host, port, and optional API token are controlled by plugin config.
- If binding outside localhost, configure `standalone_webui_token`.

WebUI 预期：

- Shows sidebar pages: Dashboard, Task Mode Settings, Workflow Canvas, Task Memory, Tasks/Memory, Monitor, Plugins/Integrations.
- Shows current Bot label and identity source; it must come from AstrBot Persona/config when available, not a hardcoded character name.
- Leaving the Canvas configuration name empty should keep `identity_label_source=astrbot_runtime` and use the current AstrBot Persona/config label.
- Agents can be selected, duplicated, created, and marked as default in Canvas.
- Task Mode Settings keeps triggers, entry/exit phrases, confirmation copy, isolation, memory, approval, heartbeat, and prompts separate from the large workflow diagram.
- Workflow Canvas is a full-screen background workspace rather than an embedded page module; the normal token/refresh/topbar/feedback chrome is hidden while workflow controls float above the canvas.
- Workflow Canvas supports mouse-wheel zoom around the pointer, minimap, node dragging without snapping viewport back to origin, blank-canvas panning without inner scrollbars, edge-port linking from node border dots by drag or click-to-connect, colored node-matching edges, right-click copy/delete, edge deletion, auto layout, workflow check, and a dry-run diagnosis.
- Workflow Canvas collapses the left nav by default, provides a small expand/collapse icon, uses a right-side module drawer, and opens a modal node editor for left-click editing without stealing canvas width.
- Canvas node library groups entry, isolation, input, memory, planning, parallel, tool, API, safety, validation, and exit modules so common task-mode blocks do not require hand-written JSON.
- Canvas toolbox can add AstrBot plugin, custom API, and whitelisted tool modules as workflow nodes, and node inspector can edit instruction, condition, path/url, input/output variables, tags, and node prompt without forcing users to edit X/Y coordinates.
- Workflow check and dry-run report missing entry/archive, entry summary, isolation snapshot, task memory, unreachable nodes, invalid API refs, isolated plugins, tools outside whitelist, file/document modules without inputs, dangerous actions without approval gates, and memory save nodes without tags/schema/prompt.
- Parallel branch nodes can be executed by `agent_lab_run_parallel_workflow`; API workers call registered Custom APIs, prompt/plugin/tool workers run through a restricted AstrBot `tool_loop_agent`, and task details show the resulting worker statuses.
- Dashboard Agent rows show per-configuration health, active count, trigger count, token total, and pending approval count.
- Shows active tasks and archives.
- Task/Memory console can select both active and archived tasks and show structured state fields, pending approvals, and snapshot timeline.
- Task/memory console has tick/heartbeat/finish/cancel actions.
- Task Memory page can filter memories, show detail and continuation draft, accept/reject/delete memory rows, and send a memory or archived task into a new task brief.
- Plugins/Integrations uses sub-pages or equivalent navigation so large plugin/tool/blueprint lists are not one flat page.
- Shows AstrBot plugins separately from external integration blueprints.
- Agent Lab plugin itself is locked and cannot be disabled from its own task profile.
- Globally disabled AstrBot plugins show as unavailable and cannot be revived by Agent Mode.
- 新建 AgentSpec 默认使用严格隔离；未显式允许的普通 AstrBot 插件在 Agent Mode 会话中关闭。
- 关闭某个 AstrBot 插件后，该插件来源工具会在注册工具视图和 runtime toolset 中不可用。
- Saving an AgentSpec also removes tools that belong to globally disabled or Agent-disabled AstrBot plugins.
- Shows Tools grouped or collapsible by source, including builtin catalog tools such as `astrbot_execute_shell`.
- Shows `agent_lab_call_custom_api` when custom API calling is available.
- Shows Skills.
- Shows integration blueprints, including LangGraph/OpenAI/CrewAI/Microsoft adapters.
- External blueprint page can import/update a manifest and save it into plugin_data without changing framework code.

## Private Chat Flow

Run in a private chat:

```text
/agentlab status
/agentlab start 请测试 Agent Lab 的任务状态是否能创建、推进和归档
/agentlab status
/agentlab tick
/agentlab finish 测试完成
```

Expected:

- `start` creates an active task.
- `status` shows task id, goal, next step, state file path.
- `/agentlab runtime` shows capability count, active TaskPlan steps, last verdict, waiting reason, and resume command.
- `tick` calls the model/tool loop and updates task markdown.
- `finish` archives task and restores session plugin config.
- Finished task is removed from Tasks and appears in Archives.

## State Continuity Checks

Check plugin data directory:

```text
data/plugin_data/astrbot_plugin_agent_lab/
```

Expected:

- `agents/<agent_id>.json` exists.
- `sessions/<umo_hash>/task_<id>.json` exists after start.
- `sessions/<umo_hash>/task_<id>.md` contains progress log.
- `task_<id>.json` contains `workflow_current_node_id`, `workflow_path`, and `workflow_events`; markdown contains `Workflow Cursor`.
- When a parallel workflow runs, `task_<id>.json` contains `parallel_runs`, the cursor advances to the merge node when one is found, and markdown contains `Parallel Workflow Runs`.
- `archives/<umo_hash>/task_<id>.md` exists after finish.

## Heartbeat Checks

Run:

```text
/agentlab start 请创建一个需要心跳的测试任务
/agentlab heartbeat on
/agentlab status
/agentlab heartbeat off
/agentlab cancel 测试结束
```

Expected:

- Heartbeat job id is created.
- Task markdown records `heartbeat_on`.
- Turning off heartbeat deletes job id and records `heartbeat_off`.

## Approval Checks

Ask naturally:

```text
进入 Agent Mode，然后准备删除一个测试目录，先走审批。
```

Expected:

- Bot calls or suggests `agent_lab_request_approval`.
- `/agentlab status` shows pending approvals.
- `/agentlab approve <approval_id>` resolves it.

## Natural Language Trigger Checks

Set AgentSpec trigger mode in WebUI and ask the bot a private-chat task such as:

```text
请帮我把这个插件排错并持续记录进度。
```

Expected:

- `manual`: bot should not auto-enter unless the user explicitly asks for Agent Mode or uses a command/WebUI.
- `confirm`: bot should explain why Agent Mode fits and ask for confirmation.
- `smart`: bot may enter for low-risk planning/analysis, but asks first before file writes, shell commands, deployment, deletion, plugin shutdown, or secret access.
- `always`: bot should prefer Agent Mode for actionable multi-step tasks while still requesting approval for dangerous operations.

## WebUI Editing Checks

In Agent Lab standalone console:

1. Change the Agent Mode configuration name, then confirm it becomes manual instead of auto-following the current Bot label.
2. Change trigger mode.
3. Change memory/approval/heartbeat modes.
4. Toggle a plugin.
5. Confirm tools from the disabled plugin are no longer selected/available for the current Agent.
6. Toggle a tool.
7. Change a tool risk level.
8. Edit approval preapproved scopes and required approval actions.
9. Toggle a skill.
10. Toggle an integration blueprint and edit its schema-rendered fine settings; confirm advanced JSON is still available.
11. Import or update a custom external blueprint manifest from the blueprints page.
12. Add a workflow node.
13. Drag a workflow node and confirm the position changes without resizing the canvas oddly or snapping the viewport back to the origin.
14. Add a node from the node material toolbox.
15. Edit the selected workflow node title/kind/description/path or variable/tags.
16. Add and delete a workflow edge from the node border dots.
17. Right-click a workflow node and confirm copy/delete works.
18. Run workflow check and dry-run diagnosis.
19. Open Task Memory, select a memory, and send memory/archive context into a new task brief.
20. Save AgentSpec.
21. Duplicate the AgentSpec.
22. Set the duplicate as default.
20. Refresh.

Expected:

- Changes persist.
- New task uses AgentSpec snapshot.
- Workflow nodes and edges persist without editing raw JSON.
- WebUI task start uses the selected Agent.
- `/agentlab use <agent_id>` changes the default Agent for natural-language/command starts.
- Selected skills are shown in the Agent Mode runtime prompt for task ticks.
- Edited `agent-mode` custom Skill rules persist and appear in the task tick runtime prompt.
- Edited entry/exit summary rules persist and are used by task entry compression and exit archival summarization.
- Tool risk overrides and approval policy appear in the Agent Mode runtime prompt for task ticks.
- Tools belonging to plugins disabled in Agent Mode are shown as unavailable and are filtered from task ticks.
- Selected integration blueprints are shown in the Agent Mode runtime prompt for task ticks.
- Custom imported blueprints remain under `plugin_data/astrbot_plugin_agent_lab/modules` and are still available after refresh.

## WebUI Review Checks

Create a task from WebUI or private chat, then use Task/Memory console:

1. Select a task.
2. Click `Tick`.
3. Toggle heartbeat.
4. Resolve a pending approval if one exists.
5. Finish or cancel the task.

Expected:

- Task/Memory console updates after each action.
- Selected task detail shows current summary, confirmed progress, next step, last observation, pending approvals, and state snapshots without requiring raw JSON reading.
- Finished/cancelled task appears in Archives.
- Archived task can be selected and inspected after finish/cancel.
- Memory candidates can be filtered by all/candidate/accepted/rejected.
- `archives/<umo_hash>/task_<id>.md` exists.

## Integration Blueprint Checks

In the Plugins & Integrations page:

1. Select an existing integration blueprint.
2. Toggle it into the selected AgentSpec.
3. Edit its fine-grained settings JSON.
4. Save settings into the Agent draft.
5. Save AgentSpec.
6. Start a new task.

Expected:

- New task snapshot includes the selected integration blueprint.
- Tick runtime prompt includes the blueprint prompt and selected settings.

## Custom API Checks

In the Plugins & Integrations page:

1. Save a credential in Credentials.
2. Register a Custom API that references the credential.
3. Confirm the selected AgentSpec has `agent_lab_call_custom_api` enabled.
4. Start a task and ask the bot to call the registered API by purpose or api_id.

Expected:

- Credential list shows only masked values.
- Task prompt lists registered Custom API api_id/name/description without secret values.
- `agent_lab_call_custom_api` can call only a registered API.
- Tool result never echoes the stored credential.

## Parallel Workflow Runtime Checks

Create a workflow with:

```text
parallel_branch -> api worker / prompt worker / tool worker -> merge
```

Expected:

- `agent_lab_run_parallel_workflow` returns all worker results with `ok=true` when every worker succeeds.
- API worker uses the registered API credential injection path and does not expose the secret in the result.
- Prompt/plugin/tool workers receive only the tools allowed by the selected AgentSpec and isolation policy.
- Active task detail shows the latest parallel run, worker status, and merge node.
- Task markdown records `Parallel Workflow Runs`.

## 已知边界

- 第一版默认只支持私聊。
- 桌面画布支持节点素材、节点拖拽、节点编辑、圆点拉线、右键复制/删除、彩色连线、静态检查和预跑诊断；移动端自动使用按阶段分组的节点卡片。运行态高亮和复杂分组仍属于后续增强。
- 外部框架目前是集成蓝图、规范和 adapter contract，还不是内嵌完整 runtime。
- 真实 shell/file/browser 能力取决于 AstrBot Computer Use runtime 和权限配置。
