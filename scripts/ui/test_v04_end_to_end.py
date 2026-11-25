"""Offline v0.4 acceptance: real bridge/compaction, files and Python processes.

Run: python scripts/ui/test_v04_end_to_end.py
The report is regenerated even on failure. No live Bot, network model or billing
measurements are involved. The deterministic provider is a context-driven policy,
not a scripted list of responses: it cannot access the workspace or fixture.

Integration contract for the bridge/continuity owners:
* AstrBotBridge.run/invoke retain their public signatures and use the host runner,
  executor and provider boundaries; only those external boundaries are replaced.
* TaskContinuity.compact archives raw history and returns ordinary message dicts.
* A stage change triggers one summary call, preserving complete recent groups.
* Tool ingress exposes full output through a real path in its 32 KiB notice.
No compatibility shim for context_views/read_cache or alternate implementation
is provided here: incomplete production integration must fail this suite.
"""
from __future__ import annotations

import asyncio
import ast
import hashlib
import importlib
import json
import platform
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid4, uuid5


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/validation/v0.4.0-scenarios.json"
PACKAGE = "v04_acceptance_agent_lab"
REQUEST = "V04_REQUEST "
RESULT = "V04_RESULT "
MEMORY = "V04_MEMORY "
CONTROL_NAMES = {"task_plan", "task_progress", "task_ask", "task_approve", "task_finish"}
SCENARIOS = []


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def wire_bytes(value):
    # Preserve dictionary order as supplied: canonical sorting would hide a
    # change to the actual serialized provider prefix.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def module(name):
    # Import real plugin modules without running the AstrBot plugin initializer.
    if PACKAGE not in sys.modules:
        package = types.ModuleType(PACKAGE)
        package.__path__ = [str(ROOT / "agent_lab")]
        sys.modules[PACKAGE] = package
    return importlib.import_module(PACKAGE + "." + name)


def scan_context(messages):
    """Extract only observations actually visible in this provider request."""
    request, facts = None, []
    for row in messages:
        content = str(row.get("content", ""))
        contents = [content]
        if content.startswith("[Agent Lab 阶段交接记录]\n"):
            handoff = json.loads(content.partition("\n")[2])
            contents.append(handoff.get("handoff", ""))
        for line in "\n".join(contents).splitlines():
            if line.startswith(REQUEST):
                request = json.loads(line[len(REQUEST):])
            elif line.startswith(MEMORY):
                note = json.loads(line[len(MEMORY):])
                request = note.get("request") or request
                facts.extend(note.get("facts", []))
        if content.startswith(RESULT):
            header, _, body = content.partition("\n")
            fact = json.loads(header[len(RESULT):])
            fact["body"] = body
            facts.append(fact)
    return request, facts


def source_block(text, symbol):
    # Exact original text, including its indentation and newline, comes from a
    # real file observation. Neither the old value nor offset is in the policy.
    match = re.search(r"^def " + re.escape(symbol) + r"\(value\):\n    return value \+ (-?\d+)\n", text, re.M)
    return match.group(0) if match else ""


class ContextPolicy:
    """Pure state policy. No filesystem, counters or hidden fixture decisions."""

    @staticmethod
    def decide(messages):
        request, facts = scan_context(messages)
        if request is None:
            return {"kind": "blocked", "reason": "request is absent from actual context"}
        reads = [f for f in facts if f.get("kind") == "read"]
        validations = [f for f in facts if f.get("kind") == "verify"]
        if validations:
            verified = validations[-1]
            if verified.get("exit_code") == 0 and verified.get("body", "").strip() == request["receipt"]:
                return {"kind": "finish", "receipt": verified["body"].strip(),
                        "changed_paths": [] if request["operation"] == "research" else [request["path"]]}
            return {"kind": "blocked", "reason": "actual subprocess verification failed"}
        if request["operation"] == "research":
            observations = {}
            for read in reads:
                for line in read["body"].splitlines():
                    if line.startswith("# OBSERVATION "):
                        item = json.loads(line[len("# OBSERVATION "):])
                        observations[item["key"]] = item["value"]
            missing = set(request["keys"]) - observations.keys()
            if not missing:
                return {"kind": "verify", "script": request["verifier"],
                        "answer": sum(observations[k] for k in request["keys"])}
            start = max([r["end_line"] for r in reads if r["path"] == request["source"]] or [0]) + 1
            return {"kind": "read", "path": request["source"], "start_line": start, "end_line": start + 799}
        mutations = [f for f in facts if f.get("kind") in {"edit", "create", "append", "delete"}]
        if mutations:
            if not mutations[-1].get("ok"):
                return {"kind": "blocked", "reason": "exact mutation failed"}
            if request.get("complete_step_before_verify"):
                plans = [f for f in facts if f.get("kind") == "task_plan"]
                if not plans:
                    return {"kind": "plan", "arguments": {"steps_json": "",
                        "completed_step": request["complete_step_before_verify"],
                        "summary": "Exact source edit succeeded; next run the actual verifier."}}
                if not plans[-1].get("ok"):
                    return {"kind": "blocked", "reason": "actual task_plan failed"}
            return {"kind": "verify", "script": request["verifier"]}
        block = next((source_block(r["body"], request["symbol"]) for r in reversed(reads)
                      if source_block(r["body"], request["symbol"])), "")
        if block:
            operation = request["operation"]
            replacement = f"def {request['symbol']}(value):\n    return value + {request['expected_delta']}\n"
            if operation == "create":
                full = next((r["body"] for r in reversed(reads) if r["path"] == request["source"]), "")
                if not full or not full.endswith("# END_SOURCE\n"):
                    return {"kind": "blocked", "reason": "complete creation template is missing"}
                return {"kind": "create", "path": request["path"], "text": full.replace(block, replacement, 1)}
            if operation == "append":
                return {"kind": "append", "path": request["path"], "old": block,
                        "new": block + "\n" + f"def {request['new_symbol']}(value):\n    return {request['symbol']}(value) + {request['expected_delta']}\n"}
            return {"kind": operation, "path": request["path"], "old": block,
                    "new": "" if operation == "delete" else replacement}
        if reads:
            # The spill path and paging offset must come from visible ingress,
            # never a guessed evidence ID or fixture-supplied archive location.
            for read in reads:
                spill = re.search(r"完整原文：(.+?)。", read["body"])
                if spill:
                    path = spill.group(1)
                    pages = [r for r in reads if r["path"] == path]
                    visible = read["body"].split("\n[输出共 ", 1)[0]
                    # A spill is a new file, beginning with the host's result
                    # header. Its local offsets do not inherit source offsets.
                    # Size pages from observed UTF-8 line widths so reading the
                    # archive does not immediately create another spill.
                    line_bytes = max((len(line.encode("utf-8")) for line in visible.splitlines(keepends=True)), default=1)
                    page_lines = max(1, 24576 // max(1, line_bytes))
                    start = (max(r["end_line"] for r in pages) + 1 if pages
                             else visible.count("\n") + 2)
                    return {"kind": "read", "path": path, "start_line": start, "end_line": start + page_lines - 1}
            start = max(r["end_line"] for r in reads) + 1
        else:
            start = 1
        return {"kind": "read", "path": request["source"], "start_line": start, "end_line": 2000}


class StateProvider:
    """The bookkeeping below never supplies information to ContextPolicy."""

    provider_config = {"max_context_tokens": 1000000}

    def __init__(self, summary_mode="normal"):
        self.summary_mode = summary_mode
        self.requests = []
        self.summary_requests = []
        self.cycle = 0
        self.cancelled = 0

    async def text_chat(self, **kwargs):
        if kwargs.get("func_tool") is not None:
            payload = {k: deepcopy(kwargs.get(k, "")) for k in ("prompt", "system_prompt", "contexts")}
            payload["tools"] = [{"name": t.name, "description": t.description,
                                 "parameters": t.parameters} for t in kwargs["func_tool"].tools]
            observation = {"cycle": self.cycle, "payload": payload}
            if callable(getattr(kwargs["func_tool"], "openai_schema", None)):
                observation["runtime_schema"] = deepcopy(kwargs["func_tool"].openai_schema())
                observation["runtime_toolset_type"] = type(kwargs["func_tool"]).__module__ + "." + type(kwargs["func_tool"]).__name__
            self.requests.append(observation)
            decision = ContextPolicy.decide(payload["contexts"])
            return SimpleNamespace(completion_text=encoded(decision), usage=None)
        self.summary_requests.append(deepcopy(kwargs))
        if self.summary_mode == "timeout":
            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
        # Recover real supplied messages from the summarizer's request, whether
        # it sends full dicts or embeds history JSON in a textual prompt.
        raw = kwargs.get("prompt", "")
        rows = []

        def walk(value):
            if isinstance(value, dict):
                if "role" in value and "content" in value:
                    rows.append(value)
                else:
                    for child in value.values():
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
            elif isinstance(value, str):
                try:
                    walk(json.loads(value))
                except (ValueError, TypeError):
                    # A split source_chunk cannot be treated as complete facts.
                    pass

        try:
            walk(json.loads(raw))
        except ValueError:
            pass
        request, facts = scan_context(rows)
        notes = []
        if request:
            for fact in facts:
                fact = deepcopy(fact)
                if fact.get("kind") == "read":
                    block = source_block(fact["body"], request.get("symbol", ""))
                    observations = [line for line in fact["body"].splitlines() if line.startswith("# OBSERVATION ")]
                    fact["body"] = block + "\n".join(observations)
                notes.append(fact)
        text = MEMORY + encoded({"request": request, "facts": notes})
        if self.summary_mode in {"long_valid", "too_long"}:
            target = 4500 if self.summary_mode == "long_valid" else 12000
            fact_line = "\n\nObserved request digest " + digest(raw) + "; verification remains pending."
            while len(text) < target:
                text += fact_line
        return SimpleNamespace(completion_text=text, usage=None)


class Event:
    unified_msg_origin = "v04-bot:FriendMessage:offline-admin"

    def __init__(self):
        self._extras = {}

    def get_extra(self, key, default=None):
        return self._extras.get(key, default)

    def set_extra(self, key, value):
        self._extras[key] = value

    def get_sender_id(self):
        return "offline-admin"

    def get_platform_name(self):
        return "v04-bot"


class Message:
    def __init__(self, row):
        self.row = deepcopy(row)
        self.role = row["role"]

    def model_dump(self):
        return deepcopy(self.row)

    @classmethod
    def model_validate(cls, row):
        return cls(row)


class ToolSet:
    def __init__(self):
        names = sorted(CONTROL_NAMES) + ["astrbot_file_read_tool", "astrbot_file_edit_tool",
                                         "astrbot_file_write_tool", "astrbot_execute_ipython"]
        self.tools = [SimpleNamespace(name=name, description="Offline native host tool", parameters={}) for name in names]
        for schema in module("task_tools").TASK_TOOL_SCHEMAS:
            tool = next(t for t in self.tools if t.name == schema["function"]["name"])
            tool.description = schema["function"]["description"]
            tool.parameters = deepcopy(schema["function"]["parameters"])

    def remove_tool(self, name):
        self.tools = [t for t in self.tools if t.name != name]


class NativeHost:
    """Real temporary file I/O, exact replacement and an isolated subprocess."""

    def __init__(self, root):
        self.root = root.resolve()
        self.reads, self.writes, self.verifications = [], [], []
        self.owner = None
        self.dispatches = []

    def path(self, value):
        path = Path(value).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("fixture host path is outside its temporary directory")
        return path

    def perform(self, action):
        kind = action["kind"]
        if kind == "read":
            path = self.path(action["path"])
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            start, end = action["start_line"], action["end_line"]
            body = "".join(lines[start-1:end])
            self.reads.append({"path": str(path), "start": start, "end": min(end, len(lines)),
                               "requested_end": end, "sha256": digest(body)})
            return {"kind": kind, "path": str(path), "start_line": start, "end_line": min(end, len(lines))}, body
        if kind in {"update", "delete", "append"}:
            path = self.path(action["path"])
            original = path.read_text(encoding="utf-8")
            if not action["old"] or original.count(action["old"]) != 1:
                return {"kind": "edit", "ok": False}, "exact original is not unique"
            changed = original.replace(action["old"], action["new"], 1)
            path.write_text(changed, encoding="utf-8", newline="")
            self.writes.append({"path": str(path), "kind": kind, "before": digest(original), "after": digest(changed)})
            return {"kind": "edit", "ok": True}, "exact replacement applied once"
        if kind == "create":
            path = self.path(action["path"])
            with path.open("x", encoding="utf-8", newline="") as stream:
                stream.write(action["text"])
            self.writes.append({"path": str(path), "kind": kind, "after": digest(action["text"])})
            return {"kind": kind, "ok": True}, "new file created"
        if kind == "verify":
            command = [sys.executable, "-I", "-B", str(self.path(action["script"]))]
            if "answer" in action:
                command.append(str(action["answer"]))
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.verifications.append({"command": command, "exit_code": result.returncode,
                                       "stdout": result.stdout, "stderr": result.stderr})
            return {"kind": kind, "exit_code": result.returncode}, result.stdout if result.returncode == 0 else result.stderr
        raise ValueError("unknown host action: " + kind)

    async def execute(self, tool, context, **arguments):
        from mcp.types import CallToolResult, TextContent
        if self.owner is not None:
            event = context.context.event
            state = module("task_control").control(self.owner.storage.load_active_task(event.unified_msg_origin))
            dispatch = {"tool": tool.name, "plan_version": state["version"],
                        "event_plan_version": event.get_extra("agent_lab_plan_version"),
                        "current_step_id": state.get("current_step_id"),
                        "round_id": event.get_extra("agent_lab_round_id")}
            self.dispatches.append(dispatch)
            if tool.name in CONTROL_NAMES:
                # A native dispatch adapter only: the registered handler calls
                # real TaskTools.dispatch -> task_plan -> TaskControl.submit_plan.
                body = await tool.handler(event, **arguments)
                task = self.owner.storage.load_active_task(event.unified_msg_origin)
                after = module("task_control").control(task)
                meta = {"kind": tool.name, "ok": task.status == "running" and not task.pending_approvals(),
                        "version": after["version"], "approved_version": after["approved_version"],
                        "current_step_id": after.get("current_step_id")}
                dispatch.update(arguments=deepcopy(arguments), after=deepcopy(meta),
                                event_plan_version_after=event.get_extra("agent_lab_plan_version"))
                yield CallToolResult(content=[TextContent(type="text", text=RESULT + encoded(meta) + "\n" + body)])
                return
        meta, body = self.perform(arguments)
        yield CallToolResult(content=[TextContent(type="text", text=RESULT + encoded(meta) + "\n" + body)])


def runner_type(host, provider, owner, compact_after_read):
    class HostRunner:
        stopped = False
        final = None
        instances = []

        async def reset(self, **kwargs):
            self.instances.append(self)
            self.stop_calls = 0
            self.provider, self.request = kwargs["provider"], kwargs["request"]
            self.context, self.executor = kwargs["run_context"], kwargs["tool_executor"]
            self.context.messages = [Message({"role": "system", "content": self.request.system_prompt}),
                                     *[Message(row) for row in self.request.contexts],
                                     Message({"role": "user", "content": self.request.prompt})]
            self.request_context_manager = SimpleNamespace(config=SimpleNamespace(max_context_tokens=1000000))

        def request_stop(self):
            self.stop_calls += 1
            self.stopped = True

        async def step_until_done(self, max_steps):
            handoff_requested = False
            for _ in range(max_steps):
                self.context.messages = await self.request_context_manager.process(self.context.messages)
                task = owner.storage.load_active_task(Event.unified_msg_origin)
                provider.cycle = module("continuity").lane_state(task).get("count", 0)
                response = await self.provider.text_chat(prompt="", system_prompt=self.request.system_prompt,
                    contexts=[m.model_dump() for m in self.context.messages if m.role != "system"], func_tool=self.request.func_tool)
                action = json.loads(response.completion_text)
                self.final = response
                if action["kind"] in {"finish", "blocked"}:
                    self.context.messages.append(Message({"role": "assistant", "content": response.completion_text}))
                    return
                tool_name = {"read": "astrbot_file_read_tool", "update": "astrbot_file_edit_tool",
                             "delete": "astrbot_file_edit_tool", "append": "astrbot_file_edit_tool",
                             "create": "astrbot_file_write_tool", "verify": "astrbot_execute_ipython",
                             "plan": "task_plan"}[action["kind"]]
                tool = next(t for t in self.request.func_tool.tools if t.name == tool_name)
                arguments = action["arguments"] if action["kind"] == "plan" else action
                call_id = "call_" + uuid4().hex
                self.context.messages.append(Message({"role": "assistant", "content": "", "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": tool_name, "arguments": encoded(arguments)}}]}))
                results = []
                async for result in self.executor.execute(tool, self.context, **arguments):
                    results.append(result)
                content = "\n".join(item.text for r in results for item in r.content if hasattr(item, "text"))
                self.context.messages.append(Message({"role": "tool", "tool_call_id": call_id, "content": content}))
                if compact_after_read and host.reads and not handoff_requested:
                    task = owner.storage.load_active_task(Event.unified_msg_origin)
                    module("continuity").lane_state(task)["pending_reason"] = "stage_changed"
                    owner.storage.save_task(task)
                    handoff_requested = True
                if self.stopped:
                    return
                yield None
            raise AssertionError("request budget exceeded without a context-supported completion")

        def get_final_llm_resp(self):
            return self.final

    return HostRunner


class V04EndToEnd(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.started = time.perf_counter()
        self.row = {"id": self._testMethodName, "status": "running"}
        SCENARIOS.append(self.row)
        self.temp = tempfile.TemporaryDirectory(prefix="agent_lab_v04_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = module("storage").AgentLabStorage(self.root / "data")
        self.host = NativeHost(self.root)
        self.provider = StateProvider()
        self.owner = SimpleNamespace(storage=self.storage, _running_ticks=set(),
            _redact_known_secrets=lambda value: value,
            _require_task_access=lambda event: None,
            _cfg_value=lambda key, default: default,
            _context_config=lambda umo: {"provider_settings": {"computer_use_runtime": "sandbox"}},
            _budget_remaining_tools=lambda task: 100,
            _consume_tool_budget=lambda *args: "",
            _consume_token_budget=lambda *args: "",
            _tool_allowed_by_agent_profile=lambda *args: True,
            _tool_available_for_agent=lambda *args: True,
            _disabled_plugin_names=lambda *args: [],
            _effective_tool_risk=lambda *args: "work",
            _infer_tool_risk=lambda *args: "work")
        self.owner.context = SimpleNamespace()
        self.owner.task_control = module("task_control").TaskControl(self.owner)
        self.owner.projects = module("projects").Projects(self.owner)
        self.task = module("models").TaskState(umo=Event.unified_msg_origin, root_goal="Offline v0.4 acceptance", status="running")
        self.task.workflow_data["task_control"] = {"version": 1, "approved_version": 1,
            "owner_id": "offline-admin", "human_paused": False, "automatic": True,
            "current_step_id": "edit", "steps": [{"id": "edit", "title": "Edit and verify", "status": "pending", "instruction": "read actual source", "evidence": []}],
            "journal": [], "execution_settings": {"mode": "full", "roots": [str(self.root)],
                "continuity": {"context_tokens": 1000000, "context_percent": 70, "summary_chars": 6000, "max_stage_ticks": 100}}}
        self.task.budget.max_tokens_per_tick = 0
        self.task.budget.max_total_tokens = 0
        self.storage.save_task(self.task)
        self.event = Event()

    def tearDown(self):
        self.row["elapsed_ms"] = round((time.perf_counter() - self.started) * 1000, 3)
        self.row["metrics"] = self.metrics()

    def metrics(self):
        payloads = [r["payload"] for r in self.provider.requests] + self.provider.summary_requests
        chars = sum(len(encoded(p)) for p in payloads)
        byte_count = sum(len(encoded(p).encode("utf-8")) for p in payloads)
        repeated = 0
        for i, read in enumerate(self.host.reads):
            repeated += int(any(prev["path"] == read["path"] and (
                                    (prev["start"], prev["requested_end"]) == (read["start"], read["requested_end"])
                                    or max(prev["start"], read["start"]) <= min(prev["end"], read["end"]))
                                for prev in self.host.reads[:i]))
        return {"llm_requests": len(payloads), "execution_requests": len(self.provider.requests),
                "summary_requests": len(self.provider.summary_requests), "input_chars": chars,
                "input_utf8_bytes": byte_count, "estimated_input_tokens": max(1, byte_count // 3),
                "read_calls": len(self.host.reads), "repeated_or_overlapping_reads": repeated,
                "mutations": len(self.host.writes), "subprocess_verifications": len(self.host.verifications),
                "verification_exit_codes": [v["exit_code"] for v in self.host.verifications]}

    def fixture(self, operation="update", wide=False):
        symbol = "calculate_" + uuid4().hex[:10]
        old, expected = int(uuid4().hex[:3], 16), int(uuid4().hex[:3], 16) + 5000
        source = self.root / "large_source.py"
        lines = [f"K{i:04d} = {i}" + (" # " + "context " * 12 if wide else "") + "\n" for i in range(1, 1901)]
        target_line = 1641
        original_block = f"def {symbol}(value):\n    return value + {old}\n"
        lines[target_line-1:target_line+1] = original_block.splitlines(keepends=True)
        keys = ["north", "south", "west"]
        values = [int(uuid4().hex[:3], 16) for _ in keys]
        for index, key, value in zip((299, 999, 1749), keys, values):
            lines[index] = "# OBSERVATION " + encoded({"key": key, "value": value}) + "\n"
        text = "".join(lines) + "# END_SOURCE\n"
        source.write_text(text, encoding="utf-8", newline="")
        target = self.root / "created_source.py" if operation == "create" else source
        receipt = "VERIFIED_" + uuid4().hex
        new_symbol = "extension_" + uuid4().hex[:10]
        verifier = self.root / "verify.py"
        code = ("import ast, pathlib, sys\n"
                f"path = pathlib.Path({str(target)!r})\n"
                "text = path.read_text(encoding='utf-8')\n"
                "ns = {}\nexec(compile(text, str(path), 'exec'), ns)\n")
        if operation == "research":
            code += ("import json\nvalues = [json.loads(line[len('# OBSERVATION '):])['value'] for line in text.splitlines() if line.startswith('# OBSERVATION ')]\n"
                     "assert int(sys.argv[1]) == sum(values), 'research answer is not supported by file contents'\n")
        elif operation == "delete":
            code += f"assert {symbol!r} not in ns, 'symbol was not removed'\n"
        elif operation == "append":
            code += f"assert ns[{symbol!r}](17) == {17+old}\nassert ns[{new_symbol!r}](17) == {17+old+expected}\n"
        else:
            code += f"assert ns[{symbol!r}](17) == {17+expected}, 'target still contains the bug'\n"
        code += f"print({receipt!r})\n"
        verifier.write_text(code, encoding="utf-8", newline="")
        request = {"operation": operation, "path": str(target), "source": str(source), "symbol": symbol,
                   "expected_delta": expected, "new_symbol": new_symbol, "verifier": str(verifier), "receipt": receipt, "keys": keys}
        self.row.update(operation=operation, source_lines=len(text.splitlines()), source_chars=len(text),
                        source_statements=len(ast.parse(text).body), target_line=target_line,
                        target_char_offset=text.index(original_block), source_sha256=digest(text))
        self.assertGreaterEqual(len(text.splitlines()), 1800)
        self.assertGreaterEqual(len(ast.parse(text).body), 1800)
        self.assertGreater(text.index(original_block), 3000)
        return request, text, original_block

    def build_runtime_toolset(self, bridge):
        from astrbot.core.agent.tool import FunctionTool, ToolSet as NativeToolSet

        registry = NativeToolSet(tools=[])
        dispatcher = module("task_tools").TaskTools(self.owner)

        def control_handler(name):
            async def handle(event, **arguments):
                return await dispatcher.dispatch(event, name, arguments)
            return handle

        for schema in module("task_tools").TASK_TOOL_SCHEMAS:
            function = schema["function"]
            registry.add_tool(FunctionTool(name=function["name"], description=function["description"],
                parameters=deepcopy(function["parameters"]), handler=control_handler(function["name"])))
        for name in (*module("task_surface").HOST_TOOLS, "agent_lab_checkpoint", "agent_lab_read_tool_evidence",
                     "agent_lab_update_state", "agent_lab_advance_workflow"):
            registry.add_tool(FunctionTool(name=name, description="Offline registered native tool",
                parameters={"type": "object", "properties": {}}))
        self.owner.context.get_llm_tool_manager = lambda: SimpleNamespace(get_full_tool_set=lambda: registry)
        self.owner.astrbot_bridge = bridge
        bridge.tool = lambda name, event=None: registry.get_tool(name)
        spec = module("models").AgentSpec()
        spec.isolation_policy.tool_mode = "whitelist"
        built = module("task_surface").build_toolset(self.owner, spec, self.event)
        self.assertIsInstance(built, NativeToolSet)
        self.host.owner = self.owner
        self.row["runtime_toolset_builder"] = "task_surface.build_toolset"
        return built

    async def run_bridge(self, request, *, compact=False, summary_mode="normal", initial=None, runtime_surface=False):
        # These are the only fake boundaries. Bridge.run, invoke, permissions,
        # task storage, usage accounting and compaction all remain real.
        bridge = module("astrbot_bridge").AstrBotBridge(self.owner)
        self.provider.summary_mode = summary_mode
        cid = str(uuid5(NAMESPACE_URL, "agent-lab:" + self.task.task_id + ":"))
        conversations = {cid: SimpleNamespace(history=json.dumps(initial or [], ensure_ascii=False), user_id=self.task.umo)}
        daily = SimpleNamespace(history='[{"role":"user","content":"daily sentinel"}]', user_id=self.task.umo)

        async def get_conversation(umo, key):
            return conversations[key]

        async def lookup(key):
            return conversations.get(key)

        async def update(umo, key, **kwargs):
            conversations[key].history = json.dumps(kwargs["history"], ensure_ascii=False)

        async def provider_id(umo):
            return "offline-state-provider"

        async def get_provider(key):
            return self.provider

        self.owner.context.conversation_manager = SimpleNamespace(db=SimpleNamespace(get_conversation_by_id=lookup),
            get_conversation=get_conversation, update_conversation=update)
        self.owner.context.provider_manager = SimpleNamespace(get_provider_by_id=get_provider)
        self.owner.context.get_current_chat_provider_id = provider_id
        bridge.execution_context = lambda event: self.owner.context
        if runtime_surface:
            tools = self.build_runtime_toolset(bridge)
        else:
            tools = ToolSet()
            bridge.tool = lambda name, event=None: next((t for t in tools.tools if t.name == name), None)
        runner = runner_type(self.host, self.provider, self.owner, compact)
        self.runners = runner.instances
        modules = {
            "astrbot.core.provider.entities": SimpleNamespace(ProviderRequest=SimpleNamespace),
            "astrbot.core.astr_agent_context": SimpleNamespace(AstrAgentContext=SimpleNamespace, AgentContextWrapper=SimpleNamespace),
            "astrbot.core.astr_agent_tool_exec": SimpleNamespace(FunctionToolExecutor=SimpleNamespace(execute=self.host.execute)),
            "astrbot.core.agent.message": SimpleNamespace(Message=Message),
            "astrbot.core.agent.runners.tool_loop_agent_runner": SimpleNamespace(
                ToolLoopAgentRunner=runner),
        }
        with patch.dict(sys.modules, modules), patch.object(module("astrbot_bridge"), "host_skills_prompt", return_value=""), \
                patch.object(module("continuity"), "SUMMARY_TIMEOUT_SECONDS", .025):
            response = await bridge.run(self.event, self.storage.load_active_task(self.task.umo), tools,
                REQUEST + encoded(request), "Complete only after actual verification.", 14, None)
        self.assertEqual(daily.history, '[{"role":"user","content":"daily sentinel"}]')
        self.assertNotIn("agent_lab_runtime", self.event._extras)
        self.row["final"] = json.loads(response.completion_text) if response else None
        self.row["stored_messages"] = len(json.loads(conversations[cid].history))
        return self.row["final"]

    def assert_prefixes(self):
        comparisons = 0
        for previous, current in zip(self.provider.requests, self.provider.requests[1:]):
            if previous["cycle"] != current["cycle"]:
                continue
            before, after = previous["payload"], current["payload"]
            self.assertEqual(before["system_prompt"].encode(), after["system_prompt"].encode())
            self.assertEqual(before["tools"], after["tools"])
            self.assertGreaterEqual(len(after["contexts"]), len(before["contexts"]))
            self.assertEqual(wire_bytes(before["contexts"]),
                             wire_bytes(after["contexts"][:len(before["contexts"])]),
                             "actual provider history prefix changed within one compaction cycle")
            comparisons += 1
        self.assertGreater(comparisons, 0, "prefix stability requires consecutive real provider requests")
        self.row["byte_identical_prefix_comparisons"] = comparisons

    def assert_finished(self, request):
        self.assertEqual(self.row["final"]["kind"], "finish", self.row["final"])
        self.assertEqual(self.row["final"]["receipt"], request["receipt"])
        self.assertEqual(self.host.verifications[-1]["exit_code"], 0)
        self.assertEqual(self.host.verifications[-1]["stdout"].strip(), request["receipt"])
        # The wide fixture needs at most seven archive pages at 24 KiB each to
        # reach line 1641, then one exact edit, one verification and delivery.
        max_requests = 12 if self.row["source_chars"] > 32768 else (5 if request["operation"] == "research" else 4)
        max_requests += int(bool(self.provider.summary_requests))
        max_requests += int(bool(request.get("complete_step_before_verify")))
        self.assertLessEqual(self.metrics()["llm_requests"], max_requests,
                             "calls grew beyond one read/edit/verify/finish or three research reads")
        self.assertEqual(self.metrics()["repeated_or_overlapping_reads"], 0, "unnecessary re-read or EOF loop")
        self.assertEqual(len(self.host.writes), int(request["operation"] != "research"))
        self.assertEqual(len(self.host.verifications), 1)
        self.row["request_budget"] = max_requests
        self.assert_prefixes()

    async def scenario(self, operation="update", compact=False, summary_mode="normal", wide=False):
        request, original, block = self.fixture(operation, wide)
        await self.run_bridge(request, compact=compact, summary_mode=summary_mode)
        self.assert_finished(request)
        actual = Path(request["path"]).read_text(encoding="utf-8")
        replacement = f"def {request['symbol']}(value):\n    return value + {request['expected_delta']}\n"
        if operation in {"update", "create"}:
            self.assertEqual(actual, original.replace(block, replacement, 1))
        elif operation == "delete":
            self.assertEqual(actual, original.replace(block, "", 1))
        elif operation == "append":
            addition = block + "\n" + f"def {request['new_symbol']}(value):\n    return {request['symbol']}(value) + {request['expected_delta']}\n"
            self.assertEqual(actual, original.replace(block, addition, 1))
        elif operation == "research":
            self.assertEqual(actual, original)
            self.assertFalse(self.host.writes)
        if operation == "create":
            self.assertEqual(Path(request["source"]).read_text(encoding="utf-8"), original)
        if compact:
            self.assertEqual(len(self.provider.summary_requests), 1, "compaction must use one summary request")
            state = module("continuity").lane_state(self.storage.load_active_task(self.task.umo))
            self.assertEqual(state["count"], 1)
            record = self.storage._read_json(self.storage.root / state["record_path"])
            self.assertTrue(any(row.get("role") == "tool" and block in row.get("content", "") for row in record["history"])
                            if operation != "research" else bool(record["history"]))
            self.assertLessEqual(len(state["summary"]), 6000)
            self.row["handoff"] = {"count": state["count"], "summary_chars": len(state["summary"]),
                                   "archived_messages": len(record["history"]), "archive_exists": True}
            resumed = [r for r in self.provider.requests if r["cycle"] == 1]
            self.assertTrue(resumed, "no provider request crossed the real compact boundary")
            text = encoded(resumed[0]["payload"]["contexts"])
            self.assertNotIn("摘要降级", text)
            self.assertNotIn("必须回查证据", text)
            module("continuity").message_groups(resumed[0]["payload"]["contexts"])
            if operation != "research":
                observed = [m["content"] for m in resumed[0]["payload"]["contexts"]
                            if m.get("role") == "tool" and block in m.get("content", "")]
                self.assertTrue(observed, "current source must survive in the exact recent tool group")
                self.assertGreater(len(observed[0].encode("utf-8")) // 3, 4000,
                                   "fixture must expose a regression to the old 4k-token recent window")
                self.assertEqual(len(self.host.reads), 1, "current source was needlessly re-read after compaction")
                self.row["handoff"]["retained_source_estimated_tokens"] = len(observed[0].encode("utf-8")) // 3
        return request

    async def test_update_1900_lines_exactly_once(self):
        await self.scenario()

    async def test_create_from_actual_source(self):
        await self.scenario("create")

    async def test_append_preserves_existing_api(self):
        await self.scenario("append")

    async def test_delete_exact_target_only(self):
        await self.scenario("delete")

    async def test_research_three_real_regions_without_writes(self):
        await self.scenario("research")

    async def test_update_crosses_real_compaction(self):
        await self.scenario(compact=True)

    async def test_task_plan_completed_step_continues_in_same_bridge_with_runtime_toolset(self):
        request, original, block = self.fixture()
        request["complete_step_before_verify"] = "edit"
        state = module("task_control").control(self.task)
        state.update(workflow="none", phase="executing", authorization_version=1,
                     scope_roots=[str(self.root)], authorized_scope_roots=[str(self.root)])
        state["steps"][0].update(status="running", stage="task_execution")
        state["steps"].append({"id": "verify", "title": "Verify the changed module", "status": "pending",
                               "instruction": "Run the actual verification subprocess", "stage": "task_execution", "evidence": []})
        self.storage.save_task(self.task)

        async def unexpected_review(**kwargs):
            self.fail("routine task_plan invoked a second planning/review model")

        async def unexpected_approval(*args, **kwargs):
            self.fail("routine completed_step unexpectedly required administrator approval")

        self.owner.context.llm_generate = unexpected_review
        self.owner.task_messages = SimpleNamespace(state=unexpected_approval)
        # Poison the old fixture constructor: this test must build and send the
        # real production surface and AstrBot ToolSet to MeteredProvider.
        with patch(__name__ + ".ToolSet", side_effect=AssertionError("hardcoded fixture ToolSet was used")):
            await self.run_bridge(request, runtime_surface=True)
        self.assert_finished(request)
        replacement = f"def {request['symbol']}(value):\n    return value + {request['expected_delta']}\n"
        self.assertEqual(Path(request["path"]).read_text(encoding="utf-8"), original.replace(block, replacement, 1))
        self.assertEqual(len(self.runners), 1, "continuation secretly created another runner")
        self.assertEqual(self.runners[0].stop_calls, 0, "completed_step implicitly stopped the running loop")
        self.assertFalse(self.runners[0].stopped)
        self.assertFalse(self.provider.summary_requests)
        self.assertEqual(len(self.provider.requests), 5)

        dispatches = self.host.dispatches
        self.assertEqual([d["tool"] for d in dispatches],
                         ["astrbot_file_read_tool", "astrbot_file_edit_tool", "task_plan", "astrbot_execute_ipython"])
        plan, continued = dispatches[2:]
        self.assertEqual(plan["arguments"]["completed_step"], "edit")
        self.assertEqual(plan["arguments"]["steps_json"], "")
        self.assertEqual(plan["plan_version"], 1)
        self.assertEqual(plan["after"]["version"], 2)
        self.assertEqual(plan["after"]["approved_version"], 2)
        self.assertEqual(plan["after"]["current_step_id"], "verify")
        self.assertEqual(continued["plan_version"], 2)
        self.assertEqual(continued["event_plan_version"], 2, "next host tool received a stale event plan version")
        self.assertEqual(continued["current_step_id"], "verify")
        self.assertEqual(len({d["round_id"] for d in dispatches}), 1)
        self.assertTrue(continued["round_id"])

        latest = self.storage.load_active_task(self.task.umo)
        after = module("task_control").control(latest)
        self.assertEqual(latest.status, "running")
        self.assertFalse(latest.pending_approvals())
        self.assertEqual(after["steps"][0]["status"], "completed")
        self.assertEqual(after["current_step_id"], "verify")
        self.assertEqual(after["authorization_version"], 1)
        verification = next(r for r in after["journal"] if r["name"] == "astrbot_execute_ipython")
        self.assertEqual(verification["status"], "completed")
        self.assertEqual(verification["plan_version"], 2)
        self.assertEqual(verification["step_id"], "verify")
        expected = {s["function"]["name"]: s["function"] for s in module("task_tools").TASK_TOOL_SCHEMAS}
        for observed in self.provider.requests:
            self.assertEqual(observed["runtime_toolset_type"], "astrbot.core.agent.tool.ToolSet")
            sent = {s["function"]["name"]: s["function"] for s in observed["runtime_schema"]}
            controls = {name for name in sent if name in CONTROL_NAMES or name.startswith("agent_lab_")}
            self.assertEqual(controls, CONTROL_NAMES)
            self.assertEqual({name: sent[name] for name in controls}, expected)
            self.assertIn("completed_step", sent["task_plan"]["parameters"]["properties"])
            for name in ("astrbot_file_read_tool", "astrbot_file_edit_tool", "astrbot_execute_ipython"):
                self.assertIn(name, sent)
        self.row["runtime_control_schemas"] = list(expected.values())
        self.row["same_bridge_continuation"] = {"runner_instances": 1, "stop_requests": 0,
            "dispatch_sequence": [d["tool"] for d in dispatches], "version_before": 1,
            "version_after": after["version"], "next_step": "verify", "continued_host_event_version": continued["event_plan_version"],
            "single_round": True, "verification_journal_status": verification["status"]}

    async def test_metered_provider_keeps_large_saved_prefix_below_configured_capacity(self):
        request, _, _ = self.fixture()
        initial = []
        for index in range(4):
            call_id = f"saved-read-{index}"
            initial.extend([
                {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function",
                 "function": {"name": "astrbot_file_read_tool", "arguments": encoded({"path": "previous-source.py"})}}]},
                {"role": "tool", "tool_call_id": call_id,
                 "content": RESULT + encoded({"kind": "reference"}) + "\n" + f"previous source region {index}\n" * 1200},
            ])
        self.assertGreater(len(wire_bytes(initial)) // 3, 24000)
        await self.run_bridge(request, initial=initial)
        self.assert_finished(request)
        first = self.provider.requests[0]["payload"]["contexts"]
        self.assertEqual(wire_bytes(first[:len(initial)]), wire_bytes(initial))
        self.assertFalse(self.provider.summary_requests, "the old 24k history lock triggered below configured capacity")
        self.row["seeded_prefix_utf8_bytes"] = len(wire_bytes(initial))

    async def test_create_crosses_real_compaction(self):
        await self.scenario("create", compact=True)

    async def test_append_crosses_real_compaction(self):
        await self.scenario("append", compact=True)

    async def test_delete_crosses_real_compaction(self):
        await self.scenario("delete", compact=True)

    async def test_research_crosses_real_compaction(self):
        await self.scenario("research", compact=True)

    async def test_timeout_retains_recent_source_and_continues(self):
        await self.scenario(compact=True, summary_mode="timeout")
        self.assertEqual(self.provider.cancelled, 1)

    async def test_overlong_summary_truncates_once_and_continues(self):
        await self.scenario(compact=True, summary_mode="too_long")

    async def test_configured_summary_is_not_capped_to_1200(self):
        await self.scenario(compact=True, summary_mode="long_valid")
        self.assertGreater(self.row["handoff"]["summary_chars"], 1200)

    async def test_32k_ingress_spills_to_readable_real_file(self):
        request = await self.scenario(wide=True)
        paths = {r["path"] for r in self.host.reads}
        self.assertGreater(len(paths), 1, "provider never followed the actual ingress spill path")
        first = next(r for r in self.provider.requests if any(m.get("role") == "tool" for m in r["payload"]["contexts"]))
        content = next(m["content"] for m in first["payload"]["contexts"] if m.get("role") == "tool")
        match = re.search(r"完整原文：(.+?)。", content)
        self.assertIsNotNone(match, "oversize output must advertise an actual readable path")
        full = Path(match.group(1)).read_text(encoding="utf-8")
        self.assertIn(request["symbol"], full)
        self.assertIn(match.group(1), paths)
        self.assertLessEqual(len(content.encode("utf-8")), 32768 + 1500)
        self.row["spill"] = {"raw_chars": len(full), "inline_utf8_bytes": len(content.encode("utf-8")), "read_by_provider": True}

    async def test_policy_cannot_edit_when_target_context_is_missing(self):
        request, text, block = self.fixture()
        messages = [{"role": "user", "content": REQUEST + encoded(request)}, {"role": "tool", "content":
            RESULT + encoded({"kind": "read", "path": request["source"], "start_line": 1, "end_line": 1901}) + "\n" + text}]
        self.assertEqual(ContextPolicy.decide(messages)["kind"], "update")
        messages[-1]["content"] = messages[-1]["content"].replace(block, "# removed from actually delivered context\n")
        self.assertEqual(ContextPolicy.decide(messages)["kind"], "read")
        self.assertEqual(ContextPolicy.decide([])["kind"], "blocked")

    async def test_wrong_exact_edit_is_rejected_without_side_effect(self):
        request, text, _ = self.fixture()
        result, _ = self.host.perform({"kind": "update", "path": request["path"], "old": "not present", "new": "fake fix"})
        self.assertFalse(result["ok"])
        self.assertEqual(Path(request["path"]).read_text(encoding="utf-8"), text)
        result, _ = self.host.perform({"kind": "verify", "script": request["verifier"]})
        self.assertNotEqual(result["exit_code"], 0, "fixture must fail verification before the fix")

    async def test_failed_real_verifier_never_finishes(self):
        request, _, _ = self.fixture()
        Path(request["verifier"]).write_text("raise AssertionError('deliberately failing verifier')\n", encoding="utf-8")
        final = await self.run_bridge(request)
        self.assertEqual(final["kind"], "blocked")
        self.assertNotEqual(self.host.verifications[-1]["exit_code"], 0)
        self.assert_prefixes()

    async def test_five_control_tools_contract(self):
        tools = module("task_tools")
        self.assertEqual(set(tools.CONTROL_TOOL_NAMES), CONTROL_NAMES)
        # Build the actual production surface with a host registry containing
        # obsolete/canvas tools. Ordinary tasks must filter them out.
        class RegistryToolSet:
            def __init__(self):
                self.tools = []

            def add_tool(self, tool):
                if not any(t.name == tool.name for t in self.tools):
                    self.tools.append(tool)

        registry = {t.name: t for t in ToolSet().tools}
        for name in ("agent_lab_update_state", "agent_lab_read_runtime", "agent_lab_read_tool_evidence",
                     "agent_lab_checkpoint", "agent_lab_advance_workflow", "agent_lab_call_custom_api"):
            registry[name] = SimpleNamespace(name=name, description="registered tool", parameters={})
        self.owner.astrbot_bridge = SimpleNamespace(tool=lambda name, event=None: registry.get(name))
        self.owner.context.get_llm_tool_manager = lambda: SimpleNamespace(
            get_full_tool_set=lambda: SimpleNamespace(tools=list(registry.values())))
        spec = SimpleNamespace(isolation_policy=SimpleNamespace(tool_mode="no_external"), enabled_tools=[])
        with patch.dict(sys.modules, {"astrbot.core.agent.tool": SimpleNamespace(ToolSet=RegistryToolSet)}):
            built = module("task_surface").build_toolset(self.owner, spec, self.event)
            self.assertEqual({t.name for t in built.tools}, CONTROL_NAMES)
            spec.isolation_policy.tool_mode = "whitelist"
            built = module("task_surface").build_toolset(self.owner, spec, self.event)
        controls = {t.name for t in built.tools if t.name in CONTROL_NAMES or t.name.startswith("agent_lab_")}
        self.assertEqual(controls, CONTROL_NAMES | {"agent_lab_call_custom_api"})
        self.assertFalse((ROOT / "agent_lab/context_views.py").exists())
        self.assertFalse((ROOT / "agent_lab/read_cache.py").exists())
        self.row["control_tools"] = sorted(CONTROL_NAMES)
        self.row["control_schema_chars"] = len(encoded(tools.TASK_TOOL_SCHEMAS))


class ReportingResult(unittest.TextTestResult):
    def addSuccess(self, test):
        test.row["status"] = "passed"
        super().addSuccess(test)

    def addFailure(self, test, err):
        test.row.update(status="failed", detail=self._exc_info_to_string(err, test))
        super().addFailure(test, err)

    def addError(self, test, err):
        if hasattr(test, "row"):
            test.row.update(status="error", detail=self._exc_info_to_string(err, test))
        super().addError(test, err)


def source_hashes():
    paths = [ROOT / "main.py", ROOT / "scripts/ui/test_v04_end_to_end.py", *sorted((ROOT / "agent_lab").glob("*.py"))]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def main():
    started = time.perf_counter()
    before = source_hashes()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(V04EndToEnd)
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReportingResult).run(suite)
    after = source_hashes()
    report = {"schema_version": 2, "target_release": "v0.4.0", "generated_at": datetime.now(timezone.utc).isoformat(),
        "command": "python scripts/ui/test_v04_end_to_end.py", "python": platform.python_version(), "platform": platform.system(),
        "scope": "离线状态驱动端到端模拟；真实 bridge.run/invoke、TaskContinuity.compact、临时文件及 Python 子进程；不是线上 Bot 或真实语言模型验收。",
        "fakes": ["AstrBot host runner/message adapter", "native tool dispatch into real temporary file operations", "context-driven deterministic provider", "in-memory conversation transport", "permission/profile and tool-budget callbacks"],
        "measurement_notes": {"characters": "Unicode code points of serialized actual provider payloads, including summary requests",
            "tokens": "UTF-8 request bytes // 3 estimate; no actual provider tokens, cache hits or billing claimed",
            "prefix": "serialized provider-received history prefixes compared byte for byte within each real compaction cycle; system prompt and tool names also compared",
            "repeated_reads": "a read overlapping an earlier read interval of the same absolute path; spill aliases remain separate paths",
            "time": "perf_counter local wall time, not online bot latency", "summary_timeout": "production timeout temporarily shortened to 25 ms; real asyncio cancellation",
            "lifecycle": "create writes a new module; update replaces its target function; append adds a function; delete removes the exact target function; research performs no workspace writes; live administrator task lifecycle UI is outside this suite",
            "completion": "policy sees only actual request messages and tool observations; independent receipt-bearing Python subprocess required",
            "source_changes": "parallel production edits are recorded; rerun after source hashes stabilize"},
        "integration_contract": __doc__.split("Integration contract", 1)[1].strip(),
        "summary": {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
            "passed": result.testsRun - len(result.failures) - len(result.errors), "successful": result.wasSuccessful(),
            "elapsed_ms": round((time.perf_counter()-started)*1000, 3)},
        "source_sha256_at_start": before, "source_sha256_at_end": after,
        "sources_changed_during_run": sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p)),
        "scenarios": SCENARIOS}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("V04_REPORT " + str(REPORT))
    print("V04_SUMMARY " + encoded(report["summary"]))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
