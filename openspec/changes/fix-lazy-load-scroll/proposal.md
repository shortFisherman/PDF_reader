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
- **API**：后端 `/api/page/<side>/<page>` 接口不变，仅请求频次与时机改变。