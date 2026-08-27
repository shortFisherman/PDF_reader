# Project Status

<!-- HISTORICAL_DOCUMENT_START -->
> [!NOTE]
> **历史资料。** 本文保留的是当时的阶段记录，不代表当前项目目的、当前实现或实施授权。请以 [project](../project.md)、[architecture](../architecture.md) 和 [roadmap](../roadmap.md) 为准。
<!-- HISTORICAL_DOCUMENT_END -->

**Status:** Frozen

**Frozen on:** 2026-08-06

**Maintenance policy:** No planned feature development. Consider only security issues, data-loss defects, or regressions that prevent the documented local workflow from starting.

## Why the project is frozen

PDF Reader reached a stable local-reader milestone, but the broader full-document translation space is already well served by PDFMathTranslate-next, its WebUI and desktop distribution, and mature Zotero plugins. Further investment in translation providers, whole-document controls, or Zotero parity would duplicate that ecosystem.

The repository is preserved as a functional local tool and as a record of the dual-column reading, translation lifecycle, glossary, progress streaming, and large-document loading work.

## Current architecture

- `app.py` creates the Flask application and the single local `AppState`.
- `routes.py` exposes document, page rendering, translation, progress, and stage endpoints.
- `state.py` owns the open source/translated documents, cache paths, translated-page state, rendering locks, and reading progress.
- `translation_orchestrator.py` bridges the synchronous PDF translation pipeline to the SSE event stream.
- `sse_stream.py` emits translation stages, progress, errors, and completion events.
- `translation_lifecycle.py` persists translated pages, merges glossary output, and cleans temporary resources.
- `translation_settings.py` and `engine_resolver.py` map the unified model configuration to pdf2zh-next settings.
- `static/app.js` coordinates the reader UI, page loading, translation controls, zoom, and progress persistence.
- `static/modules/` contains the alignment, lazy-loading, SSE, translation, stage-label, and zoom modules.

## Known limitations

- The Flask process owns one global document state. The application is designed for one local user and one open document, not concurrent or hosted use.
- Pages are rendered as PNG images. There is no selectable text layer, document search, copy, highlighting, annotations, outline navigation, or link interaction.
- Replacing translated pages rewrites and reopens `right.pdf`; repeated page-by-page translation of large files can produce substantial disk I/O.
- Translation has no persistent job queue, pause, cancellation, per-page retry queue, or restartable background task state.
- Setup requires Python, local configuration, an API key, and a local file-system path.
- Historical Node diagnostic scripts outside the supported `npm test` suite may intentionally fail or target older source shapes. See `tests/README.md`.

## Dependency and license reminder

PDF translation is provided by the upstream `pdf2zh-next` package from PDFMathTranslate-next, which is distributed under AGPL-3.0. The repository metadata currently states ISC. Before redistributing the application, hosting it as a service, or changing its licensing model, review the upstream license and the combined distribution with qualified advice. This note records a risk and is not a legal conclusion.

## How to verify the frozen baseline

From PowerShell in the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

## If development resumes

Start with user validation, not another translation-provider integration. The recommended product experiment is a PDF.js text layer supporting selection, search, contextual paragraph translation, and persistent bilingual notes while retaining PDFMathTranslate-next as optional full-page translation/export infrastructure.

Before implementation, reassess upstream capabilities, licensing, dependency compatibility, and whether real users repeatedly need the proposed workflow.
