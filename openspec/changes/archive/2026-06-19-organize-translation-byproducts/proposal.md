## Why

PDF 翻译过程中，pdf2zh_next/babeldoc 在 `translation.output` 未配置时默认将输出文件写入当前工作目录（即项目根目录），导致 `*.glossary.csv`、`*.mono.pdf` 等副产物文件散落在根目录，污染项目结构。

## What Changes

- 在 `services.py` 的 `build_settings()` 中为翻译设置一个临时输出目录，使副产物不再写入根目录
- 在 `routes.py` 的 SSE stream `finally` 块中增加对该临时输出目录的清理逻辑
- 确保翻译成功后右侧视图正确展示译文 PDF，翻译失败后无残留文件

## Capabilities

### New Capabilities

- `translation-output-isolation`: 翻译副产物隔离到临时目录，翻译结束时自动清理

### Modified Capabilities

_（无现有 spec 受影响）_

## Impact

- `services.py`: `build_settings()` 新增临时输出目录参数 / 逻辑
- `routes.py`: `translate_page()` 的 `generate()` 内部函数增加临时输出目录清理
- 不改变翻译结果的质量或内容
