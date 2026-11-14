# Stage 3 (dossier) - requirement matrix

Source: the stage-3 requirements as relayed verbatim by lead (2026-11-14, two parts). Stage-1
rows (R1-R219) and stage-2 rows (S1-S120) still apply, with every lead ruling recorded in
those plans. Changed earlier rows are listed at the end. Stage-3 row ids are `T1...` and are
never renumbered.

**Verified by** names the planned proof. No stage-3 supplied check was read for this matrix.
Codes:
- `UT`: a unit test in `stage-3/tests/`.
- `RST`: a restart test, a script that runs the container, kills it with `docker kill`, starts
  it again and compares responses (plan W11).
- `RD`: code reading.

**Where** names the work item `W*` and module under `stage-3/app/`.

## Global

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T1 | "The requirements from stages 1 and 2 continue to apply, with the additions below." | Carry-forward: `stage-3/` starts as a copy of `stage-2/` at f50cd1c. | harness stage-1/2 suites under `--stage 3` | W0 |
| T2 | "4. Every change to a selected value appears exactly once in the change feed, at the time this stage assigns to it." | Feed entries are written in the same DB transaction as the build commit that causes them (W5, W10). | UT `test_feed.py::once_per_change` (two concurrent refreshes, then a crash between builds) | W5, W10 |

## Two times per value

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T3 | "**`true_from`**: the date from which the evidence says the value holds. A page states it in the header line `Effective: <YYYY-MM-DD>`." | `page_true_from(text)`: header `Effective`, stripped, must match `^\d{4}-\d{2}-\d{2}$` and be a real calendar date. | UT `test_pages.py::effective` (valid, `2025-02-30`, `2025-2-1`, with a time) | W1 `pages.py` |
| T4 | "A page with no valid `Effective` line takes the date part, in UTC, of its `published_at`; with neither, `true_from` is null." | `published_at` is converted to UTC, then its date taken (`2025-01-01T01:00:00+02:00` gives `2024-12-31`). | UT | W1 |
| T5 | "**`learned_at`** ... For a candidate, it is the time (§8, Builds) of the first build that gathered a candidate with the same field, value, URL and provider." | Lookup key (field[/title], normalised value, url, provider) over all kept ready builds of the dossier, in build order. A failed build gathers nothing (E3-1). | UT `test_times.py::candidate_learned_at` (gathered in build 1, missing in build 2, back in build 3, keeps build 1's time) | W3 `history.py` |
| T6 | "For a selected value, it is the time of the build that made it the selected value." | If a build's selected value equals the previous selected value, its `learned_at` is carried over; otherwise it is this build's time. | UT | W3 |
| T7 | "Candidates gain `true_from` and `learned_at`. `retrieved_at` (stage 2) stays the time of the build that gathered the candidate in the current candidate set. A selected value's `true_from` is that of its selected candidate." | | UT | W2, W3 |
| T8 | "Each field of `GET /dossiers/{domain}` also carries the selected value's `true_from` and `learned_at`. Both are null when the field is `unknown`." | Seven fields, each with `true_from` and `learned_at`. | UT `test_api_shape.py` | W4 |
| T9 | "In an `as_of` response these describe the selected value at that snapshot, using no later history." | Each build's field snapshot stores `true_from` and `learned_at` as decided at that build. | UT | W6 |
| T10 | "The selection rule in `stage-2.md` is unchanged." | `selection.rank` is reused. | RD | W2 |

## Executives

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T11 | "A dossier has a seventh field, `executives`. The `fields` of every response that lists a dossier's fields hold it, after the six fields of §4." | `FIELDS7 = FIELDS + ("executives",)`, used by GET, as_of, values, history and export. `GET /dossiers` list entries are unchanged. | UT | W2, W4 |
| T12 | "A research run (§4) still asks for the six fields of §4 only." | The research schema is unchanged (`stage-2/app/build.py` research query). | UT payload | W8 |
| T13 | "Its value is an array with one object `{ "title": T, "name": N }` for each title below that has a selected person, in the order `cfo`, `coo`, `cto`. ... When no title has a selected person, the value is null and the field is `unknown`." | | UT `test_executives.py` | W2 `executives.py` |
| T14 | Title phrases: "`cfo` `chief financial officer`, `CFO`; `coo` `chief operating officer`, `COO`; `cto` `chief technology officer`, `CTO`", "with the format and normalisation of `ceo` (A.4, A.5), the title's own statement phrases taking the place of those for `ceo`" | `support.py` gains three title pseudo-fields. The ceo name scanner is parameterised by the phrase list, and the negating phrases are unchanged. | UT (`Ana Silva is the chief financial officer of Acme Robotics.` gives cfo `Ana Silva`; `Acme Robotics CTO: Ben Okafor.` gives cto; a CEO sentence gives no title; `former CFO` gives nothing) | W1 `support.py` |
| T15 | "A candidate of `executives` is a candidate of one title: it carries `title` beside `value`, and its `value` is the person's name. A research claim is never a candidate of `executives`." | | UT | W2 |
| T16 | "The selection rule in `stage-2.md` runs separately over the candidates of each title." / "`selected` is true on the highest-ranked candidate of each title" | | UT | W2 |
| T17 | "`candidates` lists every candidate by title, in the order above, then in rank order." | | UT | W2 |
| T18 | "`citations` are, for each member in order, the `url`, `excerpt` and `provider` of every candidate with the member's title and name, in rank order." | | UT | W2 |
| T19 | "`status` is `unknown` when the value is null, `contested` when the candidates of some title carry two or more different names, and `known` otherwise." | | UT | W2 |
| T20 | "A candidate's `learned_at` is the time of the first build that gathered a candidate with the same title, name, URL and provider." | Same as T5, with the title in the key. | UT | W3 |
| T21 | "A member's `true_from` is that of its title's selected candidate. The field's `true_from` is the latest of its members' `true_from`, or null when any member's is null." | | UT | W2 |
| T22 | "`GET /dossiers/{domain}/values` chooses each title's person from the candidates at `true_at` and gives the value, `true_from` and citations from them by these rules." | | UT | W7 |
| T23 | "A title **differs** between the earlier and the new value when exactly one of them has a member with that title, or both have one and their names differ. A differing title counts as a correction when both values have a member with that title, both members' `true_from` are not null, and the new member's is on or before the earlier member's. The entry is `correction` when every differing title counts as a correction, and `change` otherwise." | | **Shape (E3-7):** a build that changes `executives` adds **one** history entry and **one** feed entry for the field `executives`. Its `value`, `from` and `to` are the whole member arrays, and its type comes from this per-title rule. There is no per-title entry and no `title` key: the source says "The entry is `correction` when every differing title ..." (one entry), and the per-title detail is visible inside the arrays. | UT `test_history.py::executives_typing` (all six combinations); UT `::executives_one_entry` (cfo and cto change in one build give one history entry and one feed entry, `field: "executives"`, arrays in `from`/`to`) | W3 |
| T24 | "The `data-testid` attributes of the screens in `stage-2.md` name only the six fields of §4: `executives` takes none of them, and a screen that shows it does so with other markup. On `/contested`, "no field is contested" means none of those six fields is." | The UI loops over the six fields for testids. Executives is shown in its own section (`data-section="executives"`, no testid). Contested lists only the six. | E2E (stage-2 screen tests still pass; contested excludes executives) | W9 `ui/` |

## Changes and corrections

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T25 | "When a build completes `ready`, each field whose selected value differs from its selected value before the build gets one history entry, and one feed entry" | "Differs" uses stage-2 sameness (JSON equality, strings stripped). For executives, the arrays are compared member by member. | UT | W3 |
| T26 | "`correction` - Both the earlier and the new value are not null, and the new value's `true_from` is on or before the earlier value's `true_from`" | Compared as dates. Both `true_from` values must be non-null for a correction. | UT | W3 |
| T27 | "`change` - Every other difference, including a value appearing where there was none, a value disappearing, and either `true_from` being null" | | UT | W3 |
| T28 | "A field's first selected value, set by the dossier's first build that completes `ready`, gets a history entry of type `initial` and no feed entry." | | UT | W3 |
| T29 | "A field that is `unknown` after that build gets its first entry when it first gets a value, and that entry is a `change`." | | UT | W3 |
| T30 | "A build that completes with the same selected value for a field adds nothing for it, even when its candidates, citations or `true_from` differ. A `failed` build adds nothing." | | UT | W3 |
| T31 | "Concurrent refreshes of one dossier run one build (§8) and so add each entry once." | Stage-1 one-build rule (R123/R144) is kept. | UT gather of 10 refreshes | W5 |

## `?as_of=`

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T32 | "Returns the dossier as this service had it at `as_of`: the fields, candidates and `researched_at` of the latest build that completed `ready` and whose time is at or before `as_of`, decided by `learned_at`, never by `true_from`." | Builds are compared by instant. The response is the stored snapshot of that build. | UT `test_as_of.py` | W6 |
| T33 | "`state` is `ready`. `spent_units` is the total of the builds whose time is at or before `as_of`." | The sum covers every kept build, ready and failed, with time ≤ `as_of`. | UT | W6 |
| T34 | "When several ready builds have the same time, return the last of them in build order. This also applies when equivalent RFC 3339 timestamps use different offsets. The clock need not advance between builds." | Each build has a monotonically increasing `build_no`. Ties are broken by the highest `build_no`. | UT (two builds at the same instant written with different offsets) | W6 |
| T35 | "`as_of` is not an RFC 3339 timestamp with an explicit offset -> 422"; "No build ... completed `ready` with a time at or before `as_of` -> 404"; "No dossier -> 404" | Validation order: the path domain gives 422, then `as_of` format gives 422, then a missing dossier gives 404, then no build gives 404 (E3-2). | UT | W6 |
| T36 | "Without `as_of`, `GET /dossiers/{domain}` is unchanged." | Apart from the T8 and T11 additions. | UT | W4 |

## `/values?true_at=`

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T37 | "Returns, for each field, the value that the evidence this service had at `as_of` says held on the date `true_at`. `as_of` defaults to the current time (§8)." | Seven fields. The default is the clock's now. | UT | W7 `values.py` |
| T38 | "A **page version** is what one ready build gathered from one URL: its candidates and its `true_from`." | Every ready build stores, for each URL it rendered, `(url, true_from, candidates)`, including URLs with no candidates. | UT | W5, W7 |
| T39 | "The versions of a URL known at `as_of` are those gathered by ready builds whose time is at or before `as_of`, taken in build order. Each version holds from its `true_from`." | | UT | W7 |
| T40 | "When a later version of the same URL is gathered, it replaces every earlier version of that URL whose `true_from` is on or after its own. The latest earlier version that it does not replace stops holding on the later version's `true_from`." | The end of the surviving latest version is set to the later version's `true_from`. | UT `test_values.py` (spec walk-through and E3-3 cases) | W7 |
| T41 | "A version whose `true_from` is null holds from no date, and a later version with a null `true_from` replaces every earlier version of its URL. A gathered version with no candidates still replaces or ends earlier versions by this rule." | A null-`true_from` version never holds. | UT | W7 |
| T42 | "The candidates **at `true_at`** are those of every version that holds on that date. Each field's value is chosen from them by the selection rule ..., and its `true_from` is that of the chosen candidate." | A version holds on day d when `true_from <= d` and either it has no end or `d < end`. | UT | W7 |
| T43 | Response shape `{domain, true_at, as_of, fields: {f: {value, true_from, citations}}}`; "A field with no candidate at `true_at` has `"value": null`, `"true_from": null`, `"citations": []`. Citations are those of the candidates at `true_at` with the chosen value." | `as_of` is echoed as given, or as the clock's now when defaulted. | UT | W7 |
| T44 | "`true_at` missing or not a `YYYY-MM-DD` date, or `as_of` not an RFC 3339 timestamp with an explicit offset -> 422"; "No dossier ..., or no build of it completed `ready` with a time at or before `as_of` -> 404" | | UT | W7 |
| T45 | "For state imported from an export, the builds and versions are those Upgrades gives." | | UT | W10 |

## `/history` and `/changes`

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T46 | History shape: `{domain, fields: {<seven>: [entry...]}}`; "Each list is in the order the entries were added, oldest first." | | UT | W4 |
| T47 | "An entry's `value`, `true_from`, `learned_at` and `citations` are those of the selected value it records. An entry whose value is null has `"true_from": null` and `"citations": []`." | Entries hold `type, value, true_from, learned_at, citations`. For `executives`, `value` is the member array, `true_from` is the field's (latest member's, or null), and `citations` are the field's citations (T18, T21). | UT | W3 |
| T48 | "No dossier for the domain is 404 `not_found`." (history) | An invalid path domain gives 422 first, as before. | UT | W4 |
| T49 | "The feed holds every `change` and `correction` entry of every dossier." | | UT | W3 |
| T50 | "`seq` is a positive integer, unique across the feed, and larger for every later entry. Entries added by one build are numbered in the order of the fields in `stage-1.md` §4, then `executives`." | A persisted counter in the `meta` table, incremented inside the commit transaction. Within one build: `legal_name`, `hq_city`, `ceo`, `founded_year`, `headcount_range`, `funding_total`, then the single `executives` entry (E3-7), so there is no title ordering to define. | UT; RST (seq after restart > max before) | W5, W10 |
| T51 | "`from` and `to` are the earlier and the new selected value, either of which may be null. `true_from` is the new value's. `learned_at` is the time of the build that added the entry." | Entry shape `{seq, domain, field, type, from, to, true_from, learned_at}`, the same for `executives` (arrays or null in `from`/`to`). |  UT | W3 |
| T52 | "`since` defaults to 0 ... It is an integer, 0 or more. Entries are ordered by `seq` ascending." | Digits only (stage-1 R87 style). | UT | W4 |
| T53 | "`limit` defaults to 50, range 1 to 200. `has_more` is true when entries exist beyond the last one returned." | | UT | W4 |
| T54 | Authentication of the new endpoints | `/history`, `/values` and `/changes` require a bearer token, like every non-exempt endpoint (stage-1 R99). | UT 401 | W4 |

## Upgrades

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T55 | "A stage-3 service must accept an export produced by the same team's stage-1 or stage-2 service." | The shape is detected per dossier: stage-1 fields have no `candidates`; stage-2 fields have candidates without `true_from`; a stage-3 state has `builds`, `history` and `feed`. | UT with fixtures exported from frozen `stage-1/` and `stage-2/` | W10 `migrate.py` |
| T56 | "Every imported field that has a value gets one history entry of type `initial`, with `learned_at` the dossier's `researched_at` and `true_from` null unless the exported state records the dates that give it. The feed starts empty" | Stage-1: `true_from` is null. Stage-2: the selected candidate's `published_at` date in UTC (the export records no `Effective`; DEV-S3b). | UT | W10 |
| T57 | "the first build after import compares its selected values with the imported ones." | | UT | W10 |
| T58 | "Existing tokens, dossiers and completed idempotent responses survive the import as in `stage-1.md` §10, and the history and feed of a stage-3 export survive a stage-3 import unchanged. So do its builds: after a stage-3 import, `?as_of=` and `/values` answer as they did in the exporting service." | The stage-3 export holds builds, versions, history, feed and the seq counter. | UT round trip (all endpoints equal before and after) | W10 |
| T59 | "State imported from a stage-1 export counts as one build that completed `ready` at the dossier's `researched_at`, and each imported candidate's URL as one version gathered by it; imported candidates have `learned_at` equal to their `retrieved_at`." | Version `true_from` is null, so it holds from no date, and `/values` gives null fields for imported stage-1 state. This is the literal consequence (E3-4). | UT | W10 |
| T60 | "An `as_of` at or after that time and before the next build returns the imported fields, and an earlier `as_of` is 404. An imported dossier whose `researched_at` is null answers every `as_of` with 404 until a build completes." | | UT | W10 |
| T61 | "State imported from a stage-2 export keeps the builds that the stage-2 service made, each with its time, its outcome and its spending." | **Lead ruling U1, documented deviation DEV-S3a:** the stage-2 export (`stage-2/app/store.py:99-111`; `plans/builder-notes-stage-3.md` §1-2) records only the last ready build's candidates, `researched_at`, the last outcome and the total `spent_units`. It has no build list. A stage-2 dossier imports as one ready build at `researched_at`, holding every exported candidate and the whole `spent_units`. A null `researched_at` gives 404 for every `as_of`: no build row is created, the dossier, its exported `state` and its `spent_units` (kept as a baseline, `imported_spent`) are preserved, and `as_of` answers again only after a later ready build. Proof: UT `test_migrate3.py::stage2_null_researched_at`. The exported `state` stays the dossier's current outcome. | UT | W10 |
| T62 | "Each of them that completed `ready` keeps the candidates it gathered and, for each URL it gathered, one page version whose `true_from` follows from that page's `Effective` and `Published` lines as that build gathered them" | **Lead ruling U2, documented deviation DEV-S3b:** `Effective` was never exported, and neither were URLs read without a candidate. An imported stage-2 candidate's `true_from`, and its URL's version `true_from`, is the UTC date of its `published_at`, else null. A candidate stage 2 had itself imported (null `kind`) has a null `published_at`, so its `true_from` is null. | UT | W10 |
| T63 | "State that the stage-2 service had itself imported counts as one build that completed `ready` at the dossier's `researched_at`." | The same reconstruction as T61, so these cases need no separate handling. | UT | W10 |
| T64 | "`?as_of=`, `/values` and each candidate's `learned_at` then answer as if this service had made those builds. History is still one `initial` entry per field that has a value ... and an `as_of` response takes each field's `learned_at` and `true_from` from that history" | **Lead ruling U4:** a candidate's `learned_at` equals its `retrieved_at`. The field snapshot of the reconstructed build takes its `learned_at` and `true_from` from the initial entry. | UT | W10 |
| T65 | "An export of a stage-1 or stage-2 service has no `executives` candidates. After its import, `executives` is `unknown`, in the imported state and in every build kept from the export, and has no history entry; the first build that completes `ready` with a value for it adds a `change`, or an `initial` entry when it is the dossier's first build that completes `ready`." | "First build that completes ready" counts builds made by this service. An imported dossier with `researched_at` set already has a ready build, so executives gets a `change`. A dossier imported with no ready build gets `initial`. | UT | W10, W3 |

## Concurrency and restarts

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T66 | "Concurrent refreshes and reads must produce the same results as executing them one at a time in some order. No change appears twice in the feed, and none is missing from it." | Single event loop. Every mutation is one synchronous section that writes memory and SQLite together, with no `await` inside (E3-5). | UT gather tests | W5, W11 |
| T67 | "Disk - the container's filesystem; it survives a container restart" | The DB lives at `/srv/data/dossier.db`, a directory created in the image and owned by its runtime user `dossier` (lead ruling; builder notes R4). It is in the container filesystem, so no volume is needed. | RST | W11 |
| T68 | "The container may be stopped abruptly at any time ... The sentence "State need not survive an abrupt container restart" ... no longer applies." | SQLite with `journal_mode=WAL` and `synchronous=FULL`. Every state change commits before its response is sent. | RST (kill -9 during load, restart, compare) | W11 `db.py` |
| T69 | "Every account signs in with its password, and every bearer token is valid." | Users and token hashes are persisted at signup, login and reset. | RST | W11 |
| T70 | "Every dossier answers `GET /dossiers/{domain}`, with and without `as_of`, `GET /dossiers/{domain}/values` and `GET /dossiers/{domain}/history` as before, and `GET /dossiers` lists the same dossiers." | | RST | W11 |
| T71 | "The change feed holds the same entries with the same `seq`. An entry added after the restart has a larger `seq` than every entry before it." | | RST | W11 |
| T72 | "A replay of a completed idempotent request answers as §7 requires." | The idempotency record commits in the same transaction as the operation. | RST | W11 |
| T73 | "The clock reads the time it read before the stop until reset or `POST /_test/clock` moves it." | The clock value, and whether it has been set, are persisted in `meta` on reset, clock and import. | RST | W11 |
| T74 | "When no build is running at the stop" (scope of the guarantee) | A build interrupted by a crash is not resumed. At startup a dossier whose last build had not completed shows its last completed outcome, or `failed` if none, and the interrupted build's unsaved spend is lost (E3-6). | RST | W11 |

## Brief constraints

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| T75 | "spend units only where they change a field" (lead) and "how research spending interacts with executives" (brief) | Research still asks only the six fields (T12). Executives come only from rendered pages. One more lite query (confirmed by lead; not the bare domain), `<domain> chief financial officer chief operating officer chief technology officer CFO COO CTO`, costs 1 unit and surfaces executive pages. Budget: 9 searches + 25 research leaves 46; the 18-unit claim reserve then leaves 28 for search-page renders, about 15 renders per build in total (DEV-S2 unchanged). | UT budget; verifier `/calls` | W8 |
| T76 | "stage-1/ and stage-2/ frozen" | | CMD `git diff f50cd1c -- stage-1 stage-2` is empty | W0 |
| T77 | "stage-2 screens must keep working (the UI of stage 2 stays; executives is shown with other markup)" (brief) | | stage-2 E2E re-run in stage-3 | W9 |

## Changed earlier rows

| Earlier row | Change |
|---|---|
| R21, R179 (state need not survive restart) | Replaced by T67-T74: durable SQLite. |
| R52, S28 | Seven fields; candidates gain `true_from`, `learned_at` and `title` (executives). |
| R163-R178, S108-S116 | The export gains builds, versions, history, feed and seq. Import accepts stage-1, stage-2 and stage-3 shapes (T55-T65). |
| R160 | Unchanged: research asks for six fields (T12). |
| S117 / R213 | Searches go from 8 to 9 (T75). |

## Gaps, decisions, open items

- **DEV-S3a (T61, lead ruling U1).** The stage-2 export has no build list. Each stage-2 dossier
  imports as one ready build at `researched_at`, holding all exported candidates and the whole
  `spent_units`. Lost history:
  - an `as_of` before `researched_at` gives 404 even if stage 2 had earlier ready builds;
  - an `as_of` response's `spent_units` includes the spend of any later failed stage-2 build;
  - earlier candidates' first-gathered times are lost (`learned_at` = `retrieved_at`, U4);
  - URLs read without candidates are lost (no effect at import, since nothing earlier exists to
    replace).
- **DEV-S3b (T62, lead ruling U2).** `true_from` of imported stage-2 candidates, versions and
  initial history is the UTC date of `published_at`, else null. It is wrong exactly when the
  page had a valid `Effective` line.
- **Restart ruling (lead).**
  - Storage: stdlib SQLite, WAL mode, `synchronous=FULL`, and one transaction per state change
    committed before the response, including inside the build commit.
  - Data directory: `/srv/data`, owned by the runtime user.
  - What persists:
    - the clock;
    - tokens and accounts;
    - idempotency records;
    - builds and page versions (including pages with no candidates);
    - history, and the feed with its monotonic seq.
  - A build running at the stop is dropped on restart, and the dossier keeps its last
    completed state.
  - No new dependency.
- **E3-7** (from the audit) Executives history and feed entries are per field, not per title.
  The stage-3 text types "a history and feed entry for `executives`" by title and decides "the
  entry" from every differing title, so a build adds at most one `executives` entry. Its
  `value`/`from`/`to` are the member arrays, ordered `cfo`, `coo`, `cto` (T13). It comes after
  the six fields in seq order. No `title` key is added, since the spec's entry shapes have none.
- **E3-1** A failed build stores its time, outcome and spend but no versions or candidates. It
  is never an `as_of` snapshot.
- **E3-2** Validation order on the new endpoints, applied in sequence:
  1. auth;
  2. path domain (422);
  3. query parameters (422);
  4. dossier exists (404);
  5. build exists (404).
- **E3-3** Version tests include:
  - the spec sentences;
  - null-`true_from` replacement;
  - a no-candidate version ending an earlier one;
  - two versions in one build cannot occur (one per URL per build).
- **E3-4** Imported stage-1 versions hold from no date, so `/values` gives nulls for them.
- **E3-5** SQLite is called synchronously on the event loop. Each mutating handler runs: validate,
  then `with db.transaction():` write rows, then update memory after the commit. Reads come from
  memory, which is loaded from the DB at startup.
- **E3-6** Building flags are not persisted. A crash mid-build leaves the dossier at its last
  completed outcome. A dossier whose first build never completed is `failed` with unknown
  fields, the same as the stage-1 export rule R178.
- **Open-T1** `synchronous=FULL` cost under 50 concurrent writes on 2 vCPU: about 1-5 ms per
  commit on a local disk, not measured. To settle: the stage-1 50-request load check, re-run
  on stage 3.
- **Open-T2** Whether the harness restart check kills the container mid-request. Commit-before-
  respond covers it either way.
