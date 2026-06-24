# 更新日志

## 2026-06-24 — 修复初始加载不触发 & 滚动同步拖拽感

### `fix-initial-load-and-sync-lag`

**现象：** `fix-lazy-load-scroll` 引入的 settle gate（150ms 去抖）带来两个回归：(1) 打开 PDF 后不做任何操作，页面始终不加载，必须手动滚动才会触发；(2) 双栏滚动同步用 `requestAnimationFrame` 延迟 1 帧，拖动时有明显滞后/拖拽感。

**根因：**
- **(1)** settle gate 的 `onSettle` 回调仅在 scroll 事件驱动下触发。初始无 scroll → timer 不启动 → IO 标记的 `pendingLoad` 永远不被扫描。随后用 `setTimeout(0)` + `trigger()` 尝试修复，但 `setTimeout` 在浏览器事件循环中可能先于 IntersectionObserver 回调触发（rendering update 可被跳过）→ `pendingLoad` 仍为空 → 空扫。
- **(2)** `setupScrollSync` 用 `requestAnimationFrame` 将对侧 `scrollTop` 赋值推迟到下一帧，连续拖动时每帧晚 1 帧 (~16ms) → 视觉拖拽感。

**修复：**

| # | 说明 | 文件 |
|---|------|------|
| 1 | 初始加载：`setupIntersectionObserver` 内用 `requestAnimationFrame` 做直接视口扫描，绕过 settle gate，不依赖 IO 时序 | `lazy-loader.js`, `app.js` |
| 2 | 滚动同步：rAF 替换为同步 `scrollTop` 赋值 + `setTimeout(0)` 解锁反回环 guard | `scroll-sync.js` |
| 3 | 内联测试 & delta spec 更新 | `scroll-sync.js`, `lazy-loading/spec.md`, `dual-column-reading/spec.md` |

**关键决策：** 初始加载不用 settle scan 路径，改在 `lazy-loader.js` 内以 rAF 直接扫描 `getBoundingClientRect`——此时布局已计算、几何可信，与 IO 回调时序完全解耦。`trigger()` 方法保留但不再用于初始加载。

**delta spec：** lazy-loading +1 added，dual-column-reading +3 modified

**测试：** 107/107 Python tests pass，4 个 settle gate inline tests

---

## 2026-06-24 — 修复懒加载与滚动同步

### `fix-lazy-load-scroll`

**现象：** 三个前端交互缺陷严重影响大文档可读性：(1) 拖滚动条长距离跳转淹没 ~500 次 `/api/page/*` 请求；(2) 左右两栏单向绝对 scrollTop 同步导致错位，图片加载后高度跳变出现"一边塞两页"；(3) 翻页边界 `load→unload→load` 振荡与重复请求。

**根因：** 懒加载与滚动同步的脆弱设计——IO 即时加载无去抖、单向绝对值同步不兼容双栏高度差、加载卸载无统一闸门。

**修复（16 任务，5 组）：**

| 组 | 说明 | 文件 |
|---|---|---|
| 1 | 滚动稳定闸门（150ms settle gate） | `scroll-sync.js`, `app.js` |
| 2 | CSS `width:100%` 消除布局跳变 | `style.css`, `dom.js` |
| 3 | 双向按比例滚动同步（rAF + syncing 防回环） | `scroll-sync.js` |
| 4 | 懒加载重构：IO 降级为候选标记器 + 落点加载 + 延迟卸载（RECLAIM_DISTANCE=10）+ 容器级 `dataset.loaded` 守卫 | `lazy-loader.js`, `app.js` |
| 5 | 手动回归验证 | — |

**架构核心：** 引入 settle gate 统一收敛所有 load/unload/page-detection 到滚动停止后执行。IO 观察者不再直接调用 load/unload，改为仅标记 `pendingLoad`/`pendingReclaim` 候选集；settle 扫描时仅对视口 ±2 页加载，扫过页丢弃；离开视口 >10 页且在 settle 后确认才卸载。

**关键参数：** `SETTLE_MS=150`, `BUF=2`, `RECLAIM_DISTANCE=10`, IO `rootMargin=200%`

**执行方式：** subagent-driven development，每任务 TDD（RED→GREEN）+ spec review + quality review，最终审查发现并修复 settle gate 回调一次性失效的 critical bug。

**delta spec：** lazy-loading +2 added / +3 modified，dual-column-reading +3 modified

**测试：** JS inline tests 57 个全通过，前端手动回归 4 场景

---

## 2026-06-23 — 修复术语累计功能失效 + 拆分 pdf_renderer.py 双重职责

### `fix-glossary-merge-bom` — 术语累计失效修复

**现象：** 翻译论文后从不生成 `cumulative_glossary.csv`，跨页术语一致性功能完全失效。调试日志显示术语提取正常运行（消耗 token），但合并步骤 `elapsed=0.00`（空操作）。

**根因：** BOM 编码不匹配。babeldoc 用 `utf-8-sig`（带 BOM 头）写入自动提取的术语表 CSV，但 `glossary_merger.py` 用 `utf-8`（不处理 BOM）读取。BOM 字符 `\ufeff` 粘到第一列名上，`csv.DictReader` 看到的是 `\ufeffsource` 而非 `source`，`row.get("source")` 全部返回 `None`，所有术语被静默丢弃，`source_targets` 为空导致不写文件。

**修复：**
| 文件 | 改动 |
|------|------|
| `glossary_merger.py` | 两处 CSV 读取编码 `utf-8` → `utf-8-sig`（剥离 BOM，对无 BOM 文件安全） |
| `glossary_merger.py` | 术语文件未找到时补 warning 日志（原静默返回） |
| `glossary_service.py` | 跳过合并时补 warning 日志，输出两路径值便于排查 |
| `tests/test_glossary_merger.py` | 新增 `test_bom_encoded_auto_glossary_is_merged` 回归测试，模拟 babeldoc 真实输出格式（BOM + 3 列 `source,target,tgt_lng`） |

**测试：** 107 个测试全通过，ruff 零错误

---

## 2026-06-23 — 拆分 pdf_renderer.py 双重职责

### `split-pdf-renderer`

`pdf_renderer.py` 包含两个无关函数：`render_page()`（渲染 PNG）和 `build_settings()`（组装翻译参数）。拆分为独立模块：

| 改动 | 说明 |
|------|------|
| `translation_settings.py` — **新增** | 迁入 `build_settings()`，负责组装 pdf2zh-next 翻译参数 |
| `pdf_renderer.py` — **精简** | 删除 `build_settings()` 及相关 import，回归单一职责：PDF 页面渲染 |
| `routes.py` — **修改** | import 从 `pdf_renderer` 改为 `translation_settings` |
| `tests/test_services.py` — **修改** | 同上 |

---

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
