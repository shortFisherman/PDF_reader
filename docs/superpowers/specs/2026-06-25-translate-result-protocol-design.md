---
comet_change: add-translate-result-protocol
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-25-add-translate-result-protocol
status: final
---

# TranslateResult Protocol — Technical Design

## 1. Problem

`translation_lifecycle.finish_translation` 用 `translate_result: Any` 直接访问 `mono_pdf_path` / `dual_pdf_path` / `auto_extracted_glossary_path`。pdf2zh-next 升级改字段名时运行时静默崩，无静态检查兜底。

## 2. Solution

引入一个 `TranslateResult` Protocol（`typing.Protocol`），在 `translation_lifecycle.py` 内定义，`finish_translation` 形参从 `Any` 改为该 Protocol。所有字段标注 `Path | None`，反映上游 pdf2zh-next 真实可选性。

### 2.1 Code Change

**Before:**
```python
from typing import Any

def finish_translation(
    translate_result: Any,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
) -> None:
```

**After:**
```python
from typing import Protocol

class TranslateResult(Protocol):
    mono_pdf_path: Path | None
    dual_pdf_path: Path | None
    auto_extracted_glossary_path: Path | None


def finish_translation(
    translate_result: TranslateResult,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
) -> None:
```

函数体中的运行时访问 `translate_result.mono_pdf_path` / `.dual_pdf_path` / `.auto_extracted_glossary_path` 不变。

### 2.2 Module Boundary

Protocol 定义在 `translation_lifecycle.py` 内，不拆独立文件。当前仅此一处消费点，后续若须复用再提取。

### 2.3 Import Cleanup

若 `from typing import Any` 无其他用途则移除，`ruff check` 保持通过。

## 3. Runtime Semantics (Unchanged)

```
mono_pdf_path is not None  →  use mono_pdf_path
mono_pdf_path is None and dual_pdf_path is not None  →  fallback dual_pdf_path
both None  →  skip replace_page, continue glossary merge
auto_extracted_glossary_path exists  →  merge_after_translate()
auto_extracted_glossary_path is None  →  merge_after_translate() handles None internally
```

不改任何 if/else 分支，契约测试锁定。

## 4. Testing

新建 `tests/test_translation_lifecycle.py`，遵循 `test_<module>.py` 惯例。

### 4.1 Test Cases

| # | Scenario | mono | dual | auto_extracted | Expected |
|---|----------|------|------|---|---|
| 1 | mono 非 None | `Path("/tmp/mono.pdf")` | `None` | `None` | `replace_page("/tmp/mono.pdf")` 被调用 |
| 2 | mono=None, dual 非 None | `None` | `Path("/tmp/dual.pdf")` | `None` | `replace_page("/tmp/dual.pdf")` 被调用 |
| 3 | 两者 None | `None` | `None` | `None` | `replace_page` 未被调用，不抛异常 |
| 4 | auto_extracted 存在 | `Path("/tmp/m.pdf")` | `None` | `Path("/tmp/g.csv")` | `replace_page` 被调用；`merge_after_translate` 被调用且收到 `auto_extracted_glossary_path` |
| 5 | auto_extracted 为 None | `Path("/tmp/m.pdf")` | `None` | `None` | `merge_after_translate` 被调用且收到 `None` auto_extracted |

### 4.2 Mock Strategy

```python
from unittest.mock import MagicMock, patch

def test_finish_translation_mono_non_none():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/mono.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/mono.pdf")))
```

`merge_after_translate` 和 `debug_trace.log_glossary_merge` 作为副作用被 patch 掉；`replace_page` 是传入的 mock callable，直接断言调用次数和参数。

## 5. Non-Goals

- 不在运行时用 `isinstance` 校验 Protocol（违反结构化本意）
- 不包装 pdf2zh-next 真实类为适配器
- 不引入 mypy 到 CI

## 6. Verification

- `ruff check .` 无新告警
- `pytest tests/test_translation_lifecycle.py -v` 全部通过
