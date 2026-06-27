## Why

用户在关闭 PDF 阅读器后再次打开同一文档时，总是从头从第 1 页开始，需要手动翻回到上次阅读的位置。对外文翻译阅读场景，这一步常意味着连续翻 8、20 甚至上百页，体验割裂。本次变更让阅读器记住每个文档上次停下的页码，并在重新打开时自动跳回。

## What Changes

- 新增"阅读进度持久化"能力：在服务端按 PDF 内容哈希（已有的 `pdf_hash`）把上次阅读页码写入 `cache_dir/<hash>/` 下，使其跨浏览器、跨重装仍然有效。
- `state.py` 在 `open_pdf` 时返回上次保存的页码（如有），并对越界值做钳制降级。
- `routes.py` 新增保存进度的 HTTP 接口，供前端在页面隐藏/卸载时上报当前页码。
- 前端 `static/app.js` 打开文档后读取并自动滚动到上次页码；在页面隐藏/卸载时通过 `navigator.sendBeacon` 上报当前页码。
- 恢复粒度仅页码（不含缩放、不含页内滚动偏移）；恢复方式为自动直接跳转（无询问弹窗）。

## Capabilities

### New Capabilities
- `reading-position-resume`: 记录并恢复单本 PDF 上次阅读页码的能力。按 PDF 内容哈希持久化在服务端 cache 目录，打开文档时自动跳回，关闭/卸载时上报保存。

### Modified Capabilities
<!-- 本次为纯新增能力，不修改任何现有 spec 的 requirement -->
(none)

## Impact

- **后端代码**：`state.py`（新增进度文件读写、`open_pdf` 返回 `saved_page`）、`routes.py`（新增 `POST /api/reading-progress` 与 `GET /api/reading-progress` 路由）。
- **前端代码**：`static/app.js`（打开后定位、页面隐藏/卸载时上报），可能新增少量 helper。
- **存储**：每本 PDF 的 `cache_dir/<hash>/` 下新增进度文件（极小 JSON）。
- **依赖**：无新增第三方依赖；前端使用浏览器内置 `navigator.sendBeacon` / `visibilitychange`。
- **不影响**：翻译流程、雪花缓存、双栏渲染、缩放、术语表等现有能力的对外行为。