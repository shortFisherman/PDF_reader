## Why

当前翻译过程中，用户只能看到一个百分比进度条，完全不知道翻译引擎在后台做什么——是正在分析版面、正在逐段翻译、还是正在生成PDF。这种"黑盒"体验让用户在等待时感到焦虑和不透明。我们需要让翻译过程对普通用户可见、可理解。

## What Changes

- **SSE 事件增强**：后端在推送翻译进度时，附加阶段名称（中文）和段落级进度信息，而不只是百分比数字
- **进度条区域改造**：前端进度条从纯百分比显示升级为带文字描述的状态指示器，显示当前阶段、整体进度和段落级详情
- **阶段信息透传**：将 pdf2zh-next / BabelDOC 翻译管道产生的事件阶段（如 `layout_analysis`、`translating`、`generating_pdf`）映射为中文用户可读文本并展示

## Capabilities

### New Capabilities

<!-- 本次不需要新增 capability，仅修改现有 page-translation 的需求描述 -->

### Modified Capabilities

- `page-translation`: 修改 SSE 进度事件的需求——除百分比外还需携带阶段名称和段落级进度；前端需展示阶段状态文字而非仅百分比

## Impact

- **后端**：`routes.py` translate_page 函数中的 SSE 事件格式化逻辑
- **前端**：`static/app.js` SSE 事件处理 + `templates/index.html` 进度条区域 HTML + `static/style.css` 新增样式
- **无破坏性变更**：现有 SSE 事件格式向后兼容，仅追加字段
- **无新增依赖**
