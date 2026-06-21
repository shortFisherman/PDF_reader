## Context

当前 PDF Reader 翻译流程依赖 babeldoc + pdf2zh-next 完成底层翻译工作。这些依赖库内部有大量 INFO/DEBUG 日志，但：
1. babeldoc 的调试输出（`term_extractor_tracking.json` 等）需要 `TranslationConfig.debug = True` 才生成，当前未开启
2. `AutomaticTermExtractor.extract_terms_from_paragraphs` 对 LLM 返回的解析静默处理——若返回 `[]` 或格式异常，外部完全无法感知
3. routes.py 的翻译流程日志过于稀疏，无法追踪每步状态

**约束**：不修改 babeldoc/pdf2zh-next 源码，通过配置 + monkey-patching 实现可观测性。

## Goals / Non-Goals

**Goals:**
- 一键开启全链路调试模式（`--debug` flag）
- 术语提取过程透明化：每批 LLM 调用的 prompt 量、返回内容、解析结果、术语数量
- 翻译流程步骤透明化：每步的输入/输出/状态
- 调试文件输出至 `cache/<pdf_hash>/`，与累积术语表共存，方便事后排查
- 调试模式关闭时行为与原来完全一致

**Non-Goals:**
- 不修改 babeldoc/pdf2zh-next 源码
- 不修复术语提取效果问题（那是诊断后的事）
- 不引入新的外部依赖
- 不改变翻译性能特征（minimal overhead）

## Decisions

### Decision 1: `--debug` CLI flag + app config

**选择**：通过 `app.py` 接受 `--debug` 参数，写入 `config.DEBUG`，`services.py` 读取并传递给 `TranslationConfig.debug`。

**替代方案**：
- 环境变量 `PDF_DEBUG=true`：更轻量，但 discoverability 差，用户不知道有这个选项
- 始终开启 debug：产生大量无用 IO，浪费磁盘空间

**理由**：CLI flag 显式且可发现，用户明确知道自己开启了调试模式。

### Decision 2: Monkey-patch 而非 fork/copy

**选择**：在模块加载时 monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs`，注入日志代码。

**替代方案**：
- 复制 babeldoc 源码到项目中修改：维护负担重，版本升级后需同步
- 通过 babeldoc 插件机制：不存在此机制

**理由**：monkey-patch 零侵入，版本升级兼容性好（仅依赖方法签名不变），可随时关闭。

**实现方式**：
```python
# debug_patches.py
_original_extract = AutomaticTermExtractor.extract_terms_from_paragraphs

def _patched_extract(self, paragraphs, pbar=None, paragraph_token_count=0):
    # log input
    # call original
    # log output
    return _original_extract(self, paragraphs, pbar, paragraph_token_count)

AutomaticTermExtractor.extract_terms_from_paragraphs = _patched_extract
```

### Decision 3: 日志输出策略

**选择**：使用 Python logging 模块，logger name `pdf_reader.debug_trace`，级别 INFO。

- 每批术语提取前后各一行日志
- LLM 原始返回截断至 500 字符（避免日志爆炸）
- 解析后的术语数量单独一行

**理由**：统一日志框架，不引入新的输出机制；截断避免日志文件过大。

### Decision 4: 调试文件写入位置

**选择**：写入 `cache/<pdf_hash>/` 目录（与 `cumulative_glossary.csv` 同路径）。

**理由**：babeldoc 的 debug 输出会写到 `working_dir`，但 `working_dir` 在翻译完成后被清理。我们需要在 `working_dir` 被清理前将文件复制到 cache 目录。

## Risks / Trade-offs

- **[Risk]** monkey-patch 在 babeldoc 版本升级后方法签名变化可能失效 → **Mitigation**：用 try/except 包裹 patch 逻辑，失败时降级（不 crash，仅失去增强日志）
- **[Risk]** LLM 返回内容可能包含敏感信息，记录下来有泄露风险 → **Mitigation**：仅记录到本地文件，不通过网络传输；日志截断至 500 字符
- **[Risk]** debug 模式下术语提取 tracking 文件较大（每批的完整 prompt） → **Mitigation**：仅 debug 模式写入，正常模式零开销

## Open Questions

- DeepSeek 思考模式下的 LLM 返回格式具体是什么样？（开启 debug 后即可知道）
- 是否需要将 debug 文件自动汇总为人类可读报告？（v2）
