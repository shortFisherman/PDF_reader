## 1. 等价回归基线

- [x] 1.1 在 `tests/test_debug_trace.py` 编写测试：DEBUG=True 时，一次翻译的追踪日志输出（step/token/glossary/term batch）与现状 `test_debug_patches.py` 期望字节等价
- [x] 1.2 编写测试：DEBUG=False 时，`log_step`/`log_token_usage`/`log_glossary_merge` 无 IO、无日志输出（零开销）
- [x] 1.3 运行确认基线在现状代码上通过

## 2. 实现 debug_trace 模块

- [x] 2.1 创建 `debug_trace.py`，实现 `init_debug(debug_enabled)`：条件性应用猴补丁（从 `debug_patches.py` 迁移逻辑）
- [x] 2.2 实现 `debug_session` 上下文管理器：file handler 添加/轮转/移除，异常安全
- [x] 2.3 实现 `log_step`/`log_token_usage`/`log_glossary_merge`，内部判断 `config.DEBUG`，DEBUG=False 立即 return
- [x] 2.4 运行新模块测试通过

## 3. 去除 app.py import 副作用

- [x] 3.1 `config.py`：`DEBUG` 改由 `config.toml` 的 `[debug] enabled`（默认 False）或 CLI `--debug` 读取，删除模块级 `DEBUG = False` 硬编码
- [x] 3.2 `app.py`：删除 `config.DEBUG = True` / `apply_patches()` / `logger.info("Debug tracing enabled")` 模块级副作用
- [x] 3.3 `app.py:create_app`：显式调用 `debug_trace.init_debug(config.DEBUG)`
- [x] 3.4 支持 CLI `--debug` flag 覆盖 config
- [x] 3.5 运行 `tests/test_debug_patches.py` 等价回归通过

## 4. 重构 routes 调试逻辑

- [x] 4.1 替换 `routes.py:translate_page` 的 `if config.DEBUG` 散落逻辑为 `debug_trace.log_step`/`debug_session`/`log_token_usage`/`log_glossary_merge` 调用
- [x] 4.2 grep 确认 `routes.py` 与 service 模块无 `if config.DEBUG` 内联检查
- [x] 4.3 运行 `tests/test_routes.py` 与字节等价测试通过

## 5. 清理 debug_patches

- [x] 5.1 将 `debug_patches.py` 猴补丁逻辑并入 `debug_trace.py` 内部实现
- [x] 5.2 删除 `debug_patches.py`（或保留薄 wrapper，依实际迁移结果）
- [x] 5.3 更新引用 `debug_patches` 的导入

## 6. 全量回归与 lint

- [x] 6.1 运行 `pytest tests/ -v`，全部测试通过
- [x] 6.2 运行 `ruff check`，零错误
- [x] 6.3 grep 确认全项目业务代码无 `if config.DEBUG`（仅 `debug_trace.py` 内部允许）
