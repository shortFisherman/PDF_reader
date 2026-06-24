# Proposal: fix-concurrency-resource-cleanup

## Why

代码审查发现两个真实缺陷：
1. **tempdir 泄漏**：`routes.py:91-92` 在路由层创建 `tmpdir`/`output_dir`，清理却放在 `sse_stream.generate` 末尾 `finish_translation`。当 SSE 在 `sse_stream.py:87`（error 事件 `return`）、`:91`（无翻译结果 `return`）早退，或客户端中途断开流时，两个临时目录永远不会被删除。
2. **extract 未持锁竞态**：`routes.py:93` 调用 `pdf_extraction.extract_single_page(state.left_doc, ...)` 直接读 `_left_doc`，绕过 `AppState` 锁；而 `render_page`（`state.py:90`）在锁内 `get_pixmap`。两者并发操作同一 `pymupdf.Document`，存在数据竞争。

本变更修复这两个问题，确保资源在任意退出路径都被清理、并发读文档被锁保护。

## What Changes

- 在 `sse_stream.generate` 用 `try/finally`（或 `ExitStack` 回调）包裹，保证任意早退/异常/断连路径都清理 `tmpdir` 与 `output_dir`。
- 将 `finish_translation` 中的清理职责收敛为「总在 generate 退出时执行的兜底」，避免成功路径重复清理。
- 在 `AppState` 新增 `extract_page(page, tmpdir, extract_func)` 方法，在状态锁内执行单页抽取，与 `render_page` 同模式。
- `routes.py` 改用 `state.extract_page(...)` 替代直接传 `state.left_doc` 给 `pdf_extraction`，消除裸文档读访问。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `translation-lifecycle`: 临时目录清理 SHALL 在任意退出路径（成功/错误/无结果/客户端断连）执行，而非仅在成功路径。
- `page-translation`: 单页抽取 SHALL 在状态锁内完成，与渲染共用同一锁，杜绝并发读竞态。
- `code-quality-foundations`: 新增「extract 在状态锁内执行」的线程安全要求（thread-safe global state access 已覆盖 render/replace，扩展到 extract）。

## Impact

- **代码**：`sse_stream.py`、`translation_lifecycle.py`、`state.py`、`routes.py`、`pdf_extraction.py`（签名可能调整）。
- **依赖**：无新增。
- **测试**：新增早退/断连清理测试、并发 extract+render 测试。
- **风险**：锁内执行 IO（写临时 PDF）会扩大锁持有时长，需评估是否阻塞渲染；通过让 extract 与 render 共锁来串行化，权衡是翻译启动期间渲染短暂等待（可接受，翻译端点本就非频繁）。