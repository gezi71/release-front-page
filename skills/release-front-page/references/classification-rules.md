# Classification rules

Use these rules after deterministic collection. Classification organizes evidence; it does not prove impact.

## Precedence

1. Put commits with `type!:` or a `BREAKING CHANGE:` footer in **Breaking Changes**.
2. Put explicit migration-only commits in **Migration**.
3. Keep classification separate from front-page promotion. Set `highlight: true` only after evidence review; the renderer never promotes a Feature or Fix automatically and displays at most three explicit highlights.
4. Apply Conventional Commit mappings:

   | Type | Category |
   |---|---|
   | `feat`, `feature` | Features |
   | `fix` | Fixes |
   | `perf` | Performance |
   | `build`, `chore`, `ci`, `refactor`, `style`, `test` | Developer Experience |
   | `docs`, `doc` | Documentation |
   | `migration` | Migration |

5. Put reverts and unmatched messages in **Other** until inspected.

## Evidence checks

- Inspect changed public interfaces, CLI output, documented behavior, or tests before calling a change user-visible.
- Require measurements in the diff, benchmark artifacts, or linked public evidence before claiming a speedup.
- Require an explicit compatibility break before using breaking-change language; a refactor is not automatically breaking.
- Copy migration instructions only from code, tests, public documentation, or an explicit breaking-change footer. Otherwise write `Maintainer migration guidance required`.
- Keep reverts as reverts. Do not present the reverted feature as shipped.
- Treat merge subjects as containers, not independent user value, when their child commits are also present.

## Confidence

- **High:** directly stated and demonstrated by public API changes, tests, or documentation.
- **Medium:** supported by commit subject plus matching diff, but user impact is not demonstrated.
- **Low:** plausible interpretation that needs maintainer confirmation.

Every rewritten summary must retain its commit or PR provenance regardless of confidence.
