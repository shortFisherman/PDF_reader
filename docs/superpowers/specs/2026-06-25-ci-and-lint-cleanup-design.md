---
comet_change: add-ci-and-lint-cleanup
role: technical-design
canonical_spec: openspec
---

# CI and Lint Cleanup — Technical Design

## Architecture

Two-file change with no new runtime dependencies:

```
.github/workflows/ci.yml  (new)      — GitHub Actions workflow
ruff.toml                 (modified) — remove deprecated ANN101/ANN102
```

## CI Workflow

Single job, sequential execution on `windows-latest`:

```
push to main / pull_request
  → checkout@v4
  → setup-python@v5 (python-version: '3.12', cache: 'pip')
  → pip install -r requirements.lock
  → ruff check .     (step 1, fail → abort)
  → pytest -q         (step 2, fail → abort)
```

**Runner rationale**: Project README specifies Windows 10+ only; `pymupdf` and `pdf2zh-next` behavior must match local environment. Ubuntu runner could mask platform-specific issues.

**Dependency approach**: `requirements.lock` (pip freeze output) ensures exact version reproducibility, unlike `requirements.txt` which uses minimum version ranges.

**Config handling**: No special CI config needed. `conftest.py` already provides `mock_config` fixture via `defer-config-validation`, so `import config` succeeds without `config.toml`.

## Ruff Config Cleanup

`ruff.toml` line 6 currently ignores `ANN101` and `ANN102` — rules that ruff has removed. Running `ruff check` produces spurious "rules removed, ignoring has no effect" warnings. Simply delete these two entries from the `ignore` list. `ANN401` (dynamically typed expression) remains intentionally ignored.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| pip install fails (network/wheel) | Job fails, red X on commit |
| ruff check fails | Job fails immediately, pytest step skipped |
| pytest fails | Job fails after lint passes |
| config.toml absent in fresh clone | Tests pass via mock_config fixture |

## Verification

1. Rename `config.toml` locally, run `pytest -q` → all pass
2. Push branch with workflow, observe Actions tab → green
3. Deliberately break a lint rule, push → CI blocks with red X
4. Revert the break, push → CI returns to green
