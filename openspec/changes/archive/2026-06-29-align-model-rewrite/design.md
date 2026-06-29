## Context

当前左右两栏的对齐行为散落在三个互不知情的模块：

- `scroll-sync.js` 的 `setupScrollSync`：监听两栏 `scroll` 事件，以 `scrollTop / (scrollHeight - clientHeight)` 比例互推另一栏 `scrollTop`，用 `syncing` 标志 + `setTimeout(0)` 防反馈环。
- `zoom.js` 的 `handleWheel` / `resetZoom`：改 `--zoom` CSS 变量并按"鼠标锚点公式"重算当前列 `scrollTop/Left`，让另一栏**被动靠 scroll 事件兜底对齐**。
- `app.js` 的 `onFinish` 翻译完成回调：`unloadPageImage` → `loadPageImage` 刷新右页图，新 `<img>` 的 `onload` 时机晚于 DOM 替换，期间两栏 `scrollHeight` 不一致。

现有 spec 把这套脆弱耦合**写成契约**：`dual-column-reading` 第 9 行规定同步必须 "bidirectional and proportional"，`page-zoom` 第 51 行规定 zoom 后对齐"via the existing scroll-sync"。这正是用户两次修对齐都把同步改坏、被迫回档的契约根源——任何对一处几何的修改，都被另一处按契约补回的比例公式反噬。

本变更的背景约束：
- 仅前端、零后端改动。
- 用户为 vibecoder，TDD 是本次唯一可靠护栏；测试需可在无浏览器交互的前提下运行（沿用现有 `scroll-sync.js` / `zoom.js` 的"自测块挂 `window.__TEST_*__` 直接在 jsdom/Node 跑"模式）。
- 必须显式列出 non-goals 防止范围蔓延（用户上次失控即源于此）。

## Goals / Non-Goals

**Goals:**
- 对齐状态归单一模块所有（AlignmentController），成为系统中唯一向两栏写入 `scrollTop` 的组件。
- 用"页对齐 + 页内像素偏移"取代比例同步：对齐目标表示为 `(pageIndex, intraPageOffsetPx)`，可由任一栏滚动派生，并能从外部触发"按目标重对齐两栏"。
- 翻译完成后图 `onload`、Ctrl+滚轮缩放、用户滚动三种触发源都汇入同一 realign 入口；任何一处修改都不再能"悄悄改坏对齐"。
- 每个公开决策几何可证（zoom 鼠标锚点 vs 页内偏移；占位符 vs 真图高度差）。
- 全程 TDD：失败测试先于实现；既有 `scroll-sync.js` / `zoom.js` 自测不得回退。

**Non-Goals:**
- 不动后端 `sse_stream.generate` / `generate_batch` 孪生重复（后续独立变更）。
- 不动 `state.py` `AppState` 神对象（后续独立变更）。
- 不改 SSE 协议、翻译流程、缓存策略、阅读进度上报。
- 不调整 `dom.js calculatePlaceholderHeight` 的数值；若设计阶段证明它是翻译后对齐失真的直接原点，仅通过 AlignmentController 在 image `onload` 重对齐兜底，不改公式。
- 不引入新的 npm 依赖（沿用现有 ES module + 内嵌自测模式）。

## Decisions

### D1. 引入 AlignmentController，确立 scrollTop 写入排他性

**选择**：新增 `static/modules/alignment-controller.js`，导出 `createAlignmentController({ leftEl, rightEl, column })`，返回 `{ onScroll, onImageLoaded, onZoomChange, realign, setLockTarget, getLockTarget, dispose }`。模块内部持有 `currentTarget = { pageIndex, intraPageOffsetPx }` 和 `lockSide ∈ {'left','right'}`。任何模块需要写两栏 `scrollTop` 时**只能**经此 controller 的 `realign()`。

**理由**：排他性是"动一处崩别处"的唯一根治手段。当前 scroll-sync、zoom、app.js 三处都能写 `scrollTop`，正是失控根因；把写入收敛到单一组件后，几何修改的"blast radius"由"整张前端"收缩到"controller 的 realign 算法"一处。

**替代方案**：
- (a) 在 `scroll-sync.js` 内塞所有对齐逻辑、让 zoom/app.js 直接调它 → 拒绝：scroll-sync 仍兼任 page detection 输入源，职责过载；且其模块名暗示行为而非所有权，长期会被再次污染。
- (b) 用全局事件总线（setLockTarget/runRealign 事件）取代显式 controller → 拒绝：vibecoder 维护可读性差，"谁在调谁"难以静态追踪。
- (c) 把 AlignmentController 实现为 class 而非工厂函数 → 拒绝：项目现有前端模块（`scroll-sync`、`zoom`、`lazy-loader`）均用工厂函数返回 `{ ..., dispose }` 一致风格，沿用之。

### D2. 对齐目标表示为 `(pageIndex, intraPageOffsetPx)`

**选择**：`pageIndex` 从 `page-container[data-page]` 取整；`intraPageOffsetPx` 为视口顶到当前页容器顶的像素偏移（可负，表示已滚过页面顶部一部分）。`realign()` 计算目标栏：找到目标页对应 `.page-container`，`scrollTop = pageContainer.offsetTop + intraPageOffsetPx`。`offsetTop` 用 `getBoundingClientRect` 相对栏减栏 rect 顶得到，避免依赖 scrollHeight 受未加载页占位符影响。

**理由**：以页为离散单位 + 页内像素偏移，可在两栏 `scrollHeight` 不一致时仍页对齐；不依赖"占位符高度 = 真图高度"恒等，正是翻译完成后失对齐的根因。

**替代**：
- (a) 表示为 `(pageIndex, intraPageOffsetRatio)`：0~1 页内比例。拒绝：缩放变化时页内像素偏移随 zoom 同比缩放，但作为"页内偏移"语义上不变；若用比例需在 zoom 时维护"鼠标跨页"的复合变换，复杂且与"页对齐"语义弱。
- (b) 表示为绝对 `scrollTop` 像素：拒绝：两栏 `scrollHeight` 不同时无对应关系，回到比例同步的缺陷。

### D3. 三类触发源汇入同一 realign 入口

**选择**：

```
                       AlignmentController.realign()
                                  ▲
        ┌─────────────────────────┼─────────────────────────┐
        │                         │                         │
  onScroll(src)             onImageLoaded(side,page)   onZoomChange(z,anchor)
   更新 target =                realign() 不更新         按 zoom 比例重算
   (pageOf(src),               target，仅按现            intraPageOffsetPx，再
    intraOffsetOf(src))         target 拉回                realign()
   lockSide = src
```

- **onScroll（用户滚动）**：从源栏派生 `(pageIndex, intraPageOffsetPx)` 写入 `currentTarget`，`lockSide = src`，然后 realign 目标栏。原 scroll-sync 模块的"读 scrollTop 算比例"被废止；scroll 事件监听退化为对齐 controller 的输入。
- **onImageLoaded（翻译后图刷新）**：不修改 `currentTarget`，照当前 target 重对齐被刷新的那栏（及对侧）。这正是翻译完成对齐失真的兜底——图片 `onload` 后显式 notify、controller 拉回，不依赖 scrollHeight 恒等。
- **onZoomChange**：zoom 由 `zoom.js` 完成 `--zoom` CSS 变量与当前列鼠标锚点的 `scrollTop/Left` 调整后，显式调用 `onZoomChange(z, anchor)`，controller 按 `newIntraOffset = oldIntraOffset * (newZoom/oldZoom)` 重算 `intraPageOffsetPx`（因页内像素高度随 zoom 同比缩放），再 `realign()` 把两栏都拉到新 target。取代 zoom.js 隐式靠 scroll 事件兜底。

**理由**：三源统一 realign 入口 = 排他性落地。每源"必须做什么、不能做什么"由契约固定（仅 onScroll 可写 target；另两源只 realign 不重设 target），契约限于一个文件，几何改动 blast 半径可量化。

### D4. settle/防抖的归属

**选择**：`createSettleGate` 由 `alignment-controller` 持有或与 it 合并为一；其 `onSettle` 回调用于 `setupPageDetection`（沿用现状）和 lazy-loader。实时对齐（scroll/zoom/image）走 immediate `realign`，不 debounce——避免用户滚动期间两栏滞后。仅 `pageDetection` 与 lazy-load 决策用 settle，因它们本就显式要求"读 settle 后的几何"。

**理由**：现有 `createSettleGate` 当前同时被 page detection、lazy-loader、以及隐式被 scroll-sync 在 zoom 后的"等同步稳定"借用。三处 settle 语义各异，是隐性耦合。明确拆分"实时对齐走立即 realign / 读布局决策走 settle"两面，各自契约单一。

**替代**：让 AlignmentController 也 debounce realign（150ms 后才同步）——拒绝：用户报告"对齐失真"恰恰要让实时同步更快、更确定，debounce 反而掩盖问题。

### D5. zoom 鼠标锚点与页内偏移的几何统一

**选择**：保留 `zoom.js` 现有"鼠标锚点"公式在**当前列**的应用（即当前列的 `scrollTop/Left` 仍按 `newScroll = (old + anchor) * r - anchor` 计算）；但 realign 另一栏时**不再用比例**，而是先把当前列的新 `scrollTop` 反推为对齐 target `intraOffsetOf(src)`，再 `realign` 另一栏。

**几何证明（简）**：当前列按 r 缩放、内容点 P 在缩放后仍位于 anchor，等价于新 `scrollTop` 满足 `P_top_new = P_top_old * r = newScrollTop + anchor`。对齐 controller 用 `pageOf(src)` + `(P_top_new - pageContainer_top_new)` 重算 `intraPageOffsetPx`，恰好是 `oldIntraPageOffset * r`（页内偏移随 r 等比缩放）。所以 zoom realign 与原 zoom 兼容，只是同步路径由"比例"改为"同 target"。D3 已据此设 onZoomChange 重算 `intraPageOffsetPx *= ratio`，与当前列锚点公式**几何等价**。

**理由**：让用户原 zoom 体验（鼠标下内容不动）不变，同时消除"另一栏靠比例兜底"的不可靠。

### D6. scroll-sync 模块职责收敛

**选择**：`scroll-sync.js` 仅保留 (i) `createSettleGate`（移交给对齐 controller 持有，或导出供其装配）和 (ii) `setupPageDetection`（按现有契约）。移除 `setupScrollSync` 的比例互推函数体；其装配点 `app.js:102` 改为 `controller.installScrollListener()`。`onPageChange` 行为与稳定要求不变，但其入口由对齐 controller 在 realign 后或 settle 时调用。

**理由**：模块语义更清楚——`scroll-sync.js` 成为"settle/page-detection 模块"，对齐逻辑不应再沾边；命名可在 archive 时考虑重命名（非本次 scope）。

## Risks / Trade-offs

- **[Risk] 占位符高度与真图高度差未量化** → 设计阶段写一个失败测试故意构造 `img.naturalHeight` 让 DOM reload 后产生 1~2px 偏差，复现"翻译完成失对齐"诱导；若 controller image-onload realign 能消解则证明兜底成立。若仍有残余（如分页容器 transform 抖动），列为 Open Question 不强求本次根治，仅保证 controller 暴露足够钩子让后续可补。
- **[Risk] zoom 鼠标锚点与页内偏移的几何统一在边界情况失真（如跨页缩放、视口顶部位于页中）** → `intraPageOffsetPx` 允许为正负，跨页时由 `pageIndex + (offset<0 ? 退一页 : pageOffset)` 标准化。设计阶段写边界场景测试（视口在两页交界 zoom）覆盖。
- **[Risk] setLockTarget 排他性被绕过** → 模块只导出 controller 公共面，不暴露 `currentTarget` 原值。`app.js`/`zoom.js` 不再写 `scrollTop`。lint 时人为审阅即可（无可静态强制的钩子）。这是 conscious trade-off：过度抽象会牺牲 vibecoder 可读性。
- **[Trade-off] 比"比例同步"实现更长** → 多一个模块、多 ~120 行代码与测试，换 blast radius 收缩；用户前两次失败成本远超此代价。
- **[Trade-off] 配套 spec 修改触发 breaking spec semantics** → `dual-column-reading` 与 `page-zoom` 的 MODIFIED 是契约级破坏，但本仓库 spec 仅服务于本项目自我约束，无外部消费者，敢于改契约为正确做法。archive 阶段设计文档与 spec 同步即可。

## Migration Plan

纯前端增量迁移，无数据/配置迁移：

1. 新增 `alignment-controller.js` 含完整自测（red）。
2. `app.js openPdf` 装配 AlignmentController 时**双轨保持一周 commit**：旧 `setupScrollSync` 与新 controller 并行运行（旧仅在新抛错时兜底），便于一个 commit 内可对比回归。本变更以 TDD 流程在 build 阶段切换完成；不强制"双轨保留"超过变更范围。
3. 删除旧 `setupScrollSync` 比例互推实现（同一 PR 内完成）。
4. `routes.py` 无关改动 0；后端测试不动。
5. 回滚策略：`git revert` 单个变更 PR 即恢复原状；spec 在 archive 前以未合并的 delta 形式存在，回滚不影响 main spec。

## Open Questions

1. `createSettleGate` 是否应物理搬迁进 `alignment-controller.js`（让对齐模块同时拥有 settle + realign），还是保持在 `scroll-sync.js` 仅按 D4 收紧职责？倾向后者（小模块优先），但 design-build 边界再定。
2. Page detection 在 realign 立即发生的世界里，是否仍需 settle debounce？实时页号变更可能更抖——需在测试中观察，必要时为 onPageChange 的派生单独加 settle。
3. 初始 PDF 打开后`saved_page` 恢复（`app.js:113-114`）的 `scrollToPage` 走 `scrollIntoView`，与新对齐 target 写入路径是否需要"显式作为 onZoomChange/initial-lock 入口"统一？倾向：在 controller 暴露 `setLockTarget(pageIndex, 0)` 与 `realign()` 帮助 `scrollToPage` 直接通过 controller 写入，app.js 不再绕过 controller 调 `scrollIntoView`。