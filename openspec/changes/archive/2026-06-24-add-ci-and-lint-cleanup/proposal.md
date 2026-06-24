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
- **风险**：CI runner 选 Windows 与本地一致（pymupdf/pdf2zh-next 在 Linux runner 上也可能可行，但为保持一致先选 Windows）。