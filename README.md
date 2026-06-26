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
- **翻译进度**：SSE 实时推送翻译进度条及阶段标签
- **调试追踪**：`--debug` CLI 开关 + `config.toml` 配置驱动。debug off 时仍有 INFO 流程轨迹（open/翻译/替换/合并），debug on 时额外展示 DEBUG 细节（渲染每页、token 用量、第三方进度）。所有日志持久化到 `logs/pdf_reader.log`（轮转保留），per-PDF 调试留档到 `cache/<sha256>/debug_trace.log`
- **后端服务层模块化**：15 个独立模块，单一职责，低耦合高内聚。`services.py` 已拆分为 `file_hash.py` / `engine_resolver.py` / `pdf_renderer.py`，翻译后处理抽取为 `translation_lifecycle.py`，翻译参数组装抽取为 `translation_settings.py`
- **数据驱动引擎**：声明式 `EngineSpec` + `ENGINE_REGISTRY`（`engine_resolver.py`），新增引擎仅需一行配置
- **线程安全**：渲染全程持锁，杜绝竞态；翻译端点页码校验防越界；171 个 Python 测试 + 9 个 JS 前端测试确保变更安全

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.12 + Flask | 后端 HTTP 服务 |
| pymupdf (MuPDF) | PDF 页面渲染为 PNG（200 DPI） |
| pdf2zh-next v2.9.0 | 翻译引擎（基于 BabelDOC v0.6.2） |
| 多模型 LLM API | 翻译服务（支持 DeepSeek / 智谱 / 硅基流动 / OpenAI 等 10 引擎） |
| HTML/CSS/JS（原生 ES Module） | 前端，无框架，无构建工具 |
| IntersectionObserver | 图片懒加载 |
| pytest | 后端单元测试 |
| ruff | Python 代码 lint + 格式化 |

## 项目结构

```
PDF_reader/
├── app.py                        # Flask 入口，创建 app + 注册路由
├── config.py                     # 配置加载（环境变量 / config.toml）+ EngineSpec 引擎注册表
├── logging_config.py             # 集中式日志配置（setup_logging + 轮转文件 + 第三方降噪）
├── logs/                         # 日志输出目录（轮转：5MB×5）
│   └── .gitkeep
├── state.py                      # AppState 类（单锁线程安全状态管理）
├── file_hash.py                  # SHA256 文件哈希计算
├── engine_resolver.py            # 翻译引擎查找与参数映射
├── pdf_renderer.py               # PDF 页面渲染（PyMuPDF → PNG）
├── translation_settings.py       # 组装 pdf2zh-next 翻译参数
├── translation_lifecycle.py      # 翻译完成后的持久化、术语合并、清理
├── pdf_extraction.py             # 单页 PDF 抽取
├── translation_orchestrator.py   # 翻译编排（asyncio 线程 + 事件队列）
├── sse_stream.py                 # SSE 流式推送 + 阶段标签定义
├── glossary_service.py           # 术语表路径解析 + 翻译后合并
├── glossary_merger.py            # 术语表合并（按 source 列投票去重）
├── debug_trace.py                # 调试细节层（流程骨架 INFO + 细节 DEBUG + debug_session 文件留档）
├── routes.py                     # Flask 路由注册（Blueprint，薄路由层）
├── config.toml                   # 配置文件（模型、DPI、服务器、调试）
├── config.example.toml           # 配置文件模板（含完整参数表格）
├── glossary.csv                  # 术语表（source,target）
├── requirements.txt              # Python 运行时 + 开发依赖
├── requirements.lock             # 精确版本锁定
├── ruff.toml                     # Python lint 配置
├── templates/
│   └── index.html                # 双栏阅读器前端页面
├── static/
│   ├── app.js                    # 前端入口（ES Module）
│   ├── style.css                 # 样式
│   └── modules/
│       ├── dom.js                # DOM 引用与元素创建
│       ├── sse-client.js         # SSE 流解析（纯函数，无 DOM 依赖）
│       ├── scroll-sync.js        # 滚动同步 + 页码检测
│       ├── lazy-loader.js        # IntersectionObserver 懒加载
│       ├── stages.js             # 阶段标签（从后端 /api/stages 拉取）
│       └── translator.js         # 翻译编排（回调驱动，无 DOM 访问）
├── tests/                        # pytest 单元测试（171 个测试）
│   ├── conftest.py
│   ├── test_app.py
│   ├── test_debug_trace.py
│   ├── test_debug_patches.py
│   ├── test_engine_registry.py
│   ├── test_glossary_merger.py
│   ├── test_glossary_service.py
│   ├── test_pdf_extraction.py
│   ├── test_routes.py
│   ├── test_services.py
│   ├── test_sse_stream.py
│   ├── test_state.py
│   ├── test_config_deferred.py
│   ├── test_translation_lifecycle.py
│   ├── test_translation_orchestrator.py
│   ├── run-task-4.4-tests.mjs
│   ├── run-task-4.5-tests.mjs
│   ├── run-lazy-loader-tests.mjs
│   └── run-translator-tests.mjs
├── .github/workflows/
│   └── ci.yml                    # GitHub Actions CI 流水线
├── cache/                        # 翻译缓存目录
│   └── <sha256>/                 # 按 PDF 哈希隔离
│       ├── right.pdf             # 译文持久化文件
│       ├── cumulative_glossary.csv  # 累积术语表（自动生成）
│       ├── debug_trace.log          # 调试追踪日志
│       └── debug_trace.*.log        # 轮转的历史调试日志
├── venv/                         # Python 虚拟环境
├── openspec/                     # 项目 OpenSpec 规范
│   ├── specs/                    # 14 个 capability 规格
│   └── changes/archive/          # 已归档的变更
├── docs/superpowers/             # Superpowers 设计文档与计划
├── .comet/                       # Comet 工作流配置
├── .codegraph/                   # CodeGraph 代码索引
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

#### 调试模式

```powershell
python app.py --debug
```

或在 `config.toml` 中设置：

```toml
[debug]
enabled = true
```

开启后翻译过程输出全链路调试日志（术语提取 LLM 交互、各步骤耗时），日志写入 `cache/<sha256>/debug_trace.log`（自动轮转）。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/open` | 打开 PDF。Body: `{"path": "C:/doc.pdf"}`。返回页数、尺寸、SHA256 |
| `GET` | `/api/page/<side>/<int:page>` | 获取第 N 页 PNG 图片。side: `left` 或 `right` |
| `GET` | `/api/page-count/<side>` | 获取左/右栏的总页数 |
| `POST` | `/api/translate/<int:page>` | 翻译第 N 页。Body: `{"prompt": "自定义指令"}`（可选）。SSE 流式返回进度 |
| `GET` | `/api/translated-pages` | 获取已翻译的页码列表 |
| `GET` | `/api/stages` | 获取翻译阶段标签（前后端统一） |

## 核心设计

### 翻译流程

```
用户点击"翻译" 
  → 后端提取原 PDF 第 N 页为临时单页 PDF（pdf_extraction.py）
  → 调用翻译编排器（translation_orchestrator.py：asyncio 线程 + 事件队列）
  → pdf2zh-next（BabelDOC 管道）翻译
   → 译文插入 right.pdf 第 N 页（覆盖）
   → 每步均有 INFO 日志记录（带 [page=N] 前缀），异常时 ERROR 含 page + provider + model + exc_info
   → 前端 SSE 接收进度 → 刷新右栏图片
```

### 服务层架构

翻译端点（`routes.py`）为薄路由层，委托给独立服务模块：

- `pdf_extraction.py` — 单页 PDF 抽取（pymupdf）
- `translation_orchestrator.py` — 翻译编排（asyncio 线程 + 事件队列，`TranslationError` 异常传播）
- `sse_stream.py` — SSE 事件生成 + `STAGE_LABELS` 阶段标签定义（后处理委托给 `translation_lifecycle.py`）
- `translation_lifecycle.py` — 翻译完成后的持久化（replace_page + 术语合并 + 临时目录清理）
- `file_hash.py` — SHA256 文件哈希
- `engine_resolver.py` — 翻译引擎查找与参数映射
- `pdf_renderer.py` — PDF 页面渲染（PyMuPDF → PNG 字节）
- `translation_settings.py` — 组装 pdf2zh-next 翻译参数（SettingsModel）
- `glossary_service.py` — 术语表路径解析 + 翻译后合并
- `debug_trace.py` — 条件调试追踪（零侵入业务代码）

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

`engine_resolver.py` 中 `resolve_engine()` + `build_engine_kwargs()` 遍历 `spec.field_map` 动态构造参数，新增引擎仅需在 `ENGINE_REGISTRY` 追加一行 `EngineSpec`。

### 滚动同步与懒加载

- **滚动稳定闸门**：~150ms 去抖，所有 load/unload/page-detection 统一收敛到滚动停止后执行
- **双向按比例同步**：左右任一栏滚动 → `scrollTop/(scrollHeight-clientHeight)` 比例 → rAF 内同步另一栏，`syncing` 标志防回环
- **落点加载**：IntersectionObserver 降级为候选标记器（200% 缓冲区），settle 后仅加载视口 ±2 页，扫过页丢弃不请求
- **延迟卸载**：离开视口 >10 页且在 settle 后确认，才卸载图片，杜绝边界 `load→unload→load` 振荡
- **容器级加载守卫**：`page-container.dataset.loaded` 持久标记，`<img>` 在 `onload` 前不替换占位，加载前后高度不变

### 调试追踪

- `debug_trace.py` 提供 `log_step`（INFO 流程骨架）、`log_token_usage`（DEBUG 细节）、`log_glossary_merge`（INFO 合并完成）、`debug_session`（per-PDF 文件留档上下文管理器，仅 debug on）
- INFO 流程日志常驻不受 `config.DEBUG` 影响；DEBUG 细节仅在 root logger 级别为 DEBUG 时可见
- 日志由 `logging_config.setup_logging(debug)` 集中配置：控制台 + `logs/pdf_reader.log` 轮转文件双输出
- 第三方库（werkzeug / pdf2zh_next / babeldoc）固定为 DEBUG 级别，平时不刷屏
- 翻译流程日志带 `[page=N]` / `[batch=from-to]` 关联前缀，错误日志含 page + provider + model + tmpdir + exc_info
- 启动时 INFO 输出配置摘要（provider/model/lang/cache_dir/dpi/debug），不含 api_key

## 开发

- `ruff check .` — Python lint
- `pytest tests/ -v` — Python 单元测试（171 个）
- `npm run test:translator` — 前端翻译模块测试（9 个用例，30 个断言）
- `npm run test:task-4.4` / `npm run test:task-4.5` / `npm run test:lazy-loader` — 前端懒加载测试
- `pip freeze > requirements.lock` — 更新版本锁定
- CI（GitHub Actions）：push/PR 到 `main` 自动运行 `ruff check .` + `pytest -q`

## 相关文档

- `openspec/specs/` — 20 个 capability 的详细规格
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
| 6月21日 | 大规模优化重构（5 项变更）：① 线程安全强化（渲染全程持锁 + 页码校验）② 翻译服务层抽取（routes 薄化，6 个独立服务模块）③ 数据驱动引擎注册表（EngineSpec 声明式配置）④ 调试追踪隔离（debug_trace.py 统一、config 驱动、零侵入）⑤ 前端模块化（ES Module 拆分为 6 模块 + /api/stages 统一标签），111 测试 |
| 6月22日 | 模块内聚性重构：`services.py` 拆分为 4 个独立模块（`file_hash.py` / `engine_resolver.py` / `pdf_renderer.py` / `translation_lifecycle.py`），`GenerateContext` 接口缩小，`glossary_service` 参数类型缩小为 `Path`，`debug_trace.py` 消除重复代码，106 测试 |
| 6月23日 | 拆分 `pdf_renderer.py` 双重职责：`build_settings()` 迁入新模块 `translation_settings.py`，`pdf_renderer.py` 回归单一职责（PDF 渲染），106 测试 |
| 6月24日 | 修复懒加载与滚动同步三大缺陷：① 落点加载（长距跳转请求 ≤~5）② 双向按比例同步 ③ 消除翻页边界振荡。新增 settle gate + 候选标记 IO + 延迟卸载 + 容器级守卫，16 任务 subagent-driven 执行 |
| 6月24日 | 延迟配置校验（`defer-config-validation`）：修复 CI/新克隆环境中 `import config` 即崩溃的问题，校验从模块导入期延迟到引擎消费时 |
| 6月24-25日 | CI 与 Lint 清理（`add-ci-and-lint-cleanup`）：新增 GitHub Actions CI 流水线（ruff + pytest），清理 ruff 废弃规则告警，pytest 纳入 requirements.lock |
| 6月25日 | 修复并发资源清理（`fix-concurrency-resource-cleanup`）：SSE 异常退出时临时目录泄漏（加 `try/finally`）+ `extract_page` 未持锁导致数据竞争（新增持锁方法），新增 4 类清理测试 + 3 类并发测试 |
| 6月25日 | TranslateResult 协议（`add-translate-result-protocol`）：`finish_translation` 的 `Any` 收紧为 `Protocol`，静态检查 pdf2zh-next 上游契约，新增 4 个 fallback 路径测试 |
| 6月25日 | 前端翻译测试（`add-translator-frontend-tests`）：新增 9 个 jsdom 测试覆盖 translator.js（5 例）+ sse-client.js（4 例），`npm run test:translator` 一键运行 |
| 6月26日 | 日志系统改造（`logging-system-overhaul`）：集中式 logging_config + 10 模块命名空间化 INFO/DEBUG 日志 + 移除 monkey-patch + page/batch 关联前缀 + 错误上下文 + 第三方降噪 + 启动摘要。171 测试，ruff 零错误 |
