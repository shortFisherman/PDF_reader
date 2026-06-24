# Comet Design Handoff

- Change: add-ci-and-lint-cleanup
- Phase: design
- Mode: compact
- Context hash: 9db5e5252e79a60548d2b5741db6c24dbc2e3bd819b862f1f215abd62559b84e

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/add-ci-and-lint-cleanup/proposal.md

- Source: openspec/changes/add-ci-and-lint-cleanup/proposal.md
- Lines: 1-27
- SHA256: faef193ef8b8bbeb68b57df5fb390cc5aed0240c2b0bb5ed7ee4310fe7d0cf7d

```md
# Proposal: add-ci-and-lint-cleanup

## Why

项目目前没有任何 CI，ruff 与 pytest 仅靠手动运行；且 `ruff.toml` 忽略了已被 ruff 移除的 `ANN101`/`ANN102` 规则（远行时会触发无效果告警）。随着后续多个独立变更落地，回归风险上升，缺一道自动化安全网。本变更新增一条 GitHub Actions CI 跑 `ruff check` + `pytest`，并清理废弃 lint 规则，让每次推送/PR 自动验证质量。

## What Changes

- 新增 `.github/workflows/ci.yml`：在 push/PR 时于 Windows runner 上安装依赖（`requirements.lock`）并运行 `ruff check .` 与 `pytest -q`。
- 清理 `ruff.toml` 的 `ignore` 列表中已被移除的 `ANN101`、`ANN102`（运行 ruff 时不再产生无效果告警告警）。
- 提供 CI 环境所需的最小配置兜底（依赖 `defer-config-validation` 让 `import config` 在无 `config.toml` 下成功）。

## Capabilities

### New Capabilities

- `continuous-integration`: 提供持续集成流水线，在代码推送/PR 时自动运行 lint 与测试并报告结果。

### Modified Capabilities

- `code-quality-foundations`: ruff 配置不再忽略已废弃规则；lint 配置保持零错误。

## Impact

- **代码**：`.github/workflows/ci.yml`（新增）、`ruff.toml`（清理两行 ignore）。
- **依赖**：无新增运行时依赖；CI 用 GitHub-hosted runner。
- **前置**：依赖 `defer-config-validation`（否则全新克隆 `import config` 失败，CI 无法跑测试）。
- **风险**：CI runner 选 Windows 与本地一致（pymupdf/pdf2zh-next 在 Linux runner 上也可能可行，但为保持一致先选 Windows）。```

## openspec/changes/add-ci-and-lint-cleanup/design.md

- Source: openspec/changes/add-ci-and-lint-cleanup/design.md
- Lines: 1-37
- SHA256: 1ac98e1b66dc53d1a15ee96725547ec86d073122975b41030a6dacb9c6abbca5

```md
# Design: add-ci-and-lint-cleanup

## Context

当前无 CI，质量门禁完全靠人工。`ruff.toml:6` 忽略的 `ANN101`/`ANN102` 是 ruff 已移除规则，ruff 运行时输出无效果告警告告警。本变更新增 CI 并清理 lint 配置。前置依赖 `defer-config-validation`（让全新克隆 `import config` 成功），故被排在变更 #2 执行。

## Goals / Non-Goals

**Goals:**
- 每次 push/PR 自动触发 `ruff check .` 与 `pytest -q`，失败即阻断。
- CI 在全新克隆（无 `config.toml`）下能跑通（依赖 #1）。
- ruff 配置干净，不再忽略已废弃规则。

**Non-Goals:**
- 不加 mypy、coverage、复杂度等额外门禁。
- 不限定具体 Python 版本矩阵（单 runner 单版本，与本地 3.12 一致）。
- 不在 CI 内构建/发布产物。

## Decisions

### 决策 1：runner 选 `windows-latest`
项目 README 标注仅支持 Windows 10+、`start.bat` 为 Windows 启动脚本，pymupdf/pdf2zh-next 行为需与本地一致。Linux runner 更快但环境差异可能掩盖/暴露平台问题，先选 Windows 与本地对齐。
- 替代方案：`ubuntu-latest` → 否决（与本地环境不一致，pymupdf wheel 行为差异风险）。

### 决策 2：依赖锁文件用 `requirements.lock`
`pip install -r requirements.lock` 精确复现本地环境。不上 `requirements.txt`（仅最小集，CI 可能装到不一致版本）。

### 冈策 3：CI 内提供测试配置兜底
`conftest.py` 的 `mock_config` 等 fixture 经 `defer-config-validation` 改造后能在无 `config.toml` 下运行。CI 不再需要在此步创建垫片配置。若个别测试仍依赖 `config.toml`，回到 #1 修复，不在本变更中加 hack。

### 决策 4：ruff 清理逐条移除
从 `ruff.toml` 的 `ignore` 列表删除 `ANN101`、`ANN102` 两个字符串，并验证 `ruff check .` 仍无新增错误（这两规则已被移除，移除 ignore 不影响实际检查）。

## Risks / Trade-offs

- **[风险] Windows runner 分钟消耗高** → 缓解：单 job、仅 push/PR 触发，不开 cron。
- **[风险] 依赖锁在 CI 装失败（网络/wheel）** → 缓解：lock 文件已锁定，且 pymupdf 有 Windows wheel；首次 CI 跑通即验证。
- **[风险] 移除 ignore 后 ruff 抛新错误** → 缓解：ANN101/102 已被移除，移除 ignore 必无新报错；CI 本变更即覆盖验证。```

## openspec/changes/add-ci-and-lint-cleanup/tasks.md

- Source: openspec/changes/add-ci-and-lint-cleanup/tasks.md
- Lines: 1-19
- SHA256: 500790c386a1b01c403f17c9207f641e7f3c82f1944837e7999c077b409ebb0e

```md
# Tasks: add-ci-and-lint-cleanup

## 1. ruff 配置清理

- [ ] 1.1 从 `ruff.toml` 的 `ignore` 列表移除 `ANN101` 与 `ANN102`
- [ ] 1.2 运行 `ruff check .` 确认无错误且无「rules removed / ignoring has no effect」告警

## 2. CI workflow

- [ ] 2.1 新增 `.github/workflows/ci.yml`：触发条件为 push 到 main 与 pull_request
- [ ] 2.2 job 在 `windows-latest` 上 checkout，`setup-python@3.12`
- [ ] 2.3 用 `pip install -r requirements.lock` 安装依赖
- [ ] 2.4 运行 `ruff check .`（lint job/step，失败即终止）
- [ ] 2.5 运行 `pytest -q`（test job/step，失败即失败 CI）

## 3. 验证

- [ ] 3.1 本地模拟 CI：删除/重命名 `config.toml` 后运行 `pytest -q` 确认全过（验证 #1 前置生效）
- [ ] 3.2 提交 workflow 并在分支上推送，观察 Actions 状态为绿
- [ ] 3.3 故意注入一处 lint 错误确认 CI 能阻断，再回退```

## openspec/changes/add-ci-and-lint-cleanup/specs/code-quality-foundations/spec.md

- Source: openspec/changes/add-ci-and-lint-cleanup/specs/code-quality-foundations/spec.md
- Lines: 1-16
- SHA256: 2477bff10116d406c8e3190049f8e3efeddc96251e28199bc8e939ff60621c64

```md
# code-quality-foundations Delta: add-ci-and-lint-cleanup

## MODIFIED Requirements

### Requirement: Code linting with zero errors

The system SHALL include a ruff configuration file and SHALL pass linting checks with zero errors when `ruff check` is run against the project. The ruff configuration SHALL NOT list any rules that have been removed from ruff (such as `ANN101` / `ANN102`) in its `ignore` set, so running `ruff check` produces no "rules removed, ignoring has no effect" warnings while still passing with zero errors.

#### Scenario: Ruff check passes

- **WHEN** `ruff check` is executed in the project root
- **THEN** the command SHALL exit with code 0, produce no error output, and produce no warning about ignored removed rules

#### Scenario: Removed rules not in ignore set

- **WHEN** `ruff.toml` is inspected
- **THEN** the `ignore` list SHALL NOT contain `ANN101` or `ANN102` (or any other rule ruff reports as removed), while the existing effective lint guarantees are preserved```

## openspec/changes/add-ci-and-lint-cleanup/specs/continuous-integration/spec.md

- Source: openspec/changes/add-ci-and-lint-cleanup/specs/continuous-integration/spec.md
- Lines: 1-26
- SHA256: 63876ec327195171b15cae6578753906966693e91c8476a5a41a75f85a7aef37

```md
# continuous-integration Delta: add-ci-and-lint-cleanup

## ADDED Requirements

### Requirement: Lint and test pipeline on push and PR

The repository SHALL include a GitHub Actions workflow that, on every push to the main branch and on every pull request, automatically installs dependencies from `requirements.lock` and runs `ruff check .` followed by `pytest -q`. The workflow SHALL fail the CI status when either lint or tests report failures, so regressions are blocked before merge.

#### Scenario: CI runs on push

- **WHEN** a commit is pushed to the main branch
- **THEN** the GitHub Actions workflow SHALL trigger and run `ruff check .` and `pytest -q`

#### Scenario: CI runs on pull request

- **WHEN** a pull request is opened or updated against the main branch
- **THEN** the workflow SHALL trigger and report a failing status check if lint or tests fail

#### Scenario: Fresh clone without config.toml runs tests

- **WHEN** the CI workflow checks out the repository into a fresh clone that has no `config.toml`
- **THEN** the test suite SHALL still run successfully (relying on defer-config-validation), and `import config` SHALL not raise

#### Scenario: Lint failure blocks CI

- **WHEN** `ruff check .` exits non-zero
- **THEN** the workflow SHALL fail and the dependent job (tests) SHALL not report success```

