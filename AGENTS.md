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
