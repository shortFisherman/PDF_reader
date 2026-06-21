---
comet_change: modularize-frontend
role: technical-design
canonical_spec: openspec
status: final
archived-with: 2026-06-21-modularize-frontend
status: final
---

# Design: Modularize Frontend

## Problem

`static/app.js` is a 335-line single file loaded via `<script src="/static/app.js" defer>`, containing 5 interleaved responsibilities: DOM reference and element creation, SSE stream reading, scroll synchronization, IntersectionObserver lazy loading, and translation orchestration with progress UI. `STAGE_LABELS` is defined identically in both `sse_stream.py:16-22` (backend, dead code) and `app.js:10-16` (frontend, the copy actually consumed), creating a maintenance duplication risk. The frontend has no tests and is difficult to extend independently.

Constraints: frontend UX must remain byte-identical; no build tools (the project has no bundler); browser compatibility must be maintained.

## Architecture: ES Module Split

```
static/
├── app.js              (entry, ~60 lines)
└── modules/
    ├── dom.js           (DOM refs, createPageEl, calculatePlaceholderHeight)
    ├── sse-client.js    (readSSEStream — pure SSE parsing, no DOM)
    ├── scroll-sync.js   (setupScrollSync, setupPageDetection)
    ├── lazy-loader.js   (setupIntersectionObserver)
    ├── stages.js        (fetchStageLabels, getStageLabel)
    └── translator.js    (translateCurrentPage — DOM-free, callback-driven)
```

**`index.html` change**: `<script src="/static/app.js" defer>` → `<script type="module" src="/static/app.js">`

### Module Interfaces

**State ownership**: `app.js` holds all shared mutable state (`pageCount`, `pageHeight`, `pageWidth`, `currentPage`, `isTranslating`, `promptVisible`, `statusTimer`) as `let` variables defined at module scope. Modules are stateless utilities; state flows in as parameters and out as callbacks.

**`dom.js`**: Exports `getElements()` returning a frozen object of DOM element references, `createPageEl(pageNum, side)` returning the created `HTMLElement`, and `calculatePlaceholderHeight(pageWidth, pageHeight)` returning an aspect-ratio CSS string.

**`sse-client.js`**: Exports `readSSEStream(response, onEvent)` — a pure function that reads a `ReadableStream` with `getReader()`, splits on `\n\n`, parses `data: {json}` lines, and calls `onEvent(parsed)`. No DOM access, no side effects.

**`scroll-sync.js`**: Exports `setupScrollSync({ left, right })` using `requestAnimationFrame` to synchronize `scrollTop`, and `setupPageDetection({ left }, onPageChange)` using `IntersectionObserver` with per-page thresholds, calling `onPageChange(pageNum)` when the visible page changes.

**`lazy-loader.js`**: Exports `setupIntersectionObserver(container, { load, unload })` that creates a single `IntersectionObserver` with a 5-page-height `rootMargin`, calling the provided `load(container)` / `unload(container)` callbacks.

**`stages.js`**: Exports `fetchStageLabels()` that `fetch`es `GET /api/stages`, caches the result in a module-scoped variable, and returns it. On failure, falls back to a minimal built-in copy with `console.warn`. Also exports `getStageLabel(stage)` for synchronous label lookup.

**`translator.js`**: Exports `translateCurrentPage(page, callbacks)` where `callbacks` is `{ onStageChange(stage), onProgress(pagesCompleted, pagesTotal), onFinish(), onError(error) }`. Internally calls `fetch('/api/translate/' + page)` and pipes the response through `readSSEStream`. No DOM access — pure orchestration.

### app.js Entry

```js
import { getElements, createPageEl, calculatePlaceholderHeight } from './modules/dom.js';
import { readSSEStream } from './modules/sse-client.js';
import { setupScrollSync, setupPageDetection } from './modules/scroll-sync.js';
import { setupIntersectionObserver } from './modules/lazy-loader.js';
import { fetchStageLabels, getStageLabel } from './modules/stages.js';
import { translateCurrentPage } from './modules/translator.js';

// All shared state lives here
let pageCount, pageHeight, pageWidth, currentPage;
let isTranslating = false;
let promptVisible = false;
let statusTimer = null;
const API = '/api';

// On DOMContentLoaded (auto-deferred by type="module"):
// 1. fetchStageLabels() — cache stage labels
// 2. Bind #open-btn, #prompt-toggle, #translate-btn event listeners
// 3. openPdf() → getElements(), createPageEl(), setupIntersectionObserver(), setupScrollSync(), setupPageDetection()
// 4. translateCurrentPage(page, callbacks) → callbacks update DOM via getElements()
```

## Stage Labels: Single Source of Truth

**Backend**: Add `GET /api/stages` in `routes.py`:

```python
from sse_stream import STAGE_LABELS

@bp.route('/api/stages')
def get_stages():
    return jsonify(STAGE_LABELS)
```

The `STAGE_LABELS` definition in `sse_stream.py` becomes the single authoritative copy. Add a test in `test_routes.py` verifying the endpoint returns all 5 stage keys with Chinese labels as JSON.

**Frontend**: `stages.js` fetches on startup and caches. `translator.js` calls `getStageLabel(stage)` for progress display. The hardcoded `STAGE_LABELS` in `app.js` is deleted.

## Testing Strategy

- **Backend**: `pytest tests/` — add `test_routes.py` case for `GET /api/stages` returning correct JSON
- **Frontend manual**: `docs/manual-verification-checklist.md` covering 9 behaviors: dual-column rendering, scroll sync, independent right-column scroll, page detection, lazy loading (5-page buffer), off-screen unloading, translation progress per stage, prompt toggle, error display
- **Optional**: `sse-client.js` pure function test — parse `data:` lines from a mocked `ReadableStream` and verify `onEvent` receives correct parsed objects

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `type="module"` compatibility | All modern browsers (Chrome 61+, Firefox 60+, Safari 11+, Edge 79+) support ES Modules; project target supports this |
| `/api/stages` fetch failure | `stages.js` falls back to built-in minimal copy + `console.warn`; translation flow is not blocked |
| Module load order | ES Module `import` declaratively resolves the dependency graph; no manual ordering needed |
| No automated frontend tests | 9-item manual verification checklist covers all critical behaviors; `sse-client.js` is pure and easily unit-tested |
| `static/modules/` CORS | Same-origin static resources; no CORS issues |

## Implementation Order

1. Behavioral baseline — write checklist, manually walk through current behavior
2. Backend `/api/stages` — add endpoint + test
3. Extract modules bottom-up: `dom.js` → `lazy-loader.js` → `scroll-sync.js` → `stages.js` → `sse-client.js` → `translator.js`
4. Rewrite `app.js` as thin entry, update `index.html` script tag
5. Full regression: `pytest tests/ -v`, `ruff check`, grep confirm no frontend `STAGE_LABELS` duplicate
