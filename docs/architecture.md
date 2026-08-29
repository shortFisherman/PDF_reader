# PDF Reader 当前架构

> 本文档只描述当前 HEAD 已经实现的系统。代码和测试高于本文档；发现不一致时，必须在同一变更中修正文档。项目意图见 [project.md](project.md)，未来方向见 [roadmap.md](roadmap.md)。

## 核验基线

- 核验日期：2026-08-27；代码基线 commit：`8e3b2e4`（`docs: plan long-term documentation system`）。
- 事实来源：CodeGraph（`codegraph explore` / `codegraph node`）输出、当前源码逐行核对、`requirements.lock`、`package.json`、`scripts/verify.ps1`、`.github/workflows/ci.yml` 和测试收集结果。
- 锁定版本：Python 3.12.8、Flask 3.1.3、PyMuPDF 1.25.2、pdf2zh-next 2.9.0、BabelDOC 0.6.2。
- 测试基线：`pytest --collect-only -q` 收集到 193 个 Python 测试；`package.json` 的 `test:frontend` 定义四个正式前端套件（UI copy、translator、zoom、alignment controller）。
- 基线说明：后续文档系统提交只修改文档，不改变实现；任何新的架构核对都应以当前源码、锁定文件和测试命令为准。

## 系统总览

本项目是一个运行在本机的单 Flask 应用：浏览器打开 `templates/index.html`，通过 HTTP 请求打开本地 PDF，以双栏（左原文、右译文）连续滚动阅读。PDF 页面由服务端用 PyMuPDF 渲染为 PNG 图片返回，浏览器不解析 PDF 本身，也没有文本层。

翻译由 `pdf2zh-next`（底层 BabelDOC）执行：路由层把单页或页码范围抽取为临时 PDF，`sse_stream` 通过 `translation_orchestrator` 的 daemon 线程 + asyncio 事件循环运行上游异步翻译，把进度事件经 `queue.Queue` 转成 SSE 流推给浏览器；完成后把译文页写回缓存中的 `right.pdf`，并把自动提取的术语并入累积术语表。

所有文档级状态集中在唯一的全局 `AppState` 中，由一把非重入锁保护。应用没有持久任务队列、任务注册表、暂停/取消 API 或重启续传状态。

## 技术栈与锁定版本

| 组件 | 版本/形态 | 作用 |
|---|---|---|
| Python | 3.12.8 | 运行时与测试环境 |
| Flask | 3.1.3 | 本地 HTTP 服务、路由、SSE 响应 |
| PyMuPDF | 1.25.2 | PDF 打开、单页/多页抽取、PNG 渲染、译文页替换 |
| pdf2zh-next | 2.9.0 | 全页版面翻译编排与事件流 |
| BabelDOC | 0.6.2 | 上游版面重建、字体处理与 PDF 生成底层 |
| 前端 | 原生 HTML/CSS/ES Modules | 无构建步骤，浏览器直接加载 |
| Node.js | 22（仅测试需要） | 运行四个前端测试套件 |
| ruff / pytest | 锁定在 `requirements.lock` | 代码检查与 Python 测试 |

## 仓库结构与文件职责

| 路径 | 职责 |
|---|---|
| `app.py` | 命令行参数、`create_app()` 装配 Flask 与全局 `AppState`、启动服务 |
| `config.py` | 读取 `config.toml`、定义 `EngineSpec`/`ENGINE_REGISTRY`、环境变量与默认值、`GLOSSARY_PATH` |
| `routes.py` | Blueprint：9 个 HTTP/SSE 端点与 JSON 404 处理器 |
| `state.py` | `AppState`：不可变文档会话身份、锁内翻译快照、左右文档、缓存路径、哈希、页数/尺寸、翻译页集合、阅读进度、非重入锁 |
| `file_hash.py` | `sha256()` 流式文件哈希 |
| `pdf_renderer.py` | `render_page()` 在锁内渲染页面为 PNG |
| `pdf_extraction.py` | `extract_single_page()` / `extract_pages()` 在锁内抽取临时输入 PDF |
| `engine_resolver.py` | `resolve_engine()`（未知 Provider 回退 openai_compatible）与 `build_engine_kwargs()` |
| `translation_settings.py` | `build_settings()` 组装 pdf2zh-next `SettingsModel` |
| `translation_orchestrator.py` | `TranslationStream`：daemon worker 线程 + asyncio 循环 + 事件队列 + 协作式取消；`run_translation()` 工厂 |
| `translation_coordinator.py` | 单槽 `TranslationCoordinator`：线程安全的 active job、任务身份、409 互斥与 finish/fail/cancel 幂等释放 |
| `sse_stream.py` | SSE 格式化、`generate()` / `generate_batch()`、`STAGE_LABELS`、worker 退出确认后的临时目录清理 |
| `translation_lifecycle.py` | `finish_translation()` / `merge_glossary_only()`：译文持久化与术语合并 |
| `glossary_service.py` | 累积术语路径解析与合并入口 |
| `glossary_merger.py` | 术语多数投票合并（BOM 安全读写） |
| `logging_config.py` | 根命名空间、控制台 + 轮转文件 handler、第三方降噪 |
| `debug_trace.py` | 调试会话、步骤/Token/术语合并日志（`config.DEBUG` 关闭时零开销） |
| `templates/index.html` | 唯一 HTML 页面：打开区、双栏、工具栏 |
| `static/app.js` | 前端入口与共享状态 |
| `static/modules/` | dom、lazy-loader、scroll-sync、alignment-controller、zoom、sse-client、stages、translator |
| `static/style.css` | 深色主题、双栏与缩放 CSS 变量 |
| `tests/` | 18 个 pytest 文件（229 用例）与前端 `.mjs` 测试运行器 |
| `scripts/verify.ps1` | 统一验证入口（lint、格式、Python 测试、前端测试） |
| `.github/workflows/ci.yml` | Windows + Python 3.12 + Node 22 的 CI |
| `docs/`、`docs/archive/`、`docs/reports/` | 常青文档、历史归档与上游研究资料 |

## 运行时进程、线程、队列与锁

- 一个 Flask 进程持有唯一全局 `AppState`（`app.config["app_state"]`），同一时刻服务一个打开的文档。每次成功打开（包括再次打开同一路径）都会生成新的随机 `document_id`；关闭或切换文档立即使旧身份失效。
- `AppState` 内部是 `threading.Lock`（非重入），打开/渲染/抽取/替换/术语合并/阅读进度写入全部在锁内执行；传给 state 的回调（渲染、抽取、术语合并）不得再次进入 `AppState`。`translation_snapshot()` 在锁内一次性返回冻结的 `document_id`、PDF 哈希、页数和术语缓存路径。
- 全局 `TranslationCoordinator` 使用独立的 `threading.Lock` 保护单个 `active_job`。`start(document_id, page_indices)` 原子创建含 UUID `job_id`、文档身份、页码 tuple、UTC 创建时间和 active 状态的冻结任务；已有任务时抛 `TranslationBusyError`。`finish(job_id)` / `fail(job_id)` 只释放匹配任务，重复或迟到释放不会影响后续任务。
- 每个翻译请求由 `TranslationStream`（`run_translation()` 工厂返回）启动一个 daemon worker 线程；该线程创建独立 asyncio 事件循环，`async for` 消费 `do_translate_async_stream(settings, pdf_path)`，把事件放入 `queue.Queue`。线程总是以入队内部 `_done` 标记结束，`cancel()` 在事件边界之间做协作式取消检查，`join(timeout)` 与 `is_alive` 暴露真实 worker 状态。
- 同步 SSE 生成器从队列取事件并逐条 yield；队列空闲 1 秒时 yield 空串作为心跳，收到 `_done` 后 `__next__` 先 `join(timeout=30.0)` 确认线程退出（join timeout 记 WARNING），再结束迭代或抛 `TranslationError`。
- 上游 pdf2zh-next 内部可能以子进程方式运行 BabelDOC 的版面/PDF 生成环节；本项目自身不直接管理该子进程的生命周期，也没有持久任务队列、任务注册表、暂停/取消接口或重启续传状态。协作式取消只作用于事件边界；不响应取消的上游环节允许自然结束，其结果被丢弃。

## 启动与 Flask 应用装配

1. `python app.py`：`argparse` 解析 `--debug`（显式提供时覆盖 `config.DEBUG`）。
2. `create_app()` 调用 `logging_config.setup_logging(config.DEBUG)`，输出启动摘要（provider/model/lang/cache_dir/dpi/debug，不含 api_key）。
3. 创建 `Flask(__name__)`，装配全局 `AppState(config.CACHE_DIR)` 与 `TranslationCoordinator()`，导入并注册 `routes.register_routes`。
4. `__main__` 从 `config.toml` 的 `[server]` 读取 host/port/debug（默认 `127.0.0.1:5000`、debug 开启），调用 `app.run()`；`app.run()` 返回或异常退出时检查协调器，仍有 active job 则记录 WARNING（worker 可能成为孤儿）。

## 配置加载与 Provider 映射

- `config.py` 读取仓库根目录 `config.toml`；文件不存在时配置回退为空字典，不在导入期抛错。
- 环境变量覆盖：只有 `MODEL_API_KEY`（优先级高于 `model.api_key`）；其余模型字段全部来自 `config.toml`。
- 默认值：provider=`openai_compatible`、dpi=200、cache_dir=`cache`（`Path.resolve()`）、lang_in=`en`、lang_out=`zh`。
- 必填校验延迟到 `engine_resolver.resolve_engine()` 入口：缺少 `model.model`、缺少 API Key 或 API Key 为示例值时抛错。
- `GLOSSARY_PATH` 硬编码为仓库根 `docs/glossary.csv`，必须保持该路径。
- `ENGINE_REGISTRY` 用声明式 `EngineSpec` 注册 10 个 Provider，顺序为：`deepseek`、`zhipu`、`siliconflow`、`aliyun`、`gemini`、`groq`、`grok`、`modelscope`、`openai`、`openai_compatible`。
- 未知 Provider 在通过必填校验后回退到 `openai_compatible`。
- `translation_settings.build_settings()`：设置 `lang_in`/`lang_out`，`ignore_cache=True`，`save_auto_extracted_glossary=True`；有自定义提示词时写入 `custom_system_prompt`；把非空的 `docs/glossary.csv` 与累积术语路径拼为 `glossaries`；`output` 由生成器设置；PDF 参数为 `pages`、`no_dual=True`、`only_include_translated_page=True`、`watermark_output_mode="no_watermark"`。

## 打开 PDF 与页面渲染

1. 浏览器 `openPdf()` 把本地绝对路径 POST 到 `/api/open`。
2. 路由校验 `os.path.isfile`；若协调器存在 active job 则返回 HTTP 409 / `translation_busy`，否则调用 `state.open_pdf(path, sha256)`。
3. `AppState.open_pdf()` 在锁内：关闭旧文档并使旧身份失效 → 计算 SHA256 → 建 `cache/<hash>/` → `right.pdf` 不存在时复制源文件 → 打开左右 PyMuPDF 文档 → 生成新 `document_id` → 记录页数、首页尺寸与哈希 → 读取 `reading_progress.json`。
4. 响应返回 `page_count`、`page_height`、`page_width`、`hash`、`document_id`、`saved_page`。
5. 前端按页数创建左右页面容器，经懒加载从 `GET /api/page/<side>/<page>` 取 PNG；`state.render_page()` 在锁内调用 `pdf_renderer.render_page()`（`get_pixmap(dpi)` → PNG），越界返回 404，非法 side 返回 400。

## 单页翻译链

1. `POST /api/translate/<page>`（零基页码）校验文档已打开、页码在范围内，解析累积术语路径，`build_settings()` 组装参数。
2. 路由先取得冻结的文档快照，再调用协调器 `start(document_id, [page])` 原子占用任务槽；已有任务时返回 HTTP 409，且不构造 SSE 生成器、不创建临时目录或后台线程。接受后构造带 `job_id` 和 finish/fail 回调的 `GenerateContext`；抽取、`replace_page` 与术语合并闭包都捕获快照中的 `document_id`。
3. `generate()` 创建临时抽取目录与 cache 内输出目录，在 `debug_trace.debug_session` 内先 `extract_single_page()` 抽取单页 PDF。
4. `run_translation()` 启动 daemon worker 线程运行上游异步翻译；`format_sse_event()` 把 `progress_start`/`progress_update`/`finish`/`error` 映射为 SSE；非 dict 心跳直接 yield 空串。
5. 收到上游 `finish` 事件后保留 `translate_result` 与 token 用量，随后调用 `finish_translation()`：优先 `mono_pdf_path`，缺失时回退 `dual_pdf_path`，再调 `AppState.replace_page(..., expected_document_id)` 写入译文，并通过 `AppState.merge_glossary(..., expected_document_id)` 把自动术语并入累计文件。
6. `replace_page()` 在锁内先比较预期身份，再执行：打开译文 PDF → 删除右文档对应页 → `insert_pdf` → 保存 `.tmp` → 关闭源/右文档 → `os.replace` 原子替换 → 重开右文档 → 标记已翻译页。`merge_glossary()` 同样在锁内完成身份比较与合并回调；失配时两条边界都抛出 `StaleDocumentError`、记录 `[stale-result]` 警告且不修改当前文档。
7. 生成器最后发 `progress:100/finish` SSE；成功路径调用 `finish(job_id)`，上游错误、普通异常调用 `fail(job_id)`，消费者断开（GeneratorExit）调用 `cancel(job_id)`。所有退出路径都经 `finally`：先向 worker 请求协作式取消并 `join(timeout=30.0)`，只在 worker 确认退出后清理临时目录（join timeout 时保留目录并记 WARNING），再幂等释放任务；Response close 另有未开始迭代时的兜底释放。

## 范围与全文翻译链

1. `POST /api/translate-batch` 接收一基闭区间 `from`/`to`，校验均为整数、≥1、不越界且 `from ≤ to`。
2. 路由换算零基 `page_indices`，使用同一协调器原子占槽，再从冻结快照构造带 `job_id` 的 `GenerateBatchContext`（抽取、`replace_pages` 与术语合并闭包都捕获 `document_id`），`pages` 参数按页数设为 `"1"` 或 `"1-N"`。
3. `generate_batch()` 先发 `batch_info`，再抽取多页 PDF 一次性送入 `run_translation()`，之后逐事件转发 SSE。
4. 完成后选 `mono_pdf_path`（回退 `dual_pdf_path`）调 `AppState.replace_pages(..., expected_document_id)` 按序替换范围页，并只做一次受同一身份保护的 `merge_glossary_only()`。
5. 全文翻译是浏览器行为：`onFullTranslateClick()` 调同一批处理端点提交 `1..pageCount`，不存在独立的全文章节端点。

## 状态、缓存与持久化

| 路径/数据 | 说明 |
|---|---|
| `cache/<hash>/right.pdf` | 每文档持久化的译文工作副本，首次打开复制源文件，翻译后原子替换 |
| `cache/<hash>/cumulative_glossary.csv` | 每文档累积术语表，翻译后多数投票合并写回 |
| `cache/<hash>/reading_progress.json` | 零基阅读页码，`.tmp` + `os.replace` 原子写；损坏/越界时安全降级 |
| `logs/pdf_reader.log` | `logging_config` 配置的轮转应用日志（5MB × 5，utf-8） |
| `cache/<hash>/debug_trace.log` | 仅 debug 模式且存在缓存路径时，由 `debug_session` 创建并在会话开始前轮转 |
| `docs/glossary.csv` | 仓库级手动术语表，`config.py` 硬编码读取，非空时参与每次翻译 |

`AppState` 另维护当前 `_document_id`、`_translated_pages`（`translated_pages` 冻结集合）与左右 PyMuPDF 文档对象；`open_pdf` 会使旧身份失效并清空旧文档与翻译页集合。SSE 断开后任务先被协作式取消；迟到任务若仍自然结束，其结果被丢弃（不进入写回），抽取、PDF 提交与术语提交的写回边界仍受身份校验约束。

## 前端模块与浏览器状态

`static/app.js` 是浏览器入口，持有 `pageCount`、`pageHeight`、`pageWidth`、`currentPage`、`isTranslating`、`promptVisible`、`statusTimer`，以及 `els`、`io`（懒加载）、`settle`（滚动闸门）、`zoomInst`、`alignController`、`progressCleanup` 等实例。

| 模块 | 职责 |
|---|---|
| `dom.js` | DOM 元素缓存、页面容器创建、高度计算 |
| `lazy-loader.js` | IntersectionObserver 候选标记 + settle 扫描；视口 ±2 页加载、离开 10 页回收 |
| `scroll-sync.js` | 仅保留 `createSettleGate`（150ms）与 `setupPageDetection`；`setupScrollSync()` 为已废弃空壳 |
| `alignment-controller.js` | 当前唯一双栏对齐所有者：`(pageIndex, intraPageOffsetPx)` 目标、横向按比例同步、抑制回灌 |
| `zoom.js` | Ctrl+滚轮缩放，范围 0.25–2.2，步进 0.1，重置后通知 alignment controller |
| `sse-client.js` | `readSSEStream()` 纯解析（TextDecoder + 行缓冲） |
| `stages.js` | `GET /api/stages` 拉取阶段标签，失败回退内置副本 |
| `translator.js` | `translateCurrentPage()` / `translateBatch()`：fetch + SSE 回调编排 |

对齐事实：打开 PDF 时 `createAlignmentController` 安装滚动监听；翻译图片加载完成、Ctrl+滚轮/重置缩放、`scrollToPage` 均显式走 controller 的 `onImageLoaded`/`onZoomChange`/`setLockTarget+realign`。前端 `isTranslating` 只阻止同一浏览器页内的重叠操作，不是服务端锁。

## HTTP 与 SSE 接口

| 接口 | 作用 |
|---|---|
| `GET /` | 渲染 `templates/index.html` |
| `POST /api/open` | 无 active job 时打开本地 PDF，返回页数、尺寸、哈希、文档身份与保存页码 |
| `POST /api/reading-progress` | 持久化当前零基页码 |
| `GET /api/page/<side>/<page>` | 返回左/右页 PNG |
| `GET /api/page-count/<side>` | 返回已打开文档页数 |
| `POST /api/translate/<page>` | 单页翻译，SSE 事件流 |
| `POST /api/translate-batch` | 一基闭区间批量翻译，SSE 事件流 |
| `GET /api/translated-pages` | 返回已翻译零基页码列表 |
| `GET /api/stages` | 返回阶段标签映射 |

Blueprint 级 `@bp.app_errorhandler(404)` 返回 JSON，不属于第 10 个路由。SSE 事件类型包括 `batch_info`、`progress`（含 stage/stage_current/stage_total）、`error`、`finish`，以及空行心跳。

互斥响应：active job 存在时，新的单页/批量翻译请求以及 `/api/open` 返回 HTTP 409，JSON 至少包含 `error`（明确中文提示）、稳定 `code="translation_busy"` 和 `active_job_id`。前端已有的非 2xx JSON 错误路径会直接显示服务端提示。

## 日志与错误传播

根命名空间为 `pdf_reader`，模块命名空间：`pdf_reader.app`、`pdf_reader.state`、`pdf_reader.translate`、`pdf_reader.lifecycle`、`pdf_reader.glossary`、`pdf_reader.routes`、`pdf_reader.render`、`pdf_reader.extract`、`pdf_reader.engine`、`pdf_reader.debug_trace`。

| 级别 | 用途 |
|---|---|
| ERROR | 请求级失败，带 `exc_info` |
| WARNING | 可恢复降级（超时、文件缺失、术语合并失败） |
| INFO | 流程里程碑（打开、翻译起止、替换、合并完成、启动摘要） |
| DEBUG | 高频/细节（渲染、抽取、token 用量、端点入口） |

翻译流日志以 `[job=<uuid>]` 关联任务，并继续保留 `[page=N]` 或 `[batch=from-to]` 前缀；协调器 start/finish/fail、SSE、后台线程、生命周期、Token 与术语调试记录都携带同一 `job_id`。日志中不输出 api_key 原值。`logging_config.setup_logging()` 幂等，创建控制台 + `RotatingFileHandler`（5MB × 5），debug 关闭时 `werkzeug`/`pdf2zh_next`/`babeldoc` 抬到 WARNING，debug 开启时降到 DEBUG。

错误传播：`TranslationError` 与普通异常都被 `generate`/`generate_batch` 捕获并输出 SSE `error` 事件，同时记录上下文日志；临时目录只有在 worker 线程确认退出后才会在 `finally` 中清理（join timeout 时保留并记 WARNING）。

## 测试、CI 与验证入口

`requirements.txt` 只声明直接运行依赖，`requirements-dev.txt` 在运行依赖之上声明 pytest 与 Ruff；`requirements.lock` 是 README、CI 和本地安装共同使用的唯一锁文件，由 Python 3.12 与 pip-tools 7.6.1 从开发依赖入口生成。锁文件不包含 editable、本机路径或 `file:///` 来源。

统一入口 `scripts/verify.ps1`，顺序为：Ruff lint → Ruff format check → `pytest -q`（229 个 Python 测试）→ `npm test`（四个前端套件：`test:ui-copy`、`test:translator`、`test:zoom`、`run-alignment-controller-tests.mjs`）。脚本接受 `-PythonExecutable` 显式指定验证环境；未指定时优先使用仓库 `venv`，不存在时回退 PATH 中的 `python`。

CI（`.github/workflows/ci.yml`）在 `windows-latest` 上安装 Python 3.12 依赖（`requirements.lock`），执行 `import flask, pymupdf, pdf2zh_next` 冒烟检查，安装 Node 22 测试依赖（`npm ci`），再执行同一 `scripts/verify.ps1`。`tests/README.md` 说明正式测试与历史诊断脚本的区别。

## 当前技术约束与已确认风险

以下只记录当前事实，不构成修复方案或目标设计。

1. **单进程/全局状态。** 服务端只有一个全局 `AppState`，同一时刻只面向一个本地用户、一份打开的文档；没有多用户或并行文档隔离。
2. **SSE 断开有协作式取消但无强制终止。** 消费者断开后，`generate`/`generate_batch` 请求协作式取消并等待 worker 退出（join timeout 30s），临时目录只在 worker 确认退出后删除；join timeout 时目录保留并记 WARNING。不响应取消的上游环节（含 BabelDOC 子进程）仍会运行到自然结束，其结果被丢弃，没有强制 kill 接口。
3. **术语表写入尚非原子提交。** 单任务协调器已消除同进程并发合并，`document_id` 已阻止跨文档迟到合并，但累计 CSV 仍直接覆盖，写入失败时可能损坏最后有效版本。
4. **替换失败无恢复事务。** `replace_page`/`replace_pages` 在原子替换前已关闭源/右文档；后续步骤失败时没有文档化的恢复事务。
5. **PNG 无文本层。** 页面以图片显示，没有文本选择、搜索、复制、高亮、批注、目录、内部链接或 OCR 流程。
6. **无队列/暂停/取消/重启续传。** 不存在持久任务队列、暂停、取消、重试队列、进度恢复或进程重启后的翻译续传。

## 上游与历史参考

- 项目长期意图：[project.md](project.md)；未来方向与开放问题：[roadmap.md](roadmap.md)。
- 上游接口研究：[pdf2zh-next-development-guide.md](pdf2zh-next-development-guide.md) 与 `docs/reports/` 下两份报告，均按各自顶部标注的版本适用范围阅读。
- 历史系统描述：`docs/archive/`、`docs/superpowers/`、`openspec/` 与 `CHANGELOG.md`，只用于追溯。

归档与版本特定的上游资料是辅助上下文，不是当前实现的事实源；本文档与代码、测试冲突时，以代码和测试为准。
