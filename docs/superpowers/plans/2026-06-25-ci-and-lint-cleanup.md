---
change: add-ci-and-lint-cleanup
design-doc: docs/superpowers/specs/2026-06-25-ci-and-lint-cleanup-design.md
base-ref: 0e9d5324b9897b23090f2e680ebec0f7c8a62957
---

# CI 与 Lint 清理 实施方案

> **面向自动化执行者：** 必须子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 按任务逐项实施。步骤使用 checkbox (`- [x]`) 语法追踪。

**目标：** 为项目添加 GitHub Actions CI 流水线（lint + test），并清理 ruff 配置中已废弃的规则引用。

**架构：** 双文件变更——新建 `.github/workflows/ci.yml` 定义 `windows-latest` 上的串行 lint→test 流水线；修改 `ruff.toml` 移除已被 ruff 删除的 `ANN101`/`ANN102` 忽略项。无新增运行时依赖。

**技术栈：** GitHub Actions (checkout@v4, setup-python@v5), ruff, pytest, pip install -r requirements.lock

## 全局约束

- 平台：Windows 10+，CI 使用 `windows-latest` runner
- Python 版本：3.12
- 依赖安装：`pip install -r requirements.lock`（精确版本锁定）
- ruff 目标版本：py312，行宽 120
- `ANN401`（动态类型表达式）保持忽略，不删除
- config.toml 缺失时测试必须通过（conftest.py 已有 `mock_config` fixture）

---

## 文件结构

```
.github/
  workflows/
    ci.yml        (新建) — GitHub Actions CI 流水线定义
ruff.toml         (修改) — 第 6 行：从 ignore 列表移除 ANN101 和 ANN102
```

| 文件 | 职责 |
|------|------|
| `ruff.toml` | 项目级 ruff 检查规则配置，控制哪些规则启用、哪些规则忽略 |
| `.github/workflows/ci.yml` | CI 流水线：checkout → 安装依赖 → ruff lint → pytest |

---

### 任务 1：清理 ruff 废弃规则

**文件：**
- 修改：`ruff.toml:6`

**接口：**
- 不涉及跨任务接口

- [x] **步骤 1：修改 `ruff.toml` 第 6 行 —— 移除 ANN101 和 ANN102**

当前内容（第 6 行）：
```toml
ignore = ["ANN101", "ANN102", "ANN401"]
```

替换为：
```toml
ignore = ["ANN401"]
```

使用精确替换编辑操作：
```
oldString: ignore = ["ANN101", "ANN102", "ANN401"]
newString: ignore = ["ANN401"]
```

- [x] **步骤 2：运行 ruff check 验证清理结果**

```powershell
ruff check .
```

**预期输出：** 无错误，无 "rules removed / ignoring has no effect" 告警。若 ruff.toml 中仍有对 ANN101/ANN102 的引用，ruff 会输出类似 `warning: Rule 'ANN101' is deprecated and will be removed in a future release` 的告警——本步骤成功后不应出现此警告。

- [x] **步骤 3：确认 ANN401 仍被忽略**

```powershell
ruff check . --select ANN401
```

**预期输出：** 无新增 ANN401 错误（由于 ignore 列表仍有 ANN401，现有 ANN401 违规不会被报告）。确认 ANN401 的忽略行为未被意外移除。

- [x] **步骤 4：提交 ruff 配置变更**

```powershell
git add ruff.toml
git commit -m "chore: 从 ruff ignore 列表中移除已废弃的 ANN101/ANN102 规则"
```

---

### 任务 2：创建 GitHub Actions CI 流水线

**文件：**
- 创建：`.github/workflows/ci.yml`
- 验证依赖：`requirements.lock`（已存在，无需修改）
- 验证依赖：`tests/conftest.py`（已存在，`mock_config` fixture 已就绪）

**接口：**
- 消费：`ruff.toml` 中的 lint 规则配置（任务 1 修改后的状态）
- 消费：`tests/conftest.py` 中的 `mock_config` fixture（已存在，config.toml 缺失时测试仍通过）
- 生产：CI 流水线行为——push 到 main 或 PR 时自动触发 lint + test

- [x] **步骤 1：创建 `.github/workflows` 目录**

```powershell
New-Item -ItemType Directory -Force -Path ".github\workflows"
```

- [x] **步骤 2：编写 `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: windows-latest
    name: Lint & Test

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'

      - name: Install dependencies
        run: pip install -r requirements.lock

      - name: Lint with ruff
        run: ruff check .

      - name: Test with pytest
        run: pytest -q
```

**设计要点：**
- 触发条件：`push` 到 `main` 分支 或 对 `main` 分支发起 `pull_request`
- Runner：`windows-latest`（项目 README 限定 Windows 10+，pymupdf/pdf2zh-next 行为需与本地环境一致）
- Python 3.12（项目 `ruff.toml` 声明的目标版本）
- `cache: 'pip'` 加速后续 CI 运行
- `pip install -r requirements.lock` 确保精确版本（pip freeze 输出）
- 步骤顺序串行：lint 先于 test，lint 失败即终止，无需 `if: success()`（GitHub Actions 默认行为）
- 无 CI 专用配置：`conftest.py` 已有 `mock_config` fixture，在无 `config.toml` 的 fresh clone 环境中测试仍可通过

- [x] **步骤 3：验证 `.github/workflows/ci.yml` YAML 语法**

```powershell
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

**预期输出：** 无错误退出（YAML 解析成功，打印字典内容）。

- [x] **步骤 4：本地模拟 CI —— 确认 config.toml 缺失时测试通过**

此步骤验证 `conftest.py` 的 `mock_config` fixture 已正确被子测试文件引用（fixture 来源：`tests/conftest.py:44-59`，通过 `monkeypatch.setattr` 模拟所有 config 属性）。

```powershell
# 备份并移除 config.toml
Move-Item -Path "config.toml" -Destination "config.toml.ci-test-backup" -ErrorAction SilentlyContinue

# 运行测试（config.toml 不存在）
pytest -q

# 恢复 config.toml
Move-Item -Path "config.toml.ci-test-backup" -Destination "config.toml" -ErrorAction SilentlyContinue
```

**预期输出：** 所有测试通过（`pytest -q` 退出码 0），无因 config.toml 缺失导致的 ImportError 或配置错误。

- [x] **步骤 5：提交 CI workflow**

```powershell
git add .github/workflows/ci.yml
git commit -m "feat: 添加 GitHub Actions CI 流水线（lint + test, windows-latest）"
```

---

### 任务 3：端到端验证

**文件：**
- 无需修改文件

**接口：**
- 消费：任务 1 的 ruff 配置、任务 2 的 CI workflow
- 消费：GitHub 仓库的 Actions 标签页

- [x] **步骤 1：推送分支到 GitHub 并观察 CI 运行**

```powershell
git push -u origin HEAD
```

打开 GitHub 仓库 → Actions 标签页 → 等待 workflow 运行完成。

**预期输出：** CI 状态为 ✅ 绿色通过。具体检查：
- `Lint with ruff` 步骤：输出 `All checks passed!`（或无错误输出）
- `Test with pytest` 步骤：输出测试摘要，所有测试通过
- 整条 workflow 运行时间合理（首次运行含 pip install 较慢，后续有 cache 加速）

- [x] **步骤 2：故意注入 lint 错误验证 CI 阻断能力**

在任意 `.py` 文件尾部临时添加一行：
```python
x = 1
```

提交并推送：
```powershell
git add -A
git commit -m "test: 故意注入未使用变量以验证 CI 阻断"
git push
```

**预期输出：** CI 运行失败（❌ 红叉），`Lint with ruff` 步骤报告 `F841 Local variable 'x' is assigned to but never used`，`Test with pytest` 步骤被跳过（未执行）。

- [x] **步骤 3：回退注入的 lint 错误**

```powershell
git revert HEAD --no-edit
git push
```

**预期输出：** CI 恢复为 ✅ 绿色通过。

---

## 回滚方案

若 CI 流水线上线后发现问题需要紧急回退：

```powershell
# 移除 CI workflow 文件
git rm .github/workflows/ci.yml
git commit -m "revert: 临时移除 CI workflow"
git push
```

ruff.toml 的修改无需回滚——删除已被废弃的规则引用是无害的清理操作。
