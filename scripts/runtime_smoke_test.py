from __future__ import annotations

import asyncio
import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))


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


class FakeToolManager:
    def __init__(self) -> None:
        self.func_list = [
            SimpleNamespace(
                name="memory_noise_search",
                active=True,
                description="memory plugin tool",
                handler_module_path="memory_noise.main",
            ),
            SimpleNamespace(
                name="safe_registered_tool",
                active=True,
                description="safe registered tool",
                handler_module_path="safe_plugin.main",
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
        self._config = config or {}
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

    def is_private_chat(self) -> bool:
        return True

    def get_sender_id(self) -> str:
        return "123456"


class FakeGuard:
    def __init__(self) -> None:
        self.applied: list[tuple[str, dict[str, bool]]] = []
        self.restored: list[tuple[str, dict]] = []

    async def apply_overrides(self, umo: str, plugin_overrides: dict[str, bool]):
        self.applied.append((umo, dict(plugin_overrides)))
        return {
            umo: {
                "enabled_plugins": ["astrbot_plugin_agent_lab"],
                "disabled_plugins": [],
            }
        }

    async def restore(self, umo: str, snapshot: dict | None) -> None:
        self.restored.append((umo, snapshot or {}))


async def main() -> None:
    try:
        plugin_main = importlib.import_module(f"{ROOT.name}.main")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("astrbot"):
            print("runtime smoke skipped: AstrBot SDK/source is not importable")
            return
        raise

    with TemporaryDirectory() as tmp:
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(FakeContext(), config={"private_only": True})
        plugin.guard = FakeGuard()
        event = FakeEvent()
        assert plugin.storage.get_agent().name == "测试人格 Agent Mode"
        assert plugin._runtime_identity_payload()["bot_label_source"] == "astrbot_persona"
        spec = plugin.storage.get_agent()
        assert spec.application_scope == "entry"
        assert spec.entry_channel == "command"
        plugin.storage.save_skill_rule(
            {"skill_name": "agent-mode", "content": "运行时补充规则"}
        )
        plugin.storage.save_skill_rule(
            {"skill_name": "agent-mode-entry-summary", "content": "入口摘要测试规则"}
        )
        plugin.storage.save_skill_rule(
            {"skill_name": "agent-mode-exit-summary", "content": "出口归档测试规则"}
        )
        blank_auto_spec = plugin_main.AgentSpec(
            name="",
            identity_label_source="astrbot_runtime",
        )
        plugin._prepare_agent_spec_for_save(blank_auto_spec)
        assert blank_auto_spec.name == "测试人格 Agent Mode"
        assert blank_auto_spec.identity_label_source == "astrbot_runtime"
        custom_named_spec = plugin_main.AgentSpec(
            name="自定义任务模板",
            identity_label_source="astrbot_runtime",
        )
        plugin._prepare_agent_spec_for_save(custom_named_spec)
        assert custom_named_spec.identity_label_source == "manual"
        workflow_spec = plugin_main.AgentSpec(
            name="工作流测试",
            identity_label_source="manual",
        )
        workflow_spec.workflow_nodes = [
            {
                "id": "entry start!",
                "title": "入口",
                "kind": "unknown",
                "stage": "weird",
                "x": "12",
                "y": "34",
            },
            {
                "id": "call/api",
                "title": "调用 API",
                "kind": "api",
                "stage": "execute",
                "action": "call_api",
            },
        ]
        workflow_spec.workflow_edges = [{"from": "entry start!", "to": "call/api"}]
        plugin._prepare_agent_spec_for_save(workflow_spec)
        assert workflow_spec.workflow_nodes[0]["id"] == "entry_start"
        assert workflow_spec.workflow_nodes[0]["kind"] == "state"
        assert workflow_spec.workflow_nodes[0]["stage"] == "entry"
        assert workflow_spec.workflow_nodes[0]["x"] == 12
        assert workflow_spec.workflow_edges == [{"from": "entry_start", "to": "callapi"}]
        plugin._refresh_summarizer_rules()
        assert plugin.summarizer.config["entry_summary_system_prompt"] == "入口摘要测试规则"
        assert plugin.summarizer.config["exit_summary_system_prompt"] == "出口归档测试规则"
        assert "运行时补充规则" in plugin._build_task_extensions_prompt(spec)
        spec.enabled_tools = ["safe_registered_tool"]
        spec.tool_risk_overrides["safe_registered_tool"] = "high"
        spec.approval_policy.preapproved_scopes = ["读取项目文件"]
        risk_prompt = plugin._build_task_extensions_prompt(spec)
        assert "safe_registered_tool: risk=high" in risk_prompt
        assert "读取项目文件" in risk_prompt
        skill_file = Path(tmp) / "SKILL.md"
        skill_file.write_text("# Agent Mode\n", encoding="utf-8")
        plugin._append_agent_mode_skill_rules(skill_file)
        skill_text = skill_file.read_text(encoding="utf-8")
        assert "Agent Lab 自定义规则" in skill_text
        assert "入口摘要规则" in skill_text
        assert "出口归档规则" in skill_text
        spec.enabled_tools = ["memory_noise_search", "safe_registered_tool"]
        spec.isolation_policy.mode = "session"
        spec.plugin_overrides["memory_noise"] = False
        toolset = plugin._build_toolset(spec)
        tool_names = {tool.name for tool in toolset.tools}
        assert "memory_noise_search" not in tool_names
        assert "safe_registered_tool" in tool_names
        tool_rows = {row["name"]: row for row in plugin._tool_rows()}
        assert tool_rows["memory_noise_search"]["plugin_name"] == "memory_noise"
        strict_spec = plugin_main.AgentSpec(
            name="严格隔离测试",
            identity_label_source="manual",
        )
        strict_spec.enabled_tools = ["memory_noise_search", "safe_registered_tool"]
        strict_spec.isolation_policy.mode = "strict"
        strict_spec.plugin_overrides["safe_plugin"] = True
        strict_toolset = plugin._build_toolset(strict_spec)
        strict_tool_names = {tool.name for tool in strict_toolset.tools}
        assert "memory_noise_search" not in strict_tool_names
        assert "safe_registered_tool" in strict_tool_names
        strict_overrides = plugin._effective_session_plugin_overrides(strict_spec)
        assert strict_overrides["memory_noise"] is False
        assert strict_overrides["safe_plugin"] is True
        assert strict_overrides["astrbot_plugin_agent_lab"] is True
        save_spec = plugin_main.AgentSpec(
            name="工具测试",
            identity_label_source="manual",
        )
        save_spec.isolation_policy.mode = "session"
        save_spec.enabled_tools = [
            "memory_noise_search",
            "safe_registered_tool",
            "future_custom_tool",
            "agent_lab_tick",
        ]
        save_spec.plugin_overrides["memory_noise"] = False
        plugin._prepare_agent_spec_for_save(save_spec)
        assert save_spec.enabled_tools == ["safe_registered_tool", "future_custom_tool"]

        global_off_plugin = plugin_main.AgentLabPlugin(
            FakeContext(plugin_activation={"memory_noise": False}),
            config={"private_only": True},
        )
        global_off_spec = global_off_plugin.storage.get_agent()
        global_off_spec.isolation_policy.mode = "session"
        global_off_spec.enabled_tools = ["memory_noise_search", "safe_registered_tool"]
        global_off_spec.plugin_overrides["memory_noise"] = True
        global_off_toolset = global_off_plugin._build_toolset(global_off_spec)
        global_off_tool_names = {tool.name for tool in global_off_toolset.tools}
        assert "memory_noise_search" not in global_off_tool_names
        assert "safe_registered_tool" in global_off_tool_names
        global_off_plugin._prepare_agent_spec_for_save(global_off_spec)
        assert global_off_spec.enabled_tools == ["safe_registered_tool"]

        start = await plugin._start_task(
            event,
            goal="runtime smoke goal",
            completion_conditions="archive exists",
            brief="runtime smoke entry brief",
            request_heartbeat=False,
            source="runtime_smoke",
            risk_level="work",
        )
        assert "已进入 Agent Mode" in start
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.root_goal == "runtime smoke goal"
        assert task.profile_snapshot["agent"]["name"] == "测试人格 Agent Mode"
        assert task.profile_snapshot["agent"]["workflow_nodes"][0]["stage"] == "entry"
        assert "工作流：" in task.current_summary
        task_prompt = plugin_main.build_task_system_prompt(
            plugin_main.AgentSpec.from_dict(task.profile_snapshot["agent"]),
            task,
        )
        assert "[Workflow]" in task_prompt
        assert "run_tools" in task_prompt
        assert plugin._task_payload(task)["heartbeat_health"]["state"] == "off"

        approval = await plugin.agent_lab_request_approval(
            event,
            operation="delete test directory",
            reason="verify approval protocol",
            impact="test only",
            rollback="none",
        )
        assert "已创建审批请求" in approval
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        approval_id = task.pending_approvals()[0].approval_id
        resolved = plugin._resolve_approval(
            event.unified_msg_origin,
            approval_id,
            approved=True,
            user_id=event.get_sender_id(),
        )
        assert "审批已通过" in resolved

        api_credential = plugin.storage.save_credential(
            {"label": "Runtime API Key", "provider": "test", "value": "runtime-secret"}
        )
        api_spec = plugin.storage.save_custom_api(
            {
                "name": "Runtime API",
                "method": "post",
                "url": "https://example.com/runtime",
                "credential_id": api_credential["credential_id"],
                "auth_type": "header",
                "auth_header": "X-Test-Key",
            }
        )
        api_call = {}

        def fake_custom_api_call(method, url, query, body, headers, timeout_seconds):
            api_call.update(
                {
                    "method": method,
                    "url": url,
                    "query": query,
                    "body": body,
                    "headers": headers,
                    "timeout_seconds": timeout_seconds,
                }
            )
            return {"ok": True, "status": 200, "body": "pong"}

        plugin._perform_custom_api_http_call = fake_custom_api_call
        api_result = await plugin.agent_lab_call_custom_api(
            event,
            api_id=api_spec["api_id"],
            query_json='{"q":"smoke"}',
            body_json='{"hello":"world"}',
        )
        assert '"pong"' in api_result
        assert "runtime-secret" not in api_result
        assert api_call["headers"]["X-Test-Key"] == "runtime-secret"
        assert api_call["query"]["q"] == "smoke"
        assert api_call["body"]["hello"] == "world"
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert any(item.get("kind") == "custom_api" for item in task.progress_log)

        heartbeat = await plugin._enable_heartbeat(event, task, "runtime_smoke")
        assert "已开启心跳" in heartbeat
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.heartbeat.enabled
        assert task.heartbeat.job_id
        assert plugin._heartbeat_health(task)["state"] == "idle"

        finish = await plugin._finish_task(
            event,
            status="completed",
            final_summary="runtime smoke done",
            memory_candidates="- Agent Lab runtime smoke passed",
        )
        assert "Agent Mode 已结束并归档" in finish
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"
        assert plugin.guard.restored

    with TemporaryDirectory() as tmp:
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        context = FakeContext()
        plugin = plugin_main.AgentLabPlugin(context, config={"private_only": True})
        plugin.guard = FakeGuard()
        event = FakeEvent()
        await plugin._start_task(
            event,
            goal="finish inside tick",
            completion_conditions="archive exists",
            brief="finish inside tick brief",
            request_heartbeat=False,
            source="runtime_smoke",
            risk_level="work",
        )

        async def finish_inside_tick(**kwargs):
            await plugin.agent_lab_finish(
                event,
                final_summary="finished from tool call",
                memory_candidates="- finish did not resurrect active task",
            )
            return SimpleNamespace(completion_text="tool finished task", usage=None)

        context.tool_loop_agent_handler = finish_inside_tick
        result = await plugin._tick(event, "runtime_smoke_finish")
        assert "任务已在本轮结束或切换" in result
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"

    with TemporaryDirectory() as tmp:
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(
            FakeContext(config={"bot_name": "配置机器人"}, persona_name=None),
            config={"private_only": True},
        )
        assert plugin.storage.get_agent().name == "配置机器人 Agent Mode"
        runtime_identity = plugin._runtime_identity_payload()
        assert runtime_identity["bot_label"] == "配置机器人"
        assert runtime_identity["bot_label_source"] == "astrbot_config"

    print("Agent Lab runtime smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
    # AstrBot SDK imports can leave non-daemon scheduler/sqlite helper threads alive
    # in this isolated smoke environment. All assertions have completed here.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
