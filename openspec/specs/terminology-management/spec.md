# terminology-management

## Purpose

Maintain a CSV-based glossary of source-to-target term mappings for consistent translation across pages. The glossary is delegated to BabelDOC's Hyperscan-based matching and LLM prompt injection system through pdf2zh-next.
## Requirements
### Requirement: CSV-based glossary file

The system SHALL support a CSV glossary file (`glossary.csv`) containing source-to-target term mappings for consistent translation.

#### Scenario: Load glossary with translation

- **WHEN** the translation engine is invoked
- **THEN** the system SHALL pass the glossary CSV file path to pdf2zh-next's `TranslationSettings.glossaries`

#### Scenario: Glossary CSV format

- **WHEN** the glossary file is read
- **THEN** the system SHALL expect CSV columns `source` and `target` where `source` is the original term and `target` is the preferred translation

#### Scenario: Translation with glossary terms

- **WHEN** a glossary term appears in the source text being translated
- **THEN** the translation engine SHALL prefer the glossary-specified target term over its default translation

#### Scenario: Empty or missing glossary

- **WHEN** no glossary.csv file exists or it is empty
- **THEN** the system SHALL still perform translation without glossary injection

### Requirement: Glossary file location

The system SHALL look for `glossary.csv` in the project root directory.

#### Scenario: Default glossary path

- **WHEN** the application starts
- **THEN** it SHALL resolve the glossary path as `<project_root>/glossary.csv`

### Requirement: Glossary injection into prompt

The system SHALL delegate glossary matching and prompt injection to BabelDOC's glossary system (through pdf2zh-next).

#### Scenario: Terms matched in source text

- **WHEN** the source page contains terms that match glossary entries
- **THEN** BabelDOC SHALL inject those terms into the LLM prompt as a markdown table with instruction to prefer glossary translations

### Requirement: Glossary service parameter interface

The glossary service module's `resolve_glossary_paths` function SHALL accept `Path | None` as its input parameter for cache path resolution instead of depending on the full `AppState` type. The merge function SHALL remain unchanged, accepting `Path | None` for both cumulative and auto-extracted paths.

#### Scenario: Resolve glossary paths from cache path

- **WHEN** `resolve_glossary_paths(cache_path)` is called with a valid Path
- **THEN** the function SHALL return `[str(cache_path / "cumulative_glossary.csv")]` if the file exists and is non-empty, or `None` otherwise

#### Scenario: Resolve glossary paths with None input

- **WHEN** `resolve_glossary_paths(None)` is called
- **THEN** the function SHALL return `None`

