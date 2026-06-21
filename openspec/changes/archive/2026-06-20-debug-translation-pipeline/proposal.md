## Why

翻译流程目前对用户是一个黑箱——术语提取是否运行、LLM 返回了什么、解析是否成功、每个环节花了多久、失败在哪一步，全部不可见。用户反复遇到「术语表不生成」的问题却无法定位根因。需要通过可观测性改造，将整个翻译链路透明化。

## What Changes

- 新增 `--debug` CLI 参数，开启后启用全链路调试日志
- 开启 babeldoc `TranslationConfig.debug = True`，解锁内置调试追踪文件（`term_extractor_tracking.json`、`term_extractor_freq.json`、`auto_extractor_glossary.csv`）
- Monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs`，记录每批 LLM 术语提取的 prompt 长度、原始返回内容、解析结果、提取术语数量
- 增强 `routes.py` 翻译流程日志，输出每步的输入/输出/耗时/状态
- 调试文件输出至 `cache/<pdf_hash>/` 目录，与累积术语表同路径，方便事后排查

## Capabilities

### New Capabilities

- `debug-tracing`: 提供全链路可观测性的调试追踪模式，包括 LLM 交互细节、流程步骤状态、性能指标

### Modified Capabilities

<!-- 本次变更不修改任何现有 spec 的 REQUIREMENTS -->

## Impact

- `app.py`: 新增 `--debug` 命令行参数
- `services.py`: `build_settings` 接受 debug flag，设置 `TranslationConfig.debug = True`
- `routes.py`: 增强日志输出，翻译前后记录关键状态
- 新增 `debug_patches.py`: Monkey-patch `AutomaticTermExtractor` 模块，注入调试日志
- `config.py`: 可选新增 `DEBUG` 配置项
