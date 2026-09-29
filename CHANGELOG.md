# Changelog

All notable changes to this project are documented here.

## [1.0.0] - 2026-07-22

### Added

- Offline Git-range collection with Conventional Commit, breaking-change, revert, merge, and optional contributor evidence.
- English and Simplified Chinese release notes, self-contained HTML, newspaper SVG, and social-card SVG.
- Explicit editorial highlights, provenance validation, privacy-preserving commit collection, and reproducible sample history.
- Batched NUL-delimited Git metadata and filename-safe numstat parsing, plus non-blocking audit records for optional `gh` setup failures.
- Agent Skill and Codex Plugin distribution metadata.

### Security

- Email-shaped commit text and identity trailers are removed from collected prose.
- Markdown output escapes untrusted commit data, and PR links are restricted to the matching GitHub repository.

### Known limitations

- Generated copy remains a maintainer-reviewed draft.
- Optional PR enrichment requires explicit `--use-gh`, an authenticated `gh`, and network access.
