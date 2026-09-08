# 工具与工作流目录治理

> 建立日期：2026-08-30（P3-07），最近更新：2026-09-08。本文档集中说明当前仍在使用的
> AI、工作流和检索目录的职责、跟踪边界与重建方式，并记录退役工具的处理规则。

## 事实来源优先级

1. 当前代码、测试与可复现命令（`requirements.lock`、`package-lock.json`、`scripts/verify.ps1`）。
2. `docs/architecture.md`（严格描述当前 HEAD）。
3. `docs/project.md`（长期意图）与 `docs/roadmap.md`（未授权候选）。
4. `docs/archive/` 与 `CHANGELOG.md` 等历史资料只用于追溯；已删除的工具产物通过 Git 历史查询。
5. 工具目录中的配置与技能说明属于操作指令，不是项目事实源。

## 目录清单

| 目录 | 是否跟踪 | 职责 | 生成/维护方 | 可否重建 | 事实来源角色 |
|---|---|---|---|---|---|
| `.codex/` | 跟踪 | Codex 本地配置（hooks、工作流规则） | Codex/用户 | 可重建（重新生成配置），当前文件为基线 | 操作指令 |
| `.opencode/` | 跟踪 | OpenCode Go 命令与路由（OP DeepSeek 子 Agent 等） | OpenCode/用户 | 可重建（重新安装/生成命令） | 操作指令 |
| `.codegraph/` | 不跟踪（自带 `.gitignore`） | CodeGraph 索引数据库/daemon 状态 | `codegraph` CLI | 可重建（重新索引） | 代码检索辅助；不替代源码事实 |
| `.firecrawl/` | 不跟踪 | Firecrawl 本地运行数据 | Firecrawl 工具 | 可重建 | 无 |
| `.worktrees/` | 不跟踪（已忽略） | Git worktree 本地布局 | Git/用户 | 可重建 | 无 |
| `.git-rewrite/` | 不跟踪（已忽略） | git-filter-repo 历史重写临时状态 | git-filter-repo | 可重建，纯临时状态 | 无；不得把其中内容当作项目数据 |

## 退役工具

Superpowers 与 OpenSpec 已于 2026-09-04 从项目工作流退役；Comet 项目级集成已于
2026-09-08 通过官方 `comet uninstall . --scope project --force` 完成卸载并退役。
当前工作树不保留 `.superpowers/`、`openspec/`、`docs/superpowers/` 或只为 Superpowers
安装状态服务的 `skills-lock.json`，也不保留 Comet 项目级安装物：`.comet/` 配置与
运行时状态、`.agents/`（其中的 comet/comet-any/comet-native/comet-review 均为纯
Comet 安装副本）、`.opencode/skills/comet*`、`.opencode/commands/comet*.md`、
`.opencode/rules/comet-workflow-guard.md` 与 `.codex/rules/comet-workflow-guard.md`。
这些内容不迁入 `docs/archive/`，因为 Git 历史已经提供完整追溯，重复保存只会让旧计划与
当前事实混杂。

退役工具名称可以继续出现在 `CHANGELOG.md` 或既有归档文档的历史叙述中，但不得被描述为
当前事实来源、规范入口或新变更的产物位置。`tests/test_repo_hygiene.py` 阻止
Superpowers/OpenSpec 相关路径重新进入工作树；`tests/test_repo_governance.py` 阻止
Comet 安装物路径、`.gitignore` 中的 Comet 管理块与在用目录清单条目重新出现。

## 跟踪边界

以下内容永远不进入 Git 跟踪（`config.toml`、`.env`、API Key、用户 PDF 另有密钥扫描与
`tests/test_repo_governance.py` 契约保护）：

- 用户运行数据：`cache/`、`logs/`（仅保留 `logs/.gitkeep` 占位）、`venv/`、`node_modules/`。
- 本地缓存与构建产物：`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`、`.mypy_cache/`、
  `coverage-artifacts/`、`htmlcov/`、`build/`、`dist/`、`*.egg-info/`。
- 未跟踪的本地配置与密钥：`config.toml`、`.env`。

## 删除政策

确认某个工具目录不再使用时，必须以独立变更完成删除，并与业务代码重构、行为修复分开提交；
删除前先核验目标目录只包含该工具的状态或产物，不得把 `cache/`、`logs/`、`venv/` 或用户
PDF 当作工具遗留处理。删除后在本文档与 `CHANGELOG.md` 记录，并移除配置、测试、忽略规则和
常青文档中的现行引用。除非法律或审计要求必须在工作树保留，历史追溯统一使用 Git。

## 与密钥扫描的关系

密钥扫描（`scripts/secret_scan.py`，见 `tests/test_secret_scan.py`）只扫描 Git 跟踪内容，
不会读取本地 `config.toml`/`.env`/用户 PDF，也不会输出匹配到的 secret 值；它已接入
`scripts/verify.ps1`，因此也随 CI 的 `scripts/verify.ps1` 执行。
