## 1. 日志配置基础设施

- [ ] 1.1 新建 `logging_config.py`：定义 `setup_logging(debug: bool)`，配置根 `pdf_reader` logger（INFO/DEBUG 随 debug 切换）、控制台 `StreamHandler` + `RotatingFileHandler('logs/pdf_reader.log', maxBytes=5MB, backupCount=5, utf-8)`，统一 formatter
- [ ] 1.2 在 `setup_logging` 中显式将 `werkzeug` / `pdf2zh_next` / `babeldoc` 顶层 logger 设为 DEBUG
- [ ] 1.3 `setup_logging` 自动创建 `logs/` 目录（`logs/.gitkeep` 入库，日志文件不入库）
- [ ] 1.4 `app.py` 移除 `logging.basicConfig(level=logging.INFO)`，改为在 `create_app` 中调用 `logging_config.setup_logging(config.DEBUG)`

## 2. 重构 debug_trace.py

- [ ] 2.1 移除 `_apply_monkey_patches` / `patched_extract` / `_original_extract` / `AutomaticTermExtractor` import 与 `init_debug` 中的 patch 调用
- [ ] 2.2 `log_step` / `log_token_usage` / `log_glossary_merge` 移除 `if not config.DEBUG: return` 早返回；改为 `logger.info`（流程骨架）与 `logger.debug`（token 用量等细节），统一带 `[page=N]` / `[batch=from-to]` 前缀
- [ ] 2.3 `trace_logger` 切换为 `pdf_reader.debug_trace` 命名空间 logger，接入新配置体系；`debug_session` 的 per-PDF 文件留档逻辑保留并指向新 logger
- [ ] 2.4 `app.py` 中 `debug_trace.init_debug` 调用并入 `setup_logging` 或保留为薄封装（倾向并入）

## 3. 按模块插桩 — INFO 流程日志

- [ ] 3.1 `state.py`：`open_pdf` 成功后 INFO 记录 hash/页数/页宽高/cache 是否新建；`replace_page` / `replace_pages` 成功 INFO 记录页索引与 right.pdf 路径，失败 ERROR+exc_info
- [ ] 3.2 `pdf_renderer.py`：`render_page` 用 DEBUG 记录（side/page/耗时），确保 INFO 不刷屏
- [ ] 3.3 `pdf_extraction.py`：`extract_single_page` / `extract_pages` 用 DEBUG 记录抽页范围与临时路径
- [ ] 3.4 `translation_orchestrator.py`：线程启动/结束 INFO（带 page 上下文）；异常 ERROR+exc_info；`thread.join` 超时 WARNING
- [ ] 3.5 `sse_stream.py`：`generate` / `generate_batch` 的 `log_step` 调用迁移到 INFO 常驻；token 用量改 DEBUG；`[page=N]` / `[batch=from-to]` 前缀贯穿
- [ ] 3.6 `sse_stream.py`：异常处理分支由 `logger.warning("... generate error", exc_info=True)` 改为 ERROR 记录带 page/batch + settings 摘要（provider/model/lang/pages）+ 临时目录 + exc_info
- [ ] 3.7 `translation_lifecycle.py`：`finish_translation` / `merge_glossary_only` INFO 记录产物路径与合并耗时
- [ ] 3.8 `glossary_service.py`：`resolve_glossary_paths` DEBUG 记录解析结果；`merge_after_translate` WARNING（失败时）带文件路径
- [ ] 3.9 `routes.py`：关键端点（open/translate/translate-batch）的入口与参数校验失败 DEBUG 记录；非每请求的 404 保留现有
- [ ] 3.10 `engine_resolver.py` / `translation_settings.py`：`resolve_engine` 的 `Using engine` INFO 保留并改命名空间；`build_settings` DEBUG 记录 settings 摘要（无 api_key）

## 4. 启动配置摘要与安全

- [ ] 4.1 `app.py` 启动时 `pdf_reader.app` INFO 输出 provider/model/lang_in/lang_out/cache_dir/dpi/debug 摘要，确认不含 api_key
- [ ] 4.2 全项目 grep 复核：任何日志语句不含 `api_key` / `MODEL_API_KEY` 原值；settings 摘要构造器只取 provider/model/lang/path

## 5. 测试更新与新增

- [ ] 5.1 `tests/test_debug_trace.py`：移除 `test_init_debug_true_patches_extractor` / `test_init_debug_false_does_not_patch` 等 monkey-patch 用例；更新 `test_full_debug_trace_bytes_identical` 适配 INFO 常驻语义
- [ ] 5.2 新增 `tests/test_logging_config.py`：断言 `setup_logging` 后根 logger 拥有控制台+轮转文件 handler、werkzeug/pdf2zh_next/babeldoc 为 DEBUG、`logs/` 目录创建、`app.py` 无 `basicConfig`
- [ ] 5.3 新增流程日志测试：debug off 时 `open_pdf` / `translate` / `replace_page` 产出 INFO 记录；render 只在 DEBUG；翻译记录带 `[page=N]`
- [ ] 5.4 新增错误上下文测试：`generate` 异常时 ERROR 记录含 page + provider + model + exc_info
- [ ] 5.5 新增安全测试：启动摘要与错误上下文日志不含 api_key 值
- [ ] 5.6 更新 `tests/test_app.py`：`init_debug` 调用断言适配并入 `setup_logging` 后的形式

## 6. 文档与收尾

- [ ] 6.1 更新 `AGENTS.md`：记录日志约定（logger 命名空间、级别策略、page 前缀、运行/测试命令）
- [ ] 6.2 运行全量测试与 lint/typecheck，确认全绿
- [ ] 6.3 手动验证：debug off 打开并翻译一页，确认终端只剩项目 INFO 流程日志、文件有全量记录、第三方 INFO 噪音消失；debug on 确认 DEBUG 细节与第三方进度可见
