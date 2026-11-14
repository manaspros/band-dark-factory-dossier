# Stage 4 black-box acceptance suite

These pytest checks use the documented HTTP API, optional provider mock call log/fault controls,
and browser UI. They do not inspect or import Stage 4 implementation code.

Run from the repository root against a disposable Stage 4 service:

```sh
PYTHONDONTWRITEBYTECODE=1 DOSSIER_BASE_URL=http://127.0.0.1:8080 python -m pytest -p no:cacheprovider -q acceptance/stage-4
```

The service must be running and expose `/_test/reset`, `/_test/export`, and `/_test/import`.
`DOSSIER_MOCK_URL` and `DOSSIER_MOCK_TOKEN` enable optional provider-call and fault tests. The
abrupt restart test is opt-in: set `DOSSIER_CONTAINER` to the exact disposable container name;
it skips with a clear reason if unset or not inspectable. The browser test skips if Playwright is
not installed (install Playwright and Chromium in a throwaway environment if needed).

## Coverage map

| Test | Matrix rows |
|---|---|
| `test_batch_domain_validation` | F59-F61 |
| `test_batch_budget_validation_precedence` | F62-F63 |
| `test_wrong_typed_domains_use_malformed_request` | F60, D4-9 |
| `test_batch_idempotency_and_owner_scoping` | F2, F56-F58 |
| `test_concurrent_same_key_starts_one_batch` | F2, F57 |
| `test_batch_requires_idempotency_key` | F57 |
| `test_existing_domain_is_returned_in_order_without_batch_spend` | F64-F65 |
| `test_shared_budget_and_per_build_ceiling` | F3, F66-F69, D4-10 |
| `test_all_fields_expose_origin_corroboration_and_investor_members` | F18-F25, F29-F49 |
| `test_values_include_stage4_keys_computed_at_true_at` | F20, F50, D4-5 |
| `test_investors_section_is_visible_on_dossier_and_evidence_screens` | F54 |
| `test_public_dossier_shell_contains_no_dossier_evidence` | E19, F54 |
| `test_research_failure_falls_back_to_search_and_extract` | F70-F72 |
| `test_rate_limited_exact_domain_search_retries_and_refusals_cost_nothing` | F70, F74 |
| `test_all_provider_calls_failed_is_failed_and_refusals_are_free` | F73-F74 |
| `test_older_stage_imports_make_investors_unknown_without_history` | F34, F81, F84-F85 |
| `test_stage3_export_round_trip_preserves_history_feed_and_candidate_origins` | F27-F28, F81-F84 |
| `test_committed_state_survives_kill_and_running_build_is_terminal` | F75-F80 |
| `test_successful_identical_provider_requests_are_not_repeated` | F3, F16-F17, F86 |

The same tests also exercise the field shapes (`F19-F20`, `F34`), investor citation ordering
and member selection (`F43-F50`), error cost accounting (`F74`), and public data-free HTML
shell (`E19`).

## Coverage limits

There is no public page-text injection API. This suite cannot deterministically synthesize
arbitrary `Registrant`, `Canonical`, or `First-Published-By` headers, canonical cycles/fourth
hops/unserved originals, hand-authored multi-origin history walks, or controlled investor
excerpts. Those parser and origin-precedence edges remain verified only by the audited plan's
internal tests, not by this holdout suite. Runtime corpus responses are used for API invariants.
The restart test checks terminal recovery after killing the named service container; whether a
build is still in flight at the instant of the kill depends on the configured provider/mock.
