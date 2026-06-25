# Tasks: add-translate-result-protocol

## 1. Protocol 定义与接入

- [x] 1.1 在 `translation_lifecycle.py` 新增 `class TranslateResult(Protocol)`，声明 `mono_pdf_path: Path | None`、`dual_pdf_path: Path | None`、`auto_extracted_glossary_path: Path | None`
- [x] 1.2 将 `finish_translation` 的 `translate_result: Any` 改为 `translate_result: TranslateResult`
- [x] 1.3 移除 `from typing import Any` 若不再使用（保持 ruff 干净）
- [x] 1.4 确认运行时分支（`mono is None → dual`，两者 None 跳过替换）逻辑不变

## 2. 契约测试

- [x] 2.1 新增测试：`mono_pdf_path` 非 None 时用它替换页面
- [x] 2.2 新增测试：`mono_pdf_path is None` 且 `dual_pdf_path` 非 None 时 fallback 用 dual
- [x] 2.3 新增测试：`mono_pdf_path is None` 且 `dual_pdf_path is None` 时跳过 `replace_page`，仍执行 glossary 合并（不抛错）
- [x] 2.4 新增测试：`auto_extracted_glossary_path` 存在时经 `merge_after_translate` 合并；不存在时仅 warning 且不崩

## 3. 验证

- [x] 3.1 `ruff check .` 全过
- [x] 3.2 `pytest -q` 全过（含新增契约测试）
- [x] 3.3 （若本地有 mypy）`mypy translation_lifecycle.py` 不报字段错误；无 mypy 则跳过，记录 Protocol 已就位待 CI 接入
