## Why

翻译完成后，右侧 PDF 会闪烁但被翻译的页面没有被译文替换，仍然显示英文。根因是 `onFinish` 回调使用模块级可变变量 `currentPage` 来定位需要刷新的页面容器，而用户在翻译等待期间（约 30–40 秒）滚动到其他页面后 `currentPage` 已被 `onPageChange` 更新为当前可见页，导致刷新了错误的页面而非实际翻译的页面。这违反了 `page-translation` spec 中 "Translation completion" 场景："the right-column image for **that page** SHALL refresh to show the translated content within 2 seconds"。

## What Changes

- 在 `onTranslateClick` 入口处捕获被翻译的页码（`targetPage`），在整个翻译生命周期中使用该固定值，而非读取可变的 `currentPage`。
- `onFinish` 回调使用 `targetPage` 定位右侧页面容器并刷新图片，确保被翻译的页面（而非当前可见页）获得译文。
- 处理极端场景：若翻译完成时目标页图片已被 lazy-loader 卸载（用户滚出超过 10 页），不强制加载远端图片，仅标记 `translated` 状态；用户滚回时 lazy-loader 会以新的时间戳请求，自动获取译文版本。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

（无 — 现有 `page-translation` spec 的 "Translation completion" 场景已正确描述期望行为，本次修复使实现回归符合既有 spec，不改变 spec 级别的需求。）

## Impact

- `static/app.js`：`onTranslateClick` 函数（1 个函数，约 10 行改动）。
- 无后端改动、无 API 变更、无依赖变更、无数据库变更。
- 不影响 lazy-loader、scroll-sync 等其他前端模块的既有行为。
