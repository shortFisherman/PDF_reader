# Brainstorm Summary

- Change: debug-translation-pipeline
- Date: 2026-06-20

## Confirmed Technical Approach

**方案 A + debug=True 前置条件**：Monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs`，注入 INFO 级日志。由于 pdf2zh_next 在 `settings.basic.debug=False` 时在子进程执行 babeldoc（monkey-patch 不继承），必须设 `debug=True` 强制主进程执行。

**Monkey-patch 加载时机**：app 启动时（`create_app()` 中导入 `debug_patches.py`），仅当 `--debug` CLI flag 开启时生效。

**日志输出**：Logger `pdf_reader.debug_trace`，同时输出 console（Flask 捕获）和 `cache/<pdf_hash>/debug_trace.log` 文件。

**每批术语提取日志内容**：
- 段落数 + 总字符数
- Prompt 长度（字符）
- LLM 返回长度 + 截断至 500 字符的原始内容
- 解析出的术语数量
- JSON 解析失败时的错误详情

**翻译流程步骤日志**：build_settings complete / submit translate / merge glossary / replace page / done with elapsed time

## Key Trade-offs and Risks

- debug=True 导致输出文件加 `.debug` 后缀 → 不影响功能（translate_result 返回正确路径）
- debug=True 导致主进程执行 → 翻译期间 Flask 事件循环可能阻塞（daemon thread + async loop 已隔离）
- monkey-patch 在 babeldoc 版本升级后可能失效 → try/except 包裹，降级为 warning

## Testing Strategy

- 手动测试：`python app.py --debug`，翻译一页后检查 console 日志和 `cache/<hash>/debug_trace.log`
- 手动测试：`python app.py`（无 --debug），确认无额外日志/文件
- 自动测试：`pytest tests/ -q` 确保 39 个测试通过
- Lint：`ruff check`

## Spec Patches

None — delta spec remains as written.
