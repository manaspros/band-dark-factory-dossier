# Stage 2 (dossier) - implementation plan

Companion to `plans/stage-2-matrix.md` (S1-S120, decisions E1-E17, gaps and conflicts G1,
C-S1, C-S2). Stage-1 plan rules stay in force unless the matrix "Changed stage-1 rows" table
says otherwise. No check is claimed to pass.

## Carry-forward

- **V0 (first step):** copy `stage-1/` to `stage-2/` (no `.git`), unchanged, then extend it.
  `stage-1/` is frozen (S118).
- Behaviour that must keep working (stage-1 rows still in force): auth, reset, clock,
  idempotency (R103-R119, including the 409-before-validation order), domain normalisation,
  list paging, export/import of stage-2 state, the 80-unit cap, generation checks on
  reset/import, the exact-domain search rule (3 attempts, DEV-1), the no-5xx rule, and the
  stage-1 unit tests (kept, and updated only where a row changed).
- Existing code this plan builds on, cited from the frozen copy:
  - `stage-1/app/build.py:43-45`: retry backoff 1.05 s, fast cut-off 8.0 s.
  - `build.py:128-182`: searches, extracts and research gathered concurrently. Research is
    already unconditional there.
  - `stage-1/app/web.py:102-108`: plain extract, markdown, no render.
  - `stage-1/app/store.py:98-111`: export with fields only, no page text.
  - `store.py:131-143`: import accepts only `{value,status,citations}` fields.
  - `stage-1/app/main.py:79-80`: `/dossiers/{domain:path}` routes. A GET for
    `x.test/evidence` would hit the JSON handler, so the browser route must come first.
  - `stage-1/app/support.py:142` (`prose`), `:421` (`supports`): reused unchanged for A.1-A.5.

## Architecture changes

```
Starlette app (main.py)
  + ui_routes.py   HTML shell for /, /signup, /login, /contested, /dossiers/{d}/evidence,
  |                and /dossiers/{d} when Accept has text/html; /static/* files
  + ui/            index.html, styles.css, app.js (router), api.js, format.js, reader.js,
  |                list.js, dossier.js, evidence.js, contested.js, auth.js
build.py (changed)  searches + research -> page queue -> reader -> candidates -> selection
  + reader.py      BrowserTextReader: KernelReader (sessions.py pool) | NimbleRenderReader
  + sessions.py    process-wide pool of at most 4 Kernel sessions
  + pages.py       kind / published_at from header lines (S3-S6)
  + candidates.py  page text -> candidates (field, value, url, excerpt, provider, kind, published_at)
  + selection.py   rank, select, status, citations (S34-S44)
  + migrate.py     stage-1 export state -> stage-2 state (S108-S116)
  ~ evidence.py    decide() now delegates to candidates/selection
  ~ store.py       fields carry candidates; export/import of both shapes
  ~ web.py         render extract, open_browser for kernel, 429 classification
  ~ budget.py      render 3/URL, kernel page 1, open 0
```

The UI is a single-page app in plain ES modules with no bundler, served from the image (E8).
The reason for no bundler: there is no Node toolchain in the Docker build and no third-party
front-end dependencies, and another developer can read it directly. The trade-off is that
DOM rendering is hand-written. To keep that manageable, each screen module exports
`render(state)` that builds DOM with a tiny `h(tag, attrs, children)` helper in `app.js`.

## Build strategy (per build, cap 80)

| Step | Calls | Units |
|---|---|---|
| A (at once) | 8 lite searches (exact domain + 6 field queries + company name), as stage 1 | 8 |
| A (at once) | research run, all six fields (S117) | 25 |
| B | page reads in priority order (E3): research-cited URLs first (they arrive when research completes), then search URLs ranked by top-3 hits across field queries, then the rest | Kernel 1/page, up to 47 pages; Nimble render 3/URL, up to 15 |
| C | candidates from every page read -> selection -> fields | 0 |

- **Reader selection (S12, S13):** use `KernelReader` when `KERNEL_API_KEY` is set and an open
  succeeds. Otherwise use `NimbleRenderReader`. If a Kernel session dies mid-build, its unread
  pages go to the Nimble reader within the remaining budget.
- **Page reading with Kernel:** take up to 4 sessions from the pool. Each session pulls URLs
  from a shared queue: `goto(url)`, then `read(format="text")`, with no clicks. Reserve 1 unit
  before each `goto`. Settle 1 when a page is served, and 0 on a navigation failure. Release
  sessions in `finally` (release is free).
- **Research-cited pages arriving late:** search pages start reading at once, but the build
  holds back an allowance for up to 3 research-cited pages. When research completes, its URLs
  go to the front of the queue. Any allowance they do not use returns to the queue.
- **Retries (S20-S23, C-S1):**
  - 429 gets up to 3 retries, each after 1.05 s. The wait is recorded as a 429 interval.
  - Other refusals get up to 2 retries after 1.05 s (stage-1 L1 / lead carry-over).
  - The exact-domain search keeps its 3-attempt cap for non-429 refusals.
  - A session open answered 429 while the pool believes it has a free slot is retried as a
    429. After that it falls back to Nimble render.
- **Build clock (S23):** `Build.effective_elapsed()` is wall time minus the union of
  429-wait intervals. The stage-1 fast-regime cut-off reads this clock, and 429 retries are
  exempt from the cut-off.
- **Timing check:** with calls of 1 s or less and Kernel at 4 sessions, step A takes about 1 s
  (searches) in parallel with about 3 s (research). About 25 pages over 4 sessions at 1 s or
  less each is about 7 s. That totals about 8 s, plus the research-cited pages, which load at
  the front once research completes. For a large company the build is at risk near 10 s. The
  plan lets each session pull up to 6 pages before research completes, and prioritises
  field-query hits. If the verifier measures more than 10 s, the next lever is capping
  lower-priority pages (decision for lead, not taken silently).

## Work items

File areas are disjoint per item. The builder may split them across writers. Build order is
V0 -> V12.

### V0 Copy and keep
- **Changes:** `cp -R stage-1 stage-2` without caches, then update `RUN.md` (stage-2 name and
  the new env vars), `requirements.txt` (`webrouter[search,extract,research,browser]>=0.12.0`,
  which adds Playwright for the CDP driver; Open-S3) and the Dockerfile (no browser download
  needed; Kernel's browser is remote).
- **Rows:** S1, S118, S62.
- **Proof:** the stage-1 unit tests pass inside `stage-2/`; harness stage-1 checks keep passing
  under `--stage 2`.
- **Files:** `stage-2/Dockerfile`, `stage-2/RUN.md`, `stage-2/requirements*.txt`.

### V1 Web access, reader, sessions, rate limits, budget
- **Changes:**
  - `web.py`: `extract_rendered(url)` with `provider_options={"render": True}`;
    `open_kernel()` via `AsyncWebRouter.open_browser(provider="kernel")`;
    `provider_config["kernel"]["base_url"]` from env when set; `classify_failure` returns
    `refused_429` separately.
  - `budget.py`: new costs (S15-S17).
  - `sessions.py`: a pool built on an `asyncio.Semaphore(4)`.
  - `reader.py`: `KernelReader` and `NimbleRenderReader`, both returning
    `PageText(url, text, provider)`.
  - `build.py`: the call wrapper with 429 handling and the effective clock.
- **Rows:** S7, S8, S10-S23, S25, S117, S119.
- **Proof:** UT `test_reader.py` with a fake router covering: the Kernel happy path; a failed
  `goto` is free; a session dies and the build falls back to render; 3 concurrent builds never
  hold more than 4 sessions. UT `test_rate_limit.py` covering: 429 three times and then 200
  is read; 500 three times is dropped after 2 retries; the effective clock excludes waits.
  UT `test_budget.py` for the new costs.
- **Edges:** no `KERNEL_API_KEY`; `KERNEL_BASE_URL` unset; a page 404 inside a session; budget
  exhausted mid-queue; a reset during a build (generation check, stage-1 R31) releases sessions.
- **Files:** `stage-2/app/{web,budget,sessions,reader}.py`, the call and gather parts of
  `stage-2/app/build.py`, and `stage-2/tests/test_{reader,rate_limit,budget}.py`.

### V2 Page kind and publication time
- **Changes:** `pages.py: page_meta(url, text, domain) -> (kind, published_at)`, using the
  stage-1 header parser (`support.py` D13 rule) and `clock.parse_rfc3339`.
- **Rows:** S3-S6.
- **Proof:** UT `test_pages.py` covering: all four kinds; an unknown kind with an own host and
  with a foreign host; `www.` and an uppercase host; a missing, date-only or offset-less
  `Published`; header-only text.
- **Files:** `stage-2/app/pages.py`, `stage-2/tests/test_pages.py`.

### V3 Selection and status
- **Changes:** `selection.py: rank(cands)`, `decide_field(cands) -> {value, status, citations,
  candidates}`, `same_value(a, b)`.
- **Rows:** S2, S30, S32, S34-S44, S119 (hq_city).
- **Proof:** UT `test_selection.py` covering: each rank key in isolation; permutation
  invariance; own and filing tie; null kind ranks as aggregator; no publication time ranks
  below one with a time; instants compared across offsets; the URL code-point order; the
  provider order; value order (int vs int, strings stripped); citations equal every candidate
  with the selected value, in rank order; known, contested and unknown.
- **Files:** `stage-2/app/selection.py`, `stage-2/tests/test_selection.py`.

### V4 Candidates from page text
- **Changes:** `candidates.py: from_page(page_text, domain, build_time) -> list[Candidate]`.
  It applies `prose` and `sentences` and `supports` per field. The first supporting sentence
  per (field, value) per page is kept (E5). It attaches the provider, `kind` and
  `published_at` (V2) and `retrieved_at`. Research claims contribute only their URLs (S25,
  S26).
- **Rows:** S7, S9, S10, S24, S26-S31.
- **Proof:** UT `test_candidates.py` covering: two values on one page give two candidates; the
  same value twice on one page gives one candidate; the same value on two pages gives two; a
  claim whose own excerpt supports a value still contributes nothing unless its page text
  does; excerpt provenance (each excerpt is a collapsed substring of the page text).
- **Files:** `stage-2/app/candidates.py`, `stage-2/app/evidence.py`,
  `stage-2/tests/test_candidates.py`.

### V5 Store, API shape, list
- **Changes:** `store.py` fields gain `candidates`; the dossier view returns them; a failed
  build keeps the previous candidates. `dossiers.py` list `legal_name` is the selected value.
- **Rows:** S28, S33, S45, S116.
- **Proof:** UT for: `building` shows the previous candidates; `failed` keeps them; the list
  shows a contested legal name.
- **Files:** `stage-2/app/store.py` (model and view), `stage-2/app/dossiers.py`.

### V6 Export/import and stage-1 migration
- **Changes:**
  - Export: the export state carries candidates. `format_version` stays 1 and the track stays
    `dossier` (E18).
  - Import, validation: `import_state` validates each dossier's fields against **either**
    shape (E18).
    - The stage-1 shape is a field with exactly `value`, `status` (`known` or `unknown`) and
      `citations`. It widens stage-1's strict `_valid_field` (`stage-1/app/store.py:131-143`).
    - The stage-2 shape adds `candidates`, and `status` may also be `contested`.
    - Validation is all-or-nothing before the swap.
  - Import, migration (lead ruling, DEV-S1): a stage-1-shaped field is migrated by
    `migrate.py`.
    - One candidate per (field, value, url) from the exported citations: the first exported
      excerpt for that URL, and its exported provider.
    - `kind` and `published_at` are null, and `retrieved_at` is the dossier's
      `researched_at`.
    - The field is then decided by V3. A dossier exported as `failed` with unknown fields gets
      empty candidates.
  - Kept unchanged:
    - users and their scrypt hashes;
    - token storage as sha256 of the bearer token;
    - idempotency records keyed (user_id, method, raw path, key), with fingerprints
      `{"domain": ...}` for POST and `{}` for refresh;
    - ids, `spent_units` and `researched_at`.
- **Rows:** S108-S116, DEV-S1, E18.
- **Proof:** UT `test_migrate.py` with a committed stage-1 export fixture
  (`stage-2/tests/fixtures/stage1-export.json`, produced by running the frozen `stage-1`
  service against the harness mock and exporting). It checks:
  - every field's candidates equal one per distinct (value, citation URL), with the excerpt
    and provider as exported, null `kind` and `published_at`, and `retrieved_at` equal to
    `researched_at`;
  - statuses are recomputed (known or unknown; a stage-1-contested field is `known`, DEV-S1);
  - an old bearer token still authenticates;
  - a replayed stage-1 POST /dossiers key and refresh key return 200 with the original bodies;
  - a mixed import (one stage-1-shaped dossier, one stage-2-shaped dossier) is accepted;
  - an invalid stage-1 state gives 422 and leaves the destination unchanged;
  - a stage-2 export round trip is identical.

  E2E: sign in on stage-1, lose a research response, export, import into stage-2, retry in the
  same page, and the dossier shows.
- **Files:** `stage-2/app/migrate.py`, `stage-2/app/store.py` (export/import functions),
  `stage-2/tests/test_migrate.py`, `stage-2/tests/fixtures/`.

### V7 Content negotiation and UI routes
- **Changes:** `ui_routes.py` serves the shell for `/`, `/signup`, `/login`, `/contested`,
  `/dossiers/{domain}/evidence` (registered **before** the stage-1
  `/dossiers/{domain:path}` route), and `GET /dossiers/{domain}` when `Accept` contains
  `text/html`. It also serves `/static/*` with correct content types and
  `Cache-Control: no-cache`. HTML routes need no auth. An API GET without `text/html` behaves as
  in stage 1.
- **Rows:** S46, S48, S49.
- **Proof:** S2 `test_api_and_browser_share_the_dossier_route`; UT for: `Accept:
  application/json` returns JSON; no Accept header returns JSON; a browser Accept string
  returns HTML; `/dossiers/x.test/evidence` with a JSON Accept is not the API (the shell is
  returned).
- **Files:** `stage-2/app/ui_routes.py`, `stage-2/app/main.py` (route order only).

### V8 UI shell, design system, auth state, navigation
- **Changes:**
  - `ui/index.html`: the shell.
  - `ui/styles.css`: tokens for colour (AA contrast), spacing scale, type scale, and state
    colours with icons for known, unknown, contested, building, failed, loading, success,
    refused and uncertain; `:focus-visible`; fluid layout with no horizontal scroll at
    375 px.
  - `ui/app.js`: a history router for the six routes; the `h()` helper; the shared header with
    `current-user` and `logout-button`; redirects signed-out users to `/login`.
  - `ui/api.js`: fetch wrapper with bearer token from `localStorage`, a 15 s
    AbortController, and outcome classification (ok, refused 4xx, uncertain) (E11).
  - `ui/format.js`: formats values for people (S57).
- **Rows:** S47, S52, S55-S62, S66, S67, S120.
- **Proof:** E2E `tests/e2e/test_layout.py` (Playwright) checks, at 375 and 1280 px on every
  route: no horizontal scroll, every input has a label, focus is visible. The verifier reviews
  screenshots.
- **Files:** `stage-2/app/ui/{index.html,styles.css,app.js,api.js,format.js}`.

### V9 Screens: auth, dossier, evidence, contested
- **Changes:** `ui/auth.js`, `ui/dossier.js`, `ui/evidence.js` and `ui/contested.js` render
  every data-testid in matrix S63-S98 exactly as specified:
  - `data-value` as `String(value)`;
  - `dossier-state` exact text;
  - conditional presence of `auth-error`, `dossier-researched-at`, `field-value-*`,
    `field-contested-*`, the empty-state elements and `dossier-not-found`;
  - citations as a blockquote with a link.

  Contested aggregates the paginated list plus per-dossier GETs, at most 6 at a time.
- **Rows:** S51, S53, S54, S58, S63-S65, S77-S91, S93-S98.
- **Proof:** S2 screen tests; E2E `tests/e2e/test_screens.py` asserts every testid and
  attribute against API data for a dossier with known, contested and unknown fields, plus
  imported null kinds.
- **Files:** `stage-2/app/ui/{auth,dossier,evidence,contested}.js`.

### V10 List screen and research form
- **Changes:** `ui/list.js`:
  - `dossier-search`: debounced query; latest read wins.
  - List items with `data-state`; `empty-dossiers` replaces the list.
  - Research form: POST, then navigate to the response domain on 200 or 202. `research-error`
    on 4xx; `research-uncertain` on an unknown outcome, using V11.
- **Rows:** S68-S76, S100.
- **Proof:** S2 `test_research_from_the_list_opens_the_dossier`; E2E covers: an invalid domain
  shows `research-error`; an existing domain gives 200, opens the dossier and starts no build
  (mock `/calls`).
- **Files:** `stage-2/app/ui/list.js`.

### V11 Writes with uncertain outcomes
- **Changes:** `ui/writes.js: submitWrite({method, path, body})`. It keeps one pending record
  per (method, path, canonical body) with its `Idempotency-Key`:
  - A refusal clears the record and shows the error.
  - An unknown outcome keeps the record and shows the uncertain element (nonempty text, a
    retry button).
  - A retry reuses the same key and body.
  - Success clears the record, removes both error and uncertain elements, and then reads or
    navigates (S99, S100).
- **Rows:** S69, S70, S87, S88, S99-S106, S114.
- **Proof:** E2E `test_uncertain.py` uses Playwright route interception: it forwards the
  request, then aborts the response. Checks: uncertain is shown and not error; the retry
  carries the same key header and body; on success both elements are gone and the dossier
  shows; mock `/calls` shows one build. The same flow is run across a stage-1 export into a
  stage-2 import (V6).
- **Files:** `stage-2/app/ui/writes.js`.

### V12 Reading: polling and latest-read-wins
- **Changes:** `ui/reader.js: createReader(fetchFn)` with a per-resource sequence counter. A
  response applies only if its sequence is greater than the last applied one. While the state
  is `building`, it polls every 1.5 s from each read's issue time, and stops on `ready` or
  `failed` or when the screen is left. `dossier-reload` issues a read.
- **Rows:** S92, S101, S107.
- **Proof:** E2E: delay read #1 by 3 s and let read #2 return at once, then check the screen
  shows read #2. E2E: a build in progress turns `ready` on screen without a click within 2 s
  of the API turning ready.
- **Files:** `stage-2/app/ui/reader.js`.

## Row coverage

S1-S120 each map to at least one V item (see the matrix "Where" column). Pure permissions
(S107, S115) need no code. Stage-1 rows changed by stage 2 are listed in the matrix; all others
are carried by V0.

## For lead (decisions requested)

1. **G1:** resolved by lead ruling as accepted limitation DEV-S1 (see V6 and matrix E18).
2. **C-S1:** give 429 refusals 3 retries (spec allows three 429s in a row; the wait is
   excluded from the 10 s clock). Other refusals keep the cap of 2.
3. **C-S2:** research in every build (25 units), because research-cited pages are evidence and
   are often top-authority filings.
4. Using Kernel when configured (1 unit/page) instead of Nimble render (3/URL). Without it,
   only about 15 pages fit the budget, and candidate sets would be incomplete for companies
   with 15-24 pages.

## Unverified

Open-S1 to Open-S3 in the matrix, and stage-1 Open-1 to Open-5. The build timing estimate
with Kernel is an estimate; it was not measured. I read the mock (`pages.py`, `corpus.py`,
`kernel.py`, `nimble.py`) only to learn how rendered and plain text differ. That is harness
material, not spec.
