## Why

The bilingual PDF reader was built quickly with OpenSpec to prove the concept works. While functional, the codebase has accumulated technical debt: no tests, no type safety, no linting, global mutable state without concurrency protection, resource leaks, embedded API keys, and single-file monolithic structure. These issues are manageable in a prototype but will block future development, cause production bugs, and make the codebase hard to maintain. Fixing them now — before adding features — establishes the engineering foundation the project needs.

## What Changes

- **Security**: Move API key from config.toml to environment variable, prevent accidental commits
- **Concurrency**: Replace global mutable dict with thread-safe state management (threading.Lock or per-request context)
- **Resource management**: Close previous PDF documents when opening new ones; ensure temp file cleanup
- **Error handling**: Unified error response format, proper HTTP status codes, frontend network error UX
- **Type safety**: Add type annotations (PEP 484) to all Python functions and module-level variables
- **Testing**: Add pytest-based unit tests for core backend logic (rendering, hashing, settings builder)
- **Code organization**: Split app.py into modules (config, routes, services); split frontend JS into files
- **Linting & formatting**: Add ruff configuration for Python, ensure zero lint errors
- **Dependency management**: Generate requirements.lock for reproducible installs
- **Frontend fixes**: Deduplicate placeholder dimension calculation, add fetch error handling
- **Minor fixes**: Move imports to top of file, fix dead code (unused base_url), add logging, CSS overflow fix

## Capabilities

### New Capabilities

- `code-quality-foundations`: Establish testing, linting, type checking, and project structure standards across the entire codebase. Covers test framework setup, ruff configuration, module organization, and engineering conventions.

### Modified Capabilities

<!-- All existing capabilities remain functionally unchanged. This change improves implementation quality but does not alter spec-level behavior. -->

## Impact

- **Affected code**: `app.py` (refactor + split), `templates/index.html` (error handling + split), `static/style.css` (overflow fix)
- **New files**: `config.py`, `routes.py`, `services.py`, `tests/`, `ruff.toml`, `requirements.lock`, `static/app.js`
- **Dependencies added**: pytest, ruff (dev dependencies)
- **Config change**: `config.toml` API key moved to `.env` / environment variable
- **No breaking changes** to API endpoints or user-facing behavior
