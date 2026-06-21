# Comet Design Handoff

- Change: modularize-frontend
- Phase: design
- Mode: compact
- Context hash: c7d738938e41ccc4f9f4aa2876fae12242243406fd1fce6820ed76f9ed8fca42

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/modularize-frontend/proposal.md

- Source: openspec/changes/modularize-frontend/proposal.md
- Lines: 1-37
- SHA256: 124fe4be94974d373fef0679e4595c3ae35bf5cd46f175ae128ac24f7f766433

```md
## Why

`static/app.js` 是 335 行单文件，揉合 DOM 操作、SSE 流客户端、滚动同步、IntersectionObserver 懒加载、翻译状态管理 5 类职责。`STAGE_LABELS` 在 `routes.py:32` 和 `app.js:10` 各写一份，前后端重复维护易漂移。前端难以独立测试与扩展。

## What Changes

- 将 `app.js` 按职责拆为多个模块（ES Module 或 IIFE 命名空间，视现有加载方式而定）：
  - `dom.js`：DOM 元素引用与页面元素创建/加载/卸载
  - `sse-client.js`：SSE 流读取与事件解析
  - `scroll-sync.js`：左右栏滚动同步与当前页检测
  - `lazy-loader.js`：IntersectionObserver 懒加载逻辑
  - `translator.js`：翻译请求编排与进度 UI
  - `app.js`：入口，组合上述模块
- `STAGE_LABELS` 单一来源：后端 `sse_stream.py`（变更 B 已迁移）为权威，前端通过一个 `/api/stages` 端点或构建时生成 `stages.json` 获取，消除重复
- 前端交互行为（双栏、滚动、翻译、懒加载、进度）完全不变
- `index.html` 的 `<script>` 引用更新为新模块结构

## Capabilities

### New Capabilities

- `frontend-modular-architecture`: 前端模块化架构——将单文件 `app.js` 拆为按职责分离的模块，stage 标签单一来源消除前后端重复

### Modified Capabilities

- `dual-column-reading`: 滚动同步逻辑迁移至 `scroll-sync` 模块，行为不变
- `lazy-loading`: IntersectionObserver 逻辑迁移至 `lazy-loader` 模块，行为不变
- `page-translation`: SSE 客户端与翻译编排迁移至 `sse-client`/`translator` 模块，行为不变；stage 标签单一来源
- `code-quality-foundations`: 前端 JS 模块化需求扩展

## Impact

- **代码**：`static/app.js`（瘦身为入口）、新增 `static/*.js` 模块、`templates/index.html`（script 引用）
- **API**：可能新增 `GET /api/stages`（若选运行时获取 stage 标签）；或仅构建时生成静态文件，无新 API
- **前端 UX**：完全不变
- **测试**：前端无现有测试；考虑加最小模块单元测试或手动验证清单
- **风险**：ES Module 兼容性（需 `type="module"` 或 bundler）；stage 标签同步策略选择
```

## openspec/changes/modularize-frontend/design.md

- Source: openspec/changes/modularize-frontend/design.md
- Lines: 1-60
- SHA256: 9a62622d3708bf03d0cfb2c9006e7438cd95dcb04be60ce7edde85cbaacd2ff1

```md
## Context

`static/app.js` 335 行单文件，`<script src="/static/app.js" defer>` 加载（非 module）。5 类职责混杂：DOM 引用与元素创建、SSE 流读取、滚动同步、IntersectionObserver 懒加载、翻译编排与进度 UI。`STAGE_LABELS` 在 `routes.py:32` 与 `app.js:10` 各一份，前后端重复。

约束：前端 UX 完全不变；保守边界；无构建工具（项目无 bundler，原生 JS）；浏览器兼容性保持（ES Module 需 `type="module"`，现代浏览器支持，可接受）。

## Goals / Non-Goals

**Goals:**
- `app.js` 拆为按职责分离的模块，入口仅组合
- `STAGE_LABELS` 单一来源，前后端不重复
- 前端交互行为字节等价
- 无构建工具依赖（原生 ES Module）

**Non-Goals:**
- 不引入 bundler/框架
- 不改前端交互/样式
- 不改后端 API（除可选 stage 标签端点）

## Decisions

### 决策 1：ES Module 拆分

**选择**：`<script type="module" src="/static/app.js">`，`app.js` 作为入口 `import` 各模块：
- `static/modules/dom.js`：DOM 元素引用、`createPageEl`/`loadPageImage`/`unloadPageImage`
- `static/modules/sse-client.js`：`readSSEStream(response, onEvent)` 读取 SSE 流并回调
- `static/modules/scroll-sync.js`：`setupScrollSync`/`setupPageDetection`
- `static/modules/lazy-loader.js`：`setupIntersectionObserver`
- `static/modules/translator.js`：`translateCurrentPage` 编排，含进度 UI
- `static/modules/stages.js`：stage 标签获取与缓存
- `app.js`：入口，组合模块，绑定 open/translate 事件

**备选**：
- (a) IIFE 命名空间（window.pdfReader.xxx）——无需 module，但封装弱、依赖顺序
- (b) 引入 bundler——超保守边界，增加构建依赖

**理由**：ES Module 原生支持，封装清晰，现代浏览器兼容；`type="module"` 默认 defer。

### 决策 2：Stage 标签单一来源

**选择**：后端 `sse_stream.py`（变更 B 迁移后的权威）新增 `GET /api/stages` 端点返回 `STAGE_LABELS` JSON；前端 `stages.js` 启动时 fetch 并缓存，`translator.js` 用缓存值。消除 `app.js` 的硬编码副本。

**备选**：
- (a) 构建时生成 `static/stages.json`——需构建步骤，项目无构建工具
- (b) 前端仍硬编码但加测试防止漂移——未真正单一来源

**理由**：`/api/stages` 简单、零构建依赖、运行时权威；前端启动一次 fetch 开销可忽略。

### 决策 3：行为等价验证

**选择**：前端无现有测试；采用手动验证清单（双栏渲染、滚动同步、懒加载缓冲、翻译进度、错误显示、prompt 切换）逐项确认拆分前后行为一致。可选加最小模块单测（`sse-client` 的事件解析纯函数最易测）。

**理由**：引入完整前端测试框架超保守边界；手动清单覆盖关键路径。

## Risks / Trade-offs

- [`type="module"` CORS/路径] —— 同源静态资源无 CORS 问题；模块路径用相对 `/static/modules/`
- [stage fetch 失败] → `stages.js` fetch 失败时回退到内置最小副本并警告，保证翻译流程不阻断
- [模块拆分后加载顺序] → ES Module import 自动解析依赖，无需手动排序
- [无前端测试保护] → 手动验证清单 + `sse-client` 纯函数单测
```

## openspec/changes/modularize-frontend/tasks.md

- Source: openspec/changes/modularize-frontend/tasks.md
- Lines: 1-49
- SHA256: 4b7ec1693ac9afdf2573764e4275737f6c3d17195c52c7fbc36973b3c5262673

```md
## 1. 行为基线与手动验证清单

- [ ] 1.1 编写 `docs/manual-verification-checklist.md`：列出拆分前后需一致的行为（双栏渲染、滚动同步、独立右栏滚动、当前页检测、懒加载缓冲5页、卸载离屏、翻译进度各 stage、prompt 切换、错误显示、open 失败提示）
- [ ] 1.2 现状手动走一遍清单，记录预期行为作为对照基线

## 2. 新增后端 /api/stages 端点

- [ ] 2.1 在 `routes.py`（或变更B后的 `sse_stream.py`）新增 `GET /api/stages` 返回 `STAGE_LABELS` JSON
- [ ] 2.2 在 `tests/test_routes.py` 编写测试：`/api/stages` 返回正确 stage 标签映射
- [ ] 2.3 运行测试通过

## 3. 抽取 scroll-sync 模块

- [ ] 3.1 创建 `static/modules/scroll-sync.js`，迁移 `setupScrollSync`/`setupPageDetection`，ES Module export
- [ ] 3.2 手动验证清单：滚动同步、独立滚动、当前页指示器行为一致

## 4. 抽取 lazy-loader 模块

- [ ] 4.1 创建 `static/modules/lazy-loader.js`，迁移 `setupIntersectionObserver` 与 `loadPageImage`/`unloadPageImage` 的观察逻辑
- [ ] 4.2 手动验证清单：懒加载缓冲、卸载离屏、1000页性能一致

## 5. 抽取 dom 模块

- [ ] 5.1 创建 `static/modules/dom.js`，迁移 DOM 元素引用与 `createPageEl`/`calculatePlaceholderHeight`
- [ ] 5.2 手动验证清单：页面元素创建、占位符比例一致

## 6. 抽取 sse-client 模块

- [ ] 6.1 创建 `static/modules/sse-client.js`，实现 `readSSEStream(response, onEvent)` 迁移 SSE 读取与 `data: {json}\n\n` 解析
- [ ] 6.2 可选：编写 `tests/test_sse_client.py` 或 JS 纯函数测试验证事件解析

## 7. 抽取 stages 模块与 translator 模块

- [ ] 7.1 创建 `static/modules/stages.js`：启动时 fetch `/api/stages` 并缓存，fetch 失败回退内置最小副本
- [ ] 7.2 创建 `static/modules/translator.js`：迁移 `translateCurrentPage` 编排，用 `sse-client` 与 `stages` 模块
- [ ] 7.3 手动验证清单：翻译进度各 stage 标签、段落级进度、完成/错误显示一致

## 8. 重构 app.js 入口与 index.html

- [ ] 8.1 重写 `static/app.js` 为入口：import 各模块，绑定 open/translate/prompt 事件，组合调用
- [ ] 8.2 更新 `templates/index.html`：`<script type="module" src="/static/app.js">`
- [ ] 8.3 删除 `app.js` 中的 `STAGE_LABELS` 硬编码副本（已由 stages 模块提供）
- [ ] 8.4 完整手动验证清单走一遍，所有行为与基线一致

## 9. 全量回归与 lint

- [ ] 9.1 运行 `pytest tests/ -v`，全部后端测试通过
- [ ] 9.2 运行 `ruff check`，零错误
- [ ] 9.3 grep 确认 `STAGE_LABELS` 仅在后端单一来源（`sse_stream.py` 或 `routes.py`）定义，前端无硬编码
```

## openspec/changes/modularize-frontend/specs/code-quality-foundations/spec.md

- Source: openspec/changes/modularize-frontend/specs/code-quality-foundations/spec.md
- Lines: 1-15
- SHA256: 8896034a1c5aa23b72137024bc43507437e6095667056604459c78404f33d0d2

```md
## MODIFIED Requirements

### Requirement: Frontend JavaScript in separate file

The system's frontend JavaScript SHALL be organized into separately importable ES Module files by responsibility, loaded via `<script type="module" src="/static/app.js">` where `app.js` is the thin entry point composing the other modules. All functionality SHALL work identically to the pre-refactor single-file implementation.

#### Scenario: JavaScript loaded as ES modules

- **WHEN** the index page is loaded in a browser
- **THEN** the JavaScript SHALL be loaded as ES Modules starting from `static/app.js`, which imports responsibility-specific modules, and all functionality SHALL work identically

#### Scenario: Frontend network error handling

- **WHEN** an open PDF or translation request fails due to network error
- **THEN** the user SHALL see an error message indicating the failure, handled by the appropriate module
```

## openspec/changes/modularize-frontend/specs/dual-column-reading/spec.md

- Source: openspec/changes/modularize-frontend/specs/dual-column-reading/spec.md
- Lines: 1-43
- SHA256: 647972124c51ea96473867dc965f064bf93f15f59e662e07b8f8da7def525d7f

```md
## MODIFIED Requirements

### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization logic SHALL reside in a dedicated `scroll-sync` frontend module; behavior SHALL remain identical to the pre-refactor implementation.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Scroll synchronization

- **WHEN** the user scrolls the left column
- **THEN** the right column SHALL automatically scroll to match the left column's scroll position within 50ms

#### Scenario: Independent scroll

- **WHEN** the user scrolls the right column independently
- **THEN** the left column SHALL NOT be affected

### Requirement: Page-level image display

The system SHALL display each page as an individual image stacked vertically, creating a continuous scrollable reading experience.

#### Scenario: Continuous scroll through pages

- **WHEN** the user scrolls through the document
- **THEN** page images SHALL appear in sequential order without gaps, mimicking a continuous document view

### Requirement: Floating toolbar

The system SHALL provide a floating toolbar that remains visible during scrolling.

#### Scenario: Toolbar visibility

- **WHEN** the user scrolls through the document
- **THEN** a floating toolbar SHALL remain fixed at the bottom of the viewport, displaying the current page number and a translation trigger button

#### Scenario: Page indicator

- **WHEN** the user scrolls such that page N occupies more than 50% of the viewport
- **THEN** the toolbar SHALL display "Page N" as the current page, computed by the `scroll-sync` module's page detection
```

## openspec/changes/modularize-frontend/specs/frontend-modular-architecture/spec.md

- Source: openspec/changes/modularize-frontend/specs/frontend-modular-architecture/spec.md
- Lines: 1-34
- SHA256: 608969dfe9c67813188fa89df172d9b1e6f1842b511e0abe63b6acb101bc5fa5

```md
## ADDED Requirements

### Requirement: Frontend modular architecture

The system's frontend JavaScript SHALL be organized into separately importable ES Module files by responsibility, with `app.js` as the entry point that composes the modules. Modules SHALL cover: DOM manipulation, SSE stream reading, scroll synchronization, lazy loading, translation orchestration with progress UI, and stage label resolution.

#### Scenario: app.js is a thin entry point

- **WHEN** `app.js` is inspected
- **THEN** it SHALL primarily import and compose the other modules, binding open/translate events, and SHALL NOT contain inline implementations of scroll sync, lazy loading, SSE parsing, or DOM element creation

#### Scenario: Modules are separately importable

- **WHEN** a module file (e.g., `static/modules/scroll-sync.js`) is inspected
- **THEN** it SHALL export its functions via ES Module `export` and have no side effects on import beyond defining exports

### Requirement: Stage label single source of truth

The system SHALL maintain translation stage labels in a single source of truth on the backend. The frontend SHALL fetch stage labels from the backend at startup rather than maintaining a hardcoded duplicate, so frontend and backend stage labels cannot drift.

#### Scenario: Frontend fetches stage labels

- **WHEN** the frontend application initializes
- **THEN** it SHALL fetch stage labels from the backend and use them for progress display, instead of using a hardcoded local copy

#### Scenario: Stage label fetch failure fallback

- **WHEN** the stage label fetch fails
- **THEN** the frontend SHALL fall back to a minimal built-in copy and continue functioning, with translation progress still displayed

#### Scenario: Backend stage label endpoint

- **WHEN** the frontend requests stage labels
- **THEN** the backend SHALL expose them via a stable endpoint returning the current stage label mapping as JSON
```

## openspec/changes/modularize-frontend/specs/lazy-loading/spec.md

- Source: openspec/changes/modularize-frontend/specs/lazy-loading/spec.md
- Lines: 1-48
- SHA256: 798e0164e324a1c66f82649a8bd9ac08679aab83b9c770e161df279e5a5e523f

```md
## MODIFIED Requirements

### Requirement: Viewport-based image loading

The system SHALL load page images only when they enter or are near the browser viewport, deferring loading of off-screen pages. The IntersectionObserver logic SHALL reside in a dedicated `lazy-loader` frontend module; behavior SHALL remain identical to the pre-refactor implementation.

#### Scenario: Initial page load

- **WHEN** the dual-column view first renders
- **THEN** only page images within the viewport plus a buffer of 5 pages above and below SHALL be loaded

#### Scenario: Scroll reveals new pages

- **WHEN** the user scrolls such that a previously unloaded page enters the buffer zone
- **THEN** the system SHALL load that page's image within 200ms of entering the buffer

#### Scenario: Scroll-away unloading

- **WHEN** a page image scrolls more than 10 pages away from the viewport
- **THEN** the system MAY unload its image to free memory, replacing it with a placeholder

### Requirement: IntersectionObserver implementation

The system SHALL use the browser's IntersectionObserver API to detect which page elements are near the viewport, implemented in the `lazy-loader` module.

#### Scenario: Observer setup

- **WHEN** the dual-column view initializes
- **THEN** the `lazy-loader` module SHALL create an IntersectionObserver with rootMargin set to load pages within 5 page-heights of the viewport

#### Scenario: Placeholder dimensions

- **WHEN** a page image has not yet been loaded
- **THEN** the system SHALL display a placeholder element with the correct aspect ratio (based on the page dimensions) to maintain scroll position accuracy

### Requirement: Large PDF support

The system SHALL support PDF documents with up to 1000 pages without degrading browser performance.

#### Scenario: 1000-page document

- **WHEN** a 1000-page PDF is opened
- **THEN** the browser SHALL maintain scrolling at 30+ FPS and memory usage below 500 MB

#### Scenario: Memory management

- **WHEN** total loaded images exceed 50 pages
- **THEN** the system SHALL unload images furthest from the viewport to stay within memory limits
```

## openspec/changes/modularize-frontend/specs/page-translation/spec.md

- Source: openspec/changes/modularize-frontend/specs/page-translation/spec.md
- Lines: 1-59
- SHA256: 40eab446970a952647da34cbbe1c67eadd20dd0a077f4e7717284d2c40a01d28

```md
## MODIFIED Requirements

### Requirement: Manual per-page translation trigger

The system SHALL allow the user to trigger translation of the currently visible page via a button in the floating toolbar. Translation orchestration and progress UI SHALL reside in dedicated `translator` and `sse-client` frontend modules; behavior SHALL remain identical to the pre-refactor implementation. Stage labels SHALL be fetched from the backend single source of truth rather than hardcoded.

#### Scenario: Translate untranslated page

- **WHEN** the user clicks "Translate" on a page that has not been translated
- **THEN** the `translator` module SHALL request translation and the system SHALL replace the corresponding page in right.pdf with the translated output

#### Scenario: Re-translate already translated page

- **WHEN** the user clicks "Translate" on a page that has already been translated
- **THEN** the system SHALL re-translate the page, overwriting the previous translation in right.pdf

#### Scenario: Translation in progress

- **WHEN** a translation is in progress for a page
- **THEN** the translate button SHALL be disabled and display "Translating..." until completion

#### Scenario: Translation completion

- **WHEN** a page translation completes
- **THEN** the right-column image for that page SHALL refresh to show the translated content within 2 seconds

#### Scenario: SSE stream parsed by sse-client module

- **WHEN** the translation SSE stream is received
- **THEN** the `sse-client` module SHALL read and parse the `data: {json}\n\n` events and invoke the `translator` module's event handlers, identical to pre-refactor behavior

### Requirement: User-facing stage status display

The system SHALL display user-readable Chinese text describing the current translation stage in the progress bar area during translation, using stage labels fetched from the backend single source of truth.

#### Scenario: Layout analysis stage display

- **WHEN** the translation enters the layout_analysis stage
- **THEN** the progress bar area SHALL display the stage label fetched from the backend (e.g., "正在分析版面...") in Chinese

#### Scenario: Translating stage display

- **WHEN** the translation enters the translating stage
- **THEN** the progress bar area SHALL display the fetched stage label followed by paragraph-level progress if available (e.g., "正在翻译... 第3/8 段")

#### Scenario: Generating PDF stage display

- **WHEN** the translation completes text translation and begins generating the output PDF
- **THEN** the progress bar area SHALL display the fetched stage label (e.g., "正在生成译文...") in Chinese

#### Scenario: Translation complete display

- **WHEN** the translation finishes successfully
- **THEN** the progress bar area SHALL display the fetched completion label briefly before returning to its idle state

#### Scenario: Translation error display

- **WHEN** a translation error occurs
- **THEN** the progress bar area SHALL display the error information in red text
```

