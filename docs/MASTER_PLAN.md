# Agent Lab 画布重构 MASTER PLAN（2026-06-16 定稿）

本文件是本轮重构的权威依据，取代 docs/WORKFLOW_MATERIAL_REWORK_PLAN.md。用户已全量审批，按批次自动实施，本地分批提交。

## 已确认决策
- 自定义 API：`call_api`（一次性调用）与 `api_scope`（框选范围）都保留。
- 变量读写（variable_set / variable_get）：移到「高级功能区」，不进普通素材区；`text_template` 保留普通区。
- 当前版本 build = 20260615-fix7。
- Agent 素材（注册新agent/主Agent/任务分配/报告整理/汇总决策）当前被错误归入「计划与分支」，需独立成 Agent 编排抽屉。
- 自动整理「整理」按钮当前算法过于简单（仅按有无入边粗分级），需重做为带分层算法的高级版。

## 根因记录
- `workflowNodeGroupKey`（app.js ~1487）：别名表 `WORKFLOW_LIBRARY_GROUP_ALIASES` 只含中文键，未含 `agent_collab/flow_timing/data_template` 等英文 group id；导致带这些 library_group 的模板 fall-through 到 `plan_route`。修复：若 `item.library_group` 本身就是合法 group id，直接返回它。
- `entryRule`「触发条件（统一）」盒子（app.js ~6495）挂在所有入口节点上，与消息监听入口自身字段、与专用触发素材重复。
- 前端 `note` 简易字段（app.js ~5901）仍写"No-Op 不影响执行"，与后端 `note→prompt_inject` 执行器（main.py ~2191）矛盾。
- app.js 体积 >426KB，禁止用 Edit 工具（会被磁盘截断）；一律 bash 原子写 + `node --check`。

---

## 批次 A：触发入口去重（后端/编辑器语义）
- 删除 `entryRule`「触发条件（统一）」整块，不再挂任何入口节点。
- 消息监听入口（listen_message）自身填空字段补齐：监听时机、命令别名/斜杠命令、暗号(精确短语)、关键词(模糊)、正则、自然语言判断开关、进入前确认+确认话术。→ 同时支持模糊关键词与命令。
- 插件事件入口/复杂定时入口/Webhook 入口：各只保留自己来源字段，不出现触发类型勾选。
- 保存方案时由各入口节点归一化生成 `workflow_trigger`/`workflow_scope`，不再依赖统一盒子。
- 加载旧方案：把旧 workflow_trigger 的消息/暗号/关键词/正则迁移进消息监听入口节点字段。

## 批次 B：插件事件入口补齐 + 触发进入端口
- 插件事件入口加插件选择器（下拉已注册/启用插件）+ 事件名列表 + 匹配方式（已有字段，补 UI 选择器）。
- 触发类节点（trigger）补"左侧进入端口"语义，使其能在连线上与插件事件源/上游对应。

## 批次 C：Agent 编排独立分类 + 主Agent 领地
- 修 `workflowNodeGroupKey`：library_group 是合法 group id 时直接返回。
- 确认 `agent_collab` 在素材库作为独立可折叠分类渲染（注册新 Agent / 主 Agent / 任务分配 / 报告整理 / 意见传达 / 事项讨论 / 汇总决策）。
- 主 Agent 节点补"选领地"按钮 + 颜色字段（与子Agent 一致）。
- 清掉残留子Agent 注册抽屉 / 框选指派逻辑（workflowSubAgentOpen 等）。

## 批次 D：便签 / 变量 / 高级编辑器收口
- `note` 统一为「提示注入」：删 No-Op 描述，简易字段=注入文本+注入范围；补输入/输出端口（校验已要求）。
- 变量读写素材移入「高级功能区」（仅 advanced 库模式可见或归入 data_template-advanced）。
- 高级编辑器：锁定 id/kind/action 等破坏语义字段为只读，其余 Schema/重试/超时保留为调试区。

## 批次 E：高级自动整理算法
- 用拓扑分层（最长路径 rank）替代"有无入边"粗分。
- 分支二级出口的接管头降到次级层。
- 人工接管(handoff)/重试(retry) 不参与主链顺排，按依附关系靠边布置。
- 同 owner 的 Agent 领地节点聚簇，不被打散到不同列。
- 入口在最左，出口在最右；并行分支同列展开。

## 批次 F：子Agent 圈地交互重做（前端）
- 点卡片"选领地"→ 自动切换到框选工具 → 拖出框选区 → 区域染成该 Agent 颜色 → 把节点拖进区域即归属该 Agent。
- 透明度自调，简洁大方；可借助 ui-ux-pro-max skill。
- Agent 领地颜色 = 卡片颜色；突出用透明度/描边边框。
- 主 Agent 也可选颜色。

## 批次 G：右侧工具栏抽屉化（前端）
- 框选标签单独移到下方。
- 点框选后，移动/复制/删除/完成 以抽屉推拉+动画弹出，默认隐藏。

## 批次 H：素材库 / 小地图 / 顶栏 / 导航美化（前端）
- 去掉素材库顶部"模块库/节点素材"标题占位，省空间。
- 素材库面板上下延伸加高，便于查找。
- 小地图重设计：大框与节点配色区分，简洁。
- 顶栏 nav-toggle 加阴影/白边提示，平常可见。
- 左导航展开改为覆盖画布（绝对定位浮层），不推拉整页、不位移。
- 导航展开态与日常侧栏字号统一，消除收缩抖动。

## 批次 I：重做「注册工具」页面（前端，从零重构）
- 删除现有注册工具页面（含点绿按钮自动滚顶 bug 的烂代码）。
- 从零重做：清晰的来源插件分组、工具开关、搜索、右侧详情/操作区，有实际操作意义。

## 批次 J：校验与本地提交
- 每批：`node --check webui/app.js` + `python -m py_compile main.py`。
- 关键界面用沙盒 headless 截图复核（复用 outputs/preview_webui.sh）。
- 每批 git 本地提交，提交信息描述该批改动。
