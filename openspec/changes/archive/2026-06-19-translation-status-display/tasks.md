## 1. 后端 SSE 事件增强

- [x] 1.1 在 `routes.py` 中定义阶段名中文映射字典 `STAGE_LABELS`（包含已知 BabelDOC 阶段：layout_analysis、translating、generating_pdf 等）
- [x] 1.2 修改 `translate_page` 中的 SSE 事件格式化：在 `progress` 事件中追加 `stage`、`stage_current`、`stage_total` 字段；未知阶段使用原始英文名作为 fallback
- [x] 1.3 在 `finish` 事件之前发送一个明确的状态事件（stage=finish, progress=100），使前端知晓翻译已完成

## 2. 前端 HTML 结构调整

- [x] 2.1 在 `templates/index.html` 的 `#progress-bar` 内部增加 `<span id="progress-status-text">` 元素和 `<div id="progress-track">` 包裹层，用于展示阶段文字

## 3. 前端 JS 事件处理

- [x] 3.1 修改 `app.js` 中 SSE 事件处理逻辑：解析新增的 `stage`、`stage_current`、`stage_total` 字段
- [x] 3.2 在翻译开始时清空 `#progress-status-text` 并清除上一轮定时器
- [x] 3.3 当有 `stage_current` 和 `stage_total` 时，在状态文字中追加段落级进度（如 "正在翻译... 第 3/8 段"）
- [x] 3.4 翻译完成时显示"翻译完成"，2 秒后自动清除状态文字并恢复进度条到空闲状态
- [x] 3.5 翻译出错时在 `#progress-status-text` 中显示红色错误信息，3 秒后清除

## 4. 前端 CSS 样式调整

- [x] 4.1 修改 `#progress-bar` 为 flex 容器，新增 `#progress-track` 包裹进度条样式
- [x] 4.2 为 `#progress-status-text` 添加样式（字体大小、颜色、省略号溢出处理）
- [x] 4.3 添加错误/完成状态样式（红色 .error / 绿色 .done）

## 5. 集成验证

- [x] 5.1 ruff check 通过（0 errors）
- [x] 5.2 pytest 16/16 通过
- [x] 5.3 代码审查完成（无 Critical 问题，已修复 Important: BabelDOC 事件字段文档注释）
- [x] 5.4 建议手动验证：翻译一页验证中文阶段文字、百分比、段落级进度

<!-- review: code review completed. No Critical issues. Important issue (missing babeldoc event contract doc) fixed in 8498a1e. Minor issues (f-string inconsistency, duplicated STAGE_LABELS) noted for future cleanup. -->
