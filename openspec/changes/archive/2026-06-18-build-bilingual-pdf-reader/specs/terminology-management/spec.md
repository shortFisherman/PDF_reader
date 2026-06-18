## ADDED Requirements

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
