# Brainstorm Summary

- Change: code-quality-improvements
- Date: 2026-06-19

## Confirmed Technical Approach

**Architecture**: Split monolithic app.py into 5 modules (config, state, services, routes, app). Use `AppState` class with `threading.Lock` stored in `app.config['app_state']` — chosen over global state (Plan A) and full dependency injection (Plan C) for balance of encapsulation and simplicity.

**Key decisions in OpenSpec design.md preserved:**
- D1: threading.Lock for concurrency
- D2: config / routes / services module split
- D3: DEEPSEEK_API_KEY env var with config.toml fallback
- D4: pytest with fixture-based setup
- D5: ruff with strict ruleset
- D6: JS to static/app.js
- D7: queue.Queue replacing SSE busy-wait polling

## Key Trade-offs and Risks

| Trade-off | Mitigation |
|-----------|------------|
| current_app dependency in routes | Acceptable for Flask idiom; better than module globals |
| Lock granularity (per-method) | Single-user tool, contention negligible |
| Module split may break route decorators | Use Blueprint or import app reference |

## Testing Strategy

```
tests/
├── conftest.py       # fixtures
├── test_config.py    # config loading
├── test_state.py     # AppState + concurrency safety
├── test_services.py  # pure functions
└── test_routes.py    # Flask test client integration
```

- Unit tests for pure functions (sha256, render, settings builder)
- State tests with mock pymupdf.Document
- Integration tests via Flask test_client

## Spec Patches

None. This change is implementation quality improvement without spec-level behavior changes.
