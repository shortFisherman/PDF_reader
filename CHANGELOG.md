# 更新日志

## 未发布 — 文档体系与退役工具清理

- 新增 `docs/README.md` 作为文档总入口，明确长期文档、指南、治理、报告、已完成改进与
  历史归档的职责；同步 README、项目记忆、架构和文档治理规则。
- 从当前工作树移除已停用的 Superpowers/OpenSpec 工作区、规格、计划、验证报告和技能
  锁文件；历史内容继续由 Git 保留，不再复制到当前文档树。
- 清理相应的忽略/扫描配置，并增加仓库卫生回归，防止退役工具产物重新进入工作树。

## 未发布 — P1-01 候选术语提取从正文翻译解耦

- 新增 `src/pdf_reader/term_extraction.py`：项目自有 `TermExtractionClient`，
  使用标准库 urllib 走 OpenAI-compatible `POST /chat/completions` 受控接口；
  首版支持 `deepseek`/`openai`/`openai_compatible`，其余 Provider 稳定降级为
  unsupported。端点按 base_url 安全拼接（避免重复 `/v1`），请求体最小 schema
  （model/messages/stream=false），响应只解析受控 JSON
  `{"terms":[{"source","target"}]}`：条数（≤50）、字段长度（≤200）、控制字符、
  无效结构与响应正文（≤256 KiB）全部 fail-closed；重复项确定性去重。网络重试
  只针对超时/429/5xx，连接类错误、4xx 与格式错误不重试；base_url 只接受
  http/https 且必须带 host（拒绝 userinfo/query/fragment），/v1、/v1/ 与
  已是 /chat/completions 的路径拼接唯一确定；独立 QPS 限速与严格 timeout；
  客户端自身按 max_input_chars 前缀截断；成功与错误响应均显式 close；请求体、
  响应正文、Prompt 与 API Key 永不进入日志或异常消息。
- 新增 `src/pdf_reader/candidate_service.py`：`CandidateExtractionService` 在
  正文翻译最终验证并提交成功后才运行（单页/批量同一规则）；用 PyMuPDF 读取已
  抽取页源文本并统一 1-based 页码，输入为空跳过、超限按前缀确定性截断；候选
  只通过 `CandidateStore.record_observations` 原子写入 `term_candidates.json`，
  绝不进入 user/effective/global 权威词表或正文 SettingsModel；网络/解析/
  存储/不支持 Provider 全部降级为安全日志，不阻止正文 finish，也不产生第二个
  coordinator job 或悬挂线程。
- `CandidateStore` 新增批量原子 `record_observations` API：一次响应整体校验
  后单次 revision 原子合并，任一观察非法则整体不写；保留 accepted/rejected
  状态与 `accepted_target`/`rejected_targets`，候选变化不触发有效词表 stale。
- 新增冻结 `CandidateExtractionRuntimeConfig` 与独立 `[term_extraction]`
  配置：`enabled`（默认 true；未配置该段时跟随旧 `translation.auto_extract_glossary`
  显式值）、`timeout`（1-120s）、`qps`（1-100）、`max_workers`（1-8）、
  `retry_count`（0-3）、`max_input_chars`（1000-1000000）、独立 `prompt`；
  严格类型/范围/未知键校验接入 `AppSettings`、`validate_startup_requirements`
  与配置中心 schema（41→48 字段），配置示例同步。
- 文档同步：`README.md`、`config.example.toml`、`docs/architecture.md`、
  `docs/governance/glossary-upstream-boundary.md` 更新候选解耦事实；新增
  `docs/governance/term-extraction-client-boundary.md` 本地决策记录（上游无
  稳定纯提取公开 API → 项目自有小接口，不依赖 BabelDOC 深层私有类）。

## 未发布 — P0-05 术语合规验证、重试与提交门

- 新增 `src/pdf_reader/terminology_compliance.py`：独立验证模块，拆分为纯文本
  判定核心 `verify_translated_text` 与 PyMuPDF 提取包装
  `verify_translated_pdf`。纯函数负责规范化（CJK 相邻字符间空白移除、其余
  连续空白折叠为单空格）与逐条 pass/fail/unknown（纯 ASCII 词形按英文 token
  边界，其余按规范化精确子串）；包装只处理 `mono_pdf_path`（缺失时
  `dual_pdf_path`）、页数、提取异常与空文本边界并委托纯函数；空白文本、
  打不开、缺页、不可提取一律 UNKNOWN，不做 PDF 字符串替换。
- 源侧可用性门：`strict_glossary` 新增 `ActiveTermsResult` 与
  `resolve_active_terms_from_pdf`，显式区分 available/unavailable——rows 为空
  （`no_rows`）或源文本成功且无命中（`no_hits`）为 available+empty 并零成本
  跳过验证；源 PDF 打不开/抽取异常（`source_extraction_failed`）或抽取文本为
  空且存在 effective rows（`empty_source_text`）为 unavailable，单页/batch 在
  调用上游前发 `glossary_verification_unavailable`，不 `run_translation`、不
  replace、不 merge、job failed，不再把源侧不可用误当“无活跃术语”。
- `generate()` / `generate_batch()` 在 `replace_page` / `replace_pages` 之前
  增加提交门：验证通过才提交译文并合并自动词表；失败路径旧 `right.pdf` 完全
  不动、不 merge 任何 auto glossary。batch 首版采用整批原子验证与整批有界重试，
  不产生页级部分提交。
- 首次不合规最多在同一 job/document identity、同一输入 PDF、同一严格上下文与
  task identity 下整页/整批重试 1 次，不启动第二个 coordinator job；重试使用
  `SettingsModel` 深拷贝与独立 `attempt-2/output/` 目录，最终 system prompt 在
  原权威约束块之后追加确定性、有界（16 KiB UTF-8）的 `[术语合规纠错]` 块，
  整行纳入、超限只报告省略数量、不截断映射半行、不丢失原权威块。首次/重试
  worker 均正确 register/unregister/关闭，任务工作区在 worker 确认退出后整体
  清理。
- 生命周期/SSE：首次 FAIL 可发 `glossary_retry` progress 状态；最终失败分别发
  稳定错误码 `glossary_compliance_failed` 或 `glossary_verification_unavailable`，
  之后 job 以 failed 释放且不再发 finish；上游普通失败仍保持 `translation_error`。
  有活跃术语时按 attempt 分配明确进度窗口：attempt1 progress 钳制 0..95
  （上游 `finish`=95）、attempt2 progress 钳制 95..99（上游 `finish`=99，
  `glossary_retry` 阶段 `stage_current=2/2`）、最终验证通过提交=100，全序列
  单调不倒退；无活跃词条路径保持既有事件字节不变。合规日志只记录
  job/page/attempt/数量/状态/稳定短码，不记录术语正文、target、译文路径或
  异常原文。
- 无活跃权威词条时完全跳过验证与重试成本；`/api/stages` 与前端 fallback 增加
  `glossary_retry` 阶段标签。
- 文档同步：`README.md`、`docs/architecture.md`、
  `docs/governance/glossary-upstream-boundary.md` 更新“验证通过才提交”、一次
  整批重试、unknown 拒绝与零活跃词条零开销语义；不宣称模型输出绝对可靠。

## 未发布 — P0-04 严格正文术语路径

- 正文翻译固定关闭上游自动术语提取：`SettingsModel` 恒为
  `no_auto_extract_glossary=true`、`save_auto_extracted_glossary=false`；
  `translation.auto_extract_glossary` 在 P1-01 候选服务落地前对正文为惰性配置。
- 每次单页/批量翻译前在路由层执行旧 `cumulative_glossary.csv` 幂等迁移（只合入
  候选）→ 编译 `effective_glossary.csv` → 严格验证 fresh；任一失败返回 HTTP 500
  `glossary_prepare_failed`，不调用上游。任务占位顺序为“先 `coordinator.start`，
  成功后才做严格术语准备”；busy/shutdown 在任何准备写操作前返回 409，准备失败
  时 `coordinator.fail` 释放任务槽。`glossaries` 只指向本次有效词表，零权威行时
  安全省略；不再把全局/累计/auto candidate CSV 直接传给正文。
- 新增 `src/pdf_reader/strict_glossary.py`：预构建 `StrictTranslationContext`
  （携带 `document_id`/`pdf_hash` 身份边界，SSE 在抽取/上游前再次校验任务身份，
  迟到任务不重新编译）、本地活跃词条匹配器（大小写不敏感、连续空白等价、英文
  token 边界；`AD` 不命中
  `adherence`/`adverse`/`shadow`；不自动合并单复数/连字符/缩写全称）与
  `[权威术语约束]` Prompt 块（用户 Prompt 保留在前、块不可被覆盖；JSON 编码
  source/target；32 KiB UTF-8 确定性上限、整行纳入、超限只报告省略数量；不记录
  正文/Prompt/异常原文/本地路径/凭据）。
- 单页与批量共用同一严格设置构建函数；SSE 生成器在抽取真实输入 PDF 后应用活跃
  权威词条到最终 `custom_system_prompt`，无命中不修改 Prompt。
- 兼容说明：`auto_extract_glossary` 键仍被接受但不再影响正文；自动候选收集暂停，
  旧累计词表只会作为候选保留，不会自动升级为权威。P0-05 输出合规验证/重试/提交
  门尚未实施，因此本变更不宣称“最终译文一定合规”。
- 文档同步：`docs/architecture.md`、`docs/governance/glossary-upstream-boundary.md`、
  `README.md`、`config.example.toml` 更新严格路径事实与用户可见兼容说明。

## 未发布 — 日志工程化（统一日志管线、debug_trace 与前端错误上报）

- 主日志永久常驻 `logs/pdf_reader.log`（`DATA_ROOT/logs`，单文件 128 KiB × 5 份轮转备份，
  UTF-8；常规上限约 768 KiB），超过 14 天的编号轮转备份在启动与轮转后自动清理；统一托管
  `pdf_reader`/`werkzeug`/`pdf2zh_next`/`babeldoc` 四个 logger；四个 logger 共用同一对
  控制台 + 文件 handler 与同一个 `SafeFormatter`，第三方日志同样脱敏，不再可能经
  root/lastResort 绕过脱敏或重复输出。
- 主日志行格式改为 `ISO 时间、level、run_id、pid、thread、logger`，`run_id` 每次 setup
  生命周期唯一；任务前缀 `[job=... doc=... hash=... page=N|pages=A-B status=...]` 保持不变。
- `debug` 语义改为“详细诊断日志模式”：CLI/env/`[server].debug` 优先级不变，开启日志 DEBUG
  级别与 `debug_trace` 会话；Flask debugger 与 reloader 始终关闭
  （`app.run(debug=False, use_reloader=False)`），明确这是安全的详细诊断开关，不是无用的调试模式。
- `debug_trace.log` 改为按文档缓存目录的有界轮转诊断文件（2MB × 3 份备份），翻译会话内按
  `job_id` 过滤捕获项目与第三方日志，记录 start/end/elapsed 与失败 traceback；debug 关闭时
  零 IO，不再生成 timestamp 无限历史文件。
- 新增诊断边界：sys/threading 未捕获异常钩子、asyncio 事件循环异常处理、启动/关闭致命错误
  记录、HTTP 500 完整 traceback、前端 `window.error`+`unhandledrejection` 采集
  （`/api/client-errors` 仅 loopback、白名单字段、正文 ≤8KB、不记录 headers/cookie/prompt）。
- 脱敏扩展至 `custom_system_prompt`/`system_prompt`/`user_prompt`/`prompt` 类字段值
  （API Key、`sk-`、Bearer、`api_key` 原有规则不变）；第三方日志经同一 `SafeFormatter` 同样脱敏。
- README 增加面向非专业用户的排障步骤（先看主日志 ERROR/Traceback/job_id，必要时短期开
  debug，说明日志位置与轮转），并修复指向 `docs/engineering-improvement-plan-829.md` 与
  `docs/pdf2zh-configuration-expansion-design.md` 的失效链接，改为链接到
  `docs/completed improvements/` 下的真实文档；`docs/architecture.md` 同步当前日志架构事实。

## 未发布 — 配置能力扩展（第一批至第三批）

- 新增 41 个支持键：`[model]` 的 `send_temperature`/`send_reasoning_effort` 发送开关；
  `[translation]` 的 `min_text_length`/`qps`/`pool_max_workers`/`term_qps`/
  `term_pool_max_workers`/`auto_extract_glossary`/`primary_font_family`/
  `default_system_prompt`；`[pdf2zh]` 的 15 个 PDF 高级字段（短行、清理、富文本、
  兼容性、表格、扫描/OCR、行号、公式偏移、阈值与正则），其中 `formula_*` 映射到
  上游历史拼写 `formular_*`。
- 启动严格校验：未知 section/key/provider 直接报错；`openai_compatible` 缺
  `base_url` 启动失败；bool 不得冒充数值；数值必须有限（nan/inf 拒绝）；正则
  启动期预编译；发送开关与取值/Provider 组合校验。API Key 与 Prompt 原文不进入
  日志、异常或配置摘要。
- 兼容性：旧配置不带新键时行为不变；发送开关默认关闭保持旧请求行为；配置变化只
  影响之后执行的翻译或主动重译，PDF 哈希缓存、页面替换、累计术语与路由语义不变；
  上游请求缓存仍固定 `ignore_cache=true`。
- 文档与治理：`config.example.toml` 升级为完整配置手册；README 增加配置入口与
  行为边界；`docs/architecture.md` 同步当前配置对象、严格校验与 SettingsModel
  映射；依赖升级契约新增发送开关历史拼写、transform 与 PDFSettings 字段检查项。

## 2026-08-30 — P3 工程改进收口

- 工程改进清单（`docs/engineering-improvement-plan-829.md`）P3-01 至 P3-07 全部收口：P3-01 `2d63a0a`；P3-02 `54dae14`+`8652530`；P3-03 `6f6e79a`；P3-04 `6cf2af2`；P3-05 `f5c567e`+`f1638a3`（验收补强 `1ca789d`）；P3-06 `5282484`+`60cd77f`；P3-07 `5981217`（许可证与上游契约闭环由 `6cf2af2`/`5282484`/`60cd77f` 提供）。各条目状态、完成日期、验证证据与剩余风险已逐项记录。
- 同步收口长期文档：`docs/architecture.md` 核验基线更新到实现树 `1ca789d`（测试基线仍为 597 个 Python 测试，后续文档收口不改变实现）；`docs/roadmap.md` 移除“继续 P3 还是体验改进”的过时开放问题，并明确工程改进收口不等于授权新的产品方向。
- 最终实现树 `1ca789d` 上完整验证全绿：597 个 Python 测试；coverage line 94.8%、branch 88.3%；secret scan、Ruff lint/format、mypy、ESLint 与六套前端测试全过。定向验收：P3-02 205 passed 且 `python -m pdf_reader --help` 真实执行；P3-03 `npm test` 与 `npm run lint:js`；P3-06 定向 22、关键回归 74；P3-07 治理/密钥/版本/许可证/上游/文档组合 61；P3-05 worker 回收定向 3、相关回归 82 且同进程无 `translate-*` 残留线程。验收前后 cache（3 文件/112,503,805 B）与 logs（2 文件/3,750,478 B）逐文件 path/bytes/SHA256 不变。

## 2026-08-30 — P3-06 上游契约与文档治理

- 新增离线上游契约测试 `tests/test_upstream_contract.py`：固定 pdf2zh-next 2.9.0 / babeldoc 0.6.2
  的版本一致性、`SettingsModel` 消费字段与 `ENGINE_REGISTRY` 字段映射、承诺事件映射与未知事件忽略/
  心跳、`workspace/output` 注入与 mono→dual/glossary 路径、协作式取消/迟到丢弃/`join` 所有权；
  全部使用确定性 fake，不联网、不运行真实翻译、不需要 API Key。
- 新增文档治理测试 `tests/test_documentation_governance.py`：常青文档职责边界、链接可解析、
  README/architecture/dependency-upgrade 上游契约命令一致、易腐数字基线。
- 新增 `docs/governance/documentation.md`；同步更新 architecture/README/roadmap/
  dependency-upgrade 的契约入口与职责边界；project.md 仅补充文档地图。
- 不修改依赖版本、业务产品行为或工程清单状态；完整验证基线见本提交 verify 输出
  （测试数量等易腐数字以本提交为核验基线，不再单独列举）。

---

## 2026-08-27 — 长期文档系统

- 建立四份常青文档：README 作为项目入口，`docs/project.md` 保存长期意图，`docs/architecture.md` 记录当前实现，`docs/roadmap.md` 保存非授权的未来方向与依赖。
- 在 `AGENTS.md` 中加入文档阅读顺序、条件参考、冲突裁决和更新触发条件，使新 AI 会话能够恢复准确上下文。
- 将五份旧状态、旧架构、旧流程图和旧检查清单完整迁入 `docs/archive/`，并添加历史资料说明。
- 保留三份 PDF 翻译上游研究资料的原路径和正文，补充研究版本、当前锁定版本与适用范围。
- 本次变更只调整文档治理和资料组织，不改变应用行为、API、依赖、测试或运行时数据。

---

## 2026-06-29 — 对齐模型重构

### `align-model-rewrite`

将左右双栏对齐从分散在三处的比例同步重构为 `AlignmentController` 单一排他所有者，修复「翻译完成后图替换失对齐」与「Ctrl+滚轮缩放失对齐」两个长期 Bug。

**架构变更**：
- **新建** `static/modules/alignment-controller.js` — 导出 `createAlignmentController({leftEl, rightEl})`，以 `(pageIndex, intraPageOffsetPx)` 为对齐目标，20 个自测全绿
- **删除** `scroll-sync.js` 中 `setupScrollSync` 比例互推函数体，保留 `createSettleGate` / `setupPageDetection`
- **修改** `zoom.js` — 新增 `alignmentController` 参数，Ctrl+滚轮 / reset 后显式调 `controller.onZoomChange(newZoom, oldZoom)`
- **修改** `app.js` — 装配 controller、`onFinish` 翻译完成路径接入 `onImageLoaded`、`scrollToPage` 改走 `setLockTarget + realign`

**设计决策**：
- 排他性：仅 controller 写两栏 `scrollTop`（grep 断言通过）
- 目标语义：`(pageIndex, intraPageOffsetPx)` 用 `getBoundingClientRect` 相对栏计算，与 `scrollHeight` 比例脱钩
- 三源汇入：`onScroll` / `onImageLoaded` / `onZoomChange` 全部调 `realign()`
- 水平同步：`realign()` 内按 `lockSide` 比例同步 `scrollLeft`
- 跨页标准化：使用实际页间距（含 CSS margin）而非 `offsetHeight` 补偿
- 回流抑制：`suppressNextScrollFrom` 标记防止 `scrollTop` 写入触发的 scroll 事件回灌

**Bug 修复**：
1. 翻译完成后图替换导致左右栏不对齐 — `onImageLoaded` 在 `<img>.onload` 内调 `realign()` 兜底
2. Ctrl+滚轮缩放后左右栏不对齐 — `onZoomChange(r)` 比例缩放 `intraOffset` 后 `realign()` 双栏
3. 页面边界处左栏持续偏高 — 跨页标准化改用两页 `offsetTop` 之差而非 `offsetHeight`
4. 水平滚动条拖动后左右不同步 — `realign()` 新增 `scrollLeft` 比例同步
5. **`scrollToPage` 断点恢复失效** — `scrollToPage()` 调用 `realign()` 时未传入列参数，导致 `TypeError` 被 `requestAnimationFrame` 静默吞咽。修复：显式传入 `els.leftCol` / `els.rightCol`

**测试**：controller 20/20 + zoom 31/31 + translator 40/40 + pytest 193/193

| 文件 | 变更 |
|------|------|
| `static/modules/alignment-controller.js` | 新建 (570 行) |
| `static/modules/scroll-sync.js` | 修改 (删除比例互推，保留 settle gate) |
| `static/modules/zoom.js` | 修改 (新增 alignmentController 参数) |
| `static/app.js` | 修改 (装配 controller 并路由三路径) |
| `tests/run-alignment-controller-tests.mjs` | 新建 |
| `tests/run-alignment-repro-tests.mjs` | 新建 |
| `openspec/specs/column-alignment/spec.md` | 新建 (5 条 Requirement) |
| `openspec/specs/dual-column-reading/spec.md` | 修改 |
| `openspec/specs/page-zoom/spec.md` | 修改 |

## 2026-06-27 — 断点恢复

### `reading-position-resume`

新增阅读进度持久化功能：按 PDF 内容哈希（`pdf_hash`）在 `cache_dir/<hash>/reading_progress.json` 记录上次阅读页码，打开文档时自动跳回，卸载/关闭时通过 `navigator.sendBeacon` 可靠落盘。

- **进度存储**：`AppState` 新增 `_reading_progress_path` / `save_reading_progress` / `load_reading_progress`，原子写（`.tmp` + `os.replace`），越界钳制为 0，锁策略正确处理 `threading.Lock` 不可重入
- **HTTP 接口**：新增 `POST /api/reading-progress`（校验整数/文档已开/越界三层守卫），`POST /api/open` 响应新增 `saved_page` 字段
- **前端恢复**：`scrollToPage(index)` 通过 `scrollIntoView` 自动定位到上次页码，`requestAnimationFrame` 等占位高度就绪后执行
- **前端上报**：`pagehide`（主）+ `visibilitychange hidden`（兜底）触发 `saveProgress()`，优先 `sendBeacon` + 检查返回值 → 回退 `fetch keepalive`；`typeof` 类型防御；`progressCleanup` 闭包模式在切换文档时正确解绑
- **仅页码粒度**：不恢复缩放/页内偏移，不弹询问弹窗，仅卸载保存（切档不保存）

| 文件 | 变更 |
|------|------|
| `state.py` | 新增 `_reading_progress_path` / `save_reading_progress` / `load_reading_progress`；`open_pdf` 返回 `saved_page`；锁策略调用方持锁约定 |
| `routes.py` | 新增 `POST /api/reading-progress`（三层守卫 → 400/200） |
| `static/app.js` | 新增 `scrollToPage` 恢复定位 + `saveProgress` 卸载上报（sendBeacon + fetch keepalive）+ `progressCleanup` teardown |
| `tests/test_state.py` | +13 用例：save/load 全分支 + open_pdf saved_page + 原子写 + 进度文件不删除 |
| `tests/test_routes.py` | +6 用例：save 成功/未开/越界/非整数/文件落盘 + open 响应 schema |

**测试**：pytest 193/193、ruff check 全通过、ruff format 全通过

---

## 2026-06-26 — 日志系统改造

### `logging-system-overhaul`

全项目日志系统重构：用集中式 `logging_config.py` 替代 ad-hoc `logging.basicConfig`，移除 `debug_trace.py` 的 monkey-patch，为 10 个模块统一补入命名空间化 INFO/DEBUG 日志，实现 debug off 时仍有完整流程轨迹。

- **集中式日志配置**：`logging_config.setup_logging(debug)` 统一管理根 `pdf_reader` logger，控制台 + 轮转文件双 handler（5MB×5，utf-8），幂等安全
- **INFO 常驻流程日志**：`open_pdf` / `replace_page` / 翻译起止 / 术语合并完成 等里程碑始终输出，不再依赖 `config.DEBUG`
- **命名空间分级**：`pdf_reader.app` / `.state` / `.translate` / `.engine` / `.lifecycle` / `.glossary` / `.routes` / `.render` / `.extract` / `.debug_trace`，按模块可独立调级
- **翻译流程 page 关联**：`[page=N]` / `[batch=from-to]` 前缀贯穿抽页/编排/替换/合并全链路
- **错误上下文**：翻译异常 ERROR 记录含 page + provider + model + tmpdir + exc_info
- **第三方降噪**：werkzeug / pdf2zh_next / babeldoc 固定为 DEBUG，平时不打
- **启动摘要**：INFO 输出 provider/model/lang/cache_dir/dpi/debug，不含 api_key
- **移除 monkey-patch**：`AutomaticTermExtractor` monkey-patch 整段删除，术语排查靠 babeldoc `debug=True` tracking 文件 + 新日志定位
- **安全**：全项目 grep 复核，任何日志语句不输出 api_key 原值

| 文件 | 变更 |
|------|------|
| `logging_config.py` | **新增** — 集中式日志配置 + 第三方降噪 |
| `app.py` | 替换 `basicConfig` 为 `setup_logging`，移除 `import debug_trace`，命名空间改为 `pdf_reader.app`，启动 INFO 摘要 |
| `debug_trace.py` | 删 monkey-patch（`_apply_monkey_patches`/`patched_extract`/`_original_extract`/`init_debug`）；`log_step`→INFO 常驻、`log_token_usage`→DEBUG、`log_glossary_merge`→INFO；`trace_logger` 移除自建 handler 接入根配置；`debug_session` 保留 |
| `state.py` | `open_pdf` INFO（hash/pages/dim/cache）+ `replace_page`/`replace_pages` INFO/ERROR |
| `pdf_renderer.py` | `render_page` DEBUG |
| `pdf_extraction.py` | `extract_single_page`/`extract_pages` DEBUG |
| `translation_orchestrator.py` | `run_translation` 新增 `flow_label`，线程启停 INFO / 异常 ERROR / 超时 WARNING |
| `sse_stream.py` | 命名空间→`pdf_reader.translate`，`log_step`→`logger.info` 带 `[page=N]` 前缀，错误→ERROR 含上下文，传入 `flow_label` |
| `translation_lifecycle.py` | 命名空间→`pdf_reader.lifecycle`，签名加 `page` 参数贯穿关联 |
| `glossary_service.py` | 命名空间→`pdf_reader.glossary`，resolve DEBUG / merge WARNING 含路径 |
| `routes.py` | 命名空间→`pdf_reader.routes`，端点入口/校验失败 DEBUG |
| `engine_resolver.py` + `translation_settings.py` | 命名空间→`pdf_reader.engine`，`_settings_summary()` 安全摘要，`build_settings` DEBUG |
| `AGENTS.md` | 追加日志约定（命名空间表、级别策略、page 前缀、安全、命令） |
| `tests/test_logging_config.py` | **新增** — handler/级别/幂等/第三方降级/安全 测试 |
| `tests/test_flow_logging.py` | **新增** — 流程日志 INFO 常驻 + page 关联 + 错误上下文 测试 |
| `tests/test_debug_trace.py` | 删 monkey-patch 用例，更新 log_* 分层断言 |
| `tests/test_app.py` | `init_debug`→`setup_logging` 断言适配 |
| `tests/test_debug_patches.py` | **删除**（monkey-patch 已移除） |

**测试**：pytest 171/171、ruff check 零错误、ruff format 通过

---

## 2026-06-26 — 批量翻译

### `batch-translation`

新增批量翻译功能，支持页码范围翻译与全文翻译，将范围内全部页抽取为单一多页 PDF 一次性喂入 pdf2zh-next 引擎以获得跨页翻译连贯性。

- **范围翻译**：工具栏输入起/止页码，一次性翻译闭区间内全部页（含已翻译页重译覆盖）
- **全文翻译**：一键翻译整篇 PDF（等价于范围 1 到总页数）
- **批量确认保护**：范围超过 10 页弹出确认提示；≤10 页直接开始
- **进度展示**：翻译中显示「翻译第 from-to 页（共 N 页）」+ 引擎整体百分比/阶段标签（段落级）
- **工具栏折叠**：默认仅显示单页 Translate 按钮，点击 ▶ 展开缩放/Prompt/批量翻译等高级功能

| 文件 | 变更 |
|------|------|
| `pdf_extraction.py` | 新增 `extract_pages` 多页抽取 |
| `state.py` | 新增 `extract_pages`/`replace_pages` 锁内批量原语 |
| `translation_settings.py` | `build_settings` 参数化 `pages` |
| `translation_lifecycle.py` | 新增 `merge_glossary_only` 仅术语表合并 |
| `sse_stream.py` | 新增 `GenerateBatchContext`/`format_batch_info`/`generate_batch` |
| `routes.py` | 新增 `POST /api/translate-batch` SSE 端点 |
| `templates/index.html` | 工具栏新增起/止页输入、范围/全文按钮、折叠切换 |
| `static/modules/dom.js` | 注册新元素引用 |
| `static/style.css` | 工具栏样式、折叠布局、紧凑尺寸 |
| `static/modules/translator.js` | 新增 `translateBatch` SSE 客户端 |
| `static/app.js` | 新增批量翻译逻辑、确认保护、进度展示、互斥控制 |
| `tests/test_pdf_extraction.py` | 多页抽取顺序/页数测试 |
| `tests/test_state.py` | 批量回填与 `translated_pages` 更新测试 |
| `tests/test_routes.py` | 批量端点页码校验与 SSE 测试 |
| `tests/test_sse_stream.py` | `generate_batch` 事件流测试 |
| `tests/test_translation_lifecycle.py` | `merge_glossary_only` 测试 |
| `tests/test_services.py` | `build_settings` 参数化测试 |
| `tests/run-translator-tests.mjs` | `translateBatch` 前端测试 |

**测试**：pytest 142/142、前端 40/40、ruff 全通过

---

## 2026-06-25 — Ctrl+滚轮页面缩放

### `ctrl-wheel-zoom`

为双栏 PDF 阅读器新增 Ctrl+滚轮缩放功能：

- **交互**：按住 Ctrl 滚动滚轮缩放页面（上滚放大、下滚缩小），以鼠标位置为锚点，非 Ctrl 滚轮保持正常滚动
- **范围**：25%–220%，步进 10%，到达边界后继续滚动无反应
- **同步**：左右两栏缩放同步 + 竖向/横向滚动同步
- **实现**：CSS 变量 `--zoom` 驱动渲染宽度（非 `transform: scale`），与现有滚动同步、当前页检测、懒加载兼容
- **工具栏**：缩放百分比实时显示 + 绿色重置按钮（回到 100%，保持当前视图）

| 文件 | 变更 |
|------|------|
| `static/modules/zoom.js` | 新增 — Ctrl+滚轮缩放引擎 + 内联单元测试（28 项） |
| `static/style.css` | `--zoom` / `--page-ratio` CSS 变量，calc 驱动宽高，`safe center` + 溢出处理 |
| `static/modules/scroll-sync.js` | 新增横向滚动同步（`scrollLeft` 比例跟随） |
| `static/modules/dom.js` | `--page-ratio` 替代内联 `paddingBottom`，增加 zoom 元素引用 |
| `static/app.js` | 接入 `setupZoom`，重置绑定，dispose 清理 |
| `templates/index.html` | toolbar 增加 zoom-level / zoom-reset 控件 |
| `tests/run-zoom-tests.mjs` | 新增 — jsdom 测试运行器 |
| `package.json` | 新增 `test:zoom` 脚本 |

**测试**：zoom 28/28、translator 30/30、task-4.5 29/29、ruff 全通过、pytest 126/127

---

### `fix-reloader-orphan-startup`

Flask `debug=True` + reloader 模式下，`python app.py` 起两个进程（父 reloader + 子 worker）。Ctrl+C 只杀父进程，子进程有时残留并继续占用 5000 端口。再启动时新实例绑不上端口，请求被老孤儿接走，终端收不到任何日志。

- **`start.bat`**：启动前加 `for /f ... netstat ... findstr ":5000 " ... taskkill ...` 清理占用 5000 的遗留进程
- 不改代码逻辑，仅加固启动脚本

---

## 2026-06-25 — 前端翻译模块测试

### `add-translator-frontend-tests`

为 `translator.js`（`translateCurrentPage`）和 `sse-client.js`（`readSSEStream`）新增 9 个 jsdom 自动化测试。被测模块源码未改。

| 组 | 用例数 | 覆盖内容 |
|---|--------|----------|
| sse-client | 4 | 单 chunk 多事件、跨 chunk 拼接、非法 JSON 跳过、空流终止 |
| translator | 5 | 回调顺序、分段后缀、SSE error→onError、HTTP !ok→onError、prompt 透传 |

- **运行方式**：`npm run test:translator`（30 断言，退出码 0/1）
- **实现**：新建 `tests/run-translator-tests.mjs`，沿用项目 `.mjs` + jsdom + `new Function()` 模式，Node `stream/web` 提供 `ReadableStream`/`TextDecoder` polyfill

---

## 2026-06-25 — TranslateResult 协议

### `add-translate-result-protocol`

`translation_lifecycle.finish_translation` 用 `Any` 鸭子类型直访 pdf2zh-next 字段，与上游数据结构强耦合；`mono_pdf_path → dual_pdf_path` 回退路径无测试覆盖。

- **引入 `TranslateResult(Protocol)`**：显式声明 `mono_pdf_path` / `dual_pdf_path` / `auto_extracted_glossary_path`（均 `Optional[Path]`），形参从 `Any` 收紧为 `TranslateResult`
- **新增 4 个契约测试**：mono 替换、mono→dual 回退、双空跳过、glossary 合并
- **影响文件**：`translation_lifecycle.py`（类型收紧）、`tests/test_translation_lifecycle.py`（新建）

---

## 2026-06-25 — 修复并发资源清理

### `fix-concurrency-resource-cleanup`

两个运行时缺陷：

1. **临时目录泄漏**：SSE 生成器在 error / 无结果 / `GeneratorExit` 路径提前退出时不清理 `tmpdir` 和 `output_dir`
2. **extract 未持锁**：`routes.py` 直接传 `state.left_doc` 给 `pdf_extraction`，绕过 `threading.Lock`，与持锁的 `render_page` 并发存在数据竞争

修复：

| 修复 | 文件 | 措施 |
|------|------|------|
| 清理兜底 | `sse_stream.py` | `generate` 包裹在 `try/finally`，`finally` 中 `shutil.rmtree(ignore_errors=True)`，任意退出路径均清理 |
| 职责收敛 | `translation_lifecycle.py` | 移除 `finish_translation` 末尾的 `rmtree` 调用，清理职责集中到 `generate` |
| extract_page 持锁 | `state.py` | 新增 `extract_page` 方法，在 `_lock` 内操作 `_left_doc`，约束 `extract_func` 不得回调 AppState |
| 路由层重构 | `routes.py` | 移除直接传递 `left_doc` 的代码，改为 `ctx.extract_page` Callable 闭包 |

测试：`test_sse_stream.py`（4 类清理场景）+ `test_state.py`（3 类并发场景），共 ~328 行新增/调整

---

## 2026-06-24~25 — CI 与 Lint 清理

### `add-ci-and-lint-cleanup`

- **清理弃用 Lint 规则**（`ruff.toml`）：移除 `ANN101`/`ANN102`，消除每次 `ruff check` 的无效果告警
- **新增 GitHub Actions CI**（`.github/workflows/ci.yml`）：push/PR 到 `main` 自动运行 `ruff check .` + `pytest -q`，环境 `windows-latest` + Python 3.12
- **修复 CI 依赖**（`requirements.lock`）：pytest 纳入锁定文件，配置 pip 缓存路径
- **硬前置**：依赖 `defer-config-validation`（否则 CI 全新克隆无法 `import config`）

---

## 2026-06-24 — 延迟配置校验

### `defer-config-validation`

`config.toml` 被 `.gitignore` 忽略，全新克隆（CI、新协作者）中 `import config` 即崩溃，测试套件无法运行。

- **配置缺失容错**（`config.py`）：`config.toml` 不存在时 `CONFIG` 回退空字典，必填键均用 `.get()` + 默认值
- **校验延迟**（`config.py` + `engine_resolver.py`）：移除 import 期 `raise ValueError`，改为内部 `_validate_required_config()`，在 `resolve_engine` 入口才触发
- **新增 4 个测试**（`tests/test_config_deferred.py`）：无文件导入成功、缺失 MODEL 报错、缺失 API Key 报错、已配置不变
- **增强 mock_config**（`tests/conftest.py`）：fixture 不再依赖 `config.toml`

---

## 2026-06-24 — 修复初始加载不触发 & 滚动同步拖拽感

### `fix-initial-load-and-sync-lag`

**现象：** `fix-lazy-load-scroll` 引入的 settle gate（150ms 去抖）带来两个回归：(1) 打开 PDF 后不做任何操作，页面始终不加载，必须手动滚动才会触发；(2) 双栏滚动同步用 `requestAnimationFrame` 延迟 1 帧，拖动时有明显滞后/拖拽感。

**根因：**
- **(1)** settle gate 的 `onSettle` 回调仅在 scroll 事件驱动下触发。初始无 scroll → timer 不启动 → IO 标记的 `pendingLoad` 永远不被扫描。随后用 `setTimeout(0)` + `trigger()` 尝试修复，但 `setTimeout` 在浏览器事件循环中可能先于 IntersectionObserver 回调触发（rendering update 可被跳过）→ `pendingLoad` 仍为空 → 空扫。
- **(2)** `setupScrollSync` 用 `requestAnimationFrame` 将对侧 `scrollTop` 赋值推迟到下一帧，连续拖动时每帧晚 1 帧 (~16ms) → 视觉拖拽感。

**修复：**

| # | 说明 | 文件 |
|---|------|------|
| 1 | 初始加载：`setupIntersectionObserver` 内用 `requestAnimationFrame` 做直接视口扫描，绕过 settle gate，不依赖 IO 时序 | `lazy-loader.js`, `app.js` |
| 2 | 滚动同步：rAF 替换为同步 `scrollTop` 赋值 + `setTimeout(0)` 解锁反回环 guard | `scroll-sync.js` |
| 3 | 内联测试 & delta spec 更新 | `scroll-sync.js`, `lazy-loading/spec.md`, `dual-column-reading/spec.md` |

**关键决策：** 初始加载不用 settle scan 路径，改在 `lazy-loader.js` 内以 rAF 直接扫描 `getBoundingClientRect`——此时布局已计算、几何可信，与 IO 回调时序完全解耦。`trigger()` 方法保留但不再用于初始加载。

**delta spec：** lazy-loading +1 added，dual-column-reading +3 modified

**测试：** 107/107 Python tests pass，4 个 settle gate inline tests

---

## 2026-06-24 — 修复懒加载与滚动同步

### `fix-lazy-load-scroll`

**现象：** 三个前端交互缺陷严重影响大文档可读性：(1) 拖滚动条长距离跳转淹没 ~500 次 `/api/page/*` 请求；(2) 左右两栏单向绝对 scrollTop 同步导致错位，图片加载后高度跳变出现"一边塞两页"；(3) 翻页边界 `load→unload→load` 振荡与重复请求。

**根因：** 懒加载与滚动同步的脆弱设计——IO 即时加载无去抖、单向绝对值同步不兼容双栏高度差、加载卸载无统一闸门。

**修复（16 任务，5 组）：**

| 组 | 说明 | 文件 |
|---|---|---|
| 1 | 滚动稳定闸门（150ms settle gate） | `scroll-sync.js`, `app.js` |
| 2 | CSS `width:100%` 消除布局跳变 | `style.css`, `dom.js` |
| 3 | 双向按比例滚动同步（rAF + syncing 防回环） | `scroll-sync.js` |
| 4 | 懒加载重构：IO 降级为候选标记器 + 落点加载 + 延迟卸载（RECLAIM_DISTANCE=10）+ 容器级 `dataset.loaded` 守卫 | `lazy-loader.js`, `app.js` |
| 5 | 手动回归验证 | — |

**架构核心：** 引入 settle gate 统一收敛所有 load/unload/page-detection 到滚动停止后执行。IO 观察者不再直接调用 load/unload，改为仅标记 `pendingLoad`/`pendingReclaim` 候选集；settle 扫描时仅对视口 ±2 页加载，扫过页丢弃；离开视口 >10 页且在 settle 后确认才卸载。

**关键参数：** `SETTLE_MS=150`, `BUF=2`, `RECLAIM_DISTANCE=10`, IO `rootMargin=200%`

**执行方式：** subagent-driven development，每任务 TDD（RED→GREEN）+ spec review + quality review，最终审查发现并修复 settle gate 回调一次性失效的 critical bug。

**delta spec：** lazy-loading +2 added / +3 modified，dual-column-reading +3 modified

**测试：** JS inline tests 57 个全通过，前端手动回归 4 场景

---

## 2026-06-23 — 修复术语累计功能失效 + 拆分 pdf_renderer.py 双重职责

### `fix-glossary-merge-bom` — 术语累计失效修复

**现象：** 翻译论文后从不生成 `cumulative_glossary.csv`，跨页术语一致性功能完全失效。调试日志显示术语提取正常运行（消耗 token），但合并步骤 `elapsed=0.00`（空操作）。

**根因：** BOM 编码不匹配。babeldoc 用 `utf-8-sig`（带 BOM 头）写入自动提取的术语表 CSV，但 `glossary_merger.py` 用 `utf-8`（不处理 BOM）读取。BOM 字符 `\ufeff` 粘到第一列名上，`csv.DictReader` 看到的是 `\ufeffsource` 而非 `source`，`row.get("source")` 全部返回 `None`，所有术语被静默丢弃，`source_targets` 为空导致不写文件。

**修复：**
| 文件 | 改动 |
|------|------|
| `glossary_merger.py` | 两处 CSV 读取编码 `utf-8` → `utf-8-sig`（剥离 BOM，对无 BOM 文件安全） |
| `glossary_merger.py` | 术语文件未找到时补 warning 日志（原静默返回） |
| `glossary_service.py` | 跳过合并时补 warning 日志，输出两路径值便于排查 |
| `tests/test_glossary_merger.py` | 新增 `test_bom_encoded_auto_glossary_is_merged` 回归测试，模拟 babeldoc 真实输出格式（BOM + 3 列 `source,target,tgt_lng`） |

**测试：** 107 个测试全通过，ruff 零错误

---

## 2026-06-23 — 拆分 pdf_renderer.py 双重职责

### `split-pdf-renderer`

`pdf_renderer.py` 包含两个无关函数：`render_page()`（渲染 PNG）和 `build_settings()`（组装翻译参数）。拆分为独立模块：

| 改动 | 说明 |
|------|------|
| `translation_settings.py` — **新增** | 迁入 `build_settings()`，负责组装 pdf2zh-next 翻译参数 |
| `pdf_renderer.py` — **精简** | 删除 `build_settings()` 及相关 import，回归单一职责：PDF 页面渲染 |
| `routes.py` — **修改** | import 从 `pdf_renderer` 改为 `translation_settings` |
| `tests/test_services.py` — **修改** | 同上 |

---

## 2026-06-22 — 模块内聚性重构

### `refactor-module-cohesion`

**解决 `services.py` 杂物堆、`sse_stream.py` 职责越界、接口耦合过大等问题：**

| 改动 | 说明 |
|------|------|
| `services.py` → **删除** | 5 个函数按职责拆分到 4 个新模块 |
| `file_hash.py` — **新增** | `sha256()` 纯文件哈希，无其他模块依赖 |
| `engine_resolver.py` — **新增** | `resolve_engine()` + `build_engine_kwargs()` + `CONFIG_ATTR_MAP` |
| `pdf_renderer.py` — **新增** | `render_page()` + `build_settings()` |
| `translation_lifecycle.py` — **新增** | `finish_translation()` — 翻译后持久化、术语合并、清理 |
| `sse_stream.py` — **修改** | `GenerateContext` 不再持有 `AppState`，后处理委托给 `translation_lifecycle` |
| `glossary_service.py` — **修改** | `resolve_glossary_paths(state: AppState)` → `resolve_glossary_paths(cache_path: Path | None)` |
| `debug_trace.py` — **修改** | 删除 `setup_file_handler` / `cleanup_file_handler` 重复函数，合并入 `debug_session` |

**关键设计决策：**
- `GenerateContext` 从持有整个 `AppState` 缩小为 `replace_page: Callable` + `glossary_cache_path: Path | None`，页面号在 routes.py 中由 lambda 预绑定
- `translation_lifecycle.finish_translation()` 承担 replace_page + merge_after_translate + rmtree，`sse_stream.generate()` 回归纯 SSE 格式化
- 逐组推进 + 逐组测试：4 个任务组各以 `pytest tests/ -v` 为安全门
- 13 个子代理分派执行，14 个 commit

**测试：** 106 个测试全通过，ruff 零错误

---

## 2026-06-21 — 大规模优化重构

### A. 强化 PDF 状态并发安全 (`harden-pdf-state-concurrency`)

**修复两处运行时代码缺陷：**

- **渲染竞态修复** — `AppState.render_page` 原实现在锁外执行 pymupdf 渲染，并发 `replace_page` 关闭/重开 doc 可导致段错误。修复后渲染全程持 `_lock`，消除竞态窗口。
- **页码校验** — `/api/translate/<page>` 新增越界检查，`page < 0` 或 `page >= page_count` 返回 `400` 而非触发底层 `pymupdf.insert_pdf` 异常。
- 结论：单锁架构已正确，无需双层锁。保留 `test_concurrent_replace_different_pages` 作回归保护。

**涉及文件：** `state.py`、`routes.py`、`tests/test_state.py`、`tests/test_routes.py`

---

### B. 抽取翻译服务层 (`extract-translation-service-layer`)

**`routes.py:translate_page` 从 230 行巨函数薄化为 ≤20 行路由层，拆分为 5 个独立服务模块：**

| 模块 | 职责 | 接口 |
|------|------|------|
| `pdf_extraction.py` | 单页 PDF 抽取 | `extract_single_page(doc, page, tmpdir) -> Path` |
| `translation_orchestrator.py` | 翻译编排（asyncio 线程+事件队列） | `run_translation(settings, pdf) -> Iterator[dict]` |
| `sse_stream.py` | SSE 事件格式化+流程组合 | `generate(ctx: GenerateContext) -> Iterator[str]` |
| `glossary_service.py` | 术语表路径解析+翻译后合并 | `resolve_glossary_paths(state)`, `merge_after_translate(...)` |
| `debug_trace.py` | 调试追踪（骨架接口，变更 D 增强） | `log_step`, `log_token_usage`, `setup_file_handler`, `cleanup_file_handler` |

**关键设计决策：**
- 全部模块暴露纯函数，无类样板代码
- `TranslationError` 异常在迭代结束后传播，替代 `error_info` 字符串
- `GenerateContext` dataclass 打包组合参数
- `format_sse_event` 纯函数，字节级黄金样本回归测试保证兼容
- `finally` 块统一清理临时目录

**涉及文件：** 新增 5 个模块 + 对应测试文件

---

### C. 数据驱动引擎配置 (`data-driven-engine-config`)

**用声明式 `EngineSpec` 注册表替代硬编码的 `PROVIDER_MAP`（10 条目）+ `FIELD_MAP`（79 条目）：**

```python
@dataclass(frozen=True)
class EngineSpec:
    provider: str           # 引擎标识
    settings_cls: type      # pdf2zh-next Settings 类
    field_map: dict         # unified_name → engine_field_name
    required_fields: tuple  # 必填字段

ENGINE_REGISTRY = [EngineSpec(...), ...]  # 10 引擎，各一行
```

**收益：**
- 新增引擎仅需追加一行 `EngineSpec`，不再需在 ~10 处各加条目
- `build_engine_kwargs` 遍历 `spec.field_map` 动态构造参数，不再硬编码 8 个字段名
- 运行时 `model_fields` 检查，对 pdf2zh-next 版本升级有容错
- 等效性回归测试覆盖全部 10 引擎新旧输出对比

**涉及文件：** `config.py`（+EngineSpec, -PROVIDER_MAP, -FIELD_MAP）、`services.py`、新增 `tests/test_engine_registry.py`

---

### D. 隔离调试追踪 (`isolate-debug-tracing`)

**消除 import-time 副作用，调试逻辑完全隔离：**

- **消除副作用** — `app.py` 不再在 import 时硬编码 `config.DEBUG = True` 或无条件 monkey-patch。改用 `--debug` CLI 参数 + `config.toml` 的 `[debug]` 段驱动。
- **配置优先级** — CLI `--debug` > `[debug] enabled` > `[server] debug` > 默认 `False`
- **统一模块** — `debug_patches.py` 删除，逻辑并入 `debug_trace.py`。暴露接口：`init_debug()`、`debug_session`（上下文管理器）、`log_step`、`log_token_usage`、`log_glossary_merge`
- **零开销** — `config.DEBUG = False` 时所有调试函数立即返回，无字符串格式化、无 IO、无 handler 创建
- **容错降级** — monkey-patch 失败仅记日志不崩溃，文件 handler 创建失败静默降级

**涉及文件：** `debug_trace.py`（+176行）、`app.py`（-副作用，+argparse）、`config.py`（+`_resolve_debug`）、`sse_stream.py`（`debug_session` 上下文）、删除 `debug_patches.py`

---

### E. 前端模块化 (`modularize-frontend`)

**`static/app.js` 从 335 行单体文件拆分为 6 个 ES Module：**

| 模块 | 职责 | 行数 |
|------|------|------|
| `app.js` | 入口，持有共享状态，绑定事件 | ~60 |
| `modules/dom.js` | DOM 引用、元素创建、占位符计算 | ~75 |
| `modules/sse-client.js` | SSE 流解析（纯函数，无 DOM） | ~30 |
| `modules/scroll-sync.js` | 滚动同步 + 页码检测 | ~50 |
| `modules/lazy-loader.js` | IntersectionObserver 懒加载 | ~30 |
| `modules/stages.js` | 从后端 `/api/stages` 拉取阶段标签 | ~30 |
| `modules/translator.js` | 翻译编排（回调驱动，无 DOM） | ~50 |

**关键设计决策：**
- `index.html` 改用 `<script type="module">`
- `STAGE_LABELS` 前端不再硬编码，改为 `GET /api/stages` 拉取，失败时回退内置副本
- 模块为无状态工具函数，共享状态集中在 `app.js`
- 前端 UX 字节级兼容，无需构建工具

**涉及文件：** `static/` 目录重构、`templates/index.html`、`routes.py`（+`/api/stages` 端点）

---

### 统计

| 指标 | 重构前 | 重构后 |
|------|--------|--------|
| 后端模块 | 7 | 14 |
| 前端模块 | 1 | 7 |
| 单元测试 | 45 | 106 |
| OpenSpec specs | 9 | 17 |
| routes.py 最大函数 | 230 行 | ~30 行 |
| 引擎配置新增成本 | ~10 处修改 | 1 行 |
| 调试副作用 | import 时触发 | CLI/config 驱动 |
