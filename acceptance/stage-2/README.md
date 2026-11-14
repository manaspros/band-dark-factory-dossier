# Stage 2 acceptance suite

Independent black-box checks for the Stage 2 dossier contract. The suite reads and
changes state only through HTTP endpoints; it does not import the service or inspect its
source. It resets the target service before each test, so point it at a disposable
instance.

Run from the repository root:

```sh
python -m pip install pytest requests
DOSSIER_BASE_URL=http://127.0.0.1:8080 python -m pytest -q acceptance/stage-2
```

Set `DOSSIER_TEST_DOMAIN` to a domain available from the configured Nimble provider (the
default is `halvorsen-robotics.test`). Provider-call assertions run when both
`DOSSIER_MOCK_URL` and `DOSSIER_MOCK_TOKEN` are set. They use only the mock's HTTP admin
API. Browser checks run when Playwright and a Chromium browser are installed; otherwise
they are reported as skipped, while HTTP checks still cover the public HTML shell and
authenticated JSON boundary.

For browser checks, install Playwright and its browser in a throwaway environment outside
the repository, then run pytest with that environment's Python. For example:

```sh
python -m venv /tmp/dossier-stage2-ui
/tmp/dossier-stage2-ui/bin/pip install pytest requests playwright
/tmp/dossier-stage2-ui/bin/python -m playwright install chromium
DOSSIER_BASE_URL=http://127.0.0.1:8080 /tmp/dossier-stage2-ui/bin/python -m pytest -q acceptance/stage-2
```

The tests require no credentials in the repository.

Every test's docstring names its matrix row IDs. The table records the principal mapping;
some tests span several adjacent rows, as noted in their docstrings.

| Test | Matrix rows |
|---|---|
| `test_candidates_are_complete_ranked_records_and_drive_status` | S24, S28-S45, R147-R148 |
| `test_candidate_citations_are_pages_actually_served_when_mock_log_is_available` | S7, S9-S10, S27, S29 |
| `test_rendered_provider_spend_is_at_most_80_and_domain_search_is_unique` | S11, S13, S15, S25, R63-R64, R141, R152, R159 |
| `test_429_retries_wait_and_eventually_succeed` | S20-S23, R155 |
| Idempotency tests in `test_api_contract.py` | Stage 1 R99-R100, R103-R119 |
| `test_request_body_errors_use_the_specified_status`; key/query tests | Stage 1 R36-R40, R108, R135, R151 |
| `test_domain_normalisation_is_shared_by_create_and_path_reads` | Stage 1 R47-R51 |
| `test_list_query_filter_order_paging_and_unknown_query` | Stage 1 R44, R147, R149-R151 |
| `test_reset_during_build_clears_state_and_old_token` | Stage 1 R29, R31, R99 |
| `test_stage1_shaped_import_keeps_session_dossier_and_replay` | S108-S116; Stage 1 R161-R164, R170-R174 |
| `test_clock_moves_forward_and_rejects_backwards_time` | Stage 1 R33-R40, R122 |
| `test_html_routes_are_public_data_free_shells`; JSON auth test | S46, S48, E19; Stage 1 R99 |
| Browser required routes/layout/auth | S46-S67, S71-S74, S77-S100 |
| Browser latest-read-wins and uncertain retry | S101-S107 |

`NOT COVERED` below means the contract cannot be independently synthesized through the
public interface without controllable provider page content, a deterministic mock clock,
or implementation-defined behavior:

| Rows | Coverage limit |
|---|---|
| S35-S40, individual tie-break cases | The suite independently recalculates ranking on returned candidates, but exact authority/recency/URL/provider/value tie scenarios require matching provider pages. It does not inject or edit provider content. |
| S20-S23, 429 clock exclusion | Optional mock-log assertions check 429 sequence, zero cost and retry spacing. The public API does not expose the build's internal elapsed-time accounting. |
| S111-S116, Stage 1 upgrade fixture | The test converts a completed service export's fields to Stage 1 `{value,status,citations}` shape before import. It cannot use a binary export from a separate historical Stage 1 process in this standalone suite. |
| S56, visual distinction for every transient state | Browser checks assert named states and layout where available; screenshot review of all transient visual states remains a human review. |
| S3-S6 and S24 Appendix A support edge cases | The public API has no endpoint for injecting arbitrary page headers/text. The configured corpus does not guarantee every header and Appendix A boundary case. |
| S25 claim-page budget adversary; DEV-S2 boundary | Provider mock log verifies spend and provenance, but does not let this suite synthesize six arbitrary research claims and a tailored competing URL set. |
