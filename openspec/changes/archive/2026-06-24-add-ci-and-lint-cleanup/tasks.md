# Tasks: add-ci-and-lint-cleanup

## 1. ruff 配置清理

- [x] 1.1 从 `ruff.toml` 的 `ignore` 列表移除 `ANN101` 与 `ANN102`
- [x] 1.2 运行 `ruff check .` 确认无错误且无「rules removed / ignoring has no effect」告警

## 2. CI workflow

- [x] 2.1 新增 `.github/workflows/ci.yml`：触发条件为 push 到 main 与 pull_request
- [x] 2.2 job 在 `windows-latest` 上 checkout，`setup-python@3.12`
- [x] 2.3 用 `pip install -r requirements.lock` 安装依赖
- [x] 2.4 运行 `ruff check .`（lint job/step，失败即终止）
- [x] 2.5 运行 `pytest -q`（test job/step，失败即失败 CI）

## 3. 验证

- [x] 3.1 本地模拟 CI：删除/重命名 `config.toml` 后运行 `pytest -q` 确认全过（验证 #1 前置生效）
- [x] 3.2 提交 workflow 并在分支上推送，观察 Actions 状态为绿
- [x] 3.3 故意注入一处 lint 错误确认 CI 能阻断，再回退