---
change: ctrl-wheel-zoom
design-doc: docs/superpowers/specs/2026-06-25-ctrl-wheel-zoom-design.md
base-ref: 905840f80cd876795d1910d2d58a99654bbec1a6
archived-with: 2026-06-25-ctrl-wheel-zoom
---

# Implementation Plan — Ctrl+滚轮页面缩放

> 任务清单以 `openspec/changes/ctrl-wheel-zoom/tasks.md` 为准（6 组、21 项）。本计划补充执行顺序、依赖、每步实现要点与验证手段。设计与方案依据见 `docs/superpowers/specs/2026-06-25-ctrl-wheel-zoom-design.md`（CSS 变量 `--zoom` 驱动渲染宽度，复用既有 scroll-sync / page-detection）。

## 执行顺序与依赖

```
组1 CSS 缩放基础 ─┐
                 ├──► 组3 zoom 模块 ──► 组4 工具栏控件与接入 ──► 组5 前端测试 ──► 组6 整体验证
组2 占位符改造  ─┘
```

- 组1（`--zoom`/`--page-ratio` CSS 变量 + `.column`/`.page-container` 布局）与组2（`dom.js createPageEl`、`app.js unloadPageImage` 改设 `--page-ratio`）无相互依赖，可并行；但二者都是组3 的前置——zoom 模块写 `--zoom` 必须先有 CSS 规则消费它，占位符必须由 `--page-ratio` 驱动才能随缩放等比缩放。
- 组3（`zoom.js setupZoom`）依赖组1+组2；其 `setupZoom`/`resetZoom`/`dispose` 接口是组4 接入的前置。
- 组4（`index.html` 工具栏 + `dom.js getElements` + `app.js` 接线）依赖组3。
- 组5 单测主要测 `zoom.js`（依赖组3 完成），`package.json` 脚本与回归依赖组4；组5 必须在组6 之前。
- 组6 整体验证（ruff/pytest/手动）最后，确认无后端回归与端到端表现。

## 实现要点（按 tasks.md 编号）

### 组1 CSS 缩放基础
- 1.1 `static/style.css` `#app`（第 14 行）规则内加 `--zoom: 1;`（默认值）。为 `.page-container img`（第 37-43 行）与 `.page-placeholder`（第 45-54 行）各加 `width: calc(100% * var(--zoom, 1));`，覆盖 img 现有 `width: 100%`（第 38 行）与 placeholder 现有 `width: 100%`（第 46 行）。用 `var(--zoom, 1)` 兜底以容错未设置场景。
- 1.2 `.page-placeholder` 加 `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1));`，移除对内联 `padding-bottom` 的依赖（内联值由组2 改为设 `--page-ratio`）。宽高比保持推导见设计文档第 86-93 行：`height/width = ph/100`，与 zoom 无关。
- 1.3 `.column`（第 20-25 行）`overflow-x: hidden`（第 23 行）→ `auto`，使 >100% 横向可滚；`.page-container`（第 31-35 行）`justify-content: center`（第 34 行）→ `safe center`，<100% 居中、>100% 左缘可达（spec scenario "Zoomed-in page is horizontally scrollable" / "Zoomed-out page remains centered"）。

### 组2 占位符改造为 CSS 变量驱动
- 2.1 `static/modules/dom.js` `createPageEl`（第 49-64 行）第 59 行 `placeholder.style.paddingBottom = '${ph}%'` → `placeholder.style.setProperty('--page-ratio', '${ph}%')`。
- 2.2 `static/app.js` `unloadPageImage`（第 122-136 行）第 131 行 `placeholder.style.paddingBottom = '${ph}%'` → `placeholder.style.setProperty('--page-ratio', '${ph}%')`。（tasks.md 写 lazy-loader.js，实际逻辑在 app.js，设计文档第 72-73 行已明确，按 app.js 改。）
- 2.3 100% 下 `--zoom` 默认 1，`padding-bottom: calc(var(--page-ratio) * 1) = ph%`，与改动前完全一致；目视复核占位符高度不变即可。

### 组3 zoom 模块
- 3.1 新增 `static/modules/zoom.js`：`export function setupZoom({ columns, appEl, onZoomChange })`。常量 `const MIN = 0.25; const MAX = 4; const STEP = 0.1;`，内部 `let zoom = 1;`。返回 `{ resetZoom, getZoom, dispose }`。
- 3.2 每个 column `addEventListener('wheel', handler, { passive: false })`（必须显式 `passive:false`，否则 `preventDefault` 无效）。handler：`if (!e.ctrlKey) return;`（放行普通滚动，不 preventDefault）；`e.preventDefault();`；`const dir = Math.sign(e.deltaY);`；`const newZoom = Math.min(MAX, Math.max(MIN, zoom - dir * STEP));`（deltaY>0 滚轮向下 → 缩小，deltaY<0 向上 → 放大，符合 spec scenario；设计文档第 30 行注解有歧义，以 spec 为准）。若 `newZoom === zoom` 直接 return（边界无反应）。
- 3.3 锚点公式：`const r = newZoom / zoom;`；`const rect = col.getBoundingClientRect(); const cx = e.clientX - rect.left; const cy = e.clientY - rect.top;`；先 `appEl.style.setProperty('--zoom', String(newZoom));` 触发重排，再 `col.scrollTop = (col.scrollTop + cy) * r - cy;` 与 `col.scrollLeft = (col.scrollLeft + cx) * r - cx;`；`zoom = newZoom;`；`onZoomChange(zoom);`。仅设主动栏 scroll，既有 `setupScrollSync`（scroll-sync.js 第 50 行）以分数 `scrollTop/(scrollHeight-clientHeight)` 同步另一栏至同一内容点（设计文档第 36-48 行）。
- 3.4 `resetZoom()`：以主动栏视口中心为锚点 `cx = col.clientWidth / 2; cy = col.clientHeight / 2;`，`r = 1 / zoom;`，套同一公式（设 `--zoom=1` 再设 scroll），`zoom = 1;`，`onZoomChange(1);` —— 保持当前视图（spec "Reset preserves current view"；tasks.md 3.4 "锚定到顶部" 与 spec 冲突，以 spec / 设计文档第 58 行为准）。`getZoom()` 返回 `zoom`。`dispose()` 对每个 column `removeEventListener('wheel', handler)`。

### 组4 工具栏缩放控件与接入
- 4.1 `templates/index.html` `#toolbar`（第 22-28 行）内增加 `<span id="zoom-level">100%</span>` 与 `<button id="zoom-reset">重置缩放</button>`（置于 `#page-indicator` 与 `#prompt-toggle` 之间，沿用既有 toolbar 视觉）。
- 4.2 `static/modules/dom.js` `getElements`（第 3-39 行）加 `const zoomLevel = document.getElementById('zoom-level');` 与 `const zoomReset = document.getElementById('zoom-reset');`，并加入 `_cache`（第 21-36 行）。
- 4.3 `static/app.js` 顶部 import 增加 `import { setupZoom } from './modules/zoom.js';`；模块顶层加 `let zoomInst = null;`。`openPdf` 成功路径（约第 88 行 `loadTranslatedState()` 前）调用 `zoomInst = setupZoom({ columns: [els.leftCol, els.rightCol], appEl: els.appView, onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; } });`，并立即 `els.zoomLevel.textContent = '100%';`（spec "Initial zoom indicator"）。
- 4.4 `app.js` 中 `els.zoomReset.addEventListener('click', () => { if (zoomInst) zoomInst.resetZoom(); });`（在 `init` 或 `openPdf` 内绑定一次即可）。`openPdf` 开头清理段（第 38-39 行 `io`/`settle` 旁）加 `if (zoomInst) { zoomInst.dispose(); zoomInst = null; }`，避免打开新 PDF 时旧 wheel 监听残留。

### 组5 前端测试
- 5.1 `static/modules/zoom.js` 末尾加 `if (typeof window !== 'undefined' && window.__TEST_ZOOM__) { ... }` 内联测试块（仿 `lazy-loader.js` 第 74-181 行模式：`assert` + `passCount/failCount` + 末尾 `globalThis.__ZOOM_TESTS_DONE__ = true`）。断言：① Ctrl 门控——非 Ctrl wheel 不改 zoom 且不调 `preventDefault`，Ctrl wheel 调 `preventDefault` 并增减；② 步进/范围——`deltaY<0` 放大 +0.1、`deltaY>0` 缩小 -0.1、`MIN=0.25`/`MAX=4` clamp、边界再滚无变化；③ 锚点公式——mock `col.scrollTop/scrollHeight/scrollLeft/clientWidth/clientHeight` 与 `getBoundingClientRect`/`clientX/clientY`，断言 `newScrollTop=(scrollTop+cy)*r-cy`、`newScrollLeft` 同式数值正确；④ `onZoomChange` 被调用且参数 = newZoom；⑤ `resetZoom()` 后 `getZoom()===1`；⑥ `dispose()` 后再 dispatch wheel 不再改 zoom、不再调 `onZoomChange`。
- 5.2 新增 `tests/run-zoom-tests.mjs`，仿 `run-lazy-loader-tests.mjs`：`new JSDOM(...)` + `globalThis.window/document`；`code.replace(/^export\s+/gm, '')` 剥离 export；`jsdomWindow.__TEST_ZOOM__ = true`；`new Function('window','document','globalThis','setTimeout','console', code)` 执行；收集 logs/errors；校验 `globalThis.__ZOOM_TESTS_DONE__` 且文本无 `FAILED`/`FAIL:` → `process.exit(0)`，否则 `process.exit(1)`。
- 5.3 `package.json` `scripts`（第 10-12 行）加 `"test:zoom": "node tests/run-zoom-tests.mjs"`。
- 5.4 运行 `node tests/run-zoom-tests.mjs` 通过；回归 `node tests/run-lazy-loader-tests.mjs`、`node tests/run-task-4.5-tests.mjs`、`npm run test:translator`（占位符改造影响 lazy-loader，须确认无回归）。

### 组6 整体验证
- 6.1 `ruff check .` 通过（确认未误改 Python 文件或无新增违规）。
- 6.2 `pytest` 通过（确认后端无回归）。
- 6.3 手动验证（见下「验证手段」）。

## 测试策略

- **jsdom 单元测试**（`zoom.js` 内联 `__TEST_ZOOM__` 块 + `tests/run-zoom-tests.mjs` runner）：纯逻辑测试，覆盖 Ctrl 门控、步进/范围 clamp（25%–400%、10%）、锚点公式数值（mock scroll 几何）、`onZoomChange` 调用、`reset` 回到 1、`dispose` 移除监听。jsdom 不按 CSS 计算布局，几何/视觉表现靠手动验证。
- **回归**：`node tests/run-lazy-loader-tests.mjs`、`node tests/run-task-4.5-tests.mjs`、`npm run test:translator`（占位符 `--page-ratio` 改造影响 lazy-loader，须确认无回归）+ `ruff check .` + `pytest`。
- **手动验证**：见下「验证手段」。

## 验证手段

- **光标锚点**：将光标置于某词上，Ctrl+滚轮放大/缩小，该词保持在光标下。
- **双栏同步**：在一栏 Ctrl+滚轮，另一栏经既有 scroll-sync 保持纵向对齐（同内容点）。
- **范围边界**：缩到 25% 或放到 400% 后继续同向滚轮，无反应、不 overshoot。
- **>100% 横向溢出**：放大到 >100%，页面宽于栏，可横向滚动到左/右缘；<100% 时页面居中、无横向滚动条。
- **既有功能不回归**：缩放后滚动同步、当前页检测（`#page-indicator`）、懒加载（`/api/page/*` 按需请求）均正常。
- **非 Ctrl 滚轮**：普通滚轮正常纵向滚动，zoom 不变、不 preventDefault。
- **工具栏**：打开 PDF 时 `#zoom-level` 显示 `100%`；缩放时实时更新百分比；`#zoom-reset` 点击回 100% 且当前视图（视口中心内容）保持。
- **重置保持视图**：缩放后点重置，视口中心的内容点仍居中，阅读位置不丢。

## 隔离与提交

- 在专用 feature 分支上工作，逐组提交，commit message 前缀 `feat:`，例如：
  - `feat: 添加 --zoom CSS 变量与缩放基础样式`（组1）
  - `feat: 占位符改用 --page-ratio CSS 变量驱动`（组2）
  - `feat: 新增 zoom 模块实现 Ctrl+滚轮缩放`（组3）
  - `feat: 工具栏缩放控件与 app.js 接入`（组4）
  - `feat: 添加 zoom 单元测试与 test:zoom 脚本`（组5）
  - `feat: 整体验证与回归`（组6，或并入组5）
- 每组完成后勾选 `openspec/changes/ctrl-wheel-zoom/tasks.md` 对应任务。
- 全部完成后进入 verify 阶段。
