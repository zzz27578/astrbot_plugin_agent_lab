from __future__ import annotations

import json
from typing import Any

from .models import TaskState
from .prompts import ENTRY_SUMMARY_SYSTEM, EXIT_SUMMARY_SYSTEM


def history_to_text(history: list[dict[str, Any]], max_chars: int = 36000) -> str:
    parts: list[str] = []
    for item in history:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    text_parts.append(str(part.get("text") or part.get("content") or part))
                else:
                    text_parts.append(str(part))
            content = "\n".join(text_parts)
        parts.append(f"{role}: {content}")
    text = "\n".join(parts)
    if len(text) > max_chars:
        return text[-max_chars:]
    return text


class AgentSummarizer:
    def __init__(self, context, config: dict[str, Any] | None = None):
        self.context = context
        self.config = config or {}

    async def summarize_entry(self, event, goal: str, provided_brief: str = "") -> str:
        history = await self._load_history(event)
        prompt = (
            "请将下面会话压缩成 Agent Mode 入口 task_brief。\n\n"
            f"用户当前目标：{goal}\n\n"
            f"会话内容：\n{history_to_text(history)}"
        )
        if provided_brief.strip():
            prompt += f"\n\n用户补充：\n{provided_brief.strip()}"
        return await self._summarize(event, prompt, ENTRY_SUMMARY_SYSTEM, provided_brief)

    async def summarize_exit(self, event, task: TaskState, provided: str = "") -> str:
        prompt = (
            "请将下面 Agent Mode 任务状态压缩成出口归档摘要。\n\n"
            f"{json.dumps(task.to_dict(), ensure_ascii=False, indent=2)}\n\n"
            "请输出：\n"
            "1. 完成/未完成状态。\n"
            "2. 关键进度和修改。\n"
            "3. 遗留问题。\n"
            "4. 可回流长期记忆候选，每条独立列出。\n"
        )
        if provided.strip():
            prompt += f"\n\n用户或工具补充：\n{provided.strip()}"
        return await self._summarize(event, prompt, EXIT_SUMMARY_SYSTEM, provided)

    async def _load_history(self, event) -> list[dict[str, Any]]:
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return []
        try:
            curr_cid = await conv_mgr.get_curr_conversation_id(event.unified_msg_origin)
            if not curr_cid:
                return []
            conv = await conv_mgr.get_conversation(event.unified_msg_origin, curr_cid)
            if not conv:
                return []
            history = json.loads(conv.history or "[]")
            if isinstance(history, list):
                turns = int(self.config.get("entry_summary_turns", 24))
                return history[-turns * 2 :]
        except Exception:
            return []
        return []

    async def _summarize(self, event, prompt: str, system_prompt: str, fallback: str) -> str:
        provider_ids: list[str] = []
        try:
            provider_ids.append(await self.context.get_current_chat_provider_id(event.unified_msg_origin))
        except Exception:
            pass
        fallback_provider = str(self.config.get("fallback_summary_provider_id") or "").strip()
        if fallback_provider and fallback_provider not in provider_ids:
            provider_ids.append(fallback_provider)

        for provider_id in provider_ids:
            if not provider_id:
                continue
            try:
                resp = await self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=prompt,
                    system_prompt=system_prompt,
                )
                text = (getattr(resp, "completion_text", "") or "").strip()
                if text:
                    return text
            except Exception:
                continue
        return fallback.strip() or "自动摘要暂不可用，请根据当前 task_state 继续。"

