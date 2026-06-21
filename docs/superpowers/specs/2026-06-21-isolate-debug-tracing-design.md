---
comet_change: isolate-debug-tracing
role: technical-design
canonical_spec: openspec
status: final
---

# Design: Isolate Debug Tracing

## 1. Current State

`app.py:12-14` has import-time side effects:
```python
config.DEBUG = True       # hardcoded
apply_patches()           # monkey-patches AutomaticTermExtractor unconditionally
logger.info("Debug tracing enabled")
```

This means **any** import of `app.py` (tests, production, or otherwise) triggers monkey-patching and forces debug on. `debug_patches.py` exists as a separate module with the monkey-patch logic.

`debug_trace.py` already exists with `log_step`, `log_token_usage`, `setup_file_handler`, `cleanup_file_handler`. `sse_stream.py` already uses these interfaces — no inline `if config.DEBUG` checks remain in business code.

What's missing:
- `init_debug()` to conditionally apply monkey-patches
- `debug_session` context manager to replace manual `setup_file_handler`/`cleanup_file_handler`
- `log_glossary_merge()` dedicated function
- Monkey-patch logic still in separate `debug_patches.py`
- `config.DEBUG` not driven by config.toml or CLI
- `app.py` still has import-time side effects

## 2. Design Decisions

### 2.1 Module Interface

```python
# debug_trace.py — final interface

def init_debug(debug_enabled: bool) -> None:
    """Conditionally apply monkey-patch to AutomaticTermExtractor.
    Only patches when debug_enabled=True. Silently degrades on ImportError."""

@contextmanager
def debug_session(glossary_path: Path | None, page: int):
    """Context manager for per-translation file handler management.
    Adds file handler with log rotation on enter; removes on exit.
    Exception-safe via try/finally. No-op when DEBUG=False."""

def log_step(step: str, *args: object) -> None:
    """Log a pipeline step. Returns immediately when DEBUG=False."""

def log_token_usage(token_usage: dict) -> None:
    """Log token usage from translate_result. Returns immediately when DEBUG=False."""

def log_glossary_merge(action: str, **fields) -> None:
    """Log glossary merge events. Returns immediately when DEBUG=False."""
```

### 2.2 Config Flow

```
config.toml ([debug] enabled) ──→ config.DEBUG (bool)
config.toml ([server] debug)  ──→ fallback        ←─ CLI --debug flag
                                           │
                        ┌──────────────────┘
                        ▼
                app.py:create_app()
                    │
            init_debug(config.DEBUG)
                    │
        ┌───────────┴───────────┐
        │                       │
   monkey-patch            business code
   (conditional)           log_step / log_token_usage
                           log_glossary_merge
                           debug_session
```

Priority: CLI `--debug` > `[debug] enabled` > `[server] debug` > default `False`.

### 2.3 Zero Overhead (DEBUG=False)

- `init_debug(False)` — no monkey-patch applied
- `log_step` / `log_token_usage` / `log_glossary_merge` — first line `if not config.DEBUG: return`
- `debug_session` — `if not config.DEBUG: yield; return`
- No string formatting, no IO, no handler creation

### 2.4 File Layout Changes

| File | Action |
|------|--------|
| `debug_trace.py` | Add `init_debug()`, `debug_session`, `log_glossary_merge()`. Migrate monkey-patch from `debug_patches.py` as private `_apply_monkey_patches()` / `_original_extract`. |
| `app.py` | Remove L12-14 (import-time side effects). Add `argparse --debug`. Call `init_debug()` in `create_app()`. |
| `config.py` | `DEBUG` reads from `[debug] enabled` (fallback `[server] debug`), default `False`. |
| `debug_patches.py` | Delete. |
| `sse_stream.py` | Wrap `generate()` with `debug_session`. Replace `log_step("merge glossary...")` with `log_glossary_merge()`. |
| `config.toml` | Optionally add `[debug] enabled = true`. |

### 2.5 Backward Compatibility

- `setup_file_handler` / `cleanup_file_handler` retained as `@deprecated` thin wrappers for any external callers.
- All existing tests (`test_debug_patches.py`, `test_debug_trace.py`, `test_sse_stream.py`) pass unchanged.

## 3. Error Handling

| Scenario | Strategy |
|----------|----------|
| `AutomaticTermExtractor` import fails (incompatible babeldoc) | `init_debug` catches `ImportError`, logs warning, skips monkey-patch, does not crash |
| `debug_session` file creation fails (permissions, disk full) | try/except, logger.warning, yield normally (silent degradation), finally does not raise |
| Translation raises during `debug_session` | `@contextmanager` try/finally guarantees handler removal and close |
| `debug_trace.log` rotation fails (file locked) | shutil.move exception caught, skip rotation, attempt to write |
| `log_token_usage` receives `None` or empty dict | Silent return |

## 4. Testing Strategy

| # | Test | Content |
|---|------|---------|
| 1 | Byte-equivalence regression | DEBUG=True trace output matches current `test_debug_patches.py` expectations |
| 2 | Zero-overhead assertions | DEBUG=False: no IO, no logging, no monkey-patch, `debug_session` no-op |
| 3 | `init_debug` tests | `init_debug(True)` patches; `init_debug(False)` does not; ImportError silently degrades |
| 4 | `debug_session` tests | File creation/rotation/cleanup; exception safety; `glossary_path=None` no handler |
| 5 | `app.py` no side effects | `import app` does not trigger monkey-patch, does not set `config.DEBUG=True` |
| 6 | Config source tests | `[debug] enabled` → True; fallback to `[server] debug`; CLI `--debug` overrides |
| 7 | `sse_stream.py` regression | `debug_session` + `log_glossary_merge` behavior equivalent to manual setup/cleanup |
| 8 | Full regression | `pytest tests/ -v` all passing |

Tests use `config.DEBUG` direct assignment for isolation; no real config.toml dependency.

## 5. Risk / Mitigation

| Risk | Mitigation |
|------|------------|
| Trace content byte drift | Byte-equivalence regression tests + existing `test_debug_patches.py` |
| `[debug] enabled` vs `[server] debug` confusion | Fallback chain handles both; docs note recommendation |
| Coordination with `modularize-frontend` change | `debug_trace` interfaces defined first; service layer calls same interfaces |
| `config.DEBUG` dynamic change during translation | Each `log_*` call reads live value (current behavior preserved) |
