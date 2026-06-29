# Task 1.2 Report: Ctrl+滚轮失对齐复现红测试

## Status: COMPLETE (RED phase)

## Commits

N/A — committed by workflow, not manually.

## Files Created/Modified

### Created: `static/modules/__tests__/zoom-misalign-fixture.js`

A jsdom fixture that reproduces the Ctrl+wheel zoom misalignment bug:

- Left column: 4 pages, right column: 3 pages (different `scrollHeight`: 1800 vs 1350)
- Sets up `setupScrollSync` (proportional scroll sync) and `setupZoom` (zoom handler)
- Scrolls both columns to page 1.5 (offset 675px)
- Dispatches `WheelEvent` with `ctrlKey: true, deltaY: -100` on left column
- After zoom, dispatches `scroll` event on left column to trigger proportional sync
- Asserts that after zoom, same pageIndex `.page-container` top offsets differ

### Modified: `tests/run-alignment-repro-tests.mjs`

- Added second JSDOM instance for zoom test isolation
- Reads and strips exports from `zoom.js`
- Loads and executes `zoom-misalign-fixture.js`
- Sets `jsdomWindow.__TEST_ALIGN_REPRO_ZOOM__ = true`
- Checks `globalThis.__ALIGN_REPRO_ZOOM_DONE__` for exit code
- Reports results for both test suites independently

## Test Summary

```
=== Test 1: Translation Misalignment ===
FAIL: Expected: columns remain aligned after translation (got diff 1.8px)
2 passed, 1 FAILED
Test 1 result: FAIL (RED phase - expected)

=== Test 2: Zoom Misalignment ===
FAIL: Expected: columns remain aligned after zoom (got diff 347.625px)
left scrollTop=772.5, right scrollTop=424.875
vf=0.7725, expectedRightScrollTop=424.875
Left page 1 top=-322.5, Right page 1 top=25.125, Diff=347.625
8 passed, 1 FAILED
Test 2 result: FAIL (RED phase - expected)
```

### Zoom misalignment mechanism:
1. Ctrl+wheel on left column → `handleWheel` recalculates `leftCol.scrollTop` via anchor formula: `(675 + 300) × 1.1 - 300 = 772.5`
2. Setting `scrollTop` fires scroll event → `setupScrollSync.sync(left, right)` computes `vf = 772.5 / (1800 - 800) = 0.7725`
3. Right column gets `scrollTop = 0.7725 × (1350 - 800) = 424.875` (different from left's 772.5 due to scrollHeight mismatch)
4. Same pageIndex (page 1) has viewport top offsets of -322.5 (left) vs 25.125 (right) — diff = 347.625px

### Both tests RED — TDD RED phase confirmed.

## Concerns

None. Tests are reliable and the misalignment mechanism is well-understood.
