---
change: fix-lazy-load-scroll
design-doc: docs/superpowers/specs/2026-06-26-fix-lazy-load-scroll-design.md
base-ref: 1affb4f4ccd72d552240ff2289e8cfcad837935f
archived-with: 2026-06-24-fix-lazy-load-scroll
---

# Implementation Plan — 修复前端懒加载与滚动同步

> 任务清单以 `openspec/changes/fix-lazy-load-scroll/tasks.md` 为准（18 项，5 组）。本计划补充执行顺序、依赖、每步实现要点与验证手段。设计与方案依据见 `docs/superpowers/specs/2026-06-26-fix-lazy-load-scroll-design.md`（方案 B：IO 降级为候选标记 + 单一 settle 闸门）。

## 执行顺序与依赖

```
组1 闸门基础设施 ──► 组4 懒加载重构（依赖 settle/onSettle/比例同步）
组2 样式对齐 ──────────────────► （独立，尽早合入）
组3 双向比例同步 ─► 组4（IO 回调可触发滚动→比例同步协作）
                       组1 + 组2 + 组3 + 组4 ─► 组5 验证
```

- 组2（style.css width:100%）与组1 无依赖，可最先执行并立即验证高度不变。
- 组1 的 settle 闸门是组4 的前置；组3 的比例同步是组4 IO 引发滚动时的协作前置。
- 组4 内部：先改 IO 回调（4.1）→ 候选集扫描（4.2）→ 延迟卸载（4.3）→ app.js 加载守卫/卸载守卫（4.4/4.5）。

## 实现要点（按 tasks.md 编号）

### 组1 滚动稳定闸门基础设施
- 1.1 `scroll-sync.js` 新增 `createSettleGate(left,right)`，导出 `{ isScrollSettled, onSettle, dispose }`。常量 `SETTLE_MS=150`。任一栏 `scroll` → 重置定时器；到期 `set settled=true` 并触发 `onSettle` 回调队列。
- 1.2 `app.js` `openPdf` 中先 `const settle = createSettleGate(els.leftCol, els.rightCol)`，传入 `setupIntersectionObserver({ settle, load, unload })`，并供 `setupPageDetection` 复用。

### 组2 图片尺寸与占位对齐
- 2.1 `style.css`：`.page-container img` `max-width:100%` → `width:100%`。
- 2.2 核对 `dom.js calculatePlaceholderHeight` 与 `width:100%/height:auto` 同页宽下高度一致；公式一致即成立，预期无需改，仅复核。

### 组3 双向按比例滚动同步
- 3.1 `setupScrollSync({left,right})` 重写：源栏 scroll → `f = src.scrollTop/(src.scrollHeight-src.clientHeight)`（`scrollHeight<=clientHeight` 时 f=0）→ rAF 内 `syncing=true` 设 `tgt.scrollTop = f*(tgt.scrollHeight-tgt.clientHeight)`，帧末清 `syncing`。目标栏 scroll 处理器入口若 `syncing` 为真则直接 return。
- 3.2 除零退化已隐含于 3.1。
- 3.3 `setupPageDetection({container},onPageChange)`：不再每 scroll 计算；改为 `onSettle(dispose)` 后遍历 `.page-container` 取 `getBoundingClientRect`，选与视口相交面积最大者（保留>50%启发），调 `onPageChange`。

### 组4 懒加载重构
- 4.1 `lazy-loader.js` 重写：`rootMargin≈200%`（约2页）；回调 `entry.isIntersecting ? pendingLoad.add(page) : pendingReclaim.add(page)`；**不调 load/unload**。维护 `pendingLoad`/`pendingReclaim`（Set）。
- 4.2 `settle.onSettle(scan)`：`scan` 计算视口页范围（用 `getBoundingClientRect` 判与容器视口相交，或由 `scrollTop/clientHeight` 与占位高度换算）。`pendingLoad` 若在视口±`BUF(=2)` 调 `load` 否则丢弃；`pendingReclaim` 若距视口>`RECLAIM_DISTANCE(=10)` 调 `unload` 否则移出回收集。扫描后清空已处理项。
- 4.3 延迟卸载已由 4.2 的 settle 扫描自然实现（确认：跨步来回时 `pendingReclaim` 在未 settle 前不执行 unload → 无振荡）。
- 4.4 `app.js loadPageImage(container)`：守卫改读 `container.dataset.loaded`；`'true'` 直接 return；建 img 设 src；`img.onload` 内 `placeholder.replaceWith(img)` 且置 `dataset.loaded='true'`；`onerror` 置 `dataset.loaded='error'`。
- 4.5 `app.js unloadPageImage(container)`：仅 `dataset.loaded==='true'` 卸载；建占位（`calculatePlaceholderHeight`），`img.replaceWith(placeholder)`，置 `dataset.loaded='false'`。

### 组5 验证（手动回归，对应四类场景）
- 5.1 长距跳转请求≤~5；5.2 双向 50% 同页对齐；5.3 边界来回无振荡/重复 `?t=`；5.4 缓滚逐页加载无重复、加载前后 `offsetHeight` 不变。

## 验证手段

- 浏览器网络面板数 `/api/page/*` 请求数（5.1）。
- `console` 检查 `container.dataset.loaded` 去重（5.3/5.4）。
- DOM `element.offsetHeight` 加载前后比对（5.4）。
- 无单测基建，不跑 `npm test`/构建命令；前端静态资源由 Flask dev server 提供，回归时直接刷新页面观察。

## 隔离与提交

- 在专用分支上逐组提交，commit message 前缀 `fix:`（如 `fix: 双向按比例滚动同步`）。
- 每组完成后勾选对应 tasks.md 任务。
- 全部完成后运行 build phase guard 进入 verify。
