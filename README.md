# 双语 PDF 阅读器

这是一个用于阅读英文教材和论文的本地双语 PDF 阅读器。左栏显示原文，右栏显示译文，支持在阅读过程中按页、按范围或全文调用大模型翻译。

PDF 版面翻译由 [PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) / `pdf2zh-next` 提供。本项目主要负责本地阅读界面、按需翻译编排、双栏对齐、缓存和阅读状态。

## 当前功能

- 双栏连续滚动和双向页面对齐。
- 当前页、页码范围和全文翻译。
- SSE 翻译阶段与进度显示。
- 自定义翻译提示词。
- 按 PDF 隔离的累积术语表。
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
- [工程与架构长期改进清单](docs/engineering-improvement-plan-829.md)：按优先级跟踪可靠性、任务生命周期、目录结构和工程卫生改进。
- [pdf2zh-next 开发参考](docs/pdf2zh-next-development-guide.md)：涉及上游接口、事件和配置时按版本范围阅读。
- [工具与工作流目录治理](docs/governance/tool-directories.md)：`.agents/`、`.codex/`、`.comet/`、`.opencode/`、`openspec/` 等目录的职责、跟踪与重建边界。
- [依赖升级流程](docs/governance/dependency-upgrade.md)：Python/Node 支持范围与上游翻译依赖升级契约。

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

编辑 `config.toml` 中的 `[model]`，或者通过环境变量提供 API Key：

```powershell
$env:MODEL_API_KEY = 'your-api-key'
```

完整配置字段和模型示例见 `config.example.toml`。API Key 不应提交到 Git。

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

## 缓存与临时工作区

`DATA_ROOT/cache/<pdf-hash>/` 是**持久用户缓存**，属于用户数据，任何生命周期或清理逻辑都不会自动删除：

| 文件 | 说明 |
|---|---|
| `right.pdf` | 该文档的译文工作副本（首次打开时复制源文件，翻译后原子替换） |
| `cumulative_glossary.csv` | 该文档的累计术语表 |
| `reading_progress.json` | 阅读进度 |
| `debug_trace.log` | 仅 debug 模式产生 |

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
- 服务默认绑定 `127.0.0.1`。若配置为 `localhost`/`127.0.0.0/8`/`::1` 之外的地址，启动日志会输出醒目的安全 WARNING（服务无认证，可能暴露本地 PDF 与 API 配置），但不会阻止启动。

## 任务日志上下文

- 任务日志由 `src/pdf_reader/task_logging.py` 集中输出，稳定前缀：`[job=<完整 job_id> doc=<8 字符> hash=<12 字符> page=N|pages=A-B status=<状态>]`；页码一律 1-based，`document_id` 截断 8 字符、pdf hash 截断 12 字符。
- 生命周期状态：`created`、`started`、`client_disconnected`、`cancelling`、`finished`、`failed`、`discarded`、`cleaned`；join timeout 记录 `cleanup_deferred`，不会误报 `cleaned`。coordinator 释放语义保留 `cancelled`。
- 上下文经 `contextvars` 贯穿协调器、路由、SSE 生成器、后台 worker 线程、翻译生命周期与 AppState 写回/恢复；worker 线程显式传播，不依赖请求线程字段。
- 日志脱敏在格式化边界完成：控制台与 `logs/pdf_reader.log` 会替换 `sk-...`、`Authorization/Bearer`、`api_key` 字段及配置中的 API Key；traceback 结构保留，路径/HTML 仅作为服务端诊断内容保留；用户 prompt 不写入任何日志。

### debug 优先级与安全默认值

| 来源 | 示例 | 优先级 |
|---|---|---|
| CLI 参数 | `python -m pdf_reader --debug` / `--no-debug` | 1（最高） |
| 环境变量 | `$env:PDF_READER_DEBUG = "true"` | 2 |
| config.toml | `[server] debug = true` | 3 |
| 默认值 | — | 4（`false`） |

- `--debug` 与 `--no-debug` 互斥，同时传入会立即报错并以非零状态退出。
- `PDF_READER_DEBUG` 只接受 `true` / `false` / `1` / `0` / `on` / `off` / `yes` / `no`（不区分大小写、忽略首尾空白）；空值或其它值在启动时报错并退出。
- 解析出的同一个 debug 布尔值同时用于应用日志与 Flask 服务：`debug = true` 时启用 Flask debugger 与 reloader；`debug = false`（默认）时两者都显式关闭，不依赖 Flask 隐式默认。
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

调试模式（优先级高于环境变量与 `config.toml`）：

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

统一验证依次执行：密钥扫描（`scripts/secret_scan.py`，只扫描 Git 跟踪内容且不输出 secret 值）→ Ruff lint/format → coverage（`coverage run --branch -m pytest`，含全局与关键模块阈值策略）→ mypy（仅 `src/pdf_reader`）→ JS lint（`npm run lint:js`，ESLint flat config）→ 前端测试（`npm test`）。本地 coverage 数据写入临时目录并在结束后清理；CI 通过 `PDF_READER_COVERAGE_ARTIFACT_DIR=coverage-artifacts` 输出 coverage JSON/XML 并上传 artifact（该目录已加入 .gitignore）。

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
src/pdf_reader/translation_orchestrator.py  翻译线程与事件桥接
src/pdf_reader/sse_stream.py    翻译进度事件
src/pdf_reader/translation_lifecycle.py     译文持久化与资源清理
src/pdf_reader/translation_settings.py      pdf2zh-next 参数组装
pyproject.toml                  可安装包元数据
static/app.js                  阅读器前端入口
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
