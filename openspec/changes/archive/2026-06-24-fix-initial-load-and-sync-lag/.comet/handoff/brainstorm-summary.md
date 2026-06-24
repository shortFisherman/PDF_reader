# Brainstorm Summary

- Change: fix-initial-load-and-sync-lag
- Date: 2026-06-24

## Confirmed Technical Approach

**Issue 1 (initial load):** Add `trigger()` to `createSettleGate` in `scroll-sync.js` — synchronously fires all `onSettle` callbacks without starting the 150ms timer. Call `settle.trigger()` once in `openPdf()` after `setupIntersectionObserver`. IO observer already has initial entries in `pendingLoad` at that point; trigger immediately scans and loads viewport ±BUF pages.

**Issue 2 (sync lag):** Replace `requestAnimationFrame` deferral in `setupScrollSync` with synchronous `dst.scrollTop` assignment + `setTimeout(0)` to reset syncing guard. Synchronous assignment eliminates 1-frame visual lag. setTimeout(0) queues after the mirror column's queued scroll event task, so `syncing=true` blocks the re-entry loop, then unlocks.

## Key Trade-offs and Risks

- **Risk (low):** Programmatic scrollTop → scroll event task ordering. W3C spec mandates asynchronous dispatch. All modern browsers (Chrome/Firefox/Safari/Edge) follow this. No fallback needed.
- **No layout thrash:** One read of scrollHeight per event, one write of scrollTop. Single layout flush per event, acceptable at scroll event frequency.
- **Settle state after trigger():** trigger() sets `settled=true`. If user scrolls before next settle window, `reset()` runs normally (sets `settled=false`, starts timer). No behavioral conflict.

## Testing Strategy

- Unit: Add Test 4 to settle gate inline tests (verify trigger() immediately invokes callbacks). setupScrollSync has no unit tests (depends on real scroll event dispatch order).
- Manual regression: 4 scenarios — initial load without scroll, drag sync no lag, fast drag no feedback loop, long jump no request storm.

## Spec Patches

- `lazy-loading`: Add acceptance scenario — "When a PDF is opened, viewport pages load immediately without requiring a scroll event"
- `dual-column-reading`: Revise sync timing requirement — "The mirrored column scrollTop is set synchronously within the source scroll event handler" (replaces implicit rAF deferral)
