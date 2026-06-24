# Brainstorm Summary

- Change: fix-lazy-load-scroll
- Date: 2026-06-26

## Confirmed Technical Approach

采用**方案 B**：IntersectionObserver 降级为「候选集合标记器」，不再在回调中直接调用 load/unload；所有加载/卸载决策收敛到单一的「滚动稳定（scroll-settled, ~150ms 无 scroll 事件）」闸门之后统一扫描。

- **scroll-settled 闸门**（`scroll-sync.js` 拥有）：监听左右栏 `scroll`，置 unstable + 重置 ~150ms 定时器，到期置 settled，导出 `isScrollSettled()`/`onSettle(cb)`。
- **双向按比例同步**（`scroll-sync.js`）：任一栏滚动 → 源栏比例 `scrollTop/(scrollHeight-clientHeight)` → rAF 内设目标栏同比例 scrollTop，`syncing` 标志阻止回环。`scrollHeight===clientHeight` 退化为 0。
- **IO 候选标记**（`lazy-loader.js`）：`rootMargin` 缩为约 2 页高度；回调中进入缓冲→入候选集 `pendingLoad`，彻底离开→入 `pendingReclaim`，**不直接 load/unload**。
- **settle 后统一扫描**：settle 回调里扫 `pendingLoad`——在视口±缓冲者 `load`、扫过但已离开者丢弃；扫 `pendingReclaim`——距视口 >阈值（10 页）者 `unload`。加载/卸载共享同一 settle 闸门 → 边界无竞争 → 振荡根除。
- **容器级加载守卫**（`app.js` loadPageImage/unloadPageImage）：状态守卫迁移到 `page-container.dataset.loaded`（不随占位删除失效）；`<img>` 在 `onload` 前不替换占位。
- **图片尺寸对齐**（`style.css` / `dom.js`）：`.page-container img { width:100% }` 取代 `max-width:100%`，图片宽恒等于容器宽、高度由页比例决定，与 `padding-bottom:%` 占位同比；加载前后高度不变。
- **页码检测**（`scroll-sync.js` `setupPageDetection`）：改为 settle 后计算一次，避免拖动途中 page-indicator 抖动；保留"占视口>50% 的页"逻辑。

## Key Trade-offs and Risks

- 拖动期间页面为占位，放开后短暂空白才出图 —— 可接受（远优于 500 次请求与卡顿）。
- 极长 scrollHeight 下 scrollTop 取整使两端比例差像素级 —— 远小于一页高度，rAF 节流后不影响显示同一页。
- 稳定阈值 ~150ms 偏短可能误触发 —— 实现后实测微调。
- 延迟卸载使内存峰值略升（仅一个 settle 周期内常驻）—— 远低于 50 页上限，可忽略。
- IO 降级为标记需自管 `pendingLoad`/`pendingReclaim` 集合的清理 —— 逻辑集中在 lazy-loader 内部，复杂度可控。

## Testing Strategy

纯前端无单测基建，以**手动回归**为主，覆盖四类场景（见 tasks 5.x）：

1. 长距离跳转：1000 页第 1→500 拖条放开 → `/api/page/*` 请求 ≤ ~5、第 500 页附近正确显示。
2. 双向同步：左右栏各滚到 50% → 另一栏同比例同页、始终对齐。
3. 翻页边界来回小幅滚 → 无 load→unload→load 振荡、page-indicator 不抖、日志无重复 `?t=` 请求。
4. 逐页缓滚 → 每页滑入即加载、无重复请求、图片加载后无高度跳变。

不变量核验：浏览器网络面板数 `/api/page/*`；`console` 检查 `dataset.loaded` 去重；DOM 检查图片加载前后 page-container 高度。

## Spec Patches

None — delta specs 的验收场景已覆盖四类边界；稳定阈值 ~150ms 与缓冲 ≈2 页作为实现参数已在 specs 中描述，无需新增/重写需求。