"""Detect canvas execution from the task snapshot, without loading defaults."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

NODE_FIELDS = (
    "id", "title", "action", "kind", "stage", "instruction", "prompt", "description",
    "runtime_type", "tool_name", "ref_id", "ref_type", "api_id", "code", "command",
    "sub_agent_id", "params",
)


def canvas_kind(spec) -> Literal["blank", "workflow"]:
    """Keep meaningful legacy nodes whose ids will be supplied by normalization."""
    nodes = spec.get("workflow_nodes") if isinstance(spec, Mapping) else getattr(spec, "workflow_nodes", None)
    return "workflow" if isinstance(nodes, list) and any(
        isinstance(node, Mapping) and any(
            (bool(value.strip()) if isinstance(value, str) else bool(value))
            for key in NODE_FIELDS if (value := node.get(key)) is not None
        )
        for node in nodes
    ) else "blank"


def canvas_enabled(task) -> bool:
    """Require both an opted-in mode and nodes in this task's own snapshot."""
    if task is None:
        return False
    state = (task.workflow_data or {}).get("task_control") or {}
    spec = (task.profile_snapshot or {}).get("agent") or {}
    return state.get("workflow", "none") != "none" and canvas_kind(spec) == "workflow"


def normalize_canvas_mode(task) -> bool:
    """Migrate blank selections; return whether only canvas metadata changed.

    Authorization, checklist steps, versions and snapshot contents are untouched.
    Callers own persistence of the returned change.
    """
    if task is None:
        return False
    state = (task.workflow_data or {}).get("task_control")
    if not isinstance(state, dict) or not state:
        return False
    kind = canvas_kind((task.profile_snapshot or {}).get("agent") or {})
    changed = state.get("canvas_kind") != kind
    state["canvas_kind"] = kind
    workflow = state.get("workflow", "none")
    if kind == "blank" and workflow != "none":
        state.setdefault("requested_workflow", workflow)
        state["workflow"] = "none"
        changed = True
    return changed
