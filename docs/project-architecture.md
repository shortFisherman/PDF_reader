# PDF Reader 项目运行逻辑完整文档

> 本文档面向非计算机专业背景的开发者，用尽量通俗的语言解释项目的每一个部分是如何协同工作的。

---

## 一、这个项目是什么

一个**PDF 阅读 + 翻译工具**，运行在浏览器中。它打开一本 PDF（通常是英文教科书/论文/文档），在**左侧显示原文**、**右侧显示译文**，双击同一个位置可以同步浏览。翻译由 AI 大语言模型（LLM）驱动，你翻到哪一页点一下「翻译」按钮，LLM 就把该页翻译出来并保留版式。

你可以把它想象成：一个本地启动的小网站，你在浏览器里打开它，它帮你把 PDF 一页一页翻译成中文。

---

## 二、技术栈概览

| 层级 | 技术 | 作用 |
|------|------|------|
| **后端服务器** | Python 3.12 + Flask | 接收浏览器发来的请求，返回数据 |
| **PDF 渲染** | PyMuPDF (MuPDF) | 把 PDF 的每一页"拍"成 PNG 图片 |
| **翻译引擎** | pdf2zh-next v2.9.0 (BabelDOC) | 调用 LLM API 完成整页翻译 |
| **LLM API** | DeepSeek / OpenAI / 智谱 / 硅基流动等 10 种 | 提供翻译能力的 AI 模型 |
| **前端界面** | 原生 HTML + CSS + JavaScript (ES Modules) | 浏览器中的按钮、页面显示、滚动同步 |
| **实时推送** | Server-Sent Events (SSE) | 翻译进度从后端推送到前端显示 |
| **测试** | pytest (106 个测试用例) | 保证代码修改后不坏掉 |
| **代码检查** | ruff | 检查 Python 代码风格 |

**没有用到的技术（特意避免的）**：Node.js、npm、Webpack、Vite、TypeScript、React、Vue、Electron。整个项目不需要编译/打包步骤，零构建成本。

---

## 三、项目目录结构

```
PDF_reader/
├── app.py                          # ★ 程序入口，启动 Flask 服务器
├── config.py                       # ★ 读取配置文件 + 定义 10 个翻译引擎
├── config.toml                     #   你的配置文件（API key、模型选择等）
├── config.example.toml             #   配置文件模板（详细的参数说明）
├── state.py                        # ★ 核心状态管理（线程安全的 PDF 文档持有者）
├── file_hash.py                    #   文件 SHA256 哈希计算
├── engine_resolver.py              #   翻译引擎查找与参数映射
├── pdf_renderer.py                 #   PDF 页面渲染 + 翻译设置组装
├── translation_lifecycle.py        #   翻译完成后的持久化 + 术语合并 + 清理
├── pdf_extraction.py               #   从原 PDF 中提取单独一页
├── translation_orchestrator.py     #   启动异步线程调用 pdf2zh-next 翻译
├── sse_stream.py                   #   将翻译进度打包成 SSE 实时推送
├── glossary_service.py             #   术语表路径解析 + 翻译后合并
├── glossary_merger.py              #   术语表合并算法（多数投票）
├── debug_trace.py                  #   调试日志系统（可开关，零开销）
├── routes.py                       # ★ Flask 路由层（定义所有 URL 接口）
├── requirements.txt                #   Python 依赖列表
├── requirements.lock               #   精确锁定版本号
├── ruff.toml                       #   代码检查规则
├── start.bat                       #   Windows 一键启动脚本
│
├── templates/
│   └── index.html                  # ★ 唯一的 HTML 页面（双栏阅读器外壳）
│
├── static/
│   ├── app.js                      # ★ 前端入口（所有交互逻辑的总控）
│   ├── style.css                   #   深色主题样式
│   └── modules/                    #   前端子模块
│       ├── dom.js                  #     DOM 缓存 + 页面元素创建
│       ├── sse-client.js           #     SSE 进度流解析器
│       ├── scroll-sync.js          #     双栏滚动同步 + 当前页检测
│       ├── lazy-loader.js          #     图片懒加载（离开屏幕就卸载）
│       ├── stages.js               #     翻译阶段标签获取
│       └── translator.js           #     翻译流程编排器
│
├── cache/                          #   缓存目录（按 PDF 的 SHA256 哈希值分文件夹）
│   └── <sha256>/
│       ├── right.pdf               #     译文 PDF（持久化，关闭后再打开还在）
│       ├── cumulative_glossary.csv  #    自动累积的术语表
│       └── debug_trace.log         #    调试日志（仅在开启 debug 时生成）
│
├── tests/                          #   111 个 pytest 测试用例
│   ├── conftest.py                 #     共享的测试夹具
│   ├── test_state.py               #     测试核心状态管理
│   ├── test_routes.py              #     测试所有 API 接口
│   ├── test_services.py            #     测试工具函数
│   ├── test_engine_registry.py     #     测试 10 个翻译引擎配置
│   └── ...（共 13 个测试文件）
│
├── docs/
│   └── glossary.csv                #   手动维护的术语表
│
└── openspec/specs/                 #   14 个功能规格说明（供 AI 辅助开发参考）
```

---

## 四、怎么启动这个项目

```powershell
# 1. 创建虚拟环境（只在第一次）
python -m venv venv

# 2. 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 3. 安装依赖（只在第一次或依赖变更时）
pip install -r requirements.txt

# 4. 复制配置文件并填上你的 API key
cp config.example.toml config.toml
# 然后编辑 config.toml，填入你的 model.api_key 和 model.model

# 5. 启动服务器
python app.py

# 6. 打开浏览器访问
# http://127.0.0.1:5000
```

也可以直接双击 `start.bat`。

---

## 五、后端：Flask 服务器是怎样工作的

### 5.1 启动流程（`app.py`）

```
用户执行 python app.py
    │
    ├─ 1. 读取命令行参数（--debug 开启调试日志）
    ├─ 2. 调用 create_app() 创建 Flask 应用
    │      ├─ 初始化调试追踪系统
    │      ├─ 创建 AppState 实例（PDF 文档管理器）
    │      └─ 注册所有 URL 路由（routes.py）
    └─ 3. app.run() 启动 HTTP 服务器
```

### 5.2 配置文件加载（`config.py`）

程序启动时自动读取项目根目录下的 `config.toml`，并将配置转换成 Python 变量供各处使用。关键配置项：

| 配置项 | 含义 |
|--------|------|
| `model.provider` | 使用哪个 AI 服务商（deepseek / openai / zhipu 等） |
| `model.api_key` | AI API 密钥（也可通过环境变量 `MODEL_API_KEY` 设置） |
| `model.model` | 具体模型名称 |
| `pdf_reader.dpi` | 渲染分辨率（默认 200 DPI） |
| `pdf_reader.cache_dir` | 缓存目录路径 |
| `translation.lang_in` | 原文语言（默认 en） |
| `translation.lang_out` | 译文语言（默认 zh） |
| `server.host` | 服务器绑定地址 |
| `server.port` | 服务器端口（默认 5000） |

**引擎注册表**：10 个 AI 服务商以 `EngineSpec` 数据类的方式声明式注册。每个引擎定义了它需要哪些配置字段以及如何映射。新增一个服务商只需在 `ENGINE_REGISTRY` 列表中加一行。

---

## 六、核心状态管理（`state.py`）

`AppState` 是**整个项目运行时的中心**——它持有所有 PDF 文档对象，管理页面渲染和翻译替换。

### 6.1 它持有哪些数据

```
AppState
├── _left_doc: pymupdf.Document    ← 原版 PDF（左侧显示的来源）
├── _right_doc: pymupdf.Document   ← 译文 PDF（右侧显示的来源）
├── _right_pdf_path: str           ← 译文 PDF 的磁盘路径
├── _pdf_hash: str                 ← 当前 PDF 的 SHA256 哈希值
├── _page_count: int               ← 总页数
├── _page_height / _page_width     ← 页面尺寸
├── _translated_pages: set[int]    ← 已翻译的页面编号集合
└── _lock: threading.Lock()        ← 线程锁（保证并发安全）
```

### 6.2 线程安全设计

由于 Flask 是多线程处理请求的，多个请求可能同时访问同一个 `AppState`。所有涉及 PDF 文档对象的操作都必须持有 `_lock` 锁。

关键设计：**整个页面渲染操作都在锁内完成**（不是只锁文档查找那一步）。这是因为翻译过程中 `replace_page` 会关闭并重新打开 `right_doc`，如果渲染操作中途文档被关闭，就会导致程序崩溃（segfault）。

### 6.3 关键方法

| 方法 | 行为 |
|------|------|
| `open_pdf(path)` | 计算文件 SHA256 → 复制到缓存 → 打开两份文档 → 返回页面信息 |
| `render_page(side, page_num)` | 持有锁 → 取文档 → 渲染页面为 PNG 字节 → 释放锁 |
| `replace_page(path, page_num)` | 持有锁 → 删除旧页 → 插入翻译页 → 保存并原子替换文件 → 重开文档 |
| `get_doc(side)` | 返回左侧或右侧的文档对象（带锁） |

### 6.4 译文持久化机制

```
首次打开 PDF:
    计算 SHA256 → 缓存目录 = cache/<sha256>/
    如果 cache/<sha256>/right.pdf 不存在 → 复制原 PDF 过去
    打开 right.pdf 作为译文文档（最初和原版完全一样）

翻译第 5 页时:
    replace_page(翻译结果单页PDF, 5):
        right_doc 删除第 5 页 → 插入翻译好的第 5 页
        → 保存到 right.pdf.tmp → 原子替换 right.pdf
        → 重新打开 right.pdf

关闭程序后再次打开同一个 PDF:
    SHA256 相同 → right.pdf 已经存在（之前翻译过的页面都在里面）
    → 已翻译的页面自动恢复，无需重新翻译
```

**原子替换**是指 `os.replace(src, dst)` 这个操作——要么完全成功、要么完全不变，不会出现写到一半断电导致文件损坏的情况。这是通过先写到 `.tmp` 文件再替换来实现的。

---

## 七、后端各模块运转逻辑

### 7.1 路由层（`routes.py`）

Flask Blueprint 定义了所有前端可以调用的 URL 接口（API）：

| 方法 | URL | 功能 |
|------|-----|------|
| `GET` | `/` | 返回阅读器 HTML 页面 |
| `POST` | `/api/open` | 打开一个 PDF 文件（传文件路径） |
| `GET` | `/api/page/<side>/<int:page>` | 获取某一页的 PNG 图片 |
| `GET` | `/api/page-count/<side>` | 获取左侧/右侧总页数 |
| `POST` | `/api/translate/<int:page>` | 翻译某一页（返回 SSE 进度流） |
| `GET` | `/api/translated-pages` | 获取已翻译的页面编号列表 |
| `GET` | `/api/stages` | 获取翻译阶段的中文标签 |

### 7.2 工具模块（`file_hash.py` / `engine_resolver.py` / `pdf_renderer.py`）

原 `services.py` 的 5 个函数已按职责拆分到 3 个独立模块，每个模块的职责单一、依赖明确：

| 模块 | 函数 | 作用 |
|------|------|------|
| `file_hash.py` | `sha256(filepath)` | 流式读取文件（8KB 分块），计算 SHA256 哈希 |
| `engine_resolver.py` | `resolve_engine(provider)` | 在引擎注册表中查找指定服务商，未找到则回退到 openai_compatible |
| `engine_resolver.py` | `build_engine_kwargs(spec)` | 将配置文件中的通用字段名映射为引擎专属字段名 |
| `pdf_renderer.py` | `render_page(doc, page_num, dpi)` | 将 PDF 一页渲染为 PNG 字节 |
| `pdf_renderer.py` | `build_settings(...)` | 组装 pdf2zh-next 所需的完整翻译参数（SettingsModel） |

### 7.3 PDF 单页提取（`pdf_extraction.py`）

pdf2zh-next 需要一个完整的 PDF 文件作为输入。但是我们只翻译一页，所以需要从原 PDF 中提取单独一页，生成为临时的一页 PDF 文件。

```
extract_single_page(原文档, 第5页, 临时目录)
    → 创建一个空白的新 PDF
    → 插入原文档的第 5 页
    → 保存为 page.pdf
    → 返回这个临时文件的路径
```

### 7.4 翻译编排器（`translation_orchestrator.py`）

这个模块解决了一个关键问题：pdf2zh-next 是一个异步（asyncio）库，而 Flask 是同步的，二者不能直接混用。

```
run_translation(settings, pdf_path) 的执行流程:

    主线程（Flask）                     daemon 线程（asyncio 事件循环）
    ────────────────                    ──────────────────────────────
    1. 创建 queue.Queue()         ←──→  事件队列（桥梁）
    2. 启动 daemon 线程                  
    3. while True:                      run_translation_thread():
        从队列取事件                      创建新的 asyncio 事件循环
        如果没有事件 → yield ""          do_translate_async_stream()
        （空字符串 = 心跳，                   │ 把每个事件放入 queue
         防止 SSE 超时断开）                   │ layout_analysis 开始
        如果事件 type=="finish"             │ translating 第1/3段
            → break                       │ translating 第2/3段
        否则 yield 事件                     │ translating 第3/3段
    4. 等待线程结束                        │ generating_pdf
    5. 如果有错误 → raise                   │ finish → 放入 translate_result
                                          │ _done 信号放入 queue
                                      loop.close()
```

核心思想：**用队列（queue.Queue）作为两个线程之间的桥梁**。主线程负责对外 yield 事件给 SSE 生成器，daemon 线程负责实际调用翻译库。

### 7.5 SSE 实时推送（`sse_stream.py`）

SSE（Server-Sent Events）是一种 HTTP 推送技术：服务器向浏览器持续发送数据流，浏览器不需要反复询问"翻译好了吗？"。

**SSE 数据格式**：
```
data: {"type":"progress","progress":0,"stage":"layout_analysis","stage_current":0,"stage_total":0}

data: {"type":"progress","progress":25,"stage":"translating","stage_current":1,"stage_total":3}

data: {"type":"progress","progress":50,"stage":"translating","stage_current":2,"stage_total":3}

data: {"type":"progress","progress":75,"stage":"translating","stage_current":3,"stage_total":3}

data: {"type":"progress","progress":95,"stage":"generating_pdf","stage_current":0,"stage_total":0}

data: {"type":"progress","progress":100,"stage":"finish","stage_current":0,"stage_total":0}

data: {"type":"finish","progress":100}
```

**`generate(ctx)` 的流程**（翻译后的持久化工作已委托给 `translation_lifecycle.py`）：

```
1. 进入 debug_session 上下文（开启调试日志）
2. 调用 run_translation()，逐个接收翻译事件
3. 每个事件用 format_sse_event() 转成 SSE 文本，yield 出去
4. 翻译完成后：
   a. finish_translation() 被调用 —— 委托给 translation_lifecycle.py
      ├─ replace_page() —— 将翻译结果写入 right.pdf
      ├─ merge_after_translate() —— 合并术语表
      └─ 清理临时目录
   b. yield progress:100 + finish 事件
5. 任何异常都会被 catch，yield error 事件
```

### 7.5b 翻译生命周期（`translation_lifecycle.py`） — 新增模块

从 `sse_stream.py` 的 `generate()` 中抽取出的后处理逻辑，负责翻译完成后的三项工作：

```
finish_translation(translate_result, replace_page, glossary_cache_path, tmpdir, output_dir)
   ├─ 1. 将翻译结果页面写入 right.pdf（调用传入的 replace_page 回调）
   ├─ 2. 合并自动提取的术语到累积术语表
   └─ 3. 清理单页 PDF 和翻译输出的临时目录
```

设计意图：`sse_stream.py` 回归纯 SSE 格式化职责，不再直接操作 `AppState` 或调用 `shutil.rmtree`。

### 7.6 术语表系统（`glossary_service.py` + `glossary_merger.py`）

术语表保证同一本书里相同的术语被一致地翻译。

**两层术语体系**：

| 层级 | 来源 | 说明 |
|------|------|------|
| 手动术语表 | `docs/glossary.csv` | 你手动创建，每次都加载 |
| 累积术语表 | `cache/<sha256>/cumulative_glossary.csv` | 自动生成，随翻译越积累越多 |

**合并算法（多数投票）**：
```
每次翻译一页后，pdf2zh-next 会自动提取该页中的术语对 (source, target)
例如：waveguide → 波导, waveguide → 波导管

merge_glossary_csvs() 做的事：
    1. 读取已有的 cumulative_glossary.csv
    2. 读取新提取的 auto_extracted_glossary.csv
    3. 统计每个 source 对应的所有 target 及其出现次数
    4. 对每个 source，选择票数最高的 target
    5. 覆盖写回 cumulative_glossary.csv
```

不同 PDF（不同 SHA256）的术语表完全隔离，不会互相干扰。

### 7.7 调试追踪（`debug_trace.py`）

**零开销设计**：当 `config.DEBUG = False` 时，所有调试函数直接返回，不做任何字符串格式化、不做任何 I/O 操作。生产环境下零性能影响。

当 `config.DEBUG = True`（通过 `python app.py --debug` 或配置文件中 `debug.enabled = true`）时：
- 每个翻译会话创建独立的日志文件：`cache/<sha256>/debug_trace.log`
- 旧的日志文件自动轮转（附上时间戳）
- 日志内容：每个步骤的耗时、token 用量、术语批量提取的 prompt/response 长度
- Monkey-patch 了 BabelDOC 内部的术语提取器，以记录每次 LLM 调用的详细信息

---

## 八、前端：浏览器中是怎么运行的

### 8.1 HTML 页面结构（`templates/index.html`）

整个前端只有**一个 HTML 页面**，分为三个区域：

```
┌──────────────────────────────────────────────┐
│  #file-input-area（打开前显示）                │
│  ┌────────────────────────────────────────┐   │
│  │  Open PDF Document                     │   │
│  │  [文件路径输入框]        [Open 按钮]     │   │
│  └────────────────────────────────────────┘   │
│  #app（打开 PDF 后显示）                       │
│  ┌──────────────────┬─────────────────────┐   │
│  │  #left-column    │  #right-column      │   │
│  │  原版 PDF 图片   │  译文 PDF 图片      │   │
│  │  (左侧栏)        │  (右侧栏)           │   │
│  └──────────────────┴─────────────────────┘   │
│  #toolbar（底部固定工具栏）                     │
│  ┌────────────────────────────────────────┐   │
│  │ Page 5  [+ Prompt] [━━━━━░░░░░] [翻译] │   │
│  └────────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

### 8.2 前端模块图（ES Modules）

```
app.js (入口，持有所有共享状态：pageCount, currentPage, isTranslating 等)
  │
  ├── dom.js ──────► DOM 元素缓存 + 创建页面容器
  ├── lazy-loader.js ► IntersectionObserver 懒加载/卸载图片
  ├── scroll-sync.js ► 双栏同步滚动 + 当前页检测
  ├── stages.js ───► 获取翻译阶段中文标签
  └── translator.js ► 发起翻译请求，消费 SSE 流
       └── sse-client.js ► 解析 SSE 数据流的纯函数
```

注意：前端没有使用 React、Vue 等框架，也没有使用 npm。JS 文件通过 `<script type="module">` 标签加载，浏览器原生支持 ES 模块导入。这意味着你修改任何一个 JS 文件后刷新浏览器就能看到效果，不需要编译。

### 8.3 `app.js` 详解

**全局状态（所有模块共享的核心数据）**：
```
pageCount    = 总页数
pageHeight   = 页面高度
pageWidth    = 页面宽度
currentPage  = 用户当前正在浏览的页码
isTranslating = 是否正在翻译中（防止重复点击）
promptVisible = 自定义提示输入框是否展开
```

**核心函数调用链**：

```
init()                              — 页面加载时执行
  ├─ 绑定按钮点击事件
  └─ fetchStageLabels()             — 预加载翻译阶段标签

用户点击 Open →
  openPdf()                         — 打开 PDF
    ├─ POST /api/open               — 获取页面数量、尺寸
    ├─ 为每页创建 DOM 容器（左栏 + 右栏各一个）
    ├─ 隐藏文件输入区，显示阅读器和工具栏
    ├─ setupIntersectionObserver()  — 启动懒加载
    ├─ setupScrollSync()            — 启动滚动同步
    ├─ setupPageDetection()         — 启动当前页检测
    └─ loadTranslatedState()        — 查询并标记已翻译的页面

用户滚动 →
  IntersectionObserver              — 页面进入视口 → 加载图片；离开视口 → 卸载图片
  scroll-sync                       — 左栏滚动 → 右栏同步跟进
  page-detection                    — 计算哪一页占比最大 → 更新 Page N 显示

用户点击 Translate →
  onTranslateClick()
    ├─ 禁用按钮，显示进度条
    ├─ translateCurrentPage(currentPage, callbacks)
    │     ├─ POST /api/translate/N
    │     └─ readSSEStream(response, eventHandler)
    │           ├─ 收到 progress → 更新进度条
    │           ├─ 收到 stage_change → 更新状态文本（"正在翻译… 第 2/3 段"）
    │           └─ 收到 finish → 重新加载右栏图片，标记为已翻译
    └─ 恢复按钮（无论成功失败）
```

### 8.4 图片懒加载（`lazy-loader.js`）

PDF 页数是无限的（一本 500 页的教科书），但浏览器能同时显示的图片数有限。懒加载的意思是：**只加载当前屏幕及附近的页面图片，离开屏幕的就卸载掉**。

```
IntersectionObserver(rootMargin: "500% 0px")
    │
    │  可视区域
    │  ┌──────────────┐
    │  │              │  ← 上下各扩展 5 页作为缓冲区
    │  │  当前可见页  │
    │  │              │
    │  └──────────────┘
    │
    ├─ 页面进入缓冲区 → load(container)
    │    └─ 创建 <img src="/api/page/left/5?t=时间戳">
    │       ├─ 加载成功 → 替换占位符
    │       └─ 加载失败 → 显示 "Page N (error)"
    │
    └─ 页面离开缓冲区 → unload(container)
         └─ 把 <img> 替换回占位符，释放内存
```

### 8.5 滚动同步（`scroll-sync.js`）

滚动左栏时，右栏自动跟到相同位置，实现左右对照阅读。

```
左栏 scroll 事件
  ├─ syncing 标志位防止递归循环
  └─ requestAnimationFrame(() => {
        右栏.scrollTop = 左栏.scrollTop;
        syncing = false;
     })
```

**当前页面检测**：计算每个页面容器与可视区域的交叠面积，面积占比最大的那一页就是当前页。

### 8.6 翻译前端流程（`translator.js` + `sse-client.js`）

```
translateCurrentPage(page=5, callbacks={onStageChange, onProgress, onFinish, onError})
  │
  ├─ POST /api/translate/5
  │    body: { prompt: "用户自定义提示词（可选）" }
  │
  └─ readSSEStream(response, eventHandler)
       │
       │  ReadableStream 逐块读取数据
       │  ├─ TextDecoder 解码字节
       │  ├─ 按 \n 分行
       │  ├─ 解析 data: {...} 行 → JSON.parse()
       │  └─ 调用对应的回调函数:
       │       progress → onProgress(percent)  → 更新进度条宽度
       │       stage → onStageChange(stage, label) → 更新状态文本
       │       finish → onFinish()  → 重新加载右栏图片
       │       error → onError(msg) → 显示错误信息
```

---

## 九、三条核心数据流（完整追踪）

### 9.1 打开 PDF 的完整流程

```
用户输入路径 "C:\doc.pdf"，点击 Open
  │
  ▼
[前端 app.js] openPdf()
  │  POST /api/open  body: {"path": "C:\doc.pdf"}
  ▼
[后端 routes.py] open_pdf()
  │  state.open_pdf("C:\doc.pdf", sha256)
  ▼
[后端 state.py] open_pdf()
  ├─ SHA256("C:\doc.pdf") = "a1b2c3d4..."
  ├─ mkdir cache/a1b2c3d4/
  ├─ 如果 right.pdf 不存在 → 复制原文件
  ├─ 打开 left_doc（原版）和 right_doc（译文档案）
  ├─ 读取页数、尺寸
  └─ 返回 {"page_count": 100, "page_height": 842, "page_width": 595, "hash": "a1b2c3d4..."}
  ▼
[前端 app.js] 收到响应
  ├─ 存储 pageCount=100, pageHeight=842, pageWidth=595
  ├─ 创建 100 对页面容器（左栏 + 右栏）
  ├─ 显示阅读界面
  ├─ 启动懒加载、滚动同步、页面检测
  └─ 加载已翻译状态
  ▼
IntersectionObserver 触发 → 视口内的页面开始请求图片
  │  GET /api/page/left/0   ← 原版第 1 页
  │  GET /api/page/right/0  ← 译文第 1 页
  ▼
[后端 routes.py] get_page("left", 0)
  │  state.render_page("left", 0, render_page, 200)
  ▼
[后端 state.py] render_page()
  ├─ 获取锁
  ├─ 取 left_doc
  ├─ doc[0].get_pixmap(dpi=200)
  ├─ 转为 PNG 字节
  ├─ 释放锁
  └─ return png_bytes
  ▼
[前端] <img> 标签加载 PNG 图片 → 显示在屏幕中
```

### 9.2 翻译一页的完整流程

```
用户翻到第 6 页，点击 Translate
  │
  ▼
[前端 app.js] onTranslateClick()
  ├─ isTranslating = true, 按钮变灰
  ├─ 进度条可见，初始 0%
  ├─ translateCurrentPage(5, callbacks)  ← 注意页码从 0 开始，第 6 页 = 索引 5
  │
  ▼
[前端 translator.js] translateCurrentPage()
  │  POST /api/translate/5  body: {"prompt": null}
  │  返回 text/event-stream (SSE)
  │
  ▼
[后端 routes.py] translate_page(5)
  ├─ 验证：文档已打开？页号在范围内？
  ├─ 创建临时目录 A（存单页 PDF）
  ├─ 创建输出目录 B（存 pdf2zh-next 输出）
  ├─ extract_single_page(left_doc, 5, A) → A/page.pdf
  ├─ resolve_glossary_paths(state) → ["cache/a1b2c3d4/cumulative_glossary.csv"]
  ├─ build_settings(page.pdf, ...)
  │    ├─ resolve_engine("deepseek") → DeepSeek 引擎配置
  │    ├─ build_engine_kwargs(spec) → {deepseek_api_key: "sk-...", deepseek_model: "deepseek-v4-flash"}
  │    └─ 组装 SettingsModel（含翻译参数、PDF 参数、引擎参数）
  ├─ 打包 GenerateContext
  └─ return Response(stream_with_context(sse_stream.generate(ctx)), mimetype="text/event-stream")
  │
  ▼
[后端 sse_stream.py] generate(ctx)
  │
  ├─ 阶段 1: run_translation() 启动 daemon 线程
  │   在 daemon 线程中:
  │     do_translate_async_stream(settings, page.pdf) ── pdf2zh-next (BabelDOC 管线)
  │     ├─ Step 1: 版面分析 (layout_analysis)
  │     │    用 CV 模型检测文本块、段落边界
  │     │    → SSE: progress:0, stage:layout_analysis
  │     ├─ Step 2: 术语提取 (automatic term extraction)
  │     │    调用 LLM 识别领域术语
  │     │    参考已有的 glossary.csv + cumulative_glossary.csv
  │     │    → 生成 auto_extracted_glossary.csv
  │     ├─ Step 3: 逐段翻译 (translating)
  │     │    对每个段落:
  │     │    ├─ 调用 LLM API（携带术语表 + 自定义 prompt）
  │     │    ├─ 将译文写回对应位置
  │     │    └─ → SSE: progress:25/50/75, stage:translating, stage_current:1/2/3
  │     └─ Step 4: 生成译文 PDF (generating_pdf)
  │          ├─ 生成纯译文 PDF (mono)
  │          ├─ 生成双语对照 PDF (dual)
  │          └─ → SSE: progress:95, stage:generating_pdf  + finish 事件
  │
  ├─ 阶段 2: 翻译完成后的处理（委托给 `translation_lifecycle.py`）
  │   ├─ finish_translation(translate_result, replace_page回调, glossary_cache_path, tmpdir, output_dir)
  │   │   ├─ replace_page(translated_pdf) ← 回调（页面号已在 routes.py 中预绑定）
  │   │   │   ├─ 获取锁
  │   │   │   ├─ 删除 right_doc 第 5 页（旧页）
  │   │   │   ├─ 插入翻译好的第 5 页
  │   │   │   ├─ 保存并原子替换 right.pdf
  │   │   │   ├─ 重新打开 right_doc
  │   │   │   ├─ _translated_pages.add(5)
  │   │   │   └─ 释放锁
  │   │   ├─ merge_after_translate(cumulative_glossary, auto_extracted_glossary)
  │   │   │   多数投票合并术语
  │   │   └─ 清理临时目录 A 和 B
  │   ├─ → SSE: progress:100, stage:finish
  │   └─ → SSE: type:finish
  │
  ▼
[前端 translator.js] readSSEStream 处理每个 SSE 事件
  ├─ progress:0   → 进度条 0%, 文本 "正在分析版面…"
  ├─ progress:25  → 进度条 25%, 文本 "正在翻译… 第 1/3 段"
  ├─ progress:50  → 进度条 50%, 文本 "正在翻译… 第 2/3 段"
  ├─ progress:75  → 进度条 75%, 文本 "正在翻译… 第 3/3 段"
  ├─ progress:95  → 进度条 95%, 文本 "正在生成译文…"
  └─ type:finish  → onFinish()
       ├─ 卸载右栏第 6 页的旧图片
       ├─ 重新加载右栏第 6 页（现在显示翻译后的内容）
       ├─ 添加 .translated 类标记
       ├─ 2 秒后自动隐藏进度条
       └─ isTranslating = false, 按钮恢复
```

### 9.3 滚动阅读的完整流程

```
用户滚动左栏
  │
  ▼
[前端 scroll-sync.js] setupScrollSync 监听
  ├─ 同步右栏位置:
  │   left.scrollTop 变化
  │   → requestAnimationFrame
  │   → right.scrollTop = left.scrollTop
  │
  └─ 检测当前页码:
      遍历左栏中所有 .page-container
      计算每个容器与可视区域的重叠面积
      覆盖率最高的 = 当前页
      → onPageChange(5) → toolbar 显示 "Page 6"
  │
  ▼
[前端 lazy-loader.js] IntersectionObserver 监听
  ├─ 页面进入"可视区域 ± 5 页缓冲"
  │   → loadPageImage(container)
  │     → 创建 <img src="/api/page/left/5?t=timestamp">
  │     → 图片加载完后替换占位符
  │
  └─ 页面离开缓冲区域
      → unloadPageImage(container)
        → 移除 <img>，恢复占位符，释放浏览器内存
```

---

## 十、关键架构决策（为什么这么做）

1. **不使用前端框架**：零构建成本，浏览器原生支持 ES Modules。缺点是代码规模大了以后组织会比较困难。

2. **服务端渲染 PDF**：PyMuPDF 在服务器上把 PDF 渲染成 PNG，浏览器只需要显示 `<img>` 标签。这样浏览器不需要理解 PDF 格式，兼容性好。

3. **SSE 代替 WebSocket**：SSE 是 HTTP 原生的单向推送，比 WebSocket 简单得多。翻译进度是单向的，不需要双向通信。

4. **SHA256 缓存隔离**：不同 PDF 对应不同的缓存目录。同一本 PDF 翻译过的页面自动保留，不需要手动保存/恢复。

5. **单线程锁保护 PDF 文档**：PyMuPDF 的 Document 对象不是线程安全的。用一个非重入锁保护所有操作，并且渲染时全程持锁防止并发冲突。

6. **原子文件替换**：`save → .tmp → os.replace()` 模式保证即使程序在写入中途崩溃，也不会留下损坏的文件。

7. **声明式引擎注册表**：用 `EngineSpec` 数据类 + `ENGINE_REGISTRY` 列表代替硬编码的 if/elif 判断。新增翻译引擎只需加一行配置。

8. **零开销调试系统**：所有调试函数以 `if config.DEBUG: return` 开头。生产环境下代码直接跳过，没有任何性能损失。

9. **模块化按职责拆分**：原 `services.py` 的 5 个函数按职责分入 4 个独立模块（`file_hash.py` / `engine_resolver.py` / `pdf_renderer.py` / `translation_lifecycle.py`）。`sse_stream.py` 的 `generate()` 回归纯 SSE 格式化，翻译后处理委托给 `translation_lifecycle.py`。`GenerateContext` 不再持有整个 `AppState`，只传递所需的最小接口。

---

## 十一、如何运行测试

```powershell
# 运行所有 106 个测试
pytest tests/ -v

# 只运行某个测试文件
pytest tests/test_state.py -v

# 运行代码风格检查
ruff check .
```

测试文件与源文件一一对应：`test_state.py` 测试 `state.py`，`test_routes.py` 测试 `routes.py`，依此类推。测试中使用 `conftest.py` 提供的夹具自动创建临时的测试 PDF 和 Flask 测试客户端。

---

## 十二、扩展指引：如果你想修改

| 你想做的事 | 改动哪些文件 |
|-----------|-------------|
| 更换 AI 翻译模型 | 修改 `config.toml` 中的 `[model]` 配置块 |
| 新增一个 AI 服务商 | 在 `config.py` 的 `ENGINE_REGISTRY` 中加一行 `EngineSpec` |
| 修改引擎参数映射逻辑 | 修改 `engine_resolver.py` |
| 修改 PDF 渲染方式 | 修改 `pdf_renderer.py` |
| 修改翻译完成后的后处理 | 修改 `translation_lifecycle.py` |
| 修改翻译阶段显示的文字 | 修改 `sse_stream.py` 中的 `STAGE_LABELS` 字典 |
| 调整界面样式 | 修改 `static/style.css` |
| 改变缓存的存储位置 | 修改 `config.toml` 中的 `pdf_reader.cache_dir` |
| 修改工具栏行为 | 修改 `static/app.js` |
| 改变翻译渲染分辨率 | 修改 `config.toml` 中的 `pdf_reader.dpi` |
| 开启调试日志 | `python app.py --debug` 或 `config.toml` 中 `[debug] enabled = true` |
| 修改术语表合并策略 | 修改 `glossary_merger.py` 中的 `merge_glossary_csvs()` |

---

> 最后更新：2026-06-22
