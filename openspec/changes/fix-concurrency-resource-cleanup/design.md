# Design: fix-concurrency-resource-cleanup

## Context

`state.py` 用单 `threading.Lock` 保护所有文档操作。`render_page` 与 `replace_page` 已持锁，但 `extract_single_page` 由路由直接把 `state.left_doc` 传给 `pdf_extraction`，绕过锁。`sse_stream.generate` 在 error/无结果时 `return`，跳过 `finish_translation` 末尾的 `shutil.rmtree`，泄漏 `tmpdir`（`tempfile.mkdtemp()`）与 `output_dir`。

## Goals / Non-Goals

**Goals:**
- 任意退出路径（成功、error 事件、无翻译结果、异常、客户端断连）都清理 `tmpdir` 与 `output_dir`。
- 单页抽取在 `AppState` 锁内执行，与渲染串行化。
- 不改变成功路径的外部可观察行为。

**Non-Goals:**
- 不引入读写锁或更细粒度并发模型（保持单锁简单性）。
- 不解决单例 AppState 的多文档限制（属架构演进变更）。
- 不改 `pdf_extraction.extract_single_page` 的抽取算法本身。

## Decisions

### 决策 1：清理用 `try/finally` 而非 ExitStack
在 `sse_stream.generate` 主体包 `try/finally`，`finally` 里 `shutil.rmtree(tmpdir)` 与 `shutil.rmtree(output_dir)`（均 `ignore_errors=True`）。从 `finish_translation` 移除清理调用，使清理职责单一在 generate 兜底。
- 替代方案：路由层用 `contextlib.ExitStack` 注册清理回调 → 可行但栈需要在 async 生成生命周期内有效，generate 是 generator，跨 yield 的 ExitStack 管理复杂；`try/finally` 在 generator 中也正确触发（GeneratorExit/Close 也会进 finally），更直观。

### 决策 2：generator 的 finally 在客户端断连时执行
Flask `stream_with_context` 在客户端断开时会向 generator 抛 `GeneratorExit`，进入 `finally`。验证此行为并为此新增一个测试（用生成器提前 close 模拟）。

### 冺策 3：`AppState.extract_page` 同 `render_page` 模式
新增 `extract_page(self, page, tmpdir, extract_func)`：锁内取 `_left_doc`，校验非空后调 `extract_func(doc, page, tmpdir)`。`render_func`/`extract_func` 约定同 `render_page`——不得回调 AppState（非可重入锁）。`routes.py` 改传 `state.extract_page(page, tmpdir, pdf_extraction.extract_single_page)`。

### 决策 4：锁内写临时 PDF 的可接受性
`extract_single_page` 做一次 `insert_pdf` + `save`，IO 较轻（单页）。翻译端点非高频，且必须与渲染串行以保证文档句柄稳定，故接受短暂锁占用。

## Risks / Trade-offs

- **[风险] finally 在 generator 异常吞没时静默失败** → 缓解：清理用 `ignore_errors=True` 并 `logger.debug` 记录失败，不抛出掩盖业务错误。
- **[风险] 锁内 save 临时文件慢导致渲染延迟** → 缓解：单页抽取耗时可控；如有性能问题后续可分离只读快照，但本变更优先正确性。
- **[风险] 改 finish_signature 影响现有测试** → 缓解：`test_services.py` 等若断言 finish_translation 内清理，需同步调整；新增测试覆盖 finally 路径。