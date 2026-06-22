---
comet_change: refactor-module-cohesion
role: technical-design
canonical_spec: openspec
---

# Refactor Module Cohesion — Technical Design

## Context

当前项目后端代码结构是在多次功能迭代中逐步形成的，缺乏一次系统性的模块边界整理。核心问题：

1. `services.py` 成为杂物堆——5 个互不相关的函数（SHA256、PDF 渲染、引擎查找、引擎参数映射、设置组装）共用一个文件，每次新加工具函数都会自然地塞到这里
2. `sse_stream.py` 的 `generate()` 承担了翻译生命周期管理（replace_page、merge_after_translate、临时目录清理），已超出 SSE 格式化的职责边界
3. `GenerateContext` 直接传递整个 `AppState` 对象，暴露了 sse_stream 不需要的全部接口
4. `glossary_service.py` 依赖 `AppState` 类型但实际只使用 `.glossary_cache_path` 属性
5. `debug_trace.py` 中 `debug_session` 和 `setup_file_handler`/`cleanup_file_handler` 存在代码重复

**约束**：不修改功能行为、不修改前端、不修改测试逻辑（仅调整 import 路径）、保持 ruff 零错误、保持 111 个测试全通过。

## Decisions

### Decision 1: services.py 拆分为 3 个模块

```
Before:  services.py (120 lines, 5 unrelated functions)
After:
  file_hash.py         ← sha256()
  engine_resolver.py    ← resolve_engine(), build_engine_kwargs(), CONFIG_ATTR_MAP
  pdf_renderer.py       ← render_page(), build_settings()
```

**Why this grouping:**
- `sha256()` 是纯文件操作，与翻译引擎或 PDF 无关，独立后可在任何地方复用。放入 `file_hash.py` 后，其他模块 import 时不会意外地拖入 pymupdf 或 pdf2zh-next
- `resolve_engine()` + `build_engine_kwargs()` + `CONFIG_ATTR_MAP` 三者紧密相关：引擎查找 → 参数映射 → 配置属性映射表。放一起遵循"共同修改的东西放在一起"原则
- `render_page()` 和 `build_settings()` 都依赖 pymupdf + pdf2zh-next 的 SettingsModel。如果拆为两个文件，路由层需要两行独立 import（`from pdf_renderer import render_page` + `from settings_builder import build_settings`），反而增加了耦合面的数量

**Alternative considered**: 拆成 5 个单函数文件（`sha256.py`、`render_page.py`、`resolve_engine.py` 等）。过于碎片化——一个目录里 16 个文件的认知负担比 14 个更大。

### Decision 2: 抽取翻译生命周期到 translation_lifecycle.py

```
Before — sse_stream.generate() does everything:
  for evt in run_translation(...):
      yield format_sse_event(evt)
  state.replace_page(...)           ← not SSE's job
  merge_after_translate(...)        ← not SSE's job
  yield progress:100 + finish
  shutil.rmtree(...)                ← not SSE's job

After — sse_stream.generate() delegates:
  for evt in run_translation(...):
      yield format_sse_event(evt)
  finish_translation(ctx)           ← delegated to translation_lifecycle.py
  yield progress:100 + finish
```

`translation_lifecycle.finish_translation()` 接收 `translate_result` + `replace_page` 回调 + `glossary_cache_path` + 临时目录路径，负责：页面替换 → 术语合并 → 目录清理。

**Alternative considered**: 在 `routes.py` 中协调后处理（翻译完成后显式调用 replace + merge）。会导致路由层变厚，违背"路由层薄"的设计原则。拒绝。

### Decision 3: 缩小接口依赖

**GenerateContext 不再持有 AppState**：

```python
# Before
@dataclass
class GenerateContext:
    state: AppState        # 泄漏了全部 state 接口
    ...

# After
@dataclass
class GenerateContext:
    replace_page: Callable                    # 只需要替换页面的能力
    glossary_cache_path: Path | None           # 只需要缓存路径
    ...
```

路由层在构造 GenerateContext 前从 state 提取必要值：
```python
ctx = GenerateContext(
    replace_page=state.replace_page,
    glossary_cache_path=state.glossary_cache_path,
    ...
)
```

**glossary_service 参数缩小**：
```python
# Before
def resolve_glossary_paths(state: AppState) -> list[str] | None:
    cache_path = state.glossary_cache_path  # 实际只用这一个属性

# After
def resolve_glossary_paths(cache_path: Path | None) -> list[str] | None:
    # 不需要 AppState
```

### Decision 4: 消除 debug_trace.py 重复

`debug_session` 上下文管理器和 `setup_file_handler`/`cleanup_file_handler` 做同样的事。选择方案：将 file handler 创建/清理逻辑合并入 `debug_session`，删除独立的 `setup_file_handler` 和 `cleanup_file_handler`。

确认无外部调用者后安全删除。

## Risks / Trade-offs

| Risk | Mitigation |
|------|-----------|
| 循环导入（新模块互相引用） | 坚持单向依赖：routes → lifecycle → state，不反向。新模块只 import 标准库 + 已有模块 |
| 测试 import 路径变化导致失败 | 逐组完成后立即跑 pytest tests/ -v，不等到全部改完 |
| `build_settings` 拆到 pdf_renderer.py 后 pdf2zh-next 导入链变化 | import 语句本身不变（仍从 pdf2zh_next 导入 SettingsModel 等），只改 `from X import build_settings` |
| `render_page` 在 state.py 中作为参数传入 | state.py 使用 `from services import render_page`，改为 `from pdf_renderer import render_page` |
| `CONFIG_ATTR_MAP` 被外部 import | 确认只有 services.py 内部使用，迁移到 engine_resolver.py 后更新调用者 |

## Implementation Strategy

逐组推进、逐组验证：

```
Group 1: 拆分 services.py (tasks 1.1–1.7)
    → pytest tests/ -v  ← 必须全通过
Group 2: 抽取 lifecycle (tasks 2.1–2.5)
    → pytest tests/ -v  ← 必须全通过
Group 3: 缩小接口 (tasks 3.1–3.3)
    → pytest tests/ -v  ← 必须全通过
Group 4: 消除 debug 重复 (tasks 4.1–4.3)
    → pytest tests/ -v  ← 必须全通过
Final:  ruff check .       ← 必须零错误
```

## Testing Strategy

- 每组任务完成后运行 `pytest tests/ -v`
- 如果失败，修复当前组的代码直到全通过才进入下一组
- 不新增或删除测试用例（重构不改行为）
- 仅调整测试文件中的 import 路径以适配新模块

## File Changes Summary

| File | Action |
|------|--------|
| `services.py` | **DELETE** |
| `file_hash.py` | **NEW** — sha256() |
| `engine_resolver.py` | **NEW** — resolve_engine(), build_engine_kwargs(), CONFIG_ATTR_MAP |
| `pdf_renderer.py` | **NEW** — render_page(), build_settings() |
| `translation_lifecycle.py` | **NEW** — finish_translation() |
| `sse_stream.py` | **MODIFY** — GenerateContext 字段变更 + generate() 瘦身 |
| `routes.py` | **MODIFY** — 更新 import + GenerateContext 构造 |
| `glossary_service.py` | **MODIFY** — 参数类型缩小 |
| `state.py` | **MODIFY** — import 路径调整 |
| `debug_trace.py` | **MODIFY** — 合并重复逻辑 |
| `tests/test_services.py` | **MODIFY** — import 路径调整 |
| `tests/test_sse_stream.py` | **MODIFY** — 适配新 GenerateContext |
| `tests/test_glossary_service.py` | **MODIFY** — 适配新参数 |
| `tests/test_debug_trace.py` | **MODIFY** — 移除已删除函数测试 |
| `tests/test_state.py` | **POSSIBLY MODIFY** — import 路径调整 |
