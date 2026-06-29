# Task 1.1 Report — 翻译后失对齐复现红测试

## What was implemented

Two files were created to reproduce the translation misalignment bug in a jsdom test environment:

### 1. `static/modules/__tests__/translation-misalign-fixture.js`

A jsdom fixture that:
- Constructs two scroll columns (`#left-column`, `#right-column`) each with 4 `.page-container` elements
- Each page has a `.page-placeholder` with `--page-ratio: 150%` and `offsetHeight` = 450px
- Mocks `scrollHeight`, `clientHeight`, `offsetHeight`, and `getBoundingClientRect` for all relevant elements
- Sets up `setupScrollSync({ left, right })` from scroll-sync.js (proportional sync)
- Simulates the translation completion flow:
  - Both columns scroll to page 2 (scrollTop = 900px)
  - Right column page 2 gets its placeholder replaced with an `<img>` having `naturalHeight` = 448px (2px less)
  - Right column `scrollHeight` decreases from 1800px → 1798px
  - `getBoundingClientRect` is re-mocked to account for the new height
  - A scroll event is dispatched on the left column to trigger proportional sync
- Asserts the misalignment exists: `diff = |leftTop - rightTop| > 0` (PASSES, bug confirmed)
- Asserts expected correct behavior: `diff === 0` (FAILS — this is the RED assertion)

### 2. `tests/run-alignment-repro-tests.mjs`

A test runner following the pattern of `run-zoom-tests.mjs`:
- Creates a jsdom environment
- Loads `scroll-sync.js` and the fixture, strips `export` keywords, concatenates them
- Executes via `new Function()` in the jsdom window scope
- Sets `window.__TEST_ALIGN_REPRO_TRANSLATION__ = true`
- Captures console output, checks for `FAILED` / `FAIL:` to determine RED status
- Exits with code 1 (RED) when the bug is reproduced

## RED evidence

```
$ node tests/run-alignment-repro-tests.mjs

=== Test Output ===
FAIL: Expected: columns remain aligned after translation (got diff 1.7999999999999545px)
Left page 2 top: 0, Right page 2 top: 1.7999999999999545, Diff: 1.7999999999999545
2 passed, 1 FAILED

FAIL
```

Exit code: **1** (RED)

### Root cause confirmed

Proportional sync in `setupScrollSync` (scroll-sync.js:57-58):
```javascript
const vf = src.scrollTop / (src.scrollHeight - src.clientHeight);
dst.scrollTop = vf * (dst.scrollHeight - dst.clientHeight);
```

After the right column's page height decreases by 2px (scrollHeight 1800 → 1798):
- `vf = 900 / (1800 - 800) = 0.9`
- `right.scrollTop = 0.9 * (1798 - 800) = 0.9 * 998 = 898.2`
- Misalignment = `|900 - 898.2| = 1.8px` ✓ matches test output

## Files changed

| File | Change |
|------|--------|
| `static/modules/__tests__/translation-misalign-fixture.js` | Created (162 lines) |
| `tests/run-alignment-repro-tests.mjs` | Created (74 lines) |

## Commit

`b5d4c1d` — `align-model-rewrite: test(repro): translation misalignment reproduction fixture (RED)`

## Concerns

None. The test reproduces the bug precisely as described — a 2px height difference in a translated image causes proportional sync to produce ~1.8px of vertical misalignment between columns.
