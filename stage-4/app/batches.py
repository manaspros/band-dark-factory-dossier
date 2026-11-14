"""`POST /batches` and `GET /batches/{id}` (stage-4 "Batches").

A batch starts the first build of every listed domain that has no dossier yet, under one
shared budget (app.budget.BatchBudget). Each of its builds may spend at most its share of
that budget (``budget_units`` over the new domains, and never more than 80), so the first
builds cannot starve the later ones. Like the other two write paths it is idempotent (§7):
authentication, the key, the body, a replay check, then validation and one synchronous
section that writes everything in one transaction.
"""
from __future__ import annotations

from starlette.requests import Request

from app import idempotency
from app.auth import authenticate
from app.budget import BUILD_CAP_UNITS, BatchBudget
from app.domains import normalise
from app.errors import invalid, malformed, not_found
from app.http import json_response, read_json_object
from app.store import Batch, Dossier
from app.transfer import MAX_BATCH_BUDGET, MAX_BATCH_DOMAINS

_KNOWN = ("domains", "budget_units")


def _domains(body: dict) -> list[str]:
    """The normalised domains: 422 when missing, empty, over 50, invalid or repeated; 400
    when not a list of strings (lead ruling D4-9)."""
    if "domains" not in body:
        raise invalid("domains is required")
    raw = body["domains"]
    if not isinstance(raw, list):
        raise malformed("domains must be an array of strings")
    if not 1 <= len(raw) <= MAX_BATCH_DOMAINS:
        raise invalid(f"domains must have 1 to {MAX_BATCH_DOMAINS} entries")
    if not all(isinstance(entry, str) for entry in raw):
        raise malformed("domains must be an array of strings")
    domains = [normalise(entry) for entry in raw]
    if len(set(domains)) != len(domains):
        raise invalid("domains must be distinct after normalisation")
    return domains


def _budget_units(body: dict) -> int:
    """An integer from 1 to 100000; anything else, of any JSON type, is 422."""
    value = body.get("budget_units")
    if not (isinstance(value, int) and not isinstance(value, bool)
            and 1 <= value <= MAX_BATCH_BUDGET):
        raise invalid(f"budget_units must be an integer from 1 to {MAX_BATCH_BUDGET}")
    return value


async def create(services, request: Request):
    store, builds, clock = services.store, services.builds, services.clock
    user_id = authenticate(store, request)
    key = idempotency.require_key(request)
    body = await read_json_object(request)
    build_time = clock.now()
    # critical section
    state = store.state
    print_ = idempotency.fingerprint({k: body[k] for k in _KNOWN if k in body})
    record = idempotency.record_key(user_id, request, key)
    replayed = idempotency.replay(state, record, print_)
    if replayed is not None:
        return replayed
    domains = _domains(body)
    budget_units = _budget_units(body)
    new = [d for d in domains if d not in state.dossiers]
    share = min(BUILD_CAP_UNITS, max(1, budget_units // len(new))) if new else 0
    batch = Batch(state.new_id("b"), user_id, budget_units, domains, list(new))
    batch.budget = BatchBudget(budget_units)
    with store.transaction() as writer:
        for domain in new:
            dossier = Dossier(state.new_id("d"), domain)
            writer.put_dossier(dossier)
            state.dossiers[domain] = dossier
            builds.start(dossier, build_time, writer, batch, cap=share)
        writer.put_batch(batch)
        state.batches[batch.id] = batch
        return idempotency.remember(state, writer, record, print_, 202, batch.view(state))


async def read(services, request: Request):
    user_id = authenticate(services.store, request)
    batch = services.store.state.batches.get(request.path_params["batch_id"])
    if batch is None or batch.user_id != user_id:
        raise not_found("no such batch")
    return json_response(200, batch.view(services.store.state))
