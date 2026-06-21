# Brainstorm Summary

- Change: isolate-debug-tracing
- Date: 2026-06-21

## Confirmed Technical Approach

Approach A (Progressive Incremental): Extend the existing `debug_trace.py` module with missing interfaces while maintaining backward compatibility.

### Module Architecture
- `debug_trace.py`: Add `init_debug()`, `debug_session` context manager, `log_glossary_merge()`. Migrate monkey-patch logic from `debug_patches.py` as private implementation.
- `app.py`: Remove L12-14 import-time side effects (`config.DEBUG = True`, `apply_patches()`, `logger.info("Debug tracing enabled")`). Add argparse `--debug` flag. Explicitly call `init_debug(config.DEBUG)` in `create_app()`.
- `config.py`: `DEBUG` reads from `[debug] enabled` in config.toml, falls back to `[server] debug`, defaults to `False`.
- `debug_patches.py`: Delete; monkey-patch logic migrated into `debug_trace.py`.
- `sse_stream.py`: Replace `setup_file_handler`/`cleanup_file_handler` with `debug_session`. Replace `log_step("merge glossary...")` with `log_glossary_merge()`.
- `config.toml`: Optionally add `[debug] enabled = true`.

### Config priority
1. CLI `--debug` (explicit override)
2. `config.toml` `[debug] enabled`
3. `config.toml` `[server] debug` (fallback)
4. Default `False`

## Key Trade-offs and Risks

- **Trace content byte equivalence**: Existing `test_debug_patches.py` plus new byte-equivalence tests to capture drift
- **Coordination with modularize-frontend**: `debug_trace` interface defined first; the parallel change's service layer calls these interfaces
- **Backward compatibility**: `setup_file_handler`/`cleanup_file_handler` marked `@deprecated`, internally delegate to equivalent logic

## Testing Strategy

1. Byte-equivalence regression: DEBUG=True trace output matches current behavior
2. Zero-overhead assertions: DEBUG=False produces no IO, no logging, no monkey-patching
3. `init_debug` tests: conditional patching, ImportError silent degradation
4. `debug_session` tests: file creation/rotation/cleanup, exception safety, glossary_path=None
5. `app.py` no-side-effects: `import app` triggers no monkey-patch, no `config.DEBUG=True`
6. Config source tests: `[debug] enabled` → True, fallback to `[server] debug`, CLI `--debug`
7. Full regression: `pytest tests/ -v` all passing

## Spec Patches

None. Existing delta specs (code-quality-foundations, debug-trace-module, debug-tracing) already cover the design. Only implementation write-back needed.
