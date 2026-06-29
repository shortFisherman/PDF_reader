# Task 2.2 Report

## Status: COMPLETE

Tests (a)(b)(c) GREEN, test (d) remains RED (re-entrance guard, deferred to task 2.3).

## Commit Hash

`6d93b0e` — `align-model-rewrite: feat(task-2.2): implement currentTarget + setLockTarget + onScroll derivation + realign write`

## TDD Evidence

### RED Phase (before implementation)

```
=== Alignment Controller Tests ===
FAIL: Test a: target column scrollTop should change after realign (stayed at 0)
FAIL: Test b: getLockTarget should return a target object, got null
FAIL: Test b: target.pageIndex should be a number
FAIL: Test b: target.intraPageOffsetPx should be a number
FAIL: Test c: leftEl.scrollTop should be > 0 after realign (is 0)
FAIL: Test c: rightEl.scrollTop should be > 0 after realign (is 0)
FAIL: Test d: re-entrance guard missing — derivation called 1 time(s) during realign
2 passed, 7 FAILED
```

All 4 tests RED (7 assertion failures from (a)(b)(c)(d)).

### GREEN Phase (after implementation)

```
=== Alignment Controller Tests ===
FAIL: Test d: re-entrance guard missing — derivation called 1 time(s) during realign
8 passed, 1 FAILED
```

Tests (a)(b)(c) GREEN (8 assertions passed). Test (d) RED as expected (1 failure).

## Test Summary

| Test | Assertions | Status |
|------|-----------|--------|
| (a) Write exclusivity | leftEl.scrollTop unchanged, rightEl.scrollTop changed | GREEN (2/2) |
| (b) Target derivation | getLockTarget returns object with numeric pageIndex and intraPageOffsetPx | GREEN (3/3) |
| (c) Realign write | Both columns align to page 2 within 0.5px, both scrollTop > 0 | GREEN (3/3) |
| (d) Re-entrance guard | derivationCallsDuringRealign === 0 | RED (deferred to 2.3) |

## What Was Implemented

### State management (`static/modules/alignment-controller.js:2-4`)
- `state = { currentTarget: { pageIndex: 0, intraPageOffsetPx: 0 }, lockSide: null }`

### `setLockTarget(pageIndex, offsetPx)` (`:7-10`)
- Writes `state.currentTarget.pageIndex` and `state.currentTarget.intraPageOffsetPx`

### `getLockTarget()` (`:12-15`)
- Returns shallow copy `{ pageIndex, intraPageOffsetPx }` to prevent external mutation

### `onScroll(src)` (`:27-71`)
- Iterates `.page-container` elements in `src`, computes viewport coverage overlap
- Selects page with highest coverage ratio, deriving `pageIndex` from `dataset.page`
- Computes `intraOffset = src.scrollTop - pageContainerOffsetTop`
- If `intraOffset < 0`: normalizes by moving to previous page and adding the next page's `offsetHeight`
- Sets `state.lockSide` to `'left'` or `'right'` based on which column is scrolling
- Calls `realign(dst)` to sync the other column

### `realign(column)` (`:17-25`)
- Queries `column` for `.page-container[data-page="{currentTarget.pageIndex}"]`
- Computes `pageContainerOffsetTop` via `getBoundingClientRect` difference
- Writes `column.scrollTop = pageContainerOffsetTop + currentTarget.intraPageOffsetPx`

### `installScrollListeners()` (`:75-80`)
- Stores handler references for cleanup, adds `scroll` event listeners on `leftEl` and `rightEl`

### `dispose()` (`:82-89`)
- Removes `scroll` event listeners using stored handler references

### Test updates
- **Test (a)**: Added `page-container[data-page="0"]` to `rightEl` with mocked `getBoundingClientRect` so `realign(rightEl)` can compute a non-zero `scrollTop`
- **Test (b)**: No structural changes needed (works with existing mock page-containers)
- **Test (c)**: Added 5 `page-container` elements (200px each) to both `leftEl` and `rightEl` with mocked `getBoundingClientRect`, enabling `realign` to compute matching scroll positions on both columns
- **Test (d)**: Left unchanged (remains RED for task 2.3)

## Concerns

- ~~Test (b) `getBoundingClientRect` closures use `var` in the loop, causing all pages to report the same position (last iteration value).~~ **FIXED** — all `var` in test block reverted to `let`/`const`.
- ~~Test (c) has the same `var` scoping issue; all pages report `top: 800`.~~ **FIXED** — loop variables use `let`, each page gets correct per-iteration `pageTop`.
- `dispose()` relies on stored handler references; if `installScrollListeners()` was never called, `dispose()` is a no-op (safe).

---

## Task 2.2 Review Fix (Critical Defects)

### Status: COMPLETE

### Commit
Uncommitted (HEAD: `6d93b0e`). Diff: `static/modules/alignment-controller.js` (+41/−40).

### Fixes Applied

#### Critical 1: `var` → `let`/`const` regression (test block only)
All 15+ occurrences of `var` inside `__TEST_ALIGNMENT_CONTROLLER__` reverted to `let`/`const`:
- `var passCount` / `var failCount` → `let`
- `var pending` → `let`
- Loop counters (`var i`) → `let i` (restoring correct closure capture in for-loops)
- All element variables (`var leftEl`, `var page`, `var ctrl`, etc.) → `const`/`let` as appropriate
- `var pageTop` / `var visibleTop` in loops → `const` (now captured per-iteration)

#### Critical 2: Test (b) assertions changed from type-only to value checks
- Old: `typeof target.pageIndex === 'number'` (vacuously true on default `{pageIndex: 0}`)
- New: `target.pageIndex === 0` (verified — page 0 has most viewport coverage at scrollTop=350)
- Old: `typeof target.intraPageOffsetPx === 'number'` (vacuously true on `{intraPageOffsetPx: 0}`)
- New: `target.intraPageOffsetPx === 350`
- Also added `Object.defineProperty(page, 'offsetHeight', { value: 400, configurable: true })` — required because jsdom doesn't resolve `offsetHeight` from `style.height`, and the production `onScroll` reads `nextPage.offsetHeight` during intra-page normalization

#### Important 3: Test (c) assertions strengthened
- Old: `leftScroll > 0`, `rightScroll > 0` (weak)
- New: `leftScroll === 400`, `rightScroll === 400` (exact — page 2 offsetTop)
- Both columns produce the same scrollTop (400) because page positions are identical; the 30px scrollHeight difference doesn't affect individual page layout positions

### Test Evidence (post-fix)

```
=== Alignment Controller Tests ===
FAIL: Test d: re-entrance guard missing — derivation called 1 time(s) during realign
8 passed, 1 FAILED
```

| Test | Assertions | Status |
|------|-----------|--------|
| (a) Write exclusivity | leftEl unchanged, rightEl changed | GREEN (2/2) |
| (b) Target derivation | pageIndex=0, intraPageOffsetPx=350 | GREEN (3/3) |
| (c) Realign write | both scrollTops=400, diff<0.5px | GREEN (3/3) |
| (d) Re-entrance guard | derivationCallsDuringRealign=1 | RED (deferred) |

- Lint: `ruff check .` — All checks passed
- Format: `ruff format --check .` — 33 files already formatted
