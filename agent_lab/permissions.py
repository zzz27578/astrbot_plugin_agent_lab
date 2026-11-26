"""Permission checks, path scope guards, and credential exfiltration protection for Agent Lab v1.0.0."""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .models import Profile, TaskMeta

READ_TOOLS = frozenset(
    {"astrbot_file_read_tool", "astrbot_grep_tool", "astrbot_list_directory"}
)
WRITE_TOOLS = frozenset(
    {"astrbot_file_write_tool", "astrbot_file_edit_tool"}
)
CODE_TOOLS = frozenset(
    {
        "astrbot_execute_shell",
        "astrbot_execute_python",
        "astrbot_execute_ipython",
        "astrbot_sandboxed_shell",
        "astrbot_sandboxed_python",
        "astrbot_shell_session",
    }
)
CONTROL_TOOL_NAMES = (
    "task_plan",
    "task_progress",
    "task_ask",
    "task_approve",
    "task_finish",
)
DAILY_TOOL_NAMES = ("agent_lab_start_task", "agent_lab_control_task")

_SHELL_TOOLS = frozenset(
    {"astrbot_execute_shell", "astrbot_sandboxed_shell", "astrbot_shell_session"}
)
_PYTHON_TOOLS = frozenset(
    {
        "astrbot_execute_python",
        "astrbot_sandboxed_python",
        "astrbot_execute_ipython",
    }
)

_SAFE_SHELL_COMMANDS = frozenset(
    {
        "pwd",
        "ls",
        "cat",
        "head",
        "tail",
        "rg",
        "grep",
        "wc",
        "stat",
        "dir",
        "type",
        "get-content",
        "get-childitem",
        "get-location",
        "select-string",
    }
)
_SAFE_GIT_SUBCOMMANDS = frozenset(
    {"status", "diff", "log", "show", "ls-files", "rev-parse"}
)
_FORBIDDEN_GIT_FLAGS = frozenset({"--output", "--ext-diff", "--textconv"})
_FORBIDDEN_FIND_FLAGS = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fls", "-fprint", "-fprint0", "-fprintf"}
)

_PATH_ARG_KEYS = (
    "path",
    "file_path",
    "directory",
    "cwd",
    "target",
    "source",
    "destination",
    "dest",
    "paths",
    "files",
    "targets",
)

_TOOL_RESULT_EXTS = frozenset({".txt", ".log", ".md", ".json", ".jsonl"})

_SENSITIVE_DIR_NAMES = frozenset({".ssh", ".aws"})
_SENSITIVE_EXACT_NAMES = frozenset(
    {
        ".git-credentials",
        ".npmrc",
        ".pypirc",
        "secrets.key",
        "id_rsa",
        "id_ecdsa",
        "id_ed25519",
    }
)
_SENSITIVE_EXTS = frozenset({".pem", ".key", ".p12", ".pfx"})
_SENSITIVE_KEY_STEM_RE = re.compile(
    r"^(?:id_rsa|id_ecdsa|id_ed25519)(?:\.(?!pub$).+)?$", re.IGNORECASE
)

_MUTATING_NAME_TOKENS = frozenset(
    {
        "write",
        "edit",
        "delete",
        "del",
        "remove",
        "rm",
        "unlink",
        "create",
        "add",
        "insert",
        "update",
        "modify",
        "patch",
        "put",
        "post",
        "send",
        "upload",
        "execute",
        "exec",
        "run",
        "eval",
        "shell",
        "python",
        "bash",
        "cmd",
        "kill",
        "stop",
        "drop",
        "truncate",
        "chmod",
        "chown",
        "mkdir",
        "rmdir",
        "rename",
        "move",
        "copy",
        "save",
        "set",
        "install",
        "uninstall",
        "deploy",
        "publish",
        "commit",
        "push",
        "merge",
        "reset",
        "clean",
        "apply",
        "append",
        "overwrite",
    }
)

_SQL_DESTRUCTIVE_RE = re.compile(r"\b(?:DROP\s+(?:TABLE|DATABASE)|TRUNCATE\s+TABLE)\b", re.IGNORECASE)
_REDIS_DESTRUCTIVE_RE = re.compile(r"\b(?:FLUSHALL|FLUSHDB)\b", re.IGNORECASE)

_ENV_DUMP_SHELL_RE = re.compile(
    r"(?:^|[;&|\n\r])\s*(?:"
    r"printenv\b|"
    r"env(?:\s+-[0u]+|\s*$|\s*[|;&>\n\r])|"
    r"set(?:\s*$|\s*[|;&>\n\r])|"
    r"(?:export|declare|typeset)\s+-[px]+\b|"
    r"(?:get-childitem|gci|dir|ls|get-item|get-content|cat)\s+env:"
    r")",
    re.IGNORECASE,
)

_SHELL_OUTPUT_CMD_RE = re.compile(
    r"(?:^|[;&|\s'\"])(?:echo|printf|cat|write|print|tee|write-output|write-host|out-file|set-content|add-content)(?=\s|$)",
    re.IGNORECASE,
)


def _normalize_path_key(path: Path) -> str:
    return os.path.normcase(str(path))


def _resolve_path_safe(raw: str, base_dir: Path | None = None) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        p = Path(text)
        if not p.is_absolute():
            if base_dir is None:
                return None
            p = base_dir / p
        return p.resolve()
    except (OSError, ValueError, RuntimeError):
        return None


def execution_roots(task: TaskMeta) -> list[str]:
    """Return deduplicated valid absolute execution roots for a task."""
    candidates: list[str] = []
    if task.execution_settings and task.execution_settings.roots:
        candidates.extend(task.execution_settings.roots)
    if task.authorized_scope_roots:
        candidates.extend(task.authorized_scope_roots)
    if task.approved_version and task.approved_version == task.version and task.scope_roots:
        candidates.extend(task.scope_roots)
    if task.session_workspace_root:
        candidates.append(task.session_workspace_root)

    roots: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        s = str(item or "").strip()
        if not s:
            continue
        p = Path(s)
        if not p.is_absolute():
            continue
        try:
            resolved = p.resolve()
        except (OSError, ValueError, RuntimeError):
            continue
        key = _normalize_path_key(resolved)
        if key not in seen:
            seen.add(key)
            roots.append(str(resolved))
    return roots


def _shlex_tokens(segment: str) -> list[str] | None:
    """Tokenize a shell command segment via shlex while preserving Windows backslashes."""
    try:
        lexer = shlex.shlex(segment, posix=True)
        lexer.whitespace_split = True
        lexer.escape = ""
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _split_shell_segments(command: str) -> list[str] | None:
    """Split shell command on &&, ||, |, ; outside quotes. Returns None on syntax error."""
    segments: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(command)
    while i < n:
        ch = command[i]
        if quote is not None:
            buf.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in {";", "|", "&"}:
            if ch == "&" and (i + 1 >= n or command[i + 1] != "&"):
                # Background '&' is rejected for safety
                return None
            seg = "".join(buf).strip()
            if seg:
                segments.append(seg)
            buf.clear()
            if i + 1 < n and command[i + 1] == ch and ch in {"|", "&"}:
                i += 2
            else:
                i += 1
            continue
        buf.append(ch)
        i += 1
    if quote is not None:
        return None
    tail = "".join(buf).strip()
    if tail:
        segments.append(tail)
    return segments


def _extract_shell_command(arguments: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script"):
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _is_safe_git_tokens(tokens: list[str]) -> bool:
    idx = 1
    subcmd = ""
    while idx < len(tokens):
        tok = tokens[idx]
        if tok in {"-C", "--git-dir", "--work-tree"}:
            idx += 2
            continue
        if tok.startswith(("--git-dir=", "--work-tree=")):
            idx += 1
            continue
        if tok in {"-c", "--exec-path", "--upload-pack"} or tok.startswith(
            ("-c=", "--exec-path=", "--upload-pack=")
        ):
            return False
        if tok.startswith("-"):
            idx += 1
            continue
        subcmd = tok.lower()
        break

    if subcmd not in _SAFE_GIT_SUBCOMMANDS:
        return False

    for tok in tokens[1:]:
        low = tok.lower()
        if low in _FORBIDDEN_GIT_FLAGS or low.startswith("--output="):
            return False
    return True


def _is_safe_read_segment(segment: str) -> bool:
    tokens = _shlex_tokens(segment)
    if not tokens:
        return False
    cmd = os.path.basename(tokens[0]).lower()
    if cmd.endswith((".exe", ".cmd", ".bat")):
        cmd = cmd[:-4]

    if cmd in _SAFE_SHELL_COMMANDS:
        return True
    if cmd == "find":
        for tok in tokens[1:]:
            if tok.lower() in _FORBIDDEN_FIND_FLAGS:
                return False
        return True
    if cmd == "git":
        return _is_safe_git_tokens(tokens)
    return False


def read_only_call(tool_name: str, arguments: dict[str, Any]) -> bool:
    """Return True if the tool call is strictly read-only or a task control tool."""
    if tool_name in READ_TOOLS or tool_name in CONTROL_TOOL_NAMES:
        return True
    if tool_name not in {"astrbot_execute_shell", "astrbot_sandboxed_shell"}:
        return False

    command = _extract_shell_command(arguments or {})
    if not command:
        return False

    if any(ch in command for ch in ("`", "$", ">", "<", "(", ")", "\n", "\r", "\x00")):
        return False

    segments = _split_shell_segments(command)
    if not segments:
        return False

    return all(_is_safe_read_segment(seg) for seg in segments)


def _var_shell_pattern(var: str) -> re.Pattern[str]:
    esc = re.escape(var)
    return re.compile(
        rf"(?:\$\{{?{esc}\}}?(?![A-Za-z0-9_])|%+{esc}%+|\$env:{esc}(?![A-Za-z0-9_]))",
        re.IGNORECASE,
    )


def _python_exfiltration_reason(code: str, authorized_env_vars: list[str]) -> str:
    """Inspect Python source via AST for os.environ dumping or printing/writing secrets."""
    auth_set = set(authorized_env_vars)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None

    def _is_os_environ(node: ast.AST) -> bool:
        return (
            isinstance(node, ast.Attribute)
            and node.attr == "environ"
            and isinstance(node.value, ast.Name)
            and node.value.id == "os"
        )

    def _extract_env_var_ref(node: ast.AST) -> str | None:
        # os.environ["VAR"]
        if isinstance(node, ast.Subscript) and _is_os_environ(node.value):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                return sl.value
        # os.environ.get("VAR", ...) or os.getenv("VAR", ...)
        if isinstance(node, ast.Call):
            fn = node.func
            is_getenv = (
                isinstance(fn, ast.Attribute)
                and fn.attr == "getenv"
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "os"
            )
            is_environ_get = (
                isinstance(fn, ast.Attribute)
                and fn.attr == "get"
                and _is_os_environ(fn.value)
            )
            if (is_getenv or is_environ_get) and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                    return arg0.value
        return None

    def _is_sink_call(node: ast.Call) -> bool:
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in {"print", "pprint"}:
            return True
        if isinstance(fn, ast.Attribute) and fn.attr in {
            "write",
            "writelines",
            "write_text",
            "write_bytes",
            "pprint",
            "info",
            "warning",
            "error",
            "debug",
            "critical",
        }:
            return True
        return False

    if tree is not None:
        tainted_vars: set[str] = set()
        # Collect variables assigned from expressions referencing authorized env vars or os.environ
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                is_tainted = any(
                    ((ref := _extract_env_var_ref(sub)) and ref in auth_set) or _is_os_environ(sub)
                    for sub in ast.walk(node.value)
                )
                if is_tainted:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            tainted_vars.add(target.id)

        # Check for bare/dumped os.environ (anything other than os.environ["KEY"] or os.environ.get("KEY"))
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                if _is_os_environ(child):
                    is_key_subscript = isinstance(parent, ast.Subscript) and parent.value is child
                    is_key_get = (
                        isinstance(parent, ast.Call)
                        and isinstance(parent.func, ast.Attribute)
                        and parent.func.value is child
                        and parent.func.attr == "get"
                    )
                    if not (is_key_subscript or is_key_get):
                        return "安全拦截：禁止在 Python 代码中整体读取或导出 os.environ 环境变量"

        # Check sink calls referencing authorized env vars or tainted variables
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                # Check os.system / subprocess calls executing env dump commands
                fn = node.func
                if (
                    isinstance(fn, ast.Attribute)
                    and fn.attr in {"system", "popen", "run", "Popen", "call", "check_output"}
                    and node.args
                ):
                    arg0 = node.args[0]
                    if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
                        if _ENV_DUMP_SHELL_RE.search(arg0.value):
                            return "安全拦截：禁止通过子进程命令导出环境变量凭证"

                if _is_sink_call(node):
                    for sub in ast.walk(node):
                        if sub is node:
                            continue
                        ref = _extract_env_var_ref(sub)
                        if ref and ref in auth_set:
                            return f"安全拦截：禁止打印、回显或写入授权凭证变量 {ref}"
                        if isinstance(sub, ast.Name) and sub.id in tainted_vars:
                            return "安全拦截：禁止打印、回显或写入授权凭证变量"
    else:
        # Fallback regex if Python snippet is incomplete/invalid syntax
        if re.search(r"\bos\.environ\b(?!\s*(?:\[|\.get\s*\())", code):
            return "安全拦截：禁止在 Python 代码中整体读取或导出 os.environ 环境变量"
        if re.search(r"\b(?:print|write|write_text|write_bytes)\b", code):
            for var in authorized_env_vars:
                if re.search(rf"""['"]{re.escape(var)}['"]""", code):
                    return f"安全拦截：禁止打印、回显或写入授权凭证变量 {var}"

    return ""


def is_credential_exfiltration(
    tool_name: str,
    arguments: dict[str, Any],
    authorized_env_vars: list[str],
) -> str:
    """Detect attempts to dump, echo, print, or write authorized credential env vars."""
    if not authorized_env_vars or tool_name not in CODE_TOOLS:
        return ""

    args = arguments or {}
    texts = [
        str(args[k])
        for k in ("command", "cmd", "code", "script")
        if isinstance(args.get(k), str) and args.get(k).strip()
    ]
    if not texts:
        return ""
    combined = "\n".join(texts)

    # Check shell-level env dumping (also relevant if shell runs python -c)
    if _ENV_DUMP_SHELL_RE.search(combined):
        return "安全拦截：禁止执行导出全部环境变量的命令（凭证仅限在工具命令中直接引用）"

    # Check Python code/snippets
    if tool_name in _PYTHON_TOOLS or re.search(r"\bos\.environ\b|\bos\.getenv\b", combined):
        py_reason = _python_exfiltration_reason(combined, authorized_env_vars)
        if py_reason:
            return py_reason

    # Check shell statements that echo/print/cat/write any authorized env var
    segments = _split_shell_segments(combined.replace("\n", ";"))
    check_segments = segments if segments else [combined]
    for seg in check_segments:
        if _SHELL_OUTPUT_CMD_RE.search(seg):
            for var in authorized_env_vars:
                if _var_shell_pattern(var).search(seg):
                    return f"安全拦截：禁止回显、打印或输出授权凭证变量 {var}（仅允许在命令中直接传参使用）"

    return ""


def _is_sensitive_path(path_str: str) -> bool:
    s = str(path_str or "").strip()
    if not s:
        return False
    norm = s.replace("\\", "/")
    parts = [p for p in norm.split("/") if p and p != "."]
    for part in parts[:-1]:
        if part.lower() in _SENSITIVE_DIR_NAMES:
            return True
    name = parts[-1] if parts else os.path.basename(norm)
    low = name.lower()
    if low in _SENSITIVE_DIR_NAMES or low in _SENSITIVE_EXACT_NAMES:
        return True
    if low.startswith(".env") or low.startswith("credentials"):
        return True
    if _SENSITIVE_KEY_STEM_RE.match(name):
        return True
    _, ext = os.path.splitext(low)
    if ext in _SENSITIVE_EXTS:
        return True
    return False


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        p_norm = _normalize_path_key(path)
        r_norm = _normalize_path_key(root)
        return os.path.commonpath([p_norm, r_norm]) == r_norm
    except ValueError:
        return False


def _is_allowed_tool_result_read(
    tool_name: str,
    path: Path,
    storage_root: Path | None,
) -> bool:
    if storage_root is None or tool_name not in READ_TOOLS:
        return False
    try:
        resolved_storage = storage_root.resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    if not _is_under_root(path, resolved_storage):
        return False
    try:
        rel = path.relative_to(resolved_storage)
    except ValueError:
        return False
    return "tool_results" in rel.parts and path.suffix.lower() in _TOOL_RESULT_EXTS


def _extract_arg_paths(arguments: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in _PATH_ARG_KEYS:
        val = arguments.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
        elif isinstance(val, (list, tuple)):
            for item in val:
                if isinstance(item, str) and item.strip():
                    out.append(item.strip())
    return out


def _looks_like_path_token(tok: str) -> bool:
    if not tok or tok.startswith("-"):
        return False
    if "://" in tok:
        return False
    if tok in {".", "..", "~"}:
        return True
    if "/" in tok or "\\" in tok:
        return True
    if re.match(r"^[A-Za-z]:", tok):
        return True
    if _is_sensitive_path(tok):
        return True
    return False


def _extract_shell_paths_and_destructive(
    command: str, *, _depth: int = 0
) -> tuple[list[str], list[str]]:
    """Parse shell command into candidate path strings and destructive reasons."""
    raw_paths: list[str] = []
    destructive: list[str] = []

    if _SQL_DESTRUCTIVE_RE.search(command):
        destructive.append("检测到高危 SQL 删表/删库操作")
    if _REDIS_DESTRUCTIVE_RE.search(command):
        destructive.append("检测到高危 Redis 清库操作（FLUSHALL/FLUSHDB）")

    # Extract redirection targets like > file, >> file, < file
    for m in re.finditer(r"(?:>>?|<)\s*([^\s;&|]+)", command):
        target = m.group(1).strip("'\"")
        if target:
            raw_paths.append(target)

    segments = _split_shell_segments(command.replace("\n", ";"))
    if segments is None:
        segments = [command]

    for seg in segments:
        tokens = _shlex_tokens(seg)
        if not tokens:
            continue
        if _looks_like_path_token(tokens[0]):
            raw_paths.append(tokens[0])

        cmd = os.path.basename(tokens[0]).lower()
        if cmd.endswith((".exe", ".cmd", ".bat")):
            cmd = cmd[:-4]

        flags: list[str] = []
        operands: list[str] = []
        for t in tokens[1:]:
            if t.startswith("-"):
                flags.append(t.lower())
            elif cmd in {"del", "erase", "rd", "rmdir"} and t.startswith("/"):
                split_flags = re.findall(r"/[a-z0-9]+", t.lower())
                if split_flags:
                    flags.extend(split_flags)
                else:
                    flags.append(t.lower())
            elif cmd == "cmd" and t.lower() in {"/c", "/k"}:
                flags.append(t.lower())
            else:
                operands.append(t)

        # Recursively inspect subshell wrapper commands (depth limit 3)
        if _depth < 3:
            inner_cmd = ""
            if cmd == "cmd":
                for idx, tok in enumerate(tokens[1:], start=1):
                    if tok.lower() in {"/c", "/k"}:
                        rest = tokens[idx + 1 :]
                        if rest:
                            inner_cmd = (
                                rest[0]
                                if len(rest) == 1
                                else " ".join(shlex.quote(r) for r in rest)
                            )
                        break
            elif cmd in {"bash", "sh", "zsh", "dash"}:
                for idx, tok in enumerate(tokens[1:], start=1):
                    low_t = tok.lower()
                    if low_t == "-c" or (
                        low_t.startswith("-") and not low_t.startswith("--") and "c" in low_t[1:]
                    ):
                        rest = tokens[idx + 1 :]
                        if rest:
                            inner_cmd = (
                                rest[0]
                                if len(rest) == 1
                                else " ".join(shlex.quote(r) for r in rest)
                            )
                        break
            elif cmd in {"powershell", "pwsh"}:
                for idx, tok in enumerate(tokens[1:], start=1):
                    if tok.lower() in {"-c", "-command", "--command", "/c", "/command"}:
                        rest = tokens[idx + 1 :]
                        if rest:
                            inner_cmd = (
                                rest[0]
                                if len(rest) == 1
                                else " ".join(shlex.quote(r) for r in rest)
                            )
                        break
            if inner_cmd.strip():
                sub_paths, sub_destructive = _extract_shell_paths_and_destructive(
                    inner_cmd, _depth=_depth + 1
                )
                raw_paths.extend(sub_paths)
                destructive.extend(sub_destructive)

        if cmd == "cd" and operands:
            raw_paths.append(operands[0])
        else:
            for op in operands:
                if _looks_like_path_token(op):
                    raw_paths.append(op)

        # Destructive command checks
        if cmd in {"mkfs", "format", "diskpart", "shred", "shutdown", "reboot", "halt", "poweroff"}:
            destructive.append(f"检测到高危系统/磁盘破坏性命令 {cmd}")
        elif cmd == "find" and any(f in {"-delete"} for f in flags):
            destructive.append("检测到破坏性命令 find -delete")
        elif cmd == "rm":
            has_r = any(
                f in {"-r", "--recursive"} or (f.startswith("-") and not f.startswith("--") and ("r" in f or "R" in f.upper()))
                for f in flags
            )
            has_f = any(
                f in {"-f", "--force"} or (f.startswith("-") and not f.startswith("--") and "f" in f)
                for f in flags
            )
            if has_r and has_f:
                destructive.append("检测到高危递归强制删除 rm -rf")
            for op in operands:
                if op in {".", "..", "*", "/", "\\"} or re.fullmatch(r"[A-Za-z]:[/\\]?", op):
                    destructive.append(f"检测到高危删除目标 {op}")
        elif cmd in {"del", "erase", "rd", "rmdir"}:
            if any(f == "/s" for f in flags) and any(f == "/q" for f in flags):
                destructive.append(f"检测到高危静默递归删除 {cmd} /s /q")
            for op in operands:
                if op in {".", "..", "*", "/", "\\", "*.*"} or re.fullmatch(r"[A-Za-z]:[/\\]?", op):
                    destructive.append(f"检测到高危删除目标 {op}")
        elif cmd == "remove-item":
            low_seg = seg.lower()
            if "-recurse" in low_seg and "-force" in low_seg:
                destructive.append("检测到高危强制递归删除 Remove-Item -Recurse -Force")
        elif cmd == "git" and operands:
            sub = operands[0].lower()
            if sub == "reset" and "--hard" in flags:
                destructive.append("检测到破坏性 Git 操作 git reset --hard")
            elif sub == "clean":
                has_f = any(f == "--force" or (f.startswith("-") and not f.startswith("--") and "f" in f) for f in flags)
                has_d = any(f.startswith("-") and not f.startswith("--") and "d" in f for f in flags)
                if has_f and has_d:
                    destructive.append("检测到破坏性 Git 操作 git clean -fd")

    return raw_paths, destructive


def _call_name(node: ast.Call) -> str:
    fn = node.func
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        if isinstance(fn.value, ast.Name):
            return f"{fn.value.id}.{fn.attr}"
        return fn.attr
    return ""


def _extract_python_paths_and_destructive(code: str) -> tuple[list[str], list[str]]:
    """Inspect Python code AST for file paths and destructive operations."""
    raw_paths: list[str] = []
    destructive: list[str] = []

    if _SQL_DESTRUCTIVE_RE.search(code):
        destructive.append("检测到高危 SQL 删表/删库操作")
    if _REDIS_DESTRUCTIVE_RE.search(code):
        destructive.append("检测到高危 Redis 清库操作（FLUSHALL/FLUSHDB）")

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return raw_paths, destructive

    def _visit(node: ast.AST, in_loop: bool = False) -> None:
        now_in_loop = in_loop or isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        if isinstance(node, ast.Call):
            cname = _call_name(node)
            short = cname.split(".")[-1]
            str_arg0 = (
                node.args[0].value
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
                else None
            )

            if short in {"open", "Path"} and str_arg0:
                raw_paths.append(str_arg0)
            elif short in {"remove", "unlink", "rmdir", "rmtree"}:
                if str_arg0:
                    raw_paths.append(str_arg0)
                    if str_arg0 in {".", "..", "*", "/", "\\"} or re.fullmatch(r"[A-Za-z]:[/\\]?", str_arg0):
                        destructive.append(f"检测到高危删除目标 {str_arg0}")
                if short == "rmtree" and now_in_loop:
                    destructive.append("检测到循环中调用 shutil.rmtree")
            elif cname in {"os.system", "os.popen"} or short in {"run", "Popen"} and cname.startswith("subprocess."):
                if str_arg0:
                    sp, sd = _extract_shell_paths_and_destructive(str_arg0)
                    raw_paths.extend(sp)
                    destructive.extend(sd)
                elif node.args and isinstance(node.args[0], (ast.List, ast.Tuple)):
                    parts = [
                        elt.value
                        for elt in node.args[0].elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    ]
                    if parts:
                        sp, sd = _extract_shell_paths_and_destructive(
                            " ".join(shlex.quote(p) for p in parts)
                        )
                        raw_paths.extend(sp)
                        destructive.extend(sd)

        for child in ast.iter_child_nodes(node):
            _visit(child, now_in_loop)

    _visit(tree, False)
    return raw_paths, destructive


def full_guard(
    tool_name: str,
    arguments: dict[str, Any],
    task: TaskMeta,
    *,
    profile: Profile | None = None,
    authorized_env_vars: list[str] | None = None,
    storage_root: Path | None = None,
) -> tuple[str, list[str]]:
    """Run full security & scope guard on a tool call. Returns (reason, outside_paths)."""
    if profile and tool_name in profile.disabled_tools:
        return (f"工具 {tool_name} 已被当前方案禁用", [])

    args = arguments or {}
    exfil = is_credential_exfiltration(tool_name, args, authorized_env_vars or [])
    if exfil:
        return (exfil, [])

    reasons: list[str] = []
    outside_paths: list[str] = []
    seen_outside: set[str] = set()

    raw_paths = _extract_arg_paths(args)

    # Extract paths & destructive ops from shell / python code
    if tool_name in _SHELL_TOOLS:
        cmd = _extract_shell_command(args)
        if cmd:
            sp, sd = _extract_shell_paths_and_destructive(cmd)
            raw_paths.extend(sp)
            reasons.extend(sd)
    elif tool_name in _PYTHON_TOOLS:
        code = ""
        for key in ("code", "script"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                code = val.strip()
                break
        if not code:
            code = _extract_shell_command(args)
        if code:
            pp, pd = _extract_python_paths_and_destructive(code)
            raw_paths.extend(pp)
            reasons.extend(pd)

    # Determine base directory for relative paths WITHOUT treating inherited process cwd as explicit target
    explicit_cwd = args.get("cwd") if isinstance(args.get("cwd"), str) and args.get("cwd").strip() else None
    roots_str = execution_roots(task)
    roots = [Path(r) for r in roots_str]

    base_dir: Path | None = None
    if explicit_cwd:
        base_dir = _resolve_path_safe(explicit_cwd)
    elif task.execution_cwd:
        base_dir = _resolve_path_safe(task.execution_cwd)
    elif task.session_workspace_root:
        base_dir = _resolve_path_safe(task.session_workspace_root)
    elif roots:
        base_dir = roots[0]

    sensitive_hits: list[str] = []
    for rp in raw_paths:
        if _is_sensitive_path(rp):
            sensitive_hits.append(rp)
        resolved = _resolve_path_safe(rp, base_dir=base_dir)
        if resolved is None:
            continue
        if _is_sensitive_path(str(resolved)):
            if rp not in sensitive_hits:
                sensitive_hits.append(rp)
        if roots:
            if any(_is_under_root(resolved, root) for root in roots):
                continue
            if _is_allowed_tool_result_read(tool_name, resolved, storage_root):
                continue
            key = _normalize_path_key(resolved)
            if key not in seen_outside:
                seen_outside.add(key)
                outside_paths.append(str(resolved))

    if sensitive_hits:
        reasons.append(f"访问敏感凭证或密钥路径：{', '.join(sensitive_hits[:5])}")

    if outside_paths:
        reasons.append(f"访问工作区授权目录外路径：{', '.join(outside_paths[:5])}")

    # Custom warning rules starting with "审批:"
    warnings = task.execution_settings.warnings if task.execution_settings else []
    if warnings:
        try:
            args_blob = json.dumps(args, ensure_ascii=False, sort_keys=True)
        except TypeError:
            args_blob = str(args)
        candidates = [tool_name, args_blob, *raw_paths, *outside_paths]
        cmd_text = _extract_shell_command(args)
        if cmd_text:
            candidates.append(cmd_text)
        for rule in warnings:
            rule_s = str(rule or "").strip()
            if rule_s.startswith("审批:"):
                pattern = rule_s[len("审批:") :].strip()
            elif rule_s.startswith("审批："):
                pattern = rule_s[len("审批：") :].strip()
            else:
                continue
            if not pattern:
                continue
            if any(fnmatch.fnmatch(c, pattern) for c in candidates):
                reasons.append(f"命中自定义审批规则「{pattern}」")

    # Deduplicate reasons preserving order
    unique_reasons: list[str] = []
    for r in reasons:
        if r and r not in unique_reasons:
            unique_reasons.append(r)

    return ("; ".join(unique_reasons), outside_paths)


def _is_mutating_tool_name(tool_name: str) -> bool:
    tokens = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+", tool_name or "")
    return any(tok.lower() in _MUTATING_NAME_TOKENS for tok in tokens)


def assess_call(
    tool_name: str,
    arguments: dict[str, Any],
    task: TaskMeta,
    *,
    profile: Profile | None = None,
    risk: str = "work",
    authorized_env_vars: list[str] | None = None,
    storage_root: Path | None = None,
) -> tuple[str, str, list[str]]:
    """Assess a tool call and return (decision, reason, outside_paths)."""
    if tool_name in CONTROL_TOOL_NAMES:
        return ("allow", "", [])

    if profile and tool_name in profile.disabled_tools:
        return ("deny", f"工具 {tool_name} 已被当前方案禁用", [])

    effective_risk = (
        profile.tool_risk_overrides.get(tool_name, risk)
        if profile and profile.tool_risk_overrides
        else risk
    )
    mode = task.execution_settings.mode if task.execution_settings else "standard"

    if task.phase == "planning" or mode == "readonly":
        is_safe_external = (
            tool_name not in (WRITE_TOOLS | CODE_TOOLS)
            and effective_risk == "safe"
            and not _is_mutating_tool_name(tool_name)
        )
        if not read_only_call(tool_name, arguments) and not is_safe_external:
            return ("deny", "当前处于规划/只读阶段，仅允许只读查询工具", [])

    args = arguments or {}
    exfil = is_credential_exfiltration(tool_name, args, authorized_env_vars or [])
    if exfil:
        return ("deny", exfil, [])

    reason, outside = full_guard(
        tool_name,
        args,
        task,
        profile=profile,
        authorized_env_vars=authorized_env_vars,
        storage_root=storage_root,
    )
    if reason:
        return ("review", reason, outside)

    if effective_risk == "high" and mode != "full":
        return ("review", f"高风险工具 {tool_name} 需要审批", [])

    return ("allow", "", [])


def call_signature(
    tool_name: str,
    arguments: dict[str, Any],
    workspace: str,
    plan_version: int,
) -> str:
    """Compute canonical SHA-256 signature for an approved tool call."""
    payload = {
        "tool": tool_name,
        "args": arguments or {},
        "workspace": workspace,
        "plan_version": plan_version,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def matches_approved_call(
    task: TaskMeta,
    tool_name: str,
    arguments: dict[str, Any],
) -> tuple[str, int] | None:
    """Return (approval_id, call_index) if an approved, unconsumed tool_batch entry matches."""
    workspace = task.session_workspace_root or task.execution_cwd or ""
    sig = call_signature(tool_name, arguments or {}, workspace, task.version)

    for apr in task.approvals:
        if (
            apr.approval_type != "tool_batch"
            or apr.status != "approved"
            or apr.decision != "approved"
        ):
            continue
        for idx, item in enumerate(apr.calls or []):
            if not isinstance(item, dict):
                continue
            if item.get("execution_status") not in {"", "pending", None}:
                continue
            item_sig = item.get("signature") or item.get("call_signature")
            if not item_sig:
                item_tool = str(item.get("tool") or item.get("tool_name") or "")
                item_args = item.get("arguments")
                if not isinstance(item_args, dict):
                    item_args = item.get("args") if isinstance(item.get("args"), dict) else {}
                item_ws = apr.workspace_root or workspace
                item_sig = call_signature(item_tool, item_args, item_ws, apr.plan_version)
            if item_sig == sig:
                return (apr.approval_id, idx)
    return None
