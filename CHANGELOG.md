# Changelog

All notable changes to CourseWeave are documented in this file.

## [1.2.0.0] - 2026-08-30

### Added

- Added course workspaces, page-aware textbook parsing, editable chapter review, and resumable background jobs.
- Added evidence-grounded knowledge trees, cross-textbook concept alignment, relation review, and source-page traceability.
- Added hybrid RAG retrieval, teacher-oriented evaluation metrics, and a movable textbook question assistant.
- Added a goal-driven lesson preparation Agent with tool planning, human checkpoints, execution history, and verified deliverables.
- Added a read-only seeded public demo, automated tests, GitHub CI, dependency updates, and secret-pattern checks.

### Changed

- Reworked the interface around four focused areas: textbooks, cross-textbook links, lesson preparation, and contextual RAG.
- Improved chunk boundaries, heading recognition, citation grounding, relation filtering, model availability feedback, and task recovery.

### Fixed

- Prevented front matter, tables of contents, generic headings, broken text, and unsupported claims from entering cross-textbook links.
- Recovered interrupted jobs after service restarts and retried transient SQLite lock failures.
