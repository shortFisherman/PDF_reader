# frontend-modular-architecture Delta: add-translator-frontend-tests

## ADDED Requirements

### Requirement: Automated tests for translator and sse-client modules

The `translator` and `sse-client` frontend modules SHALL be covered by automated tests (runnable locally without a build step) verifying their core behaviors: SSE stream parsing, translation callback ordering, and error handling.

#### Scenario: readSSEStream parses multiple data events

- **WHEN** a response body streams multiple `data: {json}\n\n` events across one or more chunks
- **THEN** `readSSEStream` SHALL parse each event and invoke the callback once per event with the decoded JSON object, including events split across chunk boundaries

#### Scenario: readSSEStream skips malformed lines

- **WHEN** a chunk contains a `data: ` line whose payload is not valid JSON
- **THEN** `readSSEStream` SHALL skip that line WITHOUT throwing and SHALL continue parsing subsequent valid events

#### Scenario: translateCurrentPage invokes callbacks in order

- **WHEN** `translateCurrentPage` is called and the SSE stream yields a progress event followed by a finish event
- **THEN** `onProgress` SHALL be invoked with the progress value, `onStageChange` SHALL be invoked (when a stage is present) with the stage and label, and `onFinish` SHALL be invoked last

#### Scenario: translateCurrentPage handles SSE error event

- **WHEN** the SSE stream yields an `error` event
- **THEN** `onError` SHALL be invoked with the error message and `onFinish` SHALL NOT be invoked

#### Scenario: translateCurrentPage handles HTTP failure

- **WHEN** the `/api/translate/<page>` response is not ok
- **THEN** `translateCurrentPage` SHALL invoke `onError` with the server error message (or a fallback) and SHALL NOT invoke `onFinish`

#### Scenario: translateCurrentPage forwards prompt to request body

- **WHEN** `translateCurrentPage` is called with a `prompt` in the callbacks object
- **THEN** the POST request body SHALL contain `{ prompt: <value> }`, and SHALL contain `{ prompt: null }` when no prompt is provided