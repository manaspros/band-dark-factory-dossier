# Dossier service — stage 4

An HTTP service and browser app that researches companies by web domain and keeps a
cited profile (a dossier) for each: six fields plus the company's executives (CFO, COO, CTO)
and investors, with every candidate value its sources support and one selected per field.
Each value says which independent origins stand behind it (copies, syndicated pages and
lookalike sites count once, through their `Registrant`, `Canonical` and
`First-Published-By` header lines). Each dossier keeps
the history of its fields, answers as it stood at an earlier time (`?as_of=`) and what held on
a date (`/values?true_at=`), and publishes its changes in a feed (`/changes`). Python 3.12,
Starlette on uvicorn, state in SQLite on the container's filesystem. Every provider call goes
through WebRouter (`webrouter`, module `web_router`) to Nimble.

## Build and start

From this folder:

```sh
docker build -t dossier-stage-4 . && docker run --name dossier -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY -e NIMBLE_BASE_URL dossier-stage-4
```

- `PORT` (default `8080`) is the port the service listens on, on `0.0.0.0`.
- `NIMBLE_API_KEY` is the Nimble credential. It is read from the environment by WebRouter and
  never stored or logged by the service.
- `NIMBLE_BASE_URL` is the Nimble endpoint. Leave it unset for the live endpoint
  (`https://sdk.nimbleway.com`); never set it to an empty string, which breaks every call.
- `TAVILY_API_KEY` / `TAVILY_BASE_URL`, `KERNEL_API_KEY` / `KERNEL_BASE_URL` and
  `BROWSERBASE_API_KEY` / `BROWSERBASE_BASE_URL` may be passed but are not used: the service
  researches with Nimble alone and reads every page through Nimble's rendered extract.

Open `http://localhost:8080/` in a browser, sign up, and research a domain.

`GET /health` answers `{"status": "ok"}` once the service is up (a few seconds).

State lives in `/srv/data/dossier.db` (SQLite in WAL mode, `synchronous=FULL`) on the
container's filesystem, created in the image and owned by the runtime user `dossier`. Every
change is committed to disk before its response is sent, so after `docker kill dossier` and
`docker start dossier` the service answers as before: accounts, tokens, dossiers, builds,
history, the change feed, batches, completed idempotent requests and the clock. Every
provider call's units are written to disk before the call is made, so a build running at the
stop is ended `failed` when the service starts again (before `/health` answers), with every
unit it had reserved counted in its dossier's and its batch's `spent_units`; its fields stay
as they were, and a refresh starts a new build. No volume is needed (removing the
container with `docker rm` removes its state). `DATA_DIR` (default `/srv/data`) moves the
database directory, for running outside the image.

## Code map

| Module | What it does |
|---|---|
| `app/main.py` | Routes, error envelope, startup |
| `app/control.py` | `/health`, `/_test/reset`, `/_test/clock`, `/_test/export`, `/_test/import` |
| `app/auth.py` | Signup, login, bearer tokens, scrypt password hashing |
| `app/dossiers.py`, `app/idempotency.py` | Dossier endpoints and `Idempotency-Key` handling |
| `app/store.py`, `app/db.py` | In-memory state the handlers read; the SQLite file every change is written to first |
| `app/clock.py`, `app/domains.py`, `app/http.py`, `app/errors.py` | Clock, domain rules, request/response helpers |
| `app/build.py`, `app/budget.py` | Background builds: searches and research, then rendered page reads, the 80-unit cap |
| `app/web.py` | The only module that imports `web_router` |
| `app/support.py`, `app/pages.py`, `app/candidates.py` | Appendix A support rules; page kind and publication time; candidates per page |
| `app/selection.py`, `app/executives.py`, `app/fields.py` | The selection rule and status; executives per title; the seven fields |
| `app/history.py`, `app/commit.py` | `learned_at`, history and feed entries; recording a finished build in one transaction; ending builds a stop interrupted |
| `app/origins.py`, `app/corroboration.py`, `app/investors.py` | Origins of pages (lineage lines); `origins`/`corroborated`/`corroborated_since`; the investors field |
| `app/batches.py` | `POST /batches`, `GET /batches/{id}` |
| `app/timeline.py` | `?as_of=` snapshots and `/values` page versions |
| `app/transfer.py`, `app/migrate.py`, `app/restore.py` | Export/import; upgrading stage-1 and stage-2 exports; validating stage-3 exports |
| `app/ui_routes.py`, `app/ui/` | The browser app: one static shell, plain ES modules, no build step |

## Unit tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Batches and budgets

`POST /batches` (`{"domains": [...], "budget_units": N}`, with an `Idempotency-Key`) starts the
first build of each listed domain that has no dossier yet; `GET /batches/{id}` shows its
state and spending. Every provider call reserves its units first, from the build's cap (80
units, or its share of the batch: `budget_units` over the new domains) and from the batch's
budget, so neither is ever exceeded. Once a call would exceed the batch's budget, the batch
makes no further calls and its builds finish with what they have.

Provider failures: a refused call (5xx or 429) costs nothing and is retried (429: three times,
others: twice, 1.05 s apart); research is given up after three failed status checks in a row,
and the build goes on with the pages its searches found. Nimble is the only provider used.

## Upgrades from earlier exports

`POST /_test/import` accepts this service's exports and those of the stage-1, stage-2 and
stage-3 services. Imported candidates without an origin take their URL's host as origin;
`investors` is unknown in imported state and in every build kept from a stage-3 export.
Stage-1 and stage-2 exports record no build list and no `Effective` dates, so (lead
rulings DEV-S3a, DEV-S3b):
- each imported dossier counts as one build that completed ready at its `researched_at`,
  holding every imported candidate and its whole `spent_units`; with no `researched_at` there
  is no such build;
- an imported candidate's `true_from` is the UTC date of its `published_at`, else null, and its
  `learned_at` is its `retrieved_at`.

## Sources

Built from the stage-1 requirements and WebRouter's own documentation and docstrings only.
