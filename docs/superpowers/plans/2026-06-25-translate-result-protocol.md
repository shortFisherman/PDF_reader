---
change: add-translate-result-protocol
design-doc: docs/superpowers/specs/2026-06-25-translate-result-protocol-design.md
base-ref: 3126be2e964487d99075cd2057e73887c0cf8e02
---

# TranslateResult Protocol 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `finish_translation` 的 `translate_result` 参数从 `Any` 改为结构化 `TranslateResult` Protocol，提供静态类型检查兜底。

**Architecture:** 在 `translation_lifecycle.py` 内定义 `TranslateResult` Protocol（三个 `Path | None` 字段），替换 `Any` 类型注解。不拆独立文件，不改运行时逻辑。

**Tech Stack:** Python 3.12+, `typing.Protocol`, pytest + unittest.mock

## Global Constraints

- 不引入 `mypy` 到 CI
- 不在运行时用 `isinstance` 校验 Protocol
- 不包装 pdf2zh-next 真实类
- `ruff check .` 必须零新增告警
- 所有 if/else 运行时分支逻辑保持不变

---

### Task 1: 定义 TranslateResult Protocol 并接入

**Files:**
- Modify: `translation_lifecycle.py:1-35`

**Interfaces:**
- Produces: `class TranslateResult(Protocol)` — 三个字段 `mono_pdf_path: Path | None`、`dual_pdf_path: Path | None`、`auto_extracted_glossary_path: Path | None`
- Produces: `def finish_translation(translate_result: TranslateResult, replace_page: Callable[[str], None], glossary_cache_path: Path | None) -> None:`

- [x] **Step 1: 修改 imports — 将 `Any` 替换为 `Protocol`**

将第 5 行 `from typing import Any` 改为 `from typing import Protocol`：

```python
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import debug_trace
from glossary_service import merge_after_translate

logger = logging.getLogger("pdf_reader")
```

- [x] **Step 2: 添加 TranslateResult Protocol 类**

在 `logger` 定义之后、`finish_translation` 之前插入：

```python
class TranslateResult(Protocol):
    mono_pdf_path: Path | None
    dual_pdf_path: Path | None
    auto_extracted_glossary_path: Path | None
```

- [x] **Step 3: 将 `finish_translation` 的 `translate_result` 类型从 `Any` 改为 `TranslateResult`**

将第 14 行的 `translate_result: Any,` 改为 `translate_result: TranslateResult,`。

函数签名最终为：

```python
def finish_translation(
    translate_result: TranslateResult,
    replace_page: Callable[[str], None],
    glossary_cache_path: Path | None,
) -> None:
```

函数体保持不变（第 18-34 行不动）。

- [x] **Step 4: 确认运行时逻辑未变**

用 `git diff` 确认仅改动了 imports、新增 Protocol 类、类型注解，函数体未动：

```bash
git diff translation_lifecycle.py
```

预期：仅 3 处改动 — import 行、新增 class 块、`translate_result` 类型注解。函数体 `# ...` 片段应与原版完全相同。

- [x] **Step 5: 运行 ruff 检查**

```bash
ruff check translation_lifecycle.py
```

预期：PASS，无告警。

- [x] **Step 6: Commit**

```bash
git add translation_lifecycle.py
git commit -m "feat: add TranslateResult Protocol and wire into finish_translation"
```

---

### Task 2: 契约测试

**Files:**
- Create: `tests/test_translation_lifecycle.py`

**Interfaces:**
- Consumes: `finish_translation(translate_result: TranslateResult, replace_page: Callable[[str], None], glossary_cache_path: Path | None) -> None` (Task 1)
- Consumes: `merge_after_translate` from `glossary_service`
- Consumes: `debug_trace.log_glossary_merge`

- [x] **Step 1: 创建测试文件骨架**

新建 `tests/test_translation_lifecycle.py`：

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from translation_lifecycle import finish_translation
```

- [x] **Step 2: 编写测试 — mono_pdf_path 非 None 时替换页面**

追加到测试文件：

```python
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

- [x] **Step 3: 编写测试 — mono=None, dual 非 None 时 fallback**

追加到测试文件：

```python
def test_finish_translation_mono_none_dual_fallback():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = Path("/tmp/dual.pdf")
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/dual.pdf")))
```

- [x] **Step 4: 编写测试 — 两者 None 时跳过 replace_page 不抛异常**

追加到测试文件：

```python
def test_finish_translation_both_none_skip_replace():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = None
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate"),
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_not_called()
```

- [x] **Step 5: 编写测试 — auto_extracted_glossary_path 存在时调用 merge_after_translate**

追加到测试文件：

```python
def test_finish_translation_auto_extracted_present():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = Path("/tmp/g.csv")

    with (
        patch("translation_lifecycle.merge_after_translate") as mock_merge,
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(
        Path("/tmp/cache") / "cumulative_glossary.csv",
        Path("/tmp/g.csv"),
    )
```

- [x] **Step 6: 编写测试 — auto_extracted_glossary_path 为 None 时 merge_after_translate 收到 None**

追加到测试文件：

```python
def test_finish_translation_auto_extracted_none():
    mock_replace = MagicMock()
    result = MagicMock()
    result.mono_pdf_path = Path("/tmp/m.pdf")
    result.dual_pdf_path = None
    result.auto_extracted_glossary_path = None

    with (
        patch("translation_lifecycle.merge_after_translate") as mock_merge,
        patch("translation_lifecycle.debug_trace.log_glossary_merge"),
    ):
        finish_translation(result, mock_replace, Path("/tmp/cache"))

    mock_replace.assert_called_once_with(str(Path("/tmp/m.pdf")))
    mock_merge.assert_called_once_with(
        Path("/tmp/cache") / "cumulative_glossary.csv",
        None,
    )
```

- [x] **Step 7: 运行新增测试确认全部通过**

```bash
pytest tests/test_translation_lifecycle.py -v
```

预期：5 passed。

- [x] **Step 8: Commit**

```bash
git add tests/test_translation_lifecycle.py
git commit -m "test: add contract tests for finish_translation with TranslateResult Protocol"
```

---

### Task 3: 全量验证

**Files:**
- (无新增/修改文件)

- [x] **Step 1: 运行 ruff 全量检查**

```bash
ruff check .
```

预期：PASS，零告警。

- [x] **Step 2: 运行全量测试套件**

```bash
pytest -q
```

预期：全部通过，含 Task 2 新增的 5 个契约测试。

- [x] **Step 3: (可选) mypy 检查**

```bash
mypy translation_lifecycle.py
```

预期：不报字段访问错误。若无 mypy 则跳过，记录 Protocol 已就位待 CI 接入。

- [x] **Step 4: Commit（如 mypy 检查后无改动则跳过）**

```bash
git add -A
git commit -m "chore: final verification for TranslateResult Protocol change"
```
