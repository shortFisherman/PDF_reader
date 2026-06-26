# Comet Design Handoff

- Change: logging-system-overhaul
- Phase: design
- Mode: compact
- Context hash: 3f96599ae21236318c9e4afe8e4927d11aadeaea1396e292edd7da90752dfbd8

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/logging-system-overhaul/proposal.md

- Source: openspec/changes/logging-system-overhaul/proposal.md
- Lines: 1-33
- SHA256: db10c8ad6648c8a77d4b239409d2dbdb749cf8cb75267061e0adcb436a1a9db5

```md
## Why

当前日志系统无法支撑"出未知问题时凭日志回溯定位"的核心诉求：`debug_trace.py` 仅在 debug 开启时工作，关闭后整个项目除翻译引擎名外几乎无流程轨迹；而真正最需要回溯的环节（打开 PDF、渲染、抽页、异步翻译编排、`right.pdf` 状态变更）在任何时候都没有日志。此外 `app.py` 硬编码 `basicConfig(level=INFO)` 使 werkzeug/pdf2zh_next/babeldoc 的 INFO 噪音淹没终端，无法区分"项目自身流程"与"第三方运行噪音"。术语提取 monkey-patch 当初为排障而生，该功能现已正常运作，留着徒增耦合。

## What Changes

- 新增集中式日志配置模块（如 `logging_config.py`），统一管理根 logger 级别、按模块的 logger 层级、控制台 + 轮转文件双 handler、格式器
- **BREAKING**：`debug_trace.py` 的术语提取 monkey-patch（`_apply_monkey_patches` / `patched_extract`）整段移除；`debug-tracing` spec 中"LLM term extraction transparency"需求废弃
- 将 `log_step` / `log_token_usage` 的语义从"仅 debug 时记录"迁移为"INFO 常驻流程日志 + DEBUG 细节"，使 debug off 时仍有翻译流程轨迹
- 为当前零日志的关键环节补 INFO 流程日志：`state.open_pdf` / `render_page`(DEBUG,高频) / `extract_page` / `replace_page`(状态变更) / `translation_orchestrator` 异步边界 / `glossary_service.resolve_glossary_paths` / `translation_lifecycle.finish_translation`
- 翻译流程日志带 `page`（或 batch 范围）关联标识，串联一次翻译的抽页/编排/替换/合并全链路
- 错误日志带上文文（page、settings 摘要、临时路径）+ `exc_info`，替换 `sse_stream.py` 中无上下文的 `logger.warning`
- 第三方库 logger（`werkzeug` / `pdf2zh_next` / `babeldoc`）降级为 DEBUG：平时不打，debug on 时才显示其细节
- 启动时以 INFO 输出关键配置摘要（provider/model/lang/cache_dir），替代单条 `Starting PDF Reader`
- 保留 `debug_session` 的 per-PDF 文件留档能力，纳入新配置体系

## Capabilities

### New Capabilities
- `application-logging`: 覆盖全项目运转流程的结构化日志系统——按模块 logger 层级、INFO 常驻流程轨迹 + DEBUG 细节、控制台 + 轮转文件双输出、翻译流程 page 关联标识、带上下文的错误日志、第三方库噪音降级

### Modified Capabilities
- `debug-tracing`: 移除"LLM term extraction transparency"（monkey-patch）需求；将"Translation pipeline step logging"从 debug-only 改为 INFO 常驻 + DEBUG 细节分层；debug off 时不再"零日志"而是保留 INFO 流程
- `debug-trace-module`: 模块职责从"封装 debug 跟踪"演进为"新日志系统下的可选 debug 细节 + 文件留档层"；移除 monkey-patch 相关隔离要求

## Impact

- **新增文件**：`logging_config.py`（集中配置）；`logs/` 目录（轮转日志输出）
- **重构文件**：`debug_trace.py`（删 monkey-patch，迁移 log_* 语义）、`app.py`（替换 `basicConfig` 为 `logging_config.setup`）、`config.py`（可能新增 log 相关配置项）
- **插桩文件**：`state.py`、`pdf_renderer.py`、`pdf_extraction.py`、`translation_orchestrator.py`、`sse_stream.py`、`translation_lifecycle.py`、`glossary_service.py`、`routes.py`、`engine_resolver.py`、`translation_settings.py`
- **测试**：`tests/test_debug_trace.py` 需移除 monkey-patch 相关用例并新增日志系统测试；新增 `tests/test_logging_config.py`
- **依赖**：仅用标准库 `logging` + `logging.handlers`，无新外部依赖
- **API**：无对外 HTTP API 变化，纯内部观测层改造
```

## openspec/changes/logging-system-overhaul/design.md

- Source: openspec/changes/logging-system-overhaul/design.md
- Lines: 1-110
- SHA256: e62bec458c4b8e100d3d96dc518caef53d303f5c66472dcb19c6d1ada9fa6d0c

[TRUNCATED]

```md
## Context

PDF_reader 是一个基于 Flask + pdf2zh_next/babeldoc 的 PDF 双栏翻译应用。当前日志能力由 `debug_trace.py` 承担，但它有三个结构性缺陷：

1. **debug off 时无流程日志**：`log_step` / `log_token_usage` / `log_glossary_merge` 开头均为 `if not config.DEBUG: return`，导致正常运行时没有轨迹可回溯。
2. **关键环节全裸**：`state.open_pdf` / `render_page` / `extract_page` / `replace_page`（状态变更）/ `translation_orchestrator`（异步线程 + event queue + join 超时，最难查）在任何时候都没有日志。
3. **噪音与信号混杂**：`app.py:10` 硬编码 `logging.basicConfig(level=logging.INFO)`，使 werkzeug 每条 HTTP 请求、pdf2zh_next/babeldoc 的翻译进度 INFO 全部涌入终端，淹没项目自身信号。

术语提取 monkey-patch（`_apply_monkey_patches` / `patched_extract`）当初为排查术语提取失效而注入 babeldoc 内部，该功能现已稳定，保留它只增加与第三方库版本的耦合。`debug_session` 的 per-PDF 文件留档思路有价值，应纳入新体系。

约束：仅用标准库 `logging` + `logging.handlers`，不引入新外部依赖；不改翻译业务逻辑与前端；渲染页面是高频调用（每次滚动/查看都请求），其日志必须用 DEBUG 避免刷屏。

## Goals / Non-Goals

**Goals:**
- 平时（debug off）终端只显示项目自身的 INFO 流程日志，文件留同样全量记录，出问题可回溯"对哪页做了什么、耗时多少、在哪步失败"
- 翻译流程日志带 `page`（单页）或 `from-to`（批量）关联标识，串联抽页/编排/替换/合并全链路
- 错误日志带上下文（page、settings 摘要、临时路径）+ `exc_info`
- 第三方库 INFO 噪音降为 DEBUG，平时不打
- 重构 `debug_trace.py`：移除 monkey-patch，迁移 `log_*` 为 INFO 常驻 + DEBUG 细节分层，保留 `debug_session` 文件留档

**Non-Goals:**
- 远程日志收集 / OTEL 链路追踪 / 结构化 JSON 日志
- 前端 JS 日志
- 改翻译业务逻辑或第三方库内部日志
- 日志检索/告警平台

## Decisions

### 决策 1：集中式 `logging_config.py`，按模块 logger 层级

新建 `logging_config.py` 提供 `setup_logging(debug: bool)`，在 `app.py` 启动时调用一次，替代 `basicConfig`。

**Logger 层级**（统一 `pdf_reader.*` 命名空间）：
```
pdf_reader (root namespace, INFO)
├── pdf_reader.app        启动/配置
├── pdf_reader.state      开PDF/渲染/抽页/替换(状态变更)
├── pdf_reader.render     渲染(高频→DEBUG)
├── pdf_reader.extract    抽页
├── pdf_reader.translate  翻译编排/SSE/步骤
├── pdf_reader.lifecycle  finish_translation/替换/合并
├── pdf_reader.glossary   术语表路径/合并
├── pdf_reader.engine     引擎解析
├── pdf_reader.routes     HTTP 入口(关键端点,非每请求)
└── pdf_reader.debug_trace debug细节层(原 debug_session 文件留档)
```

第三方库显式降级：`logging.getLogger("werkzeug").setLevel(DEBUG)`，`pdf2zh_next` / `babeldoc` 顶层 logger 同样设为 DEBUG。

**为何不用单个 `pdf_reader` logger**：按模块分层后，未来可单独调某一模块级别（如只把 render 降到 DEBUG 而保留 translate 的 INFO），且日志中 logger 名本身就是定位线索。替代方案：单 logger + 消息前缀——但无法分级，且易遗漏前缀，故不采用。

### 决策 2：级别策略 —— INFO 常驻流程，DEBUG 细节

| 级别 | 用途 | 示例 |
|---|---|---|
| ERROR | 影响请求完成的失败 | 翻译线程异常、replace_page 失败 |
| WARNING | 可恢复异常/降级 | 术语表合并失败、glossary 文件缺失 |
| INFO | 流程里程碑（常驻） | open_pdf 完成、翻译起止+耗时、replace_page 完成、合并完成 |
| DEBUG | 高频/细节 | 渲染每页、第三方库进度、token 用量、term 批次 |

**关键**：`log_step`/`log_token_usage` 不再 `if not config.DEBUG: return`，而是 `logger.info(...)` 常驻流程骨架；token 用量等细节用 `logger.debug(...)`。debug 开关只控制根级别（INFO↔DEBUG）与第三方库是否显示，不再控制"有无流程日志"。

### 决策 3：翻译流程 page 关联标识

翻译相关日志统一前缀 `[page=N]`（单页）或 `[batch=from-to]`（批量）。用 `logging.LoggerAdapter` 或调用时拼入消息实现，不引入 contextvar 全局态（项目是同步+单翻译线程，contextvar 收益小、复杂度高）。

**为何不用 contextvar + Filter 注入**：能自动注入，但本项目的翻译入口集中在 `sse_stream.generate`/`generate_batch`，显式传 page 拼消息更直观、更易在文件中 grep 定位。替代方案不采用。

### 决策 4：控制台 + 轮转文件双 handler

- 控制台：`StreamHandler`，格式 `%(asctime)s %(levelname)s %(name)s [%(context)s] %(message)s`（context 由消息自带，格式器不强行注入）
- 文件：`RotatingFileHandler('logs/pdf_reader.log', maxBytes=5MB, backupCount=5, encoding=utf-8)`，同样的格式器
- `debug_session` 仍可向 `cache/<hash>/debug_trace.log` 追加 per-PDF 留档（仅 debug on），与新全局文件互不冲突

**为何按大小而非按日期轮转**：桌面应用使用呈突发，按大小可预测磁盘占用（上限 ≈ 30MB）。替代方案：TimedRotating——空闲期也会产生空文件，故不采用。

### 决策 5：移除术语提取 monkey-patch

`_apply_monkey_patches` / `patched_extract` / `_original_extract` / `init_debug` 的 patch 逻辑整段删除。`debug-tracing` spec 的 "LLM term extraction transparency" 需求废弃。`init_debug` 保留为薄封装（仅记录 debug 是否启用），或并入 `logging_config.setup_logging`。
```

Full source: openspec/changes/logging-system-overhaul/design.md

## openspec/changes/logging-system-overhaul/tasks.md

- Source: openspec/changes/logging-system-overhaul/tasks.md
- Lines: 1-46
- SHA256: 50467ece0eacd6b301c25036d03dd53fa7382bc7f86ad23579c8c8d1146f2fc0

```md
## 1. 日志配置基础设施

- [ ] 1.1 新建 `logging_config.py`：定义 `setup_logging(debug: bool)`，配置根 `pdf_reader` logger（INFO/DEBUG 随 debug 切换）、控制台 `StreamHandler` + `RotatingFileHandler('logs/pdf_reader.log', maxBytes=5MB, backupCount=5, utf-8)`，统一 formatter
- [ ] 1.2 在 `setup_logging` 中显式将 `werkzeug` / `pdf2zh_next` / `babeldoc` 顶层 logger 设为 DEBUG
- [ ] 1.3 `setup_logging` 自动创建 `logs/` 目录（`logs/.gitkeep` 入库，日志文件不入库）
- [ ] 1.4 `app.py` 移除 `logging.basicConfig(level=logging.INFO)`，改为在 `create_app` 中调用 `logging_config.setup_logging(config.DEBUG)`

## 2. 重构 debug_trace.py

- [ ] 2.1 移除 `_apply_monkey_patches` / `patched_extract` / `_original_extract` / `AutomaticTermExtractor` import 与 `init_debug` 中的 patch 调用
- [ ] 2.2 `log_step` / `log_token_usage` / `log_glossary_merge` 移除 `if not config.DEBUG: return` 早返回；改为 `logger.info`（流程骨架）与 `logger.debug`（token 用量等细节），统一带 `[page=N]` / `[batch=from-to]` 前缀
- [ ] 2.3 `trace_logger` 切换为 `pdf_reader.debug_trace` 命名空间 logger，接入新配置体系；`debug_session` 的 per-PDF 文件留档逻辑保留并指向新 logger
- [ ] 2.4 `app.py` 中 `debug_trace.init_debug` 调用并入 `setup_logging` 或保留为薄封装（倾向并入）

## 3. 按模块插桩 — INFO 流程日志

- [ ] 3.1 `state.py`：`open_pdf` 成功后 INFO 记录 hash/页数/页宽高/cache 是否新建；`replace_page` / `replace_pages` 成功 INFO 记录页索引与 right.pdf 路径，失败 ERROR+exc_info
- [ ] 3.2 `pdf_renderer.py`：`render_page` 用 DEBUG 记录（side/page/耗时），确保 INFO 不刷屏
- [ ] 3.3 `pdf_extraction.py`：`extract_single_page` / `extract_pages` 用 DEBUG 记录抽页范围与临时路径
- [ ] 3.4 `translation_orchestrator.py`：线程启动/结束 INFO（带 page 上下文）；异常 ERROR+exc_info；`thread.join` 超时 WARNING
- [ ] 3.5 `sse_stream.py`：`generate` / `generate_batch` 的 `log_step` 调用迁移到 INFO 常驻；token 用量改 DEBUG；`[page=N]` / `[batch=from-to]` 前缀贯穿
- [ ] 3.6 `sse_stream.py`：异常处理分支由 `logger.warning("... generate error", exc_info=True)` 改为 ERROR 记录带 page/batch + settings 摘要（provider/model/lang/pages）+ 临时目录 + exc_info
- [ ] 3.7 `translation_lifecycle.py`：`finish_translation` / `merge_glossary_only` INFO 记录产物路径与合并耗时
- [ ] 3.8 `glossary_service.py`：`resolve_glossary_paths` DEBUG 记录解析结果；`merge_after_translate` WARNING（失败时）带文件路径
- [ ] 3.9 `routes.py`：关键端点（open/translate/translate-batch）的入口与参数校验失败 DEBUG 记录；非每请求的 404 保留现有
- [ ] 3.10 `engine_resolver.py` / `translation_settings.py`：`resolve_engine` 的 `Using engine` INFO 保留并改命名空间；`build_settings` DEBUG 记录 settings 摘要（无 api_key）

## 4. 启动配置摘要与安全

- [ ] 4.1 `app.py` 启动时 `pdf_reader.app` INFO 输出 provider/model/lang_in/lang_out/cache_dir/dpi/debug 摘要，确认不含 api_key
- [ ] 4.2 全项目 grep 复核：任何日志语句不含 `api_key` / `MODEL_API_KEY` 原值；settings 摘要构造器只取 provider/model/lang/path

## 5. 测试更新与新增

- [ ] 5.1 `tests/test_debug_trace.py`：移除 `test_init_debug_true_patches_extractor` / `test_init_debug_false_does_not_patch` 等 monkey-patch 用例；更新 `test_full_debug_trace_bytes_identical` 适配 INFO 常驻语义
- [ ] 5.2 新增 `tests/test_logging_config.py`：断言 `setup_logging` 后根 logger 拥有控制台+轮转文件 handler、werkzeug/pdf2zh_next/babeldoc 为 DEBUG、`logs/` 目录创建、`app.py` 无 `basicConfig`
- [ ] 5.3 新增流程日志测试：debug off 时 `open_pdf` / `translate` / `replace_page` 产出 INFO 记录；render 只在 DEBUG；翻译记录带 `[page=N]`
- [ ] 5.4 新增错误上下文测试：`generate` 异常时 ERROR 记录含 page + provider + model + exc_info
- [ ] 5.5 新增安全测试：启动摘要与错误上下文日志不含 api_key 值
- [ ] 5.6 更新 `tests/test_app.py`：`init_debug` 调用断言适配并入 `setup_logging` 后的形式

## 6. 文档与收尾

- [ ] 6.1 更新 `AGENTS.md`：记录日志约定（logger 命名空间、级别策略、page 前缀、运行/测试命令）
- [ ] 6.2 运行全量测试与 lint/typecheck，确认全绿
- [ ] 6.3 手动验证：debug off 打开并翻译一页，确认终端只剩项目 INFO 流程日志、文件有全量记录、第三方 INFO 噪音消失；debug on 确认 DEBUG 细节与第三方进度可见
```

## openspec/changes/logging-system-overhaul/specs/application-logging/spec.md

- Source: openspec/changes/logging-system-overhaul/specs/application-logging/spec.md
- Lines: 1-161
- SHA256: 047250d9df82fda2132ae51f1b416c7980b24ea03d6372b23e9fae73e72e2e5d

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Centralized logging configuration

The system SHALL provide a `logging_config` module that performs all logging setup via a single `setup_logging(debug: bool)` entry point, called once at application startup. The setup SHALL configure the root `pdf_reader.*` logger namespace, per-module child loggers, console + rotating file handlers, and formatters. `app.py` SHALL NOT use `logging.basicConfig`; all logging configuration SHALL flow through `logging_config.setup_logging`.

#### Scenario: Setup invoked at startup

- **WHEN** the application starts (via `create_app` or `app.run`)
- **THEN** `logging_config.setup_logging(config.DEBUG)` is called exactly once and the root `pdf_reader` logger has both a console handler and a rotating file handler attached

#### Scenario: No basicConfig in app

- **WHEN** `app.py` is inspected
- **THEN** there is no call to `logging.basicConfig`; logging initialization is delegated to `logging_config`

### Requirement: Per-module logger hierarchy

The system SHALL organize loggers under a `pdf_reader.*` namespace with one child logger per concern: `pdf_reader.app`, `pdf_reader.state`, `pdf_reader.render`, `pdf_reader.extract`, `pdf_reader.translate`, `pdf_reader.lifecycle`, `pdf_reader.glossary`, `pdf_reader.engine`, `pdf_reader.routes`, and `pdf_reader.debug_trace`. Each module SHALL obtain its logger via `logging.getLogger("pdf_reader.<concern>")` and SHALL NOT log through the anonymous root logger.

#### Scenario: Module uses namespaced logger

- **WHEN** any covered module (`state.py`, `pdf_renderer.py`, `pdf_extraction.py`, `translation_orchestrator.py`, `sse_stream.py`, `translation_lifecycle.py`, `glossary_service.py`, `routes.py`, `engine_resolver.py`, `translation_settings.py`) logs a message
- **THEN** the log record's logger name is one of the `pdf_reader.<concern>` names, not `root` and not a bare third-party name

### Requirement: INFO flow logging is always active

The system SHALL emit INFO-level flow logs during normal operation regardless of the debug flag. Flow logs SHALL cover the milestones: opening a PDF, extracting page(s), translation start/end with elapsed time, replacing translated page(s) into `right.pdf`, and glossary merge completion. The debug flag SHALL NOT gate the existence of flow logs; it SHALL only adjust the root level (INFO when off, DEBUG when on) and whether third-party detail is shown.

#### Scenario: Flow logs present with debug off

- **WHEN** a user opens a PDF and translates one page with debug off
- **THEN** the logs contain INFO records for: open PDF (with hash and page count), extract page, translation start, translation end with elapsed seconds, replace page, glossary merge done

#### Scenario: Debug flag does not silence flow

- **WHEN** debug is off and a translation runs
- **THEN** the translation step / token usage trace functions do not return early solely because `config.DEBUG` is false; flow milestones are emitted at INFO

### Requirement: Open PDF logging

The system SHALL log at INFO when a PDF is opened, including the file hash, page count, page width/height, and whether the cache directory was newly created versus reused.

#### Scenario: Open PDF emits metadata

- **WHEN** `state.open_pdf` completes successfully
- **THEN** an INFO log record under `pdf_reader.state` contains the pdf hash, page count, and page dimensions

### Requirement: State change logging for right.pdf

The system SHALL log at INFO when translated page(s) are replaced into `right.pdf`, recording the page index (or indices), the target path, and success. A failed replace SHALL log at ERROR with `exc_info`.

#### Scenario: Replace page success

- **WHEN** `state.replace_page` successfully inserts a translated page into `right.pdf`
- **THEN** an INFO log record under `pdf_reader.state` contains the page index and the right.pdf path

#### Scenario: Replace page failure

- **WHEN** `state.replace_page` raises an exception
- **THEN** an ERROR log record under `pdf_reader.state` is emitted with `exc_info` and the page index

### Requirement: Translation orchestrator boundary logging

The system SHALL log at INFO when the async translation thread starts (with page context) and when it ends, and SHALL log at ERROR with `exc_info` if the thread captures an exception before signalling completion. The `thread.join(timeout=5)` timeout path SHALL log at WARNING if the thread did not terminate within the timeout.

#### Scenario: Thread starts and ends

- **WHEN** `run_translation` spawns its worker thread for a page
- **THEN** INFO records under `pdf_reader.translate` mark thread start and thread end

#### Scenario: Thread exception captured

- **WHEN** the worker thread raises an exception
- **THEN** an ERROR record under `pdf_reader.translate` is emitted with `exc_info` before `TranslationError` is raised

#### Scenario: Join timeout

- **WHEN** `thread.join(timeout=5)` returns but the thread is still alive
- **THEN** a WARNING record under `pdf_reader.translate` is emitted noting the timeout
```

Full source: openspec/changes/logging-system-overhaul/specs/application-logging/spec.md

## openspec/changes/logging-system-overhaul/specs/debug-trace-module/spec.md

- Source: openspec/changes/logging-system-overhaul/specs/debug-trace-module/spec.md
- Lines: 1-30
- SHA256: 978b3e1e348c1560d2cd5337eb5153563336936b6b4231208a5a11797b358d43

```md
## MODIFIED Requirements

### Requirement: Debug trace module isolation

The system SHALL provide a `debug_trace` module that encapsulates debug-detail tracing concerns: per-translation file handler management with log rotation (via `debug_session`), and step/token/glossary trace logging. Business code SHALL interact with debug tracing only through this module's interfaces. The `debug_session` context manager SHALL internally handle file handler creation and cleanup without exposing separate `setup_file_handler` / `cleanup_file_handler` public functions that duplicate its logic. The module SHALL NOT perform monkey-patching of third-party libraries; the former `AutomaticTermExtractor` monkey-patch is removed.

#### Scenario: Business code uses debug_trace interfaces

- **WHEN** the translation flow needs to log a step, token usage, or glossary merge
- **THEN** it SHALL call `debug_trace.log_step` / `log_token_usage` / `log_glossary_merge`, and SHALL NOT contain inline `if config.DEBUG` checks

#### Scenario: Debug session context management

- **WHEN** a translation starts with debug enabled
- **THEN** a `debug_session` context manager SHALL create the file handler (with log rotation), add it to the trace logger, and SHALL remove and close it on exit, even if the translation raises

#### Scenario: No duplicate file handler logic

- **WHEN** `debug_trace.py` is inspected
- **THEN** the file handler creation/cleanup logic SHALL exist in exactly one place (`debug_session`), not duplicated in separate public functions

#### Scenario: No monkey-patching

- **WHEN** `debug_trace.py` is inspected
- **THEN** there is no `_apply_monkey_patches`, no `patched_extract`, no `_original_extract`, and no `AutomaticTermExtractor` import or attribute reassignment

#### Scenario: No inline debug checks in route/service code

- **WHEN** `routes.py` and service modules are scanned
- **THEN** there SHALL be zero occurrences of `if config.DEBUG` or `if debug` inline checks in business logic; all debug branching SHALL live inside `debug_trace.py`
```

## openspec/changes/logging-system-overhaul/specs/debug-tracing/spec.md

- Source: openspec/changes/logging-system-overhaul/specs/debug-tracing/spec.md
- Lines: 1-52
- SHA256: 185f6ea8b81a2a7acfebefbe3cebe7286b30b6a4a027e5f16f1fd59099fe3cd5

```md
## MODIFIED Requirements

### Requirement: Debug mode activation

The system SHALL support debug mode driven by `config.toml` (default False) or the `--debug` CLI flag. `config.DEBUG` SHALL NOT be hardcoded to True at import time; it SHALL be resolved from configuration. When debug mode is enabled, the root `pdf_reader` logger level SHALL be lowered to DEBUG so that DEBUG-level details (high-frequency render logs, token usage, third-party library detail) become visible; when disabled, the root level SHALL be INFO so that INFO flow milestones remain visible. The previous "debug off = zero overhead / behaves identically to pre-debug release / no trace logging" guarantee is superseded: INFO flow logging is now always active by design (see `application-logging` capability).

#### Scenario: Debug mode enabled via CLI

- **WHEN** user starts the app with `python app.py --debug`
- **THEN** `config.DEBUG` is `True` and `setup_logging(True)` sets the root `pdf_reader` logger level to DEBUG, making DEBUG-level details visible

#### Scenario: Debug mode enabled via config

- **WHEN** `config.toml` sets debug enabled to true and the app starts without `--debug`
- **THEN** `config.DEBUG` is `True` and the root logger level is DEBUG

#### Scenario: Debug mode disabled (default) still emits flow logs

- **WHEN** user starts the app with `python app.py` (no `--debug`) and config does not enable debug
- **THEN** the root `pdf_reader` logger level is INFO, INFO flow milestones are emitted, and DEBUG-only details (render per page, token usage, third-party detail) are not shown

#### Scenario: No import-time side effects

- **WHEN** `app.py` is imported (without running the server)
- **THEN** no logging initialization SHALL occur; `setup_logging` SHALL happen only inside `create_app()` based on resolved config

### Requirement: Translation pipeline step logging

The system SHALL log each major step in the translation pipeline via the `pdf_reader.translate` / `pdf_reader.lifecycle` loggers. Flow milestones (build settings, submit page/batch, translation done with elapsed time, replace page, merge glossary) SHALL be emitted at INFO regardless of debug mode. Detailed inputs (full PDF path, glossary paths, token usage, term batch internals) SHALL be emitted at DEBUG. Each record SHALL carry the page correlation marker (`[page=N]` or `[batch=from-to]`).

#### Scenario: Single page translation milestones

- **WHEN** user requests translation of page 1 with debug off
- **THEN** INFO logs show: submit page 1, translation done (with elapsed seconds), replace page 1, merge glossary done — each carrying `[page=1]`

#### Scenario: Detailed inputs at debug only

- **WHEN** debug is on and a translation runs
- **THEN** DEBUG logs include the full PDF path, glossary paths, and token usage; these DEBUG records are absent when debug is off

#### Scenario: Translation failure

- **WHEN** a translation step fails with an exception
- **THEN** an ERROR log includes the step name, the page correlation marker, the exception type and message, and the traceback via `exc_info`

## REMOVED Requirements

### Requirement: LLM term extraction transparency

**Reason**: The monkey-patch on `AutomaticTermExtractor.extract_terms_from_paragraphs` was introduced to diagnose a term-extraction failure that has since been resolved. It couples the project to babeldoc internals and breaks on babeldoc upgrades. The new `application-logging` capability provides flow-level observability (whether the term-extraction stage was reached) without introspecting babeldoc internals.

**Migration**: Term-extraction internal tracing is no longer provided by this project. If deep term-extraction debugging is needed in the future, set `TranslationConfig.debug = True` so babeldoc emits its own `term_extractor_tracking.json` / `term_extractor_freq.json` / `auto_extractor_glossary.csv`, or temporarily reintroduce a patch. The `debug-tracing` spec no longer requires this capability.
```

