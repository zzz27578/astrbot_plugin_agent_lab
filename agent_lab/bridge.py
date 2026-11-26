"""AstrBot bridge for Agent Lab v1.0.0.

Handles:
- Isolated per-task toolset construction (never mutating global ToolManager tools)
- Tool execution with terminal/active/fence checks, one-shot approval matching,
  credential env injection (never logged), secret redaction, truncation, and O(1) JSONL journaling
- Approved tool_batch one-shot execution & factual receipts
- Strictly static system prompt + incremental wake message + MeteredProvider + ToolLoopAgentRunner
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .context_engine import (
    TASK_CONTROL_TOOL_SCHEMAS,
    ContextCompactor,
    HandoffError,
    StageContextManager,
    build_static_system_prompt,
    estimate_tokens,
    prepare_wake_message,
    truncate_tool_output,
)
from .guards import (
    format_host_skills_prompt,
    format_persona_prompt,
    resolve_source_persona,
)
from .models import ApprovalRequest, Profile, TaskMeta, new_id, now_iso
from .permissions import (
    CODE_TOOLS,
    CONTROL_TOOL_NAMES,
    DAILY_TOOL_NAMES,
    READ_TOOLS,
    WRITE_TOOLS,
    assess_call,
    call_signature,
    matches_approved_call,
    read_only_call,
)


class ExecutionStopped(RuntimeError):
    """Raised when task execution is stopped, ended, or superseded by a fence change."""


class OperationBlocked(RuntimeError):
    """Raised when a tool call is denied or requires explicit approval."""


class BudgetExceeded(RuntimeError):
    """Raised when token or step budget is exhausted."""


# ── Optional AstrBot runtime imports with clean test fallbacks ───────────────

try:
    from mcp.types import CallToolResult as _MCPCallToolResult
    from mcp.types import TextContent as _MCPTextContent
except Exception:  # pragma: no cover - fallback in minimal test envs
    _MCPCallToolResult = None
    _MCPTextContent = None

try:
    from astrbot.core.agent.hooks import BaseAgentRunHooks as _AstrBaseAgentRunHooks
    from astrbot.core.agent.run_context import ContextWrapper as _AstrContextWrapper
    from astrbot.core.agent.runners.tool_loop_agent_runner import (
        ToolLoopAgentRunner as _AstrToolLoopAgentRunner,
    )
    from astrbot.core.agent.tool import FunctionTool as _AstrFunctionTool
    from astrbot.core.agent.tool import ToolSet as _AstrToolSet
    from astrbot.core.agent.tool_executor import (
        BaseFunctionToolExecutor as _AstrBaseFunctionToolExecutor,
    )
    from astrbot.core.astr_agent_context import AstrAgentContext as _AstrAgentContext
    from astrbot.core.astr_agent_tool_exec import (
        FunctionToolExecutor as _AstrFunctionToolExecutor,
    )
    from astrbot.core.message.message_event_result import (
        MessageChain as _AstrMessageChain,
    )
    from astrbot.core.provider.entities import ProviderRequest as _AstrProviderRequest
except Exception:  # pragma: no cover - fallback in minimal test envs
    _AstrBaseAgentRunHooks = object
    _AstrContextWrapper = None
    _AstrToolLoopAgentRunner = None
    _AstrFunctionTool = None
    _AstrToolSet = None
    _AstrBaseFunctionToolExecutor = object
    _AstrAgentContext = None
    _AstrFunctionToolExecutor = None
    _AstrMessageChain = None
    _AstrProviderRequest = None


@dataclass
class _CompatFunctionTool:
    name: str
    description: str = ""
    parameters: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )
    handler: Any = None
    active: bool = True
    is_background_task: bool = False

    async def run(self, *args: Any, **kwargs: Any) -> Any:
        if callable(self.handler):
            res = self.handler(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        raise NotImplementedError(f"Tool {self.name} has no handler")


@dataclass
class _CompatToolSet:
    tools: list[Any] = field(default_factory=list)

    def empty(self) -> bool:
        return len(self.tools) == 0

    def add_tool(self, tool: Any) -> None:
        for i, existing in enumerate(self.tools):
            if getattr(existing, "name", "") == getattr(tool, "name", ""):
                self.tools[i] = tool
                return
        self.tools.append(tool)

    def remove_tool(self, name: str) -> None:
        self.tools = [t for t in self.tools if getattr(t, "name", "") != name]

    def get_tool(self, name: str) -> Any | None:
        for t in self.tools:
            if getattr(t, "name", "") == name:
                return t
        return None

    def names(self) -> list[str]:
        return [getattr(t, "name", "") for t in self.tools if getattr(t, "name", "")]

    def __iter__(self):
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)


def _make_tool_result(text: str, *, is_error: bool = False) -> Any:
    if _MCPCallToolResult is not None and _MCPTextContent is not None:
        return _MCPCallToolResult(
            content=[_MCPTextContent(type="text", text=text)],
            isError=is_error,
        )
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def _extract_result_text(result: Any) -> tuple[str, bool]:
    if result is None:
        return "", False
    if isinstance(result, str):
        return result, False
    if isinstance(result, list):
        parts: list[str] = []
        is_err = False
        for item in result:
            t, e = _extract_result_text(item)
            if t:
                parts.append(t)
            is_err = is_err or e
        return "\n".join(parts), is_err
    is_err = bool(getattr(result, "isError", False))
    content = getattr(result, "content", None)
    if isinstance(result, dict):
        is_err = bool(result.get("isError", False))
        content = result.get("content", result)
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("text") is not None:
                    parts.append(str(item["text"]))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            elif hasattr(item, "text") and getattr(item, "text") is not None:
                parts.append(str(getattr(item, "text")))
            else:
                parts.append(str(item))
        return "\n".join(parts), is_err
    if isinstance(result, dict):
        return json.dumps(result, ensure_ascii=False), is_err
    return str(result), is_err


def _clone_tool(tool: Any) -> Any:
    """Shallow-copy a tool object so global ToolManager entries are never mutated."""
    try:
        return copy.copy(tool)
    except Exception:
        return _CompatFunctionTool(
            name=str(getattr(tool, "name", "")),
            description=str(getattr(tool, "description", "")),
            parameters=copy.deepcopy(
                getattr(tool, "parameters", None)
                or {"type": "object", "properties": {}}
            ),
            handler=getattr(tool, "handler", None),
            active=bool(getattr(tool, "active", True)),
            is_background_task=bool(getattr(tool, "is_background_task", False)),
        )


def _tool_plugin_id(tool: Any, context: Any = None) -> str:
    for attr in ("star_name", "plugin_name", "module_name"):
        val = getattr(tool, attr, None)
        if val:
            return str(val).strip()
    mod_path = str(getattr(tool, "handler_module_path", "") or "")
    if not mod_path and getattr(tool, "handler", None) is not None:
        mod_path = str(getattr(tool.handler, "__module__", "") or "")
    if mod_path and context is not None and hasattr(context, "get_all_stars"):
        try:
            for star in context.get_all_stars() or []:
                sname = str(getattr(star, "name", "") or "")
                smod = str(getattr(star, "module_path", "") or "")
                if sname and (
                    (smod and smod in mod_path)
                    or f".{sname}." in mod_path
                    or mod_path.endswith(f".{sname}")
                ):
                    return sname
        except Exception:
            pass
    return mod_path


def _is_safe_planning_tool(tool: Any, profile: Profile) -> bool:
    name = str(getattr(tool, "name", "") or "")
    if not name:
        return False
    if name in WRITE_TOOLS or name in CODE_TOOLS:
        return name in READ_TOOLS
    if name in READ_TOOLS:
        return True
    override = profile.tool_risk_overrides.get(name, "")
    if override in {"work", "high"}:
        return False
    if override == "safe":
        return True
    lower = name.lower()
    mutating_hints = (
        "write",
        "edit",
        "delete",
        "remove",
        "create",
        "update",
        "exec",
        "shell",
        "python",
        "run",
        "send",
        "post",
        "upload",
        "click",
        "type",
        "install",
        "modify",
        "patch",
    )
    return not any(h in lower for h in mutating_hints)


def _normalize_control_schemas() -> dict[str, dict[str, Any]]:
    """Support both dict and list forms of TASK_CONTROL_TOOL_SCHEMAS."""
    out: dict[str, dict[str, Any]] = {}
    if isinstance(TASK_CONTROL_TOOL_SCHEMAS, dict):
        for name, schema in TASK_CONTROL_TOOL_SCHEMAS.items():
            if isinstance(schema, dict):
                out[str(name)] = schema
    elif isinstance(TASK_CONTROL_TOOL_SCHEMAS, (list, tuple)):
        for item in TASK_CONTROL_TOOL_SCHEMAS:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            name = str(fn.get("name") or item.get("name") or "").strip()
            if name:
                out[name] = fn
    return out


def _sanitize_complete_groups(messages: list[Any]) -> list[dict[str, Any]]:
    """Convert runner messages to dicts and drop trailing incomplete tool-call groups."""
    serialized: list[dict[str, Any]] = []
    for msg in messages:
        if isinstance(msg, dict):
            d = copy.deepcopy(msg)
        elif hasattr(msg, "model_dump"):
            d = msg.model_dump()
        elif hasattr(msg, "to_dict"):
            d = msg.to_dict()
        else:
            continue
        if d.get("role") == "system":
            continue
        serialized.append(d)

    # Walk from end and ensure no dangling assistant tool_calls without matching tool replies.
    while serialized:
        last = serialized[-1]
        if last.get("role") == "assistant" and last.get("tool_calls"):
            serialized.pop()
            continue
        break

    # Verify any open assistant tool_calls group has all expected tool_call_id responses.
    pending_ids: list[str] = []
    group_start = -1
    for idx, msg in enumerate(serialized):
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            pending_ids = []
            group_start = idx
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and tc.get("id"):
                    pending_ids.append(str(tc["id"]))
        elif role == "tool" and pending_ids:
            tc_id = str(msg.get("tool_call_id") or "")
            if tc_id in pending_ids:
                pending_ids.remove(tc_id)
            if not pending_ids:
                group_start = -1
        elif pending_ids and role != "tool":
            # Incomplete group followed by another message -> truncate from group_start
            serialized = serialized[:group_start]
            pending_ids = []
            break
    if pending_ids and group_start >= 0:
        serialized = serialized[:group_start]
    return serialized


def _call_truncate(text: str, cap_bytes: int, saved_path: Path) -> str:
    try:
        sig = inspect.signature(truncate_tool_output)
        params = list(sig.parameters.keys())
        kwargs: dict[str, Any] = {}
        if "cap_bytes" in params:
            kwargs["cap_bytes"] = cap_bytes
        elif "max_bytes" in params:
            kwargs["max_bytes"] = cap_bytes
        elif "limit_bytes" in params:
            kwargs["limit_bytes"] = cap_bytes
        if "saved_path" in params:
            kwargs["saved_path"] = str(saved_path)
        elif "overflow_path" in params:
            kwargs["overflow_path"] = str(saved_path)
        elif "file_path" in params:
            kwargs["file_path"] = str(saved_path)
        return str(truncate_tool_output(text, **kwargs))
    except TypeError:
        return str(truncate_tool_output(text, cap_bytes))


# ── MeteredProvider ──────────────────────────────────────────────────────────

class MeteredProvider:
    """Proxy around an AstrBot Provider enforcing token budgets & logging usage."""

    def __init__(
        self,
        provider: Any,
        *,
        store: Any,
        task: TaskMeta,
        max_total_tokens: int = 0,
        max_tokens_per_tick: int = 0,
    ) -> None:
        self._provider = provider
        self._store = store
        self._task = task
        self._max_total_tokens = int(max_total_tokens or 0)
        self._max_tokens_per_tick = int(max_tokens_per_tick or 0)
        self._tick_tokens = 0
        self.provider_config = getattr(provider, "provider_config", {}) or {}

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    def _check_budget_before(self) -> None:
        if self._store.is_ended(self._task.task_id):
            raise ExecutionStopped("任务已结束。")
        if self._max_total_tokens > 0 and self._task.usage.total_tokens >= self._max_total_tokens:
            raise BudgetExceeded(
                f"已达到任务总 Token 上限 ({self._task.usage.total_tokens}/{self._max_total_tokens})。"
            )
        if self._max_tokens_per_tick > 0 and self._tick_tokens >= self._max_tokens_per_tick:
            raise BudgetExceeded(
                f"已达到单轮 Token 上限 ({self._tick_tokens}/{self._max_tokens_per_tick})。"
            )

    def _record_response_usage(self, resp: Any) -> None:
        if resp is None or getattr(resp, "is_chunk", False):
            return
        usage = getattr(resp, "usage", None)
        self._task.usage.llm_calls += 1
        if usage is None:
            self._task.usage.unreported_calls += 1
            prompt_toks = 0
            comp_toks = 0
            total_toks = 0
        else:
            prompt_toks = int(getattr(usage, "input", 0) or (
                int(getattr(usage, "input_other", 0) or 0)
                + int(getattr(usage, "input_cached", 0) or 0)
            ))
            comp_toks = int(getattr(usage, "output", 0) or 0)
            total_toks = int(getattr(usage, "total", 0) or (prompt_toks + comp_toks))
            self._task.usage.prompt_tokens += prompt_toks
            self._task.usage.completion_tokens += comp_toks
            self._task.usage.total_tokens += total_toks
            self._tick_tokens += total_toks

        self._store.append_event(
            self._task.umo,
            self._task.task_id,
            "usage",
            {
                "prompt_tokens": prompt_toks,
                "completion_tokens": comp_toks,
                "total_tokens": total_toks,
                "tick_tokens": self._tick_tokens,
                "cumulative_tokens": self._task.usage.total_tokens,
                "reported": usage is not None,
            },
        )
        if self._max_total_tokens > 0 and self._task.usage.total_tokens >= self._max_total_tokens:
            raise BudgetExceeded(
                f"已达到任务总 Token 上限 ({self._task.usage.total_tokens}/{self._max_total_tokens})。"
            )
        if self._max_tokens_per_tick > 0 and self._tick_tokens >= self._max_tokens_per_tick:
            raise BudgetExceeded(
                f"已达到单轮 Token 上限 ({self._tick_tokens}/{self._max_tokens_per_tick})。"
            )

    async def text_chat(self, *args: Any, **kwargs: Any) -> Any:
        self._check_budget_before()
        resp = await self._provider.text_chat(*args, **kwargs)
        self._record_response_usage(resp)
        return resp

    async def text_chat_stream(self, *args: Any, **kwargs: Any):
        self._check_budget_before()
        async for chunk in self._provider.text_chat_stream(*args, **kwargs):
            self._record_response_usage(chunk)
            yield chunk


# ── Custom Runner Executor & Hooks ───────────────────────────────────────────

class _TaskToolExecutor(_AstrBaseFunctionToolExecutor):  # type: ignore[misc]
    def __init__(self, bridge: AstrBotBridge, task_id: str, runner: Any = None) -> None:
        self.bridge = bridge
        self.task_id = task_id
        self.runner = runner

    async def execute(self, tool: Any, run_context: Any, **tool_args: Any):
        event = getattr(getattr(run_context, "context", None), "event", None)
        try:
            results = await self.bridge.invoke_tool(
                event, tool, dict(tool_args), self.task_id
            )
            for item in results:
                yield item
        except OperationBlocked as exc:
            yield _make_tool_result(str(exc), is_error=True)
        except (ExecutionStopped, BudgetExceeded) as exc:
            if self.runner is not None and hasattr(self.runner, "request_stop"):
                self.runner.request_stop()
            yield _make_tool_result(str(exc), is_error=True)


class _TaskAgentHooks(_AstrBaseAgentRunHooks):  # type: ignore[misc]
    def __init__(self, bridge: AstrBotBridge, task_id: str, runner: Any = None) -> None:
        self.bridge = bridge
        self.task_id = task_id
        self.runner = runner

    async def on_tool_end(
        self,
        run_context: Any,
        tool: Any,
        tool_args: dict[str, Any] | None,
        tool_result: Any,
    ) -> None:
        if self.bridge.engine.store.is_ended(self.task_id):
            if self.runner is not None and hasattr(self.runner, "request_stop"):
                self.runner.request_stop()
            return
        task = self.bridge.engine.store.find_task_by_id(self.task_id)
        if not task or task.status != "running":
            if self.runner is not None and hasattr(self.runner, "request_stop"):
                self.runner.request_stop()


# ── AstrBotBridge ────────────────────────────────────────────────────────────

class AstrBotBridge:
    """Bridges Agent Lab TaskEngine with AstrBot providers, tools, workspaces, and messaging."""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self.compactor = ContextCompactor()
        self._last_progress_sent: dict[str, float] = {}
        self._turn_fences: dict[str, tuple[int, int]] = {}
        self._active_runners: dict[str, Any] = {}

    # ── Outbound Messaging ───────────────────────────────────────────────────

    async def send_dm(
        self,
        umo: str,
        text: str,
        *,
        kind: str = "status",
        task_id: str = "",
        force: bool = False,
    ) -> dict[str, Any]:
        store = self.engine.store
        clean_text = str(store.redact_secrets(text or "")).strip()
        if not clean_text:
            return {"delivery": "skipped", "reason": "empty", "text": "", "kind": kind}

        if kind == "progress" and not force:
            prefs = store.get_preferences().get("progress", {})
            umo_pref = prefs.get(umo) if isinstance(prefs.get(umo), dict) else {}
            enabled = umo_pref.get("enabled", prefs.get("enabled", True))
            if enabled is False:
                return {"delivery": "throttled", "reason": "disabled", "text": clean_text, "kind": kind}
            raw_interval = (
                umo_pref.get("min_interval_seconds")
                or umo_pref.get("interval_seconds")
                or prefs.get("min_interval_seconds")
                or prefs.get("interval_seconds")
                or prefs.get("throttle_seconds")
                or 0
            )
            try:
                interval = float(raw_interval)
            except (TypeError, ValueError):
                interval = 0.0
            if interval > 0:
                last_ts = self._last_progress_sent.get(umo, 0.0)
                if (time.monotonic() - last_ts) < interval:
                    return {
                        "delivery": "throttled",
                        "reason": "interval",
                        "text": clean_text,
                        "kind": kind,
                    }

        delivery = "recorded"
        ctx = self.engine.context
        if ctx is not None and hasattr(ctx, "send_message"):
            try:
                if _AstrMessageChain is not None:
                    chain = _AstrMessageChain().message(clean_text)
                else:
                    chain = clean_text
                sent = await ctx.send_message(umo, chain)
                delivery = "sent" if sent else "unconfirmed"
            except Exception:
                delivery = "unconfirmed"

        if kind == "progress" and delivery == "sent":
            self._last_progress_sent[umo] = time.monotonic()

        if task_id:
            store.append_event(
                umo,
                task_id,
                "message",
                {
                    "direction": "outbound",
                    "msg_kind": kind,
                    "delivery": delivery,
                    "text": clean_text,
                },
                allow_terminal=True,
            )
        return {"delivery": delivery, "text": clean_text, "kind": kind}

    # ── Trusted Workspace Resolution ─────────────────────────────────────────

    async def refresh_workspace(self, event: Any, task: TaskMeta) -> TaskMeta:
        ctx = self.engine.context
        if ctx is None or not hasattr(ctx, "get_config"):
            return task
        try:
            cfg = ctx.get_config(umo=task.umo) or {}
        except Exception:
            return task
        runtime = str((cfg.get("provider_settings") or {}).get("computer_use_runtime", "none"))
        if runtime != "local":
            return task

        try:
            from astrbot.core.tools.computer_tools.util import (
                workspace_root_for_context,
            )
        except Exception:
            return task

        if event is None:
            event = SimpleNamespace(unified_msg_origin=task.umo)
        if _AstrContextWrapper is not None and _AstrAgentContext is not None:
            ctx_wrapper: Any = _AstrContextWrapper(
                context=_AstrAgentContext(context=ctx, event=event)
            )
        else:
            ctx_wrapper = SimpleNamespace(
                context=SimpleNamespace(context=ctx, event=event)
            )

        try:
            resolved_path = await workspace_root_for_context(ctx_wrapper)
            resolved = str(Path(resolved_path).resolve(strict=False))
        except Exception:
            return task

        changed = (
            task.session_workspace_root != resolved
            or task.execution_cwd != resolved
        )
        if changed:
            task.session_workspace_root = resolved
            task.execution_cwd = resolved
            self.engine.store.save_task(task)
        return task

    # ── Isolated Task Toolset Builder ────────────────────────────────────────

    def _collect_host_tools(self, task: TaskMeta, event: Any) -> list[Any]:
        ctx = self.engine.context
        if ctx is None:
            return []
        tool_mgr = None
        if hasattr(ctx, "get_llm_tool_manager"):
            tool_mgr = ctx.get_llm_tool_manager()
        elif hasattr(ctx, "provider_manager"):
            tool_mgr = getattr(ctx.provider_manager, "llm_tools", None)
        if tool_mgr is None:
            return []

        candidates: list[Any] = []
        if hasattr(tool_mgr, "get_full_tool_set"):
            full_set = tool_mgr.get_full_tool_set()
            candidates.extend(list(full_set))
        elif hasattr(tool_mgr, "func_list"):
            candidates.extend(list(tool_mgr.func_list))

        if hasattr(ctx, "get_config") and _AstrFunctionToolExecutor is not None:
            try:
                cfg = ctx.get_config(umo=task.umo) or {}
                psettings = cfg.get("provider_settings", {}) or {}
                runtime = str(psettings.get("computer_use_runtime", "none"))
                booter = (psettings.get("sandbox") or {}).get("booter")
                if runtime in {"local", "sandbox"}:
                    rt_tools = _AstrFunctionToolExecutor._get_runtime_computer_tools(
                        runtime, tool_mgr, booter
                    )
                    candidates.extend(rt_tools.values())
            except Exception:
                pass
        return candidates

    def _build_control_tool(self, name: str, schema: dict[str, Any]) -> Any:
        desc = str(schema.get("description") or f"Agent Lab control tool: {name}")
        params = copy.deepcopy(
            schema.get("parameters") or {"type": "object", "properties": {}}
        )
        if _AstrFunctionTool is not None:
            return _AstrFunctionTool(
                name=name,
                description=desc,
                parameters=params,
                handler=None,
                active=True,
            )
        return _CompatFunctionTool(
            name=name,
            description=desc,
            parameters=params,
            handler=None,
            active=True,
        )

    def build_task_toolset(self, task: TaskMeta, profile: Profile, event: Any) -> Any:
        toolset: Any = _AstrToolSet() if _AstrToolSet is not None else _CompatToolSet()

        # 1. Add the 5 compact control tools bound to TASK_CONTROL_TOOL_SCHEMAS
        schemas = _normalize_control_schemas()
        for cname in CONTROL_TOOL_NAMES:
            schema = schemas.get(cname, {"name": cname, "description": cname, "parameters": {"type": "object", "properties": {}}})
            toolset.add_tool(self._build_control_tool(cname, schema))

        # 2. Add cloned host/plugin tools with strict filtering
        blacklist = {str(x).strip() for x in (profile.plugin_blacklist or []) if str(x).strip()}
        disabled = {str(x).strip() for x in (profile.disabled_tools or []) if str(x).strip()}
        enabled = {str(x).strip() for x in (profile.enabled_tools or []) if str(x).strip()}
        readonly_mode = task.phase == "planning" or task.execution_settings.mode == "readonly"

        for raw_tool in self._collect_host_tools(task, event):
            tname = str(getattr(raw_tool, "name", "") or "").strip()
            if not tname or not getattr(raw_tool, "active", True):
                continue
            if tname in CONTROL_TOOL_NAMES or tname in DAILY_TOOL_NAMES:
                continue
            if tname.startswith("agent_lab_"):
                continue
            if tname in disabled:
                continue
            if enabled and tname not in enabled:
                continue
            if blacklist:
                plug = _tool_plugin_id(raw_tool, self.engine.context)
                if plug and (
                    plug in blacklist
                    or any(
                        b == plug or f".{b}." in plug or plug.endswith(f".{b}")
                        for b in blacklist
                    )
                ):
                    continue
            if readonly_mode and not _is_safe_planning_tool(raw_tool, profile):
                continue
            toolset.add_tool(_clone_tool(raw_tool))

        return toolset

    # ── Control Tool Dispatch ────────────────────────────────────────────────

    async def _dispatch_control_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        task: TaskMeta,
        event: Any,
    ) -> dict[str, Any]:
        args = dict(arguments or {})
        if tool_name == "task_plan":
            res = await self.engine.submit_plan(
                task.task_id,
                args.get("steps") or [],
                goal=str(args.get("goal") or ""),
                completion_conditions=args.get("completion_conditions"),
                scope_roots=args.get("scope_roots"),
                remove_constraints=args.get("remove_constraints"),
                constraints=args.get("constraints"),
                summary=str(args.get("summary") or ""),
                completed_step=str(args.get("completed_step") or ""),
                message=str(args.get("message") or ""),
                event=event,
            )
            return res

        if tool_name == "task_ask":
            return await self.engine.ask_question(
                task.task_id,
                question=str(args.get("question") or ""),
                options=args.get("options"),
                recommendation=str(args.get("recommendation") or ""),
                event=event,
            )

        if tool_name == "task_approve":
            operation = str(args.get("operation") or "").strip()
            raw_calls = args.get("calls")
            if raw_calls is None and args.get("operations_json") is not None:
                ops_raw = args.get("operations_json")
                if isinstance(ops_raw, str):
                    try:
                        raw_calls = json.loads(ops_raw)
                    except json.JSONDecodeError:
                        raw_calls = None
                elif isinstance(ops_raw, list):
                    raw_calls = ops_raw
            if isinstance(raw_calls, list) and len(raw_calls) > 0:
                calls = raw_calls
            else:
                calls = [
                    {
                        "tool_name": "manual_operation",
                        "arguments": {"operation": operation or "manual_confirmation"},
                    }
                ]
            return await self.engine.request_approval(
                task.task_id,
                operation=operation,
                reason=str(args.get("reason") or ""),
                impact=str(args.get("impact") or ""),
                rollback=str(args.get("rollback") or ""),
                calls=calls,
                message=str(args.get("message") or ""),
                event=event,
            )

        if tool_name == "task_finish":
            summary = str(args.get("final_summary") or args.get("summary") or "")
            return await self.engine.finish_task(
                task.task_id,
                summary,
                message=str(args.get("message") or ""),
                event=event,
            )

        # 5th control tool (status / progress / read_result / etc.)
        if tool_name in {"task_read_result", "task_read_output", "task_tool_result"}:
            call_id = str(args.get("call_id") or "")
            rel = str(args.get("rel_path") or "")
            if not rel and call_id:
                rel = f"sessions"
                path = self.engine.store.task_tool_results_dir(task.umo, task.task_id) / f"{call_id}.txt"
                rel = str(path.relative_to(self.engine.store.root)).replace("\\", "/")
            max_bytes = int(args.get("max_bytes") or 24_576)
            return self.engine.store.read_task_record_preview(rel, max_bytes=max_bytes)

        if tool_name in {"task_progress", "task_update", "task_step", "task_note", "task_report"}:
            summary = str(args.get("summary") or args.get("current_summary") or "").strip()
            step_id = str(args.get("step_id") or args.get("current_step_id") or "").strip()
            next_step_id = str(args.get("next_step_id") or "").strip()
            step_status = str(args.get("status") or "").strip().lower()
            msg = str(args.get("message") or "").strip()

            prev_stage = ""
            for st in task.steps:
                if st.id == (task.current_step_id or step_id):
                    prev_stage = st.stage
                    break

            if summary:
                task.current_summary = summary[:2000]
            if step_id:
                task.current_step_id = step_id
                for st in task.steps:
                    if st.id == step_id:
                        if step_status in {"pending", "running", "completed", "skipped"}:
                            st.status = step_status
                        elif st.status == "pending":
                            st.status = "running"
                        if summary:
                            st.summary = summary[:500]
            if next_step_id:
                task.current_step_id = next_step_id
                for st in task.steps:
                    if st.id == next_step_id:
                        if st.status == "pending":
                            st.status = "running"
                        if prev_stage and st.stage and st.stage != prev_stage:
                            cstate = dict(task.continuity_state or {})
                            cstate["pending_reason"] = "stage_changed"
                            task.continuity_state = cstate
                        break
            elif step_status == "completed" and prev_stage:
                stage_open = any(
                    st.stage == prev_stage and st.status not in {"completed", "skipped"}
                    for st in task.steps
                )
                if not stage_open:
                    cstate = dict(task.continuity_state or {})
                    cstate["pending_reason"] = "stage_completed"
                    task.continuity_state = cstate

            self.engine.store.save_task(task)
            if msg:
                await self.send_dm(task.umo, msg, kind="progress", task_id=task.task_id)
            return {
                "ok": True,
                "task_id": task.task_id,
                "phase": task.phase,
                "current_step_id": task.current_step_id,
                "current_summary": task.current_summary,
            }

        # Default fallback for status/info inspection tools
        detail = self.engine.task_detail(task.task_id)
        return {
            "ok": True,
            "meta": detail.get("meta"),
            "unknown_calls": detail.get("unknown_calls"),
        }

    # ── Tool Invocation Pipeline ─────────────────────────────────────────────

    def _check_fence(self, task_id: str) -> TaskMeta:
        store = self.engine.store
        if store.is_ended(task_id):
            raise ExecutionStopped("任务已结束。")
        task = store.find_task_by_id(task_id)
        if not task or task.is_terminal():
            raise ExecutionStopped("任务不存在或已终止。")
        active = store.load_active_task(task.umo)
        if active is not None and active.task_id != task.task_id:
            raise ExecutionStopped("当前会话已切换到其他任务。")
        if task.status != "running":
            raise ExecutionStopped(f"任务当前非运行状态: {task.status} ({task.wait_reason})")
        expected = self._turn_fences.get(task_id)
        if expected is not None and (task.authorization_version, task.input_revision) != expected:
            raise ExecutionStopped("任务授权版本或输入状态已更新，当前轮次需重新对齐。")
        return task

    def _consume_approved_match(
        self, task: TaskMeta, tool_name: str, arguments: dict[str, Any]
    ) -> bool:
        matched = matches_approved_call(task, tool_name, arguments)
        if not matched:
            return False

        consumed_any = False
        if isinstance(matched, tuple) and len(matched) == 2:
            apr_id, call_idx = matched
            for appr in task.approvals:
                if appr.approval_id == apr_id and 0 <= call_idx < len(appr.calls):
                    appr.calls[call_idx]["execution_status"] = "consumed"
                    appr.calls[call_idx]["status"] = "consumed"
                    consumed_any = True
                    if all(
                        c.get("execution_status", c.get("status", "pending")) not in {"", "pending", None}
                        for c in appr.calls
                    ):
                        appr.status = "consumed"
                    break

        if not consumed_any:
            workspace = task.session_workspace_root or task.execution_cwd or ""
            sig = call_signature(tool_name, arguments, workspace, task.version)
            for appr in task.approvals:
                if appr.approval_type != "tool_batch" or appr.status != "approved":
                    continue
                for call_spec in appr.calls:
                    if call_spec.get("execution_status", call_spec.get("status", "pending")) not in {"", "pending", None}:
                        continue
                    cname = str(call_spec.get("tool_name") or call_spec.get("tool") or call_spec.get("name") or "")
                    cargs = call_spec.get("arguments") or call_spec.get("args") or {}
                    cws = appr.workspace_root or workspace
                    csig = call_spec.get("signature") or call_spec.get("call_signature") or call_signature(cname, cargs, cws, appr.plan_version)
                    if csig == sig:
                        call_spec["execution_status"] = "consumed"
                        call_spec["status"] = "consumed"
                        consumed_any = True
                        break
                if consumed_any:
                    if all(
                        c.get("execution_status", c.get("status", "pending")) not in {"", "pending", None}
                        for c in appr.calls
                    ):
                        appr.status = "consumed"
                    break

        if consumed_any:
            self.engine.store.save_task(task)
        return True

    async def _execute_raw_tool(
        self,
        tool: Any,
        event: Any,
        exec_args: dict[str, Any],
        timeout: float,
    ) -> Any:
        ctx = self.engine.context
        if event is None:
            event = SimpleNamespace(unified_msg_origin="")

        ctx_wrapper = None
        if (
            _AstrFunctionToolExecutor is not None
            and ctx is not None
            and _AstrContextWrapper is not None
            and _AstrAgentContext is not None
        ):
            try:
                ctx_wrapper = _AstrContextWrapper(
                    context=_AstrAgentContext(context=ctx, event=event),
                    tool_call_timeout=max(1, int(timeout)),
                )
            except Exception:
                ctx_wrapper = None

        if ctx_wrapper is not None:
            async def _run_astr() -> Any:
                last_res: Any = None
                async for item in _AstrFunctionToolExecutor.execute(tool, ctx_wrapper, **exec_args):
                    if item is not None:
                        last_res = item
                return last_res

            return await asyncio.wait_for(_run_astr(), timeout=timeout)

        # Fallback for unit tests / lightweight mock tools
        async def _run_fallback() -> Any:
            if hasattr(tool, "run") and callable(tool.run):
                res = tool.run(**exec_args)
                return await res if inspect.isawaitable(res) else res
            handler = getattr(tool, "handler", None)
            if callable(handler):
                try:
                    sig = inspect.signature(handler)
                    accepts_event = "event" in sig.parameters
                except (TypeError, ValueError):
                    accepts_event = False
                res = handler(event, **exec_args) if accepts_event else handler(**exec_args)
                if inspect.isasyncgen(res):
                    chunks = [str(c) async for c in res if c is not None]
                    return "\n".join(chunks)
                return await res if inspect.isawaitable(res) else res
            if hasattr(tool, "call") and callable(tool.call):
                res = tool.call(SimpleNamespace(context=SimpleNamespace(context=ctx, event=event), tool_call_timeout=int(timeout)), **exec_args)
                return await res if inspect.isawaitable(res) else res
            raise RuntimeError(f"Tool {getattr(tool, 'name', tool)} is not executable")

        return await asyncio.wait_for(_run_fallback(), timeout=timeout)

    def _parse_assessment(self, assessment: Any) -> tuple[str, str]:
        if isinstance(assessment, dict):
            decision = str(
                assessment.get("decision")
                or assessment.get("action")
                or assessment.get("verdict")
                or "allow"
            ).lower()
            reason = str(assessment.get("reason") or assessment.get("message") or "")
            return decision, reason
        if isinstance(assessment, tuple) and assessment:
            decision = str(assessment[0]).lower()
            reason = str(assessment[1]) if len(assessment) > 1 else ""
            return decision, reason
        decision = str(
            getattr(assessment, "decision", None)
            or getattr(assessment, "action", None)
            or getattr(assessment, "verdict", None)
            or "allow"
        ).lower()
        reason = str(getattr(assessment, "reason", None) or getattr(assessment, "message", None) or "")
        return decision, reason

    async def invoke_tool(
        self,
        event: Any,
        tool: Any,
        arguments: dict[str, Any],
        task_id: str,
        *,
        approved_override: bool = False,
    ) -> list[Any]:
        store = self.engine.store
        task = self._check_fence(task_id)
        tool_name = str(getattr(tool, "name", "") or "")
        args = dict(arguments or {})

        # 1. Dispatch 5 compact control tools directly via TaskEngine
        if tool_name in CONTROL_TOOL_NAMES:
            result = await self._dispatch_control_tool(tool_name, args, task, event)
            clean_payload = store.redact_secrets(result)
            return [_make_tool_result(json.dumps(clean_payload, ensure_ascii=False))]

        # 2. Block further mutations if un-reconciled started/unknown journal calls exist
        journal = store.latest_journal_by_call(task.umo, task.task_id)
        unresolved = [j for j in journal if j.get("status") in {"started", "unknown"}]
        if unresolved and not read_only_call(tool_name, args):
            cids = ", ".join(str(j.get("call_id")) for j in unresolved[:5])
            raise OperationBlocked(
                f"存在未对账的工具调用 ({cids})，已暂停后续变更操作；请先等待管理员对账确认后再继续。"
            )

        # 3. Resolve profile/project and authorized credential env map
        profile = store.get_profile(task.profile_id)
        project = store.get_project(task.project_id)
        proj_creds = (
            project.execution_settings.authorized_credentials
            if project
            else task.execution_settings.authorized_credentials
        )
        auth_env = store.build_authorized_env(
            task.project_id, profile.authorized_credentials, proj_creds
        )

        # 4. One-shot approved call matching OR permission assessment
        if not approved_override and self._consume_approved_match(task, tool_name, args):
            approved_override = True

        if not approved_override:
            default_risk = (
                "safe" if tool_name in READ_TOOLS else ("high" if tool_name in CODE_TOOLS else "work")
            )
            tool_risk = profile.tool_risk_overrides.get(tool_name, default_risk)
            assessment = assess_call(
                tool_name,
                args,
                task,
                profile=profile,
                risk=tool_risk,
                authorized_env_vars=list(auth_env.keys()),
                storage_root=store.root,
            )
            decision, reason = self._parse_assessment(assessment)
            if decision in {"deny", "review"}:
                hint = (
                    "操作被策略拒绝，请调整方案或参数，切勿反复重试相同操作。"
                    if decision == "deny"
                    else "该操作需要管理员审批；请调用 `task_approve` 提交清晰的审批申请，或改用低风险只读方案。"
                )
                raise OperationBlocked(
                    f"[{decision.upper()}] 工具 `{tool_name}` 未获直接执行许可：{reason or '超出当前权限范围'}。{hint}"
                )

        # 5. Append "started" journal line with redacted args (NEVER log auth_env)
        call_id = new_id("call")
        safe_args = store.redact_secrets(args)
        store.append_event(
            task.umo,
            task.task_id,
            "journal",
            {
                "call_id": call_id,
                "tool_name": tool_name,
                "arguments": safe_args,
                "status": "started",
                "step_id": task.current_step_id,
                "plan_version": task.version,
                "approved_override": approved_override,
            },
        )

        # 6. Inject authorized env ONLY into a fresh copy of exec_args for CODE_TOOLS that accept env
        exec_args = copy.deepcopy(args)
        if tool_name in CODE_TOOLS and auth_env:
            params_props = (
                (getattr(tool, "parameters", None) or {}).get("properties") or {}
            )
            accepts_env = "env" in params_props
            if not accepts_env:
                fn = getattr(tool, "handler", None) or getattr(tool, "call", None) or getattr(tool, "run", None)
                if callable(fn):
                    try:
                        sig = inspect.signature(fn)
                        accepts_env = (
                            "env" in sig.parameters
                            or any(
                                p.kind == inspect.Parameter.VAR_KEYWORD
                                for p in sig.parameters.values()
                            )
                        )
                    except (TypeError, ValueError):
                        accepts_env = False
            if accepts_env:
                existing_env = exec_args.get("env")
                merged_env = dict(existing_env) if isinstance(existing_env, dict) else {}
                merged_env.update(auth_env)
                exec_args["env"] = merged_env

        timeout = float(self.engine.config.get("tool_call_timeout_seconds", 180) or 180)
        is_err = False
        try:
            raw_res = await self._execute_raw_tool(tool, event, exec_args, timeout)
            raw_text, is_err = _extract_result_text(raw_res)
        except (asyncio.TimeoutError, TimeoutError) as exc:
            store.append_event(
                task.umo,
                task.task_id,
                "journal",
                {
                    "call_id": call_id,
                    "tool_name": tool_name,
                    "status": "unknown",
                    "error": f"timeout after {timeout}s: {exc}",
                },
            )
            fresh = store.find_task_by_id(task.task_id) or task
            if not store.is_ended(task.task_id):
                fresh.status = "paused"
                fresh.wait_reason = "unknown_call"
                store.save_task(fresh)
                await self.send_dm(
                    fresh.umo,
                    f"⚠️ 工具 `{tool_name}` (`{call_id}`) 执行超时，结果状态未知，任务已暂停等待对账。",
                    kind="alert",
                    task_id=fresh.task_id,
                    force=True,
                )
            raise ExecutionStopped(f"工具 `{tool_name}` 超时，已标记为 unknown 并暂停任务。") from exc
        except Exception as exc:
            msg = str(exc)
            if "execution timeout after" in msg.lower():
                store.append_event(
                    task.umo,
                    task.task_id,
                    "journal",
                    {
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "status": "unknown",
                        "error": msg,
                    },
                )
                fresh = store.find_task_by_id(task.task_id) or task
                if not store.is_ended(task.task_id):
                    fresh.status = "paused"
                    fresh.wait_reason = "unknown_call"
                    store.save_task(fresh)
                raise ExecutionStopped(f"工具 `{tool_name}` 超时，已标记为 unknown 并暂停任务。") from exc
            is_err = True
            raw_text = f"工具 `{tool_name}` 执行失败: {msg}"

        # 7. Redact secrets, persist full output, truncate for model ingress
        clean_text = str(store.redact_secrets(raw_text or ""))
        saved_path = store.save_tool_result(task.umo, task.task_id, call_id, clean_text)
        cap_bytes = task.execution_settings.continuity.ingress_cap_bytes
        final_text = _call_truncate(clean_text, cap_bytes, saved_path)

        # 8. O(1) append completed/failed journal line & update usage + ProgressGuard
        store.append_event(
            task.umo,
            task.task_id,
            "journal",
            {
                "call_id": call_id,
                "tool_name": tool_name,
                "status": "failed" if is_err else "completed",
                "output_bytes": len(clean_text.encode("utf-8")),
                "result_path": str(saved_path.relative_to(store.root)).replace("\\", "/"),
            },
        )

        if not store.is_ended(task.task_id):
            fresh = store.find_task_by_id(task.task_id) or task
            fresh.usage.tool_calls += 1

            guard_obs = self.engine.progress_guard.observe_tool(
                fresh, tool_name, safe_args, ok=not is_err, output=clean_text
            )
            g_action, g_msg = self._parse_assessment(guard_obs)
            if g_action == "warn" and g_msg:
                final_text = f"{final_text}\n\n[ProgressGuard 警告] {g_msg}"
            elif g_action == "pause":
                fresh.status = "paused"
                fresh.wait_reason = "guard_paused"
                store.save_task(fresh)
                await self.send_dm(
                    fresh.umo,
                    f"⏸️ 任务已由进度保护暂停：{g_msg or '检测到连续无效或重复操作'}",
                    kind="alert",
                    task_id=fresh.task_id,
                    force=True,
                )
                return [_make_tool_result(final_text, is_error=is_err)]

            store.save_task(fresh)

        return [_make_tool_result(final_text, is_error=is_err)]

    # ── Approved Batch One-Shot Execution ────────────────────────────────────

    async def resume_approved_batch(self, event: Any, task: TaskMeta) -> list[dict[str, Any]]:
        store = self.engine.store
        receipts: list[dict[str, Any]] = []
        pending_batches = [
            a
            for a in task.approvals
            if a.approval_type == "tool_batch" and a.status == "approved"
        ]
        if not pending_batches:
            return receipts

        profile = store.get_profile(task.profile_id)
        toolset = self.build_task_toolset(task, profile, event)
        consumed_targets: list[tuple[str, int]] = []

        for appr in pending_batches:
            for call_idx, call_spec in enumerate(appr.calls):
                if call_spec.get("execution_status", call_spec.get("status", "pending")) not in {"", "pending", None}:
                    continue
                tname = str(call_spec.get("tool_name") or call_spec.get("tool") or call_spec.get("name") or "")
                targs = dict(call_spec.get("arguments") or call_spec.get("args") or {})
                tool = toolset.get_tool(tname) if hasattr(toolset, "get_tool") else None
                if tool is None and self.engine.context is not None:
                    for cand in self._collect_host_tools(task, event):
                        if getattr(cand, "name", "") == tname:
                            tool = _clone_tool(cand)
                            break

                if tool is None:
                    consumed_targets.append((appr.approval_id, call_idx))
                    receipts.append(
                        {
                            "approval_id": appr.approval_id,
                            "tool_name": tname,
                            "arguments": store.redact_secrets(targs),
                            "ok": False,
                            "receipt": f"未找到已批准的工具 `{tname}`。",
                        }
                    )
                    continue

                try:
                    res = await self.invoke_tool(
                        event, tool, targs, task.task_id, approved_override=True
                    )
                    text, is_err = _extract_result_text(res)
                    consumed_targets.append((appr.approval_id, call_idx))
                    receipts.append(
                        {
                            "approval_id": appr.approval_id,
                            "tool_name": tname,
                            "arguments": store.redact_secrets(targs),
                            "ok": not is_err,
                            "receipt": text[:1200],
                        }
                    )
                except ExecutionStopped as exc:
                    consumed_targets.append((appr.approval_id, call_idx))
                    receipts.append(
                        {
                            "approval_id": appr.approval_id,
                            "tool_name": tname,
                            "arguments": store.redact_secrets(targs),
                            "ok": False,
                            "receipt": str(exc),
                        }
                    )
                    break
                except Exception as exc:
                    consumed_targets.append((appr.approval_id, call_idx))
                    receipts.append(
                        {
                            "approval_id": appr.approval_id,
                            "tool_name": tname,
                            "arguments": store.redact_secrets(targs),
                            "ok": False,
                            "receipt": f"执行失败: {exc}",
                        }
                    )

        if consumed_targets and not store.is_ended(task.task_id):
            fresh = store.load_task(task.umo, task.task_id) or store.find_task_by_id(task.task_id) or task
            if not store.is_ended(task.task_id):
                for appr_id, call_idx in consumed_targets:
                    for f_appr in fresh.approvals:
                        if f_appr.approval_id == appr_id:
                            if 0 <= call_idx < len(f_appr.calls):
                                f_appr.calls[call_idx]["execution_status"] = "consumed"
                                f_appr.calls[call_idx]["status"] = "consumed"
                            if all(
                                c.get("execution_status", c.get("status", "pending")) not in {"", "pending", None}
                                for c in f_appr.calls
                            ):
                                f_appr.status = "consumed"
                                f_appr.resolved_at = f_appr.resolved_at or now_iso()
                            break
                store.save_task(fresh)
        return receipts

    # ── Isolated Conversation Helper ─────────────────────────────────────────

    async def _load_isolated_conversation(
        self, conv_mgr: Any, task: TaskMeta, cid: str
    ) -> tuple[Any, list[dict[str, Any]]]:
        if conv_mgr is None:
            return SimpleNamespace(cid=cid, history="[]", token_usage=0), []

        conv = None
        if hasattr(conv_mgr, "get_conversation"):
            try:
                conv = await conv_mgr.get_conversation(
                    task.umo, cid, create_if_not_exists=False
                )
            except TypeError:
                conv = await conv_mgr.get_conversation(task.umo, cid)

        if conv is None and hasattr(conv_mgr, "db") and hasattr(conv_mgr.db, "create_conversation"):
            platform_id = task.umo.split(":", 1)[0] if ":" in task.umo else "agent_lab"
            try:
                await conv_mgr.db.create_conversation(
                    user_id=task.umo,
                    platform_id=platform_id,
                    content=[],
                    title=f"[AgentLab] {task.goal[:40]}",
                    cid=cid,
                )
                conv = await conv_mgr.get_conversation(
                    task.umo, cid, create_if_not_exists=False
                )
            except Exception:
                conv = None

        if conv is None:
            conv = SimpleNamespace(cid=cid, history="[]", token_usage=0)

        raw_hist = getattr(conv, "history", "[]")
        if isinstance(raw_hist, list):
            contexts = list(raw_hist)
        else:
            try:
                parsed = json.loads(raw_hist or "[]")
                contexts = parsed if isinstance(parsed, list) else []
            except Exception:
                contexts = []
        return conv, contexts

    # ── Single Agent Turn Execution ──────────────────────────────────────────

    async def run_task_turn(self, event: Any, task: TaskMeta) -> dict[str, Any]:
        store = self.engine.store
        ctx = self.engine.context
        if store.is_ended(task.task_id) or task.status != "running":
            return {"ok": False, "reason": "not_running"}

        turn_event = copy.copy(event) if event is not None else SimpleNamespace(unified_msg_origin=task.umo)
        try:
            setattr(turn_event, "agent_lab_runtime", task.task_id)
        except Exception:
            pass
        if hasattr(turn_event, "extras") and isinstance(turn_event.extras, dict):
            turn_event.extras["agent_lab_runtime"] = task.task_id

        # 1. Refresh workspace & execute any newly approved batch once
        task = await self.refresh_workspace(turn_event, task)
        receipts = await self.resume_approved_batch(turn_event, task)
        task = store.find_task_by_id(task.task_id) or task
        if store.is_ended(task.task_id) or task.status != "running":
            return {"ok": False, "reason": task.wait_reason or task.status}

        # 2. Resolve provider, persona, skills, and isolated conversation
        if ctx is None:
            raise RuntimeError("AstrBot context is required to run task turn.")

        provider_id = await ctx.get_current_chat_provider_id(task.umo)
        provider = ctx.get_provider_by_id(provider_id)
        if provider is None and hasattr(ctx, "provider_manager"):
            pm = ctx.provider_manager
            if hasattr(pm, "get_provider_by_id"):
                maybe = pm.get_provider_by_id(provider_id)
                provider = await maybe if inspect.isawaitable(maybe) else maybe
        if provider is None:
            raise RuntimeError(f"Provider {provider_id} not found")

        cfg = ctx.get_config(umo=task.umo) if hasattr(ctx, "get_config") else {}
        provider_settings = (cfg or {}).get("provider_settings", {}) if isinstance(cfg, dict) else {}
        persona_res = resolve_source_persona(ctx, task.umo, provider_settings)
        persona = await persona_res if inspect.isawaitable(persona_res) else persona_res
        persona_prompt = format_persona_prompt(persona)

        skills_res = format_host_skills_prompt(ctx, cfg, persona)
        host_skills = await skills_res if inspect.isawaitable(skills_res) else skills_res

        cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"agent-lab:{task.task_id}"))
        conv_mgr = getattr(ctx, "conversation_manager", None)
        conv, contexts = await self._load_isolated_conversation(conv_mgr, task, cid)

        profile = store.get_profile(task.profile_id)
        project = store.get_project(task.project_id)
        proj_creds = (
            project.execution_settings.authorized_credentials
            if project
            else task.execution_settings.authorized_credentials
        )
        authorized_creds = store.resolve_authorized_credentials(
            task.project_id, profile.authorized_credentials, proj_creds
        )

        # 3. Strictly static system prompt + incremental wake message
        system_prompt = build_static_system_prompt(persona_prompt, profile, host_skills)
        wake_msg, wake_metric = prepare_wake_message(
            store,
            task,
            contexts,
            project_summary=store.task_summary_for_project(task.project_id),
            project_task_prompt=project.execution_settings.task_prompt if project else "",
            authorized_creds=authorized_creds,
            approved_receipts=receipts,
        )

        if isinstance(wake_metric, dict):
            task.usage.last_context_chars = int(
                wake_metric.get("chars", wake_metric.get("context_chars", task.usage.last_context_chars)) or 0
            )
            task.usage.last_estimated_tokens = int(
                wake_metric.get("estimated_tokens", estimate_tokens(wake_msg)) or 0
            )
        else:
            task.usage.last_estimated_tokens = estimate_tokens(wake_msg)

        metered_provider = MeteredProvider(
            provider,
            store=store,
            task=task,
            max_total_tokens=task.execution_settings.budget.max_total_tokens,
            max_tokens_per_tick=task.execution_settings.budget.max_tokens_per_tick,
        )

        toolset = self.build_task_toolset(task, profile, turn_event)
        if _AstrToolLoopAgentRunner is None or _AstrProviderRequest is None:
            raise RuntimeError("AstrBot ToolLoopAgentRunner is unavailable in this environment.")

        runner = _AstrToolLoopAgentRunner()
        tool_executor = _TaskToolExecutor(self, task.task_id, runner=runner)
        agent_hooks = _TaskAgentHooks(self, task.task_id, runner=runner)
        request = _AstrProviderRequest(
            prompt=wake_msg,
            contexts=contexts,
            system_prompt=system_prompt,
            func_tool=toolset,
            conversation=conv,
            session_id=cid,
        )
        timeout_val = max(
            1, int(self.engine.config.get("tool_call_timeout_seconds", 180) or 180)
        )
        if _AstrContextWrapper is not None and _AstrAgentContext is not None:
            try:
                run_context: Any = _AstrContextWrapper(
                    context=_AstrAgentContext(context=ctx, event=turn_event),
                    tool_call_timeout=timeout_val,
                )
            except Exception:
                run_context = SimpleNamespace(
                    context=SimpleNamespace(context=ctx, event=turn_event),
                    tool_call_timeout=timeout_val,
                    messages=[],
                )
        else:
            run_context = SimpleNamespace(
                context=SimpleNamespace(context=ctx, event=turn_event),
                tool_call_timeout=timeout_val,
                messages=[],
            )

        self._turn_fences[task.task_id] = (
            task.authorization_version,
            task.input_revision,
        )
        self._active_runners[task.task_id] = runner

        try:
            await runner.reset(
                provider=metered_provider,
                request=request,
                run_context=run_context,
                tool_executor=tool_executor,
                agent_hooks=agent_hooks,
                streaming=False,
            )

            # Wrap runner.request_context_manager in StageContextManager
            inner_mgr = getattr(runner, "request_context_manager", None)
            tool_schemas_dump = [
                {
                    "name": getattr(t, "name", ""),
                    "description": getattr(t, "description", ""),
                    "parameters": getattr(t, "parameters", {}),
                }
                for t in toolset
            ]
            runner.request_context_manager = StageContextManager(
                store,
                task,
                metered_provider,
                inner=inner_mgr,
                compactor=self.compactor,
                static_system_prompt=system_prompt,
                tool_schemas=tool_schemas_dump,
            )

            max_steps = int(task.execution_settings.budget.native_steps or 24)
            async for _ in runner.step_until_done(max_steps):
                if store.is_ended(task.task_id):
                    runner.request_stop()
                    break

            final_resp = runner.get_final_llm_resp()
            final_text = str(getattr(final_resp, "completion_text", "") or "").strip()
            return {
                "ok": True,
                "completion_text": str(store.redact_secrets(final_text)),
                "usage": task.usage.to_dict(),
            }
        except HandoffError as exc:
            fresh = store.find_task_by_id(task.task_id) or task
            if not store.is_ended(task.task_id):
                fresh.status = "paused"
                fresh.wait_reason = "handoff_error"
                store.save_task(fresh)
                await self.send_dm(
                    fresh.umo,
                    f"⚠️ 上下文交接压缩失败，任务已暂停：{exc}",
                    kind="alert",
                    task_id=fresh.task_id,
                    force=True,
                )
            return {"ok": False, "reason": "handoff_error", "error": str(exc)}
        finally:
            self._turn_fences.pop(task.task_id, None)
            self._active_runners.pop(task.task_id, None)

            if not store.is_ended(task.task_id):
                # Persist only complete tool-call groups back to isolated task conversation
                if conv_mgr is not None and hasattr(conv_mgr, "update_conversation"):
                    msgs = getattr(getattr(runner, "run_context", None), "messages", []) or []
                    safe_history = store.redact_secrets(_sanitize_complete_groups(msgs))
                    try:
                        await conv_mgr.update_conversation(
                            task.umo,
                            cid,
                            history=safe_history,
                            token_usage=task.usage.last_estimated_tokens or None,
                        )
                    except Exception:
                        pass

                fresh = store.find_task_by_id(task.task_id)
                if fresh and not fresh.is_terminal():
                    fresh.usage = task.usage
                    fresh.continuity_state = task.continuity_state
                    store.save_task(fresh)
