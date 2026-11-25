"""Blank canvas regressions through the real plugin, HTTP API and UI functions.

Run: python -B scripts/ui/test_blank_canvas.py
Only temporary storage is used; no model or production bot is contacted.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import AsyncMock, patch

from quart import Quart, g

import test_v04_adapter_regressions as F

Mode = F.product_module("canvas_mode")


class BlankCanvasTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Session persona preferences are an external host boundary. Never open
        # AstrBot's global SQLite store during a temporary task fixture.
        preferences = patch("astrbot.api.sp.get_async", new=AsyncMock(return_value={}))
        preferences.start()
        self.addCleanup(preferences.stop)
        self.fixture = F.AdapterRegressions()
        self.fixture.setUp()
        # Run the reused fixture's cleanups on this test's initialized loop.
        self._cleanups.extend(self.fixture._cleanups)
        self.fixture._cleanups.clear()
        self.plugin, self.storage = self.fixture.plugin, self.fixture.storage
        self.spec, self.event = self.fixture.spec, self.fixture.event

    def blank(self, *, legacy=False):
        self.spec.workflow_nodes = []
        self.spec.workflow_edges = []
        task = self.fixture.new_task(canvas=True)
        if legacy:
            state = F.Control.control(task)
            state["workflow"] = "selected"
            state.pop("requested_workflow", None)
            state.pop("canvas_kind", None)
            self.storage.save_task(task)
        return task

    def test_classification_uses_snapshot_and_preserves_meaningful_legacy_nodes(self):
        for nodes in ([], [None, "junk", {}, {"x": 100, "y": 200}], [{"id": " "}]):
            self.assertEqual(Mode.canvas_kind({"workflow_nodes": nodes}), "blank")
        self.assertEqual(Mode.canvas_kind({"workflow_nodes": [{"title": "x", "action": "run_tools"}]}), "workflow")
        task = self.blank(legacy=True)
        self.assertFalse(Mode.canvas_enabled(task))
        task.profile_snapshot = {}
        self.assertFalse(Mode.canvas_enabled(task), "never fall back to the default agent")

    def test_normalize_only_changes_mode_metadata_and_is_idempotent(self):
        task = self.blank(legacy=True)
        before = deepcopy(task.to_dict())
        expected = before["workflow_data"]["task_control"]
        expected.update(workflow="none", requested_workflow="selected", canvas_kind="blank")
        self.assertTrue(Mode.normalize_canvas_mode(task))
        self.assertEqual(task.to_dict(), before)
        self.assertFalse(Mode.normalize_canvas_mode(task))

    def test_normalizer_keeps_zero_nodes_and_supplies_missing_legacy_ids(self):
        self.spec.workflow_nodes = []
        self.spec.workflow_trigger.types = ["schedule", "plugin_event", "webhook"]
        self.plugin._normalize_agent_workflow(self.spec)
        self.assertEqual(self.spec.workflow_nodes, [])
        self.assertEqual(self.spec.workflow_edges, [])
        self.spec.workflow_nodes = [{"title": "x", "action": "run_tools", "x": 123, "y": 456}]
        self.plugin._normalize_agent_workflow(self.spec)
        node = next(node for node in self.spec.workflow_nodes if node["title"] == "x")
        self.assertTrue(node["id"])
        self.assertEqual((node["x"], node["y"]), (123, 456))

    def test_selected_blank_hides_legacy_tools_and_keeps_custom_guidance(self):
        task = self.blank(legacy=True)
        self.spec.system_prompt = "CUSTOM_SCHEME_BEHAVIOR"
        self.spec.task_prompt = "CUSTOM_SCHEME_TASK_GUIDANCE"
        visible = {tool.name for tool in self.plugin._build_toolset(self.spec, self.event).tools}
        self.assertFalse(visible & F.Surface.CANVAS_TOOLS)
        self.assertTrue(F.Tools.CONTROL_TOOL_NAMES <= visible)
        system, prompt = self.plugin.runtime_runner._task_prompts(task, self.spec, "blank_regression")
        self.assertIn(self.spec.system_prompt, system)
        self.assertIn(self.spec.task_prompt, system)
        self.assertNotIn("agent_lab_advance_workflow", system + prompt)
        self.assertNotIn("agent_lab_finish", system)
        self.assertEqual(F.Control.control(self.fixture.current())["workflow"], "none")

    async def test_blank_runtime_uses_checklist_without_zero_node_plan(self):
        task = self.blank(legacy=True)
        self.plugin._sync_agent_runtime(task, self.spec, reason="blank_regression")
        plan = task.workflow_data["agent_runtime"]["plan"]
        self.assertEqual(plan["source"], "task_control")
        self.assertEqual([row["node_id"] for row in plan["steps"]], ["one"])
        self.assertFalse(any("plan initialized with 0" in str(row) for row in task.progress_log))
        run = await self.plugin._run_workflow_runtime(event=self.event, task=task, spec=self.spec, reason="blank_regression")
        self.assertTrue(run.needs_react)
        self.assertEqual(run.steps, [])
        self.assertEqual(self.plugin._workflow_runtime_view(task)["current_node"], {})

    async def settings_client(self):
        app = Quart(__name__)

        @app.before_request
        async def authenticate():
            g.username = "fixture-admin"

        app.add_url_rule("/agents", view_func=self.plugin.api_agents, methods=["POST"])
        return app.test_client()

    async def test_settings_http_preserves_latest_canvas_layout_and_default(self):
        client = await self.settings_client()
        self.spec.workflow_nodes = [{"title": "legacy", "action": "run_tools", "x": 17, "y": 19}]
        self.spec.workflow_edges = [{"from": "old", "to": "other", "layout": {"x": 42}}]
        self.storage.save_agent(self.spec)
        original = self.storage.get_agent(self.spec.agent_id).to_dict()
        default = self.storage.default_agent_id()
        response = await client.post("/agents", json={"action": "save_settings", "agent_id": self.spec.agent_id,
            "system_prompt": "custom", "task_prompt": "task guidance", "plugin_overrides": {"example": False},
            "disabled_tools": ["astrbot_file_read_tool"], "isolation_policy": {"tool_mode": "no_external"},
            "workflow_nodes": [{"id": "UNSAVED_DRAFT"}], "workflow_edges": [], "workflow_trigger": {},
            "name": "UNSAVED_NAME", "default_task_budget": {"max_total_tool_calls": 123}, "_make_default": True})
        payload = await response.get_json()
        self.assertTrue(payload["ok"], payload)
        saved = self.storage.get_agent(self.spec.agent_id).to_dict()
        for key in ("workflow_nodes", "workflow_edges", "workflow_trigger", "workflow_scope", "name", "default_task_budget"):
            self.assertEqual(saved[key], original[key], key)
        self.assertEqual(saved["plugin_overrides"], {"example": False})
        self.assertEqual(saved["disabled_tools"], ["astrbot_file_read_tool"])
        self.assertEqual(saved["isolation_policy"]["tool_mode"], "no_external")
        self.assertEqual(self.storage.default_agent_id(), default)

    async def test_blank_settings_and_editor_save_keep_zero_nodes(self):
        client = await self.settings_client()
        self.spec.workflow_nodes = self.spec.workflow_edges = []
        self.storage.save_agent(self.spec)
        for body in ({"action": "save_settings", "agent_id": self.spec.agent_id, "task_prompt": "custom"},
                     self.spec.to_dict()):
            response = await client.post("/agents", json=body)
            payload = await response.get_json()
            self.assertTrue(payload["ok"], payload)
            self.assertEqual(payload["agent"]["workflow_nodes"], [])
            self.assertEqual(payload["agent"]["workflow_edges"], [])

    async def test_new_selected_blank_task_normalizes_before_initialization(self):
        self.spec.workflow_nodes = self.spec.workflow_edges = []
        self.storage.save_agent(self.spec)
        plan = {"steps": [{"id": "one", "title": "Read fixture", "instruction": "Read fixture note"}],
                "message": "Please approve reading the fixture note."}
        await self.plugin._start_task(self.event, goal="Read fixture", completion_conditions="Read note", brief="Fixture note", request_heartbeat=False,
                                     source="fixture", risk_level="work", agent_id=self.spec.agent_id,
                                     workflow_mode="selected", plan_json=json.dumps(plan))
        task = self.fixture.current()
        self.assertEqual(F.Control.control(task)["workflow"], "none")
        self.assertEqual(F.Control.control(task)["requested_workflow"], "selected")
        self.assertEqual(task.workflow_current_node_id, "")
        self.assertFalse(any("plan initialized with 0" in str(row) for row in task.progress_log))
        self.assertIn("画布：不应用", task.approvals[-1]["impact"])

    def test_frontend_blank_schema_defaults_and_settings_payload(self):
        result = subprocess.run([shutil.which("node") or "node", "test_blank_canvas.mjs"],
                                cwd=F.ROOT / "scripts/ui", capture_output=True, text=True, encoding="utf-8", timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
