## Context

当前翻译进度仅通过 SSE 推送一个百分比数字（`{"type": "progress", "progress": 45}`），前端只更新进度条宽度。BabelDOC / pdf2zh-next 管道实际产生的事件携带丰富的阶段信息（`stage`, `stage_current`, `stage_total`），但这些信息在 `routes.py:147-157` 的 SSE 格式化中被丢弃。本设计目标是在不改变翻译管道的前提下，将这些信息透传到前端并以人类可读的方式展示。

## Goals / Non-Goals

**Goals:**
- SSE 事件携带阶段名称、段落级进度
- 前端进度条区域展示中文阶段状态文字 + 百分比 + 段落级详情
- 对现有 SSE 协议向后兼容（仅追加字段）

**Non-Goals:**
- 不修改翻译管道、pdf2zh-next 配置或 BabelDOC 行为
- 不改变 toolbar 整体布局（进度条位置、尺寸不变）
- 不增加后端持久化状态（不引入新的日志文件或数据库）
- 不处理多页批翻译进度（当前架构为单页按需翻译）

## Decisions

### 1. SSE 事件增强方案

**选择**: 在现有 `progress` 事件中追加字段，而非新增事件类型。

```python
# 改动前
{"type": "progress", "progress": 45}

# 改动后
{"type": "progress", "progress": 45, "stage": "translating",
 "stage_current": 3, "stage_total": 8}
```

**理由**: 前端已有 `type === 'progress'` 的处理分支，追加字段不会破坏现有逻辑。新增事件类型会增加不必要的分支。

**替代方案考虑**: 
- 新事件类型 `status_update` — 增加前后端复杂度，无实际收益
- 独立 `/api/status` 轮询端点 — 过度设计，SSE 本身已是推送机制

### 2. 阶段名中文映射表

**选择**: 在 `routes.py` 中维护一个硬编码映射字典。

```python
STAGE_LABELS = {
    "layout_analysis":   "正在分析版面…",
    "translating":       "正在翻译…",
    "generating_pdf":    "正在生成译文…",
    "generating_pdf_bilingual": "正在生成译文...",
    "finish":            "翻译完成",
}
```

**理由**: 映射关系稳定，BabelDOC 阶段名是代码常量不会频繁变化。硬编码零依赖，比 i18n 库轻量。

**回退策略**: 未知阶段名直接显示原始英文名作为 fallback。

### 3. 前端展示方案

**选择**: 在 `<div id="progress-bar">` 内增加一个 `<span id="progress-status-text">` 子元素，显示当前阶段文字。进度条自身按现有逻辑显示百分比宽度。

```
┌─────────────────────────────────────────────────────┐
│  [Page 3]  [+ Prompt]  [▓▓▓▓▓▓░░░░░░░░] 正在翻译... 第 3/8 段  │
│                          progress-bar   status-text              │
└─────────────────────────────────────────────────────┘
```

**理由**: 在现有 toolbar flex 布局中插入一个文本元素，不改变布局结构，不增加浮层/弹窗。文字紧邻进度条，视觉关联清晰。

**CSS 适配**: `progress-bar` 使用 `display: flex; align-items: center; gap: 8px` 包裹进度线和文字。

### 4. 前端状态生命周期

```
空闲 ──→ translating ──→ complete/error ──→ 空闲
```

- **翻译中**: 进度条 active，status-text 显示当前阶段
- **翻译完成**: 进度条置 100%，status-text 显示"翻译完成"，2 秒后清除
- **翻译出错**: 进度条隐藏，status-text 显示红色错误信息，3 秒后清除

## Risks / Trade-offs

- **[风险] BabelDOC 阶段名可能在未来版本变化** → 使用 fallback（显示原始名），影响仅限于未映射阶段以英文显示
- **[风险] 段落级进度可能导致文字频繁闪烁** → `stage_update` 事件频率由 BabelDOC 的 `report_interval` 控制（默认 0.1s），文字更新使用 `requestAnimationFrame` 或 `textContent` 直接赋值，不会产生重排
- **[权衡] 单页翻译的进度条对用户等待时间的帮助有限** → 单页翻译通常 5-15 秒，阶段展示已能大幅缓解焦虑；如需更精细的进度可后续增加 token 级进度
