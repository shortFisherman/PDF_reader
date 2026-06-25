## Context

PDF 阅读器为 Flask + 前端 ES 模块架构：服务端按固定 `config.DPI`（200）将每页渲染为 PNG，前端在双栏（左原文 / 右译文）中按 `width:100%` 显示，配合懒加载（IntersectionObserver + 150ms settle gate）、比例滚动同步（`scrollTop/(scrollHeight-clientHeight)`）和当前页检测（`getBoundingClientRect` 视口覆盖率）。当前无任何缩放能力。

关键约束：缩放必须与现有的滚动同步、当前页检测、懒加载几何兼容，且本次为纯前端方案（不动后端 / DPI）。

## Goals / Non-Goals

**Goals:**
- Ctrl+滚轮缩放，鼠标位置为锚点，左右栏同步。
- 范围 25%–400%，步进 10%，边界停止。
- 工具栏显示缩放百分比 + 一键重置 100%。
- 不破坏滚动同步、当前页检测、懒加载。

**Non-Goals:**
- 不做服务端高清重渲染（DPI 参数）——放大较多时栅格 PNG 模糊为已知限制。
- 不做触控板 pinch、不持久化缩放（刷新回 100%）。
- 不做水平滚动同步（左右栏横向独立）。

## Decisions

### 决策 1：用"改变渲染宽度"实现缩放，而非 CSS `transform: scale`

**选择**：通过 CSS 变量 `--zoom` 驱动页面图片 / 占位符的 `width: calc(100% * var(--zoom))`，真实改变布局流。

**理由**：`transform: scale` 不影响布局流（`scrollHeight` 不变），会破坏滚动同步（依赖 `scrollHeight`）和当前页检测（依赖真实 `getBoundingClientRect` 高度）。改变宽度则 `scrollHeight` 随缩放线性变化，现有几何计算自然兼容。

**备选**：`transform: scale` + 手动补偿容器高度——更复杂且易与懒加载/同步打架，放弃。

### 决策 2：CSS 变量驱动，避免逐元素更新内联样式

**选择**：在 `#app` 上设置 `--zoom`（默认 1）；占位符内联设置 `--page-ratio: <ph>%`（每文档固定的宽高比）。CSS 统一计算：
- `.page-container img, .page-placeholder { width: calc(100% * var(--zoom, 1)); }`
- `.page-placeholder { padding-bottom: calc(var(--page-ratio) * var(--zoom, 1)); }`

**理由**：占位符用 `padding-bottom` 百分比保持宽高比，而百分比相对*包含块*宽度（栏宽）。将 `--page-ratio` 与 `--zoom` 同乘，使 width 与 padding-bottom 相对同一包含块同步缩放，宽高比恒定（推导：height = 栏宽·(ph/100)·zoom，width = 栏宽·zoom，比值 = ph/100 不变）。只需改一个 `--zoom` 变量即可让全部（含 ~1000 个）占位符与图片同步重排，性能远优于逐元素改内联样式。

**集成改动**：`dom.js` 的 `createPageEl` 与 `lazy-loader.js` 的 `unloadPageImage` 现以 `placeholder.style.paddingBottom = '${ph}%'` 设高度，需改为 `placeholder.style.setProperty('--page-ratio', '${ph}%')`，并把 `padding-bottom` 移入 CSS（删除内联 paddingBottom）。

### 决策 3：鼠标锚点缩放的滚动位置重算

**选择**：缩放从 `z0 → z1` 时，对光标所在栏 `col`，令 `r = z1/z0`，以光标相对栏的 `(cx, cy)` 为锚点：
- `newScrollTop = (col.scrollTop + cy) * r - cy`
- `newScrollLeft = (col.scrollLeft + cx) * r - cx`

设置顺序：先设 `--zoom`（触发重排、`scrollHeight` 线性变化），再设 `col.scrollLeft / col.scrollTop` 为锚点值。

**理由**：所有内容高度/宽度均 ∝ zoom，故内容点的*分数位置*在缩放前后不变。公式保持"光标下的内容点"留在光标下。`scrollTop` 设置会触发现有 `scroll` 事件 → 经 `scroll-sync` 的比例同步把另一栏拉到相同分数位置；因两栏内容与缩放一致，相同分数 = 相同内容点 = 两栏对齐。复用现有同步，无需为缩放另写跨栏逻辑。

**备选**：对两栏分别套用相同锚点公式——可行但与现有 `syncing` 标志 + `setTimeout(0)` 的同步机制可能产生轻微竞争，故选择"仅设主动栏 + 复用同步"。

### 决策 4：>100% 缩放时的横向溢出处理

**选择**：
- `.column` 由 `overflow-x: hidden` 改为 `overflow-x: auto`（100% 时无溢出故无滚动条，行为不变）。
- `.page-container` 由 `justify-content: center` 改为 `justify-content: safe center`：内容能放下时居中，溢出时退化为 `start`，使左侧可横向滚动到达（规避 flex 居中溢出时左缘不可达的已知问题）。

**理由**：>100% 时页面宽于栏，需可横向滚动查看；`safe center` 兼顾 <100% 居中美感与 >100% 可达性。`safe` 关键字在主流现代浏览器已支持；不支持时退化为普通 `center`，属可接受的渐进降级。

### 决策 5：新增独立 `zoom` ES 模块，由 `app.js` 组装

**选择**：新增 `static/modules/zoom.js`，导出 `setupZoom({ columns, onZoomChange })`，返回 `{ resetZoom, getZoom, dispose }`。`app.js` 在 `openPdf` 成功后调用，并把 `onZoomChange(zoom)` 接到工具栏百分比显示与重置按钮。

**理由**：遵循 `frontend-modular-architecture` 约定——`app.js` 为瘦入口，按职责拆分模块。缩放是独立职责，单独成模块便于测试与维护。

### 决策 6：工具栏缩放控件

**选择**：`templates/index.html` 的 `#toolbar` 增加 `<span id="zoom-level">100%</span>` 与 `<button id="zoom-reset">重置缩放</button>`；`dom.js` 的 `getElements` 增加这两个引用；`app.js` 在 `onZoomChange` 中更新 `zoom-level` 文本，`zoom-reset` 点击调用 `resetZoom()`。

## Risks / Trade-offs

- **[放大模糊]** 200 DPI 栅格 PNG 在 400% 时文字发糊 → 本次接受；后续可另开"高清重渲染"变更（`/api/page` 加 DPI 参数）升级，届时 `zoom` 模块的 `onZoomChange` 可驱动防抖重请求。
- **[锚点精度]** 栏 padding(20px) 与 page-container margin(16px) 不随 zoom 缩放，锚点公式存在微小漂移 → 步进 10% 下漂移可忽略；如需精确可在公式中扣除常量，暂不做。
- **[横向不同步]** 仅主动栏横向锚定，另一栏横向独立 → 仅在 >100% 且手动横滚时可见，对照阅读主依赖纵向对齐，可接受。
- **[与懒加载 buffer 交互]** 放大后单页更高，`BUF=2` 页覆盖像素范围变大，可能多加载几页 → 现有逻辑基于元素高度自适应，无需改动；属可接受的行为。
- **[`safe center` 兼容]** 旧浏览器退化为 `center`，>100% 时左缘不可达 → 目标为现代桌面浏览器，可接受；必要时可加 JS 兜底。
