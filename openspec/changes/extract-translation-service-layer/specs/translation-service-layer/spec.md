## ADDED Requirements

### Requirement: Translation service layer modularization

The system SHALL provide a translation service layer that separates the concerns currently embedded in the `translate_page` route function. The service layer SHALL consist of independently testable modules covering: single-page PDF extraction, translation engine orchestration (asyncio thread + event queue), SSE event formatting, glossary path resolution and merge, and debug trace logging hooks.

#### Scenario: Single-page PDF extraction service

- **WHEN** the translation flow needs a single-page PDF for page N
- **THEN** a dedicated extraction service SHALL produce a temporary PDF containing only page N from the source document, without the route function directly calling pymupdf

#### Scenario: Translation orchestration service

- **WHEN** the route triggers a translation
- **THEN** a translation orchestrator service SHALL run the asyncio translation stream in a background thread and expose a synchronous iterator of translation events, isolating asyncio complexity from the route layer

#### Scenario: SSE event formatting service

- **WHEN** translation events need to be streamed to the frontend
- **THEN** a dedicated SSE formatting module SHALL convert each event dict into the `data: {json}\n\n` wire format, byte-for-byte identical to the current output

#### Scenario: Glossary service

- **WHEN** a translation starts or finishes
- **THEN** a glossary service SHALL resolve cumulative glossary paths before translation and merge auto-extracted terms after translation, without inline logic in the route function

#### Scenario: Translation error propagation

- **WHEN** the translation engine raises an exception or yields an error event
- **THEN** the orchestrator SHALL propagate the error to the SSE stream as an error event, and the route SHALL NOT crash

### Requirement: Route function thinness

The `translate_page` route function SHALL be limited to request parsing, page validation, service composition, and returning the SSE Response. It SHALL NOT contain business orchestration logic such as pymupdf calls, asyncio loop management, or inline debug logging.

#### Scenario: Route function line count

- **WHEN** the `translate_page` function is measured
- **THEN** its body SHALL be at most 40 lines, excluding the SSE generator it composes from services
