## Why

Reading 1000-page English textbooks in their original language is mentally taxing—especially technical content with domain-specific terminology and formulas. Existing solutions either translate entire PDFs blindly (no user control) or require manual copy-paste per page. There's no tool that lets a reader scroll through a textbook naturally and translate only the specific pages they need, with the ability to refine mistranslations on the fly using custom instructions and a terminology glossary. This project fills that gap.

## What Changes

- **New**: A Flask-based backend that serves PDF pages as PNG images via pymupdf rendering (200 DPI)
- **New**: A dual-column HTML frontend with synchronized scrolling (left = original, right = translated)
- **New**: Per-page on-demand translation using pdf2zh-next (BabelDOC engine) with DeepSeek API
- **New**: Custom translation prompt input per request—user can specify instructions like "translate waveguide as 波导"
- **New**: CSV-based terminology glossary for consistent translation across pages
- **New**: Translation persistence via a right.pdf file that retains all translated pages across sessions
- **New**: SHA256-hash-based cache identification so re-opening the same PDF restores prior translation state
- **New**: Lazy-loading image rendering with IntersectionObserver for large PDF performance
- **New**: Floating toolbar for page navigation and translation controls

## Capabilities

### New Capabilities

- `pdf-rendering`: Render PDF pages as high-resolution PNG images on the server side using pymupdf, serving them to the browser for display
- `dual-column-reading`: Display original and translated PDF content side by side in two synchronized scrollable columns
- `page-translation`: Translate individual PDF pages on demand via pdf2zh-next with DeepSeek API, supporting custom user prompts per request
- `terminology-management`: CSV-based glossary for term consistency, injected into translation prompts automatically
- `translation-persistence`: Maintain translated pages in a right.pdf file identified by the original PDF's SHA256 hash, preserving state across sessions
- `lazy-loading`: Load only viewport-visible page images to support 1000+ page PDFs without memory issues

### Modified Capabilities

<!-- No existing capabilities to modify -->

## Impact

- **Dependencies**: pdf2zh-next (~2.8.2), pymupdf, Flask, DeepSeek API key
- **New files**: `app.py` (Flask), `templates/index.html` (frontend), `static/` (CSS/JS), `cache/` (right.pdf + temp files), `config.toml` (configuration), `glossary.csv` (terminology)
- **No existing code affected**—this is a greenfield project
- **No breaking changes**
