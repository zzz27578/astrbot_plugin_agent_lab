"""Session workspace permissions with real temporary files and Python execution.

Run: python -B scripts/ui/test_task_workspace.py -v
No AstrBot instance, production configuration or task is loaded.
"""
from __future__ import annotations

import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("workspace_permissions", ROOT / "agent_lab" / "task_permissions.py")
Permissions = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Permissions)


class TaskWorkspaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.project = self.base / "project"
        self.workspaces = self.base / "workspaces"
        self.workspace = self.workspaces / "session-a"
        self.other = self.workspaces / "session-b"
        self.archive = self.base / "tasks" / "task-a"
        for directory in (self.project, self.workspace, self.other, self.archive / "tool_results"):
            directory.mkdir(parents=True)
        self.state = {
            "execution_settings": {"mode": "standard", "roots": [str(self.project)]},
            "execution_cwd": str(self.workspace),
            "session_workspace_root": str(self.workspace),
            "task_data_root": str(self.archive),
        }

    def assert_action(self, expected, name, args, state=None):
        actual, outside = Permissions.assess(name, args, self.state if state is None else state, risk="high")
        self.assertEqual(actual, expected, (name, args, outside))

    def scoped_calls(self, path):
        for name in sorted(Permissions.READ_TOOLS | Permissions.WRITE_TOOLS):
            yield name, {"path": str(path)}
        for name in sorted(Permissions.CODE_TOOLS):
            args = ({"command": f'cat "{path}"'} if "shell" in name
                    else {"code": f"open({str(path)!r}).read()"})
            yield name, args

    def test_effective_roots_are_a_pure_union_without_changing_project_authority(self):
        before = copy.deepcopy(self.state)
        with patch.object(Permissions, "Path", side_effect=AssertionError("helper must not do I/O")):
            self.assertEqual(Permissions.execution_roots(self.state), [str(self.project), str(self.workspace)])
            self.assertEqual(Permissions.authorized_roots(self.state), [str(self.project)])
        self.assertEqual(self.state, before)
        for authority in ({"authorized_scope_roots": [str(self.project)]},
                          {"version": 2, "approved_version": 2, "scope_roots": [str(self.project)]}):
            state = dict(authority, session_workspace_root=str(self.workspace))
            self.assertEqual(Permissions.execution_roots(state), [str(self.project), str(self.workspace)])
        for root in (None, "", "relative/workspace", 123):
            self.assertEqual(Permissions.execution_roots(dict(self.state, session_workspace_root=root)),
                             [str(self.project)])
        state = dict(self.state, session_workspace_root=str(self.project))
        self.assertEqual(Permissions.execution_roots(state), [str(self.project)])

    def test_real_read_write_and_script_execution_need_no_review(self):
        (self.workspace / "input.txt").write_text("session input", encoding="utf-8")
        code = ("from pathlib import Path\n"
                "assert Path('input.txt').read_text(encoding='utf-8') == 'session input'\n"
                "assert Path('draft.txt').read_text(encoding='utf-8') == 'draft'\n"
                "Path('result.txt').write_text('script passed', encoding='utf-8')\n"
                "print('WORKSPACE_PASS')\n")
        (self.workspace / "check.py").write_text(code, encoding="utf-8")
        before = copy.deepcopy(self.state)
        for mode in ("standard", "full"):
            state = dict(self.state, execution_settings={"mode": mode, "roots": [str(self.project)]})
            for name, args in self.scoped_calls("input.txt"):
                self.assert_action("allow", name, args, state)
            self.assertEqual((self.workspace / "input.txt").read_text(encoding="utf-8"), "session input")
            self.assert_action("allow", "astrbot_file_write_tool", {"path": "draft.txt", "content": "draft"}, state)
            (self.workspace / "draft.txt").write_text("draft", encoding="utf-8")
            self.assert_action("allow", "astrbot_file_edit_tool", {"path": "draft.txt"}, state)
            for name in sorted(Permissions.CODE_TOOLS):
                args = ({"command": "python ./check.py"} if "shell" in name else {"code": code})
                self.assert_action("allow", name, args, state)
            process = subprocess.run([sys.executable, "-B", "check.py"], cwd=self.workspace,
                                     capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertIn("WORKSPACE_PASS", process.stdout)
            self.assertEqual((self.workspace / "result.txt").read_text(encoding="utf-8"), "script passed")
        self.assertEqual(self.state, before)
        self.assertFalse((self.other / "result.txt").exists())

    def test_each_session_keeps_its_exact_boundary_and_explicit_project_roots(self):
        for workspace, other in ((self.workspace, self.other), (self.other, self.workspace)):
            state = dict(self.state, execution_cwd=str(workspace), session_workspace_root=str(workspace))
            for name, args in self.scoped_calls(workspace / "note.txt"):
                self.assert_action("allow", name, args, state)
            for name, args in self.scoped_calls(self.project / "note.txt"):
                self.assert_action("allow", name, args, state)
            for path in (other / "note.txt", "../" + other.name + "/note.txt",
                         self.workspaces, self.workspaces / (workspace.name + "-other") / "note.txt"):
                for name, args in self.scoped_calls(path):
                    with self.subTest(workspace=workspace, name=name, path=path):
                        self.assert_action("review", name, args, state)
        # Workspace-only tasks also enforce their boundary when project roots are empty.
        state = dict(self.state, execution_settings={"mode": "full", "roots": []})
        self.assertEqual(Permissions.execution_roots(state), [str(self.workspace)])
        self.assert_action("review", "astrbot_file_read_tool", {"path": str(self.other / "note.txt")}, state)

    def test_cwd_only_resolves_paths_and_cannot_grant_workspace_authority(self):
        state = dict(self.state)
        state.pop("session_workspace_root")
        self.assertEqual(Permissions.execution_roots(state), [str(self.project)])
        for name, args in self.scoped_calls("note.txt"):
            self.assert_action("review", name, args, state)
        for name in Permissions.CODE_TOOLS:
            args = {"cwd": str(self.other), "command": "echo ok", "code": "print('ok')"}
            self.assert_action("review", name, args, state)
        # File tools ignore a model's cwd for resolution; the host still uses session-b.
        state = dict(self.state, execution_cwd=str(self.other))
        for name in Permissions.READ_TOOLS | Permissions.WRITE_TOOLS:
            self.assert_action("review", name, {"path": "note.txt", "cwd": str(self.project)}, state)
        # Absolute approved project paths remain available from an unapproved cwd.
        for name, args in self.scoped_calls(self.project / "note.txt"):
            self.assert_action("allow", name, args, state)

    def test_relative_paths_use_the_actual_host_base_and_resolve_cwd_once(self):
        subdir = self.workspace / "sub"
        subdir.mkdir()
        state = dict(self.state, execution_cwd=str(subdir))
        for name, args in self.scoped_calls("../note.txt"):
            self.assert_action("allow", name, args, state)
        for name in Permissions.CODE_TOOLS:
            self.assert_action("allow", name, {"cwd": "..", "command": "cat note.txt",
                                               "code": "open('note.txt').read()"}, state)
            self.assert_action("review", name, {"cwd": "../../session-b", "command": "echo ok",
                                                "code": "print('ok')"}, state)
        state = {"execution_settings": {"roots": [str(self.project)]}}
        for name, args in self.scoped_calls("note.txt"):
            self.assert_action("review", name, args, state)
        # A trusted workspace also supplies the host's default base if cwd is absent.
        state["session_workspace_root"] = str(self.workspace)
        for name, args in self.scoped_calls("note.txt"):
            self.assert_action("allow", name, args, state)

    def test_credentials_destruction_explicit_rules_and_readonly_still_apply(self):
        calls = [("astrbot_file_read_tool", {"path": ".env"}),
                 ("astrbot_execute_shell", {"command": "cat .ssh/id_ed25519"}),
                 ("astrbot_execute_shell", {"command": "rm -rf ."}),
                 ("astrbot_execute_shell", {"command": "rm *"}),
                 ("astrbot_execute_python", {"code": "import shutil; shutil.rmtree('cache')"}),
                 ("astrbot_execute_python", {"code": "db.execute('DROP TABLE users')"}),
                 ("astrbot_execute_python", {"code": "db.execute('DELETE FROM users')"}),
                 ("astrbot_execute_shell", {"command": 'sqlite3 local.db "DROP TABLE users"'})]
        for mode in ("standard", "full"):
            state = dict(self.state, execution_settings={"mode": mode, "roots": [str(self.project)]})
            for name, args in calls:
                self.assert_action("review", name, args, state)
        state = dict(self.state, execution_settings={"roots": [str(self.project)], "warnings": ["审批:astrbot_file_write_tool"]})
        self.assert_action("review", "astrbot_file_write_tool", {"path": "deploy.py"}, state)
        state = dict(self.state, execution_settings={"mode": "readonly", "roots": [str(self.project)]})
        self.assert_action("allow", "astrbot_file_read_tool", {"path": "note.txt"}, state)
        self.assert_action("deny", "astrbot_file_write_tool", {"path": "note.txt"}, state)
        self.assert_action("deny", "astrbot_execute_shell", {"command": "python check.py"}, state)

    def test_task_results_remain_a_read_only_exception(self):
        result = self.archive / "tool_results" / "call.txt"
        result.write_text("full tool result", encoding="utf-8")
        for path in (str(result), os.path.relpath(result, self.workspace)):
            for name in Permissions.READ_TOOLS:
                self.assert_action("allow", name, {"path": path})
            for name, args in self.scoped_calls(path):
                if name not in Permissions.READ_TOOLS:
                    self.assert_action("review", name, args)
        self.assertEqual(result.read_text(encoding="utf-8"), "full tool result")
        for path in (self.archive / ".." / "task-b" / "tool_results" / "call.txt",
                     self.archive / "tool_results" / ".env.txt", self.archive / "tool_results" / "blob.bin"):
            self.assert_action("review", "astrbot_file_read_tool", {"path": str(path)})
        self.assertEqual(Permissions.execution_roots(self.state), [str(self.project), str(self.workspace)])

    def test_real_symlinks_and_traversal_cannot_escape_or_hide_credentials(self):
        (self.other / "child").mkdir()
        (self.other / "child" / "private.txt").write_text("other session", encoding="utf-8")
        (self.other / "private.txt").write_text("other session", encoding="utf-8")
        (self.workspace / "private.txt").write_text("own session", encoding="utf-8")
        (self.workspace / ".ssh").mkdir()
        (self.workspace / ".ssh" / "settings.txt").write_text("fixture secret", encoding="utf-8")

        def directory_link(link, target):
            try:
                link.symlink_to(target, target_is_directory=True)
            except OSError as exc:
                if os.name != "nt":
                    self.skipTest(f"Host cannot create symlinks: {exc}")
                # NTFS junctions exercise real resolution without symlink privileges.
                environment = dict(os.environ, TASK_TEST_LINK=str(link), TASK_TEST_TARGET=str(target))
                process = subprocess.run([
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "New-Item -ItemType Junction -Path $env:TASK_TEST_LINK "
                    "-Target $env:TASK_TEST_TARGET -ErrorAction Stop | Out-Null",
                ], env=environment, capture_output=True, text=True, timeout=10)
                self.assertEqual(process.returncode, 0, process.stderr)

        directory_link(self.workspace / "link", self.other / "child")
        directory_link(self.workspace / "alias", self.workspace / ".ssh")
        directory_link(self.archive / "tool_results" / "link", self.other / "child")
        for name, args in self.scoped_calls("link/private.txt"):
            self.assert_action("review", name, args)
        # Windows collapses '..' before following the junction; POSIX follows
        # the link first. Verify against real I/O instead of assuming either.
        traversal = "link/../private.txt"
        self.assertEqual((self.workspace / traversal).read_text(encoding="utf-8"),
                         "own session" if os.name == "nt" else "other session")
        for name, args in self.scoped_calls(traversal):
            self.assert_action("allow" if os.name == "nt" else "review", name, args)
        self.assert_action("review", "astrbot_file_read_tool", {"path": "alias/settings.txt"})
        self.assert_action("review", "astrbot_file_read_tool", {"path": str(self.archive / "tool_results" / "link" / "private.txt")})
        self.assertEqual((self.other / "private.txt").read_text(encoding="utf-8"), "other session")


if __name__ == "__main__":
    unittest.main()
