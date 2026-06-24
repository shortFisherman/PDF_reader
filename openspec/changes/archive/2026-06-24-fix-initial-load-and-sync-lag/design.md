# Design: fix-initial-load-and-sync-lag

## Approach

### Fix 1: Initial Load via trigger()

Add a `trigger()` method to the settle gate (`createSettleGate` in `scroll-sync.js`) that immediately fires all registered `onSettle` callbacks synchronously (without starting the 150ms timer). Call `settle.trigger()` once after `setupIntersectionObserver` in `openPdf()` (`app.js`).

**Rationale:** The IO observer has already marked viewport containers as `pendingLoad` by the time `setupIntersectionObserver` returns. Calling `trigger()` immediately invokes the settle scan, which loads viewport ±BUF pages. Subsequent scrolls continue to use the normal settle gate timer. This is the minimal change — one new method, one new call site.

### Fix 2: Synchronous Scroll Sync with setTimeout(0) Unlock

Replace the `requestAnimationFrame` deferral in `setupScrollSync` with synchronous `scrollTop` assignment and `setTimeout(0)` to reset the `syncing` guard:

```
syncing = true;
dst.scrollTop = f * (dst.scrollHeight - dst.clientHeight);
setTimeout(() => { syncing = false; }, 0);
```

**Rationale:** Setting `scrollTop` synchronously eliminates the 1-frame visual lag. The programmatic `scrollTop` assignment queues a scroll event task; `setTimeout(0)` queues after that scroll event task, so the `syncing` guard remains true when the mirrored column's own scroll listener fires (breaks the feedback loop). Reading `scrollHeight` triggers one layout flush per scroll event, which is acceptable given scroll event frequency.

## Files Changed

| File | Change |
|------|--------|
| `static/modules/scroll-sync.js` | Add `trigger()` to `createSettleGate`; rewrite `setupScrollSync` to synchronous + `setTimeout(0)` |
| `static/app.js` | Add `settle.trigger()` call after IO setup |
| `openspec/specs/lazy-loading/spec.md` | Add acceptance scenario: initial load without scroll |
| `openspec/specs/dual-column-reading/spec.md` | Revise sync responsiveness requirement |

## Testing

- Existing 3 settle gate inline tests remain; add Test 4 verifying `trigger()` immediately invokes callbacks without 150ms wait.
- `setupScrollSync` has no existing inline tests and will remain untested at the unit level (depends on real scroll event dispatch order which is browser-specific).
- Manual regression: open PDF → pages load without scroll; drag scroll → no visible lag; fast drag → no feedback loop or jitter.
