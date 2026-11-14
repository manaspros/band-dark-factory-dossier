# Stage 1 black-box acceptance tests

These tests exercise the Stage 1 HTTP contract without importing application code. Start the
service with provider configuration, then run:

```sh
python -m pip install pytest requests
DOSSIER_BASE_URL=http://127.0.0.1:8080 python -m pytest -q acceptance/stage-1
```

The suite resets service state before each test; use a disposable instance. Provider-accounting
tests need the documented mock web admin API. Set `DOSSIER_MOCK_URL` to its origin and
`DOSSIER_MOCK_TOKEN` to its admin token. Tests requiring those values skip when absent.

## Coverage

| Test area | Matrix rows |
|---|---|
| Domain normalization, create/read/refresh | R47–R48, R135, R142–R143, R146 |
| Authentication precedence and idempotency cases | R99–R119 |
| Reset atomicity, clock and export/import round trips | R28–R40, R45, R161–R176 |
| Listing filters, ordering and pagination | R44, R147–R151 |
| Build field/state and citation shape | R120, R126, R136–R141, R171–R172 |
| Spend, bare-domain search and citation provenance | R1–R2, R61–R63, R141, R159 |

The fixed sample provider corpus does not let this black-box suite inject arbitrary prose, so
it does not independently exercise every Appendix A tokenization/value-format edge (R183–R212).
It checks that each emitted citation came from the named provider's served text, lies in the
page prose, is bounded, and is a single sentence; the cited value's full Appendix A support
decision remains uncovered here. Fast-regime 10-second timing and live-provider 30/120/300-second
behavior (R127–R130) are also not asserted because timing against an externally configured
service would be nondeterministic. These should be reported as coverage gaps, not treated as
passed by this suite.

Each test docstring lists its specific matrix rows. The mock-log checks for spend and exact
bare-domain search require the optional mock variables above. This is a black-box suite; it
does not run the repository harness or inspect application source.
