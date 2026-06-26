# Brainstorm Summary

- Change: logging-system-overhaul
- Date: 2026-06-26

## Confirmed Technical Approach

- 集中式 `logging_config.setup_logging(debug)`，在 `create_app` 调用一次，替代 `app.py` 的 `logging.basicConfig`；`debug_trace.init_debug` 并入 `setup_logging`（移除 monkey-patch 后已空）
- `pdf_reader.*` 模块化 logger 层级（app/state/render/extract/translate/lifecycle/glossary/engine/routes/debug_trace），每模块 `getLogger("pdf_reader.<concern>")`
- 级别策略：INFO 常驻流程里程碑（开PDF/抽页/翻译起止+耗时/替换/合并）；DEBUG 高频与细节（渲染每页/token用量/第三方进度/term批次）。`log_*` 移除 `if not DEBUG: return`，改 `logger.info`/`logger.debug`
- token 用量 = DEBUG
- page 关联 = 方案 B 显式拼消息：流日志统一 `[page=N]`/`[batch=from-to]` 前缀；给 `run_translation` 加 `flow_label` 参数（如 `"page=2"`），编排线程起止/异常/超时日志用它拼消息
- 双输出：控制台 `StreamHandler` + `RotatingFileHandler('logs/pdf_reader.log', 5MB×5, utf-8)`，同 formatter；`debug_session` per-PDF 留档保留
- 第三方降级：`werkzeug`/`pdf2zh_next`/`babeldoc` 顶层 logger 设 DEBUG，debug off 不显示其 INFO
- 错误带上文文：SSE 异常分支 ERROR 带 page/batch + settings 摘要(provider/model/lang/pages) + tmpdir + exc_info；编排线程异常 ERROR+exc_info；join 超时 WARNING
- 移除 monkey-patch：`_apply_monkey_patches`/`patched_extract`/`_original_extract` 整段删；`debug-tracing` 的 LLM term extraction transparency 需求废弃

## Key Trade-offs and Risks

- INFO 常驻打破"debug off 零开销"旧承诺 → 有意取舍，spec 已用 MODIFIED 明确替换；每次翻译约 6-8 行可接受
- 显式拼消息靠约定 → 用测试 grep 守住"翻译流日志必带 `[page=`"约定
- 删 monkey-patch 后术语提取再出问题 → babeldoc 自带 `TranslationConfig.debug=True` tracking 文件 + INFO 流程能定位"是否进入术语阶段"；必要时临时恢复
- 磁盘 → 5MB×5 ≈ 30MB 封顶；api_key 不入日志

## Testing Strategy

- 新增 `test_logging_config`：handler 配置、第三方降级、logs 目录、无 basicConfig
- 流程测试：debug off 时 open/translate/replace 产 INFO；render 只 DEBUG；翻译记录带 `[page=N]`
- 错误上下文测试：generate 异常 ERROR 含 page+provider+model+exc_info
- 安全测试：启动摘要与错误日志不含 api_key
- 删 monkey-patch 用例；约定测试：grep 翻译流日志调用必带 `[page=`/`[batch=`

## Spec Patches

None. 现有 delta specs（application-logging / debug-tracing / debug-trace-module）已覆盖全部需求；`flow_label` 参数是实现细节，非 spec 要求。
