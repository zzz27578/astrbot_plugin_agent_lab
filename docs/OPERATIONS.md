# Operations

## First Run Checklist

1. Install plugin.
2. Restart AstrBot or reload plugins.
3. Open WebUI -> Plugins -> Agent Lab page.
4. Confirm `agent-mode` skill is active.
5. In private chat:

```text
/agentlab status
/agentlab start 帮我测试 Agent Lab 是否能创建任务
/agentlab tick
/agentlab finish 初步测试完成
```

## Safe Defaults

- Private chat only.
- One active task per session.
- Heartbeat manual by default.
- Dangerous actions require soft approval.
- Task state is stored in plugin_data.
- Plugin overrides are session-level and restored on exit.
- Default AgentSpec includes common AstrBot Computer Use tool names; unavailable tools are skipped or reported by AstrBot runtime.

## Validation Notes

Agent Lab should be considered healthy when:

- `agents/` contains a default AgentSpec.
- `/agentlab start` creates `active_task.json`.
- `/agentlab tick` updates the task markdown.
- `agent_lab_read_state` can return the active task summary.
- `agent_lab_update_state` can write progress and next step.
- `/agentlab finish` moves a copy to `archives/`.
- WebUI `state` API returns agents/tasks/plugins/tools/skills/modules.

Local repository smoke test:

```text
python -m compileall -q .
python scripts/smoke_test.py
```
