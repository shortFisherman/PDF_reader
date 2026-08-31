# 候选术语提取边界决策记录（P1-01）

> 本文件记录 P1-01 把“自动提取”从正文翻译中解耦为项目自有旁路候选服务时的
> 方案比较与边界决策。事实来源为固定上游 pdf2zh-next 2.9.0 / BabelDOC 0.6.2、
> 本仓库 P0-01~P0-05 契约测试与当前实现；不授权修改、fork、vendor、复制、
> Monkey-patch 或 import-shadow 上游。

建立日期：2026-08-31
固定基线：pdf2zh-next 2.9.0 / BabelDOC 0.6.2

## 1. 方案比较（只读可行性探针）

| 方案 | 受支持边界 | 结论 |
|---|---|---|
| 复用上游公开配置（`auto_extract_glossary` + 自动词表输出） | P0-01 已固定：auto-on 会改变正文词表选择，且没有“只提取术语、不翻译正文”的稳定受支持 API；`save_auto_extracted_glossary` 在 pdf2zh-next 2.9.0 中不被转发到 BabelDOC | 不采用：会把候选收集与正文词表选择重新耦合，违反候选隔离红线 |
| 调用 BabelDOC 深层私有类（如 `AutomaticTermExtractor`、`SharedContextCrossSplitPart.get_glossaries_for_translation`） | 契约测试可以导入固定行为，但属于未承诺的深层/私有实现，升级即可能破坏 | 不采用为生产核心；契约测试固定行为可以保留，生产不得依赖 |
| 项目自有小接口 `TermExtractionClient` | 项目直接声明的依赖或标准库；走 OpenAI-compatible `/chat/completions` 受控请求；复用正文 `[model]` 的 provider/api_key/model/base_url | **采用**：最小、可测试、不绑定上游私有内部，不复制 pdf2zh-next 引擎注册表 |

## 2. 决策

- 采用项目自有 `TermExtractionClient`（`src/pdf_reader/term_extraction.py`），
  使用标准库 `urllib`，不新增依赖，不读取 BabelDOC/pdf2zh-next 内部模块。
- 端点按 OpenAI-compatible chat completions 契约：`base_url` 用
  `urllib.parse` 严格解析，只接受 http/https 且必须带 netloc，拒绝
  userinfo/query/fragment；`/v1`、`/v1/` 自动拼成
  `/v1/chat/completions`，已是 `/chat/completions`（含尾斜杠）保持不变；
  `openai_compatible` 必须使用配置的 `base_url`；`deepseek`/`openai` 未配置
  base_url 时使用官方默认（`https://api.deepseek.com/v1`、
  `https://api.openai.com/v1`）。
- 首版支持 provider：`deepseek`、`openai`、`openai_compatible`。其余 provider
  返回稳定 `unsupported` 降级，不调用网络，不影响正文。
- 只解析受控 JSON `{"terms":[{"source","target"}]}`：条数、字段长度、控制字符、
  无效结构、响应正文大小全部有界且 fail-closed；去重确定。
- 网络重试只针对超时（含 `TimeoutError`/`socket.timeout` 与
  `URLError.reason` 为 timeout）/429/5xx；连接类错误、4xx 与响应解析/schema
  错误不重试；QPS、并发、timeout 全部独立于正文配置。成功与错误响应都显式
  close，客户端自身按 `max_input_chars` 前缀截断输入。
- 候选只经 `CandidateStore.record_observations`（批量原子）写入
  `term_candidates.json`；不写 `user_glossary.csv`、`effective_glossary.csv`
  、`glossary.csv`，也不改变正文 `SettingsModel`。
- 不复制 pdf2zh-next 的整个翻译引擎注册表；本项目只维护一个小型 provider
  支持集合（`SUPPORTED_PROVIDERS`）与默认 base URL 映射。

## 3. 服务时序

```text
正文翻译（严格路径）→ P0-05 合规验证 → 提交 right.pdf → 旁路候选提取
  → CandidateStore.record_observations（原子）

正文失败 / 合规失败 → 不调用候选服务
候选网络 / 解析 / 存储失败 → 安全日志降级，正文仍 finish
```

单页与批量使用同一规则；首版同步执行（严格 timeout、无悬挂线程），不启动
第二个 coordinator job。候选变化不触发有效词表 stale（P0-03 只投影
accepted），未确认候选永不进入正文。

## 4. 验证证据

- 客户端契约：`tests/test_term_extraction.py`（fake local HTTP server；请求
  schema/端点拼接、429/5xx 重试、4xx/格式/超限不重试、超时、受控解析、隐私）。
- 服务契约：`tests/test_candidate_service.py`（成功写候选、accepted/rejected
  不覆盖、unsupported/disabled/empty/超限/网络失败/存储失败全部降级、日志隐私）。
- SSE 集成：`tests/test_candidate_sse.py`（单页/批量只在提交后调用；正文失败/
  合规失败不调用；候选失败不阻 finish；候选不进 effective/Settings）。
- 存储原子性：`tests/test_candidate_store.py` 的 `record_observations` 批量用例。
- 配置：`tests/test_config_deferred.py`、`tests/test_config_editor.py`、
  `tests/test_config_example.py`。

## 5. 剩余问题

- P1-02 前证据字段为空、页码为“参与本次输入的页范围”的粗粒度归属；精确源文
  证据、边界匹配与普通词过滤属于 P1-02，本条目不越界实现。
- P1-03 前不实现更丰富计数/排序建议；`record_observations` 已保留观察次数合并
  语义，为 P1-03 提供原子入口。
