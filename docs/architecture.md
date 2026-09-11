# PDF Reader 当前架构

> 本文档只描述当前 HEAD 已经实现的系统。代码和测试高于本文档；发现不一致时，必须在同一变更中修正文档。项目意图见 [project.md](project.md)，未来方向见 [roadmap.md](roadmap.md)。

## 核验基线

- 核验日期：2026-09-01。事实来源、锁定版本与测试/覆盖率基线见下。
- 事实来源：CodeGraph（`codegraph explore` / `codegraph node`）输出、当前源码逐行核对、`requirements.lock`、`package.json`、`scripts/verify.py`/`scripts/verify.ps1`、`.github/workflows/ci.yml`、`tests/test_upstream_contract.py` 和测试收集结果。
- 锁定版本：Python 3.12.8、Flask 3.1.3、PyMuPDF 1.25.2、pdf2zh-next 2.9.0、BabelDOC 0.6.2、tomlkit 0.13.3。
- 测试基线：`pytest -q` 实测 1495 个 Python 测试通过（2026-09-01 P2-04 最终核验值，含上游契约、文档治理、日志/配置、P0/P1 术语主线、术语管理 API 与生命周期回归、P2-01 黄金样本与质量门槛、P2-02 术语诊断回归、P2-03 配置收口/旧表兼容/用户文档回归、P2-04 升级治理门回归 36 项）；`package.json` 的 `test:frontend` 定义九个正式前端套件（UI copy、error-safety、client-error、translation-ui、translator、zoom、alignment controller、config panel、glossary panel），verify 全绿。
- 覆盖率基线：全局 line 92.8%、branch 86.6%（2026-09-01 P2-04 最终核验值，`coverage run --branch -m pytest` 实测；策略与关键模块 floor 见“测试、CI 与验证入口”）。
- 基线说明：测试数量与覆盖率是易腐数字，任何新的架构核对都应以当前源码、锁定文件、测试收集结果与 coverage 报告为准；本文数值分别标注核验日期——测试基线为 2026-09-01（P2-04 最终核验值），覆盖率基线为 2026-09-01（P2-04 最终核验值）。

## 系统总览

本项目是一个运行在本机的单 Flask 应用：浏览器打开 `templates/index.html`，通过 HTTP 请求打开本地 PDF，以双栏（左原文、右译文）连续滚动阅读。PDF 页面由服务端用 PyMuPDF 渲染为 PNG 图片返回，浏览器不解析 PDF 本身，也没有文本层。

翻译由 `pdf2zh-next`（底层 BabelDOC）执行：路由层把单页或页码范围抽取为临时 PDF，`sse_stream` 通过 `translation_orchestrator` 的 daemon 线程 + asyncio 事件循环运行上游异步翻译，把进度事件经 `queue.Queue` 转成 SSE 流推给浏览器；P0-05 验证通过后把译文页写回缓存中的 `right.pdf`（旧自动术语合并入口仅作为兼容路径保留，正文已固定关闭上游自动提取）；候选由两阶段服务产出：`prepare` 在严格翻译前，`commit` 在 PDF 提交后。

所有文档级状态集中在唯一的全局 `AppState` 中，由一把非重入锁保护。应用没有持久任务队列、任务注册表、暂停/取消 API 或重启续传状态。

P1-01 起，候选术语提取与正文翻译解耦：正文严格路径固定关闭上游自动提取，
候选由项目自有 `TermExtractionClient` + `CandidateExtractionService` 在正文
提交成功后旁路产出，只写 `term_candidates.json`；用户确认前不影响正文。

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
| Node.js | >=22（仅测试需要，CI 固定 22） | 运行九个前端测试套件 |
| ruff / pytest | 锁定在 `requirements.lock` | 代码检查与 Python 测试 |

## 许可证与包元数据

- 本项目许可证为 **AGPL-3.0-only**：根目录 `LICENSE` 是标准完整 GNU AGPL v3 官方文本（来源 <https://www.gnu.org/licenses/agpl-3.0.txt>），`pyproject.toml` 以 PEP 639 `license = "AGPL-3.0-only"` + `license-files = ["LICENSE"]` 声明，`package.json` 与 `package-lock.json` 根包许可证字段同为 `AGPL-3.0-only`，README 提供许可证与再分发说明并链接治理文档。
- `package.json` 无 `main` 字段，`type: "module"` 与浏览器 ES Modules 前端及 `.mjs` 测试运行器一致（P3-03 已删除无意义入口，P3-04 不再重做 ESM）。
- 固定翻译依赖：`pdf2zh-next==2.9.0` 与 `babeldoc==0.6.2`（`requirements.lock`），两者官方元数据与发行物（PyPI、wheel、GitHub tag LICENSE）均标注 AGPL-3.0；核验日期、精确版本、直链与所见许可证标识记录在 [docs/governance/license.md](governance/license.md)。
- 分发边界：本项目当前面向本地单用户运行；重新分发本项目、与上游组合分发或网络部署前，按实际组合方式单独核验 AGPL 义务（保留版权/许可证/源码提供义务等）。该记录不是法律意见。

## 上游最小契约（P3-06）

- 契约测试入口：`tests/test_upstream_contract.py`（离线、确定性，全部使用 fake 上游流，不联网、不运行真实翻译、不需要 API Key）；升级 pdf2zh-next/BabelDOC 前必须运行（命令见 [依赖升级流程](governance/dependency-upgrade.md)）。
- 升级治理门（P2-04）：`python scripts/upgrade_governance_gate.py` 一键运行静态治理
  检查（依赖来源、任意位置影子包/fork/vendor/上游源码副本/生产 Monkey-patch）与固定
  契约测试选择（依赖契约、上游术语选择、严格正文路径、候选隔离、合规提交门），
  离线且不修改文件；`--static-only` 模式已接入 `scripts/verify.ps1`。
- 固定版本：pdf2zh-next 2.9.0 与 babeldoc 0.6.2 同时受 `pyproject.toml`/`requirements.lock` 与安装元数据约束；babeldoc 是传递依赖，只由 `requirements.lock` 固定。
- SettingsModel 消费面：`basic.debug=False`；`translation` 的 `lang_in`/`lang_out`/`min_text_length`/`qps`/`pool_max_workers`/`term_qps`/`term_pool_max_workers`（两个 term 字段为 1.x 兼容别名，仅兼容转发旧上游 SettingsModel，严格正文路径与项目候选提取不使用，启动 WARNING，计划 2.0.0 移除）/`ignore_cache=True`/`primary_font_family`/`output`（由 SSE 生成器按 attempt 赋值注入）/`custom_system_prompt`（页面 Prompt > `default_system_prompt` > 上游默认）；正文恒为 `no_auto_extract_glossary=True`、`save_auto_extracted_glossary=False`（P0-04，不再由 `translation.auto_extract_glossary` 反转）；`glossaries` 由严格正文路径传入本次 fresh 的单个 `effective_glossary.csv`（零权威行时省略，不再逗号连接多文件）。`pdf` 的 `pages`、固定 `no_dual=True`/`only_include_translated_page=True`/`watermark_output_mode="no_watermark"`，以及 `[pdf2zh]` 已开放的 15 个字段（含项目正确拼写 `formula_*` → 上游历史拼写 `formular_*`）；`translate_engine_settings` 按 `ENGINE_REGISTRY` 的字段映射构造，发送开关按 Provider 映射（OpenAI 使用历史拼写 `openai_send_temprature`，Aliyun/Compatible 使用各自字段）。
- 事件适配边界：本项目只承诺 `progress_start`、`progress_update`、`finish`、`error` 四种上游事件的映射；`progress_end` 等未承诺事件与未知事件被忽略（`format_sse_event` 返回 `None`），worker 空闲心跳（空串）原样透传为 SSE 空行。
- 输出路径边界：`settings.translation.output` 在生成器中注入为任务工作区 `output/` 目录；术语合规重试使用独立 `attempt-2/output/` 目录与 `SettingsModel` 深拷贝，避免污染首次产物。`finish` 结果的 `mono_pdf_path` 优先、缺失时回退 `dual_pdf_path`，`auto_extracted_glossary_path` 直接交给术语合并（仅验证通过后）。
- 取消/流式边界：`do_translate_async_stream(settings, file)` 按两个位置参数调用；`TranslationStream` 的协作式取消、迟到事件丢弃（`late_result_dropped`）、`join(timeout)` 与 `is_alive` 所有权接口是升级契约的一部分。

## 仓库结构与文件职责

| 路径 | 职责 |
|---|---|
| `src/pdf_reader/app.py` | 开发/服务共享的启动边界 `main(argv)`、`create_app(settings)` 装配 Flask 与全局 `AppState`、启动服务；开发入口继续对无效配置快速失败，便携服务则以安全默认 loopback 进入受限首次配置模式；便携服务通过进程私有随机令牌提供 `/api/health` 就绪验证；`src/pdf_reader/__main__.py` 提供 `python -m pdf_reader` 开发入口（导入无副作用，仅 `python -m` 时调用 `main`） |
| `src/pdf_reader/portable_launcher.py` | 顶层 `PDF Reader.exe` 的纯启动器逻辑：保持真实用户环境、从自身位置建立便携布局、以内核单实例锁判定所有权（第二次启动只验证并激活既有实例，绝不启动第二个服务，也不结束他人进程）、只启动 `app/PDF Reader Service.exe`、以 data 内原子就绪描述符和令牌化 loopback 健康检查等待服务、由父进程打开默认浏览器；就绪后固定提供三按钮控制窗口（打开阅读器/打开日志/退出程序），默认窗口不可用时稳定失败并协作关闭服务，只有显式 `--no-ui` 才允许无窗口诊断；退出时先请求服务协作关闭（停止接受新任务 → 取消/等待当前任务 → 关闭 AppState），只有超时才兜底结束本启动器自己启动的进程，启动失败/中断时同样有界 terminate→kill 回收 |
| `src/pdf_reader/portable_instance.py` | 纯标准库单实例协调层（顶层启动器在导入任何应用代码前使用）：Windows 命名互斥体 / POSIX `flock` 是“实例正在运行”的唯一权威，进程死亡即由内核释放，崩溃或强制结束都不会留下陈旧锁；`DATA_ROOT/runtime/instance.json` 只是二次启动激活用的建议性记录（PID、启动器控制端点与令牌、服务端点、健康令牌、服务控制令牌），写入前经 data 物理边界与逐字段严格校验，读取方只有在令牌认证健康探测通过后才信任它，正常退出即删除 |
| `src/pdf_reader/portable_service.py` | `PDF Reader Service.exe` 的延迟导入引导入口：先验证受控子进程环境与冻结私有运行时、准备并安装便携布局，再动态导入 `pdf_reader.app`；引导模块本身不导入 Flask、pdf2zh-next 或 BabelDOC |
| `src/pdf_reader/portable_data.py` | P1-03 便携数据治理（只依赖标准库、`paths` 与 `portable_runtime`，因此启动器可在导入应用/上游代码前调用）：以 `DATA_ROOT/portable-data.json` 为数据格式版本唯一事实（缺字段/未知字段/类型错误一律 fail closed），`prepare_portable_data()` 在取得单实例锁后、启动服务前完成检测与迁移；迁移先备份旧字节到 `data/backups/<时间戳>/files/`，再写同目录 `*.tmp`，最后 `os.replace` 原子提交并追加 `data/backups/migrations.log`；未提交失败会逆序恢复已替换目标（恢复不完整抛 `portable_data_recovery_failed` 并给出手工恢复信息），已提交迁移可 `rollback_last_migration()`/`restore_backup_directory()` 显式回滚；`category_stats()`/`run_cleanup()` 按文档缓存、模型与上游缓存、字体、日志、临时文件分类统计与清理（存在 `data/runtime/instance.json` 时拒绝清理，分类根是 link/junction 时整体拒绝，子项是链接只删链接本身，绝不递归删除 data 之外的用户 PDF）；`import_portable_data()` 只从显式给出且与目标 data 根互不包含的非链接旧 data 根复制非易变数据，`config/`、`logs/`、`temp/`、`runtime/`、`pycache/`、`home/`、迁移备份与清单永不导入 |
| `src/pdf_reader/portable_runtime.py` | 启动器/服务共享的纯标准库进程边界：构造不修改父进程的 child env，清除宿主 Python 覆盖，把虚拟 Home/Temp/缓存映射到 data，并验证冻结私有运行时；每次启动创建并清理带标记的服务 Temp；安全创建、验证和原子写入就绪描述符；提供不依赖 PID 的每次启动内核存活对象（Windows 随机命名 owned mutex + abandoned wait，POSIX 随机文件 `flock`）、服务 watchdog 与陈旧 POSIX 名称清理 |
| `packaging/windows/runtime-requirements.lock` | P0-04 的 Python 3.12 仅运行时依赖闭包：由 `pyproject.toml` 解析并受总 `requirements.lock` 约束，136 个版本必须逐项一致；排除 pytest/coverage/mypy/pip-tools 与 pip/setuptools/wheel，`ruff` 因固定 Gradio/Xsdata 依赖图的运行时要求保留并在发行说明中显式解释 |
| `packaging/windows/runtime_policy.py` | 纯标准库发行策略门：静态扫描生产源码，拒绝导入 pip/ensurepip/venv/setuptools/wheel、拒绝未批准的进程启动和系统 Python/pip 启动；P2 构建后扫描最终 onedir，拒绝系统解释器、安装工具及纯开发包，并校验 `app/runtime-manifest.json` 的 commit、Python 3.12 patch、私有服务哈希、锁文件哈希以及完整包版本/wheel SHA-256 与运行时锁一致 |
| `packaging/windows/data_policy.py` | P1-03 纯标准库发行数据策略门（P2-01 构建时对最终 onedir 执行）：拒绝发行树中的任何 `data/` 内容（空 `data/` 目录骨架允许）、泄漏到顶层的开发目录、用户 `config.toml`、`portable-data.json` 清单、`launcher.log`/`instance.json`/`migrations.log` 打点文件与 `.safetensors`/`.gguf`/`.onnx`/`.ckpt`/`.pt` 模型权重；同时审计用户发行说明，要求同一段内明确“删除整个便携目录会删除配置和缓存”并给出旧 `data` 的复制/受控导入说明 |
| `docs/governance/portable-upstream-write-contract.md` | P0-03 固定版本上游写入清单：BabelDOC 模型/字体/CMap/tiktoken/SQLite、pdf2zh-next 配置与 SQLite、huggingface-hub、Python Temp/pycache 的求值时机、控制方式、data 内目标和失败/取消/崩溃语义；依赖升级门必须同步验证 |
| `src/pdf_reader/cache_ops.py` | 任务临时工作区所有权（每任务 cache 根 workspace：input/output+标记创建与失败清理）、缓存分类、只读统计与孤儿工作区清理：固定前缀/标记校验、Windows 安全 PID 存活探测、dry-run 清理边界与启动恢复 |
| `pyproject.toml` | P2-01/P2-04 可安装包与依赖契约：setuptools src 布局、`project.dependencies` 唯一直接依赖声明、`project.optional-dependencies.dev`（pytest/Ruff/coverage/mypy/pip-tools）、PEP 639 许可证（AGPL-3.0-only + LICENSE） |
| `LICENSE` | 本项目许可证：标准完整 GNU AGPL v3 官方文本（AGPL-3.0-only），与 `pyproject.toml`/`package.json`/`package-lock.json` 声明一致 |
| `docs/governance/license.md` | 本项目与固定上游依赖（pdf2zh-next/BabelDOC）的许可证核验基线、四种使用/分发场景与发布前核验清单（非法律意见） |
| `start.bat` | Windows 启动入口：检查并激活 `.\venv`、检测 5000 端口占用（只报告不杀进程）、运行 `python -m pdf_reader` |
| `src/pdf_reader/config.py` | 读取 `config.toml`、定义冻结运行时配置（`ModelRuntimeConfig`/`TranslationRuntimeConfig`/`Pdf2zhRuntimeConfig`/`CandidateExtractionRuntimeConfig`/`UpstreamRuntimeConfig`）、严格/宽松解析、`EngineSpec`/`ENGINE_REGISTRY`、环境变量与默认值、`GLOSSARY_PATH`；对 1.x 兼容 translation 三键（`auto_extract_glossary`/`term_qps`/`term_pool_max_workers`）输出不含敏感值的启动 WARNING 迁移提示（计划 2.0.0 移除，兼容只限这三键，未知键仍严格拒绝） |
| `src/pdf_reader/config_editor.py` | 配置中心后端：45 字段 schema（分组/控件/说明/默认与常用值/Provider 适用性；三个 1.x 兼容 translation 键不展示、PUT 拒绝写入，磁盘旧键保存时原样保留）、GET 密钥脱敏（只返回 configured/source）、已知字段白名单、复用 `validate_startup_requirements`/`resolve_server_config` 严格校验、便携配置强制 loopback、revision 乐观冲突、模块级 RLock、同目录临时文件 fsync + `os.replace` 原子写并保留权限/未知字段/注释与顺序（tomlkit）；首次配置可用同一 revision 和完整有效表单原子修复 TOML 语法或结构损坏，只写 `config.toml`，不热改冻结 `AppSettings`，保存返回 `restart_required=true` |
| `src/pdf_reader/term_extraction.py` | P1-01/P2-02 项目自有 `TermExtractionClient`：标准库 urllib 走 OpenAI-compatible `/chat/completions`（支持 deepseek/openai/openai_compatible，其余 Provider 稳定 unsupported）、严格受控 JSON 解析（条数/长度/控制字符/正文大小有界）、独立 QPS/timeout/有界重试（只重试超时/429/5xx）、可选 token usage 解析（三字段全部非负 int 才构造 `TokenUsage` 且 `available` 三者全真；缺失/部分/布尔/负值 → unavailable，不伪造），请求/响应/Prompt/Key 不入日志 |
| `src/pdf_reader/candidate_filter.py` | P1-02 候选后置过滤：确定性前后标点清理/异常空白折叠、英文单词/缩写边界感知匹配、小型普通词/功能词/通用学术词精确拒绝、完整句/超词数/超字符/纯数字/公式/变量/页码/占位符结构拒绝、target 必须含 Han 字符、幻觉 source 拒绝、逐页命中页码与有界证据窗口；每条被过滤候选带稳定原因，规则版本 `candidate-filter/1` 组合进候选 `strategy_version`；导出 `FILTER_REASONS` 稳定 reason 白名单供 P2-02 诊断复用；只作用于模型自动候选，绝不删除/降级/重写用户权威决定 |
| `src/pdf_reader/candidate_service.py` | P1-01/P1-02/P1-03/P1-05/P2-02 两阶段候选服务：`prepare` 在严格翻译前读取输入 PDF、模型提取/过滤，返回不可变 `PreparedCandidates`（observations + report + 冻结 identity；带身份时 document_dir 必须等于 identity.document_dir），绝不写 `CandidateStore`；`commit` 只在正文 PDF 成功提交后执行，以 prepared 冻结身份为权威重验 job_id/document_id/pdf_hash/document_dir（目录名必须等于 pdf_hash；另传 identity 必须完全相等、写目录必须等于冻结 identity.document_dir、无身份 prepared 不得升级）再原子写 `CandidateStore`；report 含 proposed/kept(candidates)/filtered(+by_reason)/elapsed_ms/usage 稳定口径（failed 由受控 status 集合计算，不存报告字段），prepare 发 `candidate_prepare` 摘要、commit 的所有返回路径（无 observations/成功/store_failed/identity_rejected）都发 `candidate_commit` 摘要并追加 best-effort 持久状态计数 pending/accepted/rejected（统计失败三者均 unavailable）；单页/批量同规则，任何失败降级安全日志且不阻正文 finish；候选只写 `term_candidates.json`，与 P1-03 `CandidateTermService` 确定性摘要边界同模块，P1-04 管理服务沿用同一推荐排序 |
| `src/pdf_reader/term_diagnostics.py` | P2-02 术语诊断安全摘要与故障隔离：`candidate summary`/`glossary_active_terms`/`compliance_*` 稳定事件文本、event/status/reason 显式常量白名单（未知 → unknown，原始字符串不落日志；过滤 reason 复用 `FILTER_REASONS`）、`candidate_failed_count` 唯一 failed 事实源、usage unavailable 语义、`safe_task_log` 与逐层 fallback——诊断构造/格式化/发射/可选统计异常只降级，绝不影响正文、终态或术语数据；日志字段不含 source/target/evidence/Prompt/凭据 |
| `src/pdf_reader/paths.py` | 开发/便携共享的不可变 `RuntimeLayout`：显式区分 `RESOURCE_ROOT`/`PORTABLE_ROOT`/`DATA_ROOT`，从顶层 EXE 而非 CWD 解析便携根，集中提供 config/glossary/templates/static/logs/cache/temp 位置、便携目录准备与可写探针、稳定路径错误码，以及解析物理路径后的 data 边界守卫；开发态保持原环境变量与绝对 cache 兼容，便携态拒绝任意目录外 cache、`..`、symlink 和 junction 逃逸 |
| `src/pdf_reader/task_logging.py` | 集中任务日志上下文：不可变 `TaskContext`、`contextvars` 传播、统一前缀/截断（doc 8/hash 12/可选 glossary revision 12）/1-based 页码、生命周期状态、`SafeFormatter` 脱敏（API Key、sk-/Bearer、api_key、prompt 类字段） |
| `src/pdf_reader/routes.py` | Blueprint HTTP/SSE 端点（含配置中心、首次配置状态、术语管理与前端错误上报）；统一 JSON 错误契约（`code`+`error`）、404/HTTPException/500 处理器，术语/配置/错误上报 loopback-only 守卫，以及翻译与术语写入共享的 active-job 互斥边界；首次配置时全局 guard 只允许根页面、静态资源、`/api/config`、`/api/setup/status` 和令牌化健康接口，其余 API 固定返回 503 `setup_required` |
| `src/pdf_reader/state.py` | `AppState`：不可变文档会话身份、锁内翻译快照、左右文档、缓存路径、哈希、页数/尺寸、翻译页集合、阅读进度、非重入锁 |
| `scripts/cache_manage.py` | 缓存只读统计与孤儿临时工作区清理 CLI：`stats`（只读/可 `--json`）、`orphans`、`clean`（默认 dry-run，`--yes` 才删除） |
| `scripts/portable_data.py` | P1-03 便携数据治理 CLI：`status`（只读显示数据格式版本、迁移备份数与文档缓存/模型与上游缓存/字体/日志/临时文件的大小、文件数与删除后果）、`clean --category ...`/`--all`（默认只预览，`--yes` 才删除）、`import --from OLD_DATA`（默认只预览，`--yes` 才复制，`--overwrite` 才覆盖同名文件）、`rollback [--backup DIR]`（必须 `--yes`）；`--portable-root` 用于对指定便携根诊断，稳定错误码原样透出 |
| `src/pdf_reader/file_hash.py` | `sha256()` 流式文件哈希 |
| `src/pdf_reader/pdf_renderer.py` | `render_page()` 在锁内渲染页面为 PNG |
| `src/pdf_reader/pdf_extraction.py` | `extract_single_page()` / `extract_pages()` 在锁内抽取临时输入 PDF |
| `src/pdf_reader/engine_resolver.py` | `resolve_engine()`（未知 Provider 抛 `ConfigError`）与 `build_engine_kwargs(spec, model_cfg)`（显式接收 `ModelRuntimeConfig`） |
| `src/pdf_reader/translation_settings.py` | `build_settings(upstream, ...)` 显式接收 `UpstreamRuntimeConfig` 组装 pdf2zh-next `SettingsModel` |
| `src/pdf_reader/translation_orchestrator.py` | `TranslationStream`：daemon worker 线程 + asyncio 循环（含事件循环异常处理）+ 事件队列 + 协作式取消；`run_translation()` 工厂 |
| `src/pdf_reader/translation_coordinator.py` | 单槽 `TranslationCoordinator`：线程安全的 active job、任务身份、409 互斥与 finish/fail/cancel 幂等释放 |
| `src/pdf_reader/sse_stream.py` | SSE 格式化、`generate()` / `generate_batch()`、P0-05 提交门（提交前术语合规验证、一次整页/整批有界重试、独立 attempt 目录、`glossary_compliance_failed`/`glossary_verification_unavailable`）、P2-02 稳定合规事件日志（`glossary_active_terms`/`compliance_pass`/`compliance_fail`/`compliance_unknown`/`compliance_unavailable`/`compliance_retry_scheduled`/`compliance_failed_final`，均经 `_safe_diagnostics` 故障隔离）、P1-05 两阶段候选（`prepare` 在严格翻译前、失败降级正文继续；`commit` 在 PDF 提交后、失败不反转 finished；请求带 `CandidateIdentity` 与 active-job provider，prepare 冻结身份、commit 以冻结身份为权威并记录候选降级状态）、`STAGE_LABELS`、worker 退出确认后的任务工作区清理 |
| `src/pdf_reader/translation_lifecycle.py` | `finish_translation()` / `merge_glossary_only()`：译文持久化与术语合并 |
| `src/pdf_reader/glossary_service.py` | 累积术语路径解析与合并入口 |
| `src/pdf_reader/glossary_management.py` | P1-04 单文档术语管理服务：复合 revision、权威/候选搜索排序分页、CRUD/接受/拒绝/锁定、CSV 安全导入导出与变更后有效词表重编译 |
| `src/pdf_reader/glossary_merger.py` | 术语多数投票合并：模块级互斥锁 + cumulative 路径共享锁（与迁移同快照）+ 同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交（BOM 安全读写） |
| `src/pdf_reader/term_model.py` | P0-02/P1-03 术语状态模型：权威/候选/拒绝语义、source key 规范化、候选 schema 版本、target 级统计字段、确定性推荐排序与摘要形状、受保护文件名与共享错误 |
| `src/pdf_reader/path_locks.py` | P0-02 按规范路径共享的进程内可重入互斥锁（RLock，`lock_for_path`），同一文档路径的所有 Store 实例复用同一锁，允许同线程嵌套加锁（编译在输入锁内调用 Store.load 并计算摘要） |
| `src/pdf_reader/user_glossary.py` | P0-02 文档级权威术语存储 `user_glossary.csv`（schema v1、按规范路径共享锁、revision、锁定、严格校验）与全局 `docs/glossary.csv` 只读加载 |
| `src/pdf_reader/candidate_store.py` | P0-02/P1-03/P1-04 候选术语存储 `term_candidates.json`（schema v3 + v1/v2 兼容读取/写时升级、观察合并、target 级真实统计与确定性推荐、accept/reject/lock 状态保护、legacy 合入迁移、严格校验、原子读写、候选摘要） |
| `src/pdf_reader/legacy_migration.py` | P0-02 旧 `cumulative_glossary.csv` → 候选存储的幂等合入迁移（保留用户状态、备份不覆盖、失败原样） |
| `src/pdf_reader/glossary_compiler.py` | P0-03 确定性有效词表编译：文档权威 > accepted 候选 > 全局优先级、输入锁内一致快照摘要、同级冲突 fail-closed、CSV + sidecar 原子成对提交、固定名临时文件在输出路径锁内清理（并发编译不互删暂存）、严格 sidecar 校验与 stale 检测 |
| `src/pdf_reader/strict_glossary.py` | P0-04 严格正文术语路径：迁移→编译→验证的单一准备入口、活跃词条边界匹配与约束 Prompt 合成 |
| `src/pdf_reader/terminology_compliance.py` | P0-05 独立验证模块：纯文本判定核心 `verify_translated_text`（规范化 + 逐条 pass/fail/unknown）与 PyMuPDF 提取包装 `verify_translated_pdf`（路径/页数/提取异常/空文本边界，委托纯函数）、有界确定性重试纠错块合成 |
| `src/pdf_reader/term_quality.py` | P2-01 离线术语质量评测：黄金样本 fixture 校验（必需维度/AD-TCS 边界/合规三分支/两条存储主路径/provenance 元数据 fail-closed）、解析/后置过滤/合规/候选存储边界复用、candidate precision 与 candidate_target_accuracy 分离考核、版本化 metric_definitions、阈值与基线键集合/类型/有限性校验、fixture_sha256 防漂移、确定性报告（不联网、不需要 API Key、只写调用方临时目录） |
| `src/pdf_reader/logging_config.py` | 统一日志管线：同一对控制台 + `logs/pdf_reader.log` 轮转 handler 托管 `pdf_reader`/`werkzeug`/`pdf2zh_next`/`babeldoc`、ISO 元数据行格式与 run_id、sys/threading 未捕获异常钩子、reset 快照恢复 |
| `src/pdf_reader/debug_trace.py` | 按任务的有界调试会话：`cache/<hash>/debug_trace.log`（2MB × 3，job 过滤，start/end/elapsed/traceback），debug 关闭时零 IO |
| `templates/index.html` | 唯一 HTML 页面：打开区、双栏、工具栏、始终可见的“配置”按钮 |
| `static/app.js` | 前端入口与共享状态 |
| `static/modules/` | app-controller、client-error、dom、lazy-loader、scroll-sync、alignment-controller、zoom、sse-client、stages、translator、translation-ui-controller、reader-session、config-panel |
| `static/style.css` | 深色主题、双栏与缩放 CSS 变量 |
| `tests/test_upstream_contract.py` | P3-06 上游最小契约：固定版本、SettingsModel 消费字段/引擎字段映射、事件映射与未知事件忽略、输出路径与 mono→dual/glossary、协作式取消与 join/is_alive 所有权（离线确定性 fake） |
| `tests/test_documentation_governance.py` | P3-06 文档治理：常青文档职责边界、链接可解析、上游契约命令一致、易腐数字基线 |
| `tests/test_upgrade_governance_gate.py` | P2-04 升级治理门回归：违规 fixture 证明依赖来源/影子包/fork/vendor/源码副本/生产 Monkey-patch 检测确实能抓到问题，合法 tests patch 与 venv/node_modules/缓存不误报，契约测试选择与 verify.ps1/CI/文档关系固定不漂移 |
| `tests/` | pytest 文件（含 P2-07 路径、P2-06 任务日志、P2-01 包布局、P2-03 契约、P2-04 升级治理门回归、P3-04 许可证、P3-05 缓存与关闭、P3-06 上游契约/文档治理、P3-07 密钥扫描与仓库治理、P0-03 有效词表编译、日志管线/调试轨迹/前端错误上报、配置示例契约、配置中心后端用例、P2-01 黄金样本/质量门槛）与前端 `.mjs` 测试运行器（含 client-error 与 config panel 用例） |
| `tests/fixtures/term_quality/fixture.json` | P2-01 版本化黄金样本：三类最小文本 fixture、AGPL-3.0-only 原创/合成 provenance 元数据、人工核心术语/普通词/缩写边界/同义形式标注、模型响应与解析/过滤期望、合规三分支案例与 wrong-first/rejected 两条候选存储场景 |
| `scripts/term_quality_gate.py` | P2-01 独立稳定质量门：确定性 JSON 报告（含 metric_definitions）、阈值与基线漂移/哈希检查、非法 `--tolerance` 稳定返回 usage code、非零退出、`--update-baseline` 原子更新版本化基线 |
| `scripts/upgrade_governance_gate.py` | P2-04 上游升级与无补丁治理门：pyproject/requirements.lock 依赖来源治理（禁 VCS/editable/path/URL/未锁定）、全工作树影子包/fork/vendor/上游源码副本/补丁目录扫描、`src/pdf_reader` 生产 Monkey-patch 扫描、固定契约测试选择；`--static-only` 供 verify.ps1，完整模式升级前后运行，离线不修改文件 |
| `docs/reports/term-quality-baseline.json` | P2-01 版本化基线报告：当前 HEAD 的指标/阈值/metric_definitions_version/fixture_sha256 快照，供 Prompt/过滤规则变化前后对比与漂移检测 |
| `scripts/verify.py` | 跨平台公共验证编排（依赖导入、pip check、密钥扫描、升级治理门静态检查、便携运行时策略、Ruff lint/format、coverage run/report/json+policy、术语质量门、mypy、npm audit、ESLint、前端测试；失败即停；coverage 产物入临时目录或 `PDF_READER_COVERAGE_ARTIFACT_DIR`，不在仓库根残留） |
| `scripts/verify.ps1` | Windows 启动器：解析并校验 Python 解释器后用 `python scripts/verify.py` 委托公共验证并传播退出码；保留 `-PythonExecutable` 与 `PDF_READER_COVERAGE_ARTIFACT_DIR` 外部调用方式 |
| `scripts/secret_scan.py` | 高可信密钥扫描：只扫 Git 跟踪内容，占位示例放行，不输出 secret 值 |
| `.github/workflows/ci.yml` | Windows + Python 3.12 + Node 22 的 CI |
| `.github/dependabot.yml` | pip/npm 月度依赖升级 PR |
| `docs/governance/documentation.md` | 三份长期文档的更新时机、上游升级步骤、易腐数字政策与事实冲突优先级 |
| `docs/governance/` | 文档治理、工具目录治理、依赖升级流程与许可证核验基线（非法律意见） |
| `docs/`、`docs/archive/`、`docs/reports/` | 常青文档、历史归档与上游研究资料 |

## 术语状态模型与缓存组成（P0-02/P0-03/P0-04/P1-03/P1-04）

P0-02 起，术语持久化按“用户决定”和“模型候选”两类语义分离，自动流程不得跨类写入：

- `docs/glossary.csv`：全局用户权威术语，保留现有 `source,target` 手工入口。
  `user_glossary.load_global_glossary` 只读加载为 `scope=global`、未锁定记录；
  文件损坏时抛 `TermStoreError`，调用方必须中止，不静默丢弃用户决定。
- `cache/<pdf_hash>/user_glossary.csv`：当前文档用户权威术语，由
  `UserGlossaryStore` 独占读写。首行为 `# schema_version=1; revision=N` 注释头，
  随后为 `source,target,locked,created_at,updated_at,note` 表头；`locked=true`
  的词条拒绝编辑/删除，必须先解锁。读—改—写在按规范路径共享的进程内互斥锁
  （`path_locks.lock_for_path`）内执行，同一文档的多个 Store 实例互斥，新内容
  经同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交；乐观 revision
  冲突抛 `GlossaryRevisionConflictError`，锁定词条抛 `GlossaryLockedError`。
  持久文件读取 fail closed：表头必须精确匹配、`locked` 只接受
  `true`/`false`、重复规范化 source 与缺字段/坏时间戳都拒绝加载并保留原字节。
- `cache/<pdf_hash>/term_candidates.json`：自动候选存储，由 `CandidateStore`
  独占读写，同一文档的多个实例共享同一路径锁。当前写入 schema v3 顶层含
  `schema_version/revision/updated_at`，条目按规范化 source key 索引，保存
  原始 source、状态（`candidate`/`rejected`/`accepted`）、条目级首次与最近
  观察时间、策略版本、多个 target 建议、用户接受的最终 target 与被拒绝
  target 列表；P1-04 为已接受候选增加 `locked` 用户决定，锁定后拒绝修改
  accepted target 或改为 rejected，自动观察仍只能更新统计。P1-03 起每个 target 建议持久保存真实观察次数
  （`observations`）、去重页码（`pages`，不同页覆盖数可由
  `distinct_page_count` 审计）与 target 级最近观察时间（`last_observed_at`）；
  同一批 `record_observations` 先按（规范化 source、target、页码、证据）
  确定性排序再合并，同一批任意排列得到相同统计、target 时间与持久化字节，
  并发往返不再退化为 1 票。推荐排序固定为：accepted target 最高优先 >
  普通未拒绝建议 > rejected target；组内按不同页覆盖数降序 → 观察次数降序
  → target 字典序升序，与批输入/线程完成顺序无关。`accept(source,
  target=None)` 使用该确定性首选；显式 `accepted_target` 后即使其他自动
  建议统计更高也不改写。source 整体 rejected 的 target 全部默认抑制
  （摘要 `suppressed=True`），后台观察计数/页覆盖/最近观察时间仍继续增长；
  自动流程唯一写入口 `record_observation`/`record_observations` 只合并观察，
  永不改变状态、`accepted_target`、`locked` 或拒绝记录。schema v1/v2 文件
  仍严格读取（v1 target 时间以条目 `last_seen_at` 回填，v1/v2 的 locked
  默认为 false），下一次写入原子升级为 v3；持久
  文件读取 fail closed：字段缺失/类型异常、normalized key 与 source 不一致、
  重复规范化 source、accepted/rejected 状态与 accepted_target 不一致、无效
  pages/evidence/rejected_targets、v2/v3 缺/坏 target `last_observed_at`、非布尔
  locked、非 accepted 条目却 locked、损坏
  migration 标记或未知 schema 版本都拒绝加载并保留原字节，绝不静默过滤/
  更正后写回。`CandidateStore.candidate_summaries()`/`target_summaries(source)`
  与 `CandidateTermService` 提供确定性服务层摘要：target、用户状态/是否默认
  抑制、observations、distinct page count/pages、last observed time 与推荐
  顺序。
- `cache/<pdf_hash>/cumulative_glossary.csv`：旧自动累计词表，兼容期内仍由现有
  合并管线维护。`merge_glossary_csvs` 与迁移共用 cumulative 路径锁，读取与
  `os.replace` 提交全程互斥，保证迁移看到的 rows 与备份来源是同一快照。
  `legacy_migration.migrate_legacy_cumulative` 在 cumulative 锁内读取旧文件，
  再在候选路径锁内合入（锁顺序固定 cumulative → candidate，不会成环）：
  旧行追加/累加 target 观察，已有
  candidate/accepted/rejected 状态、accepted_target 与 rejected_targets 保持不变；
  成功合入后写入 `legacy_migration` 标记，只有已存在成功标记才 noop。恢复副本
  `cumulative_glossary.csv.bak` 在合入前原子创建，已有副本绝不覆盖；失败时旧
  文件原样保留、不产生半备份或半迁移文件。
- `cache/<pdf_hash>/effective_glossary.csv`：P0-03 确定性编译产物，由
  `glossary_compiler.compile_effective_glossary` 从权威输入生成，只含用户定义
  或确认的词条；格式保持上游兼容的 `source,target` CSV（无注释头，空词表也
  只有表头行）。优先级固定为：当前文档 `user_glossary.csv`（locked 或用户
  定义）> `term_candidates.json` 中 `status=accepted` 的 `accepted_target`
  > 全局 `docs/glossary.csv`；高优先级按规范化 source key 覆盖低优先级，
  输出保留获胜记录的原始 source 展示文本。比较只统一英文大小写与连续空白
  （`term_model.normalize_source_key`），不合并单复数、连字符、缩写/全称。
  同一优先级同一规范化 source 出现不同 target 抛 `GlossaryCompileError`
  fail closed，相同 target 确定性去重；candidate/rejected 无论观察次数都不
  进入。输出按规范化 key 排序，相同输入重复编译字节一致；删除产物后可随时
  从输入重建。
- `cache/<pdf_hash>/effective_glossary.meta.json`：与 CSV 同目录的确定性
  sidecar（schema v1、`glossary-compiler/1`），只记录输入文件存在性/
  revision/行数/SHA-256 与输出 filename/SHA-256/行数，不含时间戳、Prompt、
  正文或凭据。编译在 effective CSV 路径共享锁内完成（锁顺序：输出锁 → 输入
  Store 锁，当前无反向持锁路径）；每个输入的“解析内容 + revision/rows +
  字节 SHA-256”都在该输入路径的 RLock 内取得（Store.load 与哈希嵌套在同一
  锁内），sidecar 记录的是实际参与本次编译的字节摘要，不读取编译后的新版本。
  CSV 与 sidecar 各经同目录临时文件 flush/fsync/close 后 `os.replace`
  提交：先替换 CSV、再替换 sidecar，sidecar 失败时从备份临时文件回滚 CSV，
  尽量保持“旧 CSV + 旧 sidecar”整体不变；回滚也失败时抛
  `inconsistent=True` 的 `GlossaryCompileError` 并清理临时文件。输入损坏时
  拒绝覆盖旧产物。
- 验证与读取语义（P0-03）：`verify_effective_glossary(document_dir,
  global_glossary=None)` 在 effective CSV 锁内严格校验 sidecar（顶层/
  inputs/output 键精确、present/rows/revision/sha256/accepted_projection
  类型与取值严格），严格解析真实 CSV 并核对行数与 SHA-256，再用各输入锁取得
  当前一致快照与 sidecar 记录比较。freshness 规则：user/global 比较完整
  摘要；candidate 只比较 accepted 投影（仅 `status=accepted` 的 normalized
  source + accepted_target 的 rows + sha256），完整文件摘要保留在 sidecar
  中仅作历史审计。candidate/rejected 的新增、观察次数/页码/证据/策略/
  last_seen 变化不报告 stale；accepted 新增、accepted_target 修改或
  accepted→rejected/candidate 才抛 `GlossaryStaleError`，候选文件损坏时
  读取本身 fail closed。`load_effective_glossary(document_dir,
  global_glossary=None)` 不绕过 sidecar：产物对存在时先在同一锁内验证再返回
  严格校验后的行；CSV/sidecar 任一缺失或损坏都报错，只有两者都不存在时才
  返回空表（尚未编译）。

P1-04 管理边界：`GlossaryManagementService` 把文档用户词表、候选存储与有效
词表编译器组合成单文档服务。列表支持权威/候选分视图、source/target 搜索、
白名单排序和有界分页；候选响应包含 target 级观察次数、1-based 命中页码与
有界证据。每个响应返回复合 revision `{user, candidates}`；每次写操作必须同时
携带两份期望 revision，并在按规范路径排序取得 user/candidate 两把 RLock 后再次
核对，两个标签页或自动观察产生的过期写入返回 409，绝不静默覆盖。写操作还必须
携带当前 `document_id`，并经 `AppState.with_document_cache` 在状态锁内保持文档
身份与缓存目录稳定；存在 active translation job 时所有术语写端点先返回
`translation_busy`，避免翻译期间替换其有效词表输入。正常变更释放输入锁后调用
`compile_effective_glossary` 原子重编译；若用户决定已持久化但编译失败，API 返回
`glossary_compile_failed`、`decision_saved=true` 与最新 revision，前端刷新真实
状态并明确提示，不把部分失败伪装成成功。

管理输入限制为 source 200、target/note 500 字符；拒绝 C0/C1 控制字符及
`= + - @` 开头的 CSV 公式载荷。导入只接受 `source,target` 加可选
`locked,note`，最多 1 MiB/1000 行，整批校验后由 `UserGlossaryStore.add_many`
单 revision 原子追加；任一坏行、批内重复或已有 source 冲突会整批拒绝。导出
只导出当前文档用户术语，并对历史不安全值 fail closed；全局
`docs/glossary.csv` 继续是只读展示和现有手工编辑入口。API 错误只返回稳定短码
和固定安全摘要，不回显 source/target、证据、Prompt 或存储异常原文。

 严格正文路径（P0-04/P1-05）：单页/批量路由先调用 `coordinator.start(...)` 原子占用
 任务槽，成功后才执行 `strict_glossary.prepare_strict_translation_context(
  snapshot, job_id=job.job_id)`
（旧 `cumulative_glossary.csv` 幂等迁移只合入候选 → `compile_effective_glossary`
→ `verify_effective_glossary`）；busy/shutdown 在任何严格术语准备写操作前返回
HTTP 409。准备或设置构建失败时路由调用 `coordinator.fail(job_id)` 释放任务槽、
 返回 HTTP 500 `glossary_prepare_failed`，不调用上游，也不留下活动任务。该函数
 断言 `snapshot.glossary_cache_path.name == snapshot.pdf_hash`，并把 `document_id`、
 `pdf_hash`、`job_id`、本次验证通过的有效词表快照、`effective_glossary_revision`
 （已验证 sidecar 的 `meta_sha256`，不依赖路径或 mtime）与
 `effective_glossary_summary`（有效词条列表的确定性 SHA-256）一起封进
 `StrictTranslationContext`；SSE 生成器只消费该预构建上下文，并在抽取/上游前校验
 其身份（含 job_id）与 `task_ctx.document_id`/`task_ctx.pdf_hash`/
 `glossary_cache_path` 一致，不一致时
安全失败；迟到任务不会重新编译或写入其他文档。`build_settings` 对正文固定
`no_auto_extract_glossary=True`、`save_auto_extracted_glossary=False`（不再由
`translation.auto_extract_glossary` 反转），`glossaries` 只来自本次 fresh 的
`effective_glossary.csv`（零权威行时安全省略）。`generate`/`generate_batch` 在
抽取真实输入 PDF 后调用 `strict_glossary.resolve_active_terms_from_pdf`（兼容
入口 `apply_active_terms_from_pdf` 保留给既有调用/测试）：本地匹配大小写不
敏感、连续空白等价、英文 token 边界；`AD` 不命中
`adherence`/`adverse`/`shadow`，不自动合并单复数/连字符/缩写全称；只把当前页/
批次实际命中的活跃权威词条以 `[权威术语约束]` 块追加到 `custom_system_prompt`
之后，用户 Prompt 保留在块前且块声明不可被页面 Prompt 覆盖；无命中不修改
Prompt（available+empty 零成本跳过合规门），源文本不可用时解析结果为
unavailable，由 P0-05 提交门在调用上游前拒绝（有效词表仍经 `glossaries` 传入
仅描述词表输入，不构成验证通过声明）。约束块使用 JSON
编码 source/target，并按 32 KiB UTF-8 确定性上限整行纳入、超限条目只报告省略
数量；不记录正文、Prompt、异常原文、本地路径或凭据。

两阶段候选提取（P1-01/P1-05）：候选收集已从正文翻译解耦为项目自有服务，
`create_app` 装配 `CandidateExtractionService`（消费冻结
`CandidateExtractionRuntimeConfig` 与正文 `ModelRuntimeConfig`）。单页/批量共享
严格阶段顺序：输入/活跃词条 → 候选 `prepare` → `run_translation` →
合规/有界重试 → 提交 PDF → 候选 `commit` → SSE finish。`prepare` 在严格翻译前
用 PyMuPDF 读取本次已抽取输入 PDF 的源文本（1-based 页码、空文本跳过、超限按
前缀确定性截断），返回不可变 `PreparedCandidates`（observations + report +
冻结 identity），
绝不写 `CandidateStore`；正文失败、合规失败、PDF 提交失败、断开/取消路径可已
prepare 但绝不 commit，已 prepare 候选只存在于内存并随工作区丢弃。`commit` 只在
P0-05 合规门通过、`right.pdf` 提交成功后同步调用，重验 active job 身份后经
`CandidateStore.record_observations` 批量原子写入 `term_candidates.json`（一次
响应整体合法后单 revision 合并，任一观察非法则整体不写），保留
accepted/rejected 状态与 `accepted_target`。
通过 `TermExtractionClient` 走 OpenAI-compatible `/chat/completions` 受控
请求；`deepseek`/`openai` 使用官方默认 base URL（可被 `model.base_url` 覆盖），
`openai_compatible` 必须使用配置 base_url。base_url 经 `urllib.parse` 严格
校验：只接受 http/https 且带 netloc，拒绝 userinfo/query/fragment；
`/v1`、`/v1/` 拼成 `/v1/chat/completions`，已是 `/chat/completions` 保持
不变。客户端自身按 `max_input_chars` 前缀截断；响应只解析
`{"terms":[{"source","target"}]}`：≤50 条、字段 ≤200 字符、拒绝控制字符/
无效结构/未知键，正文 ≤256 KiB，重复项确定性去重，成功与错误响应均显式
close；网络重试只针对超时/429/5xx（连接类错误、4xx 与解析/schema 错误不
重试）；QPS、并发（信号量上限）、timeout 均独立于正文。P1-02 起，保留
候选先经 `candidate_filter` 确定性后置过滤：普通词/完整句/超限/纯数字/公式/变量/
页码/占位符/无 Han target/不存在于实际发送文本（含截断后）的幻觉 source 被
拒绝；每条保留候选携带边界感知匹配的实际命中页（1-based，可跨多页）与
折叠空白后的有界证据片段（固定窗口、最多 5 条、每条 ≤160 字符）。候选变化不
触发有效词表 stale，未确认候选永不进入 `effective_glossary.csv` 或正文
`SettingsModel`；网络/解析/存储失败及不支持 Provider 全部降级为安全日志，
正文仍 finish，不启动第二个 coordinator job，同步首版无悬挂线程。P1-05 起，
请求携带 `CandidateIdentity(job_id/document_id/pdf_hash/document_dir)` 与
`active_job_provider`；`prepare` 在网络请求前校验当前 active job 并把请求身份
冻结进 `PreparedCandidates`（带身份时 `document_dir` 必须等于
`identity.document_dir`，否则直接 `identity_rejected`），`commit` 在
`CandidateStore.record_observations` 写入前以冻结身份为权威再次校验——另传
identity 必须完全相等、写目录必须等于冻结 `identity.document_dir`、active job
仍为同一 job/document/pdf_hash（目录名必须等于 pdf_hash），且无身份 prepared
禁止在 commit 升级为带身份。身份拒绝、存储失败只记录稳定降级状态
（`identity_rejected`/`store_failed`），已提交正文与任务终态保持不变；迟到或
串写候选不会写入其他文档。

术语合规提交门（P0-05）：`generate`/`generate_batch` 在 `replace_page`/
`replace_pages` 之前对最终候选译文 PDF 做项目侧验证。验证输入是“当前页/批次
实际命中”的活跃权威 source→target（与送入 Prompt 的活跃词条同一份）；从
`translate_result` 选择 `mono_pdf_path`（缺失时回退 `dual_pdf_path`），用
PyMuPDF 提取译文文本。实现分两层：提取包装 `verify_translated_pdf` 只处理
路径/页数/提取异常/空文本边界，纯文本判定核心 `verify_translated_text` 负责
规范化空白/断行（CJK 相邻字符间空白移除、其余连续空白折叠为单空格）与逐条
判定。英文→中文默认范围下，对每个活跃 target 做精确检查：纯 ASCII
词形 target 按英文 token 边界匹配，其余按规范化精确子串匹配；不做任何 PDF
字符串替换。任何 FAIL 使整体 FAIL；无 FAIL 但出现无法提取/缺页/空文本/页数
不符时整体 UNKNOWN（fail-closed，绝不伪称通过）；全部命中才 PASS。无活跃词条
时完全跳过验证与重试成本。源侧同样 fail-closed：`resolve_active_terms_from_pdf`
显式区分 available/unavailable——rows 为空（`no_rows`）或源文本成功且无命中
（`no_hits`）为 available+empty 并零成本跳过验证；源 PDF 打不开/抽取异常
（`source_extraction_failed`）或抽取文本为空且存在 effective rows
（`empty_source_text`）为 unavailable，单页/batch 在调用上游前发
`glossary_verification_unavailable`，不 `run_translation`、不 replace、不 merge、
job failed，绝不把源侧不可用误当“无活跃术语”。首次 FAIL 在同一
job/document identity 下复用同一
输入 PDF、严格上下文、活跃词条与 task identity 做 1 次整页/整批有界重试，不
启动第二个 coordinator job；重试 Settings 是独立深拷贝，输出目录为
`attempt-2/output/`，最终 system prompt 在原权威约束块之后追加确定性、有界的
`[术语合规纠错]` 块（16 KiB UTF-8 上限，整行纳入、超限只报告省略数量，不截断
映射半行，不丢失原权威块）。首次/重试 worker 均各自 register/unregister 并
在最终清理前确认退出。只有 PASS 才提交（单页 `finish_translation`、批量
`replace_pages` + `merge_glossary_only`）；FAIL/UNKNOWN 路径不提交、不 merge
任何自动词表、旧 `right.pdf` 字节不变。最终 FAIL 发稳定 SSE
`glossary_compliance_failed`，无法可靠提取/验证发
`glossary_verification_unavailable`，之后 job 以 failed 释放且不再发 finish；
上游普通失败仍保持 `translation_error`。合规日志只记录 job/page/attempt/
数量/状态/稳定短码，不记录术语正文、target、译文路径或异常原文。

输入冻结边界（P1-05）：`coordinator.start` 先于严格术语准备占位，job_id 随
`StrictTranslationContext` 一起冻结，因此当前翻译生产者从占位到 SSE 结束期间
不能插入文档切换，也不会重新编译其他文档。P1-04 术语编辑 API 沿用同一活动
任务边界：活动翻译任务期间拒绝修改权威/候选输入，避免正在被 SSE 消费的
`StrictTranslationContext` 与磁盘输入之间出现未定义竞态；候选提交前还会再次
校验 active job 身份，身份不一致的迟到候选不落盘。

路径控制：文档级存储只接受 64 位小写十六进制 PDF 哈希目录名
（`user_glossary.validate_document_dir`），文件名固定。自动合并入口
`merge_glossary_csvs` 拒绝写入受保护文件名（`user_glossary.csv`、
`effective_glossary.csv`、`glossary.csv`、`term_candidates.json`）；自动流程
没有任何改写权威/锁定词条的写入口。

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

### 运行布局与写入边界

- 未显式安装布局时，`paths.get_runtime_layout()` 即时返回开发布局：资源根仍由仓库
  `config.example.toml` 标记或绝对 `PDF_READER_ROOT` 解析，数据根仍由绝对
  `PDF_READER_DATA_ROOT` 覆盖或默认等于资源根。因此现有 `start.bat`、
  `python -m pdf_reader`、仓库 `config.toml`、`cache/` 与 `logs/` 的位置不变。
- 便携入口使用 `RuntimeLayout.portable_from_executable(<顶层 PDF Reader.exe>)`
  构造布局，并必须在导入 `config`、`logging_config` 与翻译依赖前调用
  `install_runtime_layout()` 和 `prepare_runtime_layout()`。便携根固定为顶层 EXE
  的父目录，资源根固定为 `PORTABLE_ROOT/app`，数据根固定为
  `PORTABLE_ROOT/data`；CWD、`PDF_READER_ROOT` 与 `PDF_READER_DATA_ROOT` 均不能
  改写已安装的便携布局。同一进程不能切换到另一个布局。
- 便携准备只在 `data/` 下创建 `config/`、`documents/`、`glossary/`、`models/`、
  `fonts/`、`upstream-cache/`、`temp/`、`pycache/`、`logs/` 与 `home/.cache/`，
  进行创建后物理路径复核和可写探针；失败返回稳定 `PathStrategyError.code`，不回退
  到 Home、AppData 或系统临时目录，也不生成真实 `config.toml`/`glossary.csv`。
- 配置原子保存、主/调试日志、文档副本/阅读进度、候选/权威/累计/有效术语、翻译
  工作区创建和清理在真正写入或删除前调用统一 data 边界守卫。守卫使用解析后的
  物理路径比较，因而拒绝绝对目录外路径、`..`、已存在 symlink/junction 及其后面
  尚不存在的尾部路径；开发布局仍允许现有测试、工具和绝对 cache 用法。

### 便携启动器—服务进程边界

- 顶层 `PDF Reader.exe` 对应 `portable_launcher.main()`，进程自身从不改写
  `os.environ`。它从真实入口 EXE 解析布局、确认固定的
  `app/PDF Reader Service.exe` 存在，为服务构造独立环境映射并只通过
  `subprocess.Popen(env=...)` 传给子进程；默认浏览器仍由父启动器调用
  `webbrowser.open()`，因此浏览器继承真实 `HOME`/`USERPROFILE`/代理/证书环境，
  不会继承服务的虚拟 Home。
- 服务环境删除宿主 `PYTHONHOME`、`PYTHONPATH`、`PYTHONUSERBASE`、
  `PYTHONSTARTUP`、`PYTHONBREAKPOINT` 与 `PYTHONINSPECT`，固定
  `PYTHONNOUSERSITE=1`，并把 `HOME`/`USERPROFILE`、`TEMP`/`TMP`/`TMPDIR`、
  `PYTHONPYCACHEPREFIX`、`XDG_CACHE_HOME`、`HF_HOME`、
  `HUGGINGFACE_HUB_CACHE`、`TRANSFORMERS_CACHE`、`MODELSCOPE_CACHE` 和
  `TORCH_HOME` 映射到 `DATA_ROOT`。网络代理和证书等无关宿主变量保留。
  这些改动只存在于服务进程树，不调用 `setx`、注册表或系统环境 API。
- `portable_service` 的模块级依赖只有标准库、`paths` 与同样不导入上游的
  `portable_runtime`。服务先按顶层启动器路径重建布局，逐项验证受控环境，执行
  `prepare_runtime_layout()`/`install_runtime_layout()`，之后才动态导入
  `pdf_reader.app`；因此 `config.py` 顶层对 pdf2zh-next 的导入以及 BabelDOC 的
  `Path.home()` 常量求值均发生在虚拟 Home/便携 Temp 已生效之后。
- 启动器为每次运行生成 data/temp 内的随机就绪文件和随机健康令牌。服务完成严格
  配置校验，或在配置缺失/损坏时完成受限 setup 应用装配，并恢复孤儿工作区后，
  原子发布 loopback host/port/令牌；启动器只在
  带令牌请求 `/api/health` 得到精确 `{status: ok}` 后才打开根页面。描述符拒绝
  data 外路径，便携服务拒绝非 loopback 配置。启动超时、服务就绪前异常退出或
  启动器中断都会执行有界 `terminate`，超时后 `kill`，并删除就绪文件。
- 单实例所有权来自内核而非文件：Windows 使用命名互斥体（进程结束、崩溃或强制
  终止时由内核释放），POSIX 使用 `DATA_ROOT/runtime/instance.lock` 的 `flock`，
  不存在只靠可陈旧 lockfile 判断的路径。`DATA_ROOT/runtime/instance.json` 只记录
  PID、启动器控制端点/令牌、服务端点、健康令牌与服务控制令牌，是建议性元数据：
  第二次启动必须依次通过“记录可解析 → 令牌健康探测通过 → 控制通道 `open_reader`
  返回 `opened`”才承认既有实例，任一步失败都会清理陈旧记录并在本进程内继续尝试
  取得所有权，绝不据此终止任何进程。
- 第二次启动不启动第二个服务：它经既有实例的控制通道
  `POST 127.0.0.1:<launcher_port>/api/control`（令牌头
  `X-PDF-Reader-Control-Token`）请求 `open_reader`，由既有启动器以真实用户环境
  调用 `webbrowser.open()` 打开阅读器；并发双击只会产生一次服务启动。
- 控制入口固定为一个 Tk 启动器窗口，只有三个动作：打开阅读器、打开日志、退出
  程序。默认启动必须先成功创建窗口才自动打开浏览器；Tk/Tcl 缺失、没有图形会话或
  窗口初始化/运行失败均报告稳定 `launcher_ui_unavailable`，先请求刚启动的服务
  协作退出，只有退出超时才兜底，并以退出码 7 结束，不允许退化成无控制入口的隐藏
  常驻服务。只有显式 `--no-ui` 测试/诊断模式允许无窗口等待。关闭浏览器标签页与
  服务生命周期无关；关闭控制窗口等同“退出程序”，该语义由窗口内 `WINDOW_HINT`
  向用户明示；服务在用户退出前自行结束始终按异常服务退出码 6 报告。
- 退出是协作式的：`quit` 后启动器只发一次带服务控制令牌的 `POST /api/shutdown`
  （未认证请求一律 404，令牌不进 URL、日志或普通路由），服务以 202 应答并结束
  `serve_forever()`，回到 `app.main` 既有收尾路径：先
  `TranslationCoordinator.shutdown(timeout=10.0)`（停止接受新任务、协作取消并等待
  当前任务与其工作区），再 `AppState.close()`。只有服务在 `shutdown_timeout`
  （默认 15s）内没有退出时，启动器才兜底结束自己启动的子进程；服务侧另有
  `LauncherLivenessWatchdog` 监督每次启动专属的内核对象：Windows 启动器线程持有
  随机命名 mutex，服务等待其 abandoned 状态；POSIX 测试/诊断态持有 data/runtime
  下随机名称文件的 `flock`，服务只观察同一 open-file-description 的内核锁释放。
  两者都不以 PID 判断身份；即使旧 PID 或其他标识被新进程复用，旧服务仍只观察
  原启动器的随机内核对象并在其消失后请求同一协作退出路径。正常 stop 会先结束
  watchdog，再由启动器释放 owner；崩溃残留的 POSIX 文件名在取得全局实例锁后清理，
  文件存在从来不是存活权威。
- 端口占用不终止他人：端口被占时便携服务发布 `service_port_in_use` 就绪失败
  描述符并以退出码 3 结束，启动器报告同一稳定错误码并以退出码 4 结束，只清理自己
  启动的进程与状态文件，不探测或结束占用端口的其他进程，也不自动更换端口。
- 启动器退出码固定为：0 正常退出、2 启动/状态错误、3 服务启动失败、4 端口占用、
  5 无法在超时内激活既有实例、6 服务异常/意外退出、7 必需控制窗口不可用、130 用户中断；服务非零退出码由
  `_exit_code_for` 映射。启动器日志写入 `DATA_ROOT/logs/launcher.log`，控制令牌与
  健康令牌不进入日志或错误正文。
- 正常收尾保持严格所有权顺序：停止启动器控制 server → 确认服务已协作退出或完成
  有界兜底 → 关闭本次 liveness owner → 删除实例记录/就绪文件/服务 Temp → 最后释放
  全局单实例锁。第二个启动器因此不会在旧记录仍可见或旧服务仍运行时接管所有权。
- 核验日期：2026-09-10（P1-02）；上述状态机由 `tests/release/` 的可注入回归覆盖
  （内核锁与实例记录、启动器主流程、控制通道与窗口、服务生命周期）。
- 当前源码已经固定双进程协议与 PyInstaller 入口职责；真正生成两个 EXE、证明
  私有解释器/依赖的最终二进制来源以及最终 ZIP/干净机验证仍分别属于 P2-01、
  P2-02。开发入口 `start.bat` 和 `python -m pdf_reader` 不进入此双进程路径。

### 便携数据版本、迁移、导入与清理（P1-03）

- 数据格式版本只由 `DATA_ROOT/portable-data.json`（`schema_version`、`product`、
  `app_version`、`created_at`、`updated_at`、`applied_migrations`）决定：缺失记为
  `absent`（首次启动采纳为 v1），低于当前版本记为 `outdated`（启动时迁移），等于当前
  版本时完全不动字节，字段缺失/未知/类型错误记 `invalid` 并拒绝启动，高于本程序支持的
  版本记 `newer` 并以 `portable_data_schema_newer` 拒绝启动而不是降级改写。
- `prepare_portable_data()` 的调用位置固定在 `portable_launcher` 取得内核单实例锁
  之后、启动 `app/PDF Reader Service.exe` 之前，因此第二次启动只走既有实例激活路径，
  不会重复迁移或并发改写同一个数据根；便携数据准备失败以 `portable_data_unavailable`
  结束启动。启动器另有隐藏数据命令（`--data-report`、`--clean CATEGORY...`、
  `--import-data PATH`），它们同样只在取得锁之后执行，且不启动服务进程。
- 迁移由 `DataMigrationTxn` 完成：先把旧清单原字节写入
  `data/backups/<UTC 时间戳>/files/` 并写 `state.json` 账本，再在同目录写 `*.tmp`，最后
  `os.replace` 原子提交，提交后追加 `data/backups/migrations.log`。未提交事务在任一步
  失败时不允许把“新字节 + 没有 `state.json` 的备份”留在磁盘上：`replace_file()`/`commit()`
  失败会立即逆序恢复本事务真正写过的目标（旧文件写回旧字节，本事务新建的文件删除），
  `with` 语句另外兜住两步之间的意外异常，恢复沿用同一条 data root 边界、链接拒绝与原子
  写语义；恢复本身失败时抛 `portable_data_recovery_failed`，消息携带备份目录、未恢复目标
  与原始错误供人工恢复，绝不静默声称成功（恢复成功则追加
  `portable-data-recovery-completed`，未提交的备份目录保留但不被回滚采用）。已提交迁移由
  `rollback_last_migration()` 按账本逆序恢复并删除清单，`restore_backup_directory()` 支持
  指定备份，命令行入口 `scripts/portable_data.py rollback --yes`。
- 分类清理只作用于规范化 data root 的**直接子项**，分类固定为 `documents`（文档缓存，
  不可重建）、`models`（`models/` + `upstream-cache/`）、`fonts`、`logs`、`temp`；每类
  都携带稳定 `consequence` 文案供命令/界面显示大小与后果。存在
  `data/runtime/instance.json`（可能仍有实例在运行）时拒绝清理；分类根是符号链接/
  junction 时整体拒绝（`portable_data_cleanup_root_is_link`），子项是链接时只删除链接
  本身；所有目标先经 data 物理边界守卫，因此绝不递归删除 data 之外的用户 PDF。清理必须
  显式给出分类，默认 dry-run，只有 `--yes` 才真正删除。
- 受控导入只读取用户显式给出的旧 `data` 根，要求该根与目标 data 根互不包含且不是链接；
  逐条跳过链接、清单与易变状态（`config/`、`logs/`、`temp/`、`runtime/`、`pycache/`、
  `home/`、`backups/`），非 dry-run 时以临时文件 + 原子替换复制，因此模型、上游缓存、
  字体与文档缓存可整体复用而无需重新下载；目标已存在同名文件时默认跳过，`--overwrite`
  才覆盖，`config/config.toml` 永不自动导入。
- 发行包契约由 `packaging/windows/data_policy.py` 锁定：发行树不得包含真实 `data/`
  内容、用户配置、模型权重与文档缓存，用户发行说明必须明确“删除整个便携目录会删除配置
  和缓存”并给出旧 `data` 的复制/受控导入方式；原地覆盖升级只替换 `app/` 与启动器，
  `data/` 从不进入发行包。
- 核验日期：2026-09-11（P1-03，含当日未提交事务自动恢复修复）；上述行为由
  `tests/release/test_portable_data.py`（事务恢复由 `TestUncommittedMigrationRecovery`
  覆盖 `state.json` 写失败、首次采纳失败与恢复不完整三条路径）、
  `tests/release/test_portable_data_cli.py`、`tests/release/test_data_policy.py` 与
  `tests/release/test_portable_launcher.py` 的定向回归覆盖（99 passed）。真实 ZIP、干净机
  升级与最终发行物审计仍属于 P2-01/P2-02。

1. `python -m pdf_reader` 进入 `app.main(argv=None)`：模块导入不解析 CLI、不修改 `config.DEBUG`；CLI 解析只发生在该启动边界内，`__main__.py` 的 `main()` 调用受 `if __name__ == "__main__"` 守卫保护，`import pdf_reader.__main__` 同样无副作用。`--debug` 与 `--no-debug` 互斥。
2. `config.resolve_server_config(cli_debug=...)` 按优先级 CLI `--debug`/`--no-debug` > 环境变量 `PDF_READER_DEBUG` > `[server].debug` > 默认 `false` 解析一次，返回 frozen `ServerConfig(host, port, debug)`；`use_reloader` 恒为 `False`——`debug` 只表示“详细诊断日志模式”（日志 DEBUG + debug_trace），不再控制 Flask debugger/reloader。
3. `main` 调用 `config.validate_startup_requirements()` 统一严格校验 `[model]`/`[pdf_reader]`/`[translation]`/`[pdf2zh]`：未知 section/key/provider、类型/范围/组合/正则错误、`openai_compatible` 缺 `base_url` 均抛 `ConfigError`；缺少 `model.model`、API Key 或 API Key 为示例值时同样失败。main 打印 `ERROR:` 并以退出码 2 结束，不启动服务器。该函数返回严格解析出的同一个 `UpstreamRuntimeConfig`。
4. `main` 用步骤 2 的同一 `ServerConfig` 与步骤 3 的同一 `UpstreamRuntimeConfig` 调用 `config.build_app_settings(cli_debug=..., run_cfg=run_cfg, upstream=upstream)`：复用已解析结果，不再二次调用 `resolve_server_config` 或宽松重解析上游配置；`settings.debug` 与 `run_cfg.debug` 恒一致，`settings.upstream` 与严格实例恒为同一对象。
5. `create_app(settings)` 使用 `settings.debug` 调用 `logging_config.setup_logging(...)`，输出启动摘要（provider/model/lang/cache_dir/dpi/debug，不含 api_key）；创建 `Flask(__name__)` 并显式传入 `template_folder=PROJECT_ROOT/templates`、`static_folder=PROJECT_ROOT/static`（由 `src/pdf_reader/paths.py` 解析），装配全局 `AppState(settings.cache_dir)` 与 `TranslationCoordinator()`，导入并注册 `pdf_reader.routes.register_routes`。`register_routes` 只消费已注入的 `app.config["app_settings"]`；仅当该 key 缺失（绕过 `create_app` 直接注册 blueprint 的兼容边界）时才惰性调用 `config.build_app_settings()`。
6. `main` 在 `create_app`（日志已就绪）之后调用 `cache_ops.recover_orphan_temp_workspaces(settings.cache_dir)`：清理上次崩溃/超时退出遗留的、可验证归属（固定前缀 + 有效标记 + 非链接 + PID 已不存活）的翻译任务根工作区（含 `input/` 与 `output/`）；未知/无标记/损坏标记/链接路径/PID 仍存活的目录一律保守保留。清理数量与保留分类写入 INFO/WARNING 日志。
7. `main` 以 `app.run(host=..., port=..., debug=False, use_reloader=False)` 启动（显式传入全部四个参数，Flask debugger/reloader 始终关闭）；`KeyboardInterrupt` 记录 INFO 并以 130 退出，其它运行期异常经 `logger.exception` 记录完整 traceback 后以 1 退出。`app.run()` 返回或异常退出时先调用 `coordinator.shutdown(timeout=10.0)` 做有界关闭：请求协作式取消并等待 worker 与 active job，按 `no_active_job`（INFO）/ `completed`（INFO）/ `timeout`（WARNING，任务与工作区保留供下次启动恢复）记录日志，worker 未确认退出时追加 WARNING；随后 `app_state.close()` 幂等关闭并释放左右 PyMuPDF 句柄、清空状态并记录 `app state closed`（即使 `shutdown` 抛异常也会执行）。
8. 配置错误路径：TOML 语法错误在配置导入时被捕获（`config._CONFIG_LOAD_ERROR`），首次解析配置时抛 `ConfigError`；`[server]` 类型/范围错误与 `PDF_READER_DEBUG` 非法值同样由 `resolve_server_config` 抛 `ConfigError`；`--debug`/`--no-debug` 互斥由 argparse 报错。开发入口仍在启动服务器前以非零状态退出；便携服务把配置错误转换为 `AppSettings.setup_mode`，以 `127.0.0.1:5000`（有效 loopback server 配置存在时保留其端口）启动受限配置页面，不创建候选提取服务。配置保存成功只原子更新磁盘并返回 `restart_required=true`/`setup_complete=true`，不热替换当前冻结运行态；用户关闭后重新双击进入严格校验的正式模式。
- `start.bat` 是 Windows 便捷启动入口：切换到仓库根目录后先检查 `.\venv\Scripts\python.exe`（缺失时打印创建/安装命令并不为零退出），再用 `netstat -ano -p tcp | findstr "LISTENING" | findstr ":5000 "` 检测端口占用；若 5000 已被监听，打印占用 PID 与 `netstat`/`tasklist` 排查命令并以非零状态退出，绝不执行 `taskkill`/`Stop-Process` 等终止命令；无冲突时 `call .\venv\Scripts\activate.bat` 激活既有虚拟环境并运行 `python -m pdf_reader`。

## 配置加载与 Provider 映射

- `config.py` 经 `src/pdf_reader/paths.py` 读取当前布局的 `CONFIG_PATH`。开发态仍为 `PROJECT_ROOT/config.toml`；显式便携布局为 `PORTABLE_ROOT/data/config/config.toml`。开发资源根默认从 `src/pdf_reader/` 向上查找 `config.example.toml` 标记，也可用绝对 `PDF_READER_ROOT` 覆盖；便携布局不读取该覆盖。文件不存在时配置回退为空字典，不在导入期抛错。
- 导入安全：`_section`/`_string` 安全提取，非 table section 与非字符串字段在导入期使用安全默认值（不会因 `AttributeError`/`TypeError` 崩溃）；原始 `CONFIG` 保留供启动校验。
- 环境变量覆盖：`MODEL_API_KEY`（优先级高于 `model.api_key`）；`PDF_READER_DEBUG` 是 debug 优先级中间层，只接受 `true/false/1/0/on/off/yes/no`（不区分大小写、忽略首尾空白），非法值启动时报错（即使 CLI 显式覆盖也会 fail-fast）。
- `[server]` 严格校验：必须是 table；`host` 非空字符串；`port` 是 1–65535 的 int（布尔值不算）；`debug` 必须为真布尔值。旧的 `[debug].enabled` 键已停止使用。
- 冻结运行时配置：`build_upstream_runtime_config()` 把解析结果冻结为 `ModelRuntimeConfig`（`api_key` 为 `repr=False`）/`TranslationRuntimeConfig`/`Pdf2zhRuntimeConfig`/`UpstreamRuntimeConfig`；`AppSettings.upstream` 持有该对象，`model_provider`/`model`/`lang_in`/`lang_out` 从它派生，不再从 raw section 单独取值。
- 默认值：provider=`openai_compatible`、model=`""`、dpi=200；开发态 cache_dir=`cache`，便携态 cache_dir=`documents`；lang_in=`en`、lang_out=`zh`、`min_text_length=5`、`qps=4`、worker 相关为 `None`（上游跟随）、`auto_extract_glossary=True`（1.x 兼容别名：只在未配置 `[term_extraction]` 段时作为 `enabled` 的兼容来源；已配置本段时以规范段为准）、`term_qps=None`、`term_pool_max_workers=None`（1.x 兼容别名，仅兼容读取并转发旧上游 SettingsModel，严格正文路径与项目候选提取不使用）、`primary_font_family=None`（auto）、PDF 高级字段采用上游 2.9.0 默认（`translate_table_text=True`、其余 false/0.8/0.9）；`[term_extraction]` 默认 `enabled=True`（未配置该段时跟随旧 `auto_extract_glossary` 显式值）、`timeout=30.0`、`qps=2`、`max_workers=1`、`retry_count=1`、`max_input_chars=80000`、`prompt=None`。三个 1.x 兼容键在启动验证时输出不含敏感值的 WARNING 迁移提示，计划 2.0.0 移除，兼容只限这三键（未知键仍严格拒绝）。开发态相对 `cache_dir` 以 `DATA_ROOT` 解析、绝对值保持兼容；便携态相对值固定在 `PORTABLE_ROOT/data` 下，绝对值也必须位于该数据根内，否则启动失败。
- 统一严格校验 `validate_startup_requirements()`（`app.main` 启动前调用，返回严格 `UpstreamRuntimeConfig`）：`[model]`/`[pdf_reader]`/`[translation]`/`[pdf2zh]`/`[term_extraction]` 存在则必须为 table；未知 section/key 与未知 provider 直接报错；`openai_compatible` 缺 `base_url` 启动失败；bool 不得冒充 int/float；数值必须有限（nan/inf/-inf 拒绝）；`temperature` 只要求可解析且有限，`timeout` 要求有限正数；`reasoning_effort` 按 Provider 枚举校验；正则字段启动期预编译；`[term_extraction]` 的 timeout/qps/max_workers/retry_count/max_input_chars/prompt 按类型与范围校验；API Key 只出现在 `ModelRuntimeConfig.api_key`（`repr=False`），错误与日志不泄漏 Key/Prompt 原文。
- `MODEL_API_KEY` 环境值合法（非空且非示例占位值）时覆盖文件中无效的 `api_key`，但 `[model]` 段本身仍必须是 table。`build_app_settings()` 未传入 `upstream` 时用宽松解析装配（无 config.toml 的测试/兼容 fallback）；`main` 必须传回严格实例，禁止宽松重解析。
- `GLOSSARY_PATH` 由当前布局派生：开发态保持 `PROJECT_ROOT/docs/glossary.csv`，便携态为 `PORTABLE_ROOT/data/glossary/glossary.csv`；二者都不受 CWD 影响。
- `ENGINE_REGISTRY` 用声明式 `EngineSpec` 注册 10 个 Provider，顺序为：`deepseek`、`zhipu`、`siliconflow`、`aliyun`、`gemini`、`groq`、`grok`、`modelscope`、`openai`、`openai_compatible`。
- `resolve_engine()` 对未知 Provider 抛 `ConfigError`（不再回退 `openai_compatible`）；`build_engine_kwargs(spec, model_cfg)` 显式接收 `ModelRuntimeConfig`，按 `ENGINE_REGISTRY.field_map` 映射（含发送开关：OpenAI → 历史拼写 `openai_send_temprature`，Compatible/Aliyun → 各自 `send_temperature`；发送开关为 `False` 时省略以保持旧请求行为，`enable_json_mode=False` 等普通字段仍显式透传）。
- `translation_settings.build_settings(upstream, input_pdf, ...)`：设置 `lang_in`/`lang_out`/`min_text_length`/`qps`/worker 与 term 字段（`term_qps`/`term_pool_max_workers` 作为 1.x 兼容别名按旧规则转发到上游 SettingsModel；正文固定 `no_auto_extract_glossary=True`，上游自动提取已关闭，因此它们不改变正文与项目候选）；正文固定 `save_auto_extracted_glossary=False`（P0-04，不再由 `auto_extract_glossary` 反转）；Prompt 优先级为页面非空 Prompt > `default_system_prompt` > 上游默认；`ignore_cache=True`；`glossaries` 只由调用方传入（严格正文路径只传 `effective_glossary.csv`，不再自动附加全局/累计 CSV）；`output` 由生成器设置；PDF 参数为 `pages`、固定 `no_dual=True`/`only_include_translated_page=True`/`watermark_output_mode="no_watermark"`，并把 `[pdf2zh]` 的 15 个字段显式传入（`formula_*` → 上游 `formular_*`）。

## 配置中心（config_editor 与 config-panel）

- 后端 `src/pdf_reader/config_editor.py` 定义 45 字段 schema（覆盖 `[model]`/`[pdf_reader]`/`[translation]`/`[server]`/`[term_extraction]`/`[pdf2zh]`），每字段含中文名、TOML 路径、必填/可选/进阶分组、控件类型、用途说明、默认/常用值、Provider 适用性与条件必填；`translation.term_qps`/`translation.term_pool_max_workers`/`translation.auto_extract_glossary` 三个 1.x 兼容键不在 schema 中（配置中心不再展示/写入）：GET 不返回、PUT 拒绝写入，磁盘上已有的旧键由 tomlkit 原样保留（不删除、不改写）并在下次启动时继续 WARNING；`[term_extraction]` 字段说明明确“候选不会自动影响正文”与“严格正文约束始终开启”。`GET /api/config` 返回 schema、当前值与文件 sha256 revision，API Key 只返回 `{source: file|environment|missing, configured}`，不返回明文。
- 保存只接受 schema 白名单字段；合并后的文档先过滤到已知 section/字段，再复用 `config.validate_startup_requirements()` 与 `config.resolve_server_config()` 做同一套类型/范围/枚举/条件依赖校验，不维护第二套规则。
- 写入用 tomlkit 解析既有 `config.toml`：保留注释、字段顺序与未知字段；模块级 `RLock` 串行化同进程写入；临时文件创建在目标同目录，flush/fsync 后 `os.replace` 原子替换并保留原权限；失败清理临时文件且原文件不变。API Key 为空/缺失时保留文件旧值；保存成功返回 `restart_required=true`，只写文件，不修改 `config.CONFIG` 或运行中的冻结 `AppSettings`。
- 前端 `static/modules/config-panel.js` 由始终可见的“配置”按钮打开可关闭 modal：字段按必填/可选/进阶分组，显示中文名、TOML 路径、说明与默认/常用值提示；provider 为固定友好下拉（DeepSeek、智谱、硅基流动、阿里云百炼、Gemini、Groq、Grok、ModelScope、OpenAI、自定义 OpenAI 兼容接口→`openai_compatible`），按 provider 显示/隐藏适用字段，`openai_compatible` 时 Base URL 标记必填；枚举/布尔用 select，数字与字符串带 datalist 但允许自定义，API Key 用密码框且不回显；环境变量 `MODEL_API_KEY` 覆盖时显示优先提示；Esc、关闭按钮与遮罩点击均可关闭。
- 访问边界：`GET/PUT /api/config` 共享 loopback-only 守卫，只依据 `request.remote_addr`（不信任 Host/X-Forwarded-For）用 `ipaddress` 判定 127/8、`::1` 与 IPv4-mapped loopback；remote_addr 缺失/非法 fail closed，其余来源一律 HTTP 403 `config_local_only`。
- 配置写入不改变缓存语义：`right.pdf`、旧累计术语表（历史输入）与阅读进度仍按原 PDF 哈希复用，不产生配置指纹、缓存分支或自动失效（见“状态、缓存与持久化”）。

## 打开 PDF 与页面渲染

1. 浏览器 `openPdf()` 把本地绝对路径 POST 到 `/api/open`。
2. 路由校验 `os.path.isfile`；若协调器存在 active job 则返回 HTTP 409 / `translation_busy`，否则调用 `state.open_pdf(path, sha256)`。
3. `AppState.open_pdf()` 在锁内：关闭旧文档并使旧身份失效 → 计算 SHA256 → 建 `cache/<hash>/` → `right.pdf` 不存在时复制源文件 → 打开左右 PyMuPDF 文档 → 生成新 `document_id` → 记录页数、首页尺寸与哈希 → 读取 `reading_progress.json`。
4. 响应返回 `page_count`、`page_height`、`page_width`、`hash`、`document_id`、`saved_page`。
5. 前端按页数创建左右页面容器，经懒加载从 `GET /api/page/<side>/<page>` 取 PNG；`state.render_page()` 在锁内调用 `pdf_renderer.render_page()`（`get_pixmap(dpi)` → PNG），越界返回 404，非法 side 返回 400。

## 单页翻译链

1. `POST /api/translate/<page>`（零基页码）校验文档已打开、页码在范围内；路由先调用协调器 `start(document_id, [page])` 原子占用任务槽；busy/shutdown 在任何严格术语准备写操作前返回 HTTP 409。
2. 占位成功后才执行 `strict_glossary.prepare_strict_translation_context(snapshot, job_id=job.job_id)`（旧累计迁移→有效词表编译→严格验证）并 `build_strict_settings()` 组装参数；失败时 `coordinator.fail(job_id)` 释放槽、返回 HTTP 500 `glossary_prepare_failed`、不调用上游。接受后构造带 `job_id` 和 finish/fail 回调的 `GenerateContext`；抽取、`replace_page` 与术语合并闭包都捕获快照中的 `document_id`，`strict_context` 携带本次预构建的有效词表身份与快照。
3. `generate()` 先校验 `strict_context` 与 `task_ctx`/`glossary_cache_path` 身份一致，再在 cache 根创建带前缀与标记的任务工作区（`input/` 抽取输入、`output/` 首次上游输出、`attempt-2/output/` 重试输出），在 `debug_trace.debug_session` 内先 `extract_single_page()` 抽取单页 PDF，再用 `strict_glossary.resolve_active_terms_from_pdf` 解析活跃权威词条并 `apply_resolved_active_terms` 合成最终 `custom_system_prompt`；随后执行候选 `prepare`（读取输入 PDF + 模型提取/过滤，失败只降级日志，正文继续）；rows 为空或源文本无命中为 available+empty（零成本跳过合规门），源 PDF 打不开/抽取异常/文本为空且存在 effective rows 为 unavailable，在调用上游前发 `glossary_verification_unavailable`、不 `run_translation`、不提交、job failed。
4. 每次尝试用 `run_translation()` 启动 daemon worker 线程运行上游异步翻译；`format_sse_event()` 把 `progress_start`/`progress_update`/`finish`/`error` 映射为 SSE；非 dict 心跳直接 yield 空串。有活跃词条时最多尝试 2 次：首次收到 `finish` 后先做 P0-05 合规验证，FAIL 时以同一 job/输入 PDF/严格上下文/task identity 复用独立 Settings 深拷贝与 `attempt-2/output/` 重试 1 次（Prompt 追加 `[术语合规纠错]` 块），PASS 才继续；UNKNOWN 直接 `glossary_verification_unavailable` 且不提交。
5. 验证通过（或无活跃词条）后调用 `finish_translation()`：优先 `mono_pdf_path`，缺失时回退 `dual_pdf_path`，再调 `AppState.replace_page(..., expected_document_id)` 写入译文，并通过 `AppState.merge_glossary(..., expected_document_id)` 把自动术语并入累计文件；提交成功后在同一生成器内同步执行候选 `commit`（重验 active job 身份后原子写 `CandidateStore`，失败只降级日志，不改变 finish），随后才进入 finally 释放 job；FAIL/UNKNOWN 路径不 replace、不 merge、不调用候选 commit（可能已 prepare，随工作区丢弃），旧 `right.pdf` 不变。
6. `replace_page()` 在锁内先比较预期身份，再经 `_commit_replacement()` 事务提交：所有页修改在从磁盘已提交的 `right.pdf` 重开的工作副本上完成 → 保存 `.tmp` → 关闭译文/工作文档 → 关闭旧右文档句柄 → `os.replace` 原子替换 → 重开右文档 → 更新翻译页集合。磁盘提交成功前不替换内存句柄和 `_translated_pages`；任意失败（open/delete/insert/save/close/`os.replace`）都会清理 `.tmp`、关闭泄漏句柄、恢复或保留可渲染的文档句柄，旧 `right.pdf` 保持不变。`merge_glossary()` 同样在锁内完成身份比较与合并回调；失配时两条边界都抛出 `StaleDocumentError`、记录 `[stale-result]` 警告且不修改当前文档。
7. 当前部分提交语义（由 `tests/test_system_concurrency_failure.py` 固定）：`finish_translation()` 严格按「PDF 提交 → 术语合并」顺序执行两个独立文件提交。PDF 提交（`replace_page`）失败时异常向上传播，术语合并不执行，任务以 failed 释放并输出 SSE `error`；术语合并失败被 `merge_after_translate` 捕获并记录 WARNING，不向上传播——此时 PDF 提交保留、旧术语表不变，任务仍以 finished 释放并输出 SSE `finish`。两者是同一任务内两个独立文件的部分提交，不存在跨 `right.pdf` 与累计术语表的全局事务。
8. 生成器最后发 `progress:100/finish` SSE；成功路径调用 `finish(job_id)`，上游错误、普通异常调用 `fail(job_id)`，消费者断开（GeneratorExit）调用 `cancel(job_id)`。所有退出路径都经 `finally`：先向 worker 请求协作式取消并 `join(timeout=30.0)`，只在 worker 确认退出后整体清理任务工作区（join timeout 时整体保留并记 WARNING），再幂等释放任务；Response close 另有未开始迭代时的兜底释放。

## 范围与全文翻译链

1. `POST /api/translate-batch` 接收一基闭区间 `from`/`to`，校验均为整数、≥1、不越界且 `from ≤ to`。
2. 路由先使用同一协调器原子占槽（busy/shutdown 同样在任何严格术语准备写操作前返回），占位成功后再执行与单页相同的 `strict_glossary.prepare_strict_translation_context` + `build_strict_settings`（同一严格设置构建函数；失败时 `coordinator.fail` 释放槽、500 `glossary_prepare_failed`），并换算零基 `page_indices`、从冻结快照构造带 `job_id` 的 `GenerateBatchContext`（抽取、`replace_pages` 与术语合并闭包都捕获 `document_id`），`pages` 参数按页数设为 `"1"` 或 `"1-N"`。
3. `generate_batch()` 先校验 `strict_context` 身份一致，再发 `batch_info`，抽取多页 PDF 并用 `strict_glossary.resolve_active_terms_from_pdf` 解析活跃权威词条；随后执行与单页同一候选 `prepare`（失败只降级日志，正文继续）；rows 为空或源文本无命中为 available+empty，源 PDF 打不开/抽取异常/文本为空且存在 effective rows 为 unavailable（在调用上游前发 `glossary_verification_unavailable`、不 `run_translation`、不提交、job failed）。batch 首版采用整批原子验证与整批有界重试（最多 1 次）：把整批译文 PDF 视为一个原子单元，页数与批次大小不符、空白文本或不可提取一律 `glossary_verification_unavailable`；任一活跃 target 未命中即 FAIL 并整批重试，重试输出独立于 `attempt-2/output/`，不产生页级部分提交。
4. 整批验证通过（或无活跃词条）后选 `mono_pdf_path`（回退 `dual_pdf_path`）调 `AppState.replace_pages(..., expected_document_id)` 经同一 `_commit_replacement()` 事务按序替换范围页，并只做一次受同一身份保护的 `merge_glossary_only()`；提交成功后在同一生成器内同步执行候选 `commit`（重验身份后原子写 `CandidateStore`，失败只降级日志，不改变 finish）；FAIL/UNKNOWN 路径不 replace、不 merge、不调用候选 commit（可能已 prepare，随工作区丢弃）。批量与单页遵循同一部分提交语义：PDF 提交失败时术语合并不执行；术语合并失败被包含后 PDF 提交保留、任务仍以 finished 结束。
5. 全文翻译是浏览器行为：`onFullTranslateClick()` 调同一批处理端点提交 `1..pageCount`，不存在独立的全文章节端点。

## 状态、缓存与持久化

| 路径/数据 | 说明 |
|---|---|
| `<CACHE_DIR>/<hash>/right.pdf` | 每文档持久化的译文工作副本，首次打开复制源文件，翻译后原子替换；开发默认 `<DATA_ROOT>/cache`，便携默认 `<DATA_ROOT>/documents` |
| `<CACHE_DIR>/<hash>/cumulative_glossary.csv` | 旧累计术语表（历史输入，非权威）：兼容期内保留，只读、幂等迁移为未审核候选并生成 `cumulative_glossary.csv.bak`（已有副本绝不覆盖），不进入 `user_glossary.csv`/`effective_glossary.csv`；读—合并—写仍受模块级互斥锁保护，同目录 `.tmp` 写入并 flush/fsync/close 后 `os.replace` 原子提交；读取失败或表头缺少 source/target 时中止合并保留旧文件，写入/replace 失败保留旧文件并清理临时文件 |
| `<CACHE_DIR>/<hash>/reading_progress.json` | 零基阅读页码，`.tmp` + `os.replace` 原子写；损坏/越界时安全降级 |
| `DATA_ROOT/logs/pdf_reader.log` | 永久常驻的统一主日志：`logging_config` 把同一对控制台 + 轮转文件 handler 挂到 `pdf_reader`/`werkzeug`/`pdf2zh_next`/`babeldoc`，行格式为 ISO 时间/level/run_id/pid/thread/logger，128 KiB × 5、UTF-8（常规上限约 768 KiB），超过 14 天的编号轮转备份在启动与轮转后自动清理，所有通道经同一 `SafeFormatter` 脱敏 |
| `<CACHE_DIR>/<hash>/debug_trace.log` | 仅详细诊断日志模式产生：按文档缓存目录有界轮转（2MB × 3），会话内按 `job_id` 过滤捕获项目 + 第三方日志，记录 start/end/elapsed 与失败 traceback；debug 关闭时零 IO，不生成 timestamp 历史文件 |
| `<CACHE_DIR>/pdf-reader-translation-*` | 翻译任务根工作区：名称带固定前缀，内含 `.pdf-reader-temp-workspace` 标记（`kind`/`job_id`/`pid`/`created_at`）与 `input/`（抽取输入）、`output/`（上游输出）；worker 确认退出后整体删除，超时/崩溃整体保留供启动恢复 |
| `DATA_ROOT/temp/pdf-reader-service-*` | 便携服务单次启动的系统 Temp 根：`.pdf-reader-service-temp` 记录类型、启动器 PID 与创建时间，BabelDOC 的无前缀 `tempfile.mkdtemp()`、下载/SQLite 临时文件及其子进程临时文件均被包含；正常退出由启动器删除，崩溃后只在 PID 确认死亡且标记/路径/非链接条件全部满足时回收 |
| `DATA_ROOT/home/.cache/babeldoc/` | BabelDOC 0.6.2 的硬编码虚拟 Home 缓存；`models/`、`fonts/`、`cmap/`、`tiktoken/` 与 `cache.v1.db` 均在此，不安装系统字体；`DATA_ROOT/models`/`fonts` 当前仅为未来 PDF Reader 自有资源保留，不通过链接或补丁冒充上游目录 |
| `DATA_ROOT/home/.cache/pdf2zh_next/` | pdf2zh-next 2.9.0 导入期初始化的 `cache.v1.db`；项目正文虽固定 `ignore_cache=True`，导入写入仍受虚拟 Home 约束 |
| `DATA_ROOT/upstream-cache/huggingface/` | 已锁定传递依赖 huggingface-hub 1.29.0 的 `HF_HOME`/hub/assets 缓存；当前锁文件不含 ModelScope、Torch、Transformers，便携环境不注入这些未使用变量 |
| 当前布局的 `GLOSSARY_PATH` | 手动术语表；开发态为 `PROJECT_ROOT/docs/glossary.csv`，便携态为 `DATA_ROOT/glossary/glossary.csv`，非空时参与每次翻译 |

开发布局的 `DATA_ROOT` 默认等于 `PROJECT_ROOT`（仓库根），因此正常本地运行的数据位置与既有约定一致：`cache/`、`logs/` 仍在仓库根下；`PDF_READER_DATA_ROOT` 继续用于测试隔离或显式分离开发数据。便携布局固定 `DATA_ROOT=PORTABLE_ROOT/data`，忽略这两个开发覆盖变量且不允许 cache 逃逸。便携态的单实例协调状态也只有一条路径：`DATA_ROOT/runtime/instance.lock`（POSIX 锁文件，Windows 改用内核命名互斥体、不落盘）与 `DATA_ROOT/runtime/instance.json`（建议性实例记录，正常退出即删除），两者都经 data 边界守卫，绝不写入 `data/` 之外的临时目录或用户目录。

配置扩展不改变缓存身份与复用语义：文档缓存仍只按原 PDF 哈希保存（`right.pdf`、`cumulative_glossary.csv`、`reading_progress.json`；debug 会话的 `debug_trace.log` 也按同一哈希目录保存），不产生配置指纹、缓存分支或自动失效；修改模型、Prompt、字体或 PDF 高级参数只影响之后执行的翻译或主动重译，已有 `right.pdf` 页面继续复用，旧累计术语表作为历史输入继续保留并跨配置复用；上游请求缓存仍固定 `TranslationSettings.ignore_cache=True`。

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
| `glossary-panel.js` | P1-04 术语管理面板：权威/候选分栏、搜索排序分页、文档词条 CRUD/锁定、候选接受前改译法/拒绝/锁定、证据统计、CSV 导入导出、revision 冲突刷新与失败恢复；所有服务端文本只经 `textContent` 渲染 |

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
| `GET /api/setup/status` | 返回 `ready` 或脱敏后的 `setup` 状态；setup 响应明确保存后需要重启，不返回 API Key |
| `GET /api/glossary` | 按当前 `document_id` 返回权威或候选视图、复合 revision、搜索/排序/分页结果、候选统计与有界证据；仅 loopback |
| `POST/PUT/DELETE /api/glossary/terms` | 新建、编辑 source/target/note 或删除文档用户术语；写入要求当前文档身份、复合 revision 且无 active translation job |
| `POST /api/glossary/terms/lock` | 锁定/解锁文档用户术语或 accepted 候选；锁定项不能编辑、拒绝或删除 |
| `POST /api/glossary/candidates/accept` | 接受候选，可在接受前提交用户最终 target；成功后原子重编译有效词表 |
| `POST /api/glossary/candidates/reject` | 拒绝候选或删除未锁定的 accepted 候选，使其不再影响正文 |
| `POST /api/glossary/import` | 安全、整批原子追加当前文档 CSV；限制 1 MiB/1000 行并拒绝公式注入、控制字符、重复与冲突 |
| `GET /api/glossary/export` | 下载当前文档用户术语 CSV；不改写或导出全局 `docs/glossary.csv` |

Blueprint 级 `@bp.app_errorhandler(404)` 返回 JSON，不计入上述路由表。SSE 事件类型包括 `batch_info`、`progress`（含 stage/stage_current/stage_total，重试阶段为 `glossary_retry`）、`error`、`finish`，以及空行心跳。P0-05 提交门错误码稳定为：`glossary_compliance_failed`（重试后仍不合规，不提交、job failed）与 `glossary_verification_unavailable`（源 PDF 或译文缺路径/打不开/缺页/空文本/不可提取，不提交、job failed）；上游普通失败仍为 `translation_error`，项目内部异常仍为 `internal_error`。两者之后都不再发 `finish`。有活跃术语时按 attempt 分配明确进度窗口：attempt1 progress 钳制 0..95（上游 `finish`=95）、attempt2 progress 钳制 95..99（上游 `finish`=99，`glossary_retry` 阶段 `stage_current=2/2`）、最终验证通过提交=100，全序列单调不倒退；无活跃词条路径保持既有事件字节不变。

互斥响应：active job 存在时，新的单页/批量翻译请求、`/api/open` 以及所有术语写端点返回 HTTP 409，JSON 至少包含 `error`（明确中文提示）、稳定 `code="translation_busy"` 和 `active_job_id`。前端已有的非 2xx JSON 错误路径会直接显示服务端提示。

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

翻译流日志以稳定前缀 `[job=<完整 job_id> doc=<8> hash=<12> rev=<12> page=N|pages=A-B status=<状态>]` 关联任务（页码 1-based；`document_id` 8 字符、pdf hash 12 字符、有效词表 revision 12 字符，`TaskContext.__post_init__` 强制截断，直接构造也不可绕过；revision 为空时不输出 `rev=`）。路由构造任务上下文时把 `strict_ctx.effective_glossary_revision` 截断后写入 `glossary_revision`，因此正文/候选/合规诊断的普通 INFO 日志可按 job+doc+hash+revision+页码关联。上下文为不可变 `TaskContext`，经 `contextvars` 在协调器 start/release、路由构造、SSE 单页/批量生成器、`TranslationStream` worker 线程（显式 `set_current_task`）、`translation_lifecycle`、`AppState` 抽取/写回/术语合并/迟到拒绝/事务恢复与任务工作区清理中传播。生命周期状态：created、started、client_disconnected、cancelling、finished、failed、discarded、cleaned；迟到身份拒绝记 `discarded`；join timeout 记 `cleanup_deferred`（WARNING，工作区保留），coordinator 释放保留 `cancelled`；重复/迟到 release 静默不产生缺上下文的半截任务日志。任务工作区清理以 `_safe_rmtree` 的可验证结果为准：目标原本不存在或确认删除后不存在才算 `cleaned`，任一目录删除失败记 `cleanup_deferred` 且不再记 `cleaned`。

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

### 术语诊断摘要（P2-02）

候选与合规诊断集中在 `term_diagnostics.py`，普通 INFO 日志只输出受控稳定字段：数量（proposed/kept/filtered/failed）、页码、状态、受控 reason/event 名、耗时、token 计数、job/doc/hash/revision（任务前缀）；绝不输出 source/target、证据片段、正文、Prompt 或凭据。`CandidateExtractionReport` 增加 `proposed`（模型提出数）与 `elapsed_ms`（模型提取调用耗时，失败路径同样记录）；`failed` 不存为报告字段，唯一事实源是 `term_diagnostics.candidate_failed_count()`（受控终态集合 `failed`/`source_failed`/`store_failed` 计 1，其余 0，未知 status 计 0）。`usage` 契约：chat completions `usage` 三字段全部为非负 int 才构造 `TokenUsage` 并 `available=True`；缺失/部分/布尔/负值一律 `unavailable`，不伪造。

prepare 与 commit 各发一条 `candidate summary`：prepare（`event=candidate_prepare`）只使用批内口径 `proposed/kept/filtered/failed`，绝不用 accepted/rejected 命名批内计数；commit（`event=candidate_commit`）在批内口径之外追加 best-effort 读取 `CandidateStore.candidate_summaries()` 的真实持久状态计数 `pending`（status=candidate）、`accepted`（status=accepted）、`rejected`（status=rejected），统计失败时三个持久状态计数均明确 `unavailable`。所有 commit 返回路径（无 observations、成功、store_failed、identity_rejected/身份 mismatch）都发稳定 `candidate_commit` 摘要；store_failed 摘要显示 `failed=1`。event/status/reason 全部走显式常量白名单（候选过滤 reason 复用 `candidate_filter.FILTER_REASONS`；合规 reason/status/event 为 `term_diagnostics` 常量集合），未知值统一输出 `unknown`，任何原始字符串不落日志。正文解析活跃权威词条后发 `glossary_active_terms active=<命中数> sources=<有效词表行数>`；合规阶段使用稳定事件 `compliance_pass`/`compliance_fail`/`compliance_unknown`/`compliance_unavailable`/`compliance_retry_scheduled`/`compliance_failed_final`，SSE 错误码保持 `glossary_compliance_failed`/`glossary_verification_unavailable` 不变。

所有诊断构造/格式化/发射/可选统计都经过 `safe_task_log` 与调用侧 `_safe_diagnostics`/`_log_diagnostics` 多层 catch：任一诊断函数异常只降级为固定 fallback 日志，绝不阻止正文翻译、改变终态或损坏 `term_candidates.json`/有效词表/用户术语。故障注入回归位于 `tests/test_term_diagnostics.py`、`tests/test_candidate_service.py`、`tests/test_candidate_sse.py` 与 `tests/test_glossary_compliance_flow.py`（格式化/发射/统计/合规诊断故障均不改变 finish 与存储结果）。

### 错误传播

`TranslationError` 与普通异常都被 `generate`/`generate_batch` 捕获并输出 SSE `error` 事件，同时记录上下文日志；任务工作区（根目录，含 `input/` 与 `output/`）只有在 worker 线程确认退出后才会在 `finally` 中整体清理（join timeout 时整体保留并记 WARNING）。

前端装配与翻译 UI 状态（P2-02）：`static/modules/translation-ui-controller.js` 是单页/批量共享的翻译 UI 状态机（idle → running → succeeded/failed/aborted → idle），集中 busy 控件禁用、进度条、stage/status 文本、成功/失败恢复、延时清理与 operation generation 迟到回调隔离；单页与批量差异（范围文案、完成后刷新页集合）通过 operation descriptor/callback 注入，`app.js` 不再复制两套 busy/progress/error DOM 逻辑。每次翻译操作创建 `AbortController` 并把 `signal` 传入 `translator.js` 的 fetch；新操作、成功打开新文档（session dispose）与页面卸载时 abort 浏览器请求并使旧回调失效；浏览器 abort 只终止客户端请求/消费，不是可靠的服务端取消确认，服务端生命周期仍由 SSE 断开与后端机制决定。`static/modules/reader-session.js` 把 zoom/alignment/intersection observer/settle gate/page 生命周期清理收束为幂等 `dispose` 边界：仅在新文档 open 成功、准备替换 DOM 时 dispose 旧 session，失败打开保留旧 session（409 语义不变）。

错误契约（P2-05）：所有 API 4xx/5xx 返回顶层 `{"code": <stable_code>, "error": <safe_message>}`；`409` 保留 `translation_busy`、中文安全提示与 `active_job_id`（P0-02/P1-04 回归依赖），其余 400 分支使用稳定 code（`invalid_file_path`、`invalid_page`、`no_document_opened`、`page_out_of_range`、`invalid_side`、`invalid_page_numbers`、`invalid_page_range`），`403` 使用 `config_local_only`（配置中心 loopback 守卫）与 `client_errors_local_only`（前端错误上报 loopback 守卫），`404` 使用 `not_found`，`413` 使用 `payload_too_large`（前端错误上报正文超限），`500` 除 `glossary_prepare_failed`（P0-04 严格词表准备失败）外固定为 `internal_error`。`routes.http_error` 处理 `HTTPException`（不吞成 500），`routes.internal_error` 记录完整异常（含 traceback）后只返回安全摘要。SSE 统一经 `sse_stream.format_sse_error(code, message)` 输出 `{"type":"error","code","error"}`；上游原始 error、`TranslationError` 消息、普通异常消息与“无翻译结果”均只进服务端日志，不返回浏览器。前端 `static/modules/dom.js` 提供 `showError()`（DOM 节点 + `textContent`），`app.js` 不再使用 `insertAdjacentHTML` 插入错误文本；`static/modules/translator.js` 对非 JSON 响应、网络异常与缺失错误字段使用固定安全 fallback。非 loopback host（非 `localhost`、`127/8`、`::1`）在 `app.main` 中、`app.run` 前输出安全 WARNING（不记录 API Key，不阻止启动）。

## 测试、CI 与验证入口

`pyproject.toml` 是唯一直接依赖声明源（`project.dependencies` 运行依赖、`project.optional-dependencies.dev` 开发工具）；已删除 `requirements.txt`/`requirements-dev.txt`。`requirements.lock` 是 README、CI 和本地开发安装共同使用的总锁文件，由 Python 3.12 与 pip-tools 7.6.1 从 `pyproject.toml`（含 dev extra）生成；`packaging/windows/runtime-requirements.lock` 则是同一直接依赖源解析出的仅运行时闭包，以总锁文件为 constraint，当前 136 个固定版本全部与总锁一致且不含 pytest/coverage/mypy/pip-tools 或 Python 安装工具。两个 header 均记录真实命令（用 `CUSTOM_COMPILE_COMMAND` 规避 pip-tools 7.6.1 在本环境写入多余 `--no-index` 的怪癖），都不包含 editable、本机路径或 `file:///` 来源。开发安装契约仍为 `pip install -r requirements.lock` 后 `pip install -e . --no-deps`；运行时锁只供隔离的 Windows 发行构建输入，正常启动/翻译绝不安装包。

统一验证入口 `scripts/verify.py`（跨平台公共编排；`scripts/verify.ps1` 只是 Windows 启动器，两者不重复逻辑），顺序为：输出最终 Python 绝对路径与版本并核验 Python `>=3.12`、Node `>=22`（不满足快速失败）→ Python 关键依赖导入（`import flask, pymupdf, pdf2zh_next, pdf_reader`）→ `pip check` → 密钥扫描（`scripts/secret_scan.py`，只扫 Git 跟踪内容，占位示例放行，匹配值不输出）→ 上游升级治理门静态检查（`python scripts/upgrade_governance_gate.py --static-only`，P2-04：依赖来源 + 任意位置影子包/fork/vendor/源码副本 + 生产 Monkey-patch，失败即停）→ P0-04 便携运行时策略门（运行时锁/总锁一致性、生产源码禁安装/禁外部解释器启动；P2 构建脚本再以 `--artifact` 对最终目录执行产物扫描）→ Ruff lint → Ruff format check → coverage（`coverage run --branch -m pytest -q`，全部 Python 测试；`coverage report` + `coverage json` + `scripts/check_coverage_policy.py` 执行全局与关键模块阈值）→ 术语质量门（`scripts/term_quality_gate.py`，黄金样本指标阈值 + 版本化基线漂移对比，失败非零退出）→ `mypy`（仅 `src/pdf_reader`，`check_untyped_defs`/`no_implicit_optional`/`warn_unused_ignores`/`warn_redundant_casts`/`warn_return_any`/`strict_equality`）→ `npm audit` → `npm run lint:js`（ESLint flat config，lint `static/**/*.js` 与正式 `tests/*.mjs`）→ `npm test`（前端套件：`test:ui-copy`、`test:error-safety`、`test:client-error`、`test:translation-ui`、`test:translator`、`test:zoom`、`run-alignment-controller-tests.mjs`、`run-config-panel-tests.mjs`、`run-glossary-panel-tests.mjs`）。Windows 下 `scripts/verify.ps1` 接受 `-PythonExecutable` 显式指定验证环境（无效显式路径快速失败、不回退）；未指定时优先使用仓库 `venv`（`venv\Scripts\python.exe`），不存在时回退 PATH 中的 `python` 并输出醒目 WARNING（含实际路径与版本），随后以 `python scripts/verify.py` 委托公共验证并传播退出码；WSL 直接以 `venv/bin/python scripts/verify.py` 运行同一逻辑。coverage 数据默认写入临时目录并在 finally 清理；设置 `PDF_READER_COVERAGE_ARTIFACT_DIR` 时输出 coverage JSON/XML 到该目录供 CI 上传（`coverage-artifacts/` 已忽略）。P2-01 起测试与运行均从已安装的 `pdf_reader` 包导入：先 `pip install -r requirements.lock` 再 `pip install -e . --no-deps`（CI 同契约），仓库根不再提供生产模块 shim。

覆盖率策略（P2-03）：全局 line ≥90%、branch ≥80%；关键模块独立 floor——`state.py` line 80/branch 75、`translation_coordinator.py` 95/95、`translation_lifecycle.py` 95/95、`sse_stream.py` 85/75、`routes.py` 85/70。实测基线（2026-09-01 P2-04 最终核验值）：全局 line 92.8%、branch 86.6%，关键模块均高于 floor。pytest 声明 `unit`/`integration`/`system` 标记；系统红线（`tests/test_system_concurrency_failure.py`）标记为 `system`，`integration` 标记用于真实路由/磁盘事务测试，但 verify 默认全量收集、不做 marker 排除。

测试隔离：`tests/conftest.py` 在任何应用模块导入前把 `PDF_READER_DATA_ROOT` 指向 pytest 专用临时目录，并在每个测试后调用 `logging_config.reset_logging()` 关闭/移除 handler（会话结束再清理临时目录），因此完整测试不会写入或增长仓库 `logs/`、`cache/`。`tests/test_paths.py` 用两个不同 CWD 的子进程分别穿过真实开发布局与“安装便携布局 → 准备目录 → 再导入 config/app”的入口顺序，固定 config/glossary/templates/static/logs/cache 的 CWD 无关解析；同时覆盖中文/空格路径、开发环境覆盖无效、绝对/相对 cache 逃逸拒绝、symlink/Windows junction、不可写探针稳定错误码、开发绝对 cache 兼容与 `reset_logging()` 重建 handler。

上游契约与文档治理回归（P3-06）：`tests/test_upstream_contract.py` 用确定性 fake 验证固定版本、SettingsModel 消费字段与 ENGINE_REGISTRY 字段映射、承诺事件映射与未知事件忽略/心跳、workspace/output 注入与 mono/dual/glossary 路径、协作式取消/迟到丢弃/join 所有权，全部离线且不运行真实翻译；`tests/test_documentation_governance.py` 验证 architecture/project/roadmap 职责边界、常青文档链接可解析、README/architecture/dependency-upgrade 的契约命令一致与易腐数字基线。升级命令 `python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py`、P2-04 一键治理门 `python scripts/upgrade_governance_gate.py` 与范围记录在 [依赖升级流程](governance/dependency-upgrade.md) 和 [长期文档治理](governance/documentation.md)。

配置中心回归：`tests/test_config_editor.py` 覆盖 GET 脱敏、PUT 保存与密钥保留、注释/未知字段保留、非法 provider/类型/范围、`openai_compatible` 缺 `base_url`、revision 冲突、原子失败不破坏原文件、环境变量状态与 loopback-only 访问；`tests/run-config-panel-tests.mjs` 覆盖面板打开/关闭、分组与说明、provider 映射、加载/保存、API Key 不回显、错误/成功与重启提示。

P1-01 候选提取回归：`tests/test_term_extraction.py` 用 fake local HTTP server
固定请求 schema/端点拼接、429/5xx 重试、4xx/格式/超限不重试、超时、受控 JSON
解析与日志隐私；`tests/test_candidate_service.py` 固定成功写候选、accepted/
rejected 不被覆盖、unsupported/disabled/empty/超限/网络失败/存储失败全部降级；
`tests/test_candidate_sse.py` 固定单页/批量只在正文提交成功后调用、正文失败/
合规失败不调用、候选失败不阻 finish、候选不进 effective/Settings；
`tests/test_candidate_store.py` 覆盖 `record_observations` 批量原子性、状态保护
与 P1-03 统计/排序/兼容升级（见下）。

P1-02 候选过滤回归：`tests/test_candidate_filter.py` 固定 AD 边界（独立 `AD`
可命中，`adherence`/`adverse`/`shadow` 内部不命中）、大小写与内部空白折叠、
标点清理、普通词（benefits/cost/confusion/education/burden/gaining control）、
完整句/词数/字符/数字/公式/变量/页码/占位符拒绝、Han target 与幻觉 source
拒绝、医学药名/疾病名/缩写/指南术语保留、逐页页码与有界证据、跨页匹配拒绝、
确定性、单条坏候选不使整批失败与规则版本进入 strategy_version；
`tests/test_candidate_service.py` 扩展固定实际写入候选数/页码/证据、
all_filtered 不写空 revision、rejected source/target 自动观察保持用户状态；
`tests/test_candidate_store.py` 增加 rejected 再观察不创建重复条目的回归。

P1-03 候选统计与确定性建议回归：`tests/test_term_model.py` 固定候选 schema
版本、target 级 `distinct_page_count`/`last_observed_at`、确定性推荐排序
（accepted target > 普通未拒绝 > rejected target；组内不同页覆盖数降序 →
观察次数降序 → 字典序）与摘要形状；`tests/test_candidate_store.py` 固定
“错误首译 1 次 + 正确译法 10 次后正确译法成为首选且 `accept` 无参取它”、
同一批 observations 任意排列（含重复项）统计与持久化字节一致、v1/v2
`term_candidates.json` 可读且下一次写原子升级为 v3、v2/v3 严格校验 target
`last_observed_at`（缺失/坏时间戳 fail-closed 且原字节不变）、`accept`
无参使用确定性首选而非插入顺序、显式 accepted_target 在更高统计自动观察
下不变、rejected target 后续观察计数/页覆盖/最近观察时间增长但
`suppressed=True` 且状态不变、`candidate_summaries`/`target_summaries`
暴露 target/状态/抑制/observations/distinct page count/pages/last observed
time/推荐顺序；`tests/test_candidate_service.py` 固定 `CandidateTermService`
服务层摘要边界与缺失 source 报错；`tests/test_glossary_compiler.py` 固定
更高统计自动建议不能改写 accepted target/有效词表，且 v1 候选文件经兼容
读取仍可编译。并发合并、失败恢复、64-hex 文档目录与 stale/document identity
回归沿用既有用例继续通过。

P1-04 术语管理回归：`tests/test_glossary_management.py` 固定文档权威 CRUD、
source/target 同时编辑、用户与 accepted 候选锁定、自动观察不能改变锁定决定、
复合 revision 冲突、候选状态/统计/1-based 页码/证据序列化、有效词表同步更新、
CSV 整批导入/导出与公式注入/控制字符拒绝、编译部分失败不泄露输入；
`tests/test_glossary_routes.py` 穿过真实 Flask route/AppState/磁盘缓存，固定
loopback-only、document_id 过期、active job 互斥、安全错误、分页、接受/拒绝、
CSV 与双标签 revision 409；`tests/run-glossary-panel-tests.mjs` 用 jsdom 固定
新增/编辑/删除/锁定、接受前改 target、拒绝、CSV、冲突刷新、编译失败恢复、
Esc/焦点恢复，以及 source/target/note/evidence 全部按文本渲染、不生成不受信任
HTML 节点。

P1-05 生命周期回归：`tests/test_strict_glossary.py` 固定 job_id/revision/词条
摘要冻结与 job 身份校验；`tests/test_candidate_service.py` 固定 prepare 不写盘、
commit 才写盘、prepare 与 commit 之间身份变化拒绝、stale/其他 job/document
拒绝；`tests/test_candidate_sse.py` 固定单页/批量精确调用顺序（input/active
terms → prepare → run_translation → 合规 → replace PDF → commit → finish）、
prepare/commit 失败仍 finish、合规/PDF 替换/断开不 commit、身份变化拒绝；系统级
`tests/test_system_concurrency_failure.py` 增加单页/批量候选存储写失败、
单页/批量候选提取失败、断开、PDF 替换失败与合规失败，最终
PDF/候选文件/coordinator/worker/工作区状态一致（该文件现收集 22 个系统用例）。

P2-01 术语质量门槛回归：`tests/fixtures/term_quality/fixture.json` 提供医学指南、
技术论文、教材/一般技术文档三类最小黄金文本与人工标注（核心术语、普通词、
`AD` 缩写边界、TCS 全称/缩写多种表述、期望中文），并携带“原创/合成、按仓库
AGPL-3.0-only 留存”的 provenance/license 元数据；模型响应以受控 chat
completions 响应体保存，解析与后置过滤可分别评测；`src/pdf_reader/term_quality.py`
复用 `parse_model_response`/`filter_candidates`/`CandidateStore`/`verify_translated_text`
纯边界，把“术语识别”与“中文译法”分开考核：candidate precision 只算 source/forms
命中，candidate_target_accuracy 只在 TP 候选上核对 golden expected_target；其余
指标含 core term recall、普通词污染率、用户术语合规率、repeat-run determinism、
有方向指标 batch_minus_single_core_recall_delta（batch_recall - single_page_recall，
阈值只防批量相对单页退化）、rejected 候选重复提示率与错误首译锁死率。全部指标的
分子/分母/方向/空集合语义在版本化 `metric_definitions` 中随报告输出；fixture
校验 fail-closed 要求 compliance 覆盖 pass/fail/unknown、boundary 覆盖
AD/TCS 独立命中与子串误命中、store 同时包含 wrong-first 与 rejected 两条主路径、
每个 response 的解析与过滤期望非空、每类文档 core_terms/common_words 非空。
`scripts/term_quality_gate.py` 是独立稳定命令（`--json` 输出确定性报告、
`--update-baseline` 原子更新 `docs/reports/term-quality-baseline.json`、基线键集合/
值类型/有限性与 fixture_sha256 不匹配或低于阈值/漂移超出容差时非零退出），已接入
`scripts/verify.ps1`；评测不联网、不需要 API Key、只写 pytest/临时目录，基线漂移、
NaN/Infinity/类型错误、缺失必需维度与目标译法回归均有测试（`tests/test_term_quality*.py`）。

术语状态模型与迁移回归（P0-02）：`tests/test_term_model.py`、`tests/test_path_locks.py`、`tests/test_user_glossary.py`、`tests/test_candidate_store.py` 与 `tests/test_legacy_migration.py` 覆盖规范化/校验（含 strategy_version 与控制字符对称校验）、按规范路径共享锁（含两个不同 Store 实例并发写同一文档）、文档级权威词表 CRUD 与锁定、revision 冲突、原子写失败保留旧版本、损坏/schema/字段类型 fail-closed 且原字节不变、旧累计 CSV 的幂等合入迁移（保留 accepted/rejected 用户状态、并发迁移只合入一次、自动合并与迁移共用 cumulative 锁同一快照、备份不覆盖/目录 fail-closed、无半备份、失败重试）以及自动合并拒绝受保护文件名；全部使用 pytest 临时数据根。

有效词表编译回归（P0-03）：`tests/test_glossary_compiler.py` 覆盖空词表、
文档/锁定用户词条 > accepted 候选 > 全局优先级、accepted 编辑后的
accepted_target、candidate/rejected 高观察次数排除、同级冲突 fail-closed、
大小写/连续空白合并而保留原始展示文本、单复数/连字符/缩写/全称不合并、
输出排序与确定性字节、删除重建、坏输入不覆盖旧产物、fsync/CSV replace/
sidecar replace 失败保留旧产物对、回滚失败标记 inconsistent、并发编译、
路径控制、输入快照期间更新被路径锁阻塞且 sidecar 哈希对应实际编译版本、
用户/全局输入变化后的 stale 报告、候选 freshness 矩阵（candidate/rejected
观察变化与 accepted 条目被自动观察保持 fresh；accepted 新增/改 target/降级
为 rejected 报告 stale；候选文件新建无 accepted 保持 fresh、删除/损坏
fail closed）、严格 sidecar 与 accepted_projection 字段校验、CSV 行数/哈希/
规范性校验、产物对缺失时读取报错与两者都不存在时空表（不含时间戳/Prompt/
正文）。

缓存生命周期回归（P3-05）：`tests/test_cache_ops.py` 覆盖任务工作区创建（前缀/标记/input/output）、创建中途失败与标记写入失败只清理本次新建目录、崩溃模拟（抽取与输出均在已标记根工作区内）的启动恢复且用户缓存不受影响、统计分类、dry-run/真删边界、未知/无标记/损坏/恶意标记、前缀同名文件与符号链接/junction 保守保留、存活 PID 保留、Windows PID 探测（当前进程 True、明确不存在 False、拒绝访问/未知/查询失败 True、句柄必关）与清理失败报告和 CLI（`stats`/`orphans`/`clean`）契约；`tests/test_sse_stream.py` 覆盖单页/批量共享同一根工作区边界（抽取 input/、输出 output/、标记存在、成功整体删除、join timeout 整体保留）；`tests/test_shutdown.py` 覆盖 coordinator `shutdown` 无任务/完成/超时/幂等/流异常容忍、`AppState.close` 幂等与 Windows 句柄释放、`main` 启动恢复与关闭日志、关闭期间单页/批量翻译被 409 拒绝。

任务日志回归：`tests/test_task_logging.py` 覆盖前缀格式/截断/1-based 页码、跨线程传播、全部生命周期状态序列（成功/失败/断开迟到丢弃/join timeout）、stale-result 与写回失败的任务上下文关联、`SafeFormatter` 与真实 `RotatingFileHandler` 落盘脱敏（sentinel 含 API key、Windows/Unix 路径、HTML；key/token 不落盘，路径保留）。

P2-02 术语诊断回归：`tests/test_term_diagnostics.py` 固定 `TokenUsage` 解析（完整/缺失/负值/字符串/bool/float/未知字段均确定，缺失或非法 → unavailable 且不影响术语解析）、`TokenUsage.available` 三字段全真契约、`extract_terms_with_usage` 与 `extract_terms` 兼容、glossary revision 截断/前缀省略口径、`candidate_failed_count` 唯一 failed 事实源（failed/source_failed/store_failed=1，其余 0，未知 status=0）、prepare 摘要只含批内 proposed/kept/filtered/failed（accepted/rejected/pending 不出现）、commit 摘要使用 `CandidateStoreCounts` 真实持久状态（pending/accepted/rejected，统计失败三者均 unavailable）、event/status/reason 受控白名单（未知 token 输出 unknown，恶意 source/target/prompt/API key/换行不落日志且单行）、`candidate summary` 安全字段与确定性、MagicMock 部分报告降级、格式化/发射故障只降级；`tests/test_candidate_service.py` 固定 proposed/kept/filtered/elapsed/usage 进报告、缺失 usage 日志 `usage=unavailable`、commit 摘要统计真实三种持久状态（构造 candidate/accepted/rejected 各一验证计数且不泄露术语文本）、`CandidateStore.candidate_summaries` 统计故障时 pending/accepted/rejected 均 unavailable 且 store 数据完好、所有 commit 返回路径（无 observations/成功/store_failed/identity_rejected）都发 `event=candidate_commit`（store_failed 显示 failed=1）、失败报告 elapsed 可诊断；`tests/test_candidate_sse.py` 固定单页/批量 INFO 日志带 `rev=`（12 字符截断）、`event=candidate_prepare`/`event=candidate_commit`/kept/pending/accepted/rejected/usage 摘要，且 `log_candidate_summary`/`log_glossary_active_terms` 抛错时正文仍 finish、PDF 提交与候选 commit 不受影响；`tests/test_glossary_compliance_flow.py` 固定单页重试成功与批量最终违规的 `glossary_active_terms`/`compliance_pass`/`compliance_fail`/`compliance_retry_scheduled`/`compliance_failed_final` 事件与既有 SSE 错误码，且 `log_compliance` 抛错不阻止 finish。隐私断言继续覆盖：常规日志不出现 source/target/证据/正文/Prompt/API Key。

日志管线与调试轨迹回归（2026-08-30 日志工程化）：`tests/test_logging_config.py` 覆盖四个托管 logger 共享同一对 handler、128 KiB × 5 轮转与 14 天过期备份清理（过期/未过期/无关文件/清理失败降级/不递归）、ISO 行格式与 run_id 生命周期、第三方级别与脱敏、sys/threading excepthook、外部 handler 快照恢复与并发 setup/reset/attach/detach；`tests/test_debug_trace.py` 覆盖 debug 关闭零 IO、2MB × 3 有界轮转（不再生成 timestamp 文件）、job 过滤、start/end/elapsed、失败 traceback 与 handler 创建/关闭失败降级；`tests/test_routes.py` 覆盖 `/api/client-errors` 白名单字段、长度/正文上限、控制字符清洗、loopback 拒绝与脱敏落盘；`tests/run-client-error-tests.mjs` 覆盖前端 `window.error`/`unhandledrejection` 采集、sendBeacon/keepalive fetch 降级、字段截断与上报失败不递归。

启动脚本安全回归：`tests/test_start_bat.py` 在 Windows 下把真实 `start.bat` 复制到 pytest 临时目录，用 fake `netstat.cmd`/`taskkill.cmd`/`python.cmd`/`activate.bat` 在 PATH 上执行真实脚本：断言源文件不含 `taskkill`/`tskill`/`Stop-Process`/`kill` 等终止命令；模拟 5000 被占用时脚本退出非零、不调用 python 也不调用 taskkill；无占用时激活 venv 并调用 `python -m pdf_reader`；`venv` 缺失时给出提示并非零退出。测试不绑定真实端口、不启动服务器、不杀任何进程。

系统级回归：`tests/test_system_concurrency_failure.py` 的用例穿过真实 Flask route、真实 Response/SSE generator、`TranslationCoordinator`、真实 `TranslationStream` worker 线程、`AppState` 与磁盘缓存边界；仅 `translation_orchestrator.do_translate_async_stream` 使用确定性 fake（外部翻译引擎），故障注入只作用于 `tempfile.mkdtemp`、`cache_ops.write_temp_marker`、`pymupdf.Document.save` 与 `os.replace`。覆盖：翻译进行中打开 B 被 409 拒绝且 A 的结果只写回 A；两个 Flask 客户端只有一个任务被接受；SSE 断开后 worker 继续运行/最终失败/join timeout 三条所有权路径；工作区根创建/标记写入与 PDF 保存失败及重试；单页与批量提交失败后的 `right.pdf`/`translated_pages`/渲染恢复；PDF 提交与术语合并的部分提交语义；打开—翻译—渲染闭环的最终 PDF 字节/页内容、`document_id`、coordinator 与 worker 状态、工作区清理断言。

CI（`.github/workflows/ci.yml`）：`windows-latest` job 是产品权威门，安装 Python 3.12 依赖（`pip install -r requirements.lock` + `pip install -e . --no-deps`）、Node 22 测试依赖（`npm ci`，Node 只承担前端测试且由 `package-lock.json` 锁定），再执行同一 `scripts/verify.ps1`（其内部以 `python scripts/verify.py` 委托公共验证，含 Python 关键依赖导入与 `pip check`）。另设 `ubuntu-latest` 的 `ubuntu-dev-compat` job：用 Python 3.12/Node 22 安装同一 `requirements.lock` 与 `npm ci` 后运行 `python scripts/verify.py`，只验证 Linux 开发环境兼容性——不做 Windows Portable artifact 打包、不读 config.toml、不调用模型 API、不因 Linux 差异降低任何验证阈值；Windows job 仍是最终产品权威门。`tests/README.md` 说明正式测试与历史诊断脚本的区别。

## 当前技术约束与已确认风险

以下只记录当前事实，不构成修复方案或目标设计。

1. **单进程/全局状态。** 服务端只有一个全局 `AppState`，同一时刻只面向一个本地用户、一份打开的文档；没有多用户或并行文档隔离。
2. **SSE 断开有协作式取消但无强制终止。** 消费者断开后，`generate`/`generate_batch` 请求协作式取消并等待 worker 退出（join timeout 30s），任务工作区只在 worker 确认退出后整体删除；join timeout 时工作区整体保留并记 WARNING。不响应取消的上游环节（含 BabelDOC 子进程）仍会运行到自然结束，其结果被丢弃，没有强制 kill 接口。
3. **术语写入为进程内原子事务。** 自动累计合并与 `user_glossary.csv`/`term_candidates.json` 读写分别受模块级互斥锁与按规范路径共享的进程内可重入互斥锁（RLock）保护；自动累计合并与迁移还共用 cumulative 路径锁（锁顺序 cumulative → candidate），确保迁移的 rows 与备份来源同一快照。新内容经同目录临时文件 flush/fsync/close 后 `os.replace` 原子提交；损坏文件或表头/schema/字段异常时 fail-closed 并保留旧文件，写入/`os.replace` 失败保留旧文件并清理临时文件；单任务协调器与 `document_id` 阻止跨文档迟到合并。旧 `cumulative_glossary.csv` 只在候选存储无成功迁移标记时合入（保留用户状态），备份不覆盖已有副本（非普通文件 fail-closed），失败时旧文件原样保留。有效词表编译在 effective CSV 路径锁内按“输出锁 → 输入锁”顺序读取权威输入并成对提交 CSV 与 sidecar：每个输入的解析与字节摘要在同一输入 RLock 内完成，sidecar 提交失败回滚 CSV（回滚失败时明确标记 inconsistent），任何失败都保留最后有效的旧产物对，输入损坏绝不覆盖旧产物；验证时再取当前输入快照与 sidecar 比较——user/global 比完整摘要、candidate 只比 accepted 投影（完整文件摘要仅用于审计），只有权威投影变化才报 stale，避免旧有效词表被误用，同时不受自动候选观察干扰。
4. **PNG 无文本层。** 页面以图片显示，没有文本选择、搜索、复制、高亮、批注、目录、内部链接或 OCR 流程。
5. **无队列/暂停/取消/重启续传。** 不存在持久任务队列、暂停、取消、重试队列、进度恢复或进程重启后的翻译续传。
6. **部分提交语义。** 单页/批量翻译结束时先提交 `right.pdf` 再合并术语表；术语表合并失败被包含（记录 WARNING），不会回滚已提交的 PDF，也不改变任务终态；PDF 提交失败则术语合并不执行。不存在跨两个文件的全局事务。
7. **启动脚本不自动释放端口。** `start.bat` 只检测并报告端口 5000 的 `LISTENING` 占用，不包含任何进程终止命令；端口冲突需要用户自行确认归属并处理（命令见 README「启动」），或改用 `config.toml` 中 `[server].port` 指定的其他端口。
8. **临时工作区清理有明确安全边界。** 每个翻译任务拥有 cache 根下带前缀+标记的根工作区（`input/`/`output/`）；只有名称带固定前缀、含有效标记（`kind` 匹配且 `pid` 为正整数）、非符号链接/junction 且 PID 已不存活的 `cache/` 直接子目录才会被启动恢复或 `cache_manage.py clean --yes` 删除；未知、无标记、标记损坏、链接路径或可能仍在使用的目录一律保守保留；持久用户数据（`right.pdf`、术语表、阅读进度）永不作为清理目标。Windows PID 探测只读，且只把明确不存在（`ERROR_INVALID_PARAMETER` 等）判为不存活；PID 复用或查询失败时按“可能存活”保留，可能留下少量无法自动清理的目录，需要用户确认后手动处理。
9. **私有 Python 的源码契约已建立，真实冻结产物仍待 P2。** 便携服务在 `sys.frozen` 时会在第三方导入前验证自身路径、用户 site 禁用状态与 `sys.path` 的 app 内边界；运行时锁、源码扫描、最终产物/manifest 扫描规则及本机已安装原生依赖导入回归均已固定。但仓库当前尚无 PyInstaller spec 和最终 ZIP，因此“隐藏系统 Python 后启动与翻译”、Process Monitor 无 `python.exe`/`py.exe`/`pip.exe`、最终目录 DLL/动态导入完整性以及真实 wheel SHA-256 manifest 只能在 P2-01/P2-02 完成，当前不能视为发行态或干净机验收通过。
10. **候选提取是两阶段同步旁路：prepare 在严格翻译前，commit 在 PDF 提交后，页码/证据为逐页精确命中。** `generate`/`generate_batch` 在输入/活跃词条之后、`run_translation` 之前同步执行候选 `prepare`（读取输入 PDF + 模型提取/过滤，返回不可变 prepared，绝不写盘），在 `right.pdf` 成功提交后同步执行候选 `commit`（重验 active job 身份后原子写 `CandidateStore`）；严格 timeout（1-120s）与有界重试保证不会无限阻塞。prepare 失败只降级日志，正文继续；客户端断开/取消发生在 prepare 之后、PDF 提交之前时，已 prepare 候选只存在于内存并随工作区丢弃，绝不落盘。P1-02 起，模型候选先经本地确定性过滤：普通词/结构异常/幻觉 source 被拒绝，保留候选携带实际命中页与有界证据；过滤后为空返回稳定 `all_filtered` 摘要且不写空 revision；候选失败只降级日志，不改正文终态。P1-05 起，候选请求携带 job/document/pdf_hash 身份：prepare 提取前校验当前 active job 并把身份冻结进 `PreparedCandidates`（带身份时 document_dir 必须等于 identity.document_dir），commit 写入前以冻结身份为权威校验（另传 identity 必须完全相等、写目录必须等于冻结 identity.document_dir、无身份 prepared 不得升级），身份拒绝（`identity_rejected`）或存储失败不写任何候选且不改变已提交正文的 finish 终态。
   P1-03 起，候选统计为可审计真实值：每个 target 保存观察次数、去重页覆盖与
   最近观察时间，批合并先确定性排序；推荐排序固定为 accepted target > 普通
   未拒绝建议 > rejected target（组内不同页覆盖数 → 观察次数 → 字典序），
   `accept` 与未来 UI/API 摘要都走该顺序，拒绝状态只抑制提示、不冻结后台
   统计。候选排序与统计变化仍不影响有效词表与正文（仅 accepted 投影参与
   编译/stale 判断）。
11. **1.x 兼容期配置别名。** `translation.auto_extract_glossary`、`term_qps`、
    `term_pool_max_workers` 仍被严格校验读取（未知键仍拒绝，兼容只限这三键），
    启动验证时输出不含敏感值的 WARNING 迁移提示，计划 2.0.0 移除；
    `auto_extract_glossary` 只在 `[term_extraction]` 段整体缺失时作为 `enabled`
    的兼容来源，规范段存在时以规范段为准；`term_qps`/`term_pool_max_workers`
    只按旧规则转发上游 SettingsModel，严格正文路径与项目候选提取不使用它们。
    配置中心不展示/写入这三键，磁盘旧键在配置中心保存时原样保留（不删除、
    不改写）并在下次启动继续 WARNING。旧 `cumulative_glossary.csv` 是历史输入而非权威：
    兼容期内保留，只读幂等迁移为未审核候选并保留
    `cumulative_glossary.csv.bak`，绝不进入 `user_glossary.csv` 或
    `effective_glossary.csv`；`effective_glossary.csv` 是可重建编译产物。

## 上游与历史参考

- 项目长期意图：[project.md](project.md)；未来方向与开放问题：[roadmap.md](roadmap.md)。
- 文档总入口与归档规则：[README.md](README.md)。
- 长期文档治理与事实冲突优先级：[governance/documentation.md](governance/documentation.md)；依赖升级流程：[governance/dependency-upgrade.md](governance/dependency-upgrade.md)。
- 上游接口研究：[pdf2zh-next-development-guide.md](pdf2zh-next-development-guide.md) 与 `docs/reports/` 下两份报告，均按各自顶部标注的版本适用范围阅读。
- 历史系统描述：`docs/archive/` 与 `CHANGELOG.md` 只用于追溯；已移除的工具产物需要时从 Git 历史查询。

归档与版本特定的上游资料是辅助上下文，不是当前实现的事实源；本文档与代码、测试冲突时，以代码和测试为准。
