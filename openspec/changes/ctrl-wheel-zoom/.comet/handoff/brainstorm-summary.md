# Brainstorm Summary

- Change: ctrl-wheel-zoom
- Date: 2026-06-25

## Confirmed Technical Approach

纯前端 CSS 缩放：在 `#app` 上设 `--zoom` 变量（默认 1），驱动 `.page-container img` 与 `.page-placeholder` 的 `width: calc(100% * var(--zoom, 1))`；占位符内联设 `--page-ratio`，CSS 计算 `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1))` 保持宽高比。用"改宽度"而非 `transform: scale`，使 `scrollHeight` 随缩放变化，兼容现有 scroll-sync（比例同步）与 page-detection（getBoundingClientRect 覆盖率）。

新增 `static/modules/zoom.js`，导出 `setupZoom({ columns, appEl, onZoomChange })` → `{ resetZoom, getZoom, dispose }`，由 `app.js` 在 openPdf 成功后组装。

鼠标锚点公式：`r = newZoom/oldZoom`，`newScrollTop = (scrollTop + cy)*r - cy`，`newScrollLeft = (scrollLeft + cx)*r - cx`。设 `--zoom` → 设主动栏 scroll（触发 scroll-sync 把另一栏拉到同分数=同内容点）→ `onZoomChange`。

深化决策：
- wheel 监听用 `{ passive: false }` 才能 `preventDefault`。
- 滚轮方向用 `Math.sign(deltaY)`，固定 ±10% 步进，不依赖幅度。
- 重置保持当前视图：以视口中心为锚点反向套公式（r=1/oldZoom），不丢阅读位置。
- 打开新 PDF 时 `dispose` 旧 zoom 实例。
- `overflow-x: auto` + `justify-content: safe center` 处理 >100% 横向溢出。

## Key Trade-offs and Risks

- 放大到 400% 时 200DPI PNG 文字模糊 → 已知限制，接受；后续可另开"高清重渲染"变更。
- 缩小时被动栏 scrollTop 被浏览器 clamp → 主动栏设 scrollTop 后 scroll-sync 以分数覆盖，消除漂移。
- 锚点公式因栏 padding/margin 不随 zoom 缩放有微小漂移 → 10% 步进下可忽略。
- `safe center` 旧浏览器退化为 `center` → 目标现代桌面浏览器，可接受。
- 横向不同步（仅主动栏锚定）→ 仅 >100% 手动横滚时可见，可接受。

## Testing Strategy

- jsdom 单元测试（`zoom.js` 内联 `__TEST_ZOOM__` + `tests/run-zoom-tests.mjs`，仿现有 runner）：Ctrl 门控、范围/步进 clamp、锚点公式数值（mock scrollTop/scrollHeight/scrollLeft）、onZoomChange、reset 回 1、dispose 移除监听。纯逻辑测试。
- 回归：既有前端 runner（lazy-loader / task-4.5 / translator）+ `ruff check .` + `pytest`。
- 手动验证：光标锚点真实表现、左右同步、边界、横向溢出、缩放后 scroll-sync/page-detection/lazy-load 正常。

## Spec Patches

向 `specs/page-zoom/spec.md` 的 "Zoom indicator and reset control" 需求补一条场景：

#### Scenario: Reset preserves current view
- **WHEN** the user activates the reset control while zoomed to a non-100% level
- **THEN** the zoom SHALL return to 100% anchored at the viewport center, so the content currently at the center of the viewport SHALL remain at the center (reading position preserved)
