# lazy-loading

## Purpose

Support 1000-page PDFs without degrading browser performance by loading page images only when they approach the viewport. Uses IntersectionObserver with a 5-page buffer and automatic unloading of distant pages.
## Requirements
### Requirement: Viewport-based image loading

The system SHALL load page images only when the page is near the browser viewport AND the document is not actively being scrolled by a drag/fast gesture. Loading SHALL be gated by a "scroll-settled" state: a scroll event marks the document unstable and resets a settle timer (~150ms); images are loaded only after the timer fires (document stable). While unstable, the lazy-loader SHALL record pages needing load but SHALL NOT issue requests for pages merely swept past. The IntersectionObserver logic SHALL reside in the `lazy-loader` frontend module.

#### Scenario: Initial page load

- **WHEN** the dual-column view first renders
- **THEN** only page images within the viewport plus a small buffer (approximately 2 pages above and below) SHALL be loaded

#### Scenario: Scroll reveals new pages while reading

- **WHEN** the user scrolls slowly such that a previously unloaded page enters the buffer zone and scrolling settles (no scroll event for ~150ms)
- **THEN** the system SHALL load that page's image

#### Scenario: Long-distance scrollbar drag discards swept pages

- **WHEN** the user drags the scrollbar from page 1 toward page 500, sweeping many pages through the buffer
- **THEN** the system SHALL NOT issue page requests for the swept intermediate pages, and after scrolling settles SHALL load only the pages in the landing viewport plus buffer (≤ ~5 requests)

### Requirement: IntersectionObserver implementation

The system SHALL use the browser's IntersectionObserver API to detect which page elements are near the viewport, implemented in the `lazy-loader` module. The observer's `rootMargin` SHALL define a small buffer (approximately 2 page-heights), smaller than the prior 5-page buffer to reduce landing-page request volume.

#### Scenario: Observer setup

- **WHEN** the dual-column view initializes
- **THEN** the `lazy-loader` module SHALL create an IntersectionObserver with a small buffer rootMargin (approximately 2 page-heights) and SHALL only act on intersection changes when the document is settled

#### Scenario: Placeholder dimensions

- **WHEN** a page image has not yet been loaded
- **THEN** the system SHALL display a placeholder element with the correct aspect ratio (based on the page dimensions) to maintain scroll position accuracy

### Requirement: Large PDF support

The system SHALL support PDF documents with up to 1000 pages without degrading browser performance.

#### Scenario: 1000-page document scrollbar jump

- **WHEN** a 1000-page PDF is opened and the user drags the scrollbar from the first to the 500th page
- **THEN** the browser SHALL maintain responsiveness and the number of `/api/page/*` requests during the gesture SHALL be bounded (≤ ~5) rather than proportional to pages swept

#### Scenario: Memory management

- **WHEN** total loaded images exceed 50 pages
- **THEN** the system SHALL unload images furthest from the viewport (after settle) to stay within memory limits

### Requirement: Symmetric debounced unload

The system SHALL NOT unload a page image the instant it leaves the buffer. Unloading SHALL be deferred until the scroll-settled state is reached AND the page remains outside the viewport and buffer. The load/unload decision SHALL share a single scroll-settled gate so that boundary jitter cannot trigger a load→unload→load cycle.

#### Scenario: Page temporarily leaves buffer during a slow scroll

- **WHEN** a loaded page briefly crosses outside the buffer during continued scrolling and re-enters within one settle interval
- **THEN** the system SHALL NOT unload and reload it (no oscillation, no duplicate request)

#### Scenario: Scroll-away unloading after settle

- **WHEN** a loaded page remains more than 10 pages away from the viewport after the document settles
- **THEN** the system MAY unload its image to free memory, replacing it with a placeholder whose load state is reset

### Requirement: Container-level load state guards

The system SHALL track the loaded state on the `page-container` element (e.g. `dataset.loaded`), not on the placeholder. The `<img>` SHALL not replace the placeholder until `onload` fires, so an in-flight image never causes a height change or duplicate load. A page with `dataset.loaded === 'true'` SHALL NOT be re-requested.

#### Scenario: Duplicate load suppression

- **WHEN** an already-loaded page re-enters the buffer
- **THEN** the system SHALL NOT issue another request for that page

#### Scenario: Image load does not change layout

- **WHEN** a page image finishes loading
- **THEN** the placeholder SHALL be replaced by the `<img>` without changing the page-container's rendered height

