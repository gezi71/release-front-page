# Output contract

`collect_release.py` writes deterministic UTF-8 JSON with sorted keys and no timestamps, random values, or absolute paths.

## Top-level fields

- `schema_version`: currently `1.0`.
- `version`: caller-supplied display version.
- `repository`: local directory name and a recognizable GitHub origin slug when available; reading the local remote URL does not use the network.
- `range`: original refs, resolved SHAs, and merge inclusion policy.
- `github_enrichment`: whether `--use-gh` was requested, lookup counts, per-PR failures, and a setup `failure_reason` when `gh` is unavailable, logged out, or pointed at a non-GitHub origin. Enrichment failure does not block the offline release package.
- `editorial`: localized `headline` and `dek` values for `en` and `zh-CN`.
- `category_order`: stable render order.
- `summary`: counts for commits, merges, breaking changes, reverts, categories, and net file/addition/deletion totals between the two refs. `change_basis` is `net_ref_diff`; per-commit churn remains available under each commit's `stats`.
- `contributors`: empty unless explicitly enabled; contains display names and counts, never emails.
- `commits`: oldest-first evidence records.
- `limitations`: caveats included in release notes.

## Commit fields

Each commit includes full and short SHA, sanitized subject/body, Conventional Commit type/scope, category, breaking/revert/merge flags, an explicit `highlight` boolean, first-parent file statistics, provenance, localized summaries, confidence, and an optional migration note. Email-shaped text and identity trailers are removed before serialization; do not treat that filter as a substitute for human privacy review.

Agents may edit only these editorial fields without changing collected evidence:

- `editorial.<locale>.headline`
- `editorial.<locale>.dek`
- `commits[].summaries.<locale>`
- `commits[].confidence`
- `commits[].highlight`, only after verifying the item deserves one of at most three lead positions
- `commits[].migration_note`, after verifying it against evidence

Do not alter SHAs, refs, file statistics, sanitized collected messages, or provenance. A PR provenance URL is valid only when it exactly matches the analyzed GitHub repository and PR number.

## Renderer outputs

`render_release.py` always writes:

- `release-data.json`: canonical copy of the structured input
- `RELEASE_NOTES_DRAFT.md`: provenance-bearing Markdown draft
- `release-front-page.html`: responsive, printable, self-contained HTML
- `release-front-page.svg`: 1600×1000 self-contained front page
- `release-social-card.svg`: 1200×630 self-contained share card

HTML and SVG use system fonts and contain no remote scripts, fonts, or images. PNG export is intentionally outside the offline core; use a browser only as an explicitly approved enhancement.

The renderer accepts only schema `1.0`, validates required fields, SHA/statistic/provenance consistency, rejects an input/output collision, and writes each file atomically. The JSON schema version is independent from the repository's semantic version.
