# 运行手册

## 首次启动检查

1. Install plugin as `data/plugins/astrbot_plugin_agent_lab`.
2. Restart AstrBot or reload plugins.
3. 打开独立 WebUI，默认 `http://127.0.0.1:8788`。
4. 确认 `agent-mode` Skill 已启用。
5. 在私聊里运行：

```text
/agentlab status
/agentlab agents
/agentlab use <agent_id>
/agentlab start 帮我测试 Agent Lab 是否能创建任务
/agentlab tick
/agentlab finish 初步测试完成
```

## WebUI 访问

Agent Lab WebUI 是插件启动的独立 Quart 控制台。

- `standalone_webui_host`: default `127.0.0.1`.
- `standalone_webui_port`: default `8788`.
- `standalone_webui_token`: optional API token; set it when listening outside localhost.
- WebUI 任务表单需要填写 UMO，因为它可以从控制台模拟任务操作；普通使用可以直接从私聊命令开始。

## 安全默认值

- 默认只允许私聊。
- 每个会话只允许一个 active task。
- 心跳默认手动开启。
- 危险动作走软审批。
- 任务状态存储在 `plugin_data`。
- 新建 AgentSpec 默认 `isolation_policy.mode=strict`，当前会话默认关闭普通插件，只保留 Agent Lab、AstrBot 保留插件和用户显式允许的插件。
- 插件隔离只作用于会话，退出时按快照恢复。
- Agent Lab 会保护自己，避免被自身任务配置禁用。
- 默认 AgentSpec 展示名自动跟随当前 AstrBot 运行时身份：会话/对话/默认 Persona 优先，其次配置里的 bot 展示名，最后才是通用兜底名。
- 默认 AgentSpec 包含常见 AstrBot Computer Use 工具名；不可用工具会被跳过或由 AstrBot runtime 报错。
- Agent Mode 中关闭的插件，其来源工具会一起从任务工具集中过滤。
- 自定义 API 只能通过 `agent_lab_call_custom_api` 调用；工具只接受已注册 API id/name，不返回已保存的凭证值。
- WebUI 编辑的 `agent-mode` 自定义规则会保存到 `registry/skill_rules.json`，追加到已安装 Skill，并注入任务 tick。
- 入口/出口摘要规则在同一个 Skills 规则页编辑，用来控制任务入口压缩和出口归档摘要。
- 工作流节点、节点素材、拖拽位置和连线在画布面板编辑；画布支持圆点拉线、连线删除、缩放、自动布局、模板切换和检查工作流，原始 JSON 只作为高级导入/导出兜底。
- AstrBot 插件、自定义 API、白名单工具都可以从画布工具箱添加为工作流模块；模块节点会保存 `plugin_name`、`api_id` 或 `tool_name`，并可写入节点提示词、条件和并行分组。
- 工具风险等级可按 AgentSpec 编辑。风险策略是软治理：它会注入 runtime prompt，让 bot 在危险动作前主动请求确认。
- 命令和自然语言启动使用默认 Agent；WebUI 启动使用当前选中的 Agent。

## 触发模式

- `manual`：只接受命令、WebUI 或用户明确要求。
- `confirm`：bot 判断适合进入 Agent Mode 后先请求确认。
- `smart`：低风险多步工作可进入；写文件、shell、部署、删除、关闭插件、读密钥前先确认。
- `always`：可执行多步任务优先进入 Agent Mode；危险动作仍需审批。

这些规则会同步到 `agent-mode` Skill 和 runtime prompt，所以自然语言触发遵循 WebUI 当前 AgentSpec，而不是硬编码的全局行为。

## 健康判断

满足这些条件时，可以认为 Agent Lab 基本健康：

- `agents/` contains a default AgentSpec.
- `default_agent_id.txt` points to an existing AgentSpec.
- `/agentlab start` creates `active_task.json`.
- `/agentlab tick` updates the task markdown.
- `agent_lab_read_state` can return the active task summary.
- `agent_lab_update_state` can write progress and next step.
- `agent_lab_advance_workflow` can move the workflow cursor and task markdown contains `Workflow Cursor`.
- `/agentlab finish` moves a copy to `archives/`.
- Completed/cancelled tasks leave the active Tasks list and remain visible under Archives.
- 独立 WebUI `state` API 返回 agents/tasks/plugins/tools/skills/integrations。
- 独立 WebUI 显示 `bot_label_source`，能确认展示名来自 AstrBot Persona、AstrBot 配置还是兜底值。
- 监控数据包含 `heartbeat_health`；超时或阻塞任务应显示 warning/bad，而不是只显示“心跳已开启”。
- 自定义 API 和凭证库可以保存；凭证列表只显示掩码，只有调用工具内部解密。
- 任务与记忆控制台可以 tick、切换心跳、完成和取消。
- 归档列表显示 completed 或 cancelled 任务。
- 插件与集成页把 AstrBot 插件隔离和外部方案蓝图区分开；AstrBot 全局停用插件不能从 Agent Mode 复活。
- 蓝图精细设置按 `settings_schema.properties` 渲染，并保存到 `module_settings`；复杂字段仍保留高级 JSON。
- Canvas 的“检查工作流”应能发现缺少入口、出口、入口摘要、隔离快照、任务记忆、审批闸门、不可达节点、未绑定 API、被隔离插件和不在白名单中的工具。

Local repository smoke test:

```text
python -m compileall -q .
python scripts/smoke_test.py
python scripts/runtime_smoke_test.py
```
