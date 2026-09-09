# 双环境开发模式（Windows 产品环境 + WSL 开发环境）

本页规定本仓库在 **Windows 实机/CI** 与 **WSL Ubuntu 开发环境** 之间的协作方式，
以及跨平台公共验证入口的用法。它只描述开发与同步纪律，不改变产品定位。

## 平台角色

- **Windows 是唯一正式产品和发行平台。** PDF Reader 的最终用户、正式运行环境和
  发行目标始终是 Windows；Windows 实机与 Windows CI 是最终产品验收门。
  产品边界见 [`windows-portable-release-plan.md`](<improvement items/windows-portable-release-plan.md>)。
- **WSL Ubuntu 是主要开发环境，不构成 Linux 产品发行支持。** 可以在 WSL 中完成
  绝大多数开发、测试与提交，但逐步验收（Windows 实机 + Windows CI）仍是最终权威。

## 双 clone 与 GitHub main 同步中心

WSL 与 Windows 各自保留**独立 clone**；GitHub `main` 是两边唯一的代码同步中心。

- 同一时间只在一个环境中修改代码，避免两边相互覆盖的冲突。
- 开始开发前：`git pull --ff-only`（拉取另一边的最新提交）。
- 修改完成并验证通过后：立即 `git commit` 并 `git push` 到 `origin/main`。
- 切回另一环境继续前：先 `git pull --ff-only`。
- **禁止 force push**；若 push 因远端领先被拒绝，先 pull/解决冲突，绝不强推。
- 不要创建临时的功能分支来做本仓库的常规维护修改；直接在 `main` 工作。

## 不通过 Git 同步的本地状态

以下内容各自独立、绝不跨环境同步（Windows 与 WSL 各自维护）：

- `config.toml`（含 API Key，被 Git 忽略且永不提交）
- `venv/`、`node_modules/`
- `cache/`、`logs/`、`build/`、`dist/`、`coverage-artifacts/`

## 依赖变更

- `requirements.lock` 变化后：重新安装 Python 依赖（如 `venv/bin/pip install -r requirements.lock`）。
- `package-lock.json` 变化后：重新运行 `npm ci`。
- 依赖升级必须通过 `scripts/upgrade_governance_gate.py` 与 Windows 验收门。

## 跨平台公共验证入口

单一验证逻辑只维护在 [`scripts/verify.py`](../scripts/verify.py)，避免两套逻辑漂移：

- **WSL（开发环境）**：`venv/bin/python scripts/verify.py`
- **Windows**：`scripts/verify.ps1` 只是解析解释器并委托 `python scripts/verify.py` 的启动器，
  保留原有调用方式（可传 `-PythonExecutable`；读取 `PDF_READER_COVERAGE_ARTIFACT_DIR`）。

公共验证固定覆盖：Python 关键依赖导入、`pip check`、`scripts/secret_scan.py`、
`scripts/upgrade_governance_gate.py --static-only`、`packaging/windows/runtime_policy.py --source-root .`、
`ruff check .`、`ruff format --check .`、`coverage run --branch -m pytest -q` + report/json +
`scripts/check_coverage_policy.py`、`scripts/term_quality_gate.py`、`mypy`、`npm audit`、
`npm run lint:js`、`npm test`。

约束：使用当前虚拟环境解释器并打印实际 Python/Node 版本；失败即返回非零；
不在仓库根残留 `.coverage` 或 `coverage.json`；不读取 `config.toml`；
不启动真实翻译、不调用模型 API；不修改 config/cache/logs/docs/glossary.csv；
不降低覆盖率、类型或术语质量阈值。

## 验收

- Windows 实机与 Windows CI 是最终产品门；Windows Portable artifact 验证留在 Windows 发行流程。
- 若存在 Ubuntu CI job，它只验证“Linux 开发环境兼容性”，不是产品权威门，
  且不得因 Linux 差异降低任何验证阈值。
