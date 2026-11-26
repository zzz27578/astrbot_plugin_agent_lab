"""Scenario 1: Daily Chat Zero-Pollution & Hidden Toolbox adversarial tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import main as plugin_main
from agent_lab.permissions import CONTROL_TOOL_NAMES, DAILY_TOOL_NAMES
from tests.conftest import FakeContext, make_event, make_provider_request

ALL_SEVEN_PLUGIN_TOOLS = list(DAILY_TOOL_NAMES) + list(CONTROL_TOOL_NAMES)
HOST_TOOLS = ["web_search", "calculator", "astrbot_file_read_tool"]


def _build_plugin(tmp_path: Path, monkeypatch, *, config: dict | None = None):
    data_dir = tmp_path / "plugin_data"
    monkeypatch.setattr(plugin_main, "_data_dir", lambda: data_dir)
    ctx = FakeContext(workspace_root=tmp_path / "ws")
    cfg = {
        "standalone_webui_enabled": False,
        "cleanup_legacy_global_skill": True,
        "inject_daily_hint": True,
        "private_only": True,
        "admin_only": True,
        **(config or {}),
    }
    plugin = plugin_main.AgentLabPlugin(ctx, cfg)
    return plugin, ctx, data_dir


def test_idle_admin_private_chat_exposes_only_start_tool_and_tiny_hint(tmp_path: Path, monkeypatch):
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    asyncio.run(plugin.initialize())

    ev = make_event(private=True, admin=True)
    base_prompt = "You are a helpful daily assistant."
    req = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt=base_prompt)

    asyncio.run(plugin.daily_toolbox_gate(ev, req))

    remaining = [t.name for t in req.func_tool.tools]
    assert "agent_lab_start_task" in remaining
    assert "agent_lab_control_task" not in remaining
    for ctrl in CONTROL_TOOL_NAMES:
        assert ctrl not in remaining
    for host in HOST_TOOLS:
        assert host in remaining

    appended = req.system_prompt[len(base_prompt):]
    assert 0 < len(appended) < 80, f"Daily hint too long ({len(appended)} chars): {appended!r}"


def test_no_global_skill_installed_and_legacy_agent_mode_deactivated(tmp_path: Path, monkeypatch):
    skills_root = tmp_path / "astrbot_skills"
    legacy_dir = skills_root / "agent-mode"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "SKILL.md").write_text(
        "---\nname: agent-mode\ndescription: Agent Lab legacy mode\n---\n# Agent Lab\n",
        encoding="utf-8",
    )

    deactivated: list[tuple[str, bool]] = []
    installed: list[str] = []

    class FakeSkillManager:
        def set_skill_active(self, name: str, active: bool) -> None:
            deactivated.append((name, active))

        def install_skill_from_zip(self, *args, **kwargs) -> None:
            installed.append(str(args))

    import astrbot.core.skills.skill_manager as sm_mod
    import astrbot.core.utils.astrbot_path as ap_mod

    monkeypatch.setattr(ap_mod, "get_astrbot_skills_path", lambda: str(skills_root))
    monkeypatch.setattr(sm_mod, "SkillManager", FakeSkillManager)

    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    asyncio.run(plugin.initialize())

    assert installed == [], "v1.0.0 must NEVER install any global skill"
    assert ("agent-mode", False) in deactivated, "Legacy agent-mode global skill must be deactivated"
    # Verify no new skill directories were created under skills_root
    assert [p.name for p in skills_root.iterdir()] == ["agent-mode"]


def test_active_task_dynamically_exposes_control_tool_and_hides_after_stop_or_finish(
    tmp_path: Path, monkeypatch
):
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    ev = make_event(private=True, admin=True, session_id="adm_active")

    # Start a task (no event passed to avoid spawning background LLM loop)
    task = asyncio.run(plugin.engine.start_task(ev.unified_msg_origin, "分析仓库并修复问题"))

    req_active = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt="BASE")
    asyncio.run(plugin.daily_toolbox_gate(ev, req_active))
    names_active = [t.name for t in req_active.func_tool.tools]
    assert "agent_lab_start_task" in names_active
    assert "agent_lab_control_task" in names_active
    for ctrl in CONTROL_TOOL_NAMES:
        assert ctrl not in names_active

    # Stop task -> next daily turn must immediately hide agent_lab_control_task
    asyncio.run(plugin.engine.stop(task.task_id, reason="测试停止"))
    req_after_stop = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt="BASE")
    asyncio.run(plugin.daily_toolbox_gate(ev, req_after_stop))
    names_after_stop = [t.name for t in req_after_stop.func_tool.tools]
    assert "agent_lab_start_task" in names_after_stop
    assert "agent_lab_control_task" not in names_after_stop

    # Start another task and finish_task() -> also immediately hides agent_lab_control_task
    task2 = asyncio.run(plugin.engine.start_task(ev.unified_msg_origin, "只读审计项目"))
    res = asyncio.run(
        plugin.engine.finish_task(
            task2.task_id,
            "已完成只读审计，确认全部模块结构正常且无待办风险。",
        )
    )
    assert res["ok"] is True
    req_after_finish = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt="BASE")
    asyncio.run(plugin.daily_toolbox_gate(ev, req_after_finish))
    names_after_finish = [t.name for t in req_after_finish.func_tool.tools]
    assert "agent_lab_control_task" not in names_after_finish


def test_non_admin_and_group_chat_strip_all_seven_tools_and_zero_prompt_injection(
    tmp_path: Path, monkeypatch
):
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)

    # Even if an active task exists in some other way, non-admin / group must see 0 plugin tools
    scenarios = [
        make_event(private=True, admin=False, session_id="non_admin_user"),
        make_event(private=False, admin=True, session_id="group_123"),
        make_event(private=False, admin=False, session_id="group_456"),
    ]
    for ev in scenarios:
        base = "GROUP_OR_NON_ADMIN_PROMPT"
        req = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt=base)
        asyncio.run(plugin.daily_toolbox_gate(ev, req))
        remaining = [t.name for t in req.func_tool.tools]
        for pname in ALL_SEVEN_PLUGIN_TOOLS:
            assert pname not in remaining, f"{pname} leaked to non-admin/group chat"
        for host in HOST_TOOLS:
            assert host in remaining
        assert req.system_prompt == base


def test_isolated_task_runtime_bypasses_daily_gate_without_mutating_request(
    tmp_path: Path, monkeypatch
):
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    ev = make_event(private=True, admin=True, runtime_task_id="task_deadbeef1234")
    base = "STATIC_TASK_SYSTEM_PROMPT"
    req = make_provider_request(ALL_SEVEN_PLUGIN_TOOLS + HOST_TOOLS, system_prompt=base)
    before_names = [t.name for t in req.func_tool.tools]

    asyncio.run(plugin.daily_toolbox_gate(ev, req))

    assert [t.name for t in req.func_tool.tools] == before_names
    assert req.system_prompt == base


# ── Adversarial Wiring Checks on main.py ────────────────────────────────────


def test_adversarial_plugin_terminate_closes_engine_cleanly(tmp_path: Path, monkeypatch):
    """Plugin.terminate() must not crash on missing TaskEngine method (stop_all vs close)."""
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    asyncio.run(plugin.initialize())
    asyncio.run(plugin.terminate())


def test_adversarial_initialize_with_interrupted_task_logs_without_typeerror(
    tmp_path: Path, monkeypatch, caplog
):
    """initialize() when recover_on_startup recovers a task must not crash on %d formatting a dict."""
    import logging

    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    # Create an interrupted running task before initialize()
    asyncio.run(plugin.engine.start_task("aiocqhttp:FriendMessage:u1", "interrupted task"))

    # Now simulate restart -> initialize() calls recover_on_startup() with INFO logging enabled
    plugin2, _ctx2, _ = _build_plugin(tmp_path, monkeypatch)
    with caplog.at_level(logging.INFO, logger="astrbot_plugin_agent_lab"):
        asyncio.run(plugin2.initialize())
    for rec in caplog.records:
        # Formatting log record as production AstrBot handler does
        rec.getMessage()


def test_adversarial_control_tool_pause_action_wiring(tmp_path: Path, monkeypatch):
    """Calling agent_lab_control_task(action='pause') must not crash with unexpected kwarg 'human'."""
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    ev = make_event(private=True, admin=True, session_id="adm_pause")
    asyncio.run(plugin.engine.start_task(ev.unified_msg_origin, "test pause wiring"))

    out = asyncio.run(plugin.agent_lab_control_task(ev, action="pause", payload="休息一下"))
    assert '"ok": true' in out.lower()


def test_adversarial_main_internal_tools_wiring(tmp_path: Path, monkeypatch):
    """Calling main.py's task_progress / task_ask / task_approve with runtime extra must not crash."""
    plugin, _ctx, _ = _build_plugin(tmp_path, monkeypatch)
    t = asyncio.run(plugin.engine.start_task("aiocqhttp:FriendMessage:adm_wire", "test wiring"))
    ev = make_event(private=True, admin=True, session_id="adm_wire", runtime_task_id=t.task_id)

    prog_res = asyncio.run(plugin.task_progress(ev, "step 1 ok"))
    assert '"ok": true' in prog_res.lower()

    ask_res = asyncio.run(plugin.task_ask(ev, "continue?", '["yes", "no"]', "yes"))
    assert '"ok": true' in ask_res.lower()

    apr_res = asyncio.run(
        plugin.task_approve(
            ev,
            "run_cmd",
            "need check",
            "low",
            '[{"tool_name": "astrbot_execute_shell", "arguments": {"command": "echo hi"}}]',
        )
    )
    assert '"ok": true' in apr_res.lower()
