# Comet Design Handoff

- Change: extract-translation-service-layer
- Phase: design
- Mode: compact
- Context hash: d6eb45c7b63a5cac2eca5c61af6fa94f5f420e5d16327605358f2e3c46edf1db

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/extract-translation-service-layer/proposal.md

- Source: openspec/changes/extract-translation-service-layer/proposal.md
- Lines: 1-34
- SHA256: 029d9d062d2d3bc9f37cbb5da04446d0a07e5d534e6fbf7e794bbe59a215924b

```md
## Why

`routes.py:translate_page` 是 230 行巨函数，揉合 6 类职责：单页 PDF 抽取、翻译编排（asyncio 线程 + 事件队列）、SSE 流生成、调试追踪日志、术语表合并、临时目录清理。路由层本应薄，现在却承担业务编排。这导致难以测试、难以扩展（换翻译引擎或改流式协议需动路由）、难以阅读。

## What Changes

- 从 `translate_page` 抽出独立的 service 层模块，各司其职：
  - `pdf_extraction`：从原 PDF 抽取单页为临时 PDF
  - `translation_orchestrator`：封装 `do_translate_async_stream` 的 asyncio 线程 + 事件队列，对外暴露同步迭代器
  - `sse_stream`：将翻译事件转换为 SSE 格式字符串
  - `glossary_service`：累积术语表路径解析与合并（从 routes 内联逻辑抽出）
  - `debug_trace`：调试追踪日志（从 routes 内联 `if config.DEBUG` 抽出，见变更 D 协同）
- `translate_page` 路由变薄（目标 ≤ 40 行）：仅做请求解析、参数校验、调用 service、返回 SSE Response
- SSE 事件契约（事件类型、字段、stage 标签）保持不变，前端无需改动
- 现有测试保持通过；为每个新 service 模块补单元测试

## Capabilities

### New Capabilities

- `translation-service-layer`: 翻译编排服务层——将单页翻译的 PDF 抽取、引擎编排、SSE 流、术语合并、调试追踪拆为独立可测试的 service 模块，路由层仅做协调

### Modified Capabilities

- `page-translation`: 路由层职责变更——`/api/translate/<page>` 的实现 SHALL 委托给 service 层，路由函数 SHALL ≤ 40 行且不包含业务编排逻辑；SSE 事件契约不变
- `code-quality-foundations`: "模块化源码组织"需求扩展——新增 service 层模块划分要求

## Impact

- **代码**：`routes.py`（`translate_page` 大幅瘦身）、新增 `services/` 或同级 service 模块文件
- **API**：`/api/translate/<page>` 的 SSE 事件流字节级兼容，前端无感
- **依赖**：依赖变更 A 完成的并发修复（先修正确再拆结构）
- **测试**：新增各 service 模块单元测试；现有路由测试通过 mock service 验证契约
- **风险**：拆分需保证 SSE 事件顺序与字段完全一致；asyncio 线程边界处理不当会丢事件
```

## openspec/changes/extract-translation-service-layer/design.md

- Source: openspec/changes/extract-translation-service-layer/design.md
- Lines: 1-64
- SHA256: 502d660101d3e1816f7e62c40d6957b20bac505770eba1f6401370df50dc1609

```md
## Context

`routes.py:translate_page`（102-334 行）当前承担：请求解析、单页 PDF 抽取（`pymupdf.open`+`insert_pdf`）、asyncio 线程编排（`new_event_loop`+`run_until_complete`+事件队列）、SSE 事件格式化、调试日志（`if config.DEBUG` 散落 20+ 处）、术语表路径解析与合并、临时目录清理。230 行单函数，6 类职责。

约束：保守边界——SSE 事件流的类型/字段/stage 标签字节级不变，`/api/*` 契约不变；依赖变更 A 先修复并发竞态（避免在带病代码上拆结构）。

## Goals / Non-Goals

**Goals:**
- `translate_page` 路由函数 ≤ 40 行，仅做请求解析、校验、调用 service、返回 Response
- 每类职责独立模块，可独立单元测试
- SSE 事件流字节级兼容现状
- 现有测试全绿，新模块有测试

**Non-Goals:**
- 不改 SSE 事件类型/字段/stage 标签
- 不改前端
- 不改翻译引擎（pdf2zh-next 调用方式不变）
- 不改并发模型（仍单 asyncio 线程 per 请求，变更 A 已修竞态）

## Decisions

### 决策 1：service 层模块划分

**选择**：按职责拆为 5 个模块（可放 `services/` 包或顶层模块，倾向顶层保持与现有 `services.py` 一致风格）：
- `pdf_extraction.py`：`extract_single_page(src_doc, page_num) -> Path`（临时 PDF）
- `translation_orchestrator.py`：`run_translation(settings, pdf_path) -> Iterator[Event]`，封装 asyncio 线程 + 事件队列，对外暴露同步迭代器
- `sse_stream.py`：`format_sse_event(evt: dict) -> str`，纯函数，stage 标签映射在此
- `glossary_service.py`：`resolve_glossary_paths(state) -> list[str] | None`、`merge_after_translate(...)`（从 routes 内联抽出）
- `debug_trace.py`：见变更 D，此处路由仅调用 `debug_trace.log_step(...)` 而非内联 `if config.DEBUG`

**备选**：
- (a) 单个 `translation_service.py` 大类——职责仍耦合
- (b) 按 pdf2zh-next 概念分（layout/translate/generate）——与我们的路由关注点不对齐

**理由**：每模块单一职责，可独立 mock 测试；`sse_stream` 纯函数最易测；`translation_orchestrator` 隔离 asyncio 复杂性。

### 决策 2：路由层薄化目标

**选择**：`translate_page` 结构 = 解析请求 + 校验页码（变更 A 已加）+ 构建settings + `return Response(stream_with_context(sse_stream.generate(orchestrator.run(...))))`。SSE 生成器函数组合 service 调用，路由 ≤ 40 行。

**理由**：路由层只编排，不实现。

### 决策 3：SSE 字节级兼容

**选择**：`sse_stream.format_sse_event` 产出与现状完全一致的 `data: {json}\n\n` 字符串，stage 标签映射（`STAGE_LABELS`）从 routes.py 迁移到 `sse_stream.py`，前后端不重复定义（与变更 E 共享对齐）。

**备选**：改 SSE 协议为新格式——破坏前端，超保守边界。

### 决策 4：测试策略

**选择**：
- `sse_stream`：纯函数测试，给定事件 dict 断言输出字符串字节匹配现状
- `translation_orchestrator`：mock `do_translate_async_stream`，断言事件迭代器顺序与 `_done`/`error` 信号正确
- `pdf_extraction`：真实小 PDF，断言单页 PDF 页数=1
- `glossary_service`：路径解析与合并逻辑单元测试
- `translate_page` 路由：mock 各 service，断言 SSE 流与现状字节一致

## Risks / Trade-offs

- [拆分后 SSE 事件顺序错位] → `sse_stream` 字节级回归测试捕获
- [asyncio 线程边界事件丢失] → orchestrator 测试覆盖 `_done`/`error` 信号
- [模块过多增加导入复杂度] → 5 个模块属合理粒度，每个 < 100 行
- [与变更 D 耦合] → debug_trace 模块先建骨架，路由调用其接口，D 负责实现细节
```

## openspec/changes/extract-translation-service-layer/tasks.md

- Source: openspec/changes/extract-translation-service-layer/tasks.md
- Lines: 1-40
- SHA256: d19aafc42fd06222f50dede9cc2f6df853abefb78723567993a2e86b7eea3876

```md
## 1. SSE 字节级回归基线

- [ ] 1.1 在 `tests/test_sse_stream.py` 编写测试：捕获现状 `translate_page` SSE 输出（progress_start/update/finish/error 各类事件）的期望字节串作为黄金样本
- [ ] 1.2 运行确认基线测试在现状代码上通过（锁定契约）

## 2. 抽取 pdf_extraction service

- [ ] 2.1 创建 `pdf_extraction.py`，实现 `extract_single_page(src_doc, page_num) -> Path`，从 `translate_page` 内联逻辑迁移
- [ ] 2.2 在 `tests/test_pdf_extraction.py` 编写测试：小 PDF 抽取单页，断言产出 PDF 页数=1、内容匹配
- [ ] 2.3 运行新测试通过

## 3. 抽取 translation_orchestrator service

- [ ] 3.1 创建 `translation_orchestrator.py`，实现 `run_translation(settings, pdf_path) -> Iterator[dict]`，封装 asyncio 线程 + 事件队列 + `_done`/`error` 信号
- [ ] 3.2 在 `tests/test_translation_orchestrator.py` 编写测试：mock `do_translate_async_stream` 返回事件序列，断言迭代器顺序正确、error 信号传播、loop 正确关闭
- [ ] 3.3 运行新测试通过

## 4. 抽取 sse_stream service

- [ ] 4.1 创建 `sse_stream.py`，迁移 `STAGE_LABELS` 与 `format_sse_event(evt) -> str` 纯函数
- [ ] 4.2 在 `tests/test_sse_stream.py` 用步骤 1 的黄金样本验证新模块输出字节级一致
- [ ] 4.3 运行测试通过

## 5. 抽取 glossary_service

- [ ] 5.1 创建 `glossary_service.py`，迁移累积术语表路径解析与合并逻辑
- [ ] 5.2 在 `tests/test_glossary_service.py` 编写测试：路径解析（有/无累积文件）、合并调用委托 `glossary_merger`
- [ ] 5.3 运行测试通过

## 6. 重构 translate_page 路由

- [ ] 6.1 重写 `routes.py:translate_page` 为薄编排：解析请求 + 校验页码（变更A） + 调用 service + 返回 SSE Response
- [ ] 6.2 确认 `translate_page` 函数体 ≤ 40 行
- [ ] 6.3 更新 `tests/test_routes.py`：mock 各 service，断言 SSE 流字节级匹配黄金样本
- [ ] 6.4 运行 `pytest tests/test_routes.py -v` 全绿

## 7. 全量回归与 lint

- [ ] 7.1 运行 `pytest tests/ -v`，全部测试通过
- [ ] 7.2 运行 `ruff check`，零错误
```

## openspec/changes/extract-translation-service-layer/specs/code-quality-foundations/spec.md

- Source: openspec/changes/extract-translation-service-layer/specs/code-quality-foundations/spec.md
- Lines: 1-20
- SHA256: 13aad1366ee29571fff170d2c2da77b1749b6f948b3d7838750c8fb6ca81e227

```md
## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns: `config.py` (configuration), `routes.py` (HTTP routing, thin), `services.py` (pure helpers), and a translation service layer (`pdf_extraction`, `translation_orchestrator`, `sse_stream`, `glossary_service`, `debug_trace`) that isolates business orchestration from HTTP handling. `app.py` serves as the application entry point and factory.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: Route layer delegates to service layer

- **WHEN** a translation request is handled by the route function
- **THEN** the route SHALL delegate PDF extraction, translation orchestration, SSE formatting, glossary handling, and debug tracing to dedicated service modules, and SHALL NOT contain those concerns inline
```

## openspec/changes/extract-translation-service-layer/specs/page-translation/spec.md

- Source: openspec/changes/extract-translation-service-layer/specs/page-translation/spec.md
- Lines: 1-30
- SHA256: 21e5232e0938cdc1c3a3c0469136a7aa26087fe3abba7a152786f84d93563481

```md
## MODIFIED Requirements

### Requirement: Manual per-page translation trigger

The system SHALL allow the user to trigger translation of the currently visible page via a button in the floating toolbar. The `/api/translate/<page>` endpoint SHALL delegate to the translation service layer; the route function SHALL only parse the request, validate the page, compose services, and return the SSE Response.

#### Scenario: Translate untranslated page

- **WHEN** the user clicks "Translate" on a page that has not been translated
- **THEN** the system SHALL extract the page from the original PDF, send it to the translation engine, and replace the corresponding page in right.pdf with the translated output

#### Scenario: Re-translate already translated page

- **WHEN** the user clicks "Translate" on a page that has already been translated
- **THEN** the system SHALL re-translate the page, overwriting the previous translation in right.pdf

#### Scenario: Translation in progress

- **WHEN** a translation is in progress for a page
- **THEN** the translate button SHALL be disabled and display "Translating..." until completion

#### Scenario: Translation completion

- **WHEN** a page translation completes
- **THEN** the right-column image for that page SHALL refresh to show the translated content within 2 seconds

#### Scenario: SSE event stream byte-level compatibility

- **WHEN** the service layer formats SSE events
- **THEN** the event type, field names, stage labels, and `data: {json}\n\n` framing SHALL be byte-for-byte identical to the pre-refactor output, so the frontend requires no changes
```

## openspec/changes/extract-translation-service-layer/specs/translation-service-layer/spec.md

- Source: openspec/changes/extract-translation-service-layer/specs/translation-service-layer/spec.md
- Lines: 1-39
- SHA256: 0ed34963943c2801fe667f59500df947bf1524d9adf3f8b48821a7d0aa6d688d

```md
## ADDED Requirements

### Requirement: Translation service layer modularization

The system SHALL provide a translation service layer that separates the concerns currently embedded in the `translate_page` route function. The service layer SHALL consist of independently testable modules covering: single-page PDF extraction, translation engine orchestration (asyncio thread + event queue), SSE event formatting, glossary path resolution and merge, and debug trace logging hooks.

#### Scenario: Single-page PDF extraction service

- **WHEN** the translation flow needs a single-page PDF for page N
- **THEN** a dedicated extraction service SHALL produce a temporary PDF containing only page N from the source document, without the route function directly calling pymupdf

#### Scenario: Translation orchestration service

- **WHEN** the route triggers a translation
- **THEN** a translation orchestrator service SHALL run the asyncio translation stream in a background thread and expose a synchronous iterator of translation events, isolating asyncio complexity from the route layer

#### Scenario: SSE event formatting service

- **WHEN** translation events need to be streamed to the frontend
- **THEN** a dedicated SSE formatting module SHALL convert each event dict into the `data: {json}\n\n` wire format, byte-for-byte identical to the current output

#### Scenario: Glossary service

- **WHEN** a translation starts or finishes
- **THEN** a glossary service SHALL resolve cumulative glossary paths before translation and merge auto-extracted terms after translation, without inline logic in the route function

#### Scenario: Translation error propagation

- **WHEN** the translation engine raises an exception or yields an error event
- **THEN** the orchestrator SHALL propagate the error to the SSE stream as an error event, and the route SHALL NOT crash

### Requirement: Route function thinness

The `translate_page` route function SHALL be limited to request parsing, page validation, service composition, and returning the SSE Response. It SHALL NOT contain business orchestration logic such as pymupdf calls, asyncio loop management, or inline debug logging.

#### Scenario: Route function line count

- **WHEN** the `translate_page` function is measured
- **THEN** its body SHALL be at most 40 lines, excluding the SSE generator it composes from services
```

