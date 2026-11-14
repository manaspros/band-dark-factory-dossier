"""Idempotency keys for the two write paths (§7).

A record is keyed by (user, method, raw path, key) and remembers the fingerprint of the
request body and the original 2xx response. Requests that failed with 4xx are not
remembered, so their keys stay free.
"""
from __future__ import annotations

import json

from starlette.requests import Request

from app.errors import ApiError, invalid
from app.http import json_response
from app.store import IdempotencyRecord, State

MAX_KEY_CHARS = 255


def require_key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise ApiError(400, "missing_idempotency_key", "an Idempotency-Key header is required")
    if len(key) > MAX_KEY_CHARS:
        raise invalid("Idempotency-Key must be 1 to 255 characters")
    return key


def fingerprint(known_fields: dict) -> str:
    """Canonical JSON of the body's known fields: key order and whitespace do not matter."""
    return json.dumps(known_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_key(user_id: str, request: Request, key: str) -> tuple:
    raw_path = request.scope.get("raw_path") or request.url.path.encode("utf-8")
    return (user_id, request.method, raw_path.decode("latin-1"), key)


def replay(state: State, record_key: tuple, print_: str):
    """The stored response for a replay, 409 for a different body, None for a first use."""
    record = state.idempotency.get(record_key)
    if record is None:
        return None
    if record.fingerprint != print_:
        raise ApiError(409, "idempotency_key_reuse",
                       "this Idempotency-Key was already used with a different request")
    return json_response(200, record.body)


def remember(state: State, writer, record_key: tuple, print_: str, status: int, body: dict):
    """Store a successful response (with ``writer``, an open transaction) and return it."""
    record = IdempotencyRecord(print_, status, body)
    writer.put_idempotency(record_key, record)
    state.idempotency[record_key] = record
    return json_response(status, body)
