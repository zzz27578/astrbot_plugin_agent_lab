from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AgentModule:
    module_id: str
    name: str
    source: str
    description: str
    prompt: str
    links: list[str]
    capabilities: list[str] | None = None
    requires: list[str] | None = None
    settings_schema: dict[str, Any] | None = None
    default_settings: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "name": self.name,
            "source": self.source,
            "description": self.description,
            "prompt": self.prompt,
            "links": self.links,
            "capabilities": self.capabilities or [],
            "requires": self.requires or [],
            "settings_schema": self.settings_schema or {},
            "default_settings": self.default_settings or {},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AgentModule":
        return cls(
            module_id=str(payload.get("module_id") or "").strip(),
            name=str(payload.get("name") or "").strip(),
            source=str(payload.get("source") or "").strip(),
            description=str(payload.get("description") or "").strip(),
            prompt=str(payload.get("prompt") or "").strip(),
            links=[str(item) for item in payload.get("links", []) if str(item).strip()],
            capabilities=[
                str(item) for item in payload.get("capabilities", []) if str(item).strip()
            ],
            requires=[str(item) for item in payload.get("requires", []) if str(item).strip()],
            settings_schema=payload.get("settings_schema") if isinstance(payload.get("settings_schema"), dict) else {},
            default_settings=payload.get("default_settings") if isinstance(payload.get("default_settings"), dict) else {},
        )


DEFAULT_MODULES: dict[str, AgentModule] = {
    "checkpoint_state": AgentModule(
        module_id="checkpoint_state",
        name="Checkpoint State",
        source="LangGraph durable execution / persistence",
        description="每轮任务都落盘，重启或上下文压缩后以状态文件恢复。",
        links=[
            "https://docs.langchain.com/oss/python/langgraph/durable-execution",
            "https://docs.langchain.com/oss/python/langgraph/persistence",
        ],
        prompt=(
            "模块：Checkpoint State。任务状态是唯一真实来源。每轮执行必须记录时间戳、"
            "具体操作、结果、下一步和阻塞点；不得从其他任务继承进度。"
        ),
        settings_schema={
            "type": "object",
            "properties": {
                "max_log_items": {"type": "integer", "description": "任务日志保留条数"},
                "state_format": {"type": "string", "description": "状态快照格式"},
            },
        },
        default_settings={"max_log_items": 80, "state_format": "json+markdown"},
    ),
    "approval_guard": AgentModule(
        module_id="approval_guard",
        name="Approval Guard",
        source="OpenAI Agents guardrails / human-in-the-loop pattern",
        description="危险操作前由 Agent 主动请求审批，而不是撞到工具层才失败。",
        links=[
            "https://openai.github.io/openai-agents-python/guardrails/",
            "https://docs.langchain.com/oss/python/langchain/human-in-the-loop",
        ],
        prompt=(
            "模块：Approval Guard。危险操作前必须先说明动作、原因、影响范围、回滚方案，"
            "并等待用户批准；普通读写和明确授权范围内的工作可直接执行。"
        ),
        settings_schema={
            "type": "object",
            "properties": {
                "require_before": {"type": "array", "description": "必须提前审批的动作类型"},
                "allow_preapproved_scope": {"type": "boolean", "description": "允许用户一次性授权明确范围"},
            },
        },
        default_settings={
            "require_before": ["delete", "deploy", "secret_read", "service_restart"],
            "allow_preapproved_scope": True,
        },
    ),
    "heartbeat_protocol": AgentModule(
        module_id="heartbeat_protocol",
        name="Heartbeat Protocol",
        source="TaskMode heartbeat protocol",
        description="长任务通过 cron basic job 唤醒插件 runner，读档、执行、写档。",
        links=[
            "https://github.com/AstrBotDevs/AstrBot/blob/master/docs/en/use/agent-runner.md",
        ],
        prompt=(
            "模块：Heartbeat Protocol。只有长任务才开心跳。心跳 payload 不携带细节；"
            "醒来先读 task_state，再执行，再保存。重复同一问题三次必须暂停求助。"
        ),
        settings_schema={
            "type": "object",
            "properties": {
                "cron_expression": {"type": "string", "description": "默认心跳 cron"},
                "max_repeated_failures": {"type": "integer", "description": "连续重复失败阈值"},
            },
        },
        default_settings={"cron_expression": "*/5 * * * *", "max_repeated_failures": 3},
    ),
    "memory_gate": AgentModule(
        module_id="memory_gate",
        name="Memory Gate",
        source="Deep Agents / task memory split",
        description="把日常记忆和任务记忆分层，入口摘要进入，出口摘要回流。",
        links=[
            "https://docs.langchain.com/oss/python/deepagents/memory",
        ],
        prompt=(
            "模块：Memory Gate。保持当前 bot 的身份与语气连续，但普通长期记忆不得覆盖 task_state、工具结果和项目事实；"
            "任务结束后只回流稳定有用的记忆候选。"
        ),
        settings_schema={
            "type": "object",
            "properties": {
                "entry_summary_turns": {"type": "integer", "description": "进入任务时摘要最近轮数"},
                "exit_memory_candidates": {"type": "boolean", "description": "结束后生成记忆候选"},
            },
        },
        default_settings={"entry_summary_turns": 24, "exit_memory_candidates": True},
    ),
    "handoff_adapter": AgentModule(
        module_id="handoff_adapter",
        name="Handoff Adapter",
        source="OpenAI Agents handoffs / AstrBot SubAgentOrchestrator",
        description="把子代理/外部 agent 当作可选模块，而不是任务模式主体。",
        links=[
            "https://openai.github.io/openai-agents-python/handoffs/",
        ],
        prompt=(
            "模块：Handoff Adapter。需要专业子任务时可以交给子代理，但主任务状态仍由 Agent Lab 管理；"
            "handoff 结果必须回写 task_state。"
        ),
    ),
    "flow_adapter": AgentModule(
        module_id="flow_adapter",
        name="Flow Adapter",
        source="CrewAI Flows / Microsoft Agent Framework workflows",
        description="为后续可视化工作流预留顺序、条件、审批节点。",
        links=[
            "https://docs.crewai.com/en/concepts/flows",
            "https://learn.microsoft.com/en-us/agent-framework/overview/",
        ],
        prompt=(
            "模块：Flow Adapter。复杂任务可以表示为 Plan -> Execute -> Observe -> Review -> Archive；"
            "第一版使用线性流程，后续可替换为图状工作流。"
        ),
    ),
}


class ModuleRegistry:
    def __init__(self, *module_dirs: Path) -> None:
        self.module_dirs = [Path(item) for item in module_dirs]
        self._modules: dict[str, AgentModule] = {}
        self.reload()

    def reload(self) -> None:
        self._modules = dict(DEFAULT_MODULES)
        packaged = Path(__file__).resolve().parents[1] / "modules"
        for directory in (packaged, *self.module_dirs):
            self.load_dir(directory)

    def load_dir(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in sorted(directory.glob("*.json")):
            try:
                module = AgentModule.from_dict(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
            if module.module_id:
                self._modules[module.module_id] = module

    def list_modules(self) -> list[dict[str, Any]]:
        return [self._modules[module_id].to_dict() for module_id in sorted(self._modules)]

    def get(self, module_id: str) -> AgentModule | None:
        return self._modules.get(module_id)

    def build_prompt(self, module_ids: list[str], settings: dict[str, dict[str, Any]] | None = None) -> str:
        chunks = []
        settings = settings or {}
        for module_id in module_ids:
            module = self.get(module_id)
            if module:
                module_settings = settings.get(module_id) or module.default_settings or {}
                if module_settings:
                    chunks.append(
                        f"{module.prompt}\n配置：{json.dumps(module_settings, ensure_ascii=False, sort_keys=True)}"
                    )
                else:
                    chunks.append(module.prompt)
        if not chunks:
            return ""
        return "[Agent Lab Modules]\n" + "\n".join(f"- {chunk}" for chunk in chunks)

    def save_custom_module(self, payload: dict[str, Any]) -> AgentModule:
        if not self.module_dirs:
            raise ValueError("No custom module directory configured.")
        module = AgentModule.from_dict(payload)
        module.module_id = _normalize_module_id(module.module_id)
        if not module.module_id:
            raise ValueError("module_id is required.")
        if not module.name:
            module.name = module.module_id
        custom_dir = self.module_dirs[0]
        custom_dir.mkdir(parents=True, exist_ok=True)
        path = custom_dir / f"{module.module_id}.json"
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(module.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
        self.reload()
        return self._modules[module.module_id]


def _normalize_module_id(module_id: str) -> str:
    module_id = re.sub(r"\s+", "_", str(module_id or "").strip())
    module_id = re.sub(r"[^A-Za-z0-9_.-]", "", module_id)
    return module_id[:80]
