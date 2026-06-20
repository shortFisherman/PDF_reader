## Why

当前 PDF 阅读器是「看一页翻译一页」的交互模式。每次翻译单独一页时，pdf2zh-next 的术语提取阶段会将该页发现的专业术语自动翻译并生成术语表，但翻译完成后术语表随临时目录一起被清理，下一页面翻译时 LLM 无法看到前面已提取的术语。对于阅读专业教材的场景，这导致同一术语在不同页面可能被译成不同的中文，破坏译名一致性。

## What Changes

- 翻译前：检查是否已有该 PDF 的累积术语表，若有则通过 `glossaries` 参数传递给翻译管道
- 翻译后：从翻译结果中提取自动生成的术语表，与已有的累积术语表合并去重后持久化
- 以 PDF 的 SHA256 哈希作为缓存键，不同教材的术语表互不干扰

## Capabilities

### New Capabilities

- `cumulative-glossary-persistence`: 每页翻译提取的术语自动合并到按 PDF 隔离的持久化累积术语表中，后续页面翻译时自动加载

### Modified Capabilities

无。此变更仅影响术语表的生命周期管理，不改变已有 spec 级行为。

## Impact

- `routes.py`：翻译完成后合并术语表，翻译前加载累积术语表
- `services.py`：`build_settings` 支持累积术语表路径
- `state.py`：暴露 PDF 缓存子目录路径供术语表存取
