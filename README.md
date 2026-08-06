# 双语 PDF 阅读器

> **项目状态：已冻结。** 当前版本保留为本地单用户工具，不再计划新增功能；仅考虑安全问题、数据损坏或无法启动等严重缺陷。背景、已知限制和恢复建议见 [项目状态](docs/PROJECT_STATUS.md)。

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

更多说明见 [项目状态](docs/PROJECT_STATUS.md)。

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

编辑 `config.toml` 中的 `[model]`，或者通过环境变量提供 API Key：

```powershell
$env:MODEL_API_KEY = 'your-api-key'
```

完整配置字段和模型示例见 `config.example.toml`。API Key 不应提交到 Git。

## 启动

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

然后打开 `http://127.0.0.1:5000`，输入本地 PDF 的绝对路径。

调试模式：

```powershell
python app.py --debug
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

## 授权提醒

本项目依赖采用 AGPL-3.0 的 PDFMathTranslate-next / `pdf2zh-next`。重新分发、在线部署或调整许可证前，请先核对上游许可要求。该提醒不构成法律意见。
