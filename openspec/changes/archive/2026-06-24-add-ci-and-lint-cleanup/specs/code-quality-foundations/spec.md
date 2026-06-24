# code-quality-foundations Delta: add-ci-and-lint-cleanup

## MODIFIED Requirements

### Requirement: Code linting with zero errors

The system SHALL include a ruff configuration file and SHALL pass linting checks with zero errors when `ruff check` is run against the project. The ruff configuration SHALL NOT list any rules that have been removed from ruff (such as `ANN101` / `ANN102`) in its `ignore` set, so running `ruff check` produces no "rules removed, ignoring has no effect" warnings while still passing with zero errors.

#### Scenario: Ruff check passes

- **WHEN** `ruff check` is executed in the project root
- **THEN** the command SHALL exit with code 0, produce no error output, and produce no warning about ignored removed rules

#### Scenario: Removed rules not in ignore set

- **WHEN** `ruff.toml` is inspected
- **THEN** the `ignore` list SHALL NOT contain `ANN101` or `ANN102` (or any other rule ruff reports as removed), while the existing effective lint guarantees are preserved