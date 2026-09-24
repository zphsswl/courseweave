# Changelog

All notable changes to CourseWeave are documented in this file.

## [1.2.1.0] - 2026-09-24

### Added

- Expanded the fixed teacher-question benchmark from 50 to 100 questions: 80 answerable questions (including 15 cross-textbook comparisons) and 20 out-of-domain rejection checks.
- Added a reproducible benchmark runner with suite hashing, corpus metadata, per-question outcomes, category summaries, and Markdown/JSON reports that exclude textbook source text.

### Changed

- Separated Recall@8 coverage from Precision@3 citation relevance so the scorecard measures “finding enough evidence” and “citing relevant evidence” independently.
- Improved Chinese teacher-query parsing by removing question scaffolding and normalizing punctuation variants inside medical terms.
- Updated the quality dashboard and project documentation for benchmark suite v2.

### Results

- On the current 7-textbook, 6,498-chunk corpus: Recall@8 100% (80/80), Precision@3 85.83% (206/240), cross-textbook coverage 100% (15/15), and out-of-domain rejection 100% (20/20).

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
