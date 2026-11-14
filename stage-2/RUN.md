# Dossier service — stage 1

An HTTP service that researches companies by web domain and keeps a cited six-field
profile (a dossier) for each. Python 3.12, Starlette on uvicorn, state in memory. Every
provider call goes through WebRouter (`webrouter`, module `web_router`) to Nimble.

## Build and start

From this folder:

```sh
docker build -t dossier-stage-1 . && docker run --rm -p 8080:8080 -e PORT=8080 \
  -e NIMBLE_API_KEY -e NIMBLE_BASE_URL dossier-stage-1
```

- `PORT` (default `8080`) is the port the service listens on, on `0.0.0.0`.
- `NIMBLE_API_KEY` is the Nimble credential. It is read from the environment by WebRouter and
  never stored or logged by the service.
- `NIMBLE_BASE_URL` is the Nimble endpoint. Leave it unset for the live endpoint
  (`https://sdk.nimbleway.com`); never set it to an empty string, which breaks every call.
- `TAVILY_API_KEY` / `TAVILY_BASE_URL` may be passed but are not used: the service researches
  with Nimble alone.

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
| `app/build.py`, `app/budget.py` | Background builds: search, extract, conditional research, the 80-unit cap |
| `app/web.py` | The only module that imports `web_router` |
| `app/support.py`, `app/evidence.py` | Appendix A support rules; choosing each field's value and citations |

## Unit tests

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests
```

## Sources

Built from the stage-1 requirements and WebRouter's own documentation and docstrings only.
