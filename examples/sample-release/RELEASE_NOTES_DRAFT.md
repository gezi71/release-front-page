# Pipes in\. Legacy flags out\.

> Configuration can now arrive by pipe, while named profiles make the old CLI contract explicit\.

**Evidence:** 3 commits · 7 files changed · +65 / -1

> Draft: verify user impact and migration advice before publishing.

## Highlights

- The CLI now accepts configuration from stdin\. — `6e1dedb`
- Named profiles replace the legacy CLI option\. — `c0f3022`

## Features

- The CLI now accepts configuration from stdin\. — `6e1dedb`

## Fixes

- YAML parsing now preserves \<edge\> values\. — `b3cd40b`

## Breaking Changes

- Named profiles replace the legacy CLI option\. **BREAKING** — `c0f3022`
  - Migration notes: replace \-\-legacy with \-\-profile default

## Limitations

- Sample claims trace to the bundled fixture's commits, code, tests, and migration document\.
- The fixture builder runs the bundled tests; the release collector never executes target\-project code\.
- The release still requires maintainer approval before publication\.
