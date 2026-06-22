## Why

当前后端代码存在模块内聚性不足和接口耦合过大的问题：`services.py` 成了杂物堆（5 个互不相关的函数共用一个文件）、`sse_stream.py` 的 `generate()` 承担了翻译生命周期管理而非纯 SSE 格式化职责、`GenerateContext` 将整个 `AppState` 对象泄露给不需要全部接口的模块。这些问题在当前规模下勉强可控，但随着功能增长会逐渐失控。

## What Changes

- **拆分 `services.py`**：将 5 个函数按职责拆分到 3 个模块（文件哈希、引擎配置、PDF 渲染 + 设置构建）
- **抽取翻译生命周期模块**：从 `sse_stream.py` 的 `generate()` 中分离出翻译完成后的后处理逻辑（replace_page、merge_after_translate），`sse_stream.py` 回归纯 SSE 格式化职责
- **缩小接口依赖**：`GenerateContext` 不再传递整个 `AppState` 对象，改为传递翻译完成所需的最小接口或独立属性；`glossary_service.py` 不再依赖 `AppState` 类型，改为接收 `Path | None`
- **消除 `debug_trace.py` 重复代码**：`debug_session` 上下文管理器与 `setup_file_handler`/`cleanup_file_handler` 存在逻辑重复，合并为同一套实现

## Capabilities

### New Capabilities

- `translation-lifecycle`: 翻译完成后的持久化和术语合并逻辑，从 `sse_stream.py` 中独立出来
- `engine-config`: 引擎查找和配置映射逻辑，从 `services.py` 中独立出来
- `file-hash`: 文件 SHA256 哈希计算，从 `services.py` 中独立出来

### Modified Capabilities

- `translation-service-layer`: `services.py` 的边界重新划分，部分函数迁移到新模块
- `frontend-modular-architecture`: （无 spec 变更，仅后端内部重构）
- `translation-persistence`: 翻译持久化逻辑从 `sse_stream.py` 迁移到新模块，功能行为不变
- `terminology-management`: `glossary_service.py` 参数类型从 `AppState` 缩小为 `Path | None`
- `debug-trace-module`: 消除 `debug_session` 和 `setup_file_handler` 之间的代码重复

## Impact

- 受影响文件：`services.py`、`sse_stream.py`、`routes.py`、`translation_orchestrator.py`、`glossary_service.py`、`debug_trace.py`、`state.py`、`pdf_extraction.py`
- 新增文件：`translation_lifecycle.py`、`engine_resolver.py`、`file_hash.py`
- 所有 111 个现有测试预期无需逻辑修改（仅调整 import 路径）
- `ruff check` 零错误
- 不影响前端代码、不影响功能行为、不影响配置文件
