"""Scenario 4: ProgressGuard Loops & Unknown Call Reconciliation tests."""
from __future__ import annotations

import asyncio

import pytest

from agent_lab.bridge import ExecutionStopped, OperationBlocked
from agent_lab.models import new_id
from tests.conftest import make_tool


def _make_exec_task(lab_env, *, mode: str = "full"):
    umo = "aiocqhttp:FriendMessage:loop_user"
    proj = lab_env.store.save_project(
        {
            "title": "Loop Test",
            "source_umo": umo,
            "execution_settings": {"mode": mode, "roots": [str(lab_env.workspace)]},
        },
        select_for_umo=umo,
    )
    task = asyncio.run(lab_env.engine.start_task(umo, "测试循环保护与超时对账", project_id=proj.project_id))
    task.phase = "executing"
    task.version = 1
    task.approved_version = 1
    task.session_workspace_root = str(lab_env.workspace)
    task.execution_cwd = str(lab_env.workspace)
    lab_env.store.save_task(task)
    return task


def test_consecutive_equivalent_errors_warn_at_3_pause_at_5_and_reset_on_success(lab_env):
    task = _make_exec_task(lab_env)
    call_idx = 0

    def flaky_tool(path: str):
        nonlocal call_idx
        call_idx += 1
        if call_idx <= 5:
            raise RuntimeError(f"File not found at line {call_idx}")
        return "ok now"

    tool = make_tool(
        "astrbot_file_read_tool",
        handler=flaky_tool,
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )

    for i in range(1, 6):
        res = asyncio.run(
            lab_env.engine.bridge.invoke_tool(None, tool, {"path": "missing.py"}, task.task_id)
        )
        txt = res[0].content[0].text
        if i in (3, 4):
            assert "[ProgressGuard 警告]" in txt, f"Expected warn at error #{i}, got: {txt}"
        elif i == 5:
            fresh = lab_env.store.find_task_by_id(task.task_id)
            assert fresh.status == "paused"
            assert fresh.wait_reason == "guard_paused"
            assert fresh.progress_guard_state["error_streak"] == 5

    # Resume and succeed -> resets error streak
    res_resume = asyncio.run(lab_env.engine.resume(task.task_id))
    assert res_resume["ok"] is True
    res_ok = asyncio.run(
        lab_env.engine.bridge.invoke_tool(None, tool, {"path": "missing.py"}, task.task_id)
    )
    assert "[ProgressGuard 警告]" not in res_ok[0].content[0].text
    fresh2 = lab_env.store.find_task_by_id(task.task_id)
    assert fresh2.progress_guard_state["error_streak"] == 0


def test_overlapping_readonly_calls_warn_then_pause_at_20_and_reset_after_write(lab_env):
    task = _make_exec_task(lab_env)
    target = str(lab_env.workspace / "big.py")

    read_tool = make_tool(
        "astrbot_file_read_tool",
        handler=lambda **kw: "line1\nline2\nline3\n",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer"},
                "end_line": {"type": "integer"},
            },
        },
    )
    write_tool = make_tool(
        "astrbot_file_write_tool",
        handler=lambda **kw: "written ok",
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
    )

    # 1..19 overlapping reads (>= 85% overlap: lines 1..100 vs 1..95)
    for i in range(1, 21):
        end_line = 100 if i % 2 == 1 else 95
        res = asyncio.run(
            lab_env.engine.bridge.invoke_tool(
                None,
                read_tool,
                {"path": target, "start_line": 1, "end_line": end_line},
                task.task_id,
            )
        )
        txt = res[0].content[0].text
        if 14 <= i < 20:
            assert "[ProgressGuard 警告]" in txt, f"Expected overlap warn at #{i}, got: {txt}"
        elif i == 20:
            fresh = lab_env.store.find_task_by_id(task.task_id)
            assert fresh.status == "paused"
            assert fresh.wait_reason == "guard_paused"
            assert fresh.progress_guard_state["overlap_streak"] == 20

    # Resume and execute a successful write -> resets read stagnation counters
    asyncio.run(lab_env.engine.resume(task.task_id))
    asyncio.run(
        lab_env.engine.bridge.invoke_tool(
            None, write_tool, {"path": target, "content": "updated"}, task.task_id
        )
    )
    after_write = lab_env.store.find_task_by_id(task.task_id)
    assert after_write.progress_guard_state["overlap_streak"] == 0
    assert after_write.progress_guard_state["same_target_streak"] == 0
    assert after_write.progress_guard_state["read_streak"] == 0


def test_timeout_marks_unknown_blocks_subsequent_calls_and_reconciles_cleanly(lab_env, monkeypatch):
    task = _make_exec_task(lab_env)
    lab_env.engine.config["tool_call_timeout_seconds"] = 0.05

    async def slow_shell(command: str):
        await asyncio.sleep(2.0)
        return "never finishes"

    shell_tool = make_tool(
        "astrbot_execute_shell",
        handler=slow_shell,
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
    )

    with pytest.raises(ExecutionStopped):
        asyncio.run(
            lab_env.engine.bridge.invoke_tool(
                None, shell_tool, {"command": "pytest"}, task.task_id
            )
        )

    fresh = lab_env.store.find_task_by_id(task.task_id)
    assert fresh.status == "paused"
    assert fresh.wait_reason == "unknown_call"

    journal = lab_env.store.latest_journal_by_call(fresh.umo, fresh.task_id)
    unknowns = [j for j in journal if j.get("status") == "unknown"]
    assert len(unknowns) == 1
    call_id = unknowns[0]["call_id"]

    # Subsequent tool invocation must be blocked (paused fence AND unresolved journal check)
    write_tool = make_tool("astrbot_file_write_tool", handler=lambda **kw: "should not run")
    with pytest.raises(ExecutionStopped):
        asyncio.run(
            lab_env.engine.bridge.invoke_tool(
                None, write_tool, {"path": "a.txt", "content": "x"}, task.task_id
            )
        )

    # Cannot resume while unknown call remains unreconciled
    bad_resume = asyncio.run(lab_env.engine.resume(task.task_id))
    assert bad_resume["ok"] is False

    # Even if status were forced running, invoke_tool's journal guard blocks non-readonly calls
    fresh.status = "running"
    lab_env.store.save_task(fresh)
    with pytest.raises(OperationBlocked):
        asyncio.run(
            lab_env.engine.bridge.invoke_tool(
                None, write_tool, {"path": "a.txt", "content": "x"}, task.task_id
            )
        )
    fresh.status = "paused"
    fresh.wait_reason = "unknown_call"
    lab_env.store.save_task(fresh)

    # Reconcile clears the block cleanly
    rec = asyncio.run(
        lab_env.engine.reconcile_unknown_call(task.task_id, call_id, "completed", "已人工确认")
    )
    assert rec["ok"] is True
    assert rec["remaining_unknown"] == 0
    assert rec["task_status"] == "running"
    assert rec["wait_reason"] == ""


def test_recover_on_startup_marks_dangling_started_as_unknown_and_pauses(lab_env):
    task = _make_exec_task(lab_env)
    cid = new_id("call")
    lab_env.store.append_event(
        task.umo,
        task.task_id,
        "journal",
        {"call_id": cid, "tool_name": "astrbot_execute_shell", "status": "started"},
    )

    stats = lab_env.engine.recover_on_startup()
    assert stats["unknown_marked"] == 1
    assert stats["paused"] == 1

    recovered = lab_env.store.find_task_by_id(task.task_id)
    assert recovered.status == "paused"
    assert recovered.human_paused is True

    journal = lab_env.store.latest_journal_by_call(recovered.umo, recovered.task_id)
    entry = next(j for j in journal if j.get("call_id") == cid)
    assert entry["status"] == "unknown"
    assert entry.get("recovered") is True
