# Task Group 3: zoom.js Module (tasks 3.1, 3.2, 3.3, 3.4)

Create the core zoom module. This is the most critical part of the `ctrl-wheel-zoom` feature.

## File to create
`static/modules/zoom.js` (new file)

## Requirements

### 3.1 — Module skeleton and setupZoom
```js
export function setupZoom({ columns, appEl, onZoomChange }) {
  const MIN = 0.25;
  const MAX = 4;
  const STEP = 0.1;
  let zoom = 1;
  
  // ... wheel handler (3.2)
  // ... anchor recalculation helper (3.3)
  
  // register wheel listeners
  for (const col of columns) {
    col.addEventListener('wheel', handler, { passive: false });
  }
  
  // return object
  return { resetZoom, getZoom, dispose };
}
```

### 3.2 — Wheel handler with Ctrl gating
```js
function handler(e) {
  if (!e.ctrlKey) return;              // pass through normal scroll
  
  e.preventDefault();
  const dir = Math.sign(e.deltaY);
  // deltaY > 0 (scroll down) → zoom out (decrease)
  // deltaY < 0 (scroll up)   → zoom in  (increase)
  const newZoom = Math.min(MAX, Math.max(MIN, zoom - dir * STEP));
  
  if (newZoom === zoom) return;        // at boundary, no change
  
  // ... apply anchor recalculation and set --zoom
}
```

### 3.3 — Mouse cursor anchor scroll recalculation
The active column is `e.currentTarget` (the DOM element the listener is attached to).

```js
const col = e.currentTarget;
const r = newZoom / zoom;
const rect = col.getBoundingClientRect();
const cx = e.clientX - rect.left;
const cy = e.clientY - rect.top;

// Step 1: Set CSS variable first (triggers reflow)
appEl.style.setProperty('--zoom', String(newZoom));

// Step 2: Adjust scroll position to keep cursor point stable
col.scrollTop  = (col.scrollTop  + cy) * r - cy;
col.scrollLeft = (col.scrollLeft + cx) * r - cx;

// Step 3: Update state and notify
zoom = newZoom;
onZoomChange(zoom);
```

### 3.4 — resetZoom, getZoom, dispose
```js
function resetZoom() {
  const col = columns[0];  // use first column as reference
  const r = 1 / zoom;
  const cx = col.clientWidth / 2;
  const cy = col.clientHeight / 2;
  
  appEl.style.setProperty('--zoom', '1');
  col.scrollTop  = (col.scrollTop  + cy) * r - cy;
  col.scrollLeft = (col.scrollLeft + cx) * r - cx;
  zoom = 1;
  onZoomChange(1);
}

function getZoom() {
  return zoom;
}

function dispose() {
  for (const col of columns) {
    col.removeEventListener('wheel', handler);
  }
}
```

## Existing patterns in the codebase
Other modules in `static/modules/` (e.g., `scroll-sync.js`, `stages.js`) export functions. Follow the same ES module pattern.

The project uses `setupXxx` naming convention (see `setupIntersectionObserver`, `setupScrollSync`, `setupPageDetection`).

## Key Behaviors
1. **Ctrl gating**: Non-Ctrl wheel events are NOT prevented — normal scrolling works unchanged.
2. **Direction**: Scroll wheel DOWN (positive deltaY) → zoom OUT (decrease). Scroll wheel UP (negative deltaY) → zoom IN (increase).
3. **Range**: 25% (0.25) to 400% (4), step 10% (0.1). Rolling beyond limits has no effect.
4. **Anchor point**: The content point under the cursor stays under the cursor after zoom.
5. **Scroll sync**: Only the active column's scroll is set directly. The existing `scroll-sync.js` automatically syncs the other column via scrollTop ratio.
6. **Reset**: Reset to 100% with viewport center as anchor (preserves current reading position).

## Validation
- Run `node tests/run-task-4.5-tests.mjs` and `npm run test:translator` to confirm no regressions
- Manually verify the module exports correctly (no syntax errors)

## Output
- Commit with message: `feat: add zoom module with Ctrl+wheel zoom (25%-400%) and cursor anchor`
- Write report to `openspec/changes/ctrl-wheel-zoom/.comet/task-3-report.md`
