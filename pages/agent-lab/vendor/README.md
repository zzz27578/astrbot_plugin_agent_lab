# 连线路径来源

`connectors.js` 来自 [xyflow/xyflow](https://github.com/xyflow/xyflow) 的 `@xyflow/system@0.0.74`，使用 `getSmoothStepPath`、`getBezierPath`、`Position`。对应 React Flow / Svelte Flow 共用内核，许可为 [MIT](XYFLOW-LICENSE)。

仅分发路径算法，不分发 React/Svelte UI 或 D3 运行时；原画布坐标、拖拽、领地和模块数据继续由 Agent Lab 管理。普通边使用圆角折线，拖拽预览使用贝塞尔曲线；用户保存的手工 `route_hint` 继续优先。

在 `scripts/ui` 执行 `npm ci`、`npm run build` 可重建。构建脚本将未用 D3 导入标记为无副作用，防止公共入口间接加载 D3 transition 注册；同时检查产物，一旦出现 D3 代码便报错，必须先审查用途和相应许可证。

安装插件不需要构建，也不依赖外部 CDN。
