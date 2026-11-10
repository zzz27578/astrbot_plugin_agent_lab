"""Common workflow dispatch policy; keeps original node implementations intact."""
from __future__ import annotations

import asyncio
import hashlib
import json

from .models import ApprovalRequest, new_id, now_iso
from .node_runtime import NodeExecutionResult
from .task_control import control


EXTERNAL_ACTIONS = {"call_api", "http_request", "send_message", "send_private_message", "send_email",
                    "deliver_outbox", "skill_evolution", "login_flow", "revoke_session"}


async def execute_with_policy(owner, ctx):
    """Check once per attempt, then preserve existing retry/edge semantics."""
    owner._require_task_access(ctx.event)
    state = control(ctx.task)
    version = state.get("version", 0)
    if state and (ctx.task.status != "running" or not state.get("approved_version") or state["approved_version"] != version):
        return NodeExecutionResult(ok=False, blocked=True, advance=False, outcome="等待任务计划批准或恢复。")
    action = str(ctx.node.get("action") or "")
    policy = ctx.node.get("retry_policy") or {}
    attempts = max(1, min(int(policy.get("max_attempts") or 1), 8))
    # Unknown external effects are never retried by a generic retry policy.
    if action in EXTERNAL_ACTIONS or action in {"file_operation", "code_exec", "run_tools"}:
        attempts = 1
    timeout = max(0, min(int(ctx.node.get("timeout_seconds") or 0), 600))
    signature = hashlib.sha256(json.dumps([ctx.node, version, state.get("current_step_id"),
        owner.storage.list_custom_apis() if action in {"call_api", "http_request"} else []],
        ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    if action in EXTERNAL_ACTIONS:
        approval = next((row for row in ctx.task.approvals if row.get("status") == "approved" and row.get("call_signature") == signature), None)
        if not approval:
            row = ApprovalRequest(operation=f"画布节点：{ctx.node.get('title') or action}",
                reason=ctx.task.root_goal, impact=json.dumps(ctx.node, ensure_ascii=False), approval_type="tool_call").to_dict()
            row["call_signature"] = signature
            ctx.task.approvals.append(row)
            ctx.task.status = "paused"
            ctx.task.set_wait(wait_reason="need_approval", message="外部操作等待审批", source="node_policy", resume_command=f"/al approve {row['approval_id']}")
            owner.storage.save_task(ctx.task)
            return NodeExecutionResult(ok=False, blocked=True, advance=False, outcome=f"未执行节点，等待审批 {row['approval_id']}")
        approval["status"] = "consumed"
    journaled = action in EXTERNAL_ACTIONS
    record = {"id": new_id("node"), "name": action, "status": "started", "time": now_iso(),
              "step_id": state.get("current_step_id"), "plan_version": version, "arguments": ctx.node}
    if journaled:
        state.setdefault("journal", []).append(record)
    # Cursor/variables live on ctx.task; commit before awaiting any executor.
    owner.storage.save_task(ctx.task)
    for attempt in range(1, attempts + 1):
        try:
            operation = owner.node_executors.execute(ctx)
            result = await asyncio.wait_for(operation, timeout) if timeout else await operation
        except asyncio.CancelledError:
            if journaled:
                record["status"] = "unknown"
                latest = owner.storage.load_active_task(ctx.task.umo)
                if latest and latest.task_id == ctx.task.task_id:
                    rows = control(latest).get("journal", [])
                    for item in rows:
                        if item["id"] == record["id"]: item["status"] = "unknown"
                    latest.status = "paused"
                    owner.storage.save_task(latest)
            raise
        except Exception as exc:
            result = NodeExecutionResult(ok=False, blocked=True, advance=False, status="blocked", outcome=f"{type(exc).__name__}: {exc}")
            if journaled:
                record["status"] = "unknown"
        result.attempts = attempt
        if journaled and record["status"] != "unknown":
            record.update(status="completed" if result.ok and not result.blocked else "failed", result=result.outcome,
                          fingerprint=hashlib.sha256(json.dumps([action, result.data, result.outcome], sort_keys=True, default=str).encode()).hexdigest())
        latest = owner.storage.load_active_task(ctx.task.umo)
        if latest and latest.task_id == ctx.task.task_id:
            for key in ("ticks_used", "nodes_used", "tool_calls_used", "tokens_used"):
                setattr(ctx.task.budget, key, max(getattr(ctx.task.budget, key), getattr(latest.budget, key)))
            ctx.task.token_usage = latest.token_usage
            # User pause/guidance/plan changes outrank an old node snapshot.
            if latest.status != "running" or control(latest).get("version") != version:
                ctx.task.status = latest.status
                ctx.task.wait = latest.wait
                ctx.task.watchdog = latest.watchdog
            current_control = control(latest)
            if journaled:
                for item in current_control.get("journal", []):
                    if item["id"] == record["id"]: item.update(record)
            ctx.task.workflow_data["task_control"] = current_control
            if journaled and record["status"] == "unknown":
                ctx.task.status = "paused"
                ctx.task.next_step = f"核对节点结果 {record['id']} 后再恢复。"
            owner.storage.save_task(ctx.task)
        if result.ok and not result.blocked:
            return result
        if ctx.task.status != "running" or attempt == attempts:
            return result
        if policy.get("backoff") in {"linear", "exponential"}:
            await asyncio.sleep(min(3.0, 0.2 * (attempt if policy["backoff"] == "linear" else 2 ** (attempt - 1))))
    return result
