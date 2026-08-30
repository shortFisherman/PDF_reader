# PDF2ZH 配置能力扩展：设计决定与实施交接

> 状态：**已实施**（第一批至第三批已随 2026-08-30 配置扩展变更落地；阶段 4 文档同步已完成）  
> 记录日期：2026-08-30  
> 适用基线：当前项目代码、`pdf2zh-next==2.9.0`、`BabelDOC==0.6.2`  
> 文档用途：保留为设计决策与实现说明，不是 roadmap；本文不构成新的实施授权。当前事实以 [architecture.md](architecture.md) 与代码/测试为准。

> 历史语境：本文第 2～14 节记录实施前的背景、缺口、推荐方案与分阶段计划；已实现结果以 [architecture.md](architecture.md)、`config.example.toml` 与代码/测试为准。

## 1. 后续维护与升级如何使用本文

后续维护或升级本文涉及的配置面时，应按以下顺序恢复上下文：

1. 阅读本文，确认已确定的产品决定、已实施范围和分阶段历史。
2. 阅读 [project.md](project.md)，保持本地优先、用户可控、复用成熟上游等长期原则。
3. 阅读 [architecture.md](architecture.md) 中的配置、翻译任务、缓存、页面替换和测试章节；它以当前代码与测试记录当前事实。
4. 阅读 [pdf2zh-next 开发参考](pdf2zh-next-development-guide.md)，但不得把其中旧版本快照当作当前事实。
5. 重新核对 `pyproject.toml`、`requirements.lock`、当前安装包源码和 `tests/test_upstream_contract.py`。如果依赖版本已经变化，先按依赖升级流程重做字段契约核验，再决定是否调整适配代码。
6. 需要新的配置变更时建立独立变更/计划；不要仅凭本文的历史建议直接开始大范围代码修改。

本文把内容分为三类：

- **已确认产品决定**：本次变更已按此实施，后续调整需用户明确改变决定。
- **推荐实现方案**：实施时实际采用的技术路径（如有偏离，以 CHANGELOG 与 architecture.md 记录为准）。
- **暂缓项**：上游虽支持，但本次未接入。

## 2. 背景与问题

本项目不是 PDF2ZH 的完整 GUI，而是围绕本地双栏阅读、按页/范围翻译、页面回填、累计术语和阅读进度构建的前端与任务编排层。

当前项目直接构造 `pdf2zh_next.SettingsModel`，没有使用 PDF2ZH 自己的完整配置加载器：

- `src/pdf_reader/config.py` 只读取本项目 `config.toml` 中的白名单字段；
- `src/pdf_reader/engine_resolver.py` 只映射当前注册 Provider 的少量模型字段；
- `src/pdf_reader/translation_settings.py::build_settings` 手动创建 `BasicSettings`、`TranslationSettings` 和 `PDFSettings`；
- PDF2ZH 自己的 `~/.config/pdf2zh/config.v3.toml`、`--config-file`、`PDF2ZH_*` 环境变量以及 BabelDOC CLI 配置不进入本项目加载链路。

因此，上游已经支持的参数不会自动在本项目生效。要让用户使用某个参数，必须完成：

```text
config.toml 字段
    → 本项目解析和校验
    → 不可变运行时配置
    → PDF2ZH SettingsModel 字段映射
    → 契约测试和用户文档
```

实施前，`config.example.toml` 曾如实区分“当前接通”“读取但未发送”“上游支持但前端未暴露”；实施后它已是完整配置手册（见 [architecture.md](architecture.md) 与文件本身）。本设计的目标是把高价值且不破坏阅读器不变量的上游配置真正接通，该目标已随第一批至第三批实施完成。

## 3. 已确认的产品决定

本节是本次讨论的最终决定，不是待讨论建议。

### 3.1 缓存仍然只按原 PDF 哈希

继续沿用当前文档缓存身份：

```text
cache/<pdf_hash>/
    right.pdf
    cumulative_glossary.csv
    reading_progress.json
    ...
```

不得因为模型、语言、Prompt、OCR、字体、排版参数或其他新增配置变化而：

- 改成 `pdf_hash + config_hash`；
- 为不同配置建立不同缓存分支；
- 自动清空 `right.pdf`；
- 自动使已翻译页面失效；
- 增加逐页 Provider、模型或配置来源记录；
- 增加配置指纹、`translation_metadata.json` 或页面 provenance 元数据。

### 3.2 配置变化只影响后续翻译任务

示例语义：

1. 用户用 A 模型翻译第 1～5 页；
2. 用户修改配置并重启程序；
3. 用户用 B 模型翻译第 6 页；
4. 第 1～5 页继续保留 A 模型产生的译文；
5. 第 6 页使用 B 模型；
6. 用户主动重译第 3 页时，才用当前配置覆盖第 3 页。

项目不负责保证同一 PDF 的所有页面使用同一个模型、语言、Prompt 或高级参数。是否保持一致由用户决定。

实现和文档必须明确：

> 修改配置不会追溯更新已经写入文档缓存的译文。新配置只作用于之后执行的翻译或主动重译；当前页、范围或全文重译会覆盖对应页面。

不需要为配置变化增加阻塞提示、确认框或自动迁移。

### 3.3 累计术语表继续跨配置复用

`cumulative_glossary.csv` 继续只按 PDF 哈希保存：

- A 模型阶段提取和累计的术语可以继续提供给 B 模型；
- 切换模型、语言或高级设置不自动清空术语表；
- 本次配置扩展不新增术语表版本或来源追踪；
- 用户未来若需要清空/编辑术语表，应作为独立功能设计，不与本次配置扩展绑定。

### 3.4 前端页面缓存复用，但上游请求缓存继续跳过

两种缓存必须继续区分：

- **前端文档缓存**：`cache/<pdf_hash>/right.pdf`，继续复用已翻译页面；
- **PDF2ZH/BabelDOC 翻译请求缓存**：继续固定 `TranslationSettings.ignore_cache = true`。

理由：用户主动点击翻译或重译时，应按当前模型、Prompt、术语表和设置重新执行上游调用，不能因为上游缓存键覆盖不完整而拿到旧请求结果。

### 3.5 只开放白名单，不提供任意透传

不得增加以下形式的“万能”配置：

```toml
[pdf2zh.raw]
arbitrary_key = "arbitrary value"
```

每个可配置字段都必须有：

- 稳定的本项目字段名；
- 明确类型、默认值和范围；
- Provider/阶段适用范围；
- 到上游字段的显式映射；
- 无效组合的错误或 warning；
- 自动化测试；
- `config.example.toml` 说明。

### 3.6 结构性不变量继续由前端控制

用户可以让不同页面使用不同翻译配置，但不能通过 TOML 改变当前页面回填流程要求的输出结构。详见第 8 节。

## 4. 目标与非目标

> 历史语境：本节是实施前的目标清单；已实现范围以 [architecture.md](architecture.md) 为准。

### 4.1 目标

1. 修复当前“字段被读取但实际没有进入 API 请求”的配置缺口。
2. 开放对翻译质量、速率、并发、字体、术语和常见 PDF 兼容处理有价值的上游字段。
3. 保持老 `config.toml`、现有缓存目录和已翻译页面兼容。
4. 在启动阶段尽可能发现拼写、类型、范围、Provider 和字段组合错误。
5. 保持 API Key 不进入日志、异常文本、前端响应、文档或配置摘要。
6. 用上游契约测试锁住所有新增映射，降低未来升级风险。

### 4.2 非目标

本次配置扩展不负责：

- 升级 `pdf2zh-next`、BabelDOC 或 PyMuPDF；
- 开启 BabelDOC 0.6.4；
- 实现设置页面或运行时热更新；
- 记录每页由哪个模型或配置生成；
- 改变 PDF 哈希缓存身份；
- 增加缓存自动失效、缓存分支或迁移格式；
- 增加新的翻译 Provider；
- 接入 PDF2ZH 自己的 TOML/CLI/环境变量配置管理器；
- 支持双语输出、交替页输出、分卷多文件输出；
- 允许用户控制任务输出目录或页面选择内部参数；
- 重构整个翻译任务、SSE 或页面替换架构。

## 5. 实施前实现基线（历史）

以下是实施前确认的事实基线；当前事实以 [architecture.md](architecture.md) 为准。

### 5.1 实施前 TOML 读取面

当时读取 16 个字段：

```text
[pdf_reader]
  dpi, cache_dir

[model]
  provider, api_key, model, base_url, thinking_mode,
  reasoning_effort, enable_json_mode, temperature, timeout

[translation]
  lang_in, lang_out

[server]
  host, port, debug
```

当时的环境覆盖包括：

- `MODEL_API_KEY`；
- `PDF_READER_DEBUG`；
- `PDF_READER_ROOT`；
- `PDF_READER_DATA_ROOT`。

配置在进程启动/模块导入阶段读取，修改文件后需要重启。

### 5.2 实施前 SettingsModel 组装

实施前，`build_settings` 把以下值写死：

```python
BasicSettings(debug=False)

TranslationSettings(
    lang_in=...,
    lang_out=...,
    ignore_cache=True,
    save_auto_extracted_glossary=True,
    # custom_system_prompt / glossaries / output 按任务注入
)

PDFSettings(
    pages=...,
    no_dual=True,
    only_include_translated_page=True,
    watermark_output_mode="no_watermark",
)
```

### 5.3 结果消费契约（实施前后一致）

生命周期（实施前后保持一致）：

- 优先使用 `translate_result.mono_pdf_path`；
- 没有 mono 时才回退 `dual_pdf_path`；
- 单页/批量输出的第 `j` 页被插入 `right.pdf` 的第 `page_indices[j]` 页；
- 页面提交成功后再合并自动术语表；
- 临时输入和输出必须位于当前任务的带标记工作区；
- 同时只有一个会修改文档的翻译任务。

任何新增配置都不能破坏“上游输出页数与本次待替换页数一一对应”的契约。

### 5.4 实施前已知配置缺口（现已解决）

1. `temperature` 会进入 Aliyun/OpenAI/OpenAI Compatible Settings，但当时未设置相应 `send_temperature`，所以不会进入实际 API 请求。——现已解决：`[model].send_temperature` 已接通并真实进入请求选项（映射见 [architecture.md](architecture.md) 配置章节）。
2. OpenAI/OpenAI Compatible 的 `reasoning_effort` 会进入 Settings，但当时未设置 `send_reasoning_effort`，所以不会进入实际 API 请求。——现已解决：`[model].send_reasoning_effort` 已接通，OpenAI 系开启后真实进入请求选项。
3. DeepSeek v4 是例外：`thinking_mode="enabled"` 时，上游 transform 会自动设置 reasoning 发送开关。——该行为在实施后保持不变。
4. 未知 Provider 当时回退到 `openai_compatible`，可能把拼写错误延迟到翻译阶段。——现已解决：未知 Provider 在启动期抛 `ConfigError`，不再兜底。
5. `openai_compatible` 的 `base_url` 是上游必填，但当时没有在启动校验阶段按 Provider 检查。——现已解决：缺少 `base_url` 时启动直接失败。
6. 未知 TOML 字段和部分不适用字段当时可能被静默忽略。——现已解决：未知 section/key 启动报错；已知但不适用于当前 Provider 的字段输出明确 warning。

## 6. 推荐配置结构

新增字段建议继续使用本项目 TOML，而不是引入第二套 PDF2ZH 配置文件。

### 6.1 `[model]`：模型请求参数

在现有字段基础上增加两个显式发送开关：

```toml
[model]
provider = "deepseek"
api_key = "sk-your-api-key-here"
model = "deepseek-chat"

# 现有字段
# base_url = "https://example.com/v1"
# thinking_mode = "enabled"
# reasoning_effort = "high"
# enable_json_mode = true
# temperature = "0.2"
# timeout = "500"

# 新增字段；默认 false
# send_temperature = true
# send_reasoning_effort = true
```

字段规则见第 7.1 节。

### 6.2 `[translation]`：翻译文本、并发、术语和字体

建议第一批扩展：

```toml
[translation]
lang_in = "en"
lang_out = "zh"

# 少于该长度的文本不翻译；默认 5
min_text_length = 5

# 主翻译请求速率；默认 4
qps = 4

# 省略时由上游跟随 qps
# pool_max_workers = 4

# 省略时跟随 qps / pool_max_workers
# term_qps = 4
# term_pool_max_workers = 4

# 当前行为等价于 true
auto_extract_glossary = true

# "auto" / "serif" / "sans-serif" / "script"
primary_font_family = "auto"

# 全局默认 Prompt；省略时使用上游默认
# default_system_prompt = "/no_think You are a professional translation engine."
```

页面输入框中的非空 Prompt 优先于 `default_system_prompt`：

```text
页面任务 Prompt（非空） > translation.default_system_prompt > 上游默认 Prompt
```

### 6.3 `[pdf2zh]`：高级 PDF 处理参数

建议使用独立 `[pdf2zh]` 段，避免与 `[pdf_reader]` 的页面预览 DPI/前端缓存混淆：

```toml
[pdf2zh]
# 段落与短行
split_short_lines = false
short_line_split_factor = 0.8

# 清理与兼容性
skip_clean = false
disable_rich_text_translate = false
enhance_compatibility = false

# 表格（上游实验性）
translate_table_text = true

# 扫描/OCR
skip_scanned_detection = false
ocr_workaround = false
auto_enable_ocr_workaround = false

# 行号、图表与公式处理
no_merge_alternating_line_numbers = false
skip_formula_offset_calculation = false
non_formula_line_iou_threshold = 0.9
figure_table_protection_threshold = 0.9

# 本项目使用正确拼写，内部映射到上游历史字段 formular_*
# formula_font_pattern = "..."
# formula_char_pattern = "..."
```

这批字段应在第一批核心配置稳定后单独实施和验收，不建议与发送开关修复塞进同一个不可审查的大改动。

## 7. 字段目录与映射

### 7.1 模型字段

| 本项目字段 | 类型/默认 | 适用 Provider | 上游映射与要求 |
|---|---|---|---|
| `send_temperature` | `bool=false` | `aliyun`、`openai`、`openai_compatible` | Aliyun → `aliyun_dashscope_send_temperature`；OpenAI → `openai_send_temprature`（上游历史拼写错误，必须照此映射）；Compatible → `openai_compatible_send_temperature`。为 `true` 时必须同时设置可解析为浮点数的 `temperature`。 |
| `send_reasoning_effort` | `bool=false` | `openai`、`openai_compatible` | OpenAI → `openai_send_reasoning_effort`；Compatible → `openai_compatible_send_reasoning_effort`。为 `true` 时必须同时设置 `reasoning_effort`。DeepSeek 不使用本开关，它在 v4 thinking transform 中自动发送。 |
| `temperature` | `str\|None` | 同上 | 不在本项目强行规定 `0～2`；只校验非空且可解析为有限浮点数（拒绝 nan/inf/-inf），最终允许范围由 Provider 决定。`send_temperature=false` 且显式配置值时输出 warning，不再声称它已生效。 |
| `reasoning_effort` | `str\|None` | DeepSeek/OpenAI 系 | DeepSeek 仅允许 `high`/`max`，并要求 `deepseek-v4-* + thinking_mode=enabled` 才实际发送；OpenAI 系按当前上游允许 `minimal`/`low`/`medium`/`high`，且要求发送开关。 |
| `timeout` | 正数形式的字符串 | `aliyun`、`openai`、`openai_compatible` | 上游接受正浮点数字符串，不应错误限制为正整数。 |

Provider 校验建议：

- 未知 `provider` 在启动时抛 `ConfigError`，不要继续静默回退；
- `openai_compatible` 缺 `base_url` 时启动失败；
- 显式设置当前 Provider 不支持的高级字段时至少输出明确 warning；
- 未设置发送开关时保持当前行为，确保老配置不突然改变请求参数；
- 所有错误不得包含 API Key 原值。

### 7.2 翻译字段

| 本项目字段 | 类型/默认 | 上游字段 | 校验/语义 |
|---|---|---|---|
| `min_text_length` | `int=5` | `TranslationSettings.min_text_length` | 非布尔整数，建议 `>=0`；使用上游当前约束作为最终依据。 |
| `qps` | `int=4` | `TranslationSettings.qps` | 非布尔整数，`>=1`。高值可以 warning，不建议未经产品决定设置武断的硬上限。 |
| `pool_max_workers` | 可选正整数 | 同名字段 | 省略时保持 `None`，由上游跟随 qps；显式设置时使用正整数。 |
| `term_qps` | 可选正整数 | 同名字段 | 省略时保持 `None`，跟随 qps。 |
| `term_pool_max_workers` | 可选正整数 | 同名字段 | 省略时保持 `None`，跟随普通 worker 设置。若当前上游对 `0` 有特殊含义，实施时必须重新核对 2.9.0 源码并写测试，不凭记忆处理。 |
| `auto_extract_glossary` | `bool=true` | `no_auto_extract_glossary` + `save_auto_extracted_glossary` | `true` → `False + True`，保持当前自动提取并保存/合并行为；`false` → `True + False`。 |
| `primary_font_family` | `str="auto"` | 同名字段 | `auto` 映射 `None`；其余仅允许 `serif`、`sans-serif`、`script`。 |
| `default_system_prompt` | 可选非空字符串 | `custom_system_prompt` | 页面非空 Prompt 覆盖它；两者都没有时不传字段，保留上游默认。不要记录 Prompt 原文到日志。 |

并发注意事项：当前 `TranslationCoordinator` 的单槽只限制“同时一个文档修改任务”，不会限制该任务内部的上游请求线程数。`qps` 和 worker 参数可能显著增加连接数、API 消耗和限流概率，因此示例文档必须解释，而不能只给最大性能示例。

### 7.3 PDF 高级字段

| 本项目字段 | 类型/默认 | 上游映射 | 校验/风险 |
|---|---|---|---|
| `split_short_lines` | `bool=false` | 同名 | 改变段落拆分；需要版面回归样本。 |
| `short_line_split_factor` | `float=0.8` | 同名 | 非布尔数值；开启短行拆分时按上游要求校验（当前至少 `>=0.1`）。 |
| `skip_clean` | `bool=false` | 同名 | 可能改善特殊 PDF，也可能保留干扰元素。 |
| `disable_rich_text_translate` | `bool=false` | 同名 | 影响富文本翻译与样式保留。 |
| `enhance_compatibility` | `bool=false` | 同名 | 会联动兼容增强行为，必须做真实 PDF 回归。 |
| `translate_table_text` | `bool=true` | 同名 | 上游实验性；文档需标明。 |
| `skip_scanned_detection` | `bool=false` | 同名 | 跳过扫描文档检测。 |
| `ocr_workaround` | `bool=false` | 同名 | 可能强制黑字白底，影响视觉结果。 |
| `auto_enable_ocr_workaround` | `bool=false` | 同名 | 与扫描检测联动，需组合测试。 |
| `no_merge_alternating_line_numbers` | `bool=false` | 同名 | 针对带交替行号的论文/代码排版。 |
| `skip_formula_offset_calculation` | `bool=false` | 同名 | 影响公式位置计算。 |
| `non_formula_line_iou_threshold` | `float=0.9` | 同名 | 必须在 `[0,1]`。 |
| `figure_table_protection_threshold` | `float=0.9` | 同名 | 必须在 `[0,1]`。 |
| `formula_font_pattern` | 可选字符串 | `formular_font_pattern` | 本项目采用正确拼写；传给上游历史拼写字段。必须预编译验证正则。 |
| `formula_char_pattern` | 可选字符串 | `formular_char_pattern` | 同上。 |

实施时不得仅验证 Pydantic 对象能构造，还应选择至少以下回归样本：

- 普通文本型论文；
- 含表格和图片的论文；
- 含大量公式的论文；
- 扫描型 PDF；
- 带行号或特殊段落布局的 PDF；
- 单页与多页批量翻译。

## 8. 必须保持内部固定的字段

这些字段暂时不得暴露到 `config.toml`：

| 上游字段/能力 | 当前要求 | 原因 |
|---|---|---|
| `pages` | 路由/任务动态注入 | 由当前页、范围和全文操作决定；配置值会与抽取页范围冲突。 |
| `output` | 任务工作区动态注入 | 必须位于带标记的 `output/`，保证清理、崩溃恢复和结果归属。 |
| `glossaries` | 项目动态组合 | 由全局 `docs/glossary.csv` 和当前文档累计术语表组成。 |
| `custom_system_prompt` | 页面任务输入；可增加默认值但不能取消任务覆盖 | 非空页面 Prompt 是按任务控制。 |
| `ignore_cache` | 固定 `true` | 用户发起翻译/重译时必须按当前设置重新调用上游；前端 `right.pdf` 仍负责结果复用。 |
| `no_dual` | 固定 `true` | 右侧需要纯译文页；双语输出可能改变页数和内容结构。 |
| `no_mono` | 保持 `false`/上游默认 | 当前生命周期优先消费 `mono_pdf_path`。 |
| `only_include_translated_page` | 固定 `true` | 确保上游输出页数与本次待替换页数一致。 |
| `use_alternating_pages_dual` | 固定 `false` | 会改变页面顺序和数量。 |
| `dual_translate_first` | 固定 `false` | 当前不消费双语输出。 |
| `max_pages_per_part` | 保持 `None` | 分卷可能产生多个文件，当前生命周期只消费单个结果路径。 |
| `watermark_output_mode` | 固定 `no_watermark` | `both` 可能产生多个输出分支；当前没有选择/写回契约。若未来开放，只能独立设计。 |
| `BasicSettings.debug` | 固定 `false` | 它不是 Flask debug；可能改变上游执行模式和调试产物。 |
| `BasicSettings.gui/input_files` | 内部控制 | 项目使用自己的 Flask UI 和任务输入路径。 |

如果未来要开放这些字段，必须先改变输出模型或页面替换算法，不能作为本次“增加配置键”顺手加入。

## 9. 推荐代码结构

### 9.1 不再无限扩张模块级全局量

当前 `config.MODEL_*` 和 `TRANSLATION_LANG_*` 数量较少，但新增几十个字段后继续使用模块全局量会让：

- 校验分散；
- Provider 组合难以测试；
- `build_settings` 隐式依赖增多；
- `create_app` 的不可变设置边界失去意义；
- 配置摘要和密钥脱敏更难维护。

推荐在 `src/pdf_reader/config.py` 定义不可变运行时对象：

```python
@dataclass(frozen=True)
class ModelRuntimeConfig:
    provider: str
    api_key: str = field(repr=False)
    model: str
    base_url: str | None
    thinking_mode: str | None
    reasoning_effort: str | None
    send_reasoning_effort: bool
    enable_json_mode: bool | None
    temperature: str | None
    send_temperature: bool
    timeout: str | None


@dataclass(frozen=True)
class TranslationRuntimeConfig:
    lang_in: str
    lang_out: str
    min_text_length: int
    qps: int
    pool_max_workers: int | None
    term_qps: int | None
    term_pool_max_workers: int | None
    auto_extract_glossary: bool
    primary_font_family: str | None
    default_system_prompt: str | None


@dataclass(frozen=True)
class Pdf2zhRuntimeConfig:
    # 只包含本次批准开放的 PDF 高级字段
    ...


@dataclass(frozen=True)
class UpstreamRuntimeConfig:
    model: ModelRuntimeConfig
    translation: TranslationRuntimeConfig
    pdf: Pdf2zhRuntimeConfig
```

API Key 字段必须 `repr=False`，任何摘要都只能白名单输出非敏感字段。

可以把 `UpstreamRuntimeConfig` 加入现有 `AppSettings`，由 `main` 在启动校验后冻结并传给 Flask 应用。不得放进会序列化给浏览器的响应。

### 9.2 让 SettingsModel 构造显式接收配置

推荐逐步改为：

```python
def build_settings(
    upstream: UpstreamRuntimeConfig,
    input_pdf: str,
    user_prompt: str | None = None,
    output_dir: str | None = None,
    glossary_paths: list[str] | None = None,
    pages: str = "1",
) -> SettingsModel:
    ...
```

`engine_resolver.build_engine_kwargs` 也应接收 `ModelRuntimeConfig`，不要继续从 `config` 模块隐式读取所有值。

路由从 `current_app.config["app_settings"]` 取得冻结配置并传入。测试中的 fake `build_settings` 签名必须同步更新。

如果实施者为了降低单次改动风险，第一阶段暂时保留模块常量，也必须把“迁移到不可变配置对象”列入同一变更的后续步骤，不能长期形成两套来源。

### 9.3 启动校验优先

新增字段应尽量在 `validate_startup_requirements` 阶段报错，而不是让用户点击翻译后才看到上游异常。

建议校验顺序：

1. TOML section 必须是 table；
2. 未知 section/键报告明确错误；
3. 基础类型和范围；
4. Provider 是否为已注册精确名称；
5. Provider 必填字段；
6. 发送开关与对应值的组合；
7. Provider 不支持字段 warning/错误；
8. 正则表达式编译；
9. 构造一次不联网的上游 Settings 对象，验证当前版本契约。

兼容策略：

- 未知 Provider 建议立即报错；
- 完全未知的字段建议报错，避免拼写错误静默失效；
- 已知但对当前 Provider 不适用的字段，第一版可 warning 并忽略，以减少现有配置迁移冲击；
- 任何 warning 和异常不得显示 API Key。

## 10. 分阶段实施计划

### 阶段 0：建立失败测试与配置对象边界

1. 为新增字段写启动解析、默认值、类型、范围和错误消息测试。
2. 建立 `ModelRuntimeConfig`、`TranslationRuntimeConfig`、`Pdf2zhRuntimeConfig`、`UpstreamRuntimeConfig`。
3. 将 API Key 标为不可 repr，并验证日志/异常不泄漏。
4. 保证没有新增字段时，构造出的 SettingsModel 与当前行为一致。

### 阶段 1：修复模型发送开关

1. 增加 `[model].send_temperature`。
2. 增加 `[model].send_reasoning_effort`。
3. 扩展 `CONFIG_ATTR_MAP` 和各 `EngineSpec.field_map`。
4. 特别处理 OpenAI 上游字段的历史拼写 `openai_send_temprature`。
5. 启动时校验发送开关和值、Provider 适用范围和 Compatible base URL。
6. 用不联网测试检查 transform 后的 OpenAI Settings/translator options，确认参数真实进入请求选项，而不是只进入 Pydantic 字段。

阶段 1 完成后，`config.example.toml` 中的 `temperature` 和 OpenAI reasoning 不再标记为“读取但不发送”，而应按真实 Provider 行为更新矩阵。

### 阶段 2：开放翻译核心参数

接入：

- `min_text_length`；
- `qps`；
- `pool_max_workers`；
- `term_qps`；
- `term_pool_max_workers`；
- `auto_extract_glossary`；
- `primary_font_family`；
- `default_system_prompt`。

验证页面 Prompt 优先级、自动术语开关映射、worker 跟随语义和旧配置默认兼容。

### 阶段 3：开放 PDF 高级参数

按类别拆分实现和测试：

1. 短行与段落；
2. 清理、富文本和兼容性；
3. 表格；
4. 扫描/OCR；
5. 行号、图表和公式；
6. 正则和阈值。

每一类先写字段契约和真实 PDF 回归，再接下一类。不得一次性打开所有上游 PDFSettings 后只做对象构造测试。

### 阶段 4：文档与治理同步

1. （已完成）更新 `config.example.toml`，只写已经真正接通的字段。
2. （已完成）更新 README 的配置入口说明，避免复制完整字段手册。
3. （已完成）更新 `docs/architecture.md`，记录实施后的实际读取面和固定不变量。
4. （已完成）更新 `CHANGELOG.md`。
5. （已完成）更新 `docs/governance/dependency-upgrade.md`（本次新增的发送开关与 PDFSettings 深层契约检查项）。

## 11. 测试要求

### 11.1 配置解析与校验

建议新增 `tests/test_translation_config.py` 或等价测试文件，覆盖：

- 所有新字段省略时的默认值；
- 正确类型和边界值；
- bool 不能冒充 int；
- `qps=0`、负 worker、非法阈值、非法正则等拒绝；
- `primary_font_family` 枚举；
- `temperature`/`reasoning_effort` 与发送开关组合；
- Provider 不支持字段；
- 未知 Provider、未知键；
- OpenAI Compatible 缺 base URL；
- `MODEL_API_KEY` 覆盖仍然有效且不泄漏。

### 11.2 SettingsModel 映射

扩展 `tests/test_services.py`：

- 每个新增 TranslationSettings/PDFSettings 字段都断言最终值；
- `auto_extract_glossary` 的正反映射；
- 页面 Prompt 与默认 Prompt 的优先级；
- `ignore_cache`、`pages`、`output`、`glossaries` 和结构性固定值不被用户配置覆盖。

### 11.3 Provider 映射

扩展 `tests/test_engine_registry.py`：

- 所有 unified field 都存在配置来源；
- 每个 Provider 映射到当前上游 Settings 的真实字段；
- OpenAI `temprature` 历史拼写有明确契约测试；
- 不支持字段产生预期 warning/错误；
- 未知 Provider 不再静默兜底（若按推荐实施）。

### 11.4 上游契约

扩展 `tests/test_upstream_contract.py`：

- 新消费的上游字段必须存在；
- 当前锁定版本的默认值和约束符合本文；
- transform 后发送开关真实进入 translator 请求 options；
- SettingsModel 构造仍然离线、确定性、不调用真实 API。

### 11.5 缓存与页面替换回归

必须证明本次变更没有偷偷改变已确认缓存语义：

- 缓存路径仍是 `cache/<pdf_hash>`；
- 不新增 config/profile 哈希目录；
- 不新增逐页来源元数据；
- 打开已有 `right.pdf` 仍复用旧译文；
- 新翻译只替换所选页；
- 全文翻译可以覆盖全部页；
- 累计术语表继续位于同一文档哈希目录；
- `ignore_cache` 仍为 `true`；
- 页面替换失败时保留原 `right.pdf` 和当前事务语义。

现有 `tests/test_pdf_replace_transaction.py`、`tests/test_state.py`、`tests/test_system_concurrency_failure.py` 应保持通过。

### 11.6 文档契约

建议增加配置示例一致性测试：

- `config.example.toml` 可被 `tomllib` 解析；
- 示例中的活跃键属于已支持白名单；
- 已支持字段目录与解析器字段集合一致；
- 示例不包含真实 Key；
- 文档不把上游支持但尚未接通的字段写成可用。

## 12. 向后兼容与迁移

### 12.1 旧配置

没有新增键的旧 `config.toml` 必须保持当前行为：

- `min_text_length=5`；
- `qps=4`；
- worker 省略并跟随上游；
- 自动术语提取和保存继续开启；
- 字体自动选择；
- PDF 高级字段保持当前上游默认；
- `send_temperature=false`；
- `send_reasoning_effort=false`（DeepSeek v4 现有自动 transform 除外）。

### 12.2 旧缓存

不得迁移、重命名或删除已有：

- `right.pdf`；
- `cumulative_glossary.csv`；
- `reading_progress.json`；
- 文档哈希目录。

新增配置上线后，旧页继续存在；只有用户主动翻译/重译的页面使用新设置。

### 12.3 `config.example.toml`

示例更新原则：

- 默认段保持可读，不把所有高级字段都设为活跃值；
- 可选字段以注释形式给出；
- 每项说明类型、默认、范围、适用 Provider 和副作用；
- 模型目录不写成长期有效清单；
- 对 QPS、线程、OCR、实验性表格和兼容性开关给出资源/质量提示；
- 明确“配置变化只影响后续翻译，不使旧页失效”。

## 13. 暂缓项

以下上游能力不在第一轮配置扩展中：

- 独立术语提取 Provider 和第二套凭据；
- SiliconFlow 专有 thinking/send thinking 参数（可在核心发送开关稳定后单独设计）；
- `rpc_doclayout`（涉及外部网络端点、可用性和安全边界）；
- `report_interval`（用户价值低，过低会增加 SSE/队列压力）；
- 语义容易误解的 `no_remove_non_formula_lines`，实施前必须重新核对当前源码和实际效果；
- 输出双语/交替页/多文件/分卷参数；
- 新 Provider 注册；
- PDF2ZH GUI、离线资产、warmup 和批量 input_files；
- 任意 raw 参数透传。

暂缓不等于永久否决；需要时建立独立设计。

## 14. 建议修改文件

预计至少涉及：

| 文件 | 修改目的 |
|---|---|
| `src/pdf_reader/config.py` | 新配置对象、解析、默认、严格校验、Provider 组合校验。 |
| `src/pdf_reader/engine_resolver.py` | 发送开关和 Provider 字段映射；改为显式接收模型配置。 |
| `src/pdf_reader/translation_settings.py` | 把翻译/PDF 高级字段传入 SettingsModel，同时保护内部固定值。 |
| `src/pdf_reader/app.py` | 把冻结的上游运行时配置纳入 AppSettings/启动装配。 |
| `src/pdf_reader/routes.py` | 调用 `build_settings` 时传入冻结配置；不改变路由和缓存语义。 |
| `config.example.toml` | 更新真实可用字段、矩阵、默认和副作用。 |
| `README.md` | 更新入口和简要行为说明。 |
| `tests/test_config_deferred.py` 或新配置测试 | 解析、错误、默认、环境覆盖。 |
| `tests/test_engine_registry.py` | Provider 映射与发送开关。 |
| `tests/test_services.py` | SettingsModel 最终字段值。 |
| `tests/test_upstream_contract.py` | 锁定新增上游字段和 transform 行为。 |
| 缓存/系统级测试 | 证明 PDF hash 缓存和页面替换语义未改变。 |
| `docs/architecture.md`、`CHANGELOG.md` | 实施完成后同步当前事实和历史。 |

## 15. 验收标准

只有同时满足以下条件，配置扩展才能标记完成：

1. 老配置不加任何字段时行为不变。
2. 新字段全部有明确类型、默认、范围和错误信息。
3. `send_temperature=true` 时，支持 Provider 的实际 translator 请求选项包含 temperature。
4. `send_reasoning_effort=true` 时，OpenAI 系实际请求选项包含 reasoning effort。
5. 发送开关关闭时不改变旧请求行为。
6. 核心翻译配置真实进入 `TranslationSettings`。
7. PDF 高级配置真实进入 `PDFSettings`，且真实 PDF 回归通过。
8. `pages`、`output`、`glossaries`、`ignore_cache`、单语输出和页数匹配不变量无法被用户配置覆盖。
9. 缓存继续只按 PDF 哈希；没有配置指纹、逐页来源或自动失效。
10. 配置变化只影响后续任务；旧译文页面继续复用。
11. 累计术语表继续跨配置复用。
12. API Key、Prompt 原文和敏感 Header 不进入日志、异常、响应或文档。
13. `config.example.toml` 与代码支持面一致。
14. 上游契约、配置、服务、页面替换、缓存和系统级测试全部通过。
15. 当前事实文档和 CHANGELOG 已按文档治理要求同步。

## 16. 实施时仍需明确的小问题

这些问题不改变核心方向，但正式变更计划应给出答案：

1. 高 QPS/worker 只 warning，还是设置项目级硬上限？本次倾向尊重用户控制、采用上游下限并对异常高值 warning，不先武断设上限。
2. 未知字段是立即报错，还是先 warning 一个版本？本文推荐未知字段报错；已知但 Provider 不适用字段可先 warning。
3. `default_system_prompt` 是否进入第一批？本文推荐进入，并采用“页面非空 Prompt 优先”的规则。
4. PDF 高级字段是一次交付还是按类别拆分？本文强烈建议拆分。
5. 是否为配置对象重构单独建立前置变更？如果一次改动过大，可以先做配置对象边界，再做字段接线，但不得长期保留两套来源。

## 17. 一句话设计结论

> 在不改变 PDF 哈希缓存、旧页复用、累计术语和页级回填语义的前提下，以强类型白名单分阶段开放 PDF2ZH 的高价值模型、并发、术语、字体和 PDF 处理参数；配置只影响后续翻译，输出结构和任务生命周期相关字段继续由前端内部控制。
