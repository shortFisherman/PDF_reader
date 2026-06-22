# file-hash Specification

## Purpose
TBD - created by archiving change refactor-module-cohesion. Update Purpose after archive.
## Requirements
### Requirement: File hash module

The system SHALL provide a `file_hash` module that computes SHA256 hashes of files via streaming reads. The module SHALL export a single `sha256(filepath: str) -> str` function.

#### Scenario: Hash computation

- **WHEN** `sha256("/path/to/file")` is called
- **THEN** the module SHALL read the file in 8KB chunks and return its SHA256 hex digest

#### Scenario: Module independence

- **WHEN** `file_hash` is imported
- **THEN** it SHALL not depend on any other project module (only standard library `hashlib`)

