## Why

调试追踪逻辑散落在两处问题：
1. `app.py:12-14` 在 import 时硬编码 `config.DEBUG = True` + `apply_patches()` + `logger.info`，import 即产生副作用（猴补丁 BabelDOC 私有类、强制开调试），测试与生产导入 app 即受污染。
2. `routes.py` 的 `translate_page` 内 `if config.DEBUG` 散落 20+ 处（日志创建、文件 handler、step 计时、token 用量、术语合并追踪），业务逻辑与调试横切关注点深度耦合。

这导致难以关闭调试、难以测试无调试路径、业务代码 readability 差。

## What Changes

- 抽出独立 `debug_trace.py` 模块，封装所有调试追踪逻辑：
  - `init_debug(config_obj)`：条件性应用猴补丁（仅在 DEBUG=True 时）
  - `DebugSession` 上下文管理器：管理 per-translation 的 file handler 添加/移除、日志轮转
  - `log_step(name, **kwargs)` / `log_token_usage(...)` / `log_glossary_merge(...)`：业务代码调用这些接口而非内联 `if config.DEBUG`
- `app.py` 移除 import 时副作用：`config.DEBUG` 改由配置或 CLI 参数驱动（不再硬编码 True）；`init_debug` 在 `create_app` 内显式调用
- `routes.py:translate_page` 的调试逻辑替换为 `debug_trace` 模块调用
- 调试能力（日志格式、轮转、追踪内容）行为等价，现有 debug-tracing 测试保持通过

## Capabilities

### New Capabilities

- `debug-trace-module`: 调试追踪模块——将散落于 `app.py`/`routes.py` 的调试逻辑集中为独立模块，业务代码通过统一接口调用，import 无副作用

### Modified Capabilities

- `debug-tracing`: 现有调试追踪需求的实现方式变更——`config.DEBUG` SHALL 由配置/CLI 驱动而非硬编码；猴补丁 SHALL 条件性应用；业务代码 SHALL 通过 `debug_trace` 模块接口而非内联 `if config.DEBUG` 记录追踪
- `code-quality-foundations`: "模块化源码组织"需求——`app.py` SHALL 无 import 时副作用；调试追踪 SHALL 独立模块

## Impact

- **代码**：新增 `debug_trace.py`；`app.py`（移除 `config.DEBUG=True`/`apply_patches()` import 时调用）；`routes.py`（调试逻辑替换为模块调用）；`debug_patches.py`（可能并入 `debug_trace.py` 或保留为内部实现）
- **配置**：`config.toml` 可能新增 `[debug] enabled` 或复用 `server.debug`；CLI `--debug` flag 保持
- **API**：无影响
- **测试**：现有 `test_debug_patches.py` 等价回归；新增无调试路径测试（DEBUG=False 时无猴补丁、无 file IO）
- **风险**：需保证 DEBUG=True 时追踪内容字节等价；与变更 B 协同（B 的 service 层调用 debug_trace 接口）
