# Task Group 5 Review: Zoom Unit Tests

## 1. Spec Compliance

### Checklist

| #   | Requirement                                                                 | Status | Notes |
|-----|-----------------------------------------------------------------------------|--------|-------|
| 1   | zoom.js has inline test block at end, guarded by window.__TEST_ZOOM__ | ✅     | Line 57+; guard and RED-phase check present |
| 2   | tests/run-zoom-tests.mjs created, follows run-lazy-loader-tests.mjs pattern | ✅     | Structurally identical: JSDOM, export stripping, new Function, done-flag check |
| 3   | Test runner uses JSDOM, strips export keywords                              | ✅     | Same 5-regex export-strip block as lazy-loader runner |
| 4   | Test runner sets __TEST_ZOOM__=true, checks __ZOOM_TESTS_DONE__             | ✅     | Set on jsdomWindow; checks globalThis flag + text for FAILED/FAIL: |
| 5   | package.json has "test:zoom" script                                         | ✅     | "test:zoom": "node tests/run-zoom-tests.mjs" added |
| 6   | Tests cover: Ctrl gating                                                    | ✅     | Tests 4a-4c: non-Ctrl wheel -> no zoom change, no preventDefault, no onZoomChange |
| 7   | Tests cover: direction (up/down)                                            | ✅     | Tests 2a-2c (down), 3a-3b (up) |
| 8   | Tests cover: range clamp (0.25-4)                                           | ✅     | Tests 5a-5b (MIN), 6a-6b (MAX) |
| 9   | Tests cover: boundary no-op                                                 | ✅     | Test 5b: zoom stays at MIN; Test 6b: zoom stays at MAX |
| 10  | Tests cover: reset to 1                                                     | ✅     | Tests 7a-7b: resetZoom returns to 1, sets --zoom CSS |
| 11  | Tests cover: dispose removes listener                                       | ❌     | **MISSING.** instance.dispose() called but NO post-dispose assertion |
| 12  | Tests cover: anchor formula                                                 | ❌     | **MISSING.** Brief Test 8 requires scrollTop/scrollLeft anchor math verification |
| 13  | RED/GREEN evidence: 21/21 zoom pass, translator 30/30 no regression         | ⚠️     | Not verified in review; 21 assertions present but different from spec |
| 14  | Only 3 files modified: zoom.js, run-zoom-tests.mjs, package.json            | ✅     | Diff confirms exactly 3 files |

### Missing Spec Coverage Detail

**Item 11 -- dispose:** The brief (lines 115-121) specifies a post-dispose verification: after calling dispose(), fire a Ctrl+wheel event and assert zoom is unchanged (proving the listener was removed). The implementation calls instance.dispose() inside the try block but has zero assertions after it. The dispose call is dead test code.

**Item 12 -- anchor formula:** The brief (lines 85-113) specifies a detailed anchor-math verification with a known scrollTop (~259) / scrollLeft (~149) calculation. The implementation omits this entirely, replacing it with CSS property side-effect checks (Test 7b: --zoom on reset, Test 9: --zoom on wheel) which do not exercise the scroll-position anchor formula at all.

**Assertion mapping (brief vs actual):**

| Brief Assertions (21) | Actual Assertions (21) | Match? |
|-----------------------|----------------------|--------|
| API shape (resetZoom, getZoom, dispose, initial=1) | Tests 1a-1e (5 assertions: + onZoomChange count) | Approximate |
| Non-Ctrl: no preventDefault, no zoom change, no onZoomChange | Tests 4a-4c | OK |
| Ctrl+down: preventDefault, zoom decrease | Tests 2a-2c (+ onZoomChange count) | OK |
| Ctrl+up: preventDefault, zoom increase | Tests 3a-3b | OK |
| Clamp to MIN 0.25 + boundary no-op | Tests 5a-5b | OK |
| Clamp to MAX 4 | Tests 6a-6b (+ boundary no-op) | OK |
| resetZoom to 1, onZoomChange called | Tests 7a-7b, Test 8 | OK |
| Anchor formula (scrollTop~259, scrollLeft~149, zoom=1.1, onZoomChange=1.1) | Test 7b (--zoom CSS), Test 9 (--zoom CSS) | **DIVERGES** |
| Dispose: listener removed, zoom unchanged | NO ASSERTION | **MISSING** |

The implementation has 21 assertions (same count), but the anchor formula test is replaced and dispose is unverified.

### Verdict: Spec ❌

Two required test categories (dispose verification and anchor formula) are missing. The inline test block is present, the runner is created, and 11 of 14 checklist items pass, but the missing coverage is substantive.

---

## 2. Code Quality

### Strengths
- **Mocking approach is superior to the brief.** Intercepting addEventListener and constructing plain event-like objects for fireCtrlWheel/firePlainWheel avoids JSDOM WheelEvent compatibility issues. The brief's approach of using new WheelEvent() + Object.defineProperty for preventDefault is fragile in JSDOM.
- **Inline test block structure matches the lazy-loader.js pattern exactly.** The RED-phase guard (typeof setupZoom check), assert() helper, passCount/failCount, and done-flag logic all follow the established convention.
- **Test runner follows the lazy-loader runner pattern.** Same JSDOM setup, export stripping, new Function execution, error collection, and done-flag+text-based exit code logic.
- **Test assertions are meaningful.** Each assertion has a descriptive message, enabling quick identification of failures.
- **21 assertions provide good breadth.** Coverage spans API shape, Ctrl gating, zoom direction, range clamping, boundary behavior, reset, and CSS side effects.

### Issues

1. **Dispose has no assertion (dead test code).**
   `instance.dispose()` is called on the last line of the try block. No assertion follows. If dispose is broken (e.g., removeEventListener calls the wrong handler), 21/21 tests still pass.

   Fix: Append:
   ```js
   const zBeforeDisp = instance.getZoom();
   const pdBeforeDisp = preventDefaultCalls;
   fireCtrlWheel(-100);
   assert(instance.getZoom() === zBeforeDisp, 'dispose removed listener, zoom unchanged');
   assert(preventDefaultCalls === pdBeforeDisp, 'dispose removed listener, preventDefault not called');
   ```

2. **Anchor formula is untested.**
   The scroll-position anchor math (newScrollTop/newScrollLeft based on mouse position, column scroll state, and zoom ratio) is the trickiest part of handleWheel. It has zero test coverage. The brief specified it explicitly. The implemented --zoom CSS checks are useful but cover a different code path.

3. **__ZOOM_TESTS_DONE__ set unconditionally.**
   The flag is set to true regardless of pass/fail. The runner compensates by also checking text output for FAILED/FAIL:, so exit codes are still correct. However, this diverges from the lazy-loader convention where the done flag is only set on success (visible intent: "all tests done and passed"). In practice both work, but it is a slight semantic deviation.

4. **Minor: verbose runner output.**
   The runner prints "=== Test Output ===" header which the lazy-loader runner does not. Harmless, but unnecessary.

### Verdict: Quality Approved

The core testing infrastructure is solid and follows project conventions. The two missing spec items (dispose verification, anchor formula) are spec-compliance issues rather than quality defects in the code that exists. The code that IS present is well-structured, uses an appropriate mocking strategy, and would correctly report failures if any assertions fail.

---

## Overall Verdict

| Dimension       | Verdict            |
|-----------------|--------------------|
| Spec Compliance | **Spec ❌**        |
| Code Quality    | **Quality Approved** |

### Required Actions

1. **Add dispose verification:** Two assertions after `instance.dispose()` to confirm the wheel listener is actually removed.
2. **Add anchor formula test:** Either:
   - Implement the brief's scrollTop/scrollLeft numeric verification (preferred), or
   - Document why it was omitted and ensure the brief is updated to match.

### Optional
- Gate `__ZOOM_TESTS_DONE__` behind `failCount === 0` for consistency with the lazy-loader intent (cosmetic).
- Remove the "=== Test Output ===" header or add it to the lazy-loader runner for consistency across all runners.
