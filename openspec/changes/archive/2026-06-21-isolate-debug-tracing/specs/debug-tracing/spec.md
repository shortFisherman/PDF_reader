## MODIFIED Requirements

### Requirement: Debug mode activation

The system SHALL support debug mode driven by `config.toml` (default False) or the `--debug` CLI flag. When debug mode is disabled, the system SHALL behave identically to the previous release (zero overhead: no monkey-patching, no debug file IO, no trace logging). `config.DEBUG` SHALL NOT be hardcoded to True at import time; it SHALL be resolved from configuration.

#### Scenario: Debug mode enabled via CLI

- **WHEN** user starts the app with `python app.py --debug`
- **THEN** `config.DEBUG` is `True`, `init_debug(True)` applies the monkey-patch, and all debug trace features are active

#### Scenario: Debug mode enabled via config

- **WHEN** `config.toml` sets debug enabled to true and the app starts without `--debug`
- **THEN** `config.DEBUG` is `True` and all debug trace features are active

#### Scenario: Debug mode disabled (default)

- **WHEN** user starts the app with `python app.py` (no `--debug`) and config does not enable debug
- **THEN** the system behaves identically to the pre-debug version with no additional file IO, no monkey-patching, and no trace logging

#### Scenario: No import-time side effects

- **WHEN** `app.py` is imported (without running the server)
- **THEN** no monkey-patching SHALL be applied and no debug logging SHALL occur; debug initialization SHALL happen only inside `create_app()` based on resolved config

### Requirement: babeldoc debug output capture

When debug mode is active, the system SHALL set `TranslationConfig.debug = True` so that babeldoc generates internal tracking files (`term_extractor_tracking.json`, `term_extractor_freq.json`, `auto_extractor_glossary.csv`).

#### Scenario: babeldoc tracking files generated

- **WHEN** a page is translated with debug mode enabled
- **THEN** the babeldoc working directory contains `term_extractor_tracking.json`, `term_extractor_freq.json`, and `auto_extractor_glossary.csv`

#### Scenario: Debug files preserved after translation

- **WHEN** translation completes and the working directory is cleaned up
- **THEN** the debug files are copied to `cache/<pdf_hash>/` BEFORE cleanup occurs

### Requirement: LLM term extraction transparency

The system SHALL monkey-patch `AutomaticTermExtractor.extract_terms_from_paragraphs` (conditionally, only when debug is enabled) to log, for each batch of paragraphs submitted for term extraction:
- Number of paragraphs and total character count in the batch
- Length of the constructed prompt (characters)
- Length of the LLM response (characters), with the response content truncated to 500 characters
- Number of valid terms parsed from the response
- Any JSON parse errors with the problematic response content

#### Scenario: Successful term extraction batch

- **WHEN** the LLM returns a valid JSON array with 3 terms
- **THEN** the log contains: batch size, prompt length, "LLM response length: N, parsed terms: 3"

#### Scenario: LLM returns empty array

- **WHEN** the LLM returns `[]`
- **THEN** the log contains: "LLM response length: N, parsed terms: 0" and the full response `[]` is logged

#### Scenario: LLM returns invalid JSON

- **WHEN** the LLM returns text that cannot be parsed as JSON
- **THEN** the log contains the JSON parse error details and the first 500 characters of the raw response

#### Scenario: Monkey-patch fails to load

- **WHEN** babeldoc version is incompatible and the monkey-patch raises ImportError
- **THEN** the system logs a warning and continues with normal operation (no crash)

### Requirement: Translation pipeline step logging

When debug mode is active, the system SHALL log each major step in the translation pipeline via `debug_trace.log_step` with:
- Step description (e.g., "Building translation settings", "Submitting page for translation")
- Key inputs (page number, PDF path, glossary paths)
- Outcome (translation result path, elapsed time)

#### Scenario: Single page translation

- **WHEN** user requests translation of page 1
- **THEN** the log shows: build_settings step, do_translate step (with page number), merge glossary step, replace page step, each with success/failure status

#### Scenario: Translation failure

- **WHEN** a translation step fails with an exception
- **THEN** the log includes the step name, the exception type and message, and the traceback

### Requirement: Debug output file organization

The system SHALL organize all debug output files under `cache/<pdf_hash>/` with the following naming convention:
- `cumulative_glossary.csv` — accumulated glossary (existing)
- `debug_trace.log` — full debug log for this PDF session
- `term_extractor_tracking.json` — copied from babeldoc working dir
- `term_extractor_freq.json` — copied from babeldoc working dir

#### Scenario: First translation of a PDF

- **WHEN** a PDF is opened and its first page is translated with debug mode
- **THEN** the directory `cache/<pdf_hash>/` is created and contains all four files listed above

#### Scenario: Session log persistence

- **WHEN** the application is restarted and the same PDF is opened again with debug mode
- **THEN** the previous `debug_trace.log` is rotated (appended with timestamp) and a new session log begins
