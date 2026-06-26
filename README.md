# 双语 PDF 阅读器

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org)
[![Tests](https://img.shields.io/badge/tests-175%20passed-brightgreen.svg)](.)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230.svg)](https://docs.astral.sh/ruff)

双语对照 PDF 阅读器 —— 左栏原文，右栏译文，流式滚动，按需翻译。专为阅读英文教材、论文设计。

## 功能

- **双栏布局** — 左侧原文，右侧译文，双向同步滚动
- **流式阅读** — 页面纵向连续排列，鼠标滚轮阅读，无翻页 UI
- **按需翻译** — 读到哪页点翻译，不预加载，节省 API 调用
- **批量翻译** — 页码范围一次提交，跨页翻译更连贯
- **自定义提示词** — 翻译时可输入额外指令（如"waveguide 翻译为波导"）
- **术语表管理** — CSV 文件维护术语对照，翻译时自动注入；累积术语表随使用自动增长，跨会话复用
- **持久化** — 译文保存在 `right.pdf` 中，关闭后下次打开自动恢复
- **大 PDF 支持** — IntersectionObserver 懒加载，1000 页不卡顿
- **进度流式推送** — SSE 实时推送翻译进度及阶段标签
- **调试追踪** — `--debug` 开关 + `config.toml` 配置驱动；INFO 流程日志常驻，DEBUG 细节按需开启
- **模块化后端** — 15 个独立模块，单一职责
- **数据驱动引擎** — 声明式 `EngineSpec` + `ENGINE_REGISTRY`，新增引擎仅需一行配置
- **线程安全** — 渲染全程持锁 + 页码校验防越界；175 个 Python 测试 + 前端测试

## 快速开始

### 环境要求

- Windows 10+（macOS / Linux 调整路径即可）
- Python 3.12+
- LLM API Key（DeepSeek / 智谱 / OpenAI 等）

### 安装

```powershell
git clone https://github.com/<your-username>/PDF_reader.git
cd PDF_reader

python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp config.example.toml config.toml
```

### 配置模型

编辑 `config.toml`：

```toml
[model]
provider = "deepseek"
api_key  = "sk-your-api-key"
model    = "deepseek-v4-flash"
```

或通过环境变量设置（推荐）：

```powershell
$env:MODEL_API_KEY = "sk-your-api-key"
```

#### 支持的引擎

| 供应商 | `provider` 值 | 必填参数 |
|--------|--------------|----------|
| DeepSeek | `deepseek` | `api_key`, `model` |
| 智谱 | `zhipu` | `api_key`, `model` |
| OpenAI | `openai` | `api_key`, `model` |
| Groq | `groq` | `api_key`, `model` |
| Gemini | `gemini` | `api_key`, `model` |
| Grok | `grok` | `api_key`, `model` |
| 硅基流动 | `siliconflow` | `api_key`, `model` |
| 阿里云 DashScope | `dashscope` | `api_key`, `model` |
| ModelScope | `modelscope` | `api_key`, `model` |
| OpenAI 兼容接口 | `openai_compatible` | `api_key`, `model`, `base_url` |

完整参数表见 `config.example.toml`。

> **迁移提示：** 旧版 `[deepseek]` 配置段和 `DEEPSEEK_API_KEY` 环境变量已废弃，请改用 `[model]` 和 `MODEL_API_KEY`。

### 术语表（可选）

编辑 `glossary.csv`：

```csv
source,target
waveguide,波导
manifold,流形
thermodynamic potential,热力学势
```

### 启动

```powershell
.\venv\Scripts\Activate.ps1
python app.py
```

浏览器打开 `http://127.0.0.1:5000`，输入 PDF 文件路径即可开始阅读。

#### 调试模式

```powershell
python app.py --debug
```

或在 `config.toml` 中设置：

```toml
[debug]
enabled = true
```

开启后翻译过程输出全链路调试日志，写入 `cache/<sha256>/debug_trace.log`（自动轮转）。

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.12 + Flask | 后端 HTTP 服务 |
| PyMuPDF (MuPDF) | PDF 页面渲染为 PNG（200 DPI） |
| pdf2zh-next v2.9.0 | 翻译引擎（基于 BabelDOC v0.6.2） |
| 多模型 LLM API | 翻译服务（10 个内置引擎 + OpenAI 兼容接口） |
| 原生 HTML/CSS/JS (ES Modules) | 前端，无框架，无构建工具 |
| IntersectionObserver | 图片懒加载 |
| pytest | 后端单元测试 |
| Ruff | Python 代码检查与格式化 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/open` | 打开 PDF。Body: `{"path": "C:/doc.pdf"}`。返回页数、尺寸、SHA256 |
| `GET` | `/api/page/<side>/<int:page>` | 获取第 N 页 PNG。side: `left` 或 `right` |
| `GET` | `/api/page-count/<side>` | 获取左/右栏总页数 |
| `POST` | `/api/translate/<int:page>` | 翻译第 N 页。Body: `{"prompt": "..."}`（可选）。SSE 流式返回进度 |
| `POST` | `/api/translate/batch` | 批量翻译。Body: `{"start": 1, "end": 10, "prompt": "..."}` |
| `GET` | `/api/translated-pages` | 获取已翻译页码列表 |
| `GET` | `/api/stages` | 获取翻译阶段标签（前后端统一） |

## 架构设计

### 翻译流程

```
用户点击"翻译"
  → 从源 PDF 抽取第 N 页为临时单页 PDF（pdf_extraction.py）
  → 调用翻译编排器（translation_orchestrator.py：asyncio 线程 + 事件队列）
  → pdf2zh-next（BabelDOC 管道）翻译
  → 译文插入 right.pdf 第 N 页（覆盖）
  → 每步均有 INFO 日志记录（带 [page=N] 前缀），异常时 ERROR 含 page + provider + model + exc_info
  → 前端 SSE 接收进度 → 刷新右栏图片
```

### 服务层

翻译端点（`routes.py`）为薄路由层，委托给独立服务模块：

| 模块 | 职责 |
|------|------|
| `pdf_extraction.py` | 单页/多页 PDF 抽取（PyMuPDF） |
| `translation_orchestrator.py` | 翻译编排（asyncio 线程 + 事件队列） |
| `sse_stream.py` | SSE 事件生成 + 阶段标签定义 |
| `translation_lifecycle.py` | 翻译完成后持久化（replace_page + 术语合并 + 清理） |
| `translation_settings.py` | 组装 pdf2zh-next 翻译参数 |
| `file_hash.py` | SHA256 文件哈希 |
| `engine_resolver.py` | 翻译引擎查找与参数映射 |
| `pdf_renderer.py` | PDF 页面渲染（PyMuPDF → PNG 字节） |
| `glossary_service.py` | 术语表路径解析 + 翻译后合并 |
| `glossary_merger.py` | 术语表合并（多数投票去重） |
| `debug_trace.py` | 条件调试追踪（零侵入业务代码） |

### 持久化

- 首次打开 PDF 时计算 SHA256，将源 PDF 复制到 `cache/<sha256>/right.pdf`
- 每次翻译将译文替换 right.pdf 对应页，非增量保存
- 再次打开同一 PDF → 哈希匹配 → 恢复 right.pdf → 译文自动显示
- 不同 PDF 有不同哈希 → 各自独立缓存，术语表也按 PDF 隔离

### 累积术语表

- 翻译完成后，自动提取的专业术语合并到 `cache/<sha256>/cumulative_glossary.csv`
- 后续翻译同一 PDF 时，累积术语表自动加载，LLM 在术语提取和正文翻译阶段均能看到已有术语
- 同一 `source` 出现多个 `target` 时，多数投票选最频繁译名
- 按 PDF 哈希隔离，不同教材互不干扰，与手动术语表（`glossary.csv`）兼容共存

### 引擎注册表

`config.py` 使用声明式 `EngineSpec` dataclass + `ENGINE_REGISTRY` 列表描述 10 个翻译引擎：

```python
@dataclass(frozen=True)
class EngineSpec:
    provider: str          # 引擎标识
    settings_cls: type     # pdf2zh-next Settings 类
    field_map: dict        # unified_name → engine_field_name 字段映射
    required_fields: tuple # 必填字段（如 ("api_key", "model")）
```

`engine_resolver.py` 遍历 `spec.field_map` 动态构造参数，新增引擎仅需在 `ENGINE_REGISTRY` 追加一行 `EngineSpec`。

### 滚动同步与懒加载

- **滚动稳定闸门** — ~150ms 去抖，所有 load/unload/page-detection 统一收敛到滚动停止后执行
- **双向按比例同步** — 左右任一栏滚动 → `scrollTop/(scrollHeight-clientHeight)` 比例 → rAF 内同步另一栏，`syncing` 标志防回环
- **落点加载** — IntersectionObserver 降级为候选标记器（200% 缓冲区），settle 后仅加载视口 ±2 页
- **延迟卸载** — 离开视口 >10 页且在 settle 后确认才卸载图片，杜绝边界 `load→unload→load` 振荡
- **容器级加载守卫** — `page-container.dataset.loaded` 持久标记，`<img>` 在 `onload` 前不替换占位

### 调试追踪

- `debug_trace.py`：`log_step`（INFO 流程骨架）、`log_token_usage`（DEBUG 细节）、`log_glossary_merge`（INFO 合并完成）、`debug_session`（per-PDF 文件留档，仅 debug on）
- INFO 流程日志常驻，不受 `config.DEBUG` 影响；DEBUG 细节仅在 root logger 级别为 DEBUG 时可见
- 日志由 `logging_config.setup_logging(debug)` 集中配置：控制台 + `logs/pdf_reader.log` 轮转文件（5MB × 5）
- 第三方库（werkzeug / pdf2zh_next / babeldoc）固定 DEBUG 级别，不刷屏
- 翻译流程日志带 `[page=N]` / `[batch=from-to]` 前缀，错误日志含 page + provider + model + tmpdir + exc_info
- 启动时 INFO 输出配置摘要（provider / model / lang / cache_dir / dpi / debug），不含 api_key

## 项目结构

```
PDF_reader/
├── app.py                        # Flask 入口 + 路由注册
├── config.py                     # 配置加载 + 引擎注册表
├── config.toml                   # 用户配置（API Key、模型、DPI 等）
├── config.example.toml           # 配置模板
├── state.py                      # AppState（线程安全单例）
├── file_hash.py                  # SHA256 文件哈希
├── engine_resolver.py            # 引擎查找与参数映射
├── pdf_renderer.py               # PDF → PNG 渲染
├── pdf_extraction.py             # 单页/多页 PDF 抽取
├── translation_settings.py       # 组装 pdf2zh-next 翻译参数
├── translation_orchestrator.py   # 翻译编排
├── translation_lifecycle.py      # 翻译后持久化与清理
├── sse_stream.py                 # SSE 流式推送 + 阶段标签
├── glossary_service.py           # 术语表路径解析
├── glossary_merger.py            # 术语表合并去重
├── logging_config.py             # 集中式日志配置
├── debug_trace.py                # 条件调试追踪
├── glossary.csv                  # 手动术语表
├── requirements.txt              # 运行时 + 开发依赖
├── requirements.lock             # 精确版本锁定
├── ruff.toml                     # Python lint 配置
├── templates/
│   └── index.html                # 双栏阅读器前端页面
├── static/
│   ├── app.js                    # 前端入口（ES Module）
│   ├── style.css                 # 样式
│   └── modules/
│       ├── dom.js                # DOM 引用与元素创建
│       ├── sse-client.js         # SSE 流解析
│       ├── scroll-sync.js        # 滚动同步 + 页码检测
│       ├── lazy-loader.js        # IntersectionObserver 懒加载
│       ├── stages.js             # 阶段标签（从 /api/stages 拉取）
│       └── translator.js         # 翻译编排（回调驱动）
├── tests/                        # pytest 单元测试（175 个测试）
├── .github/workflows/
│   └── ci.yml                    # GitHub Actions CI（ruff + pytest）
├── cache/                        # 翻译缓存（gitignore）
├── logs/                         # 日志输出（gitignore）
├── openspec/                     # 项目规范文档
└── docs/                         # 设计文档与计划
```

## 开发

```powershell
# Python 代码检查
ruff check .

# 格式检查
ruff format --check .

# 运行全部测试（175 个）
pytest -q

# 前端测试
npm run test:translator
npm run test:lazy-loader
npm run test:task-4.4
npm run test:task-4.5

# 锁定依赖版本
pip freeze > requirements.lock
```

CI（GitHub Actions）：push/PR 到 `main` 自动运行 `ruff check .` + `pytest -q`。

## 更新日志

详见 [CHANGELOG.md](./CHANGELOG.md)。

## 许可证

MIT
