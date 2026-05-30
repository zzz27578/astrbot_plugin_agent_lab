# Operations

## First Run Checklist

1. Install plugin.
2. Restart AstrBot or reload plugins.
3. Open WebUI -> Plugins -> Agent Lab page.
4. Confirm `agent-mode` skill is active.
5. In private chat:

```text
/agentlab status
/agentlab agents
/agentlab use <agent_id>
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
- Agent Lab protects itself from being disabled by its own session plugin overrides.
- Default AgentSpec includes common AstrBot Computer Use tool names; unavailable tools are skipped or reported by AstrBot runtime.
- Commands and natural-language starts use the default Agent; WebUI starts use the selected Agent.

## Trigger Modes

- `manual`: commands/WebUI/explicit user request only.
- `confirm`: bot proposes Agent Mode and waits for user confirmation.
- `smart`: bot may enter for low-risk multi-step work, but asks before writes, shell commands, deployment, deletion, plugin shutdown, or secret access.
- `always`: bot prefers Agent Mode for actionable multi-step work; dangerous actions still require approval.

The same rules are synchronized into `agent-mode` Skill and the runtime prompt, so natural-language triggering follows the WebUI-selected AgentSpec instead of a hardcoded global behavior.

## Validation Notes

Agent Lab should be considered healthy when:

- `agents/` contains a default AgentSpec.
- `default_agent_id.txt` points to an existing AgentSpec.
- `/agentlab start` creates `active_task.json`.
- `/agentlab tick` updates the task markdown.
- `agent_lab_read_state` can return the active task summary.
- `agent_lab_update_state` can write progress and next step.
- `/agentlab finish` moves a copy to `archives/`.
- Completed/cancelled tasks leave the active Tasks list and remain visible under Archives.
- WebUI `state` API returns agents/tasks/plugins/tools/skills/modules.
- WebUI Task Review can tick, toggle heartbeat, resolve approvals, finish, and cancel.
- WebUI Archives shows completed or cancelled tasks.
- WebUI Modules can save custom module manifests into `plugin_data/modules`.

Local repository smoke test:

```text
python -m compileall -q .
python scripts/smoke_test.py
```
