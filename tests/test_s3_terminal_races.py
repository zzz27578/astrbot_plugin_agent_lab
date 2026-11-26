"""Scenario 3: Admin Stop / Deliver Concurrent Race Conditions & Terminal Fence tests."""
from __future__ import annotations

import asyncio

import pytest

from agent_lab.bridge import ExecutionStopped
from agent_lab.guards import parse_admin_shortcut
from tests.conftest import make_tool


def _setup_running_task(lab_env, goal: str = "长任务并发竞争测试"):
    umo = "aiocqhttp:FriendMessage:race_admin"
    task = asyncio.run(lab_env.engine.start_task(umo, goal))
    task.phase = "executing"
    task.version = 1
    task.approved_version = 1
    task.session_workspace_root = str(lab_env.workspace)
    task.execution_cwd = str(lab_env.workspace)
    lab_env.store.save_task(task)
    # Create a pending approval too, to verify resolve_approval cannot resurrect ended task
    stale_snapshot = lab_env.store.find_task_by_id(task.task_id)
    return umo, task, stale_snapshot


def test_stop_terminal_fence_blocks_all_late_runner_callbacks(lab_env):
    umo, task, stale_snapshot = _setup_running_task(lab_env)

    # Admin calls stop()
    stop_res = asyncio.run(lab_env.engine.stop(task.task_id, reason="管理员强制终止"))
    assert stop_res["ok"] is True
    assert stop_res["status"] == "cancelled"

    # Terminal fence ended/<task_id>.json must be written immediately
    ended_file = lab_env.store.ended_path(task.task_id)
    assert ended_file.exists()
    assert lab_env.store.is_ended(task.task_id) is True
    assert lab_env.store.load_active_task(umo) is None

    # Stale runner attempts late mutations:
    # 1) store.save_task(stale_task)
    stale_snapshot.status = "running"
    stale_snapshot.phase = "executing"
    saved = lab_env.store.save_task(stale_snapshot, active=True)
    assert saved is False, "Late save_task must be rejected by terminal fence"

    # 2) store.append_event(...)
    ev = lab_env.store.append_event(umo, task.task_id, "log", {"event": "late_runner_log"})
    assert ev is None, "Late append_event must no-op when ended"

    # 3) engine.resolve_approval(...)
    apr_res = asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))
    assert apr_res["ok"] is False

    # 4) engine.resume(...)
    res_res = asyncio.run(lab_env.engine.resume(task.task_id))
    assert res_res["ok"] is False

    # 5) bridge.invoke_tool(...)
    tool = make_tool("astrbot_file_read_tool", handler=lambda **kw: "late")
    with pytest.raises(ExecutionStopped):
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, {"path": "x.txt"}, task.task_id))

    # 6) engine.record_progress(...) (if called by main.py or runner)
    prog_res = asyncio.run(lab_env.engine.record_progress(task.task_id, "late progress"))
    assert prog_res.get("ok") is False

    # Verify status never resurrected and active_task.json was never reclaimed
    final = lab_env.store.find_task_by_id(task.task_id)
    assert final.status == "cancelled"
    assert lab_env.store.load_active_task(umo) is None


def test_deliver_as_is_terminal_fence_blocks_all_late_callbacks(lab_env):
    umo, task, stale_snapshot = _setup_running_task(lab_env, goal="按现状交付竞争测试")

    deliver_res = asyncio.run(
        lab_env.engine.deliver_as_is(task.task_id, note="阶段成果已足够，按现状交付")
    )
    assert deliver_res["ok"] is True
    assert deliver_res["status"] == "completed"

    assert lab_env.store.ended_path(task.task_id).exists()
    assert lab_env.store.load_active_task(umo) is None

    # Stale runner late callbacks
    stale_snapshot.status = "running"
    assert lab_env.store.save_task(stale_snapshot, active=True) is False
    assert lab_env.store.append_event(umo, task.task_id, "journal", {"call_id": "c1", "status": "completed"}) is None
    assert asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))["ok"] is False
    assert asyncio.run(lab_env.engine.resume(task.task_id))["ok"] is False

    tool = make_tool("astrbot_file_read_tool", handler=lambda **kw: "late")
    with pytest.raises(ExecutionStopped):
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, {"path": "x.txt"}, task.task_id))

    final = lab_env.store.find_task_by_id(task.task_id)
    assert final.status == "completed"
    assert lab_env.store.load_active_task(umo) is None


def test_parse_admin_shortcut_positives_and_non_false_positives():
    assert parse_admin_shortcut("停止任务") == ("stop", "")
    assert parse_admin_shortcut("结束任务") == ("stop", "")
    assert parse_admin_shortcut("停止当前任务！") == ("stop", "")
    assert parse_admin_shortcut("按现状交付") == ("deliver", "")
    assert parse_admin_shortcut("批准") == ("approve", "")
    assert parse_admin_shortcut("拒绝 不行") == ("reject", "不行")
    assert parse_admin_shortcut("拒绝：太危险") == ("reject", "太危险")
    assert parse_admin_shortcut("暂停任务") == ("pause", "")
    assert parse_admin_shortcut("继续任务") == ("resume", "")
    assert parse_admin_shortcut("任务状态") == ("status", "")

    # Questions and quoted strings must NEVER be intercepted
    non_shortcuts = [
        "要停止任务吗？",
        "停止任务?",
        '"停止任务"',
        "“停止任务”",
        "他说停止任务",
        "他说“停止任务”",
        "‘批准’",
        "「按现状交付」",
        "我们可以按现状交付吗？",
    ]
    for text in non_shortcuts:
        assert parse_admin_shortcut(text) is None, f"Falsely intercepted: {text!r}"
