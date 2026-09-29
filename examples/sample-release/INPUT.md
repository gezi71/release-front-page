# Reproducible sample input

The sample is rebuilt from a deterministic local Git repository with three commits between `v1.4.0` and `v2.0.0`:

- `feat(cli): accept configuration from stdin`
- `fix: preserve <edge> values in YAML`
- `feat(cli)!: replace the legacy option`, with an explicit migration footer

Each claim traces to source, behavioral tests, migration documentation, and the real SHA stored in `release-data.json`. The fixture builder runs the sample project's tests before collecting its history; the release collector itself never executes target-project code. Rebuild every checked-in artifact with:

```bash
python3 examples/sample-release/build_fixture.py --out-dir /tmp/release-front-page-sample
```

The test suite compares that fresh output byte-for-byte with this directory.
