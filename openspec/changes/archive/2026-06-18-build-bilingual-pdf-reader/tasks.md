## 1. Environment & Project Setup

- [x] 1.1 Create project directory structure (templates/, static/, cache/)
- [x] 1.2 Create and activate Python virtual environment (venv)
- [x] 1.3 Install Flask and pymupdf via pip
- [x] 1.4 Install pdf2zh-next via pip (version ~2.8.2 with babeldoc dependency)
- [x] 1.5 Create config.toml with DeepSeek API key, model, DPI, and paths
- [x] 1.6 Create empty glossary.csv with source,target headers
- [x] 1.7 Verify DeepSeek API key is accessible from config.toml

## 2. Backend Core: PDF Rendering API

- [x] 2.1 Create Flask app skeleton in app.py with config loading
- [x] 2.2 Implement POST /open — accept PDF file path, compute SHA256 hash, return page count and dimensions
- [x] 2.3 Implement right.pdf initialization logic: copy original to cache/<sha256>/right.pdf on first open
- [x] 2.4 Implement GET /api/page/<side>/<int:page> — render page N from left (original) or right (translated) PDF as PNG at 200 DPI
- [x] 2.5 Implement GET /api/page-count/<side> — return total page count for left or right PDF

## 3. Frontend Core: Dual-Column UI

- [x] 3.1 Create templates/index.html with two side-by-side scrollable div columns
- [x] 3.2 Implement IntersectionObserver-based lazy loading: only load images within 5-page buffer of viewport
- [x] 3.3 Implement scrollTop synchronization: left column scroll drives right column position
- [x] 3.4 Implement page layout: each page as a div with placeholder dimensions, image loaded on demand
- [x] 3.5 Implement global styles in static/style.css for dual-column layout and placeholder styling

## 4. Translation Engine Integration

- [x] 4.1 Implement pdf2zh-next SettingsModel builder from config.toml values
- [x] 4.2 Implement POST /api/translate/<int:page> — extract single page from original PDF, call pdf2zh-next do_translate_async_stream, replace page in right.pdf
- [x] 4.3 Implement custom prompt pass-through: accept user prompt from request body, set TranslationSettings.custom_system_prompt
- [x] 4.4 Implement SSE progress streaming: relay translation engine progress events to frontend via Server-Sent Events
- [x] 4.5 Implement force retranslation: always set ignore_cache=True
- [x] 4.6 Implement single-page output: set pages=N and only_include_translated_page=True
- [x] 4.7 Add debug mode support: set settings.basic.debug=True to run BabelDOC in-process after warmup

## 5. Persistence: right.pdf Management

- [x] 5.1 Implement SHA256 hash computation on POST /open
- [x] 5.2 Implement cache directory resolution: cache/<sha256>/
- [x] 5.3 Implement right.pdf page replacement: delete old page, insert translated page from pdf2zh-next output, save with full rewrite (non-incremental)
- [x] 5.4 Implement session restore: on POST /open, check if cache/<sha256>/right.pdf exists and use it as the right PDF

## 6. Terminology Management

- [x] 6.1 Implement glossary.csv loading on app startup
- [x] 6.2 Pass glossary path to pdf2zh-next TranslationSettings.glossaries on each translation call
- [x] 6.3 Add glossary.csv to .gitignore (may contain sensitive terms)

## 7. Frontend: Floating Toolbar & Controls

- [x] 7.1 Build floating toolbar HTML/CSS fixed at bottom of viewport
- [x] 7.2 Implement current page detection: update page indicator based on which page occupies most of viewport
- [x] 7.3 Implement translate button with click handler calling POST /api/translate/<page> with optional prompt
- [x] 7.4 Implement custom prompt input field in toolbar (text input or expandable textarea)
- [x] 7.5 Implement button state: disabled + "Translating..." text during active translation
- [x] 7.6 Implement translated page image refresh after translation completes (cache-busting URL)

## 8. Polish & Error Handling

- [x] 8.1 Add error handling for missing PDF files, invalid page numbers, translation failures
- [x] 8.2 Add translation progress indicator (SSE-driven progress bar or spinner)
- [x] 8.3 Add 404 page for unknown routes
- [x] 8.4 Add visual distinction for translated vs untranslated pages in right column (subtle border or background tint)
- [x] 8.5 Clean up temp files: delete single-page PDFs after translation completes

## 9. Verification

- [x] 9.1 Test with a 3-5 page PDF: open, render, translate page 2, verify right column updates
- [x] 9.2 Test persistence: close and reopen same PDF, verify translated pages remain
- [x] 9.3 Test custom prompt: translate with specific instruction, verify LLM follows it
- [x] 9.4 Test scroll sync: scroll left column, verify right column follows
- [x] 9.5 Test lazy loading: open 50+ page PDF, verify only viewport-adjacent images are loaded
- [x] 9.6 Test with glossary.csv: add a term, verify translation uses it
