## 1. SSE 字节级回归基线

- [x] 1.1 在 `tests/test_sse_stream.py` 编写测试：捕获现状 `translate_page` SSE 输出（progress_start/update/finish/error 各类事件）的期望字节串作为黄金样本
- [x] 1.2 运行确认基线测试在现状代码上通过（锁定契约）

## 2. 抽取 pdf_extraction service

- [x] 2.1 创建 `pdf_extraction.py`，实现 `extract_single_page(src_doc, page_num) -> Path`，从 `translate_page` 内联逻辑迁移
- [x] 2.2 在 `tests/test_pdf_extraction.py` 编写测试：小 PDF 抽取单页，断言产出 PDF 页数=1、内容匹配
- [x] 2.3 运行新测试通过

## 3. 抽取 translation_orchestrator service

- [ ] 3.1 创建 `translation_orchestrator.py`，实现 `run_translation(settings, pdf_path) -> Iterator[dict]`，封装 asyncio 线程 + 事件队列 + `_done`/`error` 信号
- [ ] 3.2 在 `tests/test_translation_orchestrator.py` 编写测试：mock `do_translate_async_stream` 返回事件序列，断言迭代器顺序正确、error 信号传播、loop 正确关闭
- [ ] 3.3 运行新测试通过

## 4. 抽取 sse_stream service

- [ ] 4.1 创建 `sse_stream.py`，迁移 `STAGE_LABELS` 与 `format_sse_event(evt) -> str` 纯函数
- [ ] 4.2 在 `tests/test_sse_stream.py` 用步骤 1 的黄金样本验证新模块输出字节级一致
- [ ] 4.3 运行测试通过

## 5. 抽取 glossary_service

- [ ] 5.1 创建 `glossary_service.py`，迁移累积术语表路径解析与合并逻辑
- [ ] 5.2 在 `tests/test_glossary_service.py` 编写测试：路径解析（有/无累积文件）、合并调用委托 `glossary_merger`
- [ ] 5.3 运行测试通过

## 6. 重构 translate_page 路由

- [ ] 6.1 重写 `routes.py:translate_page` 为薄编排：解析请求 + 校验页码（变更A） + 调用 service + 返回 SSE Response
- [ ] 6.2 确认 `translate_page` 函数体 ≤ 40 行
- [ ] 6.3 更新 `tests/test_routes.py`：mock 各 service，断言 SSE 流字节级匹配黄金样本
- [ ] 6.4 运行 `pytest tests/test_routes.py -v` 全绿

## 7. 全量回归与 lint

- [ ] 7.1 运行 `pytest tests/ -v`，全部测试通过
- [ ] 7.2 运行 `ruff check`，零错误
