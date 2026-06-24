---
comet_change: fix-initial-load-and-sync-lag
role: technical-design
canonical_spec: openspec
archived-with: 2026-06-24-fix-initial-load-and-sync-lag
status: final
---

# Technical Design: Fix Initial Load and Scroll Sync Lag

## Problem

The `fix-lazy-load-scroll` change introduced a settle gate (150ms debounce on scroll events) that successfully eliminated request storms and load/unload oscillation. However, two regressions emerged:

1. **Initial load deadlock**: The settle gate timer fires only on `scroll` events. When a PDF is first opened, no scroll occurs → `onSettle` callbacks never execute → the intersection observer's `pendingLoad` candidates (correctly marked by IO initial entries) are never scanned → viewport pages never load until the user manually scrolls.
2. **Sync drag feel**: `setupScrollSync` uses `requestAnimationFrame` to defer the mirrored column's `scrollTop` assignment by one frame (~16ms). During continuous dragging, this produces a consistent 1-frame visual lag — the right column visibly trails the left.

## Solution

### Fix 1: Immediate Initial Settle Scan

Add a `trigger()` method on the settle gate (`createSettleGate` in `scroll-sync.js`) that synchronously fires all registered `onSettle` callbacks without starting the 150ms timer. Call `settle.trigger()` once in `openPdf()` after `setupIntersectionObserver`.

```javascript
// createSettleGate return object gains:
trigger() {
    settled = true;
    const cbs = [...callbacks];
    cbs.forEach(cb => cb());
}
```

The IO observer's `observe()` call during setup immediately produces entries for viewport containers, marking them in `pendingLoad`. Calling `trigger()` immediately invokes the settle scan, which loads viewport ±BUF pages. Subsequent scrolls continue to use the normal settle gate timer (`reset()` → 150ms debounce). `trigger()` sets `settled = true`; if the user scrolls thereafter, `reset()` runs normally (sets `settled = false`, starts timer).

### Fix 2: Synchronous Scroll Sync with setTimeout(0) Guard

Replace `requestAnimationFrame` deferral in `setupScrollSync` with synchronous `scrollTop` assignment and `setTimeout(0)` to reset the `syncing` guard:

```javascript
function sync(src, dst) {
    if (syncing) return;
    const f = src.scrollHeight <= src.clientHeight ? 0
        : src.scrollTop / (src.scrollHeight - src.clientHeight);
    syncing = true;
    dst.scrollTop = f * (dst.scrollHeight - dst.clientHeight);
    setTimeout(() => { syncing = false; }, 0);
}
```

**Event ordering guarantees the feedback loop break:**

1. `dst.scrollTop = ...` executes → browser queues a scroll event task on `dst`
2. `setTimeout(0)` queues after that scroll event task
3. The scroll event task runs first → `syncing === true` → handler returns (loop blocked)
4. The setTimeout task runs → `syncing = false` → unlocked for next scroll

This ordering relies on W3C-standard asynchronous scroll event dispatch from programmatic `scrollTop` assignment — a behavior consistent across all modern browsers (Chrome, Firefox, Safari, Edge).

**Layout impact:** One read of `scrollHeight`/`clientHeight` per event, one write of `scrollTop`. Single layout flush per scroll event at ~60 events/s — well within acceptable bounds.

## Files Changed

| File | Change |
|------|--------|
| `static/modules/scroll-sync.js` | Add `trigger()` to `createSettleGate`; rewrite `setupScrollSync` synchronous + `setTimeout(0)`; add Test 4 |
| `static/app.js` | Add `settle.trigger()` call after IO setup |
| `openspec/specs/lazy-loading/spec.md` | Add requirement: initial settle scan without scroll; tighten Initial page load scenario |
| `openspec/specs/dual-column-reading/spec.md` | Replace rAF throttling with synchronous assignment + setTimeout(0) guard |

## Testing

### Unit

- settle gate inline tests: existing 3 pass, new Test 4 verifies `trigger()` immediately invokes callbacks without 150ms wait and without resetting the timer.

### Manual Regression

| # | Scenario | Expected Result |
|---|----------|----------------|
| 1 | Open PDF, do not scroll | Viewport ±2 pages load immediately |
| 2 | Drag left scrollbar continuously | Right column tracks synchronously, no visible lag |
| 3 | Rapidly scroll left then right | No feedback loop oscillation, no jitter |
| 4 | Long-distance scrollbar jump (page 1→500) | No request storm; only landing viewport pages load after settle |

## Risks

- **scroll event task ordering (low):** All target browsers dispatch programmatic `scrollTop` events asynchronously per spec. No browser-specific workaround needed.
- **No regression in settle gate behavior:** `trigger()` is additive; `reset()` and `dispose()` unchanged. Existing settle gate tests continue to pass.
