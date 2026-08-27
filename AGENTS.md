## 项目文档系统

本仓库采用新构建的长期文档系统。四份常青文档是后续 AI 恢复项目上下文的首要入口；历史资料和工具产物只能作为补充证据。

### 启动顺序

如果当前请求符合下方 Comet Ambient Resume 的探测条件，先执行 `comet resume-probe`，再按本节读取项目文档。Comet 托管块中的显式调用、流程延续和其他例外继续优先适用。

### 必读规则

1. 任何项目任务先读 `README.md`，了解入口、能力、边界和验证方式。
2. 涉及项目目标、范围、原则或产品取舍时，读 `docs/project.md`。
3. 涉及代码、实现、调试、测试、依赖或技术判断时，读 `docs/architecture.md`。
4. 涉及未来计划、功能选择、优先级或路线状态时，读 `docs/roadmap.md`。

### 条件参考

涉及 PDF 翻译接口、事件协议、SettingsModel、Provider、BabelDOC 或上游版本时，额外读取：

- `docs/pdf2zh-next-development-guide.md` — pdf2zh-next 开发参考，按顶部版本适用范围核验。
- `docs/reports/pdf2zh-internals-report.md` — pdf2zh v1 历史内部报告，不代表当前 pdf2zh-next 实现。
- `docs/reports/babeldoc-vs-pdf2zh-next-report.md` — 指定版本的上游对比快照。

查历史时读取 `CHANGELOG.md`、`docs/superpowers/`、`openspec/changes/archive/` 和 `docs/archive/`，但不得把历史内容当成当前事实或授权。

### 冲突裁决

- 当前行为事实：代码和测试高于 `docs/architecture.md`；发现冲突时必须在同一变更中修正 architecture。
- 项目意图与原则：`docs/project.md` 高于 README、roadmap 和历史资料；AI 不得自行改变其中原则。
- 未来方向：`docs/roadmap.md` 只允许指导讨论和计划，不允许直接实施。
- 归档、CHANGELOG、旧设计、旧计划和验证报告只能用于追溯。
- 原则冲突或用户意图不明确时，必须询问用户，不能从历史资料推断授权。

### 更新触发条件

- 用户可见功能、安装、启动、配置或验证方式变化：更新 `README.md`。
- 模块、API、数据流、状态、依赖、并发或运行边界变化：与代码同一变更更新 `docs/architecture.md`。
- 项目目的、长期意图、常青原则或产品边界变化：只有用户明确确认后更新 `docs/project.md`。
- 未来方向、优先级或路线状态变化：更新 `docs/roadmap.md`，但不得自动实施。
- pdf2zh-next/BabelDOC 版本升级：复核三份上游参考资料的适用范围并更新版本说明。

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

## 日志约定 (Logging Conventions)

新模块写日志前先看 `logging_config.py` / `debug_trace.py` 顶部的 `getLogger("pdf_reader.<concern>")` 命名空间分配，沿用同款命名。

### 级别策略
- **ERROR**: 请求级失败，带 exc_info
- **WARNING**: 可恢复降级（超时、文件缺失）
- **INFO**: 流程里程碑常驻（开启、翻译、替换、合并完成）
- **DEBUG**: 高频/细节（渲染、抽取、token 用量、端点入口）

### page 关联前缀
- 翻译流日志自带 `[page=N]` 或 `[batch=from-to]` 前缀
- 由调用点在消息文本中内联拼入，formatter 不注入

### 安全
- 日志中不输出 api_key 原值
- settings 摘要只取 provider/model/lang/path 等安全字段
- API Key 用 `config.MODEL_API_KEY` 访问，不在日志中插值

### 命令
```powershell
ruff check .          # lint
ruff format --check . # 格式检查
pytest -q             # 全量测试
```

<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->

## Comet Ambient Resume

In this repository, before starting work that may need code changes or investigation, pass the current user request to the read-only probe when a Comet workflow may already be active: `comet resume-probe . --stdin --json`.

- If the user explicitly invokes any Comet Skill through the host (for example, `@comet`, `/comet`, `@comet-native`, or `/comet-hotfix`), that explicit invocation takes precedence over this resume protocol; do not run the resume probe, and enter the invoked Skill directly.
- If the user explicitly invokes a non-Comet skill or slash command through the host, the task intent is already explicit in that invocation: do not run the resume probe, and execute the invoked skill directly.
- If you are already inside a Comet flow (including while waiting for the user to answer a question you asked in that flow), do not run the resume probe; treat replies such as option picks as continuation of the current change and proceed directly with the chosen option.
- Trust only the returned `workflow`, `skill`, and `entrySource`; project configuration or the no-config compatibility fallback alone selects them. Do not scan or switch to the other workflow.
- If the probe returns `auto_resume`, briefly state the selected active change and enter the permanent entry in `nextCommand`. Do not treat a state command as the resume entry or advance it blindly.
- If the probe returns `ask_user`, ask one short question and wait.
- If the current request did not explicitly invoke a Comet Skill and the probe returns `out_of_scope` or `none`, do not enter the Comet workflow.
- An `out_of_scope` or `none` result only means do not enter the Comet workflow for this new request; it never pauses or exits a Comet flow that is already in progress.
- If configuration or state is invalid and `nextCommand` is absent, stop and report the reason; do not guess another workflow.
- Never attach unrelated work merely because an active change exists. The Native entry inspects uncommitted work; the probe does not attribute it automatically.
</comet-ambient-resume>
