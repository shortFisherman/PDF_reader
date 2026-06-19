# Brainstorm Summary

- Change: organize-translation-byproducts
- Date: 2026-06-19

## Confirmed Technical Approach

Translation output directory: `tempfile.mkdtemp(dir=config.CACHE_DIR)` (system temp under `cache/`), cleaned up in `finally` block.

Changes (2 files, ~6 lines):
1. `services.py`: `build_settings()` adds `output_dir` optional param → sets `translation.output`
2. `routes.py`: create output temp dir, pass to `build_settings()`, cleanup in `finally`

## Key Trade-offs and Risks

- Babeldoc writes in subprocess → cleanup after subprocess exits; `ignore_errors=True` as fallback
- No persistence of byproducts; no impact on translation correctness

## Testing Strategy

Manual verification of 3 scenarios:
1. Successful translation → no root byproducts
2. Failed translation → temp dir cleaned
3. Translated PDF correctly shown in right panel

## Spec Patches

None — delta spec already covers both requirements.
