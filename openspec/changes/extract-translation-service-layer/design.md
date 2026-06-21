## Context

`routes.py:translate_page`（102-334 行）当前承担：请求解析、单页 PDF 抽取（`pymupdf.open`+`insert_pdf`）、asyncio 线程编排（`new_event_loop`+`run_until_complete`+事件队列）、SSE 事件格式化、调试日志（`if config.DEBUG` 散落 20+ 处）、术语表路径解析与合并、临时目录清理。230 行单函数，6 类职责。

约束：保守边界——SSE 事件流的类型/字段/stage 标签字节级不变，`/api/*` 契约不变；依赖变更 A 先修复并发竞态（避免在带病代码上拆结构）。

## Goals / Non-Goals

**Goals:**
- `translate_page` 路由函数 ≤ 40 行，仅做请求解析、校验、调用 service、返回 Response
- 每类职责独立模块，可独立单元测试
- SSE 事件流字节级兼容现状
- 现有测试全绿，新模块有测试

**Non-Goals:**
- 不改 SSE 事件类型/字段/stage 标签
- 不改前端
- 不改翻译引擎（pdf2zh-next 调用方式不变）
- 不改并发模型（仍单 asyncio 线程 per 请求，变更 A 已修竞态）

## Decisions

### 决策 1：service 层模块划分

**选择**：按职责拆为 5 个模块（可放 `services/` 包或顶层模块，倾向顶层保持与现有 `services.py` 一致风格）：
- `pdf_extraction.py`：`extract_single_page(src_doc, page_num) -> Path`（临时 PDF）
- `translation_orchestrator.py`：`run_translation(settings, pdf_path) -> Iterator[Event]`，封装 asyncio 线程 + 事件队列，对外暴露同步迭代器
- `sse_stream.py`：`format_sse_event(evt: dict) -> str`，纯函数，stage 标签映射在此
- `glossary_service.py`：`resolve_glossary_paths(state) -> list[str] | None`、`merge_after_translate(...)`（从 routes 内联抽出）
- `debug_trace.py`：见变更 D，此处路由仅调用 `debug_trace.log_step(...)` 而非内联 `if config.DEBUG`

**备选**：
- (a) 单个 `translation_service.py` 大类——职责仍耦合
- (b) 按 pdf2zh-next 概念分（layout/translate/generate）——与我们的路由关注点不对齐

**理由**：每模块单一职责，可独立 mock 测试；`sse_stream` 纯函数最易测；`translation_orchestrator` 隔离 asyncio 复杂性。

### 决策 2：路由层薄化目标

**选择**：`translate_page` 结构 = 解析请求 + 校验页码（变更 A 已加）+ 构建settings + `return Response(stream_with_context(sse_stream.generate(orchestrator.run(...))))`。SSE 生成器函数组合 service 调用，路由 ≤ 40 行。

**理由**：路由层只编排，不实现。

### 决策 3：SSE 字节级兼容

**选择**：`sse_stream.format_sse_event` 产出与现状完全一致的 `data: {json}\n\n` 字符串，stage 标签映射（`STAGE_LABELS`）从 routes.py 迁移到 `sse_stream.py`，前后端不重复定义（与变更 E 共享对齐）。

**备选**：改 SSE 协议为新格式——破坏前端，超保守边界。

### 决策 4：测试策略

**选择**：
- `sse_stream`：纯函数测试，给定事件 dict 断言输出字符串字节匹配现状
- `translation_orchestrator`：mock `do_translate_async_stream`，断言事件迭代器顺序与 `_done`/`error` 信号正确
- `pdf_extraction`：真实小 PDF，断言单页 PDF 页数=1
- `glossary_service`：路径解析与合并逻辑单元测试
- `translate_page` 路由：mock 各 service，断言 SSE 流与现状字节一致

## Risks / Trade-offs

- [拆分后 SSE 事件顺序错位] → `sse_stream` 字节级回归测试捕获
- [asyncio 线程边界事件丢失] → orchestrator 测试覆盖 `_done`/`error` 信号
- [模块过多增加导入复杂度] → 5 个模块属合理粒度，每个 < 100 行
- [与变更 D 耦合] → debug_trace 模块先建骨架，路由调用其接口，D 负责实现细节
