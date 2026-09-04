# 双语 PDF 阅读器（Bilingual PDF Reader）

[![CI](https://github.com/shortFisherman/PDF_reader/actions/workflows/ci.yml/badge.svg)](https://github.com/shortFisherman/PDF_reader/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/github/license/shortFisherman/PDF_reader)](LICENSE)

本地运行的双栏双语 PDF 阅读器：左侧原文、右侧译文，调用任意大模型 API 翻译英文论文与教材，支持按页、按范围或全文翻译。版面级排版翻译由 [pdf2zh-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) / BabelDOC 提供，本项目负责阅读界面、翻译编排、双栏对齐、术语记忆与缓存。

数据只在你的电脑上处理，服务仅监听本机。

## 目录

- [功能特性](#功能特性)
- [快速开始](#快速开始)
- [使用说明](#使用说明)
- [术语管理](#术语管理)
- [配置](#配置)
- [常见问题](#常见问题)
- [数据与备份](#数据与备份)
- [开发](#开发)
- [许可与致谢](#许可与致谢)

## 功能特性

- 双栏对照阅读：双向页面对齐、同步滚动、大 PDF 懒加载、Ctrl + 滚轮缩放。
- 三种翻译范围：当前页、页码范围、全文；SSE 实时展示阶段与进度。
- 翻译过程中可随时重新翻译或换模型，配置变更只影响之后的翻译。
- 术语记忆：按文档隔离的权威术语表 + 候选术语自动提取（模型只给建议，你确认后才生效）。
- 译文与阅读进度自动持久化：再次打开同一 PDF 直接续读。
- 灵活的自定义提示词（页面级 > 全局默认 > 上游默认）。
- 支持 DeepSeek、OpenAI 兼容接口、GLM、Qwen、Gemini、Groq、xAI 等多家服务。
- 密钥与提示词日志脱敏，服务默认只绑定 `127.0.0.1`。

## 快速开始

### 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10 或更高版本 |
| Python | **3.12**（依赖锁文件按其编译，其他版本可能装不上） |
| LLM API Key | DeepSeek / OpenAI 兼容 / Gemini 等任意一家（翻译必须，费用由你的 API 账户承担） |
| Node.js（可选） | Node.js 22 或更新（`package.json` 锁定 `>=22`；只在跑前端测试时需要） |

### 安装（一次性）

打开 PowerShell，执行：

```powershell
git clone https://github.com/shortFisherman/PDF_reader.git
cd PDF_reader

# 1. 创建虚拟环境并安装依赖（首次约几百 MB，视网络可能需要 5-15 分钟）
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.lock
pip install -e . --no-deps

# 2. 生成配置文件并填入你的 API Key
Copy-Item config.example.toml config.toml
notepad config.toml
```

在 `config.toml` 中找到 `[model]` 段，把 `api_key` 换成真实密钥：

```toml
[model]
provider = "deepseek"
api_key = "sk-你的真实密钥"
model = "deepseek-chat"
```

> 更省事的方式：不填 `api_key`（整行删除），改用环境变量 `MODEL_API_KEY`（环境变量优先于文件）。
> 占位值 `sk-your-api-key-here` 会被启动校验直接拒绝，请务必替换。

### 启动

双击根目录的 `start.bat`，或手动运行：

```powershell
.\venv\Scripts\python.exe -m pdf_reader
```

浏览器打开 http://127.0.0.1:5000 即可使用。

之后日常使用只需双击 `start.bat`。脚本会自动检查端口占用并激活环境；本机 Python 没有装 3.12 时，有两种选择：安装 [Python 3.12](https://www.python.org/downloads/) 后重来，或者用 `py -3.12` 创建虚拟环境。

## 使用说明

1. 在输入框中填写本地 PDF 的**绝对路径**并打开（支持任何页面布局，翻译前会自动做版面分析）。
2. （可选）在「术语」面板先固定关键术语，例如 `Agent → 智能体`，能明显提升译文一致性。
3. 选择翻译范围：当前页 / 页码范围 / 全文，点击翻译。
4. 等待进度完成，右栏即出现对照译文；译文与阅读位置会自动保存，下次打开接着读。
5. 翻译效果不满意？调整配置后对相应页面「重新翻译」即可。

> 首次翻译某篇文档时需要联网下载版面分析模型等资源（约几十 MB，从 GitHub / HuggingFace 自动选择可用源），仅下载一次，之后复用缓存。

## 术语管理

术语系统把“模型建议”和“你的决定”分开：模型负责发现候选，你确认后的译法才是权威术语，才真正约束翻译。

- **权威术语**：在「术语」面板中「新建术语」手工添加（如 `Agent → 智能体`），重要词条可「锁定」，防止误改误删。
- **候选术语**：翻译时自动提取；打开「候选术语」查看建议与证据，逐条「接受」或「拒绝」。未接受的候选不会影响正文。
- **导入 / 导出**：面板支持把术语导出为 `source,target,locked,note` 格式 CSV，也支持导入（含只有 `source,target` 的文件），用于跨文档迁移和备份。

术语文件按文档隔离，备份时在停止服务后整文件复制：

| 文件 | 说明 |
|---|---|
| `docs/glossary.csv` | 全局默认词表，对所有文档生效 |
| `cache/<pdf-hash>/user_glossary.csv` | 该文档的权威术语（你确认过的译法） |
| `cache/<pdf-hash>/term_candidates.json` | 候选 / 拒绝 / 接受状态与观察统计 |
| `cache/<pdf-hash>/cumulative_glossary.csv` | 历史输入而非权威；兼容期只读幂等迁移为候选，并生成 `cumulative_glossary.csv.bak` |
| `cache/<pdf-hash>/effective_glossary.csv` | 翻译前自动编译的有效词表，是可重建产物，不要手工编辑或备份 |

- `cache/<hash>/` 按源 PDF 的 SHA-256 哈希隔离；恢复时放回原目录并保持文件名不变。
- 术语文件按原子边界写入（同目录临时文件 + 整文件替换）；备份 / 恢复请使用整文件复制或替换，不要并发写入或复制写了一半的 `.tmp` 文件。

完整工作流程与冲突规则见 [术语提取与翻译控制指南](docs/terminology-system.md)。

## 配置

所有配置集中在 `config.toml`（由 `config.example.toml` 复制而来）。普通用户只需关注：

| 字段 | 说明 |
|---|---|
| `model.provider` / `model.model` / `model.api_key` | 模型服务商、模型名、密钥 |
| `translation.lang_in` / `lang_out` | 源语言 / 目标语言（默认 `en → zh`） |
| `translation.qps` | 每秒钟最多发起的模型请求数；默认 4，除非 API 配额充足否则不要超过 8，否则容易 429/超时 |
| `[server].port` | 端口，默认 5000；被占用时可改为 5001 |

环境变量（均优先于配置文件）：

```powershell
$env:MODEL_API_KEY = '你的真实密钥'   # 覆盖 model.api_key
```

完整字段手册、所有服务商配方（DeepSeek / OpenAI 兼容 / GLM / Qwen / 豆包 / Gemini / Groq / xAI 等）与类型约束都在 [config.example.toml](config.example.toml) 中，每条都有注释。

配置扩展的设计说明见 [PDF2ZH 配置能力扩展设计](docs/completed%20improvements/pdf2zh-configuration-expansion-design-830.md)（原路径 `docs/pdf2zh-configuration-expansion-design.md` 已归档）。

## 常见问题

**`[start.bat] ERROR: virtual environment not found`**
说明还没初始化环境。回到[安装](#安装一次性)步骤执行 venv 创建与依赖安装，之后再双击 start.bat。

**启动报错说 API Key 无效/缺失/是示例占位符**
`config.toml` 缺 `model.api_key` 或 `model.model`、或仍是 `sk-your-api-key-here` 时会被启动校验拒绝。填写真实密钥，或删除该行改用 `MODEL_API_KEY` 环境变量。

**双击 start.bat 窗口一闪而过**
双击启动时控制台窗口不会停留。请在 PowerShell 中运行 `.\start.bat` 查看完整错误信息；常见原因是初始化未完成或端口被占用。

**端口 5000 被占用**
`start.bat` 只报告、不杀任何进程。先确认占用者：

```powershell
netstat -ano -p tcp | findstr ":5000 "
tasklist /FI "PID eq <pid>"
```

确认为可安全关闭的程序后再自行处理；或者改 `config.toml` 的 `[server].port = 5001` 后运行 `.\venv\Scripts\python.exe -m pdf_reader`，访问 http://127.0.0.1:5001。

**第一次翻译时任务失败或进程直接退出**
首次翻译需要联网下载版面分析模型（GitHub / HuggingFace）。下载失败时请检查网络，或为 Python 进程配置系统代理后重试；模型已缓存后不再需要下载。

**翻译太慢或频繁 429**
降低 `translation.qps`（1 或 4），或检查 API 账户配额。`qps` 指每秒最多发起的请求数，调大不保证变快，但额度消耗会更快。

**想看详细日志**
日志在 `logs/pdf_reader.log`（轮转）。`python -m pdf_reader --debug` 会输出详细诊断并在文档缓存里写调试轨迹；密钥、Bearer token 与提示词内容在日志中一律脱敏。

**能翻译扫描版 PDF 吗**
目前依赖版面分析，扫描版/纯图片 PDF 不在保证范围内；相关开关见 `config.example.toml` 中 `[pdf2zh]` 段注释。

## 数据与备份

| 位置 | 内容 |
|---|---|
| `cache/<pdf-hash>/right.pdf` | 每篇文档的译文工作副本（按源 PDF 哈希隔离） |
| `cache/<pdf-hash>/user_glossary.csv` | 该文档的权威术语（你确认过的译法） |
| `cache/<pdf-hash>/term_candidates.json` | 候选术语与接受/拒绝状态 |
| `cache/<pdf-hash>/reading_progress.json` | 阅读进度 |
| `docs/glossary.csv` | 全局默认词表（对所有文档生效） |
| `logs/` | 运行日志 |

备份术语时，在停止服务后整文件复制 `docs/glossary.csv` 与 `cache/<pdf-hash>/` 下的术语文件即可；恢复时放回原目录并保持文件名不变。

清理遗留的临时工作区（只读统计 / 预览 / 删除）：

```powershell
python scripts/cache_manage.py stats          # 统计
python scripts/cache_manage.py clean          # 预览（dry-run，不删除）
python scripts/cache_manage.py clean --yes    # 删除可识别且无活进程的临时工作区
```

`clean` 只删除有归属标记且对应进程已退出的临时目录，译文、术语表、进度与任何文档缓存永远不会被清理。

## 项目结构

```text
src/pdf_reader/       Python 后端：Flask 应用、翻译编排、术语、缓存与生命周期
static/               前端：双栏阅读器与翻译 UI（无需构建）
templates/            index.html
config.example.toml   完整配置手册（含全部 provider 配方）
scripts/              缓存管理、验证、密钥扫描等工具
tests/                Python 与前端测试
docs/                 文档索引、长期事实、指南、治理、报告与归档
```

## 开发

- 依赖锁文件 `requirements.lock` 由 `pip-compile` 按 Python 3.12 生成，同时包含开发依赖（pytest / ruff / mypy / coverage）；前端测试还需要 Node.js 22 与 `npm ci`。
- 完整验证：`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`（密钥扫描 → lint → pytest 覆盖率 → mypy → 前端 lint/测试），CI 用 Windows + Python 3.12 + Node 22 每次自动执行。
- 上游依赖升级前先跑治理门静态检查：`python scripts/upgrade_governance_gate.py --static-only`。
- 升级任何 Python 依赖前先跑上游契约测试：`python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py`。

深入资料：[文档索引](docs/README.md) · [项目背景](docs/project.md) · [架构](docs/architecture.md) · [路线图](docs/roadmap.md) · [术语系统指南](docs/terminology-system.md) · [许可证说明](docs/governance/license.md) · [文档治理](docs/governance/documentation.md)

## 许可与致谢

- 本项目以 [AGPL-3.0-only](LICENSE) 发布。
- 版面级 PDF 翻译基于 [pdf2zh-next / PDFMathTranslate-next](https://github.com/PDFMathTranslate-next/PDFMathTranslate-next) 与 BabelDOC，特此致谢。
- 如果这个项目对你有帮助，欢迎点个 ⭐。
