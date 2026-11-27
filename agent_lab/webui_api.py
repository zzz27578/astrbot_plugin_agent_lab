"""Unified WebUI Backend & Standalone Quart Server for Agent Lab v1.0.1.

Provides:
- `@admin_api` auth guard supporting both AstrBot Dashboard mode (`g.username` /
  `g.agent_lab_web_admin`) and Standalone Quart mode (`Authorization: Bearer`,
  `X-Agent-Lab-Token`, or `?token=` verified via constant-time `hmac.compare_digest`,
  with tokenless local access in `preview_mode=True`).
- `WebUIController`: single business logic controller serving `/health`, `/state`,
  `/workspace`, `/profiles`, `/credentials` with genuine HTTP 4xx status codes on errors.
- `StandaloneWebUIServer`: optional Quart + Hypercorn standalone server serving
  `pages/agent-lab/` static files and rewriting `agent-lab-api-base` meta tag to `/api`.
"""
from __future__ import annotations

import asyncio
import base64
import functools
import hmac
import json
import logging
import mimetypes
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

try:
    import yaml as _yaml  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional fallback
    _yaml = None

from .bridge import _tool_plugin_id
from .engine import TaskEngine
from .guards import resolve_source_persona
from .models import (
    BudgetConfig,
    ContinuityConfig,
    ExecutionSettings,
    Profile,
    Project,
    SummarySharingConfig,
    TaskMeta,
    new_id,
    now_iso,
)
from .permissions import CODE_TOOLS, CONTROL_TOOL_NAMES, DAILY_TOOL_NAMES, READ_TOOLS, WRITE_TOOLS
from .store import AgentLabStore

logger = logging.getLogger("astrbot_plugin_agent_lab.webui")

try:
    from quart import Quart, g, has_request_context, request
except Exception:  # pragma: no cover - optional dependency fallback
    Quart = None  # type: ignore[assignment]
    g = None  # type: ignore[assignment]
    request = None  # type: ignore[assignment]

    def has_request_context() -> bool:  # type: ignore[misc]
        return False

try:
    from hypercorn.asyncio import serve as _hypercorn_serve
    from hypercorn.config import Config as _HypercornConfig
except Exception:  # pragma: no cover - optional dependency fallback
    _hypercorn_serve = None
    _HypercornConfig = None


_API_BASE_META_RE = re.compile(
    r'(<meta\s+name=["\']agent-lab-api-base["\']\s+content=["\'])'
    r'/api/plug/astrbot_plugin_agent_lab'
    r'(["\']\s*/?>)',
    re.IGNORECASE,
)

_LOCAL_ADDRS = frozenset({"", "127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1", "<local>"})


def _cfg_get(config: Any, key: str, default: Any = None) -> Any:
    if isinstance(config, dict):
        return config.get(key, default)
    return getattr(config, key, default)


def _str_or_lines(val: Any) -> list[str]:
    if isinstance(val, (list, tuple)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        return [line.strip() for line in val.splitlines() if line.strip()]
    return []


def _extract_bearer_token() -> str:
    if request is None:
        return ""
    auth = str(request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    header_tok = str(request.headers.get("X-Agent-Lab-Token") or "").strip()
    if header_tok:
        return header_tok
    return str(request.args.get("token") or "").strip()


def _infer_http_status(result: dict[str, Any]) -> int:
    if result.get("ok", True):
        return 200
    explicit = result.get("_http_status")
    if isinstance(explicit, int) and 400 <= explicit < 600:
        return explicit
    err = str(result.get("error") or "")
    if "未授权" in err:
        return 401
    if any(k in err for k in ("越界", "无权", "禁止", "permission")):
        return 403
    if any(k in err for k in ("不存在", "找不到", "not found")):
        return 404
    if any(
        k in err
        for k in (
            "已结束",
            "不可删除",
            "运行中",
            "待审批",
            "待回答",
            "未对账",
            "无法",
            "冲突",
            "不能",
        )
    ):
        return 409
    return 400


def _finalize_http_result(result: dict[str, Any]) -> tuple[dict[str, Any], int]:
    status = _infer_http_status(result)
    clean = {k: v for k, v in result.items() if k != "_http_status"}
    return clean, status


def _err(message: str, status: int = 400) -> dict[str, Any]:
    return {"ok": False, "error": message, "_http_status": status}


_MAX_PLUGIN_LOGO_BYTES = 64 * 1024

_PLUGIN_PREFIX_RE = re.compile(
    r"^(?:astrbot[_-]plugin[_-]|astrbot[_-]|astrbot/|plugin[_-])+",
    re.IGNORECASE,
)

_BUILTIN_GROUP_META: dict[str, tuple[str, str]] = {
    "astrbot_builtin_fs": (
        "文件读写工具",
        "工作区目录浏览、代码检索、文件读取与安全编辑工具组",
    ),
    "astrbot_builtin_shell": (
        "终端与脚本",
        "在授权工作区内执行 Shell 命令、Python 脚本与自动化测试",
    ),
    "astrbot_builtin_web": (
        "网页与文档检索",
        "联网检索技术文档、网页摘要与抓取正文内容",
    ),
    "astrbot_builtin": (
        "内置基础工具",
        "AstrBot 宿主提供的内置通用能力工具",
    ),
}

_KNOWN_PLUGIN_DISPLAY_NAMES: dict[str, str] = {
    "astrbot_plugin_agent_lab": "Agent Lab 任务控制台",
    "astrbot_plugin_gitlink": "Git 版本协作",
    "astrbot_plugin_scheduler_notify": "定时与通知助手",
}

_BUILTIN_TOOL_LABELS: dict[str, str] = {
    "astrbot_file_read_tool": "读取文件",
    "astrbot_grep_tool": "正则检索",
    "astrbot_list_directory": "列举目录",
    "astrbot_file_write_tool": "写入文件",
    "astrbot_file_edit_tool": "局部编辑",
    "astrbot_execute_shell": "执行终端命令",
    "astrbot_execute_python": "运行 Python 脚本",
    "astrbot_execute_ipython": "运行 IPython 代码",
    "astrbot_sandboxed_shell": "沙箱终端命令",
    "astrbot_sandboxed_python": "沙箱 Python 脚本",
    "astrbot_shell_session": "交互式终端会话",
    "astrbot_web_search": "网页搜索",
    "web_search": "网页搜索",
    "tavily_search": "网页搜索",
    "astrbot_fetch_url": "抓取网页",
    "fetch_url": "抓取网页",
    "web_fetch": "抓取网页",
    "git_repo_status": "仓库状态",
    "git_commit_changes": "提交变更",
    "git_push_remote": "推送远程",
    "schedule_list_jobs": "查看定时任务",
    "schedule_create_job": "创建定时通知",
}

_SAFE_TOOL_HINTS = (
    "read",
    "list",
    "grep",
    "search",
    "query",
    "status",
    "get_",
    "fetch",
    "view",
    "show",
    "check",
    "inspect",
    "info",
)
_HIGH_RISK_TOOL_HINTS = (
    "shell",
    "python",
    "exec",
    "eval",
    "push",
    "delete",
    "remove",
    "drop",
    "deploy",
    "publish",
    "reset",
    "kill",
)


def _strip_plugin_prefix(raw: str) -> str:
    cleaned = _PLUGIN_PREFIX_RE.sub("", str(raw or "").strip()).strip(" _-/")
    return cleaned or str(raw or "").strip()


def _humanize_identifier(raw: str) -> str:
    base = _strip_plugin_prefix(raw)
    if not base:
        return "未命名扩展"
    parts = [p for p in re.split(r"[_/\-]+", base) if p]
    if not parts:
        return base
    out: list[str] = []
    for part in parts:
        if part.isascii() and part.isalpha() and len(part) <= 4 and part.lower() in {"git", "api", "ssh", "npm", "url", "mcp", "sql", "llm", "ai"}:
            out.append(part.upper())
        elif part.isascii() and part.isalpha():
            out.append(part.capitalize())
        else:
            out.append(part)
    return " ".join(out)[:48]


def _clean_plugin_display_name(candidate: str, plugin_id: str) -> str:
    if plugin_id in _BUILTIN_GROUP_META:
        return _BUILTIN_GROUP_META[plugin_id][0]
    text = str(candidate or "").strip()
    if text:
        stripped = _PLUGIN_PREFIX_RE.sub("", text).strip()
        if text != plugin_id and stripped == text and "/" not in text and not text.startswith("astrbot_"):
            return text[:48]
        if stripped and stripped != text:
            return _humanize_identifier(stripped)
    if plugin_id in _KNOWN_PLUGIN_DISPLAY_NAMES:
        return _KNOWN_PLUGIN_DISPLAY_NAMES[plugin_id]
    return _humanize_identifier(plugin_id)


def _clean_one_line_desc(text: str, fallback: str = "宿主扩展插件工具集") -> str:
    one_line = " ".join(str(text or "").split()).strip()
    if not one_line:
        return fallback
    return one_line[:160]


def _tool_display_name(tool_name: str, tool_obj: Any = None) -> str:
    if tool_obj is not None:
        explicit = str(getattr(tool_obj, "display_name", "") or "").strip()
        if explicit and explicit != tool_name:
            return explicit[:48]
    if tool_name in _BUILTIN_TOOL_LABELS:
        return _BUILTIN_TOOL_LABELS[tool_name]
    cleaned = re.sub(r"^(?:astrbot_)+", "", tool_name).strip("_")
    cleaned = re.sub(r"_tool$", "", cleaned).strip("_")
    return _humanize_identifier(cleaned or tool_name)


def _tool_default_risk(tool_name: str) -> str:
    if tool_name in READ_TOOLS:
        return "safe"
    if tool_name in CODE_TOOLS:
        return "high"
    lower = tool_name.lower()
    if any(h in lower for h in _HIGH_RISK_TOOL_HINTS):
        return "high"
    if any(h in lower for h in _SAFE_TOOL_HINTS):
        return "safe"
    return "work"


def _classify_builtin_group(tool_name: str, plug_id: str) -> str:
    if plug_id in _BUILTIN_GROUP_META and plug_id != "astrbot_builtin":
        return plug_id
    lower = tool_name.lower()
    if tool_name in READ_TOOLS or tool_name in WRITE_TOOLS or any(
        k in lower for k in ("file", "grep", "glob", "directory", "dir_tree")
    ):
        return "astrbot_builtin_fs"
    if tool_name in CODE_TOOLS or any(
        k in lower for k in ("shell", "python", "ipython", "bash", "terminal")
    ):
        return "astrbot_builtin_shell"
    if any(
        k in lower
        for k in ("web_search", "search_web", "web_fetch", "fetch_url", "tavily", "browser")
    ):
        return "astrbot_builtin_web"
    return "astrbot_builtin"


def _resolve_plugin_dir(star: Any, plugin_id: str) -> Path | None:
    candidates: list[Path] = []
    for attr in ("root_dir", "plugin_dir", "dir_path", "directory", "path"):
        val = getattr(star, attr, None)
        if val:
            try:
                candidates.append(Path(str(val)))
            except Exception:
                pass
    file_path = getattr(star, "file_path", None)
    if file_path:
        try:
            candidates.append(Path(str(file_path)).parent)
        except Exception:
            pass
    for obj in (getattr(star, "star_cls", None), getattr(star, "module", None)):
        if obj is None:
            continue
        mod = sys.modules.get(getattr(obj, "__module__", "")) if not hasattr(obj, "__file__") else obj
        mod_file = getattr(mod, "__file__", None)
        if mod_file:
            try:
                candidates.append(Path(str(mod_file)).resolve().parent)
            except Exception:
                pass
    mod_path = str(getattr(star, "module_path", "") or "").strip()
    if mod_path:
        if "/" in mod_path or "\\" in mod_path:
            try:
                mp = Path(mod_path)
                candidates.append(mp if mp.is_dir() else mp.parent)
            except Exception:
                pass
        elif mod_path in sys.modules:
            mod_file = getattr(sys.modules[mod_path], "__file__", None)
            if mod_file:
                try:
                    candidates.append(Path(str(mod_file)).resolve().parent)
                except Exception:
                    pass

    root_dir_name = str(getattr(star, "root_dir_name", "") or "").strip()
    plugins_parent = Path(__file__).resolve().parent.parent.parent
    cwd_plugins = Path.cwd() / "data" / "plugins"
    for folder_name in dict.fromkeys(x for x in (root_dir_name, plugin_id) if x):
        candidates.append(plugins_parent / folder_name)
        candidates.append(cwd_plugins / folder_name)

    for cand in candidates:
        try:
            resolved = cand.resolve()
            if resolved.is_dir():
                return resolved
        except OSError:
            continue
    return None


def _read_plugin_metadata_yaml(plugin_dir: Path | None) -> dict[str, str]:
    if plugin_dir is None:
        return {}
    meta_file = plugin_dir / "metadata.yaml"
    if not meta_file.is_file():
        return {}
    try:
        raw_text = meta_file.read_text(encoding="utf-8")
    except OSError:
        return {}

    parsed: dict[str, Any] = {}
    if _yaml is not None:
        try:
            loaded = _yaml.safe_load(raw_text)
            if isinstance(loaded, dict):
                parsed = loaded
        except Exception:
            parsed = {}
    if not parsed:
        for line in raw_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            k, v = stripped.split(":", 1)
            parsed[k.strip()] = v.strip().strip("'\"")

    return {
        "display_name": str(parsed.get("display_name") or parsed.get("name") or "").strip(),
        "desc": str(parsed.get("desc") or parsed.get("description") or "").strip(),
    }


def _read_plugin_logo_data_url(plugin_dir: Path | None) -> str:
    if plugin_dir is None:
        return ""
    logo_path = plugin_dir / "logo.png"
    try:
        if not logo_path.is_file():
            return ""
        size = logo_path.stat().st_size
        if size <= 0 or size > _MAX_PLUGIN_LOGO_BYTES:
            return ""
        raw = logo_path.read_bytes()
        if len(raw) > _MAX_PLUGIN_LOGO_BYTES or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            return ""
        return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    except OSError:
        return ""


def _normalize_plugin_entry(entry: dict[str, Any]) -> dict[str, Any]:
    plug_id = str(entry.get("name") or "").strip()
    builtin_meta = _BUILTIN_GROUP_META.get(plug_id)
    raw_display = str(entry.get("display_name") or "").strip()
    display_name = _clean_plugin_display_name(raw_display, plug_id)
    fallback_desc = builtin_meta[1] if builtin_meta else "宿主扩展插件工具集"
    description = _clean_one_line_desc(str(entry.get("description") or entry.get("desc") or ""), fallback_desc)
    host_enabled = bool(entry.get("host_enabled", entry.get("enabled", True)))
    enabled = bool(entry.get("enabled", host_enabled))
    protected = bool(entry.get("protected", plug_id == "astrbot_plugin_agent_lab"))
    logo_data_url = str(entry.get("logo_data_url") or "")

    tools_out: list[dict[str, Any]] = []
    for raw_t in entry.get("tools") or []:
        if not isinstance(raw_t, dict):
            continue
        tname = str(raw_t.get("name") or "").strip()
        if not tname:
            continue
        dr = str(raw_t.get("default_risk") or "").strip().lower()
        if dr not in {"safe", "work", "high"}:
            dr = _tool_default_risk(tname)
        tdisplay = str(raw_t.get("display_name") or "").strip() or _tool_display_name(tname)
        tools_out.append(
            {
                "name": tname,
                "display_name": tdisplay,
                "description": _clean_one_line_desc(str(raw_t.get("description") or ""), ""),
                "default_risk": dr,
            }
        )

    return {
        "name": plug_id,
        "display_name": display_name,
        "description": description,
        "logo_data_url": logo_data_url,
        "enabled": enabled,
        "host_enabled": host_enabled,
        "protected": protected,
        "tools": tools_out,
    }


def _preview_plugins_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": "astrbot_builtin_fs",
            "display_name": "文件读写工具",
            "description": "工作区目录浏览、代码检索、文件读取与安全编辑工具组",
            "logo_data_url": "",
            "enabled": True,
            "host_enabled": True,
            "protected": False,
            "tools": [
                {
                    "name": "astrbot_file_read_tool",
                    "display_name": "读取文件",
                    "description": "读取工作区内指定文件内容与行号范围",
                    "default_risk": "safe",
                },
                {
                    "name": "astrbot_grep_tool",
                    "display_name": "正则检索",
                    "description": "在工作区代码库中执行正则检索",
                    "default_risk": "safe",
                },
                {
                    "name": "astrbot_list_directory",
                    "display_name": "列举目录",
                    "description": "列出目录树结构与文件元信息",
                    "default_risk": "safe",
                },
                {
                    "name": "astrbot_file_write_tool",
                    "display_name": "写入文件",
                    "description": "新建或覆盖写入工作区文件",
                    "default_risk": "work",
                },
                {
                    "name": "astrbot_file_edit_tool",
                    "display_name": "局部编辑",
                    "description": "对已有文件执行局部精确替换编辑",
                    "default_risk": "work",
                },
            ],
        },
        {
            "name": "astrbot_builtin_shell",
            "display_name": "终端与脚本",
            "description": "在授权工作区内执行 Shell 命令、Python 脚本与自动化测试",
            "logo_data_url": "",
            "enabled": True,
            "host_enabled": True,
            "protected": False,
            "tools": [
                {
                    "name": "astrbot_execute_shell",
                    "display_name": "执行终端命令",
                    "description": "在隔离工作区执行 Shell 命令与测试脚本",
                    "default_risk": "high",
                },
                {
                    "name": "astrbot_execute_python",
                    "display_name": "运行 Python 脚本",
                    "description": "执行 Python 诊断或数据处理脚本",
                    "default_risk": "high",
                },
            ],
        },
        {
            "name": "astrbot_plugin_gitlink",
            "display_name": "Git 版本协作",
            "description": "查看仓库状态、创建提交与推送远程分支的代码协作插件",
            "logo_data_url": "",
            "enabled": True,
            "host_enabled": True,
            "protected": False,
            "tools": [
                {
                    "name": "git_repo_status",
                    "display_name": "仓库状态",
                    "description": "查看仓库分支、差异与最近提交记录",
                    "default_risk": "safe",
                },
                {
                    "name": "git_commit_changes",
                    "display_name": "提交变更",
                    "description": "暂存工作区修改并生成规范 Git 提交",
                    "default_risk": "work",
                },
                {
                    "name": "git_push_remote",
                    "display_name": "推送远程",
                    "description": "向远程仓库推送本地分支提交",
                    "default_risk": "high",
                },
            ],
        },
        {
            "name": "astrbot_builtin_web",
            "display_name": "网页与文档检索",
            "description": "联网检索技术文档、网页摘要与抓取正文内容",
            "logo_data_url": "",
            "enabled": True,
            "host_enabled": True,
            "protected": False,
            "tools": [
                {
                    "name": "web_search",
                    "display_name": "网页搜索",
                    "description": "检索技术文档、错误信息与在线参考资料",
                    "default_risk": "safe",
                },
                {
                    "name": "fetch_url",
                    "display_name": "抓取网页",
                    "description": "读取指定网页正文并提取结构化内容",
                    "default_risk": "safe",
                },
            ],
        },
        {
            "name": "astrbot_plugin_scheduler_notify",
            "display_name": "定时与通知助手",
            "description": "管理定时巡检作业并在任务完成后主动投递通知消息",
            "logo_data_url": "",
            "enabled": False,
            "host_enabled": False,
            "protected": False,
            "tools": [
                {
                    "name": "schedule_list_jobs",
                    "display_name": "查看定时任务",
                    "description": "列出当前已注册的定时提醒与周期任务",
                    "default_risk": "safe",
                },
                {
                    "name": "schedule_create_job",
                    "display_name": "创建定时通知",
                    "description": "新增定时触发任务并推送结果通知",
                    "default_risk": "work",
                },
            ],
        },
    ]


# ── Unified Admin Auth Decorator ─────────────────────────────────────────────

def admin_api(func: Callable[..., Any]) -> Callable[..., Any]:
    """Auth guard for both AstrBot Dashboard routes and Standalone Quart routes."""

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if has_request_context() and g is not None and request is not None:
            mode = str(getattr(g, "agent_lab_mode", "") or "")
            if mode == "standalone":
                is_preview = bool(getattr(g, "agent_lab_preview_mode", False))
                remote = str(getattr(request, "remote_addr", "") or "").strip()
                if is_preview:
                    if remote not in _LOCAL_ADDRS:
                        return {"ok": False, "error": "未授权访问"}, 403
                else:
                    expected = str(getattr(g, "agent_lab_token", "") or "")
                    provided = _extract_bearer_token()
                    if not expected or not provided:
                        return {"ok": False, "error": "未授权访问"}, 401
                    if not hmac.compare_digest(
                        provided.encode("utf-8"), expected.encode("utf-8")
                    ):
                        return {"ok": False, "error": "未授权访问"}, 403
            else:
                has_user = bool(getattr(g, "username", None))
                has_admin_flag = bool(getattr(g, "agent_lab_web_admin", False))
                if not (has_user or has_admin_flag):
                    return {"ok": False, "error": "未授权访问"}, 401

        return await func(*args, **kwargs)

    return wrapper


# ── Unified WebUI Controller ─────────────────────────────────────────────────

class WebUIController:
    """Unified business logic controller for AstrBot Dashboard & Standalone Quart WebUI."""

    VERSION = "1.0.1"

    def __init__(
        self,
        store: AgentLabStore,
        engine: TaskEngine,
        context: Any = None,
        config: dict[str, Any] | None = None,
        *,
        preview_mode: bool = False,
    ) -> None:
        self.store = store
        self.engine = engine
        self.context = context
        self.config = config if config is not None else {}
        self.preview_mode = bool(preview_mode)

        # Apply configured default WebUI theme on fresh store initialization if needed
        cfg_theme = str(_cfg_get(self.config, "default_webui_theme", "") or "").strip().lower()
        if cfg_theme in {"modern", "classic"}:
            prefs = self.store.get_preferences()
            if not prefs.get("webui_theme"):
                self.store.update_preferences(webui_theme=cfg_theme)

    # ── AstrBot Dashboard Route Registration ─────────────────────────────────

    def register_astrbot_routes(self, context: Any, plugin_name: str) -> None:
        """Register ONLY GET/POST routes via AstrBot's `context.register_web_api`."""
        reg = getattr(context, "register_web_api", None)
        if not callable(reg):
            return

        @admin_api
        async def _health() -> tuple[dict[str, Any], int]:
            return _finalize_http_result(await self.get_health())

        @admin_api
        async def _state() -> tuple[dict[str, Any], int]:
            return _finalize_http_result(await self.get_state())

        @admin_api
        async def _workspace() -> tuple[dict[str, Any], int]:
            body = await self._read_request_json()
            return _finalize_http_result(await self.handle_workspace(body))

        @admin_api
        async def _profiles() -> tuple[dict[str, Any], int]:
            body = await self._read_request_json()
            return _finalize_http_result(await self.handle_profiles(body))

        @admin_api
        async def _credentials() -> tuple[dict[str, Any], int]:
            body = await self._read_request_json()
            return _finalize_http_result(await self.handle_credentials(body))

        reg(f"/{plugin_name}/v1/health", _health, ["GET"], "Agent Lab v1 WebUI health check")
        reg(f"/{plugin_name}/v1/state", _state, ["GET"], "Agent Lab v1 WebUI state snapshot")
        reg(f"/{plugin_name}/v1/workspace", _workspace, ["POST"], "Agent Lab v1 WebUI workspace actions")
        reg(f"/{plugin_name}/v1/profiles", _profiles, ["POST"], "Agent Lab v1 WebUI profiles management")
        reg(f"/{plugin_name}/v1/credentials", _credentials, ["POST"], "Agent Lab v1 WebUI credentials management")

    async def _read_request_json(self) -> dict[str, Any]:
        if request is None:
            return {}
        try:
            data = await request.get_json(silent=True)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ── Discovery Helpers ────────────────────────────────────────────────────

    async def _discover_identities(
        self,
        projects: list[Project],
        tasks: list[TaskMeta],
        preferences: dict[str, Any],
    ) -> list[dict[str, Any]]:
        identities: list[dict[str, Any]] = []
        by_umo: dict[str, dict[str, Any]] = {}
        platform_names: dict[str, str] = {}
        platform_types: dict[str, str] = {}

        # 1. Seeded preview / stored identities file (if present)
        id_file = self.store.registry_dir / "identities.json"
        stored_ids = self.store._read_json(id_file, [])
        if isinstance(stored_ids, list):
            for row in stored_ids:
                if not isinstance(row, dict):
                    continue
                umo = str(row.get("umo") or "").strip()
                if not umo:
                    continue
                pid = str(row.get("platform_id") or (umo.split(":", 1)[0] if ":" in umo else "unknown"))
                pname = str(row.get("platform_name") or row.get("type") or pid)
                ptype = str(row.get("type") or pid)
                platform_names.setdefault(pid, pname)
                platform_types.setdefault(pid, ptype)
                display_name = str(
                    row.get("display_name")
                    or row.get("name")
                    or row.get("label")
                    or f"{pname} · {umo}"
                )
                entry = {
                    "umo": umo,
                    "platform_id": pid,
                    "platform_name": pname,
                    "name": str(row.get("name") or display_name),
                    "display_name": display_name,
                    "type": ptype,
                    "label": str(row.get("label") or display_name),
                    "persona_id": str(row.get("persona_id") or ""),
                    "persona_name": str(row.get("persona_name") or ""),
                    "persona_preview": str(row.get("persona_preview") or ""),
                }
                by_umo[umo] = entry

        # 2. Discover ONLY real configured & enabled AstrBot platforms (exclude unconfigured internal webchat)
        configured_platforms: dict[str, dict[str, Any]] = {}
        has_configured_filter = False
        if self.context is not None:
            plat_mgr = getattr(self.context, "platform_manager", None)
            raw_cfg = getattr(plat_mgr, "platforms_config", None)
            if raw_cfg is None and hasattr(self.context, "get_config"):
                try:
                    c = self.context.get_config()
                    if isinstance(c, dict):
                        raw_cfg = c.get("platform")
                except Exception:
                    raw_cfg = None
            if isinstance(raw_cfg, list):
                has_configured_filter = True
                for item in raw_cfg:
                    if isinstance(item, dict) and item.get("id") and item.get("enable", False):
                        configured_platforms[str(item["id"]).strip()] = item

            insts = list(getattr(plat_mgr, "platform_insts", None) or [])
            for inst in insts:
                try:
                    meta = getattr(inst, "meta", None)
                    if callable(meta):
                        meta = meta()
                    pid = str(getattr(meta, "id", "") or "").strip()
                    if not pid:
                        continue
                    cfg_item = configured_platforms.get(pid)
                    if has_configured_filter and cfg_item is None:
                        # Skip unconfigured internal adapters (e.g. default webchat)
                        continue
                    ptype = str(
                        (cfg_item or {}).get("type")
                        or getattr(meta, "name", "")
                        or getattr(meta, "type", "")
                        or pid
                    ).strip()
                    pname = str(
                        (cfg_item or {}).get("name")
                        or (cfg_item or {}).get("display_name")
                        or getattr(meta, "adapter_display_name", "")
                        or getattr(meta, "name", "")
                        or pid
                    ).strip()
                    platform_names[pid] = pname or pid
                    platform_types[pid] = ptype or pid
                except Exception:
                    continue

        async def _resolve_persona_fields(umo_key: str) -> tuple[str, str, str]:
            if self.context is None:
                return "", "", ""
            try:
                cfg = self.context.get_config(umo=umo_key) if hasattr(self.context, "get_config") else {}
                psettings = (cfg or {}).get("provider_settings", {}) if isinstance(cfg, dict) else {}
                persona = await resolve_source_persona(self.context, umo_key, psettings)
                if not isinstance(persona, dict):
                    pmgr = getattr(self.context, "persona_manager", None)
                    get_def = getattr(pmgr, "get_default_persona_v3", None)
                    if callable(get_def):
                        persona = await get_def(umo=umo_key)
                if isinstance(persona, dict):
                    p_id = str(persona.get("persona_id") or "")
                    p_name = str(persona.get("name") or p_id)
                    p_prev = str(
                        persona.get("prompt")
                        or persona.get("system_prompt")
                        or persona.get("preview")
                        or ""
                    ).strip()[:200]
                    return p_id, p_name, p_prev
            except Exception:
                pass
            return "", "", ""

        # 3. Ensure every known UMO from projects, tasks, and preferences appears
        candidate_umos: list[str] = []
        default_bot = str(preferences.get("default_bot") or "").strip()
        if default_bot and ":" in default_bot:
            candidate_umos.append(default_bot)
        for p in projects:
            if p.source_umo:
                candidate_umos.append(p.source_umo)
        for t in tasks:
            if t.umo:
                candidate_umos.append(t.umo)
        for k in (preferences.get("progress") or {}).keys():
            if ":" in str(k):
                candidate_umos.append(str(k))

        for umo in dict.fromkeys(candidate_umos):
            if umo in by_umo:
                continue
            pid = umo.split(":", 1)[0] if ":" in umo else "astrbot"
            if has_configured_filter and pid not in platform_names:
                continue
            pname = platform_names.get(pid, pid)
            ptype = platform_types.get(pid, pid)
            tail = umo.split(":")[-1] if ":" in umo else umo
            persona_id, persona_name, persona_preview = await _resolve_persona_fields(umo)
            display_name = f"{persona_name} · {pname}" if persona_name else f"{pname} · {tail}"
            by_umo[umo] = {
                "umo": umo,
                "platform_id": pid,
                "platform_name": pname,
                "name": pname or pid,
                "display_name": display_name,
                "type": ptype,
                "label": display_name,
                "persona_id": persona_id,
                "persona_name": persona_name,
                "persona_preview": persona_preview,
            }

        # 4. Also surface loaded & enabled configured platforms with no UMO history yet
        seen_pids = {v["platform_id"] for v in by_umo.values()}
        for pid, pname in platform_names.items():
            if pid not in seen_pids:
                ptype = platform_types.get(pid, pid)
                synth_umo = f"{pid}:default"
                persona_id, persona_name, persona_preview = await _resolve_persona_fields(synth_umo)
                display_name = f"{pname} ({pid})" if pname != pid else pid
                identities.append(
                    {
                        "umo": synth_umo,
                        "platform_id": pid,
                        "platform_name": pname,
                        "name": pname or pid,
                        "display_name": display_name,
                        "type": ptype,
                        "label": display_name,
                        "persona_id": persona_id,
                        "persona_name": persona_name,
                        "persona_preview": persona_preview,
                    }
                )

        return list(by_umo.values()) + identities

    def _discover_plugins(self) -> list[dict[str, Any]]:
        if self.context is None:
            cat_file = self.store.registry_dir / "plugins_catalog.json"
            stored = self.store._read_json(cat_file, None)
            if isinstance(stored, list) and stored:
                return [_normalize_plugin_entry(item) for item in stored if isinstance(item, dict)]
            if self.preview_mode:
                return [_normalize_plugin_entry(item) for item in _preview_plugins_catalog()]
            return []

        plugins_map: dict[str, dict[str, Any]] = {}
        try:
            stars = self.context.get_all_stars() if hasattr(self.context, "get_all_stars") else []
            for st in stars or []:
                sname = str(getattr(st, "name", "") or "").strip()
                if not sname:
                    continue
                plugin_dir = _resolve_plugin_dir(st, sname)
                yaml_meta = _read_plugin_metadata_yaml(plugin_dir)
                raw_display = str(
                    getattr(st, "display_name", "") or yaml_meta.get("display_name") or ""
                ).strip()
                raw_desc = str(
                    getattr(st, "desc", "") or yaml_meta.get("desc") or ""
                ).strip()
                host_enabled = bool(getattr(st, "activated", True))
                plugins_map[sname] = {
                    "name": sname,
                    "display_name": _clean_plugin_display_name(raw_display, sname),
                    "description": _clean_one_line_desc(raw_desc),
                    "logo_data_url": _read_plugin_logo_data_url(plugin_dir),
                    "enabled": host_enabled,
                    "host_enabled": host_enabled,
                    "protected": sname == "astrbot_plugin_agent_lab",
                    "tools": [],
                }
        except Exception:
            pass

        tool_mgr = None
        if hasattr(self.context, "get_llm_tool_manager"):
            tool_mgr = self.context.get_llm_tool_manager()
        elif hasattr(self.context, "provider_manager"):
            tool_mgr = getattr(self.context.provider_manager, "llm_tools", None)

        raw_tools: list[Any] = []
        if tool_mgr is not None:
            if hasattr(tool_mgr, "get_full_tool_set"):
                raw_tools.extend(list(tool_mgr.get_full_tool_set()))
            elif hasattr(tool_mgr, "func_list"):
                raw_tools.extend(list(tool_mgr.func_list))

        managed_agent_lab = set(CONTROL_TOOL_NAMES) | set(DAILY_TOOL_NAMES)
        for tool in raw_tools:
            tname = str(getattr(tool, "name", "") or "").strip()
            if not tname or tname in managed_agent_lab or tname.startswith("agent_lab_"):
                continue
            plug_id = _tool_plugin_id(tool, self.context) or "astrbot_builtin"
            if plug_id == "astrbot_plugin_agent_lab":
                continue
            if plug_id == "astrbot_builtin" or ("." in plug_id and plug_id not in plugins_map):
                plug_id = _classify_builtin_group(tname, plug_id)
            if plug_id not in plugins_map:
                builtin_meta = _BUILTIN_GROUP_META.get(plug_id)
                plugins_map[plug_id] = {
                    "name": plug_id,
                    "display_name": builtin_meta[0] if builtin_meta else _clean_plugin_display_name("", plug_id),
                    "description": builtin_meta[1] if builtin_meta else "宿主扩展插件工具集",
                    "logo_data_url": "",
                    "enabled": True,
                    "host_enabled": True,
                    "protected": plug_id == "astrbot_plugin_agent_lab",
                    "tools": [],
                }
            plugins_map[plug_id]["tools"].append(
                {
                    "name": tname,
                    "display_name": _tool_display_name(tname, tool),
                    "description": _clean_one_line_desc(str(getattr(tool, "description", "") or ""), ""),
                    "default_risk": _tool_default_risk(tname),
                }
            )

        return list(plugins_map.values())

    def _collect_active_tasks(
        self, projects: list[Project], tasks: list[TaskMeta], preferences: dict[str, Any]
    ) -> dict[str, str]:
        umos: set[str] = set()
        def_bot = str(preferences.get("default_bot") or "").strip()
        if def_bot and ":" in def_bot:
            umos.add(def_bot)
        for p in projects:
            if p.source_umo:
                umos.add(p.source_umo)
        for t in tasks:
            if t.umo:
                umos.add(t.umo)
        active_map: dict[str, str] = {}
        for umo in umos:
            act = self.store.load_active_task(umo)
            if act is not None:
                active_map[umo] = act.task_id
        return active_map

    # ── Core API Endpoints ───────────────────────────────────────────────────

    async def get_health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "version": self.VERSION,
            "mode": "preview" if self.preview_mode else "astrbot",
        }

    async def get_state(self) -> dict[str, Any]:
        preferences = self.store.get_preferences()
        projects = self.store.list_projects()
        tasks = self.store.list_tasks()
        active_tasks = self._collect_active_tasks(projects, tasks, preferences)
        active_id_set = set(active_tasks.values())

        unknown_by_task: dict[str, int] = {}
        for t in tasks:
            unknown_by_task[t.task_id] = len(self.engine._unknown_calls(t))

        enriched_projects: list[dict[str, Any]] = []
        for proj in projects:
            ptasks = [t for t in tasks if t.project_id == proj.project_id]
            running_count = sum(1 for t in ptasks if t.status == "running")
            pending_count = sum(
                1
                for t in ptasks
                if not t.is_terminal()
                and (
                    t.pending_approvals()
                    or t.pending_questions()
                    or unknown_by_task.get(t.task_id, 0) > 0
                )
            )
            proj_active_id = next(
                (t.task_id for t in ptasks if t.task_id in active_id_set), ""
            )
            sum_path = self.store.project_summary_path(proj.project_id)
            if sum_path.exists():
                try:
                    sum_bytes = sum_path.stat().st_size
                except OSError:
                    sum_bytes = 0
            else:
                sum_bytes = len((proj.summary or "").encode("utf-8"))

            d = proj.to_dict()
            d.update(
                {
                    "task_count": len(ptasks),
                    "running_count": running_count,
                    "pending_count": pending_count,
                    "active_task_id": proj_active_id,
                    "summary_bytes": sum_bytes,
                }
            )
            enriched_projects.append(d)

        compact_tasks: list[dict[str, Any]] = []
        for t in tasks:
            compact_tasks.append(
                {
                    "task_id": t.task_id,
                    "project_id": t.project_id,
                    "profile_id": t.profile_id,
                    "umo": t.umo,
                    "goal": t.goal,
                    "status": t.status,
                    "phase": t.phase,
                    "wait_reason": t.wait_reason,
                    "steps_done": sum(1 for s in t.steps if s.status == "completed"),
                    "steps_total": len(t.steps),
                    "pending_approvals": len(t.pending_approvals()),
                    "pending_questions": len(t.pending_questions()),
                    "unknown_calls": unknown_by_task.get(t.task_id, 0),
                    "usage": t.usage.to_dict(),
                    "updated_at": t.updated_at,
                    "created_at": t.created_at,
                }
            )

        identities = await self._discover_identities(projects, tasks, preferences)
        profiles = [p.to_dict() for p in self.store.list_profiles()]
        credentials = [c.to_dict() for c in self.store.list_credentials()]
        plugins = self._discover_plugins()
        storage = self.store.storage_stats()

        return {
            "ok": True,
            "version": self.VERSION,
            "preview_mode": self.preview_mode,
            "preferences": preferences,
            "identities": identities,
            "projects": enriched_projects,
            "tasks": compact_tasks,
            "active_tasks": active_tasks,
            "profiles": profiles,
            "credentials": credentials,
            "plugins": plugins,
            "storage": storage,
        }

    # ── Workspace Actions ────────────────────────────────────────────────────

    def _event_for_umo(self, umo: str) -> Any:
        if self.context is not None and not self.preview_mode and umo:
            return SimpleNamespace(unified_msg_origin=umo)
        return None

    async def handle_workspace(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            return _err("请求体必须是 JSON 对象。", 400)
        action = str(body.get("action") or "").strip().lower()
        if not action:
            return _err("缺少 action 参数。", 400)

        if action == "set_theme":
            theme = str(body.get("theme") or "").strip().lower()
            if theme not in {"modern", "classic"}:
                return _err("主题必须是 modern 或 classic。", 400)
            prefs = self.store.update_preferences(webui_theme=theme)
            return {"ok": True, "preferences": prefs}

        if action == "set_default_bot":
            bot_id = str(
                body.get("platform_id")
                or body.get("default_bot")
                or body.get("umo")
                or ""
            ).strip()
            prefs = self.store.update_preferences(default_bot=bot_id)
            return {"ok": True, "preferences": prefs}

        if action == "set_progress":
            umo = str(body.get("umo") or "").strip()
            raw_prog = body.get("progress")
            if isinstance(raw_prog, dict):
                prog_update = {umo: raw_prog} if umo else dict(raw_prog)
            else:
                item: dict[str, Any] = {}
                if "enabled" in body:
                    item["enabled"] = bool(body.get("enabled"))
                if "min_interval_seconds" in body:
                    item["min_interval_seconds"] = max(0, int(body.get("min_interval_seconds") or 0))
                elif "interval_seconds" in body:
                    item["min_interval_seconds"] = max(0, int(body.get("interval_seconds") or 0))
                if not item:
                    return _err("缺少 progress 更新字段。", 400)
                prog_update = {umo: item} if umo else item
            prefs = self.store.update_preferences(progress=prog_update)
            return {"ok": True, "preferences": prefs}

        if action == "create_project":
            title = str(body.get("title") or "").strip()
            if not title:
                return _err("项目名称不能为空。", 400)
            payload: dict[str, Any] = {
                "title": title,
                "category": str(body.get("category") or "通用").strip() or "通用",
                "source_umo": str(body.get("source_umo") or "").strip(),
                "platform_id": str(body.get("platform_id") or "").strip(),
                "profile_id": str(body.get("profile_id") or "default").strip() or "default",
                "summary": str(body.get("summary") or ""),
            }
            if isinstance(body.get("sharing"), dict):
                payload["sharing"] = SummarySharingConfig.from_dict(body["sharing"]).to_dict()
            if isinstance(body.get("execution_settings"), dict):
                payload["execution_settings"] = ExecutionSettings.from_dict(
                    body["execution_settings"]
                ).to_dict()
            select_umo = str(body.get("select_for_umo") or payload["source_umo"] or "").strip()
            proj = self.store.save_project(payload, select_for_umo=select_umo)
            return {"ok": True, "project": proj.to_dict()}

        if action == "update_project":
            project_id = str(body.get("project_id") or "").strip()
            if not project_id:
                return _err("缺少 project_id。", 400)
            existing = self.store.get_project(project_id)
            if not existing:
                return _err(f"项目不存在: {project_id}", 404)
            merged = existing.to_dict()
            for k in ("title", "category", "source_umo", "platform_id", "profile_id", "summary"):
                if k in body and body[k] is not None:
                    merged[k] = body[k]
            if isinstance(body.get("sharing"), dict):
                merged["sharing"] = SummarySharingConfig.from_dict(
                    {**merged.get("sharing", {}), **body["sharing"]}
                ).to_dict()
            if isinstance(body.get("execution_settings"), dict):
                merged["execution_settings"] = ExecutionSettings.from_dict(
                    {**merged.get("execution_settings", {}), **body["execution_settings"]}
                ).to_dict()
            proj = self.store.save_project(merged)
            return {"ok": True, "project": proj.to_dict()}

        if action == "save_summary":
            project_id = str(body.get("project_id") or "").strip()
            if not project_id:
                return _err("缺少 project_id。", 400)
            text = str(body.get("text") if body.get("text") is not None else body.get("summary") or "")
            task_id = str(body.get("task_id") or "").strip()
            try:
                res = self.store.save_project_summary(project_id, text, task_id=task_id, auto=False)
            except ValueError as exc:
                return _err(str(exc), 404)
            return {"ok": True, **res}

        if action == "draft_summary":
            project_id = str(body.get("project_id") or "").strip()
            if not project_id:
                return _err("缺少 project_id。", 400)
            proj = self.store.get_project(project_id)
            if not proj:
                return _err(f"项目不存在: {project_id}", 404)
            draft = self._build_project_summary_draft(proj)
            return {"ok": True, "project_id": project_id, "draft": draft}

        if action == "task_detail":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            try:
                detail = self.engine.task_detail(task_id)
            except ValueError as exc:
                return _err(str(exc), 404)
            return {"ok": True, **detail}

        if action == "read_record":
            rel_path = str(body.get("rel_path") or body.get("path") or "").strip()
            if not rel_path:
                return _err("缺少 rel_path。", 400)
            max_bytes = max(512, min(262_144, int(body.get("max_bytes") or 24_576)))
            try:
                rec = self.store.read_task_record_preview(rel_path, max_bytes=max_bytes)
            except FileNotFoundError as exc:
                return _err(str(exc), 404)
            except PermissionError as exc:
                return _err(str(exc), 403)
            return {"ok": True, **rec}

        if action == "start_task":
            goal = str(body.get("goal") or "").strip()
            if not goal:
                return _err("任务目标不能为空。", 400)
            project_id = str(body.get("project_id") or "").strip()
            profile_id = str(body.get("profile_id") or "").strip()
            umo = str(body.get("umo") or "").strip()
            if not umo and project_id:
                proj = self.store.get_project(project_id)
                if proj and proj.source_umo:
                    umo = proj.source_umo
            if not umo:
                def_bot = str(self.store.get_preferences().get("default_bot") or "").strip()
                if def_bot and ":" in def_bot:
                    umo = def_bot
                elif def_bot:
                    matched_proj = next(
                        (
                            p
                            for p in self.store.list_projects()
                            if p.platform_id == def_bot and p.source_umo
                        ),
                        None,
                    )
                    umo = matched_proj.source_umo if matched_proj else f"{def_bot}:admin"
                else:
                    umo = "webui:admin"
            constraints = _str_or_lines(body.get("constraints"))
            conds = _str_or_lines(body.get("completion_conditions"))
            plan_steps = body.get("plan_steps") if isinstance(body.get("plan_steps"), list) else None
            brief = str(body.get("brief") or "").strip()
            scope_roots = _str_or_lines(body.get("scope_roots"))
            try:
                task = await self.engine.start_task(
                    umo,
                    goal,
                    project_id=project_id,
                    profile_id=profile_id,
                    brief=brief,
                    scope_roots=scope_roots,
                    constraints=constraints,
                    completion_conditions=conds,
                    plan_steps=plan_steps,
                    event=self._event_for_umo(umo),
                )
            except ValueError as exc:
                return _err(str(exc), 400)
            return {"ok": True, "task": task.to_dict()}

        if action == "activate_task":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            if task.is_terminal() or self.store.is_ended(task_id):
                return _err("已结束的任务无法设为活跃任务。", 409)
            self.store.set_active_task(task)
            return {"ok": True, "task_id": task.task_id, "umo": task.umo}

        if action == "move_task":
            task_id = str(body.get("task_id") or "").strip()
            project_id = str(body.get("project_id") or "").strip()
            if not task_id or not project_id:
                return _err("缺少 task_id 或 project_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            proj = self.store.get_project(project_id)
            if not proj:
                return _err(f"项目不存在: {project_id}", 404)
            task.project_id = project_id
            self.store.save_task(task, active=False, allow_terminal=task.is_terminal())
            return {"ok": True, "task_id": task_id, "project_id": project_id}

        if action == "pause_task":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            reason = str(body.get("reason") or "管理员在 WebUI 暂停任务").strip()
            return await self.engine.pause(task_id, reason=reason)

        if action == "resume_task":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            return await self.engine.resume(task_id, event=self._event_for_umo(task.umo))

        if action == "stop_task":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            reason = str(body.get("reason") or "管理员在 WebUI 停止任务").strip()
            return await self.engine.stop(task_id, reason=reason, actor="admin")

        if action == "deliver_task":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            note = str(body.get("note") or "").strip()
            return await self.engine.deliver_as_is(task_id, note=note, actor="admin")

        if action == "approve":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            decision = str(body.get("decision") or "approved").strip()
            approval_id = str(body.get("approval_id") or "").strip()
            note = str(body.get("note") or "").strip()
            try:
                return await self.engine.resolve_approval(
                    task_id,
                    decision,
                    approval_id=approval_id,
                    note=note,
                    event=self._event_for_umo(task.umo),
                )
            except ValueError as exc:
                return _err(str(exc), 400)

        if action == "answer":
            task_id = str(body.get("task_id") or "").strip()
            answer = str(body.get("answer") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            if not answer:
                return _err("回答内容不能为空。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            question_id = str(body.get("question_id") or "").strip()
            return await self.engine.answer_question(
                task_id,
                answer,
                question_id=question_id,
                event=self._event_for_umo(task.umo),
            )

        if action == "steer":
            task_id = str(body.get("task_id") or "").strip()
            guidance = str(body.get("guidance") if body.get("guidance") is not None else body.get("text") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            return await self.engine.steer(task_id, guidance)

        if action == "reconcile":
            task_id = str(body.get("task_id") or "").strip()
            call_id = str(body.get("call_id") or "").strip()
            status = str(body.get("status") or "").strip()
            note = str(body.get("note") or "").strip()
            if not task_id or not call_id:
                return _err("缺少 task_id 或 call_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            try:
                return await self.engine.reconcile_unknown_call(
                    task_id,
                    call_id,
                    status,
                    note=note,
                    event=self._event_for_umo(task.umo),
                )
            except ValueError as exc:
                return _err(str(exc), 400)

        if action == "update_budget":
            task_id = str(body.get("task_id") or "").strip()
            if not task_id:
                return _err("缺少 task_id。", 400)
            task = self.store.find_task_by_id(task_id)
            if not task:
                return _err(f"任务不存在: {task_id}", 404)
            if task.is_terminal() or self.store.is_ended(task_id):
                return _err("已结束的任务无法修改预算配置。", 409)

            budget_raw = dict(task.execution_settings.budget.to_dict())
            if isinstance(body.get("budget"), dict):
                budget_raw.update(body["budget"])
            for bk in (
                "max_total_tokens",
                "max_tokens_per_tick",
                "max_total_tool_calls",
                "max_total_ticks",
                "max_total_seconds",
                "native_steps",
            ):
                if bk in body and body[bk] is not None:
                    budget_raw[bk] = body[bk]
            task.execution_settings.budget = BudgetConfig.from_dict(budget_raw)

            if isinstance(body.get("continuity"), dict):
                cont_raw = {**task.execution_settings.continuity.to_dict(), **body["continuity"]}
                task.execution_settings.continuity = ContinuityConfig.from_dict(cont_raw)

            self.store.save_task(task)
            self.store.append_event(
                task.umo,
                task.task_id,
                "log",
                {
                    "event": "budget_updated",
                    "budget": task.execution_settings.budget.to_dict(),
                },
            )
            return {
                "ok": True,
                "task_id": task.task_id,
                "execution_settings": task.execution_settings.to_dict(),
            }

        if action == "cleanup_preview":
            scope = str(body.get("scope") or "").strip()
            project_id = str(body.get("project_id") or "").strip()
            task_id = str(body.get("task_id") or "").strip()
            if not scope:
                return _err("缺少 scope 参数。", 400)
            try:
                res = self.store.cleanup_preview(scope, project_id=project_id, task_id=task_id)
            except ValueError as exc:
                return _err(str(exc))
            return {"ok": True, **res}

        if action == "cleanup_confirm":
            token = str(body.get("token") or "").strip()
            if not token:
                return _err("缺少清理确认令牌。", 400)
            try:
                return self.store.cleanup_confirm(token)
            except ValueError as exc:
                return _err(str(exc), 400)

        return _err(f"不支持的工作区操作: {action}", 400)

    def _build_project_summary_draft(self, project: Project) -> str:
        tasks = self.store.list_tasks(project_id=project.project_id)
        existing = self.store.read_project_summary(project.project_id, limit=3000)
        lines: list[str] = [f"# 项目摘要：{project.title}", ""]
        if existing:
            lines.append("## 已有摘要记录")
            lines.append(existing.strip())
            lines.append("")
        lines.append("## 任务进展汇总")
        if not tasks:
            lines.append("- 暂无关联任务。")
        else:
            for t in tasks[:12]:
                done = sum(1 for s in t.steps if s.status == "completed")
                snippet = (t.final_summary or t.current_summary or "").strip().splitlines()[0:1]
                desc = f" — {snippet[0][:120]}" if snippet else ""
                lines.append(
                    f"- [{t.status}/{t.phase}] `{t.task_id}` {t.goal}（{done}/{len(t.steps)} 步）{desc}"
                )
        raw = "\n".join(lines).strip()
        return str(self.store.redact_secrets(raw))

    # ── Profiles API ─────────────────────────────────────────────────────────

    async def handle_profiles(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            return _err("请求体必须是 JSON 对象。", 400)
        action = str(body.get("action") or "").strip().lower()
        if not action:
            return _err("缺少 action 参数。", 400)

        if action == "save":
            raw_prof = body.get("profile")
            payload = dict(raw_prof) if isinstance(raw_prof, dict) else {
                k: v for k, v in body.items() if k != "action"
            }
            if not payload:
                return _err("缺少方案配置内容。", 400)
            # Explicitly preserve empty lists for blacklist / disabled_tools / enabled_tools
            for list_key in (
                "plugin_blacklist",
                "disabled_tools",
                "enabled_tools",
                "authorized_credentials",
            ):
                if list_key in payload and payload[list_key] is None:
                    payload[list_key] = []
            prof = self.store.save_profile(payload)
            return {"ok": True, "profile": prof.to_dict()}

        if action == "duplicate":
            source_id = str(body.get("profile_id") or body.get("source_id") or "").strip()
            if not source_id:
                return _err("缺少源方案 profile_id。", 400)
            profiles = self.store.list_profiles()
            src = next((p for p in profiles if p.profile_id == source_id), None)
            if src is None:
                return _err(f"方案不存在: {source_id}", 404)
            cloned = src.to_dict()
            cloned["profile_id"] = new_id("prof")
            cloned["is_default"] = False
            cloned["name"] = str(body.get("name") or f"{src.name} (副本)").strip()[:80]
            cloned["created_at"] = now_iso()
            cloned["updated_at"] = now_iso()
            prof = self.store.save_profile(cloned)
            return {"ok": True, "profile": prof.to_dict()}

        if action == "delete":
            profile_id = str(body.get("profile_id") or "").strip()
            if not profile_id:
                return _err("缺少 profile_id。", 400)
            try:
                deleted = self.store.delete_profile(profile_id)
            except ValueError as exc:
                return _err(str(exc), 409)
            if not deleted:
                return _err(f"方案不存在: {profile_id}", 404)
            return {"ok": True, "deleted": profile_id}

        return _err(f"不支持的方案操作: {action}", 400)

    # ── Credentials API ──────────────────────────────────────────────────────

    async def handle_credentials(self, body: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(body, dict):
            return _err("请求体必须是 JSON 对象。", 400)
        action = str(body.get("action") or "").strip().lower()
        if not action:
            return _err("缺少 action 参数。", 400)

        if action == "save":
            raw_cred = body.get("credential")
            payload = dict(raw_cred) if isinstance(raw_cred, dict) else {
                k: v for k, v in body.items() if k != "action"
            }
            cid = str(payload.get("credential_id") or "").strip()
            label = str(payload.get("label") or "").strip()
            if not cid and not label:
                return _err("凭证名称 label 不能为空。", 400)
            if "kind" in payload:
                kind_val = str(payload.get("kind") or "secret").strip().lower()
                if kind_val not in {"secret", "personal"}:
                    return _err("条目类型 kind 必须是 secret 或 personal。", 400)
                payload["kind"] = kind_val
            if "share_with_tasks" in payload:
                payload["share_with_tasks"] = bool(payload.get("share_with_tasks"))
            meta = self.store.save_credential(payload)
            pub = meta.to_dict()
            pub.pop("encrypted_value", None)
            pub.pop("value", None)
            return {"ok": True, "credential": pub}

        if action == "delete":
            credential_id = str(body.get("credential_id") or "").strip()
            if not credential_id:
                return _err("缺少 credential_id。", 400)
            deleted = self.store.delete_credential(credential_id)
            if not deleted:
                return _err(f"凭证不存在: {credential_id}", 404)
            return {"ok": True, "deleted": credential_id}

        return _err(f"不支持的凭证操作: {action}", 400)


# ── Standalone Quart Server ──────────────────────────────────────────────────

class StandaloneWebUIServer:
    """Optional standalone Quart WebUI server with token auth and static rewriting."""

    def __init__(
        self,
        controller: WebUIController,
        static_dir: str | Path,
        host: str = "127.0.0.1",
        port: int = 8788,
        token: str = "",
        *,
        preview_mode: bool | None = None,
    ) -> None:
        self.controller = controller
        self.static_dir = Path(static_dir).resolve()
        self.host = str(host or "127.0.0.1").strip()
        self.port = int(port or 8788)
        self.token = str(token or "").strip()
        self.preview_mode = (
            bool(controller.preview_mode) if preview_mode is None else bool(preview_mode)
        )
        self._server_task: asyncio.Task[Any] | None = None
        self._shutdown_event: asyncio.Event | None = None
        self.app: Any = self._build_app()

    def _build_app(self) -> Any:
        if Quart is None:
            return None

        app = Quart("agent_lab_standalone")

        @app.before_request
        async def _inject_standalone_context() -> None:
            if g is not None:
                g.agent_lab_mode = "standalone"
                g.agent_lab_token = self.token
                g.agent_lab_preview_mode = self.preview_mode

        @app.get("/api/health")
        @app.get("/api/v1/health")
        @admin_api
        async def _api_health() -> tuple[dict[str, Any], int]:
            return _finalize_http_result(await self.controller.get_health())

        @app.get("/api/state")
        @app.get("/api/v1/state")
        @admin_api
        async def _api_state() -> tuple[dict[str, Any], int]:
            return _finalize_http_result(await self.controller.get_state())

        @app.post("/api/workspace")
        @app.post("/api/v1/workspace")
        @admin_api
        async def _api_workspace() -> tuple[dict[str, Any], int]:
            body = await self.controller._read_request_json()
            return _finalize_http_result(await self.controller.handle_workspace(body))

        @app.post("/api/profiles")
        @app.post("/api/v1/profiles")
        @admin_api
        async def _api_profiles() -> tuple[dict[str, Any], int]:
            body = await self.controller._read_request_json()
            return _finalize_http_result(await self.controller.handle_profiles(body))

        @app.post("/api/credentials")
        @app.post("/api/v1/credentials")
        @admin_api
        async def _api_credentials() -> tuple[dict[str, Any], int]:
            body = await self.controller._read_request_json()
            return _finalize_http_result(await self.controller.handle_credentials(body))

        @app.get("/")
        async def _index() -> Any:
            return self._serve_index()

        @app.get("/<path:filename>")
        async def _static_file(filename: str) -> Any:
            if filename == "index.html":
                return self._serve_index()
            return self._serve_static(filename)

        return app

    def _serve_index(self) -> tuple[Any, int, dict[str, str]]:
        index_path = self.static_dir / "index.html"
        if not index_path.is_file():
            fallback = (
                "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                "<meta name='agent-lab-api-base' content='/api' />"
                "<title>Agent Lab v1.0.1</title></head>"
                "<body style='font-family:sans-serif;padding:2rem;'>"
                "<h2>Agent Lab v1.0.1 WebUI 后端已就绪</h2>"
                "<p>未找到前端静态文件 <code>pages/agent-lab/index.html</code>。</p>"
                "<p>API 健康检查：<a href='/api/health'>/api/health</a> · "
                "状态接口：<a href='/api/state'>/api/state</a></p>"
                "</body></html>"
            )
            return fallback, 200, {"Content-Type": "text/html; charset=utf-8"}

        html = index_path.read_text(encoding="utf-8")
        rewritten = _API_BASE_META_RE.sub(r"\1/api\2", html)
        return rewritten, 200, {"Content-Type": "text/html; charset=utf-8"}

    def _serve_static(self, filename: str) -> tuple[Any, int, dict[str, str]]:
        if not self.static_dir.exists():
            return {"ok": False, "error": "静态资源目录不存在"}, 404, {"Content-Type": "application/json"}
        try:
            target = (self.static_dir / filename).resolve()
            target.relative_to(self.static_dir)
        except Exception:
            return {"ok": False, "error": "非法路径"}, 403, {"Content-Type": "application/json"}

        if not target.is_file():
            return {"ok": False, "error": "文件不存在"}, 404, {"Content-Type": "application/json"}

        mime, _ = mimetypes.guess_type(str(target))
        ctype = mime or "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype = f"{ctype}; charset=utf-8"
        return target.read_bytes(), 200, {"Content-Type": ctype}

    async def start(self) -> None:
        if self.app is None:
            logger.warning("[AgentLab] quart 未安装，无法启动独立 WebUI 服务器。")
            return
        if self._server_task and not self._server_task.done():
            return
        if self.host not in _LOCAL_ADDRS and not self.token and not self.preview_mode:
            raise ValueError("非本地绑定独立 WebUI 必须配置 standalone_webui_token。")

        self._shutdown_event = asyncio.Event()

        if _hypercorn_serve is not None and _HypercornConfig is not None:
            cfg = _HypercornConfig()
            cfg.bind = [f"{self.host}:{self.port}"]
            cfg.accesslog = None
            cfg.errorlog = None
            shutdown_event = self._shutdown_event
            self._server_task = asyncio.create_task(
                _hypercorn_serve(self.app, cfg, shutdown_trigger=shutdown_event.wait)
            )
        else:
            self._server_task = asyncio.create_task(
                self.app.run_task(host=self.host, port=self.port)
            )
        logger.info("[AgentLab] 独立 WebUI 已启动：http://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        if self._shutdown_event is not None:
            self._shutdown_event.set()
        if self._server_task is not None:
            if not self._server_task.done():
                try:
                    await asyncio.wait_for(self._server_task, timeout=3.0)
                except asyncio.TimeoutError:
                    self._server_task.cancel()
                    try:
                        await self._server_task
                    except asyncio.CancelledError:
                        pass
                except asyncio.CancelledError:
                    pass
            self._server_task = None
        self._shutdown_event = None
        logger.info("[AgentLab] 独立 WebUI 已停止")
