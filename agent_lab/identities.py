"""Safe multi-bot display identities: platform instance ID, never adapter type.

Selecting a display scope never changes AstrBot's active provider, Persona or
administrator role. Actual execution stays bound to the task's source UMO.
"""
from __future__ import annotations


def source_platform(umo: str) -> str:
    parts = str(umo or "").split(":", 2)
    return parts[0] if len(parts) == 3 and all(parts) else ""


def identity_rows(owner, projects):
    manager = owner.context.platform_manager
    # AstrBot also loads internal adapters (e.g. WebChat). Only show instances
    # explicitly present and enabled in its real robot settings.
    configured = getattr(manager, "platforms_config", None)
    if configured is None:
        configured = (owner._context_config() or {}).get("platform", [])
    configured = {str(item.get("id")): item for item in configured or []
                  if isinstance(item, dict) and item.get("id") and item.get("enable", False)}
    rows = {}
    for platform in getattr(manager, "platform_insts", []):
        try:
            meta = platform.meta()
            cfg = configured.get(str(meta.id))
            if cfg is None:
                continue
            identifier = str(meta.id or cfg.get("id") or "")
            if not identifier:
                continue
            stats = platform.get_stats() if callable(getattr(platform, "get_stats", None)) else {}
            rows[identifier] = {"platform_id": identifier,
                "label": str(cfg.get("name") or cfg.get("display_name") or meta.adapter_display_name or meta.name or identifier),
                "platform_type": str(meta.name), "status": str(stats.get("status") or "unknown"),
                "known": True, "sessions": []}
        except (AttributeError, TypeError, ValueError):
            continue
    for project in projects:
        umo = str(project.get("source_umo") or "")
        identifier = source_platform(umo) or str(project.get("platform_id") or "")
        if identifier not in rows:
            continue
        row = rows[identifier]
        if source_platform(umo) and not any(item["umo"] == umo for item in row["sessions"]):
            _, kind, target = umo.split(":", 2)
            cfg = owner._context_config(umo) or {}
            persona = cfg.get("agent_runner", {}).get("config", {}).get("persona", {}).get("persona_id", "")
            label = {"FriendMessage": "私聊", "GroupMessage": "群聊"}.get(kind, kind)
            row["sessions"].append({"umo": umo, "label": label + " · " + target,
                                    "persona": str(persona or "沿用会话配置")})
    return sorted(rows.values(), key=lambda row: (not row["known"], row["label"], row["platform_id"]))
