# v0.2.9 可复现检查

在仓库根目录执行后端检查（依赖 `quart`，测试使用 Python 3.10 的独立模块；完整 AstrBot 的 Python 版本要求由 AstrBot 自身决定）：

```text
python scripts/static_review.py
python scripts/ui/test_project_runtime.py
python scripts/ui/test_task_continuity.py
```

`test_project_runtime.py` 运行真实 Projects / Storage / TaskControl / WorkspaceAPI / StandaloneWebUIServer 代码，在 TemporaryDirectory 内读写，使用模拟原生会话数据库与平台对象；Quart 使用测试客户端。它不导入完整 AstrBot，不接触真实模型和用户数据库。

`test_project_runtime.py` 共21项，覆盖项目、权限、消息、清理和原生工具上限同步。`test_task_continuity.py` 共16项，覆盖阶段交接、原记录保存、整理失败、分块恢复、模型容量、计划修改与返工证据；其中一项使用本机安装的 AstrBot 原生 ToolLoopAgentRunner，因此还需要可导入的 AstrBot 及其依赖。两套检查都使用确定性模型响应和临时存储，不调用真实模型或生产会话。

前端检查在 Windows、Node 22+、已安装 Microsoft Edge 的环境执行：

```text
cd scripts/ui
npm ci
npm run build
node interactions.mjs
node task-layout-check.mjs
node routing-check.mjs
node browser-check.mjs
```

`fixture.mjs` 提供两台同类型 Bot、三个项目和原工作流节点。真实前端运行在带 `allow-scripts allow-forms allow-downloads`、不带 `allow-same-origin` 的 iframe，API 和 postMessage 主页面桥接为模拟实现。它验证 DOM、坐标、事件与请求负载，不证明生产 AstrBot 端到端联调完成。

- `interactions.mjs`：68项浏览器检查，覆盖导航、身份、项目创建、预案编辑/复制/删除、连线/撤销/重做/删除/保存、管理员交付、清理确认与取消、搜索持久过滤、减少动态效果，以及开发保护中的上下文默认值和设置保存。
- `task-layout-check.mjs`：79项任务布局检查，覆盖1440/1100/820/390四种宽度、全宽详情与清单顺序、消息框滚轮/折叠/阅读位置、消息线下方的途中设置，以及权限框与相邻输入框的80px等高等宽。
- `routing-check.mjs`：6种方向/避障场景，核对有限坐标、正交线段、端口出入方向和障碍物相交。
- `browser-check.mjs`：1440/1100/820 × 900截图、页面边界与素材搜索框遮挡检查。
- `build.mjs`：锁定 XYFlow 版本并生成可离线分发的小体积路径库，检查未引入 D3 运行时代码。

输出写到被 Git 忽略的 `_preview/after-026/`，选定的交付截图与结果保存在 `docs/screenshots/v0.2.6/`。`--before` 仅用于检出 v0.2.4 时收集基线；当前版本请直接运行。

任务布局检查单独输出到 `_preview/task-layout-029/`，含任务详情、消息线、途中设置与开发保护截图及 `results.json`；本版选定截图保存在 `docs/screenshots/v0.2.9/`。

不要把这些 mock 场景当成生产数据或耗时承诺。首次渲染与拖动耗时包含浏览器自动化开销，尚未做千级任务/节点压测。


`export_capabilities.py` 从当前 `main.py` 的节点执行器注册表生成 fixture 能力表，避免前端素材目录和后端执行器名单各自维护。

任务消息测试覆盖：进展开关与限频、问题/审批共线、管理员终态优先、发送失败不自动重发，以及消息记录的独立存储。

## v0.3.1 定向验证

`test_scheme_finish.py` 检查完成证据、交付不自动送审、批准历史、人设继承、只读复用、单轮上限、变量路径和小步骤交接。`full-access-ui-smoke.mjs` 验证图形化开关状态，`scheme-settings-check.mjs` 运行三种宽度下的30项浏览器交互，截图和结果保存在 `docs/screenshots/v0.3.1/`。这组验证不调用真实模型或生产任务。

## v0.3.3 自查与极端模拟

`python scripts/ui/test_context_stress.py` 在临时目录运行7项测试、12个场景，输出 `docs/validation/v0.3.3-context-stress.json`。所有Token数均标记为模拟报告或估算，未调用真实模型。
`node scripts/ui/usage-metrics-check.mjs` 检查桌面/窄屏统计、任务线和文件字符数，截图在 `docs/screenshots/v0.3.3/`。
