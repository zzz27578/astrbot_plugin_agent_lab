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
SECRET_PATH = re.compile(r"(?:^|[/\\])(?:\.env(?:\.[^/\\]*)?|\.ssh|\.aws|\.git-credentials|\.npmrc|\.pypirc|credentials(?:\.[^/\\]*)?|id_(?:rsa|ecdsa|ed25519)|[^/\\]+\.(?:pem|key|p12|pfx))(?:$|[/\\])", re.I)
SAFE_SHELL = {"pwd", "ls", "cat", "head", "tail", "rg", "grep", "wc", "stat", "dir", "type",
              "get-content", "get-childitem", "get-location", "select-string", "test-path",
              "select-object", "measure-object"}
GUARD_RETRY_LIMIT = 3  # Compatibility/telemetry only; never a pause threshold.
UNRESOLVED_PATH_REASON = "路径变量尚未解析"


def record_guard_refusal(task, reason):
    """Record a refusal without stopping execution (legacy bridge API).

    Always return an empty string: older callers interpret any nonempty return
    as an instruction to stop. Feed failed results to progress_guard.observe_tool
    for actual consecutive-error detection and its warning-before-pause policy.
    """
    state = task.workflow_data.setdefault("task_control", {})
    key = state.get("current_step_id", "")
    previous = state.get("guard_refusals", {})
    count = previous.get("count", 0) + 1 if previous.get("key") == key else 1
    state["guard_refusals"] = {"key": key, "count": count, "reason": reason}
    return ""


def authorized_roots(state):
    """Explicit project authority only; never persist a session workspace here."""
    configured = (state.get("execution_settings") or {}).get("roots", [])
    if configured:
        return configured
    if "authorized_scope_roots" in state:
        return state["authorized_scope_roots"]
    if state.get("approved_version") and state.get("approved_version") == state.get("version"):
        return state.get("scope_roots", [])
    return []


def session_workspace_root(state):
    """Return only the exact workspace resolved by the trusted host bridge.

    This helper performs no I/O. The bridge must set this field only after
    workspace_root_for_context succeeds for the current session, and discard
    stale values before resolving another context. Neither model arguments nor
    execution_cwd establish workspace authority.
    """
    root = state.get("session_workspace_root")
    if isinstance(root, str) and root and _absolute(root) and "\x00" not in root:
        return root
    return ""


def execution_roots(state):
    """Union explicit project roots with one trusted session root, without I/O."""
    roots = list(authorized_roots(state))
    workspace = session_workspace_root(state)
    if workspace and workspace not in roots:
        roots.append(workspace)
    return roots


def execution_guidance(state):
    mode = (state.get("execution_settings") or {}).get("mode", "standard")
    if mode == "readonly":
        return "只读权限：只做读取与查询，不写入、不清理、不执行有副作用的动作；审批不能代替管理员切换权限档位。"
    return ("授权目录和宿主确认的当前会话工作区内普通读取、搜索、写入、Shell/Python 和测试直接执行，无需逐项申请。"
            "明确越界、清空或递归删除目录、访问敏感凭据、破坏数据库或系统以及管理员明确审批规则需先请示。"
            "被拒绝的动作未执行；调整方法或主动提交确切工具与参数申请。"
            "授权范围只能由管理员扩大；未配置目录时沿用宿主访问限制，本检查不替代系统隔离。")


def _absolute(value):
    return posixpath.isabs(value) or ntpath.isabs(value)


def _resolve(value, cwd):
    if not _absolute(value) and cwd:
        module = ntpath if ntpath.splitdrive(cwd)[0] else posixpath
        # Keep '..' until within() follows local symlinks. Collapsing it first
        # could turn workspace/link/../file into an apparently in-scope path.
        return module.join(cwd, value)
    return value


def _sensitive(path):
    if SECRET_PATH.search(path):
        return True
    try:
        return Path(path).is_absolute() and bool(SECRET_PATH.search(str(Path(path).resolve())))
    except (OSError, RuntimeError, ValueError):
        return True


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


_VARIABLE = re.compile(r"\$\{([A-Za-z_]\w*)\}|\$(?:env:)?([A-Za-z_]\w*)|%([A-Za-z_]\w*)%")


def _scope_shell_tokens(command, environment):
    """Expand declared literal variables only; never execute shell substitution."""
    env = {str(k):str(v) for k,v in environment.items()} if isinstance(environment, dict) else {}
    tokens, segment = [], []
    single_quoted = set(re.findall(r"'([^']*\$[^']*)'", command))
    def expand(value):
        if value in single_quoted:
            return value
        return _VARIABLE.sub(lambda m: env.get(next(v for v in m.groups() if v is not None), m.group()), value)
    for token in [*_tokens(command), ";"]:
        if token in {";", "&&", "||", "|", "\n"}:
            statement = segment[1:] if segment and segment[0].lower() in {"export", "set"} else segment
            assignments = []
            if len(statement) == 3 and statement[1] == "=" and re.fullmatch(r"\$(?:env:)?[A-Za-z_]\w*", statement[0]):
                assignments = [(statement[0].removeprefix("$env:").removeprefix("$"), statement[2])]
            elif statement and all(re.match(r"^[A-Za-z_]\w*=", value) for value in statement):
                assignments = [value.split("=", 1) for value in statement]
            if assignments:
                for key, value in assignments:
                    env[key] = expand(value)
            else:
                tokens.extend(expand(value) for value in segment)
            tokens.append(token)
            segment = []
        else:
            segment.append(token)
    return tokens


def read_only_call(name, args):
    """Only explicitly read-only tools qualify for in-round result reuse."""
    if name in READ_TOOLS:
        return True
    if name not in {"astrbot_execute_shell", "astrbot_sandboxed_shell"}:
        return False
    command = args.get("command", "")
    if not isinstance(command, str) or re.search(r"[`$]", command):
        return False
    tokens = _tokens(command)
    if not tokens:
        return False
    segment, segments = [], []
    for token in [*tokens, ";"]:
        if token in {";", "&&", "||", "|", "\n"}:
            if segment:
                segments.append(segment)
            segment = []
        else:
            segment.append(token)
    for argv in segments:
        if any(v in {">", ">>", "<", "&", "(", ")"} for v in argv):
            return False
        exe = ntpath.basename(argv[0]).lower().removesuffix(".exe")
        if exe == "git" and argv[1:2] and argv[1] in {"status", "diff", "log", "show", "ls-files", "rev-parse"}:
            if any(v.startswith(("--output", "--ext-diff", "--textconv")) for v in argv[2:]):
                return False
            continue
        if exe not in SAFE_SHELL | {"find"}:
            return False
        if any(v.startswith(("--pre", "--exec", "--config", "--files-from")) or
               v in {"-delete", "-exec", "-execdir", "-fprint", "-fprintf", "-fls"} for v in argv[1:]):
            return False
    return bool(segments)


def _destructive_query(text):
    return bool(re.search(r"\b(?:drop\s+(?:database|schema|table)|truncate\s+(?:table\s+)?[\w.]+)\b", text, re.I)
                or any(re.search(r"\bdelete\s+from\b", statement, re.I) and not re.search(r"\bwhere\b", statement, re.I)
                       for statement in text.split(";"))
                or re.search(r"\b(?:delete_many|deleteMany)\s*\(\s*\{\s*\}\s*\)", text))


def full_guard(name, args, state, _depth=0):
    """Narrow guard for explicit paths/destructive operations, not a code sandbox.

    General programs cannot be proven safe by inspecting their text. The host
    remains responsible for OS/sandbox isolation; unrecognised code is not
    turned into another blanket approval gate.
    """
    roots = execution_roots(state)
    host_cwd = state.get("execution_cwd") or session_workspace_root(state)
    host_cwd = host_cwd if isinstance(host_cwd, str) and _absolute(host_cwd) else ""
    # File tools resolve from the host workspace; a model-supplied cwd cannot
    # retarget them. Code tools may explicitly request a different process cwd,
    # which is itself checked against the same roots below.
    requested_cwd = args.get("cwd")
    cwd = (_resolve(requested_cwd, host_cwd)
           if name in CODE_TOOLS and isinstance(requested_cwd, str) and requested_cwd else host_cwd)
    paths, deletions = [], []
    def add_paths(values):
        paths.extend(_resolve(value, cwd) for value in values)
    for key in ("path", "file_path", "directory", "cwd", "target", "source", "destination", "dest", "paths", "files", "targets"):
        value = args.get(key)
        values = [value] if isinstance(value, str) else [v for v in value if isinstance(v, str)] if isinstance(value, list) else []
        if key == "cwd":
            paths.extend(_resolve(value, host_cwd) for value in values)
        else:
            add_paths(values)
    destructive = False
    database_command = False
    command = args.get("command", "") if name in CODE_TOOLS else ""
    if isinstance(command, str):
        tokens = _scope_shell_tokens(command, args.get("env", {}))
        segment = []
        redirect = False
        for token in [*tokens, ";"]:
            if token in {">", ">>", "<", "2>", "2>>"}:
                redirect = True
                continue
            if redirect:
                redirect = False
                if token not in {"/dev/null", "/dev/stdout", "/dev/stderr", "NUL", "nul"}:
                    add_paths([token])
                continue
            if token in {";", "&&", "||", "|", "&", "\n", "(", ")"} or token and set(token) <= {";", "\n"}:
                if segment:
                    exe = ntpath.basename(segment[0]).lower().removesuffix(".exe")
                    database_command |= exe in {"mysql", "mariadb", "psql", "sqlite3", "sqlcmd", "mongosh", "mongo", "cqlsh"}
                    if exe in SAFE_SHELL - {"rg", "grep", "wc", "pwd"} | {"mkdir", "touch", "cp", "mv", "rm", "unlink", "rmdir", "del", "erase", "rd", "remove-item", "ri"}:
                        operands = [v for v in segment[1:] if not v.startswith("-") and not v.isdecimal()
                                    and v.lower() not in {"/s", "/q", "/f", "/b", "/a", "/d"}]
                        add_paths(operands if operands else [cwd] if cwd else [])
                    if exe == "find":
                        bases = []
                        for value in segment[1:]:
                            if value.startswith("-") or value in {"(", ")"}:
                                break
                            bases.append(value)
                        add_paths(bases or ([cwd] if cwd else []))
                    if exe in {"rm", "unlink", "rmdir", "del", "erase", "rd", "remove-item", "ri"}:
                        targets = [v for v in segment[1:] if not v.startswith("-") and v.lower() not in {"/s", "/q", "/f"}]
                        deletions.extend(_resolve(v, cwd) for v in targets)
                        recursive = any(v.lower() in {"--recursive", "-recurse", "/s"} or
                                        v.startswith("-") and "r" in v[1:].lower() and not v.startswith("--") for v in segment[1:])
                        destructive |= recursive
                    if exe == "find" and ("-delete" in segment or any(v in {"rm", "unlink", "rmdir"} for v in segment[1:])):
                        narrowed = any(v in {"-name", "-iname", "-path", "-ipath"} and i+1 < len(segment)
                                       and segment[i+1] not in {"*", "**", "./*"} for i, v in enumerate(segment))
                        destructive |= not narrowed
                    if exe in {"mkfs", "format", "diskpart", "wipefs", "shred", "shutdown", "reboot", "halt",
                               "stop-computer", "restart-computer", "clear-disk", "remove-partition"} or exe.startswith("mkfs."):
                        destructive = True
                    if exe == "redis-cli" and any(v.upper() in {"FLUSHALL", "FLUSHDB"} for v in segment[1:]):
                        destructive = True
                    if exe == "git" and ("--hard" in segment[1:] or
                            "clean" in segment[1:] and not any(v in {"-n", "--dry-run"} for v in segment[1:])):
                        destructive = True
                    if exe == "dd" and any(v.startswith("of=/dev/") for v in segment[1:]):
                        destructive = True
                    if exe in {"cd", "chdir", "set-location"} and len(segment) > 1:
                        target = segment[-1]
                        if _absolute(target):
                            cwd = target
                        elif cwd:
                            cwd = _resolve(target, cwd)
                        else:
                            add_paths([target])
                        if cwd:
                            paths.append(cwd)
                    segment = []
            elif token not in {">", ">>", "<", "2", "1"}:
                segment.append(token)
            candidate = token.split("=", 1)[-1] if "=" in token else token
            if candidate.lower() in {"/s", "/q", "/f", "/b", "/a", "/d", "/c"} and segment and ntpath.basename(segment[0]).lower() in {"cmd", "cmd.exe", "del", "erase", "rd", "rmdir", "dir"}:
                continue
            literal_output = segment and ntpath.basename(segment[0]).lower() in {"echo", "printf", "write-output"}
            if not literal_output and (_absolute(candidate) or candidate.startswith(("./", "../", ".\\", "..\\"))):
                add_paths([candidate])
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
                    add_paths(literals[:2] if func in {"rename", "replace"} else literals[:1])
                if func in {"remove", "unlink", "rmdir", "rmtree"}:
                    deletions.extend(_resolve(v, cwd) for v in literals[:1])
                    destructive |= func == "rmtree"
                    if not literals and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Call):
                        deletions.extend(_resolve(a.value, cwd) for a in node.func.value.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
                if func in {"system", "run", "Popen", "check_call", "check_output"} and node.args and _depth < 3:
                    nested = literals[0] if literals else ""
                    if isinstance(node.args[0], (ast.List, ast.Tuple)):
                        argv = node.args[0].elts
                        if all(isinstance(a, ast.Constant) and isinstance(a.value, str) for a in argv):
                            nested = shlex.join([a.value for a in argv])
                    # An inherited process cwd resolves relative operands; it
                    # is not itself an additional filesystem access. Only an
                    # explicitly requested subprocess cwd is a scope target.
                    nested_args = {"command": nested}
                    for keyword in node.keywords:
                        if keyword.arg == "cwd" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                            nested_args["cwd"] = _resolve(keyword.value.value, cwd)
                    nested_reason, nested_outside = full_guard(
                        "astrbot_execute_shell", nested_args, dict(state, execution_cwd=cwd), _depth+1)
                    if nested_reason:
                        return nested_reason, nested_outside
        if re.search(r"\b(?:drop_database|drop_collection)\s*\(", code) or re.search(r"\b(?:delete_many|deleteMany)\s*\(\s*\{\s*\}\s*\)", code):
            destructive = True
    if any(isinstance(args.get(key), str) and _destructive_query(args[key]) for key in ("sql", "query", "statement")):
        destructive = True
    if re.search(r"(?:^|_)(?:delete|remove|unlink|rmdir)(?:_|$)", name, re.I):
        deletions.extend(paths)
        destructive |= bool(args.get("recursive") or args.get("recurse"))
    paths.extend(deletions)
    resolved = []
    for path in paths:
        if "://" in path:
            continue
        if _VARIABLE.search(path) or "$(" in path:
            continue
        resolved.append(path)
    # Result archives are readable through host file tools, but never become
    # general execution/write roots. within() resolves symlinks before approval.
    archive_root = state.get("task_data_root")
    def archive_read(path):
        return (name in READ_TOOLS and isinstance(archive_root, str)
                and posixpath.splitext(path.replace("\\", "/"))[1].lower() in {".txt", ".log", ".md", ".json", ".jsonl"}
                and within(path, archive_root) and not _sensitive(path))
    outside = list(dict.fromkeys(p for p in resolved if roots and not archive_read(p) and (
        (_absolute(p) and not any(within(p, root) for root in roots))
        or (not _absolute(p) and (name in READ_TOOLS | WRITE_TOOLS | CODE_TOOLS
                                 or ".." in p.replace("\\", "/").split("/"))))))
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
    sensitive = any(_sensitive(p) for p in [*resolved, *paths])
    if outside:
        return "超出管理员授权路径：" + "、".join(outside), outside
    if destructive or len(set(deletions)) > 20 or re.search(r"(?:^|_)(?:delete_all|remove_all|wipe|drop_database|drop_schema|drop_table|delete_directory|remove_directory|clear_directory|rmtree)(?:_|$)", name, re.I):
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
    try:
        # Resolve local symlinks where possible. This is a guard, not OS isolation.
        if Path(path).is_absolute() and Path(root).is_absolute():
            path, root = str(Path(path).resolve()), str(Path(root).resolve())
        p, r = (module.normcase(module.normpath(v)) for v in (path, root))
        return module.commonpath((p, r)) == r
    except (OSError, RuntimeError, ValueError):
        return False


def assess(name, args, state, risk="work", description=""):
    """Both development modes use the same narrow guard; risk labels are hints.

    The bridge must supply execution_cwd (the host's actual working directory)
    for relative paths and session_workspace_root only from successful host
    workspace resolution. The latter adds authority without changing explicit
    project roots. Unknown program effects belong to host isolation, not a
    speculative per-command approval gate.
    """
    reason, outside = full_guard(name, args, state)
    return ("deny" if not mode_allows(name, args, state, risk) else "review" if reason else "allow"), outside


def mode_allows(name, args, state, risk="work"):
    """A one-off approval never overrides a current read-only policy."""
    mode = (state.get("execution_settings") or {}).get("mode", "standard")
    read = read_only_call(name, args) or (name not in WRITE_TOOLS | CODE_TOOLS and risk == "safe"
            and not re.search(r"send|upload|publish|delete|write|edit|exec", name, re.I))
    return mode != "readonly" or read
