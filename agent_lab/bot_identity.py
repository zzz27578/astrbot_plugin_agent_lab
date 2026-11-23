"""Resolve the source Bot's configured persona without copying daily history."""
from __future__ import annotations


async def source_persona(context, umo, provider_settings=None):
    manager = getattr(context, "persona_manager", None)
    conversations = getattr(context, "conversation_manager", None)
    if not manager or not conversations:
        return None
    try:
        cid = await conversations.get_curr_conversation_id(umo)
        conversation = await conversations.get_conversation(umo, cid) if cid else None
        _, persona, _, _ = await manager.resolve_selected_persona(
            umo=umo, conversation_persona_id=getattr(conversation, "persona_id", None),
            platform_name=umo.split(":", 1)[0], provider_settings=provider_settings or {})
        return persona
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
