# 双语 PDF 阅读器

用于阅读英文教材的双语对照 PDF 翻译/阅读器。左栏显示原文，右栏显示译文，支持按需逐页翻译、自定义翻译指令、术语表管理。

## 功能

- **双栏布局**：左侧原文，右侧译文，同步滚动
- **流式阅读**：页面纵向连续排列，鼠标滚轮滚动，无需翻页
- **按需翻译**：读到哪页点"翻译"，只翻译当前页，不预加载
- **自定义提示词**：翻译时输入额外指令（如"waveguide 翻译为波导"）
- **强制重译**：对已翻译的页可重复翻译，每次绕过缓存
- **术语表**：CSV 文件维护术语对照，翻译时自动注入 prompt。自动提取的术语跨页面累积复用，确保同一教材中术语译名一致
- **持久化**：译文保存在 `right.pdf` 中，关闭后下次打开自动恢复
- **大 PDF 支持**：IntersectionObserver 懒加载，1000 页不卡顿
- **翻译进度**：SSE 实时推送翻译进度条
- **调试追踪**：全链路日志，术语提取每批 LLM 交互可见（prompt 内容、返回结果、术语数量），翻译各步骤耗时一目了然

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.12 + Flask | 后端 HTTP 服务 |
| pymupdf (MuPDF) | PDF 页面渲染为 PNG（200 DPI） |
| pdf2zh-next v2.9.0 | 翻译引擎（基于 BabelDOC v0.6.2） |
| 多模型 LLM API | 翻译服务（支持 DeepSeek / 智谱 / 硅基流动 / OpenAI 等 10 引擎） |
| HTML/CSS/JS（原生） | 前端，无框架 |
| IntersectionObserver | 图片懒加载 |
| pytest | 后端单元测试 |
| ruff | Python 代码 lint + 格式化 |

## 项目结构

```
PDF_reader/
├── app.py                  # Flask 入口，创建 app + 注册路由
├── config.py               # 配置加载（环境变量 / config.toml）
├── state.py                # AppState 类（线程安全状态管理）
├── services.py             # 纯函数（SHA256、PNG 渲染、设置构建）
├── glossary_merger.py       # 术语表合并（按 source 列投票去重）
├── debug_patches.py          # 调试追踪 monkey-patch（术语提取 LLM 交互日志）
├── routes.py               # Flask 路由注册（Blueprint）
├── config.toml             # 配置文件（模型、DPI、服务器）
├── glossary.csv            # 术语表（source,target）
├── requirements.txt        # Python 运行时 + 开发依赖
├── requirements.lock       # 精确版本锁定
├── ruff.toml               # Python lint 配置
├── templates/
│   └── index.html          # 双栏阅读器前端页面
├── static/
│   ├── app.js              # 前端逻辑
│   └── style.css           # 样式
├── tests/                  # pytest 单元测试
│   ├── conftest.py
│   ├── test_services.py
│   ├── test_state.py
│   ├── test_routes.py
│   ├── test_glossary_merger.py
│   └── test_debug_patches.py
├── cache/                  # 翻译缓存目录
│   └── <sha256>/           # 按 PDF 哈希隔离
│       ├── right.pdf       # 译文持久化文件
│       └── cumulative_glossary.csv  # 累积术语表（自动生成）
│       ├── debug_trace.log          # 调试追踪日志
│       └── debug_trace.*.log        # 轮转的历史调试日志
├── venv/                   # Python 虚拟环境
├── openspec/               # 项目 OpenSpec 规范
│   ├── specs/              # 8 个 capability 规格
│   └── changes/archive/    # 已归档的变更
├── docs/superpowers/       # Superpowers 设计文档与计划
├── .comet/                 # Comet 工作流配置
├── .codegraph/             # CodeGraph 代码索引
├── .gitignore
└── README.md
```

## 快速开始

### 环境要求

- Windows 10+
- Python 3.12+
- 模型供应商 API Key（DeepSeek / 智谱 / OpenAI 等）

### 安装

```powershell
# 克隆项目（或直接进入项目目录）
cd PDF_reader

# 创建虚拟环境
python -m venv venv
.\venv\Scripts\Activate.ps1

# 安装依赖
pip install -r requirements.txt

# 从模板创建配置文件
cp config.example.toml config.toml
```

### 配置模型

编辑 `config.toml` 的 `[model]` 段：

```toml
[model]
provider = "deepseek"                          # 供应商
api_key  = "sk-your-api-key"                   # API Key
model    = "deepseek-v4-flash"                 # 模型名
base_url = "https://api.deepseek.com/v1"       # 可选
```

也可通过环境变量设置 `MODEL_API_KEY`（推荐，优先级更高）：

```powershell
$env:MODEL_API_KEY = "sk-your-api-key"
```

#### 切换供应商

将 `provider` 改为其他值即可，示例：

```toml
# 使用智谱
provider = "zhipu"
api_key  = "your-zhipu-key"
model    = "glm-4-flash"

# 使用 OpenAI 兼容接口（如本地 Ollama）
provider = "openai_compatible"
api_key  = "ollama"
model    = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
```

支持 10 个内置引擎 + OpenAI 通用兼容接口，详见 `config.example.toml` 中的完整表格。

> **迁移提示：** 旧版 `[deepseek]` 配置段已废弃，请改为 `[model]`。旧环境变量 `DEEPSEEK_API_KEY` 不再支持，请改用 `MODEL_API_KEY`。

其余配置项（语言对、端口等）均可在 `config.toml` 中修改，文件内含详细的中文注释。

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

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/open` | 打开 PDF。Body: `{"path": "C:/doc.pdf"}`。返回页数、尺寸、SHA256 |
| `GET` | `/api/page/<side>/<int:page>` | 获取第 N 页 PNG 图片。side: `left` 或 `right` |
| `GET` | `/api/page-count/<side>` | 获取左/右栏的总页数 |
| `POST` | `/api/translate/<int:page>` | 翻译第 N 页。Body: `{"prompt": "自定义指令"}`（可选）。SSE 流式返回进度 |
| `GET` | `/api/translated-pages` | 获取已翻译的页码列表 |

## 核心设计

### 翻译流程

```
用户点击"翻译" 
  → 后端提取原 PDF 第 N 页为临时单页 PDF
  → 调用 pdf2zh-next（BabelDOC 管道）翻译
  → 译文插入 right.pdf 第 N 页（覆盖）
  → 前端 SSE 接收进度 → 刷新右栏图片
```

### 持久化

- 首次打开 PDF 时计算 SHA256，复制原 PDF 到 `cache/<sha256>/right.pdf`
- 每次翻译将译文替换 right.pdf 对应页，非增量保存
- 再次打开同一 PDF → 哈希匹配 → 恢复 right.pdf → 译文自动显示
- 不同 PDF 有不同哈希 → 各自独立缓存，术语表也按 PDF 隔离

### 术语表累积

- 翻译完成后，pdf2zh-next 自动提取的专业术语被合并到 `cache/<sha256>/cumulative_glossary.csv`
- 后续翻译同一 PDF 的任意页面时，累积术语表自动加载，LLM 在术语提取和正文翻译阶段均能看到已有术语
- 同一 `source` 出现多个 `target` 时，采用多数投票选最频繁的译名
- 术语表按 PDF 哈希隔离，不同教材互不干扰
- 与手动术语表（`glossary.csv`）兼容共存

### 滚动同步

- 左栏 `scroll` 事件 → `requestAnimationFrame` → 设置右栏 `scrollTop`
- 右栏独立滚动不影响左栏
- IntersectionObserver 5 页缓冲区，离屏图片自动卸载

## 开发

- `ruff check` — Python lint
- `pytest tests/ -v` — 运行测试
- `pip freeze > requirements.lock` — 更新版本锁定

## 相关文档

- `openspec/specs/` — 9 个 capability 的详细规格
- `docs/superpowers/` — 设计文档与实施计划
- `pdf2zh-internals-report.md` — pdf2zh v1 源码分析
- `babeldoc-vs-pdf2zh-next-report.md` — BabelDOC 与 pdf2zh-next 对比

## 会话历史

| 日期 | 内容 |
|------|------|
| 6月16日 | 与 Hermes 讨论方案，发现 pdf2zh |
| 6月17日 | 深度研究 pdf2zh v1 源码，确定双栏阅读器方案 |
| 6月18日 | 与 OpenCode 重新评估：放弃 v1，选用 pdf2zh-next + BabelDOC。完成 proposal → design → specs → tasks → implement → verify → archive 全流程 |
| 6月19日 | 代码审查 + Comet 全流程重构：app.py 拆为 5 模块、AppState 线程安全、16 个 pytest 测试、ruff lint 零错误、前端错误处理 |
| 6月20日 | 增量术语表累积：自动提取的术语跨页面复用，多数投票去重，按 PDF 哈希隔离，新增 glossary_merger.py + 11 个测试 |
| 6月20日 | 全链路调试追踪：monkey-patch 术语提取器，Logger `pdf_reader.debug_trace` 双输出（console + 文件），翻译各步骤耗时日志，debug_trace.log 自动轮转，45 测试 |
