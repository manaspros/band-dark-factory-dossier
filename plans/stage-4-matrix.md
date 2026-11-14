# Stage 4 (dossier) - requirement matrix

Source: the stage-4 requirements relayed verbatim by lead (2026-11-14, parts 0-3). I compared
them with `challenges/dossier/spec/stage-4.md` in the working folder and found the same text.
All earlier rows still apply with their lead rulings: stage-1 R1-R219, stage-2 S1-S120 and
stage-3 T1-T77, plus DEV-S1, DEV-S2, DEV-S3a, DEV-S3b and T38. The earlier rows this stage
changes are listed at the end. Stage-4 row ids are `F1...` and are never renumbered.
Decisions are `D4-n`. Deviations are `DEV-S4x`.

**Verified by** names the planned proof. I read no stage-4 supplied check or acceptance file,
so every row is marked **not exercised by supplied checks (unknown)**. The verifier reads
`report.json` to see which rows a run actually exercised. Codes:
- `UT`: a unit test in `stage-4/tests/`.
- `RST`: the restart script `stage-4/tests/restart_check.py`, run against the built image.
- `RD`: code reading.
- `CMD`: a shell command.

**Where** names the plan work item (`U*`) and the module under `stage-4/app/`.

## Global

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F1 | "All requirements from stages 1–3 continue to apply, with the additions below." (intro) | Carry-forward: `stage-4/` is a byte copy of `stage-3/` (ebc3dcf). The stage-1/2/3 unit and E2E tests keep passing; they are updated only where a row below changes them. | `pytest stage-4/tests`; harness `--stage 4` runs the earlier suites | U0 |
| F2 | "There are three idempotent write paths: stage 1's two and `POST /batches`." | §7 applies to `POST /batches` exactly as it does to the other two paths: user-scoped key, raw path, fingerprint, 409, 4xx not remembered, concurrent first use. | UT `test_batches_api.py::idempotency` (replay 200 with the identical body, different body 409, invalid body under a claimed key 409, a 4xx frees the key, two users with one key, 10 concurrent identical requests: one batch) | U6 `batches.py`, `idempotency.py` |
| F3 | "5. Spending never exceeds a budget that this specification or the caller sets." | Two budgets: 80 units per build (§9) and `budget_units` per batch. Both are reservations taken **before** each call (`Budget.reserve`), so neither can be exceeded, even by calls in flight or calls that are lost. This holds across a restart (F78). | UT `test_budget.py` (nested reserve; a lost call stays charged; neither cap can be passed under 50 concurrent reservations); RST | U5 `budget.py`, U7 |

## Lineage header lines

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F4 | "`Registrant: <domain>` \| The domain whose owner publishes the page" | Read with `support.header()` (first occurrence). The value is normalised as §4 (`domains.normalise`) and must be valid (`domains.is_valid`); otherwise there is no valid line. | UT `test_lineage.py::registrant` (valid; `WWW.Acme-Robotics.TEST.` normalises; `not a domain` is invalid; absent) | U1 `pages.py` |
| F5 | "`Canonical: <URL>` \| The page is a copy; the URL is the original" | Valid when the value parses with `urlsplit`, has an `http`/`https` scheme, and its host normalises to a valid domain. The original is fetched as written. **D4-1:** an invalid Canonical line counts as absent. | UT `::canonical` (valid, no scheme, bad host) | U1 |
| F6 | "`First-Published-By: <domain>` \| The page republishes material first published by that domain" | Normalised and validated as in F4. An invalid line counts as absent (D4-1). | UT `::first_published_by` | U1 |
| F7 | "Domains in these lines, and the host of a `Canonical` URL, are normalised as in §4." | `domains.normalise`, then `is_valid`. For a URL host, `pages._host_domain` (`stage-4/app/pages.py:18-26`) already does this. | UT | U1 |
| F8 | "A page with no valid `Registrant` line has the host of its own URL, normalised, as its registrant." | "Its own URL" is `Page.url`: the document URL the provider returned, else the requested URL (`web.py:115`). This is the same URL the candidates carry. | UT `::registrant_default` | U1 |

## Own pages

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F9 | "A page counts as kind `own` for a company only when its registrant is the company's domain." | `page_kind()` first computes the stage-2 kind (`pages.py:29-34`). Then: when that kind is `own` and the registrant ≠ the company's domain, the kind is `aggregator`. A page on the company's host with `Registrant: other.test` and no `Kind` line is therefore `aggregator`. | UT `test_lineage.py::kind` (Kind own with matching registrant; Kind own on another host with no Registrant; company host with a foreign Registrant; no Kind line on a foreign host) | U1 `pages.py` |
| F10 | "Any other page that states `Kind: own` has kind `aggregator` for the selection rule in `stage-2.md`, and its candidates report `"kind": "aggregator"`." | The candidate's `kind` field is the corrected kind (F9). Ranking uses that kind. | UT `test_selection.py::own_downgraded` | U1, U3 |
| F11 | "A page that states `Kind: own` and whose registrant is not the host of its own URL, normalised, is a **lookalike**" | `is_lookalike = header Kind == "own" (stripped) and registrant != _host_domain(page.url)`. It applies only to a page whose header **states** `Kind: own`. A page that is `own` by the no-Kind host default is never a lookalike. | UT `::lookalike` (states own, Registrant ≠ host → lookalike; states own without Registrant → not; no Kind line → not) | U1 |

## Origins

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F12 | "Every page has one **origin**, a domain, taken from the first of these that applies: 1. Its `First-Published-By` domain." | Rule 1 wins over Canonical and lookalike. | UT `test_origins.py::rule1` | U1 `origins.py` |
| F13 | "2. When its `Canonical` URL is not the page's own URL, the origin of the page at that URL (its **original**), by these same rules." | "Not the page's own URL": compare the Canonical value with `Page.url` as exact strings (**D4-2**). A self-canonical page falls through to rules 3/4. The original's origin is computed by rules 1-4, using the **original's** own URL and registrant, and lookalike judged against the company's domain. **Served URL (cycle-1 finding):** the original's "own URL" is the URL its provider served it at (`Page.url`, `web.py:115`). This may differ from the Canonical value when the provider redirects. So the resolver's fetch returns `Served(url, lineage)`, and that served URL is used for the original's self-canonical test, its default registrant (F8) and its lookalike host (F11). WebRouter gives no guarantee that the requested URL equals the returned URL, so none is assumed. | UT `::rule2_chain` (A→B; B has FPB x.test → origin x.test); `::self_canonical`; `::redirected_original` (Canonical U served at U′ whose Canonical is U′ → self-canonical, so the registrant default is host(U′); the same with no Registrant → host(U′), not host(U)) | U1 |
| F14 | "3. The company's domain, when the page is a lookalike." | | UT `::rule3_lookalike` (Kind own, Registrant shady.test, host acme-robotlcs.test → origin = company domain) | U1 |
| F15 | "4. Its registrant." | | UT `::rule4` | U1 |
| F16 | "A build obtains from a provider each original that rule 2 needs." | The build fetches each original with a Nimble rendered extract (3 units, through `Build.call` with the build and batch budgets). There is one fetch per URL per build (memo). An original that is already a rendered page of this build is not fetched again. **D4-3:** originals are fetched only for pages that yielded at least one candidate, because the origin of a page without candidates appears nowhere in a response (spend rule). An original is used only for its header lines. It yields candidates only when it is also evidence (a search result or a research-cited page), since §4 evidence is unchanged. | UT `test_build_origins.py` (fake web: one extract per original URL; none for a page without candidates; none for a URL already rendered) | U5 `build.py` |
| F17 | "From the page whose origin is sought, rule 2 follows at most three `Canonical` URLs in a row. Where it would follow a fourth, or where no provider serves a page at the URL, the host of that URL takes the place of the original's origin." | Hops are counted per starting page: P0→U1 (fetch), →U2 (fetch), →U3 (fetch); a fourth Canonical U4 on P3 gives `host(U4)`. A cycle is cut by the same cap. "No provider serves a page" covers: an extract that returns no document, a call still refused after its retries, a lost call, and **D4-4** a fetch the build or batch budget cannot afford. All of them give `host(URL)`. | UT `::three_hops` (exactly 3 fetches, then host of the 4th); `::cycle` (A↔B); `::unserved` (empty extract, 503 ×3, budget exhausted) | U1, U5 |
| F18 | "Pages with the same origin are one source, however many URLs, providers or kinds they have." | Every count of "distinct origins" (F21, F22, F26-F29, F37) counts origin strings, never URLs. | UT | U3 |
| F19 | "Candidates gain `origin`, the origin of their page." | `Candidate.origin: str` is a new dataclass field, output by `as_json` (in the order: after `kind`). It is not part of `identity()`, so `learned_at` (T5) is unchanged. | UT `test_api_shape.py::candidate_keys` | U3 `selection.py` |
| F20 | "Each field gains three keys" (example: `origins`, `corroborated`, `corroborated_since`) | All eight fields, in `GET /dossiers/{domain}`, `?as_of=` snapshots (stored per build), and the export. `/values` (**D4-5, lead ruling 2**): `{value, true_from, citations, origins, corroborated}` per field, computed from the candidates at `true_at` by the same member rules. There is no `corroborated_since` there. | UT shape tests; UT `test_values.py::keys` | U3, U8 |
| F21 | "`origins` lists the distinct origins of the candidates whose value is the selected value, sorted ascending. It is `[]` for an `unknown` field." | Six fields: candidates with `value_key == value_key(selected)`. Sorted by code point. A `contested` field counts only the selected value's candidates. | UT `test_corroboration.py::origins` | U3 `corroboration.py` |
| F22 | "`corroborated` is true when `origins` has two or more entries, otherwise false." | | UT | U3 |
| F23 | "`corroborated_since` is the time (§8) of the earliest ready build after which the selected value has had two or more **standing origins**, or null while it has fewer." | Computed at each ready commit by `corroboration.since(ready_builds_incl_new, field)`. The walk goes over ready builds in build order. The run of the current selected value starts at the last build that made it selected. Origins of the value's candidates accumulate per build, and the result is the time of the first build in the run where the cumulative set reaches 2. **D4-6:** builds are ordered by build number, not by time, because the test clock can give several builds one time. | UT `::since_walk` (1 origin, then +1 in the next build → that build's time; a value lost and regained restarts from none; build 2 gathers only origin a, build 3 only origin b → since = build 3) | U3, U4 `commit.py` |
| F24 | "The standing origins of a selected value are the origins of every candidate with that value that any ready build has gathered since the value became the selected value (the `learned_at` of its latest history entry, stage 3), whether or not a later build gathered it again." | Standing origins persist after the page drops out: `corroborated_since` can be non-null while `corroborated` is false. "Since it became selected" includes the build that made it selected. | UT `::standing_persists` | U3 |
| F25 | "A new selected value starts with none." | A change of selected value resets the set (the walk restarts at that build). | UT | U3 |
| F26 | "Imported candidates count as gathered at the imported `researched_at`." | A stage-1/2 import is one ready build at `researched_at` (T59/DEV-S3a), so the walk over that build gives it. | UT `test_migrate4.py` | U9 |
| F27 | "When a stage-3 export is imported, the candidates of each of its builds count as gathered at that build's time." | A stage-3 import keeps its builds. The walk runs over them, and each build's snapshot gains its own keys computed as of that build (F94). | UT `test_migrate4.py::stage3_builds_walk` | U9 |
| F28 | "Imported candidates whose export records no origin take the host of their URL, normalised, as their origin." | `pages._host_domain(url)`. A URL with no valid host makes the import 422 (**D4-7**), since an origin must be a domain. | UT | U9 `migrate.py` |
| F29 | "For `executives` (`stage-3.md`) and `investors` (below), these keys follow the field's members. A member's candidates are those with its title and name (`executives`) or with its name (`investors`)." | Executives member = a selected `{title, name}`. Its candidates have that title and the same `value_key(name)`. A candidate of the same name under another title is not one of them. | UT | U3 |
| F30 | "`origins` lists the distinct origins of the candidates of all members, sorted ascending. It is `[]` for an `unknown` field." | Union over members. | UT `test_corroboration.py::members_origins` | U3 |
| F31 | "`corroborated` is true when the candidates of every member have two or more distinct origins, and false otherwise, including for an `unknown` field." | Per member, over the current candidates. | UT (one member with 1 origin → false) | U3 |
| F32 | "`corroborated_since` is the time of the earliest ready build after which every member has had two or more standing origins, or null while some member has fewer or the field is `unknown`." | For each current member m: start(m) = the last ready build at which m became a member (it was not a member in the previous ready build). reach(m) = the first build ≥ start(m) at which m's cumulative origins reach 2. since = the time of the build max(reach(m)), else null. | UT `::members_since` (a member added later delays since; a member leaving and returning restarts) | U3 |
| F33 | "A member's standing origins are the origins of every candidate of that member that the build after which it last became a member, or any later ready build, has gathered, whether or not a later build gathered it again. Imported candidates count as above." | As in F32. | UT | U3 |

## Investors

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F34 | "A dossier has an eighth field, `investors`. The `fields` of every response that lists a dossier's fields hold it, after `executives`" | `ALL_FIELDS = FIELDS + (executives, investors)`. Applies to GET, `as_of`, `/values`, `/history` and the export. JSON key order follows `ALL_FIELDS`. | UT `test_api_shape.py::eight_fields` | U3 `fields.py` |
| F35 | "and the feed entries one build adds are numbered with `investors` last." | `entries_for_build` iterates `ALL_FIELDS`, so investors comes after executives. | UT `test_history.py::feed_order` | U4 |
| F36 | "For Appendix A, `investors` is a field with the statement phrases `investor`, `investors`, `led by`, `backed by` and `participated`." | A.2 rule 3 for investors. Whole-word and case-insensitive matching as A.2. | UT `test_support_investors.py::phrases` | U2 `support.py` |
| F37 | "Occurrences of the company's name and of these statement phrases are first taken out of the sentence and separate the words around them." | Removed spans: `_find_phrase(folded, company_name)` plus every phrase span. A capitalised word overlapping a removed span is dropped, and a run cannot cross a removed span (same technique as `_person_names`, `support.py:381-396`). | UT | U2 |
| F38 | "Of the runs of capitalised words (A.4) joined by single spaces that remain, each not part of a longer such run, a run of two or more words whose last word is `Ventures`, `Capital`, `Partners`, `Fund`, `Investments`, `Holdings` or `Equity` is an **investor name**." | Maximal runs only. The last word is compared exactly (case-sensitive; it is a capitalised word anyway). | UT `Acme Robotics is backed by Northwind Ventures and Bluebird Capital.` → both names; `Acme Robotics investor Ventures said ...` (one-word run) → none; `Acme Robotics investors include Big Sky Capital Partners.` → `Big Sky Capital Partners` only (maximal run) | U2 |
| F39 | "In an excerpt that contains an amount (A.4), the run that starts directly after `led by` or `backed by` and one space is an investor name too, whatever its length and last word: `Acme Robotics raised $40M in a round led by General Atlantic.` names `General Atlantic`, and `Acme Robotics is led by Dana Ruiz.` names no investor." | The amount is detected with `_amounts()`. "Directly after ... and one space": the phrase end is followed by exactly one space, then a capitalised word starts a maximal run (from the remaining words). A one-word run counts. Both spec examples are UT cases verbatim. | UT `::led_by_amount` (both examples) | U2 |
| F40 | "An investor name normalises to the text as the excerpt writes it." | The value is the exact substring (after the whitespace collapse already applied to excerpts). | UT | U2 |
| F41 | "Rules 1 to 4 of A.2 apply; in place of rule 5, an excerpt supports each investor name it contains." | `supports_investors(excerpt, domain) -> list[str]` returns names in sentence order, with no single-value rule. `support.candidates()` yields one `Support` per name. A negated sentence (A.3 negating phrases) yields none. | UT (two names → two candidates; `reportedly` → none; two sentences → none) | U2 |
| F42 | "The `value` of a candidate of `investors` is one investor name. A research claim is never a candidate of `investors`." | Research schema stays the six fields (T12). Investor candidates come only from rendered pages. | UT research payload has 6 properties | U2, U5 |
| F43 | "An investor name is a **member** when, among the field's candidates, one with that name has `kind` `own` or `filing`, or those with that name have two or more distinct origins." | `kind` is the corrected kind (F9). Names group by `value_key`. | UT `test_investors.py::membership` (own alone; filing alone; news+news, same origin → not a member; news+aggregator, two origins → member) | U3 `investors.py` |
| F44 | "In place of the selection rule in `stage-2.md`, the value is the array of the members' names, sorted by Unicode code point, or null when there is no member." | `sorted(names)` (Python str order = code point). | UT | U3 |
| F45 | "`investors` is `known` exactly when it has a member, and `unknown` otherwise, in place of the rules that make a field `known` exactly when the evidence supports a value for it." | Never `contested`. An `unknown` investors field may still list candidates (non-members). `true_from` and `learned_at` are null when unknown. | UT | U3 |
| F46 | "`selected` is true on every candidate whose name is a member, and false on the others." | | UT | U3 |
| F47 | "`candidates` lists every candidate in the order the selection rule in `stage-2.md` ranks them." | One ranked list over all investor candidates (`selection.rank`). | UT | U3 |
| F48 | "`citations` are, for each member in the order of the value, the `url`, `excerpt` and `provider` of every candidate with its name, in rank order." | | UT | U3 |
| F49 | "A member's `true_from` is the earliest `true_from` that is not null among the candidates with its name, or null when all of them are null. The field's `true_from` is the latest of its members' `true_from`, or null when the value is null or any member's is null." | Unlike executives (selected candidate's date), this is the earliest non-null date over the name's candidates. | UT | U3 |
| F50 | "`GET /dossiers/{domain}/values` decides membership from the candidates at `true_at` and gives the value, `true_from` and `citations` from them by these rules." | `timeline.values` calls `decide()`, which now includes `decide_investors`. Origins of version candidates are stored in build snapshots, so membership by origin works at `true_at`. Each field also gives `origins` and `corroborated` from those candidates (lead ruling 2). | UT `test_values.py::investors` | U8 `timeline.py` |
| F51 | "A history and feed entry for `investors` is typed by name, in place of the table in `stage-3.md` Changes and corrections." | One entry for the whole field (as E3-7 for executives). `value`/`from`/`to` are name arrays (or null). | UT | U4 `history.py` |
| F52 | "A name in the new value and not in the earlier one counts as a correction when its `true_from` and the earlier value's `true_from` are both not null and its `true_from` is on or before the earlier value's." | "Its `true_from`" = the member's `true_from` (F49) in the new field. "The earlier value's `true_from`" = the field-level `true_from` of the earlier field. A name only in the earlier value never counts as a correction. | UT `test_history.py::investors_typing` | U4 |
| F53 | "The entry is `correction` when every name in exactly one of the two values counts as a correction, and `change` otherwise." | Symmetric difference. Any removed name → `change`. Earlier value null → its `true_from` null → `change`. First ready build → `initial` (T-rows unchanged). | UT (added-only with earlier dates → correction; added+removed → change; later date → change) | U4 |
| F54 | "The screens treat `investors` as `stage-3.md` treats `executives`: it takes none of the `data-testid` attributes of `stage-2.md`, and "no field is contested" on `/contested` means none of the six fields of §4 is." | The dossier and evidence screens show an Investors section with `data-section` markup only. Contested iterates the six fields only (`contested.js`, unchanged). | E2E `tests/e2e/behaviour.py` (no `field-investors`/`candidate-investors-*` testid; the stage-2 suite is unchanged) | U10 UI |

## Batches

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F55 | "`POST /batches` starts builds, and so joins `POST /dossiers` and `POST /dossiers/{domain}/refresh` as a request that makes provider calls (§8, Builds)." | Every other request makes no provider call (stage-1 R-row on §8 last bullet, amended). | RD; UT fake web counts calls on GET /batches = 0 | U6 |
| F56 | "A batch researches several companies under one shared budget. A batch belongs to the user who created it; another user's batch is 404 `not_found`." | `Batch.user_id`. GET by another user → 404, the same as an unknown id. The idempotency key is user-scoped. Unauthenticated → 401 first. | UT `::other_user_404`, `::unauth_401` | U6 |
| F57 | "**An idempotent write path.** `Idempotency-Key` is required; see §7." | Missing/empty → 400 `missing_idempotency_key`; over 255 characters → 422. Order as `create`: authenticate → key → parse the body → replay check → validation (§7 last paragraph). | UT | U6 |
| F58 | 202 example: `{ "batch_id": "b_2", "state": "running", "budget_units": 200, "spent_units": 0, "dossiers": [ {domain, state} ... ] }` | Exactly these keys. `batch_id` = `b_` + an opaque id (`State.new_id("b")`, which must also avoid batch ids). The first use always gives **202** (D4-8), even when no build starts. `state` is `running` when at least one build started, else `done`. | UT shape | U6 |
| F59 | "`domains` missing, empty or longer than 50 entries \| 422 `validation_failed`" | 50 entries is valid; 51 → 422. | UT boundary 0/1/50/51 | U6 |
| F60 | "An entry of `domains` invalid after normalisation (§4) \| 422 `validation_failed`" | `domains.normalise` + `is_valid`. **D4-9:** `domains` that is not an array, or an entry that is not a string, is a field of the wrong JSON type → 400 `malformed_request` (§5). The 422-over-400 override is stated only for `budget_units`. Confirmed by lead ruling 3. | UT | U6 |
| F61 | "Two entries of `domains` the same after normalisation \| 422 `validation_failed`" | `Acme.test` and `acme.test` → 422. | UT | U6 |
| F62 | "`budget_units` missing, not an integer, below 1 or above 100000 \| 422 `validation_failed`" | 1 and 100000 valid. | UT boundaries | U6 |
| F63 | "A `budget_units` that is not an integer is 422 `validation_failed` whatever its JSON type: a string, `true` or `1.5` included. The row above takes precedence over the 400 `malformed_request` of §5 for a field of the wrong JSON type." | `is_int` excludes bool. `100.0` (a JSON float) → 422. `"200"`, `null`, `[]`, `{}` → 422. | UT parametrised | U6 |
| F64 | "`dossiers` lists the normalised domains in the order given, each with its dossier's state." | The state at response time: `building` for each new dossier; an existing dossier's current state (which may be `building` from another request). | UT | U6 |
| F65 | "A domain with no dossier gets one, and the batch runs its first build. A domain that already has a dossier is not researched by the batch and costs it nothing." | In one synchronous section: create the missing dossiers and start their builds with `batch_id`. Existing dossiers are untouched, even if a build is running. Concurrent `POST /dossiers` for the same domain still creates one dossier (§8). | UT (existing ready dossier: no calls, no spend; mixed list) | U6 |
| F66 | "`spent_units` is the total cost (§9) of the provider calls the batch's builds made. It never exceeds `budget_units`." | Live: the sum over the batch's builds of the units already settled as charged, plus the units recovered at a restart (F80). Never above `budget_units`, because every call reserves from the batch budget first. | UT (fake web, budget 30, 3 domains: spent ≤ 30, equals the sum of the dossiers' increments) | U5, U6 |
| F67 | "Each build in a batch still spends at most 80 units, and its cost also counts in its dossier's `spent_units`." | Nested budget: the build `Budget(cap=80, parent=batch_budget)`. | UT | U5 |
| F68 | "When the budget would be exceeded by a further call, the batch makes no more provider calls, and its remaining builds complete with the pages and research claims they have obtained: each of their fields is `known` exactly when those support a value for it." | When a reservation is refused by the batch budget, the batch is marked `exhausted`, and every later reservation of any of its builds is refused, even one that would fit. Each build then decides from what it has. **D4-10 — lead ruling 1.** This Batches text overrides §8's "`failed` when none of its provider calls succeeded" **for budget exhaustion only**. A batch build stopped by the exhausted batch budget completes `ready`, with each field `known` exactly when what it obtained supports a value. That includes a build that made zero calls: it ends `ready` with every field `unknown`, `researched_at` set to its build time, and no history entry. A build that made calls which all failed (provider failure, F73) is still `failed`. The rule lives in one function, `build_outcome(succeeded, attempted, stopped_by_batch_budget)`: failed iff `not succeeded and not stopped_by_batch_budget`. | UT: budget 1 with 2 domains, the second build makes 0 calls and ends `ready`/all unknown; exhausted stops a fitting 1-unit call; a batch build whose calls all 503 before exhaustion ends `failed` | U5, U6 |
| F69 | "Returns the batch in the shape above. `state` is `running` while any of its builds runs, then `done`. Unknown batch is 404 `not_found`." | `running` iff some dossier the batch started holds a running build with this `batch_id`. | UT | U6 |

## Provider failure

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F70 | "A provider may answer a call with an error (any 5xx status, or 429). The build continues: it may make the same request again, through that provider or another." | Existing retry policy (lead rulings: 429 ×3 at 1.05 s, off the clock; other refusals ×2 at 1.05 s; fast-regime cutoff 8 s). Nimble only (D4-11): Tavily, Kernel and Browserbase are never called. | UT existing `test_build.py` retry cases | U5 |
| F71 | "A build in which every call to one or more providers fails, while `nimble` answers, completes `ready`, with every field `known` that the evidence (§4) reachable through the providers that answer supports." | Holds by construction: the service calls only Nimble (D4-11). With an un-keyed Tavily the service makes no Tavily call at all. | UT: fake web where only Nimble answers → ready; RD `web.py` | U5 |
| F72 | "A build in which every research run fails, while searches and extracts are answered, completes `ready`, with every field `known` that the evidence reachable by search and extract supports." | "Research fails" covers: a start refused after retries; polls that keep erroring; a run that finishes without a response. **Gap P1 (builder notes §4):** today, failing polls loop until the 270 s deadline. Fix: give up on research after 3 consecutive failed polls, 1.05 s apart (a 429 poll waits off the clock, as today). The gather order is unchanged: claim pages first, then search pages. A failed run gives no claim URLs, so the build goes straight on to search pages and ends within §8's 10 s (about 1 s of searches, up to about 3.2 s of failed polls, then renders). | UT `test_provider_failure.py::research_fails` ×3 (each ends ready in < 10 s on the fast clock, fields from search pages) | U5 |
| F73 | "A build in which every call to every provider fails completes `failed` (§8), within the time bound of §8." | Every call refused → `succeeded` stays false → `failed`, fields unchanged. With 503: retries ×2 at 1.05 s ≈ 2.1 s, and research polls never start. With 429: waits are off the clock. Lost calls (timeouts) are not retried. | UT `::all_fail` (503 and 429 variants, elapsed < 10 s minus 429 waits) | U5 |
| F74 | "A call a provider refuses with an error status costs nothing (§9)." | `classify_failure`, `web.py:71-82`: a 429/5xx refusal → `charged=False`, and its reservation is released. A durable reservation (U7) is released in the same settle. | UT `::refused_free` (all 503 → spent 0) | U5, U7 |

## Restarts

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F75 | "The restart requirements of `stage-3.md` hold for batches as for the rest of the state." | The `batches` table is written in the same transaction as the POST's idempotency record. Batch spend is written through as calls are reserved and settled. | RST (GET /batches/{id} identical after kill; replay identical) | U6, U7 |
| F76 | "When builds are running at the stop, everything else is still answered as before the stop" | Every other dossier, batch, feed, token and replay answers the same. | RST variant `--during-build` | U7 |
| F77 | "Does not stay `building`. It ends `ready` or `failed` within 10 seconds of `GET /health` first answering 200 after the restart, when each provider call it makes after the restart answers within one second. It may end `failed` although some of its calls succeeded; it then leaves the fields as they were (§8)." | **D4-12:** at startup, **before** `/health` answers, every persisted in-flight build (`running` table) is recorded as a `failed` build at its own build time, with its persisted spend. The fields stay as they were, no history or feed entry is added, and the outcome is `failed`. No call is made after the restart. | RST (kill during a fake-slow build; first healthy GET shows `failed`, fields equal to before) | U7 |
| F78 | "Is one build across the restart: its calls before and after the stop together spend at most 80 units (§9), and a batch's builds together never spend more than its `budget_units`." | Trivial under D4-12: there are no calls after the restart, and reservations before the stop were bounded by both caps. | RST, RD | U7 |
| F79 | "Has every unit a provider billed for its calls, before and after the stop, counted in its dossier's `spent_units` and, for a batch's build, in the batch's `spent_units`. They may also count calls that were in flight at the stop and that no provider billed." | The reservation is committed durably **before** each call, and the release of a refused call's units is committed after the call. The recovered build's spend = the persisted reserved units, so billed units ≤ the counted units. **In flight (cycle 1, argued, D4-14):** a call is in flight from the moment its reservation is committed until its answer is settled. The commit and the send are adjacent: `_attempt` commits the reservation and the very next statement awaits the provider call, with no other `await`, sleep or retry wait between them. Retry waits happen after the previous attempt has settled and before the next reservation. So no reservation is held across any wait. Counting only after the send would lose units billed if the process is killed after the provider received the request (forbidden by "every unit a provider billed ... counted"), so the record must precede the send. The window between commit and send is one synchronous step. | RST (kill mid-build: dossier spent after restart ≥ units the fake provider billed, and ≤ billed + units of calls the stub saw arrive without answering); UT `test_budget.py::no_reservation_across_wait` (a reservation is never held during a retry sleep or a poll sleep) | U7 |
| F80 | "After the restart, `POST /dossiers/{domain}/refresh` starts a new build of each such dossier as it does for any other." | No `running` row is left after recovery, so `dossier.build is None`. | RST | U7 |

## Upgrades

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F81 | "A stage-4 service must accept an export produced by the same team's stage-1, stage-2 or stage-3 service, preserving dossiers, candidates, history, the change feed and completed idempotent responses as in `stage-1.md` §10." | `transfer.import_state` accepts 4 shapes per dossier: stage-1/2 (no `builds`), stage-3 (`builds`, 7 fields), stage-4 (`builds`, 8 fields). Detection: `"builds" in d` and `"investors" in d["fields"]`. | UT `test_migrate4.py` with committed fixtures `stage1-export.json`, `stage2-export.json` (exist) plus a new `stage3-export.json` exported from the frozen `stage-3/` service | U9 |
| F82 | "A stage-3 export keeps its builds: after the upgrade, `?as_of=` and `/values` answer from them as the stage-3 service did, with the keys this stage adds." | Every kept build snapshot is upgraded at import: candidates gain `origin` (F28); `investors` is added as unknown; every field gains `origins`/`corroborated`/`corroborated_since` (walk F27). The stage-3 values are otherwise byte-equal. | UT (as_of and /values on the stage-3 fixture: equal to stage-3's answers plus the new keys) | U9 |
| F83 | "Citations carried in the imported state remain citations served to this service." | Excerpts and URLs are kept verbatim (U4 of the builder notes). | UT | U9 |
| F84 | "An export of a stage-1, stage-2 or stage-3 service has no `investors` candidates. After its import, `investors` is `unknown`, in the imported state and in every build kept from the export, and has no history entry" | `history["investors"] = []`. | UT | U9 |
| F85 | "the first build that completes `ready` with a value for it adds a `change`, or an `initial` entry when it is the dossier's first build that completes `ready`." | Existing `entries_for_build` logic (first_ready → initial). The feed entry only for `change`. | UT | U4, U9 |

## Spend (lead constraint, not a spec sentence)

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| F86 | "STAGE 4 RESEARCH SPEND per correct field is judged against a fixed benchmark, so spend units only where they change a field (no redundant calls, no repeated identical calls, stop research once fields are settled)." (brief) | Strategy in plan §Spend: memo per build for search (by query) and extract (by URL); originals only for pages with candidates; batch shares; research skipped when the allowance cannot also afford a claim page. **Lead ruling 4 (D4-13):** "stop research once fields are settled" is a lead phrase, not a spec requirement. There is no early stop that could change candidates, origins, contested status or membership. Spend stays minimal otherwise: (a) no repeated identical call (search memo by query string, extract memo by URL, and by served URL once known); (b) no render of a URL that cannot yield a candidate or an original: a URL already rendered or served in this build, a URL whose host is not a valid domain (`_host_domain` is None), a non-`http(s)` URL, or a second copy of a URL in the results; (c) no original fetch for a page without candidates (D4-3). | UT `test_spend.py` (fake web): no query string sent twice; no URL extracted twice, including one that is both a claim page and a search result and one that is both an original and a search result; no extract for an invalid-host or `mailto:` URL; no original fetch for a candidate-less page | U5 |
| F87 | "WebRouter is the only route to providers; Nimble must suffice alone; no credentials committed" (brief) | `web.py` remains the only provider module. | CMD `grep -rn "httpx\|requests\." stage-4/app` shows no provider route; `git grep` for keys is empty | U5 |
| F88 | "stage-1/2/3 frozen" (brief) | | CMD `git diff 0ffd736 -- stage-1 stage-2 stage-3` is empty | all |
| F97 | "A build whose provider calls each answer within one second ends within 10 seconds of the request that started it." (stage-1 §8, carried; added in cycle 1) | Stage 4 adds work (originals up to 3 hops), so the bound is re-proven, with numbers, in plan U5 §Schedule (lead ruling 6). The nominal timeline with no retries and 1 s answers: searches and the research start together, 0-1 s; research polls, 1-3 s; claim pages, 3-4 s; their originals, 3 sequential hops, 4-7 s, with search-page renders running concurrently from 4 s; originals of the search pages, up to 3 hops, 5-8 s. With retries, one call takes up to three attempts plus two waits: 1 + 1.05 + 1 + 1.05 + 1 = **5.1 s**. Every step that depends on it shifts later by up to 4.1 s, so the nominal timeline is **not** the bound (cycle-2 correction). **The bound rests only on the guard invariant below.** **Fast-regime guard (D4-15):** while every answer has come within 1 s, no new call of any kind starts after 8.0 s of effective build time (the inherited `FAST_RETRY_CUTOFF_SECONDS`, `build.py:57`). That covers renders, original fetches, retries and research polls. 429 waits are off the clock, as before. At the guard the build decides with what it has. A Canonical hop the guard stops gives the host of its URL (DEV-S4b). A research run still unfinished at 8 s is abandoned (no claim pages). The invariant is that every attempt **starts** at ≤ 8.0 s of effective time. Each retry checks `effective_elapsed + 1.05 ≤ 8.0` before its wait (`build.py:181-184`), and each poll, render and original fetch checks `effective_elapsed ≤ 8.0` immediately before reserving. With answers ≤ 1 s, every attempt therefore **ends** ≤ 9.0 s. After 8.0 s nothing new starts: a pending retry, poll or hop sees the guard and returns not-served, and work waiting on research takes no claim URLs. So the build has no outstanding work after 9.0 s. Deciding and committing is synchronous and takes milliseconds, so the build ends < 10 s whatever the retry pattern. | UT `test_timing.py::mixed_retry_chain`. The fake web answers every call in 0.95 s and records each attempt's start time. Its pattern: every search and the research start refused 503, 503, then OK (≈ 4.95 s each); research polls 503, OK-running, then done; every claim page has candidates and a 3-hop Canonical chain, and the first hop's original is refused 503 once. Assertions: the build ends < 10 s from start and `ready`; no attempt starts after 8.0 s effective; a hop cut by the guard gives host(URL); the build's spend equals the charged attempts only. Also UT `test_timing.py::worst_case_fast` (fake web with every call answering in 0.95 s, research finishing after 3 polls, every page with candidates and a 3-hop Canonical chain, budget for every render: ends < 10 s from start, state ready); `::slow_research_fast_calls` (polls answer fast, the run never finishes → ready < 10 s); the existing all-503 and research-failure timing cases | U5 |

## Earlier rows this stage changes

| ID | Earlier row | Change |
|---|---|---|
| F89 | stage-1 §7 "Two write paths require an idempotency key" | Now three (F2). |
| F90 | stage-1 §8 Builds: "every request except `POST /dossiers` and `POST /dossiers/{domain}/refresh` make no provider call" | Plus `POST /batches` (F55). A dossier's first build may also start from `POST /batches`. |
| F91 | stage-2 "Page kind" (S-rows on Kind) | Kind `own` requires registrant = company domain (F9-F10). |
| F92 | stage-3 T50 feed numbering "then `executives`" | Then `investors` (F35). |
| F93 | stage-3 T74 / E3-6 "a build interrupted by a crash ... records nothing; unsaved spend is lost" | Replaced by F77-F79 (D4-12): it is recorded `failed` with its persisted spend. |
| F94 | stage-3 T9 `as_of` snapshots | Snapshots now carry `origins`, `corroborated`, `corroborated_since` and `investors`, stored per build at commit/import. `corroborated_since` in a snapshot is as of that build (no later builds). |
| F95 | stage-3 T75 queries (9 lite searches) | Plus one investors query (10 searches) (plan §Spend). |
| F96 | stage-3 restore validation (`restore.py:19-23` exact key sets) | Stage-3 key sets are kept for detection; stage-4 sets add `origin`, `origins`, `corroborated`, `corroborated_since`, `investors`. |

## Decisions

- **D4-1** An invalid lineage header line is treated as absent: an invalid Registrant falls back
  to the host (F8), and an invalid Canonical or First-Published-By is ignored.
- **D4-2** "Canonical URL is not the page's own URL" is an exact string comparison with
  `Page.url`. No URL canonicalisation is specified, so none is invented.
- **D4-3** Originals are fetched only for pages that yielded a candidate. They are header
  sources, not new evidence.
- **D4-4** A Canonical hop whose fetch the budget cannot afford is treated like "no provider
  serves a page": the URL's host is used.
- **D4-5 (lead ruling 2).** `/values` fields are `{value, true_from, citations, origins,
  corroborated}`, the last two computed from the candidates at `true_at` by the same member
  rules (Upgrades: "with the keys this stage adds"). There is no `corroborated_since` in
  `/values`, because its walk is undefined for an arbitrary `true_at`. `investors` is added.
- **D4-6** The `corroborated_since` walk orders builds by build number.
- **D4-7** An imported candidate URL with no valid host is an invalid import (422).
- **D4-8** The first use of `POST /batches` always gives 202, as the example shows, even when
  every domain already existed. In that case `state` is `done` at once.
- **D4-9** A `domains` value of the wrong type, or an entry of the wrong type, gives 400
  `malformed_request` (§5). Only `budget_units` has the 422 override.
- **D4-10 (lead ruling 1).** A batch build stopped by budget exhaustion completes `ready`,
  even with zero calls. The Batches text overrides §8's failed rule for budget exhaustion
  only, and a build whose calls all failed is still `failed` (F68).
- **D4-11** Nimble only, as in stages 1-3. This satisfies F71 and the Nimble-alone constraint
  and avoids paying 8 units per Tavily lite search.
- **D4-12** In-flight builds end `failed` at startup with their persisted spend (explicitly
  allowed by F77). This is the minimal answer and spends no units after the restart.
- **D4-13** (lead ruling 4) There is no settled early stop. Spend stays minimal through
  call memos, no render of a URL that cannot yield a candidate or an original, and originals
  only for candidate pages (F86).
- **D4-14** (cycle 1; lead ruling 5 confirms) A call is in flight from its reservation commit
  to its settle. The commit is immediately followed by the send, with no wait in between
  (F79).
- **D4-15** (cycle 1; lead ruling 6) Fast-regime guard: no new call starts after 8.0 s of
  effective build time (F97).
- **D4-16** (cycle 1 finding) The original's own URL is its served `Page.url`, carried by the
  resolver's `Served(url, lineage)` (F13).

## Deviations (stage 4)

- **DEV-S4b (D4-15).** In the fast regime, a Canonical hop not started by 8 s takes the host
  of its URL. It is the same fallback as an unserved original, applied only to keep the §8
  bound.

## Not exercised by supplied checks

Unknown for every row: I read no stage-4 check. The rows most likely to be covered only by our
own proofs are F11, F13, F17 (hop cap, cycles), F24, F32-F33 (standing-origin walks), F52-F53,
F60, F68 (exhausted batch), F72 (failing polls), and F77-F79 (restart during a build).

## Carried limitations

DEV-S1, DEV-S2 (budget-limited renders), DEV-S3a, DEV-S3b, and T38 (import does not
cross-check a candidate's `true_from` against its page version). T38 is **not** fixed in stage 4:
the stage-3 attempt 6d82a06 was reverted (0ffd736), and re-applying it is not cheap to prove.
