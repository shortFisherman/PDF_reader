---
comet_change: ctrl-wheel-zoom
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-25-ctrl-wheel-zoom
status: final
---

# Design Doc — Ctrl+滚轮页面缩放

## 概述

为 PDF 阅读器双栏视图添加 Ctrl+滚轮缩放：以鼠标位置为锚点缩放页面，左右栏同步，范围 25%–400%、步进 10%，工具栏显示百分比并提供一键重置（保持当前视图）。纯前端方案，不改后端渲染管线。缩放以"改变渲染宽度"实现，与现有滚动同步、当前页检测、懒加载几何自然兼容。

## 确认的技术方案

核心思想：**用 CSS 变量 `--zoom` 驱动页面图片/占位符的渲染宽度，真实改变布局流**，使 `scrollHeight` 随缩放线性变化，从而复用现有 scroll-sync（比例同步）与 page-detection（getBoundingClientRect 覆盖率），无需为缩放重写跨栏/检测逻辑。

### 架构与数据流

```
   Ctrl+wheel (over left/right column)
            │
            ▼
   ┌─────────────────────────────────────┐
   │ zoom.js  setupZoom({columns,appEl,  │
   │   onZoomChange})                     │
   │                                      │
   │  e.ctrlKey? ─no─► 放行(普通滚动)     │
   │     │yes                             │
   │  preventDefault()                    │
   │  dir = sign(deltaY)  (+1=放大,-1=缩小)│
   │  newZoom = clamp(zoom + dir*STEP,    │
   │                   MIN, MAX)          │
   │  r = newZoom / zoom                  │
   │  (cx,cy) = 光标相对主动栏            │
   │                                      │
   │  1. appEl.style.--zoom = newZoom     │── 触发重排：两栏 img/占位符
   │  2. col.scrollLeft/Top =             │   width 与 padding-bottom 同比缩放
   │     (scroll+c)*r - c                 │   → scrollHeight 线性变化
   │  3. onZoomChange(newZoom)            │
   └──────────┬──────────────────────────┘
              │ 主动栏 scrollTop 变化触发 scroll 事件
              ▼
   ┌─────────────────────────────────────┐
   │ scroll-sync.js (既有, 不改)          │
   │  f = scrollTop/(scrollHeight-client)│
   │  另一栏.scrollTop = f*(...-client)   │── 同分数 = 同内容点 = 两栏对齐
   │  syncing 守卫防回环                  │
   └─────────────────────────────────────┘
```

### 模块职责划分

- **`zoom.js`（新增）**
  - 导出 `setupZoom({ columns, appEl, onZoomChange })` → `{ resetZoom, getZoom, dispose }`。
  - 常量 `MIN=0.25, MAX=4, STEP=0.1`；内部 `zoom` 状态初始 `1`。
  - 每个 column 注册 `addEventListener('wheel', handler, { passive: false })`：仅 `e.ctrlKey` 为真时 `preventDefault` 并按 `sign(deltaY)` 增减一步、clamp；非 Ctrl 放行。
  - 锚点公式：`r=newZoom/oldZoom`，`newScrollTop=(scrollTop+cy)*r-cy`，`newScrollLeft=(scrollLeft+cx)*r-cx`；先设 `--zoom` 再设 scroll。
  - `resetZoom()`：以视口中心为锚点、`r=1/oldZoom` 反向套公式（保持当前视图），再 `onZoomChange(1)`。
  - `dispose()`：移除两栏 wheel 监听。
  - `onZoomChange(z)` 每次变化调用。

- **`app.js`（改）**
  - `openPdf` 成功后调用 `setupZoom`，传 `[els.leftCol, els.rightCol]`、`appEl=els.appView`、`onZoomChange`。
  - `onZoomChange(z)` → `els.zoomLevel.textContent = Math.round(z*100) + '%'`。
  - `els.zoomReset` 点击 → zoom 实例 `resetZoom()`。
  - 打开新 PDF 前 `dispose` 旧实例（与现有 `io.disconnect()` / `settle.dispose()` 并列）。

- **`dom.js`（改）**
  - `createPageEl`：`placeholder.style.setProperty('--page-ratio', '${ph}%')` 替换内联 `paddingBottom`。
  - `getElements`：增加 `zoomLevel`、`zoomReset` 引用。

- **`lazy-loader.js` / `app.js` `unloadPageImage`（改）**
  - 重建占位符时设 `--page-ratio` 而非内联 `padding-bottom`，使 CSS 驱动的缩放对新占位符同样生效。

- **`style.css`（改）**
  - `#app { --zoom: 1; }`（默认值）。
  - `.page-container img, .page-placeholder { width: calc(100% * var(--zoom, 1)); }`（覆盖 img 原 `width:100%`）。
  - `.page-placeholder { padding-bottom: calc(var(--page-ratio) * var(--zoom, 1)); }`（移除内联依赖）。
  - `.column { overflow-x: auto; }`（原 `hidden`）。
  - `.page-container { justify-content: safe center; }`（原 `center`）。
  - 工具栏 `#zoom-level` / `#zoom-reset` 样式（沿用 toolbar 现有视觉语言）。

- **`templates/index.html`（改）**
  - `#toolbar` 增加 `<span id="zoom-level">100%</span>` 与 `<button id="zoom-reset">重置缩放</button>`。

### 宽高比保持推导

占位符 `padding-bottom` 百分比相对*包含块*（栏宽 W）。`--page-ratio = ph%`（每文档固定 = height/width·100）。
- `width = W · zoom`
- `padding-bottom = W · (ph/100) · zoom` → `height = W·(ph/100)·zoom`
- `height/width = ph/100`（与 zoom 无关）✓

只需改一个 `--zoom`，全部（含 ~1000 个）占位符与图片同步重排，性能远优于逐元素改内联样式。

## 关键决策与备选

1. **改宽度而非 `transform: scale`**：transform 不影响布局流，破坏 scroll-sync/page-detection。备选：transform + 手动补偿容器高度——更复杂易打架，否决。
2. **CSS 变量驱动**：`--zoom` + `--page-ratio`，改一个变量即全局重排。备选：逐元素改内联 `paddingBottom`——1000 页每档更新性能差，否决。
3. **鼠标锚点 + 复用 scroll-sync**：仅设主动栏 scroll，现有同步把另一栏拉到同分数。备选：两栏分别套公式——与 `syncing`+`setTimeout(0)` 同步机制可能竞争，否决。
4. **`safe center` + `overflow-x:auto`**：<100% 居中美观，>100% 左缘可达。备选：恒 `flex-start`——<100% 不居中丑；纯 `center`——>100% 左缘不可达，否决。
5. **滚轮方向用 `sign(deltaY)`**：固定 ±10% 步进，不受触控板幅度/惯性影响（连缩几档由 clamp 兜底）。备选：按 `deltaY` 幅度比例缩放——设备差异大、易跳变，否决。
6. **重置保持当前视图**：以视口中心为锚点反向套公式。备选：回顶部（丢位置）、对齐当前页顶——前者体验差，后者多余，否决。

## 测试策略

- **jsdom 单元测试**（`zoom.js` 内联 `__TEST_ZOOM__` + `tests/run-zoom-tests.mjs`，仿 `run-lazy-loader-tests.mjs`）：
  - Ctrl 门控：非 Ctrl 不缩放、不 `preventDefault`；Ctrl 缩放并 `preventDefault`。
  - 范围/步进：±10%、25%–400% clamp、边界继续滚动无反应。
  - 锚点公式：mock `scrollTop/scrollHeight/scrollLeft/clientWidth/Height`，断言 `newScroll` 数值正确。
  - `onZoomChange` 被调用且参数正确；`reset` 回到 1；`dispose` 后再触发 wheel 无响应。
  - 纯逻辑测试（jsdom 不按 CSS 计算布局，几何/视觉靠手动）。
- **回归**：既有 `run-lazy-loader-tests.mjs`、`run-task-4.5-tests.mjs`、`test:translator`（占位符改造影响 lazy-loader，须确认无回归）+ `ruff check .` + `pytest`。
- **手动验证**：光标锚点真实表现、左右同步、25%–400% 边界、>100% 横向溢出可滚、缩放后 scroll-sync/page-detection/lazy-load 正常、重置保持视图。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 放大到 400% 文字模糊（200DPI 栅格 PNG） | 已知限制，接受；后续可另开"高清重渲染"变更（`/api/page` 加 DPI 参数 + 防抖重请求） |
| 缩小时被动栏 scrollTop 被浏览器自动 clamp | 主动栏设 scrollTop 后 scroll-sync 以分数覆盖被动栏，消除漂移 |
| 锚点公式因栏 padding(20px)/margin(16px) 不随 zoom 缩放有微小漂移 | 10% 步进下可忽略；如需精确可扣除常量，暂不做 |
| `safe center` 旧浏览器退化为 `center`，>100% 左缘不可达 | 目标现代桌面浏览器，可接受；必要时加 JS 兜底 |
| 横向不同步（仅主动栏锚定） | 仅 >100% 手动横滚时可见，对照阅读依赖纵向对齐，可接受 |
| 与懒加载 buffer 交互：放大后单页更高，`BUF=2` 覆盖像素范围变大 | 现有逻辑基于元素高度自适应，无需改动，可接受 |
| wheel 监听 passive 默认导致 `preventDefault` 无效 | 显式 `{ passive: false }` |

## 实现参数

- `MIN = 0.25`（25%），`MAX = 4`（400%），`STEP = 0.1`（10%）
- `--zoom` 默认 `1`，`--page-ratio` 每文档固定（= `pageHeight/pageWidth*100` %）

## 范围边界

仅前端：`static/style.css`、`static/modules/{zoom,dom,lazy-loader}.js`（新增 zoom、改 dom/lazy-loader 的占位符部分）、`static/app.js`、`templates/index.html`、`tests/run-zoom-tests.mjs`、`package.json`（脚本）。后端 `routes.py`/`pdf_renderer.py`/`state.py`/`config.py` 不动。无新增依赖。
