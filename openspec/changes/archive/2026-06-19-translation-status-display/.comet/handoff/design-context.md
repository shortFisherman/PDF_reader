# Comet Design Handoff

- Change: translation-status-display
- Phase: design
- Mode: compact
- Context hash: 3B84E6AEFEABE6F7954390927DC8ECF161E9D60E89E0EF4BB6B9D571786A7924

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/translation-status-display/design.md

- Source: openspec/changes/translation-status-display/design.md
- Lines: 1-94
- SHA256: 7384F60E595046E37A6B3D3ED591B522BC66AC35148736647FA503C9158A5E52

```md
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
```

## openspec/changes/translation-status-display/proposal.md

- Source: openspec/changes/translation-status-display/proposal.md
- Lines: 1-21
- SHA256: C7565169246DCBA5B014C36CD90EAE0119FA71014C3F8922C776D7DBAEED62DE

```md
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
```

## openspec/changes/translation-status-display/specs/page-translation/spec.md

- Source: openspec/changes/translation-status-display/specs/page-translation/spec.md
- Lines: 1-49
- SHA256: 6B5EBDE9A97D64ACA0BAB304B1752AAB76F7C2A8AB4D6BB174C1C95FCEA4DB45

```md
## MODIFIED Requirements

### Requirement: Translation uses pdf2zh-next with DeepSeek

The system SHALL use pdf2zh-next's `do_translate_async_stream` API with DeepSeek engine settings for all translation operations.

#### Scenario: Correct engine configuration

- **WHEN** a translation is requested
- **THEN** the system SHALL configure pdf2zh-next with `DeepSeekSettings` using the API key and model from config.toml

#### Scenario: Progress streaming with stage information

- **WHEN** a translation is in progress
- **THEN** the system SHALL relay progress events from the translation engine to the frontend via Server-Sent Events (SSE), and each progress event SHALL include the current stage name (e.g., "layout_analysis", "translating") and the overall progress percentage

#### Scenario: Paragraph-level progress in streaming

- **WHEN** the translation engine produces a progress_update event with stage_current and stage_total fields
- **THEN** the SSE event SHALL include the current paragraph index and total paragraph count so the frontend can display progress like "正在翻译 第 3/8 段"

## ADDED Requirements

### Requirement: User-facing stage status display

The system SHALL display user-readable Chinese text describing the current translation stage in the progress bar area during translation.

#### Scenario: Layout analysis stage display

- **WHEN** the translation enters the layout_analysis stage
- **THEN** the progress bar area SHALL display "正在分析版面..." in Chinese

#### Scenario: Translating stage display

- **WHEN** the translation enters the translating stage
- **THEN** the progress bar area SHALL display "正在翻译..." followed by paragraph-level progress if available (e.g., "正在翻译... 第 3/8 段")

#### Scenario: Generating PDF stage display

- **WHEN** the translation completes text translation and begins generating the output PDF
- **THEN** the progress bar area SHALL display "正在生成译文..." in Chinese

#### Scenario: Translation complete display

- **WHEN** the translation finishes successfully
- **THEN** the progress bar area SHALL display "翻译完成" briefly before returning to its idle state

#### Scenario: Translation error display

- **WHEN** a translation error occurs
- **THEN** the progress bar area SHALL display the error information in red text
```
