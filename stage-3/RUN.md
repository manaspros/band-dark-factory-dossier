# Dossier service — stage 2

An HTTP service and browser app that researches companies by web domain and keeps a
cited six-field profile (a dossier) for each, with every candidate value its sources
support and one selected per field. Python 3.12, Starlette on uvicorn, state in memory. Every
provider call goes through WebRouter (`webrouter`, module `web_router`) to Nimble.

## Build and start

From this folder:

```sh
docker build -t dossier-stage-2 . && docker run --rm -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY -e NIMBLE_BASE_URL dossier-stage-2
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

`GET /health` answers `{"status": "ok"}` once the service is up (a few seconds). State lives in
memory and does not survive a restart.

## Code map

| Module | What it does |
|---|---|
| `app/main.py` | Routes, error envelope, startup |
| `app/control.py` | `/health`, `/_test/reset`, `/_test/clock`, `/_test/export`, `/_test/import` |
| `app/auth.py` | Signup, login, bearer tokens, scrypt password hashing |
| `app/dossiers.py`, `app/idempotency.py` | Dossier endpoints and `Idempotency-Key` handling |
| `app/store.py`, `app/clock.py`, `app/domains.py`, `app/http.py`, `app/errors.py` | State, clock, domain rules, request/response helpers |
| `app/build.py`, `app/budget.py` | Background builds: searches and research, then rendered page reads, the 80-unit cap |
| `app/web.py` | The only module that imports `web_router` |
| `app/support.py`, `app/pages.py`, `app/candidates.py` | Appendix A support rules; page kind and publication time; candidates per page |
| `app/selection.py`, `app/migrate.py` | The selection rule and status; importing stage-1 and stage-2 exports |
| `app/ui_routes.py`, `app/ui/` | The browser app: one static shell, plain ES modules, no build step |

## Unit tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Sources

Built from the stage-1 requirements and WebRouter's own documentation and docstrings only.
