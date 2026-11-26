"""Scenario 2: Security, Permissions, Vault Zero-Exposure & No Double-Approval tests."""
from __future__ import annotations

import asyncio
import base64
import json
import os
import urllib.parse
from pathlib import Path

import pytest

from agent_lab.bridge import OperationBlocked
from agent_lab.context_engine import prepare_wake_message
from agent_lab.models import Profile, TaskMeta
from agent_lab.permissions import (
    CODE_TOOLS,
    READ_TOOLS,
    WRITE_TOOLS,
    assess_call,
    is_credential_exfiltration,
)
from tests.conftest import make_tool


def _make_task(workspace: Path, *, mode: str = "standard", phase: str = "executing") -> TaskMeta:
    t = TaskMeta(
        task_id="task_aabbccddeeff",
        umo="aiocqhttp:FriendMessage:sec1",
        project_id="proj_sec1",
        profile_id="default",
        goal="security test",
        status="running",
        phase=phase,
        version=1,
        approved_version=1 if phase == "executing" else 0,
        session_workspace_root=str(workspace),
        execution_cwd=str(workspace),
        scope_roots=[str(workspace)],
        authorized_scope_roots=[str(workspace)],
    )
    t.execution_settings.mode = mode
    t.execution_settings.roots = [str(workspace)]
    return t


def test_outside_workspace_paths_require_review(lab_env):
    task = _make_task(lab_env.workspace, mode="standard", phase="executing")

    outside_cases = [
        ("astrbot_execute_shell", {"command": r"C:\Windows\System32\cmd.exe /c dir"}),
        ("astrbot_file_read_tool", {"path": "/etc/passwd"}),
        ("astrbot_file_read_tool", {"path": "../../escape.txt"}),
        ("astrbot_file_write_tool", {"path": "../../escape.txt", "content": "pwn"}),
        ("astrbot_execute_python", {"code": "open('/etc/passwd').read()"}),
    ]
    for tool_name, args in outside_cases:
        decision, reason, outside = assess_call(
            tool_name, args, task, storage_root=lab_env.store.root
        )
        assert decision == "review", f"Expected review for {tool_name} {args}, got {decision} ({reason})"
        assert outside or "越界" in reason or "工作区" in reason


def test_destructive_commands_blocked_for_review(lab_env):
    task = _make_task(lab_env.workspace, mode="full", phase="executing")

    destructive_cases = [
        ("astrbot_execute_shell", {"command": "rm -rf /tmp/x"}),
        ("astrbot_execute_shell", {"command": "git reset --hard HEAD~1"}),
        ("astrbot_execute_shell", {"command": "git clean -fd"}),
        ("astrbot_execute_shell", {"command": "del /s /q build_dir"}),
        ("astrbot_execute_shell", {"command": "del /s/q build_dir"}),
        ("astrbot_execute_shell", {"command": "cmd /c rm -rf /tmp/x"}),
        (
            "astrbot_execute_python",
            {"code": "import shutil\nfor p in ['a', 'b']:\n    shutil.rmtree(p)"},
        ),
        ("astrbot_execute_shell", {"command": 'sqlite3 app.db "DROP TABLE users;"'}),
    ]
    for tool_name, args in destructive_cases:
        decision, reason, _ = assess_call(tool_name, args, task, storage_root=lab_env.store.root)
        assert decision == "review", f"Destructive op NOT caught: {tool_name} {args} -> {decision} ({reason})"


def test_sensitive_secret_file_reads_blocked(lab_env):
    task = _make_task(lab_env.workspace, mode="full", phase="executing")

    for secret_path in [".env", ".env.production", ".ssh/id_rsa", "secrets.key", "certs/server.pem"]:
        decision, reason, _ = assess_call(
            "astrbot_file_read_tool",
            {"path": secret_path},
            task,
            storage_root=lab_env.store.root,
        )
        assert decision == "review", f"Sensitive read {secret_path} allowed: {decision}"
        assert "敏感" in reason

        # Even inside planning phase via cat/read, full_guard must still flag it
        plan_task = _make_task(lab_env.workspace, mode="standard", phase="planning")
        d2, _r2, _ = assess_call(
            "astrbot_execute_shell",
            {"command": f"cat {secret_path}"},
            plan_task,
            storage_root=lab_env.store.root,
        )
        assert d2 == "review", f"Sensitive shell read {secret_path} in planning got {d2}"


def test_disabled_tools_hard_blocked_even_in_full_mode(lab_env):
    profile = Profile(
        profile_id="full_locked",
        name="Full Locked",
        permission_mode="full",
        disabled_tools=["astrbot_execute_shell", "astrbot_file_write_tool"],
    )
    lab_env.store.save_profile(profile.to_dict())
    task = _make_task(lab_env.workspace, mode="full", phase="executing")
    task.profile_id = profile.profile_id
    lab_env.store.save_task(task)

    for disabled in ("astrbot_execute_shell", "astrbot_file_write_tool"):
        decision, reason, _ = assess_call(
            disabled, {"command": "ls", "path": "a.txt"}, task, profile=profile
        )
        assert decision == "deny"
        assert "禁用" in reason

        # Also verify bridge.invoke_tool rejects it even via OperationBlocked
        tool = make_tool(disabled, handler=lambda **kw: "should not run")
        with pytest.raises(OperationBlocked):
            asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, {"path": "a.txt"}, task.task_id))

        # And build_task_toolset excludes disabled_tools
        lab_env.ctx.tool_manager.func_list = [tool, make_tool("astrbot_file_read_tool")]
        ts = lab_env.engine.bridge.build_task_toolset(task, profile, None)
        assert ts.get_tool(disabled) is None
        assert ts.get_tool("astrbot_file_read_tool") is not None


def test_planning_phase_and_readonly_mode_allow_reads_and_deny_mutations(lab_env):
    for task in (
        _make_task(lab_env.workspace, mode="standard", phase="planning"),
        _make_task(lab_env.workspace, mode="readonly", phase="executing"),
    ):
        # Allowed read tools and safe git/ls
        for tname, args in (
            ("astrbot_file_read_tool", {"path": "README.md"}),
            ("astrbot_grep_tool", {"pattern": "TODO", "path": "."}),
            ("astrbot_list_directory", {"directory": "."}),
            ("astrbot_execute_shell", {"command": "git status"}),
            ("astrbot_execute_shell", {"command": "git diff HEAD~1"}),
            ("astrbot_execute_shell", {"command": "ls -la"}),
        ):
            d, r, _ = assess_call(tname, args, task, storage_root=lab_env.store.root)
            assert d == "allow", f"Expected allow for {tname} {args}, got {d}: {r}"

        # Denied writes, redirects, python, mutations
        for tname, args in (
            ("astrbot_file_write_tool", {"path": "foo.txt", "content": "hi"}),
            ("astrbot_file_edit_tool", {"path": "foo.txt", "old": "a", "new": "b"}),
            ("astrbot_execute_shell", {"command": "ls > out.txt"}),
            ("astrbot_execute_shell", {"command": "cat a.txt >> b.txt"}),
            ("astrbot_execute_python", {"code": "print(1)"}),
            ("astrbot_execute_shell", {"command": "python -c 'print(1)'"}),
            ("astrbot_execute_shell", {"command": "git push origin main"}),
            ("custom_delete_records", {"id": "1"}),
        ):
            d, _r, _ = assess_call(tname, args, task, storage_root=lab_env.store.root)
            assert d == "deny", f"Expected deny for {tname} {args} in planning/readonly, got {d}"


def test_inherited_cwd_not_falsely_flagged_and_tool_results_read_allowed(lab_env, monkeypatch):
    # Change process cwd to outside workspace
    outside_cwd = lab_env.tmp_path / "outside_process_cwd"
    outside_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(outside_cwd)

    task = _make_task(lab_env.workspace, mode="standard", phase="executing")

    # Shell command without explicit cwd must NOT be flagged by process cwd
    d1, r1, out1 = assess_call(
        "astrbot_execute_shell",
        {"command": "git status"},
        task,
        risk="work",
        storage_root=lab_env.store.root,
    )
    assert d1 == "allow", f"Inherited process cwd falsely flagged: {d1} {r1} {out1}"

    # Explicit out-of-bounds args["cwd"] MUST be flagged
    d2, _r2, out2 = assess_call(
        "astrbot_execute_shell",
        {"command": "git status", "cwd": str(outside_cwd)},
        task,
        risk="work",
        storage_root=lab_env.store.root,
    )
    assert d2 == "review"
    assert str(outside_cwd.resolve()) in out2

    # Reading tool_results/*.txt under store.root MUST be allowed for READ_TOOLS
    saved_file = lab_env.store.save_tool_result(task.umo, task.task_id, "call_123", "big output")
    d3, r3, _out3 = assess_call(
        "astrbot_file_read_tool",
        {"path": str(saved_file)},
        task,
        storage_root=lab_env.store.root,
    )
    assert d3 == "allow", f"Reading tool_results failed: {d3} {r3}"


def test_credential_vault_zero_exposure_and_exfiltration_blocking(lab_env):
    raw_secret = "mock_gh_token_SuperSecretToken987654321"
    special_secret = "sk+test/abc=999&xyz"
    b64_secret = base64.b64encode(raw_secret.encode("utf-8")).decode("ascii")
    url_special = urllib.parse.quote(special_secret, safe="")

    c1 = lab_env.store.save_credential(
        {
            "label": "GitHub PAT",
            "provider": "github",
            "env_var": "GITHUB_TOKEN",
            "value": raw_secret,
            "scope": "global",
        }
    )
    c2 = lab_env.store.save_credential(
        {
            "label": "Special API Key",
            "provider": "generic",
            "env_var": "SPECIAL_API_KEY",
            "value": special_secret,
            "scope": "global",
        }
    )
    assert c1.has_value and c1.masked_value == "********"

    proj = lab_env.store.save_project(
        {
            "title": "Vault Test",
            "source_umo": "aiocqhttp:FriendMessage:vault_user",
            "execution_settings": {
                "mode": "full",
                "roots": [str(lab_env.workspace)],
                "authorized_credentials": [c1.credential_id, c2.credential_id],
            },
        },
        select_for_umo="aiocqhttp:FriendMessage:vault_user",
    )
    task = asyncio.run(
        lab_env.engine.start_task(
            "aiocqhttp:FriendMessage:vault_user",
            "推送代码并测试凭证隔离",
            project_id=proj.project_id,
        )
    )
    task.phase = "executing"
    task.approved_version = 1
    task.version = 1
    task.session_workspace_root = str(lab_env.workspace)
    task.execution_cwd = str(lab_env.workspace)
    lab_env.store.save_task(task)

    # 1. Check list_credentials, prepare_wake_message, task_detail, and events.jsonl
    listed_dump = json.dumps([c.to_dict() for c in lab_env.store.list_credentials()], ensure_ascii=False)
    wake_msg, _ = prepare_wake_message(
        lab_env.store,
        task,
        [],
        authorized_creds=lab_env.store.resolve_authorized_credentials(
            proj.project_id, [], [c1.credential_id, c2.credential_id]
        ),
    )
    detail_dump = json.dumps(lab_env.engine.task_detail(task.task_id), ensure_ascii=False)
    events_path = lab_env.store.task_events_path(task.umo, task.task_id)
    events_dump = events_path.read_text(encoding="utf-8") if events_path.exists() else ""

    for surface_name, blob in [
        ("list_credentials", listed_dump),
        ("prepare_wake_message", wake_msg),
        ("task_detail", detail_dump),
        ("events.jsonl", events_dump),
    ]:
        for forbidden in (raw_secret, b64_secret, special_secret, url_special):
            assert forbidden not in blob, f"Secret leaked in {surface_name}: {forbidden}"

    # 2. Exfiltration commands blocked by is_credential_exfiltration & assess_call (deny)
    exfil_attempts = [
        ("astrbot_execute_shell", {"command": "echo $GITHUB_TOKEN"}),
        ("astrbot_execute_shell", {"command": "printenv"}),
        ("astrbot_execute_shell", {"command": "env"}),
        ("astrbot_execute_shell", {"command": 'python -c "import os; print(os.environ)"'}),
        ("astrbot_execute_python", {"code": "import os; print(os.environ['GITHUB_TOKEN'])"}),
    ]
    for tname, args in exfil_attempts:
        msg = is_credential_exfiltration(tname, args, ["GITHUB_TOKEN", "SPECIAL_API_KEY"])
        assert msg, f"is_credential_exfiltration missed {tname} {args}"
        d, _r, _ = assess_call(
            tname, args, task, authorized_env_vars=["GITHUB_TOKEN", "SPECIAL_API_KEY"]
        )
        assert d == "deny", f"Expected deny for exfil {tname} {args}, got {d}"

    # 3. Legitimate usage receives GITHUB_TOKEN in env, and echoed raw/b64/url secrets are redacted
    captured_env: dict[str, str] = {}

    async def mock_shell(command: str, env: dict[str, str] | None = None, **kwargs):
        captured_env.update(env or {})
        return (
            f"pushed with {raw_secret} | b64={b64_secret} | "
            f"special={special_secret} | url={url_special}"
        )

    shell_tool = make_tool(
        "astrbot_execute_shell",
        handler=mock_shell,
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}, "env": {"type": "object"}},
        },
    )
    res = asyncio.run(
        lab_env.engine.bridge.invoke_tool(
            None,
            shell_tool,
            {"command": 'curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user'},
            task.task_id,
        )
    )
    assert captured_env.get("GITHUB_TOKEN") == raw_secret
    assert captured_env.get("SPECIAL_API_KEY") == special_secret

    returned_text = res[0].content[0].text
    for forbidden in (raw_secret, b64_secret, special_secret, url_special):
        assert forbidden not in returned_text, f"Tool output leaked {forbidden}"
    assert "********" in returned_text

    # Also verify saved tool_results/*.txt has all variants redacted
    result_files = list(lab_env.store.task_tool_results_dir(task.umo, task.task_id).glob("*.txt"))
    assert len(result_files) == 1
    disk_txt = result_files[0].read_text(encoding="utf-8")
    for forbidden in (raw_secret, b64_secret, special_secret, url_special):
        assert forbidden not in disk_txt, f"tool_results leaked {forbidden}"


def test_approval_binding_one_shot_execution_no_double_approval_and_tamper_rejected(lab_env):
    task = _make_task(lab_env.workspace, mode="standard", phase="executing")
    lab_env.store.save_task(task)

    exec_count = 0

    async def write_outside(path: str, content: str = ""):
        nonlocal exec_count
        exec_count += 1
        return f"wrote {path}"

    tool = make_tool(
        "astrbot_file_write_tool",
        handler=write_outside,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        },
    )
    lab_env.ctx.tool_manager.func_list = [tool]

    exact_args = {"path": str(lab_env.tmp_path / "outside_ok.txt"), "content": "hello"}

    # Initially blocked (review)
    with pytest.raises(OperationBlocked):
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, exact_args, task.task_id))

    # Request tool_batch approval
    apr_res = asyncio.run(
        lab_env.engine.request_approval(
            task.task_id,
            operation="写入外部文件",
            reason="用户指定路径",
            calls=[{"tool_name": "astrbot_file_write_tool", "arguments": exact_args}],
        )
    )
    assert apr_res["ok"] is True

    # Approve
    res_apr = asyncio.run(lab_env.engine.resolve_approval(task.task_id, "approved"))
    assert res_apr["ok"] is True and res_apr["status"] == "running"

    # resume_approved_batch executes ONCE and marks consumed (no double-approval!)
    fresh = lab_env.store.find_task_by_id(task.task_id)
    receipts = asyncio.run(lab_env.engine.bridge.resume_approved_batch(None, fresh))
    assert len(receipts) == 1 and receipts[0]["ok"] is True
    assert exec_count == 1

    reloaded = lab_env.store.find_task_by_id(task.task_id)
    assert reloaded.approvals[-1].status == "consumed"
    assert reloaded.approvals[-1].calls[0]["execution_status"] == "consumed"
    assert reloaded.usage.tool_calls == 1, "resume_approved_batch must preserve invoke_tool's usage.tool_calls increment!"

    # Re-issuing with tampered args OR re-issuing same args after consumption is blocked!
    tampered_args = {"path": str(lab_env.tmp_path / "evil.txt"), "content": "hello"}
    with pytest.raises(OperationBlocked):
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, tampered_args, task.task_id))
    with pytest.raises(OperationBlocked):
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, exact_args, task.task_id))
    assert exec_count == 1
