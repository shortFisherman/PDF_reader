# Test Suites

## Supported regression suites

Run all supported frontend tests with:

```powershell
npm test
```

The supported suite contains:

- `run-ui-copy-tests.mjs` — startup and toolbar copy integrity.
- `run-error-safety-tests.mjs` — DOM `textContent` error rendering safety and `app.js` no-`insertAdjacentHTML` guard.
- `run-translation-ui-tests.mjs` — translation UI state machine, abort/signal, session dispose and `app.js` assembly contract.
- `run-translator-tests.mjs` — SSE parsing and translation callbacks.
- `run-zoom-tests.mjs` — zoom behavior.
- `run-alignment-controller-tests.mjs` — dual-column alignment behavior and write exclusivity.

## Historical diagnostics

The remaining `.mjs` files are retained as development history and targeted diagnostics. They are not part of `npm test`:

- `run-alignment-repro-tests.mjs` intentionally reproduces RED-phase alignment failures.
- `run-lazy-loader-tests.mjs` is a legacy inline self-test harness and is not stable under the current Node/jsdom environment.
- `run-task-4.4-tests.mjs` and `run-task-4.5-tests.mjs` are task-specific historical harnesses that parse older `app.js` function shapes.

Do not interpret failures from historical diagnostics as a failed supported regression suite.

`npm run lint:js`（ESLint flat config）检查 `static/**/*.js` 与正式 `tests/*.mjs`；历史 fixture 与诊断 runner 以精确 ignore 排除，待 P3-03 统一结构。
