"""Optional canvas executor; plain task prompts and schemas never include it."""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import random
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, StarTools, register
from astrbot.core.message.message_event_result import MessageChain

try:
    import astrbot.core.message.components as Comp
except Exception:  # pragma: no cover - optional AstrBot component surface.
    Comp = None

try:
    from quart import jsonify, request, g, has_request_context
except Exception:  # pragma: no cover - AstrBot dashboard provides quart.
    jsonify = None
    request = None

from . import (
    AgentLabService,
    AgentLabStorage,
    AgentSpec,
    AgentRuntime,
    ApprovalRequest,
    AgentMemoryOrchestrator,
    MemoryManager,
    TaskPatternLibrary,
    TaskState,
)
from .api_executor import CustomApiExecutor
from .conditions import (
    evaluate_condition,
    resolve_path,
    schema_compatible,
    schema_validation_errors,
)
from .hooks import AgentLabRunHooks
from .models import TaskBudget, new_id, now_iso
from .models import SubAgentSpec
from .models import WorkflowScope, WorkflowTrigger
from .modules import ModuleRegistry
from .prompts import (
    build_agent_mode_policy,
    build_task_system_prompt,
    build_tick_prompt,
)
from .policy import PermissionPolicy
from .node_runtime import (
    NodeExecutionContext,
    NodeExecutionResult,
    NodeExecutorRegistry,
)
from .runtime import WorkflowDecision, WorkflowRuntime, WorkflowRuntimeRun
from .runtime_runner import AgentRuntimeRunner
from .session_guard import SessionPluginGuard
from .summarizer import AgentSummarizer
from .tool_executor import AstrBotToolExecutor
from .verifier import AgentVerifier
from .webui_server import StandaloneWebUIServer
from .workers import normalize_worker_output, worker_spec_for_node
from .task_control import TaskControl, control as task_control, prompt as task_plan_prompt
from .astrbot_bridge import AstrBotBridge
from .web_api import admin_api
from .node_policy import execute_with_policy
from .projects import Projects
from .workspace_api import WorkspaceAPI
from .execution_settings import native_steps, normalize as normalize_execution_settings
from .task_messages import TaskMessages
from .task_commands import task_command
from .task_permissions import apply_mode, execution_guidance
from .ledger_views import state_summary
from .task_tools import TaskTools, CONTROL_TOOL_NAMES


from .adapter_support import *


class CanvasRuntimeMixin:
    def _workflow_variable(self, task: TaskState, name: str, default: Any = None) -> Any:
        data = self._ensure_workflow_data(task)
        variables = data.get("variables") if isinstance(data.get("variables"), dict) else {}
        key = str(name or "").strip()
        if key in variables:
            return variables.get(key, default)
        resolved = resolve_path(variables, key, None)
        return default if resolved is None else resolved

    def _set_workflow_variable(self, task: TaskState, name: str, value: Any) -> None:
        key = str(name or "").strip()
        if not key:
            return
        data = self._ensure_workflow_data(task)
        variables = data.setdefault("variables", {})
        if not isinstance(variables, dict):
            variables = {}
            data["variables"] = variables
        variables[key] = value
        parts = [part.strip() for part in key.split(".") if part.strip()]
        if len(parts) > 1:
            current = variables
            for part in parts[:-1]:
                child = current.get(part)
                if not isinstance(child, dict):
                    child = {}
                    current[part] = child
                current = child
            current[parts[-1]] = value

    def _record_node_execution(
        self,
        task: TaskState,
        node: dict[str, Any],
        result: NodeExecutionResult,
    ) -> None:
        data = self._ensure_workflow_data(task)
        node_id = str(result.node_id or node.get("id") or "").strip()
        if not node_id:
            return
        counts = data.setdefault("execution_counts", {})
        counts[node_id] = int(counts.get(node_id, 0) or 0) + 1
        payload = {
            "time": now_iso(),
            "node_id": node_id,
            "title": node.get("title") or node_id,
            "runtime_type": node.get("runtime_type") or NodeExecutorRegistry.runtime_type(node),
            "action": node.get("action") or "",
            "execution_mode": node.get("execution_mode") or NodeExecutorRegistry.execution_mode(node),
            "status": result.status,
            "ok": result.ok,
            "outcome": result.outcome,
            "note": result.note,
            "next_node_id": result.next_node_id,
            "attempts": result.attempts,
            "data": result.data,
        }
        data.setdefault("node_outputs", {})[node_id] = payload
        tool_outputs = data.setdefault("tool_outputs", {})
        if isinstance(tool_outputs, dict) and (payload.get("runtime_type") in {"tool", "api"} or payload.get("action") in {"run_tools", "call_api", "http_request", "file_operation", "code_exec"}):
            tool_outputs[node_id] = {
                "tool": (result.data or {}).get("tool_name") or (result.data or {}).get("api_id") or payload.get("action"),
                "input": node.get("tool_args") or node.get("api_payload") or node.get("input_variable") or "",
                "output": result.outcome,
                "parsed": result.data,
            }
        output_variable = str(
            node.get("output_variable")
            or node.get("variable")
            or node.get("output")
            or ""
        ).strip()
        if output_variable:
            self._set_workflow_variable(task, output_variable, result.data or result.outcome)
        output_variables = node.get("output_variables") if isinstance(node.get("output_variables"), list) else []
        for name in output_variables:
            self._set_workflow_variable(task, str(name), result.data or result.outcome)
        task.last_observation = self._compact_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            4000,
        )
        try:
            self.storage.upsert_task_memory_artifact(task, node_id, payload)
        except Exception:
            pass
        self._record_explicit_observation(
            task,
            source="node_executor",
            node_id=node_id,
            payload=payload,
        )
        if hasattr(self, "agent_runtime"):
            if result.ok and not result.blocked and result.status == "completed":
                self.agent_runtime.mark_current(task, completed_node_id=node_id)
            verification = self.verifier.verify_node_result(node=node, result=result)
            self.agent_runtime.record_verdict(
                task,
                node_id=node_id,
                passed=verification.passed,
                status=verification.status,
                reason=verification.reason,
                missing=verification.missing,
                next_action=verification.next_action,
            )
        self._prepare_resume_anchor(task, reason=f"node:{node_id}")

    def _record_explicit_observation(
        self,
        task: TaskState,
        *,
        source: str,
        node_id: str = "",
        payload: Any = None,
    ) -> None:
        data = self._ensure_workflow_data(task)
        observations = data.setdefault("observations", [])
        if not isinstance(observations, list):
            observations = []
        observations.append(
            {
                "time": now_iso(),
                "source": str(source or "runtime"),
                "node_id": str(node_id or task.workflow_current_node_id or ""),
                "payload": payload,
            }
        )
        data["observations"] = observations[-160:]
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_observation(
                task,
                source=source,
                node_id=node_id or task.workflow_current_node_id,
                payload=payload,
                summary=payload,
            )

    def _record_react_trace(
        self,
        task: TaskState,
        *,
        node_id: str,
        prompt: str,
        response: str,
        reason: str,
    ) -> None:
        data = self._ensure_workflow_data(task)
        traces = data.setdefault("react_traces", [])
        current_node = str(node_id or task.workflow_current_node_id or "").strip()
        data_snapshot = {
            "node_id": current_node,
            "goal": self._compact_text(task.root_goal, 500),
            "action_summary": self._compact_text(response, 700),
            "observation": self._compact_text(task.last_observation, 700),
            "next_decision": self._compact_text(task.next_step, 500),
        }
        traces.append(
            {
                "time": now_iso(),
                "node_id": current_node,
                "reason": reason,
                "response": data_snapshot["action_summary"],
                **data_snapshot,
            }
        )
        data["react_traces"] = traces[-80:]
        if hasattr(self, "agent_runtime"):
            decision = self.agent_runtime.record_decision(
                task,
                phase="react",
                action="react_handoff",
                node_id=current_node,
                reason=reason,
                capability="llm.reason",
            )
            self.agent_runtime.record_observation(
                task,
                source="react",
                node_id=current_node,
                decision_id=decision.get("decision_id", ""),
                payload=data_snapshot,
                summary=response,
            )
            self.agent_runtime.update_resume(task, reason=f"react:{reason}")

    def _memory_entry_visible(
        self,
        item: dict[str, Any],
        *,
        umo: str = "",
        active_task: TaskState | None = None,
        allow_private: bool = False,
    ) -> tuple[bool, bool]:
        layer = str(item.get("layer") or "").strip()
        exposed = bool(item.get("expose_to_normal", False))
        status = str(item.get("status") or "candidate").strip().lower()
        source_umo = str(item.get("source_umo") or "")
        source_task_id = str(item.get("source_task_id") or "")
        same_scope = bool(
            allow_private
            and (
                (source_umo and source_umo == umo)
                or (active_task is not None and source_task_id == active_task.task_id)
            )
        )
        if layer in {"private_task_memory", "candidate_memory"}:
            return same_scope, same_scope
        if layer in {"accepted_memory", "archive_summary"}:
            return status == "accepted" and exposed and source_umo == umo, False
        if exposed and status == "accepted":
            return source_umo == umo, False
        return same_scope, same_scope

    def _memory_entry_row(
        self,
        item: dict[str, Any],
        *,
        include_text: bool = True,
        text_limit: int = 0,
    ) -> dict[str, Any]:
        text = str(item.get("text") or "")
        if text_limit > 0:
            text = self._compact_text(text, text_limit)
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        row = {
            "memory_id": item.get("memory_id"),
            "layer": item.get("layer") or "",
            "status": str(item.get("status") or "candidate").strip().lower(),
            "kind": item.get("kind") or "",
            "tags": item.get("tags") or [],
            "source_task_id": item.get("source_task_id") or "",
            "source_umo": item.get("source_umo") or "",
            "updated_at": item.get("updated_at") or "",
            "evidence": {
                "memory_id": evidence.get("memory_id") or item.get("memory_id") or "",
                "source_task_id": evidence.get("source_task_id") or item.get("source_task_id") or "",
                "source_umo": evidence.get("source_umo") or item.get("source_umo") or "",
                "kind": evidence.get("kind") or item.get("kind") or "",
                "layer": evidence.get("layer") or item.get("layer") or "",
            },
        }
        if include_text:
            row["text"] = text
        return row

    @staticmethod
    def _memory_similarity_score(query: str, haystack: str) -> int:
        needle = str(query or "").strip().lower()
        text = str(haystack or "").strip().lower()
        if not needle:
            return 1
        if needle in text:
            return 1000 + len(needle)
        query_terms = {
            token
            for token in re.findall(r"[\w\u4e00-\u9fff]+", needle)
            if len(token) >= 2
        }
        if not query_terms:
            return 0
        text_terms = set(re.findall(r"[\w\u4e00-\u9fff]+", text))
        score = sum(3 for token in query_terms if token in text_terms)
        score += sum(1 for token in query_terms if token in text)
        return score

    def _node_result_to_decision(
        self,
        node: dict[str, Any],
        result: NodeExecutionResult,
    ) -> WorkflowDecision:
        return WorkflowDecision(
            node_id=result.node_id or str(node.get("id") or ""),
            node=node,
            next_node_id=result.next_node_id,
            status=result.status,
            outcome=result.outcome,
            note=result.note,
            needs_react=result.needs_react,
            terminal=result.terminal,
            blocked=result.blocked,
        )

    def _resolve_workflow_template(self, task: TaskState, value: Any) -> Any:
        context = self._condition_context(task)
        if isinstance(value, dict):
            return {key: self._resolve_workflow_template(task, item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._resolve_workflow_template(task, item) for item in value]
        if not isinstance(value, str):
            return value
        text = value.strip()
        whole = re.fullmatch(r"(?:\{\{\s*([^{}]+?)\s*\}\}|\$\{\s*([^{}]+?)\s*\})", text)
        if whole:
            path = (whole.group(1) or whole.group(2) or "").strip()
            resolved = resolve_path(context, path, None)
            return resolved if resolved is not None else ""

        def replace(match: re.Match[str]) -> str:
            path = (match.group(1) or match.group(2) or "").strip()
            resolved = resolve_path(context, path, None)
            if resolved is None:
                return ""
            if isinstance(resolved, str):
                return resolved
            return json.dumps(resolved, ensure_ascii=False, default=str)

        return re.sub(r"\{\{\s*([^{}]+?)\s*\}\}|\$\{\s*([^{}]+?)\s*\}", replace, value)

    def _node_json_object(self, node: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            raw = node.get(key)
            if raw in (None, ""):
                continue
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    return parsed
        return {}

    def _node_templated_json_object(self, task: TaskState, node: dict[str, Any], *keys: str) -> dict[str, Any]:
        payload = self._node_json_object(node, *keys)
        resolved = self._resolve_workflow_template(task, payload)
        return resolved if isinstance(resolved, dict) else {}

    def _node_payload_from_variable(self, task: TaskState, node: dict[str, Any]) -> Any:
        input_variable = str(node.get("input_variable") or "").strip()
        if not input_variable:
            return None
        context = self._condition_context(task)
        value = resolve_path(context, input_variable, None)
        if value is not None:
            return value
        return self._workflow_variable(task, input_variable)

    def _node_json_value(self, task: TaskState, node: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key not in node:
                continue
            raw = node.get(key)
            if raw in (None, ""):
                continue
            if isinstance(raw, str):
                text = raw.strip()
                try:
                    raw = json.loads(text)
                except Exception:
                    raw = text
            return self._resolve_workflow_template(task, raw)
        return None

    def _node_string_list(self, task: TaskState, node: dict[str, Any], *keys: str) -> list[str]:
        value = self._node_json_value(task, node, *keys)
        if isinstance(value, str):
            value = value.replace("；", ",").replace(";", ",").split(",")
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def _json_transform_value(self, source: Any, expression: str) -> Any:
        path = str(expression or "").strip()
        if not path or path in {".", "$"}:
            return source
        if path.startswith("$."):
            path = path[2:]
        elif path.startswith("."):
            path = path[1:]
        if not path:
            return source
        return resolve_path(source, path, None)

    def _sandbox_node_path(self, task: TaskState, raw_path: Any) -> tuple[Path | None, str]:
        value = self._resolve_workflow_template(task, raw_path)
        text = str(value or "").strip()
        if not text:
            return None, "File node requires path/input_path/output_path."
        candidate = Path(text)
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (self.storage.sandbox_workspace_dir / candidate).resolve()
        root = self.storage.sandbox_workspace_dir.resolve()
        try:
            resolved.relative_to(root)
        except Exception:
            return None, f"File path must stay inside sandbox_workspace: {text}"
        return resolved, ""

    def _node_builtin_tool_allowed(
        self,
        spec: AgentSpec,
        node: dict[str, Any],
        tool_name: str,
        *,
        capability: str,
        risk: str,
    ) -> str:
        if not self._tool_allowed_by_agent_profile(spec, tool_name):
            return f"Tool is outside the Agent tool profile: {tool_name}"
        if not self._permission_allows_tool(node, capability=capability, risk=risk):
            return f"Tool permission profile blocks {tool_name}: capability={capability}, risk={risk}"
        return ""

    @staticmethod
    def _candidate_by_action(candidates: list[dict[str, Any]], actions: set[str]) -> str:
        for item in candidates:
            if str(item.get("action") or "").strip() in actions:
                return str(item.get("id") or "").strip()
        return ""

    @staticmethod
    def _candidate_by_stage(candidates: list[dict[str, Any]], stages: set[str]) -> str:
        for item in candidates:
            if str(item.get("stage") or "").strip() in stages:
                return str(item.get("id") or "").strip()
        return ""

    def _route_target_from_node(
        self,
        task: TaskState,
        node: dict[str, Any],
        outgoing: list[str],
        candidates: list[dict[str, Any]],
    ) -> str:
        if len(outgoing) == 1:
            return outgoing[0]
        for key in ("next_node_id", "target_node_id", "route_to", "default_next"):
            target = str(node.get(key) or "").strip()
            if target in outgoing:
                return target

        route_map = self._node_json_object(node, "route_map", "routes")
        route_variable = str(node.get("route_variable") or node.get("input_variable") or "").strip()
        if route_map and route_variable:
            value = self._workflow_variable(task, route_variable)
            for key in (str(value), str(value).lower()):
                target = str(route_map.get(key) or "").strip()
                if target in outgoing:
                    return target
        context = self._condition_context(task)
        default_target = ""
        for item in candidates:
            target = str(item.get("id") or "").strip()
            condition = str(item.get("condition") or item.get("when") or "").strip()
            if not condition:
                continue
            lowered = condition.lower()
            if lowered in {"default", "else", "otherwise"}:
                default_target = target
                continue
            result = evaluate_condition(condition, context)
            if result is True and target in outgoing:
                return target
        if task.pending_approvals():
            return self._candidate_by_action(candidates, {"wait_user", "handoff"}) or self._candidate_by_stage(candidates, {"guard"})

        state_text = "\n".join(
            [
                task.status or "",
                task.current_summary or "",
                task.last_confirmed_progress or "",
                task.last_observation or "",
                " ".join(item.get("issue", "") for item in task.blockers[-3:]),
            ]
        ).lower()
        failed = any(word in state_text for word in ("fail", "failed", "error", "blocked", "失败", "错误", "阻塞"))
        passed = any(word in state_text for word in ("pass", "passed", "ok", "success", "完成", "通过", "成功")) and not failed
        if failed:
            return self._candidate_by_action(candidates, {"retry", "request_approval", "wait_user", "handoff"})
        if passed:
            return self._candidate_by_action(candidates, {"save_state", "save_memory", "notify", "exit_summary", "archive"})

        default_target = default_target
        for item in candidates:
            condition = str(item.get("condition") or "").strip().lower()
            if condition in {"default", "else", "otherwise"}:
                default_target = str(item.get("id") or "").strip()
        return default_target if default_target in outgoing else ""

    def _workflow_trigger_payload(self, task: TaskState) -> dict[str, Any]:
        data = self._ensure_workflow_data(task)
        payload = data.get("trigger_payload")
        return payload if isinstance(payload, dict) else {}

    def _workflow_text_from_context(self, ctx: NodeExecutionContext) -> str:
        value = self._node_payload_from_variable(ctx.task, ctx.node)
        if value is None:
            value = self._node_json_value(ctx.task, ctx.node, "text", "message", "input", "content")
        if value is None:
            payload = self._workflow_trigger_payload(ctx.task)
            value = payload.get("text") or payload.get("message") or payload.get("content")
        if value is None:
            value = getattr(ctx.event, "message_str", "") or ctx.task.root_goal or ctx.task.last_observation
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value or "")

    def _node_patterns(self, task: TaskState, node: dict[str, Any], *keys: str) -> list[str]:
        patterns = self._node_string_list(task, node, *keys)
        if patterns:
            return patterns
        tags = node.get("tags")
        if isinstance(tags, str):
            return [part.strip() for part in re.split(r"[,;\s]+", tags) if part.strip()]
        if isinstance(tags, list):
            return [str(item).strip() for item in tags if str(item).strip()]
        return []

    async def _execute_trigger_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        payload = dict(self._workflow_trigger_payload(ctx.task))
        action = str(ctx.node.get("action") or "").strip()
        if not payload:
            payload = self._build_trigger_payload(
                source=action or "manual",
                event=ctx.event,
                text=getattr(ctx.event, "message_str", "") or ctx.task.root_goal,
            )
            self._ensure_workflow_data(ctx.task)["trigger_payload"] = payload
        trigger = WorkflowTrigger.from_dict(self._as_plain_dict(getattr(ctx.spec, "workflow_trigger", None)))
        if action == "schedule_trigger" and trigger.schedule_payload:
            payload.setdefault("schedule_payload", dict(trigger.schedule_payload))
            payload.update({key: value for key, value in trigger.schedule_payload.items() if key not in payload})
        self._set_workflow_variable(ctx.task, "trigger_payload", payload)
        if action == "schedule_trigger":
            self._set_workflow_variable(ctx.task, trigger.schedule_output_variable, payload)
        elif action == "plugin_event_trigger":
            self._set_workflow_variable(ctx.task, trigger.plugin_payload_variable, payload.get("payload") or payload)
        data = {
            "route": "success",
            "source": payload.get("source") or action,
            "text": payload.get("text") or "",
            "payload": payload,
        }
        return NodeExecutionResult(
            outcome=f"Trigger accepted from {data['source'] or 'workflow'}.",
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=False,
            advance=True,
            note="node_executor_trigger",
        )

    async def _execute_detector_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        text = self._workflow_text_from_context(ctx)
        route = "uncertain"
        matched: list[str] = []
        error = ""
        if action == "scope_filter":
            allowed, reason = self._workflow_scope_allows_event(ctx.spec, ctx.event)
            route = "success" if allowed else "failed"
            matched = [reason]
        elif action in {"match_keyword", "llm_detect"}:
            keywords = self._node_patterns(
                ctx.task,
                ctx.node,
                "keywords",
                "keyword",
                "patterns",
                "rules",
                "allow",
                "deny",
            )
            lowered = text.lower()
            matched = [item for item in keywords if item.lower() in lowered]
            if keywords:
                route = "success" if matched else "failed"
            elif action == "llm_detect":
                llm_result = await self._run_constrained_llm_detector(ctx, text)
                route = str(llm_result.get("route") or "uncertain")
                matched = [str(item) for item in llm_result.get("evidence") or [] if str(item).strip()]
        elif action == "match_regex":
            patterns = self._node_patterns(ctx.task, ctx.node, "regex", "pattern", "patterns")
            for pattern in patterns:
                try:
                    if re.search(pattern, text, flags=re.IGNORECASE):
                        matched.append(pattern)
                except re.error as exc:
                    error = f"Invalid regex {pattern}: {exc}"
                    route = "error"
                    break
            if not error:
                route = "success" if matched else ("failed" if patterns else "uncertain")

        data = {
            "route": route,
            "matched": matched,
            "text": self._compact_text(text, 1000),
            "action": action,
        }
        if action == "llm_detect" and "llm_result" in locals():
            data["llm_result"] = llm_result
        if error:
            data["error"] = error
        return NodeExecutionResult(
            ok=route in {"success", "failed", "uncertain"},
            status="completed" if route != "error" else "blocked",
            outcome=f"Detector route={route}; matched={len(matched)}." if not error else error,
            data=data,
            blocked=route == "error",
            note="node_executor_detector",
        )

    async def _run_constrained_llm_detector(
        self,
        ctx: NodeExecutionContext,
        text: str,
    ) -> dict[str, Any]:
        criteria = str(
            ctx.node.get("criteria")
            or ctx.node.get("instruction")
            or ctx.node.get("prompt")
            or ctx.node.get("description")
            or "Classify whether the input matches the detector."
        ).strip()
        examples = {
            "positive": self._node_string_list(ctx.task, ctx.node, "positive_examples", "pass_examples"),
            "negative": self._node_string_list(ctx.task, ctx.node, "negative_examples", "fail_examples"),
        }
        try:
            threshold = max(0.0, min(float(ctx.node.get("confidence_threshold") or 0.65), 1.0))
        except Exception:
            threshold = 0.65
        prompt = json.dumps(
            {
                "criteria": criteria,
                "allowed_routes": ["success", "failed", "uncertain", "error"],
                "confidence_threshold": threshold,
                "examples": examples,
                "input_text": self._compact_text(text, 4000),
                "required_json": {
                    "route": "success|failed|uncertain|error",
                    "reason": "short reason",
                    "evidence": ["quoted evidence"],
                    "confidence": 0.0,
                },
            },
            ensure_ascii=False,
        )
        system_prompt = (
            "You are a constrained workflow detector. Return one JSON object only. "
            "Do not execute actions. Use route=uncertain when evidence is insufficient."
        )
        provider_ids: list[str] = []
        provider_id = ""  # Primary nodes inherit the source bot; explicit subagent overrides are separate.
        if provider_id:
            provider_ids.append(provider_id)
        try:
            current = await self.context.get_current_chat_provider_id(ctx.event.unified_msg_origin)
            if current and current not in provider_ids:
                provider_ids.append(current)
        except Exception:
            pass
        fallback = str(_cfg(self.config, "fallback_summary_provider_id", "") or "").strip()
        if fallback and fallback not in provider_ids:
            provider_ids.append(fallback)
        last_error = ""
        for provider_id in provider_ids:
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                raw = str(getattr(resp, "completion_text", "") or "").strip()
                parsed = self._parse_detector_json(raw)
                parsed["provider_id"] = provider_id
                confidence = float(parsed.get("confidence") or 0)
                if parsed.get("route") in {"success", "failed"} and confidence < threshold:
                    parsed["route"] = "uncertain"
                    parsed["reason"] = f"confidence {confidence:.2f} below threshold {threshold:.2f}: {parsed.get('reason') or ''}"
                return parsed
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
        return {
            "route": "uncertain",
            "reason": last_error or "llm detector provider unavailable",
            "evidence": [],
            "confidence": 0.0,
        }

    @staticmethod
    def _parse_detector_json(raw: str) -> dict[str, Any]:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\s*```$", "", text).strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("detector JSON must be an object")
        route = str(parsed.get("route") or "uncertain").strip().lower()
        if route not in {"success", "failed", "uncertain", "error"}:
            route = "uncertain"
        evidence = parsed.get("evidence")
        if isinstance(evidence, str):
            evidence = [evidence]
        elif not isinstance(evidence, list):
            evidence = []
        try:
            confidence = max(0.0, min(float(parsed.get("confidence") or 0), 1.0))
        except Exception:
            confidence = 0.0
        return {
            "route": route,
            "reason": str(parsed.get("reason") or "").strip()[:1000],
            "evidence": [str(item).strip()[:400] for item in evidence if str(item).strip()][:12],
            "confidence": confidence,
        }

    async def _execute_rate_limit_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        try:
            window_seconds = max(1, min(int(ctx.node.get("window_seconds") or ctx.node.get("window") or 60), 86400))
        except Exception:
            window_seconds = 60
        try:
            max_hits = max(1, min(int(ctx.node.get("max_hits") or ctx.node.get("limit") or 5), 10000))
        except Exception:
            max_hits = 5
        key_parts = [
            str(ctx.node.get("id") or ""),
            str(ctx.node.get("bucket") or ""),
            str(getattr(ctx.event, "unified_msg_origin", "") or ""),
            str(ctx.event.get_sender_id() if hasattr(ctx.event, "get_sender_id") else ""),
        ]
        bucket_key = hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()[:24]
        data = self._ensure_workflow_data(ctx.task)
        buckets = data.setdefault("rate_limits", {})
        if not isinstance(buckets, dict):
            buckets = {}
            data["rate_limits"] = buckets
        now_ts = time.time()
        hits = [
            float(item)
            for item in buckets.get(bucket_key, [])
            if isinstance(item, (int, float)) and now_ts - float(item) <= window_seconds
        ]
        hits.append(now_ts)
        buckets[bucket_key] = hits[-max_hits * 2 :]
        allowed = len(hits) <= max_hits
        route = "success" if allowed else "failed"
        return NodeExecutionResult(
            ok=True,
            status="completed",
            outcome=f"Rate limit route={route}; hits={len(hits)}/{max_hits}.",
            data={
                "route": route,
                "bucket": bucket_key,
                "hits": len(hits),
                "max_hits": max_hits,
                "window_seconds": window_seconds,
            },
            note="node_executor_rate_limit",
        )

    async def _execute_catch_error_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        latest = next(reversed(outputs.values()), {}) if outputs else {}
        has_error = bool(
            ctx.task.blockers
            or (isinstance(latest, dict) and (latest.get("blocked") or latest.get("ok") is False))
        )
        disposition = str(ctx.node.get("disposition") or "route").strip().lower()
        if disposition not in {"route", "retry", "notify", "report", "pause"}:
            disposition = "route"
        if has_error and disposition == "pause":
            ctx.task.set_wait(
                wait_reason="blocked_by_error",
                message=str(ctx.node.get("instruction") or "捕获到错误，已暂停等待人工处理。"),
                source="workflow_catch_error_node",
            )
            ctx.task.status = "paused"
            return NodeExecutionResult(
                ok=False,
                status="running",
                outcome="捕获到错误，已暂停等待人工处理。",
                advance=False,
                data={"route": "error", "disposition": disposition, "wait": True, "latest": latest},
                note="node_executor_catch_error",
            )
        if has_error:
            route = "retry" if disposition == "retry" else "error"
        else:
            route = "success"
        return NodeExecutionResult(
            ok=True,
            status="completed",
            outcome=f"Catch error route={route}; disposition={disposition}.",
            data={"route": route, "disposition": disposition, "latest": latest, "blockers": list(ctx.task.blockers or [])[-8:]},
            note="node_executor_catch_error",
        )

    async def _execute_record_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if payload is None:
            payload = self._node_templated_json_object(ctx.task, ctx.node, "payload", "record", "data")
        record = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "title": str(ctx.node.get("title") or ""),
            "payload": payload,
        }
        data = self._ensure_workflow_data(ctx.task)
        records = data.setdefault("records", [])
        if not isinstance(records, list):
            records = []
        records.append(record)
        data["records"] = records[-120:]
        ctx.task.add_log("workflow_record", self._compact_text(json.dumps(record, ensure_ascii=False), 800))
        return NodeExecutionResult(
            outcome="Workflow record written.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "record": record},
            needs_react=False,
            advance=True,
            note="node_executor_record",
        )

    async def _execute_report_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        try:
            node_outputs_snapshot = json.loads(
                json.dumps(data.get("node_outputs") or {}, ensure_ascii=False, default=str)
            )
        except Exception:
            node_outputs_snapshot = {}
        payload = {
            "time": now_iso(),
            "task_id": ctx.task.task_id,
            "agent_id": ctx.spec.agent_id,
            "trigger": data.get("trigger_payload") or {},
            "path": list(ctx.task.workflow_path or []),
            "node_outputs": node_outputs_snapshot,
            "blockers": list(ctx.task.blockers or [])[-12:],
        }
        reports = data.setdefault("reports", [])
        if not isinstance(reports, list):
            reports = []
        reports.append(payload)
        data["reports"] = reports[-40:]
        summary = self._compact_text(
            str(ctx.node.get("template") or ctx.node.get("message") or "")
            or f"Workflow report generated for task {ctx.task.task_id}.",
            1200,
        )
        ctx.task.add_log("workflow_report", summary)
        return NodeExecutionResult(
            outcome=summary,
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "report": payload, "summary": summary},
            needs_react=False,
            advance=True,
            note="node_executor_report",
        )

    async def _execute_entry_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        if action == "summarize_entry":
            outcome = f"Entry brief is available for task {ctx.task.task_id}."
        elif action == "confirm_entry":
            outcome = "Entry confirmation is satisfied because the task exists."
        else:
            outcome = "Session isolation snapshot is already applied for this task."
        data = {"action": action, "task_id": ctx.task.task_id}
        # Inject pattern recommendations at entry time so the first planning
        # pass already has relevant past patterns available.
        if action == "summarize_entry" and hasattr(self, "pattern_library"):
            try:
                goal = str(ctx.task.root_goal or "")
                if goal:
                    patterns = self.pattern_library.recommend(
                        goal, limit=3, exclude_task_id=ctx.task.task_id
                    )
                    if patterns:
                        data["pattern_recommendations"] = [
                            self.pattern_library.compact_for_runtime(p)
                            for p in patterns
                        ]
            except Exception:
                pass
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_entry",
        )

    async def _execute_state_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        if action == "heartbeat":
            ctx.task.heartbeat.last_pulse_at = now_iso()
            outcome = "Heartbeat checkpoint recorded."
            data = {"heartbeat_enabled": ctx.task.heartbeat.enabled}
        elif action == "variable_set":
            variable_name = str(
                ctx.node.get("variable_name")
                or ctx.node.get("name")
                or ctx.node.get("output_variable")
                or ctx.node.get("variable")
                or ""
            ).strip()
            if not variable_name:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome="variable_set requires variable_name.",
                    blocked=True,
                    advance=False,
                    note="node_executor_variable_set_missing_name",
                )
            value = self._node_payload_from_variable(ctx.task, ctx.node)
            if value is None:
                value = self._node_json_value(ctx.task, ctx.node, "value", "payload", "data")
            self._set_workflow_variable(ctx.task, variable_name, value)
            outcome = f"Variable {variable_name} set."
            data = {"variable": variable_name, "value": value}
        elif action == "variable_get":
            variable_name = str(
                ctx.node.get("variable_name")
                or ctx.node.get("name")
                or ctx.node.get("input_variable")
                or ctx.node.get("variable")
                or ""
            ).strip()
            if not variable_name:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome="variable_get requires variable_name.",
                    blocked=True,
                    advance=False,
                    note="node_executor_variable_get_missing_name",
                )
            value = resolve_path(self._condition_context(ctx.task), variable_name, None)
            if value is None:
                value = self._workflow_variable(ctx.task, variable_name)
            outcome = f"Variable {variable_name} read."
            data = {"variable": variable_name, "value": value}
        elif action == "text_template":
            template = str(
                ctx.node.get("template")
                or ctx.node.get("text")
                or ctx.node.get("prompt")
                or ctx.node.get("instruction")
                or ""
            )
            rendered = self._resolve_workflow_template(ctx.task, template)
            rendered_text = str(rendered if rendered is not None else "")
            outcome = "Text template rendered."
            data = {"text": rendered_text}
        elif action in {"llm_prompt", "prompt_transform"}:
            data = await self._run_llm_prompt_node(ctx)
            route = str(data.get("route") or "success").strip().lower()
            return NodeExecutionResult(
                ok=route in {"success", "failed", "uncertain"},
                status="completed" if route != "error" else "blocked",
                outcome=str(data.get("reason") or f"LLM prompt route={route}."),
                next_node_id=self._single_next(ctx.outgoing) if route == "success" and len(ctx.outgoing) <= 1 else "",
                data=data,
                needs_react=False,
                advance=route == "success" and len(ctx.outgoing) <= 1,
                blocked=route == "error",
                note="node_executor_llm_prompt",
            )
        elif action == "plugin_prompt":
            plugin_name = str(
                ctx.node.get("plugin_name")
                or ctx.node.get("plugin")
                or ctx.node.get("target_plugin")
                or ctx.node.get("ref_id")
                or ""
            ).strip()
            if not plugin_name:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome="plugin_prompt requires plugin_name.",
                    blocked=True,
                    advance=False,
                    note="node_executor_plugin_prompt_missing_plugin",
                )
            wants_admin = bool(ctx.node.get("impersonate_admin") or ctx.node.get("as_admin"))
            admin_user_id = str(ctx.node.get("admin_user_id") or ctx.node.get("operator_user_id") or "").strip()
            try:
                sender_id = str(ctx.event.get_sender_id() or "").strip()
            except Exception:
                sender_id = ""
            admin_ids = set(self._workflow_admin_ids())
            if wants_admin and sender_id not in admin_ids and (not admin_user_id or sender_id != admin_user_id):
                ctx.task.status = "paused"
                ctx.task.set_wait(
                    wait_reason="need_admin_operator",
                    message=(
                        f"Plugin prompt {plugin_name} requested administrator impersonation, "
                        "but the current sender is not allowed. Adapter sender override may be unsupported."
                    ),
                    source="workflow_plugin_prompt",
                    required_input=[plugin_name],
                )
                return NodeExecutionResult(
                    ok=False,
                    status="running",
                    outcome="Plugin prompt needs an allowed administrator/operator before continuing.",
                    advance=False,
                    blocked=False,
                    data={
                        "route": "failed",
                        "plugin_name": plugin_name,
                        "impersonate_admin": True,
                        "admin_user_id": admin_user_id,
                        "sender_id": sender_id,
                        "adapter_boundary": "sender-role override depends on the AstrBot adapter",
                    },
                    note="node_executor_plugin_prompt_admin_boundary",
                )
            prompt = self._workflow_node_text(ctx, "plugin_prompt", "prompt", "message", "instruction")
            if not prompt:
                prompt = "Use the selected AstrBot plugin to complete this workflow step."
            handoff = {
                "time": now_iso(),
                "node_id": str(ctx.node.get("id") or ""),
                "plugin_name": plugin_name,
                "prompt": self._compact_text(prompt, 4000),
                "input": self._node_payload_from_variable(ctx.task, ctx.node),
                "impersonate_admin": wants_admin,
                "admin_user_id": admin_user_id,
                "adapter_boundary": "No direct plugin adapter is executed here; ReAct/tool routing must call the plugin if available.",
            }
            data_root = self._ensure_workflow_data(ctx.task)
            plugin_prompts = data_root.setdefault("plugin_prompts", [])
            if not isinstance(plugin_prompts, list):
                plugin_prompts = []
            plugin_prompts.append(handoff)
            data_root["plugin_prompts"] = plugin_prompts[-80:]
            self._set_workflow_variable(ctx.task, str(ctx.node.get("output_variable") or "plugin_prompt"), handoff)
            return NodeExecutionResult(
                outcome=f"Plugin prompt prepared for {plugin_name}.",
                next_node_id=self._single_next(ctx.outgoing) if len(ctx.outgoing) <= 1 else "",
                data={"route": "success", **handoff},
                needs_react=True,
                advance=len(ctx.outgoing) <= 1,
                note="node_executor_plugin_prompt",
            )
        elif action == "json_transform":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = self._node_json_value(ctx.task, ctx.node, "source", "payload", "data")
            expression = str(
                ctx.node.get("expression")
                or ctx.node.get("path")
                or ctx.node.get("json_path")
                or ctx.node.get("jq")
                or "."
            ).strip()
            transformed = self._json_transform_value(source, expression)
            outcome = f"JSON transform applied: {expression or '.'}."
            data = {"value": transformed, "expression": expression or "."}
        elif action == "merge":
            names = self._node_string_list(ctx.task, ctx.node, "inputs", "input_variables", "sources")
            merged: dict[str, Any] = {}
            if names:
                context = self._condition_context(ctx.task)
                for name in names:
                    value = resolve_path(context, name, None)
                    if value is None:
                        value = self._workflow_variable(ctx.task, name)
                    merged[name] = value
            else:
                node_outputs = (self._ensure_workflow_data(ctx.task).get("node_outputs") or {})
                for candidate in ctx.next_candidates:
                    node_id = str(candidate.get("id") or "")
                    if node_id in node_outputs:
                        merged[node_id] = node_outputs[node_id]
                if not merged:
                    merged = dict(node_outputs)
            outcome = f"Merged {len(merged)} input(s)."
            data = {"merged": merged}
        elif action == "iterator":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = self._node_json_value(ctx.task, ctx.node, "items", "source", "payload")
            if isinstance(source, dict):
                items = [{"key": key, "value": value} for key, value in source.items()]
            elif isinstance(source, list):
                items = list(source)
            else:
                items = []
            outcome = f"Iterator prepared {len(items)} item(s)."
            data = {"items": items, "count": len(items)}
        elif action == "subflow_call":
            template_id = str(ctx.node.get("template_id") or ctx.node.get("ref_id") or "").strip()
            params = self._node_templated_json_object(ctx.task, ctx.node, "params", "arguments", "payload")
            outcome = "Subflow call prepared; nested runner is not enabled yet."
            data = {"template_id": template_id, "params": params, "runner": "pending"}
        elif action == "transform_context":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = ctx.task.last_observation or ctx.task.current_summary or ctx.task.last_confirmed_progress
            text = self._compact_text(
                source if isinstance(source, str) else json.dumps(source, ensure_ascii=False),
                1600,
            )
            if text:
                ctx.task.current_summary = text
            outcome = "Context transformed into compact observation."
            data = {"summary": text}
        else:
            outcome = "Task checkpoint saved."
            data = {
                "current_summary": ctx.task.current_summary,
                "progress": ctx.task.last_confirmed_progress,
                "next_step": ctx.task.next_step,
            }
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_state",
        )

    async def _run_llm_prompt_node(self, ctx: NodeExecutionContext) -> dict[str, Any]:
        source = self._node_payload_from_variable(ctx.task, ctx.node)
        if source is None:
            source = self._node_json_value(ctx.task, ctx.node, "input", "text", "content")
        if source is None:
            source = self._workflow_trigger_payload(ctx.task).get("text") or ctx.task.last_observation or ctx.task.root_goal
        output_mode = str(ctx.node.get("output_mode") or ctx.node.get("format") or "text").strip().lower()
        if output_mode not in {"text", "json", "route"}:
            output_mode = "text"
        schema = self._node_schema(ctx.node, "output_schema")
        user_prompt = str(
            ctx.node.get("user_prompt")
            or ctx.node.get("prompt")
            or ctx.node.get("instruction")
            or "Transform the input for the next workflow node."
        ).strip()
        system_prompt = str(
            ctx.node.get("system_prompt")
            or "You are a bounded workflow prompt module. Do not execute actions or reveal secrets."
        ).strip()
        prompt_payload = {
            "instruction": user_prompt,
            "output_mode": output_mode,
            "allowed_routes": ["success", "failed", "uncertain", "error"],
            "output_schema": schema or {},
            "input": source,
        }
        prompt = json.dumps(prompt_payload, ensure_ascii=False, default=str)
        if output_mode in {"json", "route"}:
            system_prompt += " Return one JSON object only."
        provider_ids: list[str] = []
        provider_id = ""  # Primary nodes inherit the source bot; explicit subagent overrides are separate.
        if provider_id:
            provider_ids.append(provider_id)
        try:
            current = await self.context.get_current_chat_provider_id(ctx.event.unified_msg_origin)
            if current and current not in provider_ids:
                provider_ids.append(current)
        except Exception:
            pass
        fallback = str(_cfg(self.config, "fallback_summary_provider_id", "") or "").strip()
        if fallback and fallback not in provider_ids:
            provider_ids.append(fallback)
        last_error = ""
        for provider_id in provider_ids:
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                raw = self._redact_known_secrets(str(getattr(resp, "completion_text", "") or "").strip())
                if output_mode == "text":
                    return {"route": "success", "text": raw, "provider_id": provider_id}
                parsed = self._parse_prompt_json(raw)
                if output_mode == "route":
                    route = str(parsed.get("route") or "uncertain").strip().lower()
                    if route not in {"success", "failed", "uncertain", "error"}:
                        route = "uncertain"
                    parsed["route"] = route
                else:
                    parsed.setdefault("route", "success")
                if schema:
                    schema_message = self._schema_validation_message(schema, parsed, "LLM prompt output")
                    if schema_message:
                        return {"route": "error", "reason": schema_message, "raw": raw, "provider_id": provider_id}
                parsed["provider_id"] = provider_id
                return parsed
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
        return {"route": "error", "reason": last_error or "llm prompt provider unavailable"}

    @staticmethod
    def _parse_prompt_json(raw: str) -> dict[str, Any]:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"\s*```$", "", text).strip()
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            text = match.group(0)
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("prompt output must be a JSON object")
        return parsed

    async def _execute_http_request_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        gate = self._node_builtin_tool_allowed(
            ctx.spec,
            ctx.node,
            CUSTOM_API_TOOL_NAME,
            capability="api",
            risk="work",
        )
        if gate:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=gate,
                blocked=True,
                advance=False,
                note="node_executor_http_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, CUSTOM_API_TOOL_NAME)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_http_budget",
            )
        url = str(self._resolve_workflow_template(ctx.task, ctx.node.get("url") or "") or "").strip()
        if not url:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="http_request requires url.",
                blocked=True,
                advance=False,
                note="node_executor_http_missing_url",
            )
        method = str(ctx.node.get("method") or "GET").strip().upper()
        if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
            method = "GET"
        payload = self._node_templated_json_object(ctx.task, ctx.node, "payload", "request", "api_payload")
        query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
        headers = payload.get("headers") if isinstance(payload.get("headers"), dict) else {}
        body = payload.get("body") if "body" in payload else None
        try:
            timeout_seconds = max(1, min(int(ctx.node.get("timeout_seconds") or 30), 120))
        except Exception:
            timeout_seconds = 30
        result = await asyncio.to_thread(
            self._perform_custom_api_http_call,
            method,
            url,
            query,
            body,
            {str(key): str(value) for key, value in headers.items()},
            timeout_seconds,
        )
        ok = bool(result.get("ok"))
        data = {"ok": ok, "method": method, "url_host": self._safe_url_host(url), **result}
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=f"HTTP {method} {self._safe_url_host(url) or url} status={result.get('status')}",
            next_node_id=self._single_next(ctx.outgoing) if ok else "",
            data=data,
            blocked=not ok,
            note="node_executor_http",
        )

    async def _execute_identity_session_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        data = self._ensure_workflow_data(ctx.task)
        sessions = data.setdefault("identity_sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            data["identity_sessions"] = sessions
        credential_id = str(ctx.node.get("credential_id") or ctx.node.get("ref_id") or "").strip()
        provider = str(ctx.node.get("provider") or ctx.node.get("site") or ctx.node.get("domain") or "").strip()
        account = str(ctx.node.get("account") or ctx.node.get("username") or ctx.node.get("login") or "").strip()
        session_id = str(ctx.node.get("session_id") or ctx.node.get("name") or "").strip()
        if not session_id:
            seed = "|".join([action, provider, account, credential_id, str(ctx.node.get("id") or "")])
            session_id = "sess_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        if action == "secret_redaction":
            source = self._node_payload_from_variable(ctx.task, ctx.node)
            if source is None:
                source = self._node_json_value(ctx.task, ctx.node, "text", "payload", "content")
            redacted = self._redact_known_secrets(source)
            return NodeExecutionResult(
                outcome="Secret redaction applied.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "redacted": redacted},
                note="node_executor_secret_redaction",
            )
        if action == "credential_scope":
            allowed = self._identity_scope_allowed(ctx.spec, ctx.node)
            route = "success" if allowed else "failed"
            return NodeExecutionResult(
                ok=True,
                status="completed",
                outcome="Credential scope allowed." if allowed else "Credential scope denied.",
                next_node_id=self._single_next(ctx.outgoing) if allowed else "",
                data={"route": route, "provider": provider, "credential_id": credential_id, "allowed": allowed},
                note="node_executor_credential_scope",
            )
        if action in {"credential_ref", "cookie_jar", "browser_profile"}:
            session = self._identity_session_descriptor(ctx.node, session_id=session_id, action=action)
            if credential_id:
                public_credential = self._credential_public_row(credential_id)
                if not public_credential or not public_credential.get("has_value"):
                    return NodeExecutionResult(
                        ok=False,
                        status="blocked",
                        outcome=f"Credential is missing or empty: {credential_id}",
                        data={"route": "failed", "credential_id": credential_id},
                        blocked=True,
                        advance=False,
                        note="node_executor_identity_missing_credential",
                    )
                session["credential"] = public_credential
            sessions[session_id] = session
            self._set_workflow_variable(ctx.task, str(ctx.node.get("output_variable") or "identity_session"), session)
            return NodeExecutionResult(
                outcome=f"Identity session reference prepared: {session_id}.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "session": session},
                note="node_executor_identity_reference",
            )
        if action == "refresh_session":
            return NodeExecutionResult(ok=False, status="blocked", blocked=True, advance=False,
                outcome="刷新会话需要绑定实际刷新 API/工具；当前仅保存凭证引用，不代表令牌已刷新。", note="session_refresh_requires_executor")
        if action in {"session_check"}:
            session = sessions.get(session_id) if isinstance(sessions.get(session_id), dict) else {}
            has_credential = bool(credential_id and self.storage.get_credential_secret(credential_id))
            has_reference = bool(session or has_credential or ctx.node.get("profile_path") or ctx.node.get("cookie_domain"))
            route = "success" if has_reference else "failed"
            if action == "refresh_session" and route == "success":
                session = dict(session or self._identity_session_descriptor(ctx.node, session_id=session_id, action=action))
                session["refreshed_at"] = now_iso()
                session["status"] = "refresh_requested"
                sessions[session_id] = session
            return NodeExecutionResult(
                ok=True,
                status="completed",
                outcome=f"Identity session {action} route={route}.",
                next_node_id=self._single_next(ctx.outgoing) if route == "success" else "",
                data={"route": route, "session_id": session_id, "session": self._public_identity_session(session)},
                note=f"node_executor_{action}",
            )
        if action in {"login_flow", "human_login_handoff"}:
            message = str(
                ctx.node.get("message")
                or ctx.node.get("instruction")
                or "Login/2FA/captcha requires administrator handoff before this workflow can continue."
            ).strip()
            session = self._identity_session_descriptor(ctx.node, session_id=session_id, action=action)
            session["status"] = "waiting_human_login"
            session["handoff_message"] = message
            sessions[session_id] = session
            ctx.task.status = "paused"
            ctx.task.set_wait(
                wait_reason="need_login",
                message=message,
                source=f"workflow_{action}",
                required_input=[provider or session_id or "login"],
            )
            return NodeExecutionResult(
                ok=False,
                status="running",
                outcome=message,
                data={"route": "timeout", "session": self._public_identity_session(session)},
                advance=False,
                note=f"node_executor_{action}",
            )
        if action == "revoke_session":
            existed = session_id in sessions
            sessions.pop(session_id, None)
            return NodeExecutionResult(
                ok=True,
                status="completed",
                outcome="Identity session revoked." if existed else "Identity session was already absent.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "session_id": session_id, "revoked": existed},
                note="node_executor_revoke_session",
            )
        return NodeExecutionResult(
            ok=False,
            status="blocked",
            outcome=f"Unsupported identity/session action: {action}",
            data={"route": "error"},
            blocked=True,
            advance=False,
            note="node_executor_identity_unknown",
        )

    def _credential_public_row(self, credential_id: str) -> dict[str, Any] | None:
        for item in self.storage.list_credentials():
            if str(item.get("credential_id") or "") == str(credential_id or ""):
                return dict(item)
        return None

    def _identity_session_descriptor(self, node: dict[str, Any], *, session_id: str, action: str) -> dict[str, Any]:
        credential_id = str(node.get("credential_id") or node.get("ref_id") or "").strip()
        provider = str(node.get("provider") or node.get("site") or node.get("domain") or "").strip()
        profile_path = str(node.get("profile_path") or node.get("browser_profile") or "").strip()
        cookie_domain = str(node.get("cookie_domain") or node.get("domain") or "").strip()
        scopes = self._clean_string_list(node.get("scopes") or node.get("scope") or [])
        return {
            "session_id": session_id,
            "type": action,
            "provider": provider,
            "account": str(node.get("account") or node.get("username") or "").strip(),
            "credential_id": credential_id,
            "has_credential": bool(credential_id and self.storage.get_credential_secret(credential_id)),
            "cookie_domain": cookie_domain,
            "cookie_ref": str(node.get("cookie_ref") or "").strip(),
            "profile_path": profile_path,
            "scopes": scopes,
            "status": "referenced",
            "created_at": now_iso(),
            "secret_material": "redacted",
        }

    @staticmethod
    def _public_identity_session(session: dict[str, Any]) -> dict[str, Any]:
        public = dict(session or {})
        for key in ("cookie", "cookies", "token", "password", "secret", "encrypted_value"):
            public.pop(key, None)
        if public.get("has_credential"):
            public["masked_value"] = "********"
        public["secret_material"] = "redacted"
        return public

    def _identity_scope_allowed(self, spec: AgentSpec, node: dict[str, Any]) -> bool:
        credential_id = str(node.get("credential_id") or node.get("ref_id") or "").strip()
        provider = str(node.get("provider") or node.get("site") or "").strip().lower()
        requested_scopes = set(self._clean_string_list(node.get("scopes") or node.get("scope") or []))
        if credential_id and not self.storage.get_credential_secret(credential_id):
            return False
        allowed = set(str(item).strip().lower() for item in (spec.approval_policy.preapproved_scopes or []) if str(item).strip())
        if not requested_scopes:
            return True
        if not allowed:
            return False
        normalized = set(scope.lower() for scope in requested_scopes)
        if provider and provider in allowed:
            return True
        return bool(normalized.intersection(allowed))

    async def _execute_file_operation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        operation = str(ctx.node.get("operation") or ctx.node.get("edit_mode") or "read").lower()
        path = str(self._resolve_workflow_template(ctx.task, ctx.node.get("path") or ctx.node.get("input_path") or ctx.node.get("output_path") or ""))
        if not path:
            return NodeExecutionResult(ok=False, blocked=True, advance=False, outcome="文件节点需要路径。")
        if operation == "read":
            name, arguments = "astrbot_file_read_tool", {"path": path}
        elif operation in {"write", "replace"}:
            name, arguments = "astrbot_file_write_tool", {"path": path, "content": str(self._node_json_value(ctx.task, ctx.node, "content", "text", "value") or "")}
        elif operation == "append":
            content = str(self._node_json_value(ctx.task, ctx.node, "content", "text", "value") or "")
            code = "from pathlib import Path\np = Path(" + repr(path) + ")\np.parent.mkdir(parents=True, exist_ok=True)\nwith p.open('a', encoding='utf-8') as f: f.write(" + repr(content) + ")"
            return await self._execute_code_exec_node(NodeExecutionContext(event=ctx.event, task=ctx.task, spec=ctx.spec,
                node={**ctx.node, "code": code, "language": "python"}, outgoing=ctx.outgoing, next_candidates=ctx.next_candidates, reason=ctx.reason))
        else:
            return NodeExecutionResult(ok=False, blocked=True, advance=False, outcome="不支持的文件操作：" + operation)
        result = await self.tool_executor.call(event=ctx.event, task=ctx.task, spec=ctx.spec, node=ctx.node, tool_name=name, call_args=arguments)
        return NodeExecutionResult(ok=result.ok, blocked=result.blocked, outcome=result.outcome, data=result.data,
            advance=result.ok and not result.blocked and not result.needs_react, needs_react=result.needs_react,
            next_node_id=self._single_next(ctx.outgoing), note="native_file_executor")

    async def _execute_code_exec_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        language = str(ctx.node.get("language") or "python").lower()
        runtime = _cfg(self._context_config(ctx.task.umo), "provider_settings", {}).get("computer_use_runtime", "none")
        code = str(self._node_json_value(ctx.task, ctx.node, "code", "script", "command") or "")
        if language in {"python", "py"}:
            name = "astrbot_execute_python" if runtime == "local" else "astrbot_execute_ipython"
            arguments = {"code": code, "timeout": int(ctx.node.get("timeout_seconds") or 30)}
        elif language in {"shell", "powershell", "pwsh", "bash"}:
            name = "astrbot_execute_shell"
            arguments = {"command": code, "timeout": int(ctx.node.get("timeout_seconds") or 30)}
        else:
            return NodeExecutionResult(ok=False, blocked=True, advance=False, outcome="不支持的代码语言。")
        result = await self.tool_executor.call(event=ctx.event, task=ctx.task, spec=ctx.spec,
              node=ctx.node, tool_name=name, call_args=arguments)
        return NodeExecutionResult(ok=result.ok, blocked=result.blocked, outcome=result.outcome,
            data=result.data, advance=result.ok and not result.blocked, needs_react=result.needs_react,
            next_node_id=self._single_next(ctx.outgoing), note="native_code_executor")

    async def _execute_memory_filter_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        allow = self._node_string_list(ctx.task, ctx.node, "admission_allow", "allow_tags", "whitelist")
        deny = self._node_string_list(ctx.task, ctx.node, "admission_deny", "deny_tags", "blacklist")
        block_daily = bool(ctx.node.get("block_daily_memory"))
        reflow_scope = str(ctx.node.get("reflow_scope") or "tags_only").strip().lower()
        if reflow_scope not in {"none", "tags_only", "full"}:
            reflow_scope = "tags_only"
        memory_filter = {
            "admission_allow": allow,
            "admission_deny": deny,
            "block_daily_memory": block_daily,
            "reflow_scope": reflow_scope,
            "node_id": str(ctx.node.get("id") or ""),
            "updated_at": now_iso(),
        }
        data["memory_filter"] = memory_filter
        ctx.task.add_log(
            "workflow_memory_filter",
            f"admission allow={allow} deny={deny} block_daily={block_daily} reflow={reflow_scope}",
        )
        return NodeExecutionResult(
            outcome=f"Memory admission set: allow={len(allow)} deny={len(deny)} block_daily={block_daily} reflow={reflow_scope}.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "memory_filter": memory_filter},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_memory_filter",
        )

    async def _execute_retrieve_memory_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        query = str(
            ctx.node.get("query")
            or ctx.node.get("memory_query")
            or ctx.node.get("condition")
            or " ".join(self._node_string_list(ctx.task, ctx.node, "tags", "memory_tags"))
            or ctx.task.root_goal
            or ""
        ).strip()
        try:
            limit = max(1, min(int(ctx.node.get("limit") or 5), 12))
        except Exception:
            limit = 5
        tag_filter = set(self._node_string_list(ctx.task, ctx.node, "tags", "memory_tags"))
        folder_filter = str(ctx.node.get("folder_id") or ctx.node.get("memory_folder") or "").strip()
        agent_filter = str(ctx.node.get("agent_id") or ctx.spec.agent_id or "").strip()
        allow_cross_agent = bool(ctx.node.get("allow_cross_agent"))
        mem_filter = self._ensure_workflow_data(ctx.task).get("memory_filter")
        mem_filter = mem_filter if isinstance(mem_filter, dict) else {}
        admit_allow = set(str(t).strip() for t in (mem_filter.get("admission_allow") or []) if str(t).strip())
        admit_deny = set(str(t).strip() for t in (mem_filter.get("admission_deny") or []) if str(t).strip())
        block_daily = bool(mem_filter.get("block_daily_memory"))
        scored_rows: list[tuple[int, dict[str, Any]]] = []
        for item in reversed(self.storage.list_memory_entries()):
            if folder_filter and str(item.get("folder_id") or "") != folder_filter:
                continue
            item_agent = str(item.get("agent_id") or "").strip()
            if item_agent and agent_filter and item_agent != agent_filter and not allow_cross_agent:
                continue
            item_tags = set(str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip())
            if tag_filter and not tag_filter.intersection(item_tags):
                continue
            if admit_deny and admit_deny.intersection(item_tags):
                continue
            if admit_allow and not admit_allow.intersection(item_tags):
                continue
            if block_daily and not str(item.get("source_task_id") or "").strip():
                continue
            text = str(item.get("text") or "")
            haystack = "\n".join(
                [
                    text,
                    str(item.get("source_task_id") or ""),
                    str(item.get("folder_name") or ""),
                    " ".join(str(tag) for tag in item.get("tags") or []),
                ]
            )
            score = self._memory_similarity_score(query, haystack)
            if query and score <= 0:
                continue
            visible, _ = self._memory_entry_visible(
                item,
                umo=ctx.task.umo,
                active_task=ctx.task,
                allow_private=True,
            )
            if not visible:
                continue
            scored_rows.append((score, self._memory_entry_row(item, text_limit=900)))
        scored_rows.sort(key=lambda row: row[0], reverse=True)
        rows = [row for _, row in scored_rows[:limit]]

        pattern_rows = []
        try:
            if query and hasattr(self, "pattern_library"):
                raw = self.pattern_library.recommend(
                    query, limit=3, exclude_task_id=ctx.task.task_id
                )
                pattern_rows = [
                    self.pattern_library.compact_for_runtime(p) for p in raw
                ]
        except Exception:
            pattern_rows = []

        outcome = f"Retrieved {len(rows)} task memory item(s)"
        if pattern_rows:
            outcome += f" and {len(pattern_rows)} pattern(s)"
        outcome += "."

        data = {"query": query.lower(), "rows": rows}
        if folder_filter:
            data["folder_id"] = folder_filter
        if agent_filter:
            data["agent_id"] = agent_filter
        if pattern_rows:
            data["pattern_recommendations"] = pattern_rows

        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_memory_retrieve",
        )

    async def _execute_save_memory_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        outcome = "Private task memory checkpoint saved."
        self._save_workflow_private_memory(ctx.task, ctx.node, outcome)
        return NodeExecutionResult(
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={"kind": "workflow_private_memory", "expose_to_normal": False},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_memory_save",
        )

    async def _execute_memory_action_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "").strip()
        data = self._ensure_workflow_data(ctx.task)
        if action == "summarize_memory":
            summary = self._compact_text(
                str(ctx.node.get("summary") or ctx.node.get("template") or "")
                or "\n".join(
                    part
                    for part in (
                        f"Goal: {ctx.task.root_goal}",
                        f"Current: {ctx.task.current_summary}",
                        f"Progress: {ctx.task.last_confirmed_progress}",
                        f"Observation: {ctx.task.last_observation}",
                    )
                    if part.strip()
                ),
                4000,
            )
            self.storage.write_task_memory_summary(ctx.task, summary)
            data["memory_summary"] = {"time": now_iso(), "text": summary}
            return NodeExecutionResult(
                outcome="Task memory summary written.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "summary": summary},
                note="node_executor_summarize_memory",
            )
        if action == "export_task_memory":
            export = self._task_memory_export(ctx.task)
            exports = data.setdefault("memory_exports", [])
            if not isinstance(exports, list):
                exports = []
            exports.append(export)
            data["memory_exports"] = exports[-20:]
            self.storage.upsert_task_memory_artifact(ctx.task, f"memory_export_{len(exports)}", export)
            return NodeExecutionResult(
                outcome="Task memory exported as workflow artifact.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "export": export},
                note="node_executor_export_task_memory",
            )
        if action == "promote_memory_candidate":
            memory_id = str(ctx.node.get("memory_id") or ctx.node.get("candidate_id") or "").strip()
            if memory_id:
                item = self.memory_manager.accept(
                    memory_id,
                    reviewer="workflow",
                    reason=str(ctx.node.get("reason") or "workflow promoted memory candidate"),
                )
            else:
                candidate_text = str(
                    ctx.node.get("text")
                    or ctx.task.last_observation
                    or ctx.task.current_summary
                    or ctx.task.root_goal
                    or ""
                ).strip()
                item = self.storage.save_memory_entry(
                    {
                        "text": candidate_text,
                        "source_task_id": ctx.task.task_id,
                        "source_umo": ctx.task.umo,
                        "agent_id": ctx.spec.agent_id,
                        "folder_id": str(ctx.node.get("folder_id") or ctx.node.get("memory_folder") or ""),
                        "status": "accepted",
                        "kind": "workflow_promoted_memory",
                        "layer": "accepted_memory",
                        "tags": ["task", "workflow", "accepted", ctx.spec.agent_id],
                        "expose_to_normal": True,
                    }
                )
            route = "success" if item else "failed"
            return NodeExecutionResult(
                ok=route == "success",
                status="completed" if route == "success" else "blocked",
                outcome="Memory candidate promoted." if item else "Memory candidate not found.",
                next_node_id=self._single_next(ctx.outgoing) if item else "",
                data={"route": route, "memory": item or {}},
                blocked=not bool(item),
                note="node_executor_promote_memory_candidate",
            )
        if action == "archive_memory_folder":
            folder_payload = {
                "folder_id": str(ctx.node.get("folder_id") or ctx.node.get("memory_folder") or "").strip(),
                "name": str(ctx.node.get("folder_name") or ctx.node.get("name") or ctx.spec.name or "方案记忆夹").strip(),
                "agent_id": str(ctx.node.get("agent_id") or ctx.spec.agent_id or "").strip(),
                "description": str(ctx.node.get("description") or ctx.node.get("instruction") or "").strip(),
                "expose_to_normal": bool(ctx.node.get("expose_to_normal", False)),
                "detail_level": str(ctx.node.get("detail_level") or "summary").strip(),
                "retention_days": int(ctx.node.get("retention_days") or 0),
            }
            folder = self.storage.save_memory_folder(folder_payload)
            export = self._task_memory_export(ctx.task)
            text = self._compact_text(
                str(ctx.node.get("text") or "")
                or json.dumps(export, ensure_ascii=False, default=str, indent=2),
                8000,
            )
            entry = self.storage.save_memory_entry(
                {
                    "text": text,
                    "source_task_id": ctx.task.task_id,
                    "source_umo": ctx.task.umo,
                    "agent_id": ctx.spec.agent_id,
                    "folder_id": folder.get("folder_id") or "default",
                    "folder_name": folder.get("name") or "",
                    "status": str(ctx.node.get("status") or "candidate"),
                    "kind": "workflow_folder_archive",
                    "layer": "candidate_memory",
                    "tags": ["task", "workflow", "folder_archive", ctx.spec.agent_id, *(self._node_string_list(ctx.task, ctx.node, "tags", "memory_tags") or [])],
                    "expose_to_normal": bool(folder.get("expose_to_normal")),
                    "evidence": {"action": "archive_memory_folder", "folder_id": folder.get("folder_id"), "agent_id": ctx.spec.agent_id},
                }
            )
            return NodeExecutionResult(
                outcome=f"Task memory archived into folder {folder.get('name') or folder.get('folder_id')}.",
                next_node_id=self._single_next(ctx.outgoing),
                data={"route": "success", "folder": folder, "memory": entry},
                note="node_executor_archive_memory_folder",
            )
        if action == "forget_task_memory":
            memory_id = str(ctx.node.get("memory_id") or "").strip()
            if memory_id:
                ok = self.storage.delete_memory_entry(memory_id)
            else:
                ok = False
                for item in list(self.storage.list_memory_entries()):
                    if str(item.get("source_task_id") or "") == ctx.task.task_id:
                        ok = self.storage.delete_memory_entry(str(item.get("memory_id") or "")) or ok
            return NodeExecutionResult(
                ok=ok,
                status="completed" if ok else "blocked",
                outcome="Task memory forgotten." if ok else "No matching task memory to forget.",
                next_node_id=self._single_next(ctx.outgoing) if ok else "",
                data={"route": "success" if ok else "failed", "memory_id": memory_id},
                blocked=not ok,
                note="node_executor_forget_task_memory",
            )
        return NodeExecutionResult(
            ok=False,
            status="blocked",
            outcome=f"Unsupported memory action: {action}",
            blocked=True,
            advance=False,
            note="node_executor_memory_action_unknown",
        )

    async def _execute_global_control_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        control = data.get("global_control") if isinstance(data.get("global_control"), dict) else {}

        def node_int(key: str, current: int = 0, *, minimum: int = 0, maximum: int = 10_000_000) -> int:
            raw = ctx.node.get(key)
            if raw in (None, ""):
                return current
            try:
                return max(minimum, min(int(raw), maximum))
            except Exception:
                return current

        budget_fields = {
            "max_nodes_per_tick": (1, 200),
            "max_seconds_per_tick": (1, 3600),
            "max_tokens_per_tick": (0, 1_000_000),
        }
        updated_budget: dict[str, int] = {}
        for field, (minimum, maximum) in budget_fields.items():
            current = int(getattr(ctx.task.budget, field, 0) or 0)
            value = node_int(field, current, minimum=minimum, maximum=maximum)
            if value and (not current or value < current):
                setattr(ctx.task.budget, field, value)
                updated_budget[field] = value

        repeated = node_int(
            "max_repeated_failures",
            int(ctx.task.heartbeat.max_repeated_failures or 3),
            minimum=1,
            maximum=100,
        )
        ctx.task.heartbeat.max_repeated_failures = min(ctx.task.heartbeat.max_repeated_failures, repeated)

        for key in (
            "progress_notice_mode",
            "pause_commands",
            "conversation_mode",
            "report_frequency",
        ):
            if key in ctx.node:
                control[key] = self._resolve_workflow_template(ctx.task, ctx.node.get(key))
        for key in ("show_tool_use", "silent_tools", "allow_midtask_chat", "pause_on_error"):
            if key in ctx.node:
                control[key] = bool(ctx.node.get(key))
        control["max_repeated_failures"] = repeated
        control["budget"] = ctx.task.budget.to_dict() if hasattr(ctx.task.budget, "to_dict") else dict(ctx.task.budget.__dict__)
        control["updated_at"] = now_iso()
        control["node_id"] = str(ctx.node.get("id") or "")
        data["global_control"] = control
        ctx.task.add_log("workflow_control", f"Global control updated at {ctx.node.get('id') or '-'}")

        return NodeExecutionResult(
            outcome="Global workflow control applied.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "control": control, "updated_budget": updated_budget},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_global_control",
        )

    async def _execute_skill_evolution_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        tag_filter = set(self._node_string_list(ctx.task, ctx.node, "tags", "memory_tags"))
        folder_filter = str(ctx.node.get("folder_id") or ctx.node.get("memory_folder") or "").strip()
        allow_candidates = bool(ctx.node.get("include_candidates", False))
        agent_id = str(ctx.node.get("agent_id") or ctx.spec.agent_id or "").strip()
        rows: list[dict[str, Any]] = []
        for item in reversed(self.storage.list_memory_entries()):
            if agent_id and str(item.get("agent_id") or "").strip() not in {"", agent_id}:
                continue
            if folder_filter and str(item.get("folder_id") or "") != folder_filter:
                continue
            status = str(item.get("status") or "candidate").strip().lower()
            if status != "accepted" and not (allow_candidates and status == "candidate"):
                continue
            if tag_filter:
                tags = set(str(tag).strip() for tag in item.get("tags") or [] if str(tag).strip())
                if not tags.intersection(tag_filter):
                    continue
            if not str(item.get("text") or "").strip():
                continue
            rows.append(item)
            if len(rows) >= 12:
                break

        if not rows:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="No accepted memory is available for skill evolution.",
                blocked=True,
                advance=False,
                data={"route": "failed", "agent_id": agent_id, "folder_id": folder_filter},
                note="node_executor_skill_evolution_no_memory",
            )

        rule_name = str(ctx.node.get("skill_name") or ctx.node.get("rule_name") or SKILL_NAME).strip() or SKILL_NAME
        existing = self.storage.get_skill_rule(rule_name) or {}
        memory_lines = []
        for item in rows:
            tags = ", ".join(str(tag) for tag in item.get("tags") or [])
            memory_lines.append(
                f"- {item.get('memory_id')}: tags=[{tags or '-'}] "
                f"folder={item.get('folder_name') or item.get('folder_id') or '-'}; "
                f"{self._compact_text(str(item.get('text') or ''), 700)}"
            )
        custom_instruction = self._workflow_node_text(ctx, "instruction", "prompt", "evolution_prompt")
        draft = "\n".join(
            part
            for part in (
                str(existing.get("content") or "").strip(),
                "\n[Agent Lab skill evolution draft]",
                f"Updated at: {now_iso()}",
                f"Task: {ctx.task.task_id}",
                f"Agent: {agent_id or '-'}",
                f"Instruction: {custom_instruction or 'Preserve stable operating lessons from accepted task memory.'}",
                "Accepted memory evidence:",
                "\n".join(memory_lines),
                "Suggested rule:",
                self._compact_text(str(ctx.node.get("draft") or ""), 4000)
                or "- Prefer these accepted lessons when future tasks match the same tags, folder, or agent scope.",
            )
            if str(part or "").strip()
        )
        draft = self._compact_text(draft, max(2000, min(int(ctx.node.get("max_tokens") or 8000), 24000)))
        draft_row = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "skill_name": rule_name,
            "agent_id": agent_id,
            "folder_id": folder_filter,
            "memory_ids": [str(item.get("memory_id") or "") for item in rows],
            "draft": draft,
        }
        drafts = data.setdefault("skill_evolution_drafts", [])
        if not isinstance(drafts, list):
            drafts = []
        drafts.append(draft_row)
        data["skill_evolution_drafts"] = drafts[-40:]

        approval_mode = str(ctx.node.get("approval_mode") or ctx.node.get("risk") or "review").strip().lower()
        auto_apply = bool(ctx.node.get("auto_apply") or approval_mode in {"low", "auto", "apply"})
        require_approval = bool(ctx.node.get("require_approval")) or approval_mode in {"high", "review", "manual", "approval"}
        if require_approval and not auto_apply:
            approval = ApprovalRequest(
                operation=f"Apply skill evolution: {rule_name}",
                reason=custom_instruction or "Workflow generated a skill evolution draft from accepted memory.",
                impact="Agent Lab will update skill_rules and sync the Agent Mode skill prompt after approval.",
                rollback="Edit or delete the skill rule in Agent Lab WebUI registry if the draft is not desired.",
            )
            ctx.task.approvals.append(approval.to_dict())
            ctx.task.status = "paused"
            ctx.task.set_wait(
                wait_reason="need_approval",
                message=f"Skill evolution draft is ready for review: {approval.approval_id}",
                source="workflow_skill_evolution",
                resume_command=f"/agentlab approve {approval.approval_id}",
                required_input=[rule_name],
            )
            return NodeExecutionResult(
                ok=False,
                status="running",
                outcome=f"Skill evolution draft prepared and waiting for approval: {approval.approval_id}",
                advance=False,
                data={"route": "approved", "draft": draft_row, "approval": approval.to_dict()},
                note="node_executor_skill_evolution_review",
            )

        saved = self.storage.save_skill_rule({"skill_name": rule_name, "content": draft})
        self._sync_agent_mode_skill()
        ctx.task.add_log("skill_evolution", f"Saved skill rule {rule_name} from {len(rows)} memory item(s)")
        return NodeExecutionResult(
            outcome=f"Skill rule {rule_name} updated from accepted memory.",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "skill_rule": saved, "draft": draft_row},
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note="node_executor_skill_evolution",
        )

    def _task_memory_export(self, task: TaskState) -> dict[str, Any]:
        def snapshot(value: Any) -> Any:
            try:
                return json.loads(json.dumps(value, ensure_ascii=False, default=str))
            except Exception:
                return self._compact_text(str(value), 4000)

        workflow_data = task.workflow_data if isinstance(task.workflow_data, dict) else {}
        return {
            "time": now_iso(),
            "task_id": task.task_id,
            "agent_id": task.agent_id,
            "umo": task.umo,
            "root_goal": task.root_goal,
            "current_summary": task.current_summary,
            "last_confirmed_progress": task.last_confirmed_progress,
            "last_observation": task.last_observation,
            "workflow_path": list(task.workflow_path or []),
            "workflow_events": snapshot(list(task.workflow_events or [])[-80:]),
            "node_outputs": snapshot(workflow_data.get("node_outputs") or {}),
            "variables": snapshot(workflow_data.get("variables") or {}),
            "reports": snapshot(workflow_data.get("reports") or []),
            "records": snapshot(workflow_data.get("records") or []),
            "outbox": snapshot(workflow_data.get("outbox") or []),
        }

    async def _execute_parallel_branch_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        branches = self._node_string_list(ctx.task, ctx.node, "branches", "branch_list")
        shared_instruction = f"tick_reason={ctx.reason}"
        if branches:
            shared_instruction += "\n并行分支清单（名称 | 角色/提示）：\n" + "\n".join(f"- {b}" for b in branches)
        parallel = await self._run_parallel_workflow(
            event=ctx.event,
            task=ctx.task,
            spec=ctx.spec,
            branch_node_id=str(ctx.node.get("id") or ""),
            parallel_group=str(ctx.node.get("parallel_group") or ""),
            shared_instruction=shared_instruction,
            max_concurrency=max(
                1,
                min(int(_cfg(self.config, "workflow_parallel_concurrency", 3) or 3), 6),
            ),
        )
        ok = bool(parallel.get("ok"))
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=str(parallel.get("summary") or parallel.get("error") or "Parallel workflow finished."),
            next_node_id=str(parallel.get("merge_node_id") or ""),
            data=parallel,
            blocked=not ok and not parallel.get("merge_node_id"),
            needs_react=not parallel.get("merge_node_id"),
            advance=False,
            note="node_executor_parallel",
        )

    async def _execute_api_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        if not self._tool_allowed_by_agent_profile(ctx.spec, CUSTOM_API_TOOL_NAME):
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="Custom API execution is outside the Agent tool profile.",
                blocked=True,
                advance=False,
                note="node_executor_api_not_allowed",
            )
        budget_reason = self._consume_tool_budget(ctx.task, CUSTOM_API_TOOL_NAME)
        if budget_reason:
            self._pause_task_for_budget(ctx.task, budget_reason)
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=budget_reason,
                blocked=True,
                advance=False,
                note="node_executor_api_budget",
            )
        node_for_call = dict(ctx.node)
        scope = self._api_scope_for_node(ctx.task, ctx.node)
        if scope and not str(node_for_call.get("api_id") or node_for_call.get("ref_id") or "").strip():
            node_for_call["api_id"] = str(scope.get("api_id") or "").strip()
            node_for_call["api_scope_id"] = str(scope.get("node_id") or "").strip()
        base = {
            "node_id": str(node_for_call.get("id") or ""),
            "title": node_for_call.get("title") or node_for_call.get("id") or "",
            "kind": node_for_call.get("kind") or "api",
            "action": node_for_call.get("action") or "call_api",
            "ok": False,
            "status": "blocked",
            "summary": "",
            "details": "",
        }
        payload = self._node_payload_from_variable(ctx.task, node_for_call)
        if payload is None:
            payload = self._node_templated_json_object(ctx.task, node_for_call, "api_payload", "payload", "params")
        else:
            payload = self._resolve_workflow_template(ctx.task, payload)
        worker = await self._run_parallel_api_worker(node_for_call, base, api_payload=payload)
        ok = bool(worker.get("ok"))
        return NodeExecutionResult(
            ok=ok,
            status="completed" if ok else "blocked",
            outcome=str(worker.get("summary") or worker.get("error") or ""),
            next_node_id=self._single_next(ctx.outgoing) if ok else "",
            data=worker,
            blocked=not ok,
            note="node_executor_api",
        )

    def _api_scope_for_node(self, task: TaskState, node: dict[str, Any]) -> dict[str, Any]:
        node_id = str((node or {}).get("id") or "").strip()
        data = self._ensure_workflow_data(task)
        scopes = data.get("api_scopes") if isinstance(data.get("api_scopes"), dict) else {}
        selected = None
        for scope in scopes.values():
            if not isinstance(scope, dict):
                continue
            scope_mode = str(scope.get("scope_mode") or "selected").strip().lower()
            node_ids = {
                str(item).strip()
                for item in (scope.get("scope_node_ids") or [])
                if str(item).strip()
            }
            if node_ids and node_id in node_ids:
                return scope
            if scope_mode in {"all", "global", "downstream"} and selected is None:
                selected = scope
        return selected or {}

    async def _execute_tool_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        tool_name = str(
            ctx.node.get("tool_name")
            or (ctx.node.get("ref_id") if ctx.node.get("ref_type") == "tool" else "")
            or ""
        ).strip()
        call_args = self._node_templated_json_object(ctx.task, ctx.node, "tool_args", "arguments", "params")
        variable_payload = self._node_payload_from_variable(ctx.task, ctx.node)
        if isinstance(variable_payload, dict):
            resolved_payload = self._resolve_workflow_template(ctx.task, variable_payload)
            call_args = {**call_args, **(resolved_payload if isinstance(resolved_payload, dict) else {})}
        if not tool_name:
            return NodeExecutionResult(
                outcome="Tool node needs ReAct because no concrete tool_name is bound.",
                needs_react=True,
                advance=False,
                note="node_executor_tool_react_fallback",
            )
        executed = await self.tool_executor.call(
            event=ctx.event,
            task=ctx.task,
            spec=ctx.spec,
            node=ctx.node,
            tool_name=tool_name,
            call_args=call_args,
        )
        if executed.needs_react:
            return NodeExecutionResult(
                outcome=executed.outcome,
                needs_react=True,
                advance=False,
                data=executed.data,
                note=executed.note,
            )
        if executed.blocked or not executed.ok:
            return NodeExecutionResult(
                ok=False,
                status=executed.status,
                outcome=executed.outcome,
                blocked=True,
                advance=False,
                data=executed.data,
                note=executed.note,
            )
        return NodeExecutionResult(
            outcome=executed.outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data=executed.data,
            needs_react=len(ctx.outgoing) > 1,
            advance=len(ctx.outgoing) <= 1,
            note=executed.note,
        )

    async def _execute_route_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        target = self._route_target_from_node(ctx.task, ctx.node, ctx.outgoing, ctx.next_candidates)
        if not target:
            return NodeExecutionResult(
                outcome="Decision node has no deterministic route; ReAct must choose a branch.",
                needs_react=True,
                advance=False,
                note="node_executor_route_react",
            )
        return NodeExecutionResult(
            outcome=f"Decision routed to {target}.",
            next_node_id=target,
            data={"selected": target, "candidates": ctx.outgoing},
            note="node_executor_route",
        )

    async def _execute_retry_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        node_id = str(ctx.node.get("id") or "")
        count = int((data.get("execution_counts") or {}).get(node_id, 0) or 0)
        max_retries = max(1, min(int(ctx.node.get("max_retries") or ctx.task.heartbeat.max_repeated_failures or 3), 8))
        if count >= max_retries:
            ctx.task.status = "blocked"
            return NodeExecutionResult(
                ok=True,
                status="completed",
                outcome=f"Retry limit reached ({count}/{max_retries}).",
                data={"route": "failed", "count": count, "max_retries": max_retries},
                note="node_executor_retry_limit",
            )
        retry_target = self._candidate_by_action(ctx.next_candidates, {"run_tools", "call_api", "http_request", "file_operation", "code_exec"}) or self._candidate_by_stage(
            ctx.next_candidates, {"execute", "plan"}
        )
        return NodeExecutionResult(
            outcome=f"Retry allowed ({count + 1}/{max_retries}).",
            next_node_id=retry_target,
            data={"route": "retry", "count": count + 1, "max_retries": max_retries},
            needs_react=False,
            advance=True,
            note="node_executor_retry",
        )

    async def _execute_validation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        verdict = self.verifier.verify_validation_checkpoint(ctx.task)
        passed = verdict.passed
        if not passed and len(ctx.outgoing) > 1:
            retry_target = self._candidate_by_action(ctx.next_candidates, {"retry"}) or self._candidate_by_stage(
                ctx.next_candidates, {"checkpoint", "execute"}
            )
            if verdict.status == "failed" and retry_target:
                return NodeExecutionResult(
                    ok=False,
                    status="blocked",
                    outcome=f"Validation did not pass; routed to {retry_target}.",
                    next_node_id=retry_target,
                    data=verdict.to_dict(),
                    note="node_executor_validation_retry",
                )
            return NodeExecutionResult(
                outcome=verdict.reason,
                needs_react=True,
                advance=False,
                data=verdict.to_dict(),
                note="node_executor_validation_react",
            )
        return NodeExecutionResult(
            outcome="Validation passed." if passed else "Validation checkpoint recorded.",
            next_node_id=self._single_next(ctx.outgoing),
            data=verdict.to_dict(),
            needs_react=len(ctx.outgoing) > 1 and not passed,
            advance=len(ctx.outgoing) <= 1 or passed,
            note="node_executor_validation",
        )

    async def _execute_debate_validation_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        perspectives = self._node_string_list(ctx.task, ctx.node, "perspectives", "checks")
        if not perspectives:
            perspectives = ["correctness", "safety", "completion"]
        require_consensus_raw = ctx.node.get("require_consensus", True)
        if isinstance(require_consensus_raw, str):
            require_consensus = require_consensus_raw.strip().lower() not in {"false", "0", "no", "off"}
        else:
            require_consensus = bool(require_consensus_raw)

        base_verdict = self.verifier.verify_validation_checkpoint(ctx.task)
        evidence_text = "\n".join(
            [
                str(ctx.task.current_summary or ""),
                str(ctx.task.last_confirmed_progress or ""),
                str(ctx.task.last_observation or ""),
                json.dumps((ctx.task.workflow_data or {}).get("node_outputs") or {}, ensure_ascii=False, default=str),
            ]
        ).lower()
        failure_markers = ("fail", "failed", "error", "blocked", "unsafe", "risk", "失败", "错误", "阻塞")
        reviews: list[dict[str, Any]] = []
        for perspective in perspectives[:8]:
            name = str(perspective or "review").strip()
            lowered = name.lower()
            passed = bool(base_verdict.passed)
            reason = base_verdict.reason
            missing = list(base_verdict.missing or [])
            if lowered in {"safety", "security", "risk", "安全性", "风险"} and any(marker in evidence_text for marker in failure_markers):
                passed = False
                if "risk_evidence" not in missing:
                    missing.append("risk_evidence")
                reason = "Safety/risk perspective found blocking evidence."
            reviews.append(
                {
                    "perspective": name,
                    "passed": passed,
                    "status": "passed" if passed else "needs_review",
                    "reason": reason,
                    "missing": missing,
                }
            )

        passed_count = sum(1 for item in reviews if item.get("passed"))
        passed = passed_count == len(reviews) if require_consensus else passed_count > 0
        data = {
            "passed": passed,
            "require_consensus": require_consensus,
            "passed_count": passed_count,
            "total": len(reviews),
            "reviews": reviews,
            "base_verdict": base_verdict.to_dict(),
        }
        return NodeExecutionResult(
            ok=passed,
            status="completed" if passed else "blocked",
            outcome=(
                f"Debate validation passed {passed_count}/{len(reviews)} perspective(s)."
                if passed
                else f"Debate validation needs review: {passed_count}/{len(reviews)} perspective(s) passed."
            ),
            next_node_id=self._single_next(ctx.outgoing) if passed else "",
            data=data,
            blocked=not passed,
            note="node_executor_debate_validation",
        )

    async def _execute_dispatch_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """主agent 派活：把节点上的分派清单写进共享黑板 assignments。"""
        raw = self._node_json_value(ctx.task, ctx.node, "assignments", "dispatch", "tasks")
        items: list[dict[str, Any]] = []
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    items.append(entry)
                elif str(entry or "").strip():
                    # 支持编辑页 lines 格式："目标子Agent | 指令 | 资源标签(逗号)"
                    parts = [p.strip() for p in str(entry).split("|")]
                    if len(parts) >= 2:
                        items.append({
                            "sub_agent_id": parts[0],
                            "instruction": parts[1],
                            "resource_tags": parts[2] if len(parts) >= 3 else "",
                        })
                    else:
                        items.append({"instruction": parts[0]})
        assigned: list[dict[str, Any]] = []
        for entry in items[:40]:
            target = str(
                entry.get("sub_agent_id")
                or entry.get("sub_agent")
                or entry.get("target")
                or entry.get("owner")
                or ""
            ).strip()
            instruction = str(
                self._resolve_workflow_template(
                    ctx.task, entry.get("instruction") or entry.get("task") or ""
                )
            ).strip()
            tags = entry.get("resource_tags") or entry.get("tags") or []
            if isinstance(tags, str):
                tags = [t.strip() for t in re.split(r"[\n,，、;；]+", tags) if t.strip()]
            if not isinstance(tags, list):
                tags = []
            assign_id = ctx.task.post_assignment(target, instruction, resource_tags=tags)
            assigned.append(
                {"assign_id": assign_id, "sub_agent_id": target, "instruction": instruction}
            )
        ctx.task.add_log(
            "agent_dispatch", self._compact_text(json.dumps(assigned, ensure_ascii=False), 800)
        )
        return NodeExecutionResult(
            outcome=f"主agent 派发 {len(assigned)} 条任务到共享黑板。",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "assignments": assigned},
            needs_react=False,
            advance=True,
            note="node_executor_dispatch_tasks",
        )

    async def _execute_collect_report_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """收齐最近一轮并行 worker 的产出，按 owner 汇成黑板 reports。"""
        runs = list(getattr(ctx.task, "parallel_runs", []) or [])
        latest = runs[-1] if runs else {}
        workers = latest.get("workers") if isinstance(latest, dict) else []
        node_map = {str(n.get("id") or ""): n for n in (ctx.spec.workflow_nodes or [])}
        collected: list[dict[str, Any]] = []
        for w in (workers or []):
            if not isinstance(w, dict):
                continue
            wnode = node_map.get(str(w.get("node_id") or ""), {})
            owner = self._subagent_of_node(ctx.spec, wnode)
            sub_id = owner.sub_agent_id if owner else str(w.get("node_id") or "")
            ctx.task.post_report(
                sub_id,
                str(w.get("summary") or w.get("error") or "")[:600],
                evidence=self._compact_text(str(w.get("details") or ""), 800),
                risks="" if w.get("ok") else str(w.get("error") or "worker blocked"),
            )
            collected.append(
                {
                    "sub_agent_id": sub_id,
                    "ok": bool(w.get("ok")),
                    "summary": str(w.get("summary") or "")[:200],
                }
            )
        ok_count = sum(1 for c in collected if c["ok"])
        summary = f"收齐 {len(collected)} 份子Agent 汇报（{ok_count} 成功）。"
        if collected:
            ctx.task.current_summary = summary
        ctx.task.add_log("agent_collect_report", summary)
        return NodeExecutionResult(
            outcome=summary,
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "reports": collected},
            needs_react=False,
            advance=True,
            note="node_executor_collect_report",
        )

    async def _execute_agent_message_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """意见传达：向某子Agent 的信箱投一条意见/指令。"""
        target = str(
            self._resolve_workflow_template(
                ctx.task,
                ctx.node.get("target_sub_agent")
                or ctx.node.get("target")
                or ctx.node.get("sub_agent_id")
                or "",
            )
        ).strip()
        text = str(
            self._resolve_workflow_template(
                ctx.task,
                ctx.node.get("message")
                or ctx.node.get("content")
                or ctx.node.get("instruction")
                or "",
            )
        ).strip()
        if not target:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="意见传达节点缺少目标子Agent。",
                next_node_id="",
                data={"route": "failed"},
                needs_react=False,
                blocked=True,
                advance=False,
                note="node_executor_agent_message_no_target",
            )
        ctx.task.post_message(target, text, sender="orchestrator")
        return NodeExecutionResult(
            outcome=f"已向子Agent {target} 投递一条意见。",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "target": target},
            needs_react=False,
            advance=True,
            note="node_executor_agent_message",
        )

    async def _execute_summarize_decision_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """汇总决策：读共享黑板做下一步决策，写 decisions + next_step。"""
        bb = ctx.task._blackboard()
        assignments = bb.get("assignments") or []
        reports = bb.get("reports") or []
        pending = [
            a for a in assignments if str(a.get("status") or "") not in {"done", "completed"}
        ]
        report_lines = [
            f"- {r.get('sub_agent_id') or '?'}: {str(r.get('summary') or '')[:120]}"
            for r in reports[-8:]
        ]
        basis = (
            f"assignments={len(assignments)}(pending {len(pending)}), reports={len(reports)}\n"
            + "\n".join(report_lines)
        )
        explicit = str(
            self._resolve_workflow_template(
                ctx.task, ctx.node.get("decision") or ctx.node.get("instruction") or ""
            )
        ).strip()
        summary = explicit or f"已综合 {len(reports)} 份汇报，{len(pending)} 条任务待办。"
        next_hint = str(
            self._resolve_workflow_template(ctx.task, ctx.node.get("next_step") or "")
        ).strip()
        ctx.task.post_decision(summary, basis=basis, next_step=next_hint)
        if next_hint:
            ctx.task.next_step = next_hint
        ctx.task.current_summary = summary
        ctx.task.add_log("agent_decision", self._compact_text(summary + "\n" + basis, 800))
        return NodeExecutionResult(
            outcome=summary,
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "pending": len(pending), "reports": len(reports)},
            needs_react=False,
            advance=True,
            note="node_executor_summarize_decision",
        )

    async def _execute_agent_role_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """Agent 角色块：运行时确认画布角色已同步到 AgentSpec.sub_agents。"""
        sub_agent_id = str(
            ctx.node.get("sub_agent_id")
            or ctx.node.get("ref_id")
            or ctx.node.get("id")
            or ""
        ).strip()
        sub_agent = next(
            (
                item
                for item in (getattr(ctx.spec, "sub_agents", None) or [])
                if getattr(item, "sub_agent_id", "") == sub_agent_id
            ),
            None,
        )
        if not sub_agent:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="Agent 角色块未同步到有效子 Agent。",
                blocked=True,
                advance=False,
                data={"sub_agent_id": sub_agent_id},
                note="node_executor_agent_role_missing",
            )
        data = {
            "sub_agent_id": sub_agent.sub_agent_id,
            "name": sub_agent.name,
            "provider_id": sub_agent.provider_id,
            "enabled_tools": list(sub_agent.enabled_tools or []),
            "member_node_ids": list(sub_agent.member_node_ids or []),
            "max_concurrency": sub_agent.max_concurrency,
            "rate_per_minute": sub_agent.rate_per_minute,
        }
        return NodeExecutionResult(
            outcome=f"Agent 角色块已生效：{sub_agent.name or sub_agent.sub_agent_id}。",
            next_node_id=self._single_next(ctx.outgoing),
            data=data,
            needs_react=False,
            advance=True,
            note="node_executor_agent_role",
        )

    async def _execute_api_scope_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """API 范围块：写入任务上下文，供下游 call_api 读取默认 API。"""
        api_id = str(ctx.node.get("api_id") or ctx.node.get("ref_id") or "").strip()
        if not api_id:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="API 范围块必须绑定 api_id。",
                blocked=True,
                advance=False,
                note="node_executor_api_scope_missing_api",
            )
        api_spec = self.storage.get_custom_api(api_id)
        if not api_spec:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=f"未找到 API 范围块绑定的自定义 API：{api_id}",
                blocked=True,
                advance=False,
                note="node_executor_api_scope_missing_registry",
            )
        scope_node_ids = self._node_string_list(
            ctx.task,
            ctx.node,
            "scope_node_ids",
            "member_node_ids",
            "target_node_ids",
        )
        scope = {
            "node_id": str(ctx.node.get("id") or ""),
            "api_id": api_id,
            "scope_mode": str(ctx.node.get("scope_mode") or "selected").strip() or "selected",
            "scope_node_ids": scope_node_ids,
            "owner": str(ctx.node.get("owner") or "").strip(),
            "output_variable": str(ctx.node.get("output_variable") or "").strip(),
            "default_call_policy": self._node_json_object(ctx.node, "default_call_policy", "constraints"),
        }
        data = self._ensure_workflow_data(ctx.task)
        scopes = data.setdefault("api_scopes", {})
        if not isinstance(scopes, dict):
            scopes = {}
            data["api_scopes"] = scopes
        scopes[str(ctx.node.get("id") or api_id)] = scope
        if scope["output_variable"]:
            self._set_workflow_variable(ctx.task, scope["output_variable"], scope)
        return NodeExecutionResult(
            outcome=f"API 范围块已绑定：{api_spec.get('name') or api_id}。",
            next_node_id=self._single_next(ctx.outgoing),
            data=scope,
            needs_react=False,
            advance=True,
            note="node_executor_api_scope",
        )

    async def _execute_prompt_inject_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """提示注入：写入运行态，供后续 tick/ReAct 节点读取。"""
        text = str(
            ctx.node.get("inject_text")
            or ctx.node.get("prompt")
            or ctx.node.get("instruction")
            or ctx.node.get("description")
            or ""
        ).strip()
        if not text:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome="提示注入节点缺少注入文本。",
                blocked=True,
                advance=False,
                note="node_executor_prompt_inject_missing_text",
            )
        injection = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "title": str(ctx.node.get("title") or ""),
            "scope": str(ctx.node.get("inject_scope") or ctx.node.get("scope") or "downstream").strip() or "downstream",
            "text": self._compact_text(text, 2000),
        }
        data = self._ensure_workflow_data(ctx.task)
        injections = data.setdefault("prompt_injections", [])
        if not isinstance(injections, list):
            injections = []
        injections.append(injection)
        data["prompt_injections"] = injections[-40:]
        self._set_workflow_variable(ctx.task, "workflow.prompt_injections", data["prompt_injections"])
        return NodeExecutionResult(
            outcome="提示注入已写入后续执行上下文。",
            next_node_id=self._single_next(ctx.outgoing),
            data=injection,
            needs_react=False,
            advance=True,
            note="node_executor_prompt_inject",
        )

    async def _execute_delay_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        """延时：等待 N 秒再放行（上限 300s，避免长占 tick；长暂停请改用心跳）。"""
        raw = ctx.node.get("delay_seconds", ctx.node.get("seconds", 0))
        try:
            seconds = max(0, min(int(float(raw or 0)), 300))
        except Exception:
            seconds = 0
        if seconds > 0:
            await asyncio.sleep(seconds)
        return NodeExecutionResult(
            outcome=f"已延时 {seconds}s。",
            next_node_id=self._single_next(ctx.outgoing),
            data={"route": "success", "delay_seconds": seconds},
            needs_react=False,
            advance=True,
            note="node_executor_delay",
        )

    async def _execute_approval_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        if ctx.task.pending_approvals():
            ctx.task.status = "paused"
            pending = ctx.task.pending_approvals()[0]
            ctx.task.set_wait(
                wait_reason="need_approval",
                message=f"Waiting for existing approval request: {pending.operation}",
                source="workflow_approval_node",
                resume_command=f"/agentlab approve {pending.approval_id}",
                required_input=[pending.operation],
            )
            return NodeExecutionResult(
                ok=False,
                status="running",
                outcome="Waiting for existing approval request.",
                advance=False,
                data={"pending": [item.approval_id for item in ctx.task.pending_approvals()]},
                note="node_executor_approval_wait",
            )
        operation = str(ctx.node.get("operation") or ctx.node.get("title") or "workflow approval").strip()
        reason = str(ctx.node.get("reason") or ctx.node.get("instruction") or "Workflow guard requires approval.").strip()
        impact = str(ctx.node.get("impact") or "Task execution is paused until the user approves.").strip()
        approval = ApprovalRequest(operation=operation, reason=reason, impact=impact)
        ctx.task.approvals.append(approval.to_dict())
        ctx.task.status = "paused"
        ctx.task.set_wait(
            wait_reason="need_approval",
            message=f"Approval requested: {operation}",
            source="workflow_approval_node",
            resume_command=f"/agentlab approve {approval.approval_id}",
            required_input=[operation],
        )
        ctx.task.add_log("approval_requested", f"{approval.approval_id}: {operation}")
        return NodeExecutionResult(
            ok=False,
            status="running",
            outcome=f"Approval requested: {approval.approval_id}",
            advance=False,
            data=approval.to_dict(),
            note="node_executor_approval",
        )

    async def _execute_wait_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        ctx.task.status = "paused"
        action = str(ctx.node.get("action") or "").strip()
        instruction = str(ctx.node.get("instruction") or "Waiting for user input.").strip()
        handoff_mode = str(ctx.node.get("handoff_mode") or "").strip().lower()
        mode_reason = {
            "wait_reply": "waiting_user",
            "dm_admin": "need_admin_operator",
            "group_prompt": "waiting_user",
            "external_callback": "waiting_external_result",
        }.get(handoff_mode, "")
        lowered = " ".join(
            str(ctx.node.get(key) or "")
            for key in ("wait_reason", "reason", "title", "instruction", "prompt")
        ).lower()
        wait_reason = str(ctx.node.get("wait_reason") or "").strip() or mode_reason
        if not wait_reason:
            if "credential" in lowered or "secret" in lowered or "api key" in lowered:
                wait_reason = "need_credential"
            elif "login" in lowered or "captcha" in lowered or "otp" in lowered:
                wait_reason = "need_login"
            elif "external" in lowered or "webhook" in lowered or "callback" in lowered:
                wait_reason = "waiting_external_result"
            else:
                wait_reason = "need_user_decision" if action == "handoff" else "waiting_user"
        source = f"workflow_{action or 'wait'}_node"
        if handoff_mode:
            source = f"{source}:{handoff_mode}"
        ctx.task.set_wait(
            wait_reason=wait_reason,
            message=instruction,
            source=source,
            required_input=[instruction],
        )
        return NodeExecutionResult(
            ok=False,
            status="running",
            outcome=instruction,
            advance=False,
            data={"wait": True, "wait_reason": wait_reason, "handoff_mode": handoff_mode or None},
            note="node_executor_wait",
        )

    async def _execute_notify_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        action = str(ctx.node.get("action") or "notify").strip()
        if action == "deliver_outbox":
            return await self._execute_deliver_outbox_node(ctx)
        item, build_error = await self._workflow_outbox_item_from_node(ctx, action)
        if build_error:
            return NodeExecutionResult(
                ok=False,
                status="blocked",
                outcome=build_error,
                blocked=True,
                advance=False,
                data={"route": "error", "error": build_error},
                note="node_executor_notify_build_error",
            )
        data = self._ensure_workflow_data(ctx.task)
        delivered = False
        queued = False
        route = "success"
        if item.get("delivery") == "plugin_handoff":
            queued = True
            self._append_workflow_outbox_item(data, item)
        elif self._workflow_outbox_item_current_session(ctx, item):
            delivered, error = await self._send_workflow_outbox_item(ctx.event, item)
            if delivered:
                item["delivery"] = "sent"
                item["delivered_at"] = now_iso()
                self._append_workflow_outbox_history(data, item)
            else:
                item["delivery"] = "error"
                item["delivery_error"] = error
                self._append_workflow_outbox_history(data, item)
                route = "error"
        else:
            item["delivery"] = item.get("delivery") or "outbox"
            item["delivery_note"] = item.get("delivery_note") or "target is not the current event session; adapter delivery required"
            self._append_workflow_outbox_item(data, item)
            queued = True
        outcome = self._workflow_outbox_item_summary(item)
        ctx.task.add_log("notify", outcome)
        return NodeExecutionResult(
            ok=route == "success",
            status="completed" if route == "success" else "blocked",
            outcome=outcome,
            next_node_id=self._single_next(ctx.outgoing),
            data={
                "route": route,
                "message": item.get("message") or "",
                "outbox": item,
                "delivered": delivered,
                "queued": queued,
            },
            needs_react=item.get("delivery") == "plugin_handoff" or len(ctx.outgoing) > 1,
            blocked=route != "success",
            advance=route == "success" and item.get("delivery") != "plugin_handoff" and len(ctx.outgoing) <= 1,
            note="node_executor_notify",
        )

    async def _execute_deliver_outbox_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        data = self._ensure_workflow_data(ctx.task)
        outbox = data.get("outbox") if isinstance(data.get("outbox"), list) else []
        delivered = []
        failed = []
        pending = []
        for item in outbox:
            row = dict(item) if isinstance(item, dict) else {"message": str(item)}
            if row.get("delivery") == "plugin_handoff":
                pending.append(row)
                continue
            if self._workflow_outbox_item_current_session(ctx, row):
                sent, error = await self._send_workflow_outbox_item(ctx.event, row)
                if not sent:
                    row["delivery"] = "error"
                    row["delivery_error"] = error
                    row["attempted_at"] = now_iso()
                    failed.append(row)
                    continue
                row["delivery"] = "sent"
                row["delivered_at"] = now_iso()
                delivered.append(row)
            else:
                row["delivery"] = row.get("delivery") or "outbox"
                row["delivery_note"] = row.get("delivery_note") or "target is not the current event session; adapter delivery required"
                pending.append(row)
        data["outbox"] = pending[-120:]
        history = data.setdefault("outbox_delivery_history", [])
        if not isinstance(history, list):
            history = []
        history.extend(delivered + failed)
        data["outbox_delivery_history"] = history[-120:]
        route = "success" if (delivered or not outbox) and not failed and not pending else "failed"
        return NodeExecutionResult(
            ok=route == "success",
            status="completed" if route == "success" else "blocked",
            outcome=f"Outbox delivery: sent={len(delivered)}, failed={len(failed)}, pending={len(pending)}.",
            next_node_id=self._single_next(ctx.outgoing) if route == "success" else "",
            data={"route": route, "delivered": delivered, "failed": failed, "pending": pending},
            blocked=route != "success",
            note="node_executor_deliver_outbox",
        )

    async def _workflow_outbox_item_from_node(
        self,
        ctx: NodeExecutionContext,
        action: str,
    ) -> tuple[dict[str, Any], str]:
        channel = {
            "send_message": "message",
            "send_private_message": "private_message",
            "send_email": "email",
        }.get(action, "notify")
        target = str(
            ctx.node.get("target")
            or ctx.node.get("to")
            or ctx.node.get("recipient")
            or ctx.node.get("conversation")
            or ctx.node.get("umo")
            or ""
        ).strip()
        image = self._workflow_node_text(ctx, "image", "image_source", "image_url", "image_path", "image_base64")
        face = self._workflow_node_text(ctx, "face", "face_id", "emoji", "emoji_id")
        plugin_name = self._workflow_node_text(ctx, "plugin_name", "plugin", "target_plugin")
        send_type = str(
            ctx.node.get("send_type")
            or ctx.node.get("message_type")
            or ctx.node.get("content_type")
            or ""
        ).strip().lower()
        send_type = {
            "fixed": "text",
            "plain": "text",
            "prompt_reply": "prompt",
            "llm": "prompt",
            "face": "emoji",
            "emote": "emoji",
            "plugin_prompt": "plugin",
        }.get(send_type, send_type)
        if not send_type:
            if plugin_name:
                send_type = "plugin"
            elif image:
                send_type = "image"
            elif face:
                send_type = "emoji"
            else:
                send_type = "text"
        reply_mode = str(ctx.node.get("reply_mode") or ("prompt" if send_type == "prompt" else "fixed")).strip().lower()
        message = self._workflow_node_text(ctx, "message", "content", "text")
        if send_type == "prompt" or reply_mode == "prompt":
            prompt = self._workflow_node_text(ctx, "prompt", "user_prompt", "message", "content", "instruction")
            if not prompt:
                prompt = "Generate a concise workflow reply for the current conversation."
            generated, error = await self._generate_workflow_reply(ctx, prompt)
            if error:
                return {}, error
            message = generated
            reply_mode = "prompt"
            send_type = "prompt"
        elif send_type == "plugin":
            message = self._workflow_node_text(ctx, "plugin_prompt", "prompt", "message", "instruction")
            if not plugin_name:
                return {}, "send_message plugin mode requires plugin_name."
        elif not message and send_type not in {"image", "emoji"}:
            message = str(
                ctx.task.current_summary
                or ctx.task.last_confirmed_progress
                or ctx.task.last_observation
                or "Notification checkpoint."
            ).strip()
        message = self._compact_text(str(message or ""), 2000)
        item = {
            "time": now_iso(),
            "node_id": str(ctx.node.get("id") or ""),
            "action": action,
            "channel": channel,
            "target": target,
            "send_type": send_type,
            "reply_mode": reply_mode,
            "message": message,
            "image": image,
            "face": face,
            "emoji": face,
            "plugin_name": plugin_name,
            "delivery": "plugin_handoff" if send_type == "plugin" else "outbox",
        }
        for key in ("image_mime", "image_name", "emoji_md5", "emoji_cdnurl"):
            value = self._workflow_node_text(ctx, key)
            if value:
                item[key] = value
        return item, ""

    def _workflow_node_text(self, ctx: NodeExecutionContext, *keys: str) -> str:
        for key in keys:
            if key not in ctx.node:
                continue
            value = self._resolve_workflow_template(ctx.task, ctx.node.get(key))
            if value in (None, ""):
                continue
            return str(value).strip()
        return ""

    async def _generate_workflow_reply(self, ctx: NodeExecutionContext, prompt: str) -> tuple[str, str]:
        provider_ids: list[str] = []
        provider_id = ""  # Primary nodes inherit the source bot; explicit subagent overrides are separate.
        if provider_id:
            provider_ids.append(provider_id)
        try:
            current = await self.context.get_current_chat_provider_id(ctx.event.unified_msg_origin)
            if current and current not in provider_ids:
                provider_ids.append(current)
        except Exception:
            pass
        fallback = str(_cfg(self.config, "fallback_summary_provider_id", "") or "").strip()
        if fallback and fallback not in provider_ids:
            provider_ids.append(fallback)
        if not provider_ids:
            return "", "No chat provider is available for prompt reply."
        trigger = self._workflow_trigger_payload(ctx.task)
        payload = {
            "instruction": prompt,
            "trigger": trigger,
            "task": {
                "goal": ctx.task.root_goal,
                "summary": ctx.task.current_summary,
                "last_observation": ctx.task.last_observation,
                "current_node": ctx.task.workflow_current_node_id,
            },
        }
        last_error = ""
        for provider_id in provider_ids:
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=json.dumps(payload, ensure_ascii=False, default=str),
                    system_prompt=(
                        "You generate exactly the message content that Agent Lab should send now. "
                        "Return plain text only. Do not mention these instructions."
                    ),
                )
                text = self._redact_known_secrets(str(getattr(resp, "completion_text", "") or "").strip())
                if text:
                    return self._compact_text(text, 2000), ""
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
        return "", last_error or "Prompt reply provider returned no content."

    def _workflow_outbox_item_current_session(self, ctx: NodeExecutionContext, item: dict[str, Any]) -> bool:
        target = str(item.get("target") or "").strip()
        if not target:
            return item.get("channel") != "email"
        current_umo = str(getattr(ctx.event, "unified_msg_origin", "") or ctx.task.umo or "").strip()
        if target == current_umo or target == str(ctx.task.umo or "").strip():
            return True
        group_id = self._event_group_id(ctx.event)
        if group_id and target == group_id:
            return True
        try:
            sender_id = str(ctx.event.get_sender_id() or "").strip()
        except Exception:
            sender_id = ""
        try:
            is_private = bool(ctx.event.is_private_chat())
        except Exception:
            is_private = False
        return bool(is_private and sender_id and target == sender_id)

    async def _send_workflow_outbox_item(self, event: AstrMessageEvent, item: dict[str, Any]) -> tuple[bool, str]:
        if item.get("channel") == "email":
            return False, "email delivery requires an external adapter"
        send = getattr(event, "send", None)
        if not callable(send):
            return False, "event.send is unavailable"
        try:
            chain = self._workflow_message_chain(item)
            await send(chain)
            return True, ""
        except Exception as exc:
            logger.warning("[AgentLab] workflow outbox send failed: %s", exc)
            return False, f"{type(exc).__name__}: {exc}"

    def _workflow_message_chain(self, item: dict[str, Any]) -> MessageChain:
        chain = MessageChain(type="agent_lab_workflow")
        message = str(item.get("message") or "").strip()
        image = str(item.get("image") or "").strip()
        face = str(item.get("face") or item.get("emoji") or "").strip()
        if message:
            chain.message(message)
        if image:
            cleaned = image
            if cleaned.startswith("data:image") and "," in cleaned:
                cleaned = cleaned.split(",", 1)[1].strip()
            if cleaned.startswith(("http://", "https://")):
                chain.url_image(cleaned)
            elif cleaned.startswith("base64://"):
                chain.base64_image(cleaned.removeprefix("base64://"))
            elif re.fullmatch(r"[A-Za-z0-9+/=\r\n]+", cleaned) and len(cleaned) > 80:
                chain.base64_image(cleaned)
            else:
                chain.file_image(cleaned)
        if face:
            if Comp is not None and hasattr(Comp, "Face"):
                try:
                    chain.chain.append(Comp.Face(id=int(face)))
                except Exception:
                    chain.message(f"[emoji:{face}]")
            else:
                chain.message(f"[emoji:{face}]")
        if not chain.chain:
            raise ValueError("outbox item has no message, image, or emoji content")
        return chain

    def _append_workflow_outbox_item(self, data: dict[str, Any], item: dict[str, Any]) -> None:
        outbox = data.setdefault("outbox", [])
        if not isinstance(outbox, list):
            outbox = []
        outbox.append(item)
        data["outbox"] = outbox[-120:]

    def _append_workflow_outbox_history(self, data: dict[str, Any], item: dict[str, Any]) -> None:
        history = data.setdefault("outbox_delivery_history", [])
        if not isinstance(history, list):
            history = []
        history.append(dict(item))
        data["outbox_delivery_history"] = history[-120:]

    def _workflow_outbox_item_summary(self, item: dict[str, Any]) -> str:
        parts = [
            f"delivery={item.get('delivery') or 'outbox'}",
            f"channel={item.get('channel') or '-'}",
            f"type={item.get('send_type') or '-'}",
        ]
        if item.get("target"):
            parts.append(f"target={item.get('target')}")
        if item.get("plugin_name"):
            parts.append(f"plugin={item.get('plugin_name')}")
        if item.get("delivery_error"):
            parts.append(f"error={item.get('delivery_error')}")
        message = str(item.get("message") or item.get("image") or item.get("emoji") or "").strip()
        if message:
            parts.append(self._compact_text(message, 240))
        return "Workflow outbox " + "; ".join(parts)

    async def _execute_archive_task_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        plan = task_control(ctx.task)
        if plan.get("steps") and any(step.get("status") != "completed" for step in plan["steps"]):
            return NodeExecutionResult(needs_react=True, advance=False,
                outcome="画布到达出口，但具体计划仍待核对。请 Bot 核查工具记录并保存当前步骤检查点，全部步骤完成后归档。",
                note="archive_waits_for_task_plan")
        final_summary = str(
            ctx.node.get("final_summary")
            or ctx.node.get("summary")
            or ctx.node.get("message")
            or ctx.task.current_summary
            or ctx.task.last_confirmed_progress
            or ctx.task.last_observation
            or "Workflow archive completed."
        ).strip()
        memory_candidates = self._node_string_list(ctx.task, ctx.node, "memory_candidates", "candidates")
        result_text = await self._archive_task_direct(
            ctx.task,
            ctx.spec,
            status=str(ctx.node.get("status") or "completed"),
            final_summary=final_summary,
            memory_candidates=memory_candidates,
            reason="workflow_archive_task_node",
            finish_approval_id=str(ctx.node.get("finish_approval_id") or ctx.node.get("approval_id") or ""),
        )
        archived = self.storage.load_active_task(ctx.task.umo) is None
        return NodeExecutionResult(
            ok=True,
            status="completed" if archived else "needs_evidence",
            outcome=result_text,
            data={"route": "success" if archived else "failed", "archived": archived},
            blocked=False,
            needs_react=not archived,
            terminal=archived,
            advance=False,
            note="node_executor_archive_task",
        )

    async def _execute_terminal_node(self, ctx: NodeExecutionContext) -> NodeExecutionResult:
        return NodeExecutionResult(
            outcome="Terminal node requires final summary and finish decision.",
            needs_react=True,
            terminal=True,
            advance=False,
            note="node_executor_terminal_react",
        )

    async def _run_workflow_runtime(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        reason: str,
    ) -> WorkflowRuntimeRun:
        runtime_run = WorkflowRuntimeRun()
        if task_control(task).get("workflow") == "none":
            runtime_run.needs_react = True
            return runtime_run
        self._ensure_workflow_data(task)
        for _ in range(self.workflow_runtime.max_auto_steps):
            decision = self.workflow_runtime.inspect(spec, task)
            budget_reason = self._consume_node_budget(task, decision.node)
            if budget_reason:
                self._pause_task_for_budget(task, budget_reason)
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=budget_reason,
                        note="budget_exhausted",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            schema_reason = self._validate_node_input_schema(task, decision.node)
            if schema_reason:
                task.status = "paused"
                task.set_wait(
                    wait_reason="need_user_decision",
                    message=schema_reason,
                    source="schema_validation",
                    required_input=["valid_node_input"],
                )
                task.add_blocker("schema_mismatch", schema_reason)
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=schema_reason,
                        note="schema_mismatch",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            loop_reason = self._loop_guard_before_node(task, decision.node)
            if loop_reason:
                runtime_run.steps.append(
                    WorkflowDecision(
                        node_id=decision.node_id,
                        node=decision.node,
                        status="blocked",
                        outcome=loop_reason,
                        note="loop_guard",
                        blocked=True,
                    )
                )
                runtime_run.blocked = True
                break
            if decision.blocked:
                runtime_run.steps.append(decision)
                runtime_run.blocked = True
                task.add_blocker("workflow_runtime", decision.outcome)
                task.status = "blocked"
                task.add_snapshot(
                    "workflow_runtime",
                    {
                        "node_id": decision.node_id,
                        "status": "blocked",
                        "reason": decision.outcome,
                    },
                )
                break

            if self.node_executors.can_execute(decision.node):
                nodes = self.workflow_runtime.node_map(spec)
                context_edges = self._workflow_edges_from(spec, decision.node_id)
                outgoing = [str(edge.get("to") or "") for edge in context_edges if str(edge.get("to") or "") in nodes]
                ctx = NodeExecutionContext(
                    event=event,
                    task=task,
                    spec=spec,
                    node=decision.node,
                    outgoing=outgoing,
                    next_candidates=self._candidate_nodes_from_edges(nodes, context_edges),
                    reason=reason,
                )
                result = await self._execute_node_with_policy(ctx)
                latest = self.storage.load_active_task(task.umo)
                if latest is None or latest.task_id != task.task_id:
                    runtime_run.terminal = True
                    return runtime_run
                if latest.status != "running" or task_control(latest).get("version") != task_control(task).get("version"):
                    task.__dict__.update(latest.__dict__)
                    runtime_run.blocked = True
                    return runtime_run
                task.workflow_data["task_control"] = task_control(latest)
                if result.ok and not result.blocked:
                    output_reason = self._validate_node_output_schema(decision.node, result)
                    if output_reason:
                        result.ok = False
                        result.blocked = True
                        result.status = "blocked"
                        result.outcome = output_reason
                        result.note = "node_output_schema_mismatch"
                        result.advance = False
                if not result.next_node_id and not result.needs_react and not result.terminal:
                    target = self._select_next_node_after_result(task, spec, decision.node_id, result)
                    if target:
                        result.next_node_id = target
                        result.advance = True
                self._record_node_execution(task, decision.node, result)
                loop_after_reason = self._loop_guard_after_node(task, decision.node, result)
                executed = self._node_result_to_decision(decision.node, result)
                if loop_after_reason:
                    executed.blocked = True
                    executed.status = "blocked"
                    executed.note = "loop_guard"
                    executed.outcome = loop_after_reason
                    runtime_run.blocked = True
                runtime_run.steps.append(executed)
                if loop_after_reason:
                    break

                if result.terminal:
                    runtime_run.needs_react = True
                    runtime_run.react_node_id = executed.node_id
                    runtime_run.terminal = True
                    break

                if result.needs_react:
                    runtime_run.needs_react = True
                    runtime_run.react_node_id = executed.node_id
                    break

                if result.blocked:
                    if result.next_node_id:
                        self._advance_task_workflow(
                            task,
                            spec,
                            node_id=executed.node_id,
                            outcome=result.outcome,
                            next_node_id=result.next_node_id,
                            note=result.note,
                            status=result.status,
                        )
                        continue
                    runtime_run.blocked = True
                    if result.status == "blocked":
                        task.status = "blocked"
                        task.add_blocker("workflow_runtime", result.outcome)
                    break

                if result.advance:
                    self._advance_task_workflow(
                        task,
                        spec,
                        node_id=executed.node_id,
                        outcome=result.outcome,
                        next_node_id=result.next_node_id,
                        note=result.note,
                        status=result.status,
                    )
                    if not result.next_node_id:
                        runtime_run.needs_react = True
                        runtime_run.react_node_id = executed.node_id
                        break
                else:
                    break
                continue

            if decision.terminal or decision.needs_react:
                runtime_run.needs_react = True
                runtime_run.react_node_id = decision.node_id
                runtime_run.terminal = decision.terminal
                break

            self._advance_task_workflow(
                task,
                spec,
                node_id=decision.node_id,
                outcome=decision.outcome,
                next_node_id=decision.next_node_id,
                note=decision.note,
                status=decision.status,
            )
            runtime_run.steps.append(decision)
            if not decision.next_node_id:
                runtime_run.needs_react = True
                runtime_run.react_node_id = decision.node_id
                break

        if runtime_run.changed:
            task.add_log("workflow_runtime", self._compact_text(runtime_run.summary(), 1000))
            task.add_snapshot(
                "workflow_runtime",
                {
                    "reason": reason,
                    "steps": [
                        {
                            "node_id": step.node_id,
                            "next_node_id": step.next_node_id,
                            "status": step.status,
                            "outcome": step.outcome,
                            "note": step.note,
                        }
                        for step in runtime_run.steps
                    ],
                    "needs_react": runtime_run.needs_react,
                    "react_node_id": runtime_run.react_node_id,
                    "blocked": runtime_run.blocked,
                },
            )
        return runtime_run

    def _save_workflow_private_memory(
        self,
        task: TaskState,
        node: dict[str, Any],
        outcome: str = "",
    ) -> None:
        tags = node.get("tags") or node.get("memory_tags") or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.replace("，", ",").split(",")]
        tags = [str(tag).strip() for tag in tags if str(tag).strip()]
        tags = ["task", "workflow", "private", *(tags or ["checkpoint"])]
        agent_id = str(node.get("agent_id") or task.agent_id or "").strip()
        folder_id = str(node.get("folder_id") or node.get("memory_folder") or "").strip()
        folder = self.storage.get_memory_folder(folder_id, agent_id=agent_id)
        text = "\n".join(
            part
            for part in (
                f"Task: {task.task_id}",
                f"Goal: {task.root_goal}",
                f"Workflow node: {node.get('id') or '-'} / {node.get('title') or '-'}",
                f"Summary: {task.current_summary or '-'}",
                f"Progress: {task.last_confirmed_progress or '-'}",
                f"Observation: {task.last_observation or outcome or '-'}",
                f"Next step: {task.next_step or '-'}",
            )
            if part.strip()
        )
        self.storage.save_memory_entry(
            {
                "text": text,
                "source_task_id": task.task_id,
                "source_umo": task.umo,
                "agent_id": agent_id,
                "folder_id": folder.get("folder_id") or "default",
                "folder_name": folder.get("name") or "默认记忆夹",
                "status": "candidate",
                "kind": "workflow_private_memory",
                "tags": tags,
                "expose_to_normal": False,
                "evidence": {
                    "action": "save_memory",
                    "node_id": str(node.get("id") or ""),
                    "agent_id": agent_id,
                    "folder_id": folder.get("folder_id") or "default",
                },
            }
        )
        task.add_log("task_memory", f"workflow_private_memory saved at {node.get('id') or '-'}")

    def _workflow_react_prompt(
        self,
        *,
        task: TaskState,
        spec: AgentSpec,
        reason: str,
    ) -> str:
        nodes = self.workflow_runtime.node_map(spec)
        outgoing = self.workflow_runtime.outgoing(spec)
        current_id = self.workflow_runtime.current_node_id(spec, task)
        node = nodes.get(current_id) or {}
        candidates = [
            nodes[node_id]
            for node_id in outgoing.get(current_id, [])
            if node_id in nodes
        ]
        if not node:
            return build_tick_prompt(task, reason)
        return self.workflow_runtime.build_react_prompt(
            task=task,
            node=node,
            next_candidates=candidates,
            reason=reason,
        )

    @staticmethod
    def _workflow_entry_id(spec: AgentSpec) -> str:
        for node in spec.workflow_nodes:
            if node.get("action") == "summarize_entry":
                return str(node.get("id") or "")
        for node in spec.workflow_nodes:
            if node.get("stage") == "entry":
                return str(node.get("id") or "")
        return str(spec.workflow_nodes[0].get("id") or "") if spec.workflow_nodes else ""

    @staticmethod
    def _workflow_outgoing(spec: AgentSpec) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for edge in spec.workflow_edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if not start or not end:
                continue
            result.setdefault(start, []).append(end)
        return result

    def _advance_task_workflow(
        self,
        task: TaskState,
        spec: AgentSpec,
        *,
        node_id: str = "",
        outcome: str = "",
        next_node_id: str = "",
        note: str = "",
        status: str = "completed",
    ) -> str:
        self._normalize_agent_workflow(spec)
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        if not node_map:
            return "当前 AgentSpec 没有工作流节点。"
        current_id = str(node_id or task.workflow_current_node_id or self._workflow_entry_id(spec)).strip()
        if current_id not in node_map:
            return f"未找到工作流节点：{current_id}"
        outgoing = self._workflow_outgoing(spec)
        candidates = outgoing.get(current_id, [])
        target = str(next_node_id or "").strip()
        if not target and len(candidates) == 1:
            target = candidates[0]
        if target and target not in node_map:
            return f"未找到下一工作流节点：{target}"
        if target and candidates and target not in candidates:
            note = (note + f"\nmanual_jump_from={current_id}").strip()

        task.add_workflow_event(
            current_id,
            outcome=outcome,
            note=note,
            next_node_id=target,
            status=status if status in {"completed", "running", "skipped", "blocked", "entered"} else "completed",
        )
        if target:
            task.workflow_current_node_id = target
            if not task.workflow_path or task.workflow_path[-1] != target:
                task.workflow_path.append(target)
                task.workflow_path = task.workflow_path[-80:]
            task.add_log("workflow", f"{current_id} -> {target}: {self._compact_text(outcome or note, 300)}")
        else:
            task.workflow_current_node_id = current_id
            task.add_log("workflow", f"{current_id}: {self._compact_text(outcome or note, 300)}")
        task.add_snapshot(
            "workflow",
            {
                "node_id": current_id,
                "next_node_id": target,
                "candidates": candidates,
                "outcome": outcome,
                "note": note,
            },
        )
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_decision(
                task,
                phase="workflow",
                action="advance",
                node_id=current_id,
                reason=outcome or note,
                capability="workflow.control",
                next_node_id=target,
                confidence="high" if target else "medium",
            )
            self.agent_runtime.mark_current(task, completed_node_id=current_id)
            self.agent_runtime.update_resume(task, reason="advance_workflow")
        next_candidates = outgoing.get(task.workflow_current_node_id, [])
        next_text = ", ".join(next_candidates) or "-"
        return (
            f"工作流已记录：{current_id}"
            f"{' -> ' + target if target else ''}。\n"
            f"当前节点：{task.workflow_current_node_id or current_id}\n"
            f"下一候选：{next_text}"
        )

    def _subagent_of_node(self, spec: AgentSpec, node: dict[str, Any]) -> "SubAgentSpec | None":
        """按 node.owner 找到所属子Agent；无 owner 或找不到 → None（归主agent）。"""
        owner_id = str((node or {}).get("owner") or "").strip()
        if not owner_id:
            return None
        for sa in getattr(spec, "sub_agents", None) or []:
            if getattr(sa, "sub_agent_id", "") == owner_id:
                return sa
        return None

    def _node_resource_tags(self, node: dict[str, Any]) -> list[str]:
        raw = (node or {}).get("resource_tags")
        if isinstance(raw, str):
            parts = re.split(r"[\n,，、;；]+", raw)
        elif isinstance(raw, list):
            parts = raw
        else:
            parts = []
        return [str(p).strip() for p in parts if str(p).strip()]

    def _resource_lock(self, tag: str) -> asyncio.Lock:
        lock = self._resource_locks.get(tag)
        if lock is None:
            lock = asyncio.Lock()
            self._resource_locks[tag] = lock
        return lock

    @contextlib.asynccontextmanager
    async def _acquire_resource_locks(self, tags: list[str]):
        """对资源标签按序加锁（同标签跨泳道串行），避免多流程互踩同一资源。"""
        ordered = sorted({str(t).strip() for t in (tags or []) if str(t).strip()})
        acquired: list[asyncio.Lock] = []
        try:
            for tag in ordered:
                lock = self._resource_lock(tag)
                await lock.acquire()
                acquired.append(lock)
            yield
        finally:
            for lock in reversed(acquired):
                lock.release()

    async def _lane_rate_throttle(self, owner: "SubAgentSpec | None") -> None:
        """每泳道 rate_per_minute 限速（最小间隔法；0=不限）。"""
        if not owner or int(getattr(owner, "rate_per_minute", 0) or 0) <= 0:
            return
        min_interval = 60.0 / float(int(owner.rate_per_minute))
        async with self._resource_lock(f"__lane_rate__:{owner.sub_agent_id}"):
            last = self._lane_rate_state.get(owner.sub_agent_id, 0.0)
            now = time.monotonic()
            wait = min_interval - (now - last)
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._lane_rate_state[owner.sub_agent_id] = now

    async def _run_parallel_workflow(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        branch_node_id: str = "",
        parallel_group: str = "",
        merge_node_id: str = "",
        shared_instruction: str = "",
        api_payloads: dict[str, Any] | None = None,
        max_concurrency: int = 3,
    ) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        outgoing = self._workflow_outgoing(spec)
        branch_id = self._resolve_parallel_branch_id(spec, task, branch_node_id)
        if not branch_id:
            return {
                "ok": False,
                "error": "未找到 parallel_branch 节点；请先在画布中添加并行分支。",
            }
        branch = node_map.get(branch_id) or {}
        group = str(parallel_group or "").strip()
        worker_ids = [
            node_id
            for node_id in outgoing.get(branch_id, [])
            if node_id in node_map
            and node_id != merge_node_id
            and (not group or str(node_map[node_id].get("parallel_group") or "").strip() == group)
        ]
        if not worker_ids:
            return {
                "ok": False,
                "branch_node_id": branch_id,
                "error": "并行分支没有匹配的后续工作包。",
            }
        api_payloads = api_payloads or {}
        default_semaphore = asyncio.Semaphore(max(1, max_concurrency))
        lane_semaphores: dict[str, asyncio.Semaphore] = {}

        def _semaphore_for(node: dict[str, Any]) -> asyncio.Semaphore:
            owner = self._subagent_of_node(spec, node)
            if owner is None:
                return default_semaphore
            sem = lane_semaphores.get(owner.sub_agent_id)
            if sem is None:
                sem = asyncio.Semaphore(max(1, int(owner.max_concurrency or 2)))
                lane_semaphores[owner.sub_agent_id] = sem
            return sem

        async def run_worker(node_id: str) -> dict[str, Any]:
            node = node_map[node_id]
            async with _semaphore_for(node):
                async with self._acquire_resource_locks(self._node_resource_tags(node)):
                    return await self._run_parallel_worker(
                        event=event,
                        task=task,
                        spec=spec,
                        node=node,
                        shared_instruction=shared_instruction,
                        api_payload=api_payloads.get(node_id) or {},
                    )

        workers = [
            normalize_worker_output(item)
            for item in await asyncio.gather(*(run_worker(node_id) for node_id in worker_ids))
        ]
        merge_id = self._resolve_parallel_merge_id(
            spec,
            worker_ids,
            explicit_merge_id=merge_node_id,
        )
        ok_count = sum(1 for item in workers if item.get("ok"))
        summary = (
            f"并行分支 {branch_id} 完成 {ok_count}/{len(workers)} 个工作包。"
            f"{' 汇总到 ' + merge_id if merge_id else ' 未找到自动汇总节点。'}"
        )
        run = {
            "run_id": new_id("parallel"),
            "time": now_iso(),
            "ok": ok_count == len(workers),
            "branch_node_id": branch_id,
            "branch_title": branch.get("title") or branch_id,
            "parallel_group": group,
            "merge_node_id": merge_id,
            "summary": summary,
            "workers": workers,
        }
        task.add_parallel_run(run)
        task.last_observation = self._compact_text(
            json.dumps(run, ensure_ascii=False, indent=2),
            4000,
        )
        task.last_confirmed_progress = summary
        task.current_summary = summary
        task.next_step = (
            f"进入工作流节点 {merge_id}，合并并校验并行结果。"
            if merge_id
            else "检查并行结果，手动选择下一工作流节点。"
        )
        task.add_log("parallel_workflow", summary)
        task.add_snapshot(
            "parallel_workflow",
            {
                "branch_node_id": branch_id,
                "merge_node_id": merge_id,
                "worker_ids": worker_ids,
                "ok": run["ok"],
            },
        )
        for worker in workers:
            task.add_workflow_event(
                str(worker.get("node_id") or ""),
                status="completed" if worker.get("ok") else "blocked",
                outcome=str(worker.get("summary") or worker.get("error") or ""),
                note=str(worker.get("details") or "")[:1000],
                next_node_id=merge_id,
            )
            if hasattr(self, "agent_runtime"):
                node_id = str(worker.get("node_id") or "")
                summary_text = str(worker.get("summary") or worker.get("error") or "worker finished")
                worker_verdict = self.verifier.verify_worker(worker)
                self.agent_runtime.record_observation(
                    task,
                    source="parallel_worker",
                    node_id=node_id,
                    payload=worker,
                    summary=summary_text,
                )
                self.agent_runtime.record_verdict(
                    task,
                    node_id=node_id,
                    passed=worker_verdict.passed,
                    status=worker_verdict.status,
                    reason=worker_verdict.reason,
                    missing=worker_verdict.missing,
                    next_action=worker_verdict.next_action,
                )

        # Merge verification: check that worker results are sufficient.
        merge_verdict = self.verifier.verify_merge(
            workers,
            branch_node_id=branch_id,
            merge_node_id=merge_id,
        )
        run["merge_verdict"] = merge_verdict.to_dict()
        if hasattr(self, "agent_runtime"):
            self.agent_runtime.record_verdict(
                task,
                node_id=merge_id or branch_id,
                passed=merge_verdict.passed,
                status=merge_verdict.status,
                reason=merge_verdict.reason,
                missing=merge_verdict.missing,
                next_action=merge_verdict.next_action,
            )

        self._advance_task_workflow(
            task,
            spec,
            node_id=branch_id,
            outcome=summary,
            next_node_id=merge_id,
            note="agent_lab_run_parallel_workflow",
            status="completed" if run["ok"] else "blocked",
        )
        latest = self.storage.load_active_task(task.umo)
        if latest and latest.task_id == task.task_id:
            task.workflow_data["task_control"] = task_control(latest)
            task.approvals = latest.approvals
            task.budget = latest.budget
            task.token_usage = latest.token_usage
            if latest.status != "running":
                task.status, task.wait, task.watchdog = latest.status, latest.wait, latest.watchdog
        return run

    def _resolve_parallel_branch_id(
        self,
        spec: AgentSpec,
        task: TaskState,
        branch_node_id: str = "",
    ) -> str:
        node_map = {str(node.get("id") or ""): node for node in spec.workflow_nodes}
        requested = str(branch_node_id or "").strip()
        if requested and requested in node_map:
            return requested
        current = str(task.workflow_current_node_id or "").strip()
        if current in node_map and node_map[current].get("action") == "parallel_branch":
            return current
        for node in spec.workflow_nodes:
            if node.get("action") == "parallel_branch":
                return str(node.get("id") or "")
        return ""

    def _resolve_parallel_merge_id(
        self,
        spec: AgentSpec,
        worker_ids: list[str],
        *,
        explicit_merge_id: str = "",
    ) -> str:
        node_ids = {str(node.get("id") or "") for node in spec.workflow_nodes}
        explicit = str(explicit_merge_id or "").strip()
        if explicit and explicit in node_ids:
            return explicit
        outgoing = self._workflow_outgoing(spec)
        counts: dict[str, int] = {}
        for worker_id in worker_ids:
            for candidate in outgoing.get(worker_id, []):
                counts[candidate] = counts.get(candidate, 0) + 1
        if not counts:
            return ""
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        best, count = ranked[0]
        return best if count >= 2 or len(worker_ids) == 1 else ""

    async def _run_parallel_worker(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        node: dict[str, Any],
        shared_instruction: str = "",
        api_payload: Any = None,
    ) -> dict[str, Any]:
        node_id = str(node.get("id") or "").strip()
        kind = str(node.get("kind") or "state").strip()
        action = str(node.get("action") or "manual").strip()
        base = {
            "node_id": node_id,
            "title": node.get("title") or node_id,
            "kind": kind,
            "action": action,
            "parallel_group": node.get("parallel_group") or "",
            "worker_spec": worker_spec_for_node(node, allowed_tools=spec.enabled_tools).to_dict(),
            "ok": False,
            "status": "blocked",
            "summary": "",
            "details": "",
        }
        try:
            if kind == "api" or action == "call_api":
                if not self._tool_allowed_by_agent_profile(spec, CUSTOM_API_TOOL_NAME):
                    base["error"] = "Custom API worker is outside the Agent tool profile."
                    base["summary"] = base["error"]
                    return base
                node_for_call = dict(node)
                scope = self._api_scope_for_node(task, node_for_call)
                if scope and not str(node_for_call.get("api_id") or node_for_call.get("ref_id") or "").strip():
                    node_for_call["api_id"] = str(scope.get("api_id") or "").strip()
                    node_for_call["api_scope_id"] = str(scope.get("node_id") or "").strip()
                return await self._run_parallel_api_worker(
                    node_for_call,
                    base,
                    api_payload=api_payload,
                    event=event,
                )
            return await self._run_parallel_agent_worker(
                event=event,
                task=task,
                spec=spec,
                node=node,
                base=base,
                shared_instruction=shared_instruction,
            )
        except Exception as exc:
            base["error"] = f"{type(exc).__name__}: {exc}"
            base["summary"] = base["error"]
            return base

    async def _run_parallel_api_worker(
        self,
        node: dict[str, Any],
        base: dict[str, Any],
        *,
        api_payload: Any = None,
        event: AstrMessageEvent | None = None,
    ) -> dict[str, Any]:
        api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
        if not api_id:
            base["error"] = "API 节点未绑定 api_id。"
            base["summary"] = base["error"]
            return base
        query_json, body_json, headers_json = self._parallel_api_payload_json(api_payload)
        if event is not None:
            tool = self.astrbot_bridge.tool(CUSTOM_API_TOOL_NAME, event)
            text = await self.astrbot_bridge.invoke(event, tool, {"api_id": api_id,
                "query_json": query_json, "body_json": body_json, "headers_json": headers_json})
            result = json.loads(text.rsplit("\n[任务工具证据 ID:", 1)[0])
            api_spec, message = {"api_id": api_id}, ""
        else:
            result, api_spec, message = await self._call_registered_custom_api(
                api_id,
                query_json=query_json,
                body_json=body_json,
                headers_json=headers_json,
            )
        if message:
            base["error"] = message
            base["summary"] = message
            return base
        base.update(
            {
                "ok": bool(result.get("ok")),
                "status": "completed" if result.get("ok") else "blocked",
                "api_id": api_spec.get("api_id") if api_spec else api_id,
                "summary": f"API {api_spec.get('api_id') if api_spec else api_id} status={result.get('status')}",
                "details": self._compact_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    1600,
                ),
            }
        )
        return base

    async def _run_parallel_agent_worker(
        self,
        *,
        event: AstrMessageEvent,
        task: TaskState,
        spec: AgentSpec,
        node: dict[str, Any],
        base: dict[str, Any],
        shared_instruction: str = "",
    ) -> dict[str, Any]:
        plugin_name = str(
            node.get("plugin_name")
            or (node.get("ref_id") if node.get("ref_type") == "plugin" else "")
            or ""
        ).strip()
        if plugin_name and plugin_name in self._disabled_plugin_names(spec):
            base["error"] = f"插件模块被当前隔离策略禁用：{plugin_name}"
            base["summary"] = base["error"]
            return base
        owner = self._subagent_of_node(spec, node)
        owner_provider = (owner.provider_id if owner else "") or ""
        provider_id = (
            owner_provider
            or spec.provider_id
            or await self.context.get_current_chat_provider_id(event.unified_msg_origin)
        )
        lane_tools = (
            owner.enabled_tools if (owner and owner.enabled_tools) else spec.enabled_tools
        )
        worker_spec = worker_spec_for_node(node, allowed_tools=lane_tools)
        lane_role = (owner.role_prompt.strip() if (owner and owner.role_prompt) else "")
        lane_header = (
            f"[子Agent 泳道] {owner.name or owner.sub_agent_id}\n{lane_role}\n\n"
            if owner
            else ""
        )
        system_prompt = (
            f"{spec.system_prompt}\n\n"
            f"{lane_header}"
            "[Agent Lab Parallel Worker]\n"
            f"worker_type={worker_spec.worker_type}\n"
            "你是当前 AstrBot 身份下的并行工作包执行者，不是新的 bot 人设。"
            "只完成本节点分配的工作；不要调用 agent_lab_finish，不要直接决定任务完成。"
            "如需使用工具，只能使用本节点允许的工具或插件来源工具，并遵守审批/白名单。"
        )
        await self._lane_rate_throttle(owner)
        prompt = self._parallel_worker_prompt(task, node, shared_instruction)
        resp = await self.astrbot_bridge.run(
            event, task, self._build_parallel_worker_toolset(spec, node, owner_tools=set(lane_tools)),
            prompt, system_prompt + task_plan_prompt(task),
            max(1, min(int(_cfg(self.config, "parallel_worker_max_steps", 6) or 6), 12)),
            AgentLabRunHooks(self.storage, task.umo, task.task_id, budget_max_tools=0),
            lane=str(node.get("id") or "worker"), provider_id=owner_provider,
        )
        text = (getattr(resp, "completion_text", "") or "").strip()
        try:
            parsed = self._parse_detector_json(text)
        except Exception:
            parsed = {}
        ok = bool(parsed.get("status") in {"completed", "success"} and parsed.get("summary") and parsed.get("evidence"))
        base.update({"ok": ok, "status": "completed" if ok else "blocked",
            "summary": str(parsed.get("summary") or text or "工作包未提交可验证结果。")[:600],
            "details": text[:2200], "evidence": parsed.get("evidence", []),
            "error": "" if ok else "工作包没有明确完成状态与证据，需主Bot检查。"})
        return base

    def _parallel_worker_prompt(
        self,
        task: TaskState,
        node: dict[str, Any],
        shared_instruction: str = "",
    ) -> str:
        worker_spec = worker_spec_for_node(node)
        return "\n".join(
            [
                "执行一个并行工作流节点，输出结构化结果。",
                f"- worker_type: {worker_spec.worker_type}",
                f"- output_schema: {json.dumps(worker_spec.output_schema, ensure_ascii=False)}",
                f"- task_id: {task.task_id}",
                f"- root_goal: {task.root_goal}",
                f"- current_summary: {task.current_summary or '-'}",
                f"- last_progress: {task.last_confirmed_progress or '-'}",
                f"- node_id: {node.get('id') or '-'}",
                f"- title: {node.get('title') or '-'}",
                f"- kind/action: {node.get('kind') or '-'} / {node.get('action') or '-'}",
                f"- instruction: {node.get('instruction') or node.get('description') or '-'}",
                f"- condition: {node.get('condition') or '-'}",
                f"- node_prompt: {node.get('prompt') or '-'}",
                f"- shared_instruction: {shared_instruction or '-'}",
                "",
                '仅输出JSON：{"status":"completed或blocked","summary":"结论","evidence":["证据/工具结果引用"],"risks":[],"next_recommendation":"建议"}。不能把无法完成当成功。',
                "不要修改工作流，不要归档任务；由主 Agent 统一合并、校验和退出。",
            ]
        )

    def _build_parallel_worker_toolset(self, spec: AgentSpec, node: dict[str, Any], owner_tools: "set[str] | None" = None):
        from astrbot.core.agent.tool import ToolSet

        tmgr = self.context.get_llm_tool_manager()
        disabled_plugins = self._disabled_plugin_names(spec)
        toolset = ToolSet()
        kind = str(node.get("kind") or "").strip()
        ref_type = str(node.get("ref_type") or "").strip()
        tool_name = str(node.get("tool_name") or (node.get("ref_id") if ref_type == "tool" else "") or "").strip()
        plugin_name = str(node.get("plugin_name") or (node.get("ref_id") if ref_type == "plugin" else "") or "").strip()

        def tool_allowed_by_profile(name: str) -> bool:
            return self._tool_allowed_by_agent_profile(spec, name)

        def add_if_allowed(tool: Any) -> None:
            name = str(getattr(tool, "name", "") or "")
            if (
                tool
                and tool_allowed_by_profile(name)
                and self._tool_available_for_agent(tool, disabled_plugins)
            ):
                toolset.add_tool(tool)

        if kind == "tool" and tool_name:
            try:
                tool = self.astrbot_bridge.tool(tool_name)
            except Exception:
                tool = None
            add_if_allowed(tool)
            return toolset
        if plugin_name:
            for tool in list(tmgr.func_list):
                if self._tool_plugin_name(tool) == plugin_name:
                    add_if_allowed(tool)
            return toolset
        if kind == "tool":
            allowed = set(spec.enabled_tools or [])
            if owner_tools:
                allowed = allowed & set(owner_tools) if allowed else set(owner_tools)
            for name in allowed:
                if name in {
                    NO_EXTERNAL_TOOLS_SENTINEL,
                    "agent_lab_enter_mode",
                    "agent_lab_tick",
                    "agent_lab_finish",
                    "agent_lab_update_workflow",
                    "agent_lab_run_parallel_workflow",
                }:
                    continue
                try:
                    tool = self.astrbot_bridge.tool(name)
                except Exception:
                    tool = None
                add_if_allowed(tool)
        return toolset

    @staticmethod
    def _parallel_api_payload_json(api_payload: Any) -> tuple[str, str, str]:
        if not isinstance(api_payload, dict):
            return "", "", ""
        query = api_payload.get("query") or api_payload.get("query_json") or {}
        body = api_payload.get("body") if "body" in api_payload else api_payload.get("body_json", None)
        headers = api_payload.get("headers") or api_payload.get("headers_json") or {}
        return (
            query if isinstance(query, str) else json.dumps(query, ensure_ascii=False),
            body if isinstance(body, str) else ("" if body is None else json.dumps(body, ensure_ascii=False)),
            headers if isinstance(headers, str) else json.dumps(headers, ensure_ascii=False),
        )

    @classmethod
    def _normalize_agent_workflow(cls, spec: AgentSpec) -> None:
        raw_nodes = spec.workflow_nodes if isinstance(spec.workflow_nodes, list) else []

        used_ids: set[str] = set()
        id_map: dict[str, str] = {}
        nodes: list[dict[str, Any]] = []
        for index, raw_node in enumerate(raw_nodes):
            if not isinstance(raw_node, dict):
                raw_node = {}
            old_id = str(raw_node.get("id") or "").strip()
            node_id = cls._unique_workflow_id(
                cls._normalize_workflow_id(old_id or f"node_{index + 1}"),
                used_ids,
            )
            if old_id:
                id_map[old_id] = node_id
            used_ids.add(node_id)
            title = str(raw_node.get("title") or node_id).strip() or node_id
            kind = str(raw_node.get("kind") or "state").strip()
            if kind not in WORKFLOW_KINDS:
                kind = "state"
            stage = cls._workflow_stage(raw_node, kind)
            action = str(raw_node.get("action") or "manual").strip() or "manual"
            if action == "note":
                action = "prompt_inject"
            description = str(raw_node.get("description") or "").strip()
            instruction = str(
                raw_node.get("instruction") or description or title
            ).strip()
            normalized = {str(key): value for key, value in raw_node.items()}
            normalized.update(
                {
                    "id": node_id,
                    "title": title[:80],
                    "kind": kind,
                    "stage": stage,
                    "action": action[:80],
                    "description": description[:500],
                    "instruction": instruction[:1000],
                    "x": cls._clamp_int(raw_node.get("x"), -1400, 12000, 70 + index * 260),
                    "y": cls._clamp_int(raw_node.get("y"), -1400, 8000, 120),
                }
            )
            NodeExecutorRegistry.normalize_node_runtime_type(normalized)
            NodeExecutorRegistry.normalize_execution_mode(normalized)
            NodeExecutorRegistry.normalize_port_schema(normalized)
            for schema_key in ("input_schema", "output_schema"):
                schema = cls._workflow_json_object(normalized.get(schema_key))
                if schema:
                    normalized[schema_key] = schema
                elif schema_key in normalized:
                    normalized.pop(schema_key, None)
            required_inputs = cls._clean_string_list(
                normalized.get("required_inputs") or normalized.get("required_input")
            )
            if required_inputs:
                normalized["required_inputs"] = required_inputs
            output_variables = cls._clean_string_list(
                normalized.get("output_variables") or normalized.get("outputs")
            )
            if output_variables:
                normalized["output_variables"] = output_variables
            retry_policy = cls._normalize_retry_policy(normalized.get("retry_policy"))
            if retry_policy:
                normalized["retry_policy"] = retry_policy
            elif "retry_policy" in normalized:
                normalized.pop("retry_policy", None)
            try:
                timeout_seconds = int(normalized.get("timeout_seconds") or 0)
            except Exception:
                timeout_seconds = 0
            if timeout_seconds > 0:
                normalized["timeout_seconds"] = max(1, min(timeout_seconds, 600))
            elif "timeout_seconds" in normalized:
                normalized.pop("timeout_seconds", None)
            for bool_key in ("interrupt_before", "interrupt_after"):
                if bool_key in normalized:
                    normalized[bool_key] = bool(normalized.get(bool_key))
            for key, limit in (
                ("ref_type", 32),
                ("ref_id", 160),
                ("api_id", 160),
                ("api_scope_id", 160),
                ("sub_agent_id", 160),
                ("owner", 160),
                ("plugin_name", 160),
                ("tool_name", 160),
                ("skill_name", 160),
                ("condition", 1000),
                ("route_variable", 160),
                ("variable_name", 160),
                ("output_variable", 160),
                ("payload_variable", 160),
                ("scope_mode", 32),
                ("template_id", 160),
                ("path", 500),
                ("url", 500),
                ("method", 16),
                ("operation", 80),
                ("edit_mode", 32),
                ("permission_profile", 32),
                ("parallel_group", 80),
                ("prompt", 4000),
                ("role_prompt", 4000),
                ("inject_text", 4000),
            ):
                if key in normalized:
                    normalized[key] = str(normalized.get(key) or "").strip()[:limit]
            nodes.append(normalized)

        edges: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str, str, str, str]] = set()
        for raw_edge in spec.workflow_edges if isinstance(spec.workflow_edges, list) else []:
            if not isinstance(raw_edge, dict):
                continue
            start = id_map.get(str(raw_edge.get("from") or "").strip(), str(raw_edge.get("from") or "").strip())
            end = id_map.get(str(raw_edge.get("to") or "").strip(), str(raw_edge.get("to") or "").strip())
            if start not in used_ids or end not in used_ids or start == end:
                continue
            from_port = str(
                raw_edge.get("from_port")
                or raw_edge.get("source_port")
                or raw_edge.get("port")
                or ""
            ).strip().lower()[:80]
            to_port = str(raw_edge.get("to_port") or raw_edge.get("target_port") or "").strip().lower()[:80]
            inferred_type = NodeExecutorRegistry.edge_type_from_port(from_port)
            edge_type = cls._normalize_workflow_edge_type(
                raw_edge.get("edge_type") or raw_edge.get("type") or inferred_type
            )
            condition = str(raw_edge.get("condition") or raw_edge.get("when") or "").strip()[:1000]
            key = (start, end, edge_type, condition, from_port, to_port)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edge = {"from": start, "to": end, "edge_type": edge_type}
            if from_port:
                edge["from_port"] = from_port
            if to_port:
                edge["to_port"] = to_port
            if condition:
                edge["condition"] = condition
            condition_visual = raw_edge.get("condition_visual")
            if isinstance(condition_visual, dict):
                edge["condition_visual"] = condition_visual
            elif isinstance(condition_visual, str) and condition_visual.strip():
                edge["condition_visual"] = condition_visual.strip()[:1000]
            label = str(raw_edge.get("label") or "").strip()
            if label:
                edge["label"] = label[:120]
            route_hint = cls._normalize_workflow_route_hint(raw_edge.get("route_hint"))
            if route_hint:
                edge["route_hint"] = route_hint
            edges.append(edge)
        spec.workflow_nodes = nodes
        spec.workflow_edges = edges
        cls._sync_workflow_trigger_from_nodes(spec)
        cls._sync_workflow_sub_agents(spec)

    @classmethod
    def _sync_workflow_trigger_from_nodes(cls, spec: AgentSpec) -> None:
        trigger = WorkflowTrigger.from_dict(cls._as_plain_dict(getattr(spec, "workflow_trigger", None)))
        original = WorkflowTrigger.from_dict(cls._as_plain_dict(getattr(spec, "workflow_trigger", None)))
        nodes = [node for node in spec.workflow_nodes if isinstance(node, dict)]
        existing_ids = {str(node.get("id") or "") for node in nodes}
        existing_actions = {str(node.get("action") or "").strip() for node in nodes}

        def add_migrated_node(
            action: str,
            title: str,
            defaults: dict[str, Any],
        ) -> None:
            node_id = cls._unique_workflow_id(cls._normalize_workflow_id(action), existing_ids)
            existing_ids.add(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "title": title,
                    "kind": "trigger",
                    "stage": "entry",
                    "action": action,
                    "instruction": defaults.pop("instruction", title),
                    "x": 70,
                    "y": 240 + len(existing_ids) * 48,
                    **defaults,
                }
            )

        original_types = set(original.types or [])
        if "schedule" in original_types and "schedule_trigger" not in existing_actions:
            add_migrated_node(
                "schedule_trigger",
                "复杂定时入口",
                {
                    "instruction": "从旧 workflow_trigger 定时配置迁移而来，只承接 cron 定时入口。",
                    "cron": original.cron,
                    "cron_expressions": list(original.cron_expressions or []),
                    "timezone": original.schedule_timezone,
                    "jitter_seconds": original.schedule_jitter_seconds,
                    "schedule_payload": dict(original.schedule_payload or {}),
                    "output_variable": original.schedule_output_variable,
                },
            )
        if "plugin_event" in original_types and "plugin_event_trigger" not in existing_actions:
            add_migrated_node(
                "plugin_event_trigger",
                "插件事件入口",
                {
                    "instruction": "从旧 workflow_trigger 插件事件配置迁移而来，只承接插件事件入口。",
                    "plugin_sources": list(original.plugin_sources or []),
                    "event_names": list(original.plugin_events or []),
                    "match_mode": original.plugin_match_mode,
                    "payload_variable": original.plugin_payload_variable,
                },
            )
        if "webhook" in original_types and "webhook_trigger" not in existing_actions:
            add_migrated_node(
                "webhook_trigger",
                "Webhook 入口",
                {
                    "instruction": "从旧 workflow_trigger Webhook 配置迁移而来，只承接 Webhook 入口。",
                    "webhook_path": original.webhook_path,
                    "auth_type": original.webhook_auth_type,
                    "credential_id": original.webhook_secret_id,
                },
            )

        actions = {str(node.get("action") or "").strip() for node in nodes}

        message_types = {
            "command",
            "natural",
            "silent_global",
            "message_monitor",
            "keyword",
            "regex",
            "poke",
            "notice",
            "manual_webui",
        }
        types: set[str] = set()

        def params(node: dict[str, Any]) -> dict[str, Any]:
            raw = node.get("params")
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                except Exception:
                    return {}
                return parsed if isinstance(parsed, dict) else {}
            return {}

        for node in nodes:
            action = str(node.get("action") or "").strip()
            node_params = params(node)
            if action == "listen_message":
                node_types = cls._clean_string_list(node.get("trigger_types") or node.get("types"))
                selected = [item for item in node_types if item in message_types]
                if not selected:
                    selected = [item for item in original.types if item in message_types]
                if not selected:
                    selected = ["command"]
                types.update(selected)
                trigger.command_names = cls._clean_string_list(
                    node.get("command_names") or node.get("commands") or original.command_names
                )
                trigger.keywords = cls._clean_string_list(
                    node.get("keywords") or node.get("keyword") or original.keywords
                )
                trigger.regex = cls._clean_string_list(
                    node.get("regex") or node.get("regex_patterns") or original.regex
                )
            elif action == "schedule_trigger":
                types.add("schedule")
                cron_value = (
                    node.get("cron")
                    or node_params.get("cron")
                    or node.get("cron_expression")
                    or original.cron
                )
                trigger.cron = str(cron_value or "").strip()[:120]
                trigger.cron_expressions = cls._clean_string_list(
                    node.get("cron_expressions")
                    or node.get("crons")
                    or ([trigger.cron] if trigger.cron else original.cron_expressions)
                )
                trigger.schedule_timezone = str(
                    node.get("timezone")
                    or node_params.get("timezone")
                    or original.schedule_timezone
                    or ""
                ).strip()[:80]
                jitter = node.get("jitter_seconds", node_params.get("jitter_seconds", original.schedule_jitter_seconds))
                try:
                    trigger.schedule_jitter_seconds = max(0, min(int(jitter or 0), 86400))
                except Exception:
                    trigger.schedule_jitter_seconds = 0
                payload = node.get("schedule_payload") or node_params.get("payload") or original.schedule_payload
                trigger.schedule_payload = payload if isinstance(payload, dict) else {}
                trigger.schedule_output_variable = str(
                    node.get("output_variable")
                    or original.schedule_output_variable
                    or "event.schedule"
                ).strip()[:160] or "event.schedule"
            elif action == "plugin_event_trigger":
                types.add("plugin_event")
                trigger.plugin_sources = cls._clean_string_list(
                    node.get("plugin_sources")
                    or node.get("plugin_name")
                    or node.get("plugin_names")
                    or original.plugin_sources
                )
                trigger.plugin_events = cls._clean_string_list(
                    node.get("event_names")
                    or node.get("plugin_events")
                    or node.get("event_name")
                    or original.plugin_events
                )
                mode = str(node.get("match_mode") or original.plugin_match_mode or "any").strip().lower()
                trigger.plugin_match_mode = mode if mode in {"any", "all"} else "any"
                trigger.plugin_payload_variable = str(
                    node.get("payload_variable")
                    or node.get("output_variable")
                    or original.plugin_payload_variable
                    or "event.payload"
                ).strip()[:160] or "event.payload"
            elif action == "webhook_trigger":
                types.add("webhook")
                trigger.webhook_path = str(
                    node.get("webhook_path")
                    or node.get("path")
                    or node_params.get("path")
                    or original.webhook_path
                    or ""
                ).strip()[:200]
                auth_type = str(
                    node.get("auth_type")
                    or node_params.get("auth_type")
                    or original.webhook_auth_type
                    or "none"
                ).strip().lower()
                trigger.webhook_auth_type = auth_type if auth_type in {"none", "bearer", "header"} else "none"
                trigger.webhook_secret_id = str(
                    node.get("credential_id")
                    or node.get("secret_id")
                    or original.webhook_secret_id
                    or ""
                ).strip()[:160]

        if actions.intersection({"listen_message", "schedule_trigger", "plugin_event_trigger", "webhook_trigger"}):
            trigger.types = list(types) or ["command"]
        spec.workflow_trigger = WorkflowTrigger.from_dict(trigger.to_dict() if hasattr(trigger, "to_dict") else trigger.__dict__)

        for node in nodes:
            action = str(node.get("action") or "").strip()
            if action == "listen_message":
                node.setdefault("trigger_types", [item for item in spec.workflow_trigger.types if item in message_types])
                node.setdefault("command_names", list(spec.workflow_trigger.command_names))
                node.setdefault("keywords", list(spec.workflow_trigger.keywords))
                node.setdefault("regex", list(spec.workflow_trigger.regex))
            elif action == "schedule_trigger":
                node.setdefault("cron", spec.workflow_trigger.cron)
                node.setdefault("timezone", spec.workflow_trigger.schedule_timezone)
                node.setdefault("jitter_seconds", spec.workflow_trigger.schedule_jitter_seconds)
                node.setdefault("schedule_payload", dict(spec.workflow_trigger.schedule_payload))
                node.setdefault("output_variable", spec.workflow_trigger.schedule_output_variable)
            elif action == "plugin_event_trigger":
                node.setdefault("plugin_sources", list(spec.workflow_trigger.plugin_sources))
                node.setdefault("event_names", list(spec.workflow_trigger.plugin_events))
                node.setdefault("match_mode", spec.workflow_trigger.plugin_match_mode)
                node.setdefault("payload_variable", spec.workflow_trigger.plugin_payload_variable)
            elif action == "webhook_trigger":
                node.setdefault("webhook_path", spec.workflow_trigger.webhook_path)
                node.setdefault("auth_type", spec.workflow_trigger.webhook_auth_type)
                node.setdefault("credential_id", spec.workflow_trigger.webhook_secret_id)

    @classmethod
    def _sync_workflow_sub_agents(cls, spec: AgentSpec) -> None:
        existing = {
            str(getattr(item, "sub_agent_id", "") or ""): item
            for item in (getattr(spec, "sub_agents", None) or [])
            if str(getattr(item, "sub_agent_id", "") or "").strip()
        }
        by_name = {
            str(getattr(item, "name", "") or "").strip(): item
            for item in existing.values()
            if str(getattr(item, "name", "") or "").strip()
        }
        merged: dict[str, SubAgentSpec] = dict(existing)
        main_owner_ids: set[str] = set()
        for node in spec.workflow_nodes:
            if node.get("action") != "agent_role":
                continue
            if node.get("main_agent"):
                # 主 Agent 是角色块但不作为可调度子Agent；仅记录其 id 作为合法领地 owner。
                mid = str(node.get("sub_agent_id") or node.get("id") or "").strip()
                if mid:
                    node["sub_agent_id"] = mid
                    main_owner_ids.add(mid)
                continue
            sub_agent_id = str(
                node.get("sub_agent_id")
                or node.get("ref_id")
                or node.get("id")
                or ""
            ).strip()
            name = str(node.get("name") or node.get("title") or "").strip()
            source = existing.get(sub_agent_id) or by_name.get(name) or SubAgentSpec()
            payload = source.to_dict()
            if sub_agent_id:
                payload["sub_agent_id"] = sub_agent_id
            if name:
                payload["name"] = name
            for node_key, spec_key in (
                ("color", "color"),
                ("role_prompt", "role_prompt"),
                ("prompt", "role_prompt"),
                ("provider_id", "provider_id"),
                ("max_concurrency", "max_concurrency"),
                ("rate_per_minute", "rate_per_minute"),
                ("notes", "notes"),
            ):
                if node.get(node_key) not in (None, ""):
                    payload[spec_key] = node.get(node_key)
            if "enabled_tools" in node:
                payload["enabled_tools"] = cls._clean_string_list(node.get("enabled_tools"))
            item = SubAgentSpec.from_dict(payload)
            node["sub_agent_id"] = item.sub_agent_id
            node["ref_type"] = "sub_agent"
            node["ref_id"] = item.sub_agent_id
            node["color"] = item.color
            node["provider_id"] = item.provider_id
            node["max_concurrency"] = item.max_concurrency
            node["rate_per_minute"] = item.rate_per_minute
            if item.role_prompt:
                node["role_prompt"] = item.role_prompt
            merged[item.sub_agent_id] = item

        valid_ids = set(merged.keys()) | set(main_owner_ids)
        members: dict[str, list[str]] = {sub_id: [] for sub_id in merged.keys()}
        for node in spec.workflow_nodes:
            owner = str(node.get("owner") or "").strip()
            node_id = str(node.get("id") or "").strip()
            if owner and owner in valid_ids and node_id and node.get("action") != "agent_role":
                members.setdefault(owner, []).append(node_id)
            elif owner and owner not in valid_ids:
                node.pop("owner", None)
        for sub_id, item in merged.items():
            item.member_node_ids = list(dict.fromkeys(members.get(sub_id, [])))
        spec.sub_agents = list(merged.values())

    @staticmethod
    def _normalize_workflow_id(value: str) -> str:
        value = re.sub(r"\s+", "_", str(value or "").strip())
        value = re.sub(r"[^A-Za-z0-9_-]", "", value)
        return value[:64] or "node"

    @staticmethod
    def _workflow_json_object(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
            except Exception:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _normalize_workflow_edge_type(raw: Any) -> str:
        edge_type = str(raw or "success").strip().lower()
        valid = {
            "success",
            "failed",
            "uncertain",
            "error",
            "retry",
            "timeout",
            "approved",
            "rejected",
            "always",
        }
        return edge_type if edge_type in valid else "success"

    @staticmethod
    def _normalize_workflow_route_hint(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        raw_points = raw.get("points")
        if not isinstance(raw_points, list):
            return {}
        points: list[list[float]] = []
        for item in raw_points[:24]:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                x_raw, y_raw = item[0], item[1]
            elif isinstance(item, dict):
                x_raw, y_raw = item.get("x"), item.get("y")
            else:
                continue
            try:
                x = round(float(x_raw), 1)
                y = round(float(y_raw), 1)
            except Exception:
                continue
            if abs(x) > 100000 or abs(y) > 100000:
                continue
            if not points or points[-1] != [x, y]:
                points.append([x, y])
        if len(points) < 2:
            return {}
        return {"version": 1, "mode": "orthogonal_hint", "points": points}

    @staticmethod
    def _normalize_retry_policy(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str) and raw.strip():
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            return {}
        try:
            max_attempts = max(1, min(int(raw.get("max_attempts") or raw.get("attempts") or 1), 8))
        except Exception:
            max_attempts = 1
        backoff = str(raw.get("backoff") or "none").strip().lower()
        if backoff not in {"none", "linear", "exponential"}:
            backoff = "none"
        retry_on = raw.get("retry_on") if isinstance(raw.get("retry_on"), list) else ["error", "timeout"]
        return {
            "max_attempts": max_attempts,
            "backoff": backoff,
            "retry_on": [str(item).strip() for item in retry_on if str(item).strip()],
        }

    @classmethod
    def _unique_workflow_id(cls, value: str, used_ids: set[str]) -> str:
        root = cls._normalize_workflow_id(value)
        if root not in used_ids:
            return root
        index = 2
        while f"{root}_{index}" in used_ids:
            index += 1
        return f"{root}_{index}"

    @staticmethod
    def _workflow_stage(node: dict[str, Any], kind: str) -> str:
        stage = str(node.get("stage") or "").strip()
        if stage in {"entry", "plan", "execute", "guard", "checkpoint", "archive"}:
            return stage
        text = f"{node.get('id') or ''} {node.get('title') or ''}".lower()
        if "entry" in text or "入口" in text:
            return "entry"
        if "checkpoint" in text or "快照" in text or "状态" in text:
            return "checkpoint"
        if "archive" in text or "归档" in text or "出口" in text:
            return "archive"
        if kind in {"retrieval", "branch"} or "router" in text or "分流" in text:
            return "plan"
        if kind in {"tool", "api", "transform", "subflow"} or "execute" in text or "执行" in text:
            return "execute"
        if kind in {"validation", "loop"} or "校验" in text:
            return "checkpoint"
        if kind in {"notification"}:
            return "archive"
        if kind in {"guard", "human"} or "approval" in text or "heartbeat" in text:
            return "guard"
        return "plan"

    @staticmethod
    def _workflow_default_position(stage: str, index: int) -> tuple[int, int]:
        stage_order = ["entry", "plan", "execute", "guard", "checkpoint", "archive"]
        try:
            stage_index = stage_order.index(stage)
        except ValueError:
            stage_index = 1
        return 70 + stage_index * 560, 110 + (index % 6) * 215

    def _autolayout_workflow(self, spec: AgentSpec) -> None:
        self._normalize_agent_workflow(spec)
        stage_order = ["entry", "plan", "execute", "guard", "checkpoint", "archive"]
        grouped: dict[str, list[dict[str, Any]]] = {stage: [] for stage in stage_order}
        for node in spec.workflow_nodes:
            grouped.setdefault(str(node.get("stage") or "plan"), []).append(node)
        for stage_index, stage in enumerate(stage_order):
            for row_index, node in enumerate(grouped.get(stage, [])):
                node["x"] = 70 + stage_index * 560
                node["y"] = 110 + row_index * 215

    def _workflow_report(self, spec: AgentSpec) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        nodes = [item for item in spec.workflow_nodes if isinstance(item, dict)]
        edges = [item for item in spec.workflow_edges if isinstance(item, dict)]
        node_ids = {str(item.get("id") or "") for item in nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        incoming: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if start in outgoing and end in incoming:
                outgoing[start].append(end)
                incoming[end].append(start)

        issues: list[dict[str, str]] = []

        def add_issue(level: str, code: str, message: str, node_id: str = "") -> None:
            issues.append(
                {
                    "level": level,
                    "code": code,
                    "message": message,
                    "node_id": node_id,
                }
            )

        trigger_actions = {
            "listen_message",
            "schedule_trigger",
            "plugin_event_trigger",
            "webhook_trigger",
        }
        detector_actions = {"match_keyword", "match_regex", "llm_detect", "scope_filter"}
        identity_actions = {
            "credential_ref",
            "cookie_jar",
            "browser_profile",
            "login_flow",
            "session_check",
            "refresh_session",
            "credential_scope",
            "human_login_handoff",
            "revoke_session",
        }
        report_actions = {
            "notify",
            "send_message",
            "send_private_message",
            "send_email",
            "deliver_outbox",
            "write_record",
            "generate_report",
        }
        trigger = WorkflowTrigger.from_dict(self._as_plain_dict(getattr(spec, "workflow_trigger", None)))
        sub_agent_ids = {
            str(getattr(item, "sub_agent_id", "") or "").strip()
            for item in (getattr(spec, "sub_agents", None) or [])
            if str(getattr(item, "sub_agent_id", "") or "").strip()
        }
        owner_counts: dict[str, int] = {sub_id: 0 for sub_id in sub_agent_ids}

        def has_value(node: dict[str, Any], *keys: str) -> bool:
            for key in keys:
                value = node.get(key)
                if value in (None, "", [], {}):
                    continue
                return True
            return False

        def scoped_api_for(node_id: str) -> str:
            for scope_node in nodes:
                if scope_node.get("action") != "api_scope":
                    continue
                api_id = str(scope_node.get("api_id") or scope_node.get("ref_id") or "").strip()
                scope_mode = str(scope_node.get("scope_mode") or "selected").strip().lower()
                scope_ids = self._clean_string_list(
                    scope_node.get("scope_node_ids")
                    or scope_node.get("member_node_ids")
                    or scope_node.get("target_node_ids")
                )
                if scope_ids and node_id in set(scope_ids):
                    return api_id
                if scope_mode in {"all", "global"}:
                    return api_id
            return ""

        entry_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "entry"
            or node.get("kind") == "trigger"
            or node.get("action") in {"summarize_entry", "confirm_entry", *trigger_actions}
        ]
        terminal_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("action") in {"archive", "archive_task", "exit_summary"}
            or (
                node.get("stage") == "archive"
                and node.get("action") not in {"notify", "manual"}
            )
            or node.get("kind") == "report"
            or node.get("action") in report_actions
        ]
        archive_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "archive" or node.get("action") in {"archive", "archive_task", "exit_summary", "notify"}
        ]
        guard_ids = [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "guard" or node.get("kind") in {"guard", "human"}
        ]
        has_approval_gate = any(
            node.get("stage") == "guard"
            or node.get("kind") in {"guard", "human"}
            or node.get("action") in {"request_approval", "wait_user", "handoff"}
            for node in nodes
        )
        action_ids: dict[str, list[str]] = {}
        runtime_type_ids: dict[str, list[str]] = {}
        special_module_ids: dict[str, list[str]] = {}
        port_schemas: dict[str, dict[str, list[str]]] = {}
        executor_nodes: list[str] = []
        react_handoff_nodes: list[str] = []
        node_runtime: dict[str, dict[str, Any]] = {}
        for node in nodes:
            node_id = str(node.get("id") or "")
            action = str(node.get("action") or "")
            runtime_type = NodeExecutorRegistry.runtime_type(node)
            port_schema = NodeExecutorRegistry.port_schema(node)
            special_module = str(node.get("special_module") or "").strip()
            has_executor = self.node_executors.can_execute(node)
            action_ids.setdefault(action, []).append(node_id)
            runtime_type_ids.setdefault(runtime_type, []).append(node_id)
            port_schemas[node_id] = port_schema
            if special_module:
                special_module_ids.setdefault(special_module, []).append(node_id)
            if has_executor:
                executor_nodes.append(node_id)
            if not has_executor or action in {"plan", "manual"} or runtime_type in {"react", "terminal"}:
                react_handoff_nodes.append(node_id)
            node_runtime[node_id] = {
                "runtime_type": runtime_type,
                "action": action,
                "special_module": special_module,
                "port_schema": port_schema,
                "has_executor": has_executor,
                "react_handoff": node_id in react_handoff_nodes,
            }
        if not entry_ids:
            add_issue("error", "missing_entry", "工作流缺少入口节点。")
        if not terminal_ids:
            add_issue("error", "missing_archive", "工作流缺少真正的出口/归档节点，需要 archive 或 exit_summary 动作。")
        if not guard_ids:
            add_issue("warn", "missing_guard", "工作流没有审批或人工闸门，高风险任务可能无法停下确认。")
        if not any(action in action_ids for action in {"summarize_entry", *trigger_actions}):
            add_issue("warn", "missing_entry_summary", "工作流没有入口摘要节点，普通聊天上文可能无法干净压缩成 task_brief。")
        if any(action in action_ids for action in trigger_actions) and not any(
            action in action_ids for action in detector_actions
        ):
            add_issue("warn", "trigger_without_detector", "监听、定时或事件触发工作流建议接入检测器、范围过滤或条件分支。")
        confirmation_actions = {"confirm_entry", "listen_message"}
        if spec.entry_policy.require_confirmation and not any(
            action in action_ids for action in confirmation_actions
        ):
            add_issue("warn", "missing_entry_confirmation", "当前 AgentSpec 要求开启确认，但工作流没有消息监听入口或确认节点来承接确认。")
        isolation_actions = {"restore_isolation", "global_control"}
        if spec.isolation_policy.mode != "off" and not any(
            action in action_ids for action in isolation_actions
        ):
            add_issue("warn", "missing_isolation_snapshot", "隔离模式已开启，但工作流没有全局控制或隔离快照/恢复节点。")
        if not any(action in action_ids for action in {"save_memory", "summarize_memory", "export_task_memory", "promote_memory_candidate"}):
            add_issue("warn", "missing_task_memory", "工作流没有任务记忆节点，续写信息可能只停留在 task_state。")
        if "exit_summary" not in action_ids:
            add_issue("warn", "missing_exit_summary", "工作流没有出口摘要节点，任务成果和可回流记忆可能不完整。")

        reachable: set[str] = set()
        stack = list(entry_ids)
        while stack:
            current = stack.pop()
            if current in reachable:
                continue
            reachable.add(current)
            stack.extend(outgoing.get(current, []))
        for node in nodes:
            node_id = str(node.get("id") or "")
            owner_id = str(node.get("owner") or "").strip()
            if owner_id:
                if owner_id not in sub_agent_ids:
                    add_issue("error", "owner_missing_agent_role", "节点 owner 必须指向存在的 Agent 角色块/子 Agent。", node_id)
                else:
                    owner_counts[owner_id] = owner_counts.get(owner_id, 0) + 1
            if entry_ids and node_id not in reachable:
                add_issue("warn", "unreachable_node", "入口无法到达该节点。", node_id)
            if node_id not in entry_ids and not incoming.get(node_id):
                add_issue("warn", "missing_input", "节点没有输入连线。", node_id)
            if node_id not in terminal_ids and not outgoing.get(node_id):
                add_issue("warn", "missing_output", "非出口节点没有输出连线。", node_id)
            if node_id in terminal_ids and outgoing.get(node_id):
                add_issue("warn", "terminal_has_output", "出口/归档节点通常不应再连到其他节点。", node_id)
            if node.get("kind") in {"branch", "detector"} and len(outgoing.get(node_id, [])) < 2:
                add_issue("warn", "branch_single_path", "分支节点最好至少有两条输出连线。", node_id)
            if node.get("action") == "parallel_branch":
                workers = outgoing.get(node_id, [])
                if len(workers) < 2:
                    add_issue("warn", "parallel_without_workers", "并行 Agent 分支至少需要两个后续工作包。", node_id)
            if node.get("kind") == "detector":
                edge_types = {
                    str(edge.get("edge_type") or "success")
                    for edge in edges
                    if edge.get("from") == node_id
                }
                if not edge_types.intersection({"success", "failed", "uncertain", "error"}):
                    add_issue("warn", "detector_without_result_routes", "检测模块建议显式配置通过/失败/不确定/错误出口。", node_id)
            if node.get("special_module") == "listener":
                if not trigger.enabled:
                    add_issue("warn", "listener_trigger_disabled", "监听模块所在工作流的 workflow_trigger 未启用。", node_id)
                if node.get("action") == "listen_message" and not set(trigger.types or []).intersection({"command", "manual_webui", "silent_global", "message_monitor", "keyword", "regex", "natural", "poke", "notice"}):
                    add_issue("warn", "listener_without_message_trigger", "消息监听模块需要在 workflow_trigger.types 中启用 message_monitor、keyword、regex 或 natural。", node_id)
                if node.get("action") == "listen_message" and has_value(
                    node,
                    "cron",
                    "cron_expression",
                    "cron_expressions",
                    "timezone",
                    "schedule_payload",
                    "jitter_seconds",
                    "plugin_sources",
                    "plugin_events",
                    "event_names",
                    "plugin_name",
                    "webhook_path",
                    "webhook_auth_type",
                    "webhook_secret_id",
                ):
                    add_issue("error", "message_trigger_has_foreign_fields", "消息监听入口不得配置定时、插件事件或 Webhook 字段。", node_id)
                if node.get("action") == "plugin_event_trigger" and not (trigger.plugin_sources or trigger.plugin_events):
                    add_issue("error", "plugin_event_trigger_unbound", "插件事件入口必须绑定插件来源或事件名。", node_id)
                if node.get("action") == "webhook_trigger" and "webhook" not in set(trigger.types or []):
                    add_issue("warn", "webhook_trigger_not_enabled", "Webhook 监听模块需要在 workflow_trigger.types 中启用 webhook。", node_id)
                if node.get("action") == "webhook_trigger" and not trigger.webhook_path:
                    add_issue("warn", "webhook_trigger_without_path", "Webhook 入口建议配置路径，避免任何 webhook 都能命中。", node_id)
                if node.get("action") == "schedule_trigger" and ("schedule" not in set(trigger.types or [])):
                    add_issue("warn", "schedule_trigger_not_enabled", "定时监听模块需要在 workflow_trigger.types 中启用 schedule。", node_id)
                if node.get("action") == "schedule_trigger" and not (trigger.cron or trigger.cron_expressions):
                    add_issue("error", "schedule_trigger_without_cron", "定时入口必须配置 cron。", node_id)
            if node.get("action") == "agent_role":
                role_id = str(node.get("sub_agent_id") or node.get("ref_id") or "").strip()
                if not role_id or role_id not in sub_agent_ids:
                    add_issue("error", "agent_role_not_synced", "Agent 角色块必须能同步为有效子 Agent。", node_id)
            if node.get("action") == "prompt_inject":
                if not incoming.get(node_id):
                    add_issue("error", "prompt_inject_missing_input", "提示注入节点必须有输入连线。", node_id)
                if not outgoing.get(node_id):
                    add_issue("error", "prompt_inject_missing_output", "提示注入节点必须有输出连线。", node_id)
                if not str(node.get("inject_text") or node.get("prompt") or node.get("instruction") or node.get("description") or "").strip():
                    add_issue("error", "prompt_inject_missing_text", "提示注入节点必须配置注入文本。", node_id)
            if node.get("kind") == "loop" or node.get("action") == "retry":
                edge_types = {
                    str(edge.get("edge_type") or "success")
                    for edge in edges
                    if edge.get("from") == node_id
                }
                if not edge_types.intersection({"retry", "failed", "error"}):
                    add_issue("warn", "retry_without_retry_routes", "循环/重试模块建议配置 retry、failed 或 error 出口。", node_id)
                if not edge_types.intersection({"success", "failed"}):
                    add_issue("warn", "loop_without_exit_route", "循环/重试模块建议配置 success 或 failed 出口作为结束点。", node_id)
            if node.get("kind") in {"subflow", "tool", "api"} and node.get("action") in {"manual", ""} and not str(node.get("prompt") or "").strip():
                add_issue("warn", "module_without_prompt", "模块节点建议写入节点提示词或明确动作，否则运行时只能依赖泛化说明。", node_id)
            node_text = " ".join(
                str(node.get(key) or "")
                for key in ("title", "description", "instruction", "prompt", "action", "kind")
            ).lower()
            file_like = bool(
                re.search(
                    r"file|path|document|write|delete|remove|\brm\b|patch|edit|文件|文档|路径|删除|写入|改动",
                    node_text,
                )
            )
            dangerous = bool(
                re.search(
                    r"delete|remove|\brm\b|deploy|write|patch|edit|restart|credential|删除|写入|部署|重启|密钥|覆盖",
                    node_text,
                )
            )
            if file_like and not str(
                node.get("path")
                or node.get("url")
                or node.get("input_variable")
                or node.get("ref_id")
                or ""
            ).strip():
                add_issue("warn", "file_node_without_input", "文件/文档类模块需要写清 path、url 或上游变量。", node_id)
            if dangerous and not has_approval_gate and node.get("stage") != "guard":
                add_issue("warn", "danger_without_approval", "高风险写入/删除/部署动作前建议接入审批模块。", node_id)
            if node.get("action") == "save_memory" and not str(
                node.get("tags") or node.get("memory_tags") or node.get("prompt") or node.get("instruction") or ""
            ).strip():
                add_issue("warn", "memory_without_schema", "任务记忆模块需要写清标签、摘要规则或保存字段。", node_id)
            if node.get("action") in {"llm_prompt", "prompt_transform"}:
                if not str(node.get("prompt") or node.get("instruction") or node.get("user_prompt") or "").strip():
                    add_issue("warn", "prompt_module_without_prompt", "纯提示词模块需要写清局部指令，否则运行时无法稳定变换输入。", node_id)
                if not (node.get("output_schema") or node.get("output_mode") or node.get("format")):
                    add_issue("warn", "prompt_module_without_contract", "纯提示词模块建议配置 output_mode 或 output_schema，避免输出无法接线。", node_id)
            if node.get("action") in identity_actions:
                credential_id = str(node.get("credential_id") or node.get("ref_id") or "").strip()
                provider = str(node.get("provider") or node.get("site") or node.get("domain") or "").strip()
                if node.get("action") in {"credential_ref", "cookie_jar", "browser_profile", "session_check", "refresh_session"} and not (credential_id or provider or node.get("profile_path") or node.get("cookie_ref")):
                    add_issue("warn", "identity_module_unbound", "身份/登录态模块需要绑定 credential_id、站点、cookie_ref 或浏览器 profile。", node_id)
                if credential_id and not self._credential_public_row(credential_id):
                    add_issue("warn", "missing_credential", f"未找到引用的凭证：{credential_id}", node_id)
                if node.get("action") in {"login_flow", "refresh_session"} and "human_login_handoff" not in action_ids:
                    add_issue("warn", "login_without_handoff", "登录/刷新登录态流程建议连接 human_login_handoff，以处理验证码、2FA 或风控验证。", node_id)
                if node.get("action") in {"cookie_jar", "browser_profile", "credential_ref"} and "secret_redaction" not in action_ids:
                    add_issue("warn", "identity_without_redaction", "身份/Cookie/浏览器会话工作流建议加入 secret_redaction，防止报告或归档泄露敏感字段。", node_id)
            if node.get("action") == "api_scope":
                api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
                if not api_id:
                    add_issue("error", "api_scope_unbound", "API 范围块必须绑定有效 API。", node_id)
                else:
                    api_spec = self.storage.get_custom_api(api_id)
                    if not api_spec:
                        add_issue("error", "api_scope_missing_api", f"API 范围块引用的自定义 API 不存在：{api_id}", node_id)
                    elif not api_spec.get("url"):
                        add_issue("error", "api_scope_without_url", f"API 范围块引用的自定义 API 未配置 URL：{api_id}", node_id)
            if node.get("kind") == "api" or node.get("action") == "call_api":
                api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
                inherited_api_id = scoped_api_for(node_id)
                if api_id:
                    api_spec = self.storage.get_custom_api(api_id)
                    if not api_spec:
                        add_issue("error", "missing_api", f"未找到引用的自定义 API：{api_id}", node_id)
                    elif not api_spec.get("url"):
                        add_issue("error", "api_without_url", f"自定义 API 未配置 URL：{api_id}", node_id)
                elif node.get("action") == "call_api" and inherited_api_id:
                    pass
                elif node.get("action") != "api_scope":
                    add_issue("warn", "api_unbound", "API 节点尚未绑定具体自定义 API。", node_id)
            plugin_name = str(node.get("plugin_name") or "").strip()
            if plugin_name:
                plugin = next((item for item in self._plugin_rows() if item.get("name") == plugin_name), None)
                if not plugin:
                    add_issue("warn", "missing_plugin", f"未找到引用的 AstrBot 插件：{plugin_name}", node_id)
                elif not bool(plugin.get("activated", True)):
                    add_issue("warn", "plugin_inactive", f"引用插件当前未启用：{plugin_name}", node_id)
                elif plugin_name in self._disabled_plugin_names(spec):
                    add_issue("warn", "plugin_isolated", f"引用插件会被当前 AgentSpec 隔离策略关闭：{plugin_name}", node_id)
            tool_name = str(node.get("tool_name") or "").strip()
            if tool_name:
                tool = next((item for item in self._tool_rows() if item.get("name") == tool_name), None)
                if not tool:
                    add_issue("warn", "missing_tool", f"未找到引用工具：{tool_name}", node_id)
                elif not bool(tool.get("effective_active", tool.get("active", True))):
                    add_issue("warn", "tool_inactive", f"引用工具当前不可用：{tool_name}", node_id)
                elif (
                    spec.isolation_policy.tool_mode == "whitelist"
                    and spec.enabled_tools
                    and NO_EXTERNAL_TOOLS_SENTINEL not in set(spec.enabled_tools or [])
                    and tool_name not in set(spec.enabled_tools or [])
                ):
                    add_issue("warn", "tool_not_whitelisted", f"引用工具不在当前 AgentSpec 工具白名单中：{tool_name}", node_id)

        node_lookup = {str(item.get("id") or ""): item for item in nodes}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            source_node = node_lookup.get(start) or {}
            target_node = node_lookup.get(end) or {}
            from_port = str(edge.get("from_port") or "").strip()
            to_port = str(edge.get("to_port") or "").strip()
            if from_port:
                outputs = set((port_schemas.get(start) or {}).get("outputs") or [])
                if outputs and from_port not in outputs:
                    add_issue("warn", "edge_from_port_invalid", f"Edge from_port {from_port} is not declared by node {start}.", start)
            if to_port:
                inputs = set((port_schemas.get(end) or {}).get("inputs") or [])
                if inputs and to_port not in inputs:
                    add_issue("warn", "edge_to_port_invalid", f"Edge to_port {to_port} is not declared by node {end}.", end)
            source_schema = self._node_schema(source_node, "output_schema")
            target_schema = self._node_schema(target_node, "input_schema")
            if source_schema and target_schema and not schema_compatible(source_schema, target_schema):
                add_issue(
                    "warn",
                    "schema_incompatible_edge",
                    f"Node schema mismatch: {start} output cannot feed {end} input.",
                    end,
                )

        if entry_ids and terminal_ids and not any(node_id in reachable for node_id in terminal_ids):
            add_issue("error", "archive_unreachable", "入口路径无法到达任何出口/归档节点。")

        errors = sum(1 for item in issues if item["level"] == "error")
        warnings = sum(1 for item in issues if item["level"] == "warn")
        return {
            "valid": errors == 0,
            "errors": errors,
            "warnings": warnings,
            "nodes": len(nodes),
            "edges": len(edges),
            "entry_nodes": entry_ids,
            "archive_nodes": archive_ids,
            "terminal_nodes": terminal_ids,
            "guard_nodes": guard_ids,
            "memory_nodes": [
                node_id
                for action in ("save_memory", "summarize_memory", "export_task_memory", "promote_memory_candidate", "forget_task_memory")
                for node_id in action_ids.get(action, [])
            ],
            "runtime_types": runtime_type_ids,
            "special_modules": special_module_ids,
            "port_schemas": port_schemas,
            "executor_nodes": executor_nodes,
            "react_handoff_nodes": react_handoff_nodes,
            "node_runtime": node_runtime,
            "issues": issues,
        }

    def _workflow_dry_run_report(
        self, spec: AgentSpec, workflow: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._normalize_agent_workflow(spec)
        workflow = workflow or self._workflow_report(spec)
        nodes = [item for item in spec.workflow_nodes if isinstance(item, dict)]
        edges = [item for item in spec.workflow_edges if isinstance(item, dict)]
        node_map = {str(node.get("id") or ""): node for node in nodes}
        outgoing: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        incoming: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        edge_by_start: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_map}
        for edge in edges:
            start = str(edge.get("from") or "")
            end = str(edge.get("to") or "")
            if start in node_map and end in node_map:
                outgoing.setdefault(start, []).append(end)
                incoming.setdefault(end, []).append(start)
                edge_by_start.setdefault(start, []).append(edge)

        entry_ids = list(workflow.get("entry_nodes") or []) or [
            str(node.get("id") or "")
            for node in nodes
            if node.get("stage") == "entry" or node.get("action") in {"summarize_entry", "confirm_entry"}
        ]
        terminal_ids = set(workflow.get("terminal_nodes") or [])
        current = entry_ids[0] if entry_ids else ""
        primary_path: list[str] = []
        visited: set[str] = set()
        while current and current not in visited and len(primary_path) < 80:
            visited.add(current)
            primary_path.append(current)
            if current in terminal_ids:
                break
            candidates = outgoing.get(current, [])
            if not candidates:
                break
            preferred = next(
                (
                    str(edge.get("to") or "")
                    for edge in edge_by_start.get(current, [])
                    if str(edge.get("edge_type") or "success") in {"success", "always", "retry"}
                ),
                "",
            )
            current = preferred if preferred in candidates else candidates[0]

        branch_nodes = [
            node_id
            for node_id, node in node_map.items()
            if node.get("kind") == "branch" or len(outgoing.get(node_id, [])) > 1
        ]
        parallel_nodes = [
            node_id
            for node_id, node in node_map.items()
            if node.get("action") == "parallel_branch"
        ]
        merge_candidates = [
            node_id
            for node_id, inputs in incoming.items()
            if len(inputs) > 1
        ]
        notes: list[dict[str, str]] = []

        def add_note(level: str, message: str, node_id: str = "") -> None:
            notes.append({"level": level, "message": message, "node_id": node_id})

        if not entry_ids:
            add_note("error", "无法预跑：没有入口节点。")
        if not terminal_ids:
            add_note("error", "无法证明能结束：没有出口/归档节点。")
        if primary_path and primary_path[-1] not in terminal_ids:
            add_note("warn", "主路径没有抵达出口模块，请检查断开的连线。", primary_path[-1])
        if parallel_nodes and not merge_candidates:
            add_note("warn", "发现并行分支，但没有明显的多输入汇总节点。", parallel_nodes[0])
        for node_id in branch_nodes:
            if len(outgoing.get(node_id, [])) < 2:
                add_note("warn", "分支/条件节点输出不足，预跑只能走单路径。", node_id)
        for node_id in primary_path:
            node = node_map.get(node_id, {})
            if node.get("kind") == "api" or node.get("action") == "call_api":
                api_id = str(node.get("api_id") or node.get("ref_id") or "").strip()
                add_note("info" if api_id else "warn", f"API 节点绑定：{api_id or '未绑定'}。", node_id)
            if node.get("action") in {"request_approval", "wait_user", "handoff"} or node.get("kind") in {"guard", "human"}:
                add_note("info", "预跑会在这里等待用户确认或审批，不会自动越过。", node_id)
            if node.get("action") == "save_memory":
                add_note("info", "任务记忆节点会写入独立记忆区，退出后可回看/续写。", node_id)

        executable = bool(workflow.get("valid")) and bool(primary_path) and (
            not terminal_ids or primary_path[-1] in terminal_ids
        )
        if not notes:
            add_note("ok", "静态预跑未发现阻塞；真实执行仍会受审批、工具可用性和模型判断影响。")
        return {
            "summary": "静态预跑完成" if executable else "静态预跑发现阻塞",
            "executable": executable,
            "primary_path": primary_path,
            "branch_nodes": branch_nodes,
            "parallel_nodes": parallel_nodes,
            "merge_candidates": merge_candidates,
            "notes": notes,
            "workflow": workflow,
        }
