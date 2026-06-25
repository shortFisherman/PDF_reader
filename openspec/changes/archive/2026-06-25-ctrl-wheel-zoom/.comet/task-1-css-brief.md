# Task Group 1: CSS Zoom Foundation (tasks 1.1, 1.2, 1.3)

You are implementing the CSS foundation for Ctrl+wheel page zoom in a PDF reader web app. The zoom system uses CSS custom properties:
- `--zoom` (scale factor, default 1) drives render width
- `--page-ratio` (percent like "75%") drives placeholder height, set via JS later

## Requirements

### 1.1 — `--zoom` CSS variable and width calc
In `static/style.css`:
1. In the `#app` rule (line 14-18), add `--zoom: 1;` as a custom property.
2. In `.page-container img` (line 37-43), replace `width: 100%;` (line 38) with `width: calc(100% * var(--zoom, 1));`
3. In `.page-placeholder` (line 45-54), add `width: calc(100% * var(--zoom, 1));` alongside the existing `width: 100%` (line 46). The calc value should take precedence.

Use `var(--zoom, 1)` with a fallback of `1` to handle cases where the variable is not yet set.

### 1.2 — Placeholder height via `--page-ratio`
In `.page-placeholder` (line 45-54):
1. Replace `width: 100%;` (line 46) with `width: calc(100% * var(--zoom, 1));`
2. Add `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1));` — this removes the dependency on inline `padding-bottom` (which will be set as `--page-ratio` by JS instead).
3. The width/height ratio is preserved: at zoom=1, `padding-bottom = var(--page-ratio) = ph%`, matching the current inline behavior.

### 1.3 — Column overflow and page-container alignment
1. In `.column` (line 20-25), change `overflow-x: hidden;` (line 23) to `overflow-x: auto;` — so when zoom > 100% (page wider than column), horizontal scrollbar appears.
2. In `.page-container` (line 31-35), change `justify-content: center;` (line 34) to `justify-content: safe center;` — so pages < column width stay centered, but pages > column width align to the left edge (scrollable).

## Files to modify
- `static/style.css` ONLY

## Current file content (relevant sections)
```css
#app {
    display: flex;
    height: 100vh;
    overflow: hidden;
}

.column {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 20px;
}

.page-container {
    margin-bottom: 16px;
    display: flex;
    justify-content: center;
}

.page-container img {
    width: 100%;
    height: auto;
    display: block;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.5);
    border-radius: 2px;
}

.page-placeholder {
    width: 100%;
    background: #333;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #666;
    font-size: 14px;
    border-radius: 2px;
}
```

## Validation
- After changes, verify there are no CSS syntax errors (check the file is valid)
- Confirm `#app` has `--zoom: 1;`
- Confirm `.page-container img` uses `calc(100% * var(--zoom, 1))` for width
- Confirm `.page-placeholder` has `width: calc(100% * var(--zoom, 1))` and `padding-bottom: calc(var(--page-ratio) * var(--zoom, 1))`
- Confirm `.column` has `overflow-x: auto;`
- Confirm `.page-container` has `justify-content: safe center;`

## Output requirements
- Commit with message: `feat: add --zoom CSS variable and zoom-adaptive layout styles`
- Report file: write a summary of changes to `.comet/task-1-css-report.md` in the openspec change directory
