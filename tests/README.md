# Test Suites

## Supported regression suites

Run all supported frontend tests with:

```powershell
npm test
```

The supported suite contains:

- `run-ui-copy-tests.mjs` — startup and toolbar copy integrity.
- `run-error-safety-tests.mjs` — DOM `textContent` error rendering safety and `app.js` no-`insertAdjacentHTML` guard.
- `run-translation-ui-tests.mjs` — translation UI state machine, abort/signal, session dispose and `app-controller` assembly contract.
- `run-translator-tests.mjs` — SSE parsing and translation callbacks.
- `run-zoom-tests.mjs` — zoom behavior.
- `run-alignment-controller-tests.mjs` — dual-column alignment behavior and write exclusivity.
- `run-config-panel-tests.mjs` — 配置中心打开/关闭、分组与说明、provider 映射、
  API Key 不回显、加载/保存状态与重启提示。

All supported suites import production ES modules directly (`await import(...)`),
with jsdom globals set before import and browser dependencies injected through
module factories (`createReaderAppController`). No runner strips `export` from
source text or executes modules via `new Function`, and production modules
contain no `__TEST_*` branches. `package.json` declares `"type": "module"` to
match the Node ESM test contract; the browser continues to load the same
modules natively without a bundler.

## Historical diagnostics

The RED-phase/diagnostic runners and fixtures from before P3-03 are archived in
`tests/history/` (see `tests/history/README.md`). They are not part of `npm test`
and are excluded from ESLint (`tests/history/**`). They may reference the
pre-P3-03 inline `__TEST_*` self-test blocks that were removed from production
modules, so they are for history only and are not expected to run on current HEAD.

Do not interpret failures from historical diagnostics as a failed supported regression suite.

`npm run lint:js`（ESLint flat config）检查 `static/**/*.js` 与正式 `tests/*.mjs`；
`tests/history/**` 已整体排除，不再需要逐个精确 ignore。
