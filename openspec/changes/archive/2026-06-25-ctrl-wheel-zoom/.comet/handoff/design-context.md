# Comet Design Handoff

- Change: ctrl-wheel-zoom
- Phase: design
- Mode: compact
- Context hash: 57850b0adbe116828cca037b27a6536656498e50ee72d13887bee02aeae0a62a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/ctrl-wheel-zoom/proposal.md

- Source: openspec/changes/ctrl-wheel-zoom/proposal.md
- Lines: 1-30
- SHA256: adc8c36b2556eed4702b5549cba75781eb8ffc7d581fb47c9823c9b77962fd41

```md
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
```

## openspec/changes/ctrl-wheel-zoom/design.md

- Source: openspec/changes/ctrl-wheel-zoom/design.md
- Lines: 1-76
- SHA256: 798bed450f2c80ab6bbb6df76cd721160e3a46b474db19880d0e8c7856655105

```md
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
```

## openspec/changes/ctrl-wheel-zoom/tasks.md

- Source: openspec/changes/ctrl-wheel-zoom/tasks.md
- Lines: 1-38
- SHA256: 743a1a6e9b340464a09cd12ebcff635fc1fcc118304b7a6c6d2d8e708f7b3597

```md
## 1. CSS 缩放基础

- [ ] 1.1 在 `static/style.css` 中为 `#app`（或 `.column`）建立 `--zoom` CSS 变量（默认 `1`），并为 `.page-container img` 与 `.page-placeholder` 设置 `width: calc(100% * var(--zoom, 1))`（覆盖 img 现有 `width:100%`）
- [ ] 1.2 在 `static/style.css` 中将 `.page-placeholder` 的高度改为 `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1))`，移除对内联 `padding-bottom` 的依赖
- [ ] 1.3 将 `.column` 的 `overflow-x` 由 `hidden` 改为 `auto`；将 `.page-container` 的 `justify-content` 由 `center` 改为 `safe center`

## 2. 占位符改造为 CSS 变量驱动

- [ ] 2.1 修改 `static/modules/dom.js` 的 `createPageEl`：用 `placeholder.style.setProperty('--page-ratio', '${ph}%')` 替换 `placeholder.style.paddingBottom = '${ph}%'`
- [ ] 2.2 修改 `static/modules/lazy-loader.js` 的 `unloadPageImage`（在 `app.js` 中）：重建占位符时同样设置 `--page-ratio` 而非内联 `padding-bottom`
- [ ] 2.3 验证 100% 缩放下占位符宽高比与改动前一致（无视觉回归）

## 3. zoom 模块

- [ ] 3.1 新增 `static/modules/zoom.js`，导出 `setupZoom({ columns, appEl, onZoomChange })`，内部维护 zoom 状态（初始 1）、`MIN=0.25`、`MAX=4`、`STEP=0.1`
- [ ] 3.2 在 `setupZoom` 中为每个 column 注册 `wheel` 监听：仅当 `e.ctrlKey` 为真时 `preventDefault` 并按 `e.deltaY` 符号增减一步，clamp 到 `[MIN,MAX]`；非 Ctrl 时不动 zoom、不阻止默认滚动
- [ ] 3.3 实现鼠标锚点滚动重算：`r = newZoom/oldZoom`，`newScrollTop = (scrollTop + cy)*r - cy`、`newScrollLeft = (scrollLeft + cx)*r - cx`；先设 `appEl.style.--zoom` 再设主动栏 `scrollLeft/scrollTop`（依赖现有 scroll-sync 把另一栏拉到同分数位置）
- [ ] 3.4 导出 `resetZoom()`（回到 1 并触发重排 + 锚定到顶部）、`getZoom()`、`dispose()`（移除 wheel 监听）；每次 zoom 变化调用 `onZoomChange(zoom)`

## 4. 工具栏缩放控件与接入

- [ ] 4.1 在 `templates/index.html` 的 `#toolbar` 中增加 `<span id="zoom-level">100%</span>` 与 `<button id="zoom-reset">重置缩放</button>`
- [ ] 4.2 在 `static/modules/dom.js` 的 `getElements` 中增加 `zoomLevel`、`zoomReset` 引用
- [ ] 4.3 在 `static/app.js` 的 `openPdf` 成功后调用 `setupZoom`，传入 `[els.leftCol, els.rightCol]`、`appEl`、`onZoomChange`；`onZoomChange(z)` 更新 `els.zoomLevel.textContent = Math.round(z*100) + '%'`
- [ ] 4.4 在 `app.js` 中为 `els.zoomReset` 绑定点击 → 调用 zoom 实例的 `resetZoom()`；打开新 PDF 时 `dispose` 旧实例

## 5. 前端测试

- [ ] 5.1 在 `static/modules/zoom.js` 中增加内联测试（`window.__TEST_ZOOM__` 门控）：覆盖 Ctrl+wheel 增减、非 Ctrl 不缩放、边界 clamp、锚点公式数值正确、reset 回到 1、onZoomChange 被调用
- [ ] 5.2 新增 `tests/run-zoom-tests.mjs`（仿 `run-lazy-loader-tests.mjs`：jsdom + 剥离 export + 设 `__TEST_ZOOM__` + 校验 `__ZOOM_TESTS_DONE__` 与 PASS/FAIL 退出码）
- [ ] 5.3 在 `package.json` 增加 `"test:zoom": "node tests/run-zoom-tests.mjs"` 脚本
- [ ] 5.4 运行 `node tests/run-zoom-tests.mjs` 通过；并运行既有 `node tests/run-lazy-loader-tests.mjs`、`node tests/run-task-4.5-tests.mjs`、`npm run test:translator` 确认无回归

## 6. 整体验证

- [ ] 6.1 运行 `ruff check .` 通过（确认未误改 Python 文件或无新增违规）
- [ ] 6.2 运行 `pytest` 通过（确认后端无回归）
- [ ] 6.3 手动验证：打开 PDF，Ctrl+滚轮缩放以光标为锚点、左右栏同步；25%–400% 边界停止；非 Ctrl 滚轮正常滚动；工具栏显示百分比；重置按钮回 100%；缩放后滚动同步 / 当前页检测 / 懒加载正常
```

## openspec/changes/ctrl-wheel-zoom/specs/page-zoom/spec.md

- Source: openspec/changes/ctrl-wheel-zoom/specs/page-zoom/spec.md
- Lines: 1-109
- SHA256: a5e4835e17ee555e3096fd9232f916ef6e0e7013eb5c5866dc346b8efb1072af

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Ctrl+wheel page zoom

The system SHALL allow the user to zoom the dual-column page view by holding Ctrl and rolling the mouse wheel. A wheel event SHALL trigger zoom only when `e.ctrlKey` is true; when Ctrl is not held, the wheel SHALL behave as normal scrolling (no zoom, no `preventDefault` on the native scroll). The zoom SHALL be applied by changing the rendered width of page images and placeholders (via a CSS `--zoom` variable), NOT by CSS `transform: scale`, so that layout flow (`scrollHeight`) changes and existing scroll-sync / page-detection geometry remains valid. The `zoom` frontend module SHALL own this logic.

#### Scenario: Zoom in with Ctrl+wheel

- **WHEN** the user holds Ctrl and scrolls the wheel upward over a column
- **THEN** the zoom level SHALL increase by one step (10%), applied to both columns, and the page images/placeholders SHALL render wider by the new factor

#### Scenario: Zoom out with Ctrl+wheel

- **WHEN** the user holds Ctrl and scrolls the wheel downward over a column
- **THEN** the zoom level SHALL decrease by one step (10%), applied to both columns, and the page images/placeholders SHALL render narrower by the new factor

#### Scenario: Normal scroll unaffected when Ctrl not held

- **WHEN** the user scrolls the wheel without holding Ctrl over a column
- **THEN** the column SHALL scroll normally and the zoom level SHALL NOT change, and the native scroll SHALL NOT be prevented

### Requirement: Zoom range and step

The system SHALL constrain zoom to the range 25%–400% inclusive, in steps of 10%. A wheel notch that would exceed the upper or lower bound SHALL clamp to the bound and have no further effect (no overshoot, no scrolling past the bound).

#### Scenario: Upper bound clamping

- **WHEN** the zoom is at 400% and the user zooms in further with Ctrl+wheel
- **THEN** the zoom SHALL remain at 400% and no additional increase SHALL occur

#### Scenario: Lower bound clamping

- **WHEN** the zoom is at 25% and the user zooms out further with Ctrl+wheel
- **THEN** the zoom SHALL remain at 25% and no additional decrease SHALL occur

### Requirement: Cursor-anchored zoom

The system SHALL anchor zoom at the cursor position so the content point under the cursor remains under the cursor after zooming. For a zoom change from `z0` to `z1` with ratio `r = z1/z0` and cursor offset `(cx, cy)` relative to the active column, the new scroll positions SHALL be `newScrollTop = (scrollTop + cy) * r - cy` and `newScrollLeft = (scrollLeft + cx) * r - cx`. The `--zoom` variable SHALL be applied before setting the new scroll positions.

#### Scenario: Content under cursor stays fixed

- **WHEN** the user positions the cursor over a specific word and zooms in with Ctrl+wheel
- **THEN** that word SHALL remain under the cursor after the zoom completes

#### Scenario: Vertical alignment preserved across columns

- **WHEN** the user zooms with Ctrl+wheel over one column
- **THEN** the other column SHALL synchronize to the same fractional vertical position via the existing scroll-sync, so both columns remain vertically aligned at the same content point

### Requirement: Synchronized zoom across columns

The system SHALL apply the same zoom factor to both the left (original) and right (translated) columns simultaneously. Both columns SHALL use the same `--zoom` value.

#### Scenario: Both columns zoom together

- **WHEN** the user zooms in or out with Ctrl+wheel over either column
- **THEN** both columns SHALL display at the same new zoom factor

### Requirement: Zoom indicator and reset control

The floating toolbar SHALL display the current zoom level as a percentage (e.g. "120%"), updated in real time as zoom changes. The toolbar SHALL provide a reset control that, when activated, returns the zoom to 100%.

#### Scenario: Zoom percentage displayed

- **WHEN** the zoom level changes to 130%
- **THEN** the toolbar zoom indicator SHALL display "130%"

#### Scenario: Reset to 100%

- **WHEN** the user activates the reset control while zoomed to a non-100% level
- **THEN** the zoom SHALL return to 100% and the indicator SHALL display "100%"

#### Scenario: Reset preserves current view

- **WHEN** the user activates the reset control while zoomed to a non-100% level
- **THEN** the zoom SHALL return to 100% anchored at the viewport center (ratio `r = 1/oldZoom`, anchor `(clientWidth/2, clientHeight/2)`), so the content currently at the center of the viewport SHALL remain at the center and the reading position SHALL be preserved

#### Scenario: Initial zoom indicator

- **WHEN** a PDF is opened
```

Full source: openspec/changes/ctrl-wheel-zoom/specs/page-zoom/spec.md

