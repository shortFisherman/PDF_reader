# Brainstorm Summary

- Change: align-model-rewrite
- Date: 2026-06-28

## Confirmed Technical Approach

新增前端模块 `static/modules/alignment-controller.js`，作为系统中**唯一**向两栏 `scrollTop` 写入的组件。对齐目标表示为 `(pageIndex, intraPageOffsetPx)`，从源栏经 `getBoundingClientRect` 几何派生（不依赖 `scrollHeight` 比例）。三类触发源（onScroll / onImageLoaded / onZoomChange）汇入同一 `realign()` 入口；`onScroll` 是唯一可改 target，`onImageLoaded` / `onZoomChange` 仅按现有 target 拉回，并各自实现 `intraPageOffsetPx *= r`zoom 缩放。`realigning` 重入守卫防止 scroll 事件回流（取代 `setTimeout(0)` 的 syncing 标志）。`scroll-sync.js` 删除 `setupScrollSync` 的比例互推；`zoom.js` 在调完当前列锚点后显式 `controller.onZoomChange(z, anchor)`；`app.js onFinish` 在右页 `<img>.onload` 后调 `controller.onImageLoaded('right', page)`；保存页恢复改走 `controller.setLockTarget(K, 0)` + `realign()`，不再用 `scrollIntoView`。

### 关键技术取舍（brainstorming 用户确认）

- **D7（Open Question 1 解决）**：settle gate **保留在 `scroll-sync.js`** 不搬迁。lazy-loader 沿用 `settle.onSettle + isScrollSettled` 接口零改动，page-detection 沿用 `settle.onSettle`。AlignmentController 实时对齐走 immediate realign，不触碰 settle。→ 选项 A。
- **D8（lazy 接入）**：AlignmentController 不主动调 `settle.trigger()`；realign 产生的 scroll 事件沿现有路径间接重置 settle timer，与现状一致。lazy-loader 接口不动。→ 选项 I。

### 验收契约（写回 column-alignment spec；本期不另写 Spec Patches）

- column-alignment 第 5 条 Requirement "Initial-open saved page restore routes through controller" 已使 scrollToPage 路由契约化（Open Question 3 解决）。
- column-alignment "Settle and page detection ownership" Requirement 明确"实时对齐不 debounce，page-detection 仍走 settle"（Open Question 2 解决）。
- 未发现 acceptance scenario 缺失，回写 Spec 需求为空（No Spec Patches）。

## Key Trade-offs and Risks

- **[Trade-off] 比"比例同步"实现更长** —— 多 ~120 行前端代码 + ~10 条测试换 blast radius 收缩；用户前两次回档代价远超此代价。
- **[Trade-off] 配套 spec 的 MODIFIED 是契约级 breaking** —— 但本仓库 spec 仅服务于本项目内部约束，无外消费者，敢于改契约是正确做法，archive 阶段同步主 spec 即可。
- **[Risk] 占位符与真图高度差未量化** → 既有 `dom.js calculatePlaceholderHeight` 用百分比 `--page-ratio` CSS；真图片渲染由 `width:100%` 决定等同高度（已 spec'd in dual-column-reading "Page-level image display"）。设计阶段写 jsdom fixture 故意制造 1~2px 偏差的复现测试，验证 controller `onImageLoaded` realign 能消解。
- **[Risk] zoom 鼠标锚点 vs 页内偏移在跨页缩放 / 视口在两页交界处失真** → `intraPageOffsetPx` 允许正负值，跨页时由 `(pageIndex, offset)` 标准化（offset<0 退一页）。设计阶段写"视口跨两页交界 zoom"边界测试。
- **[Risk] 写入排他性无静态强制工具** → 用 grep + 测试断言"`static/{app.js,modules/**}` 内除 alignment-controller.js 外无 `.scrollTop =`"，作为 build 期门禁（Task 5.5）。
- **[Risk] 比比例同步实现更复杂** → vibecoder 未来改动需先理解 controller；用清晰 docstring + 公开面只暴露 setters 限制认知负荷。

## Testing Strategy

- **TDD 严格遵循**：失败测试先于实现（对应 tasks 1.1/1.2/2.1 一律红）。
- **前端测试入口**：沿用 `node tests/run-<x>-tests.mjs` + jsdom + `window.__TEST_<MODULE>__` 全局标记 + `globalThis.__<MODULE>_TESTS_DONE__` 完成信号模式（同 `run-zoom-tests.mjs` / `run-lazy-loader-tests.mjs`）。
- **新增入口**：`tests/run-alignment-controller-tests.mjs` + `package.json scripts.test:align`。
- **数据契约：** AlignmentController 不依赖 IntersectionObserver / 真实图片，所有场景用 jsdom mock `getBoundingClientRect`、`scrollTop`、`clientHeight`、`scrollHeight` 即可驱动。
- **既有自测不回退**：`scroll-sync.js / zoom.js / lazy-loader.js` 末尾 `__TEST_*__` 自测全部运行通过。tasks 7.1 守护。
- **失败诱因复现 → 修复转绿**：Task 1.1/1.2 红 → task 6.1/6.2 绿，是用户两次失败的核心验证。

## Spec Patches

**None.** brainstorming 仅解决 Open Question 1/2，余下决策已在 comet-open 阶段写入 `specs/column-alignment/spec.md` 与 `specs/dual-column-reading/spec.md` 与 `specs/page-zoom/spec.md`，无新增 / 删除 acceptance scenario。