from __future__ import annotations


class PermissionPolicy:
    """Runtime policy helpers for tool capability and risk checks."""

    @staticmethod
    def tool_allowed_by_agent_profile(spec, tool_name: str, no_external_sentinel: str) -> bool:
        name = str(tool_name or "").strip()
        if not name:
            return False
        if name in {
            no_external_sentinel,
            "agent_lab_enter_mode",
            "agent_lab_tick",
            "agent_lab_finish",
            "agent_lab_update_workflow",
            "agent_lab_run_parallel_workflow",
        }:
            return False
        tool_mode = str(getattr(spec.isolation_policy, "tool_mode", "whitelist") or "whitelist")
        selected_tools = set(spec.enabled_tools or [])
        if tool_mode == "no_external" or no_external_sentinel in selected_tools:
            return False
        return tool_mode == "full" or not selected_tools or name in selected_tools

    @staticmethod
    def permission_allows_tool(node: dict, *, capability: str, risk: str) -> bool:
        profile = str((node or {}).get("permission_profile") or (node or {}).get("profile") or "work").strip()
        if profile == "danger":
            return True
        if risk == "high":
            return False
        if profile == "ordinary":
            return risk == "safe" and capability not in {"shell", "code", "database"}
        if profile == "work":
            return risk in {"safe", "work"} and capability not in {"database"}
        if profile == "code":
            return capability in {"file", "code", "search", "memory", "api", "unknown"} and risk in {"safe", "work"}
        if profile == "web":
            return capability in {"web", "search", "api", "memory", "unknown"} and risk in {"safe", "work"}
        return risk == "safe"

    @staticmethod
    def permission_profiles_for(capability: str, risk: str) -> list[str]:
        if risk == "high":
            return ["danger"]
        profiles = ["work", "danger"]
        if risk == "safe" and capability not in {"code", "database"}:
            profiles.insert(0, "ordinary")
        if capability in {"file", "code", "search", "memory", "api", "unknown"}:
            profiles.append("code")
        if capability in {"web", "search", "api", "memory", "unknown"}:
            profiles.append("web")
        seen: set[str] = set()
        result = []
        for item in profiles:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result
