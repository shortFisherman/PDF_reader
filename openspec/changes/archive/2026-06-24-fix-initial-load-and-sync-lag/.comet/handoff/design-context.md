# Comet Design Handoff

- Change: fix-initial-load-and-sync-lag
- Phase: design
- Mode: compact
- Context hash: 85b844394fc920ca2b82f959ab54e0711e214c950cac45a22bf9f6db0794309a

Generated-by: comet-handoff.sh

OpenSpec remains the canonical capability spec. This handoff is a deterministic, source-traceable context pack, not an agent-authored summary.

## openspec/changes/fix-initial-load-and-sync-lag/proposal.md

- Source: openspec/changes/fix-initial-load-and-sync-lag/proposal.md
- Lines: 1-24
- SHA256: ca8adb7e7f1ea9b3dbcadcc1b14944113c7f7cb73f30b6cef4e269f5a819a105

```md
# Proposal: fix-initial-load-and-sync-lag

## Motivation

The `fix-lazy-load-scroll` change introduced a settle gate (150ms debounce) that successfully eliminated scroll-induced request storms and load/unload oscillation. However, it introduced two regressions:

1. **Initial load regression**: After opening a PDF, the viewport pages never load until the user manually scrolls. The settle gate's timer fires only on scroll events, so without a scroll, `onSettle` callbacks (including the IO load scan) never execute. The IntersectionObserver correctly marks viewport containers as `pendingLoad`, but the actual `loadPageImage` call is deferred forever.
2. **Sync drag feel**: The dual-column proportional scroll sync uses `requestAnimationFrame` to defer the mirrored column's `scrollTop` assignment by one frame (~16ms). During continuous dragging, this creates a consistent 1-frame visual lag — the right column visibly trails the left column.

## Goals

1. Viewport pages load immediately when a PDF is opened (no scroll required).
2. Dual-column scroll sync feels instantaneous (no visible frame lag).

## Scope

- **In scope**: `static/modules/scroll-sync.js` (settle gate + scroll sync), `static/app.js` (setup call order), inline tests, delta specs for `lazy-loading` and `dual-column-reading`.
- **Out of scope**: Any changes to the lazy-loader IO observer logic, the settle gate debounce behavior during scrolling, translation flow, backend, or CSS.

## Non-goals

- Remove or reduce the settle gate debounce period.
- Change the BUF or RECLAIM_DISTANCE parameters.
- Add build tooling or TypeScript.
```

## openspec/changes/fix-initial-load-and-sync-lag/design.md

- Source: openspec/changes/fix-initial-load-and-sync-lag/design.md
- Lines: 1-36
- SHA256: e23d91089e45108341143eee7c2cb7d6188840e61811708a53ad0b5aba27a890

```md
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
```

## openspec/changes/fix-initial-load-and-sync-lag/tasks.md

- Source: openspec/changes/fix-initial-load-and-sync-lag/tasks.md
- Lines: 1-16
- SHA256: e10ba077201bf7a9f812adf6e1105b13f727dc063b34361d7ff68f3b4d20915c

```md
# Tasks: fix-initial-load-and-sync-lag

- [ ] Task 1: Add `trigger()` to settle gate and call it after IO setup
  - In `createSettleGate`, add `trigger()` method that immediately fires all `onSettle` callbacks synchronously
  - In `openPdf()`, call `settle.trigger()` after `setupIntersectionObserver({...})`
  - Files: `static/modules/scroll-sync.js`, `static/app.js`

- [ ] Task 2: Rewrite scroll sync to synchronous + setTimeout(0)
  - Replace `requestAnimationFrame` in `setupScrollSync` with synchronous `dst.scrollTop` assignment
  - Use `setTimeout(() => { syncing = false; }, 0)` to reset the syncing guard after the mirror's scroll event
  - File: `static/modules/scroll-sync.js`

- [ ] Task 3: Update inline tests and delta specs
  - Add Test 4 to settle gate inline tests: verify `trigger()` invokes callbacks immediately
  - Update `lazy-loading` delta spec: add acceptance scenario for initial load without scroll
  - Update `dual-column-reading` delta spec: revise sync behavior to reflect synchronous assignment
```

