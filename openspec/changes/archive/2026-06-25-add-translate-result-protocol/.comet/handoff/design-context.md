# Comet Design Handoff

- Change: add-translate-result-protocol
- Phase: design
- Mode: compact
- Context hash: b75c3894d382310c1226a176e65fde6c5085fece358aaf44bade972e2332be57

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/add-translate-result-protocol/proposal.md

- Source: openspec/changes/add-translate-result-protocol/proposal.md
- Lines: 1-28
- SHA256: 7d59d9cb03b604697c2c9209abb73b21ad0cb490b50caaf4208a69c073cc5bde

```md
# Proposal: add-translate-result-protocol

## Why

`translation_lifecycle.finish_translation`（`translation_lifecycle.py:21`）用 `Any` 鸭子类型直接访问 `translate_result.mono_pdf_path` / `dual_pdf_path` / `auto_extracted_glossary_path`，与 pdf2zh-next v2.9 的数据契约强耦合。上游若改字段名或调整可选性，运行时静默崩，无静态检查兜底，且 `mono_pdf_path is None → fallback dual` 这条关键分支目前无测试覆盖。本变更引入一个 `TranslateResult` Protocol 把契约显式化，并补契约测试。

## What Changes

- 新增一个 `TranslateResult` Protocol（structural typing），声明 `mono_pdf_path`、`dual_pdf_path`、`auto_extracted_glossary_path` 三个 pdf2zh-next 返回结构的字段，供 mypy/静态检查引用。
- `translation_lifecycle.finish_translation` 形参类型由 `Any` 改为 `TranslateResult`（Protocol，不需安装运行时依赖）。
- 保持 `mono_pdf_path is None → fallback dual_pdf_path`（若两者都 None 则生命周期报错/不替换）的运行时行为，仅收紧静态类型。
- 新增契约测试覆盖 `mono=None→dual`、`mono 与 dual 都 None`、`auto_extracted 路径合并` 三个分支。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `translation-lifecycle`: 生命周期模块 SHALL 通过显式 `TranslateResult` Protocol 契约访问翻译结果，而非 `Any`；新增 fallback 分支契约测试要求。

## Impact

- **代码**：`translation_lifecycle.py`（类型 + 新建 Protocol 文件，可放 `translation_lifecycle.py` 或独立 `translate_result.py`）、可能 `tests/test_services.py` 调整 mock 类型。
- **依赖**：无新增运行时依赖；Protocol 用 `typing.Protocol`（py3.8+）。
- **风险**：Protocol 与上游真实结构若漂移仍无法在运行时捕获，但静态检查可在「我们引用字段名拼错」时即时发现——这正是本变更要解决的主要风险。
- **收益**：pdf2zh-next 升级改字段名时，静态检查能定位我们侧的所有引用点。```

## openspec/changes/add-translate-result-protocol/design.md

- Source: openspec/changes/add-translate-result-protocol/design.md
- Lines: 1-33
- SHA256: 52b3b2af4f85e78e443227f4c36b77b83b5e69e8959448092742c2728a0e3374

```md
# Design: add-translate-result-protocol

## Context

`translation_lifecycle.py:14-15` 形参标注 `translate_result: Any`，函数体内 `translate_result.mono_pdf_path`、`.dual_pdf_path`、`.auto_extracted_glossary_path` 都靠鸭子类型。pdf2zh-next v2.9 的 `TranslateResult`（非本项目类）提供这些字段。本项目没有对这层契约的任何抽象或测试。

## Goals / Non-Goals

**Goals:**
- 把 pdf2zh-next 翻译结果字段提升为本项目显式 `TranslateResult` Protocol，`finish_translation` 依赖该 Protocol。
- mypy/ruff 静态检查能捕获我们侧字段名拼写错误或缺失访问。
- 补契约测试覆盖一条 fallback 分支与「两者都 None」分支。

**Non-Goals:**
- 不在运行时校验上游对象是否符合 Protocol（Protocol 是结构化、静默的）。
- 不包装 pdf2zh-next 的真实类为本项目适配层（侵入过大，超出防回归范围）。
- 不引入 mypy 到 CI（属 `add-ci-and-lint-cleanup` 的后续可选项；本变更新增 Protocol 文件以备后续静态检查启用）。

## Decisions

### 决策 1：Protocol 定义放在 `translation_lifecycle.py` 内
字段本就只在此处消费，定义在消费文件内聚最高。若后续多处引用再拆 `translate_result.py`。
- 替代方案：独立模块 → 否决（当前唯一消费点，避免过早抽象）。

### 决策 2：字段标记全 Optional，反映上游真实可选性
pdf2zh-next 在 `no_dual=True` 时 `dual_pdf_path` 可能为 None，`auto_extracted_glossary_path` 在未提取时可能 None。Protocol 字段标注 `Path | None`，与现状一致。

### 决策 3：不改运行时分支逻辑
`mono_pdf_path` 为 None 时 fallback `dual_pdf_path`（`translation_lifecycle.py:22-23`），两者都 None 时仅跳过 `replace_page` 并继续 glossary 合并（当前行为）。本变更只收紧类型，不改这条逻辑，由契约测试锁定。

## Risks / Trade-offs

- **[风险] Protocol 字段与上游真实类漂移时静态检查发现不了** → 缓解：Protocol 描述「我们依赖的契约」而非「上游的完整结构」，把上游变更映射成「我们必须明确更新依赖字段」的检查点；契约测试用 mock 对象断言我们访问的行为符合预期。
- **[风险] mypy 未启用时 Protocol 仅作文档** → 缓解：标注本身即提升可读性，并在 `add-ci-and-lint-cleanup` 后续可平滑接入 mypy（无额外迁移）。```

## openspec/changes/add-translate-result-protocol/tasks.md

- Source: openspec/changes/add-translate-result-protocol/tasks.md
- Lines: 1-20
- SHA256: d0beefd8a7a27781b7613698885dc95ede7792203658e0a8431d242e842ad926

```md
# Tasks: add-translate-result-protocol

## 1. Protocol 定义与接入

- [ ] 1.1 在 `translation_lifecycle.py` 新增 `class TranslateResult(Protocol)`，声明 `mono_pdf_path: Path | None`、`dual_pdf_path: Path | None`、`auto_extracted_glossary_path: Path | None`
- [ ] 1.2 将 `finish_translation` 的 `translate_result: Any` 改为 `translate_result: TranslateResult`
- [ ] 1.3 移除 `from typing import Any` 若不再使用（保持 ruff 干净）
- [ ] 1.4 确认运行时分支（`mono is None → dual`，两者 None 跳过替换）逻辑不变

## 2. 契约测试

- [ ] 2.1 新增测试：`mono_pdf_path` 非 None 时用它替换页面
- [ ] 2.2 新增测试：`mono_pdf_path is None` 且 `dual_pdf_path` 非 None 时 fallback 用 dual
- [ ] 2.3 新增测试：`mono_pdf_path is None` 且 `dual_pdf_path is None` 时跳过 `replace_page`，仍执行 glossary 合并（不抛错）
- [ ] 2.4 新增测试：`auto_extracted_glossary_path` 存在时经 `merge_after_translate` 合并；不存在时仅 warning 且不崩

## 3. 验证

- [ ] 3.1 `ruff check .` 全过
- [ ] 3.2 `pytest -q` 全过（含新增契约测试）
- [ ] 3.3 （若本地有 mypy）`mypy translation_lifecycle.py` 不报字段错误；无 mypy 则跳过，记录 Protocol 已就位待 CI 接入```

## openspec/changes/add-translate-result-protocol/specs/translation-lifecycle/spec.md

- Source: openspec/changes/add-translate-result-protocol/specs/translation-lifecycle/spec.md
- Lines: 1-26
- SHA256: b809582c8de1831cd3fe4eb48333ddb816dfd1fe8c6931bb2d9b32658499c439

```md
# translation-lifecycle Delta: add-translate-result-protocol

## MODIFIED Requirements

### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf, merging auto-extracted terminology into the cumulative glossary, and (subject to the SSE layer's cleanup responsibility) temporary directories. The lifecycle module SHALL consume the translation result through an explicit `TranslateResult` Protocol (structural typing) declaring the fields it depends on (`mono_pdf_path`, `dual_pdf_path`, `auto_extracted_glossary_path`, each `Path | None`), rather than through an `Any`-typed parameter. The SSE streaming module SHALL delegate post-translation page-replacement and glossary-merge to this module rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL skip page replacement and continue with glossary merging (preserving current behavior), and SHALL NOT raise

#### Scenario: Lifecycle falls back to dual PDF

- **WHEN** translate_result has `mono_pdf_path is None` and a non-null `dual_pdf_path`
- **THEN** the lifecycle module SHALL use the `dual_pdf_path` as the page to insert into right.pdf

#### Scenario: Typed contract enables static checking

- **WHEN** the lifecycle module source is inspected or a static type checker is run
- **THEN** the `translate_result` parameter SHALL be typed as the `TranslateResult` Protocol (not `Any`), so field-name typos or missing attributes are detectable by static analysis```

