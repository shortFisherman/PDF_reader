## Why

`routes.py:translate_page` 是 230 行巨函数，揉合 6 类职责：单页 PDF 抽取、翻译编排（asyncio 线程 + 事件队列）、SSE 流生成、调试追踪日志、术语表合并、临时目录清理。路由层本应薄，现在却承担业务编排。这导致难以测试、难以扩展（换翻译引擎或改流式协议需动路由）、难以阅读。

## What Changes

- 从 `translate_page` 抽出独立的 service 层模块，各司其职：
  - `pdf_extraction`：从原 PDF 抽取单页为临时 PDF
  - `translation_orchestrator`：封装 `do_translate_async_stream` 的 asyncio 线程 + 事件队列，对外暴露同步迭代器
  - `sse_stream`：将翻译事件转换为 SSE 格式字符串
  - `glossary_service`：累积术语表路径解析与合并（从 routes 内联逻辑抽出）
  - `debug_trace`：调试追踪日志（从 routes 内联 `if config.DEBUG` 抽出，见变更 D 协同）
- `translate_page` 路由变薄（目标 ≤ 40 行）：仅做请求解析、参数校验、调用 service、返回 SSE Response
- SSE 事件契约（事件类型、字段、stage 标签）保持不变，前端无需改动
- 现有测试保持通过；为每个新 service 模块补单元测试

## Capabilities

### New Capabilities

- `translation-service-layer`: 翻译编排服务层——将单页翻译的 PDF 抽取、引擎编排、SSE 流、术语合并、调试追踪拆为独立可测试的 service 模块，路由层仅做协调

### Modified Capabilities

- `page-translation`: 路由层职责变更——`/api/translate/<page>` 的实现 SHALL 委托给 service 层，路由函数 SHALL ≤ 40 行且不包含业务编排逻辑；SSE 事件契约不变
- `code-quality-foundations`: "模块化源码组织"需求扩展——新增 service 层模块划分要求

## Impact

- **代码**：`routes.py`（`translate_page` 大幅瘦身）、新增 `services/` 或同级 service 模块文件
- **API**：`/api/translate/<page>` 的 SSE 事件流字节级兼容，前端无感
- **依赖**：依赖变更 A 完成的并发修复（先修正确再拆结构）
- **测试**：新增各 service 模块单元测试；现有路由测试通过 mock service 验证契约
- **风险**：拆分需保证 SSE 事件顺序与字段完全一致；asyncio 线程边界处理不当会丢事件
