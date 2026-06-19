# Bilingual PDF Reader — Design Document

## Overview

A dual-column PDF reading interface for English textbooks: left side shows original pages, right side shows translated pages. Translation is triggered manually per page via a floating toolbar, using pdf2zh-next (BabelDOC engine) with DeepSeek API. Supports custom prompts per translation, CSV-based glossary, and translation persistence across sessions.

## Architecture

```
Browser (HTML/CSS/JS)
  ├── index.html: dual-column layout
  │   ├── Left column: original PDF pages as <img> tags
  │   ├── Right column: translated PDF pages as <img> tags
  │   └── Floating toolbar: page indicator, translate button, prompt input
  └── IntersectionObserver: lazy-load images within 5-page buffer

Flask Backend (app.py)
  ├── POST /api/open       — Open PDF, compute SHA256, init right.pdf
  ├── GET  /api/page/:side/:page — Render page as PNG (200 DPI)
  ├── POST /api/translate/:page   — Translate page via pdf2zh-next, SSE progress
  ├── GET  /api/page-count/:side  — Return left/right page count
  └── GET  /api/translated-pages  — Return list of translated page numbers

pdf2zh-next (BabelDOC engine)
  └── do_translate_async_stream() with DeepSeekSettings
```

## Decisions

### D1: Server-side PNG rendering (not PDF.js)

pymupdf renders each page as 200 DPI PNG (~1600x2300 px), served as `<img>` tags.

- Two `<div>` columns with `scrollTop` synchronization is trivial
- PDF.js dual-instance scroll sync is complex and fragile
- pymupdf uses MuPDF engine — visually identical to native readers

### D2: Translation via pdf2zh-next (not v1, not BabelDOC direct)

pdf2zh-next wraps BabelDOC's pipeline (custom PDF parser, Document IL, LLM batch JSON mode, cross-page paragraph detection) with a stable public API.

- Built-in SQLite cache, subprocess crash isolation, structured progress events
- `only_include_translated_page` + `ignore_cache` flags support per-page re-translation

### D3: SHA256-hashed right.pdf for persistence (not database)

On first open, copy original PDF to `cache/<sha256>/right.pdf`. Translated pages replace corresponding pages via pymupdf. SHA256 match restores state on reopen.

- right.pdf IS the state — no database, no version tracking needed
- Full rewrite save (not incremental) prevents file fragmentation
- Different PDF hashes → separate caches (correct behavior for different editions)

### D4: CSV glossary via BabelDOC Hyperscan matching

`glossary.csv` with `source,target` columns passed to pdf2zh-next's `TranslationSettings.glossaries`. BabelDOC handles Hyperscan matching and LLM prompt injection.

### D5: Vanilla frontend (no framework)

Single `templates/index.html` with inline JS. No build step, no bundler, no npm.

### D6: IntersectionObserver for lazy loading

Each page is a `<div>` with placeholder. IntersectionObserver detects viewport proximity and loads `<img>`. Buffer of ±5 pages maintained.

## Component Design

### Backend (app.py)

| Component | Responsibility |
|-----------|---------------|
| `state` dict | In-memory session: left_doc, right_doc, page_count, translated_pages |
| `_sha256()` | File hash for cache key |
| `_render_page()` | Renders single page to PNG bytes via pymupdf |
| `_build_settings()` | Constructs pdf2zh-next SettingsModel from config |
| `_replace_page_in_right_pdf()` | Replaces page in right.pdf with translated output |

### Frontend (index.html)

| Component | Responsibility |
|-----------|---------------|
| Left/right columns | `<div>` with vertically stacked `<img>` per page |
| `scroll` handler | `requestAnimationFrame` syncs right column to left |
| IntersectionObserver | Lazy-loads images within viewport buffer |
| Floating toolbar | Fixed position, shows current page + translate controls |
| SSE consumer | Receives progress events for translation progress bar |

### Translation Flow

```
User clicks "Translate"
  → Extract page N from left_doc as temp single-page PDF
  → Build SettingsModel with DeepSeekSettings, glossary, custom prompt
  → call do_translate_async_stream() in background thread
  → SSE relay: progress_start → progress_update → finish → page replacement
  → Replace page N in right.pdf with translated output
  → Frontend refreshes right-column image for page N
```

### Persistence Flow

```
POST /open {path: "C:/doc.pdf"}
  → SHA256 of file content
  → cache/<sha256>/ directory (create if not exists)
  → If right.pdf missing: copy original as right.pdf
  → If right.pdf exists: open it as right_doc (restores prior translations)
  → Return page_count, dimensions, hash
```

## Data Model

### State (in-memory, per Flask process)

```
state = {
    pdf_path: str | None,
    pdf_hash: str | None,
    left_doc: pymupdf.Document | None,
    right_doc: pymupdf.Document | None,
    right_pdf_path: str | None,
    page_count: int,
    page_height: float,
    page_width: float,
    translated_pages: set[int],
}
```

### Config (config.toml)

```toml
[pdf_reader]
dpi = 200
cache_dir = "cache"

[deepseek]
api_key = "sk-..."
model = "deepseek-chat"
base_url = "https://api.deepseek.com"

[translation]
lang_in = "en"
lang_out = "zh"
qps = 4

[server]
host = "127.0.0.1"
port = 5000
debug = true
```

### Glossary (glossary.csv)

```csv
source,target
waveguide,波导
manifold,流形
```

## API Design

| Method | Path | Description |
|--------|------|-------------|
| POST | /api/open | Open PDF. Body: `{"path": "C:/doc.pdf"}` |
| GET | /api/page/:side/:page | PNG image for page N (side: left/right) |
| GET | /api/page-count/:side | Total pages |
| POST | /api/translate/:page | Translate page N. Body: `{"prompt": "..."}` (optional). SSE response |
| GET | /api/translated-pages | List of translated page numbers |
| GET | / | Index page (dual-column reader) |

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| No text selection (image-based) | Original PDF openable in regular reader for search |
| PNG bandwidth (~200-500 KB/page) | Lazy loading limits to ~10-20 pages in viewport |
| BabelDOC API instability | Pin pdf2zh-next version in requirements.txt |
| right.pdf save time for large PDFs | Acceptable for manual workflow; full rewrite prevents fragmentation |

## Capabilities

This design covers 6 capability areas (mirrored in openspec/specs/):

1. **pdf-rendering** — Server-side PNG rendering at 200 DPI via pymupdf
2. **dual-column-reading** — Synchronized left/right scrolling columns
3. **page-translation** — On-demand per-page translation via pdf2zh-next
4. **terminology-management** — CSV glossary with BabelDOC Hyperscan matching
5. **translation-persistence** — SHA256-hash-based right.pdf state management
6. **lazy-loading** — IntersectionObserver-based viewport-only image loading
