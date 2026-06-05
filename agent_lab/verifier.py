from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        return str(value or "")


@dataclass
class VerificationResult:
    passed: bool = False
    status: str = "needs_review"
    reason: str = ""
    missing: list[str] = field(default_factory=list)
    next_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentVerifier:
    """Small deterministic verifier for runtime checkpoints.

    This is intentionally conservative. It does not try to prove arbitrary LLM
    claims; it checks for evidence that the runtime can inspect locally and
    returns structured gaps for the agent to resolve.
    """

    PASS_WORDS = ("pass", "passed", "ok", "success", "完成", "通过", "成功")
    FAIL_WORDS = ("fail", "failed", "error", "blocked", "失败", "错误", "阻塞", "未通过")

    def verify_node_result(self, *, node: dict[str, Any], result: Any) -> VerificationResult:
        node_id = str((node or {}).get("id") or "").strip()
        action = str((node or {}).get("action") or "").strip()
        kind = str((node or {}).get("kind") or "").strip()
        ok = bool(getattr(result, "ok", False))
        blocked = bool(getattr(result, "blocked", False))
        status = str(getattr(result, "status", "") or "completed")
        outcome = str(getattr(result, "outcome", "") or getattr(result, "note", "") or "")
        data = getattr(result, "data", None)

        if blocked or status == "blocked" or not ok:
            reason = outcome or f"Node {node_id or '-'} did not complete."
            return VerificationResult(
                passed=False,
                status=status or "blocked",
                reason=reason,
                missing=[reason],
                next_action="revise_plan_or_wait",
            )

        missing: list[str] = []
        if action == "run_tools" or kind == "tool":
            if not isinstance(data, dict) or not (data.get("result") or data.get("tool_name")):
                missing.append("tool_result")
        if action == "call_api" or kind == "api":
            text = _text(data).lower()
            if "status" not in text and "ok" not in text:
                missing.append("api_response_status")
        if action == "validate_output" or kind == "validation":
            if isinstance(data, dict) and data.get("passed") is False:
                missing.append("validation_passed")

        if missing:
            return VerificationResult(
                passed=False,
                status="needs_evidence",
                reason=f"Node {node_id or '-'} lacks verifier evidence: {', '.join(missing)}.",
                missing=missing,
                next_action="collect_evidence",
            )
        return VerificationResult(
            passed=True,
            status=status or "completed",
            reason=outcome or f"Node {node_id or '-'} completed with inspectable evidence.",
            next_action=str(getattr(result, "next_node_id", "") or "continue"),
        )

    def verify_validation_checkpoint(self, task: Any) -> VerificationResult:
        text = "\n".join(
            [
                str(getattr(task, "current_summary", "") or ""),
                str(getattr(task, "last_confirmed_progress", "") or ""),
                str(getattr(task, "last_observation", "") or ""),
            ]
        ).lower()
        failed = any(word in text for word in self.FAIL_WORDS)
        passed = any(word in text for word in self.PASS_WORDS) and not failed
        if passed:
            return VerificationResult(
                passed=True,
                status="passed",
                reason="Validation checkpoint found positive completion evidence.",
                next_action="continue",
            )
        if failed:
            return VerificationResult(
                passed=False,
                status="failed",
                reason="Validation checkpoint found failure or blocking evidence.",
                missing=["passing_observation"],
                next_action="retry_or_pause",
            )
        return VerificationResult(
            passed=False,
            status="ambiguous",
            reason="Validation checkpoint needs explicit pass/fail evidence.",
            missing=["verifiable_result"],
            next_action="ask_react_or_collect_evidence",
        )

    def verify_finish(self, task: Any, *, status: str, final_summary: str) -> VerificationResult:
        if status == "cancelled":
            return VerificationResult(passed=True, status="cancelled", reason="User cancelled task.")
        if getattr(task, "pending_approvals", lambda: [])():
            return VerificationResult(
                passed=False,
                status="finish_blocked",
                reason="存在待审批操作，需先 approve/reject 后才能完成。",
                missing=["pending_approval_resolution"],
                next_action="resolve_approval",
            )
        if not str(final_summary or "").strip():
            return VerificationResult(
                passed=False,
                status="finish_blocked",
                reason="完成任务需要 final_summary。",
                missing=["final_summary"],
                next_action="write_final_summary",
            )
        data = getattr(task, "workflow_data", {}) if isinstance(getattr(task, "workflow_data", {}), dict) else {}
        node_outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        observations = data.get("observations") if isinstance(data.get("observations"), list) else []
        has_evidence = bool(
            getattr(task, "last_confirmed_progress", "")
            or getattr(task, "last_observation", "")
            or node_outputs
            or observations
            or getattr(task, "parallel_runs", [])
        )
        if not has_evidence:
            return VerificationResult(
                passed=False,
                status="finish_blocked",
                reason="缺少 observation/progress 证据，需先推进一轮或写回状态。",
                missing=["runtime_observation"],
                next_action="collect_finish_evidence",
            )
        return VerificationResult(
            passed=True,
            status="completed",
            reason="Finish request has summary and runtime evidence.",
            next_action="archive",
        )

    def verify_worker(self, worker: dict[str, Any]) -> VerificationResult:
        if not worker.get("ok"):
            reason = str(worker.get("error") or worker.get("summary") or "worker blocked")
            return VerificationResult(
                passed=False,
                status=str(worker.get("status") or "blocked"),
                reason=reason,
                missing=[reason],
                next_action="merge_or_retry_worker",
            )
        missing = []
        if not str(worker.get("summary") or "").strip():
            missing.append("summary")
        if not (worker.get("evidence") or worker.get("details") or worker.get("api_id")):
            missing.append("evidence")
        if missing:
            return VerificationResult(
                passed=False,
                status="needs_evidence",
                reason=f"Worker {worker.get('node_id') or '-'} lacks {', '.join(missing)}.",
                missing=missing,
                next_action="collect_worker_evidence",
            )
        return VerificationResult(
            passed=True,
            status=str(worker.get("status") or "completed"),
            reason=str(worker.get("summary") or "worker completed"),
            next_action="merge_parallel_results",
        )
