"""One-time tool ingress formatting; committed messages are never rewritten."""
from __future__ import annotations

MAX_INLINE_BYTES = 32768


def tool_output(text: str, path, max_bytes: int = MAX_INLINE_BYTES) -> str:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text
    visible = data[:max_bytes].decode("utf-8", errors="ignore")
    boundary = visible.rfind("\n")
    if boundary > len(visible) * .8:
        visible = visible[:boundary + 1]
    return (visible + f"\n[输出共 {len(text)} 字符 / {len(data)} 字节；此处显示前 {len(visible)} 字符。"
            f"完整原文：{path}。需要后文时用宿主文件读取工具按行读取这个文件。]")
