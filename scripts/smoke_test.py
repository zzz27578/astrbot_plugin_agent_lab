from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agent_lab import AgentLabStorage
from agent_lab.models import TaskState
from agent_lab.modules import ModuleRegistry
from agent_lab.session_guard import SessionPluginGuard


def main() -> None:
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
        assert store.default_agent_id() == spec.agent_id

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
