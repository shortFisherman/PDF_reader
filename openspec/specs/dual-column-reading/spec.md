# dual-column-reading

## Purpose

Display original and translated PDF page images side-by-side in two synchronized, vertically scrollable columns, providing a continuous reading experience comparable to a web page.
## Requirements
### Requirement: Two synchronized scrollable columns

The system SHALL display original and translated PDF pages side by side in two vertically scrollable columns. Scroll synchronization logic SHALL reside in a dedicated `scroll-sync` frontend module; behavior SHALL remain identical to the pre-refactor implementation.

#### Scenario: Initial layout

- **WHEN** a user opens a PDF
- **THEN** the system SHALL display two identical columns, each showing all pages of the original PDF stacked vertically, with the left column labeled as original and the right column as translation target

#### Scenario: Scroll synchronization

- **WHEN** the user scrolls the left column
- **THEN** the right column SHALL automatically scroll to match the left column's scroll position within 50ms

#### Scenario: Independent scroll

- **WHEN** the user scrolls the right column independently
- **THEN** the left column SHALL NOT be affected

### Requirement: Page-level image display

The system SHALL display each page as an individual image stacked vertically, creating a continuous scrollable reading experience.

#### Scenario: Continuous scroll through pages

- **WHEN** the user scrolls through the document
- **THEN** page images SHALL appear in sequential order without gaps, mimicking a continuous document view

### Requirement: Floating toolbar

The system SHALL provide a floating toolbar that remains visible during scrolling.

#### Scenario: Toolbar visibility

- **WHEN** the user scrolls through the document
- **THEN** a floating toolbar SHALL remain fixed at the bottom of the viewport, displaying the current page number and a translation trigger button

#### Scenario: Page indicator

- **WHEN** the user scrolls such that page N occupies more than 50% of the viewport
- **THEN** the toolbar SHALL display "Page N" as the current page, computed by the `scroll-sync` module's page detection

