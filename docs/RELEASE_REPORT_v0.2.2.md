# Agent Lab v0.2.2 AstrBot 插件页面兼容修复报告

- 日期：2026-07-20
- 版本：`v0.2.2`
- 根因：AstrBot 最新版已使用 `pages/<page_name>/index.html` 发现插件页面，`_dashboard/` 目录不再是最新插件页面入口。

## 修复内容

1. 页面迁移到 `pages/agent-lab/index.html`。
2. 独立控制台的 `static_dir` 同步指向 `pages/agent-lab`。
3. 原生插件页面使用 `window.AstrBotPluginPage`：
   - `apiGet(endpoint, params)` 处理 GET；
   - `apiPost(endpoint, body)` 处理 POST；
   - `ready()` 确保 bridge 已就绪；
   - `requestResize()` 同步 iframe 高度。
4. API 端点传入 bridge 时使用相对路径，例如 `state`、`task/finish`。
5. `/api/task/logs?task_id=...` 等请求会将 query 解析为 params 对象，避免 bridge 拒绝 endpoint 中的 query/hash。
6. 未注入 bridge 时自动回退到独立控制台 `/api` fetch 模式。

## 打开方式

1. 在 AstrBot Dashboard 打开「插件管理」。
2. 找到 Agent Lab。
3. 打开插件详情。
4. 进入 `agent-lab` 自定义页面。

## 回归验证

- `python -m compileall -q .`
- `python scripts/smoke_test.py`
- `python scripts/runtime_smoke_test.py`
- `node --check pages/agent-lab/app.js`
- `node scripts/subagent_ui_logic_smoke.js`
- `node scripts/plugin_page_bridge_smoke.js`
