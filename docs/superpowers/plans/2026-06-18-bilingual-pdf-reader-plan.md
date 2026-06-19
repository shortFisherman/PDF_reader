# Bilingual PDF Reader — Implementation Plan

**change:** build-bilingual-pdf-reader
**design-doc:** docs/superpowers/specs/2026-06-18-bilingual-pdf-reader-design.md
**status:** archived
**archived-with:** openspec/changes/archive/2026-06-18-build-bilingual-pdf-reader

---

## Phase 1: Environment & Project Setup

- [x] Create project directory structure (templates/, static/, cache/)
- [x] Create and activate Python virtual environment (venv)
- [x] Install Flask, pymupdf, pdf2zh-next via pip
- [x] Create config.toml with DeepSeek API key, model, DPI, paths
- [x] Create empty glossary.csv with source,target headers
- [x] Verify DeepSeek API key is accessible

## Phase 2: Backend — PDF Rendering API

- [x] Create Flask app skeleton with config loading
- [x] Implement POST /api/open — accept path, compute SHA256, return page count + dimensions
- [x] Implement right.pdf initialization logic
- [x] Implement GET /api/page/:side/:page — render PNG at 200 DPI
- [x] Implement GET /api/page-count/:side

## Phase 3: Frontend — Dual-Column UI

- [x] Create index.html with dual-column layout
- [x] Implement IntersectionObserver lazy loading (5-page buffer)
- [x] Implement scrollTop synchronization
- [x] Implement page layout with placeholder dimensions
- [x] Apply styles in static/style.css

## Phase 4: Translation Engine Integration

- [x] Build pdf2zh-next SettingsModel from config
- [x] Implement POST /api/translate/:page with single-page extraction
- [x] Custom prompt pass-through
- [x] SSE progress streaming
- [x] Force retranslation (ignore_cache=True)
- [x] Single-page output configuration
- [x] Debug mode for in-process execution

## Phase 5: Persistence — right.pdf Management

- [x] SHA256 hash computation on open
- [x] Cache directory resolution
- [x] Right.pdf page replacement with full rewrite
- [x] Session restore on reopen

## Phase 6: Terminology Management

- [x] Glossary CSV loading
- [x] Pass glossary to pdf2zh-next settings
- [x] Add glossary.csv to .gitignore

## Phase 7: Frontend — Floating Toolbar & Controls

- [x] Build floating toolbar
- [x] Current page detection
- [x] Translate button with API call
- [x] Custom prompt input
- [x] Button disabled state during translation
- [x] Translated page image refresh

## Phase 8: Polish & Error Handling

- [x] Error handling for missing files, invalid pages, translation failures
- [x] Translation progress indicator (SSE)
- [x] 404 page for unknown routes
- [x] Visual distinction for translated vs untranslated pages
- [x] Temp file cleanup

## Phase 9: Verification

- [x] Test 3-5 page PDF: open, render, translate, verify
- [x] Test persistence: close/reopen preserves translations
- [x] Test custom prompt
- [x] Test scroll sync
- [x] Test lazy loading with 50+ page PDF
- [x] Test glossary injection
