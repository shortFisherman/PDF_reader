# Long-Term Documentation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable four-document project memory system that lets a new AI session recover the project’s intent, current implementation, and future decision space without mistaking history or a roadmap entry for implementation authority.

**Architecture:** Keep `README.md` as the entry point, place the evergreen intent/current-state/future-direction records at `docs/project.md`, `docs/architecture.md`, and `docs/roadmap.md`, and teach future agents how to resolve conflicts among them through `AGENTS.md`. Move superseded current-looking documents into `docs/archive/` without deleting their bodies, while retaining upstream PDF translation references at their established paths with explicit version scope.

**Tech Stack:** Markdown, one preserved HTML diagram, PowerShell validation, Git, CodeGraph, and the current Python 3.12 / Flask / PyMuPDF / pdf2zh-next / BabelDOC / native ES Modules repository as the architecture subject.

## Global Constraints

- Before executing Task 1, this plan must already be committed with the exact subject `docs: plan long-term documentation system`; that commit is the implementation baseline located by Task 9. Committing the plan belongs to the planning handoff, not to an implementation task.
- Tasks 1–3 are one continuous canonical-document tranche. Their first two local commits contain deliberate forward links to canonical paths created by the next task; do not publish, merge, or hand off between them, and do not proceed beyond Task 3 until its cross-document link check passes.
- Required execution commands are Git, PowerShell, `rg`, and `codegraph`. If `.codegraph/` exists but the `codegraph` command is unavailable, stop and report the environment problem instead of substituting legacy architecture documents.
- Treat `docs/superpowers/specs/2026-08-27-documentation-system-design.md` as the approved design source for this change.
- This is a documentation-only change. Do not modify product source, test logic, dependencies, package metadata, runtime configuration, cache data, or generated artifacts.
- Do not add a project-state banner or narrate earlier project-state transitions in the four evergreen documents.
- Keep the document contracts exact: README is the entry point; project records long-lived intent; architecture records current HEAD only; roadmap records future decision space and never grants implementation authority.
- Do not select Zotero integration, a PDF.js text layer, notes, annotations, export, a settings UI, a task queue, or any other undecided product direction for the user.
- Every roadmap item must use one allowed status: `候选`, `待讨论`, `已决定，尚未授权实施`, `已授权（授权见链接的独立变更）`, `暂缓`, `已否决`, or `已完成`.
- Preserve every source line of the five archived documents. Add a visible historical notice, but do not rewrite their historical claims to match the current system.
- Keep `docs/pdf2zh-next-development-guide.md`, `docs/reports/pdf2zh-internals-report.md`, and `docs/reports/babeldoc-vs-pdf2zh-next-report.md` at their current paths; add version-scope notices without rewriting their research bodies.
- Do not move `docs/superpowers/`, `docs/glossary.csv`, `docs/comet/`, `openspec/`, `CHANGELOG.md`, or `tests/README.md`.
- Do not edit the approved design specification or this implementation-plan file during execution; track progress through the agent plan/status mechanism so `docs/superpowers/` remains unchanged after the implementation baseline.
- Use CodeGraph before direct code search or file reading when verifying implementation facts for `docs/architecture.md`.
- When code/tests and `docs/architecture.md` disagree, code/tests win and architecture must be corrected in the same documentation change.
- Use `apply_patch` for content edits. Execute the five file moves individually with exact source and destination paths; do not use a recursive or wildcard move.
- Preserve the content of the existing CodeGraph, logging, and managed `<comet-ambient-resume>` sections in `AGENTS.md`.
- Do not expose `MODEL_API_KEY`, `config.toml` secrets, local PDF paths, cache contents, or log contents in documentation or command output.
- Run the complete repository verification command before the final documentation-system commit is accepted.

## File Structure

Create:

- `docs/project.md` — project purpose, target user, evergreen principles, product boundaries, upstream relationship, and durable project memory.
- `docs/architecture.md` — current implementation, flows, state, APIs, dependencies, verification baseline, constraints, and confirmed risks.
- `docs/roadmap.md` — candidate directions, open questions, dependencies, statuses, and decision records; explicitly non-authorizing.

Move and mark historical:

- `docs/archive/2026-08-06-project-status.md` — historical snapshot moved from `docs/PROJECT_STATUS.md`.
- `docs/archive/project-architecture.md` — historical architecture moved from `docs/project-architecture.md`.
- `docs/archive/module-interactions.md` — historical diagram source moved from `docs/module-interactions.md`.
- `docs/archive/module-flow.html` — historical rendered diagram moved from `docs/module-flow.html`.
- `docs/archive/manual-verification-checklist.md` — historical manual checklist moved from `docs/manual-verification-checklist.md`.

Modify:

- `README.md` — remove the old status material, preserve useful setup/operation content, and add the canonical document navigation.
- `AGENTS.md` — add the new documentation-system reading, precedence, reference, and update rules before the existing CodeGraph section.
- `docs/pdf2zh-next-development-guide.md` — add the exact research/current-version scope notice.
- `docs/reports/pdf2zh-internals-report.md` — mark the v1.9.x report as historical upstream research.
- `docs/reports/babeldoc-vs-pdf2zh-next-report.md` — distinguish analyzed versions from the project’s currently locked versions.
- `CHANGELOG.md` — add a 2026-08-27 documentation-system entry while retaining all existing history.

Keep unchanged and in place:

- `docs/glossary.csv`
- `docs/superpowers/`
- `docs/comet/`
- `openspec/`
- `tests/README.md`
- all product source, tests, dependency files, configuration templates, and runtime data

---

### Task 1: Create the Evergreen Project Memory

**Files:**

- Create: `docs/project.md`
- Reference: `docs/superpowers/specs/2026-08-27-documentation-system-design.md`
- Reference: `README.md`

**Interfaces:**

- Consumes: the user-approved purpose, principles, boundaries, and documentation governance from the design specification.
- Produces: the authoritative long-lived intent document consumed by README navigation and the `AGENTS.md` conflict rules in later tasks.

- [ ] **Step 1: Prove the canonical project-memory path does not already exist**

Run:

```powershell
$planBaseline = git log -1 --format=%H --grep='^docs: plan long-term documentation system$'
if (-not $planBaseline) { throw 'committed implementation-plan baseline not found' }
Test-Path -LiteralPath 'docs/project.md'
git status --short --branch
```

Expected: the plan-baseline hash is found; `Test-Path` prints `False`; the worktree contains no unrelated changes. If an execution worktree is needed, create it with the `using-git-worktrees` skill before continuing.

- [ ] **Step 2: Create `docs/project.md` with the approved contract and evergreen content**

Use `apply_patch` to create the file. Use this exact section order and retain the meaning of every paragraph and bullet below:

```markdown
# PDF Reader 项目记忆

> 本文档只记录项目为什么存在、长期意图、常青原则、产品边界和仍影响未来判断的项目记忆。当前实现以 [architecture.md](architecture.md) 为准；未来方向和开放问题见 [roadmap.md](roadmap.md)。

## 项目为什么存在

PDF Reader 为英文书籍、教材、论文和技术文献提供一个可控的本地双语 PDF 阅读环境。它把阅读、按需翻译、术语积累和阅读进度保存在用户掌控的工作流里，使用户不必把核心体验完全交给外部阅读器或固定插件。

项目的长期价值不是重复制造一个通用 PDF 翻译器，而是在成熟上游翻译能力之上，保留可定制的阅读界面、模型与提示词选择、翻译范围、术语策略、缓存和任务体验。

## 目标用户与核心场景

- 首要用户是项目所有者本人；当前产品边界是本机、单用户、一次打开一份文档。
- 核心材料是英文书籍、教材、论文和技术文献。
- 核心流程是打开本地 PDF，在双栏阅读中按当前页、页码范围或全文触发翻译，并持续复用译文、术语和阅读位置。
- 新能力是否值得加入，由它能否改善真实阅读流程决定，而不是由外部产品是否已有同类功能决定。

## 核心价值

- 用户可以控制模型服务、模型名称、API 接入方式和自定义提示词。
- 用户可以控制单页、范围或全文翻译，而不是被固定任务流程限制。
- 译文 PDF、累积术语表和阅读进度按文档保存在本地缓存中。
- 阅读界面、双栏对齐、懒加载、缩放和翻译反馈可以围绕个人需求继续定制。
- 成熟的 PDF 解析、字体和排版能力优先由上游承担，本项目把精力留给阅读体验和任务编排。

## 常青原则

1. **本地优先。** 文档路径、译文、术语和阅读状态默认保留在用户设备上。
2. **用户可控。** 模型、提示词、翻译范围、术语策略和产品方向由用户决定。
3. **数据安全优先。** 涉及文档错写、缓存污染、密钥泄露或状态损坏的风险高于便利性优化。
4. **事实可验证。** 当前实现以代码、测试和可复现命令为依据，不能用历史计划代替事实。
5. **复用成熟上游。** 不重复实现 pdf2zh-next/BabelDOC 已稳定提供的解析、翻译、字体和排版能力。
6. **密钥安全。** API Key 不进入 Git、日志、文档示例的真实值或面向前端的响应。
7. **路线图不授权实施。** 候选方向只有在用户明确确认并建立独立变更或实施计划后才能进入实现。
8. **历史不冒充现状。** 归档、旧设计和旧报告只用于追溯，不能覆盖当前代码和常青文档。
9. **文档是项目基础设施。** 重要变更必须同步维护对应常青文档，使新会话能够恢复准确上下文。

## 产品边界

当前产品明确服务本机、单用户、单文档阅读。它不是现成的多用户 Web 服务、云端文档平台、通用知识库或完整 PDF 编辑器。

尚未决定的集成、文本层、笔记、批注、导出、设置界面和任务管理方向不在本文档中提前确定。它们只能作为 `roadmap.md` 中的开放问题或候选方向存在。

## 与上游的关系

本项目负责 Flask 本地服务、阅读器界面、翻译任务编排、页面替换、双栏状态、缓存、术语和阅读进度。PDFMathTranslate-next / `pdf2zh-next` 及其底层 BabelDOC 负责 PDF 解析、翻译引擎适配、字体处理和版面重建。

涉及上游接口、事件协议、SettingsModel、Provider 或 BabelDOC 行为时，应额外阅读 [pdf2zh-next 开发参考](pdf2zh-next-development-guide.md) 以及 `docs/reports/` 中的两份研究报告，并按其版本适用范围重新核验当前依赖。

## 项目长期记忆

- 项目已经形成可工作的本地双栏阅读、单页/范围/全文翻译、术语累积和阅读位置保存闭环。
- 全页版面翻译继续复用 pdf2zh-next/BabelDOC；项目差异化来自可控、可定制的阅读与翻译工作流。
- 当前系统的可靠性边界和技术风险属于 `architecture.md`；可能的修复或产品演进属于 `roadmap.md`，两者不能混写。
- 只有用户明确确认，才能改变本文档中的长期意图、常青原则或产品边界。

## 文档与历史地图

- `README.md`：人和 AI 的项目入口、安装、启动、使用边界与文档导航。
- `docs/project.md`：本文件，记录长期意图与常青原则。
- `docs/architecture.md`：严格记录当前 HEAD 的实现。
- `docs/roadmap.md`：记录未来方向、依赖和决策状态，不构成实施授权。
- `CHANGELOG.md`：按时间记录已经发生的项目变更。
- `docs/archive/`：旧状态、旧架构、旧流程图和旧检查清单，只用于历史追溯。
- `docs/superpowers/`、`openspec/`、`docs/comet/`：工具生成或工作流管理的设计、计划、验证和变更记录；其中内容不自动成为当前事实或新授权。
- `docs/pdf2zh-next-development-guide.md` 与 `docs/reports/`：按标注版本阅读的上游研究资料。
```

Do not insert implementation module details, current bug lists, candidate product recommendations, or project-state narration into this file.

- [ ] **Step 3: Validate the project-memory contract**

Run:

```powershell
$projectDoc = Get-Content -Raw -LiteralPath 'docs/project.md'
$requiredHeadings = @(
    '## 项目为什么存在',
    '## 目标用户与核心场景',
    '## 核心价值',
    '## 常青原则',
    '## 产品边界',
    '## 与上游的关系',
    '## 项目长期记忆',
    '## 文档与历史地图'
)
$missingHeadings = @($requiredHeadings | Where-Object { -not $projectDoc.Contains($_) })
$unfinishedMarkers = @((('T' + 'BD')), (('T' + 'ODO')), (('待' + '补')), (('占' + '位')))
$foundMarkers = @($unfinishedMarkers | Where-Object { $projectDoc.Contains($_) })
if ($missingHeadings.Count -gt 0 -or $foundMarkers.Count -gt 0) {
    throw "project.md contract failed: missing=$($missingHeadings -join ',') markers=$($foundMarkers -join ',')"
}
$projectTrailing = @(Select-String -LiteralPath 'docs/project.md' -Pattern '[ \t]+$')
if ($projectTrailing.Count -gt 0) { throw "project.md trailing whitespace: $($projectTrailing.LineNumber -join ',')" }
git add -- docs/project.md
git diff --cached --check -- docs/project.md
```

Expected: no exception; `git diff --check` exits `0`.

- [ ] **Step 4: Commit the evergreen project memory**

```powershell
git commit -m "docs: add evergreen project memory"
```

---

### Task 2: Document the Current Implementation Architecture

**Files:**

- Create: `docs/architecture.md`
- Reference: `.codegraph/`
- Reference: `app.py`, `routes.py`, `state.py`, `config.py`, `engine_resolver.py`, `translation_settings.py`, `translation_orchestrator.py`, `sse_stream.py`, `translation_lifecycle.py`, `glossary_service.py`, `glossary_merger.py`, `logging_config.py`, and `debug_trace.py`
- Reference: `templates/index.html`, `static/app.js`, `static/modules/*.js`, `package.json`, `requirements.lock`, `.github/workflows/ci.yml`, `scripts/verify.ps1`, and `tests/`

**Interfaces:**

- Consumes: current CodeGraph output, current line-numbered source, dependency pins, supported test commands, and reproducible risk evidence.
- Produces: the sole current-system architecture document used by future implementation, debugging, review, and documentation updates.

- [ ] **Step 1: Establish a reproducible architecture baseline through CodeGraph**

Run these read-only queries before using direct search:

```powershell
codegraph explore "app.py create_app routes.py register_routes AppState open_pdf render_page save_reading_progress and all HTTP endpoints"
codegraph explore "translate_page translate_batch build_settings generate generate_batch run_translation finish_translation glossary merge and translated PDF replacement"
codegraph explore "static/app.js initialization imports translator sse-client lazy-loader alignment-controller scroll-sync zoom stages and DOM flow"
codegraph node routes.py
codegraph node state.py
codegraph node config.py
codegraph node static/app.js
```

Expected: every command exits `0` and returns current source symbols or a line-numbered file. If an expected symbol is absent, use `codegraph explore` with that exact file and symbol name; do not substitute the legacy `docs/project-architecture.md` as evidence.

- [ ] **Step 2: Capture machine-checkable versions, routes, providers, and test baseline**

Run:

```powershell
$architecturePython = if (Test-Path -LiteralPath '.\venv\Scripts\python.exe') { '.\venv\Scripts\python.exe' } else { 'python' }
& $architecturePython --version
Select-String -Path requirements.lock -Pattern '^Flask==|^PyMuPDF==|^pdf2zh-next==|^BabelDOC==|^-e '
& $architecturePython -c "import config; print(len(config.ENGINE_REGISTRY)); print(','.join(spec.provider for spec in config.ENGINE_REGISTRY))"
rg -n '^@bp\.route' routes.py
& $architecturePython -m pytest --collect-only -q
node -p "require('./package.json').scripts['test:frontend']"
git rev-parse --short HEAD
```

Expected evidence:

- Python reports 3.12.x.
- The lock reports Flask 3.1.3, PyMuPDF 1.25.2, pdf2zh-next 2.9.0, BabelDOC 0.6.2, and the existing editable machine-local path.
- Provider count is `10`, in this order: `deepseek,zhipu,siliconflow,aliyun,gemini,groq,grok,modelscope,openai,openai_compatible`.
- Route search returns nine route decorators.
- pytest reports 193 collected Python tests.
- the frontend command contains the four supported suites: UI copy, translator, zoom, and alignment controller.
- record the short Git hash as the code baseline; later documentation-only commits do not change implementation behavior.

- [ ] **Step 3: Reproduce the documented cross-document result-contamination risk in a temporary directory**

Run this isolated proof. It creates only temporary PDFs outside the repository and closes all PyMuPDF handles before cleanup:

```powershell
$architecturePython = if (Test-Path -LiteralPath '.\venv\Scripts\python.exe') { '.\venv\Scripts\python.exe' } else { 'python' }
@'
from pathlib import Path
from tempfile import TemporaryDirectory

import pymupdf

from file_hash import sha256
from state import AppState


def make_pdf(path: Path, label: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), label)
    doc.save(path)
    doc.close()


with TemporaryDirectory() as temp_dir:
    root = Path(temp_dir)
    source_a = root / "a.pdf"
    source_b = root / "b.pdf"
    translated_a = root / "translated-a.pdf"
    make_pdf(source_a, "SOURCE_A")
    make_pdf(source_b, "SOURCE_B")
    make_pdf(translated_a, "TRANSLATED_A")

    state = AppState(root / "cache")
    try:
        state.open_pdf(str(source_a), sha256)
        late_result_callback = lambda path: state.replace_page(path, 0)
        state.open_pdf(str(source_b), sha256)
        late_result_callback(str(translated_a))

        right_text = state.right_doc[0].get_text()
        assert state.pdf_path == str(source_b)
        assert "TRANSLATED_A" in right_text
        print("REPRODUCED: late result for A was written into B right.pdf")
    finally:
        state._close_docs()
'@ | & $architecturePython -B -
```

Expected: exit `0` and the single `REPRODUCED` line. This proves the current mutable-target behavior without implementing or authorizing a fix.

- [ ] **Step 4: Create the architecture shell, baseline, overview, stack, structure, and runtime model**

Use `apply_patch` to create `docs/architecture.md`. Use this exact section order:

```markdown
# PDF Reader 当前架构

> 本文档只描述当前 HEAD 已经实现的系统。代码和测试高于本文档；发现不一致时，必须在同一变更中修正文档。项目意图见 [project.md](project.md)，未来方向见 [roadmap.md](roadmap.md)。

## 核验基线
## 系统总览
## 技术栈与锁定版本
## 仓库结构与文件职责
## 运行时进程、线程、队列与锁
## 启动与 Flask 应用装配
## 配置加载与 Provider 映射
## 打开 PDF 与页面渲染
## 单页翻译链
## 范围与全文翻译链
## 状态、缓存与持久化
## 前端模块与浏览器状态
## HTTP 与 SSE 接口
## 日志与错误传播
## 测试、CI 与验证入口
## 当前技术约束与已确认风险
## 上游与历史参考
```

Create the full heading shell, then populate the baseline through runtime-model sections with the following exact current facts. Organize them into prose, tables, and numbered flows. Do not copy claims from the legacy architecture unless current CodeGraph/source evidence independently confirms them:

- In `核验基线`, record the verification date `2026-08-27`, the short code-baseline hash captured in Step 2, the CodeGraph/source commands used, the locked versions, the 193-test collection count, and the four supported frontend suites. State that later commits in this plan are documentation-only and do not change the recorded implementation baseline.

1. **System boundary and stack**
   - Python 3.12; Flask 3.1.3; PyMuPDF 1.25.2; pdf2zh-next 2.9.0; BabelDOC 0.6.2; browser-native ES Modules; Node.js is used only for frontend tests.
   - Flask serves one local browser application. PDF pages are sent as rendered PNG images; the browser has no PDF text layer.
   - `app.py:create_app()` sets up logging, creates one Flask app and one global `AppState`, imports `register_routes`, and registers the blueprint.
   - The repository-responsibility table must cover: `app.py` startup; `config.py` configuration/provider registry; `routes.py` HTTP/SSE endpoints; `state.py` document/cache state; `file_hash.py`; `pdf_renderer.py`; `pdf_extraction.py`; `engine_resolver.py`; `translation_settings.py`; `translation_orchestrator.py`; `sse_stream.py`; `translation_lifecycle.py`; `glossary_service.py`/`glossary_merger.py`; `logging_config.py`/`debug_trace.py`; `templates/index.html`; `static/app.js`; `static/modules/`; `tests/`; `scripts/verify.ps1`; and the documentation/history directories.

2. **Runtime ownership and concurrency**
   - One Flask process owns one global, mutable `AppState` for the currently open document.
   - `AppState` uses one non-reentrant `threading.Lock` around document open/render/extract/replace and progress writes.
   - Each translation request starts a daemon thread in `run_translation`; that thread owns a new asyncio event loop and forwards pdf2zh-next events through a `queue.Queue` to the synchronous SSE generator.
   - pdf2zh-next may run BabelDOC in a child process. The application itself does not own a persistent job queue, task registry, pause/cancel API, or restart-resume state.

- [ ] **Step 5: Write configuration, startup, open, and render sections**

Use `apply_patch` to populate the startup, configuration, and open/render sections with these facts:

3. **Configuration and providers**
   - `config.py` reads repository-root `config.toml`; only `MODEL_API_KEY` has an environment-variable override in the current implementation.
   - Missing `config.toml` becomes an empty configuration. Model/API-key validation is delayed until `resolve_engine()` is used for translation.
   - List all ten providers exactly as captured in Step 2. Unknown providers fall back to `openai_compatible` after required model/key validation.
   - `translation_settings.build_settings()` sets language, disables upstream translation cache, enables automatic glossary extraction, conditionally passes the custom prompt and glossary paths, and builds `SettingsModel` through the selected provider settings class.

4. **Open and render flow**
   - Browser `openPdf()` posts a local absolute path to `POST /api/open`.
   - The route validates file existence and calls `AppState.open_pdf()` with `sha256`.
   - State closes prior documents, hashes the source, creates `cache/<hash>/`, copies the source to `right.pdf` when absent, opens left and right PyMuPDF documents, records page size/count, and loads `reading_progress.json`.
   - The browser creates placeholders for both columns and obtains visible pages from `GET /api/page/<side>/<page>`; `AppState.render_page()` calls the renderer under the lock and returns PNG bytes.

- [ ] **Step 6: Write single-page, batch, state, cache, and persistence sections**

Use `apply_patch` to populate both translation flows and the state/persistence table with these facts:

5. **Single-page translation flow**
   - `POST /api/translate/<page>` validates the current document and zero-based page index, resolves the cumulative glossary, builds settings, and creates `GenerateContext` callbacks over the global state.
   - `generate()` creates a temporary extraction directory and cache-local output directory, extracts one source page, runs pdf2zh-next through `run_translation()`, maps upstream events to SSE, retains the finish result, and calls `finish_translation()`.
   - `finish_translation()` prefers `mono_pdf_path`, falls back to `dual_pdf_path`, invokes `AppState.replace_page()`, then merges the auto-extracted glossary into `cumulative_glossary.csv`.
   - `replace_page()` rewrites `right.pdf` through a temporary file, reopens the right document, and marks the page translated. Temporary extraction/output directories are removed in the generator’s `finally` block.

6. **Batch/full translation flow**
   - `POST /api/translate-batch` accepts one-based inclusive `from`/`to`, validates the range, converts it to zero-based `page_indices`, and builds upstream page selection for the extracted temporary PDF.
   - `generate_batch()` emits `batch_info`, translates one extracted multi-page PDF, replaces matching pages in `right.pdf`, merges the glossary once, and emits progress/finish SSE events.
   - Full translation is a browser action that calls the same batch endpoint with `1..pageCount`; there is no separate server endpoint.

7. **State and persistence table**
   - `cache/<hash>/right.pdf`: persistent translated working copy.
   - `cache/<hash>/cumulative_glossary.csv`: per-document accumulated glossary.
   - `cache/<hash>/reading_progress.json`: zero-based saved page, written through a temporary file and `os.replace`.
   - `logs/pdf_reader.log`: rotating application log configured by `logging_config.py`.
   - cache-local `debug_trace.log`: created for a debug session only when debug mode is enabled and a document cache path exists.
   - `docs/glossary.csv`: repository-level manual glossary loaded when non-empty; its exact path is hard-coded by `config.py` and must remain in place.

- [ ] **Step 7: Write frontend, API, logging, testing, and CI sections**

Use `apply_patch` to populate the browser, interface, logging, and verification sections with these facts:

8. **Frontend modules and state**
   - `static/app.js` is the browser entry and owns `pageCount`, dimensions, current page, translation busy flag, prompt visibility, timer, observer, settle gate, zoom instance, alignment controller, and progress cleanup.
   - `dom.js` maps DOM elements and creates page placeholders.
   - `lazy-loader.js` uses IntersectionObserver with the current two-page buffer and unloads images outside the ten-page retention distance.
   - `alignment-controller.js` is the sole current dual-column alignment owner, using `(pageIndex, intraPageOffsetPx)` and synchronizing horizontal scroll proportionally.
   - `scroll-sync.js` retains settle/page-detection helpers; its deprecated `setupScrollSync()` body is empty and is not the active alignment path.
   - `zoom.js` clamps zoom to 0.25–2.2 and informs the alignment controller after Ctrl-wheel or reset.
   - `translator.js`, `sse-client.js`, and `stages.js` own fetch/SSE parsing and stage labels. Client `isTranslating` prevents overlapping actions only inside one browser page; it is not a server lock.

9. **API table**
   - `GET /` — render `templates/index.html`.
   - `POST /api/open` — open a local PDF; returns page count, dimensions, hash, and saved page.
   - `POST /api/reading-progress` — persist the current zero-based page.
   - `GET /api/page/<side>/<page>` — render a left/right page PNG.
   - `GET /api/page-count/<side>` — return an open document’s page count.
   - `POST /api/translate/<page>` — stream one page’s translation events over SSE.
   - `POST /api/translate-batch` — stream a one-based inclusive range over SSE.
   - `GET /api/translated-pages` — return translated zero-based page indexes.
   - `GET /api/stages` — return stage-label mapping.
   - The blueprint-level 404 handler returns JSON and is not a tenth route.

10. **Logging and verification**
    - Record the current root/concern namespaces: `pdf_reader`, `pdf_reader.app`, `pdf_reader.state`, `pdf_reader.translate`, `pdf_reader.lifecycle`, `pdf_reader.glossary`, `pdf_reader.routes`, `pdf_reader.render`, `pdf_reader.extract`, `pdf_reader.engine`, and `pdf_reader.debug_trace`; also record the ERROR/WARNING/INFO/DEBUG policy from `AGENTS.md`.
    - State that page/batch association is embedded in messages and API keys must never be logged.
    - Record `scripts/verify.ps1` as the unified entry: Ruff lint, Ruff format check, 193 Python tests, then the four supported frontend suites from `package.json`.

- [ ] **Step 8: Write current constraints, confirmed risks, and reference boundaries**

Use `apply_patch` to finish the document with factual constraints/risks and source-boundary links:

11. **Current constraints and confirmed risks — facts only, no remedy proposals**
    - Single process/global state means the server is not isolated for multiple users or simultaneous documents.
    - A translation request’s replacement callback targets the mutable global `AppState`; opening document B while document A is still translating can apply A’s eventual result to B’s `right.pdf`. This behavior has been reproduced and is a data-integrity risk.
    - Disconnecting the SSE consumer does not provide a server cancellation contract for the upstream translation thread/process.
    - Server routes have no task identity or mutual exclusion; the browser busy flag cannot prevent another client/request from overlapping.
    - The cumulative glossary merge writes shared per-document state without an application-level translation-task isolation contract.
    - Replacement failure can occur after closing/replacing right-document resources, and there is no documented recovery transaction.
    - `requirements.lock` contains `-e d:\open-glm\project_glm\open-autoglm`, which is machine-specific and reduces fresh-install portability.
    - Pages are PNG-only: no text selection, search, copy, highlight, annotation, outline, internal links, or OCR pipeline.
    - No persistent task queue, pause, cancellation, retry queue, progress recovery, or translation resume after process restart exists.

12. **Reference boundaries**
    - Link current intent to `project.md`, future discussion to `roadmap.md`, upstream interface research to `pdf2zh-next-development-guide.md` and `reports/`, and historical system descriptions to `archive/`.
    - Explicitly state that archived and upstream-version-specific documents are supporting context, not current implementation authority.

Do not include repair designs, target architectures, priority recommendations, or statements that a candidate feature will be built.

- [ ] **Step 9: Validate architecture completeness and separation of concerns**

Run:

```powershell
$architectureDoc = Get-Content -Raw -LiteralPath 'docs/architecture.md'
$requiredArchitecture = @(
    '## 核验基线',
    '## 运行时进程、线程、队列与锁',
    '## 配置加载与 Provider 映射',
    '## 单页翻译链',
    '## 范围与全文翻译链',
    '## 状态、缓存与持久化',
    '## HTTP 与 SSE 接口',
    '## 当前技术约束与已确认风险',
    'POST /api/translate-batch',
    '193',
    'openai_compatible',
    'right.pdf',
    'cumulative_glossary.csv',
    'reading_progress.json',
    'd:\open-glm\project_glm\open-autoglm'
)
$missingArchitecture = @($requiredArchitecture | Where-Object { -not $architectureDoc.Contains($_) })
if ($missingArchitecture.Count -gt 0) {
    throw "architecture.md missing: $($missingArchitecture -join ', ')"
}
$expectedEndpoints = @(
    'GET /',
    'POST /api/open',
    'POST /api/reading-progress',
    'GET /api/page/<side>/<page>',
    'GET /api/page-count/<side>',
    'POST /api/translate/<page>',
    'POST /api/translate-batch',
    'GET /api/translated-pages',
    'GET /api/stages'
)
$missingEndpoints = @($expectedEndpoints | Where-Object { -not $architectureDoc.Contains($_) })
if ($missingEndpoints.Count -gt 0) { throw "architecture.md API table missing: $($missingEndpoints -join ',')" }
$architectureTrailing = @(Select-String -LiteralPath 'docs/architecture.md' -Pattern '[ \t]+$')
if ($architectureTrailing.Count -gt 0) { throw "architecture.md trailing whitespace: $($architectureTrailing.LineNumber -join ',')" }
git add -- docs/architecture.md
git diff --cached --check -- docs/architecture.md
```

Expected: no exception and no whitespace errors. Manually confirm that every risk paragraph describes a current fact and does not prescribe a fix.

- [ ] **Step 10: Commit the current architecture**

```powershell
git commit -m "docs: document current system architecture"
```

---

### Task 3: Create the Non-Authorizing Roadmap

**Files:**

- Create: `docs/roadmap.md`
- Reference: `docs/project.md`
- Reference: `docs/architecture.md`
- Reference: `docs/superpowers/specs/2026-08-27-documentation-system-design.md`

**Interfaces:**

- Consumes: evergreen project principles plus current constraints/risks, without converting either into permission to change code.
- Produces: a future-direction and dependency record used only for discussion, prioritization, and links to separately authorized changes.

- [ ] **Step 1: Prove the canonical roadmap path does not already exist**

Run:

```powershell
Test-Path -LiteralPath 'docs/roadmap.md'
```

Expected: `False`.

- [ ] **Step 2: Create `docs/roadmap.md` with an explicit authorization boundary**

Use `apply_patch` and this exact structure. The quoted warning must be the first content after the title:

```markdown
# PDF Reader 路线图

> 本文档记录候选方向、开放问题和依赖顺序，不是实施授权。任何方向只有在用户明确确认并建立独立变更或实施计划后，才能进入代码实现。

## 文档职责

本文档负责保存未来讨论空间：有哪些问题、可能有哪些方向、方向之间依赖什么、用户作出了什么决定。当前实现以 [architecture.md](architecture.md) 为准，长期原则以 [project.md](project.md) 为准。

路线条目本身不能授权修改代码、依赖、界面或数据格式。`已决定，尚未授权实施` 仍然不能开工；`已授权（授权见链接的独立变更）` 必须同时给出用户授权所在的独立规格、计划或变更链接。

## 状态定义

| 状态 | 含义 |
|---|---|
| `候选` | 已识别的可能方向，尚未进入用户取舍。 |
| `待讨论` | 需要用户补充目标、场景或优先级。 |
| `已决定，尚未授权实施` | 用户认可方向，但没有批准具体实施。 |
| `已授权（授权见链接的独立变更）` | 用户已在所链接的独立变更中授权实施。 |
| `暂缓` | 当前不推进，但保留再次讨论的可能。 |
| `已否决` | 用户明确决定不采用。 |
| `已完成` | 已授权变更已经实施并通过验收。 |

## 当前开放问题

| 问题 | 状态 | 作出决定前需要回答 |
|---|---|---|
| 下一阶段首先解决可靠性风险，还是先验证新的阅读体验？ | `待讨论` | 哪类问题最影响日常使用；可接受的试验范围是什么。 |
| 项目的主要入口继续保持独立本地阅读器，还是考虑与现有文献管理工具协作？ | `待讨论` | 用户真实使用频率、切换成本和希望保留的自定义能力。 |
| 全页版面翻译与局部/段落翻译应如何分工？ | `待讨论` | 主要材料类型、选择/搜索需求和输出保存方式。 |

## 基础可靠性候选工作

| 方向 | 状态 | 当前依据 | 依赖 |
|---|---|---|---|
| 为翻译结果绑定不可变的文档身份，避免跨文档写入 | `候选` | architecture 已记录可复现的跨文档结果污染风险 | 先建立独立问题规格和回归测试设计 |
| 明确服务端翻译任务身份、互斥和生命周期 | `候选` | 当前只有浏览器页内 busy 标志，服务端无任务隔离 | 先决定单任务还是队列模型 |
| 明确 SSE 断开、取消和上游进程清理语义 | `候选` | 当前没有服务端取消契约 | 依赖任务身份与生命周期决定 |
| 修复依赖锁的机器路径可移植性 | `候选` | 当前锁文件含本机可编辑安装路径 | 先确认依赖来源和重新锁定方式 |
| 强化术语合并和右侧 PDF 替换的一致性 | `候选` | 当前写入流程缺少任务隔离/恢复事务 | 依赖文档身份与任务模型 |

这些条目是问题地图，不是缺陷修复授权。

## 产品方向候选

| 方向 | 状态 | 需要验证的问题 | 主要依赖 |
|---|---|---|---|
| 与 Zotero 或其他文献管理工具协作 | `待讨论` | 需要插件、文件跳转、元数据同步还是更轻量的协作 | 先明确独立阅读器的核心角色 |
| 引入 PDF.js 文本层或其他可选择文本能力 | `待讨论` | 搜索、复制、段落定位和局部翻译是否高频 | 先验证渲染架构与版面对齐成本 |
| 双语笔记、批注与摘录 | `待讨论` | 笔记绑定页、坐标、文本还是文档版本 | 依赖稳定文本/位置身份模型 |
| 翻译或笔记导出 | `待讨论` | 目标格式、可追溯性和版面保真需求 | 依赖输出对象和笔记模型 |
| 设置界面 | `待讨论` | 哪些配置确实需要从 TOML/环境变量迁入 UI | 先明确密钥存储与配置边界 |
| 翻译队列、暂停、取消和重启续传 | `待讨论` | 任务粒度、持久化范围和失败恢复语义 | 依赖服务端任务身份与生命周期 |

本表不替用户选择方向，也不表达默认优先级。

## 方向之间的依赖关系

1. 数据完整性和文档身份是任何并发任务、多文档或外部集成的前置基础。
2. 服务端任务身份先于取消、队列、暂停和重启续传。
3. 稳定的文本或位置身份先于可持久化笔记、批注和精确摘录导出。
4. 独立阅读器的核心角色先于是否进行 Zotero 等外部集成的选择。
5. 用户场景验证先于大范围界面或架构迁移。

依赖顺序只说明决策和技术前置关系，不自动产生实施顺序。

## 已决定方向

目前没有由用户确认且等待独立授权实施的产品方向。

## 已否决或暂缓方向

目前没有由用户明确否决或暂缓的产品方向。

## 决策记录

目前没有需要记录的产品方向决定。文档治理变更记录在 `CHANGELOG.md`，不把它混入产品路线决定。

新增决定时必须记录日期、决定、状态和用户授权或讨论依据；没有授权链接时不得使用已授权状态。
```

Per the user-approved design, do not import the earlier project-state or maintenance-policy narrative into this evergreen roadmap. Those records remain discoverable through `docs/archive/`; their existence does not create a current product decision or implementation restriction.

- [ ] **Step 3: Validate roadmap status and authorization safety**

Run:

```powershell
$roadmapDoc = Get-Content -Raw -LiteralPath 'docs/roadmap.md'
if (-not $roadmapDoc.Contains('不是实施授权')) { throw 'roadmap disclaimer missing' }
$allowedStatuses = @(
    '候选',
    '待讨论',
    '已决定，尚未授权实施',
    '已授权（授权见链接的独立变更）',
    '暂缓',
    '已否决',
    '已完成'
)
$tableStatuses = [regex]::Matches($roadmapDoc, '`([^`]+)`') | ForEach-Object { $_.Groups[1].Value } | Where-Object { $_ -in $allowedStatuses }
if ($tableStatuses.Count -lt 7) { throw 'roadmap status definitions or entries are incomplete' }
$directionRows = @('Zotero', 'PDF.js', '双语笔记', '设置界面', '翻译队列')
$missingDirections = @($directionRows | Where-Object { -not $roadmapDoc.Contains($_) })
if ($missingDirections.Count -gt 0) { throw "roadmap open questions missing: $($missingDirections -join ', ')" }
$roadmapTrailing = @(Select-String -LiteralPath 'docs/roadmap.md' -Pattern '[ \t]+$')
if ($roadmapTrailing.Count -gt 0) { throw "roadmap.md trailing whitespace: $($roadmapTrailing.LineNumber -join ',')" }
$canonicalTargets = @('docs/project.md', 'docs/architecture.md', 'docs/roadmap.md')
$missingCanonicalTargets = @($canonicalTargets | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingCanonicalTargets.Count -gt 0) { throw "canonical target missing: $($missingCanonicalTargets -join ',')" }
git add -- docs/roadmap.md
git diff --cached --check -- docs/roadmap.md
```

Expected: no exception and no whitespace errors. Manually verify every product-direction row remains `待讨论` and no sentence instructs an agent to begin implementation.

- [ ] **Step 4: Commit the non-authorizing roadmap**

```powershell
git commit -m "docs: add non-authorizing project roadmap"
```

---

### Task 4: Refresh README as the Human and AI Entry Point

**Files:**

- Modify: `README.md`
- Reference: `docs/project.md`
- Reference: `docs/architecture.md`
- Reference: `docs/roadmap.md`
- Reference: `docs/pdf2zh-next-development-guide.md`
- Reference: `tests/README.md`

**Interfaces:**

- Consumes: the three canonical documents created in Tasks 1–3 and the existing, already aligned installation/start/verification guidance.
- Produces: a standalone project entry point with no legacy status link, plus valid navigation to all evergreen documents and the primary upstream development reference.

- [ ] **Step 1: Record the two obsolete README references and the content that must be retained**

Run:

```powershell
rg -n '项目状态|docs/PROJECT_STATUS\.md' README.md
rg -n '^## (当前功能|已知边界|环境要求|安装|启动|验证|核心结构|授权提醒)$' README.md
```

Expected: the first command identifies the current top status block and the second project-status link; the second command confirms the existing useful sections that must remain represented after editing.

- [ ] **Step 2: Restructure README without changing application claims**

Use `apply_patch` to edit `README.md` in this exact section order:

```markdown
# 双语 PDF 阅读器

[existing two-paragraph project/upstream summary, without a status banner]

## 当前功能
[retain the current nine capability bullets]

## 已知边界
[retain the current four boundary bullets]

## 文档导航

- [项目记忆](docs/project.md)：项目为什么存在、长期意图、常青原则和产品边界。
- [当前架构](docs/architecture.md)：当前 HEAD 的模块、数据流、API、状态、依赖、测试和技术约束。
- [路线图](docs/roadmap.md)：候选方向、开放问题、依赖和决策状态；不构成实施授权。
- [pdf2zh-next 开发参考](docs/pdf2zh-next-development-guide.md)：涉及上游接口、事件和配置时按版本范围阅读。

## 环境要求
[retain Windows 10+, Python 3.12, Node.js 22 for tests, and API-key requirements]

## 安装
[retain clone, virtualenv, activation, requirements.lock installation, and config copy commands]

## 配置
[move the existing config.toml / MODEL_API_KEY guidance here without changing its security warning]

## 启动
[retain normal and --debug launch commands]

## 验证
[retain npm ci, scripts/verify.ps1, npm test, and tests/README.md guidance]

## 核心结构
[retain the current concise tree]

详细模块职责、调用链和运行时状态见 [当前架构](docs/architecture.md)。

## 上游依赖与授权提醒
[retain the current AGPL-3.0 risk reminder and non-legal-advice wording]
```

Required edits:

- Delete the entire old project-status blockquote and the later `更多说明见 [项目状态](docs/PROJECT_STATUS.md)` sentence.
- Do not add a replacement project-state block or refer to earlier project-state transitions.
- Keep the existing product summary, capability list, boundaries, commands, API-key safety warning, test link, core tree, and upstream-license warning accurate.
- Split configuration into its own heading so installation and configuration are independently discoverable.
- Do not copy any candidate direction from roadmap into README.

- [ ] **Step 3: Validate active links, required sections, and absence of legacy status material**

Run:

```powershell
$readme = Get-Content -Raw -LiteralPath 'README.md'
$readmeHeadings = @('## 当前功能', '## 已知边界', '## 文档导航', '## 环境要求', '## 安装', '## 配置', '## 启动', '## 验证', '## 核心结构', '## 上游依赖与授权提醒')
$missingReadmeHeadings = @($readmeHeadings | Where-Object { -not $readme.Contains($_) })
$legacyReadmeText = @('docs/PROJECT_STATUS.md', '项目状态：已冻结', '恢复建议')
$foundLegacyReadmeText = @($legacyReadmeText | Where-Object { $readme.Contains($_) })
if ($missingReadmeHeadings.Count -gt 0 -or $foundLegacyReadmeText.Count -gt 0) {
    throw "README contract failed: missing=$($missingReadmeHeadings -join ',') legacy=$($foundLegacyReadmeText -join ',')"
}
$localTargets = @('docs/project.md', 'docs/architecture.md', 'docs/roadmap.md', 'docs/pdf2zh-next-development-guide.md', 'tests/README.md', 'config.example.toml', 'requirements.lock', 'scripts/verify.ps1')
$missingTargets = @($localTargets | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missingTargets.Count -gt 0) { throw "README local target missing: $($missingTargets -join ',')" }
git diff --check -- README.md
```

Expected: no exception and no whitespace errors.

- [ ] **Step 4: Commit the refreshed README before moving legacy targets**

```powershell
git add -- README.md
git commit -m "docs: refresh project entry point"
```

This commit must precede Task 6 so no committed state points at a removed `docs/PROJECT_STATUS.md` path.

---

### Task 5: Teach Future Agents the Documentation Governance Rules

**Files:**

- Modify: `AGENTS.md`
- Reference: `README.md`
- Reference: `docs/project.md`
- Reference: `docs/architecture.md`
- Reference: `docs/roadmap.md`
- Reference: the existing managed `<comet-ambient-resume>` block

**Interfaces:**

- Consumes: all four evergreen document paths and the existing Comet/CodeGraph/logging instructions.
- Produces: the mandatory entry, reading order, precedence, conditional-reference, and update-trigger rules applied by future AI sessions.

- [ ] **Step 1: Capture the current managed blocks from Git before editing**

Run:

```powershell
$agentsBefore = (git show 'HEAD:AGENTS.md') -join "`n"
$cometBefore = [regex]::Match($agentsBefore, '(?s)<comet-ambient-resume>.*?</comet-ambient-resume>').Value
$codeGraphBefore = [regex]::Match($agentsBefore, '(?s)<!-- CODEGRAPH_START -->.*?<!-- CODEGRAPH_END -->').Value
$loggingBefore = [regex]::Match($agentsBefore, '(?s)## 日志约定.*?(?=<comet-ambient-resume>)').Value
if (-not $cometBefore -or -not $codeGraphBefore -or -not $loggingBefore) { throw 'existing AGENTS sections not found in HEAD' }
```

Expected: no exception. No file is modified by this step.

- [ ] **Step 2: Insert the documentation-system section before CodeGraph**

Use `apply_patch` to insert this complete block at the very top of `AGENTS.md`, before `<!-- CODEGRAPH_START -->`. Do not edit inside the existing CodeGraph, logging, or Comet sections:

```markdown
## 项目文档系统

本仓库采用新构建的长期文档系统。四份常青文档是后续 AI 恢复项目上下文的首要入口；历史资料和工具产物只能作为补充证据。

### 启动顺序

如果当前请求符合下方 Comet Ambient Resume 的探测条件，先执行 `comet resume-probe`，再按本节读取项目文档。Comet 托管块中的显式调用、流程延续和其他例外继续优先适用。

### 必读规则

1. 任何项目任务先读 `README.md`，了解入口、能力、边界和验证方式。
2. 涉及项目目标、范围、原则或产品取舍时，读 `docs/project.md`。
3. 涉及代码、实现、调试、测试、依赖或技术判断时，读 `docs/architecture.md`。
4. 涉及未来计划、功能选择、优先级或路线状态时，读 `docs/roadmap.md`。

### 条件参考

涉及 PDF 翻译接口、事件协议、SettingsModel、Provider、BabelDOC 或上游版本时，额外读取：

- `docs/pdf2zh-next-development-guide.md` — pdf2zh-next 开发参考，按顶部版本适用范围核验。
- `docs/reports/pdf2zh-internals-report.md` — pdf2zh v1 历史内部报告，不代表当前 pdf2zh-next 实现。
- `docs/reports/babeldoc-vs-pdf2zh-next-report.md` — 指定版本的上游对比快照。

查历史时读取 `CHANGELOG.md`、`docs/superpowers/`、`openspec/changes/archive/` 和 `docs/archive/`，但不得把历史内容当成当前事实或授权。

### 冲突裁决

- 当前行为事实：代码和测试高于 `docs/architecture.md`；发现冲突时必须在同一变更中修正 architecture。
- 项目意图与原则：`docs/project.md` 高于 README、roadmap 和历史资料；AI 不得自行改变其中原则。
- 未来方向：`docs/roadmap.md` 只允许指导讨论和计划，不允许直接实施。
- 归档、CHANGELOG、旧设计、旧计划和验证报告只能用于追溯。
- 原则冲突或用户意图不明确时，必须询问用户，不能从历史资料推断授权。

### 更新触发条件

- 用户可见功能、安装、启动、配置或验证方式变化：更新 `README.md`。
- 模块、API、数据流、状态、依赖、并发或运行边界变化：与代码同一变更更新 `docs/architecture.md`。
- 项目目的、长期意图、常青原则或产品边界变化：只有用户明确确认后更新 `docs/project.md`。
- 未来方向、优先级或路线状态变化：更新 `docs/roadmap.md`，但不得自动实施。
- pdf2zh-next/BabelDOC 版本升级：复核三份上游参考资料的适用范围并更新版本说明。
```

- [ ] **Step 3: Prove that governance is present and managed blocks are unchanged**

Run:

```powershell
$agentsAfter = (Get-Content -LiteralPath 'AGENTS.md') -join "`n"
$requiredAgentRules = @('## 项目文档系统', '### 启动顺序', '### 必读规则', '### 条件参考', '### 冲突裁决', '### 更新触发条件', 'docs/project.md', 'docs/architecture.md', 'docs/roadmap.md', '不允许直接实施')
$missingAgentRules = @($requiredAgentRules | Where-Object { -not $agentsAfter.Contains($_) })
if ($missingAgentRules.Count -gt 0) { throw "AGENTS governance missing: $($missingAgentRules -join ',')" }
$agentsBefore = (git show 'HEAD:AGENTS.md') -join "`n"
$cometBefore = [regex]::Match($agentsBefore, '(?s)<comet-ambient-resume>.*?</comet-ambient-resume>').Value
$codeGraphBefore = [regex]::Match($agentsBefore, '(?s)<!-- CODEGRAPH_START -->.*?<!-- CODEGRAPH_END -->').Value
$loggingBefore = [regex]::Match($agentsBefore, '(?s)## 日志约定.*?(?=<comet-ambient-resume>)').Value
$cometAfter = [regex]::Match($agentsAfter, '(?s)<comet-ambient-resume>.*?</comet-ambient-resume>').Value
$codeGraphAfter = [regex]::Match($agentsAfter, '(?s)<!-- CODEGRAPH_START -->.*?<!-- CODEGRAPH_END -->').Value
$loggingAfter = [regex]::Match($agentsAfter, '(?s)## 日志约定.*?(?=<comet-ambient-resume>)').Value
if ($cometBefore -cne $cometAfter) { throw 'managed Comet block changed' }
if ($codeGraphBefore -cne $codeGraphAfter) { throw 'managed CodeGraph block changed' }
if ($loggingBefore -cne $loggingAfter) { throw 'existing logging section changed' }
git diff --check -- AGENTS.md
```

Expected: no exception; only the new top section appears in `git diff -- AGENTS.md`.

- [ ] **Step 4: Commit the agent governance rules**

```powershell
git add -- AGENTS.md
git commit -m "docs: add project documentation governance"
```

---

### Task 6: Archive Superseded Current-Looking Documents

**Files:**

- Move: `docs/PROJECT_STATUS.md` → `docs/archive/2026-08-06-project-status.md`
- Move: `docs/project-architecture.md` → `docs/archive/project-architecture.md`
- Move: `docs/module-interactions.md` → `docs/archive/module-interactions.md`
- Move: `docs/module-flow.html` → `docs/archive/module-flow.html`
- Move: `docs/manual-verification-checklist.md` → `docs/archive/manual-verification-checklist.md`
- Modify after move: all five destination files, historical notice only

**Interfaces:**

- Consumes: the five legacy documents, the canonical project/architecture/roadmap files created in Tasks 1–3, and the active links already switched by Tasks 4–5.
- Produces: a clearly marked historical archive whose original source lines remain intact and whose new navigation points back to current documents.

- [ ] **Step 1: Verify exact sources, destinations, and canonical replacements**

Run:

```powershell
$archiveSources = @(
    'docs/PROJECT_STATUS.md',
    'docs/project-architecture.md',
    'docs/module-interactions.md',
    'docs/module-flow.html',
    'docs/manual-verification-checklist.md'
)
$canonicalDocs = @('docs/project.md', 'docs/architecture.md', 'docs/roadmap.md')
$missingSources = @($archiveSources | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
$missingCanonical = @($canonicalDocs | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingSources.Count -gt 0 -or $missingCanonical.Count -gt 0) {
    throw "archive precondition failed: source=$($missingSources -join ',') canonical=$($missingCanonical -join ',')"
}
if (Select-String -Path README.md,AGENTS.md,docs/project.md,docs/architecture.md,docs/roadmap.md -Pattern 'docs/PROJECT_STATUS.md') {
    throw 'active documentation still links the legacy project-status path'
}
```

Expected: no exception.

- [ ] **Step 2: Create the archive directory and move each file individually**

Run these commands exactly; do not replace them with a wildcard or recursive move:

```powershell
New-Item -ItemType Directory -Path 'docs/archive' -ErrorAction SilentlyContinue
git mv -- 'docs/PROJECT_STATUS.md' 'docs/archive/2026-08-06-project-status.md'
git mv -- 'docs/project-architecture.md' 'docs/archive/project-architecture.md'
git mv -- 'docs/module-interactions.md' 'docs/archive/module-interactions.md'
git mv -- 'docs/module-flow.html' 'docs/archive/module-flow.html'
git mv -- 'docs/manual-verification-checklist.md' 'docs/archive/manual-verification-checklist.md'
```

Expected: all five `git mv` commands exit `0`; old paths disappear and destination paths exist.

- [ ] **Step 3: Add a bounded historical notice to each Markdown archive**

Use `apply_patch` to insert this block immediately after the first H1 in each of the four Markdown destinations. Do not alter any existing source line:

```markdown
<!-- HISTORICAL_DOCUMENT_START -->
> [!NOTE]
> **历史资料。** 本文保留的是当时的阶段记录，不代表当前项目目的、当前实现或实施授权。请以 [project](../project.md)、[architecture](../architecture.md) 和 [roadmap](../roadmap.md) 为准。
<!-- HISTORICAL_DOCUMENT_END -->
```

The four Markdown destinations are:

```text
docs/archive/2026-08-06-project-status.md
docs/archive/project-architecture.md
docs/archive/module-interactions.md
docs/archive/manual-verification-checklist.md
```

- [ ] **Step 4: Add a visible historical notice to the archived HTML diagram**

Use `apply_patch` to insert this exact block immediately after `<body>` in `docs/archive/module-flow.html`:

```html
<!-- HISTORICAL_DOCUMENT_START -->
<div style="margin:16px auto;max-width:1100px;padding:12px 16px;border:1px solid #b38b00;background:#fff8d8;color:#4a3a00;font-family:system-ui,sans-serif;line-height:1.5">
  <strong>历史资料。</strong>
  本图保留的是当时的模块理解，不代表当前实现或实施授权。当前信息请阅读
  <a href="../project.md">project</a>、
  <a href="../architecture.md">architecture</a> 和
  <a href="../roadmap.md">roadmap</a>。
</div>
<!-- HISTORICAL_DOCUMENT_END -->
```

Do not change the existing Mermaid CDN script or any existing diagram source.

- [ ] **Step 5: Prove that every original source line remains in order**

Run:

```powershell
$archiveMap = [ordered]@{
    'docs/PROJECT_STATUS.md' = 'docs/archive/2026-08-06-project-status.md'
    'docs/project-architecture.md' = 'docs/archive/project-architecture.md'
    'docs/module-interactions.md' = 'docs/archive/module-interactions.md'
    'docs/module-flow.html' = 'docs/archive/module-flow.html'
    'docs/manual-verification-checklist.md' = 'docs/archive/manual-verification-checklist.md'
}
foreach ($sourcePath in $archiveMap.Keys) {
    $sourceLines = @(git show "HEAD:$sourcePath")
    $archiveLines = @(Get-Content -LiteralPath $archiveMap[$sourcePath])
    $sourceIndex = 0
    foreach ($archiveLine in $archiveLines) {
        if ($sourceIndex -lt $sourceLines.Count -and $archiveLine -ceq $sourceLines[$sourceIndex]) {
            $sourceIndex++
        }
    }
    if ($sourceIndex -ne $sourceLines.Count) {
        throw "archived body changed or lost lines: $sourcePath"
    }
}
```

Expected: no exception. This check allows the bounded notice additions but proves that all original lines still appear in their original order.

- [ ] **Step 6: Validate archive links and path state**

Run:

```powershell
$oldPaths = @(
    'docs/PROJECT_STATUS.md',
    'docs/project-architecture.md',
    'docs/module-interactions.md',
    'docs/module-flow.html',
    'docs/manual-verification-checklist.md'
)
$newPaths = @(
    'docs/archive/2026-08-06-project-status.md',
    'docs/archive/project-architecture.md',
    'docs/archive/module-interactions.md',
    'docs/archive/module-flow.html',
    'docs/archive/manual-verification-checklist.md'
)
if (@($oldPaths | Where-Object { Test-Path -LiteralPath $_ }).Count -gt 0) { throw 'legacy active path remains' }
if (@($newPaths | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -gt 0) { throw 'archive destination missing' }
rg -n 'docs/(PROJECT_STATUS|project-architecture|module-interactions|module-flow|manual-verification-checklist)' README.md AGENTS.md docs/project.md docs/architecture.md docs/roadmap.md
git add -- docs/archive
git diff --cached --check
git diff --cached --summary
git diff --cached -M --
```

Expected: the active-link search prints no matches; the cached whitespace check exits `0`; the summary identifies five renames; the rename-aware cached diff shows only those moves plus bounded historical-notice insertions, with no removed historical body lines. The HTML’s only resource dependency remains its existing absolute Mermaid CDN URL, and all three new `../*.md` links resolve.

- [ ] **Step 7: Commit the historical archive**

```powershell
git commit -m "docs: archive superseded project records"
```

---

### Task 7: Add Version Scope to Upstream Research References

**Files:**

- Modify: `docs/pdf2zh-next-development-guide.md`
- Modify: `docs/reports/pdf2zh-internals-report.md`
- Modify: `docs/reports/babeldoc-vs-pdf2zh-next-report.md`
- Reference: `requirements.lock`

**Interfaces:**

- Consumes: each report’s analyzed versions and the project’s currently locked pdf2zh-next/BabelDOC versions.
- Produces: three retained, discoverable research documents that cannot reasonably be mistaken for current project architecture or current upstream API truth.

- [ ] **Step 1: Reconfirm analyzed and locked versions before editing**

Run:

```powershell
Select-String -Path requirements.lock -Pattern '^pdf2zh-next==|^BabelDOC=='
Get-Content -LiteralPath 'docs/pdf2zh-next-development-guide.md' -TotalCount 8
Get-Content -LiteralPath 'docs/reports/pdf2zh-internals-report.md' -TotalCount 8
Get-Content -LiteralPath 'docs/reports/babeldoc-vs-pdf2zh-next-report.md' -TotalCount 10
Get-Content -LiteralPath 'docs/reports/babeldoc-vs-pdf2zh-next-report.md' -Tail 5
```

Expected:

- current lock: pdf2zh-next 2.9.0 and BabelDOC 0.6.2;
- development guide: pdf2zh-next 2.8.2, dated 2026-06-19;
- internals report: legacy pdf2zh v1.9.x, dated 2026-06-18;
- comparison report: BabelDOC 0.6.3 and pdf2zh-next 2.8.2, dated 2026-06-18.

- [ ] **Step 2: Add the exact version-scope notice to the development guide**

Use `apply_patch` to insert this notice after the H1 in `docs/pdf2zh-next-development-guide.md`, before its existing source-description blockquote:

```markdown
> [!IMPORTANT]
> **版本适用范围。** 本文主体是 2026-06-19 对 pdf2zh-next 2.8.2 的源码研究快照；当前项目锁定 pdf2zh-next 2.9.0 和 BabelDOC 0.6.2。本文用于理解上游接口与内部机制，不是本项目当前架构的事实源。涉及集成改动时，必须同时核对 `requirements.lock`、当前安装源码和 [项目当前架构](architecture.md)。
```

Do not change the existing body, local source-path note, API examples, or footer.

- [ ] **Step 3: Mark the pdf2zh v1 report as historical upstream research**

Use `apply_patch` to insert this notice after the H1 in `docs/reports/pdf2zh-internals-report.md`:

```markdown
> [!IMPORTANT]
> **历史上游研究。** 本报告是 2026-06-18 对旧 PDFMathTranslate / pdf2zh v1.9.x 管道的源码分析，不是 pdf2zh-next 的当前接口说明。本项目当前锁定 pdf2zh-next 2.9.0 和 BabelDOC 0.6.2；本文只能用于理解历史设计，不能替代 [项目当前架构](../architecture.md)、当前依赖源码或当前测试。
```

Do not rename this file or rewrite its v1 descriptions to resemble pdf2zh-next.

- [ ] **Step 4: Mark the comparison report’s cross-version mismatch explicitly**

Use `apply_patch` to insert this notice after the H1 in `docs/reports/babeldoc-vs-pdf2zh-next-report.md`:

```markdown
> [!IMPORTANT]
> **版本对比快照。** 本报告生成于 2026-06-18，比较 BabelDOC 0.6.3 与 pdf2zh-next 2.8.2；报告中的 BabelDOC 版本高于本项目当前锁定的 BabelDOC 0.6.2，而 pdf2zh-next 版本低于当前锁定的 2.9.0。结论可能随版本变化，只能作为选型历史和上游研究参考；当前项目事实以 [architecture.md](../architecture.md)、`requirements.lock`、安装源码和测试为准。
```

Do not normalize the report’s original version statements; the notice must make the mismatch visible while preserving the research snapshot.

- [ ] **Step 5: Prove all original research lines remain in order and notices contain all version boundaries**

Run:

```powershell
$referenceFiles = @(
    'docs/pdf2zh-next-development-guide.md',
    'docs/reports/pdf2zh-internals-report.md',
    'docs/reports/babeldoc-vs-pdf2zh-next-report.md'
)
foreach ($referencePath in $referenceFiles) {
    $sourceLines = @(git show "HEAD:$referencePath")
    $currentLines = @(Get-Content -LiteralPath $referencePath)
    $sourceIndex = 0
    foreach ($currentLine in $currentLines) {
        if ($sourceIndex -lt $sourceLines.Count -and $currentLine -ceq $sourceLines[$sourceIndex]) {
            $sourceIndex++
        }
    }
    if ($sourceIndex -ne $sourceLines.Count) {
        throw "upstream research body changed: $referencePath"
    }
}
$guide = Get-Content -Raw -LiteralPath 'docs/pdf2zh-next-development-guide.md'
$v1Report = Get-Content -Raw -LiteralPath 'docs/reports/pdf2zh-internals-report.md'
$comparison = Get-Content -Raw -LiteralPath 'docs/reports/babeldoc-vs-pdf2zh-next-report.md'
if (-not ($guide.Contains('2.8.2') -and $guide.Contains('2.9.0') -and $guide.Contains('0.6.2'))) { throw 'guide version scope incomplete' }
if (-not ($v1Report.Contains('v1.9.x') -and $v1Report.Contains('不是 pdf2zh-next'))) { throw 'v1 report boundary incomplete' }
if (-not ($comparison.Contains('BabelDOC 0.6.3') -and $comparison.Contains('0.6.2') -and $comparison.Contains('pdf2zh-next 2.8.2') -and $comparison.Contains('2.9.0'))) { throw 'comparison version scope incomplete' }
git diff --check -- @referenceFiles
```

Expected: no exception and no whitespace errors.

- [ ] **Step 6: Commit the upstream version boundaries**

```powershell
git add -- docs/pdf2zh-next-development-guide.md docs/reports/pdf2zh-internals-report.md docs/reports/babeldoc-vs-pdf2zh-next-report.md
git commit -m "docs: scope upstream research by version"
```

---

### Task 8: Record the Documentation-System Change

**Files:**

- Modify: `CHANGELOG.md`
- Reference: all outputs from Tasks 1–7

**Interfaces:**

- Consumes: the actual final file set created, edited, and moved by the preceding tasks.
- Produces: a chronological record of the documentation-system change without rewriting prior history or claiming application behavior changed.

- [ ] **Step 1: Confirm all deliverables exist before writing the changelog entry**

Run:

```powershell
$documentationDeliverables = @(
    'docs/project.md',
    'docs/architecture.md',
    'docs/roadmap.md',
    'docs/archive/2026-08-06-project-status.md',
    'docs/archive/project-architecture.md',
    'docs/archive/module-interactions.md',
    'docs/archive/module-flow.html',
    'docs/archive/manual-verification-checklist.md'
)
$missingDeliverables = @($documentationDeliverables | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($missingDeliverables.Count -gt 0) { throw "changelog precondition missing: $($missingDeliverables -join ',')" }
```

Expected: no exception.

- [ ] **Step 2: Add the exact changelog entry without altering old entries**

Use `apply_patch` to insert this block after `# 更新日志` and before the 2026-06-29 entry:

```markdown
## 2026-08-27 — 长期文档系统

- 建立四份常青文档：README 作为项目入口，`docs/project.md` 保存长期意图，`docs/architecture.md` 记录当前实现，`docs/roadmap.md` 保存非授权的未来方向与依赖。
- 在 `AGENTS.md` 中加入文档阅读顺序、条件参考、冲突裁决和更新触发条件，使新 AI 会话能够恢复准确上下文。
- 将五份旧状态、旧架构、旧流程图和旧检查清单完整迁入 `docs/archive/`，并添加历史资料说明。
- 保留三份 PDF 翻译上游研究资料的原路径和正文，补充研究版本、当前锁定版本与适用范围。
- 本次变更只调整文档治理和资料组织，不改变应用行为、API、依赖、测试或运行时数据。

---
```

- [ ] **Step 3: Prove previous changelog history remains intact**

Run:

```powershell
$oldChangelogLines = @(git show 'HEAD:CHANGELOG.md')
$newChangelogLines = @(Get-Content -LiteralPath 'CHANGELOG.md')
$oldIndex = 0
foreach ($newLine in $newChangelogLines) {
    if ($oldIndex -lt $oldChangelogLines.Count -and $newLine -ceq $oldChangelogLines[$oldIndex]) {
        $oldIndex++
    }
}
if ($oldIndex -ne $oldChangelogLines.Count) { throw 'existing CHANGELOG history changed' }
$changelogTop = Get-Content -LiteralPath 'CHANGELOG.md' -TotalCount 18
if (-not (($changelogTop -join "`n").Contains('## 2026-08-27 — 长期文档系统'))) { throw 'new changelog entry is not at the top' }
git diff --check -- CHANGELOG.md
```

Expected: no exception and no whitespace errors.

- [ ] **Step 4: Commit the changelog entry**

```powershell
git add -- CHANGELOG.md
git commit -m "docs: record long-term documentation system"
```

---

### Task 9: Run the Integrated Documentation and Repository Acceptance Gate

**Files:**

- Verify only: every file listed in the File Structure section
- Modify: only a previously listed documentation file if this gate finds a defect introduced by Tasks 1–8; rerun the complete gate after any correction

**Interfaces:**

- Consumes: the eight independently committed documentation deliverables.
- Produces: evidence that document responsibilities, links, archives, protected paths, Git scope, and application behavior all satisfy the approved design.

- [ ] **Step 1: Resolve the implementation baseline and inspect the exact Git scope**

Run:

```powershell
$documentationBaseline = git log -1 --format=%H --grep='^docs: plan long-term documentation system$'
if (-not $documentationBaseline) { throw 'committed implementation-plan baseline not found' }
git diff --name-status $documentationBaseline HEAD
git diff --check $documentationBaseline HEAD
git status --short --branch
```

Expected:

- exactly three canonical Markdown files are added;
- exactly five old documents are represented as moves into `docs/archive/` with notice additions;
- `README.md`, `AGENTS.md`, `CHANGELOG.md`, and the three upstream research references are modified;
- no product source, tests, dependencies, configuration, cache, logs, PDFs, or generated files appear;
- the working tree is clean and Git reports no whitespace errors.

- [ ] **Step 2: Enforce the allowed path set and protected-path invariants**

Run:

```powershell
$documentationBaseline = git log -1 --format=%H --grep='^docs: plan long-term documentation system$'
$changedPaths = @(git diff --name-only $documentationBaseline HEAD)
$allowedPaths = @(
    'README.md',
    'AGENTS.md',
    'CHANGELOG.md',
    'docs/project.md',
    'docs/architecture.md',
    'docs/roadmap.md',
    'docs/PROJECT_STATUS.md',
    'docs/project-architecture.md',
    'docs/module-interactions.md',
    'docs/module-flow.html',
    'docs/manual-verification-checklist.md',
    'docs/archive/2026-08-06-project-status.md',
    'docs/archive/project-architecture.md',
    'docs/archive/module-interactions.md',
    'docs/archive/module-flow.html',
    'docs/archive/manual-verification-checklist.md',
    'docs/pdf2zh-next-development-guide.md',
    'docs/reports/pdf2zh-internals-report.md',
    'docs/reports/babeldoc-vs-pdf2zh-next-report.md'
)
$unexpectedPaths = @($changedPaths | Where-Object { $_ -notin $allowedPaths })
if ($unexpectedPaths.Count -gt 0) { throw "unexpected changed path: $($unexpectedPaths -join ',')" }
git diff --quiet $documentationBaseline HEAD -- docs/glossary.csv docs/superpowers docs/comet openspec tests/README.md requirements.lock requirements.txt package.json config.example.toml
if ($LASTEXITCODE -ne 0) { throw 'protected path changed after the implementation-plan baseline' }
```

Expected: no exception. The protected-path diff is empty.

- [ ] **Step 3: Validate canonical responsibilities and guard against incomplete or legacy active content**

Run:

```powershell
$activeDocs = @('README.md', 'docs/project.md', 'docs/architecture.md', 'docs/roadmap.md')
$unfinishedMarkers = @((('T' + 'BD')), (('T' + 'ODO')), (('待' + '补')), (('占' + '位')))
foreach ($activePath in $activeDocs) {
    $activeText = Get-Content -Raw -LiteralPath $activePath
    $foundMarkers = @($unfinishedMarkers | Where-Object { $activeText.Contains($_) })
    if ($foundMarkers.Count -gt 0) { throw "$activePath contains an unfinished marker" }
}
$combinedActive = ($activeDocs | ForEach-Object { Get-Content -Raw -LiteralPath $_ }) -join "`n"
$legacyActiveTerms = @('docs/PROJECT_STATUS.md', '项目状态：已冻结', '不再计划新增功能', '仅考虑安全问题', '解除冻结', '恢复评估')
$foundLegacyActiveTerms = @($legacyActiveTerms | Where-Object { $combinedActive.Contains($_) })
if ($foundLegacyActiveTerms.Count -gt 0) { throw "active docs contain legacy state material: $($foundLegacyActiveTerms -join ',')" }
if (-not (Get-Content -Raw -LiteralPath 'docs/project.md').Contains('## 常青原则')) { throw 'project responsibility missing' }
if (-not (Get-Content -Raw -LiteralPath 'docs/architecture.md').Contains('## 当前技术约束与已确认风险')) { throw 'architecture responsibility missing' }
if (-not (Get-Content -Raw -LiteralPath 'docs/roadmap.md').Contains('不是实施授权')) { throw 'roadmap authorization boundary missing' }
```

Expected: no exception.

- [ ] **Step 4: Resolve every local Markdown/HTML link in active and archived documents**

Run:

```powershell
$markdownDocs = @(
    'README.md',
    'docs/project.md',
    'docs/architecture.md',
    'docs/roadmap.md',
    'docs/archive/2026-08-06-project-status.md',
    'docs/archive/project-architecture.md',
    'docs/archive/module-interactions.md',
    'docs/archive/manual-verification-checklist.md',
    'docs/pdf2zh-next-development-guide.md',
    'docs/reports/pdf2zh-internals-report.md',
    'docs/reports/babeldoc-vs-pdf2zh-next-report.md'
)
$brokenLinks = @()
foreach ($markdownPath in $markdownDocs) {
    $markdownText = Get-Content -Raw -LiteralPath $markdownPath
    $markdownBase = Split-Path -Parent $markdownPath
    if (-not $markdownBase) { $markdownBase = '.' }
    foreach ($match in [regex]::Matches($markdownText, '\[[^\]]+\]\(([^)]+)\)')) {
        $target = $match.Groups[1].Value.Split('#')[0]
        if (-not $target -or $target -match '^(https?://|mailto:)') { continue }
        $resolvedTarget = Join-Path $markdownBase $target
        if (-not (Test-Path -LiteralPath $resolvedTarget)) { $brokenLinks += "$markdownPath -> $target" }
    }
}
$htmlText = Get-Content -Raw -LiteralPath 'docs/archive/module-flow.html'
if (-not $htmlText.Contains('<title>PDF_reader · 模块交互流程图</title>')) { throw 'archived HTML title changed' }
foreach ($match in [regex]::Matches($htmlText, 'href="([^"]+)"')) {
    $target = $match.Groups[1].Value
    if ($target -match '^https?://') { continue }
    $resolvedTarget = Join-Path 'docs/archive' $target
    if (-not (Test-Path -LiteralPath $resolvedTarget)) { $brokenLinks += "docs/archive/module-flow.html -> $target" }
}
$htmlSources = @([regex]::Matches($htmlText, 'src="([^"]+)"') | ForEach-Object { $_.Groups[1].Value })
if ($htmlSources.Count -ne 1 -or @($htmlSources | Where-Object { $_ -notmatch '^https://' }).Count -gt 0) {
    throw "archived HTML source boundary changed: $($htmlSources -join ',')"
}
if ($brokenLinks.Count -gt 0) { throw "broken local links: $($brokenLinks -join '; ')" }
```

Expected: no exception. The original title remains intact, and the Mermaid CDN remains the sole external `src` with no local resource dependency.

- [ ] **Step 5: Validate archive notices, upstream version scopes, AGENTS governance, and unchanged managed blocks**

Run:

```powershell
$archivePaths = @(
    'docs/archive/2026-08-06-project-status.md',
    'docs/archive/project-architecture.md',
    'docs/archive/module-interactions.md',
    'docs/archive/module-flow.html',
    'docs/archive/manual-verification-checklist.md'
)
foreach ($archivePath in $archivePaths) {
    $archiveText = Get-Content -Raw -LiteralPath $archivePath
    if (-not ($archiveText.Contains('HISTORICAL_DOCUMENT_START') -and $archiveText.Contains('HISTORICAL_DOCUMENT_END'))) {
        throw "historical notice missing: $archivePath"
    }
}
$agents = Get-Content -Raw -LiteralPath 'AGENTS.md'
$agentRules = @('## 项目文档系统', 'comet resume-probe', 'docs/project.md', 'docs/architecture.md', 'docs/roadmap.md', '不允许直接实施')
if (@($agentRules | Where-Object { -not $agents.Contains($_) }).Count -gt 0) { throw 'AGENTS documentation governance incomplete' }
$documentationBaseline = git log -1 --format=%H --grep='^docs: plan long-term documentation system$'
$agentsBefore = (git show "${documentationBaseline}:AGENTS.md") -join "`n"
$agentsAfter = (Get-Content -LiteralPath 'AGENTS.md') -join "`n"
$sectionPatterns = @(
    '(?s)<!-- CODEGRAPH_START -->.*?<!-- CODEGRAPH_END -->',
    '(?s)## 日志约定.*?(?=<comet-ambient-resume>)',
    '(?s)<comet-ambient-resume>.*?</comet-ambient-resume>'
)
foreach ($sectionPattern in $sectionPatterns) {
    $beforeSection = [regex]::Match($agentsBefore, $sectionPattern).Value
    $afterSection = [regex]::Match($agentsAfter, $sectionPattern).Value
    if (-not $beforeSection -or $beforeSection -cne $afterSection) { throw "existing AGENTS section changed: $sectionPattern" }
}
$guide = Get-Content -Raw -LiteralPath 'docs/pdf2zh-next-development-guide.md'
$v1Report = Get-Content -Raw -LiteralPath 'docs/reports/pdf2zh-internals-report.md'
$comparison = Get-Content -Raw -LiteralPath 'docs/reports/babeldoc-vs-pdf2zh-next-report.md'
if (-not ($guide.Contains('2.8.2') -and $guide.Contains('2.9.0') -and $guide.Contains('0.6.2'))) { throw 'development-guide version notice incomplete' }
if (-not ($v1Report.Contains('v1.9.x') -and $v1Report.Contains('不是 pdf2zh-next'))) { throw 'v1-report notice incomplete' }
if (-not ($comparison.Contains('BabelDOC 0.6.3') -and $comparison.Contains('BabelDOC 0.6.2') -and $comparison.Contains('pdf2zh-next 2.8.2') -and $comparison.Contains('2.9.0'))) { throw 'comparison-report version notice incomplete' }
```

Expected: no exception. The automated comparison confirms that the existing CodeGraph, logging, and Comet sections are unchanged apart from line displacement caused by the new top section.

- [ ] **Step 6: Run the complete supported repository verification**

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify.ps1
```

Expected: Ruff lint exits `0`, Ruff format check exits `0`, all 193 Python tests pass, all four supported frontend suites pass, and the script ends with `All verification checks passed.`

- [ ] **Step 7: Inspect the final commit sequence and clean worktree**

Run:

```powershell
git log -10 --oneline
git status --short --branch
```

Expected: eight task commits follow the committed implementation plan; the working tree is clean. If any acceptance step required a documentation correction, commit only the affected documentation path with a narrowly scoped `docs:` message, then rerun Steps 1–7 from the beginning.
