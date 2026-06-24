# Brainstorm Summary

- Change: add-ci-and-lint-cleanup
- Date: 2026-06-25

## Confirmed Technical Approach

Single job sequential CI workflow on `windows-latest`:
1. Checkout code
2. Setup Python 3.12 with pip cache
3. Install dependencies from `requirements.lock`
4. Run `ruff check .` (fail on error)
5. Run `pytest -q` (fail on error)

Trigger: push to main + pull_request.

Also remove `ANN101` and `ANN102` from `ruff.toml` ignore list (rules already removed by ruff, causes spurious warnings).

Depends on `defer-config-validation` for tests to pass without `config.toml` in fresh clone.

## Key Trade-offs and Risks

- Windows runner minutes cost higher than Linux, but matches local environment
- Single job is simpler and uses fewer minutes than split lint/test jobs
- pip cache reduces repeat run time for pymupdf and other large dependencies
- Removing deprecated ruff rules cannot introduce new errors (rules don't exist anymore)

## Testing Strategy

- Local: rename/remove `config.toml`, run `pytest -q` to verify all tests pass
- CI: push branch, verify GitHub Actions status is green
- Negative: inject a lint error, verify CI blocks correctly

## Spec Patches

None — OpenSpec delta specs already cover acceptance scenarios adequately.
