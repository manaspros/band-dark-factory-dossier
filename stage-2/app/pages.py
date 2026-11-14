"""A page's kind and publication time, from its header lines (stage-2 "Page kind")."""
from __future__ import annotations

from urllib.parse import urlsplit

from app.clock import format_time, parse_rfc3339
from app.domains import is_valid
from app.errors import ApiError
from app.support import header

KINDS = ("own", "filing", "news", "aggregator")


def _host_domain(url: str) -> str | None:
    """The URL's host, normalised as a domain is (lowercase, one `www.` dropped)."""
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return None
    host = host.strip().lower().removesuffix(".")
    host = host.removeprefix("www.")
    return host if is_valid(host) else None


def page_kind(url: str, text: str, domain: str) -> str:
    """`Kind:` when it names a listed kind, else own for the company's host, else aggregator."""
    kind = header(text).get("Kind", "").strip()
    if kind in KINDS:
        return kind
    return "own" if _host_domain(url) == domain else "aggregator"


def published_at(text: str) -> str | None:
    """The `Published:` time as RFC 3339 (its own offset kept), or None when absent or invalid."""
    raw = header(text).get("Published")
    if raw is None:
        return None
    try:
        return format_time(parse_rfc3339(raw.strip()))
    except ApiError:
        return None
