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

## 环境要求

- Windows 10 或更高版本。
- Python 3.12。
- Node.js 22（只在运行前端测试时需要）。
- 可用的 LLM API Key。

## 安装

```powershell
git clone https://github.com/shortFisherman/PDF_reader.git
cd PDF_reader
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.lock
Copy-Item config.example.toml config.toml
```

`requirements.txt` 只声明直接运行依赖，`requirements-dev.txt` 在其基础上声明测试和代码检查依赖；`requirements.lock` 是 README、CI 和本地验证共同使用的唯一锁文件。锁文件由 Python 3.12 和 `pip-tools` 生成：

```powershell
py -3.12 -m venv .tmp-lock-venv
.\.tmp-lock-venv\Scripts\python.exe -m pip install pip-tools==7.6.1
.\.tmp-lock-venv\Scripts\python.exe -m piptools compile --upgrade --resolver=backtracking --strip-extras --output-file requirements.lock requirements-dev.txt
```

生成后应删除临时环境，并在新的 Python 3.12 虚拟环境中执行安装、关键导入和完整验证。不要从日常工作环境运行 `pip freeze` 更新锁文件。

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

### debug 优先级与安全默认值

| 来源 | 示例 | 优先级 |
|---|---|---|
| CLI 参数 | `python app.py --debug` / `--no-debug` | 1（最高） |
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
- `config.toml` 缺失时按空配置安全加载，但缺少 `model.model` 或 `model.api_key`（且未设置 `MODEL_API_KEY`）会在启动服务器前报错退出。
- TOML 语法错误、字段类型错误、非法端口、非法 debug 值都会在启动时输出 `ERROR: ...` 并以非零状态退出；错误信息不包含 API Key。

错误示例：

```powershell
$env:PDF_READER_DEBUG = "banana"
python app.py
# ERROR: 环境变量 PDF_READER_DEBUG 非法值 'banana'：只接受 true/false/1/0/on/off/yes/no（不区分大小写，忽略首尾空白）
# 退出码 2，服务器不会启动

python app.py --debug --no-debug
# app.py: error: argument --no-debug: not allowed with argument --debug
# 退出码 2
```

## 启动

推荐直接运行根目录的 `start.bat`（在 PowerShell 或 cmd 中执行）：

```powershell
.\start.bat
```

脚本会切换到仓库根目录、检查并激活 `.\venv`，然后运行 `python app.py`。如果端口 5000 已被占用，`start.bat` 会打印占用进程的 PID 与排查命令，并以非零状态退出；它不会自动终止任何进程。

也可以手动启动：

```powershell
.\venv\Scripts\Activate.ps1
python app.py
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
.\venv\Scripts\python.exe app.py
```

然后访问 `http://127.0.0.1:5001`。

调试模式（优先级高于环境变量与 `config.toml`）：

```powershell
python app.py --debug
python app.py --no-debug
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

安装后的关键 Python 依赖可用以下命令快速检查：

```powershell
python -c "import flask, pymupdf, pdf2zh_next"
```

单独运行前端回归测试：

```powershell
npm test
```

正式测试与历史诊断脚本的区别见 [测试说明](tests/README.md)。

## 核心结构

```text
app.py                         Flask 应用入口
routes.py                      HTTP 与 SSE 路由
state.py                       当前文档、缓存和阅读状态
translation_orchestrator.py    翻译线程与事件桥接
sse_stream.py                  翻译进度事件
translation_lifecycle.py       译文持久化与资源清理
translation_settings.py        pdf2zh-next 参数组装
static/app.js                  阅读器前端入口
static/modules/                对齐、懒加载、缩放和翻译模块
tests/                         Python 与前端测试
```

详细模块职责、调用链和运行时状态见 [当前架构](docs/architecture.md)。

## 上游依赖与授权提醒

本项目依赖采用 AGPL-3.0 的 PDFMathTranslate-next / `pdf2zh-next`。重新分发、在线部署或调整许可证前，请先核对上游许可要求。该提醒不构成法律意见。
