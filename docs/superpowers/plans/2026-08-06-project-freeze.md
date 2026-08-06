# PDF Reader Minimal Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a clean, documented, reproducibly verifiable frozen version of PDF Reader without adding product features or changing translation behavior.

**Architecture:** Preserve the existing Flask/PyMuPDF/pdf2zh-next backend and native JavaScript reader unchanged. Limit implementation to damaged UI copy, deterministic verification entry points, CI coverage, and freeze/status documentation. Treat historical RED and task-specific scripts as diagnostics rather than supported regression suites.

**Tech Stack:** Python 3.12, Flask, PyMuPDF, pdf2zh-next, pytest, Ruff, Node.js, jsdom, PowerShell, GitHub Actions.

## Global Constraints

- Do not change translation flow, cache formats, API contracts, PDF output, layout, colors, or interaction structure.
- Do not add PDF.js, annotations, search, AI Q&A, task queues, packaging, model providers, OCR, cloud deployment, or Zotero integration.
- Do not upgrade dependencies or change the repository license.
- Fix only confirmed text corruption and verification/documentation gaps.
- Keep API keys, `config.toml`, caches, logs, generated PDFs, and temporary files out of commits.
- Mention the upstream AGPL-3.0 dependency as a risk reminder, not as legal advice.

## File Structure

- Modify `templates/index.html`: restore readable toolbar and startup-page labels only.
- Modify `package.json`: restore readable package metadata and define stable frontend test scripts.
- Create `tests/run-ui-copy-tests.mjs`: prevent regression of the confirmed mojibake and malformed toolbar markup.
- Create `tests/README.md`: distinguish supported regression suites from historical diagnostic scripts.
- Create `scripts/verify.ps1`: provide the single local verification entry point.
- Modify `.github/workflows/ci.yml`: run the same supported Python and frontend checks in CI.
- Create `docs/PROJECT_STATUS.md`: record freeze status, architecture entry points, limitations, licensing reminder, and restart guidance.
- Replace `README.md`: provide a concise, readable project entry point with frozen status and current commands.

---

### Task 1: Restore Readable UI and Package Copy

**Files:**
- Create: `tests/run-ui-copy-tests.mjs`
- Modify: `templates/index.html`
- Modify: `package.json`

**Interfaces:**
- Consumes: UTF-8 text files `templates/index.html` and `package.json`.
- Produces: executable Node regression test `node tests/run-ui-copy-tests.mjs`; package script `npm run test:ui-copy`.

- [ ] **Step 1: Write the failing UI-copy regression test**

Create `tests/run-ui-copy-tests.mjs` with this complete content:

```javascript
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const testsDir = fileURLToPath(new URL('.', import.meta.url));
const rootDir = resolve(testsDir, '..');
const html = readFileSync(resolve(rootDir, 'templates', 'index.html'), 'utf8');
const packageJson = JSON.parse(readFileSync(resolve(rootDir, 'package.json'), 'utf8'));

const requiredHtml = [
    '<title>PDF 双语阅读器</title>',
    '<h2>打开 PDF 文档</h2>',
    'title="展开更多功能"',
    '>▶</button>',
    '>重置缩放</button>',
    '<label for="from-page">起</label>',
    '<label for="to-page">止</label>',
    '>范围</button>',
    '>全文</button>',
];

for (const fragment of requiredHtml) {
    assert.ok(html.includes(fragment), `missing readable UI fragment: ${fragment}`);
}

assert.equal(
    packageJson.description,
    '用于阅读英文教材和论文的本地双语 PDF 翻译阅读器。',
);

console.log('UI copy checks passed');
```

- [ ] **Step 2: Run the test and verify the current corrupted copy fails**

Run:

```powershell
node tests/run-ui-copy-tests.mjs
```

Expected: non-zero exit with `AssertionError` reporting a missing readable UI fragment.

- [ ] **Step 3: Restore the exact intended copy without changing structure**

In `templates/index.html`, preserve all existing IDs, classes, and element order. Make only these replacements:

```html
<title>PDF 双语阅读器</title>
...
<h2>打开 PDF 文档</h2>
...
<button id="toolbar-toggle" type="button" title="展开更多功能">▶</button>
...
<button id="zoom-reset">重置缩放</button>
...
<label for="from-page">起</label>
...
<label for="to-page">止</label>
...
<button id="range-translate-btn" type="button">范围</button>
<button id="full-translate-btn" type="button">全文</button>
```

In `package.json`, replace only `description` and add the first test script:

```json
"description": "用于阅读英文教材和论文的本地双语 PDF 翻译阅读器。",
...
"scripts": {
  "test": "npm run test:frontend",
  "test:ui-copy": "node tests/run-ui-copy-tests.mjs",
  "test:translator": "node tests/run-translator-tests.mjs",
  "test:zoom": "node tests/run-zoom-tests.mjs"
}
```

`test:frontend` is intentionally added in Task 2. During this task, run the direct UI-copy script rather than `npm test`.

- [ ] **Step 4: Run the focused test and existing stable frontend tests**

Run:

```powershell
node tests/run-ui-copy-tests.mjs
npm run test:translator
npm run test:zoom
node tests/run-alignment-controller-tests.mjs
```

Expected: all four commands exit `0`; UI output includes `UI copy checks passed`.

- [ ] **Step 5: Commit the copy repair and regression test**

```powershell
git add -- templates/index.html package.json tests/run-ui-copy-tests.mjs
git commit -m "fix: restore readable interface copy"
```

---

### Task 2: Define Supported Tests and a Unified Verification Entry Point

**Files:**
- Modify: `package.json`
- Create: `tests/README.md`
- Create: `scripts/verify.ps1`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `npm run test:ui-copy`, `npm run test:translator`, `npm run test:zoom`, `tests/run-alignment-controller-tests.mjs`, `pytest`, and Ruff.
- Produces: `npm test` for all supported frontend regression tests; `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` for complete repository verification.

- [ ] **Step 1: Demonstrate that the unified frontend command is not defined yet**

Run:

```powershell
npm run test:frontend
```

Expected: non-zero exit with `Missing script: "test:frontend"`.

- [ ] **Step 2: Add the supported frontend suite to `package.json`**

Make the complete scripts object:

```json
"scripts": {
  "test": "npm run test:frontend",
  "test:frontend": "npm run test:ui-copy && npm run test:translator && npm run test:zoom && node tests/run-alignment-controller-tests.mjs",
  "test:ui-copy": "node tests/run-ui-copy-tests.mjs",
  "test:translator": "node tests/run-translator-tests.mjs",
  "test:zoom": "node tests/run-zoom-tests.mjs"
}
```

- [ ] **Step 3: Document formal and historical frontend scripts**

Create `tests/README.md` with this content:

```markdown
# Test Suites

## Supported regression suites

Run all supported frontend tests with:

```powershell
npm test
```

The supported suite contains:

- `run-ui-copy-tests.mjs` — startup and toolbar copy integrity.
- `run-translator-tests.mjs` — SSE parsing and translation callbacks.
- `run-zoom-tests.mjs` — zoom behavior.
- `run-alignment-controller-tests.mjs` — dual-column alignment behavior and write exclusivity.

## Historical diagnostics

The remaining `.mjs` files are retained as development history and targeted diagnostics. They are not part of `npm test`:

- `run-alignment-repro-tests.mjs` intentionally reproduces RED-phase alignment failures.
- `run-lazy-loader-tests.mjs` is a legacy inline self-test harness and is not stable under the current Node/jsdom environment.
- `run-task-4.4-tests.mjs` and `run-task-4.5-tests.mjs` are task-specific historical harnesses that parse older `app.js` function shapes.

Do not interpret failures from historical diagnostics as a failed supported regression suite.
```

- [ ] **Step 4: Create the repository verification script**

Create `scripts/verify.ps1` with this content:

```powershell
$ErrorActionPreference = 'Stop'

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host "==> $Label"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE"
    }
}

$python = Join-Path $PSScriptRoot '..\venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = 'python'
}

Invoke-Checked 'Ruff lint' { & $python -m ruff check . }
Invoke-Checked 'Ruff format check' { & $python -m ruff format --check . }
Invoke-Checked 'Python tests' { & $python -m pytest -q }
Invoke-Checked 'Frontend tests' { npm test }

Write-Host 'All verification checks passed.'
```

- [ ] **Step 5: Update CI to cover the supported frontend suite**

Replace `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: windows-latest
    name: Lint & Test

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
          cache-dependency-path: requirements.lock

      - uses: actions/setup-node@v4
        with:
          node-version: '22'
          cache: 'npm'

      - name: Install Python dependencies
        run: pip install -r requirements.lock

      - name: Install frontend test dependencies
        run: npm ci

      - name: Verify repository
        shell: powershell
        run: ./scripts/verify.ps1
```

- [ ] **Step 6: Run the unified frontend and full local verification commands**

Run:

```powershell
npm test
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Expected: both commands exit `0`; the second ends with `All verification checks passed.`

- [ ] **Step 7: Commit the verification entry points**

```powershell
git add -- package.json tests/README.md scripts/verify.ps1 .github/workflows/ci.yml
git commit -m "test: add unified freeze verification"
```

---

### Task 3: Record the Frozen Project State

**Files:**
- Create: `docs/PROJECT_STATUS.md`

**Interfaces:**
- Consumes: current module boundaries in `app.py`, `routes.py`, `state.py`, `translation_orchestrator.py`, `sse_stream.py`, `translation_lifecycle.py`, `translation_settings.py`, `static/app.js`, and `static/modules/`.
- Produces: stable project status reference linked from `README.md` in Task 4.

- [ ] **Step 1: Create the project status document**

Create `docs/PROJECT_STATUS.md` with these exact sections and facts:

```markdown
# Project Status

**Status:** Frozen

**Frozen on:** 2026-08-06

**Maintenance policy:** No planned feature development. Consider only security issues, data-loss defects, or regressions that prevent the documented local workflow from starting.

## Why the project is frozen

PDF Reader reached a stable local-reader milestone, but the broader full-document translation space is already well served by PDFMathTranslate-next, its WebUI and desktop distribution, and mature Zotero plugins. Further investment in translation providers, whole-document controls, or Zotero parity would duplicate that ecosystem.

The repository is preserved as a functional local tool and as a record of the dual-column reading, translation lifecycle, glossary, progress streaming, and large-document loading work.

## Current architecture

- `app.py` creates the Flask application and the single local `AppState`.
- `routes.py` exposes document, page rendering, translation, progress, and stage endpoints.
- `state.py` owns the open source/translated documents, cache paths, translated-page state, rendering locks, and reading progress.
- `translation_orchestrator.py` bridges the synchronous PDF translation pipeline to the SSE event stream.
- `sse_stream.py` emits translation stages, progress, errors, and completion events.
- `translation_lifecycle.py` persists translated pages, merges glossary output, and cleans temporary resources.
- `translation_settings.py` and `engine_resolver.py` map the unified model configuration to pdf2zh-next settings.
- `static/app.js` coordinates the reader UI, page loading, translation controls, zoom, and progress persistence.
- `static/modules/` contains the alignment, lazy-loading, SSE, translation, stage-label, and zoom modules.

## Known limitations

- The Flask process owns one global document state. The application is designed for one local user and one open document, not concurrent or hosted use.
- Pages are rendered as PNG images. There is no selectable text layer, document search, copy, highlighting, annotations, outline navigation, or link interaction.
- Replacing translated pages rewrites and reopens `right.pdf`; repeated page-by-page translation of large files can produce substantial disk I/O.
- Translation has no persistent job queue, pause, cancellation, per-page retry queue, or restartable background task state.
- Setup requires Python, local configuration, an API key, and a local file-system path.
- Historical Node diagnostic scripts outside the supported `npm test` suite may intentionally fail or target older source shapes. See `tests/README.md`.

## Dependency and license reminder

PDF translation is provided by the upstream `pdf2zh-next` package from PDFMathTranslate-next, which is distributed under AGPL-3.0. The repository metadata currently states ISC. Before redistributing the application, hosting it as a service, or changing its licensing model, review the upstream license and the combined distribution with qualified advice. This note records a risk and is not a legal conclusion.

## How to verify the frozen baseline

From PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

## If development resumes

Start with user validation, not another translation-provider integration. The recommended product experiment is a PDF.js text layer supporting selection, search, contextual paragraph translation, and persistent bilingual notes while retaining PDFMathTranslate-next as optional full-page translation/export infrastructure.

Before implementation, reassess upstream capabilities, licensing, dependency compatibility, and whether real users repeatedly need the proposed workflow.
```

- [ ] **Step 2: Check the document for prohibited placeholders and scope drift**

Run:

```powershell
Select-String -Path docs/PROJECT_STATUS.md -Pattern 'TBD|TODO|待定|PLACEHOLDER'
git diff --check
```

Expected: `Select-String` prints nothing and `git diff --check` exits `0`.

- [ ] **Step 3: Commit the frozen-state record**

```powershell
git add -- docs/PROJECT_STATUS.md
git commit -m "docs: record frozen project status"
```

---

### Task 4: Replace the Corrupted README with a Frozen-Project Entry Point

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: verification command from Task 2 and `docs/PROJECT_STATUS.md` from Task 3.
- Produces: the repository's primary installation, operation, verification, and status guide.

- [ ] **Step 1: Replace `README.md` with concise UTF-8 documentation**

Use this complete structure and copy:

```markdown
# 双语 PDF 阅读器

> **项目状态：已冻结。** 当前版本保留为本地单用户工具，不再计划新增功能；仅考虑安全问题、数据损坏或无法启动等严重缺陷。背景、已知限制和恢复建议见 [项目状态](docs/PROJECT_STATUS.md)。

这是一个用于阅读英文教材和论文的本地双语 PDF 阅读器。左栏显示原文，右栏显示译文，支持在阅读过程中按页、按范围或全文调用大模型翻译。

PDF 版面翻译由 [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) / `pdf2zh-next` 提供。本项目主要负责本地阅读界面、按需翻译编排、双栏对齐、缓存和阅读状态。

## 当前功能

- 双栏连续滚动和双向页面对齐。
- 当前页、页码范围和全文翻译。
- SSE 翻译阶段与进度显示。
- 自定义翻译提示词。
- 按 PDF 隔离的累积术语表。
- 译文和阅读位置持久化。
- 大型 PDF 页面懒加载和卸载。
- Ctrl + 鼠标滚轮缩放。
- 多种 LLM 服务和 OpenAI 兼容接口。

## 已知边界

- 仅面向本机单用户、单文档使用，不适合直接部署为多用户服务。
- 页面以图片显示，不支持文本选择、搜索、复制、高亮、批注、目录或 PDF 内部链接。
- 没有翻译任务暂停、取消、持久队列或重启后续传。
- 使用前需要 Python 环境、模型 API Key 和本地 PDF 路径。

更多说明见 [项目状态](docs/PROJECT_STATUS.md)。

## 环境要求

- Windows 10 或更高版本。
- Python 3.12。
- Node.js 22（只在运行前端测试时需要）。
- 可用的 LLM API Key。

## 安装

```powershell
git clone <repository-url>
cd PDF_reader
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.lock
npm ci
Copy-Item config.example.toml config.toml
```

编辑 `config.toml` 中的 `[model]`，或者通过环境变量提供 API Key：

```powershell
$env:MODEL_API_KEY = 'your-api-key'
```

完整配置字段和模型示例见 `config.example.toml`。API Key 不应提交到 Git。

## 启动

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

然后打开 `http://127.0.0.1:5000`，输入本地 PDF 的绝对路径。

调试模式：

```powershell
python app.py --debug
```

## 验证

运行全部受支持的检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

单独运行前端回归测试：

```powershell
npm test
```

正式测试与历史诊断脚本的区别见 [测试说明](tests/README.md)。

## 核心结构

```text
app.py                         Flask 应用入口
routes.py                      HTTP 与 SSE 路由
state.py                       当前文档、缓存和阅读状态
translation_orchestrator.py    翻译线程与事件桥接
sse_stream.py                  翻译进度事件
translation_lifecycle.py       译文持久化与资源清理
translation_settings.py        pdf2zh-next 参数组装
static/app.js                  阅读器前端入口
static/modules/                对齐、懒加载、缩放和翻译模块
tests/                         Python 与前端测试
```

## 授权提醒

本项目依赖采用 AGPL-3.0 的 PDFMathTranslate-next / `pdf2zh-next`。重新分发、在线部署或调整许可证前，请先核对上游许可要求。该提醒不构成法律意见。
```

- [ ] **Step 2: Check links, placeholders, formatting, and accidental secrets**

Run:

```powershell
Select-String -Path README.md -Pattern 'TBD|TODO|待定|sk-[A-Za-z0-9]'
git diff --check
```

Expected: `Select-String` prints nothing and `git diff --check` exits `0`.

- [ ] **Step 3: Run the complete documented verification command**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Expected: exit `0` and final line `All verification checks passed.`

- [ ] **Step 4: Commit the README replacement**

```powershell
git add -- README.md
git commit -m "docs: finalize frozen project guide"
```

---

### Task 5: Final Freeze Audit

**Files:**
- Verify only; modify a previously listed file only if an audit identifies a freeze-blocking defect.

**Interfaces:**
- Consumes: all outputs from Tasks 1–4.
- Produces: evidence that the frozen baseline is reproducible and contains no generated or secret files.

- [ ] **Step 1: Run the complete verification suite from a fresh shell**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Expected: Ruff lint passes, Ruff format check passes, all Python tests pass, all supported frontend tests pass, and the final line is `All verification checks passed.`

- [ ] **Step 2: Audit the exact change scope**

Run:

```powershell
git status --short
git log -5 --oneline
git diff HEAD~4..HEAD --check
git diff HEAD~4..HEAD --name-only
```

Expected changed implementation files:

```text
.github/workflows/ci.yml
README.md
docs/PROJECT_STATUS.md
package.json
scripts/verify.ps1
templates/index.html
tests/README.md
tests/run-ui-copy-tests.mjs
```

The existing design and plan documents may also appear in the recent commit range. No `config.toml`, API key, cache, log, generated PDF, `.pytest_cache`, or temporary file may be staged or untracked.

- [ ] **Step 3: Confirm the frozen-state wording is present at both entry points**

Run:

```powershell
Select-String -Path README.md,docs/PROJECT_STATUS.md -Pattern '已冻结|Frozen'
```

Expected: at least one match in each file.

- [ ] **Step 4: Record any environment-only warnings in the handoff, not the repository**

If verification emits PyMuPDF deprecation warnings but exits `0`, report them in the final handoff without changing dependencies. If verification fails, diagnose and repair only failures introduced by Tasks 1–4, rerun the complete suite, and commit the narrowly scoped correction.
