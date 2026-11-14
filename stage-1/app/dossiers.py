"""The dossier endpoints (§8).

Each write handler parses and authenticates first, then runs one synchronous critical
section (no ``await``): idempotency lookup, validation, the state change and the stored
response. That makes concurrent requests behave as if run one at a time (§7, §11).
"""
from __future__ import annotations

from starlette.requests import Request

from app import idempotency
from app.auth import authenticate
from app.domains import normalise
from app.errors import not_found
from app.http import json_response, query_int, read_json_object, require_str
from app.store import Dossier

_REFRESH_FINGERPRINT = idempotency.fingerprint({})


def _path_domain(request: Request) -> str:
    return normalise(request.path_params["domain"])


async def create(services, request: Request):
    store, builds, clock = services.store, services.builds, services.clock
    user_id = authenticate(store, request)
    key = idempotency.require_key(request)
    body = await read_json_object(request)
    build_time = clock.now()
    # critical section
    state = store.state
    known = {"domain": body["domain"]} if "domain" in body else {}
    print_ = idempotency.fingerprint(known)
    record = idempotency.record_key(user_id, request, key)
    replayed = idempotency.replay(state, record, print_)
    if replayed is not None:
        return replayed
    domain = normalise(require_str(body, "domain"))
    dossier = state.dossiers.get(domain)
    if dossier is not None:
        return idempotency.remember(state, record, print_, 200, dossier.summary())
    dossier = Dossier(state.new_id("d"), domain)
    state.dossiers[domain] = dossier
    builds.start(dossier, build_time)
    return idempotency.remember(state, record, print_, 202, dossier.summary())


async def refresh(services, request: Request):
    store, builds, clock = services.store, services.builds, services.clock
    user_id = authenticate(store, request)
    key = idempotency.require_key(request)
    build_time = clock.now()
    # critical section; the body is ignored entirely (§7)
    state = store.state
    record = idempotency.record_key(user_id, request, key)
    replayed = idempotency.replay(state, record, _REFRESH_FINGERPRINT)
    if replayed is not None:
        return replayed
    dossier = state.dossiers.get(_path_domain(request))
    if dossier is None:
        raise not_found("no dossier for that domain")
    if dossier.build is None:
        builds.start(dossier, build_time)
    return idempotency.remember(state, record, _REFRESH_FINGERPRINT, 202, dossier.summary())


async def read(services, request: Request):
    authenticate(services.store, request)
    dossier = services.store.state.dossiers.get(_path_domain(request))
    if dossier is None:
        raise not_found("no dossier for that domain")
    return json_response(200, dossier.view())


async def list_(services, request: Request):
    authenticate(services.store, request)
    limit = query_int(request, "limit", 50, 1, 200)
    offset = query_int(request, "offset", 0, 0, None)
    q = request.query_params.get("q", "").casefold()
    matching = []
    for domain in sorted(services.store.state.dossiers):
        dossier = services.store.state.dossiers[domain]
        legal_name = dossier.fields["legal_name"]["value"]
        if q and q not in domain.casefold() and q not in (legal_name or "").casefold():
            continue
        matching.append({**dossier.summary(), "legal_name": legal_name,
                         "researched_at": dossier.researched_at,
                         "spent_units": dossier.live_spent()})
    page = matching[offset:offset + limit]
    return json_response(200, {"dossiers": page, "has_more": offset + limit < len(matching)})
