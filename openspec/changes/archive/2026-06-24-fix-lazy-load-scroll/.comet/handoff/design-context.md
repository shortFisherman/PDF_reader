# Comet Design Handoff

- Change: fix-lazy-load-scroll
- Phase: design
- Mode: compact
- Context hash: b9d637040898e267be8fa522583207370b7889e01c915ff68b0df8cde1bedb2e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/fix-lazy-load-scroll/proposal.md

- Source: openspec/changes/fix-lazy-load-scroll/proposal.md
- Lines: 1-26
- SHA256: e98677012cfe27a244739d631470b3a7af2e6e231066de7728aae5df8733fc85

```md
## Why

前端分页/滚动交互存在三个缺陷，严重影响 1000 页大文档的可读性：(1) 拖动滚动条长距离跳转时，被扫过的每一页都会触发一次 `IntersectionObserver` 回调并向后端发请求（实测 1→500 页约 500 次请求），耗时长且占满浏览器连接上限；(2) 左右两栏只有左→右单向绝对 scrollTop 同步，右栏独立滚动时左栏不跟随，导致左右严重错位，叠加图片加载后高度跳变会出现「一边卡成两页、看不全」的现象；(3) 在翻页边界附近 `load→unload→load` 自激振荡，重复请求同一页（日志末尾连续 7+ 次请求 `left/505`），造成页面抖动。这些问题同源于当前懒加载与滚动同步的脆弱设计，需要一次架构层面的修复。

## What Changes

- **滚动稳定后再加载落点**：拖动滚动条期间不立即发出页面请求，待滚动停止（~150ms 无 scroll 事件）后才加载视口内及小缓冲区的页面。扫过的中间页面一律丢弃，不产生请求。
- **双向按比例滚动同步**：左右两栏任一侧滚动均按 `scrollTop / (scrollHeight - clientHeight)` 百分比同步另一侧，`requestAnimationFrame` 节流，避免绝对 scrollTop 在两侧总高不一致时错位。
- **消除页面布局偏移**：使已加载的 `<img>` 尺寸与占位 (`page-placeholder`) 严格一致（宽度填满容器、按页比例确定高度），图片加载完成后不再改变页面高度，杜绝「一边塞两页、看不全」。
- **消除翻页边界抖动**：引入对称去抖的加载/卸载策略与容器级加载状态守卫；图片在 `onload` 前不替换占位，离开缓冲区的卸载延迟到确认稳定后执行，杜绝 `load→unload→load` 振荡与重复请求。
- 仅前端改动，不修改后端接口与渲染管线。

## Capabilities

### New Capabilities
<!-- 无新增能力 -->

### Modified Capabilities
- `lazy-loading`: 当前「进入缓冲带即加载、200ms 内请求」在滚动条快速扫过时会淹没后端；卸载策略（>10 页离开即 MAY 卸载）触发边界振荡。改为滚动稳定后才放行加载、容器级去重守卫、延迟卸载以消除振荡与重复请求。
- `dual-column-reading`: 当前滚动同步是「仅左→右的单向绝对 scrollTop 同步，右栏独立滚动不影响左栏」，直接导致左右错位。改为「双向按比例同步」；并补充图片加载完成后页面高度不变的约束，消除单边塞两页/看不全。

## Impact

- **受影响代码**：`static/style.css`、`static/modules/dom.js`、`static/modules/lazy-loader.js`、`static/modules/scroll-sync.js`、`static/app.js`（`loadPageImage` / `unloadPageImage`）。
- **不受影响**：后端 `routes.py`、`state.py`、`pdf_renderer.py`、`app.py`，以及前端的 `translator.js`、`stages.js`、`sse-client.js`、翻译 SSE 管线。
- **依赖与系统**：纯前端，使用浏览器原生 `IntersectionObserver` 与 `requestAnimationFrame`，无新增依赖。
- **API**：后端 `/api/page/<side>/<page>` 接口不变，仅请求频次与时机改变。```

## openspec/changes/fix-lazy-load-scroll/design.md

- Source: openspec/changes/fix-lazy-load-scroll/design.md
- Lines: 1-58
- SHA256: eecffc81eeb4547cfdf198957faff7ccbe8f7b80703e21dd59c8eb2130cb5ac7

```md
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
- 补充缓冲页数：原 spec 为 5 屏/5 页；本次倾向于缩小到约 2 页以减少落点请求量，在实现阶段确认。（在 specs 中以可配置缓冲参数形式描述）```

## openspec/changes/fix-lazy-load-scroll/tasks.md

- Source: openspec/changes/fix-lazy-load-scroll/tasks.md
- Lines: 1-29
- SHA256: dd944c959cd79ab2ee0e4c403511f85c08f6127a8883dcd230f67d56b0e8ac5b

```md
## 1. 滚动稳定闸门基础设施

- [ ] 1.1 在 `scroll-sync.js` 新增共享的「滚动稳定」闸门：监听左栏（及右栏）`scroll` 事件，置 `unstable` 并重置 ~150ms 定时器，到期置 `stable`，导出 `isScrollSettled()`/`onSettle(cb)` 供懒加载模块消费
- [ ] 1.2 在 `app.js` 打开 PDF 后初始化该闸门，并把稳定状态句柄传入 `setupIntersectionObserver`

## 2. 图片尺寸与占位对齐（消除布局偏移）

- [ ] 2.1 在 `style.css` 将 `.page-container img` 由 `max-width: 100%` 改为 `width: 100%`，使图片宽恒等于容器宽、高度由页比例决定，加载前后高度不变
- [ ] 2.2 核对 `dom.js` 的 `calculatePlaceholderHeight`（`padding-bottom:%`）与图片 `width:100%/height:auto` 在同一页宽下高度一致；若有差异修正占位比例计算

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
- [ ] 5.4 手动回归：逐页缓慢下滚，每页滑入即加载、无重复请求、图片加载后高度无跳变（无「一边塞两页、看不全」）```

## openspec/changes/fix-lazy-load-scroll/specs/dual-column-reading/spec.md

- Source: openspec/changes/fix-lazy-load-scroll/specs/dual-column-reading/spec.md
- Lines: 1-52
- SHA256: 9e0b1268bde69e9ceae58533d29ab0b105e7c73f6fc26ce3e95f7a3d3e68e897

```md
## MODIFIED Requirements

### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization SHALL be **bidirectional and proportional**: scrolling either column SHALL synchronize the other column to the same fractional scroll position, computed as `scrollTop / (scrollHeight - clientHeight)`. Synchronization SHALL be throttled with `requestAnimationFrame` and guarded by a `syncing` flag to prevent feedback loops. The `scroll-sync` frontend module SHALL own this logic.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Left-driven proportional sync

- **WHEN** the user scrolls the left column to a fractional position `f` (0 ≤ f ≤ 1)
- **THEN** the right column SHALL synchronize to the same fractional position `f` within one animation frame, regardless of small differences in total scrollable height

#### Scenario: Right-driven proportional sync

- **WHEN** the user scrolls the right column independently to a fractional position `f`
- **THEN** the left column SHALL synchronize to the same fractional position `f` within one animation frame (replacing the prior left-only behavior)

#### Scenario: No sync feedback loop

- **WHEN** synchronization writes the target column's `scrollTop`
- **THEN** the resulting scroll event SHALL NOT trigger a reverse synchronization back to the source column

### Requirement: Page-level image display

The system SHALL display each page as an individual image stacked vertically, creating a continuous scrollable reading experience. A loaded page image SHALL fill the column width (`width: 100%`) so its rendered height equals the placeholder's reserved height; loading an image SHALL NOT change the page-container's height, preventing misalignment where one column inadvertently displays two cropped pages.

#### Scenario: Continuous scroll through pages

- **WHEN** the user scrolls through the document
- **THEN** page images SHALL appear in sequential order without gaps, mimicking a continuous document view

#### Scenario: Image load preserves alignment

- **WHEN** a page image finishes loading in one column while the corresponding page in the other column is still a placeholder (or vice versa)
- **THEN** both columns SHALL remain aligned to the same page, with no height jump and no extra page pushed partially into the viewport

### Requirement: Floating toolbar

The system SHALL provide a floating toolbar that remains visible during scrolling.

#### Scenario: Toolbar visibility

- **WHEN** the user scrolls through the document
- **THEN** a floating toolbar SHALL remain fixed at the bottom of the viewport, displaying the current page number and a translation trigger button

#### Scenario: Page indicator

- **WHEN** the user scrolls such that page N occupies more than 50% of the viewport
- **THEN** the toolbar SHALL display "Page N" as the current page, computed by the `scroll-sync` module's page detection, and the indicator SHALL be stable (not jittering between adjacent pages) when scrolling momentarily settles at a page boundary```

## openspec/changes/fix-lazy-load-scroll/specs/lazy-loading/spec.md

- Source: openspec/changes/fix-lazy-load-scroll/specs/lazy-loading/spec.md
- Lines: 1-75
- SHA256: 2444415875503e2e75f23e1635c7259cdf89709ad6b2f6530f5d73121fefdfeb

```md
## MODIFIED Requirements

### Requirement: Viewport-based image loading

The system SHALL load page images only when the page is near the browser viewport AND the document is not actively being scrolled by a drag/fast gesture. Loading SHALL be gated by a "scroll-settled" state: a scroll event marks the document unstable and resets a settle timer (~150ms); images are loaded only after the timer fires (document stable). While unstable, the lazy-loader SHALL record pages needing load but SHALL NOT issue requests for pages merely swept past. The IntersectionObserver logic SHALL reside in the `lazy-loader` frontend module.

#### Scenario: Initial page load

- **WHEN** the dual-column view first renders
- **THEN** only page images within the viewport plus a small buffer (approximately 2 pages above and below) SHALL be loaded

#### Scenario: Scroll reveals new pages while reading

- **WHEN** the user scrolls slowly such that a previously unloaded page enters the buffer zone and scrolling settles (no scroll event for ~150ms)
- **THEN** the system SHALL load that page's image

#### Scenario: Long-distance scrollbar drag discards swept pages

- **WHEN** the user drags the scrollbar from page 1 toward page 500, sweeping many pages through the buffer
- **THEN** the system SHALL NOT issue page requests for the swept intermediate pages, and after scrolling settles SHALL load only the pages in the landing viewport plus buffer (≤ ~5 requests)

### Requirement: Symmetric debounced unload

The system SHALL NOT unload a page image the instant it leaves the buffer. Unloading SHALL be deferred until the scroll-settled state is reached AND the page remains outside the viewport and buffer. The load/unload decision SHALL share a single scroll-settled gate so that boundary jitter cannot trigger a load→unload→load cycle.

#### Scenario: Page temporarily leaves buffer during a slow scroll

- **WHEN** a loaded page briefly crosses outside the buffer during continued scrolling and re-enters within one settle interval
- **THEN** the system SHALL NOT unload and reload it (no oscillation, no duplicate request)

#### Scenario: Scroll-away unloading after settle

- **WHEN** a loaded page remains more than 10 pages away from the viewport after the document settles
- **THEN** the system MAY unload its image to free memory, replacing it with a placeholder whose load state is reset

### Requirement: Container-level load state guards

The system SHALL track the loaded state on the `page-container` element (e.g. `dataset.loaded`), not on the placeholder. The `<img>` SHALL not replace the placeholder until `onload` fires, so an in-flight image never causes a height change or duplicate load. A page with `dataset.loaded === 'true'` SHALL NOT be re-requested.

#### Scenario: Duplicate load suppression

- **WHEN** an already-loaded page re-enters the buffer
- **THEN** the system SHALL NOT issue another request for that page

#### Scenario: Image load does not change layout

- **WHEN** a page image finishes loading
- **THEN** the placeholder SHALL be replaced by the `<img>` without changing the page-container's rendered height

### Requirement: IntersectionObserver implementation

The system SHALL use the browser's IntersectionObserver API to detect which page elements are near the viewport, implemented in the `lazy-loader` module. The observer's `rootMargin` SHALL define a small buffer (approximately 2 page-heights), smaller than the prior 5-page buffer to reduce landing-page request volume.

#### Scenario: Observer setup

- **WHEN** the dual-column view initializes
- **THEN** the `lazy-loader` module SHALL create an IntersectionObserver with a small buffer rootMargin (approximately 2 page-heights) and SHALL only act on intersection changes when the document is settled

#### Scenario: Placeholder dimensions

- **WHEN** a page image has not yet been loaded
- **THEN** the system SHALL display a placeholder element with the correct aspect ratio (based on the page dimensions) to maintain scroll position accuracy

### Requirement: Large PDF support

The system SHALL support PDF documents with up to 1000 pages without degrading browser performance.

#### Scenario: 1000-page document scrollbar jump

- **WHEN** a 1000-page PDF is opened and the user drags the scrollbar from the first to the 500th page
- **THEN** the browser SHALL maintain responsiveness and the number of `/api/page/*` requests during the gesture SHALL be bounded (≤ ~5) rather than proportional to pages swept

#### Scenario: Memory management

- **WHEN** total loaded images exceed 50 pages
- **THEN** the system SHALL unload images furthest from the viewport (after settle) to stay within memory limits```

