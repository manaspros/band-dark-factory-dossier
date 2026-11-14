# Stage 1 (dossier) - requirement matrix

Source: the stage-1 requirements text as relayed verbatim by lead in four parts (room messages,
2026-11-14). Every normative statement has a row. Rows are never renumbered.

Column key

- **Quote**: verbatim from the requirements, with its section.
- **Meaning / decision**: one plain sentence where the quote needs it; `Dn` points at the
  decision log at the end.
- **Verified by**: a supplied check (`A` = `test/stage_1/test_auth.py`, `D` =
  `test/stage_1/test_dossiers.py`, `S` = `test/stage_1/test_sample.py`, all under
  `sf-buildathon-2026/challenges/dossier/`), or **NOT EXERCISED** followed by the proof the
  builder must supply instead (`UT` = unit test in `stage-1/tests/`, `RD` = code reading by the
  verifier, `CMD` = a command).
- **Where**: the work item (see `stage-1-plan.md`) and the planned module under
  `stage-1/app/`.

Only the supplied sample/visible checks were read for the "Verified by" column; the graded suite
is larger. A row marked with a supplied check may still have cases those checks miss.

## §1 Scope and global invariants

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R1 | "Every value the service asserts cites at least one excerpt that a provider endpoint served to this service, and that excerpt supports the value." (§1.1) | Every `known` field has >=1 citation whose excerpt came from provider-served text and passes Appendix A. | PARTIAL: S `test_build_a_dossier` only checks that the excerpt is a substring of the page text and that the value is in the expected set, not Appendix A support. NOT EXERCISED for support -> UT `test_support.py` (A.2 table and A.4 cases), UT `test_evidence.py::every_citation_supports_its_value` (re-runs `supports()` on every citation `decide()` emits, over synthetic pages built from the §4 and Appendix A example sentences, including conflicting and negated ones). Verifier: re-runs `support.supports(excerpt, field, domain)` on every citation of a built dossier from the mock | U6 `evidence.py`, U5 `support.py` |
| R2 | "No citation is invented, reworded, or attached to a value it does not support." (§1.1) | Excerpt is the served sentence (only whitespace collapsed); a citation is attached only to the value it supports. | S `test_build_a_dossier`; NOT EXERCISED for multi-value pages -> UT `test_evidence.py::conflicting_values_cite_only_chosen` | U5, U6 |
| R3 | "No build of a dossier spends more than 80 units (§9)." (§1.2) | Hard cap per build, enforced by reservation before each call. | NOT EXERCISED directly -> UT `test_budget.py` (fake web layer counts units incl. timeouts/concurrency); verifier reads mock `/calls` log cost sum per build | U7 `budget.py` |
| R4 | "The following apply to all operations, including concurrent requests and retries" (§1) | R1-R3 hold under concurrency and retries (incl. idempotent replays and provider retries). | NOT EXERCISED -> UT budget reservation under `asyncio.gather`; RD | U7, U8 |
| R5 | "Contact data, people search, and fields other than the six in §4 are out of scope." (§1) | No extra fields or endpoints. | RD | U6 |

## §2 Delivery and deployment

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R6 | "Deliver an HTTP service, a `Dockerfile` and a `RUN.md` with a command that builds and starts the service without manual setup." (§2) | `stage-1/Dockerfile`, `stage-1/RUN.md` with one copy-paste build+run command. | harness build (`python -m harness run`) | U1 |
| R7 | "The image must run on its own with `-e PORT=<port>` and a port mapping." (§2) | No compose, no sidecars, no volumes needed. | harness build/run | U1 |
| R8 | "All runtime dependencies, initialization and seed data must work within that single container. Compose configuration is not used to start the service." (§2) | Single process; in-memory store initialised at start. | harness run | U1, U2 |
| R9 | "Nimble is the default provider: every service must be able to research companies using Nimble alone." (§2 Web access) | Build uses `nimble` only (D1). | S `test_build_a_dossier` (mock provides Nimble) | U4 `web.py`, U7 |
| R10 | "Tavily is optional: ... its absence must not prevent research while Nimble answers." (§2) | Tavily is never called (D1), so its absence is irrelevant. | RD (no `tavily` in `web.py`) | U4 |
| R11 | "The service reaches the providers only through WebRouter, the Python package `webrouter` (module `web_router`)." (§2) | Only `web.py` imports `web_router`; no other HTTP client talks to providers. | NOT EXERCISED -> RD + CMD `grep -rn "httpx\|requests\|urllib" stage-1/app` shows no provider calls | U4 |
| R12 | "The stage folder's dependency manifest lists `webrouter>=0.12.0`." (§2) | `stage-1/requirements.txt` contains the line `webrouter[search,extract,research]>=0.12.0` (D2). | NOT EXERCISED -> CMD `grep webrouter stage-1/requirements.txt` | U1 |
| R13 | "Install it and the provider SDK dependencies from PyPI, including in the service's Docker build" (§2) | Dockerfile runs `pip install -r requirements.txt` with the extras. | harness build | U1 |
| R14 | "WebRouter's `nimble` provider reads `NIMBLE_API_KEY` and `NIMBLE_BASE_URL` from the environment" (§2 env table) | Service never reads or logs key values; WebRouter/SDK reads them. | S `test_build_a_dossier` (mock base URL) | U4 |
| R15 | "A service that uses Tavily passes its base URL to WebRouter in `provider_config`" (§2) | Not applicable: Tavily unused (D1). | RD | U4 |
| R16 | "CPU 2 vCPU; Memory 3 GiB" (§2 limits) | No heavy deps; scrypt memory bounded (D6). | NOT EXERCISED -> RD | U1, U3 |
| R17 | "Start to first healthy response 60 s" (§2 limits) | uvicorn starts in seconds; no network at startup. | harness wait-for-health | U2 |
| R18 | "Concurrent requests up to 50 in flight" (§2 limits) | Single asyncio worker; hashing off-loop (D6). | NOT EXERCISED in visible checks -> CMD 50-parallel signup/login/POST script, all < 5 s | U2, U3 |
| R19 | "Per-request timeout 5 s (10 s for `POST /_test/reset`)" (§2 limits) | No request handler awaits a provider; reset hashes few passwords. | NOT EXERCISED -> CMD timing in the 50-parallel script | U2, U3 |
| R20 | "Outbound network ... at run time, **only the provider endpoints this specification lists**" (§2 limits) | No runtime downloads, telemetry or other egress. | NOT EXERCISED -> RD | U1, U4 |
| R21 | "Disk ephemeral; state need not survive a container restart" (§2 limits) | In-memory state is acceptable. | n/a (permission) | U2 |
| R22 | "Runtime assets and dependencies must be included in the image." (§2) | All pip deps installed at build time. | harness run | U1 |
| R23 | "Never commit credentials" (brief constraint) | No keys in repo, Dockerfile, RUN.md or logs. | NOT EXERCISED -> CMD `git grep -i "api_key\s*=" stage-1` | U1, U4 |
| R216 | "Build from the supplied requirements. Source code, API documentation and schemas from existing products in this domain must not be used." (preamble) | Clean room: the builder implements from this spec and the plans only. No code, API docs or schemas from company-data or enrichment products are copied or consulted. The supplied mock (`challenges/dossier/web/mockweb`) and visible tests are harness material, not a product. They may inform wiring but never the API shape. | NOT EXERCISED -> RD: verifier checks that `stage-1/` has no vendored third-party product code and that RUN.md/README cite only this spec and WebRouter docs; builder states sources consulted in its handoff | U1 (RUN.md "Sources" line), all items |
| R217 | "WebRouter's own documentation may be used." (preamble) | Permission: the WebRouter README/docstrings (read for this plan from the 0.12.0 wheel) are the only external docs used. | n/a (permission); RD | U4 |
| R218 | "The submission is a containerized HTTP service, not a Python package. Python is not required in the implementation." (§2) | Deliverable is the image plus RUN.md. No `setup.py`/`pyproject` packaging or importable public API is needed; Python is chosen freely (D4). | harness build/run; RD (no packaging files) | U1 |
| R219 | "The submitted `Dockerfile` is built and started, and only its HTTP behavior is exercised; it does not import or execute the submission's source files on the host that runs it." (§2) | Everything (deps, startup, state) lives inside the image; nothing depends on host files, mounts or a host Python. The unit tests in `stage-1/tests/` are developer proof only and are not part of the runtime contract. | harness run; CMD build and run from a clean clone with no host venv | U1 |

## §3 Runtime contract

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R24 | "Listen on `0.0.0.0` using the `PORT` environment variable, default `8080`." (§3.1) | | harness run (sets PORT); default NOT EXERCISED -> RD `main.py` | U2 `main.py` |
| R25 | "`GET /health  ->  200  {"status": "ok"}`" (§3.2) | Exact body. | S `test_health`, A `test_health_needs_no_token_and_calls_no_provider` | U2 |
| R26 | "Return 200 once the service and its data store can serve requests, within 60 seconds of container start." (§3.2) | | harness | U2 |
| R27 | "`/health` makes no provider call." (§3.2) | | A `test_health_needs_no_token_and_calls_no_provider` | U2 |
| R28 | "Replace all service state with the fixture in the request body (§4)." `-> 204 No Content` (§3.3) | | A reset tests | U3 `control.py`, `store.py` |
| R29 | "When reset returns 204, subsequent requests must see only that fixture: no users other than the seeded ones, no dossiers and no stored idempotent responses." (§3.3) | | A `test_reset_removes_signed_up_users`, `test_reset_removes_dossiers`, `test_reset_forgets_idempotent_responses` | U3 |
| R30 | "Repeated resets are supported." (§3.3) | | A `test_repeated_resets` | U3 |
| R31 | "A build still running when reset is called must not change the state that follows the reset." (§3.3) | Builds carry the store generation; a build whose generation is stale writes nothing (D9). | NOT EXERCISED -> UT `test_build.py::reset_during_build_writes_nothing` (fake web layer with a delay) | U7 `build.py`, U2 `store.py` |
| R32 | "This control endpoint must be enabled in the delivered image and requires no authentication." (§3.3) | | A reset tests (no token) | U3 |
| R33 | "The service keeps a clock that only reset and `POST /_test/clock` move. Every timestamp the service records or returns is read from this clock." (§3.4) | `researched_at` and build time read `clock.now()`; no `datetime.now()` elsewhere. | A `test_clock_dates_the_build`; RD grep for `datetime.now` | U2 `clock.py` |
| R34 | "`POST /_test/clock` `{ "now": ... }` `->  204 No Content`" (§3.4) | | A `test_clock_dates_the_build` | U3 |
| R35 | "Reset sets the clock to the fixture's `now`." (§3.4) | | A `test_reset_sets_the_clock` | U3 |
| R36 | "Before the first reset the clock follows the system time." (§3.4) | Until the first reset/clock call, `now()` returns system UTC time. | NOT EXERCISED -> UT `test_clock.py` | U2 |
| R37 | "The clock stands still between calls: two requests with no clock call between them read the same time." (§3.4) | After it is set, the clock is a stored value, not an offset from system time. | A `test_researched_at_is_the_time_of_the_request` (partially); UT `test_clock.py` | U2 |
| R38 | "`now` is an RFC 3339 timestamp with an explicit offset." (§3.4) | Missing offset (`2026-03-01T09:30:00`) -> 422. `Z` accepted as offset (D10). | A `test_clock_needs_an_offset` | U2, U3 |
| R39 | "A `now` earlier than the clock's current time is 422 `validation_failed` and changes nothing." (§3.4) | Equal time is accepted. | A `test_clock_cannot_move_back` | U3 |
| R40 | "`POST /_test/clock` requires no authentication." (§3.4) | | A clock tests | U3 |
| R41 | "Requests and responses are `application/json; charset=utf-8`." (§3.5) | Every JSON response sets that content type; 204 has no body. | NOT EXERCISED for header value -> CMD `curl -i` | U2 `responses.py` |
| R42 | "Timestamps in responses are RFC 3339 with an explicit offset" (§3.5) | Emit `isoformat()` of an aware datetime, keeping the offset the clock was set with (D10). | D `test_researched_at_is_the_time_of_the_request` | U2 |
| R43 | "Unknown fields in a request body are ignored, never an error." (§3.5) | | A `test_unknown_body_fields_are_ignored`, D `test_unknown_body_fields_are_ignored` | U2 `requests.py` |
| R44 | "Unknown query parameters are ignored." (§3.5) | | D `test_unknown_query_parameters_are_ignored` | U9 |
| R45 | "IDs are opaque strings of at most 64 characters." (§3.5) | Generated ids are `u_`/`d_` + 16 hex chars (D11). Seeded ids (reset fixture) and imported ids must be non-empty strings of at most 64 characters; otherwise reset/import is 422 `validation_failed` and changes nothing (D30). | NOT EXERCISED -> UT `test_auth.py::reset_rejects_65_char_id`, `test_export_import.py::import_rejects_65_char_id`; RD for generated ids | U3, U8, U10 |

## §4 Model

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R46 | "Every authenticated user sees the same dossiers." (§4 Users) | Dossiers are global, not per user. | D `test_every_user_sees_the_same_dossier` | U8 |
| R47 | "Every domain the API takes, in a body or a path, is first **normalised**: surrounding whitespace removed, lowercased, one trailing `.` removed, and one leading `www.` removed." (§4 Domains) | Order: strip, lower, drop one trailing `.`, drop one leading `www.`. | D `test_every_spelling_names_one_dossier`, `test_read_by_any_spelling`; S `test_read_by_another_spelling` | U2 `domains.py` |
| R48 | "two or more labels separated by `.`, each label 1 to 63 characters of `a-z`, `0-9` and `-`, not starting or ending with `-`, and 253 characters or fewer in total." (§4) | | D `test_invalid_domain_is_422`, `test_longest_valid_domains_are_accepted` | U2 |
| R49 | "Anything else, including a URL with a scheme or a path, is 422 `validation_failed`." (§4) | Applies to body (`POST /dossiers`) and path (`GET`, `refresh`). | D `test_invalid_domain_is_422`, `test_invalid_domain_in_the_path_is_422` | U2, U8 |
| R50 | "`Acme-Robotics.TEST.`, `www.acme-robotics.test` and `acme-robotics.test` name the same company and the same dossier." (§4) | | D `test_every_spelling_names_one_dossier` | U8 |
| R51 | "Responses always carry the normalised domain." (§4) | | D `test_response_carries_the_normalised_domain` | U8 |
| R52 | "A dossier has exactly these six fields" (§4 Fields) | `legal_name`, `hq_city`, `ceo`, `founded_year`, `headcount_range`, `funding_total`. | S `test_build_a_dossier` | U6 |
| R53 | "`founded_year` Integer"; "`funding_total` Integer ... in whole US dollars" (§4 table) | JSON integers, not strings. | S `test_build_a_dossier` | U5, U6 |
| R54 | "`headcount_range` String: one of `1-10`, `11-50`, `51-200`, `201-500`, `501-1000`, `1001-5000`, `5001-10000`, `10001+`" (§4) | | S `test_build_a_dossier` | U5 |
| R55 | "`hq_city` ... the city ..., without region or country" (§4) | The A.4 `hq_city` format (capitalised run right after the phrase) is the extraction rule; no further trimming. A comma ends the run (`based in Lisbon, Portugal` -> `Lisbon`). A comma-less run (`based in Lisbon Portugal`) yields `Lisbon Portugal` by A.4/A.5. This is in tension with "without region or country", **see C3, flagged for lead**. | S `test_build_a_dossier` (value in expected set only); UT `test_support.py` for the comma case and the C3 case as decided | U5 |
| R56 | "A string value is written as the supporting excerpt writes it, without surrounding whitespace." (§4) | Value text copied from the excerpt, not from `Facts:` or research `structured`. | S `test_build_a_dossier`; UT `test_support.py` | U5 |
| R57 | "A headcount the web states as a number, or as a range that fits inside one of the ranges above, has the range that contains it as its value." (§4) | | UT `test_support.py` (`120`, `3,148`, `51-200`) | U5 |
| R58 | Field shape `{ "value", "status", "citations": [ { "url", "excerpt", "provider" } ] }` (§4) | | S `test_build_a_dossier` (`assert_dossier`) | U6, U8 |
| R59 | "`status` is `known` when `value` is not null, and `unknown` when it is." (§4) | | S `test_build_a_dossier` | U6 |
| R60 | "A `known` field has one or more citations. An `unknown` field has `"value": null` and `"citations": []`." (§4) | | S `test_build_a_dossier` | U6 |
| R61 | "`url` is the URL of the page the excerpt was served for, `provider` is `nimble` or `tavily`, the provider that served it." (§4) | For an extract, `url` = the URL WebRouter reports for the document (D12); for a research claim, the claim citation URL. `provider` is the provider of the call that returned the text (always `nimble` under D1); each candidate carries the provider and URL from the `CallOutcome` that produced it, never from a constant at render time. | PARTIAL: S `assert_citations` checks URL/text only and `assert_field` only that `provider` is an allowed label. NOT EXERCISED for provenance -> UT `test_build.py::citation_provenance` (fake web records each served (provider, url, text); every emitted citation's (provider, url) is among them and its excerpt is a whitespace-collapsed substring of that text). Verifier: correlates citations with the mock `/calls` log (`served` entries per call) | U4, U6, U7 |
| R62 | Definition of **evidence**: "every page that some search, through any provider and for any query naming the company (as in Appendix A.2), returns, with its full text, and every claim that a `nimble` research run for the company asking for all six fields answers with." (§4 Evidence) | The build approximates "all evidence" with field-targeted searches + extracts + one research run (plan §Search strategy). Pages beyond what any affordable query returns are a known residual risk (Open-1). Every page a build gathers (full text) and every research claim it receives is fed to `support.candidates()`; nothing gathered is dropped before evaluation. | PARTIAL: S `test_build_a_dossier` checks only that values are in the expected set; it does not check coverage. NOT EXERCISED for coverage -> UT `test_build.py::all_gathered_text_is_evaluated` (fake web with a supporting sentence planted in the last-extracted page and in a research claim; both reach the field). Verifier: for each sample company, compare the URLs the build extracted (mock `/calls`) with the union of searchable company pages in `challenges/dossier/web/corpus/sample/<domain>.json`, and list any supported value on an un-gathered page (Open-1) | U7 |
| R63 | "every build makes exactly one whose query is exactly the company's normalised domain, through a provider of its choice" (§4) | Exactly one *successful* search with query == normalised domain; no other query equals the domain. Refused attempts cost 0 and are retried per D29: while any other call of the build has succeeded, retries continue until success or the build deadline; only when nothing in the build has succeeded does it stop after 3 retries (so an all-refused build fails fast). | NOT EXERCISED in visible checks -> UT `test_build.py::exactly_one_domain_query` (fake web: first attempt 429), `::domain_query_retried_while_others_succeed` (refused 5 times, then succeeds, build ready with exactly one success), `::all_refused_fails_fast` | U7 |
| R64 | "its other such searches use other queries." (§4) | All other search queries differ from the bare domain string. | UT same as R63 | U7 |
| R65 | "A search that a provider answers with an error does not count." (§4) | A refused domain search is retried. | UT same as R63 | U7 |
| R66 | "The excerpt is copied character for character from that served text, except that any run of whitespace may be written as a single space. It is 1 to 500 characters long." (§4 citation) | Excerpt = one A.1 sentence with whitespace runs collapsed; sentences >500 chars are not citable. | S `assert_citations`; UT length bound | U5 |
| R67 | "It is taken from the page's prose (below), not from its header." (§4) | Header lines are removed before sentence split. | NOT EXERCISED -> UT `test_support.py::header_is_not_prose` | U5 |
| R68 | "An excerpt **supports** a value when, read on its own, it states that value for that field of this company, as Appendix A defines." (§4) | Single implementation `supports(excerpt, field, company)` returning the normalised value or None. | S; UT | U5 |
| R69 | "A research answer carries a claimed value for a field and a citation for the claim. The claim is asserted only when its citation supports it." (§4) | Research claims are candidates: each claim excerpt is run through A.2 for the claim's field (path `$.field`); the value used is the one A.5 derives from the excerpt, never the research `structured` value. | NOT EXERCISED -> UT `test_evidence.py::research_claim_unsupported_is_dropped` | U6 |
| R70 | "A field is `unknown` when no evidence supports a value for it, even when a research answer claims one." (§4) | | UT same as R69 | U6 |
| R71 | "When the evidence supports more than one value for a field, the field holds one of them and cites only excerpts that support that value." (§4) | Choice rule D7. | NOT EXERCISED -> UT `test_evidence.py::conflict` | U6 |
| R72 | "Every page has a URL, a title and a text. A text may begin with **header lines**, each of the form `Name: value`, where the name is a capitalised word or several joined by `-`." (§4 Pages) | Header-line rule per D13: the name is one or more A.4 capitalised words (any alphabet) joined by `-`, then `:`. | UT `test_support.py::header` incl. non-ASCII names (`Größe: 5`, `Über-Uns: x` are stripped; `CEO: Sam Ortiz` and `Acme robotics: x` are not header lines) | U5 |
| R73 | "The header ends at the first empty line; everything after it is the page's **prose**. A text whose first line is not a header line has no header and is all prose." (§4 Pages) | Text with header lines and no empty line has no prose (D13). | UT | U5 |
| R74 | "The header line `Facts:` ... is informative only: citations come from the prose, and whether an excerpt supports a value is decided by Appendix A alone. The service may ignore other header lines." (§4) | `Facts:` is ignored entirely (D14). | RD | U5 |
| R75 | Fixture: "`now` is required and sets the clock (§3.4)." (§4 Fixture) | Missing `now` -> 422. | A `test_reset_needs_now` | U3 |
| R76 | "Seeded users must be able to log in with the given password immediately." (§4 Fixture) | Hash seeded passwords during reset, before returning 204. | A `test_seeded_users_log_in` | U3 |
| R77 | "A fixture with two users sharing an email is a reset error: 422 `validation_failed`, changing nothing." (§4 Fixture) | Validate fully, then swap state; email comparison case-insensitive (D15). | A `test_reset_with_a_shared_email_changes_nothing` | U3 |
| R78 | (§6) "For a user seeded by the fixture (§3.3), `user_id` is that user's `id` in the fixture." | | A `test_seeded_users_log_in` (indirect); NOT EXERCISED for id value -> CMD login returns `u_ada` | U3 |

## §5 Errors

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R79 | "Every 4xx and 5xx response carries this body: `{ "error": { "code": ..., "message": ... } }`" (§5) | Includes 404/405 for unknown routes/methods (D16). | all `assert_error` checks; unknown route NOT EXERCISED -> CMD | U2 `errors.py` |
| R80 | "400 `malformed_request` Unparseable body, or a field of the wrong JSON type" (§5) | Body not JSON or not an object -> 400 (D17). | A `test_unparseable_body`, `test_signup_field_of_the_wrong_type`, `test_login_field_of_the_wrong_type`; D `test_unparseable_body`, `test_domain_of_the_wrong_type` | U2 `requests.py` |
| R81 | "400 `missing_idempotency_key` Required `Idempotency-Key` header absent or empty" (§5) | | NOT EXERCISED in visible checks -> UT/CMD | U8 `idempotency.py` |
| R82 | "401 `unauthenticated` Missing, malformed or unknown bearer token" (§5) | `Bearer` with no token, other schemes, bare token -> 401. | A `test_endpoint_needs_a_valid_token`, `test_malformed_authorization_header` | U3 `auth.py` |
| R83 | "404 `not_found` No such resource, or not visible to this caller" (§5) | | D `test_unknown_dossier_is_404`; S `test_unknown_dossier_is_404` | U8 |
| R84 | "409 `idempotency_key_reuse` Key already used by this caller with a different request body" (§5) | | NOT EXERCISED in visible checks -> UT/CMD | U8 |
| R85 | "422 `validation_failed` A required field or query parameter is missing, or a stated rule is violated with no more specific code" (§5) | | A `test_signup_field_missing`, `test_login_field_missing`; D `test_domain_missing` | U2 |
| R86 | "A field of the correct JSON type with an invalid format or out-of-range value gives 422 `validation_failed`, unless an endpoint specifies a different error." (§5) | | A/D validation tests | U2 |
| R87 | "An integer-valued **query parameter** is written as plain decimal digits: `1e9`, `4.0` and `+4` are 422 `validation_failed` whatever their numeric value." (§5) | Regex `^[0-9]+$`; leading zeros allowed (D18). | D `test_invalid_paging_is_422` | U9 |
| R88 | "Reserve 400 `malformed_request` for a body that does not parse or a field of the wrong type." (§5) | Never 400 for a well-typed but invalid value. | A/D validation tests | U2 |
| R89 | "`Idempotency-Key` 1 to 255 characters, otherwise 422 `validation_failed`" (§5 ranges) | 256+ chars -> 422 (empty is R81's 400). | NOT EXERCISED -> UT/CMD | U8 |
| R90 | "`limit` integer 1 to 200" / "`offset` integer 0 or more", otherwise 422 (§5 ranges) | | D `test_limit_bounds_are_accepted`, `test_invalid_paging_is_422` | U9 |
| R91 | "Requests must not produce 5xx responses, including under concurrent load and when a provider endpoint answers with an error." (§5) | Provider errors are contained inside the background build; request handlers never touch providers. Last-resort handler still uses the §5 envelope. | D `test_build_with_no_provider_answering_fails` (partial) ; NOT EXERCISED under load -> CMD 50-parallel script | U2, U7 |

## §6 Authentication

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R92 | "`POST /auth/signup` ... `->  201  { "user_id", "display_name", "token" }`" (§6) | | S `test_signup_and_login`; A `test_signup_token_works_at_once` | U3 |
| R93 | "`POST /auth/login` ... `->  200  { "user_id", "display_name", "token" }`" (§6) | | A `test_login_returns_the_signed_up_user` | U3 |
| R94 | "Email already registered -> 409 `email_taken`" (§6) | Case-insensitive comparison (D15); seeded emails count. | A `test_email_already_registered` | U3 |
| R95 | "Password shorter than 8 characters -> 422 `validation_failed`" (§6) | Length in Unicode code points; exactly 8 is accepted. | A `test_password_shorter_than_eight`, `test_eight_character_password_is_enough` | U3 |
| R96 | "`email` not of the form `local@domain` -> 422 `validation_failed`" (§6) | Exactly one `@`, non-empty local and domain parts, no whitespace (D19). | A `test_email_not_local_at_domain` | U3 |
| R97 | "`display_name` empty or longer than 100 characters -> 422 `validation_failed`" (§6) | 100 accepted. | A `test_display_name_empty_or_too_long`, `test_display_name_of_100_characters` | U3 |
| R98 | "Wrong password or unknown email on login -> 401 `unauthenticated`" (§6) | | A `test_wrong_password_or_unknown_email` | U3 |
| R99 | "Every other endpoint requires a bearer token, except `/health`, the `/_test/*` endpoints and the two above." (§6) | | A `test_endpoint_needs_a_valid_token` | U3 |
| R100 | "A request to such an endpoint that lacks a valid token is 401 `unauthenticated`, even when it also lacks a required `Idempotency-Key`." (§6) | Auth is checked first. | A `test_endpoint_needs_a_valid_token` (sends a key); missing-key case NOT EXERCISED -> UT | U3, U8 |
| R101 | "Tokens do not expire. An account may have multiple valid tokens and concurrent sessions." (§6) | | A `test_several_tokens_stay_valid` | U3 |
| R102 | "Passwords must be stored using a password-hashing function such as bcrypt, scrypt or Argon2, or an equivalent. Plaintext password storage is not permitted." (§6) | stdlib `hashlib.scrypt` with random salt (D6). | NOT EXERCISED -> RD + export shows no plaintext | U3 |

## §7 Idempotency

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R103 | "Two write paths require an idempotency key (§8): **`POST /dossiers`** and **`POST /dossiers/{domain}/refresh`**. Everything below applies to each of them independently." (§7) | | S `test_replay_is_200` (POST only) | U8 |
| R104 | "The key is scoped to **the authenticated user**. Two different users may use the same key string with no interaction between them." (§7) | Store key = (user_id, method, raw path, key) (D20). | NOT EXERCISED -> UT | U8 |
| R105 | "A replay means the same user sending the **same method, the same path and the same body**." (§7) | | S `test_replay_is_200` | U8 |
| R106 | "The same key with the same body on a different path is a different request, not a replay, and must succeed normally." (§7) | Different raw path with a used key = first use, no 409 (D20). | NOT EXERCISED -> UT | U8 |
| R107 | "`Acme-Robotics.test` and `acme-robotics.test` in a path or body are different requests for this rule, though they name the same dossier." (§7) | Compare raw path and raw body values, not normalised ones. | NOT EXERCISED -> UT | U8 |
| R108 | "Header absent or empty -> 400 `missing_idempotency_key`" (§7) | | NOT EXERCISED -> UT | U8 |
| R109 | "First use of the key -> The normal response (§8)" (§7) | | S `test_request_returns_202_building` | U8 |
| R110 | "Replay: same key, same body -> **200**, body identical to the original response as a JSON value" (§7) | Even if the original was 202. | S `test_replay_is_200` | U8 |
| R111 | "Same key, different body -> 409 `idempotency_key_reuse`" (§7) | Same user, same method+path, different known-field body. | NOT EXERCISED -> UT | U8 |
| R112 | "Key reused after the original request failed with 4xx -> Treated as a first use" (§7) | Only 2xx outcomes are stored. | NOT EXERCISED -> UT | U8 |
| R113 | "'Same body' means the same JSON value after parsing — key order and whitespace do not matter." (§7) | Compare canonical projection of known fields. | NOT EXERCISED -> UT | U8 |
| R114 | "Unknown fields are ignored (§3.5) and play no part in this comparison" (§7) | `POST /dossiers` projection = `{"domain": <raw value or absent>}`. | NOT EXERCISED -> UT | U8 |
| R115 | "`POST /dossiers/{domain}/refresh` takes no body; any body sent to it is ignored and plays no part in deciding a replay." (§7) | Refresh never parses the body (even invalid JSON is fine) (D21). | NOT EXERCISED -> UT | U8 |
| R116 | "For concurrent identical requests with an unused key, exactly one returns the normal response. The others return 200 with the same body. The operation takes effect only once." (§7) | Check-and-store with no `await` in between on one event loop. | NOT EXERCISED -> UT `asyncio.gather` of 20 identical requests via ASGI client | U8 |
| R117 | "A successful replay returns the original response, even after the dossier has changed. It starts no build and makes no provider call." (§7) | | S `test_replay_is_200` (immediate only; does not count builds or calls). NOT EXERCISED for "after change" and "no build, no provider call" -> UT `test_idempotency.py::replay_after_change_starts_nothing`: build, refresh, settle, then replay the original POST and the original refresh. Assert the original bodies, that the fake web's call count is unchanged, that the store's build-start counter is unchanged, and that `spent_units` is unchanged. Verifier: the mock `/calls` log length is unchanged across a replay | U8 |
| R118 | "After the body has parsed as a JSON object and the caller is authenticated, an already claimed key is resolved before field validation." (§7) | Order: auth -> key header -> body parse -> key lookup -> field validation (D22). | NOT EXERCISED -> UT | U8 |
| R119 | "changing a successful request to an invalid body with the same key still returns `409 idempotency_key_reuse`." (§7) | | NOT EXERCISED -> UT | U8 |

## §8 API

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R120 | "A **build** researches one dossier: it calls the providers, decides each field, and replaces the dossier's fields with the result when it completes." (§8 Builds) | Fields replaced atomically at completion only. | S `test_build_a_dossier` | U7 |
| R121 | "A dossier's first build starts with `POST /dossiers`, and every later one with `POST /dossiers/{domain}/refresh`." (§8) | | S `test_refresh_starts_a_build` | U8 |
| R122 | "A build's **time** is the clock's time when the request that started it was received." (§8) | Read `clock.now()` at request receipt; becomes `researched_at` if `ready`. | D `test_researched_at_is_the_time_of_the_request`, A `test_clock_dates_the_build` | U8 |
| R123 | "A dossier has at most one build running at a time." (§8) | | NOT EXERCISED -> UT | U8 |
| R124 | "A build ends in `ready` when it completed, or `failed` when none of its provider calls succeeded." (§8) | `failed` iff zero provider calls succeeded. | D `test_build_with_no_provider_answering_fails` | U7 |
| R125 | "A failed build leaves the fields as they were." (§8) | Also leaves `researched_at`. | D `test_failed_dossier_lists_a_null_legal_name` (first build); refresh-then-fail NOT EXERCISED -> UT | U7 |
| R126 | "When a build completes `ready`, each field is `known` exactly when the evidence (§4) supports a value for it." (§8) | | S `test_build_a_dossier` | U6, U7 |
| R127 | "A build whose provider calls each answer within one second ends within 10 seconds of the request that started it." (§8) | Calls are issued concurrently in two waves (plan). | NOT EXERCISED for timing -> CMD timed build against the mock | U7 |
| R128 | "against the live providers (`NIMBLE_BASE_URL` unset, or its host `sdk.nimbleway.com`) ... a build does not give up on a call that has been waiting less than 30 seconds" (§8) | Per-call timeout 45 s for search/extract; research polled up to the build deadline (D8). | NOT EXERCISED -> RD constants | U4, U7 |
| R129 | "nor stop gathering because of the time it has run in its first 120 seconds." (§8) | No phase is skipped for elapsed time before 120 s. | NOT EXERCISED -> RD | U7 |
| R130 | "It still ends `ready` or `failed` within 300 seconds." (§8) | Hard build deadline 270 s, then decide with what was gathered. | NOT EXERCISED -> UT with tiny deadline | U7 |
| R131 | "Reading a dossier, listing dossiers and every other request except `POST /dossiers` and `POST /dossiers/{domain}/refresh` make no provider call." (§8) | And those two only via a started build. | A `test_health_...`; RD | U7, U8 |
| R132 | "`POST /dossiers` ... `202 { "dossier_id", "domain", "state": "building" }`" (§8) | | S `test_request_returns_202_building`, D `test_new_domain_is_202_building` | U8 |
| R133 | "When a dossier already exists for the domain, the service starts no build and returns **200** with that dossier's `dossier_id`, `domain` and current `state`." (§8) | | S `test_existing_dossier_is_200`, D `test_existing_domain_is_200_with_its_current_state` | U8 |
| R134 | "Concurrent requests for the same domain create one dossier and start one build, whatever their keys." (§8) | | NOT EXERCISED -> UT `asyncio.gather` with distinct keys | U8 |
| R135 | "`domain` missing -> 422"; "`domain` invalid after normalisation (§4) -> 422" (§8) | Wrong type (non-string) -> 400. | D `test_domain_missing`, `test_invalid_domain_is_422`, `test_domain_of_the_wrong_type` | U8 |
| R136 | `GET /dossiers/{domain}` body: `dossier_id`, `domain`, `state`, `researched_at`, `spent_units`, `fields` (§8) | | S `test_build_a_dossier` | U8 |
| R137 | "`state` is `building` while a build runs, otherwise the outcome of the latest build, `ready` or `failed`." (§8) | | S/D build tests | U8 |
| R138 | "`fields` always holds all six fields. Before the first build completes `ready`, every field is `unknown`." (§8) | | D `test_failed_dossier_lists_a_null_legal_name`; NOT EXERCISED while building -> UT | U8 |
| R139 | "While a later build runs, `fields` are those of the last build that completed `ready`." (§8) | | NOT EXERCISED -> UT | U8 |
| R140 | "`researched_at` is the time of the last build that completed `ready`, or null." (§8) | | D `test_researched_at_is_the_time_of_the_request` | U8 |
| R141 | "`spent_units` is the total cost (§9) of every provider call made for this dossier, by every build, since it was created." (§8) | Updated as each call is accounted, including while building. | NOT EXERCISED for exact value -> verifier compares with mock `/calls` log | U7, U8 |
| R142 | "The domain in the path is normalised (§4). No dossier for it is 404 `not_found`." (§8) | | D `test_read_by_any_spelling`, `test_unknown_dossier_is_404` | U8 |
| R143 | "`POST /dossiers/{domain}/refresh` ... Starts a new build of the dossier and returns 202 with `{ "dossier_id", "domain", "state": "building" }`." (§8) | | S `test_refresh_starts_a_build` | U8 |
| R144 | "A refresh received while a build of the dossier is running starts no second build and returns 202 with the same body." (§8) | | NOT EXERCISED -> UT | U8 |
| R145 | "A refresh researches again: its build makes provider calls whether or not anything has changed since the last build, and its spending counts in `spent_units`." (§8) | No caching across builds. | NOT EXERCISED -> UT/verifier mock log | U7 |
| R146 | "No dossier for the domain -> 404 `not_found`" (refresh, §8) | Invalid path domain -> 422 first (D23). | NOT EXERCISED -> UT | U8 |
| R147 | `GET /dossiers` entry: `dossier_id`, `domain`, `state`, `legal_name`, `researched_at`, `spent_units`; plus `has_more` (§8) | | D `test_list_entry_shape`; S `test_list_dossiers` | U9 |
| R148 | "`legal_name` is the value of the dossier's `legal_name` field, or null." (§8) | | D `test_failed_dossier_lists_a_null_legal_name` | U9 |
| R149 | "When present, only dossiers whose domain or `legal_name` contains `q`, compared case-insensitively, are listed. An empty `q` lists every dossier." (§8) | Use `casefold()` on both sides. | D `test_q_matches_the_domain_ignoring_case`, `test_q_matches_the_legal_name_ignoring_case`, `test_empty_q_lists_every_dossier`, `test_q_without_a_match` | U9 |
| R150 | "Dossiers are ordered by domain ascending." (§8) | Plain code-point order of normalised domain. | D `test_list_is_ordered_by_domain` | U9 |
| R151 | "`limit` defaults to 50, range 1 to 200. `offset` defaults to 0. `has_more` is true when items exist beyond the last one returned." (§8) | | D `test_limit_and_offset_page_the_list`, `test_limit_bounds_are_accepted` | U9 |

## §9 Providers and cost

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R152 | Cost table: nimble search lite 1 / fast 5 / deep 15; tavily search 8 / 16 / 16; extract nimble 1 per URL, tavily 2 per URL; research nimble 25 at start (§9) | One cost function `cost_of(provider, method, depth, n_urls)`. | NOT EXERCISED -> UT `test_budget.py` table | U7 `budget.py` |
| R153 | "A search's depth is WebRouter's `search_depth`." (§9) | Always pass `search_depth` explicitly (`lite`). | RD | U4 |
| R154 | "A search returns at most 10 results, whatever number it asks for." (§9) | Ask `max_results=10`. | RD | U4 |
| R155 | "A call that a provider refuses with an error status costs nothing." (§9) | HTTP error status (incl. 429/5xx) -> 0 units. | NOT EXERCISED -> UT error classifier | U4, U7 |
| R156 | "A call whose answer does not arrive, because it times out or its connection fails, costs its units as in the table" (§9) | Timeouts/connection errors charged in full; SDK retries disabled so every attempt is seen (D5). | NOT EXERCISED -> UT | U4, U7 |
| R157 | "An extract that the provider answers with no page for the URL is not refused: it costs its units, as in the table, whatever status says so." (§9) | Extract with a `failures` entry, or WebRouter raising "nothing came back" after a 200, is charged. | NOT EXERCISED -> UT | U4, U7 |
| R158 | "An extract through `nimble` does not set `render`." (§9) | Never pass `render`/`provider_options`. | RD | U4 |
| R159 | "A build stops making provider calls before its spending would exceed 80 units, and completes with the pages and research claims it has obtained." (§9) | Reserve cost before each call; skip any call that would exceed the remaining budget; finish normally. | NOT EXERCISED -> UT | U7 |
| R160 | "A research request names the company by its domain in its query, and names the fields it asks for by the field names in §4, as the property names of its output schema." (§9) | Query contains the normalised domain; `output_schema.properties` has exactly the six names. | NOT EXERCISED -> UT on payload builder | U7 |

## §10 Export and import

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R161 | "The service must support `GET /_test/export` and `POST /_test/import`. Like reset, these are unauthenticated control endpoints." (§10) | | S `test_export_shape` | U10 |
| R162 | "Return 200 from export with a JSON object containing `track: "dossier"`, `format_version: 1` and `state`" (§10) | | S `test_export_shape` | U10 |
| R163 | "The state format is opaque to the caller and must be accepted unchanged by import." (§10) | | NOT EXERCISED -> UT round trip | U10 |
| R164 | "Import takes that entire object and atomically replaces the service's state, returning 204." (§10) | | NOT EXERCISED -> UT | U10 |
| R165 | "No dependency on the source process, files, volume, port or network address is allowed." (§10) | State is self-contained JSON. | NOT EXERCISED -> RD | U10 |
| R166 | "Import is replacement, not merge; repeating it restores the exported state without duplicating anything." (§10) | | NOT EXERCISED -> UT import twice | U10 |
| R167 | "Invalid JSON follows §5; missing fields, wrong track/version or an invalid state give 422 `validation_failed` without changing the destination." (§10) | Full validation before swap; `format_version` must be integer 1 (not `true`, not `1.0`) (D24). | NOT EXERCISED -> UT | U10 |
| R168 | "These control calls have a 10-second timeout." (§10) | No hashing on import (hashes copied). | NOT EXERCISED -> RD | U10 |
| R169 | "Export is an atomic, read-only snapshot; subsequent source writes do not change it." (§10) | Serialise synchronously (no `await`) to a fresh dict. | NOT EXERCISED -> UT | U10 |
| R170 | "Preserve accounts and hashed-password login, existing bearer tokens, dossiers with their ids, states, fields, citations, `researched_at` and `spent_units`, all completed idempotent request bodies and original responses." (§10) | | NOT EXERCISED -> UT round trip incl. replay after import | U10 |
| R171 | "Identities and timestamps must not be regenerated." (§10) | Id counters/sets restored; timestamps kept as stored strings with their offsets. | NOT EXERCISED -> UT | U10 |
| R172 | "Import makes no provider call: imported dossiers are not researched again, and their citations remain citations served to this service." (§10) | | NOT EXERCISED -> RD | U10 |
| R173 | "Failed request keys remain reusable." (§10) | Follows from storing only 2xx outcomes. | NOT EXERCISED -> UT | U10 |
| R174 | "Existing tokens and retries must remain valid after import" (§10) | | NOT EXERCISED -> UT | U10 |
| R175 | "Import removes all previous destination data and credentials." (§10) | Also invalidates running builds (generation bump). | NOT EXERCISED -> UT | U10 |
| R176 | "Reset clears all state, including imported state." (§10) | | NOT EXERCISED -> UT | U3 |
| R177 | "Export and import do not change the clock." (§10) | Clock is not part of exported state. | NOT EXERCISED -> UT | U10 |
| R178 | "An export taken while a build is running holds the dossier as it was before that build; after import, that dossier is in the state of its last completed build, or `failed` with every field `unknown` when no build had completed." (§10) | Export uses committed snapshot: last outcome (`ready`/`failed`) or `failed`; `spent_units` as before the running build (D25). | NOT EXERCISED -> UT | U10 |
| R179 | "Exports may contain credentials and session tokens; handle them as private artifacts." (§10) | Never log export bodies. | RD | U10 |

## §11 Concurrency

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R180 | "Concurrent requests must produce the same results as executing them one at a time in some order. The requirements above hold at every read." (§11) | Single asyncio event loop; every state mutation is a synchronous critical section (no `await` between read and write). | NOT EXERCISED -> UT gather tests (R116, R134) + CMD 50-parallel script | U2, U8 |

## Appendix A. Support (all rows implemented in `support.py`, U5)

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R181 | "This appendix is the whole definition of 'supports' used in §4. The service decides support by these rules alone." (A) | No heuristics, no `Facts:`, no research `structured` values. | RD | U5 |
| R182 | "A page's prose is split into lines at each line break, and each line into sentences." (A.1) | Line breaks: `\n`, `\r\n`, `\r`. | NOT EXERCISED -> UT | U5 |
| R183 | "A sentence ends after a `.`, `!` or `?`, together with any `"`, `”`, `’` or `)` directly after it, when whitespace follows." (A.1) | Terminator + any run of closers, then whitespace; end of line also closes the last sentence. | NOT EXERCISED -> UT | U5 |
| R184 | "A `.` that ends one of the legal-form suffixes in A.4, written as a whole word, does not end a sentence." (A.1) | Suffixes ending in `.`: `Inc.`, `Corp.`, `L.P.`, `B.V.`, `N.V.`, `S.A.`, `S.A.S.`, `S.L.`, `S.r.l.`, `S.p.A.`, `s.r.o.`, `a.s.`, `K.K.`; whole word = no letter/digit directly before. Exact case. | NOT EXERCISED -> UT (`Acme Robotics, Inc. was founded in 2014.` is one sentence) | U5 |
| R185 | "Each sentence is taken without its surrounding whitespace; empty sentences are dropped." (A.1) | | UT | U5 |
| R186 | "An excerpt is a **single sentence** when, with every run of whitespace written as one space, this rule splits it into exactly one sentence." (A.1) | | UT | U5 |
| R187 | A.2.1 "It is a single sentence (A.1)." | | UT | U5 |
| R188 | A.2.2 "It names the company: it contains the company's normalised domain, or the company's name. The company's name is the first label of its domain with each `-` read as a space" | `acme-robotics.test` -> `acme robotics`. | UT | U5 |
| R189 | A.2.3 "It contains a statement phrase for F (A.3)." | | UT | U5 |
| R190 | A.2.4 "It contains none of the negating phrases (A.3)." | | UT (`reportedly`, `not`, `former`) | U5 |
| R191 | A.2.5 "It contains at least one value in F's format (A.4), and every value in F's format that it contains normalises to V (A.5)." | Collect all format matches; supported iff non-empty and all normalise to one value. | UT | U5 |
| R192 | "The company's name, its domain and every phrase are matched without regard to case and as whole words: the characters directly before and after the match are not letters or digits. Phrases with a space match one space." (A.2) | Letter/digit test uses `str.isalpha()`/`str.isdigit()` (Unicode). Matching is done on the whitespace-collapsed sentence. | UT (`CEOs` does not match `CEO`; `unfounded` does not match `founded`) | U5 |
| R193 | A.2 examples table (six rows, e.g. "`Acme Robotics CEO: Sam Ortiz.` -> `ceo` `Sam Ortiz`", "`Acme Robotics is reportedly in talks to raise $40M.` -> nothing") | All six rows are unit tests verbatim. | NOT EXERCISED -> UT | U5 |
| R194 | A.3 statement phrases per field (table) | Copied verbatim into one constant table. | UT | U5 |
| R195 | A.3 "The negating phrases are: `in talks to`, `plans to`, `planning to`, `wants to`, `expects to`, `hopes to`, `aims to`, `seeking`, `could`, `would`, `might`, `reportedly`, `rumoured`, `former`, `formerly`, `will become`, `not`." | | UT | U5 |
| R196 | "A **capitalised word** is an uppercase letter followed by one or more lowercase letters, with no letter or digit directly before or after it. The letters may be of any alphabet" (A.4) | Unicode via `isupper()`/`islower()`; no new dependency (D3). | UT (`Zürich`, `Müller`) | U5 |
| R197 | "An **uppercase word** is two or more uppercase letters, with no letter or digit directly before or after it" (A.4) | | UT | U5 |
| R198 | "A **number** is written in digits, optionally with a `,` before each group of three digits and a decimal part after a `.` ... Digits directly next to a letter, or joined to other digits by `,` or `.` in any other way, are not a number." (A.4) | Tokenise maximal runs of `[0-9.,]` bounded by digits; accept only `\d{1,3}(,\d{3})+(\.\d+)?` or `\d+(\.\d+)?`; reject if adjacent to a letter. A trailing sentence `.` is not part of the number. | UT (`120`, `1,200`, `12.5`, `12,000,000`; reject `1,20`, `1.2.3`, `12a`) | U5 |
| R199 | `legal_name` format: "The company's name or its domain (matched as in A.2), then zero or more capitalised or uppercase words each after one space, then an optional `,`, one space, and a legal-form suffix with no letter or digit directly after it. Where several such texts start at the same place, the shortest counts" (A.4) | Value is the text as written from the name start to the suffix end. | UT (`Halvorsen Robotics AS`, `Acme Robotics, Inc.`) | U5 |
| R200 | Legal-form suffix list "matched exactly as written here" (A.4) | Case-sensitive. | UT | U5 |
| R201 | `hq_city` format: "A place name directly after a statement phrase for `hq_city` and one space: the longest run of capitalised words joined by single spaces or by `-` that starts there, not part of a longer such run" (A.4) | | UT (`Based in Valencia, ...` -> `Valencia`) | U5 |
| R202 | `ceo` format: "a run of two or three capitalised words joined by single spaces that is not part of a longer such run. Occurrences of the company's name and of the statement phrases for `ceo` are first taken out of the sentence and separate the words around them" (A.4) | Maximal runs only; a run of 1 or >=4 words yields no value. | UT (`As CEO of Halvorsen Robotics, Priya Dalton ...` -> `Priya Dalton`) | U5 |
| R203 | `founded_year` format: "A number of exactly four digits, from 1800 to 2099, that is not part of an amount" (A.4) | A number token matching `^\d{4}$` (D26). | UT | U5 |
| R204 | `headcount_range` format: "A number with no decimal part, 1 or more, that is not part of an amount. Words before it ... do not change it. A stated range such as `51-200 employees` holds two numbers" (A.4) | Every such number in the sentence must map to the same range (e.g. a year in the sentence breaks support). | UT | U5 |
| R205 | `funding_total` format: "An amount (below)" (A.4) | | UT | U5 |
| R206 | Amount form 1: "`$`, `US$` or `USD`, an optional space, a number, and optionally a scale: `k`, `m`, `mn` or `bn` directly after the number, or one space and `thousand`, `million` or `billion`." (A.4) | Case-insensitive; no letter/digit directly before or after the whole amount. | UT (`$12M`, `$12.5 million`, `US$12 million`, `USD 12 million`, `$12m`, `$12,000,000`) | U5 |
| R207 | Amount form 2: "A number, optionally one space and `thousand`, `million` or `billion`, then one space and `dollars` or `US dollars`." (A.4) | | UT (`12 million dollars`, `12,000,000 US dollars`) | U5 |
| R208 | "Amounts in other currencies are not amounts." (A.4) | `€12M`, `A$12M`, `12 million euros` -> no amount. | UT | U5 |
| R209 | A.5 "`legal_name`, `hq_city`, `ceo` -> The text as the excerpt writes it" | | UT | U5 |
| R210 | A.5 "`founded_year` -> The number as an integer" | | UT | U5 |
| R211 | A.5 "`headcount_range` -> The range of §4 that contains the number" | | UT | U5 |
| R212 | A.5 "`funding_total` -> The number times the scale (`k` and `thousand` 1,000; `m`, `mn` and `million` 1,000,000; `bn` and `billion` 1,000,000,000) in US dollars. An amount that does not come to a whole number of dollars is not a value" | `Decimal` arithmetic; non-whole -> not a value (ignored, not a conflict) (D27). | UT (`$1.2345k` not a value) | U5 |

## Brief constraints (lead)

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| R213 | "keep research spend minimal and only where it changes a field" (lead decision) | Searches and extracts run first. The 25-unit research run is started only if, after them, at least one of the six fields has no supported value (D28). Research can then only turn `unknown` fields into `known`. When all six are already known, a research claim could at most add another valid value, which does not change any field's status, so it is skipped. Typical spend is ~25-30 units without research and ~50-55 with it, cap 80. | NOT EXERCISED -> UT `test_build.py::research_skipped_when_all_known`, `::research_run_when_a_field_unknown`; verifier reads mock `/calls` per build | U7 |
| R214 | "maintainable code" (task constraint) | Small modules, one responsibility each, docstrings on public functions, unit tests for Appendix A. | RD | all |
| R215 | "No .git inside stage folders." (brief) | | CMD `find stage-1 -name .git` empty | U1 |

## Conflicts and impossibilities

- **C1 (R62 vs R3/R159)**: "evidence" is every page any search for any company-naming query
  returns. That set is unbounded, while a build may spend at most 80 units. A build can only
  approximate it. The plan covers it with field-targeted queries (plan §Search strategy) and
  records the residual risk as Open-1. This is not resolved silently.
- **C2 (R63 vs R124/R130)**: "exactly one" successful domain-query search cannot be guaranteed if
  the provider refuses that query for the whole build. Plan (D29): refused attempts are free and
  are retried until success or the build deadline (270 s) while any other call has succeeded.
  So a `ready` build lacks the domain search only if Nimble refused that one query for about
  270 s while answering others. In that residual case R124 (the build must end `ready` because
  some calls succeeded) and R130 (it must end within 300 s) win over R63. **Flagged for lead**:
  the plan accepts this residual case rather than failing a build whose other calls succeeded.
  If every call in the build is refused, retries stop after 3 and the build is `failed`, which
  matches R124.
- **C3 (R55 vs R201/R209/R181)**: §4 says `hq_city` is the city "without region or country".
  Appendix A, which §4 and A itself call "the whole definition" of support, makes the value
  the longest run of capitalised words after the phrase, "the text as the excerpt writes it".
  For `headquartered in Lisbon Portugal` (no comma), A.4/A.5 give `Lisbon Portugal`. The plan
  follows Appendix A: it is the only rule that decides support, and a trimmed `Lisbon` would
  not be the value the excerpt states under A.4. Trimming would also need a list of countries
  and regions, which the spec does not supply. A comma (`Lisbon, Portugal`) ends the run, so
  the common form gives `Lisbon`. **Flagged for lead** as a spec ambiguity. If lead rules for
  trimming, the change is confined to `support.py`'s `hq_city` value function plus its test.

## Decision log

- **D1** Only `nimble` is used. Tavily is optional (§2), costs 8-16 per search, and the live key
  set contains Nimble only. R9, R10, R15, R213.
- **D2** The manifest line is `webrouter[search,extract,research]>=0.12.0`. This satisfies "lists
  `webrouter>=0.12.0`" and installs the SDK extras §2 requires.
- **D3** Appendix A is hand-written over `str` methods: no `regex` dependency. This avoids a new
  dependency (org policy) and keeps Unicode capitalisation correct.
- **D4** Python 3.12 + Starlette + uvicorn, one worker, in-process `AsyncWebRouter`. Starlette
  rather than FastAPI because FastAPI's own 422 validation bodies conflict with §5 400/422 rules.
- **D5** SDK retries are disabled (`max_retries=0` through `provider_config`) and the service
  retries only *refused* calls (HTTP error status, 0 units). A hidden SDK retry after a timeout
  would spend units the service cannot see.
- **D6** Passwords use `hashlib.scrypt(n=2**14, r=8, p=1, dklen=32)` with a 16-byte salt, run
  through `asyncio.to_thread`. It is in the stdlib, an approved KDF, ~16 MiB per hash, and fast
  enough for 50 concurrent logins on 2 vCPU.
- **D7** When several values are supported, the field takes the value with the most distinct
  supporting URLs. Ties go to the value whose earliest supporting citation was gathered first
  (search rank order, then research), and then to the lexicographically smallest JSON
  encoding. Citations are every distinct (url, excerpt) pair supporting that value, ordered by
  gathering order.
- **D8** Timeouts: 45 s per search/extract call, research polled every 2 s (first poll right away)
  until a build deadline of 270 s from the build's start. The same constants are used for the
  mock and live, which satisfies R127-R130.
- **D9** A store generation counter is bumped by reset and import. A build captures it at start
  and discards all writes (fields, state, spent units) if it changed.
- **D10** The clock keeps the aware datetime it was given (offset preserved) and returns
  `isoformat()`. `Z` is accepted on input as `+00:00`. Input without an offset is 422.
  Comparisons ("earlier than") use absolute instants.
- **D11** Generated ids are `u_<16 hex>` and `d_<16 hex>` from `secrets`, checked unique against
  existing ids (including seeded ones).
- **D12** A citation's `url` is the URL the provider returned for the served document (the
  extract's document URL, the research claim's URL), not the URL the service asked for.
- **D13** A line is a header line when it starts with a *name* followed directly by `:`. The name
  is one or more capitalised words joined by single `-`. A capitalised word is exactly as
  defined in A.4 and implemented by the same scanner as A.4: one character with
  `str.isupper()` followed by one or more characters with `str.islower()`, any alphabet. After
  the `:` comes either a space and the value, or the end of the line. Only a leading block of
  such lines counts. The block ends at the first empty line (a line that is empty after
  stripping `\r`). If a text has header lines and no empty line, it has no prose. If the first
  line is not a header line, the text has no header.
- **D14** `Facts:` and every other header line are ignored. They are never used as values or to
  steer the build.
- **D15** Email uniqueness and login lookup are case-insensitive on the whole address. The
  stored and returned email keeps the case it was given.
- **D16** Unknown routes are 404 `not_found` and wrong methods are 405 with code
  `method_not_allowed`, both in the §5 envelope.
- **D17** A body that parses but is not a JSON object is 400 `malformed_request`.
- **D18** Integer query parameters must match `^[0-9]+$`. Leading zeros are accepted (`007` =
  7) because they are plain decimal digits.
- **D19** Email is valid iff it has exactly one `@`, a non-empty local part, a non-empty domain
  part and no whitespace.
- **D20** The idempotency record key is (user_id, method, raw path, key). The same key on another
  path is a separate first use.
- **D21** Refresh ignores its body completely, including unparseable JSON. "Same body" for
  refresh is always true.
- **D22** Check order on the two write paths: 401 auth, then 400 missing key, then 422 key
  length, then 400 body parse (POST only), then the idempotency lookup (200 replay / 409), then
  422 field validation, then the operation.
- **D23** For refresh and GET, a path domain that is invalid after normalisation is 422 before
  any 404.
- **D24** Import validation is strict: `track == "dossier"`, `format_version` an int (not bool)
  equal to 1, and `state` matching the exporter's schema, checked fully before anything is
  replaced.
- **D25** Each dossier keeps a committed snapshot (state outcome, fields, researched_at,
  spent_units) plus live build spend. Export writes the committed snapshot. A dossier with no
  completed build is exported as `failed` with all fields unknown.
- **D26** `founded_year` requires a number token of exactly four digits with no comma or
  decimal part.
- **D27** Amounts that do not come to whole dollars are ignored as values. They neither support
  nor conflict.
- **D28** Research is conditional (lead constraint R213). It runs only when, after all searches
  and extracts, some field has no supported value, and only if 25 units remain. Extracts are
  capped so that 25 units stay available while research might be needed. If the remaining
  budget is under 25, research is skipped and the build completes with what it has (R159).
  When it runs, it still asks for all six fields (R160 and the §4 evidence definition), and
  each claim is evaluated only for its own field.
- **D29** Retry policy for refused calls (HTTP error status, 0 units). The bare-domain search is
  retried with backoff (0.25 s doubling, capped at 2 s) until it succeeds or the build
  deadline, as long as any other call of the build has succeeded. If no call has succeeded, it
  stops after 3 retries. Every other call gets at most 3 retries. Timeouts and connection
  errors are charged and never retried.
- **D30** Fixture and import ids: a user `id` must be a non-empty string of at most 64
  characters, and ids must be unique. Dossier ids in an import follow the same rule. A
  violation is 422 `validation_failed` with nothing changed. This is the §3.5 bound applied
  to externally supplied ids, so every id the service returns satisfies it.

## Open items (unverified)

- **Open-1** Evidence coverage (C1): the search strategy finds every searchable company page for
  the supplied sample corpus shape (about 16 pages per company, at most 10 per query). It is not
  proven for larger hidden corpora. To settle it, the verifier compares gathered URLs with the
  mock's `/calls` log for each sample company.
- **Open-2** `provider_config={"nimble": {"max_retries": 0}}` reaching the `nimble-python` client
  is inferred from `web_router/providers/nimble.py` (`_NimbleClients.__init__` passes `**kwargs`
  into the SDK client options). Not run. The builder settles it with a one-line check in the
  container.
- **Open-3** How `ProviderError` exposes a refused status versus a timeout (`__cause__` type from
  `nimble_python`) is not verified. The builder settles it by inspecting the installed SDK
  exception classes. The plan gives the fallback rule.
- **Open-4** (partly verified) `AsyncWebRouter.submit_research(query, *, provider, output_schema,
  effort, ...) -> ResearchJob` (`web_router/client.py:751`) and `ResearchJob.aresult(...)`
  (`web_router/providers/base.py:1049`, docstring) were read. The exact `aresult` keyword for a
  timeout and the exception it raises on expiry (`ResearchTimeoutError`) come from the README
  and were not read in code. `ProviderError.original` holds the SDK exception
  (`web_router/exceptions.py:305-315`).
