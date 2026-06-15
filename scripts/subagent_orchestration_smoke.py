from __future__ import annotations

"""批次3 自检：AST 抽取 main.py 里 5 个协同执行器的真实源码（dispatch/collect/
message/summarize），用真实 TaskState + NodeExecutionResult 跑黑板读写断言。
debate 复用既有 _execute_debate_validation_node，不在此重复测。
运行：python3 scripts/subagent_orchestration_smoke.py
"""

import ast
import asyncio
import importlib.util
import json  # noqa: F401 (executor 源码用到)
import re  # noqa: F401
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(modname, relpath):
    spec = importlib.util.spec_from_file_location(modname, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


_models = _load("alm_models_std", "agent_lab/models.py")
_nr = _load("alm_noderuntime_std", "agent_lab/node_runtime.py")
SubAgentSpec = _models.SubAgentSpec
TaskState = _models.TaskState
NodeExecutionResult = _nr.NodeExecutionResult
NodeExecutionContext = _nr.NodeExecutionContext


def _extract(names):
    src = open(ROOT / "main.py", encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for it in node.body:
                if isinstance(it, (ast.FunctionDef, ast.AsyncFunctionDef)) and it.name in names:
                    start = it.lineno
                    if it.decorator_list:
                        start = min(start, min(d.lineno for d in it.decorator_list))
                    out[it.name] = textwrap.dedent("".join(lines[start - 1 : it.end_lineno]))
    miss = set(names) - set(out)
    if miss:
        raise SystemExit(f"未抽到执行器: {miss}")
    return out


EXEC_NAMES = [
    "_execute_dispatch_node",
    "_execute_collect_report_node",
    "_execute_agent_message_node",
    "_execute_summarize_decision_node",
]
segs = _extract(EXEC_NAMES)

helpers = '''    def _single_next(self, outgoing):
        return outgoing[0] if len(outgoing) == 1 else ""
    def _compact_text(self, text, limit):
        return str(text)[:limit]
    def _resolve_workflow_template(self, task, value):
        return value
    def _node_json_value(self, task, node, *keys):
        for k in keys:
            if k in node:
                return node[k]
        return None
    def _subagent_of_node(self, spec, node):
        oid = str((node or {}).get("owner") or "").strip()
        for sa in getattr(spec, "sub_agents", []) or []:
            if getattr(sa, "sub_agent_id", "") == oid:
                return sa
        return None
'''
class_src = "class Fake:\n" + helpers + textwrap.indent("\n".join(segs[n] for n in EXEC_NAMES), "    ")
g = {"NodeExecutionResult": NodeExecutionResult, "json": json, "re": re, "Any": object}
exec(compile(class_src, "<execs>", "exec"), g)
Fake = g["Fake"]


class Spec:
    def __init__(self, subs, nodes):
        self.sub_agents = subs
        self.workflow_nodes = nodes


def _ctx(task, spec, node, outgoing):
    return NodeExecutionContext(
        event=None, task=task, spec=spec, node=node, outgoing=outgoing,
        next_candidates=[], reason="test",
    )


def _assert(c, m):
    if not c:
        raise AssertionError(m)


def test_dispatch():
    f = Fake()
    task = TaskState(root_goal="g")
    spec = Spec([], [])
    node = {
        "id": "d1",
        "assignments": [
            {"sub_agent_id": "sa_a", "instruction": "查 A", "resource_tags": "account:x, file:y"},
            {"target": "sa_b", "task": "查 B"},
            "裸字符串任务",
        ],
    }
    res = asyncio.run(f._execute_dispatch_node(_ctx(task, spec, node, ["next"])))
    bb = task.workflow_data["blackboard"]
    _assert(len(bb["assignments"]) == 3, f"应派发3条, got {len(bb['assignments'])}")
    _assert(bb["assignments"][0]["sub_agent_id"] == "sa_a", "目标解析")
    _assert(bb["assignments"][0]["resource_tags"] == ["account:x", "file:y"], "资源标签字符串拆分")
    _assert(bb["assignments"][1]["sub_agent_id"] == "sa_b", "target 别名解析")
    _assert(res.next_node_id == "next" and res.advance and res.data["route"] == "success", "路由")
    print("[ok] dispatch_tasks 写 assignments + 资源标签")


def test_collect_report():
    f = Fake()
    task = TaskState(root_goal="g")
    sa = SubAgentSpec(name="检索")
    spec = Spec([sa], [{"id": "w1", "owner": sa.sub_agent_id}, {"id": "w2"}])
    task.parallel_runs = [{
        "workers": [
            {"node_id": "w1", "ok": True, "summary": "w1 完成", "details": "细节1"},
            {"node_id": "w2", "ok": False, "error": "w2 失败"},
        ]
    }]
    res = asyncio.run(f._execute_collect_report_node(_ctx(task, spec, {"id": "c1"}, ["next"])))
    reports = task.workflow_data["blackboard"]["reports"]
    _assert(len(reports) == 2, f"应汇 2 份, got {len(reports)}")
    by = {r["sub_agent_id"]: r for r in reports}
    _assert(sa.sub_agent_id in by, "owner 节点应按 sub_agent_id 归集")
    _assert(by[sa.sub_agent_id]["summary"] == "w1 完成", "汇报内容")
    _assert("w2" in by and by["w2"]["risks"], "失败 worker 记风险")
    _assert(res.data["route"] == "success", "路由")
    print("[ok] collect_report 按 owner 汇 reports")


def test_agent_message():
    f = Fake()
    task = TaskState(root_goal="g")
    spec = Spec([], [])
    res = asyncio.run(f._execute_agent_message_node(
        _ctx(task, spec, {"id": "m1", "target_sub_agent": "sa_a", "message": "注意限频"}, ["next"])))
    _assert(task.workflow_data["blackboard"]["mailbox"]["sa_a"][0]["text"] == "注意限频", "投递信箱")
    _assert(res.data["route"] == "success", "成功路由")
    # 缺目标 → blocked
    res2 = asyncio.run(f._execute_agent_message_node(_ctx(task, spec, {"id": "m2", "message": "x"}, ["next"])))
    _assert(res2.ok is False and res2.data["route"] == "failed", "缺目标应 blocked/failed")
    print("[ok] agent_message 投信箱 + 缺目标兜底")


def test_summarize_decision():
    f = Fake()
    task = TaskState(root_goal="g")
    spec = Spec([], [])
    task.post_assignment("sa_a", "活1")
    task.post_report("sa_a", "做完了一半")
    node = {"id": "s1", "next_step": "继续执行第二步"}
    res = asyncio.run(f._execute_summarize_decision_node(_ctx(task, spec, node, ["next"])))
    decisions = task.workflow_data["blackboard"]["decisions"]
    _assert(len(decisions) == 1, "应写 1 条决策")
    _assert(task.next_step == "继续执行第二步", "next_step 应被写回 task")
    _assert("reports=1" in decisions[0]["basis"], f"决策依据应含统计, got {decisions[0]['basis'][:60]}")
    _assert(res.data["route"] == "success", "路由")
    print("[ok] summarize_decision 读黑板写决策 + next_step")


if __name__ == "__main__":
    test_dispatch()
    test_collect_report()
    test_agent_message()
    test_summarize_decision()
    print("\nALL BATCH-3 ORCHESTRATION SMOKE TESTS PASSED")
