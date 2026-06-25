# frontend-modular-architecture Specification

## Purpose
TBD - created by archiving change modularize-frontend. Update Purpose after archive.
## Requirements
### Requirement: Frontend modular architecture

The system's frontend JavaScript SHALL be organized into separately importable ES Module files by responsibility, with `app.js` as the entry point that composes the modules. Modules SHALL cover: DOM manipulation, SSE stream reading, scroll synchronization, lazy loading, translation orchestration with progress UI, and stage label resolution.

#### Scenario: app.js is a thin entry point

- **WHEN** `app.js` is inspected
- **THEN** it SHALL primarily import and compose the other modules, binding open/translate events, and SHALL NOT contain inline implementations of scroll sync, lazy loading, SSE parsing, or DOM element creation

#### Scenario: Modules are separately importable

- **WHEN** a module file (e.g., `static/modules/scroll-sync.js`) is inspected
- **THEN** it SHALL export its functions via ES Module `export` and have no side effects on import beyond defining exports

### Requirement: Stage label single source of truth

The system SHALL maintain translation stage labels in a single source of truth on the backend. The frontend SHALL fetch stage labels from the backend at startup rather than maintaining a hardcoded duplicate, so frontend and backend stage labels cannot drift.

#### Scenario: Frontend fetches stage labels

- **WHEN** the frontend application initializes
- **THEN** it SHALL fetch stage labels from the backend and use them for progress display, instead of using a hardcoded local copy

#### Scenario: Stage label fetch failure fallback

- **WHEN** the stage label fetch fails
- **THEN** the frontend SHALL fall back to a minimal built-in copy and continue functioning, with translation progress still displayed

#### Scenario: Backend stage label endpoint

- **WHEN** the frontend requests stage labels
- **THEN** the backend SHALL expose them via a stable endpoint returning the current stage label mapping as JSON

### Requirement: Automated tests for translator and sse-client modules

The `translator` and `sse-client` frontend modules SHALL be covered by automated tests (runnable locally without a build step) verifying their core behaviors: SSE stream parsing, translation callback ordering, and error handling.

#### Scenario: readSSEStream parses multiple data events

- **WHEN** a response body streams multiple `data: {json}\n\n` events across one or more chunks
- **THEN** `readSSEStream` SHALL parse each event and invoke the callback once per event with the decoded JSON object, including events split across chunk boundaries

#### Scenario: readSSEStream terminates on empty stream

- **WHEN** the response body stream ends immediately with no data chunks
- **THEN** `readSSEStream` SHALL resolve without invoking any callbacks and without throwing

#### Scenario: readSSEStream skips malformed lines

- **WHEN** a chunk contains a `data: ` line whose payload is not valid JSON
- **THEN** `readSSEStream` SHALL skip that line WITHOUT throwing and SHALL continue parsing subsequent valid events

#### Scenario: translateCurrentPage invokes callbacks in order

- **WHEN** `translateCurrentPage` is called and the SSE stream yields a progress event followed by a finish event
- **THEN** `onProgress` SHALL be invoked with the progress value, `onStageChange` SHALL be invoked (when a stage is present) with the stage and label, and `onFinish` SHALL be invoked last

#### Scenario: translateCurrentPage appends page suffix to stage label conditionally

- **WHEN** a progress event includes `stage_current` and `stage_total` both greater than 0
- **THEN** the `onStageChange` label SHALL include the page segment suffix (e.g. `第 2/5 段`)
- **WHEN** `stage_current` or `stage_total` is 0 or absent
- **THEN** the label SHALL NOT include the page segment suffix

#### Scenario: translateCurrentPage handles SSE error event

- **WHEN** the SSE stream yields an `error` event
- **THEN** `onError` SHALL be invoked with the error message and `onFinish` SHALL NOT be invoked

#### Scenario: translateCurrentPage handles HTTP failure

- **WHEN** the `/api/translate/<page>` response is not ok
- **THEN** `translateCurrentPage` SHALL invoke `onError` with the server error message (or a fallback) and SHALL NOT invoke `onFinish`

#### Scenario: translateCurrentPage forwards prompt to request body

- **WHEN** `translateCurrentPage` is called with a `prompt` in the callbacks object
- **THEN** the POST request body SHALL contain `{ prompt: <value> }`, and SHALL contain `{ prompt: null }` when no prompt is provided

