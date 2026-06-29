# Comet Design Handoff

- Change: align-model-rewrite
- Phase: design
- Mode: compact
- Context hash: cdf9f4a473694df4d9ddca1f49d4030951aaae13260c763fa7234f1316742f11

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/align-model-rewrite/proposal.md

- Source: openspec/changes/align-model-rewrite/proposal.md
- Lines: 1-42
- SHA256: da45eb5096400de596b2f0b83eff383f632e678440b6e71dc057b23de0f3074e

```md
## Why

用户在维护此项目时，连续两次尝试修复左右两栏的轻微不对齐问题（左边总比右边高一点，分别在"翻译完成后"和"Ctrl+滚轮缩放时"两个场景诱发），每次修完都会把左右滚动同步改坏，被迫 `git` 回档。根因调查发现：左右对齐状态目前没有任何模块"拥有"它——它是 `scroll-sync`、`zoom`、`app.js` 翻译完成回调三个地方各自的副作用，三者彼此隐式依赖、互相不知道。更糟糕的是，现有 spec 把这个脆弱结构**写成了契约**：`dual-column-reading` 规定同步必须是"bidirectional and proportional"（`scrollTop / (scrollHeight - clientHeight)`），`page-zoom` 的"对齐保持"场景又显式依赖这条比例 scroll-sync 兜底。契约本身就把对齐所有权摊给了两个模块，于是一改就崩。

本次变更把对齐状态收归单一模块所有，建立"页对齐 + 页内偏移"语义取代比例同步，让翻译完成图刷新、Ctrl+滚轮缩放、用户手动滚动三个场景下的对齐行为都从同一写入点派生。这样后续任何对图刷新路径、缩放公式或新交互的修改，都不会再隐式破坏对齐。

## What Changes

- **BREAKING（spec 层语义变更）**：将 `dual-column-reading` 的"bidirectional and proportional scroll sync"语义替换为"页对齐 + 页内偏移同步"语义——对齐目标由 `(页号, 页内偏移)` 二元组表达，由独立的对齐模块维护，scroll 事件仅更新对齐目标，不再直接以比例互推 `scrollTop`。
- **BREAKING（spec 层语义变更）**：将 `page-zoom` 的"zime 后靠比例 scroll-sync 兜底对齐"语义替换为"zime 后由对齐模块按当前对齐目标重新执行对齐"，并明确 zoom 锚点公式与页内偏移语义的关系。
- 新增前端模块 `alignment-controller`，作为唯一向两栏写入 `scrollTop` 的组件，统一处理"用户滚动 / 图载入完成 / 缩放变化"三类触发源；所有其他模块通过事件或回调委托其重对齐，不再直接写 `scrollTop`。
- `scroll-sync` 模块退化为对齐模块的输入源之一（滚动事件 → 更新 `(页号, 页内偏移)` 目标），移除其内嵌的比例互推实现；页面检测 (`setupPageDetection`) 行为保持，但调用点由对齐模块协调。
- `zoom` 模块的 `handleWheel`/`resetZoom` 在改完 `--zoom` 与当前列锚点后，不再被动等待 scroll 事件兜底，而是显式调用对齐模块重对齐另一栏；`syncing` 标志与 `setTimeout(0)` 解锁移出 scroll-sync，由对齐模块统一管理防抖。
- `app.js` 中翻译完成回调 `onFinish` 的右页刷新逻辑（`unloadPageImage` → `loadPageImage`）在 `<img onload>` 触发后，显式通知对齐模块按当前对齐目标重对齐，消除图片载入延迟导致的残余偏差。
- 全程 TDD：先为"页对齐 + 页内偏移"语义及两个失败诱因（翻译完成、缩放）写失败测试锁定预期行为，再重构实现至测试全绿；保留并扩展 `scroll-sync.js` / `zoom.js` 中既有前端自测，确保不回退既有场景。

## Capabilities

### New Capabilities
- `column-alignment`: 对齐状态所有权与"页对齐 + 页内偏移"同步语义。定义 AlignmentController 的写入排他性、对齐目标的表示与更新规则、跨触发源（scroll / image-loaded / zoom）的重对齐入口，以及对齐 settle 的防抖契约。`specs/column-alignment/spec.md` 为本 capability 唯一规格。

### Modified Capabilities
- `dual-column-reading`: Requirement "Two synchronized scrollable columns" 中"bidirectional and proportional scroll sync"条款被替换为"页对齐 + 页内偏移"语义并显式委托给 `column-alignment` capability；`scroll-sync` 模块不再 own 同步算法；保留"two scrollable columns / 浮动工具栏 / 页指示器稳定"等不受同步算法影响的行为。
- `page-zoom`: Requirement "Cursor-anchored zoom" 的子场景"Vertical alignment preserved across columns"由"靠比例 scroll-sync 兜底"改为"经对齐模块按当前对齐目标重对齐另一栏"，并明确"两栏 zoom 同步应用"不再依赖跨栏比例对齐兜底。

## Impact

- **代码影响**：
  - `static/modules/scroll-sync.js`：`setupScrollSync` 比例互推实现退化为对齐模块的事件转发 / page detection 输入源；`createSettleGate` 防抖职责搬迁至对齐模块（或保留但语义改为对齐 settle）。
  - `static/modules/zoom.js`：`handleWheel`/`resetZoom` 在改完 zoom 与当前列锚点后，调用对齐模块 `realign()`；移除"被动靠 scroll 事件兜底"假设。
  - `static/modules/app.js`：翻译完成回调 `onFinish` 在右页图 `onload` 后通知对齐模块 `realign()`；引入并装配 AlignmentController。
  - 新增模块文件：`static/modules/alignment-controller.js`（含对应前端自测）。
- **非代码影响**：
  - 前端仅改动；后端零修改（`routes.py` / `sse_stream.py` / `state.py` 等均不动）。
  - 现有后端测试与 `{ruff,pytest}` 流水不受影响；前端自测新增。
- **显式 Non-goals**（避免上次"想顺便修一下"导致的失控）：
  - 不动后端 `sse_stream.generate` / `generate_batch` 孪生重复——后续独立变更。
  - 不动 `state.py` 的 `AppState` 神对象——后续独立变更。
  - 不修改 SSE 协议、翻译流程、缓存策略、阅读进度上报。
  - 不调整页面占位符高度公式 `dom.js calculatePlaceholderHeight` 的数值，除非设计阶段证明它是翻译后对齐失真的直接原点。
- **风险**：
  - 占位符高度与真实图片渲染高度是否完全一致，是"翻译完成图刷新是否破坏对齐"的关键未知项。若设计阶段验证发现存在量化误差，对齐模块需在图 `onload` 触发点重对齐，而非依赖占位符高度恒等——已在 scenario 中纳入。
  - zoom 锚点是基于"鼠标位置"的连续公式，引入"页内偏移"离散语义后二者需统一，存在设计整合风险，design 阶段需给出几何等价证明或合理近似。```

## openspec/changes/align-model-rewrite/design.md

- Source: openspec/changes/align-model-rewrite/design.md
- Lines: 1-120
- SHA256: e46591d1eef0426f315bc037cc5dd3b6a57a9aa29d0d896c9e87a0ee9cd462fe

[TRUNCATED]

```md
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

```

Full source: openspec/changes/align-model-rewrite/design.md

## openspec/changes/align-model-rewrite/tasks.md

- Source: openspec/changes/align-model-rewrite/tasks.md
- Lines: 1-55
- SHA256: 175a7fbcddf619fd1741be30b920e3373e64d84eead9d0b11ab61b488527ea75

```md
## 1. 锚定"翻译后失对齐"复现（红：复现样例测试，不改代码）

- [ ] 1.1 在 `static/modules/__tests__/` 下新建对齐复现 fixture：用 jsdom 构造两栏 × 多页容器（占位符 + `<img>` 用 `naturalHeight` 让图片高度与占位符预留高度差 2px），断言"翻译完成后替换图后，两栏 `pageIndex` 顶部偏移之差 > 0"。预期：在当前实现下应失败（红）。运行自测脚本（沿用 `scroll-sync.js` 末尾 `window.__TEST_*__` 模式）记录失败输出。
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
- [ ] 9.4 最后一次 commit 不带 BREAKING 字样，全部变更通过既有 OpenSpec guard 后才推进到 verify 阶段。```

## openspec/changes/align-model-rewrite/specs/column-alignment/spec.md

- Source: openspec/changes/align-model-rewrite/specs/column-alignment/spec.md
- Lines: 1-80
- SHA256: 64fee9f4b9b56e7e30a31cac7483b93984938c1c2fc964b1edd8c5a0d969eec7

```md
## ADDED Requirements

### Requirement: Alignment write ownership

The system SHALL make `AlignmentController` the sole writer of `scrollTop` to both the left and right scroll columns. No other frontend module (`scroll-sync`, `zoom`, `app.js`, translator callbacks) SHALL write `scrollTop` of either column directly. Any module needing to drive alignment SHALL route through AlignmentController's public surface (`setLockTarget`, `realign`, `onScroll`, `onImageLoaded`, `onZoomChange`). The `alignment-controller` frontend module SHALL own this logic.

#### Scenario: Translator finish refresh routes through controller

- **WHEN** a page translation finishes and the right-column page image is unloaded then reloaded, finally firing `<img>.onload`
- **THEN** `app.js` SHALL notify AlignmentController via `onImageLoaded(side, pageIndex)` instead of relying on a side-effect scroll event, and AlignmentController SHALL call `realign()` to pull both columns back to the current alignment target without modifying the target.

#### Scenario: Zoom routes through controller

- **WHEN** the user Ctrl+wheel zooms and `zoom.js` finishes applying `--zoom` and the current column's anchor-corrected `scrollTop`
- **THEN** `zoom.js` SHALL notify AlignmentController via `onZoomChange(newZoom, anchor)`, and AlignmentController SHALL rescale the current `intraPageOffsetPx` by `newZoom/oldZoom` and call `realign()` so both columns keep the same alignment target; `zoom.js` SHALL NOT passively rely on a `scroll` event to drag the other column along.

#### Scenario: User scroll updates target and realigns opposite

- **WHEN** the user scrolls either column
- **THEN** `scroll-sync`'s scroll listener (still wired by `app.js`) SHALL delegate to AlignmentController's `onScroll(src)`, which SHALL derive `(pageIndex, intraPageOffsetPx)` from `src`, update the alignment target, set `lockSide = src`, and call `realign()` to write the opposite column's `scrollTop`. The listener SHALL NOT compute or write any proportional `scrollTop` itself.

#### Scenario: No silent alignment writes outside controller

- **WHEN** any frontend module other than `alignment-controller.js` is grep-searched for direct `scrollTop =`
- **THEN** no assignment to `.scrollTop` of either column SHALL remain except inside `alignment-controller.js`.

### Requirement: Alignment target semantics

Alignment target SHALL be a tuple `(pageIndex: integer, intraPageOffsetPx: number)` where `pageIndex` is the page in the viewport and `intraPageOffsetPx` is the pixel offset from the top of that page's container to the viewport top (may be negative when the viewport top is above the page container top). `realign(column)` SHALL compute `column.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`, where `offsetTop` is resolved via `getBoundingClientRect` relative to the column (NOT `scrollHeight`-based fractions), so alignment is robust to differences in total column scrollable height and to placeholder-vs-image height mismatch.

#### Scenario: Page index recovered from source column

- **WHEN** `onScroll(src)` fires for a column showing page N straddling the viewport top
- **THEN** AlignmentController SHALL select `pageIndex = N` when more than half of page N's container intersects the viewport, else the page whose container covers the viewport top center.

#### Scenario: Two columns of differing scrollHeight stay page-aligned

- **WHEN** left and right columns have different `scrollHeight` (e.g. the right column's translated page is 1~2 px shorter than placeholder) and the alignment target is `(N, 30px)`
- **THEN** after `realign()` both columns SHALL show the top of page N offset by 30px from the viewport top, with no residual sub-pixel drift attributable to proportional scrolling.

#### Scenario: Intra-page offset scales with zoom

- **WHEN** zoom changes from `z0` to `z1` while the alignment target is `(N, offsetPx_at_z0)`
- **THEN** AlignmentController SHALL update `intraPageOffsetPx = offsetPx_at_z0 * (z1/z0)`, because page-content pixel heights scale with `--zoom`, so the same visible point remains under the original cursor anchor after realign.

### Requirement: Cross-trigger-source realign entry

`AlignmentController.realign()` SHALL be the single geometric entry that writes `scrollTop`s. `onScroll`, `onImageLoaded`, and `onZoomChange` SHALL all converge on it. `onScroll` is the only trigger that may mutate `currentTarget`; `onImageLoaded` and `onZoomChange` SHALL NOT change `(pageIndex, intraPageOffsetPx)` except `onZoomChange` rescaling the offset as required by "Alignment target semantics".

#### Scenario: Image reload does not drift target

- **WHEN** a translated page image reloads and its rendered height is 1~2 px different from its placeholder
- **THEN** `onImageLoaded` SHALL keep `(pageIndex, intraPageOffsetPx)` unchanged and `realign()` SHALL pull both columns back to the existing target, eliminating the prior "left column higher than right by a bit" drift.

#### Scenario: Reentrant realign guarded

- **WHEN** `realign()` writes a column's `scrollTop` and the resulting `scroll` event fires back into `onScroll`
- **THEN** AlignmentController SHALL detect reentrancy via an internal `realigning` flag and skip the derived-target update for that feedback event; the existing alignment target SHALL remain authoritative.

### Requirement: Settle and page detection ownership

`AlignmentController` SHALL own the settle gate used by `realign()` and page-detection. Real-time alignment (scroll / zoom / image) SHALL run immediately and SHALL NOT be debounced. Page-detection callback `onPageChange` MAY be debounced via settle, as in the prior behavior, to keep the page indicator from jittering near page boundaries.

#### Scenario: Immediate alignment during continuous scroll

- **WHEN** the user drags the scrollbar continuously
- **THEN** both columns SHALL stay aligned on every scroll event (no debounce-induced lag), scrolling settling at the same `pageIndex` and `intraPageOffsetPx`.

#### Scenario: Page indicator still debounced

- **WHEN** the viewport straddles the boundary between page N and N+1 while scrolling momentarily settles near the boundary
- **THEN** the toolbar page indicator SHALL still go through the settle gate (≥ ~150ms of no scroll) before updating, matching the prior stability requirement, and AlignmentController SHALL expose a settle callback hook for this.

### Requirement: Initial-open saved page restore routes through controller

When `app.js` reopens a PDF with a saved `reading-progress` page index, it SHALL align the columns via AlignmentController's `setLockTarget(pageIndex, 0)` followed by `realign()`, instead of bypassing the controller with direct `scrollIntoView`. This keeps the initial alignment target owned by the controller from the very first frame.

#### Scenario: Reopened PDF aligns through controller

- **WHEN** a PDF is reopened and the server returns `saved_page = K`
- **THEN** `app.js` SHALL call `controller.setLockTarget(K, 0)` then `controller.realign()` and SHALL NOT call `scrollIntoView` on the page container directly.```

## openspec/changes/align-model-rewrite/specs/dual-column-reading/spec.md

- Source: openspec/changes/align-model-rewrite/specs/dual-column-reading/spec.md
- Lines: 1-24
- SHA256: 97a6416822ed66f95c7c3475e94d5bbd6884df6d2b0552f2f39c21e0688b0d45

```md
## MODIFIED Requirements

### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization SHALL be **page-aligned with intra-page pixel offset**, owned by the `alignment-controller` frontend module: scrolling either column SHALL derive a `scrollTop`-independent alignment target `(pageIndex, intraPageOffsetPx)` and the other column SHALL be realigned to that target via `AlignmentController.realign()` within the source scroll event handler (no frame deferral). A `realigning` guard SHALL prevent feedback loops without relying on `setTimeout(0)` unlock of a `syncing` flag. The prior `scroll-sync` proportional formula `scrollTop / (scrollHeight - clientHeight)` SHALL NOT be used. The `scroll-sync` frontend module SHALL remain responsible for `createSettleGate` and `setupPageDetection`, but SHALL NOT own the sync algorithm.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Left-driven page-aligned sync

- **WHEN** the user scrolls the left column so that page N's container top sits 30px below the viewport top
- **THEN** the right column SHALL realign synchronously (no frame deferral) to the same `(pageIndex = N, intraPageOffsetPx = 30)` target, regardless of differences in total scrollable height between the two columns, instead of matching a fractional scroll position.

#### Scenario: Right-driven page-aligned sync

- **WHEN** the user scrolls the right column independently so that page N's container top sits 30px below the viewport top
- **THEN** the left column SHALL realign synchronously to `(pageIndex = N, intraPageOffsetPx = 30)`, regardless of differences in total scrollable height, replacing the prior proportional behavior.

#### Scenario: No sync feedback loop

- **WHEN** `realign()` writes the destination column's `scrollTop` and the resulting `scroll` event fires back
- **THEN** AlignmentController SHALL detect the reentrant realign via its `realigning` guard and SHALL NOT re-derive the alignment target from this feedback event; the prior alignment target SHALL remain authoritative.```

## openspec/changes/align-model-rewrite/specs/page-zoom/spec.md

- Source: openspec/changes/align-model-rewrite/specs/page-zoom/spec.md
- Lines: 1-14
- SHA256: 710806410e6db87198fc6fdb4f496d92fc482e11b1ab23e586a9a543571baa3c

```md
## MODIFIED Requirements

### Requirement: Cursor-anchored zoom

The system SHALL anchor zoom at the cursor position so the content point under the cursor remains under the cursor after zooming. For a zoom change from `z0` to `z1` with ratio `r = z1/z0` and cursor offset `(cx, cy)` relative to the active column, the new scroll positions for the active column SHALL be `newScrollTop = (scrollTop + cy) * r - cy` and `newScrollLeft = (scrollLeft + cx) * r - cx`. The `--zoom` variable SHALL be applied before setting the new scroll positions on the active column. After the active column is adjusted, the other column SHALL be realigned by invoking `AlignmentController.onZoomChange(z1, anchor)`; the other column SHALL NOT rely on a `scroll` event to catch up via proportional scroll-sync. AlignmentController SHALL rescale its current `intraPageOffsetPx` by `r` before realigning, per the `column-alignment` capability's "Alignment target semantics".

#### Scenario: Content under cursor stays fixed

- **WHEN** the user positions the cursor over a specific word and zooms in with Ctrl+wheel
- **THEN** that word SHALL remain under the cursor after the zoom completes

#### Scenario: Vertical alignment preserved across columns

- **WHEN** the user zooms with Ctrl+wheel over the left column and the zoom completes
- **THEN** AlignController SHALL realign the right column to the same `(pageIndex, intraPageOffsetPx * r)` target, so both columns remain vertically aligned at the same content point zoom-correctly, instead of being dragged by a residual proportional scroll event.```

