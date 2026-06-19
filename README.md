# 双语 PDF 阅读器

用于阅读英文教材的双语对照 PDF 翻译/阅读器。左栏显示原文，右栏显示译文，支持按需逐页翻译、自定义翻译指令、术语表管理。

## 功能

- **双栏布局**：左侧原文，右侧译文，同步滚动
- **流式阅读**：页面纵向连续排列，鼠标滚轮滚动，无需翻页
- **按需翻译**：读到哪页点"翻译"，只翻译当前页，不预加载
- **自定义提示词**：翻译时输入额外指令（如"waveguide 翻译为波导"）
- **强制重译**：对已翻译的页可重复翻译，每次绕过缓存
- **术语表**：CSV 文件维护术语对照，翻译时自动注入 prompt
- **持久化**：译文保存在 `right.pdf` 中，关闭后下次打开自动恢复
- **大 PDF 支持**：IntersectionObserver 懒加载，1000 页不卡顿
- **翻译进度**：SSE 实时推送翻译进度条

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.12 + Flask | 后端 HTTP 服务 |
| pymupdf (MuPDF) | PDF 页面渲染为 PNG（200 DPI） |
| pdf2zh-next v2.9.0 | 翻译引擎（基于 BabelDOC v0.6.2） |
| DeepSeek API | LLM 翻译服务 |
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
│   └── test_routes.py
├── cache/                  # 翻译缓存目录
│   └── <sha256>/           # 按 PDF 哈希隔离
│       └── right.pdf       # 译文持久化文件
├── venv/                   # Python 虚拟环境
├── openspec/               # 项目 OpenSpec 规范
│   ├── specs/              # 7 个 capability 规格
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
- DeepSeek API Key

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

### 配置模型 API Key

编辑 `config.toml`，填入你的 DeepSeek API Key（从 [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) 获取）：

也可通过环境变量设置（推荐，优先级更高）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-your-api-key"
```

其余配置项（模型名称、base_url、语言对、端口等）均可在 `config.toml` 中修改，文件内含详细的中文注释。`config.toml` 已被 `.gitignore` 忽略，不会提交到 git。

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
- 不同 PDF 有不同哈希 → 各自独立缓存

### 滚动同步

- 左栏 `scroll` 事件 → `requestAnimationFrame` → 设置右栏 `scrollTop`
- 右栏独立滚动不影响左栏
- IntersectionObserver 5 页缓冲区，离屏图片自动卸载

## 开发

- `ruff check` — Python lint
- `pytest tests/ -v` — 运行测试
- `pip freeze > requirements.lock` — 更新版本锁定

## 相关文档

- `openspec/specs/` — 7 个 capability 的详细规格
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
