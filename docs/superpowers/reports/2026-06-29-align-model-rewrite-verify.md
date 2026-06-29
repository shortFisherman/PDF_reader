# Verification Report: align-model-rewrite

**Date**: 2026-06-29
**Base**: 5f4f414a
**Head**: bf78b01
**Mode**: Full (30 tasks, 3 delta specs, 30 changed files)

## Summary

| Dimension    | Status                                             |
|--------------|----------------------------------------------------|
| Completeness | 30/30 tasks checked, 3 delta specs addressed       |
| Correctness  | All 51 frontend tests pass + grep exclusivity      |
| Coherence    | Design decisions D1-D8 implemented, no divergences |

## Completeness

- **Tasks**: 30/30 checked (`[x]`) in both `tasks.md` and plan
- **Delta specs**: 3 capabilities (column-alignment, dual-column-reading, page-zoom) — all addressed
- **Proposal**: Goals satisfied (see Correctness section)

## Correctness

### Test Results

| Test Suite | Result |
|------------|--------|
| `run-alignment-controller-tests.mjs` | 20/20 PASS + grep exclusivity PASS |
| `run-zoom-tests.mjs` | 31/31 PASS (28 existing + 3 new controller integration) |
| `run-translator-tests.mjs` | 40/40 PASS |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 33 files already formatted |
| `pytest -q` | 193 passed |

### Requirement Implementation Mapping

- **column-alignment/spec.md**: 5 requirements (write exclusivity, target semantics, cross-source realign, settle ownership, saved page restore) — all implemented in `alignment-controller.js` + `app.js`
- **dual-column-reading/spec.md**: page-aligned replacing proportional, realigning guard replacing setTimeout syncing — implemented via `realigning` flag guard and `getBoundingClientRect`-based offsetTop
- **page-zoom/spec.md**: zoom routes through `onZoomChange` instead of scroll event fallback — implemented in `zoom.js` + `alignment-controller.js`

### Design Decision Verification

| Decision | Status | Evidence |
|----------|--------|----------|
| D1 Write exclusivity | ✅ | grep test: only `alignment-controller.js` writes `.scrollTop` (zoom.js anchor allowed) |
| D2 Target semantics | ✅ | `(pageIndex, intraPageOffsetPx)` with `getBoundingClientRect`-based offsetTop |
| D3 Three-source convergence | ✅ | `onScroll`, `onImageLoaded`, `onZoomChange` all call `realign()` |
| D4 scroll-sync convergence | ✅ | `setupScrollSync` emptied, `createSettleGate`/`setupPageDetection` retained |
| D5 zoom geometric unity | ✅ | `handleWheel`/`resetZoom` call `alignmentController.onZoomChange(newZoom, oldZoom)` |
| D6 Translation image refresh | ✅ | `onFinish` → `loadPageImage(onLoadCallback)` → `onImageLoaded('right', page)` |
| D7 Saved page restore | ✅ | `scrollToPage` → `setLockTarget + realign()` (no `scrollIntoView`) |
| D8 Test entry | ✅ | `tests/run-alignment-controller-tests.mjs` + grep exclusivity test |

## Coherence

- No contradictions between delta specs and design doc
- Code follows project patterns (ES modules, jsdom test fixtures, `__TEST_*__` globals)
- `setupScrollSync` deprecated comment preserved for transitional clarity
- All 23 commits use `align-model-rewrite:` prefix

## Issues

### CRITICAL
None

### WARNING
None

### SUGGESTION
- `run-lazy-loader-tests.mjs` has a pre-existing `requestAnimationFrame` issue in jsdom (not caused by this change)
- Minor code style: `realigning` variable is closure-scoped while `state` object holds other mutable state (inconsistent layout, no functional impact)

## Impact Zone

| Area | Files | Changes |
|------|-------|---------|
| New module | `alignment-controller.js` (542 lines) | Core alignment logic |
| Modified module | `zoom.js` | `alignmentController` parameter + `onZoomChange` routing |
| Modified module | `scroll-sync.js` | `setupScrollSync` emptied, deprecation test added |
| Modified app | `app.js` | Controller assembly, `onImageLoaded` integration, `scrollToPage` refactor |
| New tests | `run-alignment-controller-tests.mjs`, `run-alignment-repro-tests.mjs` | Controller self-tests + bug reproduction |
| New fixtures | `__tests__/translation-misalign-fixture.js`, `__tests__/zoom-misalign-fixture.js` | Bug reproduction evidence |
| No backend changes | — | Zero Python modifications |

## Final Assessment

**All checks passed. Ready for archive.**
