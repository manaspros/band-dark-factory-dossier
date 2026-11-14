# Stage 4 (dossier) - implementation plan

Companion to `plans/stage-4-matrix.md` (F1-F96, D4-1..D4-12). Every earlier row and lead ruling
stays in force:
- 429 retries ×3 at 1.05 s, off the clock;
- other refusals ×2;
- exact-domain search, 3 attempts;
- hq_city per A.4;
- Nimble rendered extract in priority order to the 80-unit cap (DEV-S2);
- the HTML routes serve a data-free shell, and the JSON API needs a bearer token;
- type-safe import that never returns 5xx, with every excerpt supporting its value;
- SQLite WAL with `synchronous=FULL`, committed before the response.

I claim no check passes.

## Carry-forward

- **U0 (done, ebc3dcf):** `stage-4/` is a byte copy of `stage-3/` at 0ffd736. The builder
  verified it: 344 unit tests pass and the image builds (`plans/builder-notes-stage-4.md`).
  `stage-1/`, `stage-2/` and `stage-3/` stay frozen (F88).
- **Behaviour to keep:**
  - every stage-1/2/3 row;
  - the stage-2 screens and testids;
  - the generation check on reset/import (`build.py:280-283`);
  - one synchronous section per mutation (`store.py:1-10`, `dossiers.py:1-6`);
  - the stage-1/2/3 import paths (`transfer.py:68-89`);
  - `learned_at` identity (`selection.py:52-54`);
  - the executives typing (`history.py:61-73`);
  - the retry policy (`build.py:165-186`);
  - `classify_failure` (`web.py:71-82`).
- **Existing code this plan builds on** (all `stage-4/app/`, read at 679a833):
  - `pages.py:18-34`: host normalisation and `page_kind`.
  - `support.py:167-183`: `header()`.
  - `support.py:381-396`: the run scanner `_person_names`.
  - `support.py:479-494`: `candidates()`.
  - `candidates.py:16-30`: per-page candidates.
  - `selection.py:22-119`: the `Candidate` model, `rank`, `decide_field`.
  - `executives.py`.
  - `fields.py:8-25`: `ALL_FIELDS`, `decide`.
  - `history.py:83-100`: `entries_for_build`.
  - `commit.py:16-44`: `record_build`.
  - `timeline.py:28-90`: `as_of`, `/values`.
  - `budget.py:27-55`: `Budget`.
  - `build.py:109-290`: `Build`, `Builds`.
  - `store.py`, `db.py`: the state and schema.
  - `transfer.py`, `restore.py`, `migrate.py`: import/export.
  - `main.py:81-111`: routes.

## Architecture changes

```
pages.py (lineage) --> origins.py (rules 1-4, hop cap; fetch callback) <-- build.py (fetch originals)
support.py (investor names) --> candidates.py (Candidate.origin, corrected kind)
fields.decide --> selection.decide_field | executives.decide_executives | investors.decide_investors
              --> corroboration.add_keys(field, ...)   origins / corroborated (current candidates)
commit.record_build --> corroboration.since(ready builds + new)   corroborated_since
Budget(cap=80, parent=BatchBudget) --> durable spend (db.running) before each call
startup: db.load -> recover running rows as failed builds -> /health 200
```

## Work items (build order U1 → U11)

One writer per file area. When one person builds sequentially, the order still matters,
because later items import earlier ones.

### U1 Lineage, kind, lookalike, origin resolution
- **Files:**
  - `stage-4/app/pages.py`;
  - new `stage-4/app/origins.py`;
  - `stage-4/tests/test_lineage.py`, `test_origins.py`.
- **Changes:**
  - `pages.py` gains `Lineage(registrant, canonical, first_published_by, states_own)` and
    `lineage(url, text)`. It reads the three header lines plus `Kind`, normalises and
    validates them (D4-1), and defaults the registrant to `_host_domain(url)`.
  - `page_kind(url, text, domain)` gets a final step: a kind of `own` with registrant ≠
    domain becomes `aggregator` (F9-F10).
  - `is_lookalike(lineage, url)` (F11).
  - `origins.py`: `async def resolve(page_url, lineage, domain, fetch) -> str`. `fetch(url)`
    is a callback returning `Served(url, lineage) | None`. `Served.url` is the URL the
    provider served the original at (`Page.url`, `web.py:115`), which may differ from the
    requested Canonical URL after a redirect. None means not served (F17, D4-4, D4-15).
  - The rules apply in order, 1 → 2 → 3 → 4, and rule 2 recurses with `hops_left` starting
    at 3. The recursion uses `Served.url` as the original's own URL. That URL drives the
    self-canonical test (F13), the registrant default (F8) and the lookalike host (F11), so
    `lineage(...)` for an original is parsed with `Served.url`, never with the requested URL
    (D4-16).
  - When the hops run out, or `fetch` returns None, the result is `host(requested url)`.
  - The module has no provider imports, so it is testable with a dict-backed fetch.
- **Rows:** F4-F15, F17, F18.
- **Proof:** the UT cases named in the matrix rows. The edges:
  - no header at all → host;
  - an FPB that is invalid (D4-1);
  - a self-canonical page;
  - a 3-hop chain resolving at hop 3 by FPB;
  - a 4th hop → host;
  - an A↔B cycle → terminates via the cap;
  - an original that is itself a lookalike → company domain;
  - a redirected original: Canonical U served at U′ (`Served.url = U′`) whose own Canonical is
    U′ → self-canonical, so the rules use registrant host(U′); with a Kind own header and no
    Registrant, the lookalike test uses host(U′);
  - an unserved original → host of its URL.

### U2 Investor names (Appendix A)
- **Files:**
  - `stage-4/app/support.py`;
  - `stage-4/app/candidates.py`;
  - `stage-4/tests/test_support_investors.py`.
- **Changes:**
  - `INVESTOR_PHRASES = ("investor", "investors", "led by", "backed by", "participated")`;
  - `INVESTOR_SUFFIXES = ("Ventures", "Capital", "Partners", "Fund", "Investments",
    "Holdings", "Equity")`;
  - `investor_names(excerpt, domain) -> list[str]` applies A.2 rules 1-4 (single sentence,
    names the company, contains an investors phrase, no negating phrase), then:
    - remove the company-name and phrase spans;
    - form maximal runs of capitalised words joined by a single space;
    - keep runs of 2 or more words ending in a suffix;
    - when `_amounts(text)` is non-empty, also keep the maximal run whose first word starts
      exactly 1 character after the end of a `led by`/`backed by` span;
    - return the names in text order, without duplicates.
  - `candidates()` yields one `Support("investors", name, excerpt)` per name.
  - `candidates.from_page` keys `found` by `(field, title, value_key)` as now. Investors
    entries pass through, and `title` stays None.
- **Rows:** F36-F42.
- **Proof:** UT with both spec examples verbatim, plus:
  - `Acme Robotics is backed by Northwind Ventures and Bluebird Capital.` → 2 names;
  - a maximal run `Big Sky Capital Partners`;
  - a one-word suffix run → none;
  - no amount with `led by Dana Ruiz` → none;
  - an amount with `led by Sequoia` → `Sequoia`;
  - a negation → none;
  - two sentences → none;
  - a company name inside a run splits it (`Acme Robotics Ventures` alone → none).
- **Edge:**
  - the same name twice in one sentence gives one candidate;
  - the existing six fields and titles are unaffected; existing `test_support*.py` stays green.

### U3 Field model: origin, investors, corroboration keys
- **Files:**
  - `stage-4/app/selection.py`;
  - `stage-4/app/executives.py`;
  - new `stage-4/app/investors.py`;
  - new `stage-4/app/corroboration.py`;
  - `stage-4/app/fields.py`;
  - `stage-4/tests/test_investors.py`, `test_corroboration.py`, `test_selection.py`.
- **Changes:**
  - `Candidate.origin: str | None = None`. `as_json` emits `origin` after `kind`, and
    `from_json` reads `data.get("origin")`. `identity()` is unchanged.
  - `unknown_field()` gains `origins: [], corroborated: False, corroborated_since: None`.
  - `investors.decide_investors(cands)` implements F43-F49:
    - group the candidates by `value_key`;
    - membership: own/filing, or ≥ 2 distinct origins;
    - the value is the sorted member names;
    - every candidate is listed in rank order with `selected = name in members`;
    - citations are per member, in value order;
    - `true_from` per F49;
    - status `known`/`unknown`.
  - `corroboration.py`:
    - `members(name, field) -> dict[key, list[candidate-json]]`. Six fields: one key, the
      selected value. Executives: `(title, name)` per member. Investors: name per member.
    - `current_keys(name, field)` gives `origins` and `corroborated` (F21-F22, F29-F31).
    - `since(name, snapshots, times)` runs the walk of F23-F25 and F32-F33 over the ready
      builds' field snapshots, in build-number order. It returns the time or None.
  - `fields.ALL_FIELDS = FIELDS + (EXECUTIVES, INVESTORS)`. `decide()` adds investors and then
    `current_keys` for every field. `corroborated_since` is left None here; it is set at
    commit (U4) or import (U9).
- **Rows:** F10, F18-F25, F29-F34, F43-F49.
- **Proof:** the UT cases in the rows. The edges:
  - empty candidates → unknown with all keys;
  - one candidate;
  - investors with candidates but no member → unknown with listed candidates;
  - a contested six-field (only the selected value's origins count);
  - executives with one member at 1 origin → `corroborated` false.

### U4 History, typing and commit
- **Files:**
  - `stage-4/app/history.py`;
  - `stage-4/app/commit.py`;
  - `stage-4/tests/test_history.py`.
- **Changes:**
  - `entry_type()` gains an investors branch (F51-F53). The names are the symmetric
    difference; a name counts when it is in the new value and the dates satisfy F52; a removed
    name → `change`.
  - `record_build()`:
    - after `stamp_fields`, sets each field's `corroborated_since` with
      `corroboration.since(name, [b.fields for b in ready_before] + [fields], times)`;
    - also stores candidate origins (they are already on the candidates);
    - the failed path is unchanged, except it also deletes the `running` row (U7).
  - Feed order follows `ALL_FIELDS`, so investors is last (F35).
- **Rows:** F23, F35, F51-F53, F85.
- **Proof:** UT investors typing matrix:
  - added-only with earlier dates → correction;
  - added and removed → change;
  - an added name with a null date → change;
  - the earlier value null → change.

  UT feed order with all 8 fields changing.

### U5 Build: queries, originals, research failure, nested budget
- **Files:**
  - `stage-4/app/build.py`;
  - `stage-4/app/budget.py`;
  - `stage-4/tests/test_build.py`, `test_build_origins.py`, `test_provider_failure.py`,
    `test_budget.py`.
- **Changes:**
  - `budget.py`:
    - `Budget(cap=80, parent=None, on_change=None)`. `reserve(units)` succeeds only when it
      fits its own cap and the parent's (`BatchBudget.reserve`), and then calls `on_change`.
    - `settle(units, charged)` settles both levels.
    - `BatchBudget(cap)` has `reserved`, `charged` and `exhausted`. A refused reservation sets
      `exhausted`, and from then on every reservation is refused (F68).
  - `Build`:
    - **Investors query:** `queries()` gains `investors_query(domain) = f"{domain} investors
      backed by led by"` (1 unit).
    - **Search memo:** an identical query string is never sent twice per build (the
      company-name query can equal another, so dedupe the list).
    - **Extract memo:** `self._extracts: dict[url, Served|None]`, keyed by both the requested
      URL and the served URL. A URL is rendered at most once per build. A rendered evidence
      page records its `Served`.
    - **No useless render (lead ruling 4):** a URL is skipped, and nothing is spent on it, when
      it is already in the memo, appears twice in the results, is not `http(s)`, or has no
      valid host (`pages._host_domain` is None).
    - **Origins, pipelined:** as soon as a rendered page yields ≥ 1 candidate, a task resolves
      its origin with `origins.resolve`. Its `fetch` uses the memo, else
      `self.call(RENDER_UNITS, extract_rendered)`, and returns `Served(first document's url,
      lineage)`. None is returned for no document, a refusal or lost call after retries, an
      unaffordable fetch, or the 8 s guard (D4-3, D4-4, D4-15). Search-page renders do not
      wait for these tasks; the build awaits all of them before deciding.
    - **Candidate origin:** stamp `origin` on that page's candidates.
    - **Budget order:** an original fetch reserves from the same budget as renders. Renders
      of search pages take the allowance computed after the claim pages, minus 3 units per
      pending original hop known at that moment, so originals of claim pages are not starved.
  - **Schedule and time bound (F97, lead ruling 6).** These are the numbers for a build whose
    calls each answer in ≤ 1 s, measured on effective build time (429 waits excluded):

    The table is the **nominal** timeline: no retries, 1 s answers. With retries, one call
    takes up to 1 + 1.05 + 1 + 1.05 + 1 = 5.1 s, and every dependent step shifts later by up
    to 4.1 s. The table is therefore not the bound. The bound is the guard invariant after
    the table.

    | Time (nominal) | Step |
    |---|---|
    | 0-1 s | The 10 lite searches and the research start, all concurrent (with retries, up to 5.1 s). |
    | 1-3 s | Research polls, 1 s apart. Give up after 3 consecutive failed polls (F72). |
    | 3-4 s | All claim pages rendered concurrently. |
    | 4-7 s | Originals of the claim pages, ≤ 3 sequential hops (≤ 3 s), concurrent across pages. Search-page renders start at 4 s, concurrently. |
    | 5-8 s | Originals of the search pages, ≤ 3 hops. |
    | 8.0 s | **Guard:** no new call (render, original, retry, poll) starts after 8.0 s, the inherited `FAST_RETRY_CUTOFF_SECONDS` (`build.py:57`). Research still unfinished is abandoned; a hop not started takes host(URL) (DEV-S4b). |
    | ≤ 9 s | The last call answers. Decide and commit synchronously. |
    | < 10 s | The build has ended. |

    **Guard invariant (the bound):** every attempt starts at ≤ 8.0 s of effective time.
    - Retries check `effective_elapsed + RETRY_SECONDS ≤ 8.0` before waiting
      (`build.py:181-184`, kept).
    - Each research poll, render and original fetch checks `effective_elapsed ≤ 8.0`
      immediately before its reservation, and otherwise returns not-served or no-claims.

    With answers ≤ 1 s, every attempt ends ≤ 9.0 s. After 8.0 s no new attempt starts, and
    every awaiting task (a retry wait, poll loop, hop or render queue) re-checks the guard and
    returns. So nothing is outstanding after 9.0 s. Deciding and committing is synchronous
    (milliseconds), so the build ends < 10 s for any retry pattern.

    The guard applies only while `self.fast` holds (every answer ≤ 1 s). With slower live
    providers, the stage-1 §8 30 s/120 s/300 s rules and `BUILD_DEADLINE_SECONDS = 270`
    (`build.py:58`) apply unchanged.
  - **Research failure (F72):** `research_urls()` counts consecutive failed polls (a refused
    or lost poll, not a 429). After 3 it gives up and returns `[]`. A 429 poll waits off the
    clock as today.
  - **Research affordability:** start research only when `budget.remaining ≥ RESEARCH_UNITS +
    RENDER_UNITS` after the searches have reserved. Otherwise skip it, which matters only
    under a small batch share (see Spend).
  - **Outcome (D4-10, lead ruling 1):** `build_outcome(succeeded, stopped_by_batch_budget)`
    returns `ready` when some call succeeded or the batch budget stopped the build, and
    `failed` otherwise. The Batches text overrides §8 for budget exhaustion only: a batch
    build with zero calls is `ready` with all fields unknown, while a build whose calls all
    failed is `failed`.
  - **Durable spend (U7 hook):** `Build` takes an optional `on_spend(reserved_total)`
    callback, which the budget invokes after every reserve and settle.
  - **Builds.start(dossier, build_time, batch=None):** creates the nested budget with
    `cap=min(80, batch.share)` (see Spend) and `parent=batch.budget`, and inserts the
    `running` row in the caller's open transaction.
- **Rows:** F3, F16, F17, F42, F66-F68, F70-F74, F86, F95, F97.
- **Proof:** fake `WebClient` tests:
  - `test_timing.py::worst_case_fast`: every call answers in 0.95 s, research finishes after
    3 polls, every page has candidates and a 3-hop Canonical chain, and the budget allows
    every render → ends < 10 s, `ready`;
  - `::slow_research_fast_calls`: polls answer fast but the run never finishes → `ready`
    < 10 s;
  - `::mixed_retry_chain`. Setup: every call answers in 0.95 s, and each attempt's start time
    is recorded; every search and the research start are refused 503, 503, then OK; polls
    503, then running, then done; claim pages have candidates and 3-hop Canonical chains
    whose first original is refused once. Assertions:
    - the build ends < 10 s, `ready`;
    - no attempt starts after 8.0 s effective;
    - a guard-cut hop gives host(URL);
    - spend counts only the charged attempts;
  - `test_spend.py`: no repeated query or URL (including a URL that is both a claim page and
    a search result, and one that is both an original and a search result); no extract for an
    invalid-host or `mailto:` URL;
  - call counts, with one extract per URL and none for an original without candidates;
  - exactly 10 distinct searches;
  - all-503 → failed in < 10 s and spent 0;
  - all research fails three ways → ready within 10 s, with search-page fields;
  - search refused and extract answered → still ready if any call succeeded;
  - batch budget 30 with 3 builds → total ≤ 30 and exhausted stops further calls;
  - budget 1 with 2 domains → the second build makes 0 calls and ends `ready`, all fields
    unknown;
  - a batch build whose calls all 503 → `failed`;
  - a lost call is charged.
- **Edges:**
  - a 4th hop;
  - two pages with the same original (one fetch);
  - concurrent builds in one batch reserving at once (single event loop, so no race).

### U6 Batches API
- **Files:**
  - new `stage-4/app/batches.py`;
  - `stage-4/app/store.py` (the `Batch` dataclass, `State.batches`, `new_id` avoiding batch
    ids, load);
  - `stage-4/app/db.py` (the `batches` table and `Writer.put_batch`);
  - `stage-4/app/main.py` (routes `POST /batches`, `GET /batches/{id}`, registered before the
    UI shell routes);
  - `stage-4/tests/test_batches_api.py`.
- **Model:** `Batch(id, user_id, budget_units, domains: list[str], started: list[str],
  spent_units: int, exhausted: bool)`. `spent_units` is the durable count of units settled or
  in flight (U7). The in-memory `BatchBudget` is attached while builds run.
- **POST handler**, following `dossiers.create`:
  1. authenticate;
  2. `require_key`;
  3. `read_json_object`;
  4. fingerprint over the known fields `{domains, budget_units}`, those present;
  5. replay check;
  6. validate (F59-F63, D4-9);
  7. in one synchronous section with `store.transaction()`:
     - create the missing dossiers;
     - `builds.start(..., batch)` for each;
     - `put_batch`;
     - `idempotency.remember(202, body)`.
- **GET handler:** authenticate, look the batch up, return 404 when it is missing or owned by
  another user, else `json_response(200, batch.view(state))`. The view has `state`
  `running`/`done` (F69), live `spent_units`, and each dossier's current state.
- **Rows:** F2, F55-F69, F75.
- **Proof:** the UT cases in the rows. The edges:
  - 50 and 51 domains;
  - all domains existing → 202 with `state: done`, spent 0, no calls;
  - an existing dossier currently building through another request → listed as building,
    and not the batch's build;
  - concurrent `POST /dossiers` for a batch domain → one dossier;
  - replay after the dossiers changed returns the original body;
  - a reset during a batch → the batch is gone, and its builds commit nothing (generation).

### U7 Durable in-flight builds and restart recovery
- **Files:**
  - `stage-4/app/db.py` (the table `running(dossier_id PRIMARY KEY, build_time TEXT,
    batch_id TEXT NULL, spent INTEGER)`, with `Writer.put_running`, `set_running_spent`,
    `delete_running`);
  - `stage-4/app/store.py` (`load_state`);
  - `stage-4/app/main.py` (`Services.__post_init__` runs `recover_running()` before the
    app serves);
  - `stage-4/tests/restart_check.py`;
  - `stage-4/RUN.md`.
- **Write-through:**
  - On every `Budget.reserve`, one small transaction writes the build's reserved total to
    `running.spent` and the batch's total to `batches.spent_units`. It is synchronous, with no
    `await`, and commits **before** the provider call is awaited.
  - On a refused settle (units released), the same transaction writes the lowered totals.
  - On commit (`record_build`), the `running` row is deleted in the build's transaction, and
    the batch's spent stays as the sum.
- **Recovery (D4-12):** for each `running` row at load:
  - `record_build(..., candidates=None, spent=row.spent)` at `row.build_time`, which gives a
    failed build with the fields unchanged and no entries;
  - the dossier's `spent_units` includes the spend;
  - the batch keeps its `spent_units`;
  - the row is deleted;
  - all of this is one transaction, before uvicorn serves `/health` (F77-F80).
- **Graceful stop:** a SIGTERM cancel leaves the row, so the next start records it as failed.
  This replaces the T74 drop (F93).
- **Edges:**
  - a kill between the reserve commit and the call → counted, not billed (allowed);
  - a kill after billing and before settle → counted;
  - a kill during the commit transaction → SQLite atomicity means either the committed build
    (no `running` row) or the row (recovered as failed);
  - two builds of one batch in flight → both recovered, and the batch is `done`.
- **Proof:** RST: the existing restart run, plus a `--during-build` variant using a fake slow
  provider (`NIMBLE_BASE_URL` pointed at a local stub in the test container, no real keys):
  - the first healthy GET shows `failed` and the fields from before;
  - `spent_units` ≥ the units billed;
  - refresh then starts a new build;
  - the batch is `done` with `spent_units` ≤ `budget_units`.

  The write-through cost is one fsync per reservation, about 20 per build. Verify that 50
  concurrent writes stay inside 5 s with the existing `tests/load_check.py`.

### U8 Timeline (`as_of`, `/values`)
- **Files:** `stage-4/app/timeline.py`, `stage-4/tests/test_values.py`.
- **Changes:**
  - `snapshot()` is unchanged; snapshots already carry the new keys (stored at commit/import).
  - `values()` output loops over `ALL_FIELDS` (8). `decide()` includes investors membership
    from the candidates at `true_at` (F50).
  - Per D4-5 (lead ruling 2), each `/values` field is `{value, true_from, citations, origins,
    corroborated}`. `origins` and `corroborated` come from `corroboration.current_keys` over
    the candidates at `true_at`, with the same member rules. There is no
    `corroborated_since`.
- **Rows:** F50, F82, F94.
- **Proof:** UT investors at `true_at` (a member by two origins only at the later date).

### U9 Export/import across stages 1-4
- **Files:**
  - `stage-4/app/transfer.py`;
  - `stage-4/app/restore.py`;
  - `stage-4/app/migrate.py`;
  - `stage-4/tests/test_migrate4.py`;
  - `stage-4/tests/fixtures/stage3-export.json` (new, produced by running the frozen
    `stage-3/` service with the fake web; no real data).
- **Changes:**
  - **Export:** add `batches` (id, user_id, budget_units, domains, started, spent_units,
    exhausted). `running` rows are not exported. The export shows the last completed state
    (stage-1 §10), and a running batch exports with its durable spent.
  - **Import of stage-4 shape:** the restore validation with stage-4 key sets:
    - a candidate `origin` must be a valid domain;
    - fields must equal `decide(...)` plus the stored `corroborated_since`;
    - each build's `corroborated_since` must equal the walk result up to that build;
    - batches are validated (owner exists, ints in range, `started` ⊆ dossier domains).
  - **Import of stage-3 shape:** validate with the stage-3 key sets (current `restore.py`),
    then upgrade:
    - candidates get `origin = host(url)` (F28);
    - every build snapshot and the current fields get `investors` unknown and the
      current_keys;
    - the `corroborated_since` walk runs over the kept builds (F27);
    - `history.investors = []`;
    - the feed is unchanged.
  - **Import of stage-1/2 shape:** the existing `upgrade_dossier` path, then the same
    stage-4 upgrade over its one build (F26).
  - Batches are absent in earlier exports, so the import starts with none.
- **Rows:** F26-F28, F81-F85, F96.
- **Proof:** `test_migrate4.py`:
  - each fixture imports;
  - as_of and /values on the stage-3 fixture equal the stage-3 service's answers plus the new
    keys;
  - investors is unknown everywhere, with history `[]`;
  - the first build after import adds `initial` (no ready build before) or `change`;
  - a stage-4 round trip is byte-equal on every endpoint, including GET /batches;
  - an invalid origin → 422 with nothing changed;
  - tokens and replays (including a POST /batches replay) survive.

### U10 UI
- **Files:**
  - `stage-4/app/ui/screens/dossier.js`, `evidence.js`;
  - `stage-4/app/ui/format.js`;
  - `stage-4/app/ui/styles.css`;
  - `stage-4/tests/e2e/behaviour.py`.
- **Changes:**
  - The dossier screen gets an "Investors" section after Executives, using `data-section`
    markup only: names, status, citations, and the corroboration flag shown as text.
  - The evidence screen gets an investors candidate section.
  - `contested.js` is unchanged (six fields).
  - The stage-2 testids are untouched.
- **Rows:** F54.
- **Proof:**
  - the stage-2 E2E suite runs unchanged;
  - E2E asserts there is no `field-investors` or `candidate-investors-*` testid;
  - the layout at 375 px has no horizontal scroll.

### U11 Docs and carry-forward checks
- **Files:** `stage-4/RUN.md`, `plans/builder-notes-stage-4.md` (the builder's own notes).
- **Changes:** RUN.md documents `POST /batches`, the restart behaviour (in-flight builds end
  `failed`) and that Nimble is the only provider used.
- **Proof:** CMD `git diff 0ffd736 -- stage-1 stage-2 stage-3 acceptance` shows no builder
  change; `git grep -nE "(api_key|API_KEY)\s*=\s*['\"]" stage-4` is empty.
- **Rows:** F87, F88.

## Spend strategy (F86)

Per build, every call and why it can change a field:

| Call | Units | Why |
|---|---|---|
| Lite search: bare domain | 1 | Required by §4, and it finds the company's own pages (own/filing authority, and investors membership by kind) |
| Lite search ×6: domain + each field's phrases | 6 | Surfaces pages whose snippet states that field. A snippet that already supports a value is rendered first |
| Lite search: executive titles | 1 | Executives come only from pages (research never asks for them) |
| Lite search: investors (new) | 1 | Investors come only from pages, and membership needs either an own/filing page or two origins, so it needs a dedicated query |
| Lite search: company name | 1 | Pages that name the company without its domain (news, filings), which supply second origins |
| Research run | 25 | Kept by lead ruling; its cited pages are evidence (stage 2). Skipped only when the build's allowance cannot also afford one render (batch shares) |
| Rendered extract, claim pages | 3 each | Required: claim-cited pages are evidence |
| Rendered extract, originals | 3 each | Only for pages with candidates, needing rule 2, not already rendered, and at most 3 hops. Each changes `origin`, so `origins`/`corroborated`/investors membership |
| Rendered extract, search pages | 3 each | In priority order (snippet states a value, own host, URL) until the cap |

What the build never does:
- the same search or extract twice in one build (memo by query, requested URL and served
  URL);
- a render of a URL that cannot yield a candidate or an original: a duplicate, a non-`http(s)`
  URL, or one with no valid host (lead ruling 4);
- a Tavily, Kernel or Browserbase call;
- a retry of a lost (charged) call;
- an extract of an original for a candidate-less page.

**Batch shares.** A batch build's own cap is `min(80, max(1, budget_units // new_domains))`.
This stops the first builds from starving the later ones of renders. The batch budget is
still enforced as a hard shared reservation (F66), and units a build leaves unspent are not
redistributed. That keeps the strategy simple and can only lower spend.

**No "settled" early stop (lead ruling 4, D4-13).** Every additional page can change a
field's candidates, `origins`, `corroborated`, `status` (contested) or investors membership,
all of which are part of the field. So the only stops are:
- the caps (80 per build, the batch budget);
- the 8 s fast-regime guard (F97);
- an empty queue.

## Rows → work items

Every row maps to a work item:

| Rows | Work item |
|---|---|
| F1 | U0 |
| F2 | U6 |
| F3 | U5, U7 |
| F4-F15 | U1 |
| F16-F17 | U1, U5 |
| F18-F25 | U3, U4 |
| F26-F28 | U9 |
| F29-F34 | U3 |
| F35 | U4 |
| F36-F42 | U2 |
| F43-F49 | U3 |
| F50 | U8 |
| F51-F53 | U4 |
| F54 | U10 |
| F55-F69 | U6, U5 |
| F70-F74 | U5 |
| F75-F80 | U7 |
| F81-F85 | U9 |
| F86 | U5 |
| F87-F88 | U11 |
| F89-F96 | listed items |
| F97 | U5 |

## Cycle-1 audit resolution (plan-checker findings on 0ade905)

| Finding | Resolution |
|---|---|
| F86 settled stop | Lead ruling 4: no early stop; spend minimised by memo, the no-useless-render rule and candidate-only originals (D4-13) |
| D4-10 zero-call batch build | Lead ruling 1: `ready`; the Batches text overrides §8 for budget exhaustion only (`build_outcome`) |
| F79 reservation window | Lead ruling 5: a reserved, unanswered call counts as in flight. No reservation is held across any wait (D4-14) |
| §8 10 s bound | U5 schedule table with numbers and the 8.0 s guard; new row F97 with timing tests |
| D4-5 `/values` keys | Lead ruling 2: add `origins` and `corroborated` from the candidates at `true_at`; no `corroborated_since` |
| Served URL of originals | `fetch` returns `Served(url, lineage)`; the served URL drives F8/F11/F13 for originals (D4-16), with a redirect UT |
| D4-9 | Lead ruling 3: kept |
| Cycle 2: retry arithmetic | The table is relabelled nominal; with retries one call takes up to 5.1 s. The bound now rests on the guard invariant (every attempt starts ≤ 8.0 s, so it ends ≤ 9.0 s). New test `mixed_retry_chain` |

## Unverified

- I did not read any stage-4 supplied check or `acceptance/stage-4/`.
- I did not run the code. The line citations were read at 679a833.
- D4-5, D4-9 and D4-10 now follow lead rulings 2, 3 and 1. A supplied check could still
  expect otherwise.
- The schedule numbers in U5 assume the fake research run finishes within about 3 polls. A
  slower run in the fast regime is cut at 8 s by the guard, and is not otherwise bounded.
- The fsync cost of the durable reservations (U7) under 50 concurrent builds has not been
  measured. `load_check.py` settles it.
- I have not confirmed that a fake Nimble stub can be reached from the restart test
  container. The builder settles it when wiring RST.
