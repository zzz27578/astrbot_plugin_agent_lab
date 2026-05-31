# Operations

## First Run Checklist

1. Install plugin as `data/plugins/astrbot_plugin_agent_lab`.
2. Restart AstrBot or reload plugins.
3. Open the standalone WebUI, default `http://127.0.0.1:8788`.
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

## WebUI Access

Agent Lab WebUI is a standalone Quart console started by the plugin.

- `standalone_webui_host`: default `127.0.0.1`.
- `standalone_webui_port`: default `8788`.
- `standalone_webui_token`: optional API token; set it when listening outside localhost.
- The WebUI task form asks for UMO because it can simulate task operations from the console. Normal users can start from private chat commands instead.

## Safe Defaults

- Private chat only.
- One active task per session.
- Heartbeat manual by default.
- Dangerous actions require soft approval.
- Task state is stored in plugin_data.
- Plugin overrides are session-level and restored on exit.
- Agent Lab protects itself from being disabled by its own session plugin overrides.
- Default AgentSpec includes common AstrBot Computer Use tool names; unavailable tools are skipped or reported by AstrBot runtime.
- Tools from a plugin disabled in Agent Mode are filtered out together with that plugin.
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
- Standalone WebUI `state` API returns agents/tasks/plugins/tools/skills/integrations.
- Task and memory console can tick, toggle heartbeat, finish, and cancel.
- Archive list shows completed or cancelled tasks.
- Plugin and integration page separates AstrBot plugin isolation from external integration blueprints.

Local repository smoke test:

```text
python -m compileall -q .
python scripts/smoke_test.py
python scripts/runtime_smoke_test.py
```
