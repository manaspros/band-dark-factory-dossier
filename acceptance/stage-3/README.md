# Stage 3 black-box acceptance checks

Run from the repository root against a disposable running Stage 3 service:

```sh
python -m pip install pytest requests
PYTHONDONTWRITEBYTECODE=1 DOSSIER_BASE_URL=http://127.0.0.1:8080 python -m pytest -p no:cacheprovider -q acceptance/stage-3
```

The suite resets the service before each test using `POST /_test/reset`. Set
`DOSSIER_TEST_DOMAIN` to another domain in the configured test corpus if needed. When
`DOSSIER_MOCK_URL` and `DOSSIER_MOCK_TOKEN` are set, optional assertions inspect the
documented mock admin call log and enable refusal/429 tests. To run the destructive restart
check, set `DOSSIER_CONTAINER` to the exact disposable container name; that test runs
`docker kill` and `docker start` on that container. It is skipped with a reason when unset
or when Docker cannot inspect the named container.

## Coverage

| Test | Matrix rows / requirements |
|---|---|
| `test_fields_candidates_and_executives_follow_the_public_shape` | T7-T8, T11, T13, T15-T21, Stage 2 selection/status/citation rules |
| `test_candidate_true_from_matches_rendered_page_headers_when_mock_log_is_available` | T3-T4, T7, T14, rendered text provenance |
| `test_candidate_learned_at_is_first_gather_and_retrieved_at_is_current_build_time` | T5-T7, T20 |
| `test_fields_and_candidates_have_no_future_timestamps` | T5-T8, T20 |
| `test_initial_history_records_values_without_initial_feed_entries` | T23-T31, T46-T51 |
| `test_unchanged_selected_values_add_no_history_or_feed_entry` | T25-T31, T49-T51 |
| `test_feed_sequence_is_unique_monotonic_and_since_limit_page` | T49-T53 |
| `test_simultaneous_executive_title_changes_are_one_aggregate_entry` | T23, E3-7, T50-T51 |
| `test_failed_refresh_preserves_last_ready_fields_history_and_feed` | T29-T31, failed-build behavior |
| `test_concurrent_refreshes_do_not_duplicate_feed_entries` | T2, T50, T66 |
| `test_as_of_instant_ties_choose_last_build_and_include_all_spend` | T32-T37, equal instants with different RFC 3339 offsets |
| `test_as_of_rejects_missing_offset_and_values_validate_dates` | T38-T45, query validation |
| `test_as_of_not_found_before_any_ready_build_and_new_routes_require_auth` | T37, T44, T48, T54 |
| `test_values_response_has_seven_fields_and_null_value_shape` | T40-T45, T22 |
| `test_stage1_shaped_import_rebuilds_candidates_and_keeps_token_replay` | T55-T60, T65; Stage 1 token/idempotency preservation |
| `test_stage2_shaped_import_preserves_candidates_spend_and_migrates_times` | T55-T65, DEV-S3a/DEV-S3b/U4 |
| `test_stage3_export_import_round_trip_keeps_builds_history_and_feed` | T58, Stage 1 export/import preservation rules |
| `test_null_researched_at_stage1_and_stage2_imports_keep_spend_and_wait_for_ready` | T59-T61, DEV-S3a null-time case |
| `test_build_budget_and_research_domain_search` | T75, Stage 1/2 budget and exact-domain search rules |
| `test_429_is_free_and_retried_after_rate_limit_interval` | Stage 1/2 429 retry ruling |
| `test_non_429_refused_exact_domain_search_is_bounded_and_build_survives` | Stage 1/2 refusal containment and exact-search attempt cap |
| `test_committed_state_survives_container_kill_and_start` | T67-T74 restart durability |

## Observable limits

The public service API does not accept custom page prose. Therefore this suite cannot
independently synthesize every Appendix A support-parser case, every exact authority/recency/
URL/provider/value tie-break permutation, or controlled page-version replacement cases
(including an empty version and a null `true_from` version). It verifies ranking invariants
against returned candidates and checks temporal results available from the configured corpus;
the optional mock log checks page headers only for pages actually served. The multi-title
executive history check skips with an explicit reason unless the configured corpus changes
at least two titles in one refresh. Restart checks are opt-in and require the caller to name
the disposable container. These are observable input limitations, not evidence that the
requirements are met.
