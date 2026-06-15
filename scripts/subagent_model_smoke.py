from __future__ import annotations

"""批次0 自检：SubAgentSpec / AgentSpec.sub_agents / node.owner / TaskState blackboard。

运行：python3 scripts/subagent_model_smoke.py
直接按文件加载 models.py，绕开 agent_lab/__init__.py（它会 import astrbot 运行时）。
"""

from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "agent_lab_models_standalone", ROOT / "agent_lab" / "models.py"
)
_models = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _models  # dataclass 解析需要模块在 sys.modules
_spec.loader.exec_module(_models)
AgentSpec = _models.AgentSpec
TaskState = _models.TaskState
SubAgentSpec = _models.SubAgentSpec


def _assert(cond, msg):
    if not cond:
        raise AssertionError(msg)


def test_subagent_clean():
    sa = SubAgentSpec.from_dict({
        "name": "x" * 200,
        "color": "not-a-color",
        "provider_id": "  openai_main  ",
        "enabled_tools": "tool_a, tool_b\ntool_a",
        "max_concurrency": 99,
        "rate_per_minute": -5,
        "member_node_ids": ["n1", "n1", " n2 ", ""],
        "notes": "y" * 999,
    })
    _assert(len(sa.name) == 80, "name 应截断到 80")
    _assert(sa.color == "#5b8def", f"非法颜色应回退默认: {sa.color}")
    _assert(sa.provider_id == "openai_main", "provider_id 应 strip")
    _assert(sa.enabled_tools == ["tool_a", "tool_b"], f"工具拆分去重: {sa.enabled_tools}")
    _assert(sa.max_concurrency == 6, "并发上限应夹到 6")
    _assert(sa.rate_per_minute == 0, "负限速应夹到 0")
    _assert(sa.member_node_ids == ["n1", "n2"], f"成员去重去空: {sa.member_node_ids}")
    _assert(len(sa.notes) == 500, "notes 应截断到 500")
    _assert(sa.sub_agent_id.startswith("sa_"), "应自动生成 sub_agent_id")
    _assert(SubAgentSpec.from_dict({"color": "#AbCdEf"}).color == "#AbCdEf", "合法 hex 应保留")
    print("[ok] SubAgentSpec 清洗")


def test_agentspec_roundtrip():
    spec = AgentSpec(name="测试方案")
    sa = SubAgentSpec(name="检索泳道", color="#11aa33", provider_id="cheap_model", max_concurrency=3)
    spec.sub_agents = [sa]
    for node in spec.workflow_nodes:
        if node.get("id") in ("memory_recall", "plan"):
            node["owner"] = sa.sub_agent_id
    raw = spec.to_dict()
    _assert(isinstance(raw["sub_agents"], list) and isinstance(raw["sub_agents"][0], dict),
            "to_dict 应把 sub_agents 转成 dict 列表")
    back = AgentSpec.from_dict(raw)
    _assert(len(back.sub_agents) == 1, "round-trip 后 sub_agents 数量不变")
    _assert(isinstance(back.sub_agents[0], SubAgentSpec), "round-trip 后应为 SubAgentSpec 实例")
    _assert(back.sub_agents[0].name == "检索泳道", "子Agent 名字保留")
    _assert(back.sub_agents[0].provider_id == "cheap_model", "子Agent provider 保留")
    owners = {n.get("id"): n.get("owner") for n in back.workflow_nodes if n.get("owner")}
    _assert(owners.get("memory_recall") == sa.sub_agent_id, "节点 owner 保留")
    _assert(owners.get("plan") == sa.sub_agent_id, "节点 owner 保留")
    print("[ok] AgentSpec round-trip（sub_agents + node.owner 不丢）")


def test_legacy_agentspec():
    legacy = {
        "agent_id": "agent_legacy",
        "name": "老方案",
        "workflow_nodes": [
            {"id": "entry", "title": "入口", "kind": "state", "stage": "entry", "action": "summarize_entry"},
            {"id": "plan", "title": "计划", "kind": "state", "stage": "plan", "action": "plan"},
        ],
        "workflow_edges": [{"from": "entry", "to": "plan"}],
    }
    back = AgentSpec.from_dict(legacy)
    _assert(back.sub_agents == [], "老方案 sub_agents 应为空")
    _assert(all("owner" not in n for n in back.workflow_nodes), "老方案节点不应凭空多出 owner")
    _assert(back.name == "老方案", "老方案其它字段照常加载")
    print("[ok] 老方案零迁移加载")


def test_blackboard():
    task = TaskState(root_goal="g")
    aid = task.post_assignment("sa_1", "去查 A", resource_tags=["account:github"])
    _assert(aid.startswith("asg_"), "应返回 assign_id")
    task.post_report("sa_1", "查到了", assign_id=aid, evidence="e", risks="r", next_step="n")
    task.post_message("sa_1", "注意限频", sender="orchestrator")
    task.post_decision("继续", basis="证据充分", next_step="执行")
    bb = task.workflow_data["blackboard"]
    _assert(len(bb["assignments"]) == 1 and bb["assignments"][0]["resource_tags"] == ["account:github"], "assignment 写入")
    _assert(len(bb["reports"]) == 1 and bb["reports"][0]["next"] == "n", "report 写入")
    _assert(bb["mailbox"]["sa_1"][0]["text"] == "注意限频", "mailbox 写入")
    _assert(len(bb["decisions"]) == 1, "decision 写入")
    for i in range(120):
        task.post_report("sa_1", f"r{i}")
    _assert(len(task.workflow_data["blackboard"]["reports"]) == 80, "reports 应截断到 80")
    for i in range(60):
        task.post_message("sa_1", f"m{i}")
    _assert(len(task.workflow_data["blackboard"]["mailbox"]["sa_1"]) == 40, "mailbox 每人应截断到 40")
    print("[ok] blackboard 写入 + 截断")


def test_legacy_taskstate_blackboard():
    legacy = {
        "task_id": "task_legacy",
        "root_goal": "g",
        "workflow_data": {"node_outputs": {}, "variables": {}},
    }
    task = TaskState.from_dict(legacy)
    _assert("blackboard" not in task.workflow_data, "加载老任务时不应凭空补 blackboard（惰性）")
    task.post_assignment("sa_x", "活")
    _assert(task.workflow_data["blackboard"]["assignments"][0]["sub_agent_id"] == "sa_x", "惰性建 blackboard 成功")
    raw = task.to_dict()
    back = TaskState.from_dict(raw)
    _assert(back.workflow_data["blackboard"]["assignments"][0]["sub_agent_id"] == "sa_x", "TaskState round-trip 保留 blackboard")
    print("[ok] 老任务惰性 blackboard + TaskState round-trip")


if __name__ == "__main__":
    test_subagent_clean()
    test_agentspec_roundtrip()
    test_legacy_agentspec()
    test_blackboard()
    test_legacy_taskstate_blackboard()
    print("\nALL BATCH-0 SMOKE TESTS PASSED")
