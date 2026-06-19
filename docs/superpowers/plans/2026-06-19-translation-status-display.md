---
change: translation-status-display
design-doc: docs/superpowers/specs/2026-06-19-translation-status-display-design.md
base-ref: 10b74ae681243f8ea4146ca3585ce3d2d85a4705
archived-with: openspec/changes/archive/2026-06-19-translation-status-display
---

# 实施计划：翻译状态显示增强

## 任务依赖关系

```
1.1 (STAGE_LABELS) ──┐
                     ├──> 1.2 (SSE 格式化增强) ──> 1.3 (finish 状态事件)
                     │                                     │
2.1 (HTML span) ─────┤                                     │
                     │                                     │
4.1 (CSS flex) ──────┼──> 4.2 (status text 样式) ──> 4.3 (error 样式)
                     │                                     │
                     └─────────────────────────────────────┘
                                           │
                                    3.1~3.5 (JS 事件处理 + 生命周期)
                                           │
                                    5.1~5.4 (集成验证)
```

建议实施顺序：1 → 2 → 4 → 3 → 5

---

## 任务 1：后端 SSE 事件增强

### 1.1 定义 STAGE_LABELS 映射字典

**文件**: `routes.py`
**位置**: 在 `bp = Blueprint("main", __name__)` 之后（第 27 行后）新增

**具体变更**:
```python
STAGE_LABELS = {
    "layout_analysis": "正在分析版面…",
    "translating": "正在翻译…",
    "generating_pdf": "正在生成译文…",
    "generating_pdf_bilingual": "正在生成译文…",
    "finish": "翻译完成",
}
```

**预期结果**: 模块级常量字典，后续 SSE 格式化时可直接索引。

---

### 1.2 修改 SSE 事件格式化

**文件**: `routes.py`
**位置**: `translate_page` 函数内部的 `generate()` 生成器，事件产出所在的 while 循环（第 147~155 行）

**具体变更**:

1) `progress_start` 事件（当前第 148~149 行）:
```python
# 旧：
yield f"data: {json.dumps({'type': 'progress', 'progress': 0, 'stage': evt.get('stage', '')})}\n\n"

# 新：
yield f"data: {json.dumps({
    'type': 'progress',
    'progress': 0,
    'stage': evt.get('stage', ''),
    'stage_current': evt.get('current', 0),
    'stage_total': evt.get('total', 0)
})}\n\n"
```

2) `progress_update` 事件（当前第 150~151 行）:
```python
# 旧：
yield f"data: {json.dumps({'type': 'progress', 'progress': evt.get('overall_progress', 0)})}\n\n"

# 新：
yield f"data: {json.dumps({
    'type': 'progress',
    'progress': evt.get('overall_progress', 0),
    'stage': evt.get('stage', ''),
    'stage_current': evt.get('current', 0),
    'stage_total': evt.get('total', 0)
})}\n\n"
```

3) `finish` 事件（当前第 153~154 行）:
```python
# 旧：
translate_result = evt.get("translate_result")
yield f"data: {json.dumps({'type': 'progress', 'progress': 95})}\n\n"

# 新：
translate_result = evt.get("translate_result")
yield f"data: {json.dumps({
    'type': 'progress',
    'progress': 95,
    'stage': evt.get('stage', 'generating_pdf'),
    'stage_current': 0,
    'stage_total': 0
})}\n\n"
```

**注意**: 
- evt 中的字段名取决于 `pdf2zh_next.do_translate_async_stream` 返回的事件结构。如果 BabelDOC 返回的是 `current`/`total` 字段则直接用；如果不是，需要在第 133 行附近添加一个辅助函数将 BabelDOC 原始字段映射到 `stage_current`/`stage_total`。若 BabelDOC 不提供 `current`/`total`，则统一传 0，由前端 fallback 处理。
- `stage` 字段为空字符串时由前端 fallback（不更新状态文本）。

**预期结果**: 每个 SSE `data:` 帧都携带 `stage`、`stage_current`、`stage_total` 三个新字段。

---

### 1.3 finish 状态事件

**文件**: `routes.py`
**位置**: 第 181 行 finish 事件之前，即 `try` 块成功路径中 `yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"` 之前

**具体变更**:
在第 181 行之前插入一个明确的完成状态事件：
```python
yield f"data: {json.dumps({
    'type': 'progress',
    'progress': 100,
    'stage': 'finish',
    'stage_current': 0,
    'stage_total': 0
})}\n\n"
```

变更为（在原行之前插入）：
```python
            yield f"data: {json.dumps({
                'type': 'progress', 'progress': 100,
                'stage': 'finish', 'stage_current': 0, 'stage_total': 0
            })}\n\n"
            yield f"data: {json.dumps({'type': 'finish', 'progress': 100})}\n\n"
```

**预期结果**: 前端收到 `stage=finish` 事件后可触发"翻译完成"状态。

---

## 任务 2：前端 HTML 结构调整

### 2.1 在 #progress-bar 内添加状态文字 span

**文件**: `templates/index.html`
**位置**: 第 26 行

**具体变更**:
```html
<!-- 旧 -->
<div id="progress-bar"><div id="progress-fill"></div></div>

<!-- 新 -->
<div id="progress-bar"><div id="progress-fill"></div><span id="progress-status-text"></span></div>
```

**预期结果**: DOM 中 `#progress-bar` 新增一个可操作的 `<span>` 子元素。

---

## 任务 3：前端 CSS 样式调整

### 4.1 修改 #progress-bar 为 flex 容器

**文件**: `static/style.css`
**位置**: 第 121~132 行 (`#toolbar #progress-bar` 规则块)

**具体变更**:
```css
/* 旧 */
#toolbar #progress-bar {
    display: none;
    width: 120px;
    height: 4px;
    background: #444;
    border-radius: 2px;
    overflow: hidden;
}

#toolbar #progress-bar.active {
    display: block;
}

/* 新 */
#toolbar #progress-bar {
    display: none;
    align-items: center;
    gap: 8px;
    height: auto;
}

#toolbar #progress-bar.active {
    display: flex;
}
```

**注意**: 原有 `width: 120px` / `height: 4px` / `background: #444` / `border-radius` / `overflow` 这些属性应移到 `#progress-fill` 的**父容器**上。需要在 CSS 中新增一个进度条 track 容器，或直接将 `#progress-bar` 内部的进度条部分包裹在 `<div id="progress-track">` 中。

更推荐方案：在 HTML 层面将 `#progress-fill` 包裹在 `#progress-track` 中，避免 flex gap 引起的布局问题。详见 2.1 的最终 HTML 和 4.2 的 track 样式。

**最终 HTML 结构**（修正 2.1）:
```html
<div id="progress-bar">
    <div id="progress-track"><div id="progress-fill"></div></div>
    <span id="progress-status-text"></span>
</div>
```

**对应 CSS**:
- `#progress-bar`: flex 容器, `display: none` / `.active` → `display: flex`
- `#progress-track`: 120px 宽, 4px 高, 背景 #444, border-radius, overflow:hidden（原 `#progress-bar` 样式移到这里）
- `#progress-fill`: 保持现有样式不变

---

### 4.2 添加 #progress-status-text 样式

**文件**: `static/style.css`
**位置**: 在 `#progress-fill` 规则之后新增

**具体变更**:
```css
#toolbar #progress-track {
    width: 120px;
    height: 4px;
    background: #444;
    border-radius: 2px;
    overflow: hidden;
    flex-shrink: 0;
}

#toolbar #progress-status-text {
    font-size: 12px;
    color: #aaa;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 180px;
}
```

**预期结果**: 状态文字在进度条右侧水平并排，超长文本以省略号截断。

---

### 4.3 添加 error 状态样式

**文件**: `static/style.css`
**位置**: 在 `#toolbar #progress-status-text` 规则之后新增

**具体变更**:
```css
#toolbar #progress-status-text.error {
    color: #e55;
}

#toolbar #progress-status-text.done {
    color: #48c78e;
}
```

**预期结果**: 出错时文字变红，完成时变绿。

---

## 任务 4：前端 JS 事件处理

### 3.1 新增前端常量与 DOM 引用

**文件**: `static/app.js`
**位置**: 第 16 行之后（DOM 引用区）新增 `progressStatusText` 引用，并在文件顶部新增 `STAGE_LABELS` 映射

**具体变更**:

1) 在第 16 行后新增 DOM 引用:
```javascript
const progressStatusText = document.getElementById('progress-status-text');
```

2) 在 DOM 引用区之后（约第 20 行后）新增 STAGE_LABELS:
```javascript
const STAGE_LABELS = {
    layout_analysis: '正在分析版面…',
    translating: '正在翻译…',
    generating_pdf: '正在生成译文…',
    generating_pdf_bilingual: '正在生成译文…',
    finish: '翻译完成'
};
```

**预期结果**: 前端拥有与后端同义的中文映射，可用 `STAGE_LABELS[stage] || stage` 进行 fallback。

---

### 3.2 添加状态管理的生命周期变量

**文件**: `static/app.js`
**位置**: 第 7 行附近（`isTranslating` 旁边）

**具体变更**:
```javascript
let statusTimer = null;
```

**预期结果**: 用于管理 done/error 状态的自动清除定时器。

---

### 3.3 翻译开始时初始化状态显示

**文件**: `static/app.js`
**位置**: `translateCurrentPage()` 函数，第 224~226 行（设置进度条 active 的代码块）

**具体变更**: 在第 226 行后追加:
```javascript
    progressStatusText.textContent = '';
    progressStatusText.classList.remove('error', 'done');
    if (statusTimer) {
        clearTimeout(statusTimer);
        statusTimer = null;
    }
```

**预期结果**: 每次新翻译开始时清除上一轮状态。

---

### 3.4 增强 SSE progress 事件处理

**文件**: `static/app.js`
**位置**: 第 257~258 行 (`if (evt.type === 'progress')` 分支)

**具体变更**:

```javascript
// 旧：
if (evt.type === 'progress') {
    progressFill.style.width = `${evt.progress}%`;
}

// 新：
if (evt.type === 'progress') {
    progressFill.style.width = `${evt.progress}%`;

    if (evt.stage) {
        let label = STAGE_LABELS[evt.stage] || evt.stage;
        if (evt.stage_current > 0 && evt.stage_total > 0) {
            label += ` 第 ${evt.stage_current}/${evt.stage_total} 段`;
        }
        progressStatusText.textContent = label;

        if (evt.stage === 'finish') {
            progressStatusText.classList.add('done');
            progressStatusText.classList.remove('error');
        } else {
            progressStatusText.classList.remove('done', 'error');
        }
    }
}
```

**步骤拆解**:
- 每次 progress 事件更新进度条宽度
- 若 `evt.stage` 非空，映射为中文标签
- 若 `stage_current > 0 && stage_total > 0`，追加段落级进度
- 根据 stage 是否为 `finish` 设置 `.done` 样式类

---

### 3.5 翻译完成处理

**文件**: `static/app.js`
**位置**: 第 259~260 行 (`finish` 类型事件分支)

**具体变更**:
```javascript
// 旧：
} else if (evt.type === 'finish') {
    progressFill.style.width = '100%';
}

// 新：
} else if (evt.type === 'finish') {
    progressFill.style.width = '100%';
    progressStatusText.textContent = STAGE_LABELS.finish;
    progressStatusText.classList.add('done');
    progressStatusText.classList.remove('error');

    statusTimer = setTimeout(() => {
        progressBar.classList.remove('active');
        progressStatusText.textContent = '';
        progressStatusText.classList.remove('done', 'error');
    }, 2000);
}
```

**注意**: 需要修改 finally 块（第 285~289 行）——不再总是立即移除 `active`，因为 finish 后需要保持 2 秒。

---

### 3.6 修改 finally 清理逻辑

**文件**: `static/app.js`
**位置**: 第 285~289 行 (finally 块)

**具体变更**:
```javascript
// 旧：
} finally {
    isTranslating = false;
    translateBtn.disabled = false;
    translateBtn.textContent = 'Translate';
    progressBar.classList.remove('active');
}

// 新：
} finally {
    isTranslating = false;
    translateBtn.disabled = false;
    translateBtn.textContent = 'Translate';
    // 不在正常完成时立即隐藏进度条 (由 statusTimer 控制)
    // 只在异常时立即隐藏
}
```

**注意**: 需要考虑正常完成路径（finish）和异常路径的不同清理行为。

更精确的实现——在 catch 块中强制清理：
在 catch 块（第 282~284 行）增加：
```javascript
} catch (e) {
    progressBar.classList.remove('active');
    progressStatusText.textContent = e.message || '翻译出错';
    progressStatusText.classList.add('error');
    progressStatusText.classList.remove('done');
    statusTimer = setTimeout(() => {
        progressStatusText.textContent = '';
        progressStatusText.classList.remove('error', 'done');
    }, 3000);
    fileArea.classList.remove('hidden');
    fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">Translation error: ${e.message}</p>`);
}
```

finally 块改为：
```javascript
} finally {
    isTranslating = false;
    translateBtn.disabled = false;
    translateBtn.textContent = 'Translate';
}
```

**注意**: SSE 内部的 `error` 事件类型会 throw，触发 catch 块。但原来的 catch 块会做 `fileArea.classList.remove('hidden')` 这可能会影响 UI。这里保持原逻辑不变，仅追加状态文本的错误显示。

---

### 3.7 SSE error 事件处理增强

**文件**: `static/app.js`
**位置**: 第 261~263 行

当前代码 `throw new Error(evt.error)` 会跳出 while 循环，进入外层 catch。这已经能工作——错误会被 3.6 的 catch 块捕获并显示。无需额外修改此分支。

---

## 任务 5：集成验证

### 5.1 验证正常翻译流程

1. 启动应用
2. 打开 PDF → 选择一页 → 点击 Translate
3. 验证：
   - 进度条显示中文阶段文字（"正在分析版面…" / "正在翻译…" 等）
   - 段落级进度显示（如 "正在翻译... 第 3/8 段"）
   - 进度条百分比同步更新
4. 翻译完成后验证：
   - 显示绿色 "翻译完成"
   - 2 秒后进度条和文字自动消失
   - Translate 按钮恢复可点击

### 5.2 验证错误场景

1. 模拟翻译错误（如使用无效 prompt 导致翻译失败）
2. 验证：
   - 红色错误文字显示在状态文字区域
   - 3 秒后自动清除

### 5.3 验证边缘情况

1. SSE `stage` 字段缺失（旧版兼容）：状态文字不更新，进度条正常工作
2. 未知 stage 名称：显示原始英文名
3. `stage_current`/`stage_total` 为 0：不显示段落级进度
4. 快速连续翻译：旧状态被清除

### 5.4 代码质量检查

```bash
ruff check routes.py
```

确认无 lint 错误。

---

## 文件变更汇总

| 文件 | 新增行 | 修改行 | 说明 |
|------|--------|--------|------|
| `routes.py` | ~10 | 6 | STAGE_LABELS + 3处SSE格式化 |
| `templates/index.html` | 1 | 1 | #progress-bar 内部结构 |
| `static/style.css` | ~25 | 6 | flex布局 + status-text + error/done |
| `static/app.js` | ~45 | 10 | STAGE_LABELS + 生命周期 + SSE增强 |

## 注意事项

1. **BabelDOC 事件字段映射**: 实施前需确认 `do_translate_async_stream` 返回的 `progress_update` 事件中是否有 `stage`、`current`、`total` 字段。如字段名不同，需在 routes.py 中做映射适配。
2. **finally 清理逻辑变更**: 进度条 active 不再是翻译结束立即移除，而是由 statusTimer (2s) 或 error (catch 块) 来控制，需要仔细处理正常/异常两条路径。
3. **CSS 改动影响**: `#progress-bar` 从 `display: block` 改为 `display: flex` 后，JavaScript 中 `progressBar.classList.add('active')` / `remove('active')` 不受影响。
