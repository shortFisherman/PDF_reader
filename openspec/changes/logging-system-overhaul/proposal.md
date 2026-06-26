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
