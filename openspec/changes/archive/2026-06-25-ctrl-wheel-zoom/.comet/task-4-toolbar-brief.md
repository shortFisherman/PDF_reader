# Task Group 4: Toolbar Zoom Controls and Integration (tasks 4.1, 4.2, 4.3, 4.4)

Wire the zoom module into the app — add toolbar UI elements, DOM references, and app integration.

## 4.1 — index.html toolbar elements
In `templates/index.html`, add two elements to `#toolbar` between `#page-indicator` and `#prompt-toggle`:
```html
<span id="zoom-level">100%</span>
<button id="zoom-reset">重置缩放</button>
```

Current toolbar (line 22-28):
```html
<div id="toolbar" class="hidden">
    <span class="page-indicator" id="page-indicator">Page --</span>
    <button id="prompt-toggle">+ Prompt</button>
    <input type="text" id="prompt-input" placeholder="Custom prompt..." style="display:none">
    <div id="progress-bar"><div id="progress-track"><div id="progress-fill"></div></div><span id="progress-status-text"></span></div>
    <button id="translate-btn">Translate</button>
</div>
```

Desired result:
```html
<div id="toolbar" class="hidden">
    <span class="page-indicator" id="page-indicator">Page --</span>
    <span id="zoom-level">100%</span>
    <button id="zoom-reset">重置缩放</button>
    <button id="prompt-toggle">+ Prompt</button>
    <input type="text" id="prompt-input" placeholder="Custom prompt..." style="display:none">
    <div id="progress-bar"><div id="progress-track"><div id="progress-fill"></div></div><span id="progress-status-text"></span></div>
    <button id="translate-btn">Translate</button>
</div>
```

## 4.2 — dom.js getElements
In `static/modules/dom.js`, add two new element references:
1. After line 8 (`pageIndicator`): add `const zoomLevel = document.getElementById('zoom-level');`
2. After the above: add `const zoomReset = document.getElementById('zoom-reset');`
3. Add `zoomLevel` and `zoomReset` to the `_cache` object

## 4.3 — app.js setupZoom integration
In `static/app.js`:

1. Add import at top (after existing imports):
   ```js
   import { setupZoom } from './modules/zoom.js';
   ```

2. Add module-level variable near other state variables (line 16-ish):
   ```js
   let zoomInst = null;
   ```

3. In `openPdf`, after setting up scroll sync and page detection (after line 87 `setupPageDetection(...)`), call:
   ```js
   zoomInst = setupZoom({
       columns: [els.leftCol, els.rightCol],
       appEl: els.appView,
       onZoomChange: z => { els.zoomLevel.textContent = Math.round(z * 100) + '%'; }
   });
   els.zoomLevel.textContent = '100%';
   ```

## 4.4 — app.js resetZoom binding and cleanup
In `static/app.js`:

1. In `init()`, add the reset button click handler:
   ```js
   els.zoomReset.addEventListener('click', () => {
       if (zoomInst) zoomInst.resetZoom();
   });
   ```

2. In `openPdf`, at the top cleanup section (line 38-39, where `io` and `settle` are disposed):
   ```js
   if (zoomInst) { zoomInst.dispose(); zoomInst = null; }
   ```

## Files to modify
- `templates/index.html`
- `static/modules/dom.js`
- `static/app.js`

## Validation
- Run `npm run test:translator` — 30 tests should pass
- Run `node tests/run-task-4.5-tests.mjs` — no regression

## Output
- Commit with message: `feat: add toolbar zoom controls and integrate zoom module with app`
- Write report to `openspec/changes/ctrl-wheel-zoom/.comet/task-4-report.md`
