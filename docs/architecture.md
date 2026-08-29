# PDF Reader 当前架构

> 本文档只描述当前 HEAD 已经实现的系统。代码和测试高于本文档；发现不一致时，必须在同一变更中修正文档。项目意图见 [project.md](project.md)，未来方向见 [roadmap.md](roadmap.md)。

## 核验基线

- 核验日期：2026-08-30；代码基线 commit：`6f6e79a`（P3-03）；本文件与 P3-05 实现提交同步更新（P3-05 提交 hash 由收口 Agent 在工程清单完成记录中补充）。
- 事实来源：CodeGraph（`codegraph explore` / `codegraph node`）输出、当前源码逐行核对、`requirements.lock`、`package.json`、`scripts/verify.ps1`、`.github/workflows/ci.yml` 和测试收集结果。
- 锁定版本：Python 3.12.8、Flask 3.1.3、PyMuPDF 1.25.2、pdf2zh-next 2.9.0、BabelDOC 0.6.2。
- 测试基线：`pytest --collect-only -q` 收集到 545 个 Python 测试；`package.json` 的 `test:frontend` 定义六个正式前端套件（UI copy、error-safety、translation-ui、translator、zoom、alignment controller）。
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
| Node.js | >=22（仅测试需要，CI 固定 22） | 运行六个前端测试套件 |
| ruff / pytest | 锁定在 `requirements.lock` | 代码检查与 Python 测试 |

## 仓库结构与文件职责

| 路径 | 职责 |
|---|---|
| `src/pdf_reader/app.py` | 启动边界 `main(argv)`、`create_app()` 装配 Flask 与全局 `AppState`、启动服务；`src/pdf_reader/__main__.py` 提供 `python -m pdf_reader` 入口 |
| `src/pdf_reader/cache_ops.py` | 缓存分类、只读统计与孤儿翻译临时工作区清理：固定前缀/标记校验、Windows 安全 PID 存活探测、dry-run 清理边界与启动恢复 |
| `pyproject.toml` | P2-01/P2-04 可安装包与依赖契约：setuptools src 布局、`project.dependencies` 唯一直接依赖声明、`project.optional-dependencies.dev`（pytest/Ruff/coverage/mypy/pip-tools） |
| `start.bat` | Windows 启动入口：检查并激活 `.\venv`、检测 5000 端口占用（只报告不杀进程）、运行 `python -m pdf_reader` |
| `src/pdf_reader/config.py` | 读取 `config.toml`、定义 `EngineSpec`/`ENGINE_REGISTRY`、环境变量与默认值、`GLOSSARY_PATH` |
| `src/pdf_reader/paths.py` | 统一路径策略：`PROJECT_ROOT`/`DATA_ROOT` 解析、config/glossary/templates/static/logs/cache 位置、相对缓存与绝对缓存语义 |
| `src/pdf_reader/task_logging.py` | 集中任务日志上下文：不可变 `TaskContext`、`contextvars` 传播、统一前缀/截断/1-based 页码、生命周期状态、`SafeFormatter` 脱敏 |
| `src/pdf_reader/routes.py` | Blueprint：9 个 HTTP/SSE 端点；统一 JSON 错误契约（`code`+`error`）、404/HTTPException/500 处理器与 409 `translation_busy` |
| `src/pdf_reader/state.py` | `AppState`：不可变文档会话身份、锁内翻译快照、左右文档、缓存路径、哈希、页数/尺寸、翻译页集合、阅读进度、非重入锁 |
| `scripts/cache_manage.py` | 缓存只读统计与孤儿临时工作区清理 CLI：`stats`（只读/可 `--json`）、`orphans`、`clean`（默认 dry-run，`--yes` 才删除） |
| `src/pdf_reader/file_hash.py` | `sha256()` 流式文件哈希 |
| `src/pdf_reader/pdf_renderer.py` | `render_page()` 在锁内渲染页面为 PNG |
| `src/pdf_reader/pdf_extraction.py` | `extract_single_page()` / `extract_pages()` 在锁内抽取临时输入 PDF |
| `src/pdf_reader/engine_resolver.py` | `resolve_engine()`（未知 Provider 回退 openai_compatible）与 `build_engine_kwargs()` |
| `src/pdf_reader/translation_settings.py` | `build_settings()` 组装 pdf2zh-next `SettingsModel` |
| `src/pdf_reader/translation_orchestrator.py` | `TranslationStream`：daemon worker 线程 + asyncio 循环 + 事件队列 + 协作式取消；`run_translation()` 工厂 |
| `src/pdf_reader/translation_coordinator.py` | 单槽 `TranslationCoordinator`：线程安全的 active job、任务身份、409 互斥与 finish/fail/cancel 幂等释放 |
| `src/pdf_reader/sse_stream.py` | SSE 格式化、`generate()` / `generate_batch()`、`STAGE_LABELS`、worker 退出确认后的临时目录清理 |
| `src/pdf_reader/translation_lifecycle.py` | `finish_translation()` / `merge_glossary_only()`：译文持久化与术语合并 |
| `src/pdf_reader/glossary_service.py` | 累积术语路径解析与合并入口 |
| `src/pdf_reader/glossary_merger.py` | 术语多数投票合并：模块级互斥锁 + 同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交（BOM 安全读写） |
| `src/pdf_reader/logging_config.py` | 根命名空间、控制台 + 轮转文件 handler、第三方降噪 |
| `src/pdf_reader/debug_trace.py` | 调试会话、步骤/Token/术语合并日志（`config.DEBUG` 关闭时零开销） |
| `templates/index.html` | 唯一 HTML 页面：打开区、双栏、工具栏 |
| `static/app.js` | 前端入口与共享状态 |
| `static/modules/` | dom、lazy-loader、scroll-sync、alignment-controller、zoom、sse-client、stages、translator、translation-ui-controller、reader-session |
| `static/style.css` | 深色主题、双栏与缩放 CSS 变量 |
| `tests/` | 28 个 pytest 文件（含 P2-07 路径、P2-06 任务日志、P2-01 包布局与 P2-03 契约用例）与前端 `.mjs` 测试运行器 |
| `scripts/verify.ps1` | 统一验证入口（lint、格式、Python 测试、前端测试） |
| `scripts/secret_scan.py` | 高可信密钥扫描：只扫 Git 跟踪内容，占位示例放行，不输出 secret 值 |
| `.github/workflows/ci.yml` | Windows + Python 3.12 + Node 22 的 CI |
| `.github/dependabot.yml` | pip/npm 月度依赖升级 PR |
| `docs/governance/` | 工具目录治理、依赖升级流程与许可证核验基线（非法律意见） |
| `docs/`、`docs/archive/`、`docs/reports/` | 常青文档、历史归档与上游研究资料 |

## 运行时进程、线程、队列与锁

- 一个 Flask 进程持有唯一全局 `AppState`（`app.config["app_state"]`），同一时刻服务一个打开的文档。每次成功打开（包括再次打开同一路径）都会生成新的随机 `document_id`；关闭或切换文档立即使旧身份失效。
- `AppState` 内部是 `threading.Lock`（非重入），打开/渲染/抽取/替换/术语合并/阅读进度写入全部在锁内执行；传给 state 的回调（渲染、抽取、术语合并）不得再次进入 `AppState`。`translation_snapshot()` 在锁内一次性返回冻结的 `document_id`、PDF 哈希、页数和术语缓存路径。
- 术语合并的读—合并—写全过程另由 `glossary_merger` 的模块级互斥锁保护：即使绕过 `AppState` 直接调用 `merge_glossary_csvs`，两个并发合并也不会截断累计 CSV 或静默丢更新。
- 全局 `TranslationCoordinator` 使用独立的 `threading.Lock` 保护单个 `active_job`。`start(document_id, page_indices)` 原子创建含 UUID `job_id`、文档身份、页码 tuple、UTC 创建时间和 active 状态的冻结任务；已有任务时抛 `TranslationBusyError`；进入关闭流程后抛 `CoordinatorShutdownError`（路由转为 409 `translation_busy`，无 `active_job_id`）。`finish(job_id)` / `fail(job_id)` 只释放匹配任务，重复或迟到释放不会影响后续任务。
- SSE 生成器通过 `register_stream(job_id, stream)` / `unregister_stream(job_id)` 把真实 worker 登记到协调器；`shutdown(timeout)` 先置关闭标志拒绝新任务，再对已登记流请求协作式取消并按剩余时间有界 `join`，随后等待 active job 释放，返回 `ShutdownReport(outcome="no_active_job"|"completed"|"timeout", active_job_id, worker_joined)`。`shutdown` 不 kill 线程；worker 不响应取消时任务槽保留、临时目录保留，重复调用幂等且结果一致。
- 每个翻译请求由 `TranslationStream`（`run_translation()` 工厂返回）启动一个 daemon worker 线程；该线程创建独立 asyncio 事件循环，`async for` 消费 `do_translate_async_stream(settings, pdf_path)`，把事件放入 `queue.Queue`。线程总是以入队内部 `_done` 标记结束，`cancel()` 在事件边界之间做协作式取消检查，`join(timeout)` 与 `is_alive` 暴露真实 worker 状态。
- 同步 SSE 生成器从队列取事件并逐条 yield；队列空闲 1 秒时 yield 空串作为心跳，收到 `_done` 后 `__next__` 先 `join(timeout=30.0)` 确认线程退出（join timeout 记 WARNING），再结束迭代或抛 `TranslationError`。
- 上游 pdf2zh-next 内部可能以子进程方式运行 BabelDOC 的版面/PDF 生成环节；本项目自身不直接管理该子进程的生命周期，也没有持久任务队列、任务注册表、暂停/取消接口或重启续传状态。协作式取消只作用于事件边界；不响应取消的上游环节允许自然结束，其结果被丢弃。

## 启动与 Flask 应用装配

1. `python -m pdf_reader` 进入 `app.main(argv=None)`：模块导入不解析 CLI、不修改 `config.DEBUG`；CLI 解析只发生在该启动边界内。`--debug` 与 `--no-debug` 互斥。
2. `config.resolve_server_config(cli_debug=...)` 按优先级 CLI `--debug`/`--no-debug` > 环境变量 `PDF_READER_DEBUG` > `[server].debug` > 默认 `false` 解析，返回 frozen `ServerConfig(host, port, debug)`；`use_reloader` 派生为与 `debug` 相同的值（debug 开 → Flask debugger+reloader 开，关 → 两者显式关闭）。
3. `main` 把同一个解析结果写入 `config.DEBUG`（供 `debug_trace` 等消费），再调用 `config.validate_startup_requirements()` 统一校验 `[model]`/`[pdf_reader]`/`[translation]` 的 table 与核心字段类型；缺少 `model.model`、API Key 或 API Key 为示例值时抛 `ConfigError`，main 打印 `ERROR:` 并以退出码 2 结束，不启动服务器。
4. `create_app(run_cfg)` 使用 `run_cfg.debug` 调用 `logging_config.setup_logging(...)`，输出启动摘要（provider/model/lang/cache_dir/dpi/debug，不含 api_key）。
5. 创建 `Flask(__name__)` 并显式传入 `template_folder=PROJECT_ROOT/templates`、`static_folder=PROJECT_ROOT/static`（由 `src/pdf_reader/paths.py` 解析），装配全局 `AppState(config.CACHE_DIR)` 与 `TranslationCoordinator()`，导入并注册 `pdf_reader.routes.register_routes`。
6. `main` 在 `create_app`（日志已就绪）之后调用 `cache_ops.recover_orphan_temp_workspaces(settings.cache_dir)`：清理上次崩溃/超时退出遗留的、可验证归属（固定前缀 + 有效标记 + 非链接 + PID 已不存活）的翻译临时工作区；未知/无标记/损坏标记/链接路径/PID 仍存活的目录一律保守保留。清理数量与保留分类写入 INFO/WARNING 日志。
7. `app.run(host=..., port=..., debug=..., use_reloader=...)` 显式传入全部四个参数，默认 `debug=False, use_reloader=False`；`app.run()` 返回或异常退出时先调用 `coordinator.shutdown(timeout=10.0)` 做有界关闭：请求协作式取消并等待 worker 与 active job，按 `no_active_job`（INFO）/ `completed`（INFO）/ `timeout`（WARNING，任务与临时目录保留供下次启动恢复）记录日志，worker 未确认退出时追加 WARNING；随后 `app_state.close()` 幂等关闭并释放左右 PyMuPDF 句柄、清空状态（即使 `shutdown` 抛异常也会执行）。
8. 配置错误路径：TOML 语法错误在配置导入时被捕获（`config._CONFIG_LOAD_ERROR`），首次解析配置时抛 `ConfigError`；`[server]` 类型/范围错误与 `PDF_READER_DEBUG` 非法值同样由 `resolve_server_config` 抛 `ConfigError`；`--debug`/`--no-debug` 互斥由 argparse 报错。所有路径都在启动服务器前以非零状态退出。
- `start.bat` 是 Windows 便捷启动入口：切换到仓库根目录后先检查 `.\venv\Scripts\python.exe`（缺失时打印创建/安装命令并不为零退出），再用 `netstat -ano -p tcp | findstr "LISTENING" | findstr ":5000 "` 检测端口占用；若 5000 已被监听，打印占用 PID 与 `netstat`/`tasklist` 排查命令并以非零状态退出，绝不执行 `taskkill`/`Stop-Process` 等终止命令；无冲突时 `call .\venv\Scripts\activate.bat` 激活既有虚拟环境并运行 `python -m pdf_reader`。

## 配置加载与 Provider 映射

- `config.py` 经 `src/pdf_reader/paths.py` 读取 `PROJECT_ROOT/config.toml`（`CONFIG_PATH`）。`PROJECT_ROOT` 默认由 `paths.py` 从 `src/pdf_reader/` 的模块位置向上查找 `config.example.toml` 标记得到（自动回到仓库根），也可用环境变量 `PDF_READER_ROOT` 显式覆盖；文件不存在时配置回退为空字典，不在导入期抛错。
- 导入安全：`_section`/`_string` 安全提取，非 table section 与非字符串字段在导入期使用安全默认值（不会因 `AttributeError`/`TypeError` 崩溃）；原始 `CONFIG` 保留供启动校验。
- 环境变量覆盖：`MODEL_API_KEY`（优先级高于 `model.api_key`）；`PDF_READER_DEBUG` 是 debug 优先级中间层，只接受 `true/false/1/0/on/off/yes/no`（不区分大小写、忽略首尾空白），非法值启动时报错（即使 CLI 显式覆盖也会 fail-fast）。
- `[server]` 严格校验：必须是 table；`host` 非空字符串；`port` 是 1–65535 的 int（布尔值不算）；`debug` 必须为真布尔值。旧的 `[debug].enabled` 键已停止使用。
- 默认值：provider=`openai_compatible`、dpi=200、cache_dir=`cache`、lang_in=`en`、lang_out=`zh`。相对 `cache_dir` 以 `DATA_ROOT`（默认等于 `PROJECT_ROOT`）为基准解析并 `resolve()`；绝对 `cache_dir` 保持绝对，不被重写。`DATA_ROOT` 可用环境变量 `PDF_READER_DATA_ROOT` 覆盖。
- 统一校验 `validate_startup_requirements()`（`app.main` 启动前调用）：`[model]`、`[pdf_reader]`、`[translation]` 存在则必须为 table；`model.provider`/`model.model`/`model.api_key`/`model.base_url`（若有）必须是非空字符串（int/bool/list 拒绝，不泄漏密钥）；`pdf_reader.dpi` 必须为正整数（bool 不算）、`cache_dir` 必须为非空字符串；`translation.lang_in/lang_out` 必须为非空字符串。
- `MODEL_API_KEY` 环境值合法（非空且非示例占位值）时覆盖文件中无效的 `api_key`，但 `[model]` 段本身仍必须是 table；`engine_resolver.resolve_engine()` 入口仍保留同样的延迟必填校验。
- `GLOSSARY_PATH = PROJECT_ROOT/docs/glossary.csv`（由 `src/pdf_reader/paths.py` 派生），必须保持该路径；模块位于 `src/pdf_reader/` 时不因 `__file__` 变化而改变。
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
6. `replace_page()` 在锁内先比较预期身份，再经 `_commit_replacement()` 事务提交：所有页修改在从磁盘已提交的 `right.pdf` 重开的工作副本上完成 → 保存 `.tmp` → 关闭译文/工作文档 → 关闭旧右文档句柄 → `os.replace` 原子替换 → 重开右文档 → 更新翻译页集合。磁盘提交成功前不替换内存句柄和 `_translated_pages`；任意失败（open/delete/insert/save/close/`os.replace`）都会清理 `.tmp`、关闭泄漏句柄、恢复或保留可渲染的文档句柄，旧 `right.pdf` 保持不变。`merge_glossary()` 同样在锁内完成身份比较与合并回调；失配时两条边界都抛出 `StaleDocumentError`、记录 `[stale-result]` 警告且不修改当前文档。
7. 当前部分提交语义（由 `tests/test_system_concurrency_failure.py` 固定）：`finish_translation()` 严格按「PDF 提交 → 术语合并」顺序执行两个独立文件提交。PDF 提交（`replace_page`）失败时异常向上传播，术语合并不执行，任务以 failed 释放并输出 SSE `error`；术语合并失败被 `merge_after_translate` 捕获并记录 WARNING，不向上传播——此时 PDF 提交保留、旧术语表不变，任务仍以 finished 释放并输出 SSE `finish`。两者是同一任务内两个独立文件的部分提交，不存在跨 `right.pdf` 与累计术语表的全局事务。
8. 生成器最后发 `progress:100/finish` SSE；成功路径调用 `finish(job_id)`，上游错误、普通异常调用 `fail(job_id)`，消费者断开（GeneratorExit）调用 `cancel(job_id)`。所有退出路径都经 `finally`：先向 worker 请求协作式取消并 `join(timeout=30.0)`，只在 worker 确认退出后清理临时目录（join timeout 时保留目录并记 WARNING），再幂等释放任务；Response close 另有未开始迭代时的兜底释放。

## 范围与全文翻译链

1. `POST /api/translate-batch` 接收一基闭区间 `from`/`to`，校验均为整数、≥1、不越界且 `from ≤ to`。
2. 路由换算零基 `page_indices`，使用同一协调器原子占槽，再从冻结快照构造带 `job_id` 的 `GenerateBatchContext`（抽取、`replace_pages` 与术语合并闭包都捕获 `document_id`），`pages` 参数按页数设为 `"1"` 或 `"1-N"`。
3. `generate_batch()` 先发 `batch_info`，再抽取多页 PDF 一次性送入 `run_translation()`，之后逐事件转发 SSE。
4. 完成后选 `mono_pdf_path`（回退 `dual_pdf_path`）调 `AppState.replace_pages(..., expected_document_id)` 经同一 `_commit_replacement()` 事务按序替换范围页，并只做一次受同一身份保护的 `merge_glossary_only()`。批量与单页遵循同一部分提交语义：PDF 提交失败时术语合并不执行；术语合并失败被包含后 PDF 提交保留、任务仍以 finished 结束。
5. 全文翻译是浏览器行为：`onFullTranslateClick()` 调同一批处理端点提交 `1..pageCount`，不存在独立的全文章节端点。

## 状态、缓存与持久化

| 路径/数据 | 说明 |
|---|---|
| `DATA_ROOT/cache/<hash>/right.pdf` | 每文档持久化的译文工作副本，首次打开复制源文件，翻译后原子替换 |
| `DATA_ROOT/cache/<hash>/cumulative_glossary.csv` | 每文档累积术语表，读—合并—写受模块级互斥锁保护；同目录 `.tmp` 写入并 flush/fsync/close 后 `os.replace` 原子提交；读取失败或表头缺少 source/target 时中止合并保留旧文件，写入/replace 失败保留旧文件并清理临时文件 |
| `DATA_ROOT/cache/<hash>/reading_progress.json` | 零基阅读页码，`.tmp` + `os.replace` 原子写；损坏/越界时安全降级 |
| `DATA_ROOT/logs/pdf_reader.log` | `logging_config` 配置的轮转应用日志（5MB × 5，utf-8） |
| `DATA_ROOT/cache/<hash>/debug_trace.log` | 仅 debug 模式且存在缓存路径时，由 `debug_session` 创建并在会话开始前轮转 |
| `DATA_ROOT/cache/pdf-reader-translation-*` | 翻译任务临时工作区（输出目录）：名称带固定前缀，内含 `.pdf-reader-temp-workspace` 标记（`kind`/`job_id`/`pid`/`created_at`）；worker 确认退出后删除，超时/崩溃遗留供启动恢复 |
| `PROJECT_ROOT/docs/glossary.csv` | 仓库级手动术语表，由 `src/pdf_reader/paths.py` 解析，非空时参与每次翻译 |

`DATA_ROOT` 默认等于 `PROJECT_ROOT`（仓库根），因此正常本地运行的数据位置与既有约定一致：`cache/`、`logs/` 仍在仓库根下；`PDF_READER_DATA_ROOT` 只用于测试隔离或未来显式分离运行数据。

`AppState` 另维护当前 `_document_id`、`_translated_pages`（`translated_pages` 冻结集合）与左右 PyMuPDF 文档对象；`open_pdf` 会使旧身份失效并清空旧文档与翻译页集合。SSE 断开后任务先被协作式取消；迟到任务若仍自然结束，其结果被丢弃（不进入写回），抽取、PDF 提交与术语提交的写回边界仍受身份校验约束。

提交顺序固定为「先 PDF、后术语表」，两项是同一任务内两个独立文件的部分提交；失败语义（PDF 失败即中止、术语失败被包含）由 `tests/test_system_concurrency_failure.py` 的系统级用例固定。

**缓存生命周期与关闭（P3-05）**：`cache_ops` 把 `cache/` 直接子项严格分成两类——文档缓存目录（含 `right.pdf`）与翻译临时工作区（名称带固定前缀）。统计（`scripts/cache_manage.py stats`）只读，按文档列出 `right.pdf`/累计术语表/阅读进度/debug trace 大小与临时工作区数量/字节；清理（`clean`，默认 dry-run，`--yes` 才删除）只针对“固定前缀 + 有效标记（`kind` 匹配且 `pid` 为正整数）+ 非符号链接/junction + PID 已不存活”的直接子目录，未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保留，绝不把 `right.pdf`、术语表、阅读进度或任何文档缓存目录作为删除目标。PID 存活探测在 Windows 上用 `OpenProcess` + `GetExitCodeProcess`（不用 `os.kill(pid, 0)`，后者在 Windows 会 TerminateProcess 杀死目标进程）。`main` 启动时调用 `recover_orphan_temp_workspaces` 处理崩溃遗留，删除条件同上且跳过存活 PID。`AppState.close()` 幂等：置关闭标志、关闭左右 PyMuPDF 文档句柄、清空身份/路径/页数/尺寸/翻译页集合，关闭后 `open_pdf` 抛 `RuntimeError`、其余文档操作按未打开文档拒绝。

## 前端模块与浏览器状态

`static/app.js` 是浏览器入口，持有 `pageCount`、`pageHeight`、`pageWidth`、`currentPage`、`promptVisible`，以及 `els`、`session`、`translationController`、`alignController`、`zoomInst` 等实例。

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

对齐事实：打开 PDF 时 `createAlignmentController` 安装滚动监听；翻译图片加载完成、Ctrl+滚轮/重置缩放、`scrollToPage` 均显式走 controller 的 `onImageLoaded`/`onZoomChange`/`setLockTarget+realign`。前端重叠操作保护由翻译 UI 状态机承担（运行中拒绝/忽略新操作并禁用控件），只阻止同一浏览器页内的重叠操作，不是服务端锁。

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

翻译流日志以 `[job=<uuid>]` 关联任务，并继续保留 `[page=N]` 或 `[batch=from-to]` 前缀；协调器 start/finish/fail、SSE、后台线程、生命周期、Token 与术语调试记录都携带同一 `job_id`。日志中不输出 api_key 原值。`logging_config.setup_logging()` 幂等，`LOG_DIR = paths.get_log_dir()`（默认 `DATA_ROOT/logs`），创建控制台 + `RotatingFileHandler`（5MB × 5），debug 关闭时 `werkzeug`/`pdf2zh_next`/`babeldoc` 抬到 WARNING，debug 开启时降到 DEBUG。`logging_config.reset_logging()` 关闭并移除 `pdf_reader` 根 logger 的 handler，供测试隔离可靠释放文件句柄。

日志级别与 Flask 服务共享同一个由 `main` 解析出的 debug 布尔：`create_app` 的 `setup_logging(debug)` 与 `app.run(debug=..., use_reloader=...)` 来自同一 `ServerConfig`，不会出现日志 debug 与 server debug 分叉。

错误传播：`TranslationError` 与普通异常都被 `generate`/`generate_batch` 捕获并输出 SSE `error` 事件，同时记录上下文日志；临时目录只有在 worker 线程确认退出后才会在 `finally` 中清理（join timeout 时保留并记 WARNING）。

任务日志上下文（P2-06）：任务日志统一由 `task_logging.task_log` 输出，稳定前缀 `[job=<完整 job_id> doc=<8> hash=<12> page=N|pages=A-B status=<状态>]`，页码 1-based，`document_id` 8 字符、pdf hash 12 字符（`TaskContext.__post_init__` 强制截断，直接构造也不可绕过）。上下文为不可变 `TaskContext`，经 `contextvars` 在协调器 start/release、路由构造、SSE 单页/批量生成器、`TranslationStream` worker 线程（显式 `set_current_task`）、`translation_lifecycle`、`AppState` 抽取/写回/术语合并/迟到拒绝/事务恢复与临时目录清理中传播。生命周期状态：created、started、client_disconnected、cancelling、finished、failed、discarded、cleaned；迟到身份拒绝记 `discarded`；join timeout 记 `cleanup_deferred`（WARNING，目录保留），coordinator 释放保留 `cancelled`；重复/迟到 release 静默不产生缺上下文的半截任务日志。临时目录清理以 `_safe_rmtree` 的可验证结果为准：目标原本不存在或确认删除后不存在才算 `cleaned`，任一目录删除失败记 `cleanup_deferred` 且不再记 `cleaned`。日志脱敏在 `SafeFormatter` 格式化边界执行：控制台与 `logs/pdf_reader.log` 替换配置中的 API Key 与 `sk-...`、`Authorization/Bearer`（含带引号 JSON 字段）、`api_key` 字段与独立 Bearer token（凭据值替换为 `<redacted>`，字段标签/结构保留），保留 traceback 结构与路径/HTML 诊断内容；用户 prompt 不写入日志。

前端装配与翻译 UI 状态（P2-02）：`static/modules/translation-ui-controller.js` 是单页/批量共享的翻译 UI 状态机（idle → running → succeeded/failed/aborted → idle），集中 busy 控件禁用、进度条、stage/status 文本、成功/失败恢复、延时清理与 operation generation 迟到回调隔离；单页与批量差异（范围文案、完成后刷新页集合）通过 operation descriptor/callback 注入，`app.js` 不再复制两套 busy/progress/error DOM 逻辑。每次翻译操作创建 `AbortController` 并把 `signal` 传入 `translator.js` 的 fetch；新操作、成功打开新文档（session dispose）与页面卸载时 abort 浏览器请求并使旧回调失效；浏览器 abort 只终止客户端请求/消费，不是可靠的服务端取消确认，服务端生命周期仍由 SSE 断开与后端机制决定。`static/modules/reader-session.js` 把 zoom/alignment/intersection observer/settle gate/page 生命周期清理收束为幂等 `dispose` 边界：仅在新文档 open 成功、准备替换 DOM 时 dispose 旧 session，失败打开保留旧 session（409 语义不变）。

错误契约（P2-05）：所有 API 4xx/5xx 返回顶层 `{"code": <stable_code>, "error": <safe_message>}`；`409` 保留 `translation_busy`、中文安全提示与 `active_job_id`（P0-02/P1-04 回归依赖），其余 400 分支使用稳定 code（`invalid_file_path`、`invalid_page`、`no_document_opened`、`page_out_of_range`、`invalid_side`、`invalid_page_numbers`、`invalid_page_range`），`404` 使用 `not_found`，其它 HTTP 错误使用 `http_<status>`，`500` 固定为 `internal_error`。`routes.http_error` 处理 `HTTPException`（不吞成 500），`routes.internal_error` 记录完整异常（含 traceback）后只返回安全摘要。SSE 统一经 `sse_stream.format_sse_error(code, message)` 输出 `{"type":"error","code","error"}`；上游原始 error、`TranslationError` 消息、普通异常消息与“无翻译结果”均只进服务端日志，不返回浏览器。前端 `static/modules/dom.js` 提供 `showError()`（DOM 节点 + `textContent`），`app.js` 不再使用 `insertAdjacentHTML` 插入错误文本；`static/modules/translator.js` 对非 JSON 响应、网络异常与缺失错误字段使用固定安全 fallback。非 loopback host（非 `localhost`、`127/8`、`::1`）在 `app.main` 中、`app.run` 前输出安全 WARNING（不记录 API Key，不阻止启动）。

## 测试、CI 与验证入口

`pyproject.toml` 是唯一直接依赖声明源（`project.dependencies` 运行依赖、`project.optional-dependencies.dev` 开发工具）；已删除 `requirements.txt`/`requirements-dev.txt`。`requirements.lock` 是 README、CI 和本地安装共同使用的唯一锁文件，由 Python 3.12 与 pip-tools 7.6.1 从 `pyproject.toml`（含 dev extra）生成，header 记录真实命令（用 `CUSTOM_COMPILE_COMMAND` 规避 pip-tools 7.6.1 在本环境写入多余 `--no-index` 的怪癖）。锁文件不包含 editable、本机路径或 `file:///` 来源。安装契约：`pip install -r requirements.lock` 后 `pip install -e . --no-deps`；便捷安装 `pip install -e .[dev]` 与可复现安装明确区分。

统一入口 `scripts/verify.ps1`，顺序为：输出最终 Python 绝对路径与版本并核验 Python `>=3.12`、Node `>=22`（不满足快速失败）→ 密钥扫描（`scripts/secret_scan.py`，只扫 Git 跟踪内容，占位示例放行，匹配值不输出）→ Ruff lint → Ruff format check → coverage（`coverage run --branch -m pytest -q`，全部 Python 测试；`coverage report` + `coverage json` + `scripts/check_coverage_policy.py` 执行全局与关键模块阈值）→ `mypy`（仅 `src/pdf_reader`，`check_untyped_defs`/`no_implicit_optional`/`warn_unused_ignores`/`warn_redundant_casts`/`warn_return_any`/`strict_equality`）→ `npm run lint:js`（ESLint flat config，lint `static/**/*.js` 与正式 `tests/*.mjs`）→ `npm test`（前端套件：`test:ui-copy`、`test:error-safety`、`test:translation-ui`、`test:translator`、`test:zoom`、`run-alignment-controller-tests.mjs`）。脚本接受 `-PythonExecutable` 显式指定验证环境（无效显式路径快速失败、不回退）；未指定时优先使用仓库 `venv`，不存在时回退 PATH 中的 `python` 并输出醒目 WARNING（含实际路径与版本）。本地 coverage 数据写入临时目录并在 finally 清理；设置 `PDF_READER_COVERAGE_ARTIFACT_DIR` 时输出 coverage JSON/XML 到该目录供 CI 上传（`coverage-artifacts/` 已忽略）。P2-01 起测试与运行均从已安装的 `pdf_reader` 包导入：先 `pip install -r requirements.lock` 再 `pip install -e . --no-deps`（CI 同契约），仓库根不再提供生产模块 shim。

覆盖率策略（P2-03）：全局 line ≥90%、branch ≥80%；关键模块独立 floor——`state.py` line 80/branch 75、`translation_coordinator.py` 95/95、`translation_lifecycle.py` 95/95、`sse_stream.py` 85/75、`routes.py` 85/70。实测基线（含 P2-03 测试）：全局 line 95.1%、branch 89.0%，五个关键模块均高于 floor。pytest 声明 `unit`/`integration`/`system` 标记；系统红线（`tests/test_system_concurrency_failure.py`）标记为 `system`，`integration` 标记用于真实路由/磁盘事务测试，但 verify 默认全量收集、不做 marker 排除。

测试隔离：`tests/conftest.py` 在任何应用模块导入前把 `PDF_READER_DATA_ROOT` 指向 pytest 专用临时目录，并在每个测试后调用 `logging_config.reset_logging()` 关闭/移除 handler（会话结束再清理临时目录），因此完整测试不会写入或增长仓库 `logs/`、`cache/`。`tests/test_paths.py` 用两个不同 CWD 的子进程真实构造 `create_app()`，固定 config/glossary/templates/static/logs/cache 的 CWD 无关解析，并覆盖绝对 `cache_dir` 不被重写与 `reset_logging()` 可重建 handler。

缓存生命周期回归（P3-05）：`tests/test_cache_ops.py` 覆盖统计分类、dry-run/真删边界、未知/无标记/损坏/恶意标记、前缀同名文件与符号链接/junction 保守保留、存活 PID 保留、清理失败报告与 CLI（`stats`/`orphans`/`clean`）契约；`tests/test_shutdown.py` 覆盖 coordinator `shutdown` 无任务/完成/超时/幂等/流异常容忍、`AppState.close` 幂等与 Windows 句柄释放、`main` 启动恢复与关闭日志、关闭期间单页/批量翻译被 409 拒绝。

任务日志回归：`tests/test_task_logging.py` 覆盖前缀格式/截断/1-based 页码、跨线程传播、全部生命周期状态序列（成功/失败/断开迟到丢弃/join timeout）、stale-result 与写回失败的任务上下文关联、`SafeFormatter` 与真实 `RotatingFileHandler` 落盘脱敏（sentinel 含 API key、Windows/Unix 路径、HTML；key/token 不落盘，路径保留）。

启动脚本安全回归：`tests/test_start_bat.py` 在 Windows 下把真实 `start.bat` 复制到 pytest 临时目录，用 fake `netstat.cmd`/`taskkill.cmd`/`python.cmd`/`activate.bat` 在 PATH 上执行真实脚本：断言源文件不含 `taskkill`/`tskill`/`Stop-Process`/`kill` 等终止命令；模拟 5000 被占用时脚本退出非零、不调用 python 也不调用 taskkill；无占用时激活 venv 并调用 `python -m pdf_reader`；`venv` 缺失时给出提示并非零退出。测试不绑定真实端口、不启动服务器、不杀任何进程。

系统级回归：`tests/test_system_concurrency_failure.py` 的 16 个用例穿过真实 Flask route、真实 Response/SSE generator、`TranslationCoordinator`、真实 `TranslationStream` worker 线程、`AppState` 与磁盘缓存边界；仅 `translation_orchestrator.do_translate_async_stream` 使用确定性 fake（外部翻译引擎），故障注入只作用于 `tempfile.mkdtemp`、`pymupdf.Document.save` 与 `os.replace`。覆盖：翻译进行中打开 B 被 409 拒绝且 A 的结果只写回 A；两个 Flask 客户端只有一个任务被接受；SSE 断开后 worker 继续运行/最终失败/join timeout 三条所有权路径；临时目录、输出目录与 PDF 保存失败及重试；单页与批量提交失败后的 `right.pdf`/`translated_pages`/渲染恢复；PDF 提交与术语合并的部分提交语义；打开—翻译—渲染闭环的最终 PDF 字节/页内容、`document_id`、coordinator 与 worker 状态、临时目录清理断言。

CI（`.github/workflows/ci.yml`）在 `windows-latest` 上安装 Python 3.12 依赖（`pip install -r requirements.lock` + `pip install -e . --no-deps`），执行 `import flask, pymupdf, pdf2zh_next, pdf_reader` 冒烟检查，安装 Node 22 测试依赖（`npm ci`，Node 只承担前端测试且由 `package-lock.json` 锁定），再执行同一 `scripts/verify.ps1`。`tests/README.md` 说明正式测试与历史诊断脚本的区别。

## 当前技术约束与已确认风险

以下只记录当前事实，不构成修复方案或目标设计。

1. **单进程/全局状态。** 服务端只有一个全局 `AppState`，同一时刻只面向一个本地用户、一份打开的文档；没有多用户或并行文档隔离。
2. **SSE 断开有协作式取消但无强制终止。** 消费者断开后，`generate`/`generate_batch` 请求协作式取消并等待 worker 退出（join timeout 30s），临时目录只在 worker 确认退出后删除；join timeout 时目录保留并记 WARNING。不响应取消的上游环节（含 BabelDOC 子进程）仍会运行到自然结束，其结果被丢弃，没有强制 kill 接口。
3. **术语表写入为进程内原子事务。** 读—合并—写受模块级互斥锁保护，新内容经同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交；累计文件损坏或表头缺少 source/target 时中止合并保留旧文件，写入/`os.replace` 失败保留旧文件并清理临时文件；单任务协调器与 `document_id` 阻止跨文档迟到合并。
4. **PNG 无文本层。** 页面以图片显示，没有文本选择、搜索、复制、高亮、批注、目录、内部链接或 OCR 流程。
5. **无队列/暂停/取消/重启续传。** 不存在持久任务队列、暂停、取消、重试队列、进度恢复或进程重启后的翻译续传。
6. **部分提交语义。** 单页/批量翻译结束时先提交 `right.pdf` 再合并术语表；术语表合并失败被包含（记录 WARNING），不会回滚已提交的 PDF，也不改变任务终态；PDF 提交失败则术语合并不执行。不存在跨两个文件的全局事务。
7. **启动脚本不自动释放端口。** `start.bat` 只检测并报告端口 5000 的 `LISTENING` 占用，不包含任何进程终止命令；端口冲突需要用户自行确认归属并处理（命令见 README「启动」），或改用 `config.toml` 中 `[server].port` 指定的其他端口。
8. **临时工作区清理有明确安全边界。** 只有名称带固定前缀、含有效标记（`kind` 匹配且 `pid` 为正整数）、非符号链接/junction 且 PID 已不存活的 `cache/` 直接子目录才会被启动恢复或 `cache_manage.py clean --yes` 删除；未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保守保留；持久用户数据（`right.pdf`、术语表、阅读进度）永不作为清理目标。PID 复用或查询失败时按“可能存活”保留，可能留下少量无法自动清理的目录，需要用户确认后手动处理。

## 上游与历史参考

- 项目长期意图：[project.md](project.md)；未来方向与开放问题：[roadmap.md](roadmap.md)。
- 上游接口研究：[pdf2zh-next-development-guide.md](pdf2zh-next-development-guide.md) 与 `docs/reports/` 下两份报告，均按各自顶部标注的版本适用范围阅读。
- 历史系统描述：`docs/archive/`、`docs/superpowers/`、`openspec/` 与 `CHANGELOG.md`，只用于追溯。

归档与版本特定的上游资料是辅助上下文，不是当前实现的事实源；本文档与代码、测试冲突时，以代码和测试为准。
