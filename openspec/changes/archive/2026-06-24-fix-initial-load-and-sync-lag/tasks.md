# Tasks: fix-initial-load-and-sync-lag

- [x] Task 1: Add `trigger()` to settle gate and call it after IO setup
  - In `createSettleGate`, add `trigger()` method that immediately fires all `onSettle` callbacks synchronously
  - In `openPdf()`, call `settle.trigger()` after `setupIntersectionObserver({...})`
  - Files: `static/modules/scroll-sync.js`, `static/app.js`
  - Commits: b44de55, dfd45cf

- [x] Task 2: Rewrite scroll sync to synchronous + setTimeout(0)
  - Replace `requestAnimationFrame` in `setupScrollSync` with synchronous `dst.scrollTop` assignment
  - Use `setTimeout(() => { syncing = false; }, 0)` to reset the syncing guard after the mirror's scroll event
  - File: `static/modules/scroll-sync.js`
  - Commits: 2c7c123

- [x] Task 3: Update inline tests and delta specs
  - Add Test 4 to settle gate inline tests: verify `trigger()` invokes callbacks immediately
  - Update `lazy-loading` delta spec: add acceptance scenario for initial load without scroll
  - Update `dual-column-reading` delta spec: revise sync behavior to reflect synchronous assignment
  - Commits: 3b4b8a2
