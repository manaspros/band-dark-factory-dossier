# Stage 1 (dossier) - implementation plan

Companion to `plans/stage-1-matrix.md` (rows R1-R215, decisions D1-D27). Every row maps to a
work item below. Deliverable folder: `stage-1/`. The plan makes no claim that any check passes.

## Carry-forward

Stage 1 is the first stage. There is no earlier folder to copy and no earlier behaviour to keep.
Later stages copy `stage-1/` first, so module boundaries below are meant to be extended rather
than rewritten.

## Architecture

```
HTTP client
   |
uvicorn (1 worker, asyncio)  --  Starlette app (app/main.py)
   |
   +-- request layer: requests.py (body/query/auth parsing), errors.py (envelope)
   +-- handlers: control.py (/health, /_test/*), auth.py, dossiers.py, idempotency.py
   +-- store.py  (all state, in memory; generation counter; export/import serialisation)
   +-- clock.py
   +-- build.py  (background asyncio task per build)
          +-- budget.py   (unit costs, reservation, 80-unit cap)
          +-- web.py      (the ONLY importer of web_router; AsyncWebRouter, nimble only)
          +-- evidence.py (candidates -> six fields + citations)
                 +-- support.py (Appendix A: prose, sentences, formats, supports())
```

Choices (matrix D4, D1, D3, D6):

- **Python 3.12, Starlette, uvicorn, in-process `AsyncWebRouter`.** WebRouter is Python, so the
  service runs it in-process and needs no helper process (§2 allows either). Starlette is used
  instead of FastAPI so the service owns every 400/422 decision.
- **One process, one event loop, state in memory.** §11 serialisability comes from one rule:
  *no `await` between reading and writing shared state.* Every handler does its validation,
  then one synchronous critical section. The only awaits are password hashing (before the
  critical section) and the background build (whose writes are synchronous and
  generation-checked).
- **Dependencies** (`stage-1/requirements.txt`, pinned to versions at least 7 days old, per
  org policy): `webrouter[search,extract,research]>=0.12.0`, `starlette`, `uvicorn`. Nothing
  else. Tests use `pytest` and `httpx` from `stage-1/requirements-dev.txt`. These are not
  installed in the runtime image.

## Search strategy and budget (the core of R3, R62-R65, R152-R160, R213)

Per build, all through `nimble`, with `max_results=10`:

| Wave | Call | Count | Units |
|---|---|---|---|
| 1 (concurrent) | search `lite`, query = exactly the normalised domain | 1 | 1 |
| 1 (concurrent) | search `lite`, one per field: `f"{domain} {terms}"` with terms from A.3 (e.g. `"legal name registered name"`, `"headquartered in based in head office"`, `"chief executive officer CEO"`, `"founded established incorporated"`, `"employees staff headcount"`, `"raised funding investment"`) | 6 | 6 |
| 1 (concurrent) | search `lite`, query = company name (`acme robotics`) | 1 | 1 |
| 2 (concurrent, at most 8 in flight) | extract (default markdown format, no `render`), one URL per call, for the union of result URLs in rank order: domain query first, then field queries, then name query | <=N | 1 each |
| 3 | evaluate all gathered text (`support.candidates`) -> provisional fields | - | 0 |
| 4 (only if some field is unknown, D28) | research run: `submit_research(query=f"Company profile of {domain}: legal_name, hq_city, ceo, founded_year, headcount_range, funding_total", output_schema=SIX_FIELD_SCHEMA, effort="low")`, then await the result | 0 or 1 | 0 or 25 |

- Typical spend: 8 + about 16 to 20 extracts, so about 25 to 30 units. Add 25 when research
  is needed. **Budget rule:** the 8 searches (8) are reserved first. Extracts may use at most
  80 - 8 - 25 = 47 units, which keeps 25 available for a possible research run. Research runs
  only if a field is still unknown after wave 3 and 25 units remain. URLs beyond the extract
  allowance are not extracted. The cap is never crossed (R159).
- **Why research is conditional (lead constraint, R213, D28):** a research claim only matters
  if it supports a value for a field that has none. For a field that already has a supported
  value, a claim could add only another valid value, and §4 lets the field keep either. So
  research changes the outcome exactly when some field is unknown, and runs only then.
- **Why lite plus extract and not deep search:** lite costs 1 unit and returns 10 URLs. Nimble
  extract costs 1 unit per page and returns the full served text, so a full page costs 1 unit
  plus a share of a search. `deep` costs 15 units for at most 10 full pages. Field-targeted
  queries put the company's pages that carry field statements at the top of each result list.
  Each query also contains the domain, so the company's own pages rank first.
- **Exactly one domain query (R63-R65, D29):** the domain query is the only query that equals
  the domain string. All other queries add terms. If it is refused (HTTP error status, 0
  units), it is retried with backoff starting at 0.25 s, doubling, capped at 2 s. Retries
  continue until it succeeds or the build deadline, as long as any other call of the build has
  succeeded. If nothing in the build has succeeded, it stops after 3 retries, so an all-refused
  build fails fast. After one success it is never repeated. The residual case is flagged to
  lead as matrix C2: the domain query is refused for the whole build while other calls
  succeed.
- **Research (R69, R160):** the query contains the normalised domain. The schema's
  `properties` are exactly the six field names (types: string/integer, nullable). Claims come
  from `ResearchResponse.citations` with `field == "$.<name>"`. For each claim, take every
  excerpt in `citation.extra["excerpts"]` (falling back to `citation.snippet`). These are
  candidates for that field only. `structured` values are **never** used.
- **Lite snippets** are used for URL discovery only, never as citations. Citations come from
  extracted page prose and research excerpts.
- **Retries:** only *refused* calls are retried, i.e. a `ProviderError` whose `original` is an
  SDK HTTP-status error (any 4xx/5xx), which costs 0 units. The domain query follows the rule
  above. Every other call gets up to 3 retries with 0.25 s / 0.5 s / 1 s backoff, within the
  build deadline. Timeouts and connection errors are charged in full
  and **not** retried. SDK-internal retries are off: `provider_config={"nimble":
  {"max_retries": 0, "timeout": 45}}` (matrix Open-2). Fallback rule if the exception type
  cannot be told apart (Open-3): treat an unknown failure as charged, which is safe for R3.
- **Extract cost (R157):** each extract call is charged 1 unit whether it returns a document, a
  `failures` entry, or raises after an HTTP 200. Only a refused HTTP status is free.
- **Time (R127-R130, D8):** wave 1 runs concurrently, wave 2 runs concurrently, and the
  conditional research run comes last (the mock completes it on the first poll). Each call has a 45 s timeout. The research result is awaited until build start
  + 270 s. If the deadline passes, the build decides with what it has. With 1-second mock
  calls this takes 3 to 4 s, inside 10 s.
- **Outcome (R124):** `failed` iff zero provider calls succeeded (a refused or timed-out call
  is not a success). Otherwise `ready`.

## Work items

Each item lists: what changes; rows delivered; proof; edges that must hold; files it may touch.
One builder writes all of `stage-1/`, but the file areas below are disjoint, so items can be
split between writers without collisions. Build order is U1 -> U11.

### U1 Container and packaging
- **Changes:** `stage-1/Dockerfile` (`python:3.12-slim`, `pip install --no-cache-dir -r
  requirements.txt`, non-root user, `CMD` starts uvicorn on `0.0.0.0:${PORT:-8080}`, one worker).
  `stage-1/requirements.txt`, `stage-1/requirements-dev.txt`, `stage-1/.dockerignore`.
  `stage-1/RUN.md` gives one build+run command (`docker build -t dossier stage-1 && docker run
  --rm -p 8080:8080 -e PORT=8080 -e NIMBLE_API_KEY -e NIMBLE_BASE_URL dossier`) and says how to
  run the unit tests. RUN.md also has a "Sources" line: built from the stage-1 requirements and
  WebRouter's own documentation only (R216, R217). There are no packaging files (`setup.py`,
  `pyproject.toml`): the deliverable is the image (R218).
- **Rows:** R6-R8, R12, R13, R16, R20-R23, R215-R219.
- **Proof:** harness build; `grep webrouter stage-1/requirements.txt`; `find stage-1 -name .git`.
  For R219, build and run from a fresh clone on a host with no project virtualenv; `/health`
  must answer 200. For R216, the verifier reads the code (no vendored or copied third-party
  product code or schemas), and the builder's handoff lists the sources it consulted.
- **Edges:** no network at container start; no key value appears in any file; image builds
  from a clean checkout.
- **Files:** `stage-1/Dockerfile`, `stage-1/RUN.md`, `stage-1/requirements*.txt`,
  `stage-1/.dockerignore`.

### U2 App skeleton: errors, request parsing, clock, domains, store shell
- **Changes:**
  - `app/main.py`: Starlette routes, startup, and a catch-all exception handler that returns
    the §5 envelope. Unknown route -> 404 `not_found`; wrong method -> 405
    `method_not_allowed` (D16).
  - `app/errors.py`: `ApiError(status, code, message)` and the envelope.
  - `app/responses.py`: `json_response` with `application/json; charset=utf-8`.
  - `app/requests.py`: `read_json_object(request)` gives 400 on unparseable input or a
    non-object (D17). It also provides typed getters: `require_str(body, name)` gives 422 if
    missing and 400 if the type is wrong (a JSON `null` counts as the wrong type).
    `query_int(params, name, default, lo, hi)` uses `^[0-9]+$`, else 422 (R87).
  - `app/clock.py`: `Clock.now()` returns system UTC until first set. `set(dt)` rejects
    earlier instants. `parse_rfc3339(s)` requires an explicit offset (D10).
  - `app/domains.py`: `normalise(raw) -> str` raises 422 (R47-R49).
  - `app/store.py`: the `Store` dataclass (users, emails index, token hashes, dossiers by
    domain, idempotency records, generation) and `Store.replace(new)`.
- **Rows:** R17, R21, R24, R26, R33, R36-R38, R41-R43, R47-R49, R79, R80, R85-R88, R91, R180.
- **Proof:** UT `test_domains.py` (valid 253-char domain, 63-char label, `-a.test`,
  `http://x.test`, `x.test/a`, `www.`-only, `localhost`, uppercase, trailing dot).
  UT `test_clock.py` (system time before set, frozen after set, `Z` and `+02:00` accepted,
  naive rejected, earlier rejected, equal accepted). UT `test_requests.py`.
- **Edges:** empty body; body `[]` or `"x"` or `null` gives 400; JSON with a BOM is accepted;
  a 254-char domain is rejected; `www.www.x.test` keeps one `www.`; a domain that is only
  `www.test` normalises to `test` (one label) and is rejected.
- **Files:** `stage-1/app/{main,errors,responses,requests,clock,domains,store}.py`,
  `stage-1/app/__init__.py`.

### U3 Auth, reset, clock endpoint, health
- **Changes:**
  - `app/auth.py`: scrypt hash/verify (D6) via `asyncio.to_thread`; `signup`; `login`;
    `authenticate(request) -> user_id`. Only `Authorization: Bearer <token>` with a known
    token passes; all other forms give 401. Tokens are `secrets.token_urlsafe(32)` and only
    their `sha256` is stored. Emails are unique case-insensitively (D15); email shape per D19.
  - `app/control.py`: `GET /health`; `POST /_test/reset` validates the fixture fully
    (`now` required and RFC 3339; `users` list optional, default empty; each user has string
    `id`, `email`, `password`, `display_name`; `id` is 1-64 characters (D30); duplicate emails
    -> 422; duplicate ids -> 422),
    hashes passwords, then swaps state, bumps the generation and sets the clock in one
    critical section. `POST /_test/clock`.
- **Rows:** R25, R27-R32, R34, R35, R39, R40, R45, R75-R78, R82, R92-R102, R176.
- **Proof:** supplied A tests; UT `test_auth.py` (seeded login returns fixture id; export
  contains no plaintext password; a 64-character fixture id is accepted, while a 65-character
  or empty id gives 422 and leaves the state unchanged).
- **Edges:** signup of a seeded email gives 409; two concurrent signups with one email give
  one 201 and one 409 (the email check and insert happen after hashing, inside the critical
  section); reset while builds run (generation bump, R31); reset with zero users; password of
  exactly 8 characters; `display_name` of exactly 100 characters; `Bearer` with an empty
  token; lowercase `bearer` scheme gives 401 (D: only the exact scheme `Bearer` is accepted).
- **Files:** `stage-1/app/{auth,control}.py`.

### U4 WebRouter adapter
- **Changes:** `app/web.py` is the only module that imports `web_router`. It builds one
  `AsyncWebRouter(Provider.NIMBLE, provider_config={"nimble": {"max_retries": 0, "timeout":
  45}})` lazily (never at import or health). It exposes `search_lite(query)`, `extract(url)`
  and `start_research(query, schema)` / `await_research(job, timeout)`. Each returns a
  `CallOutcome(ok: bool, charged: bool, data)`, with exceptions classified as refused
  (charged=False) or lost (charged=True) (Open-3). `search_depth="lite"` and `max_results=10`
  are passed explicitly; `format` is left default and `render` is never set. It never reads or
  logs key values.
- **Rows:** R9-R11, R14, R15, R20, R61, R128, R153-R158.
- **Proof:** UT `test_web.py` with a stub router, covering the classifier for HTTP-status
  error, timeout, connection error and extract failures. RD: `grep -rn web_router
  stage-1/app` hits only `web.py`.
- **Edges:** `NIMBLE_API_KEY` missing gives `ConfigurationError` at first call; the build
  then ends `failed` and no 5xx is returned. An empty search result list is a success with no
  URLs.
- **Files:** `stage-1/app/web.py`.

### U5 Appendix A engine
- **Changes:** `app/support.py`, pure functions with no I/O:
  - `prose(text) -> str` strips the header (D13).
  - `sentences(prose) -> list[str]` (A.1, legal-suffix exception).
  - `collapse(s)` collapses whitespace runs.
  - `company_name(domain)`.
  - `supports(excerpt, field, domain) -> value | None` implements A.2 conditions 1-5 with
    phrase tables (A.3), token scanners for capitalised/uppercase words, numbers and amounts
    (A.4), and normalisation (A.5).
  - `candidates(text, domain) -> list[(field, value, excerpt)]` returns every (sentence,
    field) that supports a value, for sentences of 1 to 500 characters after collapsing.
- **Rows:** R1, R2, R53-R57, R66-R68, R72-R74, R181-R212.
- **Proof:** UT `test_support.py` must include: the six A.2 example rows verbatim; the
  examples in §4 (`$12M`, `12 million dollars`, `about 120 people`); every A.4 example
  (`Zürich`, `Müller`, `AI`, `USA`, numbers `120`, `1,200`, `12.5`, `12,000,000`, every
  amount example); suffix sentences (`Acme Robotics, Inc. was founded in 2014.` is one
  sentence and supports `founded_year` 2014 and `legal_name` `Acme Robotics, Inc.`);
  closers (`He said "it was founded in 2014." Then` splits after the closing quote);
  whole-word matching (`CEOs`, `unfounded`, `notable` do not match `CEO`, `founded`, `not`);
  conflicts (`founded in 2014 and 2015` gives no value; `51-200` gives a range but `40-60`
  gives none); a non-whole amount (`$1.2345k`) is ignored; other currencies (`€12M`, `A$12M`);
  header removal per D13: `Facts: {...}`, `Größe: 5` and `Über-Uns: x` header lines are
  stripped. A first line `CEO: Sam Ortiz` (an uppercase word, not a capitalised one) is not a
  header line, so the text is all prose. A header with no following empty line leaves no
  prose. A 501-char sentence is not citable.
- **Edges:** empty text; text with only header lines; `\r\n`; a sentence ending at end of
  line without whitespace after; non-ASCII letters adjacent to matches; the domain written in
  uppercase inside a sentence; `www.` prefix adjacent to the domain match.
- **Files:** `stage-1/app/support.py`, `stage-1/tests/test_support.py`.

### U6 Evidence to fields
- **Changes:** `app/evidence.py: decide(candidates) -> dict[field, FieldResult]`. Candidates
  carry (field, value, url, excerpt, provider, order). The function groups by value, applies
  D7, and returns `{value, status, citations}` for all six fields, with deduplicated
  citations. Research-claim candidates are evaluated only for the claim's own field (R69).
- **Rows:** R1, R2, R5, R52, R58-R60, R69-R71, R126.
- **Proof:** UT `test_evidence.py` covering: no candidates gives six unknown fields; an
  unsupported research claim gives unknown; a conflict picks per D7 and cites only that value;
  the same excerpt from two URLs gives two citations.
- **Files:** `stage-1/app/evidence.py`, `stage-1/tests/test_evidence.py`.

### U7 Build runner and budget
- **Changes:** `app/budget.py`: the cost table (R152), `Budget(cap=80).reserve(units) ->
  bool`, `refund(units)` for refused calls, and `spent`. Each charged unit is also added
  immediately to the dossier's live `build_spent` when the generation still matches.
  `app/build.py`: `run_build(store, dossier_id, generation, started_at)` implements the wave
  plan above, including the conditional research (D28) and the domain-query retry policy
  (D29). Every candidate carries the provider and URL of the call outcome that served its text
  (R61). At the end, if the generation is still current, it does one synchronous commit:
  on `ready` it replaces fields, sets `researched_at = started_at` and outcome `ready`; on
  `failed` it sets outcome `failed` and leaves fields and `researched_at` as they were. Either
  way it moves `build_spent` into `spent_units` and clears `running`. Exceptions inside the
  build are caught and the build ends normally (`failed` if nothing succeeded).
- **Rows:** R1, R3, R4, R31, R61-R65, R120, R124, R125, R127-R131, R141, R145, R152,
  R155-R157, R159, R160, R213.
- **Proof:** UT `test_build.py` with a fake `web` module. Cases: (a) the domain query is
  refused once, then succeeds, and is made exactly once successfully; (b) total units <= 80
  when the search returns 30 distinct URLs; (c) a timeout is charged; (d) all calls refused
  gives `failed`, fields unchanged, `spent_units` 0; (e) a reset mid-build leaves the new
  state untouched; (f) the deadline is hit and the build decides with partial data; (g) a
  refresh charges again; (h) the domain query is refused 5 times while other searches succeed,
  is retried, succeeds once, and the build ends `ready`; (i) every call is refused, so the
  build ends `failed` within about 2 s; (j) research is skipped when all six fields are known
  from pages, and runs when one is unknown (and its supported claim fills that field, while
  an unsupported claim leaves it unknown); (k) citation provenance: every emitted citation's
  (provider, url) was served by a fake call, and its excerpt is a whitespace-collapsed
  substring of that call's text; (l) all gathered text is evaluated: a supporting sentence in
  the last-extracted page reaches its field. CMD: time one build against the harness mock
  (<10 s).
- **Edges:** zero URLs found; one URL; research refused but searches succeed (`ready`);
  research times out (charged 25); two builds of different dossiers run at once with
  independent budgets.
- **Files:** `stage-1/app/{budget,build}.py`, `stage-1/tests/test_build.py`.

### U8 Dossier write and read endpoints, idempotency
- **Changes:**
  - `app/idempotency.py`: record key `(user_id, method, raw_path, key)` (D20) holding
    `{fingerprint, body}`.
  - `check(...)` returns `replay(body)`, `conflict`, or `first`.
  - `remember(...)` stores only 2xx outcomes (R112).
  - Fingerprint: `POST /dossiers` uses canonical JSON of `{"domain": body.get("domain",
    <absent>)}`. Refresh always uses a constant fingerprint (D21).
  - `app/dossiers.py`:
    - `POST /dossiers` order (D22): auth -> key present (400) -> key length (422) -> body
      object (400) -> replay/409 -> `domain` type (400) / missing or invalid (422) -> one
      critical section. The section either creates the dossier, sets `running`, and spawns
      `run_build` (202), or returns the existing dossier (200). Then `remember`.
    - `POST /dossiers/{domain}/refresh`: auth -> key checks -> replay/409 -> path domain (422)
      -> 404 -> one critical section that starts a build unless one is running. Returns 202
      with the same body either way.
    - `GET /dossiers/{domain}`: auth -> 422 -> 404 -> view. The view shows `state =
      "building"` if running, else the last outcome; `fields` and `researched_at` from the
      last `ready`; `spent_units = spent_units + build_spent`.
  - Build time: `clock.now()` read at the start of the handler (R122).
- **Rows:** R46, R50, R51, R81, R83, R84, R89, R100, R103-R123, R132-R144, R146, R180.
- **Proof:** supplied S/D tests; UT `test_idempotency.py` through Starlette's `TestClient`
  plus `asyncio.gather` on an ASGI client. Cases: replay 200 equal body; replay after a
  refresh changed the state still returns the original, *and* a replay of the original POST
  and of the original refresh leaves the fake web's call count, the store's build-start
  counter and `spent_units` unchanged (R117); 409 on a different domain; 409 when
  the replay body is invalid (`{"domain": 5}`) after a success; key reuse after a 422 is a
  first use; the same key on POST and on refresh does not interact; two users with the same
  key; `Acme.test` vs `acme.test` with one key gives 409; unknown fields do not affect replay;
  20 concurrent identical requests give one 202 and nineteen 200s with identical bodies, and
  one build is started; 20 concurrent requests for one domain with distinct keys give one
  dossier and one build; missing key with no token gives 401; refresh during a build gives
  202 and no second build.
- **Edges:** `Idempotency-Key` of 255 vs 256 characters; whitespace-only key (non-empty, so
  valid); a refresh body that is invalid JSON is ignored.
- **Files:** `stage-1/app/{dossiers,idempotency}.py`, `stage-1/tests/test_idempotency.py`,
  `stage-1/tests/test_dossiers_api.py`.

### U9 List endpoint
- **Changes:** `GET /dossiers` in `app/dossiers.py` (same file as U8, written after U8 by the
  same writer). It parses `q`, `limit` and `offset`, filters with `casefold`, sorts by domain,
  slices, and sets `has_more = offset + limit < total`.
- **Rows:** R44, R87, R90, R147-R151.
- **Proof:** supplied D list tests; UT for `limit=200`, `offset` past the end (empty list,
  `has_more` false), `limit=0`, `limit=201`, `limit=+4`, `offset=-1`.
- **Files:** `stage-1/app/dossiers.py` (list function only).

### U10 Export and import
- **Changes:** `app/control.py` gets `GET /_test/export` and `POST /_test/import`.
  `app/store.py` gets `to_json()` and `from_json()` with full validation (D24). The
  serialised state holds users (id, email, display_name, salt, hash), token hashes ->
  user_id, and dossiers (id, domain, committed outcome, fields, researched_at string,
  spent_units). Import also applies D30 (ids of 1-64 characters, unique). The committed snapshot is used, so a running build is excluded (D25). It also
  holds idempotency records. Import validates, then replaces the store in one critical
  section and bumps the generation. The clock is untouched.
- **Rows:** R45, R161-R175, R177-R179.
- **Proof:** UT `test_export_import.py` covering: round trip equality; login and the old
  token work after import; a replay after import returns the original body; importing twice
  equals importing once; an export during a build shows the pre-build state (`failed` and
  unknown fields if first build); 422 for wrong track, version `2`, version `true`, a missing
  `state`, or a malformed user, with the destination unchanged; a later write in the source
  does not change an earlier export.
- **Files:** `stage-1/app/{control,store}.py` (export/import functions only),
  `stage-1/tests/test_export_import.py`.

### U11 Load and timing check (proof only, no product code)
- **Changes:** `stage-1/tests/load_check.py`, a script run by hand against a running container.
  It sends 50 concurrent mixed requests (signup, login, GET, POST /dossiers) and asserts no
  5xx and every response under 5 s. It also asserts one build reaches `ready` within 10 s
  against the mock.
- **Rows:** R18, R19, R91, R127, R180.
- **Files:** `stage-1/tests/load_check.py`.

## Row coverage

Every row R1-R219 appears in at least one work item above or is a pure permission (R21) or
process rule (R214 applies to all items, R215 to U1). Rows not exercised by supplied checks
are listed with their proofs in the matrix "Verified by" column.

## What the verifier should look at first (rows no supplied check exercises)

R1/R61/R62 (support, provenance and coverage; the supplied checks are only partial here),
R3/R159 (cap), R31 (reset during a build), R213 (research only when a field is unknown), R62-R65 (exactly one domain query), R69-R71
(unsupported research claims, conflicts), R104-R119 (idempotency beyond the simple replay),
R123/R134/R144 (one build at a time), R141 (spent units match the mock `/calls` log),
R163-R178 (export/import), and A.1/A.4 edge cases (R182-R212).

## Unverified

See matrix Open-1 to Open-4. In short: evidence coverage on hidden corpora; whether
`max_retries`/`timeout` reach the Nimble SDK through `provider_config`; how refused and lost
calls show up in exceptions; and the `ResearchJob.aresult` timeout keyword. The following are
mock behaviour read in `challenges/dossier/web/mockweb/{nimble,search,research,admin}.py`, not
spec: lite is 1 unit, extract returns full served text, faults are 429/500 at 0 cost, and
research claims carry `excerpts`. They agree with §9.
