# Contributing

Thanks for helping improve Release Front Page.

## Before opening an issue

- Reduce the problem to a public or synthetic Git fixture. Do not upload private source, tokens, author emails, or unpublished vulnerability details.
- Confirm the behavior on Python 3.11 or newer and include the exact command and error output.
- Use GitHub Private Vulnerability Reporting for security issues.

## Development

The project uses the Python standard library and local Git only.

```bash
python3 -m unittest discover -s tests -v
python3 /path/to/skill-creator/scripts/quick_validate.py skills/release-front-page
python3 /path/to/plugin-creator/scripts/validate_plugin.py .
```

Changes to collectors, renderers, or fixtures must keep output deterministic. Rebuild the sample into a temporary directory and let the test suite compare it with the checked-in artifacts.

## Pull requests

Keep changes focused, add regression tests, document public CLI or JSON-contract changes, and avoid unsupported performance or user-impact claims.
