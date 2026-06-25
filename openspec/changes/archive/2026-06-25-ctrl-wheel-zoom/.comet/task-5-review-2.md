# Task Group 5 Re-Review: Zoom Unit Tests (Fix Verification)

## Fix Summary

The fix addresses both spec gaps identified in the first review (`task-5-review.md`). Only `static/modules/zoom.js` was modified (1 file, +34/-1 lines).

## Issue 1: Dispose Test — ✅ FIXED

**Original gap:** `instance.dispose()` was called with zero post-dispose assertions. Dead test code.

**Fix applied (3 changes that work together):**

1. `removeEventListener` mock now clears `wheelHandler = null` (line 81-83) — previously a no-op
2. `fireCtrlWheel` and `firePlainWheel` both guard with `if (!wheelHandler) return;` (lines 92, 105) — post-dispose events become no-ops
3. **4 post-dispose assertions** (Tests 11a-11d, lines 182-196):
   - Captures zoom/onZoomChange state before dispose
   - Fires wheel down (deltaY=100) and wheel up (deltaY=-100)
   - 11a: zoom unchanged after dispose (wheel down)
   - 11b: zoom unchanged after dispose (wheel up)
   - 11c: `onZoomChange` NOT called after dispose (changes array length frozen)
   - 11d: last recorded zoom value unchanged (belt and suspenders)

**Assessment:** The dispose test now properly verifies listener removal. The mock correctly models real DOM behavior (removeEventListener removes the handler; post-dispose events are silently ignored). The four assertions cover both zoom state and callback side effects.

## Issue 2: Anchor Formula — ✅ FIXED

**Original gap:** Anchor formula (scrollTop/scrollLeft recalculation from mouse position) had zero test coverage. The first implementation tested `--zoom` CSS side effects instead.

**Fix applied (Tests 10a-10c, lines 167-180):**
- Resets zoom, sets `col.scrollTop=200`, `col.scrollLeft=100`
- Overrides `getBoundingClientRect` → `{left:10, top:10, width:800, height:600, right:810, bottom:610}`
- Fires `Ctrl+wheel(deltaY=-100)` at `clientX=400, clientY=400`
- `cx = 400 - 10 = 390`, `cy = 400 - 10 = 390`
- zoom step formula: `newZoom = clamp(1 - (-1)*0.1, 0.25, 4) = 1.1` → `r = 1.1`
- `newScrollTop = (200 + 390) * 1.1 - 390 = 259` ✓
- `newScrollLeft = (100 + 390) * 1.1 - 390 = 149` ✓
- Tolerance: `<0.01` (more than sufficient for floating point)

**Assessment:** The anchor math is correctly verified with known values. The tolerance is appropriate. The test exercises the exact code path in `handleWheel` at line 20-21 of zoom.js.

## Test Results

```
=== Test Output ===
All 28 tests PASSED

PASS
```

28/28 assertions pass. Regression: translator 30/30 pass. (Lazy-loader and task-4.5 have pre-existing failures unrelated to zoom changes — `requestAnimationFrame` polyfill missing in JSDOM, and a padding assertion.)

## Optional Items from First Review (Unchanged)

| Item | Status | Notes |
|------|--------|-------|
| Gate `__ZOOM_TESTS_DONE__` behind `failCount === 0` | Not changed | Cosmetic; runner checks for `FAILED`/`FAIL:` in output text, exit codes are correct either way |
| Remove "=== Test Output ===" header | Not changed | Runner was not modified; harmless |

## Assertion Count Trace

| Tests | Assertions | Cumulative |
|-------|-----------|------------|
| 1a-1e (API shape) | 5 | 5 |
| 2a-2c (Ctrl+down) | 3 | 8 |
| 3a-3b (Ctrl+up) | 2 | 10 |
| 4a-4c (non-Ctrl gating) | 3 | 13 |
| 5a-5b (MIN clamp) | 2 | 15 |
| 6a-6b (MAX clamp) | 2 | 17 |
| 7a-7b (resetZoom) | 2 | 19 |
| 8 (onZoomChange on reset) | 1 | 20 |
| 9 (--zoom CSS) | 1 | 21 |
| **10a-10c (anchor formula)** ✨ | **3** | **24** |
| **11a-11d (dispose)** ✨ | **4** | **28** |

✨ = Added in this fix.

## Verdicts

| Dimension | Verdict |
|-----------|---------|
| Spec Compliance | **Spec ✅** |
| Code Quality | **Quality Approved** |

Both spec gaps are resolved. The dispose test is thorough (4 assertions covering zoom state and callback side effects). The anchor formula test verifies the scroll-position math with known values and appropriate tolerance. All 28 tests pass. No regression introduced.
