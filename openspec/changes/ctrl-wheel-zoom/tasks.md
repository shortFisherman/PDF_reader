## 1. CSS 缩放基础

- [x] 1.1 在 `static/style.css` 中为 `#app`（或 `.column`）建立 `--zoom` CSS 变量（默认 `1`），并为 `.page-container img` 与 `.page-placeholder` 设置 `width: calc(100% * var(--zoom, 1))`（覆盖 img 现有 `width:100%`）
- [x] 1.2 在 `static/style.css` 中将 `.page-placeholder` 的高度改为 `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1))`，移除对内联 `padding-bottom` 的依赖
- [x] 1.3 将 `.column` 的 `overflow-x` 由 `hidden` 改为 `auto`；将 `.page-container` 的 `justify-content` 由 `center` 改为 `safe center`

## 2. 占位符改造为 CSS 变量驱动

- [x] 2.1 修改 `static/modules/dom.js` 的 `createPageEl`：用 `placeholder.style.setProperty('--page-ratio', '${ph}%')` 替换 `placeholder.style.paddingBottom = '${ph}%'`
- [x] 2.2 修改 `static/app.js` 的 `unloadPageImage`：重建占位符时同样设置 `--page-ratio` 而非内联 `padding-bottom`
- [x] 2.3 验证 100% 缩放下占位符宽高比与改动前一致（无视觉回归）

## 3. zoom 模块

- [x] 3.1 新增 `static/modules/zoom.js`，导出 `setupZoom({ columns, appEl, onZoomChange })`，内部维护 zoom 状态（初始 1）、`MIN=0.25`、`MAX=4`、`STEP=0.1`
- [x] 3.2 在 `setupZoom` 中为每个 column 注册 `wheel` 监听：仅当 `e.ctrlKey` 为真时 `preventDefault` 并按 `e.deltaY` 符号增减一步，clamp 到 `[MIN,MAX]`；非 Ctrl 时不动 zoom、不阻止默认滚动
- [x] 3.3 实现鼠标锚点滚动重算：`r = newZoom/oldZoom`，`newScrollTop = (scrollTop + cy)*r - cy`、`newScrollLeft = (scrollLeft + cx)*r - cx`；先设 `appEl.style.--zoom` 再设主动栏 `scrollLeft/scrollTop`（依赖现有 scroll-sync 把另一栏拉到同分数位置）
- [x] 3.4 导出 `resetZoom()`（回到 1：以视口中心为锚点、`r=1/oldZoom` 反向套公式，保持当前视图）、`getZoom()`、`dispose()`（移除 wheel 监听）；每次 zoom 变化调用 `onZoomChange(zoom)`

## 4. 工具栏缩放控件与接入

- [x] 4.1 在 `templates/index.html` 的 `#toolbar` 中增加 `<span id="zoom-level">100%</span>` 与 `<button id="zoom-reset">重置缩放</button>`
- [x] 4.2 在 `static/modules/dom.js` 的 `getElements` 中增加 `zoomLevel`、`zoomReset` 引用
- [x] 4.3 在 `static/app.js` 的 `openPdf` 成功后调用 `setupZoom`，传入 `[els.leftCol, els.rightCol]`、`appEl`、`onZoomChange`；`onZoomChange(z)` 更新 `els.zoomLevel.textContent = Math.round(z*100) + '%'`
- [x] 4.4 在 `app.js` 中为 `els.zoomReset` 绑定点击 → 调用 zoom 实例的 `resetZoom()`；打开新 PDF 时 `dispose` 旧实例

## 5. 前端测试

- [x] 5.1 在 `static/modules/zoom.js` 中增加内联测试（`window.__TEST_ZOOM__` 门控）：覆盖 Ctrl+wheel 增减、非 Ctrl 不缩放、边界 clamp、锚点公式数值正确、reset 回到 1、onZoomChange 被调用
- [x] 5.2 新增 `tests/run-zoom-tests.mjs`（仿 `run-lazy-loader-tests.mjs`：jsdom + 剥离 export + 设 `__TEST_ZOOM__` + 校验 `__ZOOM_TESTS_DONE__` 与 PASS/FAIL 退出码）
- [x] 5.3 在 `package.json` 增加 `"test:zoom": "node tests/run-zoom-tests.mjs"` 脚本
- [x] 5.4 运行 `node tests/run-zoom-tests.mjs` 通过；并运行既有 `node tests/run-lazy-loader-tests.mjs`、`node tests/run-task-4.5-tests.mjs`、`npm run test:translator` 确认无回归

## 6. 整体验证

- [x] 6.1 运行 `ruff check .` 通过（确认未误改 Python 文件或无新增违规）
- [x] 6.2 运行 `pytest` 通过（确认后端无回归）
- [ ] 6.3 手动验证：打开 PDF，Ctrl+滚轮缩放以光标为锚点、左右栏同步；25%–400% 边界停止；非 Ctrl 滚轮正常滚动；工具栏显示百分比；重置按钮回 100%；缩放后滚动同步 / 当前页检测 / 懒加载正常
