# 长期文档治理

> 建立日期：2026-08-30（P3-06）。本文档说明何时更新三份长期文档（`docs/project.md`、
> `docs/architecture.md`、`docs/roadmap.md`）、上游依赖升级步骤、易腐数字政策与事实冲突优先级。

## 三份长期文档的职责与更新时机

| 文档 | 职责 | 何时更新 |
|---|---|---|
| `docs/project.md` | 长期意图、常青原则、产品边界与项目记忆 | 只有用户确认的产品意图或边界变化才更新；不写入当前测试数量、短期任务状态或未授权实施细节 |
| `docs/architecture.md` | 严格记录当前 HEAD 已实现的系统 | 实现、行为、依赖、接口、测试入口变化时在同一变更中更新；不写入 roadmap 候选或台账状态 |
| `docs/roadmap.md` | 未授权候选、开放问题与决策状态 | 新候选方向或用户决策时更新；不把未授权候选写成已实现，不把未收口事项标记为完成 |

更新原则：

- 架构行为变化时，文档修改与代码修改必须在同一提交中，禁止事后补写。
- 移动、重命名或归档 `docs/` 文件时，必须在同一变更中更新 README、architecture、project、
  roadmap 等常青文档里的相对链接与文档导航，避免留下失效链接；链接可解析性由
  `tests/test_documentation_governance.py` 回归。
- `docs/project.md` 只承载长期意图；短期进度、测试数量与实施细节属于 `CHANGELOG.md`、工程清单或提交消息。
- `docs/roadmap.md` 不构成实施授权；`已决定，尚未授权实施` 仍不能开工。

## 上游依赖升级步骤

1. 修改 `pyproject.toml` / `package.json` 的直接依赖声明；按 `README.md` 记录的
   `pip-compile` 命令重新生成 `requirements.lock`（Python 3.12 + pip-tools 7.6.1）。
2. 运行契约测试 `python -m pytest tests/test_upstream_contract.py tests/test_dependency_contract.py`，
   范围见 `docs/governance/dependency-upgrade.md`：固定版本、`SettingsModel` 消费字段与引擎字段映射、
   承诺事件映射与未知事件忽略/心跳、`workspace/output` 注入与 mono/dual/glossary 路径、
   协作式取消/迟到丢弃/`join` 所有权必须全部通过。
3. 契约变化时先更新适配代码与测试，再合并依赖升级，禁止“先升级再观察”。
4. 完整运行 `scripts/verify.ps1`；升级记录写入 `CHANGELOG.md` 与提交消息；
   许可证按 `docs/governance/license.md` 重新核验。

## 易腐数字政策

- 代码行数、测试数、覆盖率、文件数等随时间变化的数字不是长期事实。作为长期事实保留时，
  必须注明核验日期 / commit / 本次报告基线；`docs/architecture.md` 的“核验基线”节是当前数字的基线。
- `CHANGELOG.md` 按日期分节的条目视为历史基线；历史数字不需要回填当前值。
- `docs/archive/`、`openspec/` 等历史内容只用于追溯，不因当前变化回填或伪装成现状。

## 事实冲突优先级

1. 当前代码、测试与可复现命令（`requirements.lock`、`package-lock.json`、`scripts/verify.ps1`）。
2. `docs/architecture.md`（严格描述当前 HEAD）。
3. `docs/project.md`（长期意图）与 `docs/roadmap.md`（未授权候选）。
4. `CHANGELOG.md`、`docs/archive/`、`docs/superpowers/`、`openspec/` 等历史资料，只用于追溯。
5. 工具目录与技能说明属于操作指令，不是项目事实源（见 `docs/governance/tool-directories.md`）。
