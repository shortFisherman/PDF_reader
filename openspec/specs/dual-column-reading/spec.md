# dual-column-reading

## Purpose

Display original and translated PDF page images side-by-side in two synchronized, vertically scrollable columns, providing a continuous reading experience comparable to a web page.
## Requirements
### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization SHALL be **bidirectional and proportional**: scrolling either column SHALL synchronize the other column to the same fractional scroll position, computed as `scrollTop / (scrollHeight - clientHeight)`. Synchronization SHALL be throttled with `requestAnimationFrame` and guarded by a `syncing` flag to prevent feedback loops. The `scroll-sync` frontend module SHALL own this logic.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Left-driven proportional sync

- **WHEN** the user scrolls the left column to a fractional position `f` (0 ≤ f ≤ 1)
- **THEN** the right column SHALL synchronize to the same fractional position `f` within one animation frame, regardless of small differences in total scrollable height

#### Scenario: Right-driven proportional sync

- **WHEN** the user scrolls the right column independently to a fractional position `f`
- **THEN** the left column SHALL synchronize to the same fractional position `f` within one animation frame (replacing the prior left-only behavior)

#### Scenario: No sync feedback loop

- **WHEN** synchronization writes the target column's `scrollTop`
- **THEN** the resulting scroll event SHALL NOT trigger a reverse synchronization back to the source column

### Requirement: Page-level image display

The system SHALL display each page as an individual image stacked vertically, creating a continuous scrollable reading experience. A loaded page image SHALL fill the column width (`width: 100%`) so its rendered height equals the placeholder's reserved height; loading an image SHALL NOT change the page-container's height, preventing misalignment where one column inadvertently displays two cropped pages.

#### Scenario: Continuous scroll through pages

- **WHEN** the user scrolls through the document
- **THEN** page images SHALL appear in sequential order without gaps, mimicking a continuous document view

#### Scenario: Image load preserves alignment

- **WHEN** a page image finishes loading in one column while the corresponding page in the other column is still a placeholder (or vice versa)
- **THEN** both columns SHALL remain aligned to the same page, with no height jump and no extra page pushed partially into the viewport

### Requirement: Floating toolbar

The system SHALL provide a floating toolbar that remains visible during scrolling.

#### Scenario: Toolbar visibility

- **WHEN** the user scrolls through the document
- **THEN** a floating toolbar SHALL remain fixed at the bottom of the viewport, displaying the current page number and a translation trigger button

#### Scenario: Page indicator

- **WHEN** the user scrolls such that page N occupies more than 50% of the viewport
- **THEN** the toolbar SHALL display "Page N" as the current page, computed by the `scroll-sync` module's page detection, and the indicator SHALL be stable (not jittering between adjacent pages) when scrolling momentarily settles at a page boundary

