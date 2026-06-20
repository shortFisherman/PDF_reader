---
comet_change: cumulative-glossary-across-pages
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-20-cumulative-glossary-across-pages
status: final
---

# Cumulative Glossary Across Pages — Technical Design

## Overview

PDF 阅读器使用 pdf2zh-next 进行单页翻译。每次翻译的术语提取结果当前随临时目录丢弃。本设计实现跨页面术语表累积，使 LLM 在翻译后续页面时能看到前面已提取的术语，保持译名一致性。

## Architecture

```
                    routes.py translate_page()
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          state.py   services.py   (post-translation)
              │          │
              ▼          ▼
    glossary_cache_path  build_settings(glossary_paths=...)
              │          │
              │          ▼
              │    Pdf2zhTranslationSettings(glossaries="path1,path2")
              │          │
              │          ▼
              │    do_translate_async_stream() → translate_result
              │                                    │
              │                   auto_extracted_glossary_path
              │                                    │
              └────────────────────────────────────┘
                                 │
                                 ▼
                      merge_glossary_csvs() → cumulative_glossary.csv
```

Two-phase injection within pdf2zh-next (no changes to library):
1. **Term extraction prompt**: User glossaries matched via hyperscan → injected as "Reference Glossaries" section
2. **Translation prompt**: Matched glossary entries → formatted as Markdown table with enforce rule

## Key Design Decisions

### Glossary Storage

**Path**: `CACHE_DIR/<pdf_hash>/cumulative_glossary.csv`

`AppState.open_pdf()` already creates `CACHE_DIR/<hash>/` for `right.pdf`. Reusing this directory avoids additional directory management. PDF SHA256 ensures isolation across different textbooks.

### Merge Strategy

```
load existing CSV → dict[source] = {target: count}
load auto-extracted CSV → update dict[source][target]++
for each source: keep target with highest count (majority vote)
write merged CSV
```

Mirrors pdf2zh-next's internal `finalize_auto_extracted_glossary()` voting logic. Handles the case where the same term appears on multiple pages with different translations.

### Passing Glossaries to Pipeline

The `glossaries` parameter in `TranslationSettings` accepts comma-separated file paths. `pdf2zh_next`'s `_get_glossaries()` splits on comma and loads each path as an independent `Glossary` object. Both static (`docs/glossary.csv`) and cumulative glossaries are passed together:

```python
paths = []
if config.GLOSSARY_PATH.exists():
    paths.append(str(config.GLOSSARY_PATH))
if cumulative_path and cumulative_path.exists():
    paths.append(str(cumulative_path))
translation_kwargs["glossaries"] = ",".join(paths)
```

### Extraction → Merge Hook Point

In `routes.py` translate_page(), after receiving `translate_result` from the event stream:

```python
if translate_result.auto_extracted_glossary_path:
    auto_path = Path(translate_result.auto_extracted_glossary_path)
    cumulative_path = state.glossary_cache_path / "cumulative_glossary.csv"
    merge_glossary_csvs(cumulative_path, auto_path)
```

Must execute before the `finally` block's `shutil.rmtree(output_dir)`.

### State Exposure

```python
# state.py AppState
@property
def glossary_cache_path(self) -> Path | None:
    if self._pdf_hash is None:
        return None
    return self._cache_dir / self._pdf_hash
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Cumulative CSV missing | Skip loading, proceed normally (first page) |
| Auto-extracted CSV missing/empty | Skip merge, cumulative table unchanged |
| CSV encoding error | Log warning, skip merge for this page |
| Merge produces empty result | Don't overwrite existing cumulative file |

## Testing Plan

1. Manual: Translate page 5 of a PDF → verify `cumulative_glossary.csv` created
2. Manual: Translate page 10 of same PDF → verify glossary loaded + new terms merged
3. Manual: Open different PDF, translate → verify separate glossary
4. Automated: `pytest tests/` for regression
