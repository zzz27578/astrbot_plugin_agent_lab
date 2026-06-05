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
        debug("task started")
        assert "已进入 Agent Mode" in start
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.root_goal == "runtime smoke goal"
        assert task.profile_snapshot["agent"]["name"] == "测试人格 Agent Mode"
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
            next_node_id="entry_gate",
            note="runtime smoke",
        )
        assert "entry -> entry_gate" in advanced
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.workflow_current_node_id == "entry_gate"
        assert task.workflow_path[-1] == "entry_gate"
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
        assert "entry_gate" in task.workflow_path
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
        debug("custom api tool checked")
        assert '"pong"' in api_result
        assert "runtime-secret" not in api_result
        assert api_call["headers"]["X-Test-Key"] == "runtime-secret"
        assert api_call["query"]["q"] == "smoke"
        assert api_call["body"]["hello"] == "world"
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert any(item.get("kind") == "custom_api" for item in task.progress_log)
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
                    "id": "tool_exec",
                    "stage": "execute",
                    "kind": "tool",
                    "action": "run_tools",
                    "tool_name": "safe_registered_tool",
                    "tool_args": {"value": "from_node"},
                    "output_variable": "tool_result",
                    "instruction": "direct tool executor",
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
                    "id": "checkpoint_exec",
                    "stage": "checkpoint",
                    "kind": "state",
                    "action": "save_state",
                    "instruction": "checkpoint",
                },
            ],
            workflow_edges=[
                {"from": "api_exec", "to": "tool_exec"},
                {"from": "tool_exec", "to": "memory_exec"},
                {"from": "memory_exec", "to": "validate_exec"},
                {"from": "validate_exec", "to": "checkpoint_exec"},
            ],
        )
        executor_spec.enabled_tools = ["safe_registered_tool", "agent_lab_call_custom_api"]
        executor_spec.plugin_overrides["safe_plugin"] = True
        plugin._normalize_agent_workflow(executor_spec)
        task.profile_snapshot["agent"] = executor_spec.to_dict()
        task.workflow_current_node_id = "api_exec"
        task.workflow_path = ["api_exec"]
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
        assert task.workflow_data["node_outputs"]["tool_exec"]["data"]["tool_name"] == "safe_registered_tool"
        assert task.workflow_data["variables"]["tool_result"]["result"]
        assert plugin.context.tool_manager.calls[-1]["args"]["value"] == "from_node"
        assert task.workflow_data["node_outputs"]["memory_exec"]["data"]["kind"] == "workflow_private_memory"
        assert any(item.get("kind") == "task_memory" for item in task.progress_log)
        rendered = plugin.storage.render_markdown(task)
        assert "Workflow Node Outputs" in rendered
        assert "Agent Runtime" in rendered
        assert "api_exec" in rendered

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
        assert "Agent Mode 已结束并归档" in finish
        assert plugin.storage.load_active_task(event.unified_msg_origin) is None
        archives = plugin.storage.list_archives(event.unified_msg_origin)
        assert len(archives) == 1
        assert archives[0].status == "completed"
        archived_runtime = archives[0].workflow_data["agent_runtime"]
        assert archived_runtime["last_decision"]["action"] == "finish_task"
        assert archived_runtime["last_verdict"]["status"] == "completed"
        assert "## Agent Runtime" in plugin.storage.render_markdown(archives[0])
        assert plugin.guard.restored
        normal_private_memory = await plugin.agent_lab_read_task_memory(
            event,
            query="Agent Lab runtime smoke passed",
            status="all",
        )
        assert "Agent Lab runtime smoke passed" not in normal_private_memory

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
        debug("third runtime fixture")
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

    debug("runtime smoke complete")
    print("Agent Lab runtime smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
    # AstrBot SDK imports can leave non-daemon scheduler/sqlite helper threads alive
    # in this isolated smoke environment. All assertions have completed here.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
