## 1. 累积术语表管理

- [x] 1.1 `state.py`：在 `AppState` 中新增属性 `glossary_cache_path`，返回 `CACHE_DIR/<pdf_hash>/`，打开 PDF 时计算
- [x] 1.2 新增 `glossary_merger.py`（或在 `services.py` 中）：实现合并函数，读取两个 CSV 按 `source` 列合并去重，多数投票选 `target`
- [x] 1.3 `services.py`：`build_settings` 新增可选参数 `glossary_paths: list[str] | None`，逗号拼接后传给 `TranslationSettings.globals`

## 2. 翻译流程集成

- [x] 2.1 `routes.py` `translate_page()`：翻译前根据 `state.pdf_hash` 检查是否存在 `cumulative_glossary.csv`，存在则加入 `glossary_paths`
- [x] 2.2 `routes.py` `translate_page()`：翻译完成后，从 `translate_result.auto_extracted_glossary_path` 读取并合并到累计术语表（在 `finally` 清理前执行）
- [x] 2.3 合并时处理边界：累积表为空（首次）、auto_extracted 为空（无可提取术语）等

## 3. 验证

- [x] 3.1 手动测试：翻译同一 PDF 第一页 → 确认 `cumulative_glossary.csv` 已创建
- [x] 3.2 手动测试：翻译同一 PDF 第二页 → 确认累积术语表被加载且新增术语已合并
- [x] 3.3 手动测试：打开另一 PDF 翻译 → 确认使用独立术语表
- [x] 3.4 运行现有测试确保无回归：`pytest tests/`（39 passed）
