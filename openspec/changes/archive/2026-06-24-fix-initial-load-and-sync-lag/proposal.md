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
