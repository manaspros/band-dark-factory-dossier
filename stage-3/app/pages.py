"""A page's kind, publication time and `true_from` date, from its header lines (stage-2
"Page kind", stage-3 "Two times per value")."""
from __future__ import annotations

import re
from datetime import date, timezone
from urllib.parse import urlsplit

from app.clock import format_time, parse_rfc3339
from app.domains import is_valid
from app.errors import ApiError
from app.support import header

KINDS = ("own", "filing", "news", "aggregator")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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


def parse_date(raw) -> date | None:
    """A `YYYY-MM-DD` calendar date, or None when ``raw`` is not one."""
    if not isinstance(raw, str) or not _DATE.fullmatch(raw):
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:  # e.g. 2025-02-30
        return None


def utc_date(timestamp: str | None) -> str | None:
    """The date part, in UTC, of an RFC 3339 timestamp (as stored), or None."""
    if timestamp is None:
        return None
    return parse_rfc3339(timestamp).astimezone(timezone.utc).date().isoformat()


def page_true_from(text: str, published: str | None) -> str | None:
    """The page's `Effective:` date when valid, else the UTC date of its publication time,
    else None."""
    effective = parse_date(header(text).get("Effective", "").strip())
    return effective.isoformat() if effective else utc_date(published)
