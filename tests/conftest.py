"""Shared fixtures and AstrBot test doubles for Agent Lab v1.0.0 red-team tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from astrbot.api.event import AstrMessageEvent
from astrbot.api.provider import ProviderRequest
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata

from agent_lab.engine import TaskEngine
from agent_lab.store import AgentLabStore


class FakeContext:
    """Minimal AstrBot Context stub supporting messaging, tools, providers, and conversations."""

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.sent_messages: list[tuple[str, Any]] = []
        self.web_apis: list[tuple[str, Any]] = []
        self.workspace_root = str(workspace_root) if workspace_root else ""
        self.tool_manager = SimpleNamespace(
            func_list=[],
            get_full_tool_set=lambda: ToolSet(list(self.tool_manager.func_list)),
        )
        self.providers: dict[str, Any] = {}
        self.default_provider_id = "mock-provider"
        self.conversations: dict[tuple[str, str], SimpleNamespace] = {}
        self.conversation_manager = self._ConvMgr(self)
        self.persona_manager = None
        self.skill_manager = None

    class _ConvMgr:
        def __init__(self, outer: FakeContext) -> None:
            self.outer = outer
            self.db = self

        async def get_conversation(
            self, umo: str, cid: str, create_if_not_exists: bool = True
        ) -> Any:
            conv = self.outer.conversations.get((umo, cid))
            if conv is None and create_if_not_exists:
                conv = SimpleNamespace(cid=cid, history="[]", token_usage=0)
                self.outer.conversations[(umo, cid)] = conv
            return conv

        async def create_conversation(
            self,
            *,
            user_id: str,
            platform_id: str,
            content: list[Any],
            title: str = "",
            cid: str = "",
        ) -> Any:
            conv = SimpleNamespace(
                cid=cid,
                user_id=user_id,
                platform_id=platform_id,
                title=title,
                history=json.dumps(content, ensure_ascii=False),
                token_usage=0,
            )
            self.outer.conversations[(user_id, cid)] = conv
            return conv

        async def update_conversation(
            self,
            umo: str,
            cid: str,
            *,
            history: list[Any] | None = None,
            token_usage: int | None = None,
        ) -> None:
            conv = self.outer.conversations.get((umo, cid))
            if conv is None:
                conv = SimpleNamespace(cid=cid, history="[]", token_usage=0)
                self.outer.conversations[(umo, cid)] = conv
            if history is not None:
                conv.history = json.dumps(history, ensure_ascii=False)
            if token_usage is not None:
                conv.token_usage = token_usage

    async def send_message(self, umo: str, chain: Any) -> bool:
        self.sent_messages.append((umo, chain))
        return True

    def get_config(self, umo: str = "") -> dict[str, Any]:
        return {"provider_settings": {"computer_use_runtime": "none"}}

    def get_llm_tool_manager(self) -> Any:
        return self.tool_manager

    def register_web_api(self, *args: Any, **kwargs: Any) -> None:
        self.web_apis.append((str(args[0]) if args else "", kwargs))

    async def get_current_chat_provider_id(self, umo: str) -> str:
        return self.default_provider_id

    def get_provider_by_id(self, provider_id: str) -> Any:
        return self.providers.get(provider_id)

    def get_all_stars(self) -> list[Any]:
        return []


def make_event(
    *,
    message_str: str = "你好",
    private: bool = True,
    admin: bool = True,
    session_id: str = "admin_1",
    platform_id: str = "aiocqhttp",
    runtime_task_id: str = "",
) -> AstrMessageEvent:
    msg = AstrBotMessage()
    msg.self_id = "bot_main"
    msg.session_id = session_id
    msg.type = MessageType.FRIEND_MESSAGE if private else MessageType.GROUP_MESSAGE
    msg.sender = MessageMember(user_id=session_id, nickname="Tester")
    msg.message_id = "msg_1"
    msg.message_str = message_str
    msg.message = []

    ev = AstrMessageEvent(
        message_str=message_str,
        message_obj=msg,
        platform_meta=PlatformMetadata(name=platform_id, description="test", id=platform_id),
        session_id=session_id,
    )
    ev.role = "admin" if admin else "member"
    if runtime_task_id:
        ev.set_extra("agent_lab_runtime", runtime_task_id)
    return ev


class _TestFunctionTool(FunctionTool):
    """FunctionTool subclass implementing .call() so AstrBot FunctionToolExecutor and fallback both work."""

    async def call(self, context: Any, **kwargs: Any) -> Any:
        if callable(self.handler):
            event = getattr(getattr(context, "context", None), "event", None)
            res = self.handler(event, **kwargs)
            import inspect as _inspect

            if _inspect.isawaitable(res):
                return await res
            return res
        raise NotImplementedError(f"Tool {self.name} has no handler")


def make_tool(
    name: str,
    handler: Any = None,
    *,
    description: str = "",
    parameters: dict[str, Any] | None = None,
    active: bool = True,
) -> FunctionTool:
    wrapped = None
    if handler is not None:
        import inspect as _inspect

        async def _astr_handler(event: Any = None, **kwargs: Any) -> Any:
            try:
                sig = _inspect.signature(handler)
                params = sig.parameters
                if "event" in params:
                    res = handler(event, **kwargs)
                else:
                    res = handler(**kwargs)
            except (TypeError, ValueError):
                res = handler(**kwargs)
            if _inspect.isawaitable(res):
                return await res
            return res

        wrapped = _astr_handler

    return _TestFunctionTool(
        name=name,
        description=description or f"mock tool {name}",
        parameters=parameters or {"type": "object", "properties": {}},
        handler=wrapped,
        active=active,
    )


def make_toolset(names: list[str]) -> ToolSet:
    return ToolSet([make_tool(n) for n in names])


def make_provider_request(
    tool_names: list[str],
    *,
    system_prompt: str = "BASE_SYSTEM_PROMPT",
    prompt: str = "hi",
) -> ProviderRequest:
    return ProviderRequest(
        prompt=prompt,
        system_prompt=system_prompt,
        func_tool=make_toolset(tool_names),
    )


@pytest.fixture
def lab_env(tmp_path: Path):
    """Isolated AgentLabStore + FakeContext + TaskEngine + workspace dir."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    storage = tmp_path / "agent_lab_data"
    store = AgentLabStore(storage)
    ctx = FakeContext(workspace_root=workspace)
    engine = TaskEngine(store, context=ctx, config={"max_concurrent_tasks": 2})
    return SimpleNamespace(
        tmp_path=tmp_path,
        workspace=workspace,
        storage=storage,
        store=store,
        ctx=ctx,
        engine=engine,
    )
