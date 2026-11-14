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
  + reader.py      page pipeline: snippet screen -> plain-extract screen -> NimbleRenderReader
  (+ sessions.py   Kernel pool, only if V1b is triggered)
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

## Build strategy (per build, cap 80; Nimble-only, lead decision 4)

| Step | Calls | Units |
|---|---|---|
| A (at once) | 8 lite searches (exact domain + 6 field queries + company name), as stage 1 | 8 |
| A (at once) | research run, all six fields (S117, confirmed) | 25 |
| B1 | rendered extract of research-cited URLs (as soon as research completes) | 3 each |
| B2 | free snippet screen of search URLs; a supporting snippet sends the URL straight to B4 | 0 |
| B3 | plain-extract screen (served text, never cited) of the remaining search URLs, all at once | 1 each |
| B4 | rendered extract of every screened-in page, ranked by field-query top-3 hits, within the budget | 3 each |
| C | candidates from rendered text only -> selection -> fields | 0 |

- **Budget split:** of the 47 units left after step A, 3 renders (9 units) are reserved for
  research-cited pages until research completes. Unused reserve returns to B4. B3 is skipped
  for a URL when its B4 render could no longer be afforded.
- **Why the screen (E3):** plain served text equals browser text except on browser-only pages,
  and those are rendered whenever their served text has a statement. So 1 unit spent per page
  avoids a 3-unit render of a page that carries no candidate. The residual risk is matrix
  Open-S4. The verifier checks it with a Nimble-only harness run.
- **Kernel (V1b, conditional):** added only if the verifier's harness run shows that
  Nimble-only misses candidates within 80 units. If added, it serves only pages the Nimble
  pipeline could not afford. Nimble-only behaviour is unchanged when Kernel is absent,
  failing, or its 4 sessions are exhausted.
- **Retries (S20-S23, C-S1):**
  - 429 gets up to 3 retries, each after 1.05 s. The wait is recorded as a 429 interval.
  - Other refusals get up to 2 retries after 1.05 s (stage-1 L1 / lead carry-over).
  - The exact-domain search keeps its 3-attempt cap for non-429 refusals.
  - A session open answered 429 while the pool believes it has a free slot is retried as a
    429. After that it falls back to Nimble render.
- **Build clock (S23):** `Build.effective_elapsed()` is wall time minus the union of
  429-wait intervals. The stage-1 fast-regime cut-off reads this clock, and 429 retries are
  exempt from the cut-off.
- **Timing check:** with calls of 1 s or less, the steps run in sequence: step A (about 1 s
  for searches, about 3 s for research in parallel), then B3 all at once (about 1 s), then B4
  all at once (about 1 s), then the research-cited renders (about 1 s). That is about 5-6 s,
  plus excluded 429 waits.

## Work items

File areas are disjoint per item. The builder may split them across writers. Build order is
V0 -> V12.

### V0 Copy and keep
- **Changes:** `cp -R stage-1 stage-2` without caches, then update `RUN.md` (stage-2 name and
  the new env vars) and `requirements.txt`, which stays `webrouter[search,extract,research]>=0.12.0`.
  The `[browser]` extra is added only in V1b.
- **Rows:** S1, S118, S62.
- **Proof:** the stage-1 unit tests pass inside `stage-2/`; harness stage-1 checks keep passing
  under `--stage 2`.
- **Files:** `stage-2/Dockerfile`, `stage-2/RUN.md`, `stage-2/requirements*.txt`.

### V1 Web access, Nimble read pipeline, rate limits, budget
- **Changes:**
  - `web.py`: `extract_rendered(url)` with `provider_options={"render": True}`. The existing
    plain `extract` (`stage-1/app/web.py:102-108`) is kept for screening. `classify_failure`
    reports `refused_429` separately.
  - `budget.py`: the new costs (S15-S17).
  - `reader.py`: the B1-B4 pipeline (E3), returning `PageText(url, text, provider="nimble")`
    for rendered pages only.
  - `build.py`: the call wrapper with 429 handling (3 retries, 1.05 s) and other refusals
    (2 retries), and the effective clock (S23).
- **Rows:** S7-S11, S13, S15, S20-S23, S25, S117, S119.
- **Proof:**
  - UT `test_reader.py` with a fake router:
    - research-cited pages are rendered first;
    - a supporting snippet skips the screen;
    - a screened-out page is never rendered;
    - a static-vs-browser text mismatch yields candidates only from browser text;
    - the budget never exceeds 80.
  - UT `test_rate_limit.py`:
    - 429 three times, then 200, is read;
    - 500 three times is dropped after 2 retries;
    - the exact-domain search makes at most 3 attempts on 500s;
    - the effective clock excludes 429 waits.
  - UT `test_budget.py`: the new costs.
  - The verifier runs the harness Nimble-only and compares candidate value sets with the
    expected sets (Open-S4).
- **Edges:** an empty search; every page screened out; render failures (charged, not retried
  unless refused); a reset during a build (generation check, R31).
- **Files:** `stage-2/app/{web,budget,reader}.py`, the call and gather parts of
  `stage-2/app/build.py`, and `stage-2/tests/test_{reader,rate_limit,budget}.py`.

### V1b Kernel reader (conditional; only if the harness shows Nimble-only is incomplete)
- **Trigger:** the verifier's Nimble-only harness run shows missing candidate values within
  80 units.
- **Changes:**
  - Add `[browser]` to the webrouter extras, with Playwright pinned to a version at least
    7 days old (Open-S3).
  - `sessions.py`: a pool of at most 4 sessions (E4).
  - `KernelReader` for the pages the Nimble pipeline could not afford.
  - `provider_config["kernel"]["base_url"]` from env.
- **Must hold:**
  - The image builds reliably and `/health` answers within 60 s.
  - Nimble-only results are identical when `KERNEL_API_KEY` is absent, opening fails, or the
    sessions are exhausted (an open answered 429 at the cap falls back).
- **Rows:** S12, S14, S16-S19.
- **Proof:** UT:
  - the pool holds at most 4 sessions across 3 builds;
  - a failed `goto` is free;
  - a session that dies falls back to render;
  - with no key, the results equal the Nimble-only run.
- **Files:** `stage-2/app/{sessions,reader}.py`, `stage-2/requirements.txt`.

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

## Lead decisions (settled)

1. **G1:** accepted limitation DEV-S1 (V6, matrix E18).
2. **C-S1:** confirmed. A 429 gets 3 retries 1.05 s apart, with the waits excluded from the
   build clock. Other refusals keep the cap of 2. The exact-domain search keeps 3 attempts for
   non-429 refusals.
3. **C-S2:** confirmed. Research runs in every build.
4. **Kernel:** Nimble rendered extract is primary and complete on its own (E3). Kernel is added
   only via V1b, if the harness shows it is needed.

## Unverified

Open-S1 to Open-S3 in the matrix, and stage-1 Open-1 to Open-5. The build timing estimate
with Kernel is an estimate; it was not measured. I read the mock (`pages.py`, `corpus.py`,
`kernel.py`, `nimble.py`) only to learn how rendered and plain text differ. That is harness
material, not spec.
