from __future__ import annotations

import asyncio
import importlib
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
    func_list = []


class FakeContext:
    def __init__(self) -> None:
        self.web_apis = []
        self.cron_manager = FakeCronManager()
        self.conversation_manager = FakeConversationManager()

    def register_web_api(self, route, handler, methods, desc) -> None:
        self.web_apis.append((route, methods, desc))

    def get_config(self):
        return {}

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
                activated=True,
                reserved=False,
                desc="test memory plugin",
            ),
        ]

    def get_llm_tool_manager(self):
        return FakeToolManager()

    async def get_current_chat_provider_id(self, umo: str):
        raise RuntimeError("no provider in runtime smoke")

    async def llm_generate(self, **kwargs):
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
        assert task.profile_snapshot["agent"]["name"]

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

        heartbeat = await plugin._enable_heartbeat(event, task, "runtime_smoke")
        assert "已开启心跳" in heartbeat
        task = plugin.storage.load_active_task(event.unified_msg_origin)
        assert task is not None
        assert task.heartbeat.enabled
        assert task.heartbeat.job_id

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

    print("Agent Lab runtime smoke test passed.")


if __name__ == "__main__":
    asyncio.run(main())
