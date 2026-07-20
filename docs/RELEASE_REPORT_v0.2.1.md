> 注：AstrBot 最新版已改用 `pages/<page_name>/index.html` 和 `AstrBotPluginPage` bridge。v0.2.1 中 `_dashboard` 的说明已由 v0.2.2 修正。

# Agent Lab v0.2.1 修复与发布报告

- 日期：2026-07-20
- 版本：`v0.2.1`
- 范围：任务结束协议、管理员审批、WebUI 任务控制、长记忆布局、AstrBot 原生插件页面

## 1. 核心结束协议

1. Bot、聊天命令、WebUI 和工作流 `archive_task` 统一进入 verifier。
2. 完成证据不足时创建 `finish_override` 审批，任务进入等待管理员状态。
3. 管理员批准后自动执行归档，不需要 Bot 或用户再次发送 finish。
4. 归档内记录 `finish_decisions` 和 `finish_override_report`，包含批准人、缺失证据、最终状态与总结。
5. 配置 `workflow_admin_ids` 时，非管理员聊天账号无法处理审批。

## 2. WebUI 反馈和任务可控性

- 完成失败返回 `ok: false`，前端保留真实错误和审批 ID。
- 任务页和运行监控均提供：暂停、恢复、完成、停止并归档、彻底删除。
- 彻底删除不直接删活动文件：先关闭心跳、恢复会话插件、归档取消记录，再删除归档和关联记忆。
- 修复 `tasks` 路由误显示方案页的问题。

## 3. 长任务记忆布局

- 列表只显示摘要，完整内容保留在详情。
- 记忆正文 `max-height: 320px` 并独立滚动。
- 详情面板限制在视口高度内并独立滚动。
- 1280x720 实测：页面无水平溢出，详情面板 626px，长正文在 320px 内部滚动。

## 4. AstrBot 原生页面

- 前端资源从 `webui/` 迁移到 `_dashboard/`。
- AstrBot 4.24.2+ 可在 Dashboard 左侧「插件」中直接打开。
- 原生模式 API Base：`/api/plug/astrbot_plugin_agent_lab`。
- 独立模式 API Base：`/api`。
- 独立模式保留对 AstrBot 4.16–4.24.1 的兼容。

## 5. 验证项

- `python -m compileall -q .`
- `python scripts/smoke_test.py`
- `python scripts/runtime_smoke_test.py`
- `node --check pages/agent-lab/app.js`
- `node scripts/subagent_ui_logic_smoke.js`
- 浏览器实测：任务路由、任务操作按钮、长记忆滚动和 1280px 响应式布局。
