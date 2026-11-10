"""AstrBot-specific execution boundary, shared by task rounds and tool nodes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import copy
from contextlib import aclosing
from uuid import uuid5, NAMESPACE_URL

from .models import ApprovalRequest, new_id, now_iso
from .task_control import control


class ExecutionStopped(Exception):
    pass


class AstrBotBridge:
    def __init__(self, owner):
        self.owner = owner
        self._tool_locks = {}

    def tool(self, name, event=None):
        name = {"astrbot_sandboxed_shell": "astrbot_execute_shell", "astrbot_sandboxed_python": "astrbot_execute_ipython"}.get(name, name)
        manager = self.owner.context.get_llm_tool_manager()
        tool = manager.get_full_tool_set().get_tool(name)
        if tool:
            return tool
        from astrbot.core.tools.computer_tools.fs import FileReadTool, FileWriteTool, FileEditTool, GrepTool
        from astrbot.core.tools.computer_tools.shell import LocalExecuteShellTool, ExecuteShellTool
        from astrbot.core.tools.computer_tools.python import LocalPythonTool, PythonTool
        cfg = self.owner._context_config(event.unified_msg_origin if event else None) or {}
        local = cfg.get("provider_settings", {}).get("computer_use_runtime") == "local"
        factories = {"astrbot_file_read_tool": FileReadTool, "astrbot_file_write_tool": FileWriteTool,
                     "astrbot_file_edit_tool": FileEditTool, "astrbot_grep_tool": GrepTool,
                     "astrbot_execute_shell": LocalExecuteShellTool if local else ExecuteShellTool,
                     "astrbot_execute_python": LocalPythonTool, "astrbot_execute_ipython": PythonTool}
        return manager.get_builtin_tool(factories[name]) if name in factories else manager.get_func(name)

    def check(self, event, task_id="", *, allow_inflight=False):
        self.owner._require_task_access(event)
        task = self.owner.storage.load_active_task(event.unified_msg_origin)
        if not task or (task_id and task.task_id != task_id):
            raise ExecutionStopped("任务已经结束或切换。")
        if self.owner.storage.ended_path(task.task_id).exists():
            raise ExecutionStopped("管理员已经结束任务；禁止继续调用工具。")
        if task.task_id in self.owner.projects.cleaning:
            raise ExecutionStopped("当前任务正在清理缓存，等待清理完成后再继续。")
        state = control(task)
        if task.status != "running" or task.pending_approvals() or (state and (
            not state.get("approved_version") or state.get("approved_version") != state.get("version")
            or state.get("human_paused"))):
            raise ExecutionStopped("任务已暂停、计划尚未批准或存在待审批操作。")
        forbidden = {"unknown"} if allow_inflight else {"started", "unknown"}
        if any(row.get("status") in forbidden for row in state.get("journal", [])):
            raise ExecutionStopped("上一次工具结果未知，请核对后再继续。")
        return task

    async def invoke(self, event, tool, arguments, task_id="", *, count=True, native=False):
        if tool.name.startswith("agent_lab_") and tool.name != "agent_lab_call_custom_api":
            return await self._invoke(event, tool, arguments, task_id, count=count, native=native)
        lock = self._tool_locks.setdefault(event.unified_msg_origin, asyncio.Lock())
        async with lock:
            return await self._invoke(event, tool, arguments, task_id, count=count, native=native)

    async def _invoke(self, event, tool, arguments, task_id="", *, count=True, native=False):
        from astrbot.core.astr_agent_context import AstrAgentContext, AgentContextWrapper
        from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
        from .models import AgentSpec

        task = self.check(event, task_id)
        state = control(task)
        if state.get("input_revision", 0) != event.get_extra("agent_lab_input_revision", state.get("input_revision", 0)):
            raise ExecutionStopped("收到新引导，先结束本轮并重载要求。")
        tool = self.tool(tool.name, event) or tool
        encoded_args = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        if self.owner._redact_known_secrets(encoded_args) != encoded_args:
            raise ExecutionStopped("工具参数包含已保存凭证，请使用注册 API 的凭证绑定，避免密钥进入任务记录。")
        spec = AgentSpec.from_dict(task.profile_snapshot.get("agent"))
        internal = tool.name.startswith("agent_lab_") and tool.name != "agent_lab_call_custom_api"
        tick = task.workflow_data.get("tick_budget", {})
        if int(tick.get("tool_calls_used", 0)) > int(tick.get("max_tools", task.budget.max_tools_per_tick)):
            raise ExecutionStopped("本轮调用上限已达到，保存后续轮。")
        if task.budget.max_total_tool_calls and task.budget.tool_calls_used > task.budget.max_total_tool_calls:
            raise ExecutionStopped("任务调用总预算已用尽。")
        if not internal and (not self.owner._tool_allowed_by_agent_profile(spec, tool.name)
                or not self.owner._tool_available_for_agent(tool, self.owner._disabled_plugin_names(spec))):
            raise ExecutionStopped("工具不在当前任务允许范围：" + tool.name)
        risk = self.owner._effective_tool_risk(spec, tool.name, self.owner._infer_tool_risk(tool.name, tool.description))
        destructive = tool.name in {"astrbot_execute_shell", "astrbot_execute_python", "astrbot_execute_ipython"}
        needs_approval = not internal and (risk == "high" or destructive or tool.name == "agent_lab_call_custom_api")
        # Explicit machine-readable administrator scopes may authorize repeated
        # calls. Free-form descriptions never silently become execution grants.
        approved_scopes = set(state.get("approved_tool_scopes", []))
        if f"tool:{tool.name}" in approved_scopes:
            needs_approval = False
        resource = self.owner.storage.list_custom_apis() if tool.name == "agent_lab_call_custom_api" else (self.owner._context_config(task.umo) or {}).get("provider_settings", {})
        signature = hashlib.sha256(json.dumps([tool.name, arguments, resource, state.get("version", 0), state.get("current_step_id")],
                                              ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
        approval = next((row for row in task.approvals if row.get("status") == "approved"
                         and row.get("call_signature") == signature), None)
        if needs_approval and approval is None:
            row = ApprovalRequest(operation=tool.name, reason="执行当前批准计划步骤", impact=json.dumps(arguments, ensure_ascii=False),
                                  approval_type="tool_call").to_dict()
            row.update(call_signature=signature, tool_name=tool.name, arguments=arguments)
            task.approvals.append(row)
            task.status = "paused"
            task.set_wait(wait_reason="need_approval", message=f"工具等待审批：{tool.name}", source="tool_dispatch",
                          resume_command=f"/al approve {row['approval_id']}")
            self.owner.storage.save_task(task)
            raise ExecutionStopped(f"未执行工具。请管理员审批：/al approve {row['approval_id']}")
        if approval:
            approval["status"] = "consumed"
        if count:
            reason = self.owner._consume_tool_budget(task, tool.name)
            if reason:
                self.owner.storage.save_task(task)
                raise ExecutionStopped(reason)
        identifier = new_id("call")
        record = {"id": identifier, "name": tool.name, "arguments": arguments, "status": "started", "time": now_iso(),
                  "plan_version": state.get("version", 0), "step_id": state.get("current_step_id", "")}
        if not internal:
            state.setdefault("journal", []).append(record)
        self.owner.storage.save_task(task)
        context = AgentContextWrapper(context=AstrAgentContext(context=self.execution_context(event), event=event),
                                      tool_call_timeout=int(self.owner._cfg_value("tool_call_timeout", 120)))
        chunks, native_results, failed = [], [], False

        async def execute():
            nonlocal failed
            async with aclosing(FunctionToolExecutor.execute(tool, context, **arguments)) as stream:
                async for result in stream:
                    if result is None:
                        continue
                    text = "\n".join(str(getattr(part, "text", "")) for part in getattr(result, "content", []) if getattr(part, "type", "") == "text")
                    text = self.owner._redact_known_secrets(text)
                    chunks.append(text or "工具返回非文本内容；原生模型循环保留图片/文件结果。")
                    from mcp.types import CallToolResult, TextContent
                    content = [TextContent(type="text", text=text)] if text else []
                    content.extend(part for part in getattr(result, "content", []) if getattr(part, "type", "") != "text")
                    native_results.append(CallToolResult(content=content, isError=bool(getattr(result, "isError", False))))
                    failed |= bool(getattr(result, "isError", False)) or text.lower().startswith(("error", "traceback"))
                    try:
                        data = json.loads(text)
                        if isinstance(data, dict):
                            failed |= data.get("ok") is False or data.get("exit_code", 0) not in {0, None}
                            if data.get("session_id") and not data.get("session_closed", False):
                                raise ExecutionStopped("命令仍在后台运行；其结果需核对，不得标记完成。")
                    except json.JSONDecodeError:
                        pass
        status = "unknown"
        try:
            await asyncio.wait_for(execute(), timeout=context.tool_call_timeout)
            status = "failed" if failed else "completed"
        finally:
            latest = self.owner.storage.load_active_task(event.unified_msg_origin)
            if latest and latest.task_id == task.task_id and not internal:
                item = next((row for row in control(latest).get("journal", []) if row["id"] == identifier), None)
                if item:
                    output = "\n".join(chunks)
                    item.update(status=status, result=output[:12000], fingerprint=hashlib.sha256(
                        json.dumps([tool.name, arguments, output], sort_keys=True, ensure_ascii=False).encode()).hexdigest())
                    if status == "unknown":
                        latest.status = "paused"
                        latest.next_step = f"核对工具结果：{identifier}；不要盲目重试。"
                    self.owner.storage.save_task(latest)
        evidence = f"\n[任务工具证据 ID: {identifier}; status={status}]" if not internal else ""
        if native:
            from mcp.types import CallToolResult, TextContent
            if evidence:
                native_results.append(CallToolResult(content=[TextContent(type="text", text=evidence)], isError=failed))
            return native_results
        return "\n".join(chunks) + evidence

    def execution_context(self, event):
        from astrbot.api.star import Context
        owner = self.owner
        class ContextProxy(Context):
            def __init__(self):
                self.__dict__.update(owner.context.__dict__)
            def get_config(self, umo=None):
                cfg = dict(owner.context.get_config(umo=umo))
                if umo in {None, event.unified_msg_origin}:
                    owner._require_task_access(event)
                    cfg["admins_id"] = list(set(map(str, cfg.get("admins_id", []))) | {str(event.get_sender_id())})
                return cfg
        return ContextProxy()

    async def run(self, event, task, tools, prompt, system_prompt, max_steps, hooks, *, lane="", provider_id=""):
        from astrbot.core.astr_agent_context import AstrAgentContext, AgentContextWrapper
        from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
        from astrbot.core.provider.entities import ProviderRequest
        from mcp.types import CallToolResult, TextContent

        # Never mark the source daily-chat event as a private task execution.
        event = copy.copy(event)
        event._extras = dict(getattr(event, "_extras", {}))
        event.set_extra("agent_lab_runtime", task.task_id)
        system_prompt += self.owner.projects.filtered_context(task)
        # Always resolve the model selected on the source bot. No new provider UI.
        provider_id = provider_id or await self.owner.context.get_current_chat_provider_id(task.umo)
        provider = await self.owner.context.provider_manager.get_provider_by_id(provider_id)
        if not provider:
            raise ValueError("当前 Bot 没有可用聊天模型。")
        runtime = (self.owner._context_config(task.umo) or {}).get("provider_settings", {}).get("computer_use_runtime", "none")
        unsupported = {"astrbot_execute_ipython"} if runtime == "local" else {"astrbot_execute_python"}
        if runtime == "none":
            unsupported.update({"astrbot_execute_ipython", "astrbot_execute_shell"})
        for tool in list(tools.tools):
            if tool.name in unsupported:
                tools.remove_tool(tool.name)
        manager = self.owner.context.conversation_manager
        source_id = await manager.get_curr_conversation_id(task.umo)
        source_conv = await manager.get_conversation(task.umo, source_id) if source_id else None
        _, persona, _, _ = await self.owner.context.persona_manager.resolve_selected_persona(
            umo=task.umo, conversation_persona_id=getattr(source_conv, "persona_id", None),
            platform_name=(event.get_platform_name() if event.get_platform_name() != "cron" else task.umo.split(":", 1)[0]),
            provider_settings=(self.owner._context_config(task.umo) or {}).get("provider_settings", {}))
        if persona and persona.get("prompt"):
            system_prompt = str(persona["prompt"]) + "\n\n" + system_prompt
        cid = str(uuid5(NAMESPACE_URL, "agent-lab:" + task.task_id + ":" + lane))
        conv = await manager.db.get_conversation_by_id(cid)
        if conv is None:
            await manager.db.create_conversation(user_id=task.umo, platform_id=task.umo.split(":", 1)[0], cid=cid, content=[], title="Agent Lab · " + task.root_goal[:80])
        conv = await manager.get_conversation(task.umo, cid)
        contexts = json.loads(conv.history or "[]")
        runner = ToolLoopAgentRunner()
        bridge = self
        event.set_extra("agent_lab_input_revision", control(task).get("input_revision", 0))
        # A subagent keeps its own conversation, but writes tool records into
        # the same task. Tools that mutate the main plan are never delegated.
        if lane:
            for tool in list(tools.tools):
                if tool.name.startswith("agent_lab_"):
                    tools.remove_tool(tool.name)

        class Executor:
            async def execute(self, tool, run_context, **arguments):
                try:
                    results = await bridge.invoke(event, tool, arguments, task.task_id, count=True, native=True)
                    for result in results:
                        yield result
                except ExecutionStopped as exc:
                    runner.request_stop()
                    yield CallToolResult(content=[TextContent(type="text", text=str(exc))], isError=True)

        context = AgentContextWrapper(context=AstrAgentContext(context=self.execution_context(event), event=event),
                                      tool_call_timeout=int(self.owner._cfg_value("tool_call_timeout", 120)))
        class MeteredProvider:
            def __getattr__(self, name):
                return getattr(provider, name)
            async def text_chat(self, **kwargs):
                latest = bridge.check(event, task.task_id, allow_inflight=True)
                if latest.budget.max_total_tokens and latest.budget.tokens_used >= latest.budget.max_total_tokens:
                    raise ExecutionStopped("任务令牌预算已用尽。")
                response = await provider.text_chat(**kwargs)
                latest = bridge.owner.storage.load_active_task(task.umo)
                if latest and latest.task_id == task.task_id:
                    usage = getattr(response, "usage", None)
                    if usage:
                        latest.add_token_usage(usage)
                        bridge.owner._consume_token_budget(latest, usage)
                        bridge.owner.storage.save_task(latest)
                return response
        metered = MeteredProvider()
        request = ProviderRequest(prompt=prompt, contexts=contexts, system_prompt=system_prompt, func_tool=tools)
        await runner.reset(provider=metered, request=request, run_context=context, tool_executor=Executor(), agent_hooks=hooks,
                           streaming=False, llm_compress_provider=metered, llm_compress_keep_recent_ratio=0.15,
                           enforce_max_turns=-1)
        try:
            async for _ in runner.step_until_done(max_steps):
                pass
        finally:
            history = [msg.model_dump() for msg in context.messages if msg.role != "system"]
            # Persist only complete tool-call groups. An interrupted suffix stays
            # in the separate journal and must not produce orphaned tool results.
            safe = []
            index = 0
            while index < len(history):
                msg = history[index]
                if msg.get("role") == "tool":
                    index += 1
                    continue
                calls = msg.get("tool_calls") or []
                if calls:
                    results = []
                    cursor = index + 1
                    while cursor < len(history) and history[cursor].get("role") == "tool":
                        results.append(history[cursor]); cursor += 1
                    if {c["id"] for c in calls} <= {r.get("tool_call_id") for r in results}:
                        safe.extend([msg, *results])
                    index = cursor
                else:
                    safe.append(msg); index += 1
            if not self.owner.storage.ended_path(task.task_id).exists():
                await manager.update_conversation(task.umo, cid, history=safe)
        return runner.get_final_llm_resp()
