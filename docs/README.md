# PDF Reader 文档索引

本目录只保存仍对项目开发、使用或历史追溯有明确价值的文档。当前实现以代码、测试和
[`architecture.md`](architecture.md) 为准；旧开发工具生成的规格、计划和验证报告不再
保留在工作树中，需要时通过 Git 历史查询。

## 长期文档

- [`project.md`](project.md)：项目为什么存在、长期意图、常青原则与产品边界。
- [`architecture.md`](architecture.md)：当前 HEAD 已实现的架构、行为与运行边界。
- [`roadmap.md`](roadmap.md)：尚未实施的候选方向、依赖关系与决策状态。

## 使用与开发指南

- [`terminology-system.md`](terminology-system.md)：术语提取、审核、编译与翻译控制流程。
- [`dual-environment-development.md`](dual-environment-development.md)：Windows 产品环境与 WSL 开发环境的双 clone/GitHub 同步模式、跨平台公共验证入口用法。
- [`pdf2zh-next-development-guide.md`](pdf2zh-next-development-guide.md)：与固定版本上游接口协作时的开发参考。
- [`windows-portable-release-plan.md`](<improvement items/windows-portable-release-plan.md>)：已获授权的 Windows 便携发行跨会话实施台账、隔离红线与验收门。
- [`glossary.csv`](glossary.csv)：随项目提供的全局默认词表。

## 专题目录

- [`governance/`](governance/)：依赖、许可证、文档和工具目录等长期治理规则。
- [`reports/`](reports/)：有明确版本或基线的研究与质量报告。
- [`completed improvements/`](completed%20improvements/)：已完成的大型工程改进记录。
- [`archive/`](archive/)：已经过时但仍值得保留的项目级历史资料。

## 维护规则

1. 修改架构、行为、依赖或验证入口时，在同一变更中更新 `architecture.md`。
2. 只有长期意图或产品边界改变时才更新 `project.md`；候选方向只写入 `roadmap.md`。
3. 新文档必须归入上述职责之一；一次性工具产物和重复的计划/验证副本不进入 `docs/`。
4. 移动或删除文档时同步更新本索引、README 及相关相对链接，并运行文档治理测试。
5. 更完整的职责、易腐数字和事实冲突规则见 [`governance/documentation.md`](governance/documentation.md)。
