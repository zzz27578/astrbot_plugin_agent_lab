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


def main() -> None:
    modules = ModuleRegistry().list_modules()
    module_ids = {item["module_id"] for item in modules}
    assert "checkpoint_state" in module_ids
    assert "langgraph_checkpoint_adapter" in module_ids
    assert "openai_agents_guardrails_adapter" in module_ids

    with TemporaryDirectory() as tmp:
        store = AgentLabStorage(Path(tmp))
        spec = store.ensure_defaults()
        assert "astrbot_execute_shell" in spec.enabled_tools

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

        archive = store.archive_task(loaded)
        assert archive.exists()
        assert not store.active_task_path("test:private:1").exists()
        archived = store.list_archives("test:private:1")
        assert len(archived) == 1
        assert archived[0].task_id == task.task_id

    print("Agent Lab smoke test passed.")


if __name__ == "__main__":
    main()
