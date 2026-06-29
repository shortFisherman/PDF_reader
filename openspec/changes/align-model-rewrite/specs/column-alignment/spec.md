## ADDED Requirements

### Requirement: Alignment write ownership

The system SHALL make `AlignmentController` the sole writer of `scrollTop` to both the left and right scroll columns. No other frontend module (`scroll-sync`, `zoom`, `app.js`, translator callbacks) SHALL write `scrollTop` of either column directly. Any module needing to drive alignment SHALL route through AlignmentController's public surface (`setLockTarget`, `realign`, `onScroll`, `onImageLoaded`, `onZoomChange`). The `alignment-controller` frontend module SHALL own this logic.

#### Scenario: Translator finish refresh routes through controller

- **WHEN** a page translation finishes and the right-column page image is unloaded then reloaded, finally firing `<img>.onload`
- **THEN** `app.js` SHALL notify AlignmentController via `onImageLoaded(side, pageIndex)` instead of relying on a side-effect scroll event, and AlignmentController SHALL call `realign()` to pull both columns back to the current alignment target without modifying the target.

#### Scenario: Zoom routes through controller

- **WHEN** the user Ctrl+wheel zooms and `zoom.js` finishes applying `--zoom` and the current column's anchor-corrected `scrollTop`
- **THEN** `zoom.js` SHALL notify AlignmentController via `onZoomChange(newZoom, anchor)`, and AlignmentController SHALL rescale the current `intraPageOffsetPx` by `newZoom/oldZoom` and call `realign()` so both columns keep the same alignment target; `zoom.js` SHALL NOT passively rely on a `scroll` event to drag the other column along.

#### Scenario: User scroll updates target and realigns opposite

- **WHEN** the user scrolls either column
- **THEN** `scroll-sync`'s scroll listener (still wired by `app.js`) SHALL delegate to AlignmentController's `onScroll(src)`, which SHALL derive `(pageIndex, intraPageOffsetPx)` from `src`, update the alignment target, set `lockSide = src`, and call `realign()` to write the opposite column's `scrollTop`. The listener SHALL NOT compute or write any proportional `scrollTop` itself.

#### Scenario: No silent alignment writes outside controller

- **WHEN** any frontend module other than `alignment-controller.js` is grep-searched for direct `scrollTop =`
- **THEN** no assignment to `.scrollTop` of either column SHALL remain except inside `alignment-controller.js`.

### Requirement: Alignment target semantics

Alignment target SHALL be a tuple `(pageIndex: integer, intraPageOffsetPx: number)` where `pageIndex` is the page in the viewport and `intraPageOffsetPx` is the pixel offset from the top of that page's container to the viewport top (may be negative when the viewport top is above the page container top). `realign(column)` SHALL compute `column.scrollTop = pageContainer.offsetTop + intraPageOffsetPx`, where `offsetTop` is resolved via `getBoundingClientRect` relative to the column (NOT `scrollHeight`-based fractions), so alignment is robust to differences in total column scrollable height and to placeholder-vs-image height mismatch.

#### Scenario: Page index recovered from source column

- **WHEN** `onScroll(src)` fires for a column showing page N straddling the viewport top
- **THEN** AlignmentController SHALL select `pageIndex = N` when more than half of page N's container intersects the viewport, else the page whose container covers the viewport top center.

#### Scenario: Two columns of differing scrollHeight stay page-aligned

- **WHEN** left and right columns have different `scrollHeight` (e.g. the right column's translated page is 1~2 px shorter than placeholder) and the alignment target is `(N, 30px)`
- **THEN** after `realign()` both columns SHALL show the top of page N offset by 30px from the viewport top, with no residual sub-pixel drift attributable to proportional scrolling.

#### Scenario: Intra-page offset scales with zoom

- **WHEN** zoom changes from `z0` to `z1` while the alignment target is `(N, offsetPx_at_z0)`
- **THEN** AlignmentController SHALL update `intraPageOffsetPx = offsetPx_at_z0 * (z1/z0)`, because page-content pixel heights scale with `--zoom`, so the same visible point remains under the original cursor anchor after realign.

### Requirement: Cross-trigger-source realign entry

`AlignmentController.realign()` SHALL be the single geometric entry that writes `scrollTop`s. `onScroll`, `onImageLoaded`, and `onZoomChange` SHALL all converge on it. `onScroll` is the only trigger that may mutate `currentTarget`; `onImageLoaded` and `onZoomChange` SHALL NOT change `(pageIndex, intraPageOffsetPx)` except `onZoomChange` rescaling the offset as required by "Alignment target semantics".

#### Scenario: Image reload does not drift target

- **WHEN** a translated page image reloads and its rendered height is 1~2 px different from its placeholder
- **THEN** `onImageLoaded` SHALL keep `(pageIndex, intraPageOffsetPx)` unchanged and `realign()` SHALL pull both columns back to the existing target, eliminating the prior "left column higher than right by a bit" drift.

#### Scenario: Reentrant realign guarded

- **WHEN** `realign()` writes a column's `scrollTop` and the resulting `scroll` event fires back into `onScroll`
- **THEN** AlignmentController SHALL detect reentrancy via an internal `realigning` flag and skip the derived-target update for that feedback event; the existing alignment target SHALL remain authoritative.

### Requirement: Settle and page detection ownership

`AlignmentController` SHALL own the settle gate used by `realign()` and page-detection. Real-time alignment (scroll / zoom / image) SHALL run immediately and SHALL NOT be debounced. Page-detection callback `onPageChange` MAY be debounced via settle, as in the prior behavior, to keep the page indicator from jittering near page boundaries.

#### Scenario: Immediate alignment during continuous scroll

- **WHEN** the user drags the scrollbar continuously
- **THEN** both columns SHALL stay aligned on every scroll event (no debounce-induced lag), scrolling settling at the same `pageIndex` and `intraPageOffsetPx`.

#### Scenario: Page indicator still debounced

- **WHEN** the viewport straddles the boundary between page N and N+1 while scrolling momentarily settles near the boundary
- **THEN** the toolbar page indicator SHALL still go through the settle gate (≥ ~150ms of no scroll) before updating, matching the prior stability requirement, and AlignmentController SHALL expose a settle callback hook for this.

### Requirement: Initial-open saved page restore routes through controller

When `app.js` reopens a PDF with a saved `reading-progress` page index, it SHALL align the columns via AlignmentController's `setLockTarget(pageIndex, 0)` followed by `realign()`, instead of bypassing the controller with direct `scrollIntoView`. This keeps the initial alignment target owned by the controller from the very first frame.

#### Scenario: Reopened PDF aligns through controller

- **WHEN** a PDF is reopened and the server returns `saved_page = K`
- **THEN** `app.js` SHALL call `controller.setLockTarget(K, 0)` then `controller.realign()` and SHALL NOT call `scrollIntoView` on the page container directly.