---
comet_change: translation-status-display
role: technical-design
canonical_spec: openspec
archived-with: openspec/changes/archive/2026-06-19-translation-status-display
status: archived
---

# 翻译状态显示增强

为 PDF 阅读器翻译进度条增加用户可读的中文阶段状态展示。

## 架构

```
BabelDOC 事件 (stage, progress, current/total)
  → routes.py SSE 格式化 (追加 stage/stage_current/stage_total)
    → 前端 app.js (解析事件, 更新 DOM)
      → #progress-status-text (中文文本显示)
```

纯前后端增强，不引入新模块、新依赖、新 API 端点。

## 数据流

```
progress_start / progress_update / progress_end (BabelDOC)
  │
  ▼
event_queue (Queue) → 轮询 (timeout=1.0s)
  │
  ▼
SSE yield: {"type": "progress", "progress": <n>,
             "stage": "<raw>", "stage_current": <n>, "stage_total": <n>}
  │
  ▼
前端 EventSource reader:
  - stage → stageLabel() → #progress-status-text.textContent
  - stage_current+stage_total → 追加 "第 X/Y 段"
  - progress → progressFill.style.width
```

## 阶段映射

| BabelDOC stage | 中文显示 |
|----------------|----------|
| `layout_analysis` | 正在分析版面… |
| `translating` | 正在翻译… |
| `generating_pdf` | 正在生成译文… |
| `generating_pdf_bilingual` | 正在生成译文… |
| `finish` | 翻译完成 |
| 未知 | 原始英文名 (fallback) |

## 前端生命周期

```
idle → [翻译开始] → active (显示阶段+段落进度)
                    → [finish] → done ("翻译完成", 2s → idle)
                    → [error] → error (红色文本, 3s → idle)
```

## 文件变更

| 文件 | 变更 |
|------|------|
| `routes.py` | 新增 STAGE_LABELS 映射, SSE 事件追加字段 |
| `templates/index.html` | progress-bar 内新增 status-text span |
| `static/app.js` | STAGE_LABELS 映射, SSE 处理增强, 生命周期管理 |
| `static/style.css` | progress-bar flex 布局, status-text 样式, error 状态 |

## 边缘情况

- **stage 字段缺失** (旧版 SSE): status-text 不更新，仅显示百分比进度条
- **未知 stage**: 显示原始英文 stage 名
- **stage_current/stage_total 缺失**: 不显示段落级进度
- **SSE 连接中断**: 进度条停留在最后状态，不影响 UI 响应
- **快速连续翻译**: 新翻译开始时清除上一轮状态
