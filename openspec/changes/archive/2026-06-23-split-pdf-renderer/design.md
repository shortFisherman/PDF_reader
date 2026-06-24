# Design: Split pdf_renderer.py

## Change

从 `pdf_renderer.py` 中提取 `build_settings()` 到新文件 `translation_settings.py`。

## Files

| 操作 | 文件 |
|------|------|
| 新建 | `translation_settings.py` — 迁入 `build_settings()` 及其 import |
| 修改 | `pdf_renderer.py` — 删除 `build_settings()` 及相关 import |
| 修改 | `routes.py` — import 从 `pdf_renderer` 改为 `translation_settings` |
| 修改 | `tests/test_services.py` — 同上 |

## Implementation

1. 创建 `translation_settings.py`，移入 `build_settings()` 及依赖的 import（`config`, `engine_resolver`, `pdf2zh_next` 相关）
2. `pdf_renderer.py` 删除 `build_settings()` 及不再需要的 import
3. `routes.py` 添加 `from translation_settings import build_settings`，移除旧的 import
4. `tests/test_services.py` 同上调整 import

`build_settings()` 函数签名和行为完全不变，纯文件级拆分。
