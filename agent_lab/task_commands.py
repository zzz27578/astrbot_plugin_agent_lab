"""Recognise direct administrator controls without matching quoted discussions."""
from __future__ import annotations

import re


def task_command(text):
    text = str(text or "").strip()
    if any(c in text for c in "?？\"'“”「」"):
        return ""
    text = re.sub(r"[\s，,。.!！；;：:]+", "", text)
    text = re.sub(r"^(?:(?:请|麻烦|帮我|现在|立即|马上|先|给我|你))+(?=停止|取消|终止|结束|暂停|恢复|继续|按现状|直接交付)", "", text)
    text = re.sub(r"(?:吧|谢谢|了)$", "", text)
    if re.fullmatch(r"(?:停止|取消|终止|结束)(?:(?:当前|这个|本次|这项)?任务(?:模式)?)?", text) or text == "任务终止":
        return "stop"
    if text in {"按现状交付", "直接交付当前任务", "交付当前成果", "按当前进度交付"}:
        return "deliver"
    if re.fullmatch(r"暂停(?:(?:当前|这个|本次)?任务)?", text) or text == "任务暂停":
        return "pause"
    if text in {"任务继续", "任务重启", "任务恢复", "继续任务", "恢复任务"}:
        return "resume"
    return ""
