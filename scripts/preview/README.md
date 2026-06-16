# webui 无头预览（headless Chromium 截图）

在沙盒里用真实 `app.js`/`style.css` 渲染 webui 并截图，便于无真机时核对前端。数据用 `mockstate.json` 模拟（后端在用户机器上，沙盒没有）。

## 一次性准备（每个新会话跑一次；/tmp 会话结束清空）
```
bash scripts/preview/setup_chromium.sh
# 若提示"未下完"，再次运行同一命令继续（curl 断点续传，单次 bash 调用 ~45s 上限）
```

## 截图
```
LD_LIBRARY_PATH=/tmp/pw/libs node scripts/preview/preview.js            # 默认拍 workflow/integrations/canvas/monitor/memory
LD_LIBRARY_PATH=/tmp/pw/libs node scripts/preview/preview.js workflow   # 只拍某页
```
输出在 `_preview/*.png`（已 gitignore）。workflow 页会自动「整理」+「聚焦内容」再拍。

## 改 mock 数据
编辑 `scripts/preview/mockstate.json`（一个 agent，含各类节点/owner/工具/插件），可加节点测领地、分支、端口等。

## 注意
- 必须用 http（内嵌服务器），不能 file://（浏览器禁止 file:// 下 fetch /api）。
- 外部图标(GAME_ICONS 来自 github raw)在沙盒被 abort，会显示为破图，属正常；真机有网即正常。
