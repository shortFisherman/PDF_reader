# Comet Design Handoff

- Change: debug-translation-pipeline
- Phase: design
- Mode: compact
- Context hash: e7cf13f0dfc339398858499de8d76000ab3a7d202cc1b1cdc04fa99c2434a197

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/debug-translation-pipeline/proposal.md

- Source: openspec/changes/debug-translation-pipeline/proposal.md
- Lines: 1-29
- SHA256: 3b3c01a26a9d2f1b23f0c4e41a120c7c8aa6bf64e8c4be89bec9832c07d96bda

```md
## Why

翻译流程目前对用户是一个黑箱——术语提取是否运行、LLM 返回了什么、解析是否成功、每个环节花了多久、失败在哪一步，全部不可见。用户反复遇到「术语表不生成」的问题却无法定位根因。需要通过可观测性改造，将整个翻译链路透明化。

## What Changes

- 新增 `--debug` CLI 参数，开启后启用全链路调试日志
- 开启 babeldoc `TranslationConfig.debug = True`，解锁内置调试追踪文件（`term_extractor_tracking.json`、`term_extractor_freq.json`、`auto_extractor_glossary.csv`）
- Monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs`，记录每批 LLM 术语提取的 prompt 长度、原始返回内容、解析结果、提取术语数量
- 增强 `routes.py` 翻译流程日志，输出每步的输入/输出/耗时/状态
- 调试文件输出至 `cache/<pdf_hash>/` 目录，与累积术语表同路径，方便事后排查

## Capabilities

### New Capabilities

- `debug-tracing`: 提供全链路可观测性的调试追踪模式，包括 LLM 交互细节、流程步骤状态、性能指标

### Modified Capabilities

<!-- 本次变更不修改任何现有 spec 的 REQUIREMENTS -->

## Impact

- `app.py`: 新增 `--debug` 命令行参数
- `services.py`: `build_settings` 接受 debug flag，设置 `TranslationConfig.debug = True`
- `routes.py`: 增强日志输出，翻译前后记录关键状态
- 新增 `debug_patches.py`: Monkey-patch `AutomaticTermExtractor` 模块，注入调试日志
- `config.py`: 可选新增 `DEBUG` 配置项
```

## openspec/changes/debug-translation-pipeline/design.md

- Source: openspec/changes/debug-translation-pipeline/design.md
- Lines: 1-86
- SHA256: e37ce714ca4706cf1cf8304680cf30ddb980fdc879b469a2e0bee1479232d90a

[TRUNCATED]

```md
## Context

当前 PDF Reader 翻译流程依赖 babeldoc + pdf2zh-next 完成底层翻译工作。这些依赖库内部有大量 INFO/DEBUG 日志，但：
1. babeldoc 的调试输出（`term_extractor_tracking.json` 等）需要 `TranslationConfig.debug = True` 才生成，当前未开启
2. `AutomaticTermExtractor.extract_terms_from_paragraphs` 对 LLM 返回的解析静默处理——若返回 `[]` 或格式异常，外部完全无法感知
3. routes.py 的翻译流程日志过于稀疏，无法追踪每步状态

**约束**：不修改 babeldoc/pdf2zh-next 源码，通过配置 + monkey-patching 实现可观测性。

## Goals / Non-Goals

**Goals:**
- 一键开启全链路调试模式（`--debug` flag）
- 术语提取过程透明化：每批 LLM 调用的 prompt 量、返回内容、解析结果、术语数量
- 翻译流程步骤透明化：每步的输入/输出/状态
- 调试文件输出至 `cache/<pdf_hash>/`，与累积术语表共存，方便事后排查
- 调试模式关闭时行为与原来完全一致

**Non-Goals:**
- 不修改 babeldoc/pdf2zh-next 源码
- 不修复术语提取效果问题（那是诊断后的事）
- 不引入新的外部依赖
- 不改变翻译性能特征（minimal overhead）

## Decisions

### Decision 1: `--debug` CLI flag + app config

**选择**：通过 `app.py` 接受 `--debug` 参数，写入 `config.DEBUG`，`services.py` 读取并传递给 `TranslationConfig.debug`。

**替代方案**：
- 环境变量 `PDF_DEBUG=true`：更轻量，但 discoverability 差，用户不知道有这个选项
- 始终开启 debug：产生大量无用 IO，浪费磁盘空间

**理由**：CLI flag 显式且可发现，用户明确知道自己开启了调试模式。

### Decision 2: Monkey-patch 而非 fork/copy

**选择**：在模块加载时 monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs`，注入日志代码。

**替代方案**：
- 复制 babeldoc 源码到项目中修改：维护负担重，版本升级后需同步
- 通过 babeldoc 插件机制：不存在此机制

**理由**：monkey-patch 零侵入，版本升级兼容性好（仅依赖方法签名不变），可随时关闭。

**实现方式**：
```python
# debug_patches.py
_original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs

def _patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
    # log input
    # call original
    # log output
    return _original_extract(self, paragraphs, pbar, paragraph_token_count)

AutomaticTermExtractor.extract_terms_from_paragraphs = _patched_extract
```

### Decision 3: 日志输出策略

**选择**：使用 Python logging 模块，logger name `pdf_reader.debug_trace`，级别 INFO。

- 每批术语提取前后各一行日志
- LLM 原始返回截断至 500 字符（避免日志爆炸）
- 解析后的术语数量单独一行

**理由**：统一日志框架，不引入新的输出机制；截断避免日志文件过大。

### Decision 4: 调试文件写入位置

**选择**：写入 `cache/<pdf_hash>/` 目录（与 `cumulative_glossary.csv` 同路径）。

**理由**：babeldoc 的 debug 输出会写到 `working_dir`，但 `working_dir` 在翻译完成后被清理。我们需要在 `working_dir` 被清理前将文件复制到 cache 目录。

## Risks / Trade-offs

- **[Risk]** monkey-patch 在 babeldoc 版本升级后方法签名变化可能失效 → **Mitigation**：用 try/except 包裹 patch 逻辑，失败时降级（不 crash，仅失去增强日志）
- **[Risk]** LLM 返回内容可能包含敏感信息，记录下来有泄露风险 → **Mitigation**：仅记录到本地文件，不通过网络传输；日志截断至 500 字符
```

Full source: openspec/changes/debug-translation-pipeline/design.md

## openspec/changes/debug-translation-pipeline/tasks.md

- Source: openspec/changes/debug-translation-pipeline/tasks.md
- Lines: 1-38
- SHA256: 82c910cddd1d54ace4148ff5905ff06fb905df200853e1c1f52616842915f85f

```md
## 1. Debug Mode Infrastructure

- [ ] 1.1 Add `--debug` CLI argument to `app.py` and store in `config.DEBUG`
- [ ] 1.2 Update `config.py` with `DEBUG: bool = False` default

## 2. In-Process Translation via debug=True

- [ ] 2.1 Update `services.py` `build_settings()` to accept `debug: bool` parameter
- [ ] 2.2 When `debug=True`, pass `basic=BasicSettings(debug=True)` to `SettingsModel` (forces main-process execution)
- [ ] 2.3 Import `BasicSettings` from `pdf2zh_next.config.model`

## 3. LLM Term Extraction Monkey-Patch

- [ ] 3.1 Create `debug_patches.py` module with `apply_patches()` function
- [ ] 3.2 Monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs` — wrapper around original
- [ ] 3.3 Before original call: log batch size (paragraph count + character count)
- [ ] 3.4 After original call (finally): read `paragraphs.tracker.input`/`.output`, log prompt length, response length, raw response (truncated to 500 chars), term count delta
- [ ] 3.5 Handle JSON parse errors: if response can't be parsed, log error + raw output
- [ ] 3.6 Graceful degradation: if import fails, log warning and continue without patch

## 4. Pipeline Step Logging

- [ ] 4.1 Add step-begin/step-end log entries in `routes.py` translate endpoint (build settings, submit translate, merge glossary, replace page)
- [ ] 4.2 Include elapsed time for each major step when debug mode is active

## 5. Debug Trace Log File

- [ ] 5.1 Create `logging.getLogger("pdf_reader.debug_trace")` with console handler (always) and file handler (debug mode only)
- [ ] 5.2 File handler writes to `cache/<pdf_hash>/debug_trace.log`, created when translation starts
- [ ] 5.3 Clean up file handler after translation completes to avoid accumulating handlers

## 6. Verification

- [ ] 6.1 Manual test: start with `python app.py --debug`, translate a page, verify console shows batch logs + step logs
- [ ] 6.2 Manual test: verify `cache/<hash>/debug_trace.log` exists and contains the same trace entries
- [ ] 6.3 Manual test: start with `python app.py` (no flag), translate a page, verify no trace logs or files
- [ ] 6.4 Run `pytest tests/ -q` — all 39 tests pass
- [ ] 6.5 Run `ruff check` — no new errors
```

## openspec/changes/debug-translation-pipeline/specs/debug-tracing/spec.md

- Source: openspec/changes/debug-translation-pipeline/specs/debug-tracing/spec.md
- Lines: 1-89
- SHA256: 25aa95af29daea0255c0e26b8aa248e0025e2c180e55335371bd58c3b353dd23

[TRUNCATED]

```md
## ADDED Requirements

### Requirement: Debug mode activation

The system SHALL support a `--debug` CLI flag that enables full-pipeline trace logging. When the flag is absent, the system SHALL behave identically to the previous release (zero overhead).

#### Scenario: Debug mode enabled via CLI
- **WHEN** user starts the app with `python app.py --debug`
- **THEN** `config.DEBUG` is `True` and all debug trace features are active

#### Scenario: Debug mode disabled (default)
- **WHEN** user starts the app with `python app.py` (no `--debug`)
- **THEN** the system behaves identically to the pre-debug version with no additional file IO or logging

---

### Requirement: babeldoc debug output capture

When debug mode is active, the system SHALL set `TranslationConfig.debug = True` so that babeldoc generates internal tracking files (`term_extractor_tracking.json`, `term_extractor_freq.json`, `auto_extractor_glossary.csv`).

#### Scenario: babeldoc tracking files generated
- **WHEN** a page is translated with debug mode enabled
- **THEN** the babeldoc working directory contains `term_extractor_tracking.json`, `term_extractor_freq.json`, and `auto_extractor_glossary.csv`

#### Scenario: Debug files preserved after translation
- **WHEN** translation completes and the working directory is cleaned up
- **THEN** the debug files are copied to `cache/<pdf_hash>/` BEFORE cleanup occurs

---

### Requirement: LLM term extraction transparency

The system SHALL monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs` to log, for each batch of paragraphs submitted for term extraction:
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

---

### Requirement: Translation pipeline step logging

When debug mode is active, the system SHALL log each major step in the translation pipeline with:
- Step description (e.g., "Building translation settings", "Submitting page for translation")
- Key inputs (page number, PDF path, glossary paths)
- Outcome (translation result path, elapsed time)

#### Scenario: Single page translation
- **WHEN** user requests translation of page 1
- **THEN** the log shows: build_settings step, do_translate step (with page number), merge glossary step, replace page step, each with success/failure status

#### Scenario: Translation failure
- **WHEN** a translation step fails with an exception
- **THEN** the log includes the step name, the exception type and message, and the traceback

---

### Requirement: Debug output file organization

The system SHALL organize all debug output files under `cache/<pdf_hash>/` with the following naming convention:
- `cumulative_glossary.csv` — accumulated glossary (existing)
- `debug_trace.log` — full debug log for this PDF session
- `term_extractor_tracking.json` — copied from babeldoc working dir
```

Full source: openspec/changes/debug-translation-pipeline/specs/debug-tracing/spec.md

