# Brainstorm Summary

- Change: cumulative-glossary-across-pages
- Date: 2026-06-20

## Confirmed Technical Approach

按 PDF SHA256 哈希在 `CACHE_DIR/<hash>/cumulative_glossary.csv` 持久化累积术语表。翻译前加载，翻译后合并。合并策略：按 source 列分组，多数投票选最常出现的 target。通过 `glossaries` 逗号分隔多路径传给 pdf2zh-next 管道，LLM 在术语提取和正文翻译两个阶段自动看到术语表。

## Key Trade-offs and Risks

- 术语表随阅读进度自然增长，教材级术语通常 <500 条，hyperscan 可高效处理
- Flask 单线程，无并发写入问题
- 同一 source 多译文时用投票策略，极端情况下可能选到错误译文；可通过人工审查 CSV 纠正

## Testing Strategy

手动验证三步：
1. 首次翻译某页 → 确认 cumulative_glossary.csv 生成
2. 翻译同 PDF 另一页 → 确认术语表加载且新术语已合并
3. 切换到不同 PDF → 确认使用独立术语表
4. 运行 `pytest tests/` 确保无回归

## Spec Patches

None
