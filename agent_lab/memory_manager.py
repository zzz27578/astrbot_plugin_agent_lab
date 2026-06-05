from __future__ import annotations

from typing import Any


class MemoryManager:
    """Evidence-linked task memory workflow.

    Storage owns persistence and normalization. This manager owns transitions:
    candidate -> accepted/rejected, with evidence kept beside every entry.
    """

    def __init__(self, storage: Any) -> None:
        self.storage = storage

    def create_candidate(
        self,
        *,
        text: str,
        source_task_id: str = "",
        source_umo: str = "",
        kind: str = "memory_candidate",
        tags: list[str] | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.storage.save_memory_entry(
            {
                "text": text,
                "source_task_id": source_task_id,
                "source_umo": source_umo,
                "status": "candidate",
                "kind": kind,
                "layer": "candidate_memory",
                "tags": tags or ["task", "candidate", "private"],
                "expose_to_normal": False,
                "evidence": self._evidence(evidence, action="candidate"),
            }
        )

    def accept(
        self,
        memory_id: str,
        *,
        reviewer: str = "",
        reason: str = "",
        expose_to_normal: bool = True,
    ) -> dict[str, Any] | None:
        entry = self.get(memory_id)
        if not entry:
            return None
        evidence = self._evidence(entry.get("evidence"), action="accepted", reviewer=reviewer, reason=reason)
        entry["status"] = "accepted"
        entry["layer"] = "accepted_memory"
        entry["kind"] = entry.get("kind") or "accepted_memory"
        entry["expose_to_normal"] = expose_to_normal
        entry["evidence"] = evidence
        tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        entry["tags"] = self._merge_tags(tags, ["accepted"])
        return self.storage.save_memory_entry(entry)

    def reject(self, memory_id: str, *, reviewer: str = "", reason: str = "") -> dict[str, Any] | None:
        entry = self.get(memory_id)
        if not entry:
            return None
        evidence = self._evidence(entry.get("evidence"), action="rejected", reviewer=reviewer, reason=reason)
        entry["status"] = "rejected"
        entry["layer"] = "candidate_memory"
        entry["expose_to_normal"] = False
        entry["evidence"] = evidence
        tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        entry["tags"] = self._merge_tags(tags, ["rejected"])
        return self.storage.save_memory_entry(entry)

    def get(self, memory_id: str) -> dict[str, Any] | None:
        needle = str(memory_id or "").strip()
        if not needle:
            return None
        for item in self.storage.list_memory_entries():
            if item.get("memory_id") == needle:
                return dict(item)
        return None

    def candidates_for_task(self, task_id: str) -> list[dict[str, Any]]:
        return [
            item
            for item in self.storage.list_memory_entries()
            if item.get("source_task_id") == task_id and item.get("status") == "candidate"
        ]

    @staticmethod
    def _merge_tags(existing: list[Any], extra: list[str]) -> list[str]:
        seen: set[str] = set()
        result = []
        for item in [*existing, *extra]:
            tag = str(item or "").strip()
            if tag and tag not in seen:
                seen.add(tag)
                result.append(tag)
        return result

    @staticmethod
    def _evidence(
        evidence: dict[str, Any] | None,
        *,
        action: str,
        reviewer: str = "",
        reason: str = "",
    ) -> dict[str, Any]:
        payload = dict(evidence or {})
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        history.append(
            {
                "action": action,
                "reviewer": reviewer,
                "reason": reason,
            }
        )
        payload["history"] = history[-20:]
        if reviewer:
            payload["reviewer"] = reviewer
        if reason:
            payload["review_reason"] = reason
        return payload

    def count_by_status(self, source_task_id: str = "") -> dict[str, int]:
        """Return counts grouped by status (candidate, accepted, rejected)."""
        counts: dict[str, int] = {}
        for item in self.storage.list_memory_entries():
            if source_task_id and item.get("source_task_id") != source_task_id:
                continue
            status = str(item.get("status") or "candidate")
            counts[status] = counts.get(status, 0) + 1
        return counts

    def list_accepted(self, *, tags: list[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
        """Return accepted memory entries, optionally filtered by tags."""
        rows = []
        for item in self.storage.list_memory_entries():
            if str(item.get("status") or "") != "accepted":
                continue
            if tags:
                item_tags = set(str(t) for t in (item.get("tags") or []))
                if not any(t in item_tags for t in tags):
                    continue
            rows.append(dict(item))
        return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)[:limit]

    def prune_stale_candidates(self, *, max_age_days: int = 7) -> int:
        """Delete candidate entries older than max_age_days to prevent bloat."""
        import datetime
        from .models import now_iso

        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=max_age_days)
        pruned = 0
        for item in list(self.storage.list_memory_entries()):
            if str(item.get("status") or "") != "candidate":
                continue
            created = item.get("created_at") or item.get("updated_at") or ""
            if not created:
                continue
            try:
                t = datetime.datetime.fromisoformat(created)
                if t.tzinfo is None:
                    t = t.replace(tzinfo=datetime.timezone.utc)
                if t < cutoff:
                    self.storage.delete_memory_entry(item.get("memory_id", ""))
                    pruned += 1
            except Exception:
                continue
        return pruned
