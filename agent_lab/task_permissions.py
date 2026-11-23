"""Task scope, reviewable operations and the execution-time approval rule."""
from __future__ import annotations

import ast
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
GUARD_RETRY_LIMIT = 3


def record_guard_refusal(task, reason):
    """Bound repeated refusals across parameter changes and harmless read calls."""
    state = task.workflow_data.setdefault("task_control", {})
    key = state.get("current_step_id", "")
    previous = state.get("guard_refusals", {})
    count = previous.get("count", 0) + 1 if previous.get("key") == key else 1
    state["guard_refusals"] = {"key": key, "count": count, "reason": reason}
    if count < GUARD_RETRY_LIMIT:
        return ""
    message = f"本阶段已有 {count} 次操作被安全兜底拒绝，已暂停自动执行，避免反复尝试。最后原因：{reason}"
    state["human_paused"] = True
    task.status = "paused"
    task.watchdog.paused_reason = message
    task.watchdog.last_decision = "guard_retry_limit"
    task.set_wait(wait_reason="guard_retry_limit", message=message, source="execution_guard", resume_command="任务继续")
    task.add_log("guard_retry_limit", message)
    return message


def authorized_roots(state):
    """Administrator roots win; an approved plan supplies the legacy fallback."""
    configured = (state.get("execution_settings") or {}).get("roots", [])
    if configured:
        return configured
    if "authorized_scope_roots" in state:
        return state["authorized_scope_roots"]
    if state.get("approved_version") and state.get("approved_version") == state.get("version"):
        return state.get("scope_roots", [])
    return []


def execution_guidance(state):
    mode = (state.get("execution_settings") or {}).get("mode", "standard")
    if mode == "full":
        return ("完全权限：已授权范围内自主执行目录查询、搜索、新建和修改文件、Shell/Python、测试及少量明确文件清理，"
                "无需逐项申请，不因连接命令、重定向或工具类型而送审。只在越出授权范围、清空项目/目录、批量破坏数据、"
                "读取凭证或命中管理员明确审批线时，先主动调用 agent_lab_request_approval，提交确切工具与参数。"
                "后端拒绝仅表示该动作未执行，不会自动代你申请；改用合规方案或主动申请。"
                "同一阶段累计3次被兜底拒绝会暂停自动执行，修改危险参数或插入普通查询不会清零；不要反复试探。"
                "当前权限档位优先于通用工具风险标签；不能因为工具标签为 high 或旧说明泛称删除危险就为普通清理申请。"
                "授权范围只能由管理员扩大；未配置路径范围时沿用宿主访问限制，不能声称已经具备文件系统隔离。")
    if mode == "readonly":
        return "只读权限：只做读取与查询，不写入、不清理、不执行有副作用的动作；审批不能代替管理员切换权限档位。"
    return "标准开发：普通读取、明确文件写入和常规测试直接执行；危险操作先主动汇总工具与参数申请审批。预计范围外普通关联操作提醒管理员。"


def _absolute(value):
    return posixpath.isabs(value) or ntpath.isabs(value)


def _tokens(command):
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        lexer.escape = ""  # Preserve Windows paths when reviewing on a Unix host.
        return list(lexer)
    except ValueError:
        return []


def _destructive_query(text):
    return bool(re.search(r"\b(?:drop\s+(?:database|schema|table)|truncate\s+(?:table\s+)?[\w.]+)\b", text, re.I)
                or re.search(r"\bdelete\s+from\b", text, re.I) and not re.search(r"\bwhere\b", text, re.I)
                or re.search(r"\b(?:delete_many|deleteMany)\s*\(\s*\{\s*\}\s*\)", text))


def full_guard(name, args, state, _depth=0):
    """Narrow guard for explicit paths/destructive operations, not a code sandbox.

    General programs cannot be proven safe by inspecting their text. The host
    remains responsible for OS/sandbox isolation; unrecognised code is not
    turned into another blanket approval gate.
    """
    roots = authorized_roots(state)
    paths, deletions = [], []
    for key in ("path", "file_path", "directory", "cwd", "target", "source", "destination", "dest", "paths", "files", "targets"):
        value = args.get(key)
        paths.extend([value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else [])
    cwd = args.get("cwd") or state.get("execution_cwd")
    destructive = False
    database_command = False
    command = args.get("command", "") if name in CODE_TOOLS else ""
    if isinstance(command, str):
        tokens = _tokens(command)
        segment = []
        redirect = False
        for token in [*tokens, ";"]:
            if token in {">", ">>", "<", "2>", "2>>"}:
                redirect = True
                continue
            if redirect:
                redirect = False
                if token not in {"/dev/null", "/dev/stdout", "/dev/stderr", "NUL", "nul"}:
                    paths.append(token)
                continue
            if token in {";", "&&", "||", "|", "&", "\n", "(", ")"} or token and set(token) <= {";", "\n"}:
                if segment:
                    exe = ntpath.basename(segment[0]).lower().removesuffix(".exe")
                    database_command |= exe in {"mysql", "mariadb", "psql", "sqlite3", "sqlcmd", "mongosh", "mongo", "cqlsh"}
                    if exe in SAFE_SHELL - {"rg", "grep", "wc", "pwd"} | {"mkdir", "touch", "cp", "mv", "rm", "unlink", "rmdir", "del", "erase", "rd", "remove-item", "ri"}:
                        operands = [v for v in segment[1:] if not v.startswith("-") and not v.isdecimal()
                                    and v.lower() not in {"/s", "/q", "/f", "/b", "/a", "/d"}]
                        paths.extend(operands if operands else [cwd] if cwd else [])
                    if exe in {"rm", "unlink", "rmdir", "del", "erase", "rd", "remove-item", "ri"}:
                        targets = [v for v in segment[1:] if not v.startswith("-") and v.lower() not in {"/s", "/q", "/f"}]
                        deletions.extend(targets)
                        recursive = any(v.lower() in {"--recursive", "-recurse", "/s"} or
                                        v.startswith("-") and "r" in v[1:].lower() and not v.startswith("--") for v in segment[1:])
                        destructive |= recursive and any(not posixpath.splitext(v.replace("\\", "/"))[1] for v in targets)
                    if exe == "find" and ("-delete" in segment or any(v in {"rm", "unlink", "rmdir"} for v in segment[1:])):
                        narrowed = any(v in {"-name", "-iname", "-path", "-ipath"} and i+1 < len(segment)
                                       and segment[i+1] not in {"*", "**", "./*"} for i, v in enumerate(segment))
                        destructive |= not narrowed
                    if exe in {"mkfs", "format", "diskpart", "wipefs", "shred"} or exe.startswith("mkfs."):
                        destructive = True
                    if exe == "git" and any(v in {"clean", "--hard"} for v in segment[1:]):
                        destructive = True
                    if exe == "dd" and any(v.startswith("of=/dev/") for v in segment[1:]):
                        destructive = True
                    if exe in {"cd", "chdir", "set-location"} and len(segment) > 1:
                        target = segment[-1]
                        if _absolute(target):
                            cwd = target
                        elif cwd:
                            module = ntpath if ntpath.splitdrive(cwd)[0] else posixpath
                            cwd = module.normpath(module.join(cwd, target))
                        else:
                            paths.append(target)
                    segment = []
            elif token not in {">", ">>", "<", "2", "1"}:
                segment.append(token)
            candidate = token.split("=", 1)[-1] if "=" in token else token
            if candidate.lower() in {"/s", "/q", "/f", "/b", "/a", "/d", "/c"} and segment and ntpath.basename(segment[0]).lower() in {"cmd", "cmd.exe", "del", "erase", "rd", "rmdir", "dir"}:
                continue
            if _absolute(candidate) or candidate.startswith(("./", "../", ".\\", "..\\")):
                paths.append(candidate)
        if database_command and _destructive_query(command):
            destructive = True
    code = args.get("code", args.get("script", "")) if name in CODE_TOOLS else ""
    # Include Python passed through `python -c`, without treating file contents
    # written by a file tool as commands that are about to execute.
    if isinstance(command, str):
        tokens = _tokens(command)
        if "-c" in tokens and tokens.index("-c") + 1 < len(tokens) and any("python" in t.lower() for t in tokens[:tokens.index("-c")]):
            code = tokens[tokens.index("-c") + 1]
    if isinstance(code, str) and code:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            tree = None
        if tree:
            calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
            delete_calls = [node for node in calls if isinstance(node.func, ast.Attribute)
                            and node.func.attr in {"remove", "unlink", "rmdir", "rmtree"}]
            if delete_calls and any(isinstance(node, (ast.For, ast.comprehension)) for node in ast.walk(tree)):
                for node in calls:
                    func = node.func.attr if isinstance(node.func, ast.Attribute) else ""
                    if func in {"listdir", "scandir", "walk"} or (func in {"glob", "rglob"}
                            and node.args and isinstance(node.args[0], ast.Constant)
                            and node.args[0].value in {"*", "**", "**/*", "*.*"}):
                        destructive = True
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
                literals = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
                if func in {"execute", "executemany", "executescript", "query"} and any(_destructive_query(v) for v in literals):
                    destructive = True
                if func in {"open", "Path", "remove", "unlink", "rmdir", "rmtree", "listdir", "scandir", "chdir", "walk", "rename"}:
                    paths.extend(literals[:2] if func in {"rename", "replace"} else literals[:1])
                if func in {"remove", "unlink", "rmdir", "rmtree"}:
                    deletions.extend(literals[:1])
                    destructive |= func == "rmtree"
                    if not literals and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                        deletions.extend(a.value for a in node.func.value.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
                if func in {"system", "run", "Popen", "check_call", "check_output"} and literals and _depth < 3:
                    nested_reason, nested_outside = full_guard("astrbot_execute_shell", {"command": literals[0]}, state, _depth+1)
                    if nested_reason:
                        return nested_reason, nested_outside
        if re.search(r"\b(?:drop_database|drop_collection|delete_many|truncate)\s*\(", code):
            destructive = True
    if any(isinstance(args.get(key), str) and _destructive_query(args[key]) for key in ("sql", "query", "statement")):
        destructive = True
    if re.search(r"(?:^|_)(?:delete|remove|unlink|rmdir)(?:_|$)", name, re.I):
        deletions.extend(paths)
    paths.extend(deletions)
    resolved = []
    for path in paths:
        if "://" in path:
            continue
        if not _absolute(path) and cwd:
            module = ntpath if ntpath.splitdrive(cwd)[0] else posixpath
            path = module.normpath(module.join(cwd, path))
        resolved.append(path)
    outside = list(dict.fromkeys(p for p in resolved if roots and (
        (_absolute(p) and not any(within(p, root) for root in roots))
        or (not _absolute(p) and ".." in p.replace("\\", "/").split("/")))))
    for target in deletions:
        normalized = target.replace("\\", "/").rstrip("/")
        if normalized in {"", ".", "..", "*", ".*"} or normalized.rsplit("/", 1)[-1] in {"*", ".*", "**", "*.*"}:
            destructive = True
        if not _absolute(target) and cwd:
            module = ntpath if ntpath.splitdrive(cwd)[0] else posixpath
            target = module.normpath(module.join(cwd, target))
        if (_absolute(target) and (target.rstrip("/\\") in {"", ntpath.splitdrive(target)[0]} or
                any(within(root, target) for root in roots))):
            destructive = True
    warnings = (state.get("execution_settings") or {}).get("warnings", []) + state.get("risk_lines", [])
    matched = any(rule.startswith("审批:") and any(fnmatch.fnmatchcase(v, rule[3:].strip()) for v in [name, *resolved]) for rule in warnings)
    sensitive = any(SECRET_PATH.search(p) for p in resolved)
    if outside:
        return "超出管理员授权路径：" + "、".join(outside), outside
    if destructive or len(set(deletions)) > 20 or re.search(r"(?:^|_)(?:delete_all|remove_all|wipe|drop_database|drop_schema|drop_table)(?:_|$)", name, re.I):
        return "清空目录、批量删除或其他破坏性操作需要先主动申请批准。", []
    if sensitive or re.search(r"(?:^|_)(?:secret|credential|password)(?:_|$)", name, re.I):
        return "访问凭证或敏感路径需要先主动申请批准。", []
    if matched:
        return "命中管理员明确设置的审批规则，需要先主动申请批准。", []
    return "", []


def apply_mode(spec, state):
    if (state.get("execution_settings", {}).get("mode") == "full"
            and spec.isolation_policy.tool_mode != "no_external"
            and "__agent_lab_no_external_tools__" not in spec.enabled_tools):
        spec.isolation_policy.tool_mode = "full"
    return spec


def signature(name, arguments, state, resource):
    body = [name, arguments, resource, state.get("authorization_version", state.get("version")),
            state.get("current_step_id"), state.get("input_revision", 0)]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def within(path, root):
    module = ntpath if ntpath.splitdrive(path)[0] or ntpath.splitdrive(root)[0] else posixpath
    if not module.isabs(path) or not module.isabs(root):
        return False
    # Resolve local symlinks where possible. This is a guard, not OS isolation.
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
    if mode == "full":
        reason, outside = full_guard(name, args, state)
        return ("review" if reason else "allow"), outside
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
