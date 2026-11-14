"""The dossier endpoints (§8).

Each write handler parses and authenticates first, then runs one synchronous critical
section (no ``await``): idempotency lookup, validation, the state change and the stored
response. That makes concurrent requests behave as if run one at a time (§7, §11).
"""
from __future__ import annotations

from starlette.requests import Request

from app import idempotency, timeline
from app.auth import authenticate
from app.clock import format_time, parse_rfc3339
from app.domains import normalise
from app.errors import invalid, not_found
from app.fields import ALL_FIELDS
from app.http import json_response, query_int, query_text, read_json_object, require_str
from app.pages import parse_date
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
    with store.transaction() as writer:
        if dossier is not None:
            return idempotency.remember(state, writer, record, print_, 200, dossier.summary())
        dossier = Dossier(state.new_id("d"), domain)
        writer.put_dossier(dossier)
        state.dossiers[domain] = dossier
        builds.start(dossier, build_time, writer)
        return idempotency.remember(state, writer, record, print_, 202, dossier.summary())


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
    with store.transaction() as writer:
        if dossier.build is None:
            builds.start(dossier, build_time, writer)
        return idempotency.remember(state, writer, record, _REFRESH_FINGERPRINT, 202,
                                    dossier.summary())


def _as_of(request: Request):
    """The `as_of` query parameter as (text, instant), or None when absent; 422 when it is
    not an RFC 3339 timestamp with an explicit offset."""
    raw = query_text(request, "as_of")
    return None if raw is None else (raw, parse_rfc3339(raw))


def _dossier(services, domain: str) -> Dossier:
    dossier = services.store.state.dossiers.get(domain)
    if dossier is None:
        raise not_found("no dossier for that domain")
    return dossier


async def read(services, request: Request):
    """The dossier now, or as this service had it at `?as_of=` (stage 3)."""
    authenticate(services.store, request)
    domain = _path_domain(request)
    as_of = _as_of(request)
    dossier = _dossier(services, domain)
    if as_of is None:
        return json_response(200, dossier.view())
    view = timeline.snapshot(dossier, as_of[1])
    if view is None:
        raise not_found("no build of this dossier was ready at that time")
    return json_response(200, view)


async def values(services, request: Request):
    """`GET /dossiers/{domain}/values?true_at=&as_of=` (stage 3)."""
    authenticate(services.store, request)
    domain = _path_domain(request)
    raw_true_at = query_text(request, "true_at")
    true_at = parse_date(raw_true_at)
    if true_at is None:
        raise invalid("true_at must be a YYYY-MM-DD date")
    as_of = _as_of(request)
    if as_of is None:
        now = services.clock.now()
        as_of = (format_time(now), now)
    dossier = _dossier(services, domain)
    fields = timeline.values(dossier, true_at, as_of[1])
    if fields is None:
        raise not_found("no build of this dossier was ready at that time")
    return json_response(200, {"domain": dossier.domain, "true_at": raw_true_at,
                               "as_of": as_of[0], "fields": fields})


async def history(services, request: Request):
    """`GET /dossiers/{domain}/history`: every field's entries, oldest first (stage 3)."""
    authenticate(services.store, request)
    dossier = _dossier(services, _path_domain(request))
    return json_response(200, {"domain": dossier.domain,
                               "fields": {name: dossier.history[name] for name in ALL_FIELDS}})


async def changes(services, request: Request):
    """`GET /changes?since=&limit=`: the change feed by `seq` (stage 3)."""
    authenticate(services.store, request)
    since = query_int(request, "since", 0, 0, None)
    limit = query_int(request, "limit", 50, 1, 200)
    later = [entry for entry in services.store.state.feed if entry["seq"] > since]
    return json_response(200, {"changes": later[:limit], "has_more": len(later) > limit})


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
