# Changelog

## v0.1.0

- Initial Agent Lab plugin.
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
- Limited WebUI Tasks/state task listing to active tasks; finished and cancelled tasks live under Archives.
- Protected Agent Lab from being disabled by its own session plugin overrides.
