# Morning Acceptance Checklist

Use this checklist to verify Agent Lab inside a real AstrBot instance.

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

Expected WebUI:

- Shows sidebar pages: Dashboard, Canvas, Tasks/Memory, Monitor, Plugins/Integrations.
- Agents can be selected, duplicated, created, and marked as default in Canvas.
- Shows active tasks and archives.
- Task/memory console has tick/heartbeat/finish/cancel actions.
- Shows AstrBot plugins separately from external integration blueprints.
- Agent Lab plugin itself is locked and cannot be disabled from its own task profile.
- Shows Tools, including builtin catalog tools such as `astrbot_execute_shell`.
- Shows Skills.
- Shows integration blueprints, including LangGraph/OpenAI/CrewAI/Microsoft adapters.

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

1. Change Agent name.
2. Change trigger mode.
3. Change memory/approval/heartbeat modes.
4. Toggle a plugin.
5. Toggle a tool.
6. Toggle a skill.
7. Toggle an integration blueprint.
8. Save AgentSpec.
9. Duplicate the AgentSpec.
10. Set the duplicate as default.
11. Refresh.

Expected:

- Changes persist.
- New task uses AgentSpec snapshot.
- WebUI task start uses the selected Agent.
- `/agentlab use <agent_id>` changes the default Agent for natural-language/command starts.
- Selected skills are shown in the Agent Mode runtime prompt for task ticks.
- Tools belonging to plugins disabled in Agent Mode are shown as unavailable and are filtered from task ticks.
- Selected integration blueprints are shown in the Agent Mode runtime prompt for task ticks.

## WebUI Review Checks

Create a task from WebUI or private chat, then use Task/Memory console:

1. Select a task.
2. Click `Tick`.
3. Toggle heartbeat.
4. Resolve a pending approval if one exists.
5. Finish or cancel the task.

Expected:

- Task/Memory console updates after each action.
- Finished/cancelled task appears in Archives.
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

## Known Limits In v0.1.0

- First version supports private chat only.
- Canvas is a structured workflow view, not a drag-and-drop runtime yet.
- External frameworks are integration blueprints/specs and adapter contracts, not embedded full runtimes yet.
- Real shell/file/browser capability depends on AstrBot Computer Use runtime and permissions.
