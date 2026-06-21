---
change: modularize-frontend
design-doc: docs/superpowers/specs/2026-06-21-modularize-frontend-design.md
base-ref: 4f85e9028f90f1d48776fce5661f82fd36f9df5c
---

# 前端模块化重构 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 将 `static/app.js`（335 行单体文件）拆分为 6 个 ES Module + 薄入口，消除前后端 `STAGE_LABELS` 重复定义，新增 `/api/stages` 后端端点。

**架构：** ES Module 拆分，每个模块为无状态工具函数，共享状态全部集中在 `app.js` 入口。`index.html` 改用 `<script type="module">`。`STAGE_LABELS` 以后端 `sse_stream.py` 为唯一权威来源。

**技术栈：** 原生 ES Module（无打包工具）、Flask + pytest、Vanilla JS

## 全局约束

- 前端 UX 必须与原版字节一致（DOM 结构、CSS 类名、事件行为不变）
- 无构建工具（项目无 bundler）
- 浏览器兼容：Chrome 61+ / Firefox 60+ / Safari 11+ / Edge 79+（ES Module 原生支持）
- 文件编码：`\uXXXX` 转义序列用于 JS 文件中的中文字符（与原 `app.js` 风格一致）
- 后端 `ruff check` 零错误

---

## 文件结构

```
static/
├── app.js              (入口，~80 行)              [修改]
└── modules/
    ├── dom.js           (DOM 引用、元素创建、占位符) [新建]
    ├── lazy-loader.js   (IntersectionObserver 懒加载) [新建]
    ├── scroll-sync.js   (滚动同步、当前页检测)        [新建]
    ├── sse-client.js    (SSE 流解析，纯函数)          [新建]
    ├── stages.js        (stage 标签获取与缓存)        [新建]
    └── translator.js    (翻译编排，回调驱动)          [新建]
templates/
└── index.html           (<script> 标签改为 type="module") [修改]
routes.py                (新增 GET /api/stages)           [修改]
tests/
└── test_routes.py       (新增 /api/stages 测试)          [修改]
docs/
└── manual-verification-checklist.md                    [新建]
```

### 模块职责与导出

| 文件 | 导出 | 职责 |
|------|------|------|
| `dom.js` | `getElements()`, `createPageEl(pageNum, side, pageWidth, pageHeight)`, `calculatePlaceholderHeight(pageWidth, pageHeight)` | DOM 引用缓存 + 页面元素工厂 |
| `lazy-loader.js` | `setupIntersectionObserver({ load, unload })` | IntersectionObserver 管理，load/unload 回调由调用方注入 |
| `scroll-sync.js` | `setupScrollSync({ left, right })`, `setupPageDetection({ container }, onPageChange)` | 滚动同步 + 可见页检测 |
| `sse-client.js` | `readSSEStream(response, onEvent)` | 纯 SSE 解析，无 DOM 访问 |
| `stages.js` | `fetchStageLabels()`, `getStageLabel(stage)` | stage 标签缓存，fetch 失败回退内置副本 |
| `translator.js` | `translateCurrentPage(page, callbacks)` | 翻译编排，调用 sse-client 和 stages，回调驱动 DOM 更新 |

---

### Task 1：行为基线与手动验证清单

**文件：**
- 创建：`docs/manual-verification-checklist.md`

**接口：**
- 产出：`docs/manual-verification-checklist.md` — 10 项行为检查清单，供后续任务逐项回归

- [x] **Step 1：编写手动验证清单**

```markdown
# 前端行为手动验证清单

> 基线记录日期：2026-06-21
> 基线 commit：`4f85e90`
> 用途：模块化拆分后逐项核对，确保行为与原版一致

## 前置条件
1. 启动应用：`python app.py`
2. 打开浏览器访问 `http://127.0.0.1:5000`
3. 使用项目中的测试 PDF 文件

## 检查项

### 1. 双栏渲染
- [ ] 打开 PDF 后，左栏和右栏同时显示所有页面占位符
- [ ] 每栏页面数量等于 PDF 总页数
- [ ] 占位符宽高比正确（与 PDF 页面比例一致）

### 2. 滚动同步
- [ ] 滚动左栏时，右栏同步滚动到相同位置
- [ ] 滚动同步无抖动、无明显延迟

### 3. 独立右栏滚动
- [ ] 单独滚动右栏时，左栏不跟随（同步仅从左→右单向）

### 4. 当前页检测
- [ ] 底部工具栏 `#page-indicator` 显示当前可视页面编号（从 Page 1 开始）
- [ ] 滚动到不同页面时，指示器实时更新

### 5. 懒加载缓冲 5 页
- [ ] 可见页面±5 页范围内的占位符被替换为实际 `<img>` 图片
- [ ] 网络请求仅对缓冲区内页面发起

### 6. 卸载离屏
- [ ] 滚出缓冲区（超过±5 页范围）的 `<img>` 被替换回占位符
- [ ] 1000 页 PDF 滚动性能无明显下降

### 7. 翻译进度各 stage
- [ ] 点击 Translate 后，进度条显示各阶段标签（正在分析版面… → 正在翻译… → 正在生成译文… → 翻译完成）
- [ ] 翻译阶段显示段落级进度（如 "正在翻译… 第 2/5 段"）
- [ ] 翻译完成后右栏对应页面标记为已翻译（`.translated` CSS 类）

### 8. Prompt 切换
- [ ] 点击 `+ Prompt` 按钮显示自定义 prompt 输入框，按钮文字变为 `- Prompt`
- [ ] 再次点击隐藏输入框，按钮文字恢复为 `+ Prompt`

### 9. 错误显示
- [ ] 翻译出错时，进度条隐藏，错误信息显示在状态区域（红色）
- [ ] 3 秒后错误信息自动消失

### 10. Open 失败提示
- [ ] 输入不存在的文件路径并点击 Open，文件选择区显示红色错误提示
- [ ] 网络错误时同样显示错误提示
```

- [ ] **Step 2：手动走一遍基线**

在修改任何代码之前，启动应用并逐项检查上述 10 条行为，记录当前预期行为作为对照基线。

- [x] **Step 3：提交**

```bash
git add docs/manual-verification-checklist.md
git commit -m "docs: add frontend manual verification checklist for modularize-frontend"
```

---

### Task 2：后端 GET /api/stages 端点

**文件：**
- 修改：`routes.py:118`（在 `translated_pages` 路由之后插入）
- 修改：`tests/test_routes.py`（文件末尾追加测试函数）

**接口：**
- 产出：`GET /api/stages` → `{"layout_analysis": "正在分析版面\u2026", "translating": "正在翻译\u2026", "generating_pdf": "正在生成译文\u2026", "generating_pdf_bilingual": "正在生成译文\u2026", "finish": "翻译完成"}`

- [x] **Step 1：编写失败测试**

在 `tests/test_routes.py` 末尾追加：

```python
def test_get_stages(test_client):
    resp = test_client.get('/api/stages')
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert len(data) == 5
    assert data["layout_analysis"] == '\u6b63\u5728\u5206\u6790\u7248\u9762\u2026'
    assert data["translating"] == '\u6b63\u5728\u7ffb\u8bd1\u2026'
    assert data["generating_pdf"] == '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026'
    assert data["generating_pdf_bilingual"] == '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026'
    assert data["finish"] == '\u7ffb\u8bd1\u5b8c\u6210'
    assert data == {
        "layout_analysis": '\u6b63\u5728\u5206\u6790\u7248\u9762\u2026',
        "translating": '\u6b63\u5728\u7ffb\u8bd1\u2026',
        "generating_pdf": '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026',
        "generating_pdf_bilingual": '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026',
        "finish": '\u7ffb\u8bd1\u5b8c\u6210',
    }
```

- [x] **Step 2：运行测试验证失败**

```bash
pytest tests/test_routes.py::test_get_stages -v
```

预期：`FAILED` — 404 Not Found（端点尚不存在）

- [x] **Step 3：实现端点**

在 `routes.py` 第 113 行（`translated_pages` 路由函数之后，`@bp.app_errorhandler(404)` 之前）插入：

```python
@bp.route("/api/stages")
def get_stages():
    return jsonify(sse_stream.STAGE_LABELS)
```

- [x] **Step 4：运行测试验证通过**

```bash
pytest tests/test_routes.py::test_get_stages -v
```

预期：`PASSED`

- [x] **Step 5：运行全量后端测试**

```bash
pytest tests/ -v
```

预期：全部测试通过

- [x] **Step 6：提交**

```bash
git add routes.py tests/test_routes.py
git commit -m "feat: add GET /api/stages endpoint returning STAGE_LABELS"
```

---

### Task 3：抽取 dom.js 模块

**文件：**
- 创建：`static/modules/dom.js`

**接口：**
- 产出：`getElements()` → `{ leftCol, rightCol, pageIndicator, translateBtn, promptInput, promptToggle, progressBar, progressFill, progressStatusText, fileArea, appView, toolbar, openBtn, pdfPathInput }`
- 产出：`createPageEl(pageNum, side)` → `HTMLElement`
- 产出：`calculatePlaceholderHeight(pageWidth, pageHeight)` → `number`（百分比整数）

- [ ] **Step 1：创建 `static/modules/` 目录**

```powershell
New-Item -ItemType Directory -Path "static\modules" -Force
```

- [ ] **Step 2：编写 `dom.js`**

```javascript
let _cache = null;

export function getElements() {
    if (_cache) return _cache;

    const leftCol = document.getElementById('left-column');
    const rightCol = document.getElementById('right-column');
    const pageIndicator = document.getElementById('page-indicator');
    const translateBtn = document.getElementById('translate-btn');
    const promptInput = document.getElementById('prompt-input');
    const promptToggle = document.getElementById('prompt-toggle');
    const progressBar = document.getElementById('progress-bar');
    const progressFill = document.getElementById('progress-fill');
    const progressStatusText = document.getElementById('progress-status-text');
    const fileArea = document.getElementById('file-input-area');
    const appView = document.getElementById('app');
    const toolbar = document.getElementById('toolbar');
    const openBtn = document.getElementById('open-btn');
    const pdfPathInput = document.getElementById('pdf-path');

    _cache = {
        leftCol,
        rightCol,
        pageIndicator,
        translateBtn,
        promptInput,
        promptToggle,
        progressBar,
        progressFill,
        progressStatusText,
        fileArea,
        appView,
        toolbar,
        openBtn,
        pdfPathInput,
    };

    return _cache;
}

export function calculatePlaceholderHeight(pageWidth, pageHeight) {
    if (pageWidth && pageHeight) {
        const ratio = pageHeight / pageWidth;
        return Math.round(100 * ratio);
    }
    return 600;
}

export function createPageEl(pageNum, side, pageWidth, pageHeight) {
    const container = document.createElement('div');
    container.className = 'page-container';
    container.dataset.page = pageNum;
    container.dataset.side = side;

    const ph = calculatePlaceholderHeight(pageWidth, pageHeight);

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    placeholder.style.paddingBottom = `${ph}%`;
    placeholder.textContent = `Page ${pageNum + 1}`;
    placeholder.dataset.loaded = 'false';
    container.appendChild(placeholder);

    return container;
}
```

- [ ] **Step 3：提交**

```bash
git add static/modules/dom.js
git commit -m "feat: extract dom.js module — getElements, createPageEl, calculatePlaceholderHeight"
```

---

### Task 4：抽取 lazy-loader.js 模块

**文件：**
- 创建：`static/modules/lazy-loader.js`

**接口：**
- 产出：`setupIntersectionObserver({ load, unload })` → void（创建 IntersectionObserver 并 observe 所有 `.page-container`）

- [ ] **Step 1：编写 `lazy-loader.js`**

```javascript
const BUFFER = 5;

export function setupIntersectionObserver({ load, unload }) {
    const observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
            const container = entry.target;
            if (entry.isIntersecting) {
                load(container);
            } else {
                unload(container);
            }
        }
    }, {
        root: null,
        rootMargin: `${BUFFER * 100}% 0px`,
    });

    const allContainers = document.querySelectorAll('.page-container');
    allContainers.forEach(c => observer.observe(c));
}
```

- [ ] **Step 2：提交**

```bash
git add static/modules/lazy-loader.js
git commit -m "feat: extract lazy-loader.js module — setupIntersectionObserver"
```

---

### Task 5：抽取 scroll-sync.js 模块

**文件：**
- 创建：`static/modules/scroll-sync.js`

**接口：**
- 产出：`setupScrollSync({ left, right })` → void（单向滚动同步 left→right）
- 产出：`setupPageDetection({ container }, onPageChange)` → void（设置 scroll 监听，调用 `onPageChange(pageNum)` 回调）

- [ ] **Step 1：编写 `scroll-sync.js`**

```javascript
export function setupScrollSync({ left, right }) {
    let syncing = false;

    left.addEventListener('scroll', () => {
        if (!syncing) {
            syncing = true;
            right.scrollTop = left.scrollTop;
            requestAnimationFrame(() => {
                syncing = false;
            });
        }
    });
}

export function setupPageDetection({ container }, onPageChange) {
    container.addEventListener('scroll', () => {
        const containers = container.querySelectorAll('.page-container');
        let bestPage = 0;
        let bestCoverage = 0;
        const viewTop = container.scrollTop;
        const viewBottom = viewTop + container.clientHeight;

        containers.forEach(c => {
            const rect = c.getBoundingClientRect();
            const colRect = container.getBoundingClientRect();
            const top = rect.top - colRect.top + container.scrollTop;
            const bottom = top + rect.height;
            const overlap = Math.min(bottom, viewBottom) - Math.max(top, viewTop);
            const coverage = overlap / rect.height;
            if (coverage > bestCoverage) {
                bestCoverage = coverage;
                bestPage = parseInt(c.dataset.page);
            }
        });

        onPageChange(bestPage);
    });
}
```

- [ ] **Step 2：提交**

```bash
git add static/modules/scroll-sync.js
git commit -m "feat: extract scroll-sync.js module — setupScrollSync, setupPageDetection"
```

---

### Task 6：抽取 sse-client.js 模块

**文件：**
- 创建：`static/modules/sse-client.js`

**接口：**
- 产出：`readSSEStream(response, onEvent)` → `Promise<void>`（解析 SSE `data:` 行，对每个事件调用 `onEvent(parsedObject)`）

- [ ] **Step 1：编写 `sse-client.js`**

```javascript
export async function readSSEStream(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                try {
                    const evt = JSON.parse(line.slice(6));
                    onEvent(evt);
                } catch (e) {
                    if (!(e instanceof SyntaxError)) {
                        throw e;
                    }
                }
            }
        }
    }
}
```

- [ ] **Step 2：提交**

```bash
git add static/modules/sse-client.js
git commit -m "feat: extract sse-client.js module — readSSEStream pure SSE parser"
```

---

### Task 7：抽取 stages.js 模块

**文件：**
- 创建：`static/modules/stages.js`

**接口：**
- 产出：`fetchStageLabels()` → `Promise<Object>`（GET /api/stages，缓存结果，失败回退内置副本）
- 产出：`getStageLabel(stage)` → `string`（同步查找缓存的标签）

- [ ] **Step 1：编写 `stages.js`**

```javascript
const FALLBACK_LABELS = {
    layout_analysis: '\u6b63\u5728\u5206\u6790\u7248\u9762\u2026',
    translating: '\u6b63\u5728\u7ffb\u8bd1\u2026',
    generating_pdf: '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026',
    generating_pdf_bilingual: '\u6b63\u5728\u751f\u6210\u8bd1\u6587\u2026',
    finish: '\u7ffb\u8bd1\u5b8c\u6210',
};

let _cache = null;

export async function fetchStageLabels() {
    if (_cache) return _cache;

    try {
        const resp = await fetch('/api/stages');
        if (!resp.ok) throw new Error('fetch stages failed');
        _cache = await resp.json();
        return _cache;
    } catch (e) {
        console.warn('Failed to fetch /api/stages, using fallback labels:', e);
        _cache = FALLBACK_LABELS;
        return _cache;
    }
}

export function getStageLabel(stage) {
    const labels = _cache || FALLBACK_LABELS;
    return labels[stage] || stage;
}
```

- [ ] **Step 2：提交**

```bash
git add static/modules/stages.js
git commit -m "feat: extract stages.js module — fetchStageLabels, getStageLabel"
```

---

### Task 8：抽取 translator.js 模块

**文件：**
- 创建：`static/modules/translator.js`

**接口：**
- 消费：`readSSEStream` from `sse-client.js`
- 消费：`getStageLabel` from `stages.js`
- 产出：`translateCurrentPage(page, callbacks)` where `callbacks = { onStageChange(stage, labelText), onProgress(percent), onFinish(), onError(message) }` → `Promise<void>`

- [ ] **Step 1：编写 `translator.js`**

```javascript
import { readSSEStream } from './sse-client.js';
import { getStageLabel } from './stages.js';

export async function translateCurrentPage(page, callbacks) {
    const { onStageChange, onProgress, onFinish, onError } = callbacks;

    try {
        const resp = await fetch(`/api/translate/${page}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ prompt: callbacks.prompt || null }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.error || 'Translation failed');
        }

        await readSSEStream(resp, (evt) => {
            if (evt.type === 'progress') {
                onProgress(evt.progress);
                if (evt.stage) {
                    let label = getStageLabel(evt.stage);
                    if (evt.stage_current > 0 && evt.stage_total > 0) {
                        label += ` \u7b2c ${evt.stage_current}/${evt.stage_total} \u6bb5`;
                    }
                    onStageChange(evt.stage, label);
                }
            } else if (evt.type === 'finish') {
                onFinish();
            } else if (evt.type === 'error') {
                onError(evt.error);
            }
        });
    } catch (e) {
        onError(e.message || '\u7ffb\u8bd1\u51fa\u9519');
    }
}
```

- [ ] **Step 2：提交**

```bash
git add static/modules/translator.js
git commit -m "feat: extract translator.js module — translateCurrentPage callback-driven"
```

---

### Task 9：重写 app.js 入口 + 更新 index.html

**文件：**
- 重写：`static/app.js`
- 修改：`templates/index.html:30`

**接口：**
- 消费：`getElements`, `createPageEl`, `calculatePlaceholderHeight` from `dom.js`
- 消费：`setupIntersectionObserver` from `lazy-loader.js`
- 消费：`setupScrollSync`, `setupPageDetection` from `scroll-sync.js`
- 消费：`fetchStageLabels`, `getStageLabel` from `stages.js`
- 消费：`translateCurrentPage` from `translator.js`
- 产出：完整的应用入口，绑定所有事件，持有共享状态

- [ ] **Step 1：更新 `templates/index.html` 第 30 行**

```html
<script type="module" src="/static/app.js"></script>
```

替换原来的 `<script src="/static/app.js" defer></script>`

- [ ] **Step 2：重写 `static/app.js`**

```javascript
import { getElements, createPageEl, calculatePlaceholderHeight } from './modules/dom.js';
import { setupIntersectionObserver } from './modules/lazy-loader.js';
import { setupScrollSync, setupPageDetection } from './modules/scroll-sync.js';
import { fetchStageLabels, getStageLabel } from './modules/stages.js';
import { translateCurrentPage } from './modules/translator.js';

const API = '/api';
let pageCount = 0;
let pageHeight = 0;
let pageWidth = 0;
let currentPage = 0;
let isTranslating = false;
let promptVisible = false;
let statusTimer = null;

let els;

function init() {
    els = getElements();

    els.openBtn.addEventListener('click', openPdf);
    els.pdfPathInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') openPdf();
    });
    els.promptToggle.addEventListener('click', () => {
        promptVisible = !promptVisible;
        els.promptInput.style.display = promptVisible ? 'inline-block' : 'none';
        els.promptToggle.textContent = promptVisible ? '- Prompt' : '+ Prompt';
    });
    els.translateBtn.addEventListener('click', onTranslateClick);

    fetchStageLabels();
}

async function openPdf() {
    const path = els.pdfPathInput.value.trim();
    if (!path) return;

    try {
        const resp = await fetch(`${API}/open`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path }),
        });

        if (!resp.ok) {
            const errText = await resp.text();
            let errMsg = 'Failed to open PDF';
            try {
                const errData = JSON.parse(errText);
                errMsg = errData.error || errMsg;
            } catch (e) {}
            els.fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">${errMsg}</p>`);
            return;
        }

        const data = await resp.json();
        pageCount = data.page_count;
        pageHeight = data.page_height;
        pageWidth = data.page_width;

        els.leftCol.innerHTML = '';
        els.rightCol.innerHTML = '';

        for (let i = 0; i < pageCount; i++) {
            els.leftCol.appendChild(createPageEl(i, 'left', pageWidth, pageHeight));
            els.rightCol.appendChild(createPageEl(i, 'right', pageWidth, pageHeight));
        }

        els.fileArea.classList.add('hidden');
        els.appView.classList.remove('hidden');
        els.toolbar.classList.remove('hidden');

        setupIntersectionObserver({
            load: loadPageImage,
            unload: unloadPageImage,
        });
        setupScrollSync({ left: els.leftCol, right: els.rightCol });
        setupPageDetection({ container: els.leftCol }, onPageChange);
        loadTranslatedState();
    } catch (e) {
        els.fileArea.insertAdjacentHTML('beforeend', `<p style="color:#e55;margin-top:10px">Network error: ${e.message}</p>`);
    }
}

function loadPageImage(container) {
    const page = parseInt(container.dataset.page);
    const side = container.dataset.side;
    const placeholder = container.querySelector('.page-placeholder');

    if (placeholder && placeholder.dataset.loaded === 'true') return;

    const img = document.createElement('img');
    img.src = `${API}/page/${side}/${page}?t=${Date.now()}`;
    img.onload = () => {
        if (placeholder) {
            placeholder.replaceWith(img);
        }
    };
    img.onerror = () => {
        if (placeholder) {
            placeholder.textContent = `Page ${page + 1} (error)`;
        }
    };

    if (placeholder) {
        placeholder.dataset.loaded = 'true';
        container.insertBefore(img, placeholder);
    }
}

function unloadPageImage(container) {
    const img = container.querySelector('img');
    if (!img) return;

    const placeholder = document.createElement('div');
    placeholder.className = 'page-placeholder';
    const ph = calculatePlaceholderHeight(pageWidth, pageHeight);
    placeholder.style.paddingBottom = `${ph}%`;
    placeholder.textContent = `Page ${parseInt(container.dataset.page) + 1}`;
    placeholder.dataset.loaded = 'false';

    img.replaceWith(placeholder);
}

async function loadTranslatedState() {
    try {
        const resp = await fetch(`${API}/translated-pages`);
        if (!resp.ok) return;
        const data = await resp.json();
        data.pages.forEach(p => {
            const el = els.rightCol.querySelector(`.page-container[data-page="${p}"]`);
            if (el) el.classList.add('translated');
        });
    } catch (e) {}
}

function onPageChange(pageNum) {
    if (pageNum !== currentPage) {
        currentPage = pageNum;
        els.pageIndicator.textContent = `Page ${pageNum + 1}`;
    }
}

async function onTranslateClick() {
    if (isTranslating) return;
    isTranslating = true;
    els.translateBtn.disabled = true;
    els.translateBtn.textContent = 'Translating...';
    els.progressBar.classList.add('active');
    els.progressFill.style.width = '0%';
    els.progressStatusText.textContent = '';
    els.progressStatusText.classList.remove('error', 'done');
    if (statusTimer) {
        clearTimeout(statusTimer);
        statusTimer = null;
    }

    await translateCurrentPage(currentPage, {
        prompt: els.promptInput.value.trim() || null,
        onStageChange(stage, labelText) {
            els.progressStatusText.textContent = labelText;
            if (stage === 'finish') {
                els.progressStatusText.classList.add('done');
                els.progressStatusText.classList.remove('error');
            } else {
                els.progressStatusText.classList.remove('done', 'error');
            }
        },
        onProgress(percent) {
            els.progressFill.style.width = `${percent}%`;
        },
        onFinish() {
            els.progressFill.style.width = '100%';
            els.progressStatusText.textContent = getStageLabel('finish');
            els.progressStatusText.classList.add('done');
            els.progressStatusText.classList.remove('error');
            statusTimer = setTimeout(() => {
                els.progressBar.classList.remove('active');
                els.progressStatusText.textContent = '';
                els.progressStatusText.classList.remove('done', 'error');
            }, 2000);

            const rightEl = els.rightCol.querySelector(`.page-container[data-page="${currentPage}"]`);
            if (rightEl) {
                unloadPageImage(rightEl);
                loadPageImage(rightEl);
                rightEl.classList.add('translated');
            }
            loadTranslatedState();
        },
        onError(message) {
            els.progressBar.classList.remove('active');
            els.progressStatusText.textContent = message;
            els.progressStatusText.classList.add('error');
            els.progressStatusText.classList.remove('done');
            statusTimer = setTimeout(() => {
                els.progressStatusText.textContent = '';
                els.progressStatusText.classList.remove('error', 'done');
            }, 3000);
        },
    });

    isTranslating = false;
    els.translateBtn.disabled = false;
    els.translateBtn.textContent = 'Translate';
}

init();
```

- [ ] **Step 3：手动验证清单**

对照 Task 1 的 10 项清单，逐项检查所有行为与基线一致。

- [ ] **Step 4：提交**

```bash
git add static/app.js templates/index.html
git commit -m "refactor: rewrite app.js as thin ES module entry, update index.html to type=module"
```

---

### Task 10：全量回归与 lint

**文件：**
- 无新建文件
- 验证涉及：`tests/`, `static/app.js`, `static/modules/`, `routes.py`, `sse_stream.py`

- [ ] **Step 1：运行全量后端测试**

```bash
pytest tests/ -v
```

预期：全部测试通过

- [ ] **Step 2：运行 ruff check**

```bash
ruff check
```

预期：零错误

- [ ] **Step 3：grep 确认 STAGE_LABELS 单一来源**

```bash
rg "STAGE_LABELS" static/
```

预期：前端 `static/` 目录中**不出现** `STAGE_LABELS` 常量定义（仅在 `stages.js` 中以 `FALLBACK_LABELS` 名存在，且该副本仅作为 fetch 失败时的降级方案）。

```bash
rg "STAGE_LABELS" --type py
```

预期：仅在 `sse_stream.py` 中定义（第 16 行），`routes.py` 中通过 `sse_stream.STAGE_LABELS` 引用。

- [ ] **Step 4：最终手动验证**

按照 `docs/manual-verification-checklist.md` 的 10 项清单，完成最终全量回归验证。

- [ ] **Step 5：提交**

```bash
git add -A
git commit -m "chore: final regression — all tests pass, ruff clean, single STAGE_LABELS source"
```

---

## 自审清单

### 1. Spec 覆盖

| 设计要求 | 对应任务 |
|----------|---------|
| 手动验证清单（9 项行为） | Task 1 |
| 后端 `/api/stages` 端点 + 测试 | Task 2 |
| 抽取 `dom.js` | Task 3 |
| 抽取 `lazy-loader.js` | Task 4 |
| 抽取 `scroll-sync.js` | Task 5 |
| 抽取 `sse-client.js` | Task 6 |
| 抽取 `stages.js`（fetch + 缓存 + 回退） | Task 7 |
| 抽取 `translator.js`（回调驱动） | Task 8 |
| 重写 `app.js` 入口 | Task 9 |
| 更新 `index.html` `<script type="module">` | Task 9 |
| 删除前端 `STAGE_LABELS` 硬编码 | Task 9（新版 app.js 不再包含） |
| 后端 `STAGE_LABELS` 为单一来源 | Task 10 Step 3 |
| 全量回归 `pytest tests/ -v` + `ruff check` | Task 10 |
| 前端 UX 字节一致 | 每个模块任务后手动验证 + Task 10 Step 4 |

### 2. 无占位符检查

所有步骤均包含实际代码、确切命令、预期输出。无 "TBD"、"TODO"、"implement later"。

### 3. 类型一致性

- `createPageEl(pageNum, side, pageWidth, pageHeight)` — Task 3 定义，Task 9 调用参数一致
- `setupIntersectionObserver({ load, unload })` — Task 4 定义，Task 9 传入 `{ load: loadPageImage, unload: unloadPageImage }`
- `setupScrollSync({ left, right })` — Task 5 定义，Task 9 传入 `{ left: els.leftCol, right: els.rightCol }`
- `setupPageDetection({ container }, onPageChange)` — Task 5 定义，Task 9 传入 `{ container: els.leftCol }, onPageChange`
- `readSSEStream(response, onEvent)` — Task 6 定义，Task 8 调用
- `fetchStageLabels()` → `Promise<Object>` — Task 7 定义，Task 9 调用
- `getStageLabel(stage)` → `string` — Task 7 定义，Task 8 和 Task 9 调用
- `translateCurrentPage(page, callbacks)` — Task 8 定义，Task 9 调用，`callbacks = { prompt, onStageChange, onProgress, onFinish, onError }`

## 执行交接

计划已保存至 `docs/superpowers/plans/2026-06-21-modularize-frontend.md`。两种执行方式：

**1. Subagent-Driven (推荐)** — 每个 Task 启动独立 subagent，任务间 review，快速迭代

**2. Inline 执行** — 本 session 内使用 executing-plans 逐步执行，批量提交 review

选择哪种方式？
