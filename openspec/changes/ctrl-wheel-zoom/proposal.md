## Why

当前 PDF 阅读器只能在固定缩放下浏览页面：页面图片以 `width:100%` 填满栏宽，用户无法放大查看小字细节，也无法缩小纵览全局。缺少缩放能力限制了阅读体验，尤其在面对字号较小的扫描件或密集排版的 PDF 时。现在添加此功能，是因为它纯前端即可实现、不触及后端渲染管线，且与现有的双栏同步、懒加载、当前页检测架构兼容。

## What Changes

- 新增 Ctrl+滚轮缩放交互：按住 Ctrl 滚动滚轮时以鼠标位置为锚点缩放页面，未按 Ctrl 时滚轮保持正常滚动（不缩放）。
- 缩放范围 25%–400%，每次滚轮步进 10%，到达边界后继续滚动无反应。
- 左右两栏（原文 / 译文）同步缩放，保持与现有滚动同步一致的对照阅读体验。
- 缩放通过改变页面图片 / 占位符的渲染宽度实现（非 CSS `transform: scale`），以真实改变布局流，从而兼容现有的滚动同步（基于 `scrollTop / (scrollHeight - clientHeight)` 的比例同步）和当前页检测（基于 `getBoundingClientRect` 的视口覆盖率）。
- 工具栏新增缩放百分比指示器（实时显示当前缩放比例）与一键重置按钮（回到 100%）。
- 新增前端 `zoom` ES 模块，由 `app.js` 组装接入，遵循现有前端模块化架构。

## Capabilities

### New Capabilities

- `page-zoom`: 通过 Ctrl+滚轮对双栏页面进行同步缩放（25%–400%、步进 10%、鼠标位置锚点），并在工具栏显示缩放百分比与提供一键重置。缩放以改变渲染宽度的方式实现，以兼容现有滚动同步与懒加载几何。

### Modified Capabilities

<!-- 无。本次为新增能力，不改变现有 dual-column-reading / lazy-loading / frontend-modular-architecture 的需求语义：默认 100% 缩放时"图片填满栏宽"等既有行为保持不变，缩放是叠加其上的新行为。 -->

## Impact

- **前端代码**：新增 `static/modules/zoom.js`；修改 `static/app.js`（接入 zoom 模块、在打开 PDF 后启用缩放）；修改 `static/modules/dom.js` 或新增辅助逻辑以按缩放倍数计算占位符 / 图片宽度；修改 `static/style.css`（缩放相关样式、工具栏缩放控件样式）；修改 `templates/index.html`（toolbar 增加缩放百分比与重置按钮元素）。
- **后端代码**：无改动。本次为纯 CSS / 前端缩放，不涉及 `routes.py`、`pdf_renderer.py`、`state.py` 或 DPI 参数。
- **现有交互兼容性**：缩放改变 `scrollHeight`，需确保滚动同步、当前页检测、懒加载 buffer/reclaim 在缩放后仍正常工作；缩放时需抑制 Ctrl+滚轮的默认页面缩放/滚动行为（`preventDefault`）。
- **已知限制**：页面为 200 DPI 栅格 PNG，纯 CSS 放大至 400% 时文字会模糊——本次接受该限制（后续可另开变更升级为高清重渲染）。
- **依赖**：无新增第三方依赖。
