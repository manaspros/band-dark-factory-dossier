# Dossier service — stage 3

An HTTP service and browser app that researches companies by web domain and keeps a
cited profile (a dossier) for each: six fields plus the company's executives (CFO, COO, CTO),
with every candidate value its sources support and one selected per field. Each dossier keeps
the history of its fields, answers as it stood at an earlier time (`?as_of=`) and what held on
a date (`/values?true_at=`), and publishes its changes in a feed (`/changes`). Python 3.12,
Starlette on uvicorn, state in SQLite on the container's filesystem. Every provider call goes
through WebRouter (`webrouter`, module `web_router`) to Nimble.

## Build and start

From this folder:

```sh
docker build -t dossier-stage-3 . && docker run --name dossier -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY -e NIMBLE_BASE_URL dossier-stage-3
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
history, the change feed, completed idempotent requests and the clock. A build running at the
stop is dropped; its dossier keeps its last completed state. No volume is needed (removing the
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
| `app/history.py`, `app/commit.py` | `learned_at`, history and feed entries; recording a finished build in one transaction |
| `app/timeline.py` | `?as_of=` snapshots and `/values` page versions |
| `app/transfer.py`, `app/migrate.py`, `app/restore.py` | Export/import; upgrading stage-1 and stage-2 exports; validating stage-3 exports |
| `app/ui_routes.py`, `app/ui/` | The browser app: one static shell, plain ES modules, no build step |

## Unit tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Upgrades from earlier exports

`POST /_test/import` accepts this service's exports and those of the stage-1 and stage-2
services. Those earlier exports record no build list and no `Effective` dates, so (lead
rulings DEV-S3a, DEV-S3b):
- each imported dossier counts as one build that completed ready at its `researched_at`,
  holding every imported candidate and its whole `spent_units`; with no `researched_at` there
  is no such build;
- an imported candidate's `true_from` is the UTC date of its `published_at`, else null, and its
  `learned_at` is its `retrieved_at`.

## Sources

Built from the stage-1 requirements and WebRouter's own documentation and docstrings only.
