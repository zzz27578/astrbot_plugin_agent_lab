"""Scenario 7: Unified Classic WebUI + API Security & Integration Regression Suite."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from agent_lab.engine import TaskEngine
from agent_lab.store import AgentLabStore
from agent_lab.webui_api import StandaloneWebUIServer, WebUIController
from scripts.preview_webui import seed_preview_data

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PAGES_DIR = PLUGIN_ROOT / "pages" / "agent-lab"

PREVIEW_SECRET_1 = "mock_gh_token_PreviewSecretTokenValue_9981_DoNotLeak"
PREVIEW_SECRET_2 = "ssh-passphrase-preview-4412-secret"
PREVIEW_PERSONAL_1 = "demo-maintainer <demo@example.com>"


def _build_standalone(
    tmp_path: Path,
    *,
    token: str = "",
    preview_mode: bool = False,
    seed: bool = False,
    static_dir: Path | None = None,
) -> tuple[AgentLabStore, TaskEngine, WebUIController, StandaloneWebUIServer]:
    store = AgentLabStore(tmp_path / "data")
    if seed:
        seed_preview_data(store, reset=True)
    engine = TaskEngine(store, context=None, config={})
    controller = WebUIController(
        store,
        engine,
        context=None,
        config={},
        preview_mode=preview_mode,
    )
    server = StandaloneWebUIServer(
        controller=controller,
        static_dir=static_dir or PAGES_DIR,
        host="127.0.0.1",
        port=0,
        token=token,
        preview_mode=preview_mode,
    )
    return store, engine, controller, server


async def _json(resp: Any) -> dict[str, Any]:
    data = await resp.get_json()
    assert isinstance(data, dict)
    return data


# ── 1. Standalone Auth & Security ────────────────────────────────────────────


def test_standalone_auth_requires_valid_token_when_not_preview(tmp_path: Path):
    async def _run() -> None:
        _store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="secret-admin-token",
            preview_mode=False,
        )
        client = server.app.test_client()

        # 1. Missing token -> HTTP 401/403 with ok=False on all protected APIs
        for method, path, body in (
            ("GET", "/api/state", None),
            ("POST", "/api/workspace", {"action": "set_theme", "theme": "classic"}),
            ("POST", "/api/profiles", {"action": "save", "name": "x"}),
            ("POST", "/api/credentials", {"action": "save", "label": "x", "value": "v"}),
        ):
            resp = await (client.get(path) if method == "GET" else client.post(path, json=body))
            assert resp.status_code in (401, 403), f"{method} {path} without token returned {resp.status_code}"
            data = await _json(resp)
            assert data.get("ok") is False

        # 2. Wrong token -> HTTP 401/403
        for hdrs in (
            {"Authorization": "Bearer wrong-token"},
            {"X-Agent-Lab-Token": "wrong-token"},
        ):
            for method, path, body in (
                ("GET", "/api/state", None),
                ("POST", "/api/workspace", {"action": "set_theme", "theme": "classic"}),
                ("POST", "/api/profiles", {"action": "save", "name": "x"}),
                ("POST", "/api/credentials", {"action": "save", "label": "x", "value": "v"}),
            ):
                resp = await (
                    client.get(path, headers=hdrs)
                    if method == "GET"
                    else client.post(path, headers=hdrs, json=body)
                )
                assert resp.status_code in (401, 403), f"{method} {path} wrong token returned {resp.status_code}"
                data = await _json(resp)
                assert data.get("ok") is False

        # 3. Valid token via both Authorization: Bearer and X-Agent-Lab-Token -> HTTP 200
        for hdrs in (
            {"Authorization": "Bearer secret-admin-token"},
            {"X-Agent-Lab-Token": "secret-admin-token"},
        ):
            resp_state = await client.get("/api/state", headers=hdrs)
            assert resp_state.status_code == 200
            assert (await _json(resp_state))["ok"] is True

            resp_ws = await client.post(
                "/api/workspace",
                headers=hdrs,
                json={"action": "set_theme", "theme": "classic"},
            )
            assert resp_ws.status_code == 200
            assert (await _json(resp_ws))["ok"] is True

            resp_prof = await client.post(
                "/api/profiles",
                headers=hdrs,
                json={"action": "save", "profile_id": "auth_prof", "name": "Auth Profile"},
            )
            assert resp_prof.status_code == 200
            assert (await _json(resp_prof))["ok"] is True

            resp_cred = await client.post(
                "/api/credentials",
                headers=hdrs,
                json={"action": "save", "credential_id": "auth_cred", "label": "Auth Cred", "value": "tok_123"},
            )
            assert resp_cred.status_code == 200
            assert (await _json(resp_cred))["ok"] is True

    asyncio.run(_run())


def test_standalone_serves_index_and_static_assets_and_rewrites_meta(tmp_path: Path):
    async def _run() -> None:
        _store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="secret-admin-token",
            preview_mode=False,
        )
        client = server.app.test_client()

        # GET / serves index.html with <meta name="agent-lab-api-base" content="/api" />
        resp = await client.get("/")
        assert resp.status_code == 200
        html = await resp.get_data(as_text=True)
        assert '<meta name="agent-lab-api-base" content="/api"' in html

        # All required static assets return HTTP 200; deleted Modern UI files return 404
        for asset in (
            "/api.js",
            "/store.js",
            "/classic.css",
            "/classic-view.js",
        ):
            r = await client.get(asset)
            assert r.status_code == 200, f"GET {asset} returned {r.status_code}"
            body = await r.get_data(as_text=True)
            assert len(body) > 50

        for removed_asset in ("/modern.css", "/modern-view.js"):
            r_rem = await client.get(removed_asset)
            assert r_rem.status_code == 404, f"Removed asset {removed_asset} unexpectedly returned {r_rem.status_code}"

        # Static path traversal must be blocked
        trav = await client.get("/../../main.py")
        assert trav.status_code in (400, 403, 404)

        # Also verify _serve_index rewrites /api/plug/astrbot_plugin_agent_lab -> /api when present
        custom_static = tmp_path / "custom_static"
        custom_static.mkdir()
        (custom_static / "index.html").write_text(
            '<!doctype html><html><head><meta name="agent-lab-api-base" content="/api/plug/astrbot_plugin_agent_lab" /></head><body>ok</body></html>',
            encoding="utf-8",
        )
        _s2, _e2, _c2, server2 = _build_standalone(
            tmp_path / "sub",
            token="secret-admin-token",
            preview_mode=False,
            static_dir=custom_static,
        )
        client2 = server2.app.test_client()
        r2 = await client2.get("/")
        assert r2.status_code == 200
        html2 = await r2.get_data(as_text=True)
        assert '<meta name="agent-lab-api-base" content="/api" />' in html2
        assert "/api/plug/astrbot_plugin_agent_lab" not in html2

    asyncio.run(_run())


# ── 2. Preview Server Seed & End-to-End API Flow ─────────────────────────────


def test_preview_seed_state_counts_and_zero_secret_leak(tmp_path: Path):
    async def _run() -> None:
        _store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="",
            preview_mode=True,
            seed=True,
        )
        client = server.app.test_client()

        resp = await client.get("/api/state")
        assert resp.status_code == 200
        state = await _json(resp)
        assert state["ok"] is True
        assert state["preview_mode"] is True

        assert len(state["identities"]) == 2
        assert len(state["projects"]) == 3
        assert len(state["tasks"]) == 4
        assert len(state["profiles"]) == 3

        # 5 Chinese plugin cards (with 定时与通知助手 host_enabled=False)
        plugins = state["plugins"]
        assert len(plugins) == 5
        plugins_by_name = {p["display_name"]: p for p in plugins}
        expected_plugin_names = [
            "文件读写工具",
            "终端与脚本",
            "Git 版本协作",
            "网页与文档检索",
            "定时与通知助手",
        ]
        assert list(plugins_by_name.keys()) == expected_plugin_names
        assert plugins_by_name["定时与通知助手"]["host_enabled"] is False
        for pname in expected_plugin_names[:-1]:
            assert plugins_by_name[pname]["host_enabled"] is True

        # 3 encrypted vault items: 2 secret + 1 personal
        creds = state["credentials"]
        assert len(creds) == 3
        assert sum(1 for c in creds if c.get("kind") == "secret") == 2
        assert sum(1 for c in creds if c.get("kind") == "personal") == 1

        for cred in creds:
            assert cred["has_value"] is True
            assert cred["masked_value"] == "********"
            assert "value" not in cred
            assert "encrypted_value" not in cred

        serialized = json.dumps(state, ensure_ascii=False)
        assert PREVIEW_SECRET_1 not in serialized
        assert PREVIEW_SECRET_2 not in serialized
        assert PREVIEW_PERSONAL_1 not in serialized
        assert "encrypted_value" not in serialized

    asyncio.run(_run())


def test_workspace_end_to_end_flow_and_error_status_codes(tmp_path: Path):
    async def _run() -> None:
        store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="",
            preview_mode=True,
            seed=True,
        )
        client = server.app.test_client()

        t1_id = "task_a1b2c3d4e5f6"
        t2_id = "task_b2c3d4e5f6a7"
        t4_id = "task_d4e5f6a7b8c9"
        proj_1 = "proj_agentlab_v1"

        # 1. set_theme switches modern <-> classic and persists
        r_classic = await client.post("/api/workspace", json={"action": "set_theme", "theme": "classic"})
        assert r_classic.status_code == 200
        assert (await _json(r_classic))["preferences"]["webui_theme"] == "classic"
        assert store.get_preferences()["webui_theme"] == "classic"

        s1 = await _json(await client.get("/api/state"))
        assert s1["preferences"]["webui_theme"] == "classic"

        r_modern = await client.post("/api/workspace", json={"action": "set_theme", "theme": "modern"})
        assert r_modern.status_code == 200
        assert store.get_preferences()["webui_theme"] == "modern"

        # 2. task_detail returns meta, journal, messages, files, unknown_calls
        r_det = await client.post("/api/workspace", json={"action": "task_detail", "task_id": t1_id})
        assert r_det.status_code == 200
        det = await _json(r_det)
        for key in ("meta", "journal", "messages", "files", "unknown_calls"):
            assert key in det
        assert det["meta"]["task_id"] == t1_id
        assert len(det["journal"]) >= 2
        assert len(det["messages"]) >= 5
        assert len(det["files"]) >= 2

        # 3. read_record returns redacted content and blocks path traversal
        umo_qq = det["meta"]["umo"]
        secret_rec_path = store.save_tool_result(
            umo_qq,
            t1_id,
            "call_secret_check",
            f"debug output: token={PREVIEW_SECRET_1} end",
        )
        rel_secret = str(secret_rec_path.relative_to(store.root)).replace("\\", "/")
        r_rec = await client.post("/api/workspace", json={"action": "read_record", "rel_path": rel_secret})
        assert r_rec.status_code == 200
        rec_data = await _json(r_rec)
        assert PREVIEW_SECRET_1 not in rec_data["content"]
        assert "已脱敏" in rec_data["content"] or "****" in rec_data["content"]

        r_trav = await client.post("/api/workspace", json={"action": "read_record", "rel_path": "../../etc/passwd"})
        assert r_trav.status_code in (400, 403)
        assert (await _json(r_trav))["ok"] is False

        # 4. approve -> answer -> transitions t1 to running
        r_apr = await client.post(
            "/api/workspace",
            json={
                "action": "approve",
                "task_id": t1_id,
                "approval_id": "apr_push_clean",
                "decision": "approved",
                "note": "Approved in S7 test",
            },
        )
        assert r_apr.status_code == 200
        apr_data = await _json(r_apr)
        assert apr_data["ok"] is True
        assert apr_data["decision"] == "approved"

        r_ans = await client.post(
            "/api/workspace",
            json={
                "action": "answer",
                "task_id": t1_id,
                "question_id": "q_webui_mode",
                "answer": "选项 1",
            },
        )
        assert r_ans.status_code == 200
        ans_data = await _json(r_ans)
        assert ans_data["ok"] is True
        assert ans_data["status"] == "running"
        assert ans_data["wait_reason"] == ""

        # 5. steer
        r_steer = await client.post(
            "/api/workspace",
            json={"action": "steer", "task_id": t1_id, "guidance": "请优先核验脱敏输出"},
        )
        assert r_steer.status_code == 200
        steer_data = await _json(r_steer)
        assert steer_data["ok"] is True
        assert steer_data["input_revision"] >= 4

        # 6. reconcile unknown call on t2
        r_rec_call = await client.post(
            "/api/workspace",
            json={
                "action": "reconcile",
                "task_id": t2_id,
                "call_id": "call_timeout_01",
                "status": "completed",
                "note": "Confirmed completed externally",
            },
        )
        assert r_rec_call.status_code == 200
        rec_call_data = await _json(r_rec_call)
        assert rec_call_data["ok"] is True
        assert rec_call_data["remaining_unknown"] == 0
        assert rec_call_data["task_status"] == "running"

        # 7. update_budget
        r_bud = await client.post(
            "/api/workspace",
            json={
                "action": "update_budget",
                "task_id": t1_id,
                "budget": {"max_total_tokens": 250_000, "max_total_ticks": 60},
            },
        )
        assert r_bud.status_code == 200
        bud_data = await _json(r_bud)
        assert bud_data["ok"] is True
        assert bud_data["execution_settings"]["budget"]["max_total_tokens"] == 250_000
        assert bud_data["execution_settings"]["budget"]["max_total_ticks"] == 60

        # 8. draft_summary & save_summary
        r_draft = await client.post("/api/workspace", json={"action": "draft_summary", "project_id": proj_1})
        assert r_draft.status_code == 200
        draft_data = await _json(r_draft)
        assert draft_data["ok"] is True
        assert "项目摘要" in draft_data["draft"]

        r_save_sum = await client.post(
            "/api/workspace",
            json={"action": "save_summary", "project_id": proj_1, "text": "S7 集成回归测试摘要"},
        )
        assert r_save_sum.status_code == 200
        assert (await _json(r_save_sum))["ok"] is True
        assert "S7 集成回归测试摘要" in store.read_project_summary(proj_1)

        # 9. pause_task -> resume_task -> deliver_task on t1
        r_pause = await client.post("/api/workspace", json={"action": "pause_task", "task_id": t1_id})
        assert r_pause.status_code == 200
        assert (await _json(r_pause))["status"] == "paused"

        r_resume = await client.post("/api/workspace", json={"action": "resume_task", "task_id": t1_id})
        assert r_resume.status_code == 200
        assert (await _json(r_resume))["status"] == "running"

        r_deliv = await client.post(
            "/api/workspace",
            json={"action": "deliver_task", "task_id": t1_id, "note": "S7 交付归档"},
        )
        assert r_deliv.status_code == 200
        deliv_data = await _json(r_deliv)
        assert deliv_data["ok"] is True
        assert deliv_data["status"] == "completed"

        # 10. stop_task on t4
        r_stop = await client.post(
            "/api/workspace",
            json={"action": "stop_task", "task_id": t4_id, "reason": "S7 停止测试"},
        )
        assert r_stop.status_code == 200
        stop_data = await _json(r_stop)
        assert stop_data["ok"] is True
        assert stop_data["status"] == "cancelled"

        # 11. cleanup_preview -> cleanup_confirm works once, rejects reused & invalid token (HTTP 400)
        r_cprev = await client.post(
            "/api/workspace",
            json={"action": "cleanup_preview", "scope": "task_cache", "task_id": t1_id},
        )
        assert r_cprev.status_code == 200
        cprev = await _json(r_cprev)
        assert cprev["ok"] is True
        tok = cprev["token"]
        assert tok and cprev["path_count"] >= 1

        r_cconf = await client.post("/api/workspace", json={"action": "cleanup_confirm", "token": tok})
        assert r_cconf.status_code == 200
        assert (await _json(r_cconf))["ok"] is True

        # Reuse same token -> HTTP 400
        r_reuse = await client.post("/api/workspace", json={"action": "cleanup_confirm", "token": tok})
        assert r_reuse.status_code == 400
        assert (await _json(r_reuse))["ok"] is False

        # Invalid/expired token -> HTTP 400
        r_bad_tok = await client.post(
            "/api/workspace",
            json={"action": "cleanup_confirm", "token": "expired_or_fake_token"},
        )
        assert r_bad_tok.status_code == 400
        assert (await _json(r_bad_tok))["ok"] is False

        # 12. Invalid actions or nonexistent task IDs return real HTTP 400/404 (NEVER fake 200 {ok: false})
        for bad_body in (
            {},
            {"action": "nonexistent_workspace_action"},
            {"action": "set_theme", "theme": "invalid_theme"},
        ):
            r_bad = await client.post("/api/workspace", json=bad_body)
            assert r_bad.status_code == 400
            assert (await _json(r_bad))["ok"] is False

        for missing_body in (
            {"action": "task_detail", "task_id": "task_000000000000"},
            {"action": "pause_task", "task_id": "task_000000000000"},
            {"action": "resume_task", "task_id": "task_000000000000"},
            {"action": "stop_task", "task_id": "task_000000000000"},
            {"action": "deliver_task", "task_id": "task_000000000000"},
            {"action": "approve", "task_id": "task_000000000000", "decision": "approved"},
            {"action": "answer", "task_id": "task_000000000000", "answer": "yes"},
            {"action": "steer", "task_id": "task_000000000000", "guidance": "go"},
            {"action": "reconcile", "task_id": "task_000000000000", "call_id": "c1", "status": "completed"},
            {"action": "update_budget", "task_id": "task_000000000000", "budget": {"max_total_ticks": 10}},
        ):
            r_miss = await client.post("/api/workspace", json=missing_body)
            assert r_miss.status_code == 404, f"{missing_body['action']} returned {r_miss.status_code}"
            assert (await _json(r_miss))["ok"] is False

    asyncio.run(_run())


def test_read_record_blocks_internal_vault_and_sibling_prefix_traversal(tmp_path: Path):
    """Security regression: read_record must not expose Fernet secrets.key, credentials.json, or sibling dirs."""
    async def _run() -> None:
        _store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="",
            preview_mode=True,
            seed=True,
        )
        client = server.app.test_client()

        # Sibling directory sharing store.root's name prefix: <tmp_path>/data_evil/leak.txt
        evil_dir = tmp_path / "data_evil"
        evil_dir.mkdir(parents=True, exist_ok=True)
        (evil_dir / "leak.txt").write_text("SIBLING_LEAK", encoding="utf-8")

        for forbidden in (
            "../data_evil/leak.txt",
            "registry/secrets.key",
            "registry/credentials.json",
        ):
            resp = await client.post("/api/workspace", json={"action": "read_record", "rel_path": forbidden})
            assert resp.status_code in (400, 403), f"read_record allowed {forbidden} with HTTP {resp.status_code}"
            assert (await _json(resp))["ok"] is False

    asyncio.run(_run())


def test_profiles_api_save_empty_lists_duplicate_and_delete(tmp_path: Path):
    async def _run() -> None:
        store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="",
            preview_mode=True,
            seed=True,
        )
        client = server.app.test_client()

        # Save with plugin_blacklist=["temp_plugin"] and disabled_tools=["astrbot_execute_shell"]
        r_save = await client.post(
            "/api/profiles",
            json={
                "action": "save",
                "profile": {
                    "profile_id": "s7_custom_prof",
                    "name": "S7 定制方案",
                    "permission_mode": "standard",
                    "plugin_blacklist": ["temp_plugin"],
                    "disabled_tools": ["astrbot_execute_shell"],
                },
            },
        )
        assert r_save.status_code == 200
        saved = (await _json(r_save))["profile"]
        assert saved["plugin_blacklist"] == ["temp_plugin"]
        assert saved["disabled_tools"] == ["astrbot_execute_shell"]

        # Update to empty plugin_blacklist=[] -> must persist empty list, NOT drop it
        r_upd = await client.post(
            "/api/profiles",
            json={
                "action": "save",
                "profile": {
                    "profile_id": "s7_custom_prof",
                    "name": "S7 定制方案",
                    "permission_mode": "standard",
                    "plugin_blacklist": [],
                    "disabled_tools": ["astrbot_execute_shell"],
                },
            },
        )
        assert r_upd.status_code == 200
        updated = (await _json(r_upd))["profile"]
        assert updated["plugin_blacklist"] == []
        assert updated["disabled_tools"] == ["astrbot_execute_shell"]
        persisted = store.get_profile("s7_custom_prof")
        assert persisted.plugin_blacklist == []
        assert persisted.disabled_tools == ["astrbot_execute_shell"]

        # Duplicate
        r_dup = await client.post(
            "/api/profiles",
            json={"action": "duplicate", "profile_id": "s7_custom_prof", "name": "S7 副本"},
        )
        assert r_dup.status_code == 200
        dup = (await _json(r_dup))["profile"]
        assert dup["profile_id"] != "s7_custom_prof"
        assert dup["is_default"] is False
        assert dup["plugin_blacklist"] == []
        assert dup["disabled_tools"] == ["astrbot_execute_shell"]

        # Delete duplicated profile -> 200
        r_del = await client.post(
            "/api/profiles",
            json={"action": "delete", "profile_id": dup["profile_id"]},
        )
        assert r_del.status_code == 200
        assert (await _json(r_del))["ok"] is True

        # Bind a project to "default", then delete "default" while >= 2 profiles exist -> 200,
        # auto-promoting a remaining profile as default and rebinding projects
        bound_proj = store.save_project(
            {"project_id": "proj_rebind_def", "title": "Rebind Test", "profile_id": "default"}
        )
        assert bound_proj.profile_id == "default"

        r_del_def = await client.post(
            "/api/profiles",
            json={"action": "delete", "profile_id": "default"},
        )
        assert r_del_def.status_code == 200
        assert (await _json(r_del_def))["ok"] is True

        remaining_after_def = store.list_profiles()
        assert all(p.profile_id != "default" for p in remaining_after_def)
        promoted = [p for p in remaining_after_def if p.is_default]
        assert len(promoted) == 1
        assert store.get_project("proj_rebind_def").profile_id == promoted[0].profile_id

        # Delete remaining profiles down to 1 -> all succeed
        for p in remaining_after_def[:-1]:
            r_del_extra = await client.post(
                "/api/profiles",
                json={"action": "delete", "profile_id": p.profile_id},
            )
            assert r_del_extra.status_code == 200
            assert (await _json(r_del_extra))["ok"] is True

        last_profile = store.list_profiles()
        assert len(last_profile) == 1

        # Deleting the last remaining profile MUST fail (400 / 409)
        r_del_last = await client.post(
            "/api/profiles",
            json={"action": "delete", "profile_id": last_profile[0].profile_id},
        )
        assert r_del_last.status_code in (400, 409)
        assert (await _json(r_del_last))["ok"] is False

    asyncio.run(_run())


def test_credentials_api_save_update_metadata_zero_leak_and_delete(tmp_path: Path):
    async def _run() -> None:
        store, _engine, _ctrl, server = _build_standalone(
            tmp_path,
            token="",
            preview_mode=True,
            seed=True,
        )
        client = server.app.test_client()

        secret_val = "mock_pypi_token_98765432_0000_1111_2222_333344445555"
        personal_val = "personal-ssh-alias-host-10.0.0.42"

        # 1. Save new secret credential
        r_save = await client.post(
            "/api/credentials",
            json={
                "action": "save",
                "credential": {
                    "label": "PyPI Release Token",
                    "kind": "secret",
                    "provider": "pypi",
                    "env_var": "TWINE_PASSWORD",
                    "scope": "global",
                    "note": "initial note",
                    "value": secret_val,
                },
            },
        )
        assert r_save.status_code == 200
        save_data = await _json(r_save)
        assert save_data["ok"] is True
        cred = save_data["credential"]
        cid = cred["credential_id"]
        assert cred["kind"] == "secret"
        assert cred["has_value"] is True
        assert cred["masked_value"] == "********"
        assert secret_val not in json.dumps(save_data, ensure_ascii=False)
        assert "encrypted_value" not in json.dumps(save_data, ensure_ascii=False)

        # 1b. Save new personal vault item
        r_save_pers = await client.post(
            "/api/credentials",
            json={
                "action": "save",
                "credential": {
                    "label": "常用跳板机别名",
                    "kind": "personal",
                    "provider": "personal",
                    "env_var": "SHOULD_NOT_INJECT_ENV",
                    "scope": "global",
                    "share_with_tasks": False,
                    "note": "personal note",
                    "value": personal_val,
                },
            },
        )
        assert r_save_pers.status_code == 200
        save_pers_data = await _json(r_save_pers)
        assert save_pers_data["ok"] is True
        pers_cred = save_pers_data["credential"]
        pid = pers_cred["credential_id"]
        assert pers_cred["kind"] == "personal"
        assert pers_cred["has_value"] is True
        assert pers_cred["masked_value"] == "********"
        assert personal_val not in json.dumps(save_pers_data, ensure_ascii=False)
        assert "encrypted_value" not in json.dumps(save_pers_data, ensure_ascii=False)

        # 2. Update metadata without passing `value` -> secret & personal MUST NOT be wiped
        r_upd = await client.post(
            "/api/credentials",
            json={
                "action": "save",
                "credential": {
                    "credential_id": cid,
                    "label": "PyPI Prod Token",
                    "kind": "secret",
                    "provider": "pypi",
                    "env_var": "TWINE_PASSWORD",
                    "scope": "global",
                    "note": "updated metadata",
                },
            },
        )
        assert r_upd.status_code == 200
        upd_cred = (await _json(r_upd))["credential"]
        assert upd_cred["label"] == "PyPI Prod Token"
        assert upd_cred["kind"] == "secret"
        assert upd_cred["note"] == "updated metadata"
        assert upd_cred["has_value"] is True
        assert upd_cred["masked_value"] == "********"
        assert store.get_credential_secret(cid) == secret_val

        r_upd_pers = await client.post(
            "/api/credentials",
            json={
                "action": "save",
                "credential": {
                    "credential_id": pid,
                    "label": "跳板机备忘（已更新）",
                    "kind": "personal",
                    "provider": "personal",
                    "env_var": "SHOULD_NOT_INJECT_ENV",
                    "scope": "global",
                    "note": "updated personal note",
                },
            },
        )
        assert r_upd_pers.status_code == 200
        upd_pers = (await _json(r_upd_pers))["credential"]
        assert upd_pers["label"] == "跳板机备忘（已更新）"
        assert upd_pers["kind"] == "personal"
        assert upd_pers["note"] == "updated personal note"
        assert upd_pers["has_value"] is True
        assert upd_pers["masked_value"] == "********"
        assert personal_val not in json.dumps(upd_pers, ensure_ascii=False)
        assert "encrypted_value" not in json.dumps(upd_pers, ensure_ascii=False)
        assert store.get_credential_secret(pid) == personal_val

        # 2b. build_authorized_env injects ONLY kind="secret", NEVER kind="personal"
        injected_env = store.build_authorized_env("proj_agentlab_v1", [cid, pid], [])
        assert injected_env == {"TWINE_PASSWORD": secret_val}
        assert "SHOULD_NOT_INJECT_ENV" not in injected_env
        assert personal_val not in injected_env.values()

        # 3. GET /api/state NEVER leaks plaintext or encrypted_value
        state_json = json.dumps(await _json(await client.get("/api/state")), ensure_ascii=False)
        assert secret_val not in state_json
        assert personal_val not in state_json
        assert PREVIEW_SECRET_1 not in state_json
        assert PREVIEW_SECRET_2 not in state_json
        assert PREVIEW_PERSONAL_1 not in state_json
        assert "encrypted_value" not in state_json

        # 4. Delete works for both and second delete returns 404
        for del_id in (cid, pid):
            r_del = await client.post("/api/credentials", json={"action": "delete", "credential_id": del_id})
            assert r_del.status_code == 200
            assert (await _json(r_del))["deleted"] == del_id

            r_del2 = await client.post("/api/credentials", json={"action": "delete", "credential_id": del_id})
            assert r_del2.status_code == 404
            assert (await _json(r_del2))["ok"] is False

    asyncio.run(_run())


# ── 3. AstrBot Native Route Registration ─────────────────────────────────────


def test_astrbot_native_route_registration_get_post_only(tmp_path: Path):
    """Mock AstrBot's Context.register_web_api(path, handler, methods, desc) and verify all 5 routes."""
    store = AgentLabStore(tmp_path / "data")
    engine = TaskEngine(store, context=None, config={})
    controller = WebUIController(store, engine, context=None, config={})

    registered: list[dict[str, Any]] = []

    class MockAstrBotContext:
        # Matches astrbot.api.star.Context.register_web_api(self, route, view_handler, methods, desc)
        def register_web_api(self, path: str, handler: Any, methods: list[str], desc: str) -> None:
            registered.append(
                {
                    "path": path,
                    "handler": handler,
                    "methods": list(methods),
                    "desc": desc,
                }
            )

    ctx = MockAstrBotContext()
    controller.register_astrbot_routes(ctx, "astrbot_plugin_agent_lab")

    assert len(registered) == 5
    by_path = {r["path"]: r for r in registered}
    expected_methods = {
        "/astrbot_plugin_agent_lab/v1/health": ["GET"],
        "/astrbot_plugin_agent_lab/v1/state": ["GET"],
        "/astrbot_plugin_agent_lab/v1/workspace": ["POST"],
        "/astrbot_plugin_agent_lab/v1/profiles": ["POST"],
        "/astrbot_plugin_agent_lab/v1/credentials": ["POST"],
    }
    assert set(by_path.keys()) == set(expected_methods.keys())
    for route, req_methods in expected_methods.items():
        actual_methods = by_path[route]["methods"]
        assert actual_methods == req_methods
        assert set(actual_methods).issubset({"GET", "POST"})
        assert "DELETE" not in actual_methods
        assert "PUT" not in actual_methods
        assert callable(by_path[route]["handler"])


def test_discover_identities_excludes_unconfigured_webchat_and_keeps_enabled_aiocqhttp(tmp_path: Path):
    """Regression: only platforms enabled in platform_manager.platforms_config appear; internal webchat is excluded."""
    async def _run() -> None:
        store = AgentLabStore(tmp_path / "data")
        engine = TaskEngine(store, context=None, config={})

        inst_aiocqhttp = SimpleNamespace(
            meta=lambda: SimpleNamespace(
                id="aiocqhttp",
                name="aiocqhttp",
                adapter_display_name="OneBot v11 (aiocqhttp)",
            )
        )
        inst_webchat = SimpleNamespace(
            meta=lambda: SimpleNamespace(
                id="webchat",
                name="webchat",
                adapter_display_name="AstrBot WebChat",
            )
        )
        mock_plat_mgr = SimpleNamespace(
            platforms_config=[
                {"id": "aiocqhttp", "type": "aiocqhttp", "name": "QQ 主号", "enable": True},
                {"id": "webchat", "type": "webchat", "name": "WebChat", "enable": False},
            ],
            platform_insts=[inst_aiocqhttp, inst_webchat],
        )
        mock_ctx = SimpleNamespace(platform_manager=mock_plat_mgr)
        controller = WebUIController(store, engine, context=mock_ctx, config={}, preview_mode=False)

        identities = await controller._discover_identities(
            projects=[],
            tasks=[],
            preferences={"default_bot": "", "progress": {}},
        )
        assert len(identities) == 1
        assert identities[0]["platform_id"] == "aiocqhttp"
        assert all(ident["platform_id"] != "webchat" for ident in identities)
        assert all(not str(ident["umo"]).startswith("webchat:") for ident in identities)

    asyncio.run(_run())


# ── 4. Frontend Safety & Unified Classic UI Contract Check ───────────────────


def test_frontend_classic_ui_contract_dirty_form_bridge_and_no_native_dialogs():
    index_html = (PAGES_DIR / "index.html").read_text(encoding="utf-8")
    api_js = (PAGES_DIR / "api.js").read_text(encoding="utf-8")
    store_js = (PAGES_DIR / "store.js").read_text(encoding="utf-8")
    classic_css = (PAGES_DIR / "classic.css").read_text(encoding="utf-8")
    classic_js = (PAGES_DIR / "classic-view.js").read_text(encoding="utf-8")

    # 1. Cold-minimalist Classic UI only: zero gradients, no Modern UI or theme switcher
    assert "gradient" not in classic_css.lower(), "classic.css must have zero gradient occurrences"
    assert not (PAGES_DIR / "modern.css").exists()
    assert not (PAGES_DIR / "modern-view.js").exists()

    assert "classic.css" in index_html
    assert "classic-view.js" in index_html
    assert "mountClassicView" in index_html
    for removed in ("modern.css", "modern-view.js", "mountModernView", "subscribeTheme", "set_theme"):
        assert removed not in index_html, f"index.html should not reference {removed}"

    assert re.search(r"\bexport\s+function\s+mountClassicView\s*\(", classic_js)
    assert "AbortController" in classic_js and "ac.abort()" in classic_js

    # 2. store.js handles dirty-form & active-input focus preservation
    for symbol in (
        "markDirty",
        "clearDirty",
        "isDirty",
        "isFormFocusedInView",
        "shouldDeferViewRender",
        "flushDeferredRenderIfReady",
        "pendingSilentRender",
        "document.activeElement",
        "focusout",
    ):
        assert symbol in store_js, f"store.js missing focus/dirty-form guard: {symbol}"

    # 3. api.js supports AstrBotPluginView & AstrBotPluginPage and uses GET/POST only
    assert "window.AstrBotPluginView" in api_js
    assert "window.AstrBotPluginPage" in api_js
    assert "bridge.ready" in api_js
    assert "bridge.requestResize" in api_js
    assert "stripApiPrefix" in api_js
    assert re.search(r'method:\s*"GET"', api_js)
    assert re.search(r'method:\s*"POST"', api_js)
    assert not re.search(r'method:\s*"(DELETE|PUT|PATCH)"', api_js)

    # 4. No raw window.prompt / window.confirm / window.alert (or bare prompt/confirm/alert)
    for fname, src in (
        ("api.js", api_js),
        ("store.js", store_js),
        ("classic-view.js", classic_js),
    ):
        assert not re.search(r"\bwindow\.(prompt|confirm|alert)\b", src), f"Raw window dialog in {fname}"
        assert not re.search(r"(?<![.\w])(prompt|confirm|alert)\s*\(", src), f"Bare dialog call in {fname}"

    # 5. Versioned v1 API endpoints, cache-bust query params, breadcrumb bar, and profile delete rule
    for ep in ("/api/v1/health", "/api/v1/state", "/api/v1/workspace", "/api/v1/profiles", "/api/v1/credentials"):
        assert ep in store_js, f"store.js missing versioned endpoint {ep}"
    for asset in ("classic.css?v=1.0.0-r2", "store.js?v=1.0.0-r2", "classic-view.js?v=1.0.0-r2"):
        assert asset in index_html, f"index.html missing cache-busted asset {asset}"
    assert "cl-breadcrumb-bar" in classic_js and "cl-breadcrumb-bar" in classic_css
    assert "cl-view-animate" in classic_js and "cl-view-animate" in classic_css
    assert "prefers-reduced-motion" in classic_css
    assert 'profile_id === "default"' not in classic_js
