# cumulative-glossary-persistence Specification

## Purpose
TBD - created by archiving change cumulative-glossary-across-pages. Update Purpose after archive.
## Requirements
### Requirement: 累积术语表加载

翻译某页前，如果该 PDF 已有累积术语表文件，系统 SHALL 将其路径与用户静态术语表路径一并传递给翻译管道。

#### Scenario: 已有累积术语表
- **WHEN** 用户翻译某页，且 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv` 已存在
- **THEN** `build_settings` 的 `glossaries` 参数包含该路径，翻译管道加载并注入术语提取和正文翻译 prompt

#### Scenario: 无累积术语表（首次翻译）
- **WHEN** 用户首次翻译该 PDF 的某页，且 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv` 不存在
- **THEN** 行为与当前一致，术语提取正常执行，不加载额外术语表

#### Scenario: 切换教材
- **WHEN** 用户打开另一本 PDF 并翻译
- **THEN** 使用该 PDF 哈希对应的独立累积术语表，不与上一本教材的术语表混淆

### Requirement: 累积术语表合并

翻译完成后，系统 SHALL 将本轮自动提取的术语与已有累积术语表合并去重后持久化。

#### Scenario: 首次合并
- **WHEN** 翻译完成且 `translate_result.auto_extracted_glossary_path` 指向有效 CSV，且累积术语表不存在
- **THEN** 直接将自动提取的术语 CSV 作为累积术语表写入 `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv`

#### Scenario: 追加合并
- **WHEN** 翻译完成且自动提取术语表和累积术语表均存在
- **THEN** 读取两者，按 `source` 列合并，同一 source 取多数投票的 `target`，写回累积术语表

#### Scenario: 无自动提取术语
- **WHEN** 翻译完成但 auto_extracted_glossary_path 为 None 或文件不包含新术语
- **THEN** 累积术语表保持不变

### Requirement: 与静态术语表兼容

系统 SHALL 同时支持用户静态术语表（`GLOSSARY_PATH`）和累积术语表，两者共存不冲突。

#### Scenario: 静态术语表 + 累积术语表共存
- **WHEN** 用户配置了 `docs/glossary.csv` 且已有累积术语表
- **THEN** `glossaries` 参数包含两个路径（逗号分隔），两个术语表同时生效

