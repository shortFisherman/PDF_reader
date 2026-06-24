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
- **收益**：pdf2zh-next 升级改字段名时，静态检查能定位我们侧的所有引用点。