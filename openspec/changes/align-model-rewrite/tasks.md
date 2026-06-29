## 1. 锚定"翻译后失对齐"复现（红：复现样例测试，不改代码）

- [x] 1.1 在 `static/modules/__tests__/` 下新建对齐复现 fixture：用 jsdom 构造两栏 × 多页容器（占位符 + `<img>` 用 `naturalHeight` 让图片高度与占位符预留高度差 2px），断言"翻译完成后替换图后，两栏 `pageIndex` 顶部偏移之差 > 0"。预期：在当前实现下应失败（红）。运行自测脚本（沿用 `scroll-sync.js` 末尾 `window.__TEST_*__` 模式）记录失败输出。
- [ ] 1.2 同样在 jsdom fixture 下复现"Ctrl+滚轮放大大约一档后两栏页内偏移不一致"诱因——构造 zoom 模拟器，断言 zoom 后两栏 `pageIndex` 顶部偏移之差 > 0。预期：在当前实现下应失败（红）。

## 2. AlignmentController 核心 (红 → 绿)

- [ ] 2.1 新建 `static/modules/alignment-controller.js`，导出空 `createAlignmentController({ leftEl, rightEl })` 与内嵌自测块 `window.__TEST_ALIGNMENT_CONTROLLER__`。先写自测：4 个失败测试对齐 `column-alignment` 能力的关键 scenario（write 排他性、target 派生、realign 写入、realigning 重入保护），全部红。
- [ ] 2.2 实现 `currentTarget = { pageIndex, intraPageOffsetPx }`、`lockSide`、`setLockTarget(pageIndex, offsetPx)`、`onScroll(src)` 派生 `(pageOf(src), intraOffsetOf(src))`、`realign(column)` 写 `column.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`（用 `getBoundingClientRect` 相对栏算 `offsetTop`），对其暴露 `getLockTarget()`。让 2.1 的 write排他性/target派生/realign 写入测试转绿。
- [ ] 2.3 实现 `realigning` 重入保护：`realign()` 进入时置 flag、写 `scrollTop`、退出清 flag；`onScroll` 检测到 `realigning` 时跳过派生。写重入保护测试（红→绿）。
- [ ] 2.4 实现 `onImageLoaded(side, pageIndex)`：仅 `realign()`，不修改 `currentTarget`。写测试驱动此函数仅调一次 realign。
- [ ] 2.5 实现 `onZoomChange(newZoom, oldZoom)`：`intraPageOffsetPx *= newZoom/oldZoom`，再 `realign()`，不更新 `pageIndex`。写测试覆盖页内偏移缩放比例正确。
- [ ] 2.6 用 `getBoundingClientRect` 做 pageOf(src) 与 intraOffsetOf(src) 的几何测试（含 negative offset 即视口顶位于页容器上方一截的情况）。

## 3. 拆解 scroll-sync 的比例互推

- [ ] 3.1 在 `scroll-sync.js` 写自测突出 `setupScrollSync` 当前比例互推行为（保留现有 4 个 settle gate 测试不动）。此 commit 暂不删除任何代码，仅添加"该函数仍存在但即将被替换"的标记。
- [ ] 3.2 删除 `setupScrollSync` 函数体的比例互推实现（保留函数签名导出空壳或移除导出并改 app.js 装配点）。`createSettleGate`、`setupPageDetection` 保留不移。
- [ ] 3.3 更新 `scroll-sync.js` 末尾自测：若 `setupScrollSync` 被移除导出，相应 import 测试也调整；`createSettleGate` 与 `setupPageDetection` 现有 4 + 3 个测试全绿、不得回退。

## 4. zoom 模块改走 controller

- [ ] 4.1 在 `zoom.js` 自测块新增测试：完成一次 Ctrl+wheel 后，要求 `[columns.map(c => c._realignSpy).filter(Boolean].length === 1`（i.e. 调了一次对齐 controller，而不是依赖 scroll 事件）。预期红。
- [ ] 4.2 修改 `setupZoom({ columns, appEl, onZoomChange, alignmentController })` 接收 `alignmentController`；`handleWheel`/`resetZoom` 在算完当前列锚点 `scrollTop` 后，调 `alignmentController.onZoomChange(newZoom, oldZoom)`。`onZoomChange` 参数保持向后兼容（显示百分比指示器）。让 4.1 测试转绿。

## 5. app.js 装配 controller + 翻译完成路径

- [ ] 5.1 在 `openPdf` 装配 `AlignmentController`：装配后两栏 scroll 监听由 controller `onScroll` 接管；移除外部 `setupScrollSync(...)` 调用。
- [ ] 5.2 `setupPageDetection` 仍从 controller 暴露的 settle 回调处取信号（确认 `controller` 持有 settle gate 或协调之，按 design Open Question 1 暂倾向`createSettleGate` 留在 scroll-sync.js 仅做页检测用）。
- [ ] 5.3 `onFinish` 翻译完成回调中，右页 `<img>.onload` 后调 `controller.onImageLoaded('right', targetPage)`。
- [ ] 5.4 将保存页恢复路径 `scrollToPage` 从 `el.scrollIntoView` 改为 `controller.setLockTarget(saved, 0); controller.realign()`。
- [ ] 5.5 用 grep 或自测断言：除 `alignment-controller.js` 外 `static/modules/**` 与 `static/app.js` 无 `.scrollTop =` 赋值（`column-alignment` 能力 "No silent alignment writes outside controller" scenario）。

## 6. 两条失败诱因复现测试转绿（回到 Section 1）

- [ ] 6.1 重跑 1.1 测试——翻译完成后替换图后两栏 `pageIndex` 顶部偏移之差应 == 0（绿）。
- [ ] 6.2 重跑 1.2 测试——Ctrl+滚轮缩放后两栏页内偏移一致（绿）。

## 7. 兼顾既有自测不回退 + 残余边界场景

- [ ] 7.1 通过 `node` 单边运行 `scroll-sync.js` 与 `zoom.js` 末尾既有的全部 `__TEST_*__` 测试块（即以现成 jsdom 环境运行；查 README/`tests/` 看现有运行入口，例如 `node --experimental-vm-modules tests/run-*-tests.mjs`）确认无回退。
- [ ] 7.2 在 jsdom fixture 写"视口在两页交界处 zoom"的边界场景测试，验证 `intraPageOffsetPx` 跨页标准化正确（offset 走 negative 退一页规则）。
- [ ] 7.3 写"急速滚动期间对齐仍实时"测试：100 次 scroll 事件分别逐次 onScroll 后断言对齐一致性（无 debounce 滞后）。
- [ ] 7.4 在 `column-alignment` 测试中覆盖"两栏 scrollHeight 差 30px 时刻意 mock 真图 vs 占位符 2px 差"，断言对齐仍按 page + intraOffset 收敛（设计 Risk 兜底成立）。

## 8. 文档与 frontend 自测入口接通

- [ ] 8.1 确认新增的 `alignment-controller.js` 自测块如何被现有 frontend 测试运行器发现。读 README、`tests/run-translator-tests.mjs`、`package.json scripts`，确认 fixture 入口；缺则补一个 `tests/run-align-tests.mjs` 并注册到 `package.json test` 脚本。
- [ ] 8.2 在 `README.md` 末尾"前端测试"章节补一句"alignment-controller 自测运行方式"，与 `scroll-sync.js`/`zoom.js` 既有描述风格一致。

## 9. 质量 gates + 提交节奏

- [ ] 9.1 每个绿后小 commit：commit message 以 `align-model-rewrite:` 前缀，按设计意图描述（例如 `feat(align): page-aligned realign + image-onload hook`）。一 task 一 commit。
- [ ] 9.2 全量后端 lint/test 不回退：`ruff check .`、`ruff format --check .`、`pytest -q` 全绿（后端零改动预期，仅验证）。
- [ ] 9.3 前端自测全绿：所有 `__TEST_*__` 块运行通过。
- [ ] 9.4 最后一次 commit 不带 BREAKING 字样，全部变更通过既有 OpenSpec guard 后才推进到 verify 阶段。