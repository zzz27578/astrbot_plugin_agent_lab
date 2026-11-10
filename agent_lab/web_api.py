"""Shared business-error and administrator boundary for both WebUI transports."""
from functools import wraps
from quart import g, jsonify


def admin_api(handler):
    @wraps(handler)
    async def wrapped(*args, **kwargs):
        if not (getattr(g, "username", None) or getattr(g, "agent_lab_web_admin", False)):
            return jsonify({"ok": False, "error": "请先登录 AstrBot 管理员或独立控制台。"}), 403
        try:
            return await handler(*args, **kwargs)
        except (ValueError, KeyError, PermissionError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
    return wrapped
