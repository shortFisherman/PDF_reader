# 术语上游边界决策记录（P0-01）

> 本文件记录 P0-01 已用离线契约核验的上游事实与项目边界决策，是后续 P0-04
> （严格正文路径）与 P1-01（候选解耦）的适配依据。上游行为以固定版本的契约测试为准，
> 不授权修改、fork、vendor、复制、Monkey-patch 或 import-shadow 上游。

建立日期：2026-08-31
固定基线：pdf2zh-next 2.9.0 / BabelDOC 0.6.2
来源清单：`docs/improvement items/glossary-memory-improvement-plan-831.md` 第 3 节红线与 P0-01

## 1. 已固定的上游事实

BabelDOC 0.6.2 `SharedContextCrossSplitPart.get_glossaries_for_translation(auto_extract_enabled)`
的正文词表选择：

| auto_extract_enabled | 自动词表状态 | 正文翻译拿到的词表 |
|---|---|---|
| true | 存在 | 仅自动词表（用户/累计词表被排除） |
| true | 不存在 | 用户词表（回退） |
| false | 存在或不存在 | 用户词表 + 自动词表（如存在） |

本项目 `translation_settings.build_settings()` 在 P0-04 后的严格正文映射：

| `translation.auto_extract_glossary` | `no_auto_extract_glossary` | `save_auto_extracted_glossary` | `glossaries` |
|---|---|---|---|
| true（正文惰性） | true | false | 调用方传入的 `effective_glossary.csv`（零权威行时省略） |
| false | true | false | 同上 |

`translation.auto_extract_glossary` 不再反转正文开关；正文恒为严格路径。
P1-01 候选服务落地后，自动候选收集由项目侧旁路服务恢复：未配置
`[term_extraction]` 段时 `enabled` 跟随本键显式值（旧默认 true），候选只进
`term_candidates.json`，不经用户接受绝不进入正文。

真实转换链还有一个已核验的上游缺口：pdf2zh-next 2.9.0 `create_babeldoc_config`
只转发 `auto_extract_glossary`，不把 `save_auto_extracted_glossary` 传给 BabelDOC，
因此 BabelDOC 侧恒为默认 true；auto-off 时自动词表不存在，实际不会写自动词表文件。

结论：auto-on 下，用户/累计词表主要作为自动提取参考；只要自动提取产生了任意词表，
正文翻译只使用自动词表。用户权威术语若未被提取器复述，就不会直接约束正文。
这是 P0-01 用稳定通过的特征测试固定下来的已知产品限制；测试正向断言当前上游行为，
因此不会把预期失败长期留在测试基线中。

## 2. 边界决策

严格正文路径（P0-04）与候选解耦（P1-01）按以下边界执行：

- 严格正文路径已在项目调用边界关闭上游自动提取：正文 SettingsModel 恒为
  `no_auto_extract_glossary=true`、`save_auto_extracted_glossary=false`，只把本次
  fresh 的 `effective_glossary.csv` 经受支持的 `glossaries` 传入正文。路由先
  `coordinator.start` 占位再准备词表，busy/shutdown 不触发任何准备写操作；SSE
  在抽取/上游前校验 `StrictTranslationContext` 与任务身份一致，约束块有 32 KiB
  UTF-8 上限且整行纳入。
- 自动候选由项目侧独立候选服务产出，只写候选存储；用户确认前不得进入正文有效词表，
  也不改变正文翻译的词表选择。
- P1-01 候选服务是正文成功提交后的旁路：`TermExtractionClient` 走项目自有
  OpenAI-compatible `/chat/completions` 受控请求（支持 deepseek/openai/
  openai_compatible，其余 Provider 稳定降级），响应只解析受控 JSON，失败只
  降级日志；详见 [term-extraction-client-boundary.md](term-extraction-client-boundary.md)。
- 提交门（P0-05）在项目边界验证最终候选译文：`replace_page`/`replace_pages`
  前用 PyMuPDF 提取译文文本，对当前页/批次活跃权威 source→target 做精确 target
  检查。源侧同样 fail-closed：rows 为空或源文本成功且无命中才视为
  available+empty 并零成本跳过验证；源 PDF 打不开/抽取异常/文本为空且存在
  effective rows 为 unavailable，在调用上游前返回
  `glossary_verification_unavailable`，不 `run_translation`、不提交、不 merge。
  首次不合规只整页/整批重试 1 次（同一 job/输入/严格上下文/task identity，
  独立 `attempt-2/output/` 目录与 Settings 深拷贝，Prompt 追加有界纠错块），
  重试通过才提交；无法可靠提取/缺页/空文本返回
  `glossary_verification_unavailable`，重试仍不合规返回
  `glossary_compliance_failed`，两者都不提交、不 merge、不修改旧 `right.pdf`。
  无活跃词条时零验证/重试成本。验证不做 PDF 字符串替换，也不宣称模型绝对可靠。
- 允许使用并持续核验的上游边界：`SettingsModel` 的 `glossaries` /
  `no_auto_extract_glossary` / `save_auto_extracted_glossary`（及对应的 BabelDOC
  `TranslationConfig` 字段）、翻译事件、mono/dual/glossary 输出路径。
- 契约测试可以导入 BabelDOC 深层类型（如 `SharedContextCrossSplitPart`、
  `TranslateResult`）来固定行为；生产核心不得把深层私有类作为长期实现依赖。
- 禁止：编辑 `venv/site-packages`、维护上游 fork、vendor/复制上游源码、创建同名影子包、
  运行时替换 `AutomaticTermExtractor` / `get_glossaries_for_translation` 等上游函数或模块。

若上游行为无法满足产品不变量，处理顺序固定为：
先用契约测试证明限制 → 在本项目边界增加适配或独立服务 → 必要时暂时关闭该上游功能 →
记录剩余问题。不得把“直接修改上游内部代码”作为备选方案。

## 3. 仓库守卫

`tests/test_upstream_boundary_governance.py` 持续检查：

- Git 跟踪内容不含 `pdf2zh_next/`、`babeldoc/` 影子包，也没有包含上游独有
  类/函数定义标记的源码副本；
- `src/pdf_reader` 生产模块没有显式 Monkey-patch 上游术语功能、没有替换上游模块，
  也没有引入 mock/monkeypatch/patch 测试替身；
- 守卫只扫描生产目录，`tests/` 使用 mock patch 不误报。

## 4. 验证证据

- 行为契约：`tests/test_upstream_contract.py` 的
  `SharedContextCrossSplitPart.get_glossaries_for_translation` auto-on/auto-off/
  无自动词表回退用例、auto-on 用户术语缺失的特征测试与
  `build_settings` 两个开关的映射用例。
- 治理守卫：`tests/test_upstream_boundary_governance.py`。
- 升级前置：`docs/governance/dependency-upgrade.md`。

## 5. 剩余问题

- P0-05 提交门已实施，但精确 target 检查只做规范化后子串/词边界匹配，可能拒绝
  语义等价但字形/标点不同的合法译法（宁可重试或拒绝，不误报通过）；batch 首版
  是整批原子验证与整批重试，单页违规会触发整批成本，逐页定位留待 P1-05 统一
  单页/批量术语生命周期与失败语义。
- P0-01 验收要求的上游契约测试与仓库守卫已可执行；条目台账的“已完成”状态需在
  实现提交后由主 Agent 更新。
