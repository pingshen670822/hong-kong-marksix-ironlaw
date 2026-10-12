# V10 renderer tests

Run from the repository root with Python 3 and Node.js:

```sh
python -m unittest discover -s tests -p 'test_renderer.py' -v
node tests/renderer_expiry.cjs
```

The unittest suite invokes the Node harness automatically when `node` is on
`PATH`. If Node is absent, that one integration test is explicitly skipped.
The standalone Node command uses `python3` to obtain the rendered fixture;
override the executable with `PYTHON=/path/to/python` if needed.

Both suites are deterministic, use synthetic input, and require no network,
browser, deployed site, full historical dataset, or third-party packages.
They do not write a release or modify source data.

## Coverage

- Exact report release metadata, timestamps, and provenance hashes
- Deterministic HTML, anchored sections, responsive-style hooks, and no external assets
- Blank formal selection even when malformed input contains a number
- Separate research ranks, original seals, and the recalculation/seal difference warning
- Correct normal-number `6/49` and special-number `1/49` baselines
- Separate development, evaluation, prospective, and legacy records
- HTML attribute/text escaping and embedded JSON script-end-tag containment
- `fresh_verified` versus `snapshot`; neither is described as continuously live
- Exact 24-hour source expiry and Hong Kong target-day expiry
- Missing, malformed, future, and clock-skewed timestamps
- Unknown target dates, page restoration, tab return, and repeated refresh clicks
- Read-only reload behavior with no network API or service worker

These are structural and behavioral tests. They do not constitute browser visual
QA, official source freshness verification, model qualification, or a claim of
predictive advantage.
