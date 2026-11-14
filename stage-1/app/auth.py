"""Signup, login and bearer tokens (§6). Passwords are stored as scrypt hashes."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets

from starlette.requests import Request

from app.errors import ApiError, invalid, unauthenticated
from app.http import json_response, read_json_object, require_str
from app.store import Store, User, email_key

_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32, "maxmem": 64 * 1024 * 1024}


def _scrypt(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def hash_password_sync(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${salt.hex()}${_scrypt(password, salt).hex()}"


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(hash_password_sync, password)


def _verify_sync(password: str, encoded: str) -> bool:
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)).hex(), expected)
    except ValueError:
        return False


async def verify_password(password: str, encoded: str) -> bool:
    return await asyncio.to_thread(_verify_sync, password, encoded)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(store: Store, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    store.state.tokens[token_digest(token)] = user_id
    return token


def authenticate(store: Store, request: Request) -> str:
    """The caller's user id from `Authorization: Bearer <token>`, else 401."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme != "Bearer" or not token or token.strip() != token:
        raise unauthenticated()
    user_id = store.state.tokens.get(token_digest(token))
    if user_id is None:
        raise unauthenticated()
    return user_id


def valid_email(email: str) -> bool:
    local, at, domain = email.partition("@")
    return bool(at and local and domain and "@" not in domain
                and not any(c.isspace() for c in email))


def validate_new_user(email: str, password: str, display_name: str) -> None:
    if len(password) < 8:
        raise invalid("password must be at least 8 characters")
    if not valid_email(email):
        raise invalid("email must be of the form local@domain")
    if not 1 <= len(display_name) <= 100:
        raise invalid("display_name must be 1 to 100 characters")


def _email_taken() -> ApiError:
    return ApiError(409, "email_taken", "that email is already registered")


async def signup(store: Store, request: Request):
    body = await read_json_object(request)
    email = require_str(body, "email")
    password = require_str(body, "password")
    display_name = require_str(body, "display_name")
    validate_new_user(email, password, display_name)
    if email_key(email) in store.state.emails:
        raise _email_taken()
    password_hash = await hash_password(password)
    state = store.state  # critical section: no await from here on
    if email_key(email) in state.emails:
        raise _email_taken()
    user = User(state.new_id("u"), email, display_name, password_hash)
    state.add_user(user)
    token = issue_token(store, user.id)
    return json_response(201, {"user_id": user.id, "display_name": display_name, "token": token})


async def login(store: Store, request: Request):
    body = await read_json_object(request)
    email = require_str(body, "email")
    password = require_str(body, "password")
    user = store.state.users.get(store.state.emails.get(email_key(email), ""))
    if user is None or not await verify_password(password, user.password_hash):
        raise unauthenticated()
    if store.state.users.get(user.id) is not user:  # state replaced while hashing
        raise unauthenticated()
    token = issue_token(store, user.id)
    return json_response(200, {"user_id": user.id, "display_name": user.display_name,
                               "token": token})
