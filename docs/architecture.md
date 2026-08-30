# PDF Reader 当前架构

> 本文档只描述当前 HEAD 已经实现的系统。代码和测试高于本文档；发现不一致时，必须在同一变更中修正文档。项目意图见 [project.md](project.md)，未来方向见 [roadmap.md](roadmap.md)。

## 核验基线

- 核验日期：2026-08-30。事实来源、锁定版本与测试/覆盖率基线见下。
- 事实来源：CodeGraph（`codegraph explore` / `codegraph node`）输出、当前源码逐行核对、`requirements.lock`、`package.json`、`scripts/verify.ps1`、`.github/workflows/ci.yml`、`tests/test_upstream_contract.py` 和测试收集结果。
- 锁定版本：Python 3.12.8、Flask 3.1.3、PyMuPDF 1.25.2、pdf2zh-next 2.9.0、BabelDOC 0.6.2、tomlkit 0.13.3。
- 测试基线：`pytest --collect-only -q` 收集到 804 个 Python 测试（2026-08-30 日志工程化核验值，含上游契约、文档治理、配置示例契约、日志管线/调试轨迹、前端错误上报、配置中心后端用例与全部 P0–P3 用例）；`package.json` 的 `test:frontend` 定义八个正式前端套件（UI copy、error-safety、client-error、translation-ui、translator、zoom、alignment controller、config panel）。
- 覆盖率基线：全局 line 94.0%、branch 86.2%（2026-08-30 日志工程化核验值，`coverage run --branch -m pytest` 实测；策略与关键模块 floor 见“测试、CI 与验证入口”）。
- 基线说明：测试数量与覆盖率是易腐数字，任何新的架构核对都应以当前源码、锁定文件、测试收集结果与 coverage 报告为准；本文数值只代表 2026-08-30 的核验结果。

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
| tomlkit | 0.13.3 | 直接运行依赖：保留注释/顺序/未知字段的 TOML 编辑（配置中心保存 config.toml） |
| 前端 | 原生 HTML/CSS/ES Modules | 无构建步骤，浏览器直接加载 |
| Node.js | >=22（仅测试需要，CI 固定 22） | 运行八个前端测试套件 |
| ruff / pytest | 锁定在 `requirements.lock` | 代码检查与 Python 测试 |

## 许可证与包元数据

- 本项目许可证为 **AGPL-3.0-only**：根目录 `LICENSE` 是标准完整 GNU AGPL v3 官方文本（来源 <https://www.gnu.org/licenses/agpl-3.0.txt>），`pyproject.toml` 以 PEP 639 `license = "AGPL-3.0-only"` + `license-files = ["LICENSE"]` 声明，`package.json` 与 `package-lock.json` 根包许可证字段同为 `AGPL-3.0-only`，README 提供许可证与再分发说明并链接治理文档。
- `package.json` 无 `main` 字段，`type: "module"` 与浏览器 ES Modules 前端及 `.mjs` 测试运行器一致（P3-03 已删除无意义入口，P3-04 不再重做 ESM）。
- 固定翻译依赖：`pdf2zh-next==2.9.0` 与 `babeldoc==0.6.2`（`requirements.lock`），两者官方元数据与发行物（PyPI、wheel、GitHub tag LICENSE）均标注 AGPL-3.0；核验日期、精确版本、直链与所见许可证标识记录在 [docs/governance/license.md](governance/license.md)。
- 分发边界：本项目当前面向本地单用户运行；重新分发本项目、与上游组合分发或网络部署前，按实际组合方式单独核验 AGPL 义务（保留版权/许可证/源码提供义务等）。该记录不是法律意见。

## 上游最小契约（P3-06）

- 契约测试入口：`tests/test_upstream_contract.py`（离线、确定性，全部使用 fake 上游流，不联网、不运行真实翻译、不需要 API Key）；升级 pdf2zh-next/BabelDOC 前必须运行（命令见 [依赖升级流程](governance/dependency-upgrade.md)）。
- 固定版本：pdf2zh-next 2.9.0 与 babeldoc 0.6.2 同时受 `pyproject.toml`/`requirements.lock` 与安装元数据约束；babeldoc 是传递依赖，只由 `requirements.lock` 固定。
- SettingsModel 消费面：`basic.debug=False`；`translation` 的 `lang_in`/`lang_out`/`min_text_length`/`qps`/`pool_max_workers`/`term_qps`/`term_pool_max_workers`/`no_auto_extract_glossary`（由 `auto_extract_glossary` 反转）/`ignore_cache=True`/`save_auto_extracted_glossary`/`primary_font_family`/`output`（由 SSE 生成器赋值注入）/`glossaries`（逗号连接）/`custom_system_prompt`（页面 Prompt > `default_system_prompt` > 上游默认）；`pdf` 的 `pages`、固定 `no_dual=True`/`only_include_translated_page=True`/`watermark_output_mode="no_watermark"`，以及 `[pdf2zh]` 已开放的 15 个字段（含项目正确拼写 `formula_*` → 上游历史拼写 `formular_*`）；`translate_engine_settings` 按 `ENGINE_REGISTRY` 的字段映射构造，发送开关按 Provider 映射（OpenAI 使用历史拼写 `openai_send_temprature`，Aliyun/Compatible 使用各自字段）。
- 事件适配边界：本项目只承诺 `progress_start`、`progress_update`、`finish`、`error` 四种上游事件的映射；`progress_end` 等未承诺事件与未知事件被忽略（`format_sse_event` 返回 `None`），worker 空闲心跳（空串）原样透传为 SSE 空行。
- 输出路径边界：`settings.translation.output` 在生成器中注入为任务工作区 `output/` 目录；`finish` 结果的 `mono_pdf_path` 优先、缺失时回退 `dual_pdf_path`，`auto_extracted_glossary_path` 直接交给术语合并。
- 取消/流式边界：`do_translate_async_stream(settings, file)` 按两个位置参数调用；`TranslationStream` 的协作式取消、迟到事件丢弃（`late_result_dropped`）、`join(timeout)` 与 `is_alive` 所有权接口是升级契约的一部分。

## 仓库结构与文件职责

| 路径 | 职责 |
|---|---|
| `src/pdf_reader/app.py` | 启动边界 `main(argv)`、`create_app(settings)` 装配 Flask 与全局 `AppState`、启动服务；`src/pdf_reader/__main__.py` 提供 `python -m pdf_reader` 入口（导入无副作用，仅 `python -m` 时调用 `main`） |
| `src/pdf_reader/cache_ops.py` | 任务临时工作区所有权（每任务 cache 根 workspace：input/output+标记创建与失败清理）、缓存分类、只读统计与孤儿工作区清理：固定前缀/标记校验、Windows 安全 PID 存活探测、dry-run 清理边界与启动恢复 |
| `pyproject.toml` | P2-01/P2-04 可安装包与依赖契约：setuptools src 布局、`project.dependencies` 唯一直接依赖声明、`project.optional-dependencies.dev`（pytest/Ruff/coverage/mypy/pip-tools）、PEP 639 许可证（AGPL-3.0-only + LICENSE） |
| `LICENSE` | 本项目许可证：标准完整 GNU AGPL v3 官方文本（AGPL-3.0-only），与 `pyproject.toml`/`package.json`/`package-lock.json` 声明一致 |
| `docs/governance/license.md` | 本项目与固定上游依赖（pdf2zh-next/BabelDOC）的许可证核验基线、四种使用/分发场景与发布前核验清单（非法律意见） |
| `start.bat` | Windows 启动入口：检查并激活 `.\venv`、检测 5000 端口占用（只报告不杀进程）、运行 `python -m pdf_reader` |
| `src/pdf_reader/config.py` | 读取 `config.toml`、定义冻结运行时配置（`ModelRuntimeConfig`/`TranslationRuntimeConfig`/`Pdf2zhRuntimeConfig`/`UpstreamRuntimeConfig`）、严格/宽松解析、`EngineSpec`/`ENGINE_REGISTRY`、环境变量与默认值、`GLOSSARY_PATH` |
| `src/pdf_reader/config_editor.py` | 配置中心后端：41 字段 schema（分组/控件/说明/默认与常用值/Provider 适用性）、GET 密钥脱敏（只返回 configured/source）、已知字段白名单、复用 `validate_startup_requirements`/`resolve_server_config` 严格校验、revision 乐观冲突、模块级 RLock、同目录临时文件 fsync + `os.replace` 原子写并保留权限/未知字段/注释与顺序（tomlkit）；只写 `config.toml`，不热改冻结 `AppSettings`，保存返回 `restart_required=true` |
| `src/pdf_reader/paths.py` | 统一路径策略：`PROJECT_ROOT`/`DATA_ROOT` 解析、config/glossary/templates/static/logs/cache 位置、相对缓存与绝对缓存语义 |
| `src/pdf_reader/task_logging.py` | 集中任务日志上下文：不可变 `TaskContext`、`contextvars` 传播、统一前缀/截断/1-based 页码、生命周期状态、`SafeFormatter` 脱敏（API Key、sk-/Bearer、api_key、prompt 类字段） |
| `src/pdf_reader/routes.py` | Blueprint：12 个 HTTP/SSE 端点（含配置中心 GET/PUT `/api/config` 与 `POST /api/client-errors` 的 loopback-only 守卫）；统一 JSON 错误契约（`code`+`error`）、404/HTTPException/500 处理器与 409 `translation_busy`、403 `config_local_only`/`client_errors_local_only` |
| `src/pdf_reader/state.py` | `AppState`：不可变文档会话身份、锁内翻译快照、左右文档、缓存路径、哈希、页数/尺寸、翻译页集合、阅读进度、非重入锁 |
| `scripts/cache_manage.py` | 缓存只读统计与孤儿临时工作区清理 CLI：`stats`（只读/可 `--json`）、`orphans`、`clean`（默认 dry-run，`--yes` 才删除） |
| `src/pdf_reader/file_hash.py` | `sha256()` 流式文件哈希 |
| `src/pdf_reader/pdf_renderer.py` | `render_page()` 在锁内渲染页面为 PNG |
| `src/pdf_reader/pdf_extraction.py` | `extract_single_page()` / `extract_pages()` 在锁内抽取临时输入 PDF |
| `src/pdf_reader/engine_resolver.py` | `resolve_engine()`（未知 Provider 抛 `ConfigError`）与 `build_engine_kwargs(spec, model_cfg)`（显式接收 `ModelRuntimeConfig`） |
| `src/pdf_reader/translation_settings.py` | `build_settings(upstream, ...)` 显式接收 `UpstreamRuntimeConfig` 组装 pdf2zh-next `SettingsModel` |
| `src/pdf_reader/translation_orchestrator.py` | `TranslationStream`：daemon worker 线程 + asyncio 循环（含事件循环异常处理）+ 事件队列 + 协作式取消；`run_translation()` 工厂 |
| `src/pdf_reader/translation_coordinator.py` | 单槽 `TranslationCoordinator`：线程安全的 active job、任务身份、409 互斥与 finish/fail/cancel 幂等释放 |
| `src/pdf_reader/sse_stream.py` | SSE 格式化、`generate()` / `generate_batch()`、`STAGE_LABELS`、worker 退出确认后的任务工作区清理 |
| `src/pdf_reader/translation_lifecycle.py` | `finish_translation()` / `merge_glossary_only()`：译文持久化与术语合并 |
| `src/pdf_reader/glossary_service.py` | 累积术语路径解析与合并入口 |
| `src/pdf_reader/glossary_merger.py` | 术语多数投票合并：模块级互斥锁 + 同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交（BOM 安全读写） |
| `src/pdf_reader/logging_config.py` | 统一日志管线：同一对控制台 + `logs/pdf_reader.log` 轮转 handler 托管 `pdf_reader`/`werkzeug`/`pdf2zh_next`/`babeldoc`、ISO 元数据行格式与 run_id、sys/threading 未捕获异常钩子、reset 快照恢复 |
| `src/pdf_reader/debug_trace.py` | 按任务的有界调试会话：`cache/<hash>/debug_trace.log`（2MB × 3，job 过滤，start/end/elapsed/traceback），debug 关闭时零 IO |
| `templates/index.html` | 唯一 HTML 页面：打开区、双栏、工具栏、始终可见的“配置”按钮 |
| `static/app.js` | 前端入口与共享状态 |
| `static/modules/` | app-controller、client-error、dom、lazy-loader、scroll-sync、alignment-controller、zoom、sse-client、stages、translator、translation-ui-controller、reader-session、config-panel |
| `static/style.css` | 深色主题、双栏与缩放 CSS 变量 |
| `tests/test_upstream_contract.py` | P3-06 上游最小契约：固定版本、SettingsModel 消费字段/引擎字段映射、事件映射与未知事件忽略、输出路径与 mono→dual/glossary、协作式取消与 join/is_alive 所有权（离线确定性 fake） |
| `tests/test_documentation_governance.py` | P3-06 文档治理：常青文档职责边界、链接可解析、上游契约命令一致、易腐数字基线 |
| `tests/` | pytest 文件（含 P2-07 路径、P2-06 任务日志、P2-01 包布局、P2-03 契约、P3-04 许可证、P3-05 缓存与关闭、P3-06 上游契约/文档治理、P3-07 密钥扫描与仓库治理、日志管线/调试轨迹/前端错误上报、配置示例契约、配置中心后端用例）与前端 `.mjs` 测试运行器（含 client-error 与 config panel 用例） |
| `scripts/verify.ps1` | 统一验证入口（lint、格式、Python 测试、前端测试） |
| `scripts/secret_scan.py` | 高可信密钥扫描：只扫 Git 跟踪内容，占位示例放行，不输出 secret 值 |
| `.github/workflows/ci.yml` | Windows + Python 3.12 + Node 22 的 CI |
| `.github/dependabot.yml` | pip/npm 月度依赖升级 PR |
| `docs/governance/documentation.md` | 三份长期文档的更新时机、上游升级步骤、易腐数字政策与事实冲突优先级 |
| `docs/governance/` | 文档治理、工具目录治理、依赖升级流程与许可证核验基线（非法律意见） |
| `docs/`、`docs/archive/`、`docs/reports/` | 常青文档、历史归档与上游研究资料 |

## 运行时进程、线程、队列与锁

- 一个 Flask 进程持有唯一全局 `AppState`（`app.config["app_state"]`），同一时刻服务一个打开的文档。每次成功打开（包括再次打开同一路径）都会生成新的随机 `document_id`；关闭或切换文档立即使旧身份失效。
- `AppState` 内部是 `threading.Lock`（非重入），打开/渲染/抽取/替换/术语合并/阅读进度写入全部在锁内执行；传给 state 的回调（渲染、抽取、术语合并）不得再次进入 `AppState`。`translation_snapshot()` 在锁内一次性返回冻结的 `document_id`、PDF 哈希、页数和术语缓存路径。
- 术语合并的读—合并—写全过程另由 `glossary_merger` 的模块级互斥锁保护：即使绕过 `AppState` 直接调用 `merge_glossary_csvs`，两个并发合并也不会截断累计 CSV 或静默丢更新。
- 全局 `TranslationCoordinator` 使用独立的 `threading.Lock` 保护单个 `active_job`。`start(document_id, page_indices)` 原子创建含 UUID `job_id`、文档身份、页码 tuple、UTC 创建时间和 active 状态的冻结任务；已有任务时抛 `TranslationBusyError`；进入关闭流程后抛 `CoordinatorShutdownError`（路由转为 409 `translation_busy`，无 `active_job_id`）。`finish(job_id)` / `fail(job_id)` 只释放匹配任务，重复或迟到释放不会影响后续任务。
- SSE 生成器通过 `register_stream(job_id, stream)` / `unregister_stream(job_id)` 把真实 worker 登记到协调器；`shutdown(timeout)` 先置关闭标志拒绝新任务，再对已登记流请求协作式取消并按剩余时间有界 `join`，随后等待 active job 释放，返回 `ShutdownReport(outcome="no_active_job"|"completed"|"timeout", active_job_id, worker_joined)`。`shutdown` 不 kill 线程；worker 不响应取消时任务槽与任务工作区保留，重复调用幂等且结果一致。
- 每个翻译请求由 `TranslationStream`（`run_translation()` 工厂返回）启动一个 daemon worker 线程；该线程创建独立 asyncio 事件循环并安装异常处理器（未等待的 asyncio 异常按任务上下文记录 ERROR + traceback），`async for` 消费 `do_translate_async_stream(settings, pdf_path)`，把事件放入 `queue.Queue`。线程总是以入队内部 `_done` 标记结束，`cancel()` 在事件边界之间做协作式取消检查，`join(timeout)` 与 `is_alive` 暴露真实 worker 状态。
- 同步 SSE 生成器从队列取事件并逐条 yield；队列空闲 1 秒时 yield 空串作为心跳，收到 `_done` 后 `__next__` 先 `join(timeout=30.0)` 确认线程退出（join timeout 记 WARNING），再结束迭代或抛 `TranslationError`。
- 上游 pdf2zh-next 内部可能以子进程方式运行 BabelDOC 的版面/PDF 生成环节；本项目自身不直接管理该子进程的生命周期，也没有持久任务队列、任务注册表、暂停/取消接口或重启续传状态。协作式取消只作用于事件边界；不响应取消的上游环节允许自然结束，其结果被丢弃。

## 启动与 Flask 应用装配

1. `python -m pdf_reader` 进入 `app.main(argv=None)`：模块导入不解析 CLI、不修改 `config.DEBUG`；CLI 解析只发生在该启动边界内，`__main__.py` 的 `main()` 调用受 `if __name__ == "__main__"` 守卫保护，`import pdf_reader.__main__` 同样无副作用。`--debug` 与 `--no-debug` 互斥。
2. `config.resolve_server_config(cli_debug=...)` 按优先级 CLI `--debug`/`--no-debug` > 环境变量 `PDF_READER_DEBUG` > `[server].debug` > 默认 `false` 解析一次，返回 frozen `ServerConfig(host, port, debug)`；`use_reloader` 恒为 `False`——`debug` 只表示“详细诊断日志模式”（日志 DEBUG + debug_trace），不再控制 Flask debugger/reloader。
3. `main` 调用 `config.validate_startup_requirements()` 统一严格校验 `[model]`/`[pdf_reader]`/`[translation]`/`[pdf2zh]`：未知 section/key/provider、类型/范围/组合/正则错误、`openai_compatible` 缺 `base_url` 均抛 `ConfigError`；缺少 `model.model`、API Key 或 API Key 为示例值时同样失败。main 打印 `ERROR:` 并以退出码 2 结束，不启动服务器。该函数返回严格解析出的同一个 `UpstreamRuntimeConfig`。
4. `main` 用步骤 2 的同一 `ServerConfig` 与步骤 3 的同一 `UpstreamRuntimeConfig` 调用 `config.build_app_settings(cli_debug=..., run_cfg=run_cfg, upstream=upstream)`：复用已解析结果，不再二次调用 `resolve_server_config` 或宽松重解析上游配置；`settings.debug` 与 `run_cfg.debug` 恒一致，`settings.upstream` 与严格实例恒为同一对象。
5. `create_app(settings)` 使用 `settings.debug` 调用 `logging_config.setup_logging(...)`，输出启动摘要（provider/model/lang/cache_dir/dpi/debug，不含 api_key）；创建 `Flask(__name__)` 并显式传入 `template_folder=PROJECT_ROOT/templates`、`static_folder=PROJECT_ROOT/static`（由 `src/pdf_reader/paths.py` 解析），装配全局 `AppState(settings.cache_dir)` 与 `TranslationCoordinator()`，导入并注册 `pdf_reader.routes.register_routes`。`register_routes` 只消费已注入的 `app.config["app_settings"]`；仅当该 key 缺失（绕过 `create_app` 直接注册 blueprint 的兼容边界）时才惰性调用 `config.build_app_settings()`。
6. `main` 在 `create_app`（日志已就绪）之后调用 `cache_ops.recover_orphan_temp_workspaces(settings.cache_dir)`：清理上次崩溃/超时退出遗留的、可验证归属（固定前缀 + 有效标记 + 非链接 + PID 已不存活）的翻译任务根工作区（含 `input/` 与 `output/`）；未知/无标记/损坏标记/链接路径/PID 仍存活的目录一律保守保留。清理数量与保留分类写入 INFO/WARNING 日志。
7. `main` 以 `app.run(host=..., port=..., debug=False, use_reloader=False)` 启动（显式传入全部四个参数，Flask debugger/reloader 始终关闭）；`KeyboardInterrupt` 记录 INFO 并以 130 退出，其它运行期异常经 `logger.exception` 记录完整 traceback 后以 1 退出。`app.run()` 返回或异常退出时先调用 `coordinator.shutdown(timeout=10.0)` 做有界关闭：请求协作式取消并等待 worker 与 active job，按 `no_active_job`（INFO）/ `completed`（INFO）/ `timeout`（WARNING，任务与工作区保留供下次启动恢复）记录日志，worker 未确认退出时追加 WARNING；随后 `app_state.close()` 幂等关闭并释放左右 PyMuPDF 句柄、清空状态并记录 `app state closed`（即使 `shutdown` 抛异常也会执行）。
8. 配置错误路径：TOML 语法错误在配置导入时被捕获（`config._CONFIG_LOAD_ERROR`），首次解析配置时抛 `ConfigError`；`[server]` 类型/范围错误与 `PDF_READER_DEBUG` 非法值同样由 `resolve_server_config` 抛 `ConfigError`；`--debug`/`--no-debug` 互斥由 argparse 报错。所有路径都在启动服务器前以非零状态退出。
- `start.bat` 是 Windows 便捷启动入口：切换到仓库根目录后先检查 `.\venv\Scripts\python.exe`（缺失时打印创建/安装命令并不为零退出），再用 `netstat -ano -p tcp | findstr "LISTENING" | findstr ":5000 "` 检测端口占用；若 5000 已被监听，打印占用 PID 与 `netstat`/`tasklist` 排查命令并以非零状态退出，绝不执行 `taskkill`/`Stop-Process` 等终止命令；无冲突时 `call .\venv\Scripts\activate.bat` 激活既有虚拟环境并运行 `python -m pdf_reader`。

## 配置加载与 Provider 映射

- `config.py` 经 `src/pdf_reader/paths.py` 读取 `PROJECT_ROOT/config.toml`（`CONFIG_PATH`）。`PROJECT_ROOT` 默认由 `paths.py` 从 `src/pdf_reader/` 的模块位置向上查找 `config.example.toml` 标记得到（自动回到仓库根），也可用环境变量 `PDF_READER_ROOT` 显式覆盖；文件不存在时配置回退为空字典，不在导入期抛错。
- 导入安全：`_section`/`_string` 安全提取，非 table section 与非字符串字段在导入期使用安全默认值（不会因 `AttributeError`/`TypeError` 崩溃）；原始 `CONFIG` 保留供启动校验。
- 环境变量覆盖：`MODEL_API_KEY`（优先级高于 `model.api_key`）；`PDF_READER_DEBUG` 是 debug 优先级中间层，只接受 `true/false/1/0/on/off/yes/no`（不区分大小写、忽略首尾空白），非法值启动时报错（即使 CLI 显式覆盖也会 fail-fast）。
- `[server]` 严格校验：必须是 table；`host` 非空字符串；`port` 是 1–65535 的 int（布尔值不算）；`debug` 必须为真布尔值。旧的 `[debug].enabled` 键已停止使用。
- 冻结运行时配置：`build_upstream_runtime_config()` 把解析结果冻结为 `ModelRuntimeConfig`（`api_key` 为 `repr=False`）/`TranslationRuntimeConfig`/`Pdf2zhRuntimeConfig`/`UpstreamRuntimeConfig`；`AppSettings.upstream` 持有该对象，`model_provider`/`model`/`lang_in`/`lang_out` 从它派生，不再从 raw section 单独取值。
- 默认值：provider=`openai_compatible`、model=`""`、dpi=200、cache_dir=`cache`、lang_in=`en`、lang_out=`zh`、`min_text_length=5`、`qps=4`、worker 相关为 `None`（上游跟随）、`auto_extract_glossary=True`、`primary_font_family=None`（auto）、PDF 高级字段采用上游 2.9.0 默认（`translate_table_text=True`、其余 false/0.8/0.9）。相对 `cache_dir` 以 `DATA_ROOT`（默认等于 `PROJECT_ROOT`）为基准解析并 `resolve()`；绝对 `cache_dir` 保持绝对，不被重写。`DATA_ROOT` 可用环境变量 `PDF_READER_DATA_ROOT` 覆盖。
- 统一严格校验 `validate_startup_requirements()`（`app.main` 启动前调用，返回严格 `UpstreamRuntimeConfig`）：`[model]`/`[pdf_reader]`/`[translation]`/`[pdf2zh]` 存在则必须为 table；未知 section/key 与未知 provider 直接报错；`openai_compatible` 缺 `base_url` 启动失败；bool 不得冒充 int/float；数值必须有限（nan/inf/-inf 拒绝）；`temperature` 只要求可解析且有限，`timeout` 要求有限正数；`reasoning_effort` 按 Provider 枚举校验；正则字段启动期预编译；API Key 只出现在 `ModelRuntimeConfig.api_key`（`repr=False`），错误与日志不泄漏 Key/Prompt 原文。
- `MODEL_API_KEY` 环境值合法（非空且非示例占位值）时覆盖文件中无效的 `api_key`，但 `[model]` 段本身仍必须是 table。`build_app_settings()` 未传入 `upstream` 时用宽松解析装配（无 config.toml 的测试/兼容 fallback）；`main` 必须传回严格实例，禁止宽松重解析。
- `GLOSSARY_PATH = PROJECT_ROOT/docs/glossary.csv`（由 `src/pdf_reader/paths.py` 派生），必须保持该路径；模块位于 `src/pdf_reader/` 时不因 `__file__` 变化而改变。
- `ENGINE_REGISTRY` 用声明式 `EngineSpec` 注册 10 个 Provider，顺序为：`deepseek`、`zhipu`、`siliconflow`、`aliyun`、`gemini`、`groq`、`grok`、`modelscope`、`openai`、`openai_compatible`。
- `resolve_engine()` 对未知 Provider 抛 `ConfigError`（不再回退 `openai_compatible`）；`build_engine_kwargs(spec, model_cfg)` 显式接收 `ModelRuntimeConfig`，按 `ENGINE_REGISTRY.field_map` 映射（含发送开关：OpenAI → 历史拼写 `openai_send_temprature`，Compatible/Aliyun → 各自 `send_temperature`；发送开关为 `False` 时省略以保持旧请求行为，`enable_json_mode=False` 等普通字段仍显式透传）。
- `translation_settings.build_settings(upstream, input_pdf, ...)`：设置 `lang_in`/`lang_out`/`min_text_length`/`qps`/worker 与 term 字段/`no_auto_extract_glossary`+`save_auto_extracted_glossary`（由 `auto_extract_glossary` 映射）/`primary_font_family`；Prompt 优先级为页面非空 Prompt > `default_system_prompt` > 上游默认；`ignore_cache=True`；把非空的 `docs/glossary.csv` 与累积术语路径拼为 `glossaries`；`output` 由生成器设置；PDF 参数为 `pages`、固定 `no_dual=True`/`only_include_translated_page=True`/`watermark_output_mode="no_watermark"`，并把 `[pdf2zh]` 的 15 个字段显式传入（`formula_*` → 上游 `formular_*`）。

## 配置中心（config_editor 与 config-panel）

- 后端 `src/pdf_reader/config_editor.py` 定义 41 字段 schema（覆盖 `[model]`/`[pdf_reader]`/`[translation]`/`[server]`/`[pdf2zh]`），每字段含中文名、TOML 路径、必填/可选/进阶分组、控件类型、用途说明、默认/常用值、Provider 适用性与条件必填；`GET /api/config` 返回 schema、当前值与文件 sha256 revision，API Key 只返回 `{source: file|environment|missing, configured}`，不返回明文。
- 保存只接受 schema 白名单字段；合并后的文档先过滤到已知 section/字段，再复用 `config.validate_startup_requirements()` 与 `config.resolve_server_config()` 做同一套类型/范围/枚举/条件依赖校验，不维护第二套规则。
- 写入用 tomlkit 解析既有 `config.toml`：保留注释、字段顺序与未知字段；模块级 `RLock` 串行化同进程写入；临时文件创建在目标同目录，flush/fsync 后 `os.replace` 原子替换并保留原权限；失败清理临时文件且原文件不变。API Key 为空/缺失时保留文件旧值；保存成功返回 `restart_required=true`，只写文件，不修改 `config.CONFIG` 或运行中的冻结 `AppSettings`。
- 前端 `static/modules/config-panel.js` 由始终可见的“配置”按钮打开可关闭 modal：字段按必填/可选/进阶分组，显示中文名、TOML 路径、说明与默认/常用值提示；provider 为固定友好下拉（DeepSeek、智谱、硅基流动、阿里云百炼、Gemini、Groq、Grok、ModelScope、OpenAI、自定义 OpenAI 兼容接口→`openai_compatible`），按 provider 显示/隐藏适用字段，`openai_compatible` 时 Base URL 标记必填；枚举/布尔用 select，数字与字符串带 datalist 但允许自定义，API Key 用密码框且不回显；环境变量 `MODEL_API_KEY` 覆盖时显示优先提示；Esc、关闭按钮与遮罩点击均可关闭。
- 访问边界：`GET/PUT /api/config` 共享 loopback-only 守卫，只依据 `request.remote_addr`（不信任 Host/X-Forwarded-For）用 `ipaddress` 判定 127/8、`::1` 与 IPv4-mapped loopback；remote_addr 缺失/非法 fail closed，其余来源一律 HTTP 403 `config_local_only`。
- 配置写入不改变缓存语义：`right.pdf`、累计术语表与阅读进度仍按原 PDF 哈希复用，不产生配置指纹、缓存分支或自动失效（见“状态、缓存与持久化”）。

## 打开 PDF 与页面渲染

1. 浏览器 `openPdf()` 把本地绝对路径 POST 到 `/api/open`。
2. 路由校验 `os.path.isfile`；若协调器存在 active job 则返回 HTTP 409 / `translation_busy`，否则调用 `state.open_pdf(path, sha256)`。
3. `AppState.open_pdf()` 在锁内：关闭旧文档并使旧身份失效 → 计算 SHA256 → 建 `cache/<hash>/` → `right.pdf` 不存在时复制源文件 → 打开左右 PyMuPDF 文档 → 生成新 `document_id` → 记录页数、首页尺寸与哈希 → 读取 `reading_progress.json`。
4. 响应返回 `page_count`、`page_height`、`page_width`、`hash`、`document_id`、`saved_page`。
5. 前端按页数创建左右页面容器，经懒加载从 `GET /api/page/<side>/<page>` 取 PNG；`state.render_page()` 在锁内调用 `pdf_renderer.render_page()`（`get_pixmap(dpi)` → PNG），越界返回 404，非法 side 返回 400。

## 单页翻译链

1. `POST /api/translate/<page>`（零基页码）校验文档已打开、页码在范围内，解析累积术语路径，`build_settings()` 组装参数。
2. 路由先取得冻结的文档快照，再调用协调器 `start(document_id, [page])` 原子占用任务槽；已有任务时返回 HTTP 409，且不构造 SSE 生成器、不创建任务工作区或后台线程。接受后构造带 `job_id` 和 finish/fail 回调的 `GenerateContext`；抽取、`replace_page` 与术语合并闭包都捕获快照中的 `document_id`。
3. `generate()` 在 cache 根创建带前缀与标记的任务工作区（`input/` 抽取输入、`output/` 上游输出），在 `debug_trace.debug_session` 内先 `extract_single_page()` 抽取单页 PDF。
4. `run_translation()` 启动 daemon worker 线程运行上游异步翻译；`format_sse_event()` 把 `progress_start`/`progress_update`/`finish`/`error` 映射为 SSE；非 dict 心跳直接 yield 空串。
5. 收到上游 `finish` 事件后保留 `translate_result` 与 token 用量，随后调用 `finish_translation()`：优先 `mono_pdf_path`，缺失时回退 `dual_pdf_path`，再调 `AppState.replace_page(..., expected_document_id)` 写入译文，并通过 `AppState.merge_glossary(..., expected_document_id)` 把自动术语并入累计文件。
6. `replace_page()` 在锁内先比较预期身份，再经 `_commit_replacement()` 事务提交：所有页修改在从磁盘已提交的 `right.pdf` 重开的工作副本上完成 → 保存 `.tmp` → 关闭译文/工作文档 → 关闭旧右文档句柄 → `os.replace` 原子替换 → 重开右文档 → 更新翻译页集合。磁盘提交成功前不替换内存句柄和 `_translated_pages`；任意失败（open/delete/insert/save/close/`os.replace`）都会清理 `.tmp`、关闭泄漏句柄、恢复或保留可渲染的文档句柄，旧 `right.pdf` 保持不变。`merge_glossary()` 同样在锁内完成身份比较与合并回调；失配时两条边界都抛出 `StaleDocumentError`、记录 `[stale-result]` 警告且不修改当前文档。
7. 当前部分提交语义（由 `tests/test_system_concurrency_failure.py` 固定）：`finish_translation()` 严格按「PDF 提交 → 术语合并」顺序执行两个独立文件提交。PDF 提交（`replace_page`）失败时异常向上传播，术语合并不执行，任务以 failed 释放并输出 SSE `error`；术语合并失败被 `merge_after_translate` 捕获并记录 WARNING，不向上传播——此时 PDF 提交保留、旧术语表不变，任务仍以 finished 释放并输出 SSE `finish`。两者是同一任务内两个独立文件的部分提交，不存在跨 `right.pdf` 与累计术语表的全局事务。
8. 生成器最后发 `progress:100/finish` SSE；成功路径调用 `finish(job_id)`，上游错误、普通异常调用 `fail(job_id)`，消费者断开（GeneratorExit）调用 `cancel(job_id)`。所有退出路径都经 `finally`：先向 worker 请求协作式取消并 `join(timeout=30.0)`，只在 worker 确认退出后整体清理任务工作区（join timeout 时整体保留并记 WARNING），再幂等释放任务；Response close 另有未开始迭代时的兜底释放。

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
| `DATA_ROOT/logs/pdf_reader.log` | 永久常驻的统一主日志：`logging_config` 把同一对控制台 + 轮转文件 handler 挂到 `pdf_reader`/`werkzeug`/`pdf2zh_next`/`babeldoc`，行格式为 ISO 时间/level/run_id/pid/thread/logger，128 KiB × 5、UTF-8（常规上限约 768 KiB），超过 14 天的编号轮转备份在启动与轮转后自动清理，所有通道经同一 `SafeFormatter` 脱敏 |
| `DATA_ROOT/cache/<hash>/debug_trace.log` | 仅详细诊断日志模式产生：按文档缓存目录有界轮转（2MB × 3），会话内按 `job_id` 过滤捕获项目 + 第三方日志，记录 start/end/elapsed 与失败 traceback；debug 关闭时零 IO，不生成 timestamp 历史文件 |
| `DATA_ROOT/cache/pdf-reader-translation-*` | 翻译任务根工作区：名称带固定前缀，内含 `.pdf-reader-temp-workspace` 标记（`kind`/`job_id`/`pid`/`created_at`）与 `input/`（抽取输入）、`output/`（上游输出）；worker 确认退出后整体删除，超时/崩溃整体保留供启动恢复 |
| `PROJECT_ROOT/docs/glossary.csv` | 仓库级手动术语表，由 `src/pdf_reader/paths.py` 解析，非空时参与每次翻译 |

`DATA_ROOT` 默认等于 `PROJECT_ROOT`（仓库根），因此正常本地运行的数据位置与既有约定一致：`cache/`、`logs/` 仍在仓库根下；`PDF_READER_DATA_ROOT` 只用于测试隔离或未来显式分离运行数据。

配置扩展不改变缓存身份与复用语义：文档缓存仍只按原 PDF 哈希保存（`right.pdf`、`cumulative_glossary.csv`、`reading_progress.json`；debug 会话的 `debug_trace.log` 也按同一哈希目录保存），不产生配置指纹、缓存分支或自动失效；修改模型、Prompt、字体或 PDF 高级参数只影响之后执行的翻译或主动重译，已有 `right.pdf` 页面继续复用，累计术语表跨配置复用；上游请求缓存仍固定 `TranslationSettings.ignore_cache=True`。

`AppState` 另维护当前 `_document_id`、`_translated_pages`（`translated_pages` 冻结集合）与左右 PyMuPDF 文档对象；`open_pdf` 会使旧身份失效并清空旧文档与翻译页集合。SSE 断开后任务先被协作式取消；迟到任务若仍自然结束，其结果被丢弃（不进入写回），抽取、PDF 提交与术语提交的写回边界仍受身份校验约束。

提交顺序固定为「先 PDF、后术语表」，两项是同一任务内两个独立文件的部分提交；失败语义（PDF 失败即中止、术语失败被包含）由 `tests/test_system_concurrency_failure.py` 的系统级用例固定。

**缓存生命周期与关闭（P3-05）**：每个翻译任务开始时 `cache_ops.create_temp_workspace` 在 `cache/` 根创建唯一带前缀的根工作区，含 `input/` 与 `output/` 子目录和有效标记；创建中途失败只清理本次新建目录，清理失败时保留未标记目录，不触碰其他缓存内容。`cache_ops` 把 `cache/` 直接子项严格分成两类——文档缓存目录（含 `right.pdf`）与翻译任务工作区（名称带固定前缀）。`settings.translation.output` 指向工作区 `output/`，抽取输入写入 `input/`，使崩溃遗留的抽取与输出都落在同一个已标记恢复边界内。统计（`scripts/cache_manage.py stats`）只读，按文档列出 `right.pdf`/累计术语表/阅读进度/debug trace 大小与工作区数量/字节；清理（`clean`，默认 dry-run，`--yes` 才删除）只针对“固定前缀 + 有效标记（`kind` 匹配且 `pid` 为正整数）+ 非符号链接/junction + PID 已不存活”的直接子目录，未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保留，绝不把 `right.pdf`、术语表、阅读进度或任何文档缓存目录作为删除目标。PID 存活探测在 Windows 上用只读 `OpenProcess` + `GetExitCodeProcess`（不用 `os.kill(pid, 0)`，后者在 Windows 会 TerminateProcess 杀死目标进程）；`OpenProcess` 返回空句柄时只有明确不存在（`ERROR_INVALID_PARAMETER` 等可靠信号）才判定为不存活，拒绝访问/未知错误/`GetExitCodeProcess` 失败一律按可能存活保留。`main` 启动时调用 `recover_orphan_temp_workspaces` 处理崩溃遗留，删除条件同上且跳过存活 PID。`AppState.close()` 幂等：置关闭标志、关闭左右 PyMuPDF 文档句柄、清空身份/路径/页数/尺寸/翻译页集合，关闭后 `open_pdf` 抛 `RuntimeError`、其余文档操作按未打开文档拒绝。

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
| `client-error.js` | 采集 `window` 的 `error`/`unhandledrejection`，白名单清洗后经 sendBeacon（回退 keepalive fetch）上报 `/api/client-errors`；上报失败不递归 |
| `config-panel.js` | 配置中心面板：分组渲染、provider 联动、API Key 密码框不回显、加载/保存状态与重启提示 |

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
| `POST /api/client-errors` | 前端全局错误上报：白名单字段（kind/message/source/line/column/stack）、正文 ≤8KB、控制字符折叠后记 WARNING；仅 loopback 来源可访问，否则 403 `client_errors_local_only`；不记录请求 headers/cookies/prompt |
| `GET /api/config` | 返回配置中心 schema + 当前值 + revision（API Key 脱敏）；仅 loopback 来源可访问，否则 403 `config_local_only` |
| `PUT /api/config` | 白名单校验并原子保存 config.toml（revision 乐观并发）；成功返回 `restart_required=true`；仅 loopback 来源可访问，否则 403 `config_local_only` |

Blueprint 级 `@bp.app_errorhandler(404)` 返回 JSON，不计入上述路由表。SSE 事件类型包括 `batch_info`、`progress`（含 stage/stage_current/stage_total）、`error`、`finish`，以及空行心跳。

互斥响应：active job 存在时，新的单页/批量翻译请求以及 `/api/open` 返回 HTTP 409，JSON 至少包含 `error`（明确中文提示）、稳定 `code="translation_busy"` 和 `active_job_id`。前端已有的非 2xx JSON 错误路径会直接显示服务端提示。

## 日志与错误传播

根命名空间为 `pdf_reader`，模块命名空间：`pdf_reader.app`、`pdf_reader.state`、`pdf_reader.translate`、`pdf_reader.lifecycle`、`pdf_reader.glossary`、`pdf_reader.routes`、`pdf_reader.client`、`pdf_reader.render`、`pdf_reader.extract`、`pdf_reader.engine`、`pdf_reader.debug_trace`。

| 级别 | 用途 |
|---|---|
| ERROR | 请求级失败、未捕获异常（sys/threading/asyncio）、HTTP 500，带 `exc_info` |
| WARNING | 可恢复降级（超时、文件缺失、术语合并失败）、前端错误上报、非 loopback 访问拒绝 |
| INFO | 流程里程碑（打开、翻译起止、替换、合并完成、启动摘要、debug session start/end） |
| DEBUG | 高频/细节（渲染、抽取、token 用量、端点入口）；仅详细诊断日志模式开启 |

### 主日志管线

`logging_config.setup_logging(debug)` 创建同一对 handler（控制台 + `DATA_ROOT/logs/pdf_reader.log` 轮转文件，128 KiB × 5、UTF-8；编号备份超过 14 天在 setup 启动与每次轮转后清理，清理失败只记 warning、不影响写入/启动），挂到 `pdf_reader`、`werkzeug`、`pdf2zh_next`、`babeldoc` 四个 logger；四个托管 logger 均 `propagate=False` 且 `disabled=False`，避免经 root/lastResort/旧 handler 绕过脱敏或重复输出。主日志永久常驻，每次启动自动创建/追加。行格式为 `ISO时间 level run_id=… pid=… thread=… logger=… [message]`；`run_id`（12 hex）在每次 setup 生命周期内唯一，reset 后重新生成。`setup_logging` 幂等，重复调用只更新级别；`reset_logging` 精确恢复被托管 logger 的既有 handler/level/propagate/disabled 快照并关闭本管线创建的 handler。

debug 关闭（默认）：`pdf_reader` 主级别 INFO、第三方（`werkzeug`/`pdf2zh_next`/`babeldoc`）WARNING、文件 handler 仍放行 DEBUG；debug 开启：全部降到 DEBUG。`settings.debug` 只表示“详细诊断日志模式”，`ServerConfig.use_reloader` 恒为 `False`，`main` 始终以 `app.run(debug=False, use_reloader=False)` 启动——Flask debugger 与 reloader 永不启用。

### 任务前缀与上下文

翻译流日志以稳定前缀 `[job=<完整 job_id> doc=<8> hash=<12> page=N|pages=A-B status=<状态>]` 关联任务（页码 1-based；`document_id` 8 字符、pdf hash 12 字符，`TaskContext.__post_init__` 强制截断，直接构造也不可绕过）。上下文为不可变 `TaskContext`，经 `contextvars` 在协调器 start/release、路由构造、SSE 单页/批量生成器、`TranslationStream` worker 线程（显式 `set_current_task`）、`translation_lifecycle`、`AppState` 抽取/写回/术语合并/迟到拒绝/事务恢复与任务工作区清理中传播。生命周期状态：created、started、client_disconnected、cancelling、finished、failed、discarded、cleaned；迟到身份拒绝记 `discarded`；join timeout 记 `cleanup_deferred`（WARNING，工作区保留），coordinator 释放保留 `cancelled`；重复/迟到 release 静默不产生缺上下文的半截任务日志。任务工作区清理以 `_safe_rmtree` 的可验证结果为准：目标原本不存在或确认删除后不存在才算 `cleaned`，任一目录删除失败记 `cleanup_deferred` 且不再记 `cleaned`。

### 脱敏

`SafeFormatter` 在格式化边界统一处理四个托管 logger 的全部输出（控制台、主日志文件、debug_trace）：替换配置中的 API Key 与 `sk-...`、`Authorization/Bearer`（含带引号 JSON 字段）、`api_key` 字段、独立 Bearer token，以及 `custom_system_prompt`/`system_prompt`/`user_prompt`/`prompt` 类字段值（凭据值替换为 `<redacted>`，字段标签/结构保留）；traceback 结构保留，路径/HTML 仅作为服务端诊断内容保留。第三方（`werkzeug`/`pdf2zh_next`/`babeldoc`）记录与项目记录走同一 handler 和同一 formatter，因此同样脱敏。

### debug_trace 会话

debug 开启时，单页/批量翻译在 `debug_trace.debug_session(...)` 内把有界 `RotatingFileHandler`（`cache/<hash>/debug_trace.log`，2MB × 3、UTF-8、同一 `SafeFormatter`）临时挂到四个托管 logger；生产路径按 `job_id` 过滤，只保留当前 `TaskContext.job_id` 匹配的记录。会话标记记录 start/end（含 `elapsed`）与失败（ERROR + traceback，随后重新抛出）。debug=false 时 `debug_session` 完全无 IO：不建目录、不写文件。不再生成 timestamp 命名历史文件，只追加并做有界轮转。

### 诊断边界

- sys/threading 未捕获异常：`setup_logging` 安装安全 `sys.excepthook`/`threading.excepthook`，把未捕获异常写入统一日志（含 traceback，经脱敏）；普通异常记录成功后不再调用原 hook，`KeyboardInterrupt`/`SystemExit` 与记录失败时回退原 hook。
- asyncio：`TranslationStream` 为每个 worker 事件循环安装 `loop.set_exception_handler`，未等待的 asyncio 异常按任务上下文记录 ERROR + traceback。
- 启动：日志初始化后的致命异常由 `main` 统一 `logger.exception` 记录并返回非零；`KeyboardInterrupt` 记录 INFO 并返回 130；配置校验错误在日志就绪前打印 `ERROR:` 并以退出码 2 结束。
- 关闭：`coordinator.shutdown(timeout=10.0)` 按 `no_active_job`/`completed`/`timeout` 记录，worker 未确认退出追加 WARNING；随后 `app_state.close()` 幂等释放句柄并记录 `app state closed`。
- HTTP 500：`routes.http_error`（`HTTPException` 且 status=500）与 `routes.internal_error` 均记录完整异常与 traceback 后只返回安全摘要；4xx 记录 WARNING。
- 前端：`static/modules/client-error.js` 收集 `window` 的 `error` 与 `unhandledrejection`，由 `app-controller` 安装，用 sendBeacon（回退 keepalive fetch）上报 `/api/client-errors`；上报自身失败被吞掉，不递归。服务端仅接受 loopback 来源（否则 403 `client_errors_local_only`），白名单字段 `kind/message/source/line/column/stack`（长度上限 64/1024/512/4096，正文 ≤8KB，超限 413 `payload_too_large`），控制字符折叠，不记录请求 headers、cookies 或 prompt；清洗后的单行经 `pdf_reader.client` 记 WARNING，仍受统一脱敏。

### 错误传播

`TranslationError` 与普通异常都被 `generate`/`generate_batch` 捕获并输出 SSE `error` 事件，同时记录上下文日志；任务工作区（根目录，含 `input/` 与 `output/`）只有在 worker 线程确认退出后才会在 `finally` 中整体清理（join timeout 时整体保留并记 WARNING）。

前端装配与翻译 UI 状态（P2-02）：`static/modules/translation-ui-controller.js` 是单页/批量共享的翻译 UI 状态机（idle → running → succeeded/failed/aborted → idle），集中 busy 控件禁用、进度条、stage/status 文本、成功/失败恢复、延时清理与 operation generation 迟到回调隔离；单页与批量差异（范围文案、完成后刷新页集合）通过 operation descriptor/callback 注入，`app.js` 不再复制两套 busy/progress/error DOM 逻辑。每次翻译操作创建 `AbortController` 并把 `signal` 传入 `translator.js` 的 fetch；新操作、成功打开新文档（session dispose）与页面卸载时 abort 浏览器请求并使旧回调失效；浏览器 abort 只终止客户端请求/消费，不是可靠的服务端取消确认，服务端生命周期仍由 SSE 断开与后端机制决定。`static/modules/reader-session.js` 把 zoom/alignment/intersection observer/settle gate/page 生命周期清理收束为幂等 `dispose` 边界：仅在新文档 open 成功、准备替换 DOM 时 dispose 旧 session，失败打开保留旧 session（409 语义不变）。

错误契约（P2-05）：所有 API 4xx/5xx 返回顶层 `{"code": <stable_code>, "error": <safe_message>}`；`409` 保留 `translation_busy`、中文安全提示与 `active_job_id`（P0-02/P1-04 回归依赖），其余 400 分支使用稳定 code（`invalid_file_path`、`invalid_page`、`no_document_opened`、`page_out_of_range`、`invalid_side`、`invalid_page_numbers`、`invalid_page_range`），`403` 使用 `config_local_only`（配置中心 loopback 守卫）与 `client_errors_local_only`（前端错误上报 loopback 守卫），`404` 使用 `not_found`，`413` 使用 `payload_too_large`（前端错误上报正文超限），其它 HTTP 错误使用 `http_<status>`，`500` 固定为 `internal_error`。`routes.http_error` 处理 `HTTPException`（不吞成 500），`routes.internal_error` 记录完整异常（含 traceback）后只返回安全摘要。SSE 统一经 `sse_stream.format_sse_error(code, message)` 输出 `{"type":"error","code","error"}`；上游原始 error、`TranslationError` 消息、普通异常消息与“无翻译结果”均只进服务端日志，不返回浏览器。前端 `static/modules/dom.js` 提供 `showError()`（DOM 节点 + `textContent`），`app.js` 不再使用 `insertAdjacentHTML` 插入错误文本；`static/modules/translator.js` 对非 JSON 响应、网络异常与缺失错误字段使用固定安全 fallback。非 loopback host（非 `localhost`、`127/8`、`::1`）在 `app.main` 中、`app.run` 前输出安全 WARNING（不记录 API Key，不阻止启动）。

## 测试、CI 与验证入口

`pyproject.toml` 是唯一直接依赖声明源（`project.dependencies` 运行依赖、`project.optional-dependencies.dev` 开发工具）；已删除 `requirements.txt`/`requirements-dev.txt`。`requirements.lock` 是 README、CI 和本地安装共同使用的唯一锁文件，由 Python 3.12 与 pip-tools 7.6.1 从 `pyproject.toml`（含 dev extra）生成，header 记录真实命令（用 `CUSTOM_COMPILE_COMMAND` 规避 pip-tools 7.6.1 在本环境写入多余 `--no-index` 的怪癖）。锁文件不包含 editable、本机路径或 `file:///` 来源。安装契约：`pip install -r requirements.lock` 后 `pip install -e . --no-deps`；便捷安装 `pip install -e .[dev]` 与可复现安装明确区分。

统一入口 `scripts/verify.ps1`，顺序为：输出最终 Python 绝对路径与版本并核验 Python `>=3.12`、Node `>=22`（不满足快速失败）→ 密钥扫描（`scripts/secret_scan.py`，只扫 Git 跟踪内容，占位示例放行，匹配值不输出）→ Ruff lint → Ruff format check → coverage（`coverage run --branch -m pytest -q`，全部 Python 测试；`coverage report` + `coverage json` + `scripts/check_coverage_policy.py` 执行全局与关键模块阈值）→ `mypy`（仅 `src/pdf_reader`，`check_untyped_defs`/`no_implicit_optional`/`warn_unused_ignores`/`warn_redundant_casts`/`warn_return_any`/`strict_equality`）→ `npm run lint:js`（ESLint flat config，lint `static/**/*.js` 与正式 `tests/*.mjs`）→ `npm test`（前端套件：`test:ui-copy`、`test:error-safety`、`test:client-error`、`test:translation-ui`、`test:translator`、`test:zoom`、`run-alignment-controller-tests.mjs`、`run-config-panel-tests.mjs`）。脚本接受 `-PythonExecutable` 显式指定验证环境（无效显式路径快速失败、不回退）；未指定时优先使用仓库 `venv`，不存在时回退 PATH 中的 `python` 并输出醒目 WARNING（含实际路径与版本）。本地 coverage 数据写入临时目录并在 finally 清理；设置 `PDF_READER_COVERAGE_ARTIFACT_DIR` 时输出 coverage JSON/XML 到该目录供 CI 上传（`coverage-artifacts/` 已忽略）。P2-01 起测试与运行均从已安装的 `pdf_reader` 包导入：先 `pip install -r requirements.lock` 再 `pip install -e . --no-deps`（CI 同契约），仓库根不再提供生产模块 shim。

覆盖率策略（P2-03）：全局 line ≥90%、branch ≥80%；关键模块独立 floor——`state.py` line 80/branch 75、`translation_coordinator.py` 95/95、`translation_lifecycle.py` 95/95、`sse_stream.py` 85/75、`routes.py` 85/70。实测基线（2026-08-30 日志工程化核验值）：全局 line 94.0%、branch 86.2%，五个关键模块均高于 floor。pytest 声明 `unit`/`integration`/`system` 标记；系统红线（`tests/test_system_concurrency_failure.py`）标记为 `system`，`integration` 标记用于真实路由/磁盘事务测试，但 verify 默认全量收集、不做 marker 排除。

测试隔离：`tests/conftest.py` 在任何应用模块导入前把 `PDF_READER_DATA_ROOT` 指向 pytest 专用临时目录，并在每个测试后调用 `logging_config.reset_logging()` 关闭/移除 handler（会话结束再清理临时目录），因此完整测试不会写入或增长仓库 `logs/`、`cache/`。`tests/test_paths.py` 用两个不同 CWD 的子进程真实构造 `create_app()`，固定 config/glossary/templates/static/logs/cache 的 CWD 无关解析，并覆盖绝对 `cache_dir` 不被重写与 `reset_logging()` 可重建 handler。

上游契约与文档治理回归（P3-06）：`tests/test_upstream_contract.py` 用确定性 fake 验证固定版本、SettingsModel 消费字段与 ENGINE_REGISTRY 字段映射、承诺事件映射与未知事件忽略/心跳、workspace/output 注入与 mono/dual/glossary 路径、协作式取消/迟到丢弃/join 所有权，全部离线且不运行真实翻译；`tests/test_documentation_governance.py` 验证 architecture/project/roadmap 职责边界、常青文档链接可解析、README/architecture/dependency-upgrade 的契约命令一致与易腐数字基线。升级命令 `python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py` 与范围记录在 [依赖升级流程](governance/dependency-upgrade.md) 和 [长期文档治理](governance/documentation.md)。

配置中心回归：`tests/test_config_editor.py` 覆盖 GET 脱敏、PUT 保存与密钥保留、注释/未知字段保留、非法 provider/类型/范围、`openai_compatible` 缺 `base_url`、revision 冲突、原子失败不破坏原文件、环境变量状态与 loopback-only 访问；`tests/run-config-panel-tests.mjs` 覆盖面板打开/关闭、分组与说明、provider 映射、加载/保存、API Key 不回显、错误/成功与重启提示。

缓存生命周期回归（P3-05）：`tests/test_cache_ops.py` 覆盖任务工作区创建（前缀/标记/input/output）、创建中途失败与标记写入失败只清理本次新建目录、崩溃模拟（抽取与输出均在已标记根工作区内）的启动恢复且用户缓存不受影响、统计分类、dry-run/真删边界、未知/无标记/损坏/恶意标记、前缀同名文件与符号链接/junction 保守保留、存活 PID 保留、Windows PID 探测（当前进程 True、明确不存在 False、拒绝访问/未知/查询失败 True、句柄必关）与清理失败报告和 CLI（`stats`/`orphans`/`clean`）契约；`tests/test_sse_stream.py` 覆盖单页/批量共享同一根工作区边界（抽取 input/、输出 output/、标记存在、成功整体删除、join timeout 整体保留）；`tests/test_shutdown.py` 覆盖 coordinator `shutdown` 无任务/完成/超时/幂等/流异常容忍、`AppState.close` 幂等与 Windows 句柄释放、`main` 启动恢复与关闭日志、关闭期间单页/批量翻译被 409 拒绝。

任务日志回归：`tests/test_task_logging.py` 覆盖前缀格式/截断/1-based 页码、跨线程传播、全部生命周期状态序列（成功/失败/断开迟到丢弃/join timeout）、stale-result 与写回失败的任务上下文关联、`SafeFormatter` 与真实 `RotatingFileHandler` 落盘脱敏（sentinel 含 API key、Windows/Unix 路径、HTML；key/token 不落盘，路径保留）。

日志管线与调试轨迹回归（2026-08-30 日志工程化）：`tests/test_logging_config.py` 覆盖四个托管 logger 共享同一对 handler、128 KiB × 5 轮转与 14 天过期备份清理（过期/未过期/无关文件/清理失败降级/不递归）、ISO 行格式与 run_id 生命周期、第三方级别与脱敏、sys/threading excepthook、外部 handler 快照恢复与并发 setup/reset/attach/detach；`tests/test_debug_trace.py` 覆盖 debug 关闭零 IO、2MB × 3 有界轮转（不再生成 timestamp 文件）、job 过滤、start/end/elapsed、失败 traceback 与 handler 创建/关闭失败降级；`tests/test_routes.py` 覆盖 `/api/client-errors` 白名单字段、长度/正文上限、控制字符清洗、loopback 拒绝与脱敏落盘；`tests/run-client-error-tests.mjs` 覆盖前端 `window.error`/`unhandledrejection` 采集、sendBeacon/keepalive fetch 降级、字段截断与上报失败不递归。

启动脚本安全回归：`tests/test_start_bat.py` 在 Windows 下把真实 `start.bat` 复制到 pytest 临时目录，用 fake `netstat.cmd`/`taskkill.cmd`/`python.cmd`/`activate.bat` 在 PATH 上执行真实脚本：断言源文件不含 `taskkill`/`tskill`/`Stop-Process`/`kill` 等终止命令；模拟 5000 被占用时脚本退出非零、不调用 python 也不调用 taskkill；无占用时激活 venv 并调用 `python -m pdf_reader`；`venv` 缺失时给出提示并非零退出。测试不绑定真实端口、不启动服务器、不杀任何进程。

系统级回归：`tests/test_system_concurrency_failure.py` 的用例穿过真实 Flask route、真实 Response/SSE generator、`TranslationCoordinator`、真实 `TranslationStream` worker 线程、`AppState` 与磁盘缓存边界；仅 `translation_orchestrator.do_translate_async_stream` 使用确定性 fake（外部翻译引擎），故障注入只作用于 `tempfile.mkdtemp`、`cache_ops.write_temp_marker`、`pymupdf.Document.save` 与 `os.replace`。覆盖：翻译进行中打开 B 被 409 拒绝且 A 的结果只写回 A；两个 Flask 客户端只有一个任务被接受；SSE 断开后 worker 继续运行/最终失败/join timeout 三条所有权路径；工作区根创建/标记写入与 PDF 保存失败及重试；单页与批量提交失败后的 `right.pdf`/`translated_pages`/渲染恢复；PDF 提交与术语合并的部分提交语义；打开—翻译—渲染闭环的最终 PDF 字节/页内容、`document_id`、coordinator 与 worker 状态、工作区清理断言。

CI（`.github/workflows/ci.yml`）在 `windows-latest` 上安装 Python 3.12 依赖（`pip install -r requirements.lock` + `pip install -e . --no-deps`），执行 `import flask, pymupdf, pdf2zh_next, pdf_reader` 冒烟检查，安装 Node 22 测试依赖（`npm ci`，Node 只承担前端测试且由 `package-lock.json` 锁定），再执行同一 `scripts/verify.ps1`。`tests/README.md` 说明正式测试与历史诊断脚本的区别。

## 当前技术约束与已确认风险

以下只记录当前事实，不构成修复方案或目标设计。

1. **单进程/全局状态。** 服务端只有一个全局 `AppState`，同一时刻只面向一个本地用户、一份打开的文档；没有多用户或并行文档隔离。
2. **SSE 断开有协作式取消但无强制终止。** 消费者断开后，`generate`/`generate_batch` 请求协作式取消并等待 worker 退出（join timeout 30s），任务工作区只在 worker 确认退出后整体删除；join timeout 时工作区整体保留并记 WARNING。不响应取消的上游环节（含 BabelDOC 子进程）仍会运行到自然结束，其结果被丢弃，没有强制 kill 接口。
3. **术语表写入为进程内原子事务。** 读—合并—写受模块级互斥锁保护，新内容经同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交；累计文件损坏或表头缺少 source/target 时中止合并保留旧文件，写入/`os.replace` 失败保留旧文件并清理临时文件；单任务协调器与 `document_id` 阻止跨文档迟到合并。
4. **PNG 无文本层。** 页面以图片显示，没有文本选择、搜索、复制、高亮、批注、目录、内部链接或 OCR 流程。
5. **无队列/暂停/取消/重启续传。** 不存在持久任务队列、暂停、取消、重试队列、进度恢复或进程重启后的翻译续传。
6. **部分提交语义。** 单页/批量翻译结束时先提交 `right.pdf` 再合并术语表；术语表合并失败被包含（记录 WARNING），不会回滚已提交的 PDF，也不改变任务终态；PDF 提交失败则术语合并不执行。不存在跨两个文件的全局事务。
7. **启动脚本不自动释放端口。** `start.bat` 只检测并报告端口 5000 的 `LISTENING` 占用，不包含任何进程终止命令；端口冲突需要用户自行确认归属并处理（命令见 README「启动」），或改用 `config.toml` 中 `[server].port` 指定的其他端口。
8. **临时工作区清理有明确安全边界。** 每个翻译任务拥有 cache 根下带前缀+标记的根工作区（`input/`/`output/`）；只有名称带固定前缀、含有效标记（`kind` 匹配且 `pid` 为正整数）、非符号链接/junction 且 PID 已不存活的 `cache/` 直接子目录才会被启动恢复或 `cache_manage.py clean --yes` 删除；未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保守保留；持久用户数据（`right.pdf`、术语表、阅读进度）永不作为清理目标。Windows PID 探测只读，且只把明确不存在（`ERROR_INVALID_PARAMETER` 等）判为不存活；PID 复用或查询失败时按“可能存活”保留，可能留下少量无法自动清理的目录，需要用户确认后手动处理。

## 上游与历史参考

- 项目长期意图：[project.md](project.md)；未来方向与开放问题：[roadmap.md](roadmap.md)。
- 长期文档治理与事实冲突优先级：[governance/documentation.md](governance/documentation.md)；依赖升级流程：[governance/dependency-upgrade.md](governance/dependency-upgrade.md)。
- 上游接口研究：[pdf2zh-next-development-guide.md](pdf2zh-next-development-guide.md) 与 `docs/reports/` 下两份报告，均按各自顶部标注的版本适用范围阅读。
- 历史系统描述：`docs/archive/`、`docs/superpowers/`、`openspec/` 与 `CHANGELOG.md`，只用于追溯。

归档与版本特定的上游资料是辅助上下文，不是当前实现的事实源；本文档与代码、测试冲突时，以代码和测试为准。
