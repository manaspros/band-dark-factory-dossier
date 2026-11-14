"""Unauthenticated control endpoints: health, reset, clock, export, import (§3, §10)."""
from __future__ import annotations

import asyncio

from starlette.requests import Request

from app.auth import hash_password
from app.clock import parse_rfc3339
from app.errors import invalid, malformed
from app.http import json_response, no_content, read_json, read_json_object
from app.store import FORMAT_VERSION, TRACK, State, User, email_key, export_state, import_state


async def health(services, request: Request):
    return json_response(200, {"status": "ok"})


def _fixture_users(body: dict) -> list[dict]:
    users = body.get("users", [])
    if not isinstance(users, list):
        raise malformed("users must be a list")
    ids, emails = set(), set()
    for user in users:
        if not isinstance(user, dict):
            raise malformed("each user must be an object")
        for name in ("id", "email", "password", "display_name"):
            if name not in user:
                raise invalid(f"user {name} is required")
            if not isinstance(user[name], str):
                raise malformed(f"user {name} must be a string")
        if not 1 <= len(user["id"]) <= 64:
            raise invalid("user id must be 1 to 64 characters")
        if user["id"] in ids or email_key(user["email"]) in emails:
            raise invalid("fixture users must have distinct ids and emails")
        ids.add(user["id"])
        emails.add(email_key(user["email"]))
    return users


async def reset(services, request: Request):
    body = await read_json_object(request)
    if "now" not in body:
        raise invalid("now is required")
    now = parse_rfc3339(body["now"])
    users = _fixture_users(body)
    hashes = await asyncio.gather(*(hash_password(u["password"]) for u in users))
    state = State()  # critical section: swap state and set the clock together
    for user, password_hash in zip(users, hashes):
        state.add_user(User(user["id"], user["email"], user["display_name"], password_hash))
    services.store.replace(state)
    services.clock.reset_to(now)
    return no_content()


async def set_clock(services, request: Request):
    body = await read_json_object(request)
    if "now" not in body:
        raise invalid("now is required")
    services.clock.set(parse_rfc3339(body["now"]))
    return no_content()


async def export(services, request: Request):
    return json_response(200, {"track": TRACK, "format_version": FORMAT_VERSION,
                               "state": export_state(services.store.state)})


async def import_(services, request: Request):
    payload = await read_json(request)
    services.store.replace(import_state(payload))
    return no_content()
