"""Task scope, reviewable operations and the execution-time approval rule."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import ntpath
import posixpath
import re
import shlex
from pathlib import Path


READ_TOOLS = {"astrbot_file_read_tool", "astrbot_grep_tool", "astrbot_list_directory"}
WRITE_TOOLS = {"astrbot_file_write_tool", "astrbot_file_edit_tool"}
CODE_TOOLS = {"astrbot_execute_shell", "astrbot_execute_python", "astrbot_execute_ipython",
              "astrbot_sandboxed_shell", "astrbot_sandboxed_python", "astrbot_shell_session"}
SECRET_PATH = re.compile(r"(?:^|[/\\])(?:\.env(?:\.[^/\\]*)?|\.ssh|\.git-credentials|credentials(?:\.[^/\\]*)?|id_(?:rsa|ed25519)|[^/\\]+\.pem)(?:$|[/\\])", re.I)
SAFE_SHELL = {"pwd", "ls", "cat", "head", "tail", "rg", "grep", "wc", "stat", "dir", "type"}


def apply_mode(spec, state):
    if (state.get("execution_settings", {}).get("mode") == "full"
            and spec.isolation_policy.tool_mode != "no_external"
            and "__agent_lab_no_external_tools__" not in spec.enabled_tools):
        spec.isolation_policy.tool_mode = "full"
    return spec


def signature(name, arguments, state, resource):
    body = [name, arguments, resource, state.get("version"), state.get("current_step_id"), state.get("input_revision", 0)]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def within(path, root):
    module = ntpath if ntpath.splitdrive(path)[0] or ntpath.splitdrive(root)[0] else posixpath
    if not module.isabs(path) or not module.isabs(root):
        return False
    # Declared scope is advisory. Use canonical local paths where available;
    # the host still enforces real filesystem access, including sandbox paths.
    if Path(path).is_absolute() and Path(root).is_absolute():
        path, root = str(Path(path).resolve()), str(Path(root).resolve())
    try:
        p, r = (module.normcase(module.normpath(v)) for v in (path, root))
        return module.commonpath((p, r)) == r
    except ValueError:
        return False


def assess(name, args, state, risk="work", description=""):
    policy = state.get("execution_settings") or {}
    mode = policy.get("mode", "standard")
    roots = policy.get("roots", []) + state.get("scope_roots", [])
    warnings = policy.get("warnings", []) + state.get("risk_lines", [])
    paths = [args[k] for k in ("path", "file_path", "directory", "cwd", "target", "url") if isinstance(args.get(k), str)]
    command = args.get("command") if name in CODE_TOOLS else None
    read = name in READ_TOOLS or (name not in WRITE_TOOLS | CODE_TOOLS and risk == "safe" and not re.search(r"send|upload|publish|delete|write|edit|exec", name, re.I))
    dangerous = risk == "high" or name == "agent_lab_call_custom_api" or bool(re.search(
        r"send|upload|publish|deploy|restart|secret|credential|delete|truncate|revoke|reset|(?:^|_)drop(?:_|$)", name, re.I))

    if isinstance(command, str) and not re.search(r"[;&|<>`$\r\n%!*?{}^~\\]", command):
        try:
            argv = shlex.split(command, posix=True)
        except ValueError:
            argv = []
        if argv:
            exe = argv[0]
            paths.extend(a for a in argv[1:] if a.startswith("/") or ntpath.splitdrive(a)[0])
            if exe in SAFE_SHELL and not any(a.startswith(("--pre", "--exec", "--config", "--files-from")) for a in argv[1:]):
                dangerous, read = False, True
            elif exe == "git" and len(argv) >= 2 and argv[1] in {"status", "diff", "log", "show", "ls-files", "rev-parse"} and not any(a.startswith(("--output", "--ext-diff", "--textconv")) for a in argv[2:]):
                dangerous, read = False, True
            elif exe in {"python", "python3", "py"} and (argv[1:3] in (["-m", "pytest"], ["-m", "unittest"], ["-m", "compileall"]) or argv[1:] == ["--version"]):
                dangerous = False
            elif exe in {"pytest", "ruff"} or (exe in {"npm", "pnpm"} and argv[1:] in (["test"], ["run", "build"], ["run", "test"], ["run", "lint"])):
                dangerous = False
            elif exe in {"rm", "unlink"} and len(argv) > 1 and all(not target.startswith("-") and (
                target in state.get("approved_cleanup_paths", []) or any(within(target, root) and not within(root, target)
                for root in policy.get("roots", []))) for target in argv[1:]):
                dangerous = False  # Explicit administrator root; named files, never recursive/glob.
            else:
                dangerous = True
    elif name in CODE_TOOLS:
        dangerous = True

    if name in WRITE_TOOLS and args.get("path") and Path(str(args["path"])).name.lower() in {"cmd_config.json", "config.json"} and not any(within(str(args["path"]), r) for r in policy.get("roots", [])):
        dangerous = True
    if any(SECRET_PATH.search(path) for path in paths):
        dangerous = True
    selector = [name, *paths]
    matched = [rule for rule in warnings if rule.startswith("审批:") and any(fnmatch.fnmatchcase(v, rule[3:].strip()) for v in selector)]
    if matched:
        dangerous = True
    outside = [path for path in dict.fromkeys(paths) if roots and (path.startswith("/") or ntpath.splitdrive(path)[0]) and not any(within(path, root) for root in roots)]
    return ("deny" if mode == "readonly" and not read else "review" if dangerous else "allow"), outside
