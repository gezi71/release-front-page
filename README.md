# Release Front Page

**Turn a Git ref range into evidence-backed release notes, a printable newspaper front page, and a share card—without publishing anything.**

[中文](README.zh-CN.md)

![A generated newspaper front page for the fixed sample release](examples/sample-release/release-front-page.svg)

Commit logs are excellent evidence and terrible front pages. Release Front Page keeps the evidence, then gives an agent a disciplined editorial workflow for translating it into user-facing release material.

```text
BEFORE                                      AFTER
feat(cli): accept configuration from stdin  The CLI now accepts configuration from stdin. · 6e1dedb
fix: preserve <edge> values in YAML         YAML parsing preserves <edge> values. · b3cd40b
feat(cli)!: replace the legacy option       BREAKING + a verified migration note · c0f3022
```

The image above is generated from a [reproducible real Git fixture](examples/sample-release/build_fixture.py), not a mockup. The fixture builder runs its behavioral tests, then its commits, source, migration document, JSON, Markdown, HTML, and SVG are rebuilt byte-for-byte in CI.

## What it produces

- `release-data.json`: deterministic evidence and localized editorial fields
- `RELEASE_NOTES_DRAFT.md`: reviewable notes with SHA/PR provenance
- `release-front-page.html`: responsive, printable, self-contained HTML
- `release-front-page.svg`: a 1600×1000 newspaper front page
- `release-social-card.svg`: a 1200×630 share card

English and Simplified Chinese render from the same JSON contract. The core needs only Python 3.11+ and local Git; it does not need Node, a browser, network access, an API key, or third-party Python packages.

## Install

### Codex marketplace

Pin the repository marketplace to this release, then install **Release Front Page** from the Codex Plugins page:

```bash
codex plugin marketplace add gezi71/release-front-page --ref v1.0.0
```

### Cross-agent Skills CLI

This path requires Node.js and network access:

```bash
npx skills add gezi71/release-front-page --skill release-front-page -g -a codex -y
```

### Local development

Clone this repository, then copy the Skill to the current cross-agent Skill directory:

```bash
mkdir -p "$HOME/.agents/skills"
cp -R skills/release-front-page "$HOME/.agents/skills/release-front-page"
```

Then ask:

```text
Use $release-front-page to compare v1.4.0..v2.0.0 and prepare English
release notes plus a broadsheet front page. Do not publish anything.
```

## Use the offline scripts directly

Collect facts from a local repository:

```bash
python3 skills/release-front-page/scripts/collect_release.py \
  --repo /path/to/repository \
  --from v1.4.0 \
  --to v2.0.0 \
  --version v2.0.0 \
  --output release-data.json
```

Review the JSON and verify user-facing claims against the diff. Then render it:

```bash
python3 skills/release-front-page/scripts/render_release.py \
  --input release-data.json \
  --out-dir release-package \
  --locale en \
  --theme broadsheet
```

Available render choices are `en` / `zh-CN` and `broadsheet` / `modern`. Merge commits and contributor display names are opt-in. Public PR enrichment is also opt-in through `--use-gh`; it is the only core path that may use the network. If `gh` is missing, logged out, or unsuitable for the origin, the offline package still succeeds and records the reason in `github_enrichment.failure_reason`.

Rebuild the checked-in release package from its deterministic Git history with:

```bash
python3 examples/sample-release/build_fixture.py --out-dir examples/sample-release
```

## Evidence before adjectives

The collector performs deterministic extraction and conservative Conventional Commit classification. Every commit starts with `highlight: false`; only an evidence review may explicitly promote up to three lead stories. The Skill tells the agent to inspect diffs before rewriting summaries, retain provenance on every major statement, keep internal refactors internal, and mark unsupported claims for maintainer review.

| Claim | Required evidence |
|---|---|
| User-visible feature | Public interface, test, or documentation change |
| Performance improvement | Measurements or linked benchmark evidence |
| Breaking change | Explicit contract break or `BREAKING CHANGE` footer |
| Migration instruction | Verified code, tests, docs, or explicit footer |
| Security impact | Already-public evidence and maintainer approval |

This complements tools such as [git-cliff](https://github.com/orhun/git-cliff) and [Release Drafter](https://github.com/release-drafter/release-drafter). Those tools are strong deterministic changelog foundations; Release Front Page adds evidence-aware editorial review and visual delivery instead of replacing Git data.

## Supported scope

- Local Git ranges, branches, tags, Conventional Commits, reverts, optional merges, net range statistics, and per-commit first-parent statistics
- Features, fixes, performance, developer experience, documentation, breaking changes, migrations, highlights, and uncategorized work
- English and Simplified Chinese copy from one structured source
- Markdown, self-contained HTML, and self-contained SVG

## Limits

- A commit message and diff can support a claim, but cannot prove how users experienced it.
- Non-Conventional Commit messages may remain in `Other` until an agent or maintainer reviews them.
- Merge file statistics compare the merge result with its first parent.
- PR lookup is unavailable offline and deliberately disabled unless `--use-gh` is passed.
- PR provenance is accepted only when its exact GitHub URL belongs to the analyzed repository. Enrichment requests, successes, and failures remain visible in JSON.
- Email-shaped text and identity trailers are removed from collected commit prose. Contributor names are opt-in, but every draft still needs a privacy review.
- The renderer accepts JSON schema `1.0`; this contract version is maintained separately from release `v1.0.0`.
- Generated files are drafts. The tool never edits a CHANGELOG, creates a tag, publishes a GitHub Release, or pushes a remote branch.
- PNG export is optional and intentionally outside the browser-free core.

## Development

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/skill-creator/scripts/quick_validate.py skills/release-front-page
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

The test suite creates temporary Git repositories covering features, fixes, breaking changes, documentation, reverts, merges, empty ranges, invalid refs, Unicode, contributor privacy, schema and provenance rejection, deterministic output, long releases, and XML validity.

See [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) before publishing or contributing.

## License

[MIT](LICENSE)
