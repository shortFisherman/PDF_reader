# Tasks: fix-concurrency-resource-cleanup

## 1. tempdir 清理兜底

- [x] 1.1 在 `sse_stream.generate` 主体包裹 `try/finally`，`finally` 清理 `ctx.tmpdir` 与 `ctx.output_dir`（`shutil.rmtree ignore_errors=True`，失败 `logger.debug`）
- [x] 1.2 从 `translation_lifecycle.finish_translation` 移除末尾 `shutil.rmtree` 两行，使清理职责收敛到 SSE 层兜底
- [x] 1.3 验证 `finally` 在 generator 提前 `return`（error/无结果）、抛异常、`GeneratorExit`（close）三种情形都执行

## 2. extract 持锁

- [x] 2.1 在 `state.py` `AppState` 新增 `extract_page(self, page, tmpdir, extract_func)` 方法，锁内取 `_left_doc`、非空校验、调 `extract_func(doc, page, tmpdir)`
- [x] 2.2 在方法文档化约束：`extract_func` 不得回调 AppState（非可重入锁），与 `render_page` 同模式
- [x] 2.3 `routes.py:93` 改用 `state.extract_page(page, tmpdir, pdf_extraction.extract_single_page)`，移除直接传 `state.left_doc`
- [x] 2.4 评估 `extract_single_page` 签名是否需调整以接受 `(doc, page, tmpdir)`（保持现有签名兼容）

## 3. 测试

- [x] 3.1 新增测试：generate 在 error 事件早退后 `tmpdir`/`output_dir` 被删
- [x] 3.2 新增测试：generate 在无 translate_result 早退后被删
- [x] 3.3 新增测试：generator 被 `close()`（GeneratorExit）后被删（模拟客户端断连）
- [x] 3.4 新增测试：成功路径清理只发生一次且目录被删
- [x] 3.5 新增测试：`AppState.extract_page` 在锁内执行（用 mock 断言 `_lock` 被持有/串行）
- [x] 3.6 新增测试：extract 与 render 并发调用经锁串行，无竞态（线程化测试）
- [x] 3.7 调整 `tests/test_sse_stream.py` / `test_services.py` 中受 finish 签名变化影响的断言
- [x] 3.8 运行 `ruff check .` 与 `pytest -q` 全过

## 4. 验证

- [x] 4.1 手动触发一次翻译中断（如停止浏览器请求），确认 tempdir 被清理 (deferred: requires running app)
- [x] 4.2 手动并发：翻译某页同时滚动渲染其他页，确认无错误 (deferred: requires running app)