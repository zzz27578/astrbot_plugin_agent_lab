from __future__ import annotations

import json
import re
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
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        if state.get("steps") and all(step.get("status") == "completed" for step in state["steps"]):
            missing = self._plan_evidence_gaps(task)
            return VerificationResult(passed=not missing, status="needs_evidence" if missing else "passed",
                                      reason="任务步骤仍需补齐有效执行证据。" if missing else "全部步骤已有匹配的成功工具证据。",
                                      missing=missing, next_action="collect_evidence" if missing else "continue")
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
        state = data.get("task_control", {})
        if state.get("steps"):
            missing = self._plan_evidence_gaps(task)
            missing.extend(self._delivery_gaps(task, final_summary))
            return VerificationResult(passed=not missing, status="needs_evidence" if missing else "completed",
                reason="请补齐真实执行、验证或交付说明。" if missing else "批准步骤已完成，交付与真实执行、验证记录一致。",
                missing=missing, next_action="collect_finish_evidence" if missing else "archive")
        node_outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        observations = data.get("observations") if isinstance(data.get("observations"), list) else []
        reports = data.get("reports") if isinstance(data.get("reports"), list) else []
        records = data.get("records") if isinstance(data.get("records"), list) else []
        has_evidence = bool(
            getattr(task, "last_confirmed_progress", "")
            or getattr(task, "last_observation", "")
            or node_outputs
            or observations
            or reports
            or records
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
        missing_conditions = self.missing_completion_conditions(task, final_summary=final_summary)
        if missing_conditions:
            return VerificationResult(
                passed=False,
                status="finish_blocked",
                reason="Finish request lacks evidence for completion conditions.",
                missing=missing_conditions,
                next_action="collect_completion_evidence",
            )
        return VerificationResult(
            passed=True,
            status="completed",
            reason="Finish request has summary and runtime evidence.",
            next_action="archive",
        )

    def missing_completion_conditions(self, task: Any, *, final_summary: str = "") -> list[str]:
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        if state.get("steps"):
            return self._plan_evidence_gaps(task)
        evidence_text = self._finish_evidence_text(task, final_summary=final_summary)
        missing: list[str] = []
        for condition in getattr(task, "completion_conditions", []) or []:
            condition_text = str(condition or "").strip()
            if not condition_text or self._condition_is_finish_boundary(condition_text):
                continue
            if not self._condition_has_evidence(condition_text, evidence_text):
                missing.append(condition_text)
        return missing

    @staticmethod
    def _record_succeeded(row):
        if row.get("status") != "completed" or row.get("isError") or row.get("ok") is False:
            return False
        # Reading an error log or a JSON fixture with ok=false is a successful
        # read. Only executable tool outputs carry process-result semantics.
        name = str(row.get("name", "")).lower()
        if name == "report" or any(part in name for part in ("file_read", "read_file", "grep", "search", "list_directory")):
            return True
        text = _text(row.get("result", ""))
        try:
            result = json.loads(text)
        except (ValueError, TypeError):
            result = {}
        for data in (row, result if isinstance(result, dict) else {}):
            if data.get("ok") is False or data.get("isError") or any(data.get(key, 0) not in (0, None) for key in ("exit_code", "returncode")):
                return False
        return not re.search(r"(?:exit[_ ]code|returncode)\s*[:=]\s*-?[1-9]\d*|^Traceback \(most recent call last\)", text, re.I | re.M)

    @classmethod
    def journal_records(cls, task):
        """Successful current records, including legacy saved reports."""
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        authority = state.get("authorization_version", state.get("approved_version", 0))
        revisions = {s["id"]: s.get("revision", 0) for s in state.get("steps", [])}
        return [row for row in state.get("journal", [])
                if cls._record_succeeded(row)
                and row.get("authorization_version", row.get("plan_version")) == authority
                and row.get("step_revision", 0) == revisions.get(row.get("step_id"), row.get("step_revision", 0))]

    @classmethod
    def execution_records(cls, task):
        """Model reports and controller calls cannot stand in for actual runs."""
        return [row for row in cls.journal_records(task) if row.get("name") and row["name"] != "report"
                and not row["name"].startswith(("agent_lab_", "task_"))]

    @classmethod
    def link_step_evidence(cls, task):
        """Persist links derived from the journal, without asking for IDs."""
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        records = cls.journal_records(task)
        for step in state.get("steps", []):
            step["evidence"] = [r["id"] for r in records if r.get("id") and r.get("step_id") == step["id"]]

    @classmethod
    def _plan_evidence_gaps(cls, task):
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        journal = state.get("journal", [])
        missing = []
        if not state.get("approved_version") or state.get("approved_version") != state.get("version"):
            missing.append("当前计划尚未批准")
        for step in state.get("steps", []):
            if step.get("status") != "completed":
                missing.append(f"{step.get('title', step['id'])}：尚未完成")
        # Splitting/reordering a checklist does not invalidate actual work. The
        # finish boundary checks task execution, not a citation on every item.
        if not cls.execution_records(task):
            missing.append("尚无当前授权下的成功执行记录；总结或手填记录ID不能代替执行")
        if any(row.get("status") in {"started", "unknown"} for row in journal):
            missing.append("存在执行中或结果未知的操作，需先核对")
        return missing

    @staticmethod
    def _is_verification(row):
        name = str(row.get("name", "")).lower()
        if any(part in name for part in ("file_read", "file_write", "file_edit", "read_file", "write_file", "edit_file", "grep", "search")):
            return False
        if row.get("kind") in {"validation", "verification"} or re.search(r"(?:test|verify|validat|lint|compile)", name):
            return True
        if not any(part in name for part in ("execute", "shell", "python", "run_command", "exec_command")):
            return False
        args = row.get("arguments", {})
        command = "\n".join(str(args.get(key, "")) for key in ("command", "cmd", "code", "script"))
        return bool(re.search(r"(?:pytest|unittest|py_compile|compileall|assert\b|\b(?:test|check|typecheck|verify|validate|smoke|lint|ruff|mypy|tsc)\b|(?:test|check|verify|validate|smoke)[_\w-]*\.(?:py|js|sh|ps1)|--(?:check|self-test|selftest))", command, re.I))

    @classmethod
    def _delivery_gaps(cls, task, summary):
        state = (getattr(task, "workflow_data", {}) or {}).get("task_control", {})
        journal = state.get("journal", [])
        valid = cls.execution_records(task)
        missing, changed, last_write = [], [], -1
        valid_objects = {id(row) for row in valid}
        for index, row in enumerate(journal):
            if id(row) not in valid_objects:
                continue
            name = row["name"].lower()
            if any(word in name for word in ("file_write", "file_edit", "write_file", "edit_file", "apply_patch")):
                last_write = index
                args = row.get("arguments", {})
                changed.extend(str(args[key]) for key in ("path", "file_path", "filepath", "filename", "file") if args.get(key))
        summary_normal = summary.replace("\\", "/").lower()
        for path in dict.fromkeys(changed):
            if path.replace("\\", "/").rsplit("/", 1)[-1].lower() not in summary_normal:
                missing.append(f"交付说明缺少改动文件：{path}")
        verification_needed = last_write >= 0 or bool(re.search(
            r"测试|自检|验证命令|编译|\b(?:tests?|pytest|unittest|lint|compile)\b",
            " ".join(getattr(task, "completion_conditions", []) or []), re.I))
        verification_needed |= bool(re.search(
            r"(?:测试|验证|自检|编译|检查)[^。\n]{0,30}(?:通过|成功)|\b(?:tests?|checks?|validation)\b[^.\n]{0,40}\b(?:pass\w*|success\w*)\b",
            summary, re.I))
        if verification_needed:
            checks = [row for row in journal[last_write+1:] if cls._is_verification(row)]
            # A later retry supersedes a failed invocation of the same command.
            latest = {}
            for row in checks:
                key = (row.get("name"), json.dumps(row.get("arguments", {}), ensure_ascii=False, sort_keys=True))
                latest[key] = row
            if not any(id(row) in valid_objects for row in latest.values()):
                missing.append("缺少最后改动之后成功执行的验证记录")
            if any(not cls._record_succeeded(row) for row in latest.values()):
                missing.append("存在尚未通过的验证，请修复并重跑后交付")
            if not re.search(r"验证|测试|自检|编译|检查|\b(?:test|pass|check|validat|lint|compil)\w*", summary, re.I):
                missing.append("交付说明需写明实际验证方式与结果")
        return missing

    def _finish_evidence_text(self, task: Any, *, final_summary: str = "") -> str:
        data = getattr(task, "workflow_data", {}) if isinstance(getattr(task, "workflow_data", {}), dict) else {}
        node_outputs = data.get("node_outputs") if isinstance(data.get("node_outputs"), dict) else {}
        observations = data.get("observations") if isinstance(data.get("observations"), list) else []
        reports = data.get("reports") if isinstance(data.get("reports"), list) else []
        records = data.get("records") if isinstance(data.get("records"), list) else []
        structured_markers: list[str] = []
        if node_outputs or observations or getattr(task, "parallel_runs", []):
            structured_markers.append('运行证据 observation evidence 验证记录')
        if reports:
            structured_markers.append('结构化报告 report 已生成报告')
        if records:
            structured_markers.append('审计记录 record')
        parts = [
            final_summary,
            getattr(task, "current_summary", ""),
            getattr(task, "last_confirmed_progress", ""),
            getattr(task, "last_observation", ""),
            getattr(task, "exit_summary", ""),
            node_outputs,
            observations,
            reports,
            records,
            structured_markers,
            getattr(task, "parallel_runs", []),
            getattr(task, "progress_log", []),
            getattr(task, "state_snapshots", []),
            [lane.get("summary", "") for lane in data.get("task_control", {}).get("continuity", {}).get("lanes", {}).values()
             if isinstance(lane, dict)],
            [dict(summary=s.get("summary", ""), evidence=s.get("evidence", []))
             for s in data.get("task_control", {}).get("steps", []) if s.get("status") == "completed"],
            [dict(id=r.get("id"), status=r.get("status"), result=r.get("result", ""))
             for r in data.get("task_control", {}).get("journal", []) if r.get("status") == "completed"],
        ]
        return "\n".join(_text(part) for part in parts if part)

    @staticmethod
    def _condition_is_finish_boundary(condition: str) -> bool:
        text = str(condition or "").strip().lower()
        if not text:
            return True
        boundary_words = (
            "archive",
            "archived",
            "user acceptance",
            "user accepted",
            "user confirm",
            "user approval",
            "workflow automation route completed",
            "automation route completed",
            "工作流自动化完成",
            "归档",
            "存档",
            "用户验收",
            "用户确认",
            "用户同意",
            "明确完成",
        )
        return any(word in text for word in boundary_words)

    def _condition_has_evidence(self, condition: str, evidence_text: str) -> bool:
        condition_norm = self._normalize(condition)
        evidence_norm = self._normalize(evidence_text)
        if not condition_norm:
            return True
        if condition_norm in evidence_norm:
            return True
        tokens = self._condition_tokens(condition_norm)
        if not tokens:
            return True
        matched = [token for token in tokens if token in evidence_norm]
        if len(tokens) <= 4:
            return len(matched) == len(tokens)
        required = max(4, int(len(tokens) * 0.7))
        return len(matched) >= required

    @staticmethod
    def _normalize(text: Any) -> str:
        return " ".join(str(text or "").lower().split())

    @staticmethod
    def _condition_tokens(text: str) -> list[str]:
        import re

        stop_words = {
            "the", "and", "or", "a", "an", "is", "are", "be", "to", "of", "for", "with",
            "must", "should", "done", "complete", "completed", "finish", "finished", "pass",
            "passed", "success", "successful",
            '通过', '完成', '必须', '应该', '需要', '已经', '已', '进行', '提供', '生成', '输出', '确认',
        }
        concept_words = (
            '证据', '报告', '测试', '验证', '归档', '总结', '风险', '改动', '成果', '部署', '文档', '审计', '记录', '验收', '批准',
        )
        normalized = re.sub(r"[，。；、和及与或]+", " ", str(text or ""))
        raw_tokens = re.findall(r"[a-z0-9_./-]{3,}|[\u4e00-\u9fff]{2,}", normalized.lower())
        tokens: list[str] = []
        for raw in raw_tokens:
            cleaned = raw.strip("._-/")
            cleaned = re.sub(r"^(需要|必须|应该|已经|已|请|完成|进行|提供|生成|输出|确认)+", "", cleaned)
            if cleaned and cleaned not in stop_words:
                tokens.append(cleaned[:80])
        matched_concepts = [word for word in concept_words if word in text]
        if matched_concepts:
            tokens = matched_concepts
        seen: set[str] = set()
        result: list[str] = []
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            result.append(token)
        return result[:20]

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


    def verify_merge(
        self,
        workers: list[dict[str, Any]],
        *,
        branch_node_id: str = "",
        merge_node_id: str = "",
    ) -> VerificationResult:
        """Verify that parallel worker results are complete enough to merge.

        Checks:
          - At least one worker succeeded.
          - Failed workers have recorded errors.
          - All workers have a summary and evidence.
        Returns a structured result with missing items and next action."""
        if not workers:
            return VerificationResult(
                passed=False,
                status="merge_skipped",
                reason="No parallel workers to merge.",
                missing=["parallel_workers"],
                next_action="skip_merge",
            )
        ok_count = sum(1 for w in workers if w.get("ok"))
        total = len(workers)
        missing_items: list[str] = []
        for w in workers:
            node_id = str(w.get("node_id") or "?")
            if not w.get("ok"):
                reason = str(w.get("error") or w.get("summary") or "unknown error")
                missing_items.append(f"{node_id}: {reason}")
                continue
            if not str(w.get("summary") or "").strip():
                missing_items.append(f"{node_id}: missing summary")
            if not (w.get("evidence") or w.get("details") or w.get("output_schema")):
                missing_items.append(f"{node_id}: missing evidence/details")

        if ok_count == 0:
            return VerificationResult(
                passed=False,
                status="merge_blocked",
                reason=f"All {total} parallel workers failed.",
                missing=missing_items[:10],
                next_action="retry_or_replan",
            )
        if ok_count < total:
            return VerificationResult(
                passed=False,
                status="merge_partial",
                reason=f"{ok_count}/{total} workers succeeded, {total - ok_count} failed.",
                missing=missing_items[:10],
                next_action="merge_with_warnings",
            )
        if missing_items:
            return VerificationResult(
                passed=False,
                status="merge_incomplete",
                reason=f"{len(missing_items)} worker(s) missing evidence.",
                missing=missing_items[:10],
                next_action="merge_with_caveats",
            )
        return VerificationResult(
            passed=True,
            status="merge_complete",
            reason=f"All {total} workers completed with evidence.",
            next_action="advance_to_merge_node",
        )
