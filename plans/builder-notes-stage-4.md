# Builder notes — stage 4 carry-forward

Base: stage-3 final (accepted 5bacfdb; `stage-3/` byte-identical at 0ffd736). `stage-4/` is a
byte-identical copy of the committed `stage-3/` tree (commit ebc3dcf, copy only). Spec:
`challenges/dossier/spec/stage-4.md` as relayed by the lead.

Checks on the copy:
- `cd stage-4 && /tmp/builder-venv/bin/python -m pytest -q -p no:cacheprovider tests` gave exit 0:
  "344 passed, 1 warning in 38.15s". A second, verbose run also passed: "344 passed in 42.28s".
- `cd stage-4 && docker build -q -t dossier-s4-copy:builder .` gave exit 0.

## 1. What stage 3 records per page and candidate

- **Page.** `Build.pages` holds only `{url: true_from}` for every page read, as reported by
  `Page.url` (the document URL the provider returned, else the requested URL). Page text is
  never kept. A build record stores `pages` [{url, true_from}] and the seven decided fields.
- **Headers.** `app.support.header()` returns the first occurrence of each header line.
  `app.pages` reads only `Kind`, `Published` and `Effective`. `Registrant`, `Canonical` and
  `First-Published-By` are not read.
- **Kind.** `page_kind()` trusts a `Kind:` header that names a listed kind, including `own` from
  any host. Without one, the kind is `own` when the URL host is the company domain, else
  `aggregator`. There is no registrant, so no lookalike detection.
- **Candidate keys.** value, url, excerpt, provider (always `nimble`), kind, published_at,
  retrieved_at, true_from, learned_at, selected, and `title` for executives. There is no
  `origin`.
- **Field keys.** value, status, true_from, learned_at, citations, candidates. There is no
  `origins`, `corroborated` or `corroborated_since`.
- **Fields.** Seven: the six of §4 plus `executives`. There is no `investors`, and its
  membership-based selection does not exist.

## 2. How provider calls are made

- **Route.** Only `app/web.py` talks to providers: `web_router.AsyncWebRouter("nimble")` with
  `max_retries 0` and a 45 s timeout. The calls are:
  - lite search, 1 unit;
  - rendered extract (`render: True`), 3 units per URL;
  - `submit_research`, 25 units;
  - `job.astatus()` polls, free.

  Tavily, Kernel and Browserbase are never called. Their costs are listed in
  `app/budget.py`.
- **Failures.** `classify_failure`:
  - a status of 400 or more is a refusal: free, and not charged;
  - for extract, only 429 and 5xx count as refusals; other 4xx answers are charged (§9);
  - any other failure (timeout, connection) is charged.
- **Retries.** In `Build.call`:
  - a 429 gets 3 retries 1.05 s apart, and those waits are off the build clock;
  - other refusals get 2 retries 1.05 s apart;
  - in the fast regime, no retry starts after 8 s.

  There is no fallback to another provider, since Nimble suffices alone.
- **Budget.** Each build has its own `Budget`: a reservation before each call, settled after,
  against a cap of 80. Searches and research start at once. Claim pages are rendered first,
  then search pages in priority order until the cap. The batch-level budget does not exist.

## 3. Build lifecycle and restart recovery

- **Lifecycle.** `Builds.start()` runs inside the request's synchronous section. It sets
  `dossier.build`, which exists in memory only, and creates an asyncio task. When the build
  ends, `_commit` writes everything in one SQLite transaction: the build record, fields,
  history, feed and the dossier's `spent_units`. Nothing about a running build is persisted.
- **Restart.** The building state and the units spent so far are lost. After a restart the
  dossier shows its last completed outcome, or `failed` if it never completed one. A build
  cancelled at shutdown records nothing (stage-3 lead ruling T74).

## 4. Gaps against the stage-4 sections

### Provider failure

- **P1. Research polls that keep failing hold the build until its 270 s deadline.**
  `research_urls()` keeps polling while a poll returns an error (5xx), sleeping 1 s between
  polls, until `BUILD_DEADLINE_SECONDS`. `gather()` waits for the research before it renders
  anything. So "every research run fails, while searches and extracts are answered" does end
  `ready`, but far outside §8's 10 s.
  - A start refusal is fine: it ends after the retries.
  - Proposed: count failed polls against the same retry policy (or a short poll budget), then
    give up on research for the build and continue with search pages.
- **P2. "Every call to one or more providers fails, while nimble answers."** Nimble is the only
  provider called, so this holds trivially. If Nimble itself refuses everything, the build
  ends `failed` after its retries, about 2–3 s, within §8. No gap, but it should be proven
  with a test per case:
  - every research refused;
  - every search refused while extract answers;
  - all calls refused.
- **P3. A refused call costs nothing (§9).** This holds for 429 and 5xx on every method. A 4xx
  refusal of search or research is also free, which stage 1 allowed. No gap.

### Restarts (in-flight builds)

- **R1. A build running at the stop must end `ready` or `failed` within 10 s of the first
  healthy `/health` after the restart.** Stage 3 drops it: the dossier shows the last outcome,
  and nothing records that a build was running. This needs a persisted in-flight build row
  holding the dossier, build time, units reserved or charged so far, and batch id. At startup,
  each such row must be resumed or ended, `failed` with fields unchanged being the minimal
  answer.
- **R2. One build across the restart: at most 80 units in total, and within a batch's
  `budget_units`.** The units spent before the stop must be durable before the call is made.
  Writing the reservation (units reserved at call start) is allowed, since the spec lets
  in-flight unbilled calls count. Any continuation after the restart gets only the remaining
  allowance.
- **R3. Every billed unit, before and after the stop, counts in the dossier's and the batch's
  `spent_units`.** Today a dropped build's spending is lost from `spent_units`. Spending must
  be written as calls are reserved or settled, not only at commit.
- **R4. After the restart, refresh starts a new build** as for any dossier. This works once
  the in-flight row has ended.
- **R5. Batches must persist with their state, spending and builds.** There is no batch model
  today.

### Upgrades

- **U1. Stage-3 export shape.** `app/restore.py` requires exact key sets:
  - fields have 6 keys;
  - candidates have no `origin`;
  - `ALL_FIELDS` has 7 entries.

  A stage-4 import must accept stage-3 dossiers. Each needs:
  - `investors` added as unknown in the current fields and in every kept build's snapshot;
  - each candidate's origin set to the normalised host of its URL (spec: "export records no
    origin");
  - `origins`, `corroborated` and `corroborated_since` computed for every field. Imported
    candidates count as gathered at each stage-3 build's time.
- **U2. `?as_of=` and `/values` "answer from [stage-3 builds] ... with the keys this stage
  adds".** Build snapshots are stored stage-3-shaped. Either upgrade them at import (add the
  new keys and `investors`) or compute the keys on read. Upgrading at import keeps a single
  stored shape.
- **U3. Stage-1/2 imports.** `upgrade_dossier` needs `investors` unknown, origin = URL host,
  and the corroboration keys. Imported candidates count as gathered at `researched_at`.
- **U4. "Citations carried in the imported state remain citations served to this service."**
  Imported excerpts are kept verbatim, as today. No gap beyond not rewriting them.
- **U5. Stage-4 export.** It must add batches, the in-flight build rows (or their outcome), and
  the new field and candidate keys.
- **U6. Carried limitation T38.** A stage-3 import does not cross-check a candidate's
  `true_from` against its page version. A cheap fix exists: compare each candidate's
  `true_from` with its build's `pages` entry, and derive history and feed from the builds.
  It was made and reverted in stage 3 (6d82a06, reverted by 0ffd736), so it could be applied
  to `stage-4/` if the plan wants it.

## 5. Other stage-4 items with no stage-3 base (for the plan)

- **Lineage headers and origins.** Rule 2 needs extra extracts of `Canonical` originals, up to
  3 hops. Each costs 3 units under the 80-unit cap and the batch budget. Spend these only
  where they can change a field: a page with a candidate.
- **Investors.** A new Appendix A field, with membership instead of selection, typing by name,
  and a new lite query if needed (spend rule).
- **`POST /batches`.**
  - A third idempotent write path. The generic `(user, method, raw path, key)` record works.
  - `budget_units` validation must return 422 for any non-integer JSON type, which takes
    precedence over 400.
  - Domains: up to 50, distinct after normalisation.
  - Budget: a shared budget reserved before every call of every build in the batch, beside
    each build's 80-unit cap.
- **Owner scoping.** Another user's batch gives 404.
