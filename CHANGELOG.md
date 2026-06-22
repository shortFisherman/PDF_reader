# 更新日志

## 2026-06-22 — 模块内聚性重构

### `refactor-module-cohesion`

**解决 `services.py` 杂物堆、`sse_stream.py` 职责越界、接口耦合过大等问题：**

| 改动 | 说明 |
|------|------|
| `services.py` → **删除** | 5 个函数按职责拆分到 4 个新模块 |
| `file_hash.py` — **新增** | `sha256()` 纯文件哈希，无其他模块依赖 |
| `engine_resolver.py` — **新增** | `resolve_engine()` + `build_engine_kwargs()` + `CONFIG_ATTR_MAP` |
| `pdf_renderer.py` — **新增** | `render_page()` + `build_settings()` |
| `translation_lifecycle.py` — **新增** | `finish_translation()` — 翻译后持久化、术语合并、清理 |
| `sse_stream.py` — **修改** | `GenerateContext` 不再持有 `AppState`，后处理委托给 `translation_lifecycle` |
| `glossary_service.py` — **修改** | `resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)` |
| `debug_trace.py` — **修改** | 删除 `setup_file_handler` / `cleanup_file_handler` 重复函数，合并入 `debug_session` |

**关键设计决策：**
- `GenerateContext` 从持有整个 `AppState` 缩小为 `replace_page: Callable` + `glossary_cache_path: Path | None`，页面号在 routes.py 中由 lambda 预绑定
- `translation_lifecycle.finish_translation()` 承担 replace_page + merge_after_translate + rmtree，`sse_stream.generate()` 回归纯 SSE 格式化
- 逐组推进 + 逐组测试：4 个任务组各以 `pytest tests/ -v` 为安全门
- 13 个子代理分派执行，14 个 commit

**测试：** 106 个测试全通过，ruff 零错误

---

## 2026-06-21 — 大规模优化重构

### A. 强化 PDF 状态并发安全 (`harden-pdf-state-concurrency`)

**修复两处运行时代码缺陷：**

- **渲染竞态修复** — `AppState.render_page` 原实现在锁外执行 pymupdf 渲染，并发 `replace_page` 关闭/重开 doc 可导致段错误。修复后渲染全程持 `_lock`，消除竞态窗口。
- **页码校验** — `/api/translate/<page>` 新增越界检查，`page < 0` 或 `page >= page_count` 返回 `400` 而非触发底层 `pymupdf.insert_pdf` 异常。
- 结论：单锁架构已正确，无需双层锁。保留 `test_concurrent_replace_different_pages` 作回归保护。

**涉及文件：** `state.py`、`routes.py`、`tests/test_state.py`、`tests/test_routes.py`

---

### B. 抽取翻译服务层 (`extract-translation-service-layer`)

**`routes.py:translate_page` 从 230 行巨函数薄化为 ≤20 行路由层，拆分为 5 个独立服务模块：**

| 模块 | 职责 | 接口 |
|------|------|------|
| `pdf_extraction.py` | 单页 PDF 抽取 | `extract_single_page(doc, page, tmpdir) -> Path` |
| `translation_orchestrator.py` | 翻译编排（asyncio 线程+事件队列） | `run_translation(settings, pdf) -> Iterator[dict]` |
| `sse_stream.py` | SSE 事件格式化+流程组合 | `generate(ctx: GenerateContext) -> Iterator[str]` |
| `glossary_service.py` | 术语表路径解析+翻译后合并 | `resolve_glossary_paths(state)`, `merge_after_translate(...)` |
| `debug_trace.py` | 调试追踪（骨架接口，变更 D 增强） | `log_step`, `log_token_usage`, `setup_file_handler`, `cleanup_file_handler` |

**关键设计决策：**
- 全部模块暴露纯函数，无类样板代码
- `TranslationError` 异常在迭代结束后传播，替代 `error_info` 字符串
- `GenerateContext` dataclass 打包组合参数
- `format_sse_event` 纯函数，字节级黄金样本回归测试保证兼容
- `finally` 块统一清理临时目录

**涉及文件：** 新增 5 个模块 + 对应测试文件

---

### C. 数据驱动引擎配置 (`data-driven-engine-config`)

**用声明式 `EngineSpec` 注册表替代硬编码的 `PROVIDER_MAP`（10 条目）+ `FIELD_MAP`（79 条目）：**

```python
@dataclass(frozen=True)
class EngineSpec:
    provider: str           # 引擎标识
    settings_cls: type      # pdf2zh-next Settings 类
    field_map: dict         # unified_name → engine_field_name
    required_fields: tuple  # 必填字段

ENGINE_REGISTRY = [EngineSpec(...), ...]  # 10 引擎，各一行
```

**收益：**
- 新增引擎仅需追加一行 `EngineSpec`，不再需在 ~10 处各加条目
- `build_engine_kwargs` 遍历 `spec.field_map` 动态构造参数，不再硬编码 8 个字段名
- 运行时 `model_fields` 检查，对 pdf2zh-next 版本升级有容错
- 等效性回归测试覆盖全部 10 引擎新旧输出对比

**涉及文件：** `config.py`（+EngineSpec, -PROVIDER_MAP, -FIELD_MAP）、`services.py`、新增 `tests/test_engine_registry.py`

---

### D. 隔离调试追踪 (`isolate-debug-tracing`)

**消除 import-time 副作用，调试逻辑完全隔离：**

- **消除副作用** — `app.py` 不再在 import 时硬编码 `config.DEBUG = True` 或无条件 monkey-patch。改用 `--debug` CLI 参数 + `config.toml` 的 `[debug]` 段驱动。
- **配置优先级** — CLI `--debug` > `[debug] enabled` > `[server] debug` > 默认 `False`
- **统一模块** — `debug_patches.py` 删除，逻辑并入 `debug_trace.py`。暴露接口：`init_debug()`、`debug_session`（上下文管理器）、`log_step`、`log_token_usage`、`log_glossary_merge`
- **零开销** — `config.DEBUG = False` 时所有调试函数立即返回，无字符串格式化、无 IO、无 handler 创建
- **容错降级** — monkey-patch 失败仅记日志不崩溃，文件 handler 创建失败静默降级

**涉及文件：** `debug_trace.py`（+176行）、`app.py`（-副作用，+argparse）、`config.py`（+`_resolve_debug`）、`sse_stream.py`（`debug_session` 上下文）、删除 `debug_patches.py`

---

### E. 前端模块化 (`modularize-frontend`)

**`static/app.js` 从 335 行单体文件拆分为 6 个 ES Module：**

| 模块 | 职责 | 行数 |
|------|------|------|
| `app.js` | 入口，持有共享状态，绑定事件 | ~60 |
| `modules/dom.js` | DOM 引用、元素创建、占位符计算 | ~75 |
| `modules/sse-client.js` | SSE 流解析（纯函数，无 DOM） | ~30 |
| `modules/scroll-sync.js` | 滚动同步 + 页码检测 | ~50 |
| `modules/lazy-loader.js` | IntersectionObserver 懒加载 | ~30 |
| `modules/stages.js` | 从后端 `/api/stages` 拉取阶段标签 | ~30 |
| `modules/translator.js` | 翻译编排（回调驱动，无 DOM） | ~50 |

**关键设计决策：**
- `index.html` 改用 `<script type="module">`
- `STAGE_LABELS` 前端不再硬编码，改为 `GET /api/stages` 拉取，失败时回退内置副本
- 模块为无状态工具函数，共享状态集中在 `app.js`
- 前端 UX 字节级兼容，无需构建工具

**涉及文件：** `static/` 目录重构、`templates/index.html`、`routes.py`（+`/api/stages` 端点）

---

### 统计

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 后端模块 | 7 | 14 |
| 前端模块 | 1 | 7 |
| 单元测试 | 45 | 106 |
| OpenSpec specs | 9 | 17 |
| routes.py 最大函数 | 230 行 | ~30 行 |
| 引擎配置新增成本 | ~10 处修改 | 1 行 |
| 调试副作用 | import 时触发 | CLI/config 驱动 |
