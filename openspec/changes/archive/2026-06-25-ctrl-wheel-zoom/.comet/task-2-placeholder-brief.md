# Task Group 2: Placeholder refactored to CSS variable (tasks 2.1, 2.2)

## Context
The CSS foundation (Task 1) added `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1))` to `.page-placeholder`. Now we must switch JS from setting inline `padding-bottom` to setting the CSS custom property `--page-ratio` instead, so the placeholder height is driven by the CSS calc which respects the `--zoom` variable.

## Requirements

### 2.1 — `dom.js` `createPageEl`
In `static/modules/dom.js`, function `createPageEl` (line 49-64):
- Line 59: Change `placeholder.style.paddingBottom = \`${ph}%\`;` to `placeholder.style.setProperty('--page-ratio', \`${ph}%\`);`

### 2.2 — `app.js` `unloadPageImage`
In `static/app.js`, function `unloadPageImage` (line 122-136):
- Line 131: Change `placeholder.style.paddingBottom = \`${ph}%\`;` to `placeholder.style.setProperty('--page-ratio', \`${ph}%\`);`

## Rationale
At zoom=1, the CSS calc becomes `calc(var(--page-ratio) * 1) = var(--page-ratio) = ph%`, identical to the old inline padding-bottom. When zoom changes, the height scales proportionally.

## Files to modify
- `static/modules/dom.js` (1 line: line 59)
- `static/app.js` (1 line: line 131)

## Validation
- Confirm placeholder height at default zoom (100%) is visually identical to before
- Run `node tests/run-lazy-loader-tests.mjs` to verify no regression (the lazy-loader creates placeholders too)
- Run `npm run test:translator` to verify no regression (30 tests should pass)

## Output
- Commit with message: `feat: replace inline padding-bottom with --page-ratio CSS variable for placeholders`
- Write report to `openspec/changes/ctrl-wheel-zoom/.comet/task-2-report.md`
