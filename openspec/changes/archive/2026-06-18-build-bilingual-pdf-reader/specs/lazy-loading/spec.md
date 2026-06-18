## ADDED Requirements

### Requirement: Viewport-based image loading

The system SHALL load page images only when they enter or are near the browser viewport, deferring loading of off-screen pages.

#### Scenario: Initial page load

- **WHEN** the dual-column view first renders
- **THEN** only page images within the viewport plus a buffer of 5 pages above and below SHALL be loaded

#### Scenario: Scroll reveals new pages

- **WHEN** the user scrolls such that a previously unloaded page enters the buffer zone
- **THEN** the system SHALL load that page's image within 200ms of entering the buffer

#### Scenario: Scroll-away unloading

- **WHEN** a page image scrolls more than 10 pages away from the viewport
- **THEN** the system MAY unload its image to free memory, replacing it with a placeholder

### Requirement: IntersectionObserver implementation

The system SHALL use the browser's IntersectionObserver API to detect which page elements are near the viewport.

#### Scenario: Observer setup

- **WHEN** the dual-column view initializes
- **THEN** the system SHALL create an IntersectionObserver with rootMargin set to load pages within 5 page-heights of the viewport

#### Scenario: Placeholder dimensions

- **WHEN** a page image has not yet been loaded
- **THEN** the system SHALL display a placeholder element with the correct aspect ratio (based on the page dimensions) to maintain scroll position accuracy

### Requirement: Large PDF support

The system SHALL support PDF documents with up to 1000 pages without degrading browser performance.

#### Scenario: 1000-page document

- **WHEN** a 1000-page PDF is opened
- **THEN** the browser SHALL maintain scrolling at 30+ FPS and memory usage below 500 MB

#### Scenario: Memory management

- **WHEN** total loaded images exceed 50 pages
- **THEN** the system SHALL unload images furthest from the viewport to stay within memory limits
