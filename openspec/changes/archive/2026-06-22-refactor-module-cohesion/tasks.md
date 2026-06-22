## 1. 拆分 services.py

- [x] 1.1 创建 `file_hash.py`：迁移 `sha256()` 函数，确认无其他模块依赖
- [x] 1.2 创建 `engine_resolver.py`：迁移 `resolve_engine()`、`build_engine_kwargs()`、`CONFIG_ATTR_MAP`，确认依赖 `config.py`
- [x] 1.3 创建 `pdf_renderer.py`：迁移 `render_page()` 和 `build_settings()`
- [x] 1.4 更新 `routes.py` 的 import：从新模块导入，移除对 `services` 的旧引用
- [x] 1.5 更新 `state.py` 的 import：从 `pdf_renderer` 导入 `render_page`（不再从 `services` 导入）
- [x] 1.6 更新测试文件 `test_services.py`：拆分或重命为对应新模块的测试，调整 import
- [x] 1.7 删除 `services.py`

## 2. 抽取翻译生命周期模块

- [x] 2.1 创建 `translation_lifecycle.py`：包含 `finish_translation()` 函数（replace_page + merge_after_translate + 临时目录清理）
- [x] 2.2 修改 `sse_stream.py` 的 `GenerateContext`：`state: AppState` → `replace_page: Callable` + `glossary_cache_path: Path | None`
- [x] 2.3 修改 `sse_stream.py` 的 `generate()`：后处理逻辑委托给 `finish_translation()`，自身只保留 SSE 格式化 + 翻译事件流转发
- [x] 2.4 修改 `routes.py` 的 `translate_page()`：构造 `GenerateContext` 时从 `state` 提取 `replace_page` 和 `glossary_cache_path`
- [x] 2.5 更新 `test_sse_stream.py`：适配新的 GenerateContext 接口

## 3. 缩小接口依赖

- [x] 3.1 修改 `glossary_service.py`：`resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)`
- [x] 3.2 修改 `routes.py` 中调用 `resolve_glossary_paths` 处：传入 `state.glossary_cache_path` 而非 `state`
- [x] 3.3 更新 `test_glossary_service.py`：适配新参数类型

## 4. 消除 debug_trace.py 重复

- [x] 4.1 将 `setup_file_handler` / `cleanup_file_handler` 的逻辑合并入 `debug_session` 上下文管理器
- [x] 4.2 删除独立的 `setup_file_handler` 和 `cleanup_file_handler` 函数（确认无外部调用者）
- [x] 4.3 更新 `test_debug_trace.py`：移除对已删除函数的测试

## 5. 验证

- [x] 5.1 运行 `ruff check .` 确保零错误
- [x] 5.2 运行 `pytest tests/ -v` 确保全部测试通过
