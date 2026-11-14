"""Request parsing and JSON responses shared by every handler (§3.5, §5)."""
from __future__ import annotations

import json
import re

from starlette.requests import Request
from starlette.responses import Response

from app.errors import ApiError, invalid, malformed

_DIGITS = re.compile(r"[0-9]+")
_ABSENT = object()


def json_response(status: int, payload) -> Response:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Response(body, status_code=status, media_type="application/json; charset=utf-8")


def error_response(error: ApiError) -> Response:
    return json_response(error.status, error.body())


def no_content() -> Response:
    return Response(status_code=204)


async def read_json(request: Request):
    """The parsed body, or 400 ``malformed_request`` when it does not parse."""
    raw = await request.body()
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise malformed("the request body is not valid JSON") from None


async def read_json_object(request: Request) -> dict:
    body = await read_json(request)
    if not isinstance(body, dict):
        raise malformed("the request body must be a JSON object")
    return body


def require_str(body: dict, name: str) -> str:
    """A required string field: 422 when missing, 400 when of another JSON type."""
    value = body.get(name, _ABSENT)
    if value is _ABSENT:
        raise invalid(f"{name} is required")
    if not isinstance(value, str):
        raise malformed(f"{name} must be a string")
    return value


def query_int(request: Request, name: str, default: int, low: int, high: int | None) -> int:
    """An integer query parameter written as plain decimal digits, within [low, high]."""
    raw = request.query_params.get(name)
    if raw is None:
        return default
    if not _DIGITS.fullmatch(raw):
        raise invalid(f"{name} must be written as decimal digits")
    value = int(raw)
    if value < low or (high is not None and value > high):
        raise invalid(f"{name} is out of range")
    return value
