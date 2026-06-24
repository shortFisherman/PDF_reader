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
- **[风险] 移除 ignore 后 ruff 抛新错误** → 缓解：ANN101/102 已被移除，移除 ignore 必无新报错；CI 本变更即覆盖验证。