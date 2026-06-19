# Brainstorm Summary

- Change: translation-status-display
- Date: 2026-06-19

## Confirmed Technical Approach

SSE 事件在现有 `progress` 事件中追加 `stage`、`stage_current`、`stage_total` 三个字段，向后兼容。后端维护英文阶段名到中文的映射字典（硬编码），前端用同样映射 + English fallback 渲染。前端在 `#progress-bar` 内新增 `<span id="progress-status-text">`，进度条容器改为 flex 布局并排展示。

## Key Trade-offs and Risks

- **风险**: BabelDOC 阶段名未来可能变化 → fallback 显示原始英文名
- **风险**: 段落进度更新频率高可能闪烁 → BabelDOC 默认 report_interval=0.1s 可控
- **权衡**: 不放前端单独映射，而是前后端各维护一份映射表（后端用于未来可能的日志用途，前端用于显示 fallback）

## Testing Strategy

- 手动测试完整翻译流程，验证各阶段文字显示和生命周期（完成清除、错误显示）
- ruff check 零 lint 错误
- 向后兼容：旧版 SSE 事件（无 stage 字段）不影响前端正常运行

## Spec Patches

- page-translation delta spec 已写：修改 progress streaming requirement 追加 stage 字段，新增 user-facing stage status display requirement
