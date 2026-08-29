# continuous-integration Specification

## Purpose
TBD - created by archiving change add-ci-and-lint-cleanup. Update Purpose after archive.
## Requirements
### Requirement: Lint and test pipeline on push and PR

The repository SHALL include a GitHub Actions workflow that, on every push to the main branch and on every pull request, automatically installs dependencies from `requirements.lock`, installs the local package with `pip install -e . --no-deps`, installs frontend test dependencies with `npm ci`, and runs the single unified `scripts/verify.ps1` entry. The workflow SHALL fail the CI status when any lint or test step reports failures, so regressions are blocked before merge.

#### Scenario: CI runs on push

- **WHEN** a commit is pushed to the main branch
- **THEN** the GitHub Actions workflow SHALL trigger and run `scripts/verify.ps1`

#### Scenario: CI runs on pull request

- **WHEN** a pull request is opened or updated against the main branch
- **THEN** the workflow SHALL trigger and report a failing status check if lint or tests fail

#### Scenario: Fresh clone without config.toml runs tests

- **WHEN** the CI workflow checks out the repository into a fresh clone that has no `config.toml`
- **THEN** the test suite SHALL still run successfully (relying on defer-config-validation), and `from pdf_reader import config` SHALL not raise

#### Scenario: Lint failure blocks CI

- **WHEN** `ruff check .` exits non-zero
- **THEN** the workflow SHALL fail and the dependent job (tests) SHALL not report success
