# 工具与工作流目录治理

> 建立日期：2026-08-30（P3-07）。本文档集中说明仓库中 AI/工作流/工具目录的职责、
> 是否必须跟踪、生成与维护方、能否重建，以及事实来源优先级，避免新会话把工具状态
> 误当成项目事实，也避免在业务重构时顺手删除仍在使用的工具遗留。

## 事实来源优先级

1. 当前代码、测试与可复现命令（`requirements.lock`、`package-lock.json`、`scripts/verify.ps1`）。
2. `docs/architecture.md`（严格描述当前 HEAD）。
3. `docs/project.md`（长期意图）与 `docs/roadmap.md`（未授权候选）。
4. `openspec/`、`docs/superpowers/`、`docs/archive/`、`CHANGELOG.md` 等历史/规范资料，只用于追溯。
5. 工具目录中的配置与技能说明属于操作指令，不是项目事实源。

## 目录清单

| 目录 | 是否跟踪 | 职责 | 生成/维护方 | 可否重建 | 事实来源角色 |
|---|---|---|---|---|---|
| `.agents/` | 跟踪 | 项目级 agent skills（comet 等）与子代理说明 | 用户/Agent 技能工具（skill installer） | 可从上游技能仓库重新安装，但本地定制会丢失 | 操作指令；不作为代码事实 |
| `.codex/` | 跟踪 | Codex 本地配置（hooks、工作流规则） | Codex/用户 | 可重建（重新生成配置），当前文件为基线 | 操作指令 |
| `.comet/` | 仅跟踪 `config.yaml` | Comet 工作流配置与运行时状态（其余内容已忽略） | Comet CLI | `comet init` 可重建配置，运行时状态不可完整重建 | 操作指令；工作流状态不进入架构事实 |
| `.opencode/` | 跟踪 | OpenCode Go 命令与路由（OP DeepSeek 子 Agent 等） | OpenCode/用户 | 可重建（重新安装/生成命令） | 操作指令 |
| `openspec/` | 跟踪 | OpenSpec 规格、设计、任务与变更归档 | openspec CLI / AI 工作流 | 可重建（内容在 Git 历史中） | 次级规范资料；与代码冲突时以代码为准 |
| `.codegraph/` | 不跟踪（自带 `.gitignore`） | CodeGraph 索引数据库/daemon 状态 | `codegraph` CLI | 可重建（重新索引） | 代码检索辅助；不替代源码事实 |
| `.superpowers/` | 不跟踪 | 历史 superpowers 工作区（内部 `.gitignore` 排除全部内容） | 历史 AI 工作流 | 无需重建，仅本地追溯 | 无 |
| `.firecrawl/` | 不跟踪 | Firecrawl 本地运行数据 | Firecrawl 工具 | 可重建 | 无 |
| `.worktrees/` | 不跟踪（已忽略） | Git worktree 本地布局 | Git/用户 | 可重建 | 无 |
| `.git-rewrite/` | 不跟踪（已忽略） | git-filter-repo 历史重写临时状态 | git-filter-repo | 可重建，纯临时状态 | 无；不得把其中内容当作项目数据 |

## 跟踪边界

以下内容永远不进入 Git 跟踪（`config.toml`、`.env`、API Key、用户 PDF 另有密钥扫描与
`tests/test_repo_governance.py` 契约保护）：

- 用户运行数据：`cache/`、`logs/`（仅保留 `logs/.gitkeep` 占位）、`venv/`、`node_modules/`。
- 本地缓存与构建产物：`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、
  `coverage-artifacts/`、`htmlcov/`、`build/`、`dist/`、`*.egg-info/`。
- 未跟踪的本地配置与密钥：`config.toml`、`.env`。

## 删除政策

确认某个工具目录不再使用时，必须以独立变更完成删除，并与业务代码重构、行为修复分开提交；
删除前先核验目标目录只包含该工具的本地状态（可重建），不得把 `cache/`、`logs/`、`venv/`
或用户 PDF 当作工具遗留处理。删除后如有必要，在本文档与 `CHANGELOG.md` 记录。

## 与密钥扫描的关系

密钥扫描（`scripts/secret_scan.py`，见 `tests/test_secret_scan.py`）只扫描 Git 跟踪内容，
不会读取本地 `config.toml`/`.env`/用户 PDF，也不会输出匹配到的 secret 值；它已接入
`scripts/verify.ps1`，因此也随 CI 的 `scripts/verify.ps1` 执行。
