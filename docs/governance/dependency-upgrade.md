# 依赖升级流程

> 建立日期：2026-08-30（P3-07/P3-06）。本文档定义 Python/Node 依赖的支持范围与升级方式；
> 升级上游翻译依赖（pdf2zh-next / BabelDOC）必须运行关键上游契约测试（P3-06）。

## 支持范围

| 运行时 | 支持范围 | 当前锁定/验证基线 |
|---|---|---|
| Python | `>=3.12`（`pyproject.toml` `requires-python`；锁文件按 3.12 生成） | 3.12.8（本机验证基线） |
| Node.js | `>=22`（`package.json` `engines`；仅前端测试需要） | CI 固定 22；本机验证基线 24.14.0 |

`scripts/verify.ps1` 在开头核验 Python 与 Node 主版本，低于支持范围立即失败并提示，
避免在错误版本组合下产生不可复现的验证结果。

## 升级方式

1. 自动依赖检查：`.github/dependabot.yml` 每月为 pip（`pyproject.toml`）与 npm
   （`package.json`）提交升级 PR。Dependabot 只更新直接声明；pip-tools 锁文件
   （`requirements.lock`）需按下方人工流程重新生成后随 PR 提交。
2. 人工流程（未用 Dependabot 或需要主动升级时）：
   - 修改 `pyproject.toml` / `package.json` 的直接依赖声明。
   - 按 `README.md` 记录的 `pip-compile` 命令重新生成 `requirements.lock`（Python 3.12 +
     pip-tools 7.6.1）；npm 用 `npm install` 更新 `package-lock.json`。
   - 运行 `python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py`。
   - 另运行 P0-01 上游边界守卫：`python -m pytest tests/test_upstream_boundary_governance.py`
     （拒绝影子包、上游源码副本与生产 Monkey-patch）。
   - 运行完整 `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`。
3. 升级 `pdf2zh-next` 或 BabelDOC 的强制前置条件：
   - 核对 `docs/pdf2zh-next-development-guide.md` 与 `docs/reports/` 的版本适用范围；
   - 运行关键上游契约测试：`python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py`；
   - P0-01 术语行为契约（`tests/test_upstream_contract.py` 内，升级前后都必须通过）：
     - `SharedContextCrossSplitPart.get_glossaries_for_translation` 的正文词表选择：
       auto-on 且自动词表存在时只返回自动词表（用户/累计词表不直接进入正文）、
       auto-off 返回 user+auto、auto-on 无自动词表时回退用户词表；
     - `build_settings` 的 `no_auto_extract_glossary` / `save_auto_extracted_glossary` /
       `glossaries` 映射（auto_extract_glossary=true → false/true/CSV 列表；
       false → true/false/相同 CSV 列表）；
     - 真实 `create_babeldoc_config` 会转发 `auto_extract_glossary`，但 pdf2zh-next 2.9.0
       不转发 `save_auto_extracted_glossary`（BabelDOC 恒为默认 true；auto-off 时无自动词表
       可保存）。若上游修复该缺口，先重新核验再决定是否简化适配；
     - 决策与边界记录见 `docs/governance/glossary-upstream-boundary.md`；
   - 契约范围（`tests/test_upstream_contract.py` 必须全部通过）：
     - 固定版本：`pdf2zh-next==2.9.0`、`babeldoc==0.6.2` 与 `pyproject.toml`/`requirements.lock`/安装元数据一致
       （babeldoc 是传递依赖，只由锁文件固定）；
     - `SettingsModel` 消费字段：`translation` 的 `lang_in`/`lang_out`/`ignore_cache`/`output`/`glossaries`/
       `save_auto_extracted_glossary`/`custom_system_prompt`，`pdf` 的 `pages`/`no_dual`/
       `only_include_translated_page`/`watermark_output_mode`，以及 `ENGINE_REGISTRY` 全部引擎字段映射；
     - 发送开关与 transform 契约（2.9.0 基线）：OpenAI 发送温度开关必须仍是历史拼写
       `openai_send_temprature`；`OpenAICompatibleSettings`/`AliyunDashScopeSettings` 的
       `send_temperature`/`send_reasoning_effort` 经 `transform()` 后必须进入 OpenAI 请求字段；
       DeepSeek v4 的 thinking transform 自动设置 reasoning 发送；`OpenAITranslator.options`
       必须真实携带 `temperature`/`reasoning_effort`（不联网契约测试锁定）；
     - PDFSettings 深层字段与默认（15 个）：`split_short_lines`、`short_line_split_factor`、
       `skip_clean`、`disable_rich_text_translate`、`enhance_compatibility`、
       `translate_table_text`、`skip_scanned_detection`、`ocr_workaround`、
       `auto_enable_ocr_workaround`、`no_merge_alternating_line_numbers`、
       `skip_formula_offset_calculation`、`non_formula_line_iou_threshold`、
       `figure_table_protection_threshold`、`formular_font_pattern`、`formular_char_pattern`
       必须存在且默认与 2.9.0 一致（本项目 `formula_*` 映射到历史拼写）；`term_pool_max_workers=0`
       的“跟随 pool_max_workers”语义需重新核对源码与测试；
     - 事件适配：`progress_start`/`progress_update`/`finish`/`error` 映射不变，未承诺事件（如
       `progress_end`）与未知事件保持忽略，心跳（空串）透传；
     - 输出路径：`settings.translation.output` 注入任务工作区 `output/`，`mono_pdf_path`→`dual_pdf_path`
       回退与 `auto_extracted_glossary_path` 适配不变；
     - 取消/流式：`do_translate_async_stream(settings, file)` 调用方式、协作式取消、迟到事件丢弃与
       `join`/`is_alive` 所有权接口不变。
     - 最小深层契约（0.6.2）：`babeldoc.format.pdf.translation_config.TranslateResult` 是私有路径
       （`pdf2zh_next` 顶层不公开该结果类型），承载 `mono_pdf_path` / `dual_pdf_path` /
       `auto_extracted_glossary_path` 三个输出字段；升级 BabelDOC 时若该路径不可用，必须先核对
       mono/dual/glossary 适配与 `tests/test_upstream_contract.py` 的构造 helper，再更新契约。
   - 若契约变化，先更新适配代码与测试，再合并依赖升级，禁止“先升级再观察”。
   - 升级前后都运行 P2-04/P0-01 上游边界守卫：
     `python -m pytest tests/test_upstream_boundary_governance.py`；若新上游原生修复了
     词表选择或边界匹配，先验证，再决定是否简化本地适配，不要直接删除本地正确性门。

## 升级记录

每次依赖升级在提交消息与 `CHANGELOG.md` 中记录：新版本、锁文件命令、契约测试结果与完整
验证基线。许可证影响见 `docs/governance/license.md`；易腐数字与长期文档更新时机见
`docs/governance/documentation.md`。
