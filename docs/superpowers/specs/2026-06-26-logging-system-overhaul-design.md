---
comet_change: logging-system-overhaul
role: technical-design
canonical_spec: openspec
---

# Design Doc: Logging System Overhaul

> 配套 OpenSpec 变更 `logging-system-overhaul`。本文件为 Superpowers 深度设计，规格以 OpenSpec delta specs 为准。

## 1. 背景与目标

PDF_reader 当前的日志能力由 `debug_trace.py` 承担，存在三个结构性缺陷：

1. **debug off 时无流程日志** —— `log_step`/`log_token_usage`/`log_glossary_merge` 均以 `if not config.DEBUG: return` 开头，正常运行无轨迹可回溯。
2. **关键环节全裸** —— `state.open_pdf`/`render_page`/`extract_page`/`replace_page`（状态变更）/`translation_orchestrator`（异步线程+event queue+join 超时，最难查）在任何时候都没有日志。
3. **噪音与信号混杂** —— `app.py:10` 硬编码 `logging.basicConfig(level=logging.INFO)`，werkzeug 每条 HTTP 请求、pdf2zh_next/babeldoc 翻译进度 INFO 全部涌入终端，淹没项目自身信号。

术语提取 monkey-patch 当初为排障而生，该功能已稳定，保留只增加与 babeldoc 内部的耦合。

**目标**：平时（debug off）终端只显示项目自身 INFO 流程日志、文件留全量记录，出未知问题可凭日志回溯"对哪页做了什么、耗时多少、在哪步失败"。

**非目标**：远程日志收集/OTEL、前端 JS 日志、改翻译业务逻辑、改第三方库内部日志、JSON 结构化日志。

## 2. 架构

### 2.1 集中式配置入口

新建 `logging_config.py`，唯一入口 `setup_logging(debug: bool) -> None`，在 `app.create_app()` 中调用一次。

```
setup_logging(debug)
├─ 创建 logs/ 目录（若缺）
├─ 构造 formatter: "%(asctime)s %(levelname)s %(name)s [%(message)s]"
│   （page 前缀由消息自带，formatter 不强行注入）
├─ console = StreamHandler(stdout)   level=INFO/DEBUG 随 debug
├─ file = RotatingFileHandler('logs/pdf_reader.log', maxBytes=5MB, backupCount=5, encoding='utf-8')
├─ root_pdf = getLogger('pdf_reader'); setLevel(DEBUG if debug else INFO)
│   addHandler(console); addHandler(file)
├─ 第三方降级: getLogger('werkzeug'/'pdf2zh_next'/'babeldoc').setLevel(DEBUG)
└─ （原 init_debug 的 monkey-patch 逻辑整段删除，不在此处）
```

`app.py` 移除 `logging.basicConfig(level=logging.INFO)` 与 `debug_trace.init_debug(config.DEBUG)` 调用，改为 `logging_config.setup_logging(config.DEBUG)`。

### 2.2 模块化 logger 层级

统一 `pdf_reader.*` 命名空间，按关注点分 child：

| logger | 覆盖模块 | 默认级别诉求 |
|---|---|---|
| `pdf_reader.app` | app.py | INFO 启动摘要 |
| `pdf_reader.state` | state.py | INFO 状态变更 |
| `pdf_reader.render` | pdf_renderer.py | DEBUG（高频） |
| `pdf_reader.extract` | pdf_extraction.py | DEBUG |
| `pdf_reader.translate` | sse_stream.py / translation_orchestrator.py | INFO 流程 |
| `pdf_reader.lifecycle` | translation_lifecycle.py | INFO |
| `pdf_reader.glossary` | glossary_service.py / glossary_merger.py | DEBUG/WARNING |
| `pdf_reader.engine` | engine_resolver.py / translation_settings.py | INFO/DEBUG |
| `pdf_reader.routes` | routes.py | DEBUG |
| `pdf_reader.debug_trace` | debug_trace.py | DEBUG 细节层 |

每模块 `logger = logging.getLogger("pdf_reader.<concern>")`，不再用匿名 root。子 logger 级别默认未设（继承根 INFO/DEBUG），仅 `pdf_reader.render` 无需特殊设置（根 DEBUG 时自然显示）。

### 2.3 级别策略

| 级别 | 用途 | 示例 |
|---|---|---|
| ERROR | 影响请求完成的失败 | 翻译线程异常、replace_page 失败、SSE generate 异常 |
| WARNING | 可恢复异常/降级 | 术语表合并失败、glossary 文件缺失、join 超时 |
| INFO | 流程里程碑（常驻） | open_pdf 完成、翻译起止+耗时、replace_page 完成、合并完成、启动配置摘要 |
| DEBUG | 高频/细节 | 渲染每页、抽页路径、token 用量、第三方库进度、term 批次 |

**关键**：`log_step`/`log_token_usage`/`log_glossary_merge` 移除 `if not config.DEBUG: return` 早返回。流程骨架改 `logger.info`，token 用量等细节改 `logger.debug`。debug 开关只控制根级别（INFO↔DEBUG）与第三方是否显示，不再控制"有无流程日志"。

### 2.4 page 关联标识（方案 B：显式拼消息）

翻译相关日志统一前缀 `[page=N]`（单页）或 `[batch=from-to]`（批量），由调用点拼入消息。

- `sse_stream.generate(ctx)` 已有 `ctx.page`，直接 `logger.info("[page=%d] submit translate", ctx.page)` 贯穿抽页/翻译起止/替换/合并
- `sse_stream.generate_batch(ctx)` 用 `ctx.from_page`/`ctx.to_page` 拼 `[batch=%d-%d]`
- `translation_orchestrator.run_translation(settings, pdf_path, flow_label)` 新增 `flow_label: str` 参数，编排线程的起止/异常/超时日志用 `logger.info("[%s] thread start", flow_label)` 拼消息
- 错误日志同样带前缀：`logger.error("[page=%d] translate failed: provider=%s model=%s ...", page, provider, model, exc_info=True)`

**约定由测试守住**：新增约定测试 grep 翻译流日志调用必带 `[page=`/`[batch=`。

### 2.5 双输出与轮转

- 控制台 `StreamHandler`（实时观测）
- `RotatingFileHandler('logs/pdf_reader.log', maxBytes=5_000_000, backupCount=5, encoding='utf-8')`（回溯档案，上限 ≈ 30MB）
- 同 formatter，避免控制台与文件不一致
- `logs/.gitkeep` 入库，日志文件本身不入库（`.gitignore` 加 `logs/*.log*`）
- `debug_trace.debug_session` 仍向 `cache/<hash>/debug_trace.log` 追加 per-PDF 留档（仅 debug on），与新全局文件互不冲突

### 2.6 错误日志带上文文

`sse_stream.py` 现有 `logger.warning("translate_page generate error", exc_info=True)`（无上下文）替换为：

```python
logger.error(
    "[page=%d] translate failed: provider=%s model=%s lang=%s->%s tmpdir=%s",
    ctx.page, provider, model, lang_in, lang_out, tmpdir,
    exc_info=True,
)
```

批量同理带 `[batch=from-to]`。`translation_orchestrator` 在抛 `TranslationError` 前补 `logger.error("[%s] thread exception", flow_label, exc_info=True)`；`thread.join(timeout=5)` 超时 `logger.warning("[%s] thread join timeout", flow_label)`。

### 2.7 移除术语提取 monkey-patch

`debug_trace.py` 删除：`_apply_monkey_patches`、`patched_extract`、`_original_extract`、`AutomaticTermExtractor` import、`init_debug` 中的 patch 调用。`debug-tracing` spec 的 "LLM term extraction transparency" 需求废弃（spec REMOVED 段已写迁移说明）。术语提取再出问题时，靠 babeldoc 自身 `TranslationConfig.debug=True` 产出的 tracking 文件 + 新系统 INFO 流程定位"是否进入术语阶段"。

## 3. 数据流

```
启动
  create_app() → logging_config.setup_logging(config.DEBUG)
    → 配置根 pdf_reader logger + console + rotating file
    → werkzeug/pdf2zh_next/babeldoc 降 DEBUG
  pdf_reader.app INFO: "Starting PDF Reader provider=deepseek model=... lang=en->zh dpi=200 debug=off"

打开 PDF  POST /api/open
  routes.open_pdf → state.open_pdf
    pdf_reader.state INFO: "[open] hash=abc123 pages=20 dim=612x792 cache=new"
  （render 高频，GET /api/page 仅 DEBUG）

翻译  POST /api/translate/<page>  (SSE)
  sse_stream.generate(ctx)
    pdf_reader.translate INFO: "[page=2] submit translate"
    pdf_reader.extract DEBUG: "[page=2] extract to tmpdir=..."
    run_translation(settings, pdf_path, flow_label="page=2")
      pdf_reader.translate INFO: "[page=2] thread start"
      ┊ babeldoc 翻译（第三方 INFO 仅 debug on 可见）
      pdf_reader.translate INFO: "[page=2] thread end"
    pdf_reader.translate INFO: "[page=2] translate done (30.77s)"
    pdf_reader.translate DEBUG: "[page=2] token usage: main=12345 term=678"
    finish_translation → state.replace_page
      pdf_reader.state INFO: "[page=2] replace into right.pdf"
    glossary merge
      pdf_reader.lifecycle INFO: "[page=2] glossary merge done (0.02s)"
    SSE finish

错误路径
  pdf_reader.translate ERROR: "[page=2] translate failed: provider=... model=... tmpdir=..." (exc_info)
```

## 4. 测试策略

### 4.1 新增 `tests/test_logging_config.py`
- `setup_logging(True/False)` 后根 `pdf_reader` logger 拥有且仅有一个 console + 一个 rotating file handler
- `werkzeug`/`pdf2zh_next`/`babeldoc` logger 级别为 DEBUG
- `logs/` 目录被创建
- `app.py` 源码无 `logging.basicConfig`

### 4.2 流程日志测试（debug off）
- `state.open_pdf` 成功 → `pdf_reader.state` INFO 记录含 hash/pages
- 翻译一页 → INFO 记录含 submit/done/replace/merge，且每条带 `[page=N]`
- `render_page` 在 debug off 时不产 INFO，仅 DEBUG（debug on 时可见）

### 4.3 错误上下文测试
- `generate` 捕获异常 → ERROR 记录含 `[page=N]` + provider + model + exc_info
- `run_translation` 线程异常 → ERROR 含 `[page=N]` + exc_info
- join 超时 → WARNING 含 `[page=N]`

### 4.4 安全测试
- 启动摘要记录不含 `api_key`/`MODEL_API_KEY` 值
- 错误上下文记录不含 api_key 值
- 全项目 grep 复核无日志语句含 api_key 原值

### 4.5 约定测试
- grep `sse_stream.py`/`translation_orchestrator.py`/`translation_lifecycle.py` 中翻译流日志调用，断言消息含 `[page=` 或 `[batch=`

### 4.6 删除/更新
- 移除 `test_debug_trace.py` 中 `test_init_debug_true_patches_extractor`/`test_init_debug_false_does_not_patch` 等 monkey-patch 用例
- 更新 `test_full_debug_trace_bytes_identical` 适配 INFO 常驻语义
- 更新 `test_app.py` 中 `init_debug` 调用断言为 `setup_logging` 形式

## 5. 风险与取舍

| 风险/取舍 | 缓解 |
|---|---|
| INFO 常驻打破"debug off 零开销"旧承诺 | 有意取舍；spec MODIFIED 已明确替换；每次翻译约 6-8 行可接受 |
| 显式拼消息靠约定 | 约定测试 grep 守住 |
| 删 monkey-patch 后术语提取再出问题难 trace | babeldoc tracking 文件 + INFO 流程定位阶段；必要时临时恢复 |
| 文件磁盘占用 | 5MB×5 ≈ 30MB 封顶 |
| 第三方库后续新增子 logger 可能又冒 INFO | 在 `setup_logging` 中对顶层 `pdf2zh_next`/`babeldoc` 设 DEBUG，子 logger 继承；定期复核 |
| api_key 泄露 | settings 摘要构造器只取 provider/model/lang/path；安全测试 + grep 复核 |

## 6. 迁移与回滚

**迁移顺序**：
1. 新增 `logging_config.py` + `logs/.gitkeep` + `.gitignore`
2. `app.py` 替换 `basicConfig`/`init_debug` 调用为 `setup_logging`
3. 重构 `debug_trace.py`（删 monkey-patch，迁移 `log_*`）
4. 逐模块插桩（state→render→extract→orchestrator→sse_stream→lifecycle→glossary→routes→engine→translation_settings）
5. 第三方降级（已在 `setup_logging` 统一）
6. 更新测试
7. 更新 `AGENTS.md`

**回滚**：回退 `app.py` 的 `setup_logging` 调用为 `basicConfig` 即可恢复旧行为；插桩的 `logger.info` 属增量，可单独保留或回退。

## 7. 实现顺序提示（与 tasks.md 对齐）

按 tasks.md 六组顺序推进：基础设施 → 重构 debug_trace → 按模块插桩 → 启动摘要与安全 → 测试 → 文档收尾。每组完成后运行相关测试与 lint/typecheck。
