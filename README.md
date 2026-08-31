# 双语 PDF 阅读器

这是一个用于阅读英文教材和论文的本地双语 PDF 阅读器。左栏显示原文，右栏显示译文，支持在阅读过程中按页、按范围或全文调用大模型翻译。

PDF 版面翻译由 [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) / `pdf2zh-next` 提供。本项目主要负责本地阅读界面、按需翻译编排、双栏对齐、缓存和阅读状态。

## 当前功能

- 双栏连续滚动和双向页面对齐。
- 当前页、页码范围和全文翻译。
- SSE 翻译阶段与进度显示。
- 自定义翻译提示词。
- 按 PDF 隔离的累积术语表。
- 旁路候选术语提取：正文提交成功后自动收集模型候选，仅用户确认后才影响正文。
- 译文和阅读位置持久化。
- 大型 PDF 页面懒加载和卸载。
- Ctrl + 鼠标滚轮缩放。
- 多种 LLM 服务和 OpenAI 兼容接口。

## 已知边界

- 仅面向本机单用户、单文档使用，不适合直接部署为多用户服务。
- 页面以图片显示，不支持文本选择、搜索、复制、高亮、批注、目录或 PDF 内部链接。
- 没有翻译任务暂停、取消、持久队列或重启后续传。
- 使用前需要 Python 环境、模型 API Key 和本地 PDF 路径。

## 文档导航

- [项目记忆](docs/project.md)：项目为什么存在、长期意图、常青原则和产品边界。
- [当前架构](docs/architecture.md)：当前 HEAD 的模块、数据流、API、状态、依赖、测试和技术约束。
- [路线图](docs/roadmap.md)：候选方向、开放问题、依赖和决策状态；不构成实施授权。
- [工程与架构长期改进清单](docs/completed%20improvements/engineering-improvement-plan-829.md)：按优先级跟踪可靠性、任务生命周期、目录结构和工程卫生改进（P0–P3 已收口，文档保留在 `docs/completed improvements/`）。
- [pdf2zh-next 开发参考](docs/pdf2zh-next-development-guide.md)：涉及上游接口、事件和配置时按版本范围阅读。
- [工具与工作流目录治理](docs/governance/tool-directories.md)：`.agents/`、`.codex/`、`.comet/`、`.opencode/`、`openspec/` 等目录的职责、跟踪与重建边界。
- [依赖升级流程](docs/governance/dependency-upgrade.md)：Python/Node 支持范围与上游翻译依赖升级契约。
- [长期文档治理](docs/governance/documentation.md)：三份长期文档的更新时机、上游升级步骤、易腐数字政策与事实冲突优先级。

## 环境要求

- Windows 10 或更高版本。
- Python 3.12（`pyproject.toml` `requires-python` 为 `>=3.12`，锁文件按 3.12 生成）。
- Node.js 22 或更新版本（`package.json` `engines.node` 为 `>=22`；只在运行前端测试时需要，CI 固定 22）。
- 可用的 LLM API Key。

## 安装

```powershell
git clone https://github.com/shortFisherman/PDF_reader.git
cd PDF_reader
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps
Copy-Item config.example.toml config.toml
```

`pyproject.toml` 是唯一直接依赖声明源：`project.dependencies` 声明运行直接依赖，`project.optional-dependencies.dev` 声明 pytest、Ruff、coverage、mypy 与 pip-tools（P2-03 才启用 coverage/类型检查，本项只建立依赖边界）。`requirements.lock` 是 README、CI 和本地验证共同使用的唯一锁文件，由 Python 3.12 与 pip-tools 7.6.1 从 `pyproject.toml`（含 dev extra）生成：

```powershell
py -3.12 -m venv .tmp-lock-venv
.\.tmp-lock-venv\Scripts\python.exe -m pip install pip-tools==7.6.1
$env:CUSTOM_COMPILE_COMMAND = 'pip-compile --resolver=backtracking --strip-extras --extra=dev --output-file=requirements.lock pyproject.toml'
.\.tmp-lock-venv\Scripts\python.exe -m piptools compile --resolver=backtracking --strip-extras --extra=dev --output-file requirements.lock pyproject.toml
Remove-Item Env:CUSTOM_COMPILE_COMMAND
```

说明：pip-tools 7.6.1 在本环境会在 header 记录多余的 `--no-index`；用其官方 `CUSTOM_COMPILE_COMMAND` 机制把 header 固定为上面的真实命令（最小调整）。生成后应删除临时环境，并在新的 Python 3.12 虚拟环境中执行 `pip install -r requirements.lock` + `pip install -e . --no-deps`、关键导入和完整验证。不要从日常工作环境运行 `pip freeze` 更新锁文件。

便捷安装（非可复现开发/验证安装）：直接 `pip install -e .[dev]` 会从索引解析最新兼容版本；可复现安装必须使用上面的锁文件流程。

例如，可将干净环境的解释器显式传给统一验证脚本，避免误用仓库中已有的 `venv`：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1 -PythonExecutable .\.tmp-verify-venv\Scripts\python.exe
```

## 配置

把 [config.example.toml](config.example.toml) 复制为 `config.toml` 后编辑；完整字段手册、
每个字段的类型/默认值/范围/Provider 适用性与副作用、Provider 配方和内部固定值都在该文件中。
配置扩展的设计决策与实施说明见 [PDF2ZH 配置能力扩展设计](docs/completed%20improvements/pdf2zh-configuration-expansion-design-830.md)。
该设计文档已随收口移入 `docs/completed improvements/`（原路径 `docs/pdf2zh-configuration-expansion-design.md` 不再使用）。

> **普通用户提示：只改你确定的字段。** 高级参数不了解就保持注释或删除，全部都有可直接使用的
> 默认值；不要猜阈值或并发值。48 键的完整类型、默认值与副作用手册仍在
> [config.example.toml](config.example.toml)。

### DeepSeek 最小 config.toml

最简可用配置如下（`api_key` 是占位符，必须换成真实值，或用 `MODEL_API_KEY` 环境变量提供）：

```toml
[model]
provider = "deepseek"
api_key = "sk-your-api-key-here"
model = "deepseek-chat"

[translation]
lang_in = "en"
lang_out = "zh"
qps = 4
```

启动时会拒绝 `sk-your-api-key-here` 这类示例占位符：换成真实值，或删除该行后设置
`$env:MODEL_API_KEY = '你的真实密钥'`（环境变量优先于文件）。其他高级字段全部省略即可运行。

### 普通用户并发速查

| 用法 | `qps` | `pool_max_workers` | 说明 |
|---|---|---|---|
| 稳定 | `1` | `1` | 最保守，适合低配额/免费账号或经常遇到 429 |
| 默认 | `4` | 省略（跟随 `qps`） | 项目内置默认，普通用户推荐起点 |
| 高速试用 | `8` | `8` | 仅当 API 配额允许时；一出现 429/超时马上降回 4 或 1 |

`qps` 是“每秒最多启动多少个模型 API 请求”，不是页/秒，也不是完成数保证；1/4/8 的每分钟
理论上限约为 60/240/480 个新请求，实际吞吐受响应延迟、worker 数、供应商 RPM/TPM、网络和
文本块数量限制。调大不一定线性变快，但额度与费用消耗会更快。普通用户不建议超过 8。

### 常见故障调参

| 现象 | 调整 | 说明 |
|---|---|---|
| 429 / 限流 | 降 `qps`，同时降 `pool_max_workers`（8→4→1 逐级降） | 不要继续调大；等配额恢复再试 |
| 超时频繁 | 先降 `qps`/`pool_max_workers`，或增大 `model.timeout` | `timeout` 仅 `aliyun`/`openai`/`openai_compatible` 支持，其它 provider 设置会被忽略 |
| 速度慢但无 429 | 逐级 1→4→8 | 每级观察是否出现限流或超时 |
| 费用增长过快 | 降 `qps`，或把 `[term_extraction].enabled` 设为 `false` | 正文固定关闭上游自动术语提取；候选提取默认开启但独立于正文，可随时关闭 |

### 其它常用参数怎么选

| 参数 | 默认 | 怎么选 |
|---|---|---|
| `translation.min_text_length` | `5` | 短标题/图注被漏翻可尝试 `2`；噪声碎片太多可尝试 `10`；一次只小幅调整 |
| `translation.auto_extract_glossary` | `true` | 1.x 兼容别名：正文恒走严格路径；只在未配置 `[term_extraction]` 段时作为候选提取 `enabled` 的来源；启动 WARNING，计划 2.0.0 移除 |
| `translation.term_qps` / `translation.term_pool_max_workers` | 省略 | 1.x 兼容别名（旧上游术语提取调优）：严格路径与项目候选提取均不使用；启动 WARNING，计划 2.0.0 移除，请改用 `term_extraction.qps` / `term_extraction.max_workers` |
| `term_extraction.enabled` | `true` | 候选旁路提取总开关；只写候选存储，未确认前不影响正文；失败也不影响正文 |
| `term_extraction.timeout` | `30` | 候选请求超时；失败只降级日志，正文仍 finish |
| `term_extraction.retry_count` | `1` | 只对超时/429/5xx 重试；4xx 与格式错误不重试 |
| `translation.primary_font_family` | `auto` | 只有字体视觉明显不合适才改 `serif`/`sans-serif`/`script` |
| `translation.default_system_prompt` | 省略 | 只有希望每次任务固定附加翻译指令时才设置；页面非空 Prompt 仍优先 |
| `model.timeout` | provider 默认 | 仅 `aliyun`/`openai`/`openai_compatible` 生效；调大只允许更久等待，不会让模型变快；其它 provider 设置被忽略 |
| `model` 的 temperature / reasoning / 发送开关 | 省略 | 普通翻译不了解就全部省略；不要为了“更快”打开 reasoning |
| `[pdf2zh]` 整段 | 省略 | 普通用户默认整段省略；遇到明确的排版/OCR/公式问题时一次只改一个字段，重启后先重译单页对比；已译的其它页不会失效 |

更完整的字段类型/默认值/范围/副作用见 [config.example.toml](config.example.toml)；不要在
README 里背 48 个键。

当前支持 48 个键：`[pdf_reader]`（2）、`[model]`（11）、`[translation]`（10）、
`[server]`（3）、`[term_extraction]`（7）、`[pdf2zh]`（15）。其中
`translation.auto_extract_glossary`、`translation.term_qps`、
`translation.term_pool_max_workers` 是 1.x 兼容别名：仍可读取并做类型/范围
校验，启动时输出不含敏感值的 WARNING 迁移提示，配置中心不再展示/写入，
计划 2.0.0 移除；规范候选调优字段全部在 `[term_extraction]`。启动时会严格校验类型、范围、组合与正则：
未知 section/key、未知 provider、非法数值（含 nan/inf）、`openai_compatible` 缺少
`base_url` 都会在启动阶段直接报错，不再静默忽略或兜底。

编辑 `[model]`，或者通过环境变量提供 API Key：

```powershell
$env:MODEL_API_KEY = 'your-api-key'
```

行为边界：

- 配置变化只影响之后执行的翻译或主动重译，不会追溯更新已写入文档缓存的旧 `right.pdf` 页面。
- 前端文档缓存仍只按原 PDF 哈希保存；旧累计术语表作为历史输入继续跨模型/配置复用。
- 每次翻译固定跳过上游请求缓存（`ignore_cache=true`），但不会影响本前端按 PDF 哈希复用的译文页面。
- 页面 Prompt 优先级：非空页面 Prompt > `translation.default_system_prompt` > 上游默认提示词。
- 正文翻译固定关闭上游自动术语提取（`no_auto_extract_glossary=true`、
  `save_auto_extracted_glossary=false`），`translation.auto_extract_glossary`
  不再改变正文行为，仅作为未配置 `[term_extraction]` 段时 `enabled` 的兼容
  默认来源；它与 `term_qps`/`term_pool_max_workers` 一起处于 1.x 兼容期
  （启动 WARNING、配置中心不展示/写入、计划 2.0.0 移除）。
- 候选提取是独立的旁路服务：正文最终验证并提交成功后才运行，只把模型建议
  原子写入 `term_candidates.json`（含 1-based 页码与策略版本，P1-02 前证据
  为空、页码为粗粒度页范围）；未经用户接受绝不进入 `effective_glossary.csv`
  或正文 `SettingsModel`。候选提取失败（网络/解析/存储/Provider 不支持）
  只降级为安全日志，不阻止正文 `finish`；正文失败或术语合规失败不会触发
  候选提取。支持 `deepseek`/`openai`/`openai_compatible`，其余 Provider
  稳定降级为 unsupported。
- 每次单页/批量翻译前先对当前文档执行旧累计术语幂等迁移（只合入候选）、编译并
  严格验证 `effective_glossary.csv`；正文 `glossaries` 只指向该有效词表。当前页/
  批次实际命中的权威词条会追加为不可被页面 Prompt 覆盖的强制约束块。
- 术语合规提交门（P0-05）：`replace_page`/`replace_pages` 之前会从候选译文 PDF
  提取文本并精确检查当前页/批次活跃权威术语的 target 是否出现；首次不合规最多
  用同一任务重试 1 次，重试通过才提交。重试仍不合规返回
  `glossary_compliance_failed`，无法可靠提取/缺页/空文本返回
  `glossary_verification_unavailable`，两者都不写入 `right.pdf` 也不合并自动
  词表。源 PDF 打不开/抽取异常/文本为空且存在有效权威词条时同样在调用上游前
  返回 `glossary_verification_unavailable`，不调用上游、不提交；仅当权威词条为
  空或源文本成功且无命中时才视为无活跃术语，完全跳过验证与重试。模型仍可能
  偶发漏译或变体，本项目不宣称模型输出绝对可靠，验证是尽力而为的第二道门。

API Key 不应提交到 Git。

## 路径约定

项目资源位置与运行数据位置由 `src/pdf_reader/paths.py` 统一解析，与启动时的当前工作目录（CWD）无关：

| 路径 | 基准 | 说明 |
|---|---|---|
| `config.toml` | `PROJECT_ROOT` | 用户配置；缺失时安全回退为空配置 |
| `docs/glossary.csv` | `PROJECT_ROOT` | 仓库级手动术语表 |
| `templates/`、`static/` | `PROJECT_ROOT` | Flask 显式使用统一资源根 |
| `logs/` | `DATA_ROOT` | 轮转应用日志 |
| 相对 `cache_dir` | `DATA_ROOT` | 相对配置值按 `DATA_ROOT` 解析 |
| 绝对 `cache_dir` | 原样 | 不被重写 |

- `PROJECT_ROOT`（项目资源根）＝仓库根。`paths.py` 位于 `src/pdf_reader/`，从自身位置向上查找 `config.example.toml` 标记自动回到仓库根，无需改数据位置。环境变量 `PDF_READER_ROOT` 可显式覆盖。
- `DATA_ROOT`（运行数据根）默认等于 `PROJECT_ROOT`：日志仍在仓库 `logs/`，相对缓存仍在仓库根下。环境变量 `PDF_READER_DATA_ROOT` 可覆盖（测试隔离等场景）。
- 安装本包后，从任意 CWD 运行 `python -m pdf_reader`（或 `start.bat`，其自身仍会切换到仓库根），配置、手动术语表、模板、静态文件、日志和缓存位置一致。

## 术语管理与备份恢复

阅读页工具栏中的“术语”按钮打开当前文档的术语面板，用于管理权威术语和候选术语：

- 权威术语：新建、编辑、锁定/解锁、删除；锁定术语只有解锁后才能修改或删除。
- 候选术语：查看出现页码、有界证据与观察次数；接受（接受前可修改 target）或
  拒绝；拒绝的候选不会反复提示，但不冻结后台统计。
- 候选不会自动影响正文：只有权威术语（含接受后的候选）经确定性编译进入
  `effective_glossary.csv`，每次正文翻译前会重新编译并验证；严格正文约束始终
  开启，配置里没有关闭它的开关。
- CSV 导入/导出：面板支持把当前文档权威术语导出为
  `source,target,locked,note` 格式（UTF-8 带 BOM），也支持导入同格式（可只含
  `source,target`）。这是备份与迁移用户决定的推荐方式：它直接读写权威存储，
  写后自动重新编译有效词表，且不会触碰其他文档或全局词表。

备份与恢复由用户决定，应用不会自动删除这些文件。推荐在停止服务后整文件复制：

| 文件 | 说明 |
|---|---|
| `docs/glossary.csv` | 全局手工权威术语 |
| `cache/<hash>/user_glossary.csv` | 每个文档的用户权威术语 |
| `cache/<hash>/term_candidates.json` | 每个文档的候选/拒绝/接受状态与观察统计 |

- `cache/<hash>/` 的 `<hash>` 是源 PDF 的 SHA-256（小写十六进制）；恢复时必须
  放回与原 PDF 对应的同一目录并保持文件名不变，否则新打开的会话不会把它识别为
  该文档的术语数据。
- 这些文件由应用按原子文件边界写入（同目录临时文件 + `os.replace` 整文件替换）。
  备份/恢复请停止服务后用整文件复制或整文件替换，不要并发写入，也不要复制写了一半
  的 `.tmp` 文件；恢复前建议把当前文件移到一旁而不是直接覆盖，以便出错时回滚。
- `effective_glossary.csv` 是可重建产物：由 `docs/glossary.csv`、
  `cache/<hash>/user_glossary.csv` 与已接受候选确定性编译，每次翻译前自动重建，
  不需要备份或恢复它。
- `cumulative_glossary.csv` 是历史输入而非权威：兼容期内保留原文件，并只读、
  幂等地迁移为未审核候选；迁移会生成 `cumulative_glossary.csv.bak` 恢复副本
  （已有副本绝不覆盖）。不要手工把它合并进 `user_glossary.csv` 或
  `effective_glossary.csv`——如需保留旧译法，请在面板中接受对应候选或重新新建。

## 缓存与临时工作区

`DATA_ROOT/cache/<pdf-hash>/` 是**持久用户缓存**，属于用户数据，任何生命周期或清理逻辑都不会自动删除：

| 文件 | 说明 |
|---|---|
| `right.pdf` | 该文档的译文工作副本（首次打开时复制源文件，翻译后原子替换） |
| `cumulative_glossary.csv` | 旧累计术语表（历史输入，非权威）：兼容期内保留，幂等迁移为未审核候选并生成 `cumulative_glossary.csv.bak`；不进入权威或有效词表 |
| `term_candidates.json` | 自动候选/拒绝/接受状态存储（候选不会直接进入正文） |
| `user_glossary.csv` | 该文档的用户权威术语（用户确认后才约束正文） |
| `effective_glossary.csv` | 每次正文翻译前编译并验证的只读有效词表（可重建产物，不要手工编辑或当作备份源） |
| `reading_progress.json` | 阅读进度 |
| `debug_trace.log` | 仅详细诊断日志模式产生：按文档保存的有界轮转调试轨迹（2MB × 3 备份，按 job 过滤） |

翻译任务运行时会在 `cache/` 直接子目录创建一个**任务根工作区** `pdf-reader-translation-*`，内部固定含 `input/`（抽取输入 PDF）与 `output/`（上游译文输出）两个子目录，根工作区内含 `.pdf-reader-temp-workspace` 标记（`kind`/`job_id`/`pid`/`created_at`）。整个根工作区只在后台 worker 确认退出后一次性删除；join timeout、进程崩溃或强制退出留下的工作区会**整体保留**（input/output/标记都在），供下次启动识别并安全处理。标记写入或创建中途失败时，只清理本次新建的空目录，不触碰其他缓存内容。

只读统计与手动清理入口（`python scripts/cache_manage.py`）：

```powershell
python scripts/cache_manage.py stats              # 只读统计：文档缓存组成 + 临时工作区数量/大小
python scripts/cache_manage.py stats --json      # 机器可读输出
python scripts/cache_manage.py orphans           # 列出可识别的临时工作区及其标记/PID/年龄
python scripts/cache_manage.py clean             # dry-run：只预览，不删除
python scripts/cache_manage.py clean --yes       # 真正删除
```

`clean` 的删除边界严格限定为：`cache_dir` 直接子目录 + 名称带固定前缀 + 含有效标记（`kind` 匹配且 `pid` 为正整数）+ 非符号链接/junction + PID 已不存活。Windows 上 PID 探测使用只读 `OpenProcess` + `GetExitCodeProcess`（不使用会终止进程的 `os.kill(pid, 0)`）：只有明确不存在（如 `ERROR_INVALID_PARAMETER`）才判定为不存活，拒绝访问或查询失败一律按“可能存活”保留。未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保留；`right.pdf`、术语表、阅读进度和任何文档缓存目录永远不会作为清理目标。`--cache-dir PATH` 可覆盖默认缓存根（默认取配置解析后的 `cache_dir`）。

启动时 `main` 会执行崩溃恢复：只清理上述可验证归属且 PID 已不存活的临时工作区，其余保守保留并记录日志。正常关闭时，`main` 先对 active job 做有界等待（默认 10 秒，协作式取消、不强制 kill），按“完成/超时/保留”记录日志，再调用 `AppState.close()` 幂等关闭并释放左右 PyMuPDF 文档句柄。

## 错误契约与安全

- 所有 API 4xx/5xx 错误统一返回 JSON：`{"code": <稳定错误码>, "error": <安全消息>}`。`409` 保留既有 `translation_busy` 与 `active_job_id`；`404` 使用 `not_found`；`500` 使用固定 `internal_error` 与通用安全摘要。
- 服务端日志保留完整异常与 traceback；客户端永远不会收到异常类名、内部文件路径、API Key、提示词或上游原始响应。
- SSE 错误事件统一为 `{"type": "error", "code": <稳定错误码>, "error": <安全消息>}`；上游 `error` 事件、`TranslationError`、普通异常与“无翻译结果”均只发送安全摘要。
- 前端错误文本一律经 DOM 节点 `textContent` 呈现，不拼接未转义 HTML。
- 前端翻译请求使用 `AbortController` 终止浏览器 fetch/SSE 消费；浏览器 abort 不是服务端取消确认，服务端任务生命周期仍由 SSE 断开与后端机制决定。
- 前端 `window` 的 `error` 与 `unhandledrejection` 会经 `static/modules/client-error.js` 采集并上报 `/api/client-errors`：仅接受本机来源，白名单字段 `kind/message/source/line/column/stack`，正文上限 8KB，不记录请求 headers、cookies 或 prompt。
- 服务默认绑定 `127.0.0.1`。若配置为 `localhost`/`127.0.0.0/8`/`::1` 之外的地址，启动日志会输出醒目的安全 WARNING（服务无认证，可能暴露本地 PDF 与 API 配置），但不会阻止启动。

## 日志位置与排障

程序常驻写入 `logs/pdf_reader.log`（位于 `PDF_READER_DATA_ROOT`，默认仓库根下），单文件 128 KiB
（128×1024 字节）、保留 5 份轮转备份（常规上限约 768 KiB）；超过 14 天的轮转备份会在启动与轮转时
自动清理，不需要手动清理。每行包含 ISO 时间、级别、`run_id`、pid、thread、logger，翻译任务行
还带 `[job=... doc=... hash=... page=... status=...]` 前缀；`werkzeug`、`pdf2zh_next`、`babeldoc`
的第三方日志与项目日志写入同一文件、走同一脱敏。

遇到翻译失败或界面异常时按下面顺序排查：

1. 打开 `logs/pdf_reader.log`，先搜 `ERROR` 或 `Traceback` 定位失败发生点；
2. 页面/接口返回里出现 `job_id` 时，在日志中搜 `job=<该 id>`，即可看到该任务的完整生命周期；
3. 需要更多细节时，短期用 `python -m pdf_reader --debug` 重启（额外生成按文档保存的
   `cache/<hash>/debug_trace.log`，2MB × 3 轮转），复现问题后关掉 debug 恢复正常运行；
4. 日志中 API Key、Bearer token、`api_key` 字段与 prompt 内容都会被打码，看到 `<redacted>` 是正常行为。

debug 只控制日志详细程度，不会启用 Flask debugger 或 reloader。

## 任务日志上下文

- 任务日志由 `src/pdf_reader/task_logging.py` 集中输出，稳定前缀：`[job=<完整 job_id> doc=<8 字符> hash=<12 字符> page=N|pages=A-B status=<状态>]`；页码一律 1-based，`document_id` 截断 8 字符、pdf hash 截断 12 字符。
- 生命周期状态：`created`、`started`、`client_disconnected`、`cancelling`、`finished`、`failed`、`discarded`、`cleaned`；join timeout 记录 `cleanup_deferred`，不会误报 `cleaned`。coordinator 释放语义保留 `cancelled`。
- 上下文经 `contextvars` 贯穿协调器、路由、SSE 生成器、后台 worker 线程、翻译生命周期与 AppState 写回/恢复；worker 线程显式传播，不依赖请求线程字段。
- 日志脱敏在格式化边界完成：控制台、`logs/pdf_reader.log` 与 `debug_trace.log` 会替换配置中的 API Key、`sk-...`、`Authorization/Bearer`、`api_key` 字段以及 `custom_system_prompt`/`system_prompt`/`user_prompt`/`prompt` 类字段值；`werkzeug`/`pdf2zh_next`/`babeldoc` 的第三方日志与项目日志共用同一对 handler 和同一个 `SafeFormatter`，因此同样脱敏。traceback 结构保留，路径/HTML 仅作为服务端诊断内容保留。

### debug 优先级与安全默认值

| 来源 | 示例 | 优先级 |
|---|---|---|
| CLI 参数 | `python -m pdf_reader --debug` / `--no-debug` | 1（最高） |
| 环境变量 | `$env:PDF_READER_DEBUG = "true"` | 2 |
| config.toml | `[server] debug = true` | 3 |
| 默认值 | — | 4（`false`） |

- `--debug` 与 `--no-debug` 互斥，同时传入会立即报错并以非零状态退出。
- `PDF_READER_DEBUG` 只接受 `true` / `false` / `1` / `0` / `on` / `off` / `yes` / `no`（不区分大小写、忽略首尾空白）；空值或其它值在启动时报错并退出。
- `debug` 只表示“详细诊断日志模式”：`debug = true` 开启日志 DEBUG 级别与 `debug_trace` 会话记录；Flask debugger 与 reloader 无论 debug 值如何都保持关闭（`app.run(debug=False, use_reloader=False)`），不会暴露交互式调试器或自动重载进程。它是有用的详细诊断开关，不是“没用的调试模式”。
- debug 开启时，每次翻译任务会在文档缓存目录写入/追加 `cache/<hash>/debug_trace.log`（2MB × 3 备份，按 `job_id` 过滤）；关闭时不产生该文件。
- `MODEL_API_KEY` 环境变量仍优先于 `config.toml` 的 `model.api_key`。

### 启动配置校验

启动服务器前会严格校验 `config.toml`：

- `[server]` 必须是 table；`host` 必须是非空字符串；`port` 必须是 1–65535 的整数（布尔值不算整数）；`debug` 必须是布尔值 `true` / `false`。
- `[model]`、`[pdf_reader]`、`[translation]` 若存在必须是 table；`model.provider`、`model.model`、`model.api_key`、`model.base_url`（若有）必须是非空字符串（数字/布尔/列表均拒绝）；`pdf_reader.dpi` 必须是正整数（布尔值不算）、`cache_dir` 必须是非空字符串；`translation.lang_in` / `lang_out` 必须是非空字符串。
- 导入 `config` / `app` 不因这些错误类型崩溃（非 table section 与错误类型在导入期使用安全默认值），错误统一由启动入口在启动服务器前以 `ERROR: ...` 和非零状态报出。
- `MODEL_API_KEY` 环境变量仍优先于文件；环境值为合法非空字符串（且非示例占位值）时可以覆盖文件中无效的 `api_key`，但 `[model]` 段本身仍必须是 table。
- `config.toml` 缺失时按空配置安全加载，但缺少 `model.model` 或 `model.api_key`（且未设置 `MODEL_API_KEY`）会在启动服务器前报错退出。
- TOML 语法错误、字段类型错误、非法端口、非法 debug 值都会在启动时输出 `ERROR: ...` 并以非零状态退出；错误信息不包含 API Key。

错误示例：

```powershell
$env:PDF_READER_DEBUG = "banana"
python -m pdf_reader
# ERROR: 环境变量 PDF_READER_DEBUG 非法值 'banana'：只接受 true/false/1/0/on/off/yes/no（不区分大小写，忽略首尾空白）
# 退出码 2，服务器不会启动

python -m pdf_reader --debug --no-debug
# usage: python -m pdf_reader [-h] [--debug | --no-debug]
# python -m pdf_reader: error: argument --no-debug: not allowed with argument --debug
# 退出码 2
```

## 启动

推荐直接运行根目录的 `start.bat`（在 PowerShell 或 cmd 中执行）：

```powershell
.\start.bat
```

脚本会切换到仓库根目录、检查并激活 `.\venv`，然后运行 `python -m pdf_reader`。如果端口 5000 已被占用，`start.bat` 会打印占用进程的 PID 与排查命令，并以非零状态退出；它不会自动终止任何进程。

也可以手动启动：

```powershell
.\venv\Scripts\Activate.ps1
python -m pdf_reader
```

然后打开 `http://127.0.0.1:5000`，输入本地 PDF 的绝对路径。

### 端口 5000 被占用时的安全处理

`start.bat` 默认只报告、不杀进程。先确认占用者是谁：

```powershell
netstat -ano -p tcp | findstr ":5000 "
tasklist /FI "PID eq <pid>"
```

确认 `<pid>` 对应的是你正在运行的本项目实例或其他可以安全关闭的程序后，再自行处理（例如正常关闭对应程序，或在你确认它没有未保存数据时使用 `taskkill /PID <pid>`）。不要对未确认归属的进程使用 `taskkill /F`。

如果不想结束现有程序，也可以改用其他端口：编辑 `config.toml` 的 `[server]` 段（例如 `port = 5001`）后直接运行：

```powershell
.\venv\Scripts\python.exe -m pdf_reader
```

然后访问 `http://127.0.0.1:5001`。

详细诊断日志模式（优先级高于环境变量与 `config.toml`；只影响日志，不会启用 Flask debugger/reloader）：

```powershell
python -m pdf_reader --debug
python -m pdf_reader --no-debug
```

## 验证

运行前端测试或完整验证前，需要先安装 Node.js 测试依赖（普通运行不需要）：

```powershell
npm ci
```

运行全部受支持的检查：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

`scripts/verify.ps1` 会先输出最终选用的 Python 绝对路径与版本，并核验 Python `>=3.12` 与
Node.js `>=22`（版本不满足时快速失败并给出提示）：显式 `-PythonExecutable` 优先；未指定时
优先仓库 `venv`；仓库 `venv` 缺失而回退 PATH 中的 `python` 时会输出醒目 WARNING（不会静默）。
显式路径无效时快速失败、不回退。

统一验证依次执行：密钥扫描（`scripts/secret_scan.py`，只扫描 Git 跟踪内容且不输出 secret 值）→ 上游升级治理门静态检查（`python scripts/upgrade_governance_gate.py --static-only`，见下）→ Ruff lint/format → coverage（`coverage run --branch -m pytest`，含全局与关键模块阈值策略）→ mypy（仅 `src/pdf_reader`）→ JS lint（`npm run lint:js`，ESLint flat config）→ 前端测试（`npm test`）。本地 coverage 数据写入临时目录并在结束后清理；CI 通过 `PDF_READER_COVERAGE_ARTIFACT_DIR=coverage-artifacts` 输出 coverage JSON/XML 并上传 artifact（该目录已加入 .gitignore）。

升级 pdf2zh-next/BabelDOC 前，先运行上游契约测试（离线、确定性，不联网、不调用真实翻译、不需要 API Key）：

```powershell
python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py
```

推荐直接运行一键“上游升级术语治理门”（P2-04）：它在静态治理检查后自动运行上述契约
测试，以及严格正文路径、候选隔离和合规提交门回归：

```powershell
python scripts/upgrade_governance_gate.py
```

治理门拒绝未锁定/VCS/editable/path 等依赖来源，扫描任意位置的
`pdf2zh_next`/`babeldoc` 影子包、fork/vendor 目录变体、上游源码副本和生产
Monkey-patch；不联网、不修改任何文件，范围与命令见
[依赖升级流程](docs/governance/dependency-upgrade.md)。

安装后的关键 Python 依赖可用以下命令快速检查：

```powershell
python -c "import flask, pymupdf, pdf2zh_next, pdf_reader"
```

单独运行前端回归测试：

```powershell
npm test
```

单独运行 JS 静态检查：

```powershell
npm run lint:js
```

正式测试与历史诊断脚本的区别见 [测试说明](tests/README.md)。

## 核心结构

```text
src/pdf_reader/                 可安装包（python -m pdf_reader 入口）
src/pdf_reader/app.py           Flask 应用入口
src/pdf_reader/routes.py        HTTP 与 SSE 路由
src/pdf_reader/state.py         当前文档、缓存和阅读状态
src/pdf_reader/logging_config.py 统一日志管线（主日志轮转、第三方托管、脱敏）
src/pdf_reader/debug_trace.py   按任务的有界 debug_trace.log 会话捕获
src/pdf_reader/translation_orchestrator.py  翻译线程与事件桥接
src/pdf_reader/sse_stream.py    翻译进度事件
src/pdf_reader/translation_lifecycle.py     译文持久化与资源清理
src/pdf_reader/translation_settings.py      pdf2zh-next 参数组装
pyproject.toml                  可安装包元数据
static/app.js                  阅读器前端入口
static/modules/client-error.js 前端全局错误上报（window error/unhandledrejection）
static/modules/translation-ui-controller.js  翻译 UI 状态机（busy/progress/stage/error/abort/reset）
static/modules/reader-session.js             文档级资源 session/dispose 边界
static/modules/                对齐、懒加载、缩放、SSE、翻译与状态机模块
tests/                         Python 与前端测试
```

详细模块职责、调用链和运行时状态见 [当前架构](docs/architecture.md)。

## 许可证与再分发

本项目源代码以 **AGPL-3.0-only** 授权，根目录 [LICENSE](LICENSE) 为标准完整 GNU AGPL v3 官方文本；`pyproject.toml`、`package.json`、`package-lock.json` 与 README 的许可证声明一致。

PDF 版面翻译依赖 `pdf2zh-next`（2.9.0）与底层 BabelDOC（0.6.2），其官方元数据与发行物均标注 **AGPL-3.0**。重新分发本项目、与上游组合分发或网络部署前，请按实际组合方式核对许可证与源码提供义务；不要假定“只要 Python 依赖就自动必然构成衍生作品”，也不要移除上游 LICENSE 与版权声明。

许可证与再分发核验基线、本地内部使用、源代码再分发、与上游组合再分发或网络部署四种场景见 [许可证与再分发治理](docs/governance/license.md)。本说明不构成法律意见。
