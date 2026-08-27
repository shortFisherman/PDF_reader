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
