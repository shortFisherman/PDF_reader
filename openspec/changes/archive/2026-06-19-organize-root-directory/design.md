## 方案

移动 4 个文件并更新一处配置引用：

```
babeldoc-vs-pdf2zh-next-report.md    → docs/reports/babeldoc-vs-pdf2zh-next-report.md
pdf2zh-internals-report.md            → docs/reports/pdf2zh-internals-report.md
pdf2zh-next-development-guide.md      → docs/pdf2zh-next-development-guide.md
glossary.csv                          → docs/glossary.csv
```

`config.py:14` 中的 `GLOSSARY_PATH` 从 `Path(__file__).parent / "glossary.csv"` 改为 `Path(__file__).parent / "docs" / "glossary.csv"`。
