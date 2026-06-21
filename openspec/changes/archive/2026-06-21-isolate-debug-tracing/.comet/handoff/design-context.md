# Comet Design Handoff

- Change: isolate-debug-tracing
- Phase: design
- Mode: compact
- Context hash: 4cc6a2c9f860c91bbc43c97b603d0e93e6b382a33629ab34730a27a38ea0e202

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/isolate-debug-tracing/proposal.md

- Source: openspec/changes/isolate-debug-tracing/proposal.md
- Lines: 1-36
- SHA256: e451ba0e734400888aec5cb186fd6bba5de931a96f47b3ea191583c7fec5f025

```md
## Why

调试追踪逻辑散落在两处问题：
1. `app.py:12-14` 在 import 时硬编码 `config.DEBUG = True` + `apply_patches()` + `logger.info`，import 即产生副作用（猴补丁 BabelDOC 私有类、强制开调试），测试与生产导入 app 即受污染。
2. `routes.py` 的 `translate_page` 内 `if config.DEBUG` 散落 20+ 处（日志创建、文件 handler、step 计时、token 用量、术语合并追踪），业务逻辑与调试横切关注点深度耦合。

这导致难以关闭调试、难以测试无调试路径、业务代码 readability 差。

## What Changes

- 抽出独立 `debug_trace.py` 模块，封装所有调试追踪逻辑：
  - `init_debug(config_obj)`：条件性应用猴补丁（仅在 DEBUG=True 时）
  - `DebugSession` 上下文管理器：管理 per-translation 的 file handler 添加/移除、日志轮转
  - `log_step(name, **kwargs)` / `log_token_usage(...)` / `log_glossary_merge(...)`：业务代码调用这些接口而非内联 `if config.DEBUG`
- `app.py` 移除 import 时副作用：`config.DEBUG` 改由配置或 CLI 参数驱动（不再硬编码 True）；`init_debug` 在 `create_app` 内显式调用
- `routes.py:translate_page` 的调试逻辑替换为 `debug_trace` 模块调用
- 调试能力（日志格式、轮转、追踪内容）行为等价，现有 debug-tracing 测试保持通过

## Capabilities

### New Capabilities

- `debug-trace-module`: 调试追踪模块——将散落于 `app.py`/`routes.py` 的调试逻辑集中为独立模块，业务代码通过统一接口调用，import 无副作用

### Modified Capabilities

- `debug-tracing`: 现有调试追踪需求的实现方式变更——`config.DEBUG` SHALL 由配置/CLI 驱动而非硬编码；猴补丁 SHALL 条件性应用；业务代码 SHALL 通过 `debug_trace` 模块接口而非内联 `if config.DEBUG` 记录追踪
- `code-quality-foundations`: "模块化源码组织"需求——`app.py` SHALL 无 import 时副作用；调试追踪 SHALL 独立模块

## Impact

- **代码**：新增 `debug_trace.py`；`app.py`（移除 `config.DEBUG=True`/`apply_patches()` import 时调用）；`routes.py`（调试逻辑替换为模块调用）；`debug_patches.py`（可能并入 `debug_trace.py` 或保留为内部实现）
- **配置**：`config.toml` 可能新增 `[debug] enabled` 或复用 `server.debug`；CLI `--debug` flag 保持
- **API**：无影响
- **测试**：现有 `test_debug_patches.py` 等价回归；新增无调试路径测试（DEBUG=False 时无猴补丁、无 file IO）
- **风险**：需保证 DEBUG=True 时追踪内容字节等价；与变更 B 协同（B 的 service 层调用 debug_trace 接口）
```

## openspec/changes/isolate-debug-tracing/design.md

- Source: openspec/changes/isolate-debug-tracing/design.md
- Lines: 1-77
- SHA256: c5d4d8677d5b9d380e32e382e59c5fb2aac135e5435ae5edacae430526acfbc2

```md
## Context

调试追踪现状：
- `app.py:12-14`：`config.DEBUG = True`（硬编码）→ `apply_patches()`（猴补丁 `AutomaticTermExtractor`）→ `logger.info("Debug tracing enabled")`，import 时即执行
- `routes.py:translate_page`：`if config.DEBUG` 散落 20+ 处——file handler 创建/轮转、step 计时、token 用量、术语合并追踪，与业务编排交织
- `debug_patches.py`：猴补丁实现，无条件应用

约束：DEBUG=True 时追踪内容（日志格式、轮转、字段）字节等价；DEBUG=False 时零开销（无猴补丁、无 file IO）；与变更 B 协同（service 层调用 debug_trace 接口）。

## Goals / Non-Goals

**Goals:**
- `app.py` import 无副作用（无强制 DEBUG、无条件猴补丁）
- `config.DEBUG` 由 `config.toml` 或 CLI `--debug` 驱动
- 业务代码调用 `debug_trace` 模块接口，无内联 `if config.DEBUG`
- DEBUG=False 时零开销
- DEBUG=True 时追踪内容字节等价

**Non-Goals:**
- 不改追踪日志的内容/格式
- 不改 debug_trace.log 轮转策略
- 不改猴补丁的追踪字段（BabelDOC 升级适配另行处理）

## Decisions

### 决策 1：`debug_trace.py` 模块接口

**选择**：
```python
# debug_trace.py
def init_debug(debug_enabled: bool) -> None:
    """条件性应用猴补丁，仅 debug_enabled=True 时。"""

@contextmanager
def debug_session(log_path: Path | None):
    """per-translation 上下文：添加 file handler、轮转旧日志；退出时移除。"""

def log_step(name: str, **fields) -> None: ...        # 替代内联 if config.DEBUG: trace_logger.info("[step] ...")
def log_token_usage(usage: dict) -> None: ...
def log_glossary_merge(action: str, **fields) -> None: ...
```
所有函数内部判断 `config.DEBUG`，业务代码无 `if config.DEBUG`。

**备选**：
- (a) 装饰器 `@trace_step`——表达力强但改控制流，与现有计时逻辑结构差异大
- (b) logging filter——不解决猴补丁与 file handler 管理

**理由**：显式函数调用最接近现状结构，迁移机械、风险低。

### 决策 2：去除 app.py import 副作用

**选择**：
- `config.DEBUG` 改由 `config.toml` 的 `[server] debug` 或 `[debug] enabled` 读取（默认 False），CLI `--debug` 覆盖
- `app.py:create_app` 内显式调用 `debug_trace.init_debug(config.DEBUG)`
- 删除 `app.py:12-14` 的模块级副作用

**备选**：保留模块级 `apply_patches()` 但条件化——仍有 import 时副作用，测试导入 app 即受影响。

**理由**：`create_app` 是显式初始化点，测试可控制是否启用调试。

### 决策 3：debug_patches 并入 debug_trace

**选择**：`debug_patches.py` 的猴补丁逻辑并入 `debug_trace.init_debug` 内部实现（私有函数），`debug_patches.py` 可保留为薄 wrapper 或删除。倾向并入以单一来源。

**理由**：猴补丁是调试追踪的实现细节，应封装在 debug_trace 内。

### 决策 4：DEBUG=False 零开销

**选择**：`log_step` 等函数在 `config.DEBUG=False` 时立即 return（无字符串格式化、无 IO）；`init_debug(False)` 不应用猴补丁。

**理由**：对齐现有 `debug-tracing` spec "Debug mode disabled (default)... zero overhead" 需求。

## Risks / Trade-offs

- [追踪内容字节漂移] → 现有 `test_debug_patches.py` + 新增字节等价测试捕获
- [与变更 B 协同] → debug_trace 接口先行定义，B 的 service 调用之；两变更可并行设计
- [config.DEBUG 来源切换可能影响现有用户] → `config.toml` 默认值与 CLI 保持向后兼容；文档说明
```

## openspec/changes/isolate-debug-tracing/tasks.md

- Source: openspec/changes/isolate-debug-tracing/tasks.md
- Lines: 1-38
- SHA256: d4660d99dc04f2aa1156f8cd4d6d3ff20ba5330aad721d88b342c8c867842d68

```md
## 1. 等价回归基线

- [ ] 1.1 在 `tests/test_debug_trace.py` 编写测试：DEBUG=True 时，一次翻译的追踪日志输出（step/token/glossary/term batch）与现状 `test_debug_patches.py` 期望字节等价
- [ ] 1.2 编写测试：DEBUG=False 时，`log_step`/`log_token_usage`/`log_glossary_merge` 无 IO、无日志输出（零开销）
- [ ] 1.3 运行确认基线在现状代码上通过

## 2. 实现 debug_trace 模块

- [ ] 2.1 创建 `debug_trace.py`，实现 `init_debug(debug_enabled)`：条件性应用猴补丁（从 `debug_patches.py` 迁移逻辑）
- [ ] 2.2 实现 `debug_session` 上下文管理器：file handler 添加/轮转/移除，异常安全
- [ ] 2.3 实现 `log_step`/`log_token_usage`/`log_glossary_merge`，内部判断 `config.DEBUG`，DEBUG=False 立即 return
- [ ] 2.4 运行新模块测试通过

## 3. 去除 app.py import 副作用

- [ ] 3.1 `config.py`：`DEBUG` 改由 `config.toml` 的 `[debug] enabled`（默认 False）或 CLI `--debug` 读取，删除模块级 `DEBUG = False` 硬编码
- [ ] 3.2 `app.py`：删除 `config.DEBUG = True` / `apply_patches()` / `logger.info("Debug tracing enabled")` 模块级副作用
- [ ] 3.3 `app.py:create_app`：显式调用 `debug_trace.init_debug(config.DEBUG)`
- [ ] 3.4 支持 CLI `--debug` flag 覆盖 config
- [ ] 3.5 运行 `tests/test_debug_patches.py` 等价回归通过

## 4. 重构 routes 调试逻辑

- [ ] 4.1 替换 `routes.py:translate_page` 的 `if config.DEBUG` 散落逻辑为 `debug_trace.log_step`/`debug_session`/`log_token_usage`/`log_glossary_merge` 调用
- [ ] 4.2 grep 确认 `routes.py` 与 service 模块无 `if config.DEBUG` 内联检查
- [ ] 4.3 运行 `tests/test_routes.py` 与字节等价测试通过

## 5. 清理 debug_patches

- [ ] 5.1 将 `debug_patches.py` 猴补丁逻辑并入 `debug_trace.py` 内部实现
- [ ] 5.2 删除 `debug_patches.py`（或保留薄 wrapper，依实际迁移结果）
- [ ] 5.3 更新引用 `debug_patches` 的导入

## 6. 全量回归与 lint

- [ ] 6.1 运行 `pytest tests/ -v`，全部测试通过
- [ ] 6.2 运行 `ruff check`，零错误
- [ ] 6.3 grep 确认全项目业务代码无 `if config.DEBUG`（仅 `debug_trace.py` 内部允许）
```

## openspec/changes/isolate-debug-tracing/specs/code-quality-foundations/spec.md

- Source: openspec/changes/isolate-debug-tracing/specs/code-quality-foundations/spec.md
- Lines: 1-25
- SHA256: b40a8037073bd8083be85d89aa25af259184e5772572db94946d0f7e7418b93c

```md
## MODIFIED Requirements

### Requirement: Modular source code organization

The system SHALL be organized into separate Python modules with clear separation of concerns. `app.py` SHALL be free of import-time side effects: no monkey-patching, no hardcoded debug flags, and no logging at module import. Debug initialization SHALL occur explicitly inside `create_app()`. Debug tracing SHALL be encapsulated in a dedicated `debug_trace` module.

#### Scenario: Config loading is independent

- **WHEN** config.py is imported
- **THEN** it SHALL load and expose all configuration values without depending on Flask or other modules

#### Scenario: Routes are registered via app

- **WHEN** app.py creates the Flask application
- **THEN** it SHALL import and register routes from the routes module

#### Scenario: app.py import has no side effects

- **WHEN** `app.py` is imported without executing the server
- **THEN** no monkey-patching SHALL be applied, no debug flag SHALL be hardcoded, and no debug logging SHALL occur

#### Scenario: Debug tracing is module-isolated

- **WHEN** business modules need debug tracing
- **THEN** they SHALL call the `debug_trace` module interfaces, and all `if config.DEBUG` branching SHALL live inside `debug_trace.py`, not in route or service business logic
```

## openspec/changes/isolate-debug-tracing/specs/debug-trace-module/spec.md

- Source: openspec/changes/isolate-debug-tracing/specs/debug-trace-module/spec.md
- Lines: 1-20
- SHA256: 0e14c900d9544ee07df7f21926f85a3a0dd66bca0fc9dfeb0ec608d0c104c255

```md
## ADDED Requirements

### Requirement: Debug trace module isolation

The system SHALL provide a dedicated `debug_trace` module that encapsulates all debug tracing concerns: conditional monkey-patching, per-translation file handler management with log rotation, and step/token/glossary trace logging. Business code SHALL interact with debug tracing only through this module's interfaces, not via inline `if config.DEBUG` checks.

#### Scenario: Business code uses debug_trace interfaces

- **WHEN** the translation flow needs to log a step, token usage, or glossary merge
- **THEN** it SHALL call `debug_trace.log_step` / `log_token_usage` / `log_glossary_merge`, and SHALL NOT contain inline `if config.DEBUG` checks

#### Scenario: Debug session context management

- **WHEN** a translation starts with debug enabled
- **THEN** a `debug_session` context manager SHALL add the file handler (with log rotation) and SHALL remove it on exit, even if the translation raises

#### Scenario: No inline debug checks in route/service code

- **WHEN** `routes.py` and service modules are scanned
- **THEN** there SHALL be zero occurrences of `if config.DEBUG` or `if debug` inline checks in business logic; all debug branching SHALL live inside `debug_trace.py`
```

## openspec/changes/isolate-debug-tracing/specs/debug-tracing/spec.md

- Source: openspec/changes/isolate-debug-tracing/specs/debug-tracing/spec.md
- Lines: 1-103
- SHA256: 90bca1424f5b2da276c156fe4f8fb3ca40b3517268fda7716753dcf7f9b8dcfa

[TRUNCATED]

```md
## MODIFIED Requirements

### Requirement: Debug mode activation

The system SHALL support debug mode driven by `config.toml` (default False) or the `--debug` CLI flag. When debug mode is disabled, the system SHALL behave identically to the previous release (zero overhead: no monkey-patching, no debug file IO, no trace logging). `config.DEBUG` SHALL NOT be hardcoded to True at import time; it SHALL be resolved from configuration.

#### Scenario: Debug mode enabled via CLI

- **WHEN** user starts the app with `python app.py --debug`
- **THEN** `config.DEBUG` is `True`, `init_debug(True)` applies the monkey-patch, and all debug trace features are active

#### Scenario: Debug mode enabled via config

- **WHEN** `config.toml` sets debug enabled to true and the app starts without `--debug`
- **THEN** `config.DEBUG` is `True` and all debug trace features are active

#### Scenario: Debug mode disabled (default)

- **WHEN** user starts the app with `python app.py` (no `--debug`) and config does not enable debug
- **THEN** the system behaves identically to the pre-debug version with no additional file IO, no monkey-patching, and no trace logging

#### Scenario: No import-time side effects

- **WHEN** `app.py` is imported (without running the server)
- **THEN** no monkey-patching SHALL be applied and no debug logging SHALL occur; debug initialization SHALL happen only inside `create_app()` based on resolved config

### Requirement: babeldoc debug output capture

When debug mode is active, the system SHALL set `TranslationConfig.debug = True` so that babeldoc generates internal tracking files (`term_extractor_tracking.json`, `term_extractor_freq.json`, `auto_extractor_glossary.csv`).

#### Scenario: babeldoc tracking files generated

- **WHEN** a page is translated with debug mode enabled
- **THEN** the babeldoc working directory contains `term_extractor_tracking.json`, `term_extractor_freq.json`, and `auto_extractor_glossary.csv`

#### Scenario: Debug files preserved after translation

- **WHEN** translation completes and the working directory is cleaned up
- **THEN** the debug files are copied to `cache/<pdf_hash>/` BEFORE cleanup occurs

### Requirement: LLM term extraction transparency

The system SHALL monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs` (conditionally, only when debug is enabled) to log, for each batch of paragraphs submitted for term extraction:
- Number of paragraphs and total character count in the batch
- Length of the constructed prompt (characters)
- Length of the LLM response (characters), with the response content truncated to 500 characters
- Number of valid terms parsed from the response
- Any JSON parse errors with the problematic response content

#### Scenario: Successful term extraction batch

- **WHEN** the LLM returns a valid JSON array with 3 terms
- **THEN** the log contains: batch size, prompt length, "LLM response length: N, parsed terms: 3"

#### Scenario: LLM returns empty array

- **WHEN** the LLM returns `[]`
- **THEN** the log contains: "LLM response length: N, parsed terms: 0" and the full response `[]` is logged

#### Scenario: LLM returns invalid JSON

- **WHEN** the LLM returns text that cannot be parsed as JSON
- **THEN** the log contains the JSON parse error details and the first 500 characters of the raw response

#### Scenario: Monkey-patch fails to load

- **WHEN** babeldoc version is incompatible and the monkey-patch raises ImportError
- **THEN** the system logs a warning and continues with normal operation (no crash)

### Requirement: Translation pipeline step logging

When debug mode is active, the system SHALL log each major step in the translation pipeline via `debug_trace.log_step` with:
- Step description (e.g., "Building translation settings", "Submitting page for translation")
- Key inputs (page number, PDF path, glossary paths)
- Outcome (translation result path, elapsed time)

#### Scenario: Single page translation

- **WHEN** user requests translation of page 1
- **THEN** the log shows: build_settings step, do_translate step (with page number), merge glossary step, replace page step, each with success/failure status
```

Full source: openspec/changes/isolate-debug-tracing/specs/debug-tracing/spec.md

