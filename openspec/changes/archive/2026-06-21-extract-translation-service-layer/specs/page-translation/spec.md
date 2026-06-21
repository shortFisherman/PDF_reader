## MODIFIED Requirements

### Requirement: Manual per-page translation trigger

The system SHALL allow the user to trigger translation of the currently visible page via a button in the floating toolbar. The `/api/translate/<page>` endpoint SHALL delegate to the translation service layer; the route function SHALL only parse the request, validate the page, compose services, and return the SSE Response.

#### Scenario: Translate untranslated page

- **WHEN** the user clicks "Translate" on a page that has not been translated
- **THEN** the system SHALL extract the page from the original PDF, send it to the translation engine, and replace the corresponding page in right.pdf with the translated output

#### Scenario: Re-translate already translated page

- **WHEN** the user clicks "Translate" on a page that has already been translated
- **THEN** the system SHALL re-translate the page, overwriting the previous translation in right.pdf

#### Scenario: Translation in progress

- **WHEN** a translation is in progress for a page
- **THEN** the translate button SHALL be disabled and display "Translating..." until completion

#### Scenario: Translation completion

- **WHEN** a page translation completes
- **THEN** the right-column image for that page SHALL refresh to show the translated content within 2 seconds

#### Scenario: SSE event stream byte-level compatibility

- **WHEN** the service layer formats SSE events
- **THEN** the event type, field names, stage labels, and `data: {json}\n\n` framing SHALL be byte-for-byte identical to the pre-refactor output, so the frontend requires no changes
