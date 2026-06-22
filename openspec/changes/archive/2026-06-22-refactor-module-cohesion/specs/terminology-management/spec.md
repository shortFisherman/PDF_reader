## ADDED Requirements

### Requirement: Glossary service parameter interface

The glossary service module's `resolve_glossary_paths` function SHALL accept `Path | None` as its input parameter for cache path resolution instead of depending on the full `AppState` type. The merge function SHALL remain unchanged, accepting `Path | None` for both cumulative and auto-extracted paths.

#### Scenario: Resolve glossary paths from cache path

- **WHEN** `resolve_glossary_paths(cache_path)` is called with a valid Path
- **THEN** the function SHALL return `[str(cache_path / "cumulative_glossary.csv")]` if the file exists and is non-empty, or `None` otherwise

#### Scenario: Resolve glossary paths with None input

- **WHEN** `resolve_glossary_paths(None)` is called
- **THEN** the function SHALL return `None`
