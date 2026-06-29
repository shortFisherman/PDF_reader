---
change: align-model-rewrite
design-doc: docs/superpowers/specs/2026-06-28-align-model-rewrite-design.md
base-ref: 5f4f414a5fa3d1012c995b741ca3f85c22f30d1a
---

# 实施计划 — align-model-rewrite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把左右两栏对齐状态从「分散在三处的副作用 + 比例同步」重构为 AlignmentController 单一排他所有者，以 `(pageIndex, intraPageOffsetPx)` 为目标，三源（scroll / image onload / zoom）汇入同一 `realign()` 入口；TDD 严格，复现并修复用户两次失败的「翻译刷新失对齐」与「Ctrl+滚轮失对齐」诱因。

**Architecture:** 新建 `static/modules/alignment-controller.js`（含内嵌自测块 `window.__TEST_ALIGNMENT_CONTROLLER__`），导出工厂 `createAlignmentController({leftEl,rightEl})`。`scroll-sync.js` 删除 `setupScrollSync` 比例互推函数体，保留 `createSettleGate`/`setupPageDetection`。`zoom.js` 在算完当前列锚点后调 `controller.onZoomChange(r)`。`app.js` 在 `openPdf` 装配 controller、`onFinish` `<img>.onload` 内调 `onImageLoaded`、`scrollToPage(saved)` 改走 `setLockTarget + realign`。新增 `tests/run-alignment-controller-tests.mjs` 入口、`package.json scripts.test:align`。

**Tech Stack:** 原生 ES Module JS（前端 `static/modules/*.js`、`static/app.js`）；jsdom + `node tests/run-*.mjs`（前端自测）；后端零改动，仅做 `ruff`/`pytest` 回退验证。

## 变更背景

用户两次尝试修复左右栏「左栏总比右栏高一点」的对齐偏差——诱因分别是**翻译完成后图替换**与**Ctrl+滚轮缩放**——两次都把 `setupScrollSync`/`zoom`/`onFinish` 三处的副作用链改崩、被迫 `git revert`。根因调查发现：对齐状态没有任何模块真正"拥有"它，由三处副作用拼成；更糟的是既有 OpenSpec 把这套脆弱结构写成了契约（`dual-column-reading` 规定"proportional"，`page-zoom` 规定 zoom 后对齐走现有 scroll-sync）。改一处必崩的根因即此。

## 关联工件

- Design Doc：`docs/superpowers/specs/2026-06-28-align-model-rewrite-design.md`（8 项关键决策 D1–D8 + 风险表 R1–R7 + 数据流图）。
- OpenSpec 变更目录：`openspec/changes/align-model-rewrite/`（含 `tasks.md` 与三份 delta spec）。
- 能力 spec — 新增：`openspec/changes/align-model-rewrite/specs/column-alignment/spec.md`（AlignmentController 排他写入 / 目标语义 / 跨源 realign / settle ownership / 保存页恢复 5 条 Requirement）。
- 能力 spec — 修改：`openspec/changes/align-model-rewrite/specs/dual-column-reading/spec.md`（page-aligned 替代 proportional、realigning guard 取代 setTimeout syncing）。
- 能力 spec — 修改：`openspec/changes/align-model-rewrite/specs/page-zoom/spec.md`（zoom 完成当前列锚点后调 `onZoomChange` 取代 scroll 事件兜底）。

## 设计概要 (摘要)

- **D1 排他性**：AlignmentController 是系统中唯一向两栏写 `scrollTop` 的组件；其它模块要走 `setLockTarget`/`realign`/`onScroll`/`onImageLoaded`/`onZoomChange` 公共面。
- **D2 目标语义**：对齐目标是 `(pageIndex, intraPageOffsetPx)`（offset 可为负）；`realign(col)` 写 `col.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`，`offsetTop` 用 `getBoundingClientRect` 相对栏算，与 `scrollHeight` 比例脱钩 → 两栏 scrollHeight 不一致时仍页对齐。
- **D3 三源汇入**：`onScroll`/`onImageLoaded`/`onZoomChange` 全部调 `realign()`；只有 `onScroll` 可 mutate `currentTarget`；`realigning` 守卫取代 `setTimeout(0) syncing` 防 scroll 事件回流。
- **D4 scroll-sync 收敛**：删 `setupScrollSync` 函数体（line 50–70 比例互推）；保留 `createSettleGate`/`setupPageDetection`；`app.js` 不再调 `setupScrollSync`，改由 controller `installScrollListeners` 接管 scroll 监听并委托回 `onScroll`。
- **D5 zoom 几何统一**：`zoom.js` 当前列仍按锚点公式 `newScrollTop = (scrollTop+cy)*r - cy`；完成后显式调 `controller.onZoomChange(r)`；controller 内 `intraPageOffsetPx *= r` 再 `realign()` 两栏同 target。
- **D6 翻译完成图刷新**：`onFinish` 中 `unloadPageImage → loadPageImage` 触发新 `<img>.onload`；`onload` 内调 `controller.onImageLoaded('right', targetPage)`；`onImageLoaded` 不改 target，仅 `realign()` 兜底（即使真图 vs 占位符差 1~2px）。
- **D7 保存页恢复**：`openPdf` 中 `scrollToPage(saved)` 改为 `controller.setLockTarget(saved, 0); controller.realign()`，不经 `scrollIntoView`，alignment 从首帧起被 controller 拥有。
- **D8 测试入口**：新增 `tests/run-alignment-controller-tests.mjs`，沿用 jsdom + `window.__TEST_ALIGNMENT_CONTROLLER__` 全局触发模式（仿照 `run-zoom-tests.mjs`）；`package.json` 增 `"test:align": "node tests/run-alignment-controller-tests.mjs"`。
- **TDD 强约束**：失败复现测试先于实现（Section 1 红 → Section 6 绿）；controller 主线红→绿 (Section 2)→拆 scroll-sync 旧实现并保既有自测不回退 (Section 3)→zoom 路由 (Section 4)→app.js 装配 (Section 5)→诱因复现转绿 (Section 6)→边界 (Section 7)→入口+README (Section 8)→lint/pytest 全绿 (Section 9)。

## 执行方式与隔离

> 待用户确认：**isolation**（git branch 还是 git worktree）、**execution mode**（superpowers:subagent-driven-development 还是 superpowers:executing-plans）、**TDD mode**（严格红→绿每步一 commit，还是分批）。

本计划文件不替用户决定。若使用 worktree，由主会话通过 `superpowers:using-git-worktrees` 在执行时创建隔离工作区；plan 文件本身仅作计划依据。

---

## 任务清单 (TDD 严格)

任务编号沿用 `openspec/changes/align-model-rewrite/tasks.md` 的 9 节、30 个复选框。每个 task 下面逐条勾选；每个 `[ ]` 即可在执行时直接对应一次 commit。下游实现者只需读「此条目描述」即可知：动哪个文件、实现什么行为、预期红→绿判据。

### Section 1. 锚定"翻译后失对齐"复现（红：复现样例测试，不改代码）

> 本节只是复现当前实现的 bug；不动 `scroll-sync.js`/`zoom.js`/`app.js`/`alignment-controller.js`。两测试在 Section 6 转绿。fixture 风格统一放 `static/modules/__tests__/` 新建目录、由 `tests/run-alignment-controller-tests.mjs` 在红阶段提前加载（红阶段允许 `__TEST_ALIGN_REPRO__` 这类临时全局标记，绿阶段并入主自测块）。

- [x] **1.1 翻译后失对齐复现红测试** — 新建 jsdom fixture（两栏 × 多页 `.page-container`，占位符 `--page-ratio` 与 `<img naturalHeight>` 故意差 2px）。模拟"翻译完成后替换右栏图后"流程：右栏某页卸载占位符 → 新图 `onload` 触发；断言"两栏同 `pageIndex` 的页面容器顶在视口坐标系下偏移差 == 0"。在当前 `setupScrollSync` 比例实现 + 无 controller 兜底下应失败（即偏移差 > 0）。
  <task standards> 预期 RED：fixture 在当前实现下断言 `Math.abs(leftTop - rightTop) <= 0.5` 不成立、输出 `1 passed, 1 FAILED` 或等价。完成后 GREEN 由 Section 6.1 接管。
- [ ] **1.2 Ctrl+滚轮失对齐复现红测试** — 同 fixture 上加 zoom 模拟器：模拟一次 Ctrl+wheel 触发 `handleWheel` 把 `--zoom` 从 1 改为 1.1、当前列按锚点公式算 `scrollTop`，断言"两栏同 `pageIndex` 页内偏移一致"。当前实现下右栏靠被动 scroll 事件兜底、未被对齐拉回 → 失败（偏移不一致）。
  <task standards> 预期 RED：两栏 `intraPageOffset` 差 > 0（即不对齐）；完成后 GREEN 由 Section 6.2 接管。

### Section 2. AlignmentController 核心 (红 → 绿)

> 新文件 `static/modules/alignment-controller.js`，导出 `createAlignmentController({leftEl, rightEl})`。先写自测块（用 `window.__TEST_ALIGNMENT_CONTROLLER__` 触发），全部红 → 再逐步实现直至全绿。每个复选框一个 commit。

- [ ] **2.1 创建空 controller 与 4 个失败自测** — 新建 `static/modules/alignment-controller.js`：导出 `createAlignmentController({leftEl, rightEl})` 返回 `{onScroll, onImageLoaded, onZoomChange, realign, setLockTarget, getLockTarget, installScrollListeners, dispose}`（全部空函数 stub）。末尾复刻 `scroll-sync.js` 既有自测模式：`if (window.__TEST_ALIGNMENT_CONTROLLER__) { ... }`，写 4 个针对 `column-alignment` 关键 scenario 的失败测试：(a) write 排他性、(b) target 派生、(c) realign 写入、(d) realigning 重入保护。跑 `node tests/run-alignment-controller-tests.mjs`（此时新增入口见 Section 8 但为本节可先临时建一个最小入口驱动）应失败。
  <task standards> 预期 RED：4 个测试全 FAIL（stub 不写 `scrollTop`、不派生 target、无重入保护）。
- [ ] **2.2 实现 `currentTarget` + `setLockTarget` + `onScroll` 派生 + `realign` 写入** — 实现 `state = { currentTarget: {pageIndex, intraPageOffsetPx}, lockSide }`。`setLockTarget(pageIndex, offsetPx)` 写 `currentTarget`。`onScroll(src)`：iterate `src.querySelectorAll('.page-container')`，选 rect 覆盖视口中点的页（视图边界为 `src.scrollTop ~ +clientHeight`），按 `column-alignment/Page index recovered from source column` scenario（>50% 覆盖优先，否则视口顶中心页）取 `pageIndex`；`intraOffset = src.scrollTop - pageContainer.offsetTop`；若 `< 0` 则 `pageIndex -= 1, intraOffset += page(idx+1).offsetHeight`（跨页标准化）；`lockSide = src`；调 `realign(dst)`。`realign(column)` 写 `column.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`，`offsetTop` 用 `pageContainer.getBoundingClientRect().top - column.getBoundingClientRect().top + column.scrollTop` 算。暴露 `getLockTarget()`。让 2.1 的 (a)(b)(c) 三测试转绿。
  <task standards> 完成后 GREEN：排他性测试断言"调 `realign` 后只有受控栏 `scrollTop` 变化"，target 派生测试断言"onScroll 后 `getLockTarget()` 返回 `(N, 30)`"，realign 写入测试断言"两栏 scrollHeight 差 30px 时两栏 `pageIndex` 顶偏移差 == 0"。
- [ ] **2.3 实现 `realigning` 重入保护** — `realign(column)` 入口置 `this.realigning = true`，写完 `scrollTop`、本任务周期退出清 `false`。`onScroll` 收到 scroll 事件时先检 `realigning`，为 `true` 则直接 return 不派生 target。写重入保护测试：spy 派生函数；调一次 `realign` 后，模拟其触发的回流 scroll 事件进入 `onScroll`，断言派生函数未被调用、`getLockTarget()` 未变。
  <task standards> 先写测试（红：无保护时派生被回触发、`getLockTarget` 漂移）→ 实现保护（绿）。
- [ ] **2.4 实现 `onImageLoaded(side, pageIndex)`** — 仅 `realign()`（写两栏 `scrollTop` 拉回 target），**不**改 `currentTarget`。写测试：spy `realign`，`onImageLoaded` 触发后断言 `realign` 调一次、`getLockTarget()` 与调用前一致。
  <task standards> 红→绿：先红（stub 不调 realign 或改了 target）→ 绿。
- [ ] **2.5 实现 `onZoomChange(newZoom, oldZoom)`** — `intraPageOffsetPx *= newZoom/oldZoom`、`pageIndex` 不变、再 `realign()`。写测试覆盖比例缩放正确（如 target `(2, 100)`、`r = 1.1` → realign 后两栏 page2 顶在 `110px`）。
  <task standards> 测试断言 `getLockTarget().intraPageOffsetPx === 100 * 1.1` 且 `pageIndex` 未变。
- [ ] **2.6 `getBoundingClientRect` 几何测试（含 negative offset）** — fixture 构造视口顶位于页容器上方一截的情形，`onScroll(src)` 派生应触发 negative offset 规则：`pageIndex -= 1, intraOffset += nextPage.offsetHeight`。写测试断言派生后的 `(pageIndex, intraPageOffsetPx)` 取整后等价于"原 src 的 scrollTop 处的内容点"。
  <task standards> 红若跨页规则未实现（offset 仍为负、pageIndex 不回退） → 绿实现回退规则后。

### Section 3. 拆解 scroll-sync 的比例互推

> 文件 `static/modules/scroll-sync.js`。本节不动 `createSettleGate` / `setupPageDetection` 的实现与既有 4+3 自测（settlegate 4 + pageDetection 3 个）。

- [ ] **3.1 标记 setupScrollSync 即将被替换** — 在 `scroll-sync.js` 自测块中加一条断言"`setupScrollSync` 在模块导出中存在"的占位测试（仍绿），并用注释标注 `@deprecated align-model-rewrite: 即将被 controller 替换`。本 commit 不删任何代码。
  <task standards> 不改行为；`createSettleGate`/`setupPageDetection` 测试全绿不回退。
- [ ] **3.2 删除 `setupScrollSync` 比例互推函数体** — 删 `scroll-sync.js` line 50–70 整个 `setupScrollSync({...})` 实现。两种选择二选一：(a) 整体移除 `export function setupScrollSync` 与导出，并同步删 `app.js:3` import 中相关项（与 Section 5.1 同步落地）；(b) 保留空签名壳 `export function setupScrollSync() {}` 以维持 import 不破。**实施时优先 (a)**：删导出+删 app.js import+删 app.js:102 调用一气呵成于本 commit，避免长期残留空壳。
  <task standards> 完成后 GREEN：`scroll-sync.js` 不再含 `scrollTop =` 比例写入；`grep "scrollTop" static/modules/scroll-sync.js` 仅剩自测块无赋值。
- [ ] **3.3 更新 scroll-sync 自测** — 若 (a) 路径移除了导出，相应 import 测试一并调整；`createSettleGate` 4 个 + `setupPageDetection` 3 个全绿、不得回退。运行 `node tests/run-*-tests.mjs`（含 `run-lazy-loader-tests.mjs` 因为 lazy-loader 依赖 `settle.onSettle` 接口 —— 接口不变所以应仍绿）。
  <task standards> 完成后 GREEN：所有前端 `run-*-tests.mjs` 仍 PASS（除尚未实现 controller 的红测试外）。

### Section 4. zoom 模块改走 controller

- [ ] **4.1 zoom 自测新增红测试** — 在 `zoom.js` 末尾 `__TEST_ZOOM__` 块内新增测试：构造 `setupZoom({ columns, appEl, onZoomChange, alignmentController })`，其中 `alignmentController` 是带 `onZoomChange` spy 的 mock；完成一次 Ctrl+wheel 后断言 `alignmentController.onZoomChange` 被调用一次（即"调了一次对齐 controller，而非依赖 scroll 事件兜底"）。预期红（当前 `setupZoom` 签名不接受 `alignmentController`，且不调 `onZoomChange`）。
  <task standards> 预期 RED：`onZoomChange` spy 调用次数 === 0。
- [ ] **4.2 修改 setupZoom 接收 alignmentController 并接入** — 修改 `setupZoom({ columns, appEl, onZoomChange, alignmentController })`：参数对象新增 `alignmentController`（向后兼容——若未传则行为不变，仅不调 controller）。`handleWheel`/`resetZoom` 在设 `--zoom` 并按锚点公式写当前列 `scrollTop`/`scrollLeft` 后，调 `alignmentController.onZoomChange(newZoom, oldZoom)`（`oldZoom` = 局部 `zoom` 改之前的值；`newZoom` = 改之后）。`onZoomChange`（即 `app.js` 传入的百分比指示器回调）保持原签名向后兼容。让 4.1 测试转绿。
  <task standards> 完成后 GREEN：4.1 测试 PASS；既有 zoom 测试（`run-zoom-tests.mjs` 全部 ~11 个断言）不回退（既有测试不传 `alignmentController`，行为不变）。

### Section 5. app.js 装配 controller + 翻译完成路径

> 文件 `static/app.js`。装配次序在 `settle = createSettleGate(...)` 之后、`zoomInst = setupZoom(...)` 之前。

- [ ] **5.1 openPdf 装配 AlignmentController** — 在 `openPdf` 中 import `{ createAlignmentController } from './modules/alignment-controller.js'`。在 `settle = createSettleGate(...)` 与 `io = setupIntersectionObserver(...)` 之后，移除现有 `setupScrollSync({left: els.leftCol, right: els.rightCol})` 调用，改为 `const alignController = createAlignmentController({ leftEl: els.leftCol, rightEl: els.rightCol }); alignController.installScrollListeners();`。模块级加 `let alignController = null;`（与 `zoomInst` 一组），在 `openPdf` 入口 teardown 序列加 `if (alignController) { alignController.dispose(); alignController = null; }`。
  <task standards> 完成后 GREEN：`alignController` 接管双栏 scroll 监听；`scroll-sync.js` 不再被 `app.js` 调用；既有 `setupPageDetection({container: els.leftCol, settle}, onPageChange)` 仍按现状装配（settle gate 留在 scroll-sync.js）。
- [ ] **5.2 setupPageDetection 取 settle 信号路径不变** — 按 design Open Question 1 之用户决议 A：`createSettleGate` 保留在 `scroll-sync.js`，`setupPageDetection` 仍由 `app.js` 直接 `createSettleGate` + `setupPageDetection` 装配。本任务只需在 plan 中固化此约定并在实现时验证 `onPageChange` 仍由 settle 回调触发、page 指示器不抖动。
  <task standards> 完成后 GREEN：`run-lazy-loader-tests.mjs` 仍 PASS（settle 接口未变）。
- [ ] **5.3 onFinish 翻译完成路径接入 controller** — `app.js onFinish` 在 `unloadPageImage(rightEl); loadPageImage(rightEl);` 之后，需要在新 `<img>.onload` 内调 `alignController.onImageLoaded('right', targetPage)`。注意：现有 `loadPageImage` 实现把 `img.onload` 写在内部、`placeholder.replaceWith(img)`，未对外暴露 onload 钩子。两种实现法二选一：(a) 给 `loadPageImage` 增加可选第二参 `onLoadCallback`，在内部 `img.onload` 末尾调用；(b) 给 `loadPageImage` 增加可选 `{ onImageLoaded }` 选项对象。**选 (a)** 与现有 `dataset.side`/`dataset.page` 读取风格一致。`runBatchTranslate` 的 `onFinish` 也同步接入（循环调对各页 `alignController.onImageLoaded('right', p)`）。新 `<img>` 是异步加载，`onImageLoaded` 需在 onload 真发生时调（即在 `img.onload` 内），不能在 `loadPageImage` 同步返回后立即调。
  <task standards> 完成后 GREEN：手动验证脚本在 dev 环境 — 翻译一页完成后左右栏页顶偏移差 == 0；Section 1.1 fixture 转绿前仍需 Section 6.1 跑。
- [ ] **5.4 scrollToPage 改走 controller** — 将 `app.js` 现有 `function scrollToPage(index) { ... el.scrollIntoView(...); }` 改为 `alignController.setLockTarget(index, 0); alignController.realign();`。`openPdf` 中 `requestAnimationFrame(() => scrollToPage(saved))` 调用点保持，但语义改成"经 controller 设 target 后立刻 realign"。
  <task standards> 完成后 GREEN：再次打开有 `saved_page` 的 PDF，两栏对齐到 page K 顶且 `page-indicator` 由 settle gate 回调刷新。
- [ ] **5.5 grep 断言排他性** — 用 grep 或自测断言：在 `static/modules/**` 与 `static/app.js` 中查找 `.scrollTop =`，断言除 `alignment-controller.js` 外无任何赋值（`column-alignment` 能力 "No silent alignment writes outside controller" scenario）。建议在 `tests/run-alignment-controller-tests.mjs` 末尾加一个文件级 grep 自测：用 `fs.readFileSync` 读 `static/modules/*.js` 与 `static/app.js`，正则 `/\.scrollTop\s*=/`，断言命中文件集合 `=== {alignment-controller.js}`。注意 `zoom.js` 仅写 `col.scrollTop` 当前列（D5 几何等价证明已显式确认这是当前列锚点公式，不是对齐写入）；此点是 spec 排他性写"两栏"——zoom 写"当前列"算锚点不算违反（spec 原文：`zoom.js` 完成当前列锚点**后**调 `onZoomChange`，另一列由 controller realign）。需在断言中精确判断：`zoom.js` 的 `col.scrollTop =` 是对 `e.currentTarget`/`columns[0]` 的当前列写入，非"两栏赋值"。可选实现：grep 命中行若包含 `currentTarget`/`columns[0]` 且属 `handleWheel`/`resetZoom` 则放行。**简化约定**：本断言只校验"非 zoom.js、非 alignment-controller.js 之外再无 `.scrollTop =` 赋值"，`zoom.js` 仅写当前列由 Section 4 的"完成后调 controller"语义间接保证。
  <task standards> 完成后 GREEN：grep 测试 PASS；人工 review `scroll-sync.js`/`lazy-loader.js`/`dom.js`/`app.js` 不含 `.scrollTop =` 赋值。

### Section 6. 两条失败诱因复现测试转绿（回到 Section 1）

- [ ] **6.1 翻译后失对齐复现转绿** — 重跑 Section 1.1 fixture 测试。装配好 controller + `onImageLoaded` 路径（Section 5.3）后，新 `<img>.onload` 触发 `realign()` 兜底，两栏 `pageIndex` 顶偏移差应收敛到 0。断言 `Math.abs(leftTop - rightTop) <= 0.5` 成立。
  <task standards> 完成后 GREEN：Section 1.1 测试从 RED 转 GREEN。
- [ ] **6.2 Ctrl+滚轮失对齐复现转绿** — 重跑 Section 1.2 fixture 测试。装配 zoom 接入 controller（Section 4.2）后，zoom 完成当前列锚点 → 调 `onZoomChange(r)` → controller `intraOffset *= r` → `realign()` 把另一列拉回同 target，两栏页内偏移一致。
  <task standards> 完成后 GREEN：Section 1.2 测试从 RED 转 GREEN。

### Section 7. 兼顾既有自测不回退 + 残余边界场景

- [ ] **7.1 既有前端自测全绿确认** — 通过 `node` 运行 `tests/run-zoom-tests.mjs`、`tests/run-lazy-loader-tests.mjs`、`tests/run-translator-tests.mjs`、`tests/run-task-4.4-tests.mjs`、`tests/run-task-4.5-tests.mjs`（若存在）确认 Section 3 拆解 scroll-sync 后无回退。
  <task standards> 完成后 GREEN：所有 `__TEST_*__` 块运行通过、`*TESTS_DONE__` 全部置位。
- [ ] **7.2 视口在两页交界处 zoom 边界场景** — jsdom fixture 构造视口顶恰好跨 page N 与 N+1 交界（page N 仅底下 10px、page N+1 顶上 590px）。触发 `onScroll(src)` 派生：`pageIndex` 应取视口顶中心所在页（即 N+1），`intraOffset` 为该页 `offsetTop` 减 `src.scrollTop` 得负值；按 negative offset 规则回退 `pageIndex -= 1`，`intraOffset += page(N+1).offsetHeight`。断言派生后的目标与原始 scroll 位置等价。然后触发 zoom `r = 1.1`，断言派生后 `intraOffset *= 1.1`、`pageIndex` 不变、两栏 realign 后页内偏移按比例放大。
  <task standards> 完成后 GREEN：边界 fixture 测试 PASS，验证 Risk R2 缓解（跨页标准化规则）。
- [ ] **7.3 急速滚动期间对齐仍实时** — 写测试：连续派 100 次 scroll 事件（不延时），每次 onScroll 后立刻断言另一栏 `scrollTop` 已被 controller realign 到同 target（无 debounce 滞后）。`column-alignment` 能力 "Immediate alignment during continuous scroll" scenario。
  <task standards> 完成后 GREEN：每次 onScroll 后 `Math.abs(leftTarget - rightTarget) <= 0.5`；Risk R5 缓解。
- [ ] **7.4 两栏 scrollHeight 差 30px + 真图 vs 占位符 2px 差兜底** — 在 `column-alignment` 测试组里加 fixture：左栏 scrollHeight = X、右栏 = X-30（占位符 vs 真图差 2px × 多页累计）。设 target `(N, 30)` → `realign()` 后两栏 page N 顶都在视口顶 +30px，无 residual drift。
  <task standards> 完成后 GREEN：Risk R1 缓解（`getBoundingClientRect`-based `offsetTop` 与 `scrollHeight` 比例脱钩）。

### Section 8. 文档与 frontend 自测入口接通

- [ ] **8.1 新增 `tests/run-align-tests.mjs` 入口（或复用 Section 2.1 已临时建的 `run-alignment-controller-tests.mjs`）并注册 `package.json scripts`** — 仿 `tests/run-zoom-tests.mjs` 模板：jsdom 新建 `<body>` → `globalThis.window = jsdomWindow` → 读 `static/modules/alignment-controller.js` 源码、用正则剥 `export ` 前缀 → `new Function('window','document','globalThis','setTimeout','console', code)` 执行 → 设 `jsdomWindow.__TEST_ALIGNMENT_CONTROLLER__ = true`。脚本末尾判 `globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__`、日志含 FAIL 则 `exit(1)`。`package.json scripts` 增 `"test:align": "node tests/run-alignment-controller-tests.mjs"`。
  <task standards> 完成后 GREEN：`node tests/run-alignment-controller-tests.mjs` 退出码 0；既有 `test:zoom`、`test:translator` 不受影响。
- [ ] **8.2 README 前端测试章节补一行** — 在 `README.md` 末尾「前端测试」章节加一句"alignment-controller 自测运行方式"，与 `scroll-sync.js`/`zoom.js` 既有描述风格一致（一句话 + 命令）。
  <task standards> 完成后 GREEN：README 增量与既有风格一致。

### Section 9. 质量 gates + 提交节奏

- [ ] **9.1 一 task 一 commit、前缀 `align-model-rewrite:`** — 每个绿后小 commit；commit message 主语描述设计意图而非步骤（如 `feat(align): page-aligned realign + image-onload hook`、`refactor(scroll-sync): drop proportional sync, keep settle gate`）。
  <task standards> 检查 `git log --oneline` 全部 commit 信息均含前缀。
- [ ] **9.2 后端 lint/test 不回退** — Run `ruff check .`、`ruff format --check .`、`pytest -q`。后端零改动预期，仅验证不回退；若 `ruff format --check` 提示文件需格式化，执行 `ruff format <file>` 后 amend 或新提交。
  <task standards> 完成后 GREEN：三个命令全 PASS。
- [ ] **9.3 前端自测全绿** — Run `node tests/run-alignment-controller-tests.mjs`、`node tests/run-zoom-tests.mjs`、`node tests/run-lazy-loader-tests.mjs`（及既有 `run-translator-tests.mjs` 等）。所有 `__TEST_*__` 块运行通过。
  <task standards> 完成后 GREEN：所有 `run-*-tests.mjs` 退出码 0。
- [ ] **9.4 最后一次 commit 不带 BREAKING 字样** — 全部变更通过既有 OpenSpec guard 后才推进到 verify 阶段。最后一次 commit 描述以"complete"语义而非 BREAKING；OpenSpec delta specs archive 阶段同步主 spec，本变更 PR 内不带 BREAKING CHANGE 标签。
  <task standards> 完成后 GREEN：`git log` 末条 message 无 BREAKING；OpenSpec guard 通过。

---

## 质量门

- `ruff check .` → All checks passed.（后端零改动预期）
- `ruff format --check .` → 无需格式改动（提示文件需格式化时执行 `ruff format <file>` 后重 check）。
- `pytest -q` → 全绿（仅验证后端不回退）。
- 前端自测：
  - `node tests/run-alignment-controller-tests.mjs` → PASS（包含 Section 1 复现 + Section 2 主线 + Section 5.5 grep 排他性 + Section 7 边界）。
  - `node tests/run-zoom-tests.mjs` → PASS（既有 11 个 + Section 4.1 新增 controller 接入测试）。
  - `node tests/run-lazy-loader-tests.mjs` → PASS（`settle.onSettle` 接口未动）。
  - `node tests/run-translator-tests.mjs` → PASS（翻译流程未动）。
- grep 排他性断言（对应 tasks.md 5.5）：除 `alignment-controller.js` 外，`static/modules/**` 与 `static/app.js` 内 `.scrollTop =` 赋值已移除；`zoom.js` 内 `col.scrollTop =` 作当前列锚点公式保留（由 Section 4 完成后调 controller 接管的语义间接保证，spec 排他性约束"两栏"对齐写入）。

## commit 节奏

- **一 task 一 commit**，commit message 前缀 `align-model-rewrite:`。
- message 主语描述设计意图而非步骤（例如 `feat(align): page-aligned realign + image-onload hook`、`refactor(scroll-sync): drop proportional sync, keep settle gate`、`feat(zoom): route post-zoom realign through controller`、`refactor(app): assemble AlignmentController, route onFinish/saved-page through it`）。
- TDD 严格：红测试 commit 后立刻实现 commit；同一 task 的红→绿可拆两个 commit 或合一个，但每条 `[ ]` 必须能独立追溯。

## 回滚策略

- 设计文档 (`docs/superpowers/specs/2026-06-28-align-model-rewrite-design.md`)、本计划 (`docs/superpowers/plans/2026-06-28-align-model-rewrite.md`)、delta specs 三份 (`openspec/changes/align-model-rewrite/specs/*`) 与代码改动**全部在同一变更 PR**。
- `git revert` 单个变更 PR 即完整回滚（前端 + 文档 + delta spec 一体）。
- archive 阶段前 delta spec 仅存在于 `openspec/changes/align-model-rewrite/specs/`，**不影响** `openspec/specs/` 主 spec；回滚不触及主 spec。
- archive 时由 `comet-archive` skill 同步 delta 至主 spec；若变更被回滚则不进入 archive。

## 风险与缓解

来源：design-doc §5「风险与缓解」表（verbatim 等价摘录，执行者可据此直接行动）。

- **R1** — 占位符 vs 真图高度 1~2px 差：jsdom fixture 复现测试（task 1.1 红 → 6.1 绿）；`onImageLoaded` 内 `realign()` 兜底。
- **R2** — zoom 跨页 / 视口在两页交界：jsdom 边界测试（task 7.2）；`intraPageOffset` 跨页标准化规则（D2 negative offset 退一页）。
- **R3** — 写入排他性被绕过：grep 测试断言（task 5.5）：除 `alignment-controller.js` 外 `static/modules/**` 与 `static/app.js` 无 `.scrollTop =` 给两栏。
- **R4** — realign 触发的 scroll 事件回流：`realigning` 重入守卫（task 2.3）+ 测试断言反馈事件不派生 target。
- **R5** — 急速滚动期对齐滞后：immediate realign（不走 settle debounce），task 7.3 测试 100 次 scroll 事件逐次对齐。
- **R6** — page 指示器在 realign 世界里跳动：page detection **仍走 settle** 不变（用户确认 A），仅 `pageIndex` 派生函数与 controller 共享；settle gate 留在 `scroll-sync.js`。
- **R7** — spec 契约变更破坏 archive：archive 阶段同步 MODIFIED 主 spec；design-doc 与 spec 在同一 commit 中一起推。

## 回到本变更（resume）

若上下文压缩或会话切档，主会话恢复执行此变更需重读以下工件并定位首个未完成 task：

- `.comet.yaml`（若存在，确认当前 phase = build / verify）。
- 本 plan：`docs/superpowers/plans/2026-06-28-align-model-rewrite.md`。
- design-doc：`docs/superpowers/specs/2026-06-28-align-model-rewrite-design.md`。
- 任务清单：`openspec/changes/align-model-rewrite/tasks.md`。
- 定位首个未勾选 task 的命令：

  ```powershell
  grep -nE '^- \[ \]' openspec/changes/align-model-rewrite/tasks.md | head -1
  ```

  或对齐本 plan 的等价命令（本 plan 的 task 编号与 tasks.md 1:1 对应）：

  ```powershell
  Select-String -Path 'docs\superpowers\plans\2026-06-28-align-model-rewrite.md' -Pattern '^\- \[ \]' | Select-Object -First 1
  ```

- 重读后从该 task 起按 commit 节奏继续；若该 task 是 RED 测试，先确认上一 task 的 GREEN commit 已落（`git log --oneline -5` 含 `align-model-rewrite:` 前缀）。