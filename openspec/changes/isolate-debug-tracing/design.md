## Context

调试追踪现状：
- `app.py:12-14`：`config.DEBUG = True`（硬编码）→ `apply_patches()`（猴补丁 `AutomaticTermExtractor`）→ `logger.info("Debug tracing enabled")`，import 时即执行
- `routes.py:translate_page`：`if config.DEBUG` 散落 20+ 处——file handler 创建/轮转、step 计时、token 用量、术语合并追踪，与业务编排交织
- `debug_patches.py`：猴补丁实现，无条件应用

约束：DEBUG=True 时追踪内容（日志格式、轮转、字段）字节等价；DEBUG=False 时零开销（无猴补丁、无 file IO）；与变更 B 协同（service 层调用 debug_trace 接口）。

## Goals / Non-Goals

**Goals:**
- `app.py` import 无副作用（无强制 DEBUG、无条件猴补丁）
- `config.DEBUG` 由 `config.toml` 或 CLI `--debug` 驱动
- 业务代码调用 `debug_trace` 模块接口，无内联 `if config.DEBUG`
- DEBUG=False 时零开销
- DEBUG=True 时追踪内容字节等价

**Non-Goals:**
- 不改追踪日志的内容/格式
- 不改 debug_trace.log 轮转策略
- 不改猴补丁的追踪字段（BabelDOC 升级适配另行处理）

## Decisions

### 决策 1：`debug_trace.py` 模块接口

**选择**：
```python
# debug_trace.py
def init_debug(debug_enabled: bool) -> None:
    """条件性应用猴补丁，仅 debug_enabled=True 时。"""

@contextmanager
def debug_session(log_path: Path | None):
    """per-translation 上下文：添加 file handler、轮转旧日志；退出时移除。"""

def log_step(name: str, **fields) -> None: ...        # 替代内联 if config.DEBUG: trace_logger.info("[step] ...")
def log_token_usage(usage: dict) -> None: ...
def log_glossary_merge(action: str, **fields) -> None: ...
```
所有函数内部判断 `config.DEBUG`，业务代码无 `if config.DEBUG`。

**备选**：
- (a) 装饰器 `@trace_step`——表达力强但改控制流，与现有计时逻辑结构差异大
- (b) logging filter——不解决猴补丁与 file handler 管理

**理由**：显式函数调用最接近现状结构，迁移机械、风险低。

### 决策 2：去除 app.py import 副作用

**选择**：
- `config.DEBUG` 改由 `config.toml` 的 `[server] debug` 或 `[debug] enabled` 读取（默认 False），CLI `--debug` 覆盖
- `app.py:create_app` 内显式调用 `debug_trace.init_debug(config.DEBUG)`
- 删除 `app.py:12-14` 的模块级副作用

**备选**：保留模块级 `apply_patches()` 但条件化——仍有 import 时副作用，测试导入 app 即受影响。

**理由**：`create_app` 是显式初始化点，测试可控制是否启用调试。

### 决策 3：debug_patches 并入 debug_trace

**选择**：`debug_patches.py` 的猴补丁逻辑并入 `debug_trace.init_debug` 内部实现（私有函数），`debug_patches.py` 可保留为薄 wrapper 或删除。倾向并入以单一来源。

**理由**：猴补丁是调试追踪的实现细节，应封装在 debug_trace 内。

### 决策 4：DEBUG=False 零开销

**选择**：`log_step` 等函数在 `config.DEBUG=False` 时立即 return（无字符串格式化、无 IO）；`init_debug(False)` 不应用猴补丁。

**理由**：对齐现有 `debug-tracing` spec "Debug mode disabled (default)... zero overhead" 需求。

## Risks / Trade-offs

- [追踪内容字节漂移] → 现有 `test_debug_patches.py` + 新增字节等价测试捕获
- [与变更 B 协同] → debug_trace 接口先行定义，B 的 service 调用之；两变更可并行设计
- [config.DEBUG 来源切换可能影响现有用户] → `config.toml` 默认值与 CLI 保持向后兼容；文档说明
