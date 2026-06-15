from __future__ import annotations

"""批次2 自检：用 AST 从 main.py 抽取真实的并发/资源/限速 helper 源码，
在无 astrbot 的沙箱里行为级验证。
- _subagent_of_node 按 owner 解析
- _acquire_resource_locks 同标签串行 / 不同标签可并行
- _lane_rate_throttle 限速间隔
运行：python3 scripts/subagent_concurrency_smoke.py
"""

import ast
import asyncio
import importlib.util
import sys
import textwrap
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# SubAgentSpec（按文件加载 models，绕开 __init__ 的 astrbot 依赖）
_spec = importlib.util.spec_from_file_location("alm_standalone", ROOT / "agent_lab" / "models.py")
_models = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _models
_spec.loader.exec_module(_models)
SubAgentSpec = _models.SubAgentSpec


def _extract_methods(names):
    src = open(ROOT / "main.py", encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name in names:
                    start = item.lineno
                    if item.decorator_list:
                        start = min(start, min(d.lineno for d in item.decorator_list))
                    seg = "".join(lines[start - 1 : item.end_lineno])
                    found[item.name] = textwrap.dedent(seg)
    missing = set(names) - set(found)
    if missing:
        raise SystemExit(f"未在 main.py 抽到方法: {missing}")
    return found


NAMES = ["_subagent_of_node", "_node_resource_tags", "_resource_lock",
         "_acquire_resource_locks", "_lane_rate_throttle"]
segs = _extract_methods(NAMES)

# 组装一个仅含这些真实方法的 Fake 类
import re as _re  # noqa: F401  (helper 源码里用到 re)
import contextlib as _contextlib  # noqa: F401

body = textwrap.indent("\n".join(segs[n] for n in NAMES), "    ")
class_src = (
    "import asyncio, re, time, contextlib\n"
    "from typing import Any\n"
    "class Fake:\n"
    "    def __init__(self):\n"
    "        self._resource_locks = {}\n"
    "        self._lane_rate_state = {}\n"
    + body
)
ns: dict = {}
exec(compile(class_src, "<fake>", "exec"), ns)
Fake = ns["Fake"]


def _assert(c, m):
    if not c:
        raise AssertionError(m)


def test_subagent_of_node():
    f = Fake()

    class Spec:
        sub_agents = [SubAgentSpec(name="A"), SubAgentSpec(name="B")]

    spec = Spec()
    sa = spec.sub_agents[0]
    _assert(f._subagent_of_node(spec, {"owner": sa.sub_agent_id}) is sa, "应按 owner 命中子Agent")
    _assert(f._subagent_of_node(spec, {}) is None, "无 owner → None")
    _assert(f._subagent_of_node(spec, {"owner": "sa_nope"}) is None, "未知 owner → None")
    print("[ok] _subagent_of_node 按 owner 解析")


def test_resource_locks():
    f = Fake()
    state = {"in": 0, "max_same": 0}

    async def worker_same(tag):
        async with f._acquire_resource_locks([tag]):
            state["in"] += 1
            state["max_same"] = max(state["max_same"], state["in"])
            await asyncio.sleep(0.03)
            state["in"] -= 1

    async def run_same():
        await asyncio.gather(*(worker_same("account:github") for _ in range(4)))

    asyncio.run(run_same())
    _assert(state["max_same"] == 1, f"同资源标签必须串行，实测峰值并发={state['max_same']}")

    # 不同标签应能并行
    state2 = {"in": 0, "max": 0}

    async def worker_diff(tag):
        async with f._acquire_resource_locks([tag]):
            state2["in"] += 1
            state2["max"] = max(state2["max"], state2["in"])
            await asyncio.sleep(0.03)
            state2["in"] -= 1

    async def run_diff():
        await asyncio.gather(*(worker_diff(f"file:{i}") for i in range(4)))

    asyncio.run(run_diff())
    _assert(state2["max"] >= 2, f"不同资源标签应可并行，实测峰值={state2['max']}")
    print("[ok] _acquire_resource_locks 同标签串行/异标签并行")


def test_rate_throttle():
    f = Fake()
    owner = SubAgentSpec(name="lane", rate_per_minute=600)  # min_interval=0.1s

    async def run():
        t0 = time.monotonic()
        await f._lane_rate_throttle(owner)  # 首次无等待
        await f._lane_rate_throttle(owner)  # 第二次应至少等 ~0.1s
        await f._lane_rate_throttle(owner)  # 第三次再 ~0.1s
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    _assert(elapsed >= 0.18, f"3 次限速调用应 >= ~0.2s（间隔0.1s×2），实测 {elapsed:.3f}s")

    # rate=0 不限速
    owner0 = SubAgentSpec(name="free", rate_per_minute=0)

    async def run0():
        t0 = time.monotonic()
        for _ in range(5):
            await f._lane_rate_throttle(owner0)
        return time.monotonic() - t0

    _assert(asyncio.run(run0()) < 0.05, "rate=0 不应有等待")
    print("[ok] _lane_rate_throttle 限速间隔 + 0=不限")


def test_node_resource_tags():
    f = Fake()
    _assert(f._node_resource_tags({"resource_tags": "a, b\nc"}) == ["a", "b", "c"], "字符串拆分")
    _assert(f._node_resource_tags({"resource_tags": ["x", " y ", ""]}) == ["x", "y"], "列表清洗")
    _assert(f._node_resource_tags({}) == [], "无标签 → 空")
    print("[ok] _node_resource_tags 解析")


if __name__ == "__main__":
    test_subagent_of_node()
    test_node_resource_tags()
    test_resource_locks()
    test_rate_throttle()
    print("\nALL BATCH-2 CONCURRENCY SMOKE TESTS PASSED")
