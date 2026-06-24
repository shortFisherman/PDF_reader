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
- **[风险] mypy 未启用时 Protocol 仅作文档** → 缓解：标注本身即提升可读性，并在 `add-ci-and-lint-cleanup` 后续可平滑接入 mypy（无额外迁移）。