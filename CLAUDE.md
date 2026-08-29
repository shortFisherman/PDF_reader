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

## 项目长期文档

以下三份文档承载项目的长期记忆；由 AI 按当前任务自行判断是否需要查阅：

- `docs/project.md`：记录项目为什么存在、项目背景、长期意图、常青原则和产品边界。
- `docs/architecture.md`：严格记录当前 HEAD 已实现的架构、技术事实和运行边界。
- `docs/roadmap.md`：记录未来的候选方向、开放问题、依赖关系和决策状态。

<!-- CODEGRAPH_START -->
## CodeGraph

In repositories indexed by CodeGraph (a `.codegraph/` directory exists at the repo root), reach for it BEFORE grep/find or reading files when you need to understand or locate code:

- **MCP tools** (when available): `codegraph_explore` answers most code questions in one call — the relevant symbols' verbatim source plus the call paths between them. `codegraph_node` returns one symbol's source + callers, or reads a whole file with line numbers. If the tools are listed but deferred, load them by name via tool search.
- **Shell** (always works): `codegraph explore "<symbol names or question>"` and `codegraph node <symbol-or-file>` print the same output.

If there is no `.codegraph/` directory, skip CodeGraph entirely — indexing is the user's decision.
<!-- CODEGRAPH_END -->

<comet-ambient-resume>
<!-- Managed by Comet. Edits inside this block may be replaced by comet init/update. -->
<!-- Contract: comet.resume_probe.v2 -->
