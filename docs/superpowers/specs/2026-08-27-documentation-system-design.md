# PDF Reader 长期文档系统设计

**日期：** 2026-08-27
**设计状态：** 设计方向已获用户认可；本规格待用户审阅，在用户批准实施计划前不实施文件迁移
**适用仓库：** `PDF_reader`

## 背景

项目现有资料并不缺少，但当前事实、历史设计、阶段快照、上游研究和运行时数据混在同一个 `docs/` 层级中。新会话虽然可以找到大量信息，却难以判断哪些内容仍反映当前实现、哪些只是历史记录。已确认的例子包括：

- `docs/project-architecture.md` 仍描述旧的滚动同步模型、旧测试数量和已经迁移的模块职责。
- `docs/module-interactions.md` 与 `docs/module-flow.html` 缺少批量翻译、阅读进度、缩放和当前对齐控制器。
- `docs/PROJECT_STATUS.md` 同时混合项目意图、当前架构和未来建议，无法成为长期稳定的单一职责文档。
- `docs/superpowers/` 保存了有价值的设计、计划和验收历史，但其路径被历史工具元数据引用，不适合为了目录整洁而移动。
- `docs/pdf2zh-next-development-guide.md` 和 `docs/reports/` 中的上游研究资料具有长期价值，但基于特定历史版本，需要明确适用范围。

本设计建立四份常青文档，使不懂代码的项目所有者可以在长线程、跨会话的 AI 协作中持续保留项目意图、当前实现和未来方向，同时完整保存既有研究与历史记录。

## 目标

1. 让新的人类或 AI 会话通过固定入口快速理解项目。
2. 将项目意图、当前实现和未来方向分离，避免时间维度混杂。
3. 让 `docs/architecture.md` 成为当前实现的唯一文档事实源。
4. 让 `docs/project.md` 保存项目为什么存在、长期意图、常青原则和仍影响未来判断的总体记忆。
5. 让 `docs/roadmap.md` 承载候选方向、开放问题和依赖顺序，同时明确它不构成实施授权。
6. 在 `AGENTS.md` 中强制后续 AI 按任务类型阅读和维护上述文档。
7. 完整保留 PDF2zh/BabelDOC 参考资料、历史设计、计划、验收报告和旧架构快照。
8. 不改变应用行为、API、缓存格式、依赖或运行时数据路径。

## 非目标

- 本次不决定 Zotero、PDF.js、批注、任务队列、导出或其他产品方向。
- 本次不把 roadmap 条目转换为代码任务。
- 本次不修复架构文档中记录的技术缺陷。
- 本次不重写 PDF2zh/BabelDOC 研究正文，只增加适用范围说明。
- 本次不移动 `docs/superpowers/`、`openspec/`、`docs/comet/` 或 `docs/glossary.csv`。
- 本次不新增文档生成器、站点、自动目录或额外的 `docs/README.md`。
- 当前常青文档只面向项目目的、当前实现与后续开发；旧状态叙事只保留在历史归档中。

## 核心治理原则

> 项目意图只写进 `docs/project.md`，当前事实只写进 `docs/architecture.md`，未来方向只写进 `docs/roadmap.md`，`README.md` 只做入口和使用摘要。其他文档只能引用它们，不能建立平行版本。

进一步规则：

- README 面向首次进入仓库的人类和 AI。
- project 文档低频更新，只在用户明确改变项目意图或原则时修改。
- architecture 必须严格反映当前代码；架构相关代码变更必须在同一变更中更新它。
- roadmap 只指导讨论、排序和计划，不能授权实现。
- 历史资料用于追溯，不得覆盖代码、测试或常青文档中的当前事实。
- 上游研究资料是参考快照；修改集成前必须针对当前锁定版本重新核对。

## 目标文件结构

```text
README.md
AGENTS.md
CHANGELOG.md

docs/
├── project.md
├── architecture.md
├── roadmap.md
├── pdf2zh-next-development-guide.md
├── glossary.csv
├── reports/
│   ├── pdf2zh-internals-report.md
│   └── babeldoc-vs-pdf2zh-next-report.md
├── archive/
│   ├── 2026-08-06-project-status.md
│   ├── project-architecture.md
│   ├── module-interactions.md
│   ├── module-flow.html
│   └── manual-verification-checklist.md
└── superpowers/
    ├── specs/
    ├── plans/
    └── reports/
```

`docs/comet/` 继续由 Comet Native 管理，不放置人工维护的常青文档。`openspec/` 保持原位。

## 四份常青文档的契约

| 文档 | 唯一职责 | 更新触发条件 | 明确排除 |
|---|---|---|---|
| `README.md` | 项目简介、用户可见能力、安装、配置、启动、验证和文档导航 | 用户可见功能、安装方式、运行要求或项目入口变化 | 详细架构、长期原则、候选路线 |
| `docs/project.md` | 项目存在原因、目标用户、长期意图、核心价值、常青原则、产品边界、上游关系和长期记忆 | 用户明确确认意图、原则或长期边界变化 | 当前模块细节、临时待办、实现计划 |
| `docs/architecture.md` | 当前 HEAD 的技术栈、模块、数据流、API、状态、缓存、并发、外部依赖、测试和技术约束 | 模块、API、数据流、状态、依赖或运行边界变化 | 愿景、未来方案、修复建议 |
| `docs/roadmap.md` | 候选方向、开放问题、依赖顺序、已决定/暂缓/否决方向和决策记录 | 用户确认方向、优先级或路线状态变化 | 当前实现说明、代码任务、未经授权的实施计划 |

## README.md 内容设计

README 保留现有可用内容并做必要精简，章节顺序为：

1. 项目简介。
2. 主要能力。
3. 已知使用边界。
4. 文档导航。
5. 环境要求。
6. 安装。
7. 配置。
8. 启动。
9. 验证。
10. 核心目录速览。
11. 上游依赖与授权提醒。

具体要求：

- 删除当前状态横幅和对 `docs/PROJECT_STATUS.md` 的现役链接。
- 不新增替代性的项目状态横幅。
- 在靠前位置链接 `docs/project.md`、`docs/architecture.md`、`docs/roadmap.md` 和 `docs/pdf2zh-next-development-guide.md`。
- 保留安装、启动和统一验证命令。
- 核心结构仅作摘要，详细调用链指向 architecture。
- 不复制 roadmap 候选方向。

## docs/project.md 内容设计

章节为：

1. **文档职责**：说明 project 只记录意图、原则和长期记忆；当前实现见 architecture，未来方向见 roadmap。
2. **项目为什么存在**：为英文书籍、教材和论文提供可控的本地双语 PDF 阅读环境。
3. **目标用户与核心场景**：首先服务项目所有者本人，支持本地阅读、按页/范围/全文翻译，并长期保存每本 PDF 的译文、术语和阅读状态。
4. **核心价值**：用户掌控模型、API、提示词、术语策略、阅读界面和任务流程；数据本地保留。
5. **常青原则**：本地优先、用户可控、数据安全优先、事实可验证、复用成熟上游、密钥安全、roadmap 非授权、历史不冒充现状。
6. **产品边界**：保持对当前单用户本地场景的明确描述；未决定的未来功能不得在此提前拍板。
7. **上游关系**：本项目负责阅读器、任务编排、缓存、术语和状态；pdf2zh-next/BabelDOC 负责 PDF 解析、翻译、字体和排版。
8. **项目长期记忆**：只记录仍影响未来判断的关键决策；逐次变更归 CHANGELOG 和历史档案。
9. **文档与历史地图**：解释 `docs/superpowers/`、`docs/archive/`、`openspec/`、`docs/comet/` 和参考资料的身份。

project 文档不复制旧状态叙事，也不把任何候选产品方向写成常青原则。

## docs/architecture.md 内容设计

architecture 必须基于 CodeGraph 和当前源码重新编写，不得从旧架构文档照抄。初始版本核对当前 HEAD，包含以下章节：

1. 文档契约与核验基线。
2. 系统总览。
3. 技术栈和锁定版本。
4. 仓库结构与文件职责。
5. 运行时进程、线程、队列和锁模型。
6. 启动与 Flask 应用装配。
7. 配置加载、环境变量和十个 Provider。
8. 打开 PDF 与页面 PNG 渲染链。
9. 单页翻译链。
10. 范围与全文翻译链。
11. `AppState`、`right.pdf`、术语表、阅读进度和调试追踪。
12. 前端模块、懒加载、对齐、缩放和页面状态。
13. 全部当前 API 端点。
14. 日志与错误传播。
15. 测试、CI 和统一验证入口。
16. 当前已知技术约束与已确认风险。
17. 上游与历史参考文档指针。

初始架构事实至少覆盖：

- Python 3.12、Flask、PyMuPDF、pdf2zh-next、BabelDOC 和原生 ES Modules 的边界。
- 单 Flask 进程、单全局 `AppState`、非重入锁、翻译 daemon 线程、独立 asyncio 循环、事件队列和上游子进程。
- 打开 PDF、渲染、单页翻译、范围翻译的真实调用顺序。
- `cache/<hash>/right.pdf`、`cumulative_glossary.csv`、`reading_progress.json` 和 `debug_trace.log`。
- 十个 Provider、环境变量优先级、未知 Provider fallback 和延迟配置校验。
- 当前前端模块以及 `alignment-controller.js` 取代旧比例滚动同步的事实。
- 当前受支持的验证入口、193 个 Python 测试和四个正式前端套件。
- 页面为 PNG、无文本层、无任务队列/暂停/取消/重启续传等现状。
- 已复现的跨文档译文污染缺陷。
- SSE 断开不取消后台翻译、服务端无任务隔离、依赖锁含机器绝对路径等当前风险事实。

architecture 只记录这些问题的现状和证据，不写修复方案。

## docs/roadmap.md 内容设计

roadmap 顶部固定写明：

> 本文档记录候选方向、开放问题和依赖顺序，不是实施授权。任何方向只有在用户明确确认并建立独立变更或实施计划后，才能进入代码实现。

章节为：

1. 文档职责和状态定义。
2. 当前开放问题。
3. 基础可靠性候选工作。
4. 产品方向候选。
5. 方向之间的依赖关系。
6. 已决定方向。
7. 已否决或暂缓方向。
8. 决策记录。

允许的状态为：

- `候选`
- `待讨论`
- `已决定，尚未授权实施`
- `已授权（授权见链接的独立变更）`
- `暂缓`
- `已否决`
- `已完成`

初始版本不得替用户选择 Zotero、PDF.js 文本层、批注、导出、设置 UI、任务队列或其他产品路线。它只记录已经识别的开放问题、可靠性候选工作、方向依赖和未来需要用户作出的决定。

## AGENTS.md 治理设计

在现有 CodeGraph 说明之前新增“项目文档系统”章节。其规则为：

如果当前请求符合 `AGENTS.md` 中 Comet Ambient Resume 的探测条件，必须先完成 `comet resume-probe`，再按下述顺序读取项目文档；Comet 托管块列出的显式调用、流程延续和其他例外继续优先适用。

### 必读顺序

1. 任何项目任务先读 `README.md`。
2. 涉及项目目标、范围、原则或取舍时读 `docs/project.md`。
3. 涉及代码、实现、调试或技术判断时读 `docs/architecture.md`。
4. 涉及未来计划、功能选择或优先级时读 `docs/roadmap.md`。

### 条件参考

涉及 PDF 翻译接口、事件协议、SettingsModel、Provider、BabelDOC 或上游版本时，额外读取：

- `docs/pdf2zh-next-development-guide.md`
- `docs/reports/pdf2zh-internals-report.md`
- `docs/reports/babeldoc-vs-pdf2zh-next-report.md`

查历史时读取 `CHANGELOG.md`、`docs/superpowers/`、`openspec/changes/archive/` 和 `docs/archive/`，但不得把历史内容当成当前事实或授权。

### 冲突裁决

- 当前行为事实：代码和测试高于 architecture；发现冲突时必须在同一变更中修正 architecture。
- 项目意图与原则：project 高于 README、roadmap 和历史资料；AI 不得自行改变原则。
- 未来方向：roadmap 只允许指导讨论和计划，不允许直接实施。
- 归档与历史记录只能用于追溯。
- 如果原则冲突或用户意图不明确，必须询问用户，不能从历史资料推断授权。

### 更新触发条件

- 用户可见功能、安装、启动或验证方式变化：更新 README。
- 模块、API、数据流、状态、依赖或运行边界变化：与代码同一变更更新 architecture。
- 项目目的、长期意图或常青原则变化：只有用户明确确认后更新 project。
- 未来方向、优先级或路线状态变化：更新 roadmap，但不得自动实现。
- pdf2zh-next/BabelDOC 版本升级：复核参考资料的适用范围并更新版本横幅。

## 旧文档归档设计

所有文件完整保留，不删除正文：

| 当前路径 | 目标路径 | 归档处理 |
|---|---|---|
| `docs/PROJECT_STATUS.md` | `docs/archive/2026-08-06-project-status.md` | 顶部加历史快照说明 |
| `docs/project-architecture.md` | `docs/archive/project-architecture.md` | 顶部声明已由新 architecture 取代 |
| `docs/module-interactions.md` | `docs/archive/module-interactions.md` | 顶部声明不反映当前模块关系 |
| `docs/module-flow.html` | `docs/archive/module-flow.html` | 页面顶部加入可见历史说明，不重写旧图 |
| `docs/manual-verification-checklist.md` | `docs/archive/manual-verification-checklist.md` | 顶部声明是未继续维护的历史验收记录 |

Markdown 归档文档统一说明：

> 本文档是历史快照，不再维护，也不得用于判断当前实现。当前项目意图见 `docs/project.md`，当前实现见 `docs/architecture.md`，未来方向见 `docs/roadmap.md`。

归档文件中的相对链接在移动后必须检查并修复，不能留下死链。

## 上游参考资料保护设计

以下文件保持当前路径：

- `docs/pdf2zh-next-development-guide.md`
- `docs/reports/pdf2zh-internals-report.md`
- `docs/reports/babeldoc-vs-pdf2zh-next-report.md`

只在顶部增加研究快照说明：

- 记录最初核对的上游版本和日期。
- 说明当前实际依赖版本以 `requirements.lock` 为准。
- 提醒修改集成前重新核对当前上游源码。
- 明确它们是外部依赖参考，不是当前项目架构事实源。

其中 development guide 主要基于 `pdf2zh-next 2.8.2`；当前仓库锁定 `pdf2zh-next 2.9.0` 和 `BabelDOC 0.6.2`。两份报告保留各自原始研究版本语境。

## 保持原位的路径

- `docs/superpowers/`：历史设计、计划和验收记录；路径可能被工具元数据引用。
- `docs/glossary.csv`：应用运行时读取的数据文件。
- `openspec/`：现有规格和历史变更。
- `docs/comet/`：由 Comet Native 管理。
- `tests/README.md`：正式测试与历史诊断脚本说明。
- `CHANGELOG.md`：时间序列变更历史。

## CHANGELOG 设计

在 CHANGELOG 顶部增加本次文档系统变更，记录：

- 建立 README/project/architecture/roadmap 四文档体系。
- AGENTS 增加必读顺序、冲突裁决和维护规则。
- 旧现役文档完整归档。
- PDF2zh/BabelDOC 研究资料保留并标注版本适用范围。
- 应用行为、API 和缓存格式没有变化。

## 实施约束

- 文件内容修改使用 `apply_patch`。
- 文件移动必须逐个执行并核对精确源、目标路径，不做递归批量移动。
- 不修改产品源码、测试逻辑、依赖文件或运行时配置。
- 不移动 `docs/superpowers/`、`docs/glossary.csv`、`openspec/`、`docs/comet/`、`CHANGELOG.md` 或 `tests/README.md`。
- 不删除任何现有重要文档。
- architecture 中的事实必须通过 CodeGraph、源码、配置和验证命令交叉核对。
- Roadmap 中不得出现无状态条目或暗示自动实施的措辞。

## 验证设计

实施后执行以下验证：

1. 检查 `README.md`、`docs/project.md`、`docs/architecture.md`、`docs/roadmap.md` 均存在且链接正确。
2. 检查 `AGENTS.md` 包含四文档阅读规则、条件参考、冲突裁决和更新触发条件。
3. 搜索 README 和现役文档，确认没有遗留指向旧 `docs/PROJECT_STATUS.md` 或旧现役路径的链接。
4. 检查五份旧文档都存在于 `docs/archive/`，且 Markdown/HTML 有可见历史说明。
5. 检查三份 PDF2zh/BabelDOC 参考资料仍在原路径并包含版本适用范围说明。
6. 检查 `docs/superpowers/`、`docs/glossary.csv`、`openspec/`、`docs/comet/`、`CHANGELOG.md` 和 `tests/README.md` 仍在原路径；除本设计明确要求的 CHANGELOG 新条目外，后两者的既有内容未被改写。
7. 搜索新四文档中的 `TBD`、`TODO`、未解释占位和历史状态叙事。
8. 以“初始架构事实”清单为核对表，通过 CodeGraph、源码、配置和验证命令逐项交叉核对 architecture 中的模块、数据流、端点、并发、缓存、依赖和测试事实。
9. 检查 `docs/archive/` 中所有归档文档的相对链接和资源引用，确认移动后不存在因路径变化导致的死链。
10. 运行 `powershell -ExecutionPolicy Bypass -File scripts/verify.ps1`。
11. 检查最终 Git diff 只包含文档系统相关变更。

## 验收标准

1. 新会话从 `AGENTS.md` 可以明确知道应先阅读哪几份文档。
2. 四份常青文档之间没有职责重叠或互相矛盾。
3. README 可以独立指导安装、启动和验证，并成为常青文档导航入口。
4. project 清晰说明项目存在原因、核心价值、原则、边界和上游关系，不包含实现细节或候选路线决策。
5. architecture 完整、准确地反映当前 HEAD，不包含未来方案。
6. roadmap 明确非实施授权，且不擅自决定尚未确认的产品方向。
7. 旧现役文档全部归档并保留正文，不再冒充当前事实。
8. PDF2zh/BabelDOC 高价值参考资料保持可发现、可引用，并明确版本语境。
9. 历史工具路径和运行时术语数据未被破坏。
10. 统一验证通过，应用行为没有变化。
