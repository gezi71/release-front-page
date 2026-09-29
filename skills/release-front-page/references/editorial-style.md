# Editorial style

## Voice

Write for users, not the Git log. Prefer concrete verbs and named behavior. Keep a newspaper-like sense of occasion in headlines while keeping body copy factual.

- Good: `The CLI now accepts configuration from stdin (a1b2c3d).`
- Avoid: `Revolutionary configuration makes workflows dramatically faster.`
- Good: `Internal cache handling was reorganized; no user-visible change is documented (d4e5f6a).`
- Avoid: `A faster, more reliable cache.`

## Headline and deck

- Make the headline short enough for two lines on the front page.
- Make the deck a one- or two-sentence factual release summary.
- Do not put unverified metrics, superlatives, or security details in either.
- Keep version names verbatim.

## Sections

- Lead with at most three changes supported by the strongest evidence by setting only those commits to `highlight: true`.
- Separate breaking changes from features, even when the same commit supplies both.
- Put required actions in migration notes; never hide them in marketing prose.
- Describe documentation and developer-experience work without inflating it into end-user functionality.
- Retain short SHA or PR provenance on every bullet.

## Bilingual data

Store localized headline/deck values under `editorial.en` and `editorial.zh-CN`. Store localized commit summaries under each commit's `summaries` object. Translate meaning, not commit syntax. If a translation cannot be verified, retain the original subject rather than inventing detail.

Humor may decorate the edition, never alter the facts or mock contributors.
