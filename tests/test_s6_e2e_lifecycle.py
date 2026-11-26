"""Scenario 6: Full Two-Phase Blank-Task Lifecycle end-to-end tests."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_lab.bridge import OperationBlocked
from agent_lab.context_engine import TASK_CONTROL_TOOL_SCHEMAS
from tests.conftest import make_tool


def test_full_two_phase_blank_task_lifecycle(lab_env):
    umo = "aiocqhttp:FriendMessage:e2e_admin"
    proj = lab_env.store.save_project(
        {
            "title": "E2E Project",
            "source_umo": umo,
            "execution_settings": {
                "mode": "standard",
                "roots": [str(lab_env.workspace)],
            },
        },
        select_for_umo=umo,
    )

    # 1. Start blank task (NO event -> verify immediate initial state without blind propose() LLM call)
    task = asyncio.run(
        lab_env.engine.start_task(
            umo,
            "新增 calc.py 并通过 pytest 验证",
            project_id=proj.project_id,
            constraints=["不得修改 README.md"],
        )
    )
    assert task.phase == "planning"
    assert task.status == "running"
    assert task.version == 0
    assert task.approved_version == 0

    # Prepare mock workspace tools
    target_file = lab_env.workspace / "calc.py"
    target_file.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

    read_tool = make_tool(
        "astrbot_file_read_tool",
        handler=lambda path, **kw: Path(path).read_text(encoding="utf-8") if Path(path).is_absolute() else (lab_env.workspace / path).read_text(encoding="utf-8"),
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
    )
    write_tool = make_tool(
        "astrbot_file_write_tool",
        handler=lambda path, content, **kw: ((lab_env.workspace / path).write_text(content, encoding="utf-8"), "written")[1],
        parameters={"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}},
    )
    shell_tool = make_tool(
        "astrbot_execute_shell",
        handler=lambda command, **kw: f"ran: {command} -> 1 passed",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
    )
    lab_env.ctx.tool_manager.func_list = [read_tool, write_tool, shell_tool]

    # 2. In planning: read succeeds, write is denied (OperationBlocked)
    read_res = asyncio.run(
        lab_env.engine.bridge.invoke_tool(None, read_tool, {"path": "calc.py"}, task.task_id)
    )
    assert "def add" in read_res[0].content[0].text

    with pytest.raises(OperationBlocked):
        asyncio.run(
            lab_env.engine.bridge.invoke_tool(
                None, write_tool, {"path": "calc.py", "content": "x"}, task.task_id
            )
        )

    # 3. Model submits initial plan -> pauses with need_plan_approval
    plan1 = asyncio.run(
        lab_env.engine.submit_plan(
            task.task_id,
            [
                {"id": "s1", "title": "修改 calc.py"},
                {"id": "s2", "title": "运行测试验证"},
            ],
            summary="先读取后实现并测试",
        )
    )
    assert plan1["ok"] is True and plan1["needs_approval"] is True
    assert plan1["wait_reason"] == "need_plan_approval"

    # 4. Admin approves -> transitions to phase="executing", status="running"
    apr1 = asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))
    assert apr1["ok"] is True
    assert apr1["phase"] == "executing"
    assert apr1["status"] == "running"

    # 5. Routine submit_plan (splitting/checking steps) -> stays running, NO re-approval!
    routine = asyncio.run(
        lab_env.engine.submit_plan(
            task.task_id,
            [
                {"id": "s1a", "title": "修改 calc.py 函数", "status": "completed"},
                {"id": "s1b", "title": "补充边界处理", "status": "running"},
                {"id": "s2", "title": "运行测试验证", "status": "pending"},
            ],
            completed_step="s1a",
        )
    )
    assert routine["ok"] is True and routine["needs_approval"] is False
    t_after_routine = lab_env.store.find_task_by_id(task.task_id)
    assert t_after_routine.status == "running"

    # 6. Authority-expanding submit_plan -> pauses for re-approval!
    extra_dir = str(lab_env.tmp_path / "extra_root")
    exp = asyncio.run(
        lab_env.engine.submit_plan(
            task.task_id,
            [
                {"id": "s1a", "title": "修改 calc.py 函数", "status": "completed"},
                {"id": "s2", "title": "运行测试验证", "status": "pending"},
            ],
            goal="顺便重构 README.md 与外部目录",
            scope_roots=[extra_dir],
            remove_constraints=["不得修改 README.md"],
        )
    )
    assert exp["ok"] is True and exp["needs_approval"] is True
    assert exp["wait_reason"] == "need_plan_approval"

    # Approve authority expansion to continue executing
    apr2 = asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))
    assert apr2["status"] == "running"

    # 7. ask_question -> pauses (need_answer) -> answer_question -> resumes cleanly
    q_res = asyncio.run(
        lab_env.engine.ask_question(
            task.task_id,
            "除零时返回 None 还是抛 ValueError？",
            options=["抛 ValueError", "返回 None"],
            recommendation="抛 ValueError",
        )
    )
    assert q_res["ok"] is True and q_res["wait_reason"] == "need_answer"
    assert lab_env.store.find_task_by_id(task.task_id).status == "paused"

    a_res = asyncio.run(lab_env.engine.answer_question(task.task_id, "抛 ValueError"))
    assert a_res["ok"] is True and a_res["status"] == "running"

    # 8. Write calc.py and mark steps completed
    asyncio.run(
        lab_env.engine.bridge.invoke_tool(
            None,
            write_tool,
            {"path": "calc.py", "content": "def add(a, b):\n    return a + b\n\ndef div(a, b):\n    if b == 0:\n        raise ValueError('zero')\n    return a / b\n"},
            task.task_id,
        )
    )
    asyncio.run(
        lab_env.engine.submit_plan(
            task.task_id,
            [
                {"id": "s1a", "title": "修改 calc.py 函数", "status": "completed"},
                {"id": "s2", "title": "运行测试验证", "status": "completed"},
            ],
        )
    )

    # finish_task without verification after write -> rejected!
    bad_finish1 = asyncio.run(
        lab_env.engine.finish_task(task.task_id, "已完成 calc.py 的全部开发工作。")
    )
    assert bad_finish1["ok"] is False and bad_finish1["gaps"]

    # Run passing test command (in standard mode CODE_TOOLS default_risk=high, so approve once or set tool_risk_overrides;
    # test tool_batch approval -> execute shell test -> verify)
    asyncio.run(
        lab_env.engine.request_approval(
            task.task_id,
            operation="运行 pytest",
            reason="验证修改",
            calls=[{"tool_name": "astrbot_execute_shell", "arguments": {"command": "pytest -q"}}],
        )
    )
    asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))
    fresh_t = lab_env.store.find_task_by_id(task.task_id)
    receipts = asyncio.run(lab_env.engine.bridge.resume_approved_batch(None, fresh_t))
    assert receipts and receipts[0]["ok"] is True

    # finish_task omitting written filename -> rejected!
    bad_finish2 = asyncio.run(
        lab_env.engine.finish_task(task.task_id, "已经通过 pytest -q 测试验证，一切正常。")
    )
    assert bad_finish2["ok"] is False
    assert any("calc.py" in g for g in bad_finish2["gaps"])

    # finish_task mentioning calc.py after verification -> succeeds, writes terminal fence & SUMMARY.md!
    good_finish = asyncio.run(
        lab_env.engine.finish_task(
            task.task_id,
            "已更新 calc.py 增加 div 并通过 pytest -q 全部验证。",
        )
    )
    assert good_finish["ok"] is True
    assert good_finish["status"] == "completed"
    assert lab_env.store.is_ended(task.task_id) is True
    assert "calc.py" in lab_env.store.read_project_summary(proj.project_id)


def test_adversarial_task_approve_schema_vs_bridge_dispatch(lab_env):
    """If the LLM calls task_approve using TASK_CONTROL_TOOL_SCHEMAS (no 'calls' field),
    bridge._dispatch_control_tool should handle it instead of crashing with ValueError."""
    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:adm_disp", "审批分发测试"))
    task.phase = "executing"
    task.version = 1
    task.approved_version = 1
    lab_env.store.save_task(task)

    # Check schema properties vs bridge dispatch
    schema_props = TASK_CONTROL_TOOL_SCHEMAS["task_approve"]["parameters"]["properties"]
    assert "calls" not in schema_props  # schema doesn't expose calls

    tool = make_tool("task_approve")
    # Model calls task_approve strictly conforming to TASK_CONTROL_TOOL_SCHEMAS
    res = asyncio.run(
        lab_env.engine.bridge.invoke_tool(
            None,
            tool,
            {
                "operation": "astrbot_execute_shell",
                "reason": "需要运行集成测试",
                "impact": "仅读取并测试",
                "rollback": "无",
            },
            task.task_id,
        )
    )
    assert res and '"ok": true' in res[0].content[0].text.lower()


def test_adversarial_plain_function_tool_handler_in_fallback_mode(lab_env):
    """A standard AstrBot FunctionTool(handler=...) executed with event=None (fallback mode)
    must invoke .handler instead of crashing in FunctionTool.call()."""
    from astrbot.core.agent.tool import FunctionTool

    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:fb1", "fallback handler test"))
    task.phase = "executing"
    task.version = 1
    task.approved_version = 1
    lab_env.store.save_task(task)

    async def my_read(event, path: str = ""):
        return f"read:{path}"

    plain_tool = FunctionTool(
        name="astrbot_file_read_tool",
        description="read",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=my_read,
    )
    res = asyncio.run(
        lab_env.engine.bridge.invoke_tool(None, plain_tool, {"path": "a.txt"}, task.task_id)
    )
    assert res[0].content[0].text == "read:a.txt"
