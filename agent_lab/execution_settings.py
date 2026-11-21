"""Project execution defaults and the shared AstrBot runner setting."""
from __future__ import annotations

import asyncio
from copy import deepcopy

from .models import TaskBudget
from .continuity import DEFAULTS as CONTINUITY_DEFAULTS, LIMITS as CONTINUITY_LIMITS

BUDGET_LIMITS = {
    "max_nodes_per_tick": (1, 200), "max_seconds_per_tick": (1, 3600),
    "max_tokens_per_tick": (0, 1_000_000), "max_total_ticks": (0, 100_000),
    "max_total_tool_calls": (0, 100_000), "max_total_tokens": (0, 50_000_000),
}
MODES = {"readonly", "standard", "full"}


def integer(value, low, high):
    text = str(value)
    if not text.isascii() or not text.isdecimal() or len(text) > 10 or not low <= int(text) <= high:
        raise ValueError(f"请输入 {low} 至 {high} 之间的整数。")
    return int(text)


def lines(values, limit=20):
    if not isinstance(values, list) or len(values) > limit:
        raise ValueError(f"请输入至多 {limit} 条规则。")
    if any(not isinstance(value, str) or len(value) > 500 for value in values):
        raise ValueError("每条规则必须是 500 字以内的文本。")
    return list(dict.fromkeys(v.strip() for v in values if v.strip()))


def normalize(payload):
    if not isinstance(payload, dict):
        raise ValueError("项目运行设置必须是对象。")
    mode = payload.get("mode", "standard")
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("请选择有效的权限档位。")
    budget = payload.get("budget", {})
    if not isinstance(budget, dict):
        raise ValueError("任务预算必须是对象。")
    task_prompt = str(payload.get("task_prompt") or "").strip()
    if len(task_prompt) > 4000:
        raise ValueError("任务指引不能超过 4000 字。")
    continuity = payload.get("continuity", {})
    if not isinstance(continuity, dict) or set(continuity) - set(CONTINUITY_LIMITS):
        raise ValueError("请选择有效的阶段交接设置。")
    continuity = {key: integer(continuity.get(key, value), *CONTINUITY_LIMITS[key]) for key, value in CONTINUITY_DEFAULTS.items()}
    return {"mode": mode, "roots": lines(payload.get("roots", [])), "continuity": continuity,
            "warnings": lines(payload.get("warnings", [])), "task_prompt": task_prompt,
            "budget": {key: integer(value, *BUDGET_LIMITS[key]) for key, value in budget.items() if key in BUDGET_LIMITS}}


def native_steps(owner, umo=None):
    cfg = owner.context.get_config(umo=umo) if umo else owner.context.get_config()
    misc = cfg.get("agent_runner", {}).get("config", {}).get("misc", {})
    try:
        return integer(misc.get("max_steps", 128), 1, 10000)
    except ValueError:
        return 128


async def save_native_steps(owner, umo, value):
    value = integer(value, 1, 10000)
    cfg = owner.context.get_config(umo=umo) if umo else owner.context.get_config()
    runner = deepcopy(cfg.get("agent_runner", {}))
    runner.setdefault("config", {}).setdefault("misc", {})["max_steps"] = value
    update = {"agent_runner": runner}
    previous = deepcopy(cfg.get("agent_runner"))
    try:
        if callable(save := getattr(cfg, "save_config_async", None)):
            if await save(update) is False:
                raise ValueError("AstrBot 配置刚被更新，请刷新后重试。")
        elif callable(save := getattr(cfg, "save_config", None)):
            await asyncio.to_thread(save, update)
        else:
            raise ValueError("当前 AstrBot 配置档不支持写入。")
    except Exception:
        if cfg.get("agent_runner") == runner:
            if previous is None:
                cfg.pop("agent_runner", None)
            else:
                cfg["agent_runner"] = previous
        raise
    return value


def effective(owner, project, budget=None):
    settings = normalize(project.get("execution_settings") or {})
    base = budget or TaskBudget()
    settings["budget"] = {key: settings["budget"].get(key, getattr(base, key)) for key in BUDGET_LIMITS}
    settings["native_steps"] = native_steps(owner, project.get("source_umo") or None)
    return settings
