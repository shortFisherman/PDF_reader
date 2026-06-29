## MODIFIED Requirements

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