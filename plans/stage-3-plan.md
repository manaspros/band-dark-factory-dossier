# Stage 3 (dossier) - implementation plan

Companion to `plans/stage-3-matrix.md` (T1-T77, documented deviations DEV-S3a/DEV-S3b, decisions E3-1..E3-6). All
earlier rows and lead rulings stay in force:
- retry caps, with 1.05 s backoff for 429;
- the exact-domain search gets 3 attempts;
- hq_city follows A.4;
- research runs on every build;
- Nimble rendered extract runs in priority order until the 80-unit cap (DEV-S2);
- the HTML routes serve a public shell with no data, and the JSON API needs a bearer token;
- import validation is type-safe and checks each excerpt supports its value;
- import never returns a 5xx.

No check is claimed to pass.

## Carry-forward

- **W0:** copy `stage-2/` to `stage-3/` (no `.git`, no caches) and extend it. `stage-1/` and
  `stage-2/` are frozen.
- Existing code this plan builds on, all in `stage-2/app/`:
  - `store.py:20-97`: the in-memory `State` and `Dossier`.
  - `store.py:99-111`: the export.
  - `build.py:175-176`: 8 queries.
  - `build.py:256-290`: `_run`/`_commit`, generation-checked.
  - `selection.py:21-45, 66-107`: the `Candidate` model and `rank`/`decide`.
  - `candidates.py`: per-page candidates.
  - `pages.py`: `Kind` and `Published`.
  - `migrate.py`: the stage-1 import.
  - `main.py:79-96`: routes. `/dossiers/{domain:path}` is last, so the new
    `/dossiers/{domain:path}/values` and `/history` routes must be registered before it, next
    to `/refresh`.
- Behaviour to keep: every stage-1/2 row, the stage-2 screens and their testids, the generation
  check on reset/import, and the stage-1/2 unit and E2E tests (updated only where a row changed).

## Architecture

```
handlers (unchanged shape) --> Store (in-memory, read path)
                         \--> db.py (SQLite, WAL, synchronous=FULL; write path)
build.py --commit--> one transaction: build row + versions + dossier fields + history + feed + seq
startup: db.load() -> Store; health is 200 only after the load
```

- **Durable store (lead note, T67-T74):** SQLite through the stdlib `sqlite3`, so no new
  dependency. The file is `/srv/data/dossier.db`. The Dockerfile creates `/srv/data` and
  chowns it to the runtime user `dossier`, because `/srv` is root-owned (lead ruling; builder
  notes R4).
  - Settings: `PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA foreign_keys=ON`.
  - Tables: `meta(key, value)` (clock, clock_set, seq), `users`, `tokens`, `dossiers`,
    `builds(dossier_id, build_no, time, outcome, spent, fields_json, candidates_json)`,
    `versions(dossier_id, build_no, url, true_from, candidates_json)`,
    `history(dossier_id, field, n, entry_json)`,
    `feed(seq PRIMARY KEY, dossier_id, entry_json)`,
    `idempotency(user_id, method, path, key, fingerprint, status, body_json)`.
- **Write rule (E3-5):** each mutating handler validates, then runs
  `with db.tx(): write rows`. The commit (fsync under `synchronous=FULL`) happens before the
  in-memory update and before the response. There is no `await` inside, so on one event loop
  this keeps §11 serialisability. A failed commit raises before memory changes, and the
  catch-all returns the error envelope.
- **Reads** come from memory, which mirrors the DB.
- **Reset and import** run one transaction that deletes every row and inserts the new state,
  then swap memory and bump the generation.

## Work items

File areas are disjoint per item. Build order is W0 -> W11. Each item lists its rows (matrix),
its proof, and the edges it must hold.

### W1 Appendix A titles and page times
- **Changes:**
  - `support.py`: add `TITLE_PHRASES` for cfo, coo and cto. Generalise the ceo name scanner
    so `_ceo_names` takes a phrase list. `candidates()` yields title candidates as field
    `executives` with a `title`.
  - `pages.py`: `page_true_from(text, published_at)` reads the `Effective` header and falls
    back to the UTC date of `published_at`.
- **Rows:** T3, T4, T14.
- **Proof:** UT `test_support_titles.py`. The table in T14 is used verbatim. A sentence that
  names two titles (`Ana Silva is CFO and Ben Okafor is CTO of Acme Robotics.`) supports no
  title, because each title's scan sees two names (A.2.5). UT `test_pages.py` covers
  `Effective` validity and the UTC date conversion.
- **Files:** `stage-3/app/{support,pages}.py`, `stage-3/tests/test_{support_titles,pages}.py`.

### W2 Candidate model, executives field, selection
- **Changes:**
  - `selection.py`: `Candidate` gains `title` (None for the six fields), `true_from` and
    `learned_at`.
  - New `executives.py`: `decide_executives(cands)` ranks each title separately and builds
    the members array, citations, status and `true_from` (latest of the members, null if any
    is null).
  - `decide()` returns seven fields, each with `true_from` and `learned_at`.
- **Rows:** T7, T10, T11, T13, T15-T19, T21.
- **Proof:** UT `test_executives.py`:
  - only cfo;
  - cfo and cto;
  - a contested coo;
  - none (unknown);
  - member order;
  - citation order;
  - `true_from` latest or null.
- **Files:** `stage-3/app/{selection,executives,candidates}.py`, tests.

### W3 Times, history typing, feed entries
- **Changes:** `history.py` provides:
  - `stamp_learned_at(dossier_builds, new_cands, build_time)`;
  - `selected_learned_at(prev_field, new_field, build_time)`;
  - `entries_for_build(prev_fields, new_fields, is_first_ready, build_time) ->
    (history_entries, feed_entries)`, with typing per T26-T30. Executives gets one entry for
    the whole field, typed by the per-title rule (T23, E3-7); `from`/`to`/`value` are member
    arrays, and it is placed after the six fields.
- **Rows:** T5, T6, T20, T23, T25-T30, T47, T49, T51, T65.
- **Proof:** UT `test_history.py`:
  - initial;
  - unknown, then a value (change);
  - a value disappearing (change);
  - an earlier `true_from` (correction);
  - an equal `true_from` (correction);
  - a later `true_from` (change);
  - a null `true_from` (change);
  - the same value with different citations (nothing);
  - failed (nothing);
  - the executives typing matrix;
  - cfo and cto changing in one build give exactly one `executives` history entry and one
    feed entry, last in seq order for that build (E3-7).

  UT `test_times.py`: candidate `learned_at` across builds.
- **Files:** `stage-3/app/history.py`, tests.

### W4 API: field shape, history, changes
- **Changes:**
  - `dossiers.py`: GET adds `true_from`, `learned_at` and executives. New handlers `history`
    and `changes` (since/limit parsing as stage-1 R87/R90).
  - `main.py`: register `/dossiers/{domain:path}/history` and `/values` before the catch-all
    `/dossiers/{domain:path}`. Register `GET /changes`.
- **Rows:** T8, T11, T36, T46, T48, T52-T54.
- **Proof:** UT `test_api_shape.py`, `test_changes_api.py`:
  - `since=0`, `since=-1` (422), `since=1e3` (422);
  - `limit` 1, 200 and 201;
  - `has_more`;
  - 401 without a token;
  - 404 for an unknown dossier on history.
- **Files:** `stage-3/app/{dossiers,main}.py`.

### W5 Build commit: builds, versions, entries, seq (one transaction)
- **Changes:** `build.py` `_commit`, in one `db.tx()`:
  - insert the `builds` row (`build_no` = previous + 1, time, outcome, spend);
  - on `ready`: insert one `versions` row per rendered URL (with `true_from` from the page,
    candidates possibly empty), stamp candidate `learned_at` (W3), decide the fields, compute
    entries, append history, append feed entries numbered from `meta.seq` in field order and
    then executives, and update `meta.seq` and the dossier row.

  The reader keeps every rendered URL's `true_from` even when the page yields no candidates.
  The generation check runs before the transaction.
- **Rows:** T2, T31, T38, T50, T66.
- **Proof:**
  - UT: 10 concurrent refreshes give one build and entries once.
  - UT: the commit is atomic. A fault injected after the history insert rolls everything
    back: no build row and no seq bump.
  - UT: seq is strictly increasing across dossiers.
- **Files:** `stage-3/app/build.py` (commit part), `stage-3/app/db.py`.

### W6 `?as_of=`
- **Changes:** `as_of.py: snapshot(dossier, as_of)`.
  - It picks the latest ready build with time ≤ `as_of` by instant, breaking ties by
    `build_no`.
  - It returns `{dossier_id, domain, state: "ready", researched_at: build time, spent_units:
    sum of spend over builds with time ≤ as_of, fields: build snapshot}`. The snapshot keeps
    each field's `learned_at` and `true_from` as of that build.
  - It applies the validation order of E3-2.
- **Rows:** T9, T32-T35.
- **Proof:** UT `test_as_of.py`:
  - before the first build gives 404;
  - between builds;
  - equal times written with different offsets pick the later `build_no`;
  - a failed build's spend is counted but the build is never returned;
  - `as_of=2026-03-01T09:00:00` (no offset) gives 422.
- **Files:** `stage-3/app/as_of.py`.

### W7 `/values?true_at=`
- **Changes:** `values.py`:
  - `versions_holding(versions, true_at)` implements T39-T42 per URL in build order: a
    replacement removes earlier versions whose `true_from` is ≥ its own; the latest survivor's
    end is set to its `true_from`; a null `true_from` replaces all earlier versions and never
    holds.
  - The candidates at `true_at` then go through stage-2 selection per field (W2 for
    executives).
- **Rows:** T22, T37-T44.
- **Proof:** UT `test_values.py` with hand-built version lists:
  - the spec examples;
  - a correction moving `true_from` earlier;
  - a version without candidates ending an earlier one;
  - null `true_from`;
  - `true_at` before any `true_from` gives null fields;
  - `as_of` before the first ready build gives 404;
  - `true_at=2025-6-1` gives 422.
- **Files:** `stage-3/app/values.py`.

### W8 Build queries and budget
- **Changes:** `field_queries` gains the executives query (T75). That makes 9 searches. The
  research schema is unchanged. The render allowance is recomputed from the actual search
  count.
- **Rows:** T12, T75.
- **Proof:** UT that the research payload has exactly six properties; UT that the budget is
  ≤ 80 with 9 searches, 6 claim pages and 30 URLs.
- **Files:** `stage-3/app/build.py` (queries only), `stage-3/app/budget.py`.

### W9 UI
- **Changes:** the dossier screen shows an "Executives" section (title label, name, status,
  citations), using `data-section` attributes and no stage-2 testids. The evidence screen
  lists executives candidates in their own section. Contested stays limited to the six fields.
  History and as_of screens are not required and are not built.
- **Rows:** T24, T77.
- **Proof:** the stage-2 E2E suite re-runs unchanged. E2E checks that `field-executives` and
  `candidate-executives-*` testids are absent and that contested ignores executives.
- **Files:** `stage-3/app/ui/{dossier,evidence}.js`, `styles.css`.

### W10 Export/import across stages
- **Changes:**
  - `migrate.py` detects the shape (T55) and builds stage-3 state.
    - Stage-1: one ready build at `researched_at` (none if null). Versions come from citation
      URLs with `true_from` null. Initial history uses `true_from` null.
    - Stage-2 (lead rulings U1, U2, U4):
      - one ready build at `researched_at` holding every exported candidate and the whole
        spend (DEV-S3a); a null `researched_at` means no build, so every `as_of` is 404;
      - versions are one per candidate URL, with `true_from` = the UTC date of `published_at`,
        else null (DEV-S3b);
      - candidate `learned_at` = `retrieved_at` (U4);
      - initial history takes `true_from` from the selected candidate's date;
      - the exported `state` stays the current outcome.
    - Both: executives is unknown, the feed is empty, and seq is 0.
    - Stage-3: everything as exported, including `meta.seq`.
  - Export writes the full stage-3 state (`format_version` 1). An export during a build shows
    the last completed state (stage-1 R178).
  - Validation stays type-safe and support-checked (lead carry-over), with no 5xx.
- **Rows:** T45, T55-T65.
- **Proof:** UT `test_migrate3.py` with committed fixtures exported from the frozen `stage-1/`
  and `stage-2/` services. It checks:
  - initial entries;
  - as_of at and before `researched_at`;
  - `/values` (nulls for stage-1);
  - the first build after import gives `change` entries, executives `change` vs `initial`;
  - tokens and idempotent replays survive;
  - a stage-3 round trip leaves every endpoint byte-equal;
  - invalid state gives 422 with nothing changed.
- **Files:** `stage-3/app/{migrate,store}.py`, `stage-3/tests/fixtures/`.

### W11 Durability and restart
- **Changes:**
  - `db.py`: schema, migrations at startup, `tx()`, `load()`.
  - Every mutating path writes through the DB: signup/login (user and token), reset, clock,
    import, POST /dossiers (dossier and idempotency record), refresh (idempotency), and the
    build commit (W5).
  - The clock is persisted on change.
  - Startup marks no build as running (E3-6).
  - The Dockerfile creates `/srv/data`, owned by `dossier`. RUN.md documents that state lives
    in the container filesystem at that path.
- **Rows:** T66-T74.
- **Proof:** `stage-3/tests/restart_check.py` (RST), run against the built image:
  - reset, sign up, build two dossiers, refresh one so it has feed entries, set the clock,
    and record every endpoint's response;
  - `docker kill` (SIGKILL), then `docker start`, wait for `/health`;
  - all responses must be identical, including logins, old tokens, as_of, values, history,
    feed seq, and an idempotent replay;
  - a new feed entry has a larger seq;
  - the clock is unchanged.

  A second run kills the container during 50 concurrent writes, then checks that every
  acknowledged write is present and nothing is half-applied. The stage-1 load check is
  re-run for Open-T1.
- **Files:** `stage-3/app/db.py`, write calls in `stage-3/app/{auth,control,dossiers,
  idempotency,clock}.py`, `stage-3/Dockerfile`, `stage-3/RUN.md`,
  `stage-3/tests/restart_check.py`.

## Research spending and executives (brief question)

A research run still asks only the six fields (T12). Executives therefore come only from
rendered pages. The budget gains one lite query for executive pages, so 9 search units, plus
25 for research and an 18-unit reserve for claim pages. That leaves about 9 search-page renders,
and up to 15 renders in total if research cites fewer pages. Pages beyond the budget remain the
documented budget limit DEV-S2.

## Lead rulings (settled)

1. **U1 / DEV-S3a:** a stage-2 import is one ready build at `researched_at`, holding all
   candidates and the whole spend. A null `researched_at` gives 404 for every `as_of`. The
   consequences of the lost history are in matrix DEV-S3a.
2. **U2 / DEV-S3b:** imported `true_from` is the UTC date of `published_at`, else null.
3. **U4:** imported `learned_at` = `retrieved_at`.
4. **Executives query:** one extra lite search per build (1 unit, not the bare domain).
   Research still asks only the six fields (T12, T75).
5. **Restarts:** stdlib SQLite in WAL mode with `synchronous=FULL`, one transaction per change
   committed before the response (including the build commit), data in `/srv/data` owned by
   the runtime user, everything persisted, a running build dropped on restart, and no new
   dependency (W11).

## Unverified

Open-T1 (commit latency under load) and Open-T2 (how the harness kills the container). I read
the frozen `stage-2/app` code for the carry-forward facts. I did not read the stage-3 supplied
checks or acceptance/.
