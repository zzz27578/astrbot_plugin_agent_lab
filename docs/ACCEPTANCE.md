# Morning Acceptance Checklist

Use this checklist to verify Agent Lab inside a real AstrBot instance.

## Repository Checks

```text
python -m compileall -q .
python scripts/smoke_test.py
```

Expected:

- Python compile succeeds.
- Smoke test prints `Agent Lab smoke test passed.`

## Install Checks

1. Install this repo as an AstrBot plugin.
2. Reload plugins or restart AstrBot.
3. Confirm plugin appears as `Agent Lab`.
4. Confirm `agent-mode` Skill is active.
5. Open plugin Page `Agent Lab`.

Expected WebUI:

- Shows Agents.
- Shows Tasks.
- Shows Plugins.
- Shows Tools, including builtin catalog tools such as `astrbot_execute_shell`.
- Shows Skills.
- Shows Modules, including LangGraph/OpenAI/CrewAI/Microsoft adapters.

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
小莫，进入 Agent Mode，然后准备删除一个测试目录，先走审批。
```

Expected:

- Bot calls or suggests `agent_lab_request_approval`.
- `/agentlab status` shows pending approvals.
- `/agentlab approve <approval_id>` resolves it.

## WebUI Editing Checks

In Agent Lab Page:

1. Change Agent name.
2. Change trigger mode.
3. Toggle a plugin.
4. Toggle a tool.
5. Save AgentSpec.
6. Refresh.

Expected:

- Changes persist.
- New task uses AgentSpec snapshot.

## Known Limits In v0.1.0

- First version supports private chat only.
- WebUI is a functional test console, not yet a full workflow builder.
- External frameworks are module manifests/specs, not embedded full runtimes yet.
- Real shell/file/browser capability depends on AstrBot Computer Use runtime and permissions.

