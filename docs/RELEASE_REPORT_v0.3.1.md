# v0.3.1：修复 AstrBot 原生插件页面无法打开

日期：2026-11-10。针对 v0.3.0 原生插件页面白屏、后端没有报错的反馈。

## 原因

AstrBot 4.29.4 的 `PluginViewPage.vue` 使用 `sandbox="allow-scripts allow-forms allow-downloads"`，未开放 `allow-same-origin`。页面因此运行在不透明来源中，读取 `window.sessionStorage` 属性本身就会抛出 `SecurityError`。

v0.3.0 的 App 首次渲染调用 `getToken()`，其中直接读取 `sessionStorage`，导致 React 在发起后端请求前停止渲染。后端日志通常不会记录这个浏览器异常。重新安装相同版本不会改变该代码路径。

## 修复

- 原生 bridge 存在时跳过独立控制台 Token 读取。
- 所有令牌、模板元信息和画布草稿使用统一存储访问器，将获取 Storage 属性、读、写、删全部放在异常保护内。
- 存储不可用时在当前页面内存保留草稿和令牌，删除使用标记防止旧值意外恢复。正式保存的数据仍由后端持久化。
- History API 受限不再中断保存 Token。
- 页面资源加载失败、加载超时或 React 渲染失败时显示可见提示，避免无提示白屏。
- 更新静态检查，禁止组件直接操作 `sessionStorage` / `localStorage`，检查启动错误边界和静态加载提示。

## 检查及部署

通过 TypeScript 类型检查、Vite 生产构建、Python/前端存储访问静态检查和 Git 差异检查。没有启动 AstrBot、浏览器或调用实际模型，部署环境仍由维护者确认。

更新到 v0.3.1 后，关闭旧插件页面并重新打开。无需再次卸载重装。原生 iframe 内存草稿在整个页面重新加载后会丢失，重要修改应点击保存；这不影响已保存的计划和模板。
