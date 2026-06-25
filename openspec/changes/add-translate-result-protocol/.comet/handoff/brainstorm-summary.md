# Brainstorm Summary

- Change: add-translate-result-protocol
- Date: 2026-06-25

## Confirmed Technical Approach

- 在 `translation_lifecycle.py` 内定义 `TranslateResult(Protocol)`，三个字段均为 `Path | None`
- `finish_translation` 形参类型由 `Any` 改为 `TranslateResult`
- 不移除或包装 pdf2zh-next 真实类，Protocol 纯结构化、静默校验
- 不改运行时分支逻辑（mono→dual fallback、两者 None 跳过替换）
- 新增 `tests/test_translation_lifecycle.py`，mock `TranslateResult` 对象覆盖四种场景
- 移除 `from typing import Any`（若不再使用）

## Key Trade-offs and Risks

- Protocol 与上游真实结构漂移时静态检查发现不了 → 契约测试用 mock 断言行为
- mypy 未启用时 Protocol 仅作文档 → 标注本身提升可读性，后续 CI 可平滑接入

## Testing Strategy

- 新建 `tests/test_translation_lifecycle.py`，单一测试 `finish_translation`
- Mock 依赖：`replace_page`（Callable）、`merge_after_translate`（patch）、`debug_trace.log_glossary_merge`（patch）
- 四场景：mono 非 None / mono None + dual 非 None / 两者 None / auto_extracted 存在/不存在

## Spec Patches

无——delta spec 场景已完备。
