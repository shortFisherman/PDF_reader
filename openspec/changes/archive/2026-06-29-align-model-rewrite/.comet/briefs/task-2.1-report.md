# Task 2.1 Report

## Status: DONE

## Commit
- `75d9e7d` — task-2.1: create empty AlignmentController + 4 RED self-tests

## Files Created
- `static/modules/alignment-controller.js` — factory function `createAlignmentController()` with 8 stubs + 4 self-tests
- `tests/run-alignment-controller-tests.mjs` — jsdom-based test runner

## Test Summary

`node tests/run-alignment-controller-tests.mjs` → **exit code 1 (RED)**

```
2 passed, 7 FAILED
```

| Test | Assertions | Result |
|------|-----------|--------|
| (a) Write exclusivity | leftEl unchanged ✓ / rightEl should change ✗ | RED |
| (b) Target derivation | getLockTarget returns null (expected non-null) ✗✗✗ | RED |
| (c) Realign write | both scrollTops are 0 (expected >0 + aligned) ✓✗✗ | RED |
| (d) Re-entrance guard | derivation called 1 time during realign (expected 0) ✗ | RED |

The 2 passes are:
- Test (a): leftEl.scrollTop remained 0 (correct behavior, trivial with stubs)
- Test (c): `Math.abs(0 - 0) < 0.5` (false positive — both zero, but the subsequent `> 0` assertions correctly fail)

## Concerns

- Test (d) re-entrance guard simulates the scroll event by calling `ctrl.onScroll(col)` after `realign` returns. This is sufficient for the RED phase but may need refinement in GREEN phase tasks (2.2-2.6) when the real `realign` sets/clears the `realigning` flag — the manual `onScroll` call happens after the guard is cleared. The test can be restructured in the GREEN phase if needed.
- All 4 test scenarios have at least 1 failing assertion, confirming the RED phase goal.
