# translation-lifecycle Specification

## Purpose
TBD - created by archiving change refactor-module-cohesion. Update Purpose after archive.
## Requirements
### Requirement: Translation lifecycle module

The system SHALL provide a `translation_lifecycle` module that encapsulates all post-translation operations: persisting the translated page into right.pdf, merging auto-extracted terminology into the cumulative glossary, and (subject to the SSE layer's cleanup responsibility) temporary directories. The lifecycle module SHALL consume the translation result through an explicit `TranslateResult` Protocol (structural typing) declaring the fields it depends on (`mono_pdf_path`, `dual_pdf_path`, `auto_extracted_glossary_path`, each `Path | None`), rather than through an `Any`-typed parameter. The SSE streaming module SHALL delegate post-translation page-replacement and glossary-merge to this module rather than calling state.replace_page and glossary merging directly.

#### Scenario: Translation completion triggers lifecycle

- **WHEN** a translation completes successfully (translate_result is available)
- **THEN** the translation lifecycle module SHALL replace the translated page in right.pdf via AppState.replace_page and merge auto-extracted glossary terms

#### Scenario: Lifecycle handles missing output

- **WHEN** translate_result has no mono_pdf_path and no dual_pdf_path
- **THEN** the translation lifecycle module SHALL skip page replacement and continue with glossary merging (preserving current behavior), and SHALL NOT raise

#### Scenario: Lifecycle falls back to dual PDF

- **WHEN** translate_result has `mono_pdf_path is None` and a non-null `dual_pdf_path`
- **THEN** the lifecycle module SHALL use the `dual_pdf_path` as the page to insert into right.pdf

#### Scenario: Typed contract enables static checking

- **WHEN** the lifecycle module source is inspected or a static type checker is run
- **THEN** the `translate_result` parameter SHALL be typed as the `TranslateResult` Protocol (not `Any`), so field-name typos or missing attributes are detectable by static analysis

