from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


def debug(message: str) -> None:
    if os.environ.get("AGENT_LAB_SMOKE_DEBUG"):
        print(f"[runtime_smoke] {message}", flush=True)


class FakeCronManager:
    def __init__(self) -> None:
        self.jobs: dict[str, SimpleNamespace] = {}
        self.deleted: list[str] = []

    async def add_basic_job(self, **kwargs):
        job_id = f"job_{len(self.jobs) + 1}"
        job = SimpleNamespace(job_id=job_id, **kwargs)
        self.jobs[job_id] = job
        return job

    async def delete_job(self, job_id: str) -> None:
        self.deleted.append(job_id)
        self.jobs.pop(job_id, None)

    async def list_jobs(self, job_type: str):
        return list(self.jobs.values())


class FakeConversationManager:
    async def get_curr_conversation_id(self, umo: str):
        return None


class FakeCallableTool:
    def __init__(
        self,
        *,
        name: str,
        description: str,
        handler_module_path: str,
        calls: list[dict],
    ) -> None:
        self.name = name
        self.active = True
        self.description = description
        self.handler_module_path = handler_module_path
        self.calls = calls
        self.parameters = {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        }

    async def call(self, context, **kwargs):
        self.calls.append({"tool": self.name, "args": dict(kwargs)})
        return {"ok": True, "tool": self.name, "args": kwargs}


class FakeToolManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.func_list = [
            SimpleNamespace(
                name="memory_noise_search",
                active=True,
                description="memory plugin tool",
                handler_module_path="memory_noise.main",
            ),
            FakeCallableTool(
                name="safe_registered_tool",
                description="safe registered tool",
                handler_module_path="safe_plugin.main",
                calls=self.calls,
            ),
        ]

    def get_func(self, name: str):
        return next((item for item in self.func_list if item.name == name), None)

    def get_full_tool_set(self):
        from astrbot.core.agent.tool import ToolSet

        toolset = ToolSet()
        for tool in self.func_list:
            toolset.add_tool(tool)
        return toolset


class FakeContext:
    def __init__(
        self,
        *,
        config: dict | None = None,
        persona_name: str | None = "测试人格",
        plugin_activation: dict[str, bool] | None = None,
    ) -> None:
        self._config = {"admins_id": ["123456"], **(config or {})}
        self.plugin_activation = plugin_activation or {}
        self.web_apis = []
        self.cron_manager = FakeCronManager()
        self.conversation_manager = FakeConversationManager()
        self.tool_manager = FakeToolManager()
        self.tool_loop_agent_handler = None
        self.persona_manager = SimpleNamespace(
            selected_default_persona_v3={"name": persona_name} if persona_name else None
        )

    def register_web_api(self, route, handler, methods, desc) -> None:
        self.web_apis.append((route, methods, desc))

    def get_config(self, *args, **kwargs):
        return self._config

    def get_all_stars(self):
        return [
            SimpleNamespace(
                name="astrbot_plugin_agent_lab",
                display_name="Agent Lab",
                activated=True,
                reserved=False,
                desc="self",
            ),
            SimpleNamespace(
                name="memory_noise",
                display_name="Memory Noise",
                activated=self.plugin_activation.get("memory_noise", True),
                reserved=False,
                desc="test memory plugin",
                module_path="memory_noise.main",
                root_dir_name="memory_noise",
            ),
            SimpleNamespace(
                name="safe_plugin",
                display_name="Safe Plugin",
                activated=self.plugin_activation.get("safe_plugin", True),
                reserved=False,
                desc="safe plugin",
                module_path="safe_plugin.main",
                root_dir_name="safe_plugin",
            ),
        ]

    def get_llm_tool_manager(self):
        return self.tool_manager

    async def get_current_chat_provider_id(self, umo: str):
        return "fake-provider"

    async def llm_generate(self, **kwargs):
        raise RuntimeError("no provider in runtime smoke")

    async def tool_loop_agent(self, **kwargs):
        if self.tool_loop_agent_handler:
            return await self.tool_loop_agent_handler(**kwargs)
        raise RuntimeError("no provider in runtime smoke")


@dataclass
class FakeEvent:
    unified_msg_origin: str = "aiocqhttp:FriendMessage:123456"
    message_str: str = ""
    role: str = "admin"
    _extras: dict = field(default_factory=dict)

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def is_private_chat(self) -> bool:
        return True

    def get_sender_id(self) -> str:
        return "123456"


async def main():
    """Bounded adapter/mixin smoke; scenario and loop tests live in scripts/ui.

    No production DB, tools, model calls, or outgoing messages are used.
    """
    plugin_main = importlib.import_module(f"{ROOT.name}.main")
    tools_module = importlib.import_module(f"{ROOT.name}.agent_lab.task_tools")
    with TemporaryDirectory() as temp:
        original = plugin_main.StarTools.get_data_dir
        plugin_main.StarTools.get_data_dir = staticmethod(lambda name=None: Path(temp) / 'data')
        try:
            context = FakeContext()
            plugin = plugin_main.AgentLabPlugin(context, config={'private_only': True})
            event = FakeEvent()
            assert plugin.service.check_health().ok
            assert len(plugin.node_executors.kinds()) if hasattr(plugin.node_executors, 'kinds') else plugin.node_executors
            # The real registration wrappers and compact schemas must agree.
            for schema in tools_module.TASK_TOOL_SCHEMAS:
                entry = schema['function']
                assert callable(getattr(plugin, entry['name']))
                tool = FakeCallableTool(name=entry['name'], description=entry['description'],
                                        handler_module_path='astrbot_plugin_agent_lab.main', calls=[])
                tool.parameters = entry['parameters']
                context.tool_manager.func_list.append(tool)
            spec = plugin.storage.get_agent()
            report = plugin._workflow_report(spec)
            assert isinstance(report, dict)
            assert plugin._workflow_entry_id(spec)
            task = plugin_main.TaskState(umo=event.unified_msg_origin, root_goal='Inspect project',
                                         profile_snapshot={'agent': spec.to_dict()})
            plugin.task_control.initialize(task, event, 'none')
            plugin.storage.save_task(task)
            # Avoid transport; preserve the actual plan approval state.
            async def local_state(*args, **kwargs): return 'recorded locally'
            plugin.task_messages.state = local_state
            await plugin.task_plan(event, steps_json=json.dumps([
                {'id': 'inspect', 'title': 'Inspect', 'instruction': 'Inspect project'}]), message='May I inspect this project?')
            current = plugin.storage.load_active_task(task.umo)
            state = plugin_main.task_control(current)
            assert len(current.pending_approvals()) == 1
            row = current.approvals[-1]
            row['status'] = 'approved'
            plugin.task_control.approval(current, row, True)
            current.status = 'running'
            plugin.storage.save_task(current)
            ordinary = plugin._build_toolset(spec, event)
            controls = {tool.name for tool in ordinary.tools if tool.name.startswith(('task_', 'agent_lab_'))}
            assert controls == set(tools_module.CONTROL_TOOL_NAMES), controls
            system, prompt = plugin.runtime_runner._task_prompts(current, spec, 'smoke')
            assert 'task_finish' in system
            assert not any(word in system + prompt for word in ['agent_lab_read_runtime', '[Workflow]', 'read_tool_evidence'])
            assert current.root_goal in prompt
            assert plugin._budget_remaining_tools(current) > 24
            # Routine checklist changes neither send a second approval nor stop.
            await plugin.task_plan(event, steps_json=json.dumps([
                {'id': 'inspect', 'title': 'Inspect source', 'instruction': 'Inspect source'},
                {'id': 'review', 'title': 'Review findings', 'instruction': 'Review findings'}]))
            current = plugin.storage.load_active_task(task.umo)
            assert current.status == 'running' and not current.pending_approvals()
            assert plugin_main.task_control(current)['approved_version'] == plugin_main.task_control(current)['version']
            current.budget.max_total_tool_calls = 2
            current.budget.tool_calls_used = 2
            assert plugin._total_budget_reason(current)
            current.budget.max_total_tool_calls = 0
            plugin_main.task_control(current)['workflow'] = 'selected'
            plugin.storage.save_task(current)
            canvas = plugin._build_toolset(spec, event)
            assert isinstance(canvas.tools, list)
            # Exercise an inherited canvas entry executor against real ledger.
            assert callable(plugin._execute_entry_node) and callable(plugin._run_workflow_runtime)
            assert callable(plugin._normalize_agent_workflow) and callable(plugin._workflow_dry_run_report)
            text = json.dumps(report, ensure_ascii=False)
            assert text
            skill = (ROOT / 'skills/agent-mode/SKILL.md').read_text(encoding='utf-8')
            assert len(skill.splitlines()) <= 50
            await plugin.task_control.stop()
        finally:
            plugin_main.StarTools.get_data_dir = original
    print('Agent Lab v0.4 adapter/canvas smoke passed (offline, no live model).')


if __name__ == '__main__':
    asyncio.run(main())
