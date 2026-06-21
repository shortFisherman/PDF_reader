## ADDED Requirements

### Requirement: Translation page range validation

The system SHALL validate that the requested page index is within the opened document's page range before initiating translation. Out-of-range pages SHALL return a 400 error with a clear message, rather than triggering a low-level PDF engine exception.

#### Scenario: Translate page below range

- **WHEN** a translation is requested for a negative page index (via direct handler call; Flask's `<int:page>` route converter matches only non-negative integers, so this path is defensive for direct callers)
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine

#### Scenario: Translate page above range

- **WHEN** a translation is requested for a page index greater than or equal to the document's page count
- **THEN** the system SHALL return HTTP 400 with an error response, without invoking the translation engine
