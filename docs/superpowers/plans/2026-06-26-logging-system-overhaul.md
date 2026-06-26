---
change: logging-system-overhaul
design-doc: docs/superpowers/specs/2026-06-26-logging-system-overhaul-design.md
base-ref: 022162846f082e987df8eb9ab1c0cc081c22ab7b
---

# 实现计划：Logging System Overhaul

> 配套设计文档 `docs/superpowers/specs/2026-06-26-logging-system-overhaul-design.md`（下文以 §节号引用其决策）与 OpenSpec 变更 `logging-system-overhaul` 的 `tasks.md`。本计划把 6 组 26 项任务展开为可执行步骤，保留原分组与编号，补充：改动文件/函数、改动要点、完成判定、依赖关系、TDD 标记。
>
> 本计划只描述「改什么、为什么、如何验证」，不含代码实现。

## 0. 全局约定

- **Logger 命名空间**：统一 `pdf_reader.<concern>`，每个模块顶部 `logger = logging.getLogger("pdf_reader.<concern>")`，禁止再用匿名 root 或裸 `logging.getLogger("pdf_reader")`（§2.2）。
- **级别策略**（§2.3）：ERROR=请求级失败；WARNING=可恢复降级；INFO=流程里程碑常驻；DEBUG=高频/细节。
- **page 关联前缀**（§2.4）：翻译流日志消息自带 `[page=N]` 或 `[batch=from-to]`，由调用点拼入消息文本，formatter 不注入。
- **debug 开关语义**：只控制根 `pdf_reader` logger 级别（off=INFO / on=DEBUG）与第三方是否可见，**不再**控制「有无流程日志」（§2.3）。
- **安全**：任何日志不得输出 `api_key` / `MODEL_API_KEY` 原值；settings 摘要只取 provider/model/lang/path（§2.6、§4.4）。

## 依赖顺序总览

```
1.1 → 1.2 → 1.3 → 1.4 ─┐
                        ├→ 2.3 → 2.2 → 2.1 → 2.4
                        │        (2.1 可先于 2.2)
                        ├→ 3.1 ─┐
                        │       ├→ 3.4 ↔ 3.5 → 3.6
                        │       │
                        │   3.2, 3.3, 3.7, 3.8, 3.9, 3.10（彼此独立，1.1 后即可）
                        │
                        └→ 4.1（依赖 1.4 + 3.10）→ 4.2

5.x 测试：5.2 随 1.x（TDD 先红）；5.1 随 2.x；5.3/5.4 随 3.x（TDD 先红）；5.5 随 4.x；5.6 随 1.4/2.4
6.x 收尾：全部实现与测试完成后
```

关键耦合：**3.4 与 3.5 必须一起改**——`run_translation` 新增 `flow_label` 形参（3.4），`sse_stream` 调用处传入 `flow_label="page=N"` / `"batch=from-to]"`（3.5），二者同一次提交完成，否则签名不匹配会破坏现有 SSE。

## TDD 标记说明

- **[TDD]**：建议先写对应失败测试（红）再实现（绿）。这些任务的对应测试在「第 5 组」，按 TDD 应**提前**到该任务之前执行。
- **[TDD-可选]**：可写测试但实现简单，先实现再补测亦可。
- **[非TDD]**：纯删除/文档/配置类，无行为可先测，直接改 + 事后回归。

---

## 1. 日志配置基础设施

### 1.1 新建 `logging_config.py` 与 `setup_logging` — [TDD]（对应 5.2 先红）

- **改文件**：新建 `logging_config.py`
- **改函数**：新增 `setup_logging(debug: bool) -> None`
- **改动要点**（§2.1、§2.5）：
  - 创建 `logs/` 目录（若缺）。
  - formatter：`"%(asctime)s %(levelname)s %(name)s [%(message)s]"`（page 前缀由消息自带，formatter 不注入）。
  - `console = StreamHandler(sys.stdout)`，level 随 debug（off=INFO / on=DEBUG）。
  - `file = RotatingFileHandler("logs/pdf_reader.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")`。
  - `root_pdf = getLogger("pdf_reader")`；`setLevel(DEBUG if debug else INFO)`；`addHandler(console)`、`addHandler(file)`。
  - 幂等：重复调用不重复叠加 handler（先清 `pdf_reader` 上已有 handler 或判断已存在）。
- **logger/级别**：本任务配置根 `pdf_reader`，本身不发日志。
- **完成判定**：`setup_logging(False)` 后 `getLogger("pdf_reader")` 恰有 1 个 `StreamHandler` + 1 个 `RotatingFileHandler`；`setup_logging(True)` 后根级别为 DEBUG；formatter 一致。
- **依赖**：无（基础设施最先）。
- **TDD**：先写 `tests/test_logging_config.py` 的 handler/级别断言（5.2 的前半），运行见红，再实现。

### 1.2 第三方 logger 降级 DEBUG — [TDD]（并入 5.2）

- **改文件**：`logging_config.py`
- **改函数**：`setup_logging` 内追加
- **改动要点**（§2.1、§2.5 风险行）：`getLogger("werkzeug").setLevel(DEBUG)`、`getLogger("pdf2zh_next").setLevel(DEBUG)`、`getLogger("babeldoc").setLevel(DEBUG)`。子 logger 继承顶层，无需逐个设。
- **完成判定**：`setup_logging(False)` 后三者 effective level 为 DEBUG；debug off 时 werkzeug 每请求 INFO 不进控制台/文件。
- **依赖**：1.1（同函数体内）。

### 1.3 `logs/` 目录与入库策略 — [TDD-可选]（并入 5.2）

- **改文件**：新建 `logs/.gitkeep`；`.gitignore` 追加 `logs/*.log*`
- **改动要点**（§2.5）：`logs/.gitkeep` 入库保证目录存在；日志文件本身不入库。`setup_logging` 内 `Path("logs").mkdir(parents=True, exist_ok=True)`。
- **完成判定**：`logs/` 目录存在且含 `.gitkeep`；`git status` 不跟踪 `logs/*.log`；`setup_logging` 后 `logs/pdf_reader.log` 可写。
- **依赖**：1.1。

### 1.4 `app.py` 替换 `basicConfig` 为 `setup_logging` — [TDD]（对应 5.6 先红）

- **改文件**：`app.py`
- **改函数**：模块顶部、`create_app()`
- **改动要点**（§2.1）：
  - 删除 `logging.basicConfig(level=logging.INFO)`（app.py:10）。
  - `import logging_config`；`create_app()` 中 `debug_trace.init_debug(config.DEBUG)` 调用替换/并入为 `logging_config.setup_logging(config.DEBUG)`（与 2.4 协同，倾向并入，见 2.4）。
  - 模块 logger 改 `logger = logging.getLogger("pdf_reader.app")`。
- **logger/级别**：`pdf_reader.app`（启动摘要见 4.1）。
- **完成判定**：`app.py` 源码无 `logging.basicConfig`；`create_app()` 调用 `setup_logging` 恰一次；import `app` 不产生副作用（沿用 test_app 约束）。
- **依赖**：1.1；与 2.4 协同。
- **TDD**：先更新 `tests/test_app.py`（5.6）断言 `setup_logging` 被调用、`init_debug` 不再被调用，见红再改。

---

## 2. 重构 debug_trace.py

### 2.1 移除术语提取 monkey-patch — [TDD]

- **改文件**：`debug_trace.py`
- **删函数/符号**：`_apply_monkey_patches`、`patched_extract`、`_original_extract`、`init_debug` 中 patch 调用、`AutomaticTermExtractor` import（§2.7）。
- **改动要点**：`init_debug` 删除或退化为空/薄封装（见 2.4 决策：倾向并入 `setup_logging`，则 `init_debug` 整体删除）。术语提取再出问题靠 babeldoc `TranslationConfig.debug=True` tracking 文件 + 新 INFO 流程定位阶段。
- **完成判定**：`debug_trace.py` 无 `AutomaticTermExtractor` / `_apply_monkey_patches` / `patched_extract` / `_original_extract`；`grep -r "AutomaticTermExtractor" .` 仅剩可能的测试残留（应一并删，见 5.1）。
- **依赖**：与 2.4 协同（决定 `init_debug` 去留）。
- **TDD**：先在 `test_debug_trace.py` / `test_debug_patches.py` 删除 monkey-patch 用例并新增「`init_debug` 不存在或为空」断言（红），再删实现。

### 2.2 `log_step` / `log_token_usage` / `log_glossary_merge` 去早返回 + 分层 + page 前缀 — [TDD]

- **改文件**：`debug_trace.py`
- **改函数**：`log_step`、`log_token_usage`、`log_glossary_merge`
- **改动要点**（§2.3、§2.4）：
  - 删除三者开头的 `if not config.DEBUG: return` / `if config.DEBUG:` 早返回。
  - `log_step`：流程骨架改 `logger.info`，消息带 `[page=N]` / `[batch=from-to]` 前缀（由调用点拼入 step 文本，或 `log_step` 接收 page 参数——倾向调用点拼，保持函数签名简单）。
  - `log_token_usage`：改 `logger.debug`（细节层）；空 dict 仍跳过。
  - `log_glossary_merge`：流程里程碑改 `logger.info`（合并完成属 INFO 流程，见 §3 数据流），字段含 page 与 elapsed。
- **logger/级别**：`pdf_reader.debug_trace`——`log_step` INFO、`log_token_usage` DEBUG、`log_glossary_merge` INFO。
- **完成判定**：debug off 时 `log_step("submit translate page %d", 2)` 仍产出 INFO 记录；`log_token_usage({...})` 仅 debug on 时可见（DEBUG）；三者不再读 `config.DEBUG` 决定是否输出。
- **依赖**：2.3（logger 命名空间与 handler 接入）。
- **TDD**：先改 `test_debug_trace.py` 的 `test_log_step_no_op_when_debug_false` → 改为「debug off 仍输出 INFO」，见红再改。

### 2.3 `trace_logger` 接入新配置体系；`debug_session` 保留 — [TDD-可选]

- **改文件**：`debug_trace.py`
- **改函数**：模块级 `trace_logger` 初始化、`debug_session`
- **改动要点**（§2.5 末段）：
  - `trace_logger = logging.getLogger("pdf_reader.debug_trace")` 已就位，**删除**其下自建的 `console_handler` 与 `setLevel(INFO)` 块（debug_trace.py:93-98）——handler 统一由 `setup_logging` 在根 `pdf_reader` 上挂，子 logger 继承。
  - `debug_session` 的 per-PDF 文件留档逻辑保留：仍向 `cache/<hash>/debug_trace.log` 追加 `FileHandler`（仅 debug on），与新全局 `logs/pdf_reader.log` 互不冲突；旋转与异常清理逻辑不动。
- **logger/级别**：`pdf_reader.debug_trace`，继承根 INFO/DEBUG；`debug_session` 内部 `trace_logger.info("=== Debug session start ===")`。
- **完成判定**：`debug_trace.py` 不再自建 console handler；`debug_session(glossary_path, page)` 在 debug on 时仍生成 `debug_trace.log`，debug off 时仍 no-op。
- **依赖**：1.1（根 handler 由 setup_logging 提供）。

### 2.4 `init_debug` 并入 `setup_logging` — [非TDD]

- **改文件**：`app.py`、`debug_trace.py`
- **改动要点**（§2.1、迁移顺序 §6 步骤 2）：采用设计倾向——`init_debug` 整体删除（其唯一职责 patch 已在 2.1 删除），`create_app()` 直接调 `logging_config.setup_logging(config.DEBUG)`。若保留薄封装则封装内仅转发，但倾向删除以减少入口。
- **完成判定**：`debug_trace.py` 无 `init_debug`；`app.py` 无 `debug_trace.init_debug` 调用；`create_app()` 只调 `setup_logging`。
- **依赖**：1.4、2.1。

---

## 3. 按模块插桩 — INFO 流程日志

> 插桩任务彼此大多独立，1.1 完成后即可并行；唯 3.4 ↔ 3.5 必须成对改。建议顺序：3.1 → 3.2 → 3.3 → (3.4+3.5) → 3.6 → 3.7 → 3.8 → 3.9 → 3.10。

### 3.1 `state.py`：open_pdf / replace_page(s) — [TDD]（对应 5.3）

- **改文件**：`state.py`
- **改函数**：`open_pdf`、`replace_page`、`replace_pages`
- **改动要点**（§2.3、§3 数据流、spec application-logging「Open PDF logging」「State change logging」）：
  - 模块 logger：`logger = logging.getLogger("pdf_reader.state")`。
  - `open_pdf` 成功后 INFO：`"[open] hash=%s pages=%d dim=%.0fx%.0f cache=%s"`，其中 cache 标记 new/reused（由 `right_pdf_path.exists()` 判断 copy 是否发生）。
  - `replace_page` 成功后 INFO：`"[page=%d] replace into %s"`（right.pdf 路径）；失败 try/except 包裹 `logger.error("[page=%d] replace failed", page_num, exc_info=True)` 后 re-raise。
  - `replace_pages` 同理用 `[batch=...]` 或列出 indices：`"[batch] replace pages %s into %s"`；失败 ERROR + exc_info。
- **logger/级别**：`pdf_reader.state`，INFO 成功 / ERROR 失败。
- **完成判定**：`open_pdf` 成功产生含 hash+pages 的 INFO；`replace_page` 成功产生含 page 索引+right.pdf 路径的 INFO；失败产生 ERROR+exc_info；render 调用不在此模块打 INFO。
- **依赖**：1.1。
- **TDD**：先写 5.3 的 open_pdf/replace_page INFO 断言（红）再插桩。

### 3.2 `pdf_renderer.py`：render_page DEBUG — [TDD]（对应 5.3）

- **改文件**：`pdf_renderer.py`
- **改函数**：`render_page`
- **改动要点**（§2.3、spec「High-frequency render logging is DEBUG」）：加 `logger = logging.getLogger("pdf_reader.render")`；`render_page` 末尾 `logger.debug("[render] page=%d dpi=%d", page_num, dpi)`（可含耗时，但渲染很快，耗时可选）。**禁止 INFO**，避免每页刷屏。
- **logger/级别**：`pdf_reader.render`，DEBUG。
- **完成判定**：debug off 时 `render_page` 不产任何控制台输出；debug on 时产 DEBUG 含 page。
- **依赖**：1.1。

### 3.3 `pdf_extraction.py`：extract DEBUG — [TDD-可选]

- **改文件**：`pdf_extraction.py`
- **改函数**：`extract_single_page`、`extract_pages`
- **改动要点**（§2.3、§3 数据流）：加 `logger = logging.getLogger("pdf_reader.extract")`；两函数末尾 `logger.debug("[page=%d] extract to %s", page_num, single_page_pdf)` / `logger.debug("[batch=%d-%d] extract to %s", page_indices[0]+1, page_indices[-1]+1, multi_page_pdf)`。
- **logger/级别**：`pdf_reader.extract`，DEBUG。
- **完成判定**：debug on 时抽页产 DEBUG 含范围与临时路径；debug off 不可见。
- **依赖**：1.1。

### 3.4 `translation_orchestrator.py`：线程边界 + flow_label — [TDD]（对应 5.3/5.4，与 3.5 成对）

- **改文件**：`translation_orchestrator.py`
- **改函数**：`run_translation`（签名变更）、`run_translation_thread`
- **改动要点**（§2.4、§2.6、spec「Translation orchestrator boundary logging」）：
  - 加 `logger = logging.getLogger("pdf_reader.translate")`。
  - `run_translation(settings, pdf_path, flow_label: str)` 新增 `flow_label: str` 形参。
  - 线程启动前 `logger.info("[%s] thread start", flow_label)`；线程 `_done` 后、`thread.join` 前/后 `logger.info("[%s] thread end", flow_label)`。
  - `except Exception as e:` 内、设 `error_info` 后、放 `_done` 前：`logger.error("[%s] thread exception", flow_label, exc_info=True)`。
  - `thread.join(timeout=5.0)` 后判断 `if thread.is_alive(): logger.warning("[%s] thread join timeout", flow_label)`。
- **logger/级别**：`pdf_reader.translate`，INFO 起止 / ERROR 异常 / WARNING 超时。
- **完成判定**：一次翻译产 thread start + thread end 两条 INFO（带 flow_label）；线程抛异常产 ERROR+exc_info；join 超时产 WARNING。
- **依赖**：1.1；**与 3.5 同次提交**（签名变更需调用方同步）。
- **TDD**：5.4 的 orchestrator 异常/超时断言先红。

### 3.5 `sse_stream.py`：log_step 迁移 INFO + page 前缀 + 传 flow_label — [TDD]（对应 5.3，与 3.4 成对）

- **改文件**：`sse_stream.py`
- **改函数**：`generate`、`generate_batch`
- **改动要点**（§2.4、§3 数据流、spec「Translation flow page correlation」）：
  - 模块 logger 由 `logging.getLogger("pdf_reader")` 改为 `logging.getLogger("pdf_reader.translate")`。
  - `generate`：`debug_trace.log_step("submit translate page %d", ctx.page)` → INFO 常驻，消息形如 `"[page=%d] submit translate"`（直接用 `logger.info` 或经 `log_step`，只要走 INFO）。
  - `run_translation(ctx.settings, str(single_page_pdf))` → 传 `flow_label=f"page={ctx.page}"`。
  - 翻译完成 `log_step("translate page %d done (%.2fs)", ...)` → INFO `[page=%d] translate done (X.XXs)`。
  - `log_token_usage` 调用保留（已改 DEBUG，见 2.2）→ 消息 `[page=%d] token usage: main=... term=...`。
  - `generate_batch`：前缀改 `[batch=%d-%d]`，`flow_label=f"batch={ctx.from_page}-{ctx.to_page}"`，done/usage 同理。
  - `finish_translation` / `merge_glossary_only` 调用不变（其内部日志在 3.7 改）。
- **logger/级别**：`pdf_reader.translate`，INFO 流程 / DEBUG token。
- **完成判定**：debug off 翻译一页，日志含 `[page=N] submit translate`、`[page=N] thread start`、`[page=N] thread end`、`[page=N] translate done (Xs)`；token usage 仅 debug on 可见。
- **依赖**：2.2（log_step 已去早返回）、3.4（flow_label 形参）。

### 3.6 `sse_stream.py`：错误日志带上下文 — [TDD]（对应 5.4）

- **改文件**：`sse_stream.py`
- **改函数**：`generate`、`generate_batch` 的 `except Exception` 分支
- **改动要点**（§2.6、spec「Contextual error logging」）：
  - 替换 `logging.getLogger("pdf_reader").warning("translate_page generate error", exc_info=True)`（sse_stream.py:186）为：
    `logger.error("[page=%d] translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s", ctx.page, provider, model, lang_in, lang_out, tmpdir, exc_info=True)`。
  - 批量同理 `[batch=%d-%d] ...`。
  - provider/model/lang_in/lang_out 从 `ctx.settings`/`config` 取；构造 settings 摘要时**只取 provider/model/lang/path，不含 api_key**（§4.4）。
- **logger/级别**：`pdf_reader.translate`，ERROR + exc_info。
- **完成判定**：`generate` 捕获异常时 ERROR 记录含 `[page=N]` + provider + model + tmpdir + exc_info；源码无 `logger.warning("... generate error", ...)` 裸调用。
- **依赖**：3.5（logger 命名空间）。
- **TDD**：5.4 错误上下文断言先红。

### 3.7 `translation_lifecycle.py`：finish/merge INFO — [TDD-可选]（对应 5.3）

- **改文件**：`translation_lifecycle.py`
- **改函数**：`finish_translation`、`merge_glossary_only`
- **改动要点**（§3 数据流、§2.3）：模块 logger 由 `logging.getLogger("pdf_reader")` 改 `logging.getLogger("pdf_reader.lifecycle")`；`log_glossary_merge("merge_done", page=-1, elapsed=...)` 已在 2.2 改 INFO——确认消息带 page 上下文：`finish_translation` 需知道 page，目前签名无 page 参数，**两个选项**（择一）：
  - 选项 A（推荐）：`finish_translation` 增加 `page: int` 参数，`sse_stream.generate` 传入 `ctx.page`，合并日志 `[page=%d] glossary merge done (X.XXs)`。
  - 选项 B：保持签名，合并日志用 `[glossary] merge done (X.XXs)`，不带 page。
  - 倾向选项 A 以贯穿 page 关联（§2.4）。`merge_glossary_only` 同理加 `from_page`/`to_page` 或用 `[batch=...]`。
  - `replace_page` 调用后的 INFO 由 3.1 负责，此处不重复。
- **logger/级别**：`pdf_reader.lifecycle`，INFO。
- **完成判定**：合并完成产 INFO 含产物路径与耗时；带 page/batch 前缀（若选 A）。
- **依赖**：2.2、3.5（若改签名则 sse_stream 调用处同步）。

### 3.8 `glossary_service.py`：resolve DEBUG / merge WARNING — [TDD-可选]

- **改文件**：`glossary_service.py`（及 `glossary_merger.py` 若其有日志）
- **改函数**：`resolve_glossary_paths`、`merge_after_translate`
- **改动要点**（§2.3）：模块 logger 由 `logging.getLogger("pdf_reader")` 改 `logging.getLogger("pdf_reader.glossary")`；`resolve_glossary_paths` DEBUG 记录解析结果（返回的路径列表或 None）；`merge_after_translate` 失败分支 WARNING 已存在——补文件路径字段：`logger.warning("[glossary] merge failed: cumulative=%s auto=%s", cumulative_path, auto_extracted_path, exc_info=True)`。
- **logger/级别**：`pdf_reader.glossary`，DEBUG 解析 / WARNING 失败。
- **完成判定**：resolve 产 DEBUG；merge 失败产 WARNING 含两个文件路径 + exc_info。
- **依赖**：1.1。

### 3.9 `routes.py`：端点入口 DEBUG — [非TDD]

- **改文件**：`routes.py`
- **改函数**：`open_pdf`、`translate_page`、`translate_batch`
- **改动要点**（§2.3）：加 `logger = logging.getLogger("pdf_reader.routes")`；`open_pdf` 入口 `logger.debug("[route] open_pdf path=%s", pdf_path)`；参数校验失败 `logger.debug("[route] open_pdf invalid path")`；`translate_page`/`translate_batch` 入口与校验失败 DEBUG。**注意**：werkzeug 每请求 INFO 已由 1.2 降级，此处只补项目自身 DEBUG，不打 INFO 避免与 werkzeug 重复。404 处理器保留现有行为。
- **logger/级别**：`pdf_reader.routes`，DEBUG。
- **完成判定**：debug on 时端点入口/校验失败产 DEBUG；debug off 不可见。
- **依赖**：1.1。

### 3.10 `engine_resolver.py` / `translation_settings.py`：命名空间 + settings 摘要 — [TDD-可选]（对应 5.5 摘要构造）

- **改文件**：`engine_resolver.py`、`translation_settings.py`
- **改函数**：`resolve_engine`、`build_engine_kwargs`、`build_settings`
- **改动要点**（§2.2 表、§4.4 安全）：
  - 两文件 logger 由 `logging.getLogger("pdf_reader")` 改 `logging.getLogger("pdf_reader.engine")`。
  - `resolve_engine` 的 `logger.info("Using engine: %s (%s)", ...)` 保留并改命名空间（已是 INFO，保持）。
  - `build_settings` 末尾 `logger.debug("[settings] provider=%s model=%s lang=%s->%s pages=%s", config.MODEL_PROVIDER, config.MODEL, lang_in, lang_out, pages)`——**只取 provider/model/lang/pages，不含 api_key**。可抽一个 `_settings_summary()` 辅助只取白名单字段，供 3.6 错误日志与 4.1 启动摘要复用。
- **logger/级别**：`pdf_reader.engine`，INFO Using engine / DEBUG settings 摘要。
- **完成判定**：`Using engine` INFO 出现在 `pdf_reader.engine`；`build_settings` 产 DEBUG 摘要无 api_key。
- **依赖**：1.1；与 4.1 共享摘要构造器。

---

## 4. 启动配置摘要与安全

### 4.1 `app.py` 启动摘要 — [TDD]（对应 5.5）

- **改文件**：`app.py`
- **改函数**：`create_app()`（或模块加载后）
- **改动要点**（§3 数据流、§4.4、spec「Startup configuration summary」）：在 `setup_logging` 之后发 `logger.info("Starting PDF Reader provider=%s model=%s lang=%s->%s cache_dir=%s dpi=%d debug=%s", provider, model, lang_in, lang_out, cache_dir, dpi, debug)`。摘要构造**只取** provider/model/lang_in/lang_out/cache_dir/dpi/debug，**不含 api_key**。可复用 3.10 的 `_settings_summary()` 思路。
- **logger/级别**：`pdf_reader.app`，INFO。
- **完成判定**：启动产一条 INFO 含上述 7 字段；记录文本中不出现 `MODEL_API_KEY` 值（如 `sk-...`）。
- **依赖**：1.4、3.10（摘要构造器）。
- **TDD**：5.5 安全测试先红（断言摘要含 provider 且不含 api_key 值）。

### 4.2 全项目 grep 复核无 api_key 泄露 — [非TDD]

- **改文件**：无（审计；若发现违规则回修对应日志语句）
- **改动要点**（§4.4）：`grep -rn "api_key" --include=*.py .` 逐条核对每处 `logger.*` / `log_*` 调用，确认无 `%s`, api_key / f-string 含 api_key 原值。settings 摘要构造器只取白名单。
- **完成判定**：grep 结果中无任何日志语句直接输出 `config.MODEL_API_KEY` / `api_key` 原值；5.5 安全测试绿。
- **依赖**：3.10、4.1。

---

## 5. 测试更新与新增

> 凡标 [TDD] 的实现任务，其对应 5.x 测试应**先于**实现写成红测；此处列出测试本身的写法要点。

### 5.1 更新 `tests/test_debug_trace.py` 与 `tests/test_debug_patches.py` — [随 2.x]

- **改文件**：`tests/test_debug_trace.py`、`tests/test_debug_patches.py`
- **改动要点**（§4.6）：
  - 删除 `test_init_debug_true_patches_extractor`、`test_init_debug_false_does_not_patch`、`test_init_debug_handles_import_error`（test_debug_trace.py）及 `test_debug_patches.py` 全部用例（monkey-patch 已删）。
  - `test_log_step_no_op_when_debug_false` → 改为「debug off 仍 INFO 输出」；`test_log_token_usage_*` 改为断言 DEBUG 级别（off 时不可见、on 时可见）。
  - `test_log_glossary_merge_no_op_when_debug_false` → 改为 INFO 常驻。
  - `test_full_debug_trace_bytes_identical` 适配 INFO 常驻语义（debug off 也应有流程行）。
  - `test_zero_overhead_no_io_when_debug_false`：该语义已废弃，删除或改为「debug off 时 token usage(DEBUG) 无 IO，但 log_step(INFO) 有 IO」。
  - `debug_session` 相关用例（rotate/exception_safe/no_op）保留，验证 debug on 行为。
- **完成判定**：`pytest tests/test_debug_trace.py tests/test_debug_patches.py` 绿；无引用已删符号。
- **依赖**：2.1-2.3。

### 5.2 新增 `tests/test_logging_config.py` — [TDD 先红，随 1.x]

- **改文件**：新建 `tests/test_logging_config.py`
- **测试要点**（§4.1、§4.2、spec「Centralized logging configuration」「Console and rotating file dual output」「Third-party library noise demotion」）：
  - `setup_logging(False)` 后 `getLogger("pdf_reader")` 有且仅有 1 个 `StreamHandler` + 1 个 `RotatingFileHandler`（类型断言 + 数量）。
  - 根级别 INFO；`setup_logging(True)` 后 DEBUG；幂等（调两次 handler 不翻倍）。
  - `werkzeug`/`pdf2zh_next`/`babeldoc` effective level == DEBUG。
  - `logs/` 目录被创建；`logs/.gitkeep` 存在。
  - 源码断言：读 `app.py` 文本，`assert "logging.basicConfig" not in app_py`。
  - 测试需在前后清理 `pdf_reader` logger 的 handler，避免污染其他用例（fixture 用 monkeypatch/最终还原）。
- **完成判定**：新增测试在 1.1-1.4 完成后全绿；实现前为红。
- **依赖**：1.1-1.4。

### 5.3 新增流程日志测试（debug off）— [TDD 先红，随 3.1/3.5/3.7]

- **改文件**：新建 `tests/test_flow_logging.py`（或并入 `test_logging_config.py`）
- **测试要点**（§4.2、spec「Flow logs present with debug off」「Open PDF logging」「High-frequency render logging is DEBUG」「Translation flow page correlation」）：
  - 用 `caplog` fixture（pytest）捕获，设 `caplog.set_level(logging.INFO, logger="pdf_reader.state")` 等。
  - debug off 下 `state.open_pdf(sample_pdf, sha256)` → `pdf_reader.state` INFO 记录含 hash + pages。
  - debug off 下 `render_page` → 断言**无** INFO 记录（仅 DEBUG，caplog 设 INFO 时捕获不到）。
  - 翻译一页（mock `run_translation` 返回 finish 事件 + token_usage）→ INFO 记录含 submit/done/replace/merge，且每条消息含 `[page=N]`。
  - 批量 → 每条含 `[batch=from-to]`。
- **完成判定**：debug off 流程测试绿；`[page=N]` 贯穿断言通过。
- **依赖**：3.1、3.2、3.5、3.7。

### 5.4 新增错误上下文测试 — [TDD 先红，随 3.4/3.6]

- **改文件**：新建 `tests/test_error_logging.py`（或并入上述）
- **测试要点**（§4.3、spec「Contextual error logging」「Translation orchestrator boundary logging」）：
  - `generate` 捕获异常（mock `run_translation` 抛 Exception）→ caplog ERROR 记录含 `[page=N]` + provider + model + `exc_info`。
  - `run_translation` 线程内抛异常 → ERROR 含 flow_label + exc_info，且随后抛 `TranslationError`。
  - `thread.join` 超时（mock 线程不结束）→ WARNING 含 flow_label。
  - 批量同理 `[batch=from-to]`。
- **完成判定**：错误/超时测试绿。
- **依赖**：3.4、3.6。

### 5.5 新增安全测试 — [TDD 先红，随 4.1]

- **改文件**：并入 `tests/test_logging_config.py` 或新建 `tests/test_log_security.py`
- **测试要点**（§4.4、spec「No secrets in logs」）：
  - 启动摘要 caplog 记录文本不含 `config.MODEL_API_KEY` 值（用一个特征值如 `sk-secret-xxx` 注入 config，断言不出现在任何 INFO 记录）。
  - `generate` 错误上下文记录不含 api_key 值。
  - 可加一个全项目 grep 风格测试：扫描 `sse_stream.py`/`engine_resolver.py`/`translation_settings.py`/`app.py` 源码，断言无 `logger.*` 行含 `api_key` 字面插值。
- **完成判定**：安全测试绿；api_key 值在任何 caplog 记录中不可见。
- **依赖**：4.1、3.6、3.10。

### 5.6 更新 `tests/test_app.py` — [TDD 先红，随 1.4/2.4]

- **改文件**：`tests/test_app.py`
- **改动要点**（§4.6）：
  - `test_import_app_does_not_trigger_side_effects`：`patch("app.debug_trace.init_debug")` → `patch("app.logging_config.setup_logging")`，断言 import 时不调用。
  - `test_create_app_calls_init_debug` → `test_create_app_calls_setup_logging`：断言 `create_app()` 调 `setup_logging(config.DEBUG)` 恰一次。
  - CLI debug flag 用例保留不变。
- **完成判定**：`pytest tests/test_app.py` 绿；无引用 `debug_trace.init_debug`。
- **依赖**：1.4、2.4。

---

## 6. 文档与收尾

### 6.1 更新 `AGENTS.md` — [非TDD]

- **改文件**：`AGENTS.md`
- **改动要点**：在 CodeGraph 段后追加「日志约定」段：logger 命名空间表（§2.2）、级别策略（§2.3）、page 前缀约定（§2.4）、运行/测试命令（见下「验证与收尾」）。注明 `app.py` 不再用 `basicConfig`，统一走 `logging_config.setup_logging`。
- **完成判定**：`AGENTS.md` 含命名空间、级别、page 前缀、命令四小节。
- **依赖**：1-5 完成。

### 6.2 全量测试与 lint/typecheck — [非TDD]

- **改动要点**：运行下方「验证与收尾」命令，确认全绿。
- **完成判定**：所有命令退出码 0。
- **依赖**：全部实现 + 测试。

### 6.3 手动验证 — [非TDD]

- **改动要点**（§4.6、§3 数据流）：实跑应用，debug off 打开并翻译一页，观察终端与 `logs/pdf_reader.log`。
- **完成判定**：见下方「手动验证步骤」全部通过。
- **依赖**：6.2 绿。

---

## 验证与收尾

### 命令（在仓库根目录执行）

```powershell
# lint（含 ANN 注解规则）
ruff check .

# 格式检查
ruff format --check .

# 全量测试
pytest -q
```

> **关于 typecheck**：本项目未配置独立类型检查器（无 mypy/pyright 配置）。类型相关约束由 `ruff.toml` 的 `select = ["ANN"]` 规则覆盖（在 `ruff check` 中执行）。若需严格类型检查，可在收尾后另行引入 mypy 并写入 `AGENTS.md`，本次变更范围内不强制。

### 手动验证步骤

1. **debug off 场景**（`config.toml` 不开 `[debug] enabled`，或不传 `--debug`）：
   - 启动 `python app.py`，确认终端**只有**项目自身 INFO：`Starting PDF Reader provider=... model=... lang=en->zh ... debug=off` + `Using engine: ...`。
   - 确认 werkzeug 的 `POST /api/open` / `GET /api/page/...` 每请求 INFO **不再出现**。
   - 打开一个 PDF：终端出现 `[open] hash=... pages=... dim=... cache=...`。
   - 翻译一页：终端出现 `[page=N] submit translate` → `[page=N] thread start` → `[page=N] thread end` → `[page=N] translate done (X.XXs)` → `[page=N] replace into ...right.pdf` → `[page=N] glossary merge done (X.XXs)`；**不出现** token usage（DEBUG）与 babeldoc/pdf2zh_next 进度。
   - 翻译批量：上述前缀改 `[batch=from-to]`。
2. **文件留档**：`logs/pdf_reader.log` 存在且内容与控制台一致（同 formatter）；控制台 INFO 在文件中也都有。
3. **debug on 场景**（`python app.py --debug`）：
   - 终端额外出现 `[render] page=...`、`[page=N] extract to ...`、`[page=N] token usage: main=... term=...`、babeldoc/pdf2zh_next 翻译进度 INFO。
   - `cache/<hash>/debug_trace.log` 生成（per-PDF 留档）。
4. **错误场景**：用无效 provider 或断网触发翻译失败 → 终端出现 `[page=N] translate failed: provider=... model=... tmpdir=...`（ERROR，带 traceback）；确认 traceback 与摘要中**无 api_key 值**。
5. **噪音确认**：debug off 时 `grep -i werkzeug logs/pdf_reader.log` 无每请求行；`grep babeldoc logs/pdf_reader.log` 无翻译进度行。
6. **回滚演练**（可选）：回退 `app.py` 的 `setup_logging` 调用为 `basicConfig`，确认旧行为恢复（验证改动可回滚，§6）。

### 收尾检查清单

- [x] `ruff check .` 绿
- [x] `ruff format --check .` 绿
- [x] `pytest -q` 全绿
- [x] `app.py` 无 `logging.basicConfig`（5.2 源码断言通过）
- [x] `debug_trace.py` 无 `AutomaticTermExtractor` / monkey-patch
- [x] 全项目 grep 无日志语句输出 api_key 原值
- [x] 翻译流日志均带 `[page=` / `[batch=`（5.3 约定断言通过）
- [x] `AGENTS.md` 已更新日志约定
- [ ] 手动验证 1-5 全通过
