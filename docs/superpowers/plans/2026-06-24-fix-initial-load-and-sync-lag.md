---
change: fix-initial-load-and-sync-lag
design-doc: docs/superpowers/specs/2026-06-24-fix-initial-load-and-sync-lag-design.md
base-ref: 81e95321222deb316c1d7e309b414ae2a456a126
archived-with: 2026-06-24-fix-initial-load-and-sync-lag
---

# Implementation Plan: Fix Initial Load and Scroll Sync Lag

## Overview

Two small, independent fixes in the frontend `scroll-sync.js` module with a one-line call in `app.js`. No new dependencies, no backend changes.

## Task 1: Add `trigger()` to settle gate and call it after IO setup

**Files:** `static/modules/scroll-sync.js`, `static/app.js`

**Steps:**
1. In `createSettleGate` return object, add `trigger` method that sets `settled = true` and executes all callbacks synchronously.
2. In `app.js:openPdf()`, after `setupIntersectionObserver({...})` line, add `settle.trigger();`.
3. Verify: navigate PDF reader app, open a PDF, viewport pages should load without manual scrolling.

**Commit:** `fix: add trigger() to settle gate for initial viewport load`

## Task 2: Rewrite scroll sync to synchronous + setTimeout(0)

**File:** `static/modules/scroll-sync.js`

**Steps:**
1. In `setupScrollSync`, replace the two per-side scroll listeners with a single `sync(src, dst)` helper.
2. Replace `requestAnimationFrame` with synchronous `dst.scrollTop` assignment.
3. Use `setTimeout(() => { syncing = false; }, 0)` to reset the guard.
4. Verify: drag left scrollbar → right column tracks immediately, no visible lag. Rapid scroll → no feedback loop oscillation.

**Commit:** `fix: replace rAF with synchronous scroll sync`

## Task 3: Update inline tests and delta specs

**Files:** `static/modules/scroll-sync.js`, `openspec/specs/lazy-loading/spec.md`, `openspec/specs/dual-column-reading/spec.md`

**Steps:**
1. Add Test 4 to `scroll-sync.js` inline settle gate tests: verify `trigger()` synchronously invokes callbacks without 150ms timer.
2. Update `lazy-loading/spec.md`: already done in design phase (immediate initial settle scan).
3. Update `dual-column-reading/spec.md`: already done in design phase (synchronous sync).
4. Verify: all 4 settle gate inline tests pass.

**Commit:** `test: add trigger() test; docs: update delta specs for sync behavior`

## Verification

- Run inline tests: `scroll-sync.js` settle gate tests (via dev server)
- Manual regression: open PDF → immediate load, smooth sync, no oscillation
