---
comet_change: fix-lazy-load-scroll
role: technical-design
canonical_spec: openspec
---

# Design Doc — 修复前端懒加载与滚动同步

## 概述

修复 PDF 阅读器前端分页交互的三个缺陷：(1) 拖滚动条长距离跳转淹没约 500 次页面请求；(2) 左右两栏单向绝对 scrollTop 同步导致错位、图片加载后高度跳变使单边塞两页看不全；(3) 翻页边界 `load→unload→load` 振荡造成抖动与重复请求。根因同源于懒加载与滚动同步的脆弱设计，需要架构层面收敛。

## 确认的技术方案（方案 B：IO 降级为候选标记 + 单一 settle 闸门）

核心思想：**把"何时加载/卸载"收敛到单一时间线（scroll-settled），把"哪些页值得加载"交给 IntersectionObserver 的缓冲检测本职**，双线变单线，根除振荡。

### 架构与数据流

```
                      scroll事件(left/right)
                              │
                    ┌─────────▼──────────┐
                    │ scroll-sync 闸门    │
                    │ unstable + 150ms   │ ── 双向按比例同步 ──► 目标栏 scrollTop
                    │ settle -> settled  │      (rAF, syncing 守卫)
                    └─────────┬──────────┘
                              │ isScrollSettled()/onSettle(cb)
                              │
   ┌──────────────────────────┼──────────────────────────────┐
   ▼                                                         ▼
┌────────────────────┐                              ┌─────────────────────┐
│ IntersectionObserver│                              │  settle 回调扫描      │
│ rootMargin≈2 页    │ 进入缓冲►pendingLoad(+page)  │                      │
│ (lazy-loader.js)   │ 彻底离开►pendingReclaim      │ pendingLoad∩视口±缓冲►load
│ 回调不直接调用 load │                              │ pendingReclaim&&>10页►unload
│ /unload，只做标记  │                              │ 扫过但已离开视口  ►丢弃
└────────────────────┘                              └─────────────────────┘
```

### 模块职责划分

- **`scroll-sync.js`**
  - `createSettleGate(left,right)`：导出 `isScrollSettled()`、`onSettle(cb)`、并移除旧回调。稳定阈值常量 `SETTLE_MS ≈ 150`。
  - `setupScrollSync`：双向按比例同步。源栏 scroll → `f = scrollTop / (scrollHeight-clientHeight)`（除零退化为 0）→ rAF 内置 `syncing=true` 设目标栏 `scrollTop = f * (target.scrollHeight-clientHeight)`，再清 `syncing`；目标栏触发自身的 scroll 因 `syncing` 为真而不再反向同步（回环守卫）。
  - `setupPageDetection`：改为 `onSettle` 触发计算"占视口>50% 的页"一次，写入 page-indicator；拖动途中不再每帧计算，杜绝抖动。

- **`lazy-loader.js`**
  - `setupIntersectionObserver({ settle, load, unload })`：`rootMargin` 改为约 2 页高度（如 `200%` 或按页高换算）。回调职责仅：`isIntersecting` → `pendingLoad.add(page)`；`!isIntersecting` → `pendingReclaim.add(page)`。**不直接调用 load/unload**。
  - `settle.onSettle(scan)`:每次 settle 触发 `scan()`：
    - 计算当前视口页范围 `[firstVisible, lastVisible]`（由容器 scrollTop/clientHeight 与占位高度换算，或用 `getBoundingClientRect` 实时判视口相交）。
    - `pendingLoad`：在 `[firstVisible-BUF, lastVisible+BUF]` → 调 `load`；范围外页 **丢弃**（删除集合项）。
    - `pendingReclaim`：距视口 `> 10` 页 → 调 `unload`；否则移出回收集（暂留）。

- **`app.js`**（`loadPageImage` / `unloadPageImage`）
  - `loadPageImage(container)`：守卫读 `container.dataset.loaded`；`'true'` 直接返回。建 `<img>`，设 `src`；`img.onload` 内才 `placeholder.replaceWith(img)` 并置 `container.dataset.loaded='true'`（onload 前不替换占位，无高度跳变、无重复请求）。`onerror` 置 `dataset.loaded='error'`。
  - `unloadPageImage(container)`：仅当 `dataset.loaded==='true'` 才卸载；建占位（沿用 `dom.js calculatePlaceholderHeight`），`img.replaceWith(placeholder)`，置 `dataset.loaded='false'`。
  - 打开 PDF 后初始化 settle 闸门并把 `settle` 句柄传入 `setupIntersectionObserver`。

- **`style.css`**
  - `.page-container img { width:100%; }`（取代 `max-width:100%`）。宽恒等容器宽 + `height:auto` 维持页比例 = 占位 `padding-bottom:%` 同比 → 加载前后 page-container 高度不变。

- **`dom.js`**
  - `calculatePlaceholderHeight` 保持基于页宽高比的 `padding-bottom:%`；核对与 `width:100%/height:auto` 在同页宽下高度一致（公式一致即成立，无需改）。

## 关键决策与备选

1. **settle 闸门检测**：用 ~150ms 无 scroll 事件。备选：滚动速度低于阈值——否决，需额外速度滤波、调参更重。
2. **双向比例同步**：`f = scrollTop/(scrollHeight-clientHeight)` + rAF + `syncing` 守卫。备选：单向绝对 scrollTop（现状错位）、锁定单栏——否决，体验差。
3. **IO 降级为标记（方案 B）**：候选集 + settle 扫描，单时间线。备选：IO 回调内 gate on settle（方案 A，双线协调、振荡面更大）——否决。
4. **图片尺寸=占位**：`width:100%` 使加载零偏移。备选：固定容器 height——否决，溢出/裁剪风险。
5. **延迟卸载**：settle 后距视口 >10 页才 unload，与 load 共享闸门。备选：离开即卸载（现状抖动根因）、永不卸载（内存失控）——否决。

## 测试策略

纯前端无单测基建，手动回归为主，四类场景对应 tasks 5.x：

1. **长距跳转**（核心）：1000 页，第 1→500 拖条放开 → 网络面板 `/api/page/*` 请求 ≤ ~5、第 500 页附近正确显示。
2. **双向同步**：左/右各滚到 50% → 另一栏同比例同页、始终对齐；DOM 核对两栏 page-container 起始一致。
3. **边界来回**：翻页边界小幅来回 → 无 `load→unload→load`、page-indicator 不抖、日志无重复 `?t=` 请求。
4. **缓滚逐页**：每页滑入即加载、无重复请求、图片加载前后 page-container 高度不变（`console` 比对 `offsetHeight`）。

不变量核验手段：网络面板数请求；`console` 查 `dataset.loaded` 去重；DOM 比对高度。

## 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 拖动期间空白 | 落点稳定后缓冲区 1~3 张请求加载快；可接受 |
| 大文档 scrollTop 取整误差 | 比例同步误差像素级，远小于一页高，rAF 节流后不影响同页 |
| settle 阈值误触发 | ~150ms 可实测微调为常量 |
| pending 集 无限增长 | settle 扫描中范围外项立即从 `pendingLoad` 丢弃；`pendingReclaim` 卸载/暂留后移出 |
| 两栏图片加载时序差致短暂 sync 抖动 | 图片加载不改变高度 → 比例不变 → 无抖动 |

## 实现参数（待实测微调）

- `SETTLE_MS = 150`
- 缓冲页数 `BUF = 2`
- 卸载距离阈值 `RECLAIM_DISTANCE = 10`
- IO `rootMargin` ≈ 2 页高度

## 范围边界

仅前端 `static/style.css`、`static/modules/{dom,scroll-sync,lazy-loader}.js`、`static/app.js`。后端、翻译 SSE、stages/translator/sse-client 不动。无新增依赖。