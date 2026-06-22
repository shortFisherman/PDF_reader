# Comet Design Handoff

- Change: refactor-module-cohesion
- Phase: design
- Mode: compact
- Context hash: b204295345b914eb2629204876575fbf07ab79fb30c3039a6c2a9a0ca9fb5be5

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/refactor-module-cohesion/proposal.md

- Source: openspec/changes/refactor-module-cohesion/proposal.md
- Lines: 1-34
- SHA256: 61e50e215d4c5ff0c2bf99f773e51580034fde00e4d1a305cad899868f176e15

```md
## Why

当前后端代码存在模块内聚性不足和接口耦合过大的问题：`services.py` 成了杂物堆（5 个互不相关的函数共用一个文件）、`sse_stream.py` 的 `generate()` 承担了翻译生命周期管理而非纯 SSE 格式化职责、`GenerateContext` 将整个 `AppState` 对象泄露给不需要全部接口的模块。这些问题在当前规模下勉强可控，但随着功能增长会逐渐失控。

## What Changes

- **拆分 `services.py`**：将 5 个函数按职责拆分到 3 个模块（文件哈希、引擎配置、PDF 渲染 + 设置构建）
- **抽取翻译生命周期模块**：从 `sse_stream.py` 的 `generate()` 中分离出翻译完成后的后处理逻辑（replace_page、merge_after_translate），`sse_stream.py` 回归纯 SSE 格式化职责
- **缩小接口依赖**：`GenerateContext` 不再传递整个 `AppState` 对象，改为传递翻译完成所需的最小接口或独立属性；`glossary_service.py` 不再依赖 `AppState` 类型，改为接收 `Path | None`
- **消除 `debug_trace.py` 重复代码**：`debug_session` 上下文管理器与 `setup_file_handler`/`cleanup_file_handler` 存在逻辑重复，合并为同一套实现

## Capabilities

### New Capabilities

- `translation-lifecycle`: 翻译完成后的持久化和术语合并逻辑，从 `sse_stream.py` 中独立出来
- `engine-config`: 引擎查找和配置映射逻辑，从 `services.py` 中独立出来
- `file-hash`: 文件 SHA256 哈希计算，从 `services.py` 中独立出来

### Modified Capabilities

- `translation-service-layer`: `services.py` 的边界重新划分，部分函数迁移到新模块
- `frontend-modular-architecture`: （无 spec 变更，仅后端内部重构）
- `translation-persistence`: 翻译持久化逻辑从 `sse_stream.py` 迁移到新模块，功能行为不变
- `terminology-management`: `glossary_service.py` 参数类型从 `AppState` 缩小为 `Path | None`
- `debug-trace-module`: 消除 `debug_session` 和 `setup_file_handler` 之间的代码重复

## Impact

- 受影响文件：`services.py`、`sse_stream.py`、`routes.py`、`translation_orchestrator.py`、`glossary_service.py`、`debug_trace.py`、`state.py`、`pdf_extraction.py`
- 新增文件：`translation_lifecycle.py`、`engine_resolver.py`、`file_hash.py`
- 所有 111 个现有测试预期无需逻辑修改（仅调整 import 路径）
- `ruff check` 零错误
- 不影响前端代码、不影响功能行为、不影响配置文件
```

## openspec/changes/refactor-module-cohesion/design.md

- Source: openspec/changes/refactor-module-cohesion/design.md
- Lines: 1-92
- SHA256: 2260a0a233f8ce980c705c8c48028f865542dc72b760d3365ffc5927d82f6666

[TRUNCATED]

```md
## Context

当前项目后端代码结构是在多次功能迭代中逐步形成的，缺乏一次系统性的模块边界整理。核心问题：

1. `services.py` 成为"杂物堆"——5 个互不相关的函数（SHA256、PDF 渲染、引擎查找、引擎参数映射、设置组装）共用一个文件
2. `sse_stream.py` 的 `generate()` 承担了翻译生命周期管理（replace_page、merge_after_translate、临时目录清理），已超出"SSE 格式化"的职责边界
3. `GenerateContext` 直接传递整个 `AppState` 对象，暴露了 `sse_stream.py` 不需要的全部接口
4. `glossary_service.py` 依赖 `AppState` 类型但实际只使用 `.glossary_cache_path` 属性
5. `debug_trace.py` 中 `debug_session` 上下文管理器和 `setup_file_handler`/`cleanup_file_handler` 存在重复的文件 handler 创建逻辑

**约束**：不修改功能行为、不修改前端、不修改测试逻辑（仅调整 import）、保持 ruff 零错误、保持 111 个测试全通过。

## Goals / Non-Goals

**Goals:**
- 每个 .py 文件有单一、明确的职责
- 模块间依赖最小化，不传递不需要的完整对象
- 新模块命名直观，见名知义
- 消除 debug_trace.py 内部重复

**Non-Goals:**
- 不改变任何功能行为
- 不修改 `config.py`、`config.toml`、`state.py`、`routes.py`、`translation_orchestrator.py`、`pdf_extraction.py` 的核心逻辑
- 不修改前端代码
- 不新增或删除测试用例（仅调整 import 路径）

## Decisions

### Decision 1: services.py 拆分为 3 个模块

**选择方案**：按函数职责拆分为 `file_hash.py`、`engine_resolver.py`、`pdf_renderer.py`

```
Before:  services.py (120 lines, 5 functions)
After:
  file_hash.py       ← sha256()
  engine_resolver.py  ← resolve_engine(), build_engine_kwargs(), CONFIG_ATTR_MAP
  pdf_renderer.py     ← render_page(), build_settings()
```

- `sha256()` 是纯文件操作，与翻译引擎或 PDF 无关，独立后可在任何地方复用
- `resolve_engine()` + `build_engine_kwargs()` + `CONFIG_ATTR_MAP` 三者紧密相关：引擎查找 → 参数映射 → 配置属性映射表，放一起是自然的
- `render_page()` 和 `build_settings()` 都依赖 pymupdf + pdf2zh-next 的 SettingsModel，虽然它们做的事不同，但 `build_settings` 是翻译流程的入口点，`render_page` 是渲染流程的入口点。拆为两个独立文件会让路由层 `from pdf_renderer import render_page, build_settings` 变成两行 import。权衡后保持在一起：它们共同构成"pdf2zh-next 相关操作的入口"。

**备选方案**：拆成 5 个单函数文件。过于碎片化，拒绝。

### Decision 2: 抽取翻译生命周期到 `translation_lifecycle.py`

**选择方案**：新建 `translation_lifecycle.py`，容纳翻译完成后的所有后处理逻辑

```python
# sse_stream.py (瘦身后):
def generate(ctx):       # 只负责: debug_session → run_translation → format_sse_event → yield
    for evt in run_translation(...):
        yield format_sse_event(evt)
    # 翻译完成后委托出去
    finish_translation(ctx)  # → translation_lifecycle.py
    yield progress:100 + finish

# translation_lifecycle.py (新增):
def finish_translation(ctx):  # replace_page + merge_after_translate
```

**备选方案**：在 `routes.py` 中协调，翻译完成后显式调用 replace + merge。会导致路由层变厚，违背"路由层薄"的设计原则，拒绝。

### Decision 3: 缩小接口依赖

**GenerateContext 不再包含 `state: AppState`**：
- `sse_stream.generate()` 需要的是"完成翻译后做什么"，不需要整个 `AppState`
- 改动：`GenerateContext` 中 `state` 替换为 `replace_page: Callable` + `glossary_cache_path: Path | None`
- 路由层在构造 `GenerateContext` 前将 `state.replace_page` 和 `state.glossary_cache_path` 提取为局部值

**glossary_service.py 参数类型缩小**：
- `resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)`
- `merge_after_translate` 不变（已经只依赖 Path）

### Decision 4: 消除 debug_trace.py 重复

`debug_session` 上下文管理器和 `setup_file_handler`/`cleanup_file_handler` 做同样的事。选择方案：

```

Full source: openspec/changes/refactor-module-cohesion/design.md

## openspec/changes/refactor-module-cohesion/tasks.md

- Source: openspec/changes/refactor-module-cohesion/tasks.md
- Lines: 1-34
- SHA256: 191fddd14d6bdac8b06dbe6a2e0ca2b0068787d09abca0d8595443e98e263526

```md
## 1. 拆分 services.py

- [ ] 1.1 创建 `file_hash.py`：迁移 `sha256()` 函数，确认无其他模块依赖
- [ ] 1.2 创建 `engine_resolver.py`：迁移 `resolve_engine()`、`build_engine_kwargs()`、`CONFIG_ATTR_MAP`，确认依赖 `config.py`
- [ ] 1.3 创建 `pdf_renderer.py`：迁移 `render_page()` 和 `build_settings()`
- [ ] 1.4 更新 `routes.py` 的 import：从新模块导入，移除对 `services` 的旧引用
- [ ] 1.5 更新 `state.py` 的 import：从 `pdf_renderer` 导入 `render_page`（不再从 `services` 导入）
- [ ] 1.6 更新测试文件 `test_services.py`：拆分或重命为对应新模块的测试，调整 import
- [ ] 1.7 删除 `services.py`

## 2. 抽取翻译生命周期模块

- [ ] 2.1 创建 `translation_lifecycle.py`：包含 `finish_translation()` 函数（replace_page + merge_after_translate + 临时目录清理）
- [ ] 2.2 修改 `sse_stream.py` 的 `GenerateContext`：`state: AppState` → `replace_page: Callable` + `glossary_cache_path: Path | None`
- [ ] 2.3 修改 `sse_stream.py` 的 `generate()`：后处理逻辑委托给 `finish_translation()`，自身只保留 SSE 格式化 + 翻译事件流转发
- [ ] 2.4 修改 `routes.py` 的 `translate_page()`：构造 `GenerateContext` 时从 `state` 提取 `replace_page` 和 `glossary_cache_path`
- [ ] 2.5 更新 `test_sse_stream.py`：适配新的 GenerateContext 接口

## 3. 缩小接口依赖

- [ ] 3.1 修改 `glossary_service.py`：`resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)`
- [ ] 3.2 修改 `routes.py` 中调用 `resolve_glossary_paths` 处：传入 `state.glossary_cache_path` 而非 `state`
- [ ] 3.3 更新 `test_glossary_service.py`：适配新参数类型

## 4. 消除 debug_trace.py 重复

- [ ] 4.1 将 `setup_file_handler` / `cleanup_file_handler` 的逻辑合并入 `debug_session` 上下文管理器
- [ ] 4.2 删除独立的 `setup_file_handler` 和 `cleanup_file_handler` 函数（确认无外部调用者）
- [ ] 4.3 更新 `test_debug_trace.py`：移除对已删除函数的测试

## 5. 验证

- [ ] 5.1 运行 `ruff check .` 确保零错误
- [ ] 5.2 运行 `pytest tests/ -v` 确保全部 111 个测试通过
```

## openspec/changes/refactor-module-cohesion/specs/debug-trace-module/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/debug-trace-module/spec.md
- Lines: 1-25
- SHA256: ec0a73bc05007ab834ce1fa0a43fed59ebcc4680c1fb892307af1f1a7b5cf013

```md
## MODIFIED Requirements

### Requirement: Debug trace module isolation

The system SHALL provide a dedicated `debug_trace` module that encapsulates all debug tracing concerns: conditional monkey-patching, per-translation file handler management with log rotation, and step/token/glossary trace logging. Business code SHALL interact with debug tracing only through this module's interfaces. The `debug_session` context manager SHALL internally handle file handler creation and cleanup without exposing separate `setup_file_handler` / `cleanup_file_handler` public functions that duplicate its logic.

#### Scenario: Business code uses debug_trace interfaces

- **WHEN** the translation flow needs to log a step, token usage, or glossary merge
- **THEN** it SHALL call `debug_trace.log_step` / `log_token_usage` / `log_glossary_merge`, and SHALL NOT contain inline `if config.DEBUG` checks

#### Scenario: Debug session context management

- **WHEN** a translation starts with debug enabled
- **THEN** a `debug_session` context manager SHALL create the file handler (with log rotation), add it to the trace logger, and SHALL remove and close it on exit, even if the translation raises

#### Scenario: No duplicate file handler logic

- **WHEN** `debug_trace.py` is inspected
- **THEN** the file handler creation/cleanup logic SHALL exist in exactly one place (`debug_session`), not duplicated in separate public functions

#### Scenario: No inline debug checks in route/service code

- **WHEN** `routes.py` and service modules are scanned
- **THEN** there SHALL be zero occurrences of `if config.DEBUG` or `if debug` inline checks in business logic; all debug branching SHALL live inside `debug_trace.py`
```

## openspec/changes/refactor-module-cohesion/specs/engine-config/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/engine-config/spec.md
- Lines: 1-20
- SHA256: 3808eae4452453fa413188a19af1b9d03aa157956014e409c3f329f6461ecc26

```md
## ADDED Requirements

### Requirement: Engine configuration module

The system SHALL provide an `engine_resolver` module that encapsulates engine lookup, field mapping, and kwargs building. The module SHALL export `resolve_engine()`, `build_engine_kwargs()`, and `CONFIG_ATTR_MAP`, and SHALL NOT import or depend on `services.py`.

#### Scenario: Engine resolution from provider name

- **WHEN** `resolve_engine("deepseek")` is called
- **THEN** the module SHALL return the EngineSpec matching the provider, using `PROVIDER_INDEX` from `config.py`

#### Scenario: Unknown provider falls back

- **WHEN** `resolve_engine("unknown_provider")` is called
- **THEN** the module SHALL fall back to the `openai_compatible` engine spec

#### Scenario: Engine kwargs built from config

- **WHEN** `build_engine_kwargs(spec)` is called for a valid EngineSpec
- **THEN** the module SHALL dynamically map unified config field names to engine-specific field names using `spec.field_map`
```

## openspec/changes/refactor-module-cohesion/specs/engine-registry/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/engine-registry/spec.md
- Lines: 1-15
- SHA256: ec73344a0da8fa8310550ef62266c24cf39dec28e9b2f3a0322f1089edb72e02

```md
## MODIFIED Requirements

### Requirement: Declarative translation engine registry

The system SHALL maintain a declarative engine registry where each supported translation engine is described by a single `EngineSpec` record. The engine resolution and kwargs building logic SHALL reside in a dedicated `engine_resolver` module, not in `services.py`. The `EngineSpec` dataclass and `ENGINE_REGISTRY` list SHALL remain in `config.py`.

#### Scenario: Engine resolution is in dedicated module

- **WHEN** the system needs to resolve an engine or build engine kwargs
- **THEN** it SHALL import from `engine_resolver`, not from `services`

#### Scenario: Registry remains the single source of truth

- **WHEN** the system resolves an engine class or builds engine kwargs
- **THEN** it SHALL consult only the engine registry in `config.py`, and no separate `PROVIDER_MAP` or multi-key `FIELD_MAP` dictionaries SHALL exist
```

## openspec/changes/refactor-module-cohesion/specs/file-hash/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/file-hash/spec.md
- Lines: 1-15
- SHA256: 0d0cecf72d9745b3f05ffd7603d0a3467ea94eb455c44c35acd4863e47200995

```md
## ADDED Requirements

### Requirement: File hash module

The system SHALL provide a `file_hash` module that computes SHA256 hashes of files via streaming reads. The module SHALL export a single `sha256(filepath: str) -> str` function.

#### Scenario: Hash computation

- **WHEN** `sha256("/path/to/file")` is called
- **THEN** the module SHALL read the file in 8KB chunks and return its SHA256 hex digest

#### Scenario: Module independence

- **WHEN** `file_hash` is imported
- **THEN** it SHALL not depend on any other project module (only standard library `hashlib`)
```

## openspec/changes/refactor-module-cohesion/specs/terminology-management/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/terminology-management/spec.md
- Lines: 1-15
- SHA256: 80685ba42308f04d8fb1396611ea0701dba056669843ad68b456fd97b232ef9b

```md
## MODIFIED Requirements

### Requirement: Glossary service parameter interface

The glossary service module SHALL accept `Path | None` as its input parameter for cache path resolution instead of depending on the full `AppState` type. The merge function SHALL remain unchanged, accepting `Path | None` for both cumulative and auto-extracted paths.

#### Scenario: Resolve glossary paths from cache path

- **WHEN** `resolve_glossary_paths(cache_path)` is called with a valid Path
- **THEN** the function SHALL return `[str(cache_path / "cumulative_glossary.csv")]` if the file exists and is non-empty, or `None` otherwise

#### Scenario: Resolve glossary paths with None input

- **WHEN** `resolve_glossary_paths(None)` is called
- **THEN** the function SHALL return `None`
```

## openspec/changes/refactor-module-cohesion/specs/translation-lifecycle/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/translation-lifecycle/spec.md
- Lines: 1-20
- SHA256: fdef7e64e85c1e9431a4e5c16235ee000429e901a463066795c29c846e23352d

```md
## ADDED Requirements

### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf, merging auto-extracted terminology into the cumulative glossary, and cleaning up temporary directories. The SSE streaming module SHALL delegate to this module for post-translation actions rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL raise an error that propagates as an SSE error event

#### Scenario: Temporary directory cleanup

- **WHEN** translation lifecycle runs (success or failure)
- **THEN** the temporary directories created for single-page extraction and translation output SHALL be removed
```

## openspec/changes/refactor-module-cohesion/specs/translation-persistence/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/translation-persistence/spec.md
- Lines: 1-20
- SHA256: 65c7e8bc10e1777ae2b422fcc1318b3b2d1a98bc1b690645b9ce73d76a1140c7

```md
## MODIFIED Requirements

### Requirement: Right.pdf as translation state

The system SHALL maintain a right.pdf file that stores the current translation state, where translated pages contain translated content and untranslated pages contain the original content. The page replacement operation SHALL be invoked by the translation lifecycle module, which receives the necessary callable context from the route layer rather than accessing AppState directly.

#### Scenario: First open creates right.pdf

- **WHEN** a PDF is opened for the first time
- **THEN** the system SHALL compute the SHA256 hash of the original PDF and create `cache/<sha256>/right.pdf` as an exact copy of the original

#### Scenario: Subsequent open restores state

- **WHEN** a PDF that was previously opened and partially translated is opened again
- **THEN** the system SHALL detect the existing right.pdf via SHA256 hash match and load it, preserving all prior translations

#### Scenario: Translation updates right.pdf

- **WHEN** a page is translated
- **THEN** the translation lifecycle module SHALL invoke the page replacement operation, which replaces the corresponding page in right.pdf with the translated output and saves the file
```

## openspec/changes/refactor-module-cohesion/specs/translation-service-layer/spec.md

- Source: openspec/changes/refactor-module-cohesion/specs/translation-service-layer/spec.md
- Lines: 1-59
- SHA256: ff401cc67668a2f71418658837a7458432340df9a06987c417f29d89b5623a16

```md
## MODIFIED Requirements

### Requirement: Translation service layer modularization

The system SHALL provide a translation service layer that separates the concerns currently embedded in the `translate_page` route function. The service layer SHALL consist of independently testable modules covering: single-page PDF extraction (`pdf_extraction`), translation engine orchestration (`translation_orchestrator`), SSE event formatting (`sse_stream`), translation lifecycle management (`translation_lifecycle`), glossary path resolution and merge (`glossary_service`, `glossary_merger`), debug trace logging hooks (`debug_trace`), engine configuration (`engine_resolver`), file hashing (`file_hash`), and PDF rendering + settings building (`pdf_renderer`).

#### Scenario: Single-page PDF extraction service

- **WHEN** the translation flow needs a single-page PDF for page N
- **THEN** a dedicated extraction service SHALL produce a temporary PDF containing only page N from the source document, without the route function directly calling pymupdf

#### Scenario: Translation orchestration service

- **WHEN** the route triggers a translation
- **THEN** a translation orchestrator service SHALL run the asyncio translation stream in a background thread and expose a synchronous iterator of translation events, isolating asyncio complexity from the route layer

#### Scenario: SSE event formatting service

- **WHEN** translation events need to be streamed to the frontend
- **THEN** a dedicated SSE formatting module SHALL convert each event dict into the `data: {json}\n\n` wire format, byte-for-byte identical to the current output, and SHALL delegate post-translation processing to the translation lifecycle module

#### Scenario: Translation lifecycle service

- **WHEN** a translation completes
- **THEN** the translation lifecycle module SHALL handle page replacement in right.pdf, glossary merging, and temporary directory cleanup, without the SSE module invoking these operations directly

#### Scenario: Glossary service

- **WHEN** a translation starts or finishes
- **THEN** a glossary service SHALL resolve cumulative glossary paths before translation and merge auto-extracted terms after translation, without inline logic in the route function

#### Scenario: Engine configuration service

- **WHEN** translation settings need to be built
- **THEN** the engine resolver module SHALL resolve the engine spec and build engine-specific kwargs from unified config fields

#### Scenario: File hash service

- **WHEN** a PDF file's identity needs to be computed
- **THEN** the file hash module SHALL compute the SHA256 digest for cache directory naming

#### Scenario: PDF rendering service

- **WHEN** a PDF page needs to be rendered or translation settings need to be assembled
- **THEN** a dedicated pdf_renderer module SHALL handle pymupdf rendering and pdf2zh-next SettingsModel construction

#### Scenario: Translation error propagation

- **WHEN** the translation engine raises an exception or yields an error event
- **THEN** the orchestrator SHALL propagate the error to the SSE stream as an error event, and the route SHALL NOT crash

### Requirement: Route function thinness

The `translate_page` route function SHALL be limited to request parsing, page validation, service composition, and returning the SSE Response. It SHALL NOT contain business orchestration logic such as pymupdf calls, asyncio loop management, or inline debug logging.

#### Scenario: Route function line count

- **WHEN** the `translate_page` function is measured
- **THEN** its body SHALL be at most 40 lines, excluding the SSE generator it composes from services
```

