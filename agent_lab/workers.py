from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


WORKER_KINDS = {
    "research": "ResearchWorker",
    "code_read": "CodeReaderWorker",
    "patch": "PatchWorker",
    "test": "TestWorker",
    "review": "ReviewerWorker",
    "summarize": "SummarizerWorker",
    "api": "ApiWorker",
    "tool": "ToolWorker",
    "generic": "GenericWorker",
}


@dataclass
class WorkerSpec:
    worker_type: str = "GenericWorker"
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    allowed_capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def infer_worker_type(node: dict[str, Any]) -> str:
    raw = str((node or {}).get("worker_type") or (node or {}).get("role") or "").strip()
    if raw:
        return WORKER_KINDS.get(raw, raw)
    text = " ".join(
        str((node or {}).get(key) or "").lower()
        for key in ("id", "title", "kind", "action", "instruction", "prompt")
    )
    if any(word in text for word in ("research", "检索", "资料", "查阅", "search")):
        return "ResearchWorker"
    if any(word in text for word in ("read code", "读代码", "代码阅读", "inspect")):
        return "CodeReaderWorker"
    if any(word in text for word in ("patch", "修改", "改代码", "edit")):
        return "PatchWorker"
    if any(word in text for word in ("test", "验证", "校验", "smoke")):
        return "TestWorker"
    if any(word in text for word in ("review", "复核", "审查")):
        return "ReviewerWorker"
    if any(word in text for word in ("summary", "summarize", "总结", "归档")):
        return "SummarizerWorker"
    if str((node or {}).get("kind") or "") == "api" or str((node or {}).get("action") or "") == "call_api":
        return "ApiWorker"
    if str((node or {}).get("kind") or "") == "tool" or str((node or {}).get("action") or "") == "run_tools":
        return "ToolWorker"
    return "GenericWorker"


def worker_spec_for_node(node: dict[str, Any], *, allowed_tools: list[str] | None = None) -> WorkerSpec:
    worker_type = infer_worker_type(node)
    allowed_tools = [str(item) for item in (allowed_tools or []) if str(item).strip()]
    input_schema = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "scope": {"type": "string"},
            "node_id": {"type": "string"},
            "instruction": {"type": "string"},
            "allowed_tools": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["task_id", "node_id", "instruction"],
        "additionalProperties": True,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "evidence": {"type": "array"},
            "risks": {"type": "array"},
            "next_recommendation": {"type": "string"},
            "status": {"type": "string"},
        },
        "required": ["summary", "evidence", "risks", "next_recommendation"],
        "additionalProperties": True,
    }
    capabilities = []
    if worker_type in {"ResearchWorker", "CodeReaderWorker"}:
        capabilities.extend(["file.read", "file.search", "memory.read"])
    if worker_type == "PatchWorker":
        capabilities.extend(["file.read", "file.write", "shell.run"])
    if worker_type == "TestWorker":
        capabilities.extend(["shell.run", "tool.call"])
    if worker_type == "ApiWorker":
        capabilities.append("api.call")
    if worker_type == "ToolWorker":
        capabilities.append("tool.call")
    if not capabilities:
        capabilities.append("llm.reason")
    return WorkerSpec(
        worker_type=worker_type,
        input_schema=input_schema,
        output_schema=output_schema,
        allowed_capabilities=capabilities,
    )


def normalize_worker_output(worker: dict[str, Any]) -> dict[str, Any]:
    payload = dict(worker or {})
    summary = str(payload.get("summary") or payload.get("error") or payload.get("details") or "").strip()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
    if not evidence:
        if payload.get("details"):
            evidence = [{"kind": "details", "text": str(payload.get("details"))[:1600]}]
        elif payload.get("api_id"):
            evidence = [{"kind": "api", "api_id": payload.get("api_id"), "status": payload.get("status")}]
    risks = payload.get("risks") if isinstance(payload.get("risks"), list) else []
    if payload.get("error") and not risks:
        risks = [str(payload.get("error"))]
    payload["summary"] = summary or "worker finished"
    payload["evidence"] = evidence
    payload["risks"] = risks
    payload["next_recommendation"] = str(
        payload.get("next_recommendation")
        or ("merge_parallel_results" if payload.get("ok") else "retry_or_escalate")
    )
    return payload
