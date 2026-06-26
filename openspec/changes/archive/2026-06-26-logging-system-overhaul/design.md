## Context

PDF_reader 是一个基于 Flask + pdf2zh_next/babeldoc 的 PDF 双栏翻译应用。当前日志能力由 `debug_trace.py` 承担，但它有三个结构性缺陷：

1. **debug off 时无流程日志**：`log_step` / `log_token_usage` / `log_glossary_merge` 开头均为 `if not config.DEBUG: return`，导致正常运行时没有轨迹可回溯。
2. **关键环节全裸**：`state.open_pdf` / `render_page` / `extract_page` / `replace_page`（状态变更）/ `translation_orchestrator`（异步线程 + event queue + join 超时，最难查）在任何时候都没有日志。
3. **噪音与信号混杂**：`app.py:10` 硬编码 `logging.basicConfig(level=logging.INFO)`，使 werkzeug 每条 HTTP 请求、pdf2zh_next/babeldoc 的翻译进度 INFO 全部涌入终端，淹没项目自身信号。

术语提取 monkey-patch（`_apply_monkey_patches` / `patched_extract`）当初为排查术语提取失效而注入 babeldoc 内部，该功能现已稳定，保留它只增加与第三方库版本的耦合。`debug_session` 的 per-PDF 文件留档思路有价值，应纳入新体系。

约束：仅用标准库 `logging` + `logging.handlers`，不引入新外部依赖；不改翻译业务逻辑与前端；渲染页面是高频调用（每次滚动/查看都请求），其日志必须用 DEBUG 避免刷屏。

## Goals / Non-Goals

**Goals:**
- 平时（debug off）终端只显示项目自身的 INFO 流程日志，文件留同样全量记录，出问题可回溯"对哪页做了什么、耗时多少、在哪步失败"
- 翻译流程日志带 `page`（单页）或 `from-to`（批量）关联标识，串联抽页/编排/替换/合并全链路
- 错误日志带上下文（page、settings 摘要、临时路径）+ `exc_info`
- 第三方库 INFO 噪音降为 DEBUG，平时不打
- 重构 `debug_trace.py`：移除 monkey-patch，迁移 `log_*` 为 INFO 常驻 + DEBUG 细节分层，保留 `debug_session` 文件留档

**Non-Goals:**
- 远程日志收集 / OTEL 链路追踪 / 结构化 JSON 日志
- 前端 JS 日志
- 改翻译业务逻辑或第三方库内部日志
- 日志检索/告警平台

## Decisions

### 决策 1：集中式 `logging_config.py`，按模块 logger 层级

新建 `logging_config.py` 提供 `setup_logging(debug: bool)`，在 `app.py` 启动时调用一次，替代 `basicConfig`。

**Logger 层级**（统一 `pdf_reader.*` 命名空间）：
```
pdf_reader (root namespace, INFO)
├── pdf_reader.app        启动/配置
├── pdf_reader.state      开PDF/渲染/抽页/替换(状态变更)
├── pdf_reader.render     渲染(高频→DEBUG)
├── pdf_reader.extract    抽页
├── pdf_reader.translate  翻译编排/SSE/步骤
├── pdf_reader.lifecycle  finish_translation/替换/合并
├── pdf_reader.glossary   术语表路径/合并
├── pdf_reader.engine     引擎解析
├── pdf_reader.routes     HTTP 入口(关键端点,非每请求)
└── pdf_reader.debug_trace debug细节层(原 debug_session 文件留档)
```

第三方库显式降级：`logging.getLogger("werkzeug").setLevel(DEBUG)`，`pdf2zh_next` / `babeldoc` 顶层 logger 同样设为 DEBUG。

**为何不用单个 `pdf_reader` logger**：按模块分层后，未来可单独调某一模块级别（如只把 render 降到 DEBUG 而保留 translate 的 INFO），且日志中 logger 名本身就是定位线索。替代方案：单 logger + 消息前缀——但无法分级，且易遗漏前缀，故不采用。

### 决策 2：级别策略 —— INFO 常驻流程，DEBUG 细节

| 级别 | 用途 | 示例 |
|---|---|---|
| ERROR | 影响请求完成的失败 | 翻译线程异常、replace_page 失败 |
| WARNING | 可恢复异常/降级 | 术语表合并失败、glossary 文件缺失 |
| INFO | 流程里程碑（常驻） | open_pdf 完成、翻译起止+耗时、replace_page 完成、合并完成 |
| DEBUG | 高频/细节 | 渲染每页、第三方库进度、token 用量、term 批次 |

**关键**：`log_step`/`log_token_usage` 不再 `if not config.DEBUG: return`，而是 `logger.info(...)` 常驻流程骨架；token 用量等细节用 `logger.debug(...)`。debug 开关只控制根级别（INFO↔DEBUG）与第三方库是否显示，不再控制"有无流程日志"。

### 决策 3：翻译流程 page 关联标识

翻译相关日志统一前缀 `[page=N]`（单页）或 `[batch=from-to]`（批量）。用 `logging.LoggerAdapter` 或调用时拼入消息实现，不引入 contextvar 全局态（项目是同步+单翻译线程，contextvar 收益小、复杂度高）。

**为何不用 contextvar + Filter 注入**：能自动注入，但本项目的翻译入口集中在 `sse_stream.generate`/`generate_batch`，显式传 page 拼消息更直观、更易在文件中 grep 定位。替代方案不采用。

### 决策 4：控制台 + 轮转文件双 handler

- 控制台：`StreamHandler`，格式 `%(asctime)s %(levelname)s %(name)s [%(context)s] %(message)s`（context 由消息自带，格式器不强行注入）
- 文件：`RotatingFileHandler('logs/pdf_reader.log', maxBytes=5MB, backupCount=5, encoding=utf-8)`，同样的格式器
- `debug_session` 仍可向 `cache/<hash>/debug_trace.log` 追加 per-PDF 留档（仅 debug on），与新全局文件互不冲突

**为何按大小而非按日期轮转**：桌面应用使用呈突发，按大小可预测磁盘占用（上限 ≈ 30MB）。替代方案：TimedRotating——空闲期也会产生空文件，故不采用。

### 决策 5：移除术语提取 monkey-patch

`_apply_monkey_patches` / `patched_extract` / `_original_extract` / `init_debug` 的 patch 逻辑整段删除。`debug-tracing` spec 的 "LLM term extraction transparency" 需求废弃。`init_debug` 保留为薄封装（仅记录 debug 是否启用），或并入 `logging_config.setup_logging`。

**为何不保留为可选工具**：术语提取已稳定，patch 与 babeldoc 内部方法 `extract_terms_from_paragraphs` 强耦合，babeldoc 升级易破；保留收益低于维护成本。若未来需排障，可临时加回，不作为常驻能力。

### 决策 6：错误日志带上文文

`sse_stream.py` 中 `logger.warning("translate_page generate error", exc_info=True)` 改为带 page、settings 摘要（provider/model/lang/pages）、临时目录：`logger.error("[page=N] translate failed: provider=... model=... tmpdir=...", exc_info=True)`。`translation_orchestrator` 的 `error_info` 在抛 `TranslationError` 前补 `logger.error` 记录线程上下文。

## Risks / Trade-offs

- **[Risk] INFO 流程日志体量增加** → 流程骨架日志每次翻译约 6-8 行，开 PDF 1 行，可接受；高频渲染已定为 DEBUG 不会刷屏
- **[Risk] 文件日志磁盘占用** → 5MB×5 轮转封顶 ≈ 30MB，可预测；不写敏感数据（api_key 已在 config 不入日志，settings 摘要只含 provider/model/lang）
- **[Risk] 删除 monkey-patch 后术语提取再出问题无法 trace** → babeldoc 自身仍可设 `TranslationConfig.debug=True` 产出 tracking 文件；新日志系统的 INFO 流程也能定位"是否进入术语提取阶段"；必要时临时恢复 patch
- **[Trade-off] 显式 page 拼消息 vs contextvar 自动注入** → 选显式，牺牲一点一致性换取简单与可 grep；要求所有翻译日志调用点统一带 `[page=N]` 前缀，靠测试守住约定
- **[Trade-off] 移除"debug off 零开销"承诺** → 原 `debug-tracing` spec 要求 debug off 行为与旧版完全一致、零开销；新体系 INFO 日志常驻，有微量 IO 开销。这是有意取舍，用 spec 的 MODIFIED 需求明确替换该承诺

## Migration Plan

1. 新增 `logging_config.py` 与 `logs/` 目录（加 `.gitkeep`，日志文件不入库）
2. `app.py` 替换 `basicConfig` 为 `logging_config.setup_logging(config.DEBUG)`
3. 重构 `debug_trace.py`：删 monkey-patch，`log_*` 改为 `logger.info/debug`，`debug_session` 保留并接入新 logger
4. 逐模块插桩：state → render → extract → orchestrator → sse_stream → lifecycle → glossary → routes → engine → translation_settings
5. 第三方库降级在 `setup_logging` 中统一设置
6. 更新测试：删 monkey-patch 用例，新增 `test_logging_config` 与各模块日志断言
7. 更新 `AGENTS.md` 记录日志约定与运行命令

**回滚**：若新日志系统引发问题，回退 `app.py` 的 `setup_logging` 调用为 `basicConfig` 即可恢复旧行为；插桩的 `logger.info` 调用属增量，可单独保留或回退。

## Open Questions

- 无重大未决项。`init_debug` 是否完全并入 `setup_logging` 留待 build 阶段定夺（倾向并入，减少入口）。
