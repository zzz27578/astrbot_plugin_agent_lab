"""Keep a human decision distinct from the lifetime of its executable grant."""
from .models import now_iso


def close_approvals(task):
    for row in task.approvals:
        status = row.get("status")
        if status == "approved":
            row.setdefault("decision", "approved")
            if row.get("approval_type") in {"task_plan", "finish_override"}:
                row.update(status="consumed", execution_status="applied", consumed_at=now_iso())
            elif row.get("calls"):
                cancelled = False
                for call in row["calls"]:
                    if call.get("status") == "queued":
                        call.update(status="cancelled", cancellation_reason="task_ended")
                        cancelled = True
                row.update(status="expired" if cancelled else "consumed",
                           execution_status="cancelled_before_execution" if cancelled else "dispatched")
            else:
                row["execution_status"] = "task_ended"  # Approval itself remains an approval.
        elif status == "pending":
            row.update(status="expired", execution_status="not_approved", expiration_reason="task_ended")
        elif status in {"consumed", "rejected"}:
            row.setdefault("decision", "approved" if status == "consumed" else "rejected")
