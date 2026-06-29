# dual-column-reading

## Purpose

Display original and translated PDF page images side-by-side in two synchronized, vertically scrollable columns, providing a continuous reading experience comparable to a web page.
## Requirements
### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization SHALL be **page-aligned with intra-page pixel offset**, owned by the `alignment-controller` frontend module: scrolling either column SHALL derive a `scrollTop`-independent alignment target `(pageIndex, intraPageOffsetPx)` and the other column SHALL be realigned to that target via `AlignmentController.realign()` within the source scroll event handler (no frame deferral). A `realigning` guard SHALL prevent feedback loops without relying on `setTimeout(0)` unlock of a `syncing` flag. The prior `scroll-sync` proportional formula `scrollTop / (scrollHeight - clientHeight)` SHALL NOT be used. The `scroll-sync` frontend module SHALL remain responsible for `createSettleGate` and `setupPageDetection`, but SHALL NOT own the sync algorithm.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Left-driven page-aligned sync

- **WHEN** the user scrolls the left column so that page N's container top sits 30px below the viewport top
- **THEN** the right column SHALL realign synchronously (no frame deferral) to the same `(pageIndex = N, intraPageOffsetPx = 30)` target, regardless of differences in total scrollable height between the two columns, instead of matching a fractional scroll position.

#### Scenario: Right-driven page-aligned sync

- **WHEN** the user scrolls the right column independently so that page N's container top sits 30px below the viewport top
- **THEN** the left column SHALL realign synchronously to `(pageIndex = N, intraPageOffsetPx = 30)`, regardless of differences in total scrollable height, replacing the prior proportional behavior.

#### Scenario: No sync feedback loop

- **WHEN** `realign()` writes the destination column's `scrollTop` and the resulting `scroll` event fires back
- **THEN** AlignmentController SHALL detect the reentrant realign via its `realigning` guard and SHALL NOT re-derive the alignment target from this feedback event; the prior alignment target SHALL remain authoritative.

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

