## 1. 滚动稳定闸门基础设施

- [x] 1.1 在 `scroll-sync.js` 新增共享的「滚动稳定」闸门：监听左栏（及右栏）`scroll` 事件，置 `unstable` 并重置 ~150ms 定时器，到期置 `stable`，导出 `isScrollSettled()`/`onSettle(cb)` 供懒加载模块消费
- [x] 1.2 在 `app.js` 打开 PDF 后初始化该闸门，并把稳定状态句柄传入 `setupIntersectionObserver`

## 2. 图片尺寸与占位对齐（消除布局偏移）

- [x] 2.1 在 `style.css` 将 `.page-container img` 由 `max-width: 100%` 改为 `width: 100%`，使图片宽恒等于容器宽、高度由页比例决定，加载前后高度不变
- [x] 2.2 核对 `dom.js` 的 `calculatePlaceholderHeight`（`padding-bottom:%`）与图片 `width:100%/height:auto` 在同一页宽下高度一致；若有差异修正占位比例计算

## 3. 双向按比例滚动同步

- [ ] 3.1 重写 `scroll-sync.js` 的 `setupScrollSync`：左右任一栏 `scroll` → 计算源栏比例 `scrollTop/(scrollHeight-clientHeight)` → `requestAnimationFrame` 内设目标栏同比例 `scrollTop`，并以 `syncing` 标志阻止回环
- [ ] 3.2 处理 `scrollHeight === clientHeight`（无滚动空间）的退化情况，避免除零（比例视为 0）
- [ ] 3.3 `setupPageDetection` 的页码检测改造为在「稳定」后计算一次，避免拖动途中频繁刷新 page-indicator 抖动；保留「占视口>50% 的页」为当前页逻辑

## 4. 懒加载重构（落点加载 + 去抖卸载 + 容器级守卫）

- [ ] 4.1 重写 `lazy-loader.js`：`IntersectionObserver` 的 `rootMargin` 缩小为约 2 页高度；回调中仅在 `isScrollSettled()` 为真时放行 `load`，否则记录待加载集合不发起请求
- [ ] 4.2 实现「落点加载」：稳定后遍历待加载集合与当前视口，仅对视口内 + 缓冲的页面调用 `load`，扫过但已离开的待加载项被丢弃
- [ ] 4.3 实现延迟卸载：`unload` 改为「离开缓冲且文档稳定后」才执行，复用 1.x 的同一稳定闸门，杜绝边界 `load→unload→load` 振荡
- [ ] 4.4 在 `app.js` 的 `loadPageImage` 把加载状态守卫迁移到 `page-container`（`dataset.loaded`），不依赖会被删除的占位；`<img>` 在 `onload` 前不替换占位
- [ ] 4.5 在 `app.js` 的 `unloadPageImage` 复位 `page-container.dataset.loaded='false'`；确保已加载页不被重复请求

## 5. 验证

- [ ] 5.1 手动回归：1000 页 PDF，从第 1 页拖滚动条到第 500 页放开，确认 `/api/page/*` 请求 ≤ ~5 且第 500 页附近正确显示
- [ ] 5.2 手动回归：左右栏分别滚动到 50%，确认另一栏同步到同一比例、同一页；左右始终对齐
- [ ] 5.3 手动回归：在翻页边界来回小幅滚动，确认无 `load→unload→load` 振荡、`page-indicator` 不抖动、日志无重复 `?t=` 请求
- [ ] 5.4 手动回归：逐页缓慢下滚，每页滑入即加载、无重复请求、图片加载后高度无跳变（无「一边塞两页、看不全」）