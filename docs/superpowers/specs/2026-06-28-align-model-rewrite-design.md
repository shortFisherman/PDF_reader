---
comet_change: align-model-rewrite
role: technical-design
canonical_spec: openspec
---

# Design Doc — align-model-rewrite (左右栏对齐模型重构)

> Canonical specs live in `openspec/changes/align-model-rewrite/specs/`. This Doc is the Superpowers design record; conflicts defer to the specs.

## 1. 背景与现状

用户两次尝试修复左右两栏轻微不对齐（左边总比右边高一点），诱因分别是**翻译完成后图刷新**与**Ctrl+滚轮缩放**，两次都把**左右滚动同步**改坏、被迫 `git` 回档。

调查发现：左右对齐状态没有模块"拥有"它——它由 `scroll-sync.js setupScrollSync`、`zoom.js handleWheel/resetZoom`、`app.js onFinish` 三处各自的副作用拼成；更糟的是现有 spec 把这套脆弱结构写成了契约（`dual-column-reading` 规定"bidirectional and proportional"，`page-zoom` 规定 zoom 后对齐"via the existing scroll-sync"）。改一处必崩的根因即此。

```
AD_before:        scrollHeight-比例  →           scrollHeight-比例
  ┌────┐                                            ┌────┐
  │ 左 │ ──── sync靠被动 scroll 事件兜底 ────────▶ │ 右 │
  │    │ ◀───  zoom靠被动 scroll 事件兜底 ──────    │    │
  │    │     img onload 不通知任何人，             │    │
  │    │     scrollHeight 静悄悄变化               │    │
  └────┘                                            └────┘
   target = 比例 f = scrollTop/(H-ch)  ← H 不一致时失真
```

## 2. 目标 / 非目标

**目标**
- 对齐状态归单一组件所有（AlignmentController），是该系统中**唯一**向两栏写入 `scrollTop` 的组件。
- 用 `(pageIndex, intraPageOffsetPx)` 取代比例同步；目标页对齐 + 页内像素偏移。
- 翻译后图 `onload`、Ctrl+滚轮缩放、用户滚动三种触发源汇入同一 `realign()` 入口；任何一源改动都不再能"悄悄改坏对齐"。
- 全程 TDD：失败测试先于实现，覆盖两个失败诱因并复现、修复后转绿；既有自测不回退。

**非目标（防止"想顺便修一下"导致的失控）**
- 不动后端 `sse_stream.generate` / `generate_batch` 孪生重复（后续独立变更）。
- 不动 `state.py` `AppState` 神对象（后续独立变更）。
- 不改 SSE 协议、翻译流程、缓存策略、阅读进度上报、占位符高度公式 `dom.js calculatePlaceholderHeight`。
- 不动 `lazy-loader` 的 settle 接口 (`settle.onSettle + isScrollSettled`)；settle gate 不搬到 AlignmentController。
- 不引入新的 npm 依赖。

## 3. 关键决策

### D1. AlignmentController 排他性写入

新增 `static/modules/alignment-controller.js`，导出工厂 `createAlignmentController({ leftEl, rightEl })`，返回 `{ onScroll, onImageLoaded, onZoomChange, realign, setLockTarget, getLockTarget, installScrollListeners, dispose }`。任何前端模块要写 `scrollTop` 必须**经此 controller**。

**替代已否决**：把对齐算法塞回 `scroll-sync.js`（模块名暗示行为而非所有权，长期会被再次污染）；或全局事件总线（vibecoder 维护可读性差）。

### D2. 对齐目标 = `(pageIndex, intraPageOffsetPx)`

`pageIndex` 用 `page-container[data-page]` 取整；`intraPageOffsetPx` 可为负（视口顶高于页面容器顶=已滚过页顶一部分）。`realign(col)` 计算：

```
col.scrollTop = pageContainer.offsetTop + intraPageOffsetPx
```

其中 `pageContainer.offsetTop` = `pageContainer.getBoundingClientRect().top - col.getBoundingClientRect().top + col.scrollTop`（即"页面容器在栏坐标系下的绝对偏移"），与未加载页占位符对 `scrollHeight` 的贡献无关 → 在两栏 `scrollHeight` 不一致时仍页对齐。

**派生 target（来自 src）**：iterate `src.querySelectorAll('.page-container')`，选 rect 覆盖视口中点的页（视图边界用 `src.scrollTop ~ +clientHeight`）；计算 `intraOffset = src.scrollTop - pageContainer.offsetTop`，若 `< 0` 则 `pageIndex -= 1, intraOffset += page(idx+1).offsetHeight`（跨页标准化的内层规则）。

### D3. 三源汇入同一 `realign()` 入口

```
                                  AlignmentController.realign(target col)
                                              ▲
                 ┌────────────────────────────┼────────────────────────────┐
                 │                            │                            │
       onScroll(src)              onImageLoaded(side,page)       onZoomChange(newZoom,anchor)
       派生 (pageOf src,            仅 realign()，不改 target      intraOffset *= newZoom/oldZoom;
        intraOffsetOf src)                                        改 target 的 intraOffset；
       lockSide = src;                                            再 realign()
       再 realign 另一栏
```

- `onScroll` 唯一能改 `currentTarget`；另两者只 `realign()`（zoom 同时按 `r = newZoom/oldZoom` 同比缩放 `intraPageOffsetPx`）。
- `realigning` 守卫：`realign()` 入口置 flag，写完 `scrollTop`、卸载事件周期退出时清；`onScroll` 收到反馈事件时 `realigning==true` 即跳过派生 → 取代 `setTimeout(0)` syncing 标志。

### D4. `scroll-sync.js` 职责收敛（用户确认 A）

- 删除 `setupScrollSync` 比例互推实现（即 line 50–70 函数体）。
- 保留 `createSettleGate`（settle gate 仍住此模块，供 lazy-loader 与 page-detection 消费）。
- 保留 `setupPageDetection`（page detection 通过 settle 回调，沿用现有契约）。
- `app.js:102` 处对外 `setupScrollSync(...)` 调用解除，改由 `AlignmentController.installScrollListeners()` 接管 scroll 监听并委托回 controller `onScroll`。
- 用户决议：**lazy-loader 接入方式 = I**（不动其接口；realign 产生的 scroll 事件沿现有路径间接重置 settle timer，与现状一致）。

### D5. zoom 鼠标锚点与页内偏移的几何统一

`zoom.js` 在当前列仍按现有锚点公式 `newScrollTop = (oldScrollTop + cy) * r - cy` 调当前列。完成后**显式**调 `controller.onZoomChange(r)`。controller 在 `onZoomChange` 内 `intraOffset *= r` 再 `realign()` 把两栏都拉到新 target（target 的 intraOffset 已缩放）。

**几何等价简证**：当前列锚点公式对内容点 P 满足 `P_top_new = P_top_old * r`，且 `P_top_new = newScrollTop + cy = (oldScrollTop + cy) * r - cy + cy = (oldScrollTop + cy) * r`，恰是 `P_top_old * r`（因 `P_top_old = oldScrollTop + cy`）。controller 用 `pageIndex = pageOf(src)` 和 `newIntraOffset = pageIntraOffset_old * r`，几何上让 `P_top_new` 落在新版的同一内容点。两路径对**当前列**等价，对**另一列**取代"靠 scroll 事件兜底"为"同 target 拉回"。

### D6. 翻译完成图刷新路径

`app.js onFinish`：
1. `unloadPageImage(rightEl)` → `loadPageImage(rightEl)`，触发新 `<img>.onload`。
2. `<img>.onload` 内部回调里调 `controller.onImageLoaded('right', targetPage)`。
3. `onImageLoaded` 不改 target，仅 `realign()` 拉回两栏。即使图片实际高度与占位符差 1~2px，也由 realign 兜底对齐。

### D7. 保存页恢复路径（Open Question 3）

`app.js openPdf` 中现有 `scrollToPage(saved)` 改为：
```js
controller.setLockTarget(saved, 0);
controller.realign();
```
完全不经 `scrollIntoView`；alignment 自此从首帧起被 controller 拥有。

### D8. 测试入口（Design 已确定为 `tests/run-alignment-controller-tests.mjs`）

- 模式：`node tests/run-alignment-controller-tests.mjs`，使用 jsdom + `window.__TEST_ALIGNMENT_CONTROLLER__` 全局标记触发 `alignment-controller.js` 末尾的自测块；脚本 `await globalThis.__ALIGNMENT_CONTROLLER_TESTS_DONE__` 等位完成。
- `package.json scripts`：增 `"test:align": "node tests/run-alignment-controller-tests.mjs"`。
- README 末尾"前端测试"章节加一行，与现有 `test:translator` / `test:zoom` 描述风格一致。

## 4. 数据流（重构后）

```
┌───────────────────────────────────────────────────────────────────────┐
│                              AlignmentController                          │
│  state: currentTarget = {pageIndex, intraPageOffsetPx}, lockSide    │
│  ─────────────────────────────────────────────────────  │
│  onScroll(src)      → derive target → realign(dst)        │
│  onImageLoaded(side,page) → realign(src,dst)                 │
│  onZoomChange(r)    → intraOffset *= r → realign(both)      │
│  setLockTarget(N,offset), realign(col) [settle 独立]   │
└───────────────────────────────────────────────────────────────────┘
       ▲                       ▲                       ▲            ▲
       │                       │                       │            │
  scroll 事件            <img>.onload            zoom.js              app.js
  (双栏监听)             onFinish                (完成当前列锚点)   saved_page 恢复
       │                       │                       │
       |                       |                       |
  [scroll-sync.js]         [app.js]               [zoom.js]
   (settle / pageDetect)   (orchestrate)          (zoom + 锚点)
```

## 5. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 占位符 vs 真图高度 1~2px 差 | jsdom fixture 复现测试（task 1.1 红 → 6.1 绿）；onImageLoaded realign 兜底 |
| R2 | zoom 跨页 / 视口在两页交界 | jsdom 边界测试（task 7.2）；`intraPageOffset` 跨页标准化规则 |
| R3 | 写入排他性被绕过 | grep 测试断言 (task 5.5)：除 alignment-controller.js 外无 `.scrollTop =` 给两栏 |
| R4 | realign 触发的 scroll 事件回流 | `realigning` 重入守卫（task 2.3）+ 测试断言反馈不派生 target |
| R5 | 急速滚动期对齐滞后 | immediate realign（不走 settle debounce），task 7.3 测试 100 次 scroll 事件都逐次对齐 |
| R6 | page 指示器在 realign 世界里跳动 | page detection **仍走 settle** 不变（用户确认 A），仅 pageIndex 派生函数与 controller 共享 |
| R7 | spec 契约变更破坏 archive | archive 阶段同步 MODIFIED 主 spec；design-doc 与 spec 在 commit 中一起 |

## 6. 测试策略

- TDD：失败复现测试先行（task 1.1/1.2 因现有比例实现的红测试）→ controller 主线红→绿（task 2.x）→ 拆掉 scroll-sync 旧实现并保既有自测不回退（task 3.x）→ zoom、app.js 路由 controller（task 4.x/5.x）→ 失败诱因复现测试绿（task 6.1/6.2）→ 边界场景（task 7.x）→ 测试入口 + README（task 8.x）→ commit/lint/pytest 全绿（task 9.x）。
- 一个 task 一个 commit，message 前缀 `align-model-rewrite:`。
- 后端零改动：`ruff check .`、`ruff format --check .`、`pytest -q` 仅验证不回退。

## 7. 迁移与回滚

- 纯增量前端：新建 `alignment-controller.js` + 自测 → 改 `scroll-sync.js`(删 setupSync 函数体) → 改 `zoom.js`(接入 controller) → 改 `app.js`(`onFinish` 接入 + `openPdf` 装配 controller + `scrollToPage` 走 controller) → 加测试入口。所有改动在同一变更 PR 内完成。
- 回滚：`git revert` 单个变更 PR；OpenSpec delta spec 在 archive 前以未影响 main spec 的形式存在，回滚 → 不触及 main spec。

## 8. Open Questions（design-build 边界再决定的不需用户拍板项）

1. **D4 已答**：settle 保留在 `scroll-sync.js`，AlignmentController 不拥有 settle。✅ 用户确认 A。
2. **lazy 接入已答**：沿用现有路径，不主动 trigger settle。✅ 用户确认 I。
3. **scrollToPage 路由**：已收为 column-alignment spec 第 5 条 Requirement。✅
4. ** arbeitet** 与 D2 跨页标准化的内层函数实现细节——build 阶段以 TDD fixture 实现，不需要用户拍板。

## 9. Spec 影响

无 Spec Patches 需要回写（brainstorming 没新增/删除/重写 acceptance scenario）。comet-open 阶段的 `specs/column-alignment/spec.md` / `specs/dual-column-reading/spec.md` / `specs/page-zoom/spec.md` 已涵盖 brainstorming 全部决议。

## 10. 实施边界与下发

tasks.md（同目录 OpenSpec artifact）已按 TDD 流分组到 9 节、~30 个复选框。本文档与 tasks.md 共同作为 comet-build 阶段实现依据。