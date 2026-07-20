from __future__ import annotations

import asyncio
import importlib
import json
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
        debug("import plugin main")
        plugin_main = importlib.import_module(f"{ROOT.name}.main")
        debug("plugin main imported")
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("astrbot"):
            print("runtime smoke skipped: AstrBot SDK/source is not importable")
            return
        raise

    with TemporaryDirectory() as tmp:
        debug("first runtime fixture")
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(FakeContext(), config={"private_only": True})
        plugin.guard = FakeGuard()
        event = FakeEvent()
        assert any(route.endswith("/workflow/check") for route, _, _ in plugin.context.web_apis)
        assert plugin.storage.get_agent().name == "测试人格任务模式"
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
        assert blank_auto_spec.name == "测试人格任务模式"
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
        workflow_spec.workflow_edges = [
            {
                "from": "entry start!",
                "to": "call/api",
                "route_hint": {"points": [[12.345, 34.56], {"x": 90, "y": 120}]},
            }
        ]
        plugin._prepare_agent_spec_for_save(workflow_spec)
        assert workflow_spec.workflow_nodes[0]["id"] == "entry_start"
        assert workflow_spec.workflow_nodes[0]["kind"] == "state"
        assert workflow_spec.workflow_nodes[0]["stage"] == "entry"
        assert workflow_spec.workflow_nodes[0]["x"] == 12
        assert workflow_spec.workflow_edges == [
            {
                "from": "entry_start",
                "to": "callapi",
                "edge_type": "success",
                "route_hint": {
                    "version": 1,
                    "mode": "orthogonal_hint",
                    "points": [[12.3, 34.6], [90.0, 120.0]],
                },
            }
        ]
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
        assert tool_rows["safe_registered_tool"]["parameters_schema"]["required"] == ["value"]
        assert tool_rows["safe_registered_tool"]["input_schema"]["properties"]["value"]["type"] == "string"
        assert tool_rows["safe_registered_tool"]["output_schema"]["type"] == "object"
        assert "work" in tool_rows["safe_registered_tool"]["permission_profiles"]
        plugin_rows = {row["name"]: row for row in plugin._plugin_rows()}
        assert "memory" in plugin_rows["memory_noise"]["capabilities"]
        assert plugin_rows["memory_noise"]["tool_count"] == 1
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
        assert save_spec.enabled_tools == ["memory_noise_search", "safe_registered_tool", "future_custom_tool"]

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
        assert global_off_spec.enabled_tools == ["memory_noise_search", "safe_registered_tool"]

        start = await plugin._start_task(
            event,
            goal="runtime smoke goal",
            completion_conditions="archive exists",
            brief="runtime smoke entry brief",
            request_heartbeat=False,
            source="runtime_smoke",
            risk_level="work",
        )
        debug("task started")
        assert "已进入任务模式" in start
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.root_goal == "runtime smoke goal"
        assert task.profile_snapshot["agent"]["name"] == "测试人格任务模式"
        assert task.profile_snapshot["agent"]["workflow_nodes"][0]["stage"] == "entry"
        assert "工作流：" in task.current_summary
        assert task.workflow_current_node_id == "entry"
        assert task.workflow_path == ["entry"]
        assert task.workflow_events and task.workflow_events[0]["status"] == "entered"
        agent_runtime = task.workflow_data["agent_runtime"]
        assert agent_runtime["agent_instance"]["task_id"] == task.task_id
        assert agent_runtime["agent_instance"]["lifecycle"]["plan"] is True
        assert agent_runtime["plan"]["goal"] == "runtime smoke goal"
        assert agent_runtime["plan"]["steps"][0]["node_id"] == "entry"
        assert any(item["name"] == "agent_lab_read_runtime" for item in agent_runtime["capabilities"])
        assert agent_runtime["resume"]["resume_command"] == "/agentlab tick"
        lease_ok, lease_token = plugin._acquire_task_lease(
            task,
            reason="runtime_smoke_lease",
            ttl_seconds=60,
        )
        assert lease_ok
        lease_again, lease_message = plugin._acquire_task_lease(
            task,
            reason="runtime_smoke_lease",
            ttl_seconds=60,
        )
        assert not lease_again
        assert "lease" in lease_message.lower()
        plugin._release_task_lease(task, lease_token)
        plugin.storage.save_task(task)

        budget_task = plugin_main.TaskState(
            umo=event.unified_msg_origin,
            root_goal="budget smoke",
        )
        budget_task.budget.max_nodes_per_tick = 1
        assert plugin._budget_before_tick(budget_task, "runtime_smoke_budget") == ""
        assert plugin._consume_node_budget(budget_task, {"id": "budget_a"}) == ""
        budget_pause = plugin._consume_node_budget(budget_task, {"id": "budget_b"})
        assert budget_pause
        plugin._pause_task_for_budget(budget_task, budget_pause)
        assert budget_task.status == "paused"
        assert budget_task.watchdog.needs_user

        condition_task = plugin_main.TaskState(umo=event.unified_msg_origin)
        condition_task.workflow_data = {"variables": {"api_result": {"ok": True}}}
        route_target = plugin._route_target_from_node(
            condition_task,
            {"id": "route", "action": "route_condition"},
            ["route_ok", "route_else"],
            [
                {"id": "route_ok", "condition": "api_result.ok == true"},
                {"id": "route_else", "condition": "else"},
            ],
        )
        assert route_target == "route_ok"
        condition_task.workflow_data = {
            "variables": {
                "api_result": {
                    "ok": True,
                    "body": "runtime smoke completed successfully",
                    "items": ["alpha", "beta"],
                },
                "tool_result": {"result": "safe_registered_tool returned ok"},
            }
        }
        complex_route_target = plugin._route_target_from_node(
            condition_task,
            {"id": "complex_route", "action": "route_condition"},
            ["route_complex", "route_fallback"],
            [
                {
                    "id": "route_complex",
                    "condition": "exists(api_result.body) and contains(api_result.body, 'completed') and not missing(tool_result.result)",
                },
                {"id": "route_fallback", "condition": "else"},
            ],
        )
        assert complex_route_target == "route_complex"
        or_route_target = plugin._route_target_from_node(
            condition_task,
            {"id": "or_route", "action": "route_condition"},
            ["route_or", "route_fallback"],
            [
                {"id": "route_or", "condition": "api_result.items contains 'beta' or api_result.ok == false"},
                {"id": "route_fallback", "condition": "else"},
            ],
        )
        assert or_route_target == "route_or"
        task_prompt = plugin_main.build_task_system_prompt(
            plugin_main.AgentSpec.from_dict(task.profile_snapshot["agent"]),
            task,
        )
        assert "[Workflow]" in task_prompt
        assert "[Workflow Runtime Cursor]" in task_prompt
        assert "[Structured Agent Runtime]" in task_prompt
        assert "agent_lab_read_runtime" in task_prompt
        assert "agent_lab_advance_workflow" in task_prompt
        assert "run_tools" in task_prompt
        read_state = await plugin.agent_lab_read_state(event)
        assert "workflow: current=entry" in read_state
        assert "runtime: current=entry" in read_state
        runtime_text = await plugin.agent_lab_read_runtime(event)
        assert "Agent Runtime:" in runtime_text
        assert "agent_lab_read_runtime" in runtime_text
        runtime_json = json.loads(await plugin.agent_lab_read_runtime(event, format="json"))
        assert runtime_json["agent_instance"]["task_id"] == task.task_id
        assert runtime_json["capability_count"] >= 1
        advanced = await plugin.agent_lab_advance_workflow(
            event,
            node_id="entry",
            outcome="入口摘要已完成。",
            next_node_id="global_control",
            note="runtime smoke",
        )
        assert "entry -> global_control" in advanced
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.workflow_current_node_id == "global_control"
        assert task.workflow_path[-1] == "global_control"
        assert "## Workflow Cursor" in plugin.storage.render_markdown(task)
        assert "## Agent Runtime" in plugin.storage.render_markdown(task)
        task_payload = plugin._task_payload(task)
        assert task_payload["heartbeat_health"]["state"] == "off"
        assert task_payload["agent_runtime_summary"]["capability_count"] >= 1

        runtime_react_calls = []

        async def fake_runtime_react(**kwargs):
            hooks = kwargs.get("agent_hooks")
            if hooks:
                fake_tool = SimpleNamespace(name="safe_registered_tool")
                await hooks.on_tool_start(None, fake_tool, {"value": "react_tool"})
                await hooks.on_tool_end(None, fake_tool, {"value": "react_tool"}, {"ok": True})
            runtime_react_calls.append(
                {
                    "prompt": str(kwargs.get("prompt") or ""),
                    "system_prompt": str(kwargs.get("system_prompt") or ""),
                }
            )
            return SimpleNamespace(
                completion_text="runtime react reached plan node",
                usage=SimpleNamespace(input_other=2, input_cached=0, output=3, total=5),
            )

        plugin.context.tool_loop_agent_handler = fake_runtime_react
        tick_result = await plugin._tick(event, "runtime_smoke_workflow_runtime")
        assert "runtime react reached plan node" in tick_result
        assert runtime_react_calls
        assert "node_id: plan" in runtime_react_calls[0]["prompt"]
        assert "Run one bounded ReAct step" in runtime_react_calls[0]["prompt"]
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.workflow_current_node_id == "plan"
        assert task.workflow_path[-1] == "plan"
        assert "global_control" in task.workflow_path
        assert "memory_recall" in task.workflow_path
        assert any(item.get("kind") == "workflow_runtime" for item in task.progress_log)
        assert task.workflow_data["react_traces"]
        assert task.workflow_data["react_traces"][-1]["node_id"] == "plan"
        assert "runtime react reached plan node" in task.workflow_data["react_traces"][-1]["response"]
        assert '"source": "tool_loop"' in task.last_observation
        assert task.workflow_data["observations"][-1]["source"] == "tool_loop"
        assert task.workflow_data["resume"]["last_observation"] == task.last_observation
        assert task.workflow_data["resume"]["workflow_current_node_id"] == "plan"
        assert task.workflow_data["agent_runtime"]["last_verdict"]
        assert any(
            item.get("source") == "tool_loop"
            for item in task.workflow_data["agent_runtime"]["observations"]
        )
        assert task.token_usage["total"] == 5
        report_with_runtime = plugin._workflow_report(plugin_main.AgentSpec.from_dict(task.profile_snapshot["agent"]))
        assert "api_call" in report_with_runtime["executor_nodes"]
        assert report_with_runtime["node_runtime"]["plan"]["react_handoff"] is True
        plugin.storage.save_memory_entry(
            {
                "text": "private active runtime memory",
                "source_task_id": task.task_id,
                "source_umo": task.umo,
                "status": "candidate",
                "kind": "workflow_private_memory",
                "tags": ["runtime", "private"],
                "expose_to_normal": False,
            }
        )
        active_private_memory = await plugin.agent_lab_read_task_memory(
            event,
            query="private active runtime memory",
        )
        assert "private active runtime memory" in active_private_memory
        plugin.context.tool_loop_agent_handler = None

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

        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.status == "running"
        assert not task.wait.active
        assert not task.watchdog.needs_user

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
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        runtime_spec = plugin_main.AgentSpec.from_dict(
            task.profile_snapshot.get("agent") or plugin.storage.get_agent().to_dict()
        )
        runtime_spec.enabled_tools = list(
            dict.fromkeys([*runtime_spec.enabled_tools, "agent_lab_call_custom_api"])
        )
        task.profile_snapshot["agent"] = runtime_spec.to_dict()
        plugin._sync_agent_runtime(task, runtime_spec, reason="runtime_smoke_custom_api_capability")
        api_capability_rows = task.workflow_data.get("agent_runtime", {}).get("capabilities", [])
        api_capability = next(
            item
            for item in api_capability_rows
            if item.get("name") == f"api:{api_spec['api_id']}"
        )
        assert api_capability["capability"] == "api.call"
        assert api_capability["metadata"]["url_host"] == "https://example.com"
        assert api_capability["metadata"]["credential_configured"] is True
        assert "runtime-secret" not in json.dumps(api_capability, ensure_ascii=False)
        plugin.storage.save_task(task)
        workflow_update = await plugin.agent_lab_update_workflow(
            event,
            operation="add_node",
            title="Runtime API 节点",
            kind="api",
            stage="execute",
            action="call_api",
            instruction="调用 runtime smoke API。",
            ref_type="api",
            ref_id=api_spec["api_id"],
        )
        assert '"changed": true' in workflow_update
        prompt_update = await plugin.agent_lab_update_workflow(
            event,
            operation="add_node",
            title="Runtime Prompt Worker",
            kind="subflow",
            stage="execute",
            action="manual",
            instruction="并行提示词工作包。",
            prompt="只处理 runtime smoke 分配的子任务，输出结构化结论。",
            parallel_group="runtime_smoke",
        )
        assert '"changed": true' in prompt_update
        workflow_report = plugin._workflow_report(plugin.storage.get_agent())
        assert workflow_report["errors"] == 0
        assert any(
            node.get("api_id") == api_spec["api_id"]
            for node in plugin.storage.get_agent().workflow_nodes
        )
        assert any(
            node.get("parallel_group") == "runtime_smoke" and node.get("prompt")
            for node in plugin.storage.get_agent().workflow_nodes
        )
        invalid_api_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {"id": "entry", "stage": "entry", "action": "summarize_entry", "instruction": "entry"},
                {"id": "api", "stage": "execute", "kind": "api", "action": "call_api", "api_id": "missing-api", "instruction": "call missing api"},
                {"id": "archive", "stage": "archive", "action": "exit_summary", "instruction": "archive"},
            ],
            workflow_edges=[{"from": "entry", "to": "api"}, {"from": "api", "to": "archive"}],
        )
        invalid_report = plugin._workflow_report(invalid_api_spec)
        assert any(issue["code"] == "missing_api" for issue in invalid_report["issues"])
        api_calls = []

        def fake_custom_api_call(method, url, query, body, headers, timeout_seconds):
            api_calls.append(
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
        debug("custom api tool checked")
        assert '"pong"' in api_result
        assert "runtime-secret" not in api_result
        assert api_calls[-1]["headers"]["X-Test-Key"] == "runtime-secret"
        assert api_calls[-1]["query"]["q"] == "smoke"
        assert api_calls[-1]["body"]["hello"] == "world"
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert any(item.get("kind") == "custom_api" for item in task.progress_log)
        plugin.workflow_runtime.max_auto_steps = 18
        executor_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "api_exec",
                    "stage": "execute",
                    "kind": "api",
                    "action": "call_api",
                    "api_id": api_spec["api_id"],
                    "output_variable": "api_result",
                    "api_payload": {"query": {"executor": "yes"}},
                    "instruction": "direct API executor",
                },
                {
                    "id": "set_payload",
                    "stage": "execute",
                    "kind": "state",
                    "action": "variable_set",
                    "variable_name": "payload.answer",
                    "value": {"number": 42, "text": "ok", "items": ["alpha", "beta"]},
                    "instruction": "set nested workflow variable",
                },
                {
                    "id": "get_payload_number",
                    "stage": "execute",
                    "kind": "state",
                    "action": "variable_get",
                    "variable_name": "variables.payload.answer.number",
                    "output_variable": "payload_number",
                    "instruction": "read nested workflow variable",
                },
                {
                    "id": "template_exec",
                    "stage": "execute",
                    "kind": "state",
                    "action": "text_template",
                    "template": "number={{variables.payload.answer.number}} text={{variables.payload.answer.text}} api={{variables.api_result.api_id}} goal=${task.root_goal}",
                    "output_variable": "rendered_text",
                    "output_schema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                    "instruction": "render deterministic template",
                },
                {
                    "id": "json_transform_exec",
                    "stage": "execute",
                    "kind": "state",
                    "action": "json_transform",
                    "input_variable": "variables.payload.answer",
                    "expression": ".number",
                    "output_variable": "json_value",
                    "instruction": "extract number from JSON payload",
                },
                {
                    "id": "merge_exec",
                    "stage": "execute",
                    "kind": "state",
                    "action": "merge",
                    "inputs": [
                        "variables.payload.answer",
                        "variables.rendered_text.text",
                        "variables.json_value.value",
                    ],
                    "output_variable": "merged_result",
                    "instruction": "merge deterministic outputs",
                },
                {
                    "id": "iterator_exec",
                    "stage": "execute",
                    "kind": "state",
                    "action": "iterator",
                    "input_variable": "variables.payload.answer.items",
                    "output_variable": "iterator_result",
                    "instruction": "prepare loop items",
                },
                {
                    "id": "http_exec",
                    "stage": "execute",
                    "kind": "api",
                    "action": "http_request",
                    "method": "POST",
                    "url": "https://example.com/runtime-http",
                    "payload": {
                        "query": {"number": "{{variables.json_value.value}}"},
                        "headers": {"X-Smoke": "runtime"},
                        "body": {"text": "{{variables.payload.answer.text}}"},
                    },
                    "output_variable": "http_result",
                    "instruction": "direct HTTP executor",
                },
                {
                    "id": "tool_exec",
                    "stage": "execute",
                    "kind": "tool",
                    "action": "run_tools",
                    "tool_name": "safe_registered_tool",
                    "tool_args": {"value": "from {{variables.api_result.api_id}} / ${task.root_goal}"},
                    "output_variable": "tool_result",
                    "instruction": "direct tool executor with templated args",
                },
                {
                    "id": "api_template_exec",
                    "stage": "execute",
                    "kind": "api",
                    "action": "call_api",
                    "api_id": api_spec["api_id"],
                    "output_variable": "api_template_result",
                    "api_payload": {
                        "query": {
                            "from_tool": "{{variables.tool_result.args.value}}",
                            "goal": "${task.root_goal}",
                            "node": "{{node_outputs.tool_exec.node_id}}",
                        },
                        "body": {"source_api": "{{variables.api_result.api_id}}"},
                    },
                    "instruction": "templated API executor",
                },
                {
                    "id": "memory_exec",
                    "stage": "checkpoint",
                    "kind": "memory",
                    "action": "save_memory",
                    "instruction": "save private memory",
                },
                {
                    "id": "validate_exec",
                    "stage": "checkpoint",
                    "kind": "validation",
                    "action": "validate_output",
                    "instruction": "validate result",
                },
                {
                    "id": "validation_signal_exec",
                    "stage": "checkpoint",
                    "kind": "state",
                    "action": "variable_set",
                    "variable_name": "validation_signal",
                    "value": "ok success completed",
                    "instruction": "write explicit verifier evidence",
                },
                {
                    "id": "debate_validate_exec",
                    "stage": "checkpoint",
                    "kind": "validation",
                    "action": "debate_validation",
                    "perspectives": ["correctness", "completion"],
                    "instruction": "deterministic multi-perspective validation",
                },
                {
                    "id": "checkpoint_exec",
                    "stage": "checkpoint",
                    "kind": "state",
                    "action": "save_state",
                    "instruction": "checkpoint",
                },
            ],
            workflow_edges=[
                {"from": "api_exec", "to": "set_payload"},
                {"from": "set_payload", "to": "get_payload_number"},
                {"from": "get_payload_number", "to": "template_exec"},
                {"from": "template_exec", "to": "json_transform_exec"},
                {"from": "json_transform_exec", "to": "merge_exec"},
                {"from": "merge_exec", "to": "iterator_exec"},
                {"from": "iterator_exec", "to": "http_exec"},
                {"from": "http_exec", "to": "tool_exec"},
                {"from": "tool_exec", "to": "api_template_exec"},
                {"from": "api_template_exec", "to": "memory_exec"},
                {"from": "memory_exec", "to": "validate_exec"},
                {"from": "validate_exec", "to": "validation_signal_exec"},
                {"from": "validation_signal_exec", "to": "debate_validate_exec"},
                {"from": "debate_validate_exec", "to": "checkpoint_exec"},
            ],
        )
        executor_spec.enabled_tools = ["safe_registered_tool", "agent_lab_call_custom_api"]
        executor_spec.plugin_overrides["safe_plugin"] = True
        plugin._normalize_agent_workflow(executor_spec)
        task.profile_snapshot["agent"] = executor_spec.to_dict()
        task.workflow_current_node_id = "api_exec"
        task.workflow_path = ["api_exec"]
        task.budget.max_nodes_per_tick = 18
        task.workflow_data = {}
        plugin.storage.save_task(task)
        runtime_exec = await plugin._run_workflow_runtime(
            event=event,
            task=task,
            spec=executor_spec,
            reason="runtime_smoke_node_executors",
        )
        debug("node executors checked")
        assert runtime_exec.changed
        assert "api_exec" in task.workflow_data["node_outputs"]
        assert task.workflow_data["node_outputs"]["api_exec"]["data"]["ok"] is True
        assert task.workflow_data["variables"]["api_result"]["api_id"] == api_spec["api_id"]
        assert task.workflow_data["variables"]["payload"]["answer"]["number"] == 42
        assert task.workflow_data["variables"]["payload.answer"]["text"] == "ok"
        assert task.workflow_data["variables"]["payload_number"]["value"] == 42
        assert "number=42 text=ok" in task.workflow_data["variables"]["rendered_text"]["text"]
        assert task.workflow_data["variables"]["json_value"]["value"] == 42
        assert task.workflow_data["variables"]["merged_result"]["merged"]["variables.json_value.value"] == 42
        assert task.workflow_data["variables"]["iterator_result"]["count"] == 2
        assert task.workflow_data["node_outputs"]["http_exec"]["data"]["ok"] is True
        assert task.workflow_data["variables"]["http_result"]["url_host"] == "https://example.com"
        assert task.workflow_data["node_outputs"]["tool_exec"]["data"]["tool_name"] == "safe_registered_tool"
        assert task.workflow_data["variables"]["tool_result"]["result"]
        expected_template_value = f"from {api_spec['api_id']} / runtime smoke goal"
        assert plugin.context.tool_manager.calls[-1]["args"]["value"] == expected_template_value
        assert task.workflow_data["node_outputs"]["api_template_exec"]["data"]["ok"] is True
        assert task.workflow_data["variables"]["api_template_result"]["api_id"] == api_spec["api_id"]
        assert task.workflow_data["variables"]["validation_signal"] == "ok success completed"
        templated_api_call = next(item for item in api_calls if item["query"].get("from_tool") == expected_template_value)
        assert templated_api_call["query"]["goal"] == "runtime smoke goal"
        assert templated_api_call["query"]["node"] == "tool_exec"
        assert templated_api_call["body"]["source_api"] == api_spec["api_id"]
        http_call = next(item for item in api_calls if item["url"] == "https://example.com/runtime-http")
        assert http_call["query"]["number"] == 42
        assert http_call["headers"]["X-Smoke"] == "runtime"
        assert http_call["body"]["text"] == "ok"
        assert task.workflow_data["node_outputs"]["memory_exec"]["data"]["kind"] == "workflow_private_memory"
        assert task.workflow_data["node_outputs"]["debate_validate_exec"]["data"]["passed"] is True
        assert any(item.get("kind") == "task_memory" for item in task.progress_log)
        rendered = plugin.storage.render_markdown(task)
        assert "Workflow Node Outputs" in rendered
        assert "Agent Runtime" in rendered
        assert "api_exec" in rendered

        error_edge_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "bad_file",
                    "stage": "execute",
                    "kind": "tool",
                    "action": "file_operation",
                    "operation": "read",
                    "path": "missing-runtime-smoke.txt",
                    "instruction": "trigger file error output",
                },
                {
                    "id": "error_handler",
                    "stage": "checkpoint",
                    "kind": "state",
                    "action": "variable_set",
                    "variable_name": "error.handled",
                    "value": "yes",
                    "instruction": "record handled file error",
                },
            ],
            workflow_edges=[
                {"from": "bad_file", "to": "error_handler", "edge_type": "error"},
            ],
        )
        error_edge_spec.enabled_tools = ["astrbot_file_read_tool"]
        plugin._normalize_agent_workflow(error_edge_spec)
        task.status = "running"
        task.blockers = []
        task.clear_wait()
        task.profile_snapshot["agent"] = error_edge_spec.to_dict()
        task.workflow_current_node_id = "bad_file"
        task.workflow_path = ["bad_file"]
        task.workflow_data = {}
        error_edge_run = await plugin._run_workflow_runtime(
            event=event,
            task=task,
            spec=error_edge_spec,
            reason="runtime_smoke_error_edge",
        )
        assert error_edge_run.changed
        assert not error_edge_run.blocked
        assert task.workflow_data["node_outputs"]["bad_file"]["note"] == "node_executor_file_missing"
        assert task.workflow_data["node_outputs"]["error_handler"]["note"] == "node_executor_state"
        assert task.workflow_data["variables"]["error"]["handled"] == "yes"
        assert task.workflow_path[-1] == "error_handler"
        task.status = "running"
        task.blockers = []
        task.clear_wait()

        schema_block_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "schema_tool",
                    "stage": "execute",
                    "kind": "tool",
                    "action": "run_tools",
                    "tool_name": "safe_registered_tool",
                    "tool_args": {},
                    "instruction": "should be blocked by missing required tool args",
                }
            ],
            workflow_edges=[],
        )
        schema_block_spec.enabled_tools = ["safe_registered_tool"]
        schema_block_spec.plugin_overrides["safe_plugin"] = True
        plugin._normalize_agent_workflow(schema_block_spec)
        schema_call_count = len(plugin.context.tool_manager.calls)
        task.status = "running"
        task.blockers = []
        task.profile_snapshot["agent"] = schema_block_spec.to_dict()
        task.workflow_current_node_id = "schema_tool"
        task.workflow_path = ["schema_tool"]
        task.workflow_data = {}
        schema_block_run = await plugin._run_workflow_runtime(
            event=event,
            task=task,
            spec=schema_block_spec,
            reason="runtime_smoke_tool_schema",
        )
        assert schema_block_run.blocked
        assert len(plugin.context.tool_manager.calls) == schema_call_count
        assert task.workflow_data["node_outputs"]["schema_tool"]["note"] == "node_executor_tool_schema_mismatch"
        assert "required" in task.workflow_data["node_outputs"]["schema_tool"]["outcome"]
        task.status = "running"
        task.blockers = []

        blocked_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "blocked_tool",
                    "stage": "execute",
                    "kind": "tool",
                    "action": "run_tools",
                    "tool_name": "safe_registered_tool",
                    "tool_args": {"value": "blocked"},
                    "instruction": "should be blocked by no_external",
                }
            ],
            workflow_edges=[],
        )
        blocked_spec.isolation_policy.tool_mode = "no_external"
        blocked_spec.enabled_tools = [plugin_main.NO_EXTERNAL_TOOLS_SENTINEL]
        blocked_spec.plugin_overrides["safe_plugin"] = True
        plugin._normalize_agent_workflow(blocked_spec)
        call_count = len(plugin.context.tool_manager.calls)
        task.profile_snapshot["agent"] = blocked_spec.to_dict()
        task.workflow_current_node_id = "blocked_tool"
        task.workflow_path = ["blocked_tool"]
        task.workflow_data = {}
        blocked_run = await plugin._run_workflow_runtime(
            event=event,
            task=task,
            spec=blocked_spec,
            reason="runtime_smoke_no_external_tool",
        )
        assert blocked_run.blocked
        assert len(plugin.context.tool_manager.calls) == call_count
        assert task.workflow_data["node_outputs"]["blocked_tool"]["note"] == "node_executor_tool_not_allowed"
        task.status = "running"
        task.blockers = []

        parallel_api_calls = []

        def fake_parallel_custom_api_call(method, url, query, body, headers, timeout_seconds):
            parallel_api_calls.append(
                {
                    "method": method,
                    "url": url,
                    "query": query,
                    "body": body,
                    "headers": headers,
                    "timeout_seconds": timeout_seconds,
                }
            )
            return {
                "ok": True,
                "status": 200,
                "body": {
                    "worker": "api_worker",
                    "query": query,
                    "body": body,
                },
            }

        tool_loop_calls = []

        api_blocked_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "blocked_api",
                    "stage": "execute",
                    "kind": "api",
                    "action": "call_api",
                    "api_id": api_spec["api_id"],
                    "api_payload": {"query": {"blocked": "yes"}},
                    "instruction": "should be blocked when custom api tool is not enabled",
                }
            ],
            workflow_edges=[],
        )
        api_blocked_spec.enabled_tools = ["safe_registered_tool"]
        plugin._normalize_agent_workflow(api_blocked_spec)
        task.profile_snapshot["agent"] = api_blocked_spec.to_dict()
        task.workflow_current_node_id = "blocked_api"
        task.workflow_path = ["blocked_api"]
        task.workflow_data = {}
        api_blocked_run = await plugin._run_workflow_runtime(
            event=event,
            task=task,
            spec=api_blocked_spec,
            reason="runtime_smoke_api_not_allowed",
        )
        assert api_blocked_run.blocked
        assert not parallel_api_calls
        assert task.workflow_data["node_outputs"]["blocked_api"]["note"] == "node_executor_api_not_allowed"
        task.status = "running"
        task.blockers = []

        parallel_api_blocked_spec = plugin_main.AgentSpec(
            workflow_nodes=[
                {
                    "id": "parallel_branch",
                    "stage": "plan",
                    "kind": "branch",
                    "action": "parallel_branch",
                    "instruction": "blocked api worker branch",
                },
                {
                    "id": "api_worker",
                    "stage": "execute",
                    "kind": "api",
                    "action": "call_api",
                    "api_id": api_spec["api_id"],
                    "parallel_group": "blocked_api",
                    "instruction": "should be blocked by missing custom api tool",
                },
                {
                    "id": "parallel_merge",
                    "stage": "checkpoint",
                    "kind": "transform",
                    "action": "transform_context",
                    "instruction": "merge",
                },
            ],
            workflow_edges=[
                {"from": "parallel_branch", "to": "api_worker"},
                {"from": "api_worker", "to": "parallel_merge"},
            ],
        )
        parallel_api_blocked_spec.enabled_tools = ["safe_registered_tool"]
        plugin._normalize_agent_workflow(parallel_api_blocked_spec)
        task.profile_snapshot["agent"] = parallel_api_blocked_spec.to_dict()
        task.workflow_current_node_id = "parallel_branch"
        task.workflow_path = ["parallel_branch"]
        task.workflow_data = {}
        parallel_api_blocked = await plugin._run_parallel_workflow(
            event=event,
            task=task,
            spec=parallel_api_blocked_spec,
            branch_node_id="parallel_branch",
            parallel_group="blocked_api",
            api_payloads={"api_worker": {"query": {"blocked": "parallel"}}},
            max_concurrency=1,
        )
        assert parallel_api_blocked["ok"] is False
        assert not parallel_api_calls
        assert parallel_api_blocked["workers"][0]["error"] == "Custom API worker is outside the Agent tool profile."
        task.status = "running"
        task.blockers = []

        async def fake_parallel_worker(**kwargs):
            tools = kwargs.get("tools")
            tool_names = [
                str(getattr(tool, "name", "") or "")
                for tool in getattr(tools, "tools", [])
            ]
            prompt = str(kwargs.get("prompt") or "")
            tool_loop_calls.append(
                {
                    "prompt": prompt,
                    "tool_names": tool_names,
                    "system_prompt": str(kwargs.get("system_prompt") or ""),
                }
            )
            if "tool_worker" in prompt:
                assert tool_names == ["safe_registered_tool"]
                return SimpleNamespace(
                    completion_text="tool_worker completed with safe_registered_tool",
                    usage=SimpleNamespace(input_other=1, input_cached=0, output=2, total=3),
                )
            assert tool_names == []
            return SimpleNamespace(
                completion_text="prompt_worker completed with isolated prompt",
                usage=SimpleNamespace(input_other=1, input_cached=0, output=1, total=2),
            )

        task.profile_snapshot["agent"]["enabled_tools"] = [
            "safe_registered_tool",
            "agent_lab_call_custom_api",
            "agent_lab_run_parallel_workflow",
        ]
        task.profile_snapshot["agent"].setdefault("plugin_overrides", {})["safe_plugin"] = True
        task.profile_snapshot["agent"]["workflow_nodes"] = [
            {
                "id": "entry",
                "title": "Entry",
                "kind": "state",
                "stage": "entry",
                "action": "summarize_entry",
                "instruction": "entry",
            },
            {
                "id": "parallel_branch",
                "title": "Parallel Branch",
                "kind": "branch",
                "stage": "plan",
                "action": "parallel_branch",
                "instruction": "split independent workers",
            },
            {
                "id": "api_worker",
                "title": "API Worker",
                "kind": "api",
                "stage": "execute",
                "action": "call_api",
                "instruction": "call registered API",
                "ref_type": "api",
                "ref_id": api_spec["api_id"],
                "api_id": api_spec["api_id"],
                "parallel_group": "runtime_smoke",
            },
            {
                "id": "prompt_worker",
                "title": "Prompt Worker",
                "kind": "subflow",
                "stage": "execute",
                "action": "manual",
                "instruction": "run prompt-only worker",
                "prompt": "prompt_worker should return a concise structured result",
                "parallel_group": "runtime_smoke",
            },
            {
                "id": "tool_worker",
                "title": "Tool Worker",
                "kind": "tool",
                "stage": "execute",
                "action": "run_tools",
                "instruction": "run whitelisted tool worker",
                "ref_type": "tool",
                "ref_id": "safe_registered_tool",
                "tool_name": "safe_registered_tool",
                "prompt": "tool_worker should use only the safe tool profile",
                "parallel_group": "runtime_smoke",
            },
            {
                "id": "parallel_merge",
                "title": "Parallel Merge",
                "kind": "transform",
                "stage": "checkpoint",
                "action": "transform_context",
                "instruction": "merge worker results",
            },
            {
                "id": "archive",
                "title": "Archive",
                "kind": "memory",
                "stage": "archive",
                "action": "exit_summary",
                "instruction": "archive",
            },
        ]
        task.profile_snapshot["agent"]["workflow_edges"] = [
            {"from": "entry", "to": "parallel_branch"},
            {"from": "parallel_branch", "to": "api_worker"},
            {"from": "parallel_branch", "to": "prompt_worker"},
            {"from": "parallel_branch", "to": "tool_worker"},
            {"from": "api_worker", "to": "parallel_merge"},
            {"from": "prompt_worker", "to": "parallel_merge"},
            {"from": "tool_worker", "to": "parallel_merge"},
            {"from": "parallel_merge", "to": "archive"},
        ]
        task.workflow_current_node_id = "parallel_branch"
        task.workflow_path = ["entry", "parallel_branch"]
        plugin.storage.save_task(task)
        plugin._perform_custom_api_http_call = fake_parallel_custom_api_call
        plugin.context.tool_loop_agent_handler = fake_parallel_worker

        parallel_result_text = await plugin.agent_lab_run_parallel_workflow(
            event,
            branch_node_id="parallel_branch",
            parallel_group="runtime_smoke",
            shared_instruction="runtime smoke parallel execution",
            api_payloads_json=json.dumps(
                {
                    "api_worker": {
                        "query": {"q": "parallel"},
                        "body": {"payload": "runtime"},
                    }
                }
            ),
            max_concurrency="2",
        )
        debug("parallel workflow checked")
        parallel_result = json.loads(parallel_result_text)
        assert parallel_result["ok"] is True
        assert parallel_result["branch_node_id"] == "parallel_branch"
        assert parallel_result["merge_node_id"] == "parallel_merge"
        assert {item["node_id"] for item in parallel_result["workers"]} == {
            "api_worker",
            "prompt_worker",
            "tool_worker",
        }
        assert all(item["worker_spec"]["worker_type"] for item in parallel_result["workers"])
        assert all("output_schema" in item["worker_spec"] for item in parallel_result["workers"])
        assert all(item["evidence"] for item in parallel_result["workers"])
        assert all(item["next_recommendation"] for item in parallel_result["workers"])
        assert parallel_api_calls
        assert parallel_api_calls[0]["headers"]["X-Test-Key"] == "runtime-secret"
        assert parallel_api_calls[0]["query"]["q"] == "parallel"
        assert parallel_api_calls[0]["body"]["payload"] == "runtime"
        assert len(tool_loop_calls) == 2
        assert any(call["tool_names"] == ["safe_registered_tool"] for call in tool_loop_calls)
        assert any(call["tool_names"] == [] for call in tool_loop_calls)
        assert all("Agent Lab Parallel Worker" in call["system_prompt"] for call in tool_loop_calls)
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.parallel_runs
        assert task.parallel_runs[-1]["merge_node_id"] == "parallel_merge"
        assert task.workflow_current_node_id == "parallel_merge"
        assert task.workflow_path[-1] == "parallel_merge"
        assert any(item.get("node_id") == "api_worker" for item in task.workflow_events)
        assert "Parallel Workflow Runs" in plugin.storage.render_markdown(task)
        assert "## Agent Runtime" in plugin.storage.render_markdown(task)
        assert task.workflow_data["agent_runtime"]["last_verdict"]
        assert any(
            item.get("source") == "parallel_worker"
            for item in task.workflow_data["agent_runtime"]["observations"]
        )
        assert "runtime-secret" not in parallel_result_text

        heartbeat = await plugin._enable_heartbeat(event, task, "runtime_smoke")
        debug("heartbeat enabled")
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
        debug("first task finished")
        assert "任务模式已结束并归档" in finish
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"
        archived_runtime = archives[0].workflow_data["agent_runtime"]
        assert archived_runtime["last_decision"]["action"] == "finish_task"
        assert archived_runtime["last_verdict"]["status"] == "completed"
        assert archives[0].workflow_data["archive_evidence"]["task_id"] == archives[0].task_id
        assert archives[0].workflow_data["memory_orchestrator"]["candidate_count"] == 1
        assert "## Agent Runtime" in plugin.storage.render_markdown(archives[0])
        assert plugin.guard.restored
        learned_patterns = plugin.pattern_library.recommend("runtime smoke goal", limit=3)
        assert learned_patterns
        learned_pattern = learned_patterns[0]
        assert learned_pattern["source_task_id"] == archives[0].task_id
        assert learned_pattern["evidence"]["archive_path"]
        assert Path(learned_pattern["evidence"]["archive_path"]).exists()
        assert learned_pattern["plan_template"]["steps"]
        pattern_tool_text = await plugin.agent_lab_recommend_task_patterns(
            event,
            query="runtime smoke goal",
            limit="2",
        )
        assert learned_pattern["pattern_id"] in pattern_tool_text
        assert "archive_path" in pattern_tool_text
        assert learned_pattern["pattern_id"] in plugin._patterns_text("runtime smoke goal")
        assert "Agent Lab Task Pattern Recommendations" in plugin._build_task_pattern_prompt("runtime smoke goal")
        normal_private_memory = await plugin.agent_lab_read_task_memory(
            event,
            query="Agent Lab runtime smoke passed",
            status="all",
        )
        assert "Agent Lab runtime smoke passed" not in normal_private_memory
        candidate = next(
            item
            for item in plugin.storage.list_memory_entries()
            if item.get("kind") == "memory_candidate"
            and "Agent Lab runtime smoke passed" in item.get("text", "")
        )
        assert candidate["status"] == "candidate"
        assert candidate["evidence"]["source_task_id"] == archives[0].task_id
        accepted_text = plugin._memory_command_text(
            event,
            f"accept {candidate['memory_id']} runtime smoke accepted",
        )
        assert "已接受记忆" in accepted_text
        accepted_memory = await plugin.agent_lab_read_task_memory(
            event,
            query="Agent Lab runtime smoke passed",
            status="accepted",
        )
        assert "Agent Lab runtime smoke passed" in accepted_memory
        accepted_entry = plugin.memory_manager.get(candidate["memory_id"])
        assert accepted_entry is not None
        assert accepted_entry["layer"] == "accepted_memory"
        assert accepted_entry["evidence"]["history"][-1]["action"] == "accepted"

    with TemporaryDirectory() as tmp:
        debug("second runtime fixture")
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
        blocked_finish = await plugin._finish_task(
            event,
            status="completed",
            final_summary="premature finish",
            memory_candidates="",
        )
        assert "暂不能完成任务" in blocked_finish
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.status == "paused"
        assert task.workflow_data["agent_runtime"]["last_verdict"]["status"] == "finish_blocked"
        finish_approval = next(
            item for item in task.approvals
            if item.get("status") == "pending" and item.get("approval_type") == "finish_override"
        )
        plugin._resolve_approval(
            event.unified_msg_origin, finish_approval["approval_id"], False, "runtime-smoke"
        )
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        task.status = "running"
        task.watchdog.needs_user = False
        task.watchdog.paused_reason = ""
        task.clear_wait()
        task.last_observation = "archive exists and runtime evidence is present"
        task.last_confirmed_progress = "archive exists"
        plugin.storage.save_task(task)

        async def finish_inside_tick(**kwargs):
            await plugin.agent_lab_finish(
                event,
                final_summary="finished from tool call",
                memory_candidates="- finish did not resurrect active task",
            )
            return SimpleNamespace(completion_text="tool finished task", usage=None)

        context.tool_loop_agent_handler = finish_inside_tick
        result = await plugin._tick(event, "runtime_smoke_finish")
        debug("finish-inside-tick checked")
        assert "任务已在本轮结束或切换" in result
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"

    with TemporaryDirectory() as tmp:
        debug("finish condition verifier fixture")
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(FakeContext(), config={"private_only": True})
        plugin.guard = FakeGuard()
        event = FakeEvent()
        await plugin._start_task(
            event,
            goal="condition verifier smoke",
            completion_conditions="special artifact generated",
            brief="",
            request_heartbeat=False,
            source="runtime_smoke",
            risk_level="work",
        )
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        task.last_observation = "generic observation exists"
        task.last_confirmed_progress = "generic progress exists"
        plugin.storage.save_task(task)

        blocked_finish = await plugin._finish_task(
            event,
            status="completed",
            final_summary="generic summary",
            memory_candidates="",
        )
        assert plugin.storage.load_active_task(event.unified_msg_origin) is not None
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.status == "paused"
        finish_verdict = task.workflow_data["agent_runtime"]["last_verdict"]
        assert finish_verdict["status"] == "finish_blocked"
        assert "special artifact generated" in finish_verdict["missing"]
        assert "special artifact generated" in blocked_finish

        finish_approval = next(
            item for item in task.approvals
            if item.get("status") == "pending" and item.get("approval_type") == "finish_override"
        )
        plugin._resolve_approval(
            event.unified_msg_origin, finish_approval["approval_id"], False, "runtime-smoke"
        )
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        task.status = "running"
        task.clear_wait()
        task.last_observation = "special artifact generated and verified"
        task.last_confirmed_progress = "special artifact generated"
        plugin.storage.save_task(task)
        completed_finish = await plugin._finish_task(
            event,
            status="completed",
            final_summary="special artifact generated",
            memory_candidates="",
        )
        assert "任务模式" in completed_finish
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"

    with TemporaryDirectory() as tmp:
        debug("workflow automation trigger fixture")
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(FakeContext(), config={"private_only": False})
        plugin.guard = FakeGuard()
        spec = plugin.storage.get_agent()
        spec.name = "Workflow automation smoke"
        spec.identity_label_source = "manual"
        spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {
                "enabled": True,
                "types": ["webhook", "keyword"],
                "keywords": ["spam"],
                "webhook_path": "moderation/spam",
            }
        )
        spec.workflow_scope = plugin_main.WorkflowScope.from_dict({"chat_types": ["private"]})
        spec.workflow_nodes = [
            {"id": "trigger", "kind": "trigger", "action": "webhook_trigger"},
            {
                "id": "detect",
                "kind": "detector",
                "action": "match_keyword",
                "keywords": ["spam"],
            },
            {
                "id": "report",
                "kind": "report",
                "action": "generate_report",
                "message": "moderation report",
            },
            {
                "id": "notify",
                "kind": "notification",
                "action": "send_private_message",
                "target": "admin",
                "message": "spam detected",
            },
        ]
        spec.workflow_edges = [
            {"from": "trigger", "to": "detect", "edge_type": "success"},
            {"from": "detect", "to": "report", "edge_type": "success"},
            {"from": "report", "to": "notify", "edge_type": "success"},
        ]
        plugin._prepare_agent_spec_for_save(spec)
        plugin.storage.save_agent(spec)
        event = FakeEvent(message_str="this contains spam")
        payload = plugin._build_trigger_payload(
            source="webhook",
            event=event,
            text="this contains spam",
            data={"webhook_path": "moderation/spam"},
        )
        result = await plugin._trigger_workflow_from_payload(
            event=event,
            source="webhook",
            payload=payload,
            agent_id=spec.agent_id,
        )
        assert result["ok"] is True
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.workflow_data["trigger_payload"]["webhook_path"] == "moderation/spam"
        detect_output = task.workflow_data["node_outputs"]["detect"]
        assert detect_output["data"]["route"] == "success"
        assert "spam" in detect_output["data"]["matched"]
        assert task.workflow_data["reports"]
        assert task.workflow_data["outbox"][-1]["channel"] == "private_message"
        assert task.workflow_current_node_id == "notify"

        unmatched_event = FakeEvent(unified_msg_origin="aiocqhttp:FriendMessage:654321", message_str="clean")
        unmatched_payload = plugin._build_trigger_payload(
            source="webhook",
            event=unmatched_event,
            text="clean",
            data={"webhook_path": "wrong/path"},
        )
        unmatched = await plugin._trigger_workflow_from_payload(
            event=unmatched_event,
            source="webhook",
            payload=unmatched_payload,
            agent_id=spec.agent_id,
        )
        assert unmatched["ok"] is False

        schedule_spec = plugin_main.AgentSpec(name="schedule smoke", identity_label_source="manual")
        schedule_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["schedule"], "cron": "*/5 * * * *"}
        )
        plugin.storage.save_agent(schedule_spec)
        await plugin._rehydrate_workflow_schedules()
        assert schedule_spec.agent_id in plugin._workflow_schedule_jobs
        await plugin._disable_workflow_schedules()
        assert not plugin._workflow_schedule_jobs

        multi_schedule_spec = plugin_main.AgentSpec(name="multi schedule smoke", identity_label_source="manual")
        multi_schedule_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["schedule"], "cron_expressions": ["*/5 * * * *", "0 * * * *"]}
        )
        plugin.storage.save_agent(multi_schedule_spec)
        await plugin._rehydrate_workflow_schedules()
        assert f"{multi_schedule_spec.agent_id}:0" in plugin._workflow_schedule_jobs
        assert f"{multi_schedule_spec.agent_id}:1" in plugin._workflow_schedule_jobs
        await plugin._disable_workflow_schedules()
        assert not plugin._workflow_schedule_jobs

        discovery_credential = plugin.storage.save_credential(
            {"label": "Discovery API Key", "provider": "test", "value": "runtime-secret"}
        )
        discovery_api = plugin.storage.save_custom_api(
            {
                "name": "Discovery API",
                "method": "post",
                "url": "https://example.com/runtime",
                "credential_id": discovery_credential["credential_id"],
                "auth_type": "header",
                "auth_header": "X-Test-Key",
            }
        )
        discovered = plugin._discovered_workflow_modules()
        module_ids = {item["module_id"] for item in discovered}
        assert "plugin:memory_noise" in module_ids
        assert "tool:safe_registered_tool" in module_ids
        assert "builtin:llm_detect" in module_ids
        assert "builtin:archive_task" in module_ids
        assert "builtin:credential_ref" in module_ids
        assert "builtin:browser_profile" in module_ids
        assert "builtin:llm_prompt" in module_ids
        assert "builtin:run_tools" in module_ids
        assert "builtin:call_api" in module_ids
        assert "builtin:request_approval" in module_ids
        assert "builtin:generate_report" in module_ids
        assert "builtin:plan" in module_ids
        assert f"api:{discovery_api['api_id']}" in module_ids
        api_module = next(item for item in discovered if item["module_id"] == f"api:{discovery_api['api_id']}")
        assert api_module["action"] == "call_api"
        assert api_module["runtime_type"] == "api"
        assert api_module["metadata"]["url_host"] == "https://example.com"
        assert api_module["metadata"]["credential_configured"] is True
        assert "runtime-secret" not in json.dumps(api_module, ensure_ascii=False)

        class LlmDetectContext(FakeContext):
            async def llm_generate(self, **kwargs):
                return SimpleNamespace(
                    completion_text=json.dumps(
                        {
                            "route": "success",
                            "reason": "matched toxic insult",
                            "evidence": ["badword"],
                            "confidence": 0.91,
                        }
                    )
                )

        llm_plugin = plugin_main.AgentLabPlugin(LlmDetectContext(), config={"private_only": False})
        llm_plugin.guard = FakeGuard()
        llm_spec = llm_plugin.storage.get_agent()
        llm_spec.name = "llm detector smoke"
        llm_spec.identity_label_source = "manual"
        llm_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["silent_global"], "keywords": ["badword"]}
        )
        llm_spec.workflow_scope = plugin_main.WorkflowScope.from_dict({"chat_types": ["private"]})
        llm_spec.workflow_nodes = [
            {"id": "listen", "kind": "trigger", "action": "listen_message"},
            {"id": "detect", "kind": "detector", "action": "llm_detect", "criteria": "detect toxic content"},
            {"id": "memory", "kind": "memory", "action": "export_task_memory"},
            {"id": "archive", "kind": "memory", "stage": "archive", "action": "archive_task", "summary": "moderation completed"},
        ]
        llm_spec.workflow_edges = [
            {"from": "listen", "to": "detect", "from_port": "success"},
            {"from": "detect", "to": "memory", "from_port": "success"},
            {"from": "memory", "to": "archive", "from_port": "success"},
        ]
        llm_plugin._prepare_agent_spec_for_save(llm_spec)
        llm_plugin.storage.save_agent(llm_spec)
        llm_event = FakeEvent(unified_msg_origin="aiocqhttp:FriendMessage:llm-detect", message_str="badword here")
        await llm_plugin._maybe_trigger_message_monitor(llm_event, mode="native")
        assert llm_plugin.storage.load_active_task(llm_event.unified_msg_origin) is None
        llm_archives = llm_plugin.storage.list_archives(llm_event.unified_msg_origin)
        assert len(llm_archives) == 1
        archived = llm_archives[0]
        assert archived.status == "completed"
        assert archived.workflow_data["node_outputs"]["detect"]["data"]["route"] == "success"
        assert archived.workflow_data["node_outputs"]["detect"]["data"]["llm_result"]["confidence"] == 0.91
        assert archived.workflow_data["memory_exports"]

        dedupe_plugin = plugin_main.AgentLabPlugin(FakeContext(), config={"private_only": False})
        dedupe_plugin.guard = FakeGuard()
        dedupe_spec = dedupe_plugin.storage.get_agent()
        dedupe_spec.name = "dedupe smoke"
        dedupe_spec.identity_label_source = "manual"
        dedupe_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["silent_global"], "keywords": ["once"]}
        )
        dedupe_spec.workflow_scope = plugin_main.WorkflowScope.from_dict({"chat_types": ["private"]})
        dedupe_spec.workflow_nodes = [
            {"id": "listen", "kind": "trigger", "action": "listen_message"},
            {"id": "report", "kind": "report", "action": "generate_report", "message": "once"},
        ]
        dedupe_spec.workflow_edges = [{"from": "listen", "to": "report"}]
        dedupe_plugin._prepare_agent_spec_for_save(dedupe_spec)
        dedupe_plugin.storage.save_agent(dedupe_spec)
        dedupe_event = FakeEvent(unified_msg_origin="aiocqhttp:FriendMessage:dedupe", message_str="once")
        await dedupe_plugin._maybe_trigger_message_monitor(dedupe_event, mode="native")
        await dedupe_plugin._maybe_trigger_message_monitor(dedupe_event, mode="native")
        assert len(dedupe_plugin.storage.list_tasks(dedupe_event.unified_msg_origin)) == 1

        class PromptContext(FakeContext):
            async def llm_generate(self, **kwargs):
                return SimpleNamespace(
                    completion_text=json.dumps(
                        {"route": "success", "summary": "safe summary", "tags": ["github"]}
                    )
                )

        prompt_plugin = plugin_main.AgentLabPlugin(PromptContext(), config={"private_only": False})
        prompt_plugin.guard = FakeGuard()
        prompt_credential = prompt_plugin.storage.save_credential(
            {"label": "GitHub PAT", "provider": "github", "scope": "repo", "value": "ghp_secret_runtime"}
        )
        prompt_spec = prompt_plugin.storage.get_agent()
        prompt_spec.name = "identity prompt smoke"
        prompt_spec.identity_label_source = "manual"
        prompt_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["webhook"], "webhook_path": "identity/prompt"}
        )
        prompt_spec.workflow_scope = plugin_main.WorkflowScope.from_dict({"chat_types": ["private"]})
        prompt_spec.workflow_nodes = [
            {"id": "trigger", "kind": "trigger", "action": "webhook_trigger"},
            {
                "id": "identity",
                "kind": "guard",
                "action": "credential_ref",
                "credential_id": prompt_credential["credential_id"],
                "provider": "github",
                "output_variable": "github_session",
            },
            {
                "id": "prompt",
                "kind": "state",
                "action": "llm_prompt",
                "prompt": "Summarize repository maintenance request.",
                "output_mode": "json",
                "input": "Maintain GitHub repo",
                "output_schema": {
                    "type": "object",
                    "properties": {"route": {"type": "string"}, "summary": {"type": "string"}},
                    "required": ["route", "summary"],
                },
            },
            {"id": "redact", "kind": "state", "action": "secret_redaction", "text": "token=ghp_secret_runtime"},
        ]
        prompt_spec.workflow_edges = [
            {"from": "trigger", "to": "identity"},
            {"from": "identity", "to": "prompt"},
            {"from": "prompt", "to": "redact"},
        ]
        prompt_plugin._prepare_agent_spec_for_save(prompt_spec)
        prompt_plugin.storage.save_agent(prompt_spec)
        prompt_report = prompt_plugin._workflow_report(prompt_spec)
        assert "identity" in prompt_report["special_modules"]
        prompt_event = FakeEvent(unified_msg_origin="aiocqhttp:FriendMessage:identity-prompt", message_str="identity")
        prompt_payload = prompt_plugin._build_trigger_payload(
            source="webhook",
            event=prompt_event,
            text="identity",
            data={"webhook_path": "identity/prompt"},
        )
        prompt_result = await prompt_plugin._trigger_workflow_from_payload(
            event=prompt_event,
            source="webhook",
            payload=prompt_payload,
            agent_id=prompt_spec.agent_id,
        )
        assert prompt_result["ok"] is True
        prompt_task = prompt_plugin.storage.load_active_task(prompt_event.unified_msg_origin)
        assert prompt_task is not None
        identity_output = prompt_task.workflow_data["node_outputs"]["identity"]["data"]
        assert identity_output["session"]["has_credential"] is True
        assert "ghp_secret_runtime" not in json.dumps(identity_output, ensure_ascii=False)
        prompt_output = prompt_task.workflow_data["node_outputs"]["prompt"]["data"]
        assert prompt_output["summary"] == "safe summary"
        redact_output = prompt_task.workflow_data["node_outputs"]["redact"]["data"]
        assert "ghp_secret_runtime" not in json.dumps(redact_output, ensure_ascii=False)
        assert redact_output["redacted"] == "token=********"

        special_spec = plugin_main.AgentSpec(name="special module compile", identity_label_source="manual")
        special_spec.workflow_trigger = plugin_main.WorkflowTrigger.from_dict(
            {"enabled": True, "types": ["message_monitor"], "keywords": ["loop"]}
        )
        special_spec.workflow_nodes = [
            {"id": "listen", "kind": "trigger", "action": "listen_message"},
            {"id": "detect", "kind": "detector", "action": "match_keyword", "keywords": ["loop"]},
            {"id": "retry", "kind": "loop", "action": "retry", "max_retries": 1},
            {"id": "execute", "kind": "state", "action": "save_state"},
            {"id": "failed", "kind": "report", "action": "generate_report", "message": "retry exhausted"},
        ]
        special_spec.workflow_edges = [
            {"from": "listen", "to": "detect", "from_port": "success"},
            {"from": "detect", "to": "retry", "from_port": "success"},
            {"from": "retry", "to": "execute", "from_port": "retry", "to_port": "input"},
            {"from": "retry", "to": "failed", "from_port": "failed", "to_port": "input"},
        ]
        plugin._prepare_agent_spec_for_save(special_spec)
        plugin.storage.save_agent(special_spec)
        compiled = plugin._workflow_report(special_spec)
        assert compiled["special_modules"]["listener"] == ["listen"]
        assert "retry" in compiled["special_modules"]["loop"]
        assert compiled["port_schemas"]["retry"]["inputs"] == ["start", "retry", "error"]
        retry_edges = {edge["to"]: edge for edge in special_spec.workflow_edges if edge["from"] == "retry"}
        assert retry_edges["execute"]["edge_type"] == "retry"
        assert retry_edges["failed"]["edge_type"] == "failed"

        retry_event = FakeEvent(unified_msg_origin="aiocqhttp:FriendMessage:loop-special", message_str="loop")
        retry_payload = plugin._build_trigger_payload(source="message_monitor", event=retry_event, text="loop")
        retry_result = await plugin._trigger_workflow_from_payload(
            event=retry_event,
            source="message_monitor",
            payload=retry_payload,
            agent_id=special_spec.agent_id,
        )
        assert retry_result["ok"] is True
        retry_task = plugin.storage.load_active_task(retry_event.unified_msg_origin)
        assert retry_task is not None
        assert retry_task.workflow_current_node_id == "execute"
        retry_task.workflow_current_node_id = "retry"
        retry_task.workflow_data.setdefault("execution_counts", {})["retry"] = 1
        plugin.storage.save_task(retry_task)
        rerun = await plugin._run_workflow_runtime(
            event=retry_event,
            task=retry_task,
            spec=special_spec,
            reason="runtime_smoke_retry_failed_route",
        )
        assert rerun.changed
        assert retry_task.workflow_current_node_id == "failed"
        assert retry_task.workflow_data["node_outputs"]["retry"]["data"]["route"] == "failed"

    with TemporaryDirectory() as tmp:
        debug("administrator finish override fixture")
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(
            FakeContext(), config={"private_only": True, "workflow_admin_ids": "admin-1"}
        )
        plugin.guard = FakeGuard()
        event = FakeEvent()
        await plugin._start_task(
            event,
            goal="finish override smoke",
            completion_conditions="evidence and report delivered",
            brief="",
            request_heartbeat=False,
            source="runtime_smoke",
            risk_level="work",
        )
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        task.last_observation = "generic progress without completion evidence"
        plugin.storage.save_task(task)
        server = plugin_main.StandaloneWebUIServer(
            owner=plugin,
            static_dir=ROOT / "pages" / "agent-lab",
            host="127.0.0.1",
            port=8788,
            token="",
        )
        client = server.app.test_client()
        blocked_response = await client.post(
            "/api/task/finish",
            json={
                "umo": event.unified_msg_origin,
                "summary": "administrator reviewed the remaining gap",
            },
        )
        blocked_payload = await blocked_response.get_json()
        assert blocked_payload["ok"] is False
        assert blocked_payload["status"] == "paused"
        assert blocked_payload["approval"]["approval_type"] == "finish_override"
        approval_id = blocked_payload["approval"]["approval_id"]
        assert approval_id in blocked_payload["error"]
        denied = plugin._resolve_approval(event.unified_msg_origin, approval_id, True, "not-admin")
        assert "workflow_admin_ids" in denied
        approved_response = await client.post(
            "/api/task/approval",
            json={
                "umo": event.unified_msg_origin,
                "approval_id": approval_id,
                "approved": True,
            },
        )
        approved_payload = await approved_response.get_json()
        assert approved_payload["ok"] is True
        assert approved_payload["archived"] is True
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archived = plugin.storage.list_archives(event.unified_msg_origin)[0]
        decisions = archived.workflow_data.get("finish_decisions") or []
        assert decisions and decisions[-1]["approval_id"] == approval_id
        assert decisions[-1]["approved_by"] == "webui"
        reports = archived.workflow_data.get("reports") or []
        assert any(item.get("kind") == "finish_override_report" for item in reports)

    with TemporaryDirectory() as tmp:
        debug("third runtime fixture")
        plugin_main.StarTools.get_data_dir = staticmethod(
            lambda plugin_name=None: Path(tmp) / "plugin_data" / (plugin_name or "unknown")
        )
        plugin = plugin_main.AgentLabPlugin(
            FakeContext(config={"bot_name": "配置机器人"}, persona_name=None),
            config={"private_only": True},
        )
        assert plugin.storage.get_agent().name == "配置机器人任务模式"
        runtime_identity = plugin._runtime_identity_payload()
        assert runtime_identity["bot_label"] == "配置机器人"
        assert runtime_identity["bot_label_source"] == "astrbot_config"

    debug("runtime smoke complete")
    print("Agent Lab runtime smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
    # AstrBot SDK imports can leave non-daemon scheduler/sqlite helper threads alive
    # in this isolated smoke environment. All assertions have completed here.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
