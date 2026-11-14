# Stage 2 (dossier) - requirement matrix

Source: the stage-2 requirements as relayed verbatim by lead (2026-11-14, two parts). Stage-1
rows (`plans/stage-1-matrix.md`, R1-R219) still apply. The rows they change are listed in
"Changed stage-1 rows" with the stage-2 row that replaces them. Stage-2 row ids are `S1...`.
They are never renumbered.

Column key as in stage 1.
- **Verified by:** `S2` = `challenges/dossier/test/stage_2/test_sample.py` (the only supplied
  stage-2 check read), or **NOT EXERCISED** with the planned proof. Proof codes: `UT` = unit
  test in `stage-2/tests/`, `E2E` = Playwright script in `stage-2/tests/e2e/`, `RD` = code
  reading, `CMD` = command.
- **Where:** the plan work item (`V1...`) and the module under `stage-2/app/` (`ui/` = static
  front end).

## Global

| ID | Quote (section) | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S1 | "The stage-1 requirements continue to apply, with the additions below." (preamble) | Every R row stays in force unless listed as changed below. Carry-forward rule: `stage-2/` starts as a copy of `stage-1/`. | harness stage-1 suite re-run in stage 2 | V0 |
| S2 | "3. A field's selected value is the one the selection rule below picks from the field's candidates; the same candidates always yield the same value." (invariant 3) | `select()` is a pure total order (S27-S32). Input order never matters. | UT `test_selection.py::permutation_invariant` (every permutation of 6 candidates gives the same ranking) | V3 `selection.py` |

## Page kind and publication time

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S3 | "`Kind: own`, `Kind: filing`, `Kind: news`, `Kind: aggregator` - The page's **kind**" (Page kind) | Read from the page's header block (stage-1 header rule D13). The value is matched exactly after trimming spaces (E1). | UT `test_pages.py::kind_header` | V2 `pages.py` |
| S4 | "`Published: <RFC 3339 timestamp>` - When the page was published" | Parse with the stage-1 `parse_rfc3339` (offset required). Output keeps the page's own offset. | UT | V2 |
| S5 | "A page with no `Kind` line, or with a value not listed above, is of kind `own` when the host of its URL, normalised as `stage-1.md` normalises a domain, is the company's domain, and of kind `aggregator` otherwise." | Host via `urllib.parse.urlsplit(url).hostname`, then `domains.normalise` (www. stripped, lowercased). A subdomain other than `www.` is `aggregator`. | UT (`https://www.acme.test/x` gives own; `https://blog.acme.test` gives aggregator; `Kind: blog` falls back) | V2 |
| S6 | "A page with no `Published` line, or with a value that is not an RFC 3339 timestamp, has no publication time." | `published_at: null`; a date without time or without an offset counts as no time. | UT | V2 |

## Page text and web access

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S7 | "a page's **text** is the text a browser shows once the page has loaded, without clicking controls." (Page text) | Candidates come only from browser text: Nimble rendered extract, or a Kernel session's `read(format="text")` with no clicks (E2). Plain extract and search text are never used for candidates. | S2 `test_every_field_has_ranked_candidates` (`assert_citations` substring vs corpus text, partial); NOT EXERCISED for browser-only pages -> UT with fake reader returning different static vs browser text | V1 `reader.py`, V4 |
| S8 | "Activating disclosure controls is not required." | No clicking. | RD | V1 |
| S9 | "Evidence (§4) is read from page text so defined, and a citation's excerpt must appear in the page's text." | Excerpts are sentences of the browser text (whitespace-collapsed). | S2 `assert_citations` (partial); UT provenance | V4 |
| S10 | "A citation's `provider` is the provider that served the text the excerpt was copied from." | `nimble` for rendered extract, `kernel` for session reads. | UT provenance (`kernel` reader gives `kernel`) | V1, V4 |
| S11 | "an extract through `nimble` may ask Nimble to load the page in a browser ...: `provider_options={"render": True}` on WebRouter's extract." | Nimble path: `extract(url, provider="nimble", provider_options={"render": True})`. | RD; verifier: mock `/calls` shows `render: true` | V1 `web.py` |
| S12 | "Two optional browser vendors are also available ...: `kernel`, through `open_browser`; `browserbase`, through `open_browser` and `browse`." | **Lead decision 4:** Nimble rendered extract is the primary, required path. Kernel is added (V1b) only if a harness run shows Nimble alone cannot gather the full candidate set within 80 units. Browserbase is never used. | RD | V1, V1b |
| S13 | "A service may use Nimble's rendered extract alone to obtain every page's browser text; neither browser vendor is required." | Nimble-only uses rendered extract in priority order until the cap, with no probe filter (E3). A page the budget does not reach is the documented budget limit DEV-S2. If Kernel is ever added, Nimble-only keeps working when Kernel is absent, failing, or its sessions are exhausted. | UT `test_reader.py` (no Kernel key gives Nimble only; Kernel failure falls back); verifier harness run with Nimble only | V1 |
| S14 | "A service that uses these vendors passes their base URLs to WebRouter in `provider_config`" `{"kernel": {"base_url": <KERNEL_BASE_URL>}, ...}` | `provider_config["kernel"] = {"base_url": env}` only when set. Keys are never read by the service. | RD | V1 `web.py` |
| S15 | Cost: "Extract through `nimble` that loads the page in a browser - 3 per URL requested, including a URL for which no page is returned" | `cost_of("nimble","extract",render=True)=3`, charged unless refused. | UT `test_budget.py` | V1 `budget.py` |
| S16 | Cost: "Open a session through `kernel` 0"; "`browserbase` 2"; "Each page served to a session, through either 1"; "Browse run through `browserbase` 4" | Kernel page load: reserve 1, settle 1 on a served page. A failed load is free. | UT | V1 |
| S17 | "A failed open, a failed page load and releasing a session cost nothing." | Settle 0 on open failure, failed `goto` (navigation error / non-200), and release. Applies only if V1b is triggered. | UT (V1b) `test_reader.py`: a failed `open_browser` costs 0, a failed `goto` costs 0, a release costs 0; budget totals asserted | V1b |
| S18 | "Each provider keeps at most 4 sessions open at once; opening another is answered with an error." | Process-wide semaphore of 4 Kernel sessions shared by all builds (E4). | UT pool never exceeds 4 under 3 concurrent builds | V1 `sessions.py` |
| S19 | "A session that no client has been connected to for 60 seconds is closed by the provider." | Sessions are opened per build and released in `finally`. A closed session (PageClosedError) falls back to rendered extract for the remaining pages. | UT | V1 |

## Rate limits

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S20 | "a provider may answer any call with 429. A call answered 429 costs nothing" | 429 is a refusal (0 units). | UT | V1 build |
| S21 | "The same call ... made again less than one second after a 429 for it was answered is answered 429 again." | Wait 1.05 s before retrying after a 429 (lead carry-over). | UT fake clock | V1 |
| S22 | "No call is answered 429 more than three times in a row, except that opening a session while its provider keeps 4 open ... is answered 429 until one of them closes." | A 429 gets up to **3** retries (4 attempts), so the 4th attempt is guaranteed past the 429 streak. Other refusals keep the stage-1 cap of 2 retries. **Confirmed by lead (C-S1)**: this raises the stage-1 L1 cap for 429 only. A session open that is 429 at the cap falls back to rendered extract. | UT (429 x3 then 200 is read; 500 x3 is dropped) | V1 |
| S23 | "Time a build spends waiting to make a call again after a 429 does not count toward the 10 seconds of `stage-1.md` §8." | Build clock = wall time minus the union of 429-wait intervals. The stage-1 fast-regime cut-off uses this clock, and 429 retries are not cut off by it. | UT `test_build.py::clock_excludes_429_waits` | V1 `build.py` |

## Candidates

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S24 | "A **candidate** is one value for one field, supported by one excerpt of one page. Every value that a page of the evidence (§4) supports for a field is a candidate of that field, once for each such page." | Key (field, normalised value, url). Each page's sentences are scanned in order; the first supporting sentence becomes the excerpt (E5). | S2 `test_disagreeing_sources_make_a_field_contested` (value set equals expected) | V4 `candidates.py` |
| S25 | "The evidence now also holds the page that each research claim of the evidence cites, whether or not the citation supports its claim: a build reads that page as it reads any other." | Every distinct research claim URL (at most six, one per field) is rendered whatever the claim says. 18 units are reserved until research completes, and search-page renders wait for it (plan Budget split). | NOT EXERCISED -> UT (an unsupported claim's page is still read and its supported values become candidates; `six_distinct_claim_pages_all_read`: six claims cite six pages while searches return 25 URLs, and all six are rendered within 80 units) | V1 |
| S26 | "A research claim whose citation does not support it is still not a candidate." | Claim excerpts are never candidates themselves. Candidates come only from the page text that was read (E6). | UT | V4 |
| S27 | "A candidate's `provider` is a provider that served the text its excerpt is taken from; when several did, any of them may be given." | | UT provenance | V4 |
| S28 | Candidate shape: `value, url, excerpt, provider, kind, published_at, retrieved_at, selected` (Candidates example) | | S2 `fx.assert_candidates` | V4, V6 |
| S29 | "`url`, `excerpt` and `provider` follow the citation rules in §4." | 1-500 chars, single sentence, from prose (stage-1 R66/R67). | S2 `assert_citations` (partial); UT | V4 |
| S30 | "`kind` is the page's kind, and `published_at` its publication time or null. Only an imported candidate (below) has a null `kind`; it has the authority of `aggregator`." | | UT | V3, V4 |
| S31 | "`retrieved_at` is the time of the build that gathered the candidate (§8, Builds)." | The build's time, which is also `researched_at` when it completes `ready`. | S2 `test_every_field_has_ranked_candidates` | V4 |
| S32 | "`selected` is true on exactly one candidate of a field that has candidates, the one the rule picks, and false on the others." | | S2 `assert_candidates` | V3 |
| S33 | "`candidates` lists the candidates of the last build that completed `ready`, in the order the selection rule ranks them, the selected one first. A field with no candidate has `"candidates": []` and is `unknown`." | While a later build runs, the previous candidates show. A failed build keeps them. | S2 (partial); UT for building/failed | V4, V5 |
| S34 | "Two values are the same value when they are equal as JSON values; strings are compared exactly, after removing surrounding whitespace." | `same(a,b)`: same JSON type, ints equal, `str.strip()` equal. `1` vs `"1"` are different. | UT | V3 |

## Selection rule

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S35 | "1. **Authority** of the page's kind: `own` and `filing` rank equal and highest, then `news`, then `aggregator`." | Authority: own/filing 3, news 2, aggregator/null 1. | UT | V3 `selection.py` |
| S36 | "2. **Recency** within the same authority: the later `published_at` ranks higher. A candidate without a publication time ranks below every candidate of the same authority that has one." | Compare instants, not strings. | UT (`+02:00` vs `Z` at the same instant tie) | V3 |
| S37 | "3. **URL**: ... the candidate whose `url` is smaller, comparing the strings by Unicode code point, ranks higher; between two candidates with the same URL, they rank by provider in the order `nimble`, `tavily`, `kernel`, `browserbase`." | Python `str` comparison is by code point. | UT | V3 |
| S38 | "4. **Value**: ... integers compare as numbers, strings by Unicode code point after removing surrounding whitespace." | | UT | V3 |
| S39 | "The highest-ranked candidate is the selected one. The field's `value` is the selected candidate's value, and its `citations` are the `url`, `excerpt` and `provider` of every candidate with that value, in rank order." | Replaces stage-1 D7 and D32 (lead ruling L3's hq_city preference is superseded by the spec rule) (E7). | S2 (partial); UT | V3 |
| S40 | "A candidate of lower authority is selected only when no candidate of higher authority exists for that field. The rule runs over all of a field's candidates." | Follows from S35 being the first key. | UT | V3 |

## Status and list

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S41 | "`known` - The field has candidates, and they all have the same value" | | S2 `test_agreed_fields_are_known` | V3 |
| S42 | "`contested` - The field's candidates carry two or more different values" | | S2 `test_disagreeing_sources_make_a_field_contested` | V3 |
| S43 | "`unknown` - The field has no candidate; `value` is null" | | S2 | V3 |
| S44 | "A `contested` field still has a selected `value` and its citations." | | S2 | V3 |
| S45 | "`GET /dossiers` (§8) is unchanged. The `legal_name` it lists is the selected value." | | NOT EXERCISED for contested legal_name -> UT | V5 |

## Screens and routing

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S46 | Routes `/`, `/dossiers/{domain}`, `/dossiers/{domain}/evidence`, `/contested`, `/signup`, `/login` "must be reachable by URL" | Served as a static HTML shell with no dossier data, without a bearer token (E19), by a client-rendered SPA (E8). | S2 `test_routes_are_directly_navigable` | V7 `ui_routes.py` |
| S47 | "Other screens must be reachable through the UI." | No other screens are planned. Navigation links connect all six routes. | RD | V8 |
| S48 | "The browser and the API share `/dossiers/{domain}`. Return the UI for `Accept: text/html`; API requests without that header receive JSON." | `text/html` anywhere in `Accept` gives the HTML shell, without needing a token. Otherwise the stage-1 JSON handler runs (auth as before). | S2 `test_api_and_browser_share_the_dossier_route` | V7 |
| S49 | "`/`, `/dossiers/{domain}/evidence` and `/contested` are browser routes; they read the API's dossier data." | No new API endpoints. Evidence reads `GET /dossiers/{domain}`. Contested reads the paginated `GET /dossiers` plus a `GET` per dossier. | RD | V8 |
| S50 | "The domain in a browser route is normalised as in §4." | The client normalises with the same rule. An invalid domain shows `dossier-not-found`, and canonical-form routing uses `history.replaceState` (E9). | E2E (`/dossiers/WWW.ACME.TEST` shows `acme.test`) | V8 |
| S51 | "The UI must expose the `data-testid` attributes listed below" | Every listed id is planned in V8/V9. | S2 (subset); E2E for all | V8, V9 |

## Product and visual direction

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S52 | "coherent, presentation-ready research product ... calm, legible, evidence-first" | One design system (`ui/styles.css` tokens). | NOT EXERCISED -> verifier screenshot review at 375 px and 1280 px | V8 |
| S53 | "A field's value and its status must be the clearest information on the dossier screen, with its citations directly beside it." | Field card layout: value (large), then a status chip, then the citations list. | screenshot review | V9 |
| S54 | "status, provider, page kind and publication time should be understandable without interpreting raw API data" | Human labels: "Company site", "Filing", "News", "Data aggregator", "Unknown source type"; provider names; dates formatted. | screenshot review | V9 |
| S55 | "Use a consistent visual system for typography, spacing, colour, controls and feedback. Primary actions - research, refresh - must be easy to identify." | | screenshot review | V8 |
| S56 | "Known, unknown, contested, building, failed, loading, successful, refused and uncertain states must be visually distinct" | Each has its own chip/banner style with icon and text, not colour alone. | E2E captures each state; screenshot review | V8, V9 |
| S57 | "Format names, years, headcount ranges, money and timestamps for people first; expose technical identifiers only where they help the user." | `founded_year` "2014" (no grouping); headcount "51-200 employees"; money "US$12,000,000" with a compact hint "($12M)"; timestamps via `Intl.DateTimeFormat`; ids hidden. | UT `format.test` (node-free: exercised in E2E) | V8 `ui/format.js` |
| S58 | "Each citation shows its excerpt as quoted text and links to its URL." | `<blockquote>` + `<a href=url>` (host shown as link text). | E2E | V9 |
| S59 | "usable at a 375 CSS-pixel viewport and at conventional desktop widths, without horizontal page scrolling" | Fluid layout. Long URLs and excerpts use `overflow-wrap:anywhere`. | E2E asserts `scrollWidth <= innerWidth` at 375 and 1280 on every route | V8 |
| S60 | "Inputs need visible labels, keyboard focus must be apparent, and text and controls need sufficient contrast." | `<label for>` on every input; `:focus-visible` outline; WCAG AA contrast tokens. | E2E (labels present); RD contrast table in `styles.css` comments | V8 |
| S61 | "Provide considered empty, loading and error states, and keep navigation consistent across the required routes." | Shared header/nav on every route. | E2E | V8 |
| S62 | "Runtime assets ... fonts, scripts and stylesheets" must be in the image (stage-1 §2, R22) | No CDN, no web fonts (system font stack). | CMD `grep -rn "https://" stage-2/app/ui` shows no asset URLs | V8 |

## Signup and login

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S63 | `signup-email`, `signup-password`, `signup-display-name`, `signup-submit` | | S2 routes test; E2E | V9 `ui/auth.js` |
| S64 | `login-email`, `login-password`, `login-submit` | | S2; E2E | V9 |
| S65 | "`auth-error` - Error message. Present only when there is one" | Removed from the DOM, not just hidden, when there is no error. | E2E | V9 |
| S66 | "`current-user` - Visible on every screen when signed in. Text contains the display name" | Header shows the display name stored with the token. | E2E | V8 |
| S67 | "`logout-button` - Button" | Clears the stored token and user, then goes to `/login`. No server call (tokens never expire, §6) (E10). | E2E | V8 |

## Dossier list `/`

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S68 | `research-domain` input; "`research-submit` - Button. Sends `POST /dossiers`" | Sends with a fresh `Idempotency-Key` per new attempt. | S2 `test_research_from_the_list_opens_the_dossier` | V10 `ui/list.js` |
| S69 | "`research-error` - Error message, when the request is refused - including an invalid domain" | Any 4xx response. The message comes from the API `error.message`, mapped to friendly text for 422. | E2E | V10 |
| S70 | "`research-uncertain` - Shown when the outcome of a research request is unknown" | Network error, timeout (15 s AbortController) or 5xx (E11). | E2E with request interception (abort after the server commits) | V10, V11 |
| S71 | "`dossier-search` - Input. Filters the list as `q` does on `GET /dossiers`" | Debounced 250 ms `GET /dossiers?q=`. Latest read wins. | E2E | V10 |
| S72 | "`dossier-list` - Container. Children ordered by domain ascending" | Server order kept. Pages through `has_more` (limit 200). | E2E | V10 |
| S73 | "`dossier-item-{domain}` ... Carries `data-state="{state}"`. Text contains the domain, and the legal name when known. Links to `/dossiers/{domain}`" | "When known" means the selected value is not null (contested names are shown too). | E2E | V10 |
| S74 | "`empty-dossiers` - Shown instead of the list when no dossier matches" | `dossier-list` is not rendered then (E12). | E2E | V10 |
| S75 | "A research request that succeeds, with 202 or 200, opens `/dossiers/{domain}` for the normalised domain." | Navigate using the response `domain`. | S2 | V10 |
| S76 | "A domain that already has a dossier, including one created by another client after this browser read the list, opens that dossier and starts no build." | Always POSTs; a 200 opens the dossier (the server starts no build). | E2E | V10 |

## Dossier `/dossiers/{domain}`

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S77 | "`dossier-domain` - Text is exactly the normalised domain" | | S2 | V9 `ui/dossier.js` |
| S78 | "`dossier-state` - Text is exactly `building`, `ready` or `failed`" | Exact text in the element; any decoration sits outside it. | E2E | V9 |
| S79 | "`dossier-spent` - Formatted `spent_units`. Carries `data-units="{integer}"`" | | E2E | V9 |
| S80 | "`dossier-researched-at` - Text contains `researched_at`, formatted. Absent when it is null" | | E2E | V9 |
| S81 | "`field-{field}` - One per field, six in all, in the order of the table in `stage-1.md` §4. Carries `data-status`" | | S2 `test_dossier_screen_shows_its_fields` | V9 |
| S82 | "`field-value-{field}` - The formatted value. Carries `data-value`. Present only when the value is not null" | | S2 | V9 |
| S83 | "`field-contested-{field}` - A marker. Present only when the field is `contested`" | | E2E | V9 |
| S84 | "`field-citations-{field}` - Container of the field's citations, in API order" | | E2E | V9 |
| S85 | "`citation-{field}-{n}` ... Text contains the excerpt. Contains a link whose `href` is the citation's `url`. Carries `data-provider`" | `n` counts from 1. | E2E | V9 |
| S86 | "`dossier-evidence-link` - Link to `/dossiers/{domain}/evidence`" | | E2E | V9 |
| S87 | "`dossier-refresh` - Button. Sends `POST /dossiers/{domain}/refresh`" | | E2E | V9, V11 |
| S88 | "`refresh-error`" when refused; "`refresh-uncertain`" when unknown | Same classification as S69/S70. | E2E | V11 |
| S89 | "`dossier-reload` - Button. Reads the dossier again without starting a build" | GET only. | E2E (mock `/calls` unchanged) | V9 |
| S90 | "`dossier-not-found` - Shown instead of the fields when no dossier exists for the domain" | Shown on a 404 or 422 for the path domain. | E2E | V9 |
| S91 | "`data-value` is the API value as text: a string value unchanged, an integer in plain decimal digits." | `String(v)` for ints, the raw string otherwise. | S2 | V9 |
| S92 | "While the dossier's state is `building`, the screen reads the dossier again at least every 2 seconds until the state is `ready` or `failed`, and then shows the new fields without a manual reload." | Poll every 1.5 s from the time each read is issued. Stops on a terminal state or on navigation away. | E2E | V12 `ui/reader.js` |

## Evidence and contested

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S93 | "`evidence-{field}` - One container per field, six in all. Children in API `candidates` order" | | S2 routes test (anchor); E2E | V9 `ui/evidence.js` |
| S94 | "`candidate-{field}-{n}` ... Text contains the formatted value and the excerpt. Carries `data-value`, `data-provider`, `data-kind`, `data-url`, `data-published-at` (the RFC 3339 `published_at`, empty when null) and `data-selected`" | `data-kind` is empty for an imported null kind (E13). | E2E | V9 |
| S95 | "`evidence-empty-{field}` - Shown instead of candidates when the field has none" | | E2E | V9 |
| S96 | "`contested-list` - Container. Children ordered by domain ascending, then by field in the order of the table in `stage-1.md` §4" | | E2E | V9 `ui/contested.js` |
| S97 | "`contested-item-{domain}-{field}` - One per contested field of any dossier. Carries `data-value` for the selected value. Text contains the domain, the field and every distinct candidate value. Links to `/dossiers/{domain}/evidence`" | Field shown with a human label, plus the raw field name in small text so "contains the field" holds (E14). | E2E | V9 |
| S98 | "`empty-contested` - Shown instead of the list when no field is contested" | | S2 routes test | V9 |

## Refresh and competing clients

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S99 | "After any successful action, the data on the same page must show the new state without a manual reload." | After 202/200, re-read the dossier, which then polls while `building`. | E2E | V11 |
| S100 | "Navigation must wait for the write to succeed before it refreshes the data." | `await` the POST, then navigate or read. | E2E | V10, V11 |
| S101 | "**Latest read wins:** a delayed earlier read must not overwrite a later one, including when responses arrive out of order. This applies to the reads while a dossier is `building` as well." | Each screen has a monotonically increasing read sequence. A response is applied only if its sequence is greater than the last applied one (E15). | E2E with route interception: reload race, polling race while building, reload vs poll (V12) | V12 |
| S102 | "A refresh from this browser while that build runs is answered 202 like any other and the screen follows the running build to its end." | 202 leads to a read showing `building`, then polling. | E2E | V11 |
| S103 | "If a research or refresh response is lost, including after the request commits, show `research-uncertain` or `refresh-uncertain` (nonempty text), not `research-error` or `refresh-error`." | | E2E (route abort after forwarding) | V11 |
| S104 | "Keep the request retryable with the **same key and body**." | The pending `{key, body, path}` is kept in memory. The retry button and a repeat submit of the same domain reuse it (E16). | E2E: inspect request headers on retry | V11 |
| S105 | "A successful retry removes both the error and the uncertainty elements, shows the dossier, and starts at most one build." | | E2E + mock `/calls` (one build) | V11 |
| S106 | "Unknown outcomes are not confirmed refusals." | Never show the error element for unknown outcomes. | E2E | V11 |
| S107 | "No background polling beyond the reading while `building`, live synchronization, or recovery across page reloads is required." | Nothing more is built. | n/a | V12 |

## Existing clients after an upgrade

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S108 | "A stage-2 service must accept an export produced by the same team's stage-1 service." | `import_state` accepts the stage-1 state shape: fields of exactly `{value,status,citations}` (`stage-1/app/store.py:131-143`) and no candidates. | NOT EXERCISED -> UT using a real stage-1 export fixture generated from `stage-1/` (E17) | V6 `migrate.py` |
| S109 | "A browser signed in before that export/import upgrade must remain signed in afterwards." | Token hashes carry over (`stage-1/app/store.py:104`). The UI keeps its token in `localStorage`. | E2E | V6, V8 |
| S110 | "Imported dossiers appear in the list and on their screens." | | E2E | V6 |
| S111 | "Each imported field gains one candidate for every value that text the providers served to the dossier's last stage-1 build that completed `ready` supports for that field, once for each page whose served text supports it." | **Lead ruling (accepted limitation DEV-S1):** the stage-1 export records only each field's selected value and its citations, with no page texts, kind or publication time (`stage-1/app/store.py:98-111`; `plans/builder-notes-stage-2.md`, commit 980c440). Import rebuilds candidates from the exported citations only: one candidate per (field, value, url), taking the excerpt and provider as exported (the first exported excerpt for that URL). Values stage-1 supported but did not select cannot be recovered, so such fields import as `known` with one value. | UT `test_migrate.py` with a stage-1 export fixture (one candidate per distinct citation URL; a dossier that was contested in stage-1 imports as `known`, documented) | V6 |
| S112 | "The candidate's excerpt is taken from that text and supports the value; its `provider` is the provider that served that text, its `kind` and `published_at` are as the exported state records them or else null, and its `retrieved_at` is the dossier's `researched_at`." | Per the lead ruling: `kind` and `published_at` null (null kind has `aggregator` authority, so selection falls through to URL, then provider, then value); `excerpt` and `provider` as exported; `retrieved_at` = `researched_at`. | UT | V6 |
| S113 | "Each imported field's `value`, `status` and `citations` then follow from its candidates by the selection rule and Status, as after a build." | | UT | V6 |
| S114 | "A research or refresh request whose response was lost before export remains retryable after import with the same body and key; the UI must recover the original response and show the imported dossier." | Idempotency records carry over. A replay gives 200 with the original body. The UI's in-memory pending request survives because no reload happens. | E2E: lose response, export from stage-1, import into stage-2, retry | V6, V11 |
| S115 | "These requirements apply when import completes between browser requests; migration during an in-flight request is not required. No page reload or new screen is required." | | n/a | V6 |
| S116 | "The candidates of an imported dossier are replaced by those of its next completed build." | A `ready` build replaces them. A failed build keeps them (stage-1 R125). | UT | V5 |

## Brief constraints

| ID | Quote | Meaning / decision | Verified by | Where |
|---|---|---|---|---|
| S117 | "spend units only where they change a field" (lead) | Research runs in every build. Its cited pages are evidence (S25) and are often non-searchable `filing` pages, which have top authority and so can change the selected value and the status. The stage-1 conditional rule (D28) no longer holds. Page renders run in priority order until the cap (E3); unreached pages are the budget limit DEV-S2. **Confirmed by lead (C-S2)**. | verifier `/calls` per build | V1 |
| S118 | "stage-1/ frozen" | No edits under `stage-1/`. | CMD `git diff 1135775 -- stage-1` is empty | V0 |
| S119 | Lead carry-over: "retry cap 2 with 1.05 s backoff; exact-domain search max 3 attempts; hq_city per A.4" | Kept, except S22 (429 gets 3 retries, flagged) and S39 (hq_city selection now follows the spec rule; A.4 extraction is unchanged). | RD | V1, V3 |
| S120 | Judging: "coherent, responsive (375 px and desktop, no horizontal scroll), clear in every state ..., labels, visible focus and contrast" (brief) | Same as S52-S61. | E2E + screenshots | V8 |

## Changed stage-1 rows

| Stage-1 row | Change |
|---|---|
| R1, R2, R61 | Excerpts must appear in browser page text (S9). `provider` may be `kernel` (S10). |
| R52, R58 | Field shape gains `candidates` (S28). |
| R59, R60 | `status` gains `contested` (S41-S44). A contested field has a value and citations. |
| R62, R69, R70 | Evidence adds research-cited pages (S25). Claims are not candidates on their own (S26). |
| R71, D7, D32 | Replaced by the selection rule (S35-S40). |
| R125 | A failed build also keeps candidates (S33). |
| R152 | Cost table adds rendered extract and session costs (S15-S17). |
| R155 | 429 is free and is retried after 1.05 s, up to 3 times (S20-S22). |
| R127 | Time spent waiting after a 429 is excluded (S23). |
| R163-R178 | Export state gains candidates. Import accepts stage-1 and stage-2 shapes (S108-S116). |
| R213, D28 | Research is no longer conditional (S117). |
| R216 | The clean-room rule now covers the UI as well: no copied product UI or code. |

## Conflicts, gaps and decisions

- **G1 / DEV-S1 (S111), resolved by lead ruling (accepted limitation).** The stage-1 export lacks
  page texts, kind, publication time and losing values. Import rebuilds candidates from the
  exported citations only: one per (field, value, url), with excerpt and provider as exported,
  `kind` and `published_at` null, and `retrieved_at` = `researched_at`. A field that had other
  values in stage 1 imports as `known` with one value until its next build.
- **E18 (lead ruling, carry-forward compatibility).** Stage 2 keeps these unchanged:
  - token storage as sha256 of the bearer token (the UI sends the same bearer token from
    `localStorage`);
  - the idempotency record key (user_id, method, raw path, key);
  - fingerprints: canonical JSON of `{"domain": ...}` for `POST /dossiers`, and `{}` for
    refresh;
  - `format_version: 1` for exports.

  The import validator is widened to accept both field shapes: the stage-1 shape (exactly
  `value`, `status` known/unknown, `citations`) and the stage-2 shape (with `candidates`, and
  status known/contested/unknown). Rows S108, S109, S114.
- **C-S1 (S22), confirmed by lead.** A 429 refusal gets 3 retries, 1.05 s apart, and the waits
  are excluded from the build clock (S23). Other refusals keep the cap of 2. The exact-domain
  search keeps 3 attempts for non-429 refusals.
- **C-S2 (S117), confirmed by lead.** Research runs in every build (25 units), because its cited
  pages are evidence.
- **C-S3 / DEV-S2 (S7/S13/S24 vs R3), resolved by lead ruling (documented budget limit).**
  Correctness wins: no page is excluded from rendering by a probe. With Nimble-only rendering
  at 3 units per page, a page the 80-unit budget does not reach is the only legitimate loss.
  Each build logs the count of unreached URLs. Kernel (V1b) is triggered if a Nimble-only
  harness run shows such losses change candidates.
- **E1** Header values are taken after `Kind:` with the line's surrounding spaces trimmed, and
  matched case-sensitively against the four kinds.
- **E2** Browser text from Kernel is `browser.read(format="text")` after `goto`. The README
  says it returns an `ExtractedDocument`; whether it is the page's `innerText` is unverified
  (Open-S1).
- **E3** (lead decision 4 and lead ruling on E3) Nimble-only read pipeline. 47 units remain after
  8 search units and 25 for research, and 18 of them are reserved for up to six
  research-cited pages (S25).
  1. Research-cited URLs are always rendered first (3 each), once research completes.
  2. Search URLs are then rendered (3 each) in priority order:
     - first, those whose lite snippet contains a supporting sentence;
     - then the rest by authority hint: the `Kind:` header when the page's text is already
       known, else the company's own host first;
     - ties broken by URL in code-point order.
  3. Rendering continues until the 80-unit cap leaves room for no more. Every rendered page is
     read in full.
  4. No plain-extract probe is used, and no page is excluded for lacking a snippet statement.
     Candidates come only from rendered text (S7).
- **E4** (only if V1b is triggered) A process-wide pool of at most 4 Kernel sessions. Page loads
  cost 1, open costs 0, and sessions are released in `finally`. Kernel serves only pages the
  Nimble pipeline could not afford. It is never required.
- **E5** Per (field, value, page), the excerpt is the first supporting sentence in page order.
- **E6** If a research-cited page cannot be read (budget or failure), that claim contributes
  no candidate.
- **E7** The stage-1 L3 `hq_city` preference is superseded by the spec's selection rule. A.4
  extraction is unchanged.
- **E8** The UI is a client-rendered single-page app: plain ES modules, no build step, static
  files served from `/static/`. The six routes return one HTML shell.
- **E9** A non-canonical domain in the URL is replaced in place with `history.replaceState`.
- **E10** Logout is client-side only.
- **E11** An unknown outcome is a fetch rejection (network error or abort after 15 s) or any 5xx.
  A 4xx is a refusal.
- **E12** Empty states replace their containers.
- **E13** An imported null `kind` gives `data-kind=""` and the label "Unknown source type
  (imported)".
- **E14** Contested items show the human field label and the API field name.
- **E15** Read sequence numbers are per screen and per resource. A response that arrives late
  is discarded.
- **E16** The pending write is keyed by (method, path, body). A new body gets a new key.
- **E19** (open to lead, from the audit) Auth boundary for HTML. Stage-1 R99 covers the JSON API.
  The browser routes, including `GET /dossiers/{domain}` with `Accept: text/html`, return
  the same static shell with no dossier data. A top-level browser navigation cannot carry a
  bearer header, and the shell reads every dossier through the authenticated API. So no
  dossier data is served without a valid token. Proof: UT `test_ui_routes.py`: a
  `text/html` request without a token returns 200 with the shell, and the body contains no
  domain-specific data; the JSON API without a token is still 401.
- **E17** The migration fixture is produced by running the frozen `stage-1/` service in tests
  (or a recorded export from it) and committed under `stage-2/tests/fixtures/`.

## Open items (unverified)

- **Open-S1** Whether WebRouter's async browser handle `read(format="text")` returns browser
  `innerText` from a Kernel CDP session against the mock page server. To settle: builder runs one
  read in the container against the harness mock.
- **Open-S2** Whether Nimble rendered extract through `provider_options={"render": True}` maps to
  the request field `render: true` (the mock bills `RENDER_COST` 3 on `render is True`, per
  `challenges/dossier/web/mockweb/nimble.py`). To settle: check the mock `/calls` log.
- **Open-S4** Moot after the lead ruling on E3: there is no probe left to be wrong. The remaining
  loss is DEV-S2, which the Nimble-only harness run measures.
- **Open-S3** (V1b only) The Playwright dependency for the `[browser]` extra adds image size. Version
  pinning must follow the org's 7-day release-age rule.
- **Open-1..5** (stage 1) still apply.
