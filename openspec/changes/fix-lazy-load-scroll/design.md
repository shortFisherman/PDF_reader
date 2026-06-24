## Context

当前前端分页阅读器由 `static/modules/lazy-loader.js`、`static/modules/scroll-sync.js`、`static/modules/dom.js`、`static/app.js` 协同实现：
- `lazy-loader.js` 用 `IntersectionObserver`（`rootMargin: 500%`，缓冲约 5 屏）在每个页面进入缓冲带时**即时**调用 `loadPageImage`，无去抖、无取消。
- `scroll-sync.js` 仅挂接 `left.addEventListener('scroll')`，把 `left.scrollTop` 复制给 `right.scrollTop`（单向、绝对值），右栏滚动不影响左栏。
- `dom.js` 为每页生成 `padding-bottom:%` 的高比例占位；`style.css` 中 `<img>` 用 `max-width:100%`，容器宽与图片自然像素宽不一致时，加载后高度变化，触发布局偏移。
- `app.js` 的 `loadPageImage` 把去重守卫写在会被删除的 `page-placeholder` 上（`placeholder.replaceWith(img)` 后守卫失效），离开即卸载、进入即重载，构成 `load→unload→load` 振荡。

约束：纯前端，浏览器原生 `IntersectionObserver` 与 `requestAnimationFrame`，无新增依赖；不改后端接口。

## Goals / Non-Goals

**Goals:**
- 长距离拖滚动条跳转时，仅请求落点附近一页 ± 小缓冲，扫过的中间页零请求。
- 左右两栏双向按比例滚动同步，总高不一致也能始终显示同一页。
- 图片加载完成后页面高度不变（消除「一边塞两页、看不全」）。
- 翻页边界附近不再出现 `load→unload→load` 振荡与重复请求。

**Non-Goals:**
- 不做服务端渲染缓存、不做稀疏中途预取。
- 不改变翻译 SSE 管线、工具栏等非滚动相关模块。
- 不改变占位比例的计算公式（基于页面宽高比）。

## Decisions

### 决策 1：滚动稳定闸门 + IntersectionObserver 协同
- 引入一个「滚动稳定」标记：发生 `scroll` 事件即置为不稳定并重置 ~150ms 定时器，定时器到期置为稳定。
- `IntersectionObserver` 回调只在「稳定」时放行 `load`；不稳定期间记录待加载页集合但**不发起请求**。
- **备选**：进入缓冲带即加载（现状）——被否决，正是 500 次请求的根因；稀疏预取——被否决，非目标且增加复杂度。
- **理由**：拖动放开到停止天然存在一段静止期，闸门把「扫过」与「落点」自然区分开。

### 决策 2：双向按比例同步
- 左右任一栏 `scroll` 事件触发：读源栏 `scrollTop/(scrollHeight-clientHeight)` 比例 → 设目标栏同比例 `scrollTop`。
- `requestAnimationFrame` 节流，并在同步写入目标栏时置 `syncing` 标志阻止回环（同步触发的 `scroll` 不再反向同步）。
- **备选**：保留单向绝对 scrollTop（现状）——被否决，右栏独立滚动即错位；锁定右栏不可滚——被否决，用户体验差且左右总高不一仍会错位。
- **理由**：比例同步对两侧 `scrollHeight` 微差天然鲁棒。

### 决策 3：图片尺寸与占位严格一致
- `style.css`：`.page-container img { width:100%; }`（取代 `max-width:100%`），使图片宽恒等于容器宽；`height:auto` 维持页比例，与占位 `padding-bottom:%` 同比。
- 结果：图片加载前后该页容器高度不变，布局零偏移。
- **理由**：占位已按页宽高比预留，只要图片填满容器宽，高度必然相同。

### 决策 4：对称去抖的加载/卸载 + 容器级加载状态
- 加载状态守卫迁移到 `page-container` 上（`dataset.loaded`），不随占位删除而失效；`loadPageImage` 中 `<img>` 在 `onload` 前不替换占位，避免高度抖动。
- 卸载改为「延迟卸载」：页面离开缓冲带不立即卸载，等「滚动稳定」后仍不在视口/缓冲区才卸载，并复用同一去抖闸门，杜绝边界振荡。
- **备选**：离开即卸载（现状）——被否决，是抖动根因；永不卸载——被否决，1000 页内存失控。
- **理由**：振荡源于「离开即卸载」与「进入即加载」的边界竞争；改用同一稳定闸门收敛两者即消除。

## Risks / Trade-offs

- **拖动期间的即时反馈** → 拖动中页面为占位，放开后才出现图片，视觉上有短暂空白。可接受：相比 500 次请求与长时间卡顿，落点稳定后快速呈现更优；缓冲区落点页通常 1~3 张请求，加载快。
- **比例同步在大文档的取整误差** → `scrollTop` 在极长 `scrollHeight` 下被浏览器量化，两端比例可能差 1 像素级。可接受：差距远小于一页高度，配合同步节流不影响显示同一页。
- **稳定阈值过短仍可能误触发** → 取 ~150ms 既能覆盖常见拖动放开后的惯性滚动，又不过分延迟；后续可按实测调整。
- **缓冲卸载延迟使内存峰值略升** → 仅延迟一个稳定周期（~150ms 内的页面常驻），远小于 50 页内存上限，可忽略。

## Open Questions

- 稳定阈值（~150ms）需在实现后实测微调。
- 补充缓冲页数：原 spec 为 5 屏/5 页；本次倾向于缩小到约 2 页以减少落点请求量，在实现阶段确认。（在 specs 中以可配置缓冲参数形式描述）