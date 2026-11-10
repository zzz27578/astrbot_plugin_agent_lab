"""Dispatch fences around AstrBot's native tool executor.

Approvals authorize one exact invocation. Neither model instructions nor agent
hooks are trusted to enforce the fence. A durable intent is written before the
native executor is entered, including for calls which later time out.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from contextlib import aclosing
from typing import Any

from .harness_store import HarnessConflict


READ_TOOLS = frozenset({"astrbot_file_read_tool", "astrbot_grep_tool"})
REPORT_TOOL = "agent_lab_save_report"
CORE_TOOLS = READ_TOOLS | {
    "astrbot_file_write_tool", "astrbot_file_edit_tool",
    "astrbot_execute_shell", "astrbot_execute_python", "astrbot_execute_ipython",
}


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical_name(tool: Any) -> str:
    api_id = getattr(tool, "harness_api_id", "")
    return f"api:{api_id}" if api_id else str(tool.name)


def native_result_failed(text: str, result: Any) -> bool:
    if bool(getattr(result, "isError", False)) or text.lstrip().lower().startswith(("error:", "error ", "traceback ")):
        return True
    match = re.match(r"Command completed with exit code (-?\d+)", text)
    if match:
        return int(match.group(1)) != 0
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(value, dict):
        return False
    return (value.get("ok") is False or value.get("success") is False
            or value.get("status") in {"failed", "timed_out", "terminated", "output_limited"}
            or (value.get("exit_code") is not None and value["exit_code"] != 0))


class GuardedToolExecutor:
    """Keep the task, plan, role, budget and approval checks at dispatch time."""

    def __init__(self, adapter: Any, task: dict, step: dict, runner: Any = None):
        self.adapter, self.store = adapter, adapter.store
        self.task_id, self.step_id = task["task_id"], step["id"]
        self.plan_version = task["plan_version"]
        self.step_kind = step.get("kind", "agent")
        self.runner = runner
        self.halted = ""
        self.reason = ""
        self.evidence: list[str] = []

    def _halt(self, status: str, reason: str) -> None:
        self.halted, self.reason = status, reason
        if self.runner is not None:
            self.runner.request_stop()

    def _matching_approval(self, task: dict, name: str, arguments: dict, resource: str) -> dict | None:
        for approval in self.store.list_approvals(self.task_id):
            if (approval.get("status") == "approved"
                    and approval.get("plan_version") == self.plan_version
                    and approval.get("step_id") == self.step_id
                    and approval.get("tool_name") == name
                    and approval.get("arguments") == arguments
                    and approval.get("resource_fingerprint", "") == resource):
                return approval
        return None

    async def execute(self, tool: Any, run_context: Any, **tool_args: Any):
        import jsonschema
        from mcp.types import CallToolResult, TextContent
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor

        def failure(message: str):
            return CallToolResult(content=[TextContent(type="text", text=message)], isError=True)

        intent = None
        task = None
        name = ""
        try:
            task = await self.adapter.require_dispatch(self.task_id, self.plan_version, self.step_id)
            if self.halted:
                yield failure(self.reason)
                return
            if task.get("inbox"):
                self._halt("continue", "New instructions arrived; read them before dispatching another tool")
                yield failure(self.reason)
                return
            name = canonical_name(tool)
            current_toolset = self.adapter.build_toolset(task)
            available = next((item for item in current_toolset.tools if canonical_name(item) == name), None)
            if available is None or not getattr(available, "active", True):
                raise HarnessConflict(f"Tool is no longer permitted: {name}")
            # Re-resolve the descriptor so a stale object cannot bypass a reload.
            tool = available
            jsonschema.validate(tool_args, tool.parameters)
            if self.adapter.redact(json.dumps(tool_args, ensure_ascii=False, sort_keys=True)) != json.dumps(tool_args, ensure_ascii=False, sort_keys=True):
                raise HarnessConflict("Do not pass stored secrets in tool arguments; use the registered API credential binding")
            if tool_args.get("background") or tool_args.get("background_task"):
                raise HarnessConflict("Detached tool jobs are not supported; run a bounded foreground call")
            if name == "astrbot_execute_shell":
                requested_timeout = tool_args.get("timeout")
                if (not isinstance(requested_timeout, int) or isinstance(requested_timeout, bool)
                        or not 1 <= requested_timeout <= int(run_context.tool_call_timeout)):
                    raise HarnessConflict("Shell calls must set an explicit timeout within the tool-call timeout; revise the arguments")
            await self.adapter.validate_runtime(task, run_context, tool=tool)
            resource = self.adapter.tool_resource_fingerprint(task, tool)
            approval = self._matching_approval(task, name, tool_args, resource)
            requires_approval = self.adapter.requires_approval(task, tool, tool_args)
            if requires_approval and approval is None:
                self.store.request_approval(self.task_id, {
                    "tool_name": name, "arguments": tool_args, "step_id": self.step_id,
                    "resource_fingerprint": resource,
                    "execution_mode": task["execution_mode"], "workspace": task.get("workspace", ""),
                    "summary": f"Allow one invocation of {name} for this step?",
                })
                self._halt("waiting_approval", f"Awaiting approval for {name}; nothing was executed")
                yield failure(self.reason)
                return
            # Recheck after every await and before the atomic storage fence.
            task = await self.adapter.require_dispatch(self.task_id, self.plan_version, self.step_id)
            key = f"approval:{approval['approval_id']}" if approval else ""
            if self.step_kind == "tool" and not key:
                key = fingerprint([self.plan_version, self.step_id, name, tool_args, resource])
            intent = self.store.record_tool_intent(
                self.task_id, name, tool_args, step_id=self.step_id,
                idempotency_key=key, approval_id=approval["approval_id"] if approval else "",
                resource_fingerprint=resource,
            )
            if intent.get("reused"):
                if intent["status"] != "completed":
                    raise HarnessConflict("This operation already has an unresolved outcome; reconcile it before retrying")
                self.evidence.append(intent["intent_id"])
                yield CallToolResult(content=[TextContent(type="text", text=json.dumps(intent.get("result"), ensure_ascii=False))])
                return
            output: list[str] = []
            errored = False
            truncated = False
            # Native dispatch handles decorated handlers, generators and builtins.
            # The outer timeout also covers MCP and custom API calls.
            timeout = max(1, int(run_context.tool_call_timeout))
            async def collect_results():
                nonlocal errored, truncated
                shell_session = ""
                async with aclosing(FunctionToolExecutor.execute(tool, run_context, **tool_args)) as results:
                    async for result in results:
                        if result is None:
                            continue
                        text_parts = [str(getattr(part, "text", "")) for part in getattr(result, "content", []) if getattr(part, "type", "") == "text"]
                        text = self.adapter.redact("\n".join(text_parts))
                        if not text:
                            text = "Tool returned non-text content; inspect the task artifact before accepting the result."
                        # Keep at most 32k result characters in the model context.
                        room = max(0, 32000 - sum(len(part) for part in output))
                        if room:
                            output.append(text[:room])
                        truncated = truncated or len(text) > room
                        errored = errored or native_result_failed(text, result)
                        if name == "astrbot_execute_shell" and task["execution_mode"] == "direct":
                            try:
                                state = json.loads(text)
                            except (ValueError, TypeError):
                                state = {}
                            if isinstance(state, dict) and state.get("session_id") and not state.get("session_closed"):
                                shell_session = str(state["session_id"])
                if shell_session:
                    from astrbot.core.tools.computer_tools.shell import ShellSessionTool
                    poller = ShellSessionTool()
                    while shell_session:
                        # Polling belongs to the same approved invocation, not a
                        # new model tool call. The outer timeout bounds its life.
                        current = self.adapter._latest(self.task_id)
                        if current["status"] != "running" or current["plan_version"] != self.plan_version or not await self.adapter.authorized(current):
                            raise HarnessConflict("Task changed while the native shell was running")
                        polled = await poller.call(run_context, action="poll", session_id=shell_session, yield_time_ms=1000, max_output_chars=16000)
                        text = self.adapter.redact(str(polled))
                        room = max(0, 32000 - sum(len(part) for part in output))
                        if room:
                            output.append(text[:room])
                        truncated = truncated or len(text) > room
                        errored = errored or native_result_failed(text, None)
                        try:
                            state = json.loads(text)
                        except (ValueError, TypeError) as exc:
                            raise HarnessConflict("Native shell polling did not return a session result") from exc
                        if state.get("session_closed"):
                            shell_session = ""
                            output.append(f"\nFinal native shell status: {state.get('status')}; exit_code={state.get('exit_code')}")
            await asyncio.wait_for(collect_results(), timeout=timeout)
            result_payload = {"text": "\n".join(output), "ok": not errored, "truncated": truncated}
            self.store.record_tool_result(self.task_id, intent["intent_id"], result_payload, "failed" if errored else "completed")
            self.evidence.append(intent["intent_id"])
            intent = None
            # Commit the outcome before handing it back to a cancellable runner.
            yield CallToolResult(content=[TextContent(type="text", text=result_payload["text"] or "Tool returned no text")], isError=errored)
        except asyncio.CancelledError:
            if task and name == "astrbot_execute_shell" and task["execution_mode"] == "direct":
                await self._terminate_task_shells(run_context)
            if intent and not intent.get("reused"):
                self.store.record_tool_result(self.task_id, intent["intent_id"], {"error": "Interrupted; external outcome may be unknown"}, "unknown")
            raise
        except (TimeoutError, asyncio.TimeoutError):
            if task and name == "astrbot_execute_shell" and task["execution_mode"] == "direct":
                await self._terminate_task_shells(run_context)
            if intent and not intent.get("reused"):
                self.store.record_tool_result(self.task_id, intent["intent_id"], {"error": "Timeout; external outcome must be reconciled"}, "unknown")
            self._halt("blocked", "Tool timed out; verify its result before retrying")
            yield failure(self.reason)
        except Exception as exc:
            if task and name == "astrbot_execute_shell" and task["execution_mode"] == "direct":
                await self._terminate_task_shells(run_context)
            message = self.adapter.redact(f"{type(exc).__name__}: {exc}")
            if intent and not intent.get("reused"):
                self.store.record_tool_result(self.task_id, intent["intent_id"], {"error": message}, "unknown")
            self._halt("blocked", message)
            yield failure(message)

    async def _terminate_task_shells(self, run_context: Any) -> None:
        """Cancel only managed processes belonging to this task's private UMO."""
        from astrbot.core.computer.computer_client import get_local_booter
        event = run_context.context.event
        shell = get_local_booter().shell
        identity = {"owner_id": event.unified_msg_origin, "requester_id": event.get_sender_id(), "requester_is_admin": True}
        try:
            sessions = await shell.list_sessions(**identity)
            for session in sessions.get("sessions", []):
                await shell.terminate_session(**identity, session_id=session["session_id"], max_output_chars=1000)
        except Exception:
            # Durable 'unknown' remains the source of truth when cleanup fails.
            self.store.append_event(self.task_id, "tool.cleanup_incomplete", {"step_id": self.step_id, "requires_reconciliation": True})
