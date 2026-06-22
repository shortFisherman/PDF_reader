## Context

当前项目后端代码结构是在多次功能迭代中逐步形成的，缺乏一次系统性的模块边界整理。核心问题：

1. `services.py` 成为"杂物堆"——5 个互不相关的函数（SHA256、PDF 渲染、引擎查找、引擎参数映射、设置组装）共用一个文件
2. `sse_stream.py` 的 `generate()` 承担了翻译生命周期管理（replace_page、merge_after_translate、临时目录清理），已超出"SSE 格式化"的职责边界
3. `GenerateContext` 直接传递整个 `AppState` 对象，暴露了 `sse_stream.py` 不需要的全部接口
4. `glossary_service.py` 依赖 `AppState` 类型但实际只使用 `.glossary_cache_path` 属性
5. `debug_trace.py` 中 `debug_session` 上下文管理器和 `setup_file_handler`/`cleanup_file_handler` 存在重复的文件 handler 创建逻辑

**约束**：不修改功能行为、不修改前端、不修改测试逻辑（仅调整 import）、保持 ruff 零错误、保持 111 个测试全通过。

## Goals / Non-Goals

**Goals:**
- 每个 .py 文件有单一、明确的职责
- 模块间依赖最小化，不传递不需要的完整对象
- 新模块命名直观，见名知义
- 消除 debug_trace.py 内部重复

**Non-Goals:**
- 不改变任何功能行为
- 不修改 `config.py`、`config.toml`、`state.py`、`routes.py`、`translation_orchestrator.py`、`pdf_extraction.py` 的核心逻辑
- 不修改前端代码
- 不新增或删除测试用例（仅调整 import 路径）

## Decisions

### Decision 1: services.py 拆分为 3 个模块

**选择方案**：按函数职责拆分为 `file_hash.py`、`engine_resolver.py`、`pdf_renderer.py`

```
Before:  services.py (120 lines, 5 functions)
After:
  file_hash.py       ← sha256()
  engine_resolver.py  ← resolve_engine(), build_engine_kwargs(), CONFIG_ATTR_MAP
  pdf_renderer.py     ← render_page(), build_settings()
```

- `sha256()` 是纯文件操作，与翻译引擎或 PDF 无关，独立后可在任何地方复用
- `resolve_engine()` + `build_engine_kwargs()` + `CONFIG_ATTR_MAP` 三者紧密相关：引擎查找 → 参数映射 → 配置属性映射表，放一起是自然的
- `render_page()` 和 `build_settings()` 都依赖 pymupdf + pdf2zh-next 的 SettingsModel，虽然它们做的事不同，但 `build_settings` 是翻译流程的入口点，`render_page` 是渲染流程的入口点。拆为两个独立文件会让路由层 `from pdf_renderer import render_page, build_settings` 变成两行 import。权衡后保持在一起：它们共同构成"pdf2zh-next 相关操作的入口"。

**备选方案**：拆成 5 个单函数文件。过于碎片化，拒绝。

### Decision 2: 抽取翻译生命周期到 `translation_lifecycle.py`

**选择方案**：新建 `translation_lifecycle.py`，容纳翻译完成后的所有后处理逻辑

```python
# sse_stream.py (瘦身后):
def generate(ctx):       # 只负责: debug_session → run_translation → format_sse_event → yield
    for evt in run_translation(...):
        yield format_sse_event(evt)
    # 翻译完成后委托出去
    finish_translation(ctx)  # → translation_lifecycle.py
    yield progress:100 + finish

# translation_lifecycle.py (新增):
def finish_translation(ctx):  # replace_page + merge_after_translate
```

**备选方案**：在 `routes.py` 中协调，翻译完成后显式调用 replace + merge。会导致路由层变厚，违背"路由层薄"的设计原则，拒绝。

### Decision 3: 缩小接口依赖

**GenerateContext 不再包含 `state: AppState`**：
- `sse_stream.generate()` 需要的是"完成翻译后做什么"，不需要整个 `AppState`
- 改动：`GenerateContext` 中 `state` 替换为 `replace_page: Callable` + `glossary_cache_path: Path | None`
- 路由层在构造 `GenerateContext` 前将 `state.replace_page` 和 `state.glossary_cache_path` 提取为局部值

**glossary_service.py 参数类型缩小**：
- `resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)`
- `merge_after_translate` 不变（已经只依赖 Path）

### Decision 4: 消除 debug_trace.py 重复

`debug_session` 上下文管理器和 `setup_file_handler`/`cleanup_file_handler` 做同样的事。选择方案：

- 将 `setup_file_handler` 的逻辑内联到 `debug_session` 的 `__enter__`，`cleanup_file_handler` 内联到 `__exit__`
- 删除独立的 `setup_file_handler` 和 `cleanup_file_handler`（确认没有外部调用者后删除）

## Risks / Trade-offs

- **[Risk] 测试文件 import 路径变化** → Mitigation: 运行全部 111 个测试，逐一修正
- **[Risk] 循环导入** → Mitigation: 新模块坚持单向依赖（路由层 → lifecycle → state，不反向）
- **[Risk] ruff 规则冲突** → Mitigation: 新文件遵循现有 ruff.toml 配置，完成后运行 `ruff check`

## Open Questions

无。所有问题已在分析阶段明确。
