## MODIFIED Requirements

### Requirement: Cursor-anchored zoom

The system SHALL anchor zoom at the cursor position so the content point under the cursor remains under the cursor after zooming. For a zoom change from `z0` to `z1` with ratio `r = z1/z0` and cursor offset `(cx, cy)` relative to the active column, the new scroll positions for the active column SHALL be `newScrollTop = (scrollTop + cy) * r - cy` and `newScrollLeft = (scrollLeft + cx) * r - cx`. The `--zoom` variable SHALL be applied before setting the new scroll positions on the active column. After the active column is adjusted, the other column SHALL be realigned by invoking `AlignmentController.onZoomChange(z1, anchor)`; the other column SHALL NOT rely on a `scroll` event to catch up via proportional scroll-sync. AlignmentController SHALL rescale its current `intraPageOffsetPx` by `r` before realigning, per the `column-alignment` capability's "Alignment target semantics".

#### Scenario: Content under cursor stays fixed

- **WHEN** the user positions the cursor over a specific word and zooms in with Ctrl+wheel
- **THEN** that word SHALL remain under the cursor after the zoom completes

#### Scenario: Vertical alignment preserved across columns

- **WHEN** the user zooms with Ctrl+wheel over the left column and the zoom completes
- **THEN** AlignController SHALL realign the right column to the same `(pageIndex, intraPageOffsetPx * r)` target, so both columns remain vertically aligned at the same content point zoom-correctly, instead of being dragged by a residual proportional scroll event.