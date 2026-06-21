## ADDED Requirements

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
