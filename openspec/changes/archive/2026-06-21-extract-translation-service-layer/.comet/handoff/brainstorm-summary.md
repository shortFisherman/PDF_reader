# Brainstorm Summary

- Change: extract-translation-service-layer
- Date: 2026-06-21

## Confirmed Technical Approach

**Architecture: Function-oriented service modules (方案 A)**

5 个顶层平铺 service 模块（与现有 services.py、glossary_merger.py、state.py 同级），每个模块暴露纯函数，无类样板代码。`sse_stream.generate` 作为组合中心，接收 `GenerateContext` dataclass 打包参数。

模块接口：
- `pdf_extraction.extract_single_page(src_doc, page_num, tmpdir) -> Path`：抽取单页 PDF，调用方负责 tmpdir 清理
- `translation_orchestrator.run_translation(settings, pdf_path) -> Iterator[dict]`：封装 asyncio 线程 + 事件队列，`_done` 信号变为内部实现，线程异常通过 `TranslationError` 异常传播
- `sse_stream.format_sse_event(evt) -> str | None`：纯函数，字节级兼容现状；`sse_stream.generate(ctx) -> Iterator[str]`：组合中心
- `glossary_service.resolve_glossary_paths(state) -> list[str] | None`、`merge_after_translate(cumulative, auto) -> None`（合并失败仅记日志不抛异常）
- `debug_trace.log_step()`/`setup_file_handler()`/`cleanup_file_handler()`/`log_token_usage()`：骨架接口 + 简单委托，变更 D 优化

路由 `translate_page` ≤ 40 行：校验 + 创建 tmpdir + 调用 service + 构建 GenerateContext + 返回 Response。

## Key Trade-offs and Risks

- **generate 参数较多** → 用 `GenerateContext` dataclass 打包，避免函数签名过长
- **SSE 字节级兼容** → `format_sse_event` 纯函数测试 + 黄金样本回归捕获
- **asyncio 线程边界事件丢失** → orchestrator 测试覆盖 `TranslationError` 传播 + loop 正确关闭
- **debug_trace 骨架与变更 D 耦合** → 本变更建骨架接口 + 简单委托，变更 D 负责优化
- **临时文件清理** → `generate` 的 finally 块统一清理 tmpdir + output_dir（与现状一致）
- **错误传播** → service 层抛异常，generate 统一捕获并格式化为 SSE error 事件；glossary merge 例外（吞掉仅记日志，保持现状）

## Testing Strategy

- `format_sse_event`：纯函数测试，给定事件 dict 断言输出字节匹配黄金样本
- `run_translation`：mock `do_translate_async_stream`，断言迭代器顺序 + TranslationError 传播 + loop 关闭
- `extract_single_page`：真实小 PDF，断言产出页数=1
- `glossary_service`：路径解析（有/无累积文件）+ 合并委托
- `debug_trace`：DEBUG=True/False 行为 + FileHandler 创建/清理
- `generate`：mock orchestrator + state，断言 SSE 流字节级匹配
- `translate_page` 路由：mock service，断言 SSE 匹配 + ≤ 40 行
- 黄金样本：tasks.md 步骤 1 先在现状代码上捕获 SSE 输出作为基线

## Spec Patches

补充 `translation-service-layer/spec.md` 一个 scenario：
- Translation error propagation：翻译引擎抛异常或 yield error 事件时，orchestrator 传播错误到 SSE 流，路由不崩溃
