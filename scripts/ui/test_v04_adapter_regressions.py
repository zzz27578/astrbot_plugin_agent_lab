"""Exercise the six v0.4 adapter regressions through the real plugin.

Run: python -B scripts/ui/test_v04_adapter_regressions.py

The installed AstrBot decorators, ToolSet, tool executor and complete plugin
class are imported, including its canvas mixin. Product methods are never
extracted, replaced or mocked. Only the host context, file-tool handler,
scheduler, model and message transport are fixtures. All storage is temporary;
this script writes no repository report and makes no model/network requests.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from copy import copy, deepcopy
from functools import partial
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import AsyncMock, patch

sys.dont_write_bytecode = True

import jsonschema
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, StarTools
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.provider.func_tool_manager import FunctionToolManager
from astrbot.core.provider.register import llm_tools
from mcp.types import CallToolResult, TextContent
from quart import Quart, g

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "v04_adapter_regression_product"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT)]
sys.modules[PACKAGE] = package

# Capture the actual decorator-created tools, without replacing tools belonging
# to another test imported in this same process. Per-test binding below mirrors
# AstrBot's plugin loader and keeps the original registration objects intact.
previous_tools = list(llm_tools.func_list)
try:
    with patch.object(logger, "disabled", True):
        Product = importlib.import_module(PACKAGE + ".main")
    REGISTERED = {tool.name: tool for tool in llm_tools.func_list
                  if getattr(tool.handler, "__module__", "") == Product.__name__}
finally:
    llm_tools.func_list[:] = previous_tools


def product_module(name):
    return importlib.import_module(PACKAGE + ".agent_lab." + name)


Models = product_module("models")
Support = product_module("adapter_support")
Surface = product_module("task_surface")
Tools = product_module("task_tools")
Control = product_module("task_control")
NodeContext = product_module("node_runtime").NodeExecutionContext


class HostEvent(AstrMessageEvent):
    """A private host event; product authorization still runs normally."""

    def __init__(self, sender="123"):
        self.unified_msg_origin = "fixture:FriendMessage:123"
        self.message_str = "Continue the authorized fixture task."
        self.role = "admin"
        self.sender = sender
        self._extras = {}
        self._result = None
        self.message_obj = S(type="FriendMessage")
        self.platform_meta = S(name="fixture", id="fixture")

    def is_private_chat(self):
        return True

    def get_sender_id(self):
        return self.sender

    def get_sender_name(self):
        return "Fixture administrator"

    def get_group_id(self):
        return ""


class HostContext(Context):
    """Only host-facing APIs are fixtures; the manager/schema classes are real."""

    def __init__(self, workspace):
        self.workspace = workspace
        self._config = {"admins_id": ["123"], "bot_label": "Fixture Bot",
                        "provider_settings": {"computer_use_runtime": "local"}}
        self.manager = FunctionToolManager()
        self.routes = []
        self.external_calls = []
        self.next_result = None
        self.cron_manager = None
        self.persona_manager = None
        self.platform_manager = S(platform_insts=[], platforms_config=[])
        self.conversation_manager = S()
        self.send_message = AsyncMock(return_value=True)
        self.get_current_chat_provider_id = AsyncMock(return_value="offline-provider")
        self.llm_generate = AsyncMock(side_effect=AssertionError("unexpected model request"))

    def get_config(self, umo=None):
        return self._config

    def get_all_stars(self):
        return []

    def get_llm_tool_manager(self):
        return self.manager

    def register_web_api(self, *args):
        self.routes.append(args)

    async def read_file(self, event, path, offset=0, limit=800):
        target = Path(path).resolve()
        if not target.is_relative_to(self.workspace.resolve()):
            raise AssertionError("fixture host tool escaped its temporary workspace")
        self.external_calls.append({"path": str(target), "offset": offset, "limit": limit})
        if self.next_result is not None:
            result, self.next_result = self.next_result, None
            return result
        lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
        return CallToolResult(content=[TextContent(type="text", text="".join(lines[offset:offset + limit]))])


class SlowDeleteJob:
    """Pause only the first host scheduler call; concurrent admin work can run."""

    def __init__(self):
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def delete_job(self, job_id):
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await self.release.wait()


class AdapterRegressions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()
        self.context = HostContext(self.workspace)
        previous_context = StarTools._context
        self.addCleanup(setattr, StarTools, "_context", previous_context)
        with patch.object(StarTools, "get_data_dir", return_value=Path(self.temp.name) / "data"):
            self.plugin = Product.AgentLabPlugin(self.context, {
                "workflow_admin_ids": "123", "install_agent_mode_skill": False,
                "standalone_webui_enabled": False, "inject_agent_mode_policy": True,
            })
        self.storage = self.plugin.storage
        self.event = HostEvent()
        for original in REGISTERED.values():
            tool = copy(original)
            tool.handler = partial(original.handler, self.plugin)
            tool.handler_module_path = Product.__name__
            self.context.manager.func_list.append(tool)
        self.context.manager.func_list.append(FunctionTool(
            name="astrbot_file_read_tool", description="Read a temporary fixture file.",
            handler=self.context.read_file,
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}},
                "required": ["path"], "additionalProperties": False}))
        self.context.manager.func_list.append(FunctionTool(
            name="host_unrelated", description="Unrelated host tool.",
            parameters={"type": "object", "properties": {}}))
        self.spec = Models.AgentSpec()
        self.spec.enabled_tools = ["astrbot_file_read_tool"]
        self.spec.isolation_policy.tool_mode = "whitelist"
        self.spec.isolation_policy.mode = "off"

    def new_task(self, *, canvas=False):
        task = Models.TaskState(umo=self.event.unified_msg_origin, root_goal="Read the fixture research note",
                                status="running", profile_snapshot={"agent": self.spec.to_dict()})
        self.plugin.task_control.initialize(task, self.event, "selected" if canvas else "none")
        state = Control.control(task)
        state.update(version=1, approved_version=1, authorization_version=1, input_revision=0,
                     phase="execution", human_paused=False, current_step_id="one",
                     steps=[{"id": "one", "title": "Read the note", "instruction": "Read note.md",
                             "status": "pending", "evidence": [], "revision": 0}],
                     scope_roots=[str(self.workspace)], authorized_scope_roots=[str(self.workspace)],
                     execution_settings={"mode": "standard", "roots": [str(self.workspace)]})
        task.status = "running"
        project = self.plugin.projects.create("Adapter regression", "tests", task.umo, "123")
        self.plugin.projects.attach(task, project["project_id"])
        self.storage.save_task(task)
        return task

    def current(self):
        return self.storage.load_active_task(self.event.unified_msg_origin)

    async def completed_task(self):
        task = self.new_task()
        note = self.workspace / "note.md"
        note.write_text("Actual research note read from a temporary file.\n", encoding="utf-8")
        tool = self.plugin.astrbot_bridge.tool("astrbot_file_read_tool", self.event)
        results = await self.plugin.astrbot_bridge.invoke(
            self.event, tool, {"path": str(note)}, task.task_id, native=True)
        self.assertTrue(results and not any(result.isError for result in results))
        await self.plugin.task_plan(self.event, steps_json="", completed_step="one",
                                    summary="Read note.md and confirmed the research material.")
        task = self.current()
        verdict = self.plugin.verifier.verify_finish(task, status="completed", final_summary=self.delivery)
        self.assertTrue(verdict.passed, verdict)
        return task

    delivery = "已核对 note.md 的真实资料，研究完成；未修改文件，也未运行测试。"

    async def test_structured_tool_error_blocks_the_real_canvas_node(self):
        task = self.new_task(canvas=True)
        self.context.next_result = CallToolResult(
            content=[TextContent(type="text", text="The requested item is unavailable.")], isError=True)
        node = {"id": "read", "kind": "tool", "action": "run_tools",
                "tool_name": "astrbot_file_read_tool", "permission_profile": "work",
                "tool_args": {"path": str(self.workspace / "missing.md")}}
        result = await self.plugin._execute_tool_node(NodeContext(
            event=self.event, task=task, spec=self.spec, node=node,
            outgoing=["next"], next_candidates=[{"id": "next"}]))
        row = Control.control(self.current())["journal"][-1]
        self.assertEqual(len(self.context.external_calls), 1, "the host executor must actually run")
        self.assertEqual(row["status"], "failed")
        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertFalse(result.advance, "a failed host tool must not advance the canvas")
        self.assertEqual(result.next_node_id, "")
        self.assertIn("unavailable", result.outcome)

    async def test_successful_canvas_read_does_not_treat_old_status_text_as_an_error(self):
        task = self.new_task(canvas=True)
        note = self.workspace / "note.md"
        note.write_text("Log format documentation: status=failed] and status=unknown]\n", encoding="utf-8")
        node = {"id": "read", "kind": "tool", "action": "run_tools", "permission_profile": "work",
                "tool_name": "astrbot_file_read_tool", "tool_args": {"path": str(note)}}
        result = await self.plugin._execute_tool_node(NodeContext(
            event=self.event, task=task, spec=self.spec, node=node,
            outgoing=["next"], next_candidates=[{"id": "next"}]))
        self.assertEqual(Control.control(self.current())["journal"][-1]["status"], "completed")
        self.assertTrue(result.ok)
        self.assertFalse(result.blocked)
        self.assertTrue(result.advance)
        self.assertEqual(result.next_node_id, "next")

    async def test_bot_delivery_is_archived_verbatim_without_a_second_model(self):
        task = await self.completed_task()
        result = await self.plugin.task_finish(self.event, final_summary=self.delivery)
        self.assertIsNone(self.current(), result)
        archived = self.storage._read_json(self.storage.archive_task_json_path(task.umo, task.task_id))
        self.assertEqual(archived["status"], "completed")
        self.assertEqual(archived["exit_summary"], self.delivery)
        self.assertTrue(self.storage.ended_path(task.task_id).is_file())
        self.context.llm_generate.assert_not_awaited()
        self.assertTrue(self.context.send_message.await_args_list, "real TaskMessages should use the host transport")
        self.assertTrue(any(self.delivery in str(call.args) for call in self.context.send_message.await_args_list))

    async def run_finish_race(self, action):
        task = await self.completed_task()
        task.heartbeat.enabled, task.heartbeat.job_id = True, "fixture-slow-delete"
        self.storage.save_task(task)
        scheduler = SlowDeleteJob()
        self.context.cron_manager = scheduler
        operation = asyncio.create_task(self.plugin.task_finish(self.event, final_summary=self.delivery))
        try:
            await asyncio.wait_for(scheduler.entered.wait(), 3)
            if action == "pause":
                await self.plugin._administrator_task_control(self.event, "pause")
                self.assertNotIn("finishing_nonce", Control.control(self.current()))
            elif action == "steer":
                self.plugin.task_control.steer(task.umo, "保留当前任务，管理员还需要复核。")
            elif action == "plan":
                await self.plugin.task_control.submit_plan(self.event, json.dumps([
                    {"id": "one", "title": "Read the note", "instruction": "Read note.md"},
                    {"id": "review", "title": "Additional review", "instruction": "Inspect another source"}]))
            elif action == "stop":
                await self.plugin._administrator_task_control(self.event, "stop")
            else:
                raise AssertionError(action)
            if action == "stop":
                protected = self.storage.archive_task_json_path(task.umo, task.task_id).read_bytes()
            else:
                protected = self.storage.task_path(task.umo, task.task_id).read_bytes()
            scheduler.release.set()
            await asyncio.wait_for(operation, 3)
            if action == "stop":
                self.assertIsNone(self.current())
                path = self.storage.archive_task_json_path(task.umo, task.task_id)
                self.assertEqual(path.read_bytes(), protected, "late automatic finish overwrote administrator archive")
                self.assertEqual(self.storage._read_json(path)["status"], "cancelled")
            else:
                current = self.current()
                self.assertIsNotNone(current, "late automatic finish removed the active task")
                self.assertEqual(current.status, "paused")
                self.assertEqual(self.storage.task_path(task.umo, task.task_id).read_bytes(), protected)
                self.assertFalse(self.storage.ended_path(task.task_id).exists())
                self.assertFalse(self.storage.archive_task_json_path(task.umo, task.task_id).exists())
            self.context.llm_generate.assert_not_awaited()
        finally:
            scheduler.release.set()
            if not operation.done():
                operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)

    async def test_admin_pause_during_disable_heartbeat_survives_late_finish(self):
        await self.run_finish_race("pause")

    async def test_new_input_revision_during_disable_heartbeat_fences_late_finish(self):
        await self.run_finish_race("steer")

    async def test_new_plan_version_during_disable_heartbeat_fences_late_finish(self):
        await self.run_finish_race("plan")

    async def test_admin_stop_during_disable_heartbeat_keeps_its_terminal_archive(self):
        await self.run_finish_race("stop")

    async def test_paused_entry_blocks_automatic_finish_but_administrator_can_deliver(self):
        task = await self.completed_task()
        await self.plugin.projects.pause_execution(task)
        protected = self.storage.task_path(task.umo, task.task_id).read_bytes()
        await self.plugin.task_finish(self.event, final_summary=self.delivery)
        self.assertEqual(self.storage.task_path(task.umo, task.task_id).read_bytes(), protected)
        self.assertEqual(self.current().status, "paused")
        self.assertFalse(self.storage.ended_path(task.task_id).exists())
        await self.plugin._administrator_task_control(self.event, "deliver")
        self.assertIsNone(self.current())
        self.assertEqual(self.storage._read_json(
            self.storage.archive_task_json_path(task.umo, task.task_id))["status"], "completed")
        self.context.llm_generate.assert_not_awaited()

    async def test_annotated_catalog_export_and_real_modules_api(self):
        self.assertIn("BUILTIN_WORKFLOW_MODULE_CATALOG", Support.__all__)
        self.assertIs(Product.BUILTIN_WORKFLOW_MODULE_CATALOG, Support.BUILTIN_WORKFLOW_MODULE_CATALOG)
        app = Quart(__name__)

        @app.before_request
        async def authenticate():
            g.username = "fixture-admin"

        app.add_url_rule("/modules", view_func=self.plugin.api_modules, methods=["GET"])
        response = await app.test_client().get("/modules")
        self.assertEqual(response.status_code, 200)
        payload = await response.get_json()
        self.assertTrue(payload["ok"])
        actions = {row["action"] for row in payload["builtin_modules"]}
        self.assertEqual(actions, set(Support.BUILTIN_WORKFLOW_MODULE_CATALOG))
        self.assertTrue({"run_tools", "request_approval", "archive_task"} <= actions)

    async def check_daily_filter(self, *, enabled, authorized):
        self.new_task()
        self.plugin.config["inject_agent_mode_policy"] = enabled
        event = self.event if authorized else HostEvent("untrusted")
        prompt = "Original source Bot prompt."
        request = ProviderRequest(system_prompt=prompt, func_tool=self.context.manager.get_full_tool_set())
        shared_names = [tool.name for tool in self.context.manager.func_list]
        await self.plugin.inject_agent_lab_policy(event, request)
        visible = {tool.name for tool in request.func_tool.tools}
        self.assertFalse(visible & Tools.CONTROL_TOOL_NAMES)
        self.assertFalse({"agent_lab_finish", "agent_lab_request_approval", "agent_lab_checkpoint"} & visible)
        self.assertIn("host_unrelated", visible)
        self.assertEqual([tool.name for tool in self.context.manager.func_list], shared_names)
        if authorized:
            self.assertIn("agent_lab_enter_mode", visible)
            self.assertIn("agent_lab_project", visible)
        else:
            self.assertFalse(any(name.startswith("agent_lab_") for name in visible))
        if not enabled or not authorized:
            self.assertEqual(request.system_prompt, prompt)
        else:
            self.assertTrue(request.system_prompt.startswith(prompt))
            self.assertGreater(len(request.system_prompt), len(prompt))

    async def test_daily_filter_remains_active_when_prompt_injection_is_disabled(self):
        await self.check_daily_filter(enabled=False, authorized=True)

    async def test_untrusted_daily_request_is_filtered_when_prompt_injection_is_disabled(self):
        await self.check_daily_filter(enabled=False, authorized=False)

    async def test_daily_filter_with_prompt_injection_enabled(self):
        await self.check_daily_filter(enabled=True, authorized=True)

    async def test_canvas_legacy_approval_and_finish_match_the_real_prompt(self):
        self.new_task(canvas=True)
        # No-external mode also has to retain the canvas's own controls.
        self.spec.isolation_policy.tool_mode = "no_external"
        tools = self.plugin._build_toolset(self.spec, self.event)
        prompt, _ = self.plugin.runtime_runner._task_prompts(self.current(), self.spec, "regression")
        for name in ("agent_lab_request_approval", "agent_lab_finish"):
            with self.subTest(name=name):
                self.assertIn(name, prompt)
                tool = tools.get_tool(name)
                self.assertIsNotNone(tool)
                self.assertIsNotNone(tool.handler)
                self.assertIs(tool.handler.func, REGISTERED[name].handler)
        current = self.current()
        Control.control(current)["workflow"] = "none"
        self.storage.save_task(current)
        plain = self.plugin._build_toolset(self.spec, self.event)
        self.assertEqual({tool.name for tool in plain.tools}, set(Tools.CONTROL_TOOL_NAMES))

    async def test_real_five_tool_schemas_are_private_copies_of_registered_tools(self):
        self.new_task()
        self.spec.isolation_policy.tool_mode = "no_external"
        host = {name: self.context.manager.get_func(name) for name in Tools.CONTROL_TOOL_NAMES}
        originals = {name: (deepcopy(tool.parameters), tool.description, tool.handler) for name, tool in host.items()}
        definitions = {row["function"]["name"]: row["function"] for row in Tools.TASK_TOOL_SCHEMAS}
        catalog_before = deepcopy(Tools.TASK_TOOL_SCHEMAS)
        first = self.plugin._build_toolset(self.spec, self.event)
        second = self.plugin._build_toolset(self.spec, self.event)
        first_api = {row["function"]["name"]: row["function"] for row in first.openai_schema()}
        self.assertEqual(set(first_api), set(Tools.CONTROL_TOOL_NAMES))
        for name in sorted(Tools.CONTROL_TOOL_NAMES):
            with self.subTest(name=name):
                schema = first_api[name]["parameters"]
                self.assertEqual(schema, definitions[name]["parameters"])
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate({}, schema)
                valid = {key: "fixture value" for key in schema["required"]}
                jsonschema.validate(valid, schema)
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate({**valid, "unexpected_argument": "value"}, schema)
                self.assertIsNot(first.get_tool(name), host[name])
                self.assertIsNot(second.get_tool(name), first.get_tool(name))
                self.assertIs(first.get_tool(name).handler, host[name].handler)
                self.assertIs(first.get_tool(name).handler.func, REGISTERED[name].handler)
                first.get_tool(name).parameters["properties"][schema["required"][0]]["description"] = "local mutation"
                self.assertEqual(second.get_tool(name).parameters, definitions[name]["parameters"])
                self.assertEqual(host[name].parameters, originals[name][0])
                self.assertEqual(host[name].description, originals[name][1])
                self.assertIs(host[name].handler, originals[name][2])
        self.assertEqual(Tools.TASK_TOOL_SCHEMAS, catalog_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
