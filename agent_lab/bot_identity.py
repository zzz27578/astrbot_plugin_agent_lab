"""Resolve the source Bot's configured persona without copying daily history."""
from __future__ import annotations

from copy import deepcopy


async def source_persona(context, umo, provider_settings=None):
    manager = getattr(context, "persona_manager", None)
    conversations = getattr(context, "conversation_manager", None)
    if not manager or not conversations:
        return None
    try:
        cid = await conversations.get_curr_conversation_id(umo)
        conversation = None
        if cid:
            # The host's legacy get_conversation() serializes full history.
            # Identity needs only persona_id; leave daily history in the DB.
            lookup = getattr(getattr(conversations, "db", None), "get_conversation_by_id", None)
            conversation = (await lookup(cid) if lookup
                            else await conversations.get_conversation(umo, cid))
            if conversation and getattr(conversation, "user_id", umo) != umo:
                return None
        if provider_settings is None:
            get_config = getattr(context, "get_config", None)
            provider_settings = (get_config(umo=umo) or {}).get("provider_settings", {}) if get_config else {}
        # UMO starts with the adapter *instance ID*. PersonaManager expects the
        # adapter name here (notably for the WebChat default-persona branch).
        platform_name = str(umo).split(":", 1)[0]
        platforms = getattr(getattr(context, "platform_manager", None), "platform_insts", [])
        for platform in platforms:
            meta = platform.meta()
            if str(meta.id) == platform_name:
                platform_name = meta.name
                break
        _, persona, _, _ = await manager.resolve_selected_persona(
            umo=umo, conversation_persona_id=getattr(conversation, "persona_id", None),
            platform_name=platform_name, provider_settings=provider_settings or {})
        return deepcopy(persona)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def persona_prompt(persona):
    if not isinstance(persona, dict):
        return ""
    prompt = str(persona.get("prompt") or "").strip()
    name = str(persona.get("name") or persona.get("persona_id") or "").strip()
    if not prompt and not name:
        return ""
    return f"[当前 Bot 人设：{name}]\n{prompt}\n面向管理员的进展、请示和交付沿用这个身份的自然语气，保证事实、风险和操作明确，不必套固定公文模板。"


def host_skills_prompt(context, cfg, persona):
    """Use the active AstrBot skill catalog and its configured plugin/persona filters."""
    try:
        from astrbot.core.skills.skill_manager import SkillManager, build_skills_prompt
        manager = SkillManager()
        try:
            skills = manager.list_skills(active_only=True, runtime=cfg.get("computer_use_runtime", "none"))
        except TypeError:
            skills = manager.list_skills(active_only=True)
        try:
            from astrbot.core.astr_main_agent import _filter_skills_for_current_config
            skills = _filter_skills_for_current_config(skills, cfg)
        except ImportError:
            # Older hosts have no plugin skill filter; keep only their active catalog.
            pass
        selected = persona.get("skills") if isinstance(persona, dict) else None
        if selected is not None:
            skills = [skill for skill in skills if skill.name in selected]
        return build_skills_prompt(skills) if skills else ""
    except Exception:
        return ""
