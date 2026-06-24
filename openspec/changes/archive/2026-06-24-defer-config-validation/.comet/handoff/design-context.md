# Comet Design Handoff

- Change: defer-config-validation
- Phase: design
- Mode: compact
- Context hash: b1e70f086256c982038fafa74837756cbe0c45bbfa18a4c9040c56f98a574646

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/defer-config-validation/proposal.md

- Source: openspec/changes/defer-config-validation/proposal.md
- Lines: 1-29
- SHA256: 25948b8f6c317b138aef25a4712d486659f8c806234dcb795e968eb39dc8575f

```md
# Proposal: defer-config-validation

## Why

当前 `config.py` 在模块导入期（`config.py:36-39`）即校验 `MODEL_API_KEY` 和 `MODEL`，一旦缺失就 `raise ValueError`。`config.toml` 已被 `.gitignore` 忽略，导致全新克隆（如 CI 环境、新协作者）中任何 `import config` 都会立即抛错，使整个测试套件无法运行、CI 无法建立。本变更将校验从导入期推迟到配置首次被实际消费时，让模块导入在任意环境下都能成功，为后续 CI 变更和测试可移植性铺路。

## What Changes

- 将 `MODEL_API_KEY` / `MODEL` 的强制校验从模块导入期移至首次使用时（延迟校验），导入 `config` 不再因未配置而抛错。
- 保留延迟到真正消费配置的服务层入口触发校验（如 `engine_resolver.resolve_engine` / `translation_settings.build_settings`）。
- **BREAKING**（仅对未配置环境下直接 `import config` 的外部脚本）：原先导入即报错，现在改为导入成功、使用时才报错。
- 调整 `tests/conftest.py` 的 `mock_config` 及受影响测试，确保测试可在无 `config.toml` 的环境下运行。
- 不改 `config.toml` 的 schema、不改业务运行时行为（已正确配置的环境表现完全一致）。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `engine-config`: 配置校验时机改变——从模块导入期延迟到消费期；新增「导入不抛错、缺失配置在消费时报错」的需求。

## Impact

- **代码**：`config.py`（校验逻辑迁移）、`engine_resolver.py`（消费期校验触发点）、`tests/conftest.py` 与若干测试 fixture。
- **依赖**：无新增依赖。
- **下游**：是 `add-ci-and-lint-cleanup` 变更的前置依赖（CI 全新克隆需 `import config` 成功）。
- **风险**：延迟校验可能让「配置缺失」错误晚于预期暴露；通过在翻译端点等关键消费点显式校验并保持原错误文案来控制。```

## openspec/changes/defer-config-validation/design.md

- Source: openspec/changes/defer-config-validation/design.md
- Lines: 1-41
- SHA256: b0f7aaf4a59f9f4090028176683ebb97d7f50a15cfd4510ba454cc2eab48b4b6

```md
# Design: defer-config-validation

## Context

`config.py` 在模块顶层执行 `open(CONFIG_PATH)` 加载 `config.toml`，并在 `config.py:36-39` 直接 `raise ValueError` 校验 `MODEL_API_KEY`/`MODEL`。`config.toml` 已被 `.gitignore` 忽略，因此全新克隆中 `import config` 必然失败。这阻断了 CI 与无配置环境下的测试运行。当前服务的消费点集中在 `engine_resolver.resolve_engine` 与 `translation_settings.build_settings`，这两处是触发翻译的唯一业务入口。

## Goals / Non-Goals

**Goals:**
- `import config` 在任意环境（含无 `config.toml` / 无 API key）下都不抛错。
- 配置缺失错误在「配置首次被业务消费」（解析引擎/构建翻译参数）时以人类可读的中文报错抛出。
- 已正确配置环境的运行时行为与原先完全一致（同样的报错文案、同样的触发语义）。
- 测试套件可在无 `config.toml` 的全新克隆中运行（为本变更及后续 CI 变更铺路）。

**Non-Goals:**
- 不改 `config.toml` 的 schema 或加载机制（仍是模块导入期加载，缺失文件时 `CONFIG` 取空 dict 容错，不抛错）。
- 不引入配置对象/依赖注入等架构改造。
- 不做运行时热重载或多环境 profile。
- 不处理 `requirements` / 虚拟环境的可移植性（属 CI 变更范围）。

## Decisions

### 决策 1：文件缺失走容错而非抛错
`config.py:20` 的 `open(CONFIG_PATH)` 改为：文件不存在时 `CONFIG = {}`，后续以 `dict.get` 安全取值（已是第 23-34 行的模式）。这样导入不依赖 `config.toml` 存在。
- 替代方案：在缺失时仍抛错但仅警告 → 否决，因 CI 全新克隆需导入成功。

### 决策 2：API key/model 校验延迟到消费点
删除导入期 `config.py:36-39` 的 `raise`。新增一个内部校验函数 `_validate_required()`，由 `engine_resolver.resolve_engine`（消费 `MODEL`/`MODEL_API_KEY` 的首个业务入口）在解析前调用，缺失时抛与原先文案一致的 `ValueError`。
- 替代方案：在每个 property getter 里校验 → 否决，过度分散且重复触发。
- 替代方案：用 `@functools.cached_property` 惰性求值 → 引入更复杂的访问模型，超出本变更 scope。

### 决策 3：校验触发点选择 `resolve_engine`
`translation_settings.build_settings` 第一步即调用 `resolve_engine`，故只在 `resolve_engine` 入口校验即可覆盖全部翻译路径，单一入口、改动最小。`pdf_renderer`/`page` 渲染路径不依赖 API key，无需校验，符合「按需校验」语义。

### 决策 4：测试 fixture 调整
`tests/conftest.py` 的 `mock_config` 已 monkeypatch 各 `MODEL_*` 属性——保持不变，但需确保其不再依赖「导入期校验」的存在。新增一个测试覆盖「无 config.toml 时 import 成功、消费时报错」的场景。新增测试覆盖「已配置时行为不变」。

## Risks / Trade-offs

- **[风险] 配置缺失错误晚于导入期暴露** → 缓解：在 `resolve_engine` 等关键消费点显式校验并保留原中文文案；CI 与测试新增断言覆盖「缺失→消费期报错」。
- **[风险] 外部脚本依赖导入即校验来提前失败** → 缓解：属本变更已知 BREAKING 行为，已在 proposal 标注；项目内无此类外部脚本。
- **[风险] 容错 `CONFIG = {}` 掩盖 `config.toml` 笔误** → 缓解：`DPI`/`CACHE_DIR` 等整型/路径键在缺失时应有明确默认或显式报错，本变更在 design 阶段确认 `DPI`/`CACHE_DIR` 缺失的处理（维持现状或补 KeyError 报错），写入 tasks。```

## openspec/changes/defer-config-validation/tasks.md

- Source: openspec/changes/defer-config-validation/tasks.md
- Lines: 1-27
- SHA256: 125d237d8ae2ec16d1c7c8bfe492544cf47eb8f2ba5438074e26891176347dbe

```md
# Tasks: defer-config-validation

## 1. config.py 改造

- [ ] 1.1 修改 `config.py:20` 的 `CONFIG` 加载：`config.toml` 不存在时 `CONFIG = {}`（容错，不抛错）
- [ ] 1.2 移除 `config.py:36-39` 导入期对 `MODEL_API_KEY`/`MODEL` 的 `raise` 校验
- [ ] 1.3 新增内部 `_validate_required_config()` 函数，缺失/哨兵时抛与原文案一致的 `ValueError`（保留中文 "请设置 model.api_key 或环境变量 MODEL_API_KEY" / "请设置 model.model"）
- [ ] 1.4 确认 `DPI`/`CACHE_DIR` 等必键在缺失时的处理：维持现状或补明确报错，按 design 决策落地

## 2. 消费期校验接入

- [ ] 2.1 在 `engine_resolver.resolve_engine` 入口调用 `_validate_required_config()`（解析引擎前）
- [ ] 2.2 确认 `translation_settings.build_settings` 经由 `resolve_engine` 自动覆盖校验，无需重复触发

## 3. 测试

- [ ] 3.1 新增测试：无 `config.toml` 时 `import config` 成功且 `CONFIG == {}`
- [ ] 3.2 新增测试：`MODEL` 缺失时 `resolve_engine` 抛 "请设置 model.model"
- [ ] 3.3 新增测试：`MODEL_API_KEY` 缺失/哨兵时 `resolve_engine` 抛 "请设置 model.api_key 或环境变量 MODEL_API_KEY"
- [ ] 3.4 新增测试：已正确配置时行为不变（消费点触发同等校验）
- [ ] 3.5 调整 `tests/conftest.py` `mock_config` 等 fixture，确保无 `config.toml` 依赖
- [ ] 3.6 运行 `ruff check .` 与 `pytest -q`，确认 107+ 测试全过、lint 全过

## 4. 验证

- [ ] 4.1 手动验证：在有 `config.toml` 环境下整链路翻译功能正常
- [ ] 4.2 手动验证：在无 `config.toml` 环境下 `python -c "import config"` 不抛错
- [ ] 4.3 交叉验证此变更为 `add-ci-and-lint-cleanup` 的前置依赖不再阻断```

## openspec/changes/defer-config-validation/specs/engine-config/spec.md

- Source: openspec/changes/defer-config-validation/specs/engine-config/spec.md
- Lines: 1-35
- SHA256: f0268b641b717ab7b4ab2246dabc5eb2aa94d2718f1e2d1af3aa413cd7c26af3

```md
# engine-config Delta: defer-config-validation

## ADDED Requirements

### Requirement: Config import shall not fail on missing config

The `config` module SHALL be importable in any environment, including when `config.toml` does not exist or required model fields are unconfigured. The system SHALL NOT raise any exception at module import time due to missing configuration. When `config.toml` is missing, the loaded `CONFIG` SHALL default to an empty mapping.

#### Scenario: Import config with no config.toml present

- **WHEN** the `config` module is imported in a fresh clone where `config.toml` does not exist
- **THEN** the import SHALL succeed without raising, and `config.CONFIG` SHALL be an empty mapping

#### Scenario: Import config with unconfigured API key present

- **WHEN** the `config` module is imported while `MODEL_API_KEY` / `MODEL` are missing or sentinel (`sk-your-api-key`)
- **THEN** the import SHALL succeed without raising

### Requirement: Required model config validated at consumption time

The system SHALL validate that required model configuration (`MODEL_API_KEY`, `MODEL`) is present at the first business consumption point (`engine_resolver.resolve_engine`), raising a user-facing error matching the original Chinese messages when the configuration is missing or unconfigured.

#### Scenario: Translation consumption reports missing config

- **WHEN** `resolve_engine` is invoked while `MODEL` is unconfigured
- **THEN** the system SHALL raise an error with the original "请设置 model.model" message

#### Scenario: Translation consumption reports missing API key

- **WHEN** `resolve_engine` is invoked while `MODEL_API_KEY` is missing or the `sk-your-api-key` sentinel
- **THEN** the system SHALL raise an error with the original "请设置 model.api_key 或环境变量 MODEL_API_KEY" message

#### Scenario: Correctly configured environment behaves unchanged

- **WHEN** `config.toml` is present and fully configured and a translation is requested
- **THEN** the system SHALL behave exactly as before the change (same validation messages emitted at the same consumption point, same runtime behavior)```

