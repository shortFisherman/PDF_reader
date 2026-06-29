# page-zoom Specification

## Purpose
TBD - created by archiving change ctrl-wheel-zoom. Update Purpose after archive.
## Requirements
### Requirement: Ctrl+wheel page zoom

The system SHALL allow the user to zoom the dual-column page view by holding Ctrl and rolling the mouse wheel. A wheel event SHALL trigger zoom only when `e.ctrlKey` is true; when Ctrl is not held, the wheel SHALL behave as normal scrolling (no zoom, no `preventDefault` on the native scroll). The zoom SHALL be applied by changing the rendered width of page images and placeholders (via a CSS `--zoom` variable), NOT by CSS `transform: scale`, so that layout flow (`scrollHeight`) changes and existing scroll-sync / page-detection geometry remains valid. The `zoom` frontend module SHALL own this logic.

#### Scenario: Zoom in with Ctrl+wheel

- **WHEN** the user holds Ctrl and scrolls the wheel upward over a column
- **THEN** the zoom level SHALL increase by one step (10%), applied to both columns, and the page images/placeholders SHALL render wider by the new factor

#### Scenario: Zoom out with Ctrl+wheel

- **WHEN** the user holds Ctrl and scrolls the wheel downward over a column
- **THEN** the zoom level SHALL decrease by one step (10%), applied to both columns, and the page images/placeholders SHALL render narrower by the new factor

#### Scenario: Normal scroll unaffected when Ctrl not held

- **WHEN** the user scrolls the wheel without holding Ctrl over a column
- **THEN** the column SHALL scroll normally and the zoom level SHALL NOT change, and the native scroll SHALL NOT be prevented

### Requirement: Zoom range and step

The system SHALL constrain zoom to the range 25%–400% inclusive, in steps of 10%. A wheel notch that would exceed the upper or lower bound SHALL clamp to the bound and have no further effect (no overshoot, no scrolling past the bound).

#### Scenario: Upper bound clamping

- **WHEN** the zoom is at 400% and the user zooms in further with Ctrl+wheel
- **THEN** the zoom SHALL remain at 400% and no additional increase SHALL occur

#### Scenario: Lower bound clamping

- **WHEN** the zoom is at 25% and the user zooms out further with Ctrl+wheel
- **THEN** the zoom SHALL remain at 25% and no additional decrease SHALL occur

### Requirement: Cursor-anchored zoom

The system SHALL anchor zoom at the cursor position so the content point under the cursor remains under the cursor after zooming. For a zoom change from `z0` to `z1` with ratio `r = z1/z0` and cursor offset `(cx, cy)` relative to the active column, the new scroll positions for the active column SHALL be `newScrollTop = (scrollTop + cy) * r - cy` and `newScrollLeft = (scrollLeft + cx) * r - cx`. The `--zoom` variable SHALL be applied before setting the new scroll positions on the active column. After the active column is adjusted, the other column SHALL be realigned by invoking `AlignmentController.onZoomChange(z1, anchor)`; the other column SHALL NOT rely on a `scroll` event to catch up via proportional scroll-sync. AlignmentController SHALL rescale its current `intraPageOffsetPx` by `r` before realigning, per the `column-alignment` capability's "Alignment target semantics".

#### Scenario: Content under cursor stays fixed

- **WHEN** the user positions the cursor over a specific word and zooms in with Ctrl+wheel
- **THEN** that word SHALL remain under the cursor after the zoom completes

#### Scenario: Vertical alignment preserved across columns

- **WHEN** the user zooms with Ctrl+wheel over the left column and the zoom completes
- **THEN** AlignController SHALL realign the right column to the same `(pageIndex, intraPageOffsetPx * r)` target, so both columns remain vertically aligned at the same content point zoom-correctly, instead of being dragged by a residual proportional scroll event.

### Requirement: Synchronized zoom across columns

The system SHALL apply the same zoom factor to both the left (original) and right (translated) columns simultaneously. Both columns SHALL use the same `--zoom` value.

#### Scenario: Both columns zoom together

- **WHEN** the user zooms in or out with Ctrl+wheel over either column
- **THEN** both columns SHALL display at the same new zoom factor

### Requirement: Zoom indicator and reset control

The floating toolbar SHALL display the current zoom level as a percentage (e.g. "120%"), updated in real time as zoom changes. The toolbar SHALL provide a reset control that, when activated, returns the zoom to 100%.

#### Scenario: Zoom percentage displayed

- **WHEN** the zoom level changes to 130%
- **THEN** the toolbar zoom indicator SHALL display "130%"

#### Scenario: Reset to 100%

- **WHEN** the user activates the reset control while zoomed to a non-100% level
- **THEN** the zoom SHALL return to 100% and the indicator SHALL display "100%"

#### Scenario: Reset preserves current view

- **WHEN** the user activates the reset control while zoomed to a non-100% level
- **THEN** the zoom SHALL return to 100% anchored at the viewport center (ratio `r = 1/oldZoom`, anchor `(clientWidth/2, clientHeight/2)`), so the content currently at the center of the viewport SHALL remain at the center and the reading position SHALL be preserved

#### Scenario: Initial zoom indicator

- **WHEN** a PDF is opened
- **THEN** the toolbar zoom indicator SHALL display "100%"

### Requirement: Aspect-ratio-preserving placeholder under zoom

Placeholders for not-yet-loaded pages SHALL preserve the page aspect ratio at any zoom factor. The placeholder SHALL reserve height via `padding-bottom: calc(var(--page-ratio) * var(--zoom))` and width via `width: calc(100% * var(--zoom))`, where `--page-ratio` is the per-document height/width percentage. Both the `createPageEl` and the lazy-loader's `unloadPageImage` placeholder creation SHALL set `--page-ratio` (not an inline `padding-bottom`) so the CSS-driven zoom scales width and height proportionally.

#### Scenario: Placeholder keeps aspect ratio when zoomed

- **WHEN** the zoom changes to 200% and a page is still a placeholder
- **THEN** the placeholder's rendered width and height SHALL both scale by 2x, preserving the original page aspect ratio

#### Scenario: Reloaded placeholder honors current zoom

- **WHEN** a loaded page image is unloaded (replaced by a placeholder) while zoom is not 100%
- **THEN** the new placeholder SHALL render at the current zoom factor with the correct aspect ratio

### Requirement: Horizontal overflow for zoomed-in pages

When zoom makes a page wider than its column, the column SHALL allow horizontal scrolling to reveal the overflowed content. The page-container SHALL use `justify-content: safe center` so that narrower-than-column pages remain centered while wider-than-column pages are reachable from their left edge via horizontal scroll.

#### Scenario: Zoomed-in page is horizontally scrollable

- **WHEN** the zoom exceeds 100% such that the page image is wider than the column
- **THEN** the column SHALL permit horizontal scrolling to view the full page width

#### Scenario: Zoomed-out page remains centered

- **WHEN** the zoom is below 100% such that the page image is narrower than the column
- **THEN** the page SHALL remain centered within the column with no horizontal scrollbar

