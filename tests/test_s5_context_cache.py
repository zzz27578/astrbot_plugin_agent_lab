"""Scenario 5: 30-Turn Stress, 100KB Outputs, Prefix Cache & Handoff Compaction tests."""
from __future__ import annotations

import asyncio
import json

import pytest

from agent_lab.context_engine import (
    HANDOFF_MARKER,
    RECEIPT_MARKER,
    ContextCompactor,
    HandoffError,
    StageContextManager,
    build_static_system_prompt,
    estimate_tokens,
    prepare_wake_message,
)
from agent_lab.models import Profile, TaskStep
from tests.conftest import make_tool


def test_static_system_prompt_100pct_byte_identical_across_30_mutating_turns(lab_env):
    profile = lab_env.store.get_profile("default")
    persona_text = "[当前 Bot 人设：测试助手]\n严谨可靠。"
    host_skills = "[宿主可用技能]\n- code_audit: 审计代码"

    baseline = build_static_system_prompt(persona_text, profile, host_skills)
    assert baseline

    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:cache1", "30轮前缀缓存压测"))
    contexts: list[dict] = []

    for turn in range(1, 31):
        # Mutate project_summary, project_task_prompt, steps, guidance, current_step_id
        task.steps = [TaskStep(id=f"s{i}", title=f"步骤{i}", status="completed" if i < turn else "running") for i in range(1, 6)]
        task.current_step_id = f"s{min(5, turn)}"
        task.guidance.append({"time": f"t{turn}", "text": f"引导 {turn}"})
        task.input_revision += 1

        # Static system prompt MUST stay 100% byte-for-byte identical
        sp = build_static_system_prompt(persona_text, profile, host_skills)
        assert sp == baseline, f"System prompt mutated on turn {turn}"

        wake, _metric = prepare_wake_message(
            lab_env.store,
            task,
            contexts,
            project_summary=f"第 {turn} 轮变化的摘要内容",
            project_task_prompt=f"第 {turn} 轮变化的项目提示",
        )
        contexts.append({"role": "user", "content": wake})
        contexts.append({"role": "assistant", "content": f"turn {turn} ok"})


def test_prepare_wake_message_full_delta_steer_and_post_handoff_rebootstrap(lab_env):
    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:wake1", "增量唤醒测试"))
    task.steps = [TaskStep(id="s1", title="分析", status="running")]
    task.current_step_id = "s1"
    lab_env.store.save_task(task)

    # 1st wake: mode="full"
    contexts: list[dict] = []
    msg1, m1 = prepare_wake_message(lab_env.store, task, contexts)
    assert m1["mode"] == "full"
    assert task.goal in msg1
    contexts.append({"role": "user", "content": msg1})
    contexts.append({"role": "assistant", "content": "working..."})

    # 2nd wake with no change: tiny mode="delta" (< 220 chars)
    msg2, m2 = prepare_wake_message(lab_env.store, task, contexts)
    assert m2["mode"] == "delta"
    assert len(msg2) < 220, f"Empty delta wake too large ({len(msg2)} chars): {msg2!r}"
    assert task.goal not in msg2
    contexts.append({"role": "user", "content": msg2})
    contexts.append({"role": "assistant", "content": "still working..."})

    # 3rd wake after steer: only sends changed keys (guidance, input_revision)
    asyncio.run(lab_env.engine.steer(task.task_id, "请优先检查超时处理"))
    task = lab_env.store.find_task_by_id(task.task_id)
    msg3, m3 = prepare_wake_message(lab_env.store, task, contexts)
    assert m3["mode"] == "delta"
    payload3 = json.loads(msg3.split("]\n", 1)[1])
    assert set(payload3["changes"].keys()) == {"guidance", "input_revision"}

    # After handoff wipes wake markers -> cleanly re-bootstraps mode="full"
    handoff_contexts = [{"role": "user", "content": f"{HANDOFF_MARKER}\n阶段交接完成"}]
    msg4, m4 = prepare_wake_message(lab_env.store, task, handoff_contexts)
    assert m4["mode"] == "full"
    assert task.goal in msg4


def test_100kb_tool_output_redacted_saved_to_disk_truncated_and_history_unmutated(lab_env):
    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:bigout", "100KB输出截断测试"))
    task.phase = "executing"
    task.version = 1
    task.approved_version = 1
    task.session_workspace_root = str(lab_env.workspace)
    task.execution_cwd = str(lab_env.workspace)
    lab_env.store.save_task(task)

    big_lines = [f"line-{i:04d}: " + ("X" * 90) for i in range(1050)]  # > 100 KB
    raw_100kb = "\n".join(big_lines)
    assert len(raw_100kb.encode("utf-8")) > 100_000

    tool = make_tool("astrbot_file_read_tool", handler=lambda **kw: raw_100kb)
    existing_history = [{"role": "user", "content": "old message"}, {"role": "assistant", "content": "old reply"}]
    snapshot_before = json.dumps(existing_history)

    res = asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, {"path": "big.log"}, task.task_id))
    returned = res[0].content[0].text
    assert len(returned.encode("utf-8")) <= 15_360
    expected_bytes = len(raw_100kb.encode("utf-8"))
    expected_lines = len(raw_100kb.splitlines())
    assert f"{expected_bytes}B/{expected_lines}行" in returned
    assert "tool_results" in returned

    saved_files = list(lab_env.store.task_tool_results_dir(task.umo, task.task_id).glob("*.txt"))
    assert len(saved_files) == 1
    assert saved_files[0].read_text(encoding="utf-8") == raw_100kb
    assert json.dumps(existing_history) == snapshot_before


def test_context_compactor_and_stage_context_manager_invariants(lab_env):
    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:comp1", "压缩交接测试"))
    task.execution_settings.continuity.context_tokens = 4000
    task.execution_settings.continuity.context_percent = 50  # effective limit = 2000 tokens
    lab_env.store.save_task(task)

    compactor = ContextCompactor()

    # 1. Orphaned tool message must raise HandoffError
    with pytest.raises(HandoffError):
        asyncio.run(
            compactor.compact(
                lab_env.store,
                task,
                [{"role": "tool", "tool_call_id": "orphan_1", "content": "oops"}],
                provider=None,
                reason="token_limit",
                token_limit=2000,
            )
        )

    # 2. Build history with >= 8KB completed write call + thinking metadata + recent atomic tool group
    lab_env.store.append_event(
        task.umo,
        task.task_id,
        "journal",
        {"call_id": "call_big_write", "tool_name": "astrbot_file_write_tool", "status": "completed", "summary": "wrote module"},
    )
    lab_env.store.append_event(
        task.umo,
        task.task_id,
        "journal",
        {"call_id": "call_recent_read", "tool_name": "astrbot_file_read_tool", "status": "completed", "summary": "read file"},
    )

    big_content = "A" * 9500
    history = [
        {"role": "user", "content": "开始写大文件"},
        {
            "role": "assistant",
            "content": [{"type": "thinking", "text": "secret thoughts"}, {"type": "text", "text": "写入中"}],
            "reasoning": "internal chain",
            "thought_signature": "sig_123",
            "tool_calls": [
                {
                    "id": "call_big_write",
                    "type": "function",
                    "function": {
                        "name": "astrbot_file_write_tool",
                        "arguments": json.dumps({"path": "out.py", "content": big_content}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_big_write", "content": "wrote out.py successfully"},
        {"role": "user", "content": "再读一下配置"},
        {
            "role": "assistant",
            "content": "读取中",
            "tool_calls": [
                {
                    "id": "call_recent_read",
                    "type": "function",
                    "function": {"name": "astrbot_file_read_tool", "arguments": '{"path": "cfg.py"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_recent_read", "content": "TIMEOUT = 30"},
    ]
    history_snapshot = json.dumps(history, ensure_ascii=False)

    captured_prompts: list[str] = []

    class MockSummarizerProvider:
        async def text_chat(self, *, prompt: str, system_prompt: str, contexts: list, **kwargs):
            captured_prompts.append(prompt)
            return "已完成 out.py 写入并读取 cfg.py（TIMEOUT=30）。"

    scm = StageContextManager(
        lab_env.store,
        task,
        MockSummarizerProvider(),
        compactor=compactor,
        static_system_prompt="STATIC",
        tool_schemas=[],
        prompt_tokens=50,
    )

    # Trigger compaction via StageContextManager.process
    compacted = asyncio.run(scm.process(history, trusted_token_usage=2500))

    # Original working history was NEVER mutated
    assert json.dumps(history, ensure_ascii=False) == history_snapshot

    # Verbatim archive exists BEFORE reduction and holds all 6 original messages
    handoff_files = list(lab_env.store.task_handoffs_dir(task.umo, task.task_id).glob("*.json"))
    assert len(handoff_files) == 1
    archived = json.loads(handoff_files[0].read_text(encoding="utf-8"))
    assert archived["message_count"] == len(history)
    assert len(archived["messages"]) == len(history)

    # Summarizer received folded RECEIPT_MARKER and stripped thinking/signature metadata
    assert len(captured_prompts) == 1
    assert RECEIPT_MARKER in captured_prompts[0]
    assert "secret thoughts" not in captured_prompts[0]
    assert "sig_123" not in captured_prompts[0]
    assert "reasoning" not in captured_prompts[0]

    # Compacted output starts with HANDOFF_MARKER, preserves atomic tool groups, and is strictly < token_limit
    assert HANDOFF_MARKER in compacted[0]["content"]
    assert scm.count_tokens(compacted) < scm._effective_limit(task)

    # Secondary process() call must NOT trigger immediate secondary compaction loop!
    second_pass = asyncio.run(scm.process(compacted, trusted_token_usage=0))
    assert second_pass == compacted


def test_meta_json_stays_under_8kb_after_50_events(lab_env):
    task = asyncio.run(lab_env.engine.start_task("aiocqhttp:FriendMessage:meta_sz", "meta.json体积测试"))
    for i in range(55):
        lab_env.store.append_event(
            task.umo,
            task.task_id,
            "journal" if i % 3 == 0 else ("usage" if i % 3 == 1 else "log"),
            {"seq": i, "call_id": f"c_{i}", "payload": "x" * 500, "status": "completed"},
        )
    meta_path = lab_env.store.task_meta_path(task.umo, task.task_id)
    assert meta_path.stat().st_size < 8192
    events_path = lab_env.store.task_events_path(task.umo, task.task_id)
    assert len(events_path.read_text(encoding="utf-8").splitlines()) >= 55
