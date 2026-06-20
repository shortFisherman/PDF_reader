# Verification Report: cumulative-glossary-across-pages

**Date**: 2026-06-20
**Verify Mode**: Full

## Summary

| Dimension | Status |
|-----------|--------|
| Completeness | 10/10 tasks complete, 3 requirements covered |
| Correctness | 3/3 requirements implemented, 3/3 scenarios covered |
| Coherence | Design decisions followed, no divergences |

## Completeness

All 10 tasks checked off. Implementation evidence:

| Task | File(s) | Status |
|------|---------|--------|
| 1.1 glossary_cache_path | `state.py:56` | ✓ |
| 1.2 merge_glossary_csvs | `glossary_merger.py:9` | ✓ |
| 1.3 glossary_paths param | `services.py:75` | ✓ |
| 2.1 Pre-translation load | `routes.py:112-117` | ✓ |
| 2.2 Post-translation merge | `routes.py:224-235` | ✓ |
| 2.3 Boundary handling | `glossary_merger.py:10-13` (missing auto), `:30-32` (empty auto) | ✓ |
| 3.1-3.4 Verification | Test suite: 39/39 passed | ✓ |

## Correctness

### Requirement: 累积术语表加载

- **Pre-translation check**: `routes.py:114-117` — checks `cumulative_file.exists()` and `st_size > 0` before passing to `build_settings`
- **Scenario "已有累积术语表"**: `routes.py:117` sets `glossary_paths = [str(cumulative_file)]`
- **Scenario "无累积术语表"**: `routes.py:113` defaults `glossary_paths = None`
- **Scenario "切换教材"**: `state.py:57` returns `cache_dir / pdf_hash`, different hash = different path

### Requirement: 累积术语表合并

- **Post-translation merge**: `routes.py:224-235` — executes AFTER `replace_page` and BEFORE `finally` cleanup
- **Scenario "首次合并"**: `glossary_merger.py:16-21` — reads existing (empty), creates from auto
- **Scenario "追加合并"**: `glossary_merger.py:23-28` — reads both, majority vote at line `:38`
- **Scenario "无自动提取术语"**: `glossary_merger.py:10-11` — early return if auto missing

### Requirement: 与静态术语表兼容

- **Coexistence**: `services.py:86-93` — builds `paths` list from static + dynamic, joins with comma
- **Scenario "两者共存"**: Both appended to `paths`, `",".join(paths)` produces comma-separated string

## Coherence

| Design Decision | Verification |
|-----------------|-------------|
| Storage: `CACHE_DIR/<hash>/cumulative_glossary.csv` | `state.py:57` returns `cache_dir / pdf_hash` |
| Merge: majority vote | `glossary_merger.py:38` uses `max(targets, key=lambda t: targets[t])` |
| Comma-separated glossaries | `services.py:93` `",".join(paths)` |
| Merge before finally cleanup | `routes.py:224` (merge) vs `routes.py:242` (finally's rmtree) |
| Static + cumulative coexistence | `services.py:86-93` appends both to `paths` list |

## Issues

**No issues found.** All checks pass.

## Test Results

```
39 passed in 0.20s
```

## Assessment

All checks passed. Ready for archive.
