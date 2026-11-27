"""v1.0.1 regressions: bounded search, planning authority, recovery and delivery."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from pathlib import Path

import pytest

import main as plugin_main
from agent_lab.bridge import OperationBlocked
from agent_lab.context_engine import prepare_wake_message
from agent_lab.engine import TaskEngine
from agent_lab.models import TaskMeta
from agent_lab.permissions import assess_call, execution_roots
from agent_lab.webui_api import StandaloneWebUIServer, WebUIController
from tests.conftest import make_event, make_tool


def _task(env, *, phase="executing"):
    task = TaskMeta(
        task_id="task_aabbccdd0101",
        umo="test:FriendMessage:regression",
        project_id=env.store.ensure_default_project("test:FriendMessage:regression").project_id,
        profile_id="default",
        goal="v1.0.1 regression",
        status="running",
        phase=phase,
        version=1,
        approved_version=1 if phase == "executing" else 0,
        session_workspace_root=str(env.workspace),
        execution_cwd=str(env.workspace),
        scope_roots=[str(env.workspace)],
        authorized_scope_roots=[str(env.workspace)],
    )
    task.execution_settings.roots = [str(env.workspace)]
    env.store.save_task(task)
    return task


def _assess(env, task, name, args):
    return assess_call(name, args, task, storage_root=env.store.root)


def _text(results):
    return "\n".join(c.text for result in results for c in result.content if hasattr(c, "text"))


def test_grep_bomb_and_shell_search_bombs_denied(lab_env):
    for phase in ("planning", "executing"):
        task = _task(lab_env, phase=phase)
        for pattern in (".", ".*", "^", "$", r"\s", r"[\s\S]", "(?s)."):
            decision, reason, _ = _assess(
                lab_env, task, "astrbot_grep_tool", {"path": ".", "pattern": pattern}
            )
            assert decision == "deny", (phase, pattern, decision, reason)
            assert "正则" in reason
        for command in ("rg .", "grep -r .", "find /"):
            decision, reason, _ = _assess(lab_env, task, "astrbot_execute_shell", {"command": command})
            assert decision == "deny", (phase, command, decision, reason)
        for pattern in (r"\.json", "supervisor-desk", "nest_ledger_tools"):
            decision, reason, outside = _assess(
                lab_env, task, "astrbot_grep_tool", {"path": ".", "pattern": pattern}
            )
            assert (decision, reason, outside) == ("allow", "", [])


def test_sensitive_grep_globs_and_shell_wildcards_require_review(lab_env):
    from agent_lab.permissions import full_guard, is_sensitive_path

    globs = ("*.key", "*.pem", "*.p12", "*.pfx", ".env*", "*secret*",
             "*credential*", "id_rsa*", "id_ed25519*", "id_ecdsa*",
             "*.[kp]em", "*.{py,key}")
    for phase in ("planning", "executing"):
        task = _task(lab_env, phase=phase)
        for glob in globs:
            args = {"path": ".", "pattern": "needle", "glob": glob}
            decision, reason, _ = _assess(lab_env, task, "astrbot_grep_tool", args)
            assert decision == "review" and "敏感" in reason, (phase, glob, reason)
            assert "敏感" in full_guard("astrbot_grep_tool", args, task)[0]
        for command in ("cat *.key", "cat .env*", "cat *secret*", "head *credential*",
                        "env FLAG=test command cat id_rsa*", "cat *.[kp]em"):
            decision, reason, _ = _assess(
                lab_env, task, "astrbot_execute_shell", {"command": command}
            )
            assert decision == "review" and "敏感" in reason, (phase, command, reason)
        assert _assess(lab_env, task, "astrbot_grep_tool",
                       {"path": ".", "pattern": "needle", "glob": "*.py"})[0] == "allow"
    for name in (".env.production", ".ssh/config", ".aws/config", "db.credentials.json",
                 "app-secret.txt", "id_rsa.backup", "id_ed25519-old", "tls.key"):
        assert is_sensitive_path(name), name
    assert not is_sensitive_path("src/service.py")


def test_python_grep_never_opens_sensitive_files(lab_env, monkeypatch):
    from agent_lab.bridge import _python_local_grep
    from agent_lab.permissions import is_sensitive_path

    sensitive = [
        ".env", ".env.local", ".ssh/config", ".aws/config", "secrets.key",
        "server.pem", "bundle.p12", "bundle.pfx", "service-credentials.txt",
        "app-secret.txt", "id_rsa.backup", "id_ed25519", "id_ecdsa",
        ".git-credentials", ".npmrc", ".pypirc",
    ]
    for name in sensitive:
        file = lab_env.workspace / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("needle PRIVATE_SENTINEL", encoding="utf-8")
    (lab_env.workspace / "ordinary.txt").write_text("needle PUBLIC_SENTINEL", encoding="utf-8")
    opened = []
    original_open = Path.open

    def checked_open(file, *args, **kwargs):
        assert not is_sensitive_path(str(file)), f"Sensitive file was opened: {file}"
        opened.append(file)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(Path, "open", checked_open)
    for glob in ("", "*", "*.txt", "*.key", "*secret*"):
        text, error = _python_local_grep(
            {"pattern": "needle", "glob": glob, "-C": 1}, lab_env.workspace
        )
        assert error is False and "PRIVATE_SENTINEL" not in text
        if glob in ("", "*", "*.txt"):
            assert "PUBLIC_SENTINEL" in text
    assert opened
    for name in sensitive:
        assert _python_local_grep({"pattern": "needle"}, lab_env.workspace / name) == (
            "No matches found.", False
        )


def test_grep_custom_cwd_denied_before_validation_or_execution(lab_env, monkeypatch):
    from agent_lab.permissions import full_guard

    task = _task(lab_env)
    sub = lab_env.workspace / "sub"
    sub.mkdir()
    outside = lab_env.tmp_path / "README.md"
    outside.write_text("needle PRIVATE_SENTINEL", encoding="utf-8")
    (lab_env.workspace / "README.md").write_text("needle approved", encoding="utf-8")
    args = {"path": "../README.md", "cwd": str(sub), "pattern": "needle"}
    message = "astrbot_grep_tool 不支持 cwd 参数，请直接传目标路径"
    assert _assess(lab_env, task, "astrbot_grep_tool", args) == ("deny", message, [])
    assert full_guard("astrbot_grep_tool", args, task) == (message, [])
    monkeypatch.setattr(lab_env.ctx, "get_config", lambda **_kw: {
        "provider_settings": {"computer_use_runtime": "local"}
    })
    assert asyncio.run(lab_env.engine.bridge._safe_local_grep(args, task)) == (message, True)
    invoked = []
    tool = make_tool("astrbot_grep_tool", handler=lambda **kw: invoked.append(kw))
    for override in (False, True):
        with pytest.raises(OperationBlocked, match="不支持 cwd"):
            asyncio.run(lab_env.engine.bridge.invoke_tool(
                None, tool, args, task.task_id, approved_override=override
            ))
    assert invoked == [] and lab_env.store.latest_journal_by_call(task.umo, task.task_id) == []


def test_grep_large_dir_and_node_modules_guarded(lab_env, monkeypatch):
    task = _task(lab_env, phase="planning")
    large = lab_env.tmp_path / "large"
    large.mkdir()
    for index in range(2001):
        (large / f"source_{index}.txt").touch()
    deps = lab_env.workspace / "node_modules"
    deps.mkdir()
    (deps / "dependency.js").write_text("specific-keyword", encoding="utf-8")
    small = lab_env.workspace / "src"
    small.mkdir()
    (small / "app.py").write_text("specific-keyword", encoding="utf-8")
    for rg_path in (None, "rg-test-binary"):
        monkeypatch.setattr(shutil, "which", lambda name, value=rg_path: value if name == "rg" else None)
        decision, reason, _ = _assess(
            lab_env, task, "astrbot_grep_tool", {"path": str(deps), "pattern": "specific-keyword"}
        )
        assert decision == "deny" and "node_modules" in reason
        decision, reason, _ = _assess(
            lab_env, task, "astrbot_grep_tool", {"path": str(large), "pattern": "specific-keyword"}
        )
        assert decision == ("allow" if rg_path else "deny"), reason
        if not rg_path:
            assert "2000" in reason
        assert _assess(lab_env, task, "astrbot_grep_tool", {"path": str(small), "pattern": "specific-keyword"}) == ("allow", "", [])
    assert _assess(lab_env, task, "astrbot_grep_tool", {"path": ".", "pattern": "specific-keyword"})[0] == "deny"


def test_safe_local_grep_proxy_early_stop_and_no_rg_fallback(lab_env, monkeypatch):
    task = _task(lab_env)
    tool = make_tool("astrbot_grep_tool", handler=lambda **_kw: "ORIGINAL_MOCK_HANDLER")
    assert lab_env.ctx.get_config()["provider_settings"]["computer_use_runtime"] == "none"
    assert "ORIGINAL_MOCK_HANDLER" in _text(asyncio.run(
        lab_env.engine.bridge.invoke_tool(None, tool, {"path": ".", "pattern": "needle"}, task.task_id)
    ))
    monkeypatch.setattr(lab_env.ctx, "get_config", lambda **_kw: {"provider_settings": {"computer_use_runtime": "local"}})
    real_rg = shutil.which("rg")
    source = lab_env.workspace / "matches.txt"
    source.write_text(("needle " + "X" * 1500 + "\n") * 50, encoding="utf-8")
    deps = lab_env.workspace / "node_modules"
    deps.mkdir()
    (deps / "hidden.txt").write_text("DEPENDENCY_ONLY needle", encoding="utf-8")
    (lab_env.workspace / "binary.txt").write_bytes(b"needle\x00BINARY_ONLY")
    (lab_env.workspace / "oversized.txt").write_text("OVERSIZED_ONLY needle\n" + "Z" * (2 * 1024 * 1024), encoding="utf-8")

    class FakeProcess:
        def __init__(self):
            self.stdout = self
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode = None
            self.reads = 0
            self.killed = False
            self.waited = False

        async def read(self, _size):
            if self.killed:
                return b""
            self.reads += 1
            assert self.reads <= 6, "rg stdout was consumed beyond the requested result limit"
            return f"matches.txt:{self.reads}:needle\n".encode()

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            self.waited = True
            assert self.killed, "early stopping must terminate and reap the producer"
            return self.returncode

    async def check_early_stop():
        proc = FakeProcess()
        calls = []

        async def spawn(*args, **kwargs):
            calls.append((args, kwargs))
            return proc

        with monkeypatch.context() as patch:
            patch.setattr(shutil, "which", lambda name: "controlled-rg" if name == "rg" else None)
            patch.setattr(asyncio, "create_subprocess_exec", spawn)
            text, error = await lab_env.engine.bridge._safe_local_grep(
                {"path": str(lab_env.workspace), "pattern": "needle", "result_limit": 5}, task
            )
        assert error is False
        assert proc.killed and proc.waited and proc.reads == 5
        assert len([line for line in text.splitlines() if re.match(r"matches\.txt:\d+:needle$", line)]) == 5
        assert "Truncated to first 5 result groups" in text
        command = calls[0][0]
        assert "--max-columns=1000" in command and "--max-columns-preview" in command
        assert "--glob=!**/node_modules/**" in command and "--max-filesize=2M" in command
        assert command[-2:] == ("--", str(lab_env.workspace.resolve()))
    asyncio.run(check_early_stop())

    async def check_search(expected_rg):
        text, error = await lab_env.engine.bridge._safe_local_grep(
            {"path": str(lab_env.workspace), "pattern": "needle", "glob": "*.txt", "result_limit": 5}, task
        )
        assert error is False, text
        lines = [line for line in text.splitlines() if "matches.txt:" in line]
        assert len(lines) == 5
        assert "X" * 1001 not in text
        assert "Truncated to first 5 result groups" in text
        for forbidden in ("DEPENDENCY_ONLY", "BINARY_ONLY", "oversized.txt", "ORIGINAL_MOCK_HANDLER"):
            assert forbidden not in text
        if not expected_rg:
            assert all(len(line.split(":", 3)[-1]) <= 1000 for line in lines)
        hidden, hidden_error = await lab_env.engine.bridge._safe_local_grep(
            {"path": str(lab_env.workspace), "pattern": "DEPENDENCY_ONLY|BINARY_ONLY|OVERSIZED_ONLY", "glob": "*.txt"}, task
        )
        assert (hidden, hidden_error) == ("No matches found.", False)
    if real_rg:
        asyncio.run(check_search(True))
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    asyncio.run(check_search(False))
    result = asyncio.run(lab_env.engine.bridge.invoke_tool(
        None, tool, {"path": str(source), "pattern": "needle", "result_limit": 5}, task.task_id
    ))
    assert "ORIGINAL_MOCK_HANDLER" not in _text(result)
    assert "Truncated to first 5 result groups" in _text(result)


def test_planning_phase_allows_outside_readonly_but_blocks_sensitive_and_writes(lab_env):
    task = _task(lab_env, phase="planning")
    outside = lab_env.tmp_path / "outside"
    outside.mkdir()
    plain = outside / "notes.txt"
    plain.write_text("ordinary research notes", encoding="utf-8")
    for tool, args in (
        ("astrbot_file_read_tool", {"path": str(plain)}),
        ("astrbot_list_directory", {"directory": str(outside)}),
        ("astrbot_execute_shell", {"command": f'cat "{plain}"'}),
    ):
        assert _assess(lab_env, task, tool, args) == ("allow", "", [])
    for name in (".env", "secrets.key", "credentials.json", ".ssh/id_rsa"):
        decision, reason, _ = _assess(lab_env, task, "astrbot_file_read_tool", {"path": str(outside / name)})
        assert decision == "review" and "敏感" in reason, (name, reason)
    for tool, args in (
        ("astrbot_file_write_tool", {"path": str(plain), "content": "mutation"}),
        ("astrbot_file_edit_tool", {"path": str(plain), "old": "a", "new": "b"}),
        ("astrbot_execute_python", {"code": "print(1)"}),
        ("astrbot_execute_shell", {"command": "python -c 'print(1)'"}),
    ):
        assert _assess(lab_env, task, tool, args)[0] == "deny"
    task.phase = "executing"
    task.approved_version = task.version
    decision, reason, paths = _assess(lab_env, task, "astrbot_file_read_tool", {"path": str(plain)})
    assert decision == "review" and str(plain.resolve()) in paths


def test_wake_message_exposes_effective_roots_and_cwd(lab_env):
    task = asyncio.run(lab_env.engine.start_task("test:FriendMessage:wake", "scope-aware wake"))
    project = lab_env.store.get_project(task.project_id)
    assert project.execution_settings.roots == []
    task.session_workspace_root = str(lab_env.workspace)
    task.execution_cwd = str(lab_env.workspace)
    candidate = str(lab_env.tmp_path / "candidate")
    task.scope_roots = [candidate]
    message, metric = prepare_wake_message(lab_env.store, task, [])
    payload = json.loads(message.split("]\n", 1)[1])
    assert metric["mode"] == "full"
    assert payload["authorized_roots"] == execution_roots(task) == [str(lab_env.workspace.resolve())]
    assert payload["session_workspace_root"] == str(lab_env.workspace)
    assert payload["execution_cwd"] == str(lab_env.workspace)
    assert payload["candidate_scope_roots"] == [candidate]
    assert candidate not in payload["authorized_roots"]


def test_review_hint_for_readonly_outside_path_no_misleading_fallback(lab_env):
    task = _task(lab_env)
    outside = lab_env.tmp_path / "external.txt"
    outside.write_text("outside scope", encoding="utf-8")
    invoked = []
    tool = make_tool("astrbot_file_read_tool", handler=lambda **kw: invoked.append(kw))
    with pytest.raises(OperationBlocked) as caught:
        asyncio.run(lab_env.engine.bridge.invoke_tool(None, tool, {"path": str(outside)}, task.task_id))
    text = str(caught.value)
    assert "低风险只读方案" not in text
    for expected in ("[REVIEW]", "authorized_roots", repr(str(lab_env.workspace)), "outside_paths", repr(str(outside)), "task_approve", "scope_roots"):
        assert expected in text
    assert invoked == []


def test_start_task_scope_roots_zero_trust_and_submit_plan_pending_roots(lab_env, monkeypatch):
    engine, store = lab_env.engine, lab_env.store
    target = str(lab_env.tmp_path / "target")
    extra = str(lab_env.tmp_path / "extra")
    task = asyncio.run(engine.start_task(
        "test:FriendMessage:scope", "zero trust", scope_roots=[" " + target + " ", target, ""], brief="background"
    ))
    assert task.scope_roots == [os.path.normpath(target)]
    assert task.authorized_scope_roots == [] and task.execution_settings.roots == []
    assert task.brief == "background" and execution_roots(task) == []
    result = asyncio.run(engine.submit_plan(task.task_id, ["inspect", "implement"], scope_roots=[extra]))
    assert result["ok"] is True and result["needs_approval"] is True
    pending = store.find_task_by_id(task.task_id)
    assert pending.authorized_scope_roots == []
    assert pending.status == "paused" and pending.wait_reason == "need_plan_approval"
    assert target in pending.pending_approvals()[0].reason and extra in pending.pending_approvals()[0].reason
    approved = asyncio.run(engine.resolve_approval(task.task_id, "approved"))
    assert approved["ok"] is True
    assert store.find_task_by_id(task.task_id).authorized_scope_roots == [target, extra]

    project = store.save_project({"title": "existing roots", "execution_settings": {"roots": [str(lab_env.workspace)]}})
    task2 = asyncio.run(engine.start_task("test:FriendMessage:scope2", "retain roots", project_id=project.project_id, scope_roots=[target]))
    assert task2.scope_roots == [str(lab_env.workspace), target]
    assert task2.authorized_scope_roots == [str(lab_env.workspace)]
    # Simulate a persisted plan containing only its new scope: both older sources must survive approval.
    historical = str(lab_env.tmp_path / "previously_authorized")
    task2.authorized_scope_roots = [historical]
    task2.scope_roots = [target]
    store.save_task(task2)
    asyncio.run(engine.submit_plan(task2.task_id, ["implement"]))
    asyncio.run(engine.resolve_approval(task2.task_id, "approved"))
    task2 = store.find_task_by_id(task2.task_id)
    assert task2.authorized_scope_roots == [historical, target, str(lab_env.workspace)]
    assert task2.phase == "executing" and task2.approved_version == task2.version
    routine = asyncio.run(engine.submit_plan(task2.task_id, ["implement", "verify"]))
    assert routine["needs_approval"] is False

    # Verify both public start entrypoints forward candidates and brief without granting authority.
    plugin = plugin_main.AgentLabPlugin.__new__(plugin_main.AgentLabPlugin)
    plugin.store, plugin.engine = store, engine
    monkeypatch.setattr(plugin, "_require_access", lambda _event: None)
    monkeypatch.setattr(engine, "schedule", lambda *_args: None)
    public = json.loads(asyncio.run(plugin.agent_lab_start_task(
        make_event(), "public start", scope_roots=f"{target}; {extra}, {target}\n ", brief="public brief"
    )))
    assert public["ok"] is True
    forwarded = store.find_task_by_id(public["task_id"])
    assert forwarded.scope_roots == [target, extra] and forwarded.authorized_scope_roots == []
    assert forwarded.brief == "public brief"
    ctrl = WebUIController(store, engine, context=None, config={}, preview_mode=True)
    web = asyncio.run(ctrl.handle_workspace({"action": "start_task", "goal": "web start", "scope_roots": [extra], "brief": "web brief"}))
    assert web["ok"] is True
    assert web["task"]["scope_roots"] == [extra] and web["task"]["authorized_scope_roots"] == []
    assert web["task"]["brief"] == "web brief"


def test_unknown_profile_id_no_silent_escalation(lab_env, monkeypatch, caplog):
    store, engine = lab_env.store, lab_env.engine
    full = store.get_profile("full_autonomous")
    full.is_default = True
    store._write_json(store.profiles_path, [full.to_dict()])
    assert store.get_profile("default").profile_id == "full_autonomous"  # Historical reads remain compatible.
    active = asyncio.run(engine.start_task("test:FriendMessage:profile", "existing task"))
    with pytest.raises(ValueError, match="full_autonomous"):
        asyncio.run(engine.start_task(active.umo, "invalid start", profile_id="default"))
    assert store.load_active_task(active.umo).task_id == active.task_id
    assert store.find_task_by_id(active.task_id).status == "running"
    with pytest.raises(ValueError, match="default"):
        store.get_profile("default", strict=True)
    plugin = plugin_main.AgentLabPlugin.__new__(plugin_main.AgentLabPlugin)
    plugin.store, plugin.engine = store, engine
    monkeypatch.setattr(plugin, "_require_access", lambda _event: None)
    before = len(store.list_tasks())
    result = json.loads(asyncio.run(plugin.agent_lab_start_task(make_event(), "invalid", profile_id="default")))
    assert result["ok"] is False and "default" in result["error"]
    assert result["available_profiles"] == [{"profile_id": full.profile_id, "name": full.name, "permission_mode": "full", "is_default": True}]
    assert len(store.list_tasks()) == before
    ctrl = WebUIController(store, engine, context=None, config={}, preview_mode=True)
    server = StandaloneWebUIServer(controller=ctrl, static_dir=Path(__file__).resolve().parents[1] / "pages" / "agent-lab", host="127.0.0.1", port=0, token="", preview_mode=True)

    async def bad_web_start():
        response = await server.app.test_client().post("/api/workspace", json={"action": "start_task", "goal": "invalid", "profile_id": "default"})
        assert response.status_code == 400
        payload = await response.get_json()
        assert payload["ok"] is False and "full_autonomous" in payload["error"]
    asyncio.run(bad_web_start())
    assert len(store.list_tasks()) == before
    stale = store.save_project({"title": "stale project", "profile_id": "removed-profile", "execution_settings": {"mode": "standard"}})
    with caplog.at_level(logging.WARNING, logger="astrbot_plugin_agent_lab.engine"):
        fallback = asyncio.run(engine.start_task("test:FriendMessage:stale", "legacy fallback", project_id=stale.project_id))
    assert fallback.profile_id == "full_autonomous" and fallback.execution_settings.mode == "standard"
    assert any("removed-profile" in record.message and "full" in record.message for record in caplog.records)


def test_store_read_json_handles_utf8_bom(lab_env):
    store = lab_env.store
    profiles = [p.to_dict() for p in store.list_profiles()]
    bom = b"\xef\xbb\xbf"
    store.profiles_path.write_bytes(bom + json.dumps(profiles, ensure_ascii=False).encode("utf-8"))
    assert [p.to_dict() for p in store.list_profiles()] == profiles
    assert store.get_profile("readonly_research", strict=True).permission_mode == "readonly"
    project = store.ensure_default_project("test:FriendMessage:bom")
    summary = store.project_summary_path(project.project_id)
    summary.write_bytes(bom + "BOM summary".encode("utf-8"))
    assert store.read_project_summary(project.project_id) == "BOM summary"
    task = asyncio.run(lab_env.engine.start_task(project.source_umo, "BOM events"))
    events = store.task_events_path(task.umo, task.task_id)
    events.write_bytes(bom + b'{"kind":"usage","total_tokens":17}\n')
    assert store.read_events(task.umo, task.task_id, kind="usage", limit=0) == [{"kind": "usage", "total_tokens": 17}]
    store._write_json(store.profiles_path, profiles)
    assert not store.profiles_path.read_bytes().startswith(bom)
    store.save_project_summary(project.project_id, "standard UTF-8")
    assert not summary.read_bytes().startswith(bom)


def test_recover_on_startup_reconciles_usage_and_send_dm_logs_warning(lab_env, monkeypatch, caplog):
    store, engine = lab_env.store, lab_env.engine
    task = asyncio.run(engine.start_task("test:FriendMessage:crash", "recover usage"))
    for prompt, completion in ((5000, 980), (6000, 449)):
        store.append_event(task.umo, task.task_id, "usage", {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion, "reported": True})
    # More than 500 events proves recovery cannot use read_events' default window.
    for _ in range(501):
        store.append_event(task.umo, task.task_id, "usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reported": False})
    for call_id, statuses in (("done", ("started", "completed")), ("failed", ("started", "failed")), ("inflight", ("started",))):
        for status in statuses:
            store.append_event(task.umo, task.task_id, "journal", {"call_id": call_id, "tool_name": "mock_read", "status": status})
    assert store.find_task_by_id(task.task_id).usage.total_tokens == 0
    paused = asyncio.run(engine.start_task("test:FriendMessage:paused", "paused crash"))
    paused.status, paused.wait_reason, paused.human_paused = "paused", "human_paused", True
    store.save_task(paused)
    store.append_event(paused.umo, paused.task_id, "usage", {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "reported": True})
    restarted = TaskEngine(store, context=lab_env.ctx)
    assert restarted.recover_on_startup() == {"unknown_marked": 1, "paused": 1}
    recovered = store.find_task_by_id(task.task_id)
    expected = {"prompt_tokens": 11000, "completion_tokens": 1429, "total_tokens": 12429, "llm_calls": 503, "unreported_calls": 501, "tool_calls": 2}
    assert {key: getattr(recovered.usage, key) for key in expected} == expected
    assert recovered.status == "paused" and recovered.wait_reason == "recovered_pause"
    assert {j["call_id"]: j["status"] for j in store.latest_journal_by_call(task.umo, task.task_id)} == {"done": "completed", "failed": "failed", "inflight": "unknown"}
    assert store.find_task_by_id(paused.task_id).usage.total_tokens == 7
    assert store.find_task_by_id(paused.task_id).wait_reason == "human_paused"
    assert restarted.recover_on_startup() == {"unknown_marked": 0, "paused": 0}
    recovered.usage.tool_calls = 99
    store.save_task(recovered)
    assert restarted._reconcile_usage_from_events(recovered) is False
    assert recovered.usage.tool_calls == 99
    ahead = TaskMeta.from_dict(recovered.to_dict())
    for field in expected:
        setattr(ahead.usage, field, expected[field] + 1000)
    ahead.usage.ticks_used = 7
    snapshot = ahead.usage.to_dict()
    assert restarted._reconcile_usage_from_events(ahead) is False
    assert ahead.usage.to_dict() == snapshot

    store.append_event(task.umo, task.task_id, "usage", {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3, "reported": True})
    meta_path = store.task_meta_path(task.umo, task.task_id)
    before = meta_path.read_bytes()
    detail = restarted.task_detail(task.task_id)
    assert detail["meta"]["usage"]["total_tokens"] == 12432
    assert detail["meta"]["usage"]["llm_calls"] == 504
    assert meta_path.read_bytes() == before, "task_detail must not persist a read-only aggregation"
    assert store.find_task_by_id(task.task_id).usage.total_tokens == 12429
    assert asyncio.run(restarted.stop(task.task_id))["ended"] is True
    stopped = store.find_task_by_id(task.task_id)
    assert stopped.usage.total_tokens == 12432 and stopped.usage.tool_calls == 99
    store.append_event(paused.umo, paused.task_id, "usage", {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5, "reported": True})
    assert asyncio.run(restarted.deliver_as_is(paused.task_id))["ended"] is True
    delivered = store.find_task_by_id(paused.task_id)
    assert delivered.usage.total_tokens == 12 and delivered.usage.llm_calls == 2

    async def raising_send(_umo, _chain):
        raise RuntimeError("delivery transport unavailable")

    async def falsy_send(_umo, _chain):
        return False

    for sender, cause in ((raising_send, "delivery transport unavailable"), (falsy_send, "returned=False")):
        caplog.clear()
        monkeypatch.setattr(lab_env.ctx, "send_message", sender)
        with caplog.at_level(logging.WARNING, logger="astrbot_plugin_agent_lab.bridge"):
            result = asyncio.run(restarted.bridge.send_dm(task.umo, "notification", task_id=task.task_id, kind="status", force=True))
        assert result["delivery"] == "unconfirmed"
        records = [r for r in caplog.records if r.name == "astrbot_plugin_agent_lab.bridge" and r.levelno == logging.WARNING]
        assert len(records) == 1
        for value in (task.umo, task.task_id, "kind=status", cause):
            assert value in records[0].message


def test_real_rg_grep_never_exposes_sensitive_files(lab_env):
    from agent_lab.bridge import _rg_local_grep

    executable = shutil.which("rg")
    assert executable is not None, "This regression requires a real rg executable on PATH"
    sensitive = (
        "secrets.key", ".env", ".env.local",
        "nested/secrets.key", "nested/.env", "nested/.env.production",
    )
    for index, name in enumerate(sensitive):
        file = lab_env.workspace / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(f"private context\nneedle PRIVATE_SENTINEL_{index}\n", encoding="utf-8")
    (lab_env.workspace / "ordinary.txt").write_text("needle PUBLIC_SENTINEL\n", encoding="utf-8")
    (lab_env.workspace / "nested" / "ordinary.txt").write_text("needle NESTED_PUBLIC\n", encoding="utf-8")

    async def check_searches():
        for glob in ("", "*", "*.txt", "*.key", ".env*", "*secret*"):
            text, error = await _rg_local_grep(
                executable, {"pattern": "needle", "glob": glob, "-C": 1}, lab_env.workspace
            )
            assert error is False, (glob, text)
            assert "PRIVATE_SENTINEL" not in text and "private context" not in text, (glob, text)
            if glob in ("", "*", "*.txt"):
                assert "PUBLIC_SENTINEL" in text and "NESTED_PUBLIC" in text, (glob, text)
            else:
                assert text == "No matches found.", (glob, text)
        for name in sensitive:
            assert await _rg_local_grep(
                executable, {"pattern": "needle", "glob": "*.key"}, lab_env.workspace / name
            ) == ("No matches found.", False)

    asyncio.run(check_searches())


def test_plan_versions_supersede_pending_and_authorize_only_snapshot_roots(lab_env):
    engine, store = lab_env.engine, lab_env.store
    task = _task(lab_env)
    older, newer, late, rejected_old, rejected_new = (
        str(lab_env.tmp_path / name)
        for name in ("older", "newer", "late", "rejected_old", "rejected_new")
    )
    for root in (older, newer, late, rejected_old, rejected_new):
        Path(root).mkdir()
    first = asyncio.run(engine.submit_plan(task.task_id, ["inspect older"], scope_roots=[older]))
    second = asyncio.run(engine.submit_plan(task.task_id, ["inspect newer"], scope_roots=[newer]))
    assert first["ok"] and first["needs_approval"]
    assert second["ok"] and second["needs_approval"]
    assert second["version"] == first["version"] + 1
    pending = store.find_task_by_id(task.task_id)
    old_request = next(a for a in pending.approvals if a.approval_id == first["approval_id"])
    assert old_request.status == "superseded" and old_request.resolved_at
    assert "新版" in old_request.decision_note
    assert [a.approval_id for a in pending.pending_approvals()] == [second["approval_id"]]
    current = pending.pending_approvals()[0]
    snapshot = tuple(current.calls[0]["scope_roots"])
    assert snapshot == (str(lab_env.workspace), older, newer)
    assert current.plan_version == pending.version == second["version"]
    assert pending.authorized_scope_roots == [str(lab_env.workspace)]

    # Candidate edits after submission must not change what the administrator approves.
    pending.scope_roots.append(late)
    store.save_task(pending)
    before = store.task_meta_path(task.umo, task.task_id).read_bytes()
    stale = asyncio.run(engine.resolve_approval(task.task_id, "approved", approval_id=first["approval_id"]))
    assert stale["ok"] is False and "过期" in stale["error"]
    assert store.task_meta_path(task.umo, task.task_id).read_bytes() == before
    pending = store.find_task_by_id(task.task_id)
    assert tuple(pending.pending_approvals()[0].calls[0]["scope_roots"]) == snapshot
    assert late not in execution_roots(pending)

    approved = asyncio.run(engine.resolve_approval(task.task_id, "approved", approval_id=second["approval_id"]))
    assert approved["ok"] is True
    accepted = store.find_task_by_id(task.task_id)
    assert accepted.authorized_scope_roots == accepted.scope_roots == list(snapshot)
    assert execution_roots(accepted) == [str(Path(root).resolve()) for root in snapshot]
    assert accepted.phase == "executing" and accepted.status == "running"
    assert accepted.approved_version == accepted.version == second["version"]
    assert late not in execution_roots(accepted)

    third = asyncio.run(engine.submit_plan(task.task_id, ["expand again"], scope_roots=[rejected_old]))
    fourth = asyncio.run(engine.submit_plan(task.task_id, ["revise expansion"], scope_roots=[rejected_new]))
    assert third["ok"] and fourth["ok"] and fourth["needs_approval"]
    pending = store.find_task_by_id(task.task_id)
    assert [a.approval_id for a in pending.pending_approvals()] == [fourth["approval_id"]]
    assert rejected_old in pending.scope_roots and rejected_new in pending.scope_roots
    assert asyncio.run(engine.resolve_approval(
        task.task_id, "rejected", approval_id=fourth["approval_id"]
    ))["ok"] is True
    withdrawn = store.find_task_by_id(task.task_id)
    assert withdrawn.pending_approvals() == []
    assert withdrawn.authorized_scope_roots == withdrawn.scope_roots == list(snapshot)
    assert execution_roots(withdrawn) == execution_roots(accepted)
    for root in (late, rejected_old, rejected_new):
        assert root not in execution_roots(withdrawn)


def test_wrapped_search_bombs_and_approved_override_remain_denied(lab_env):
    from agent_lab.permissions import read_only_call

    (lab_env.workspace / "node_modules").mkdir()
    invoked = []
    tools = {
        name: make_tool(name, handler=lambda **kw: invoked.append(kw))
        for name in ("astrbot_execute_shell", "astrbot_grep_tool")
    }
    for command in ("rg --pre=echo foo .", "env rg --pre=echo foo .", "command rg --pre=echo foo ."):
        assert read_only_call("astrbot_execute_shell", {"command": command}) is False, command
    cases = [
        ("astrbot_execute_shell", {"command": "env rg . ."}, "正则"),
        ("astrbot_execute_shell", {"command": "command rg . ."}, "正则"),
        ("astrbot_execute_shell", {"command": "rg --pre=echo foo ."}, "--pre"),
        ("astrbot_execute_shell", {"command": 'rg "a*" .'}, "正则"),
        ("astrbot_execute_shell", {"command": 'rg "needle|" .'}, "正则"),
        ("astrbot_grep_tool", {"path": ".", "pattern": "a*"}, "正则"),
        ("astrbot_grep_tool", {"path": ".", "pattern": "needle|"}, "正则"),
        ("astrbot_grep_tool", {"path": ".", "pattern": "needle", "glob": "*?*"}, "node_modules"),
        ("astrbot_execute_shell", {"command": 'rg -g "*?*" needle .'}, "node_modules"),
        ("astrbot_execute_shell", {"command": "find / -maxdepth 999999"}, "maxdepth"),
    ]
    for phase in ("planning", "executing"):
        task = _task(lab_env, phase=phase)
        assert _assess(lab_env, task, "astrbot_grep_tool", {
            "path": ".", "pattern": "needle", "glob": "*.py"
        }) == ("allow", "", [])
        for name, args, expected in cases:
            decision, reason, _ = _assess(lab_env, task, name, args)
            assessment_reason = "只读" if phase == "planning" and "--pre" in args.get("command", "") else expected
            assert decision == "deny" and assessment_reason in reason, (phase, name, args, decision, reason)
            for override in (False, True):
                with pytest.raises(OperationBlocked, match=r"\[DENY\]") as caught:
                    asyncio.run(lab_env.engine.bridge.invoke_tool(
                        None, tools[name], args, task.task_id, approved_override=override
                    ))
                assert expected in str(caught.value), (phase, args, override, str(caught.value))
        assert lab_env.store.latest_journal_by_call(task.umo, task.task_id) == []
    assert invoked == []


def test_deleted_runtime_profile_pauses_execution_and_journal_has_no_2000_limit(lab_env):
    store, engine = lab_env.store, lab_env.engine
    task = _task(lab_env)
    assert store.get_profile(task.profile_id, strict=True).permission_mode != "full"
    full = store.get_profile("full_autonomous", strict=True)
    full.is_default = True
    store._write_json(store.profiles_path, [full.to_dict()])
    assert store.get_profile(task.profile_id).profile_id == "full_autonomous"
    with pytest.raises(ValueError):
        store.get_profile(task.profile_id, strict=True)
    invoked = []
    tool = make_tool("astrbot_file_write_tool", handler=lambda **kw: invoked.append(kw))
    args = {"path": str(lab_env.workspace / "must_not_exist.txt"), "content": "mutation"}

    for entrypoint in ("invoke", "override", "turn", "drive", "resume"):
        active = store.find_task_by_id(task.task_id)
        active.status, active.wait_reason, active.human_paused = "running", "", False
        store.save_task(active)
        if entrypoint in {"invoke", "override"}:
            with pytest.raises(OperationBlocked, match="方案已不存在"):
                asyncio.run(engine.bridge.invoke_tool(
                    None, tool, args, task.task_id, approved_override=entrypoint == "override"
                ))
        elif entrypoint == "turn":
            with pytest.raises(OperationBlocked, match="方案已不存在"):
                asyncio.run(engine.bridge.run_task_turn(None, active))
        elif entrypoint == "drive":
            asyncio.run(engine._drive(None, task.task_id))
        else:
            result = asyncio.run(engine.resume(task.task_id))
            assert result["ok"] is False and result["wait_reason"] == "profile_missing"
        paused = store.find_task_by_id(task.task_id)
        assert paused.status == "paused" and paused.wait_reason == "profile_missing", entrypoint
        assert paused.profile_id == task.profile_id != "full_autonomous", entrypoint
        assert store.latest_journal_by_call(task.umo, task.task_id) == []
    assert invoked == [] and not (lab_env.workspace / "must_not_exist.txt").exists()
    assert lab_env.ctx.conversations == {}
    assert not any(e.get("event") == "tick_error" for e in store.read_events(task.umo, task.task_id, kind="log", limit=0))

    # Both an unresolved call and the first half of a completed call precede the old window.
    for call_id in ("early-inflight", "spanning"):
        store.append_event(task.umo, task.task_id, "journal", {
            "call_id": call_id, "tool_name": "astrbot_file_write_tool", "status": "started",
            "arguments": {"path": "report.txt"},
        })
    for index in range(2001):
        store.append_event(task.umo, task.task_id, "journal", {
            "call_id": f"bulk_{index}", "tool_name": "mock_read", "status": "completed",
        })
    store.append_event(task.umo, task.task_id, "journal", {"call_id": "spanning", "status": "completed"})
    assert len(store.read_events(task.umo, task.task_id, kind="journal", limit=0)) == 2004
    journal = store.latest_journal_by_call(task.umo, task.task_id)
    assert [j["call_id"] for j in journal] == ["early-inflight", "spanning"] + [f"bulk_{i}" for i in range(2001)]
    assert journal[0]["status"] == "started"
    assert journal[1]["status"] == "completed"
    assert journal[1]["tool_name"] == "astrbot_file_write_tool"
    assert journal[1]["arguments"] == {"path": "report.txt"}
    assert all(j["status"] == "completed" for j in journal[2:])
    assert [j["call_id"] for j in engine._unknown_calls(paused)] == ["early-inflight"]
