## MODIFIED Requirements

### Requirement: Frontend JavaScript in separate file

The system's frontend JavaScript SHALL be organized into separately importable ES Module files by responsibility, loaded via `<script type="module" src="/static/app.js">` where `app.js` is the thin entry point composing the other modules. All functionality SHALL work identically to the pre-refactor single-file implementation.

#### Scenario: JavaScript loaded as ES modules

- **WHEN** the index page is loaded in a browser
- **THEN** the JavaScript SHALL be loaded as ES Modules starting from `static/app.js`, which imports responsibility-specific modules, and all functionality SHALL work identically

#### Scenario: Frontend network error handling

- **WHEN** an open PDF or translation request fails due to network error
- **THEN** the user SHALL see an error message indicating the failure, handled by the appropriate module
