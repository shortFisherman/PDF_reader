## Context

The user needs to read 1000-page English textbooks with on-demand translation. Existing solutions either translate entire PDFs blindly or require manual effort. This project builds a dual-column reading interface where the left side shows the original PDF, the right side shows translated pages (defaulting to a copy of the original for untranslated pages). Translation is triggered manually per page via a floating toolbar, with support for custom prompts and a CSV-based glossary.

**Constraints:**
- Windows 10 + Python 3.11.9, must use venv
- pdf2zh v1 is already installed via uv tool at `C:\Users\Couper\AppData\Roaming\uv\tools\pdf2zh\`
- pdf2zh-next (v2.8.2) must be installed separately
- DeepSeek API key is set as system environment variable
- User prefers config file management over environment variables

## Goals / Non-Goals

**Goals:**
- Dual-column layout (left = original, right = translated) with synchronized scroll
- Server-side PNG rendering at 200 DPI via pymupdf for both columns
- Per-page manual translation using pdf2zh-next with DeepSeek API
- Custom user prompt per translation request
- CSV-based glossary for term consistency
- Translation persistence via SHA256-hash-based right.pdf caching
- Lazy-loading images for 1000+ page PDFs
- Floating toolbar with page indicator and translation controls

**Non-Goals:**
- Text selection, search, or copy-paste from the reader
- Automatic pre-loading / predictive translation of upcoming pages
- PDF annotation or editing
- Chapter/table-of-contents navigation (future enhancement)
- Multi-language support for the UI
- Mobile/responsive design

## Decisions

### D1: Translation engine → pdf2zh-next (not v1, not BabelDOC direct)

**Chosen**: pdf2zh-next v2.8.2 via `do_translate_async_stream()` with `DeepSeekSettings`.

**Rationale**:
- pdf2zh-next wraps BabelDOC's superior pipeline (custom PDF parser, Document IL, LLM batch JSON mode, cross-page paragraph detection)
- Provides stable public API vs BabelDOC's explicitly internal API
- 22 translation service adapters including first-class DeepSeek support
- Built-in SQLite translation cache, subprocess crash isolation, structured progress events
- `only_include_translated_page` + `ignore_cache` flags directly support per-page re-translation

**Alternatives considered:**
- pdf2zh v1: Works but lacks glossary, custom prompt, single-page output. Inferior pipeline.
- BabelDOC direct: Has all features but API is officially "internal" and unsupported.

**Resolution on subprocess overhead**: Use `settings.basic.debug=True` to run BabelDOC in-process after a startup warmup, eliminating the 3-6s per-translation subprocess startup cost.

### D2: Frontend rendering → Server-side PNG (not PDF.js)

**Chosen**: pymupdf renders each page as 200 DPI PNG (~1600x2300 px), served as `<img>` tags.

**Rationale**:
- Two `<div>` columns with `scrollTop` synchronization is trivial (one line of JS)
- PDF.js dual-instance scroll sync is complex and fragile
- pymupdf uses the same MuPDF engine as most PDF readers—rendering is visually identical
- 200 DPI is sufficient for on-screen reading; can increase if needed

**Alternatives considered:**
- PDF.js: Better for text selection/search, but sync complexity outweighs benefit for this use case. Can be added later if needed.
- Browser native `<iframe>`: No scroll sync possible, independent page navigation.

### D3: Persistence → SHA256-hashed right.pdf (not database)

**Chosen**: On first open, copy original PDF to `cache/<sha256>/right.pdf`. Translated pages replace corresponding pages in right.pdf via pymupdf. On subsequent opens, SHA256 match restores previous state.

**Rationale**:
- right.pdf IS the state: which pages are translated is inherent in the file
- No database, no state file, no version tracking needed
- SHA256 hash ensures the same PDF always maps to the same cache
- If original PDF changes (new edition), different hash → fresh start (correct behavior)

**Save strategy**: After each translation, `save()` (full rewrite, not incremental) to avoid file fragmentation.

### D4: Glossary → CSV + Hyperscan matching (delegated to BabelDOC)

**Chosen**: A `glossary.csv` file in the project root with `source,target` columns. Passed to pdf2zh-next's `TranslationSettings.glossaries`. BabelDOC handles Hyperscan matching and prompt injection.

**Rationale**:
- PDF2zh-next/BabelDOC already has a complete glossary system
- CSV is human-editable, no tooling needed
- Hyperscan matching is high-performance (chunks of 20K patterns)
- Glossary is injected into LLM prompt as markdown table with instruction to adhere

**Future**: Optionally run a full-document term extraction pass (auto-extract glossary) to bootstrap the CSV.

### D5: Architecture → Flask backend + vanilla HTML/CSS/JS frontend

**Chosen**: Single `app.py` with Flask REST API. Single `templates/index.html` with inline JS.

**Rationale**:
- Simple enough to not need a frontend framework
- Flask is lightweight, single-file, well-understood
- REST API is straightforward: open PDF, get page image, translate page
- No build step, no bundler, no npm

### D6: Lazy loading → IntersectionObserver

**Chosen**: Each page is a `<div>` with a placeholder. `IntersectionObserver` detects visibility and loads the actual `<img>`. A buffer of ~5 pages above and below viewport is maintained.

## Risks / Trade-offs

- **[R1] No text selection**: Image-based rendering means users cannot select, copy, or search text. Mitigation: The original PDF can be opened in a regular reader for search. Text overlay (future) could address this.
- **[R2] Bandwidth**: Each page PNG is ~200-500 KB. 1000 pages viewed fully = ~200-500 MB transferred. Mitigation: Lazy loading means only ~10-20 pages in viewport at once; browser image caching avoids re-download on scroll-back.
- **[R3] BabelDOC API instability**: pdf2zh-next pins `babeldoc>=0.5.20,<0.6.0`. Breaking changes in 0.6.x could require adaptation. Mitigation: Pin pdf2zh-next version in requirements.txt.
- **[R4] Subprocess startup overhead**: Default mode spawns a process per translation (3-6s overhead). Mitigation: Use debug mode (in-process) with warmup.
- **[R5] Single-page auto term extraction is poor**: `only_include_translated_page` combined with auto-extract yields few terms. Mitigation: Provide glossary.csv; optionally run full-document term extraction once as a bootstrap step.
- **[R6] right.pdf file size**: Full rewrite (not incremental) recompresses the PDF each time. For 1000-page PDFs this may take 1-2 seconds per save. Mitigation: Acceptable for manual translation workflow (not automated).
