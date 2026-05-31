from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_lab import AgentLabStorage
from agent_lab.models import AgentSpec, TaskState
from agent_lab.modules import ModuleRegistry
from agent_lab.session_guard import SessionPluginGuard
from agent_lab.webui_server import StandaloneWebUIServer


class FakeWebOwner:
    async def api_state(self):
        from quart import jsonify

        return jsonify({"ok": True, "agents": []})

    async def api_agents(self):
        from quart import jsonify

        return jsonify({"ok": True})

    api_modules = api_agents
    api_registry = api_agents
    api_memory = api_agents
    api_task_logs = api_agents
    api_task_start = api_agents
    api_task_tick = api_agents
    api_task_finish = api_agents
    api_task_cancel = api_agents
    api_task_heartbeat = api_agents
    api_task_approval = api_agents


async def smoke_webui_server() -> None:
    server = StandaloneWebUIServer(
        owner=FakeWebOwner(),
        static_dir=ROOT / "webui",
        host="127.0.0.1",
        port=8788,
        token="secret",
    )
    client = server.app.test_client()
    denied = await client.get("/api/state")
    ok = await client.get("/api/state", headers={"X-Agent-Lab-Token": "secret"})
    page = await client.get("/")
    assert denied.status_code == 401
    assert ok.status_code == 200
    assert page.status_code == 200


def main() -> None:
    asyncio.run(smoke_webui_server())

    base_spec = AgentSpec()
    assert base_spec.name == ""
    assert base_spec.identity_label_source == "astrbot_runtime"

    modules = ModuleRegistry().list_modules()
    module_ids = {item["module_id"] for item in modules}
    assert "checkpoint_state" in module_ids
    assert "langgraph_checkpoint_adapter" in module_ids
    assert "openai_agents_guardrails_adapter" in module_ids

    with TemporaryDirectory() as tmp:
        registry = ModuleRegistry(Path(tmp))
        saved = registry.save_custom_module(
            {
                "module_id": "custom module!",
                "name": "Custom Module",
                "source": "smoke",
                "description": "custom module smoke",
                "prompt": "模块：Custom Module。",
                "links": ["https://example.com"],
                "capabilities": ["test"],
                "requires": ["checkpoint_state"],
            }
        )
        assert saved.module_id == "custom_module"
        assert registry.get("custom_module") is not None
        assert (Path(tmp) / "custom_module.json").exists()

    guard = SessionPluginGuard(protected_plugins={"astrbot_plugin_agent_lab"})
    protected = guard._protected_config(
        "test:private:1",
        {
            "test:private:1": {
                "enabled_plugins": [],
                "disabled_plugins": ["astrbot_plugin_agent_lab", "memory_noise"],
            }
        },
    )
    protected_session = protected["test:private:1"]
    assert "astrbot_plugin_agent_lab" in protected_session["enabled_plugins"]
    assert "astrbot_plugin_agent_lab" not in protected_session["disabled_plugins"]
    assert "memory_noise" in protected_session["disabled_plugins"]

    with TemporaryDirectory() as tmp:
        store = AgentLabStorage(Path(tmp))
        spec = store.ensure_defaults()
        assert "astrbot_execute_shell" in spec.enabled_tools
        assert spec.identity_label_source == "astrbot_runtime"
        assert isinstance(spec.tool_risk_overrides, dict)
        assert isinstance(spec.module_settings, dict)
        assert spec.workflow_nodes
        assert spec.workflow_edges
        assert store.default_agent_id() == spec.agent_id

        credential = store.save_credential(
            {"label": "Smoke Key", "provider": "test", "value": "secret-value"}
        )
        assert credential["has_value"]
        assert "encrypted_value" not in credential
        assert store.get_credential_secret(credential["credential_id"]) == "secret-value"
        assert store.list_credentials()[0]["masked_value"] == "********"
        custom_api = store.save_custom_api(
            {
                "name": "Smoke API",
                "method": "post",
                "url": "https://example.com/api",
                "credential_id": credential["credential_id"],
                "auth_type": "header",
                "auth_header": "X-Smoke-Key",
                "timeout_seconds": 5,
            }
        )
        assert custom_api["method"] == "POST"
        assert custom_api["auth_header"] == "X-Smoke-Key"
        assert store.get_custom_api(custom_api["api_id"])["name"] == "Smoke API"
        assert store.get_custom_api("Smoke API")["api_id"] == custom_api["api_id"]
        skill_rule = store.save_skill_rule(
            {"skill_name": "agent-mode", "content": "测试任务模式补充规则"}
        )
        assert skill_rule["content"] == "测试任务模式补充规则"
        assert store.get_skill_rule("agent-mode")["content"] == "测试任务模式补充规则"
        memory = store.save_memory_entry({"text": "Remember smoke test", "status": "candidate"})
        assert memory["memory_id"]

        second = spec.to_dict()
        second.pop("agent_id", None)
        second["name"] = "Second Agent"
        second_spec = type(spec).from_dict(second)
        store.save_agent(second_spec)
        assert store.get_agent().agent_id == spec.agent_id
        assert store.set_default_agent(second_spec.agent_id)
        assert store.get_agent().agent_id == second_spec.agent_id

        task = TaskState(
            agent_id=spec.agent_id,
            agent_name=spec.name,
            umo="test:private:1",
            root_goal="smoke test",
            completion_conditions=["archive works"],
        )
        task.add_log("test", "created")
        task.add_snapshot("test", {"ok": True})
        store.save_task(task)

        loaded = store.load_active_task("test:private:1")
        assert loaded is not None
        assert loaded.task_id == task.task_id
        active = store.list_tasks("test:private:1")
        assert len(active) == 1
        assert active[0].task_id == task.task_id

        archive = store.archive_task(loaded)
        assert archive.exists()
        assert not store.active_task_path("test:private:1").exists()
        assert store.list_tasks("test:private:1") == []
        archived = store.list_archives("test:private:1")
        assert len(archived) == 1
        assert archived[0].task_id == task.task_id

    print("Agent Lab smoke test passed.")


if __name__ == "__main__":
    main()
