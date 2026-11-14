"""A page's kind, publication time, `true_from` date and lineage, from its header lines
(stage-2 "Page kind", stage-3 "Two times per value", stage-4 "Lineage header lines" and
"Own pages")."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timezone
from urllib.parse import urlsplit

from app.clock import format_time, parse_rfc3339
from app.domains import is_valid, normalise
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


def _domain_line(raw: str | None) -> str | None:
    """A header line's domain, normalised as §4, or None when absent or invalid (D4-1)."""
    if raw is None:
        return None
    try:
        return normalise(raw)
    except ApiError:
        return None


def _canonical_line(raw: str | None) -> str | None:
    """A `Canonical:` URL with an http(s) scheme and a valid host, as written, else None."""
    if raw is None:
        return None
    url = raw.strip()
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return None
    return url if scheme in ("http", "https") and _host_domain(url) else None


@dataclass(frozen=True)
class Lineage:
    """What a page's header says about who publishes it (stage-4 lineage lines)."""
    url: str                         # the page's own URL (as the provider served it)
    registrant: str | None           # `Registrant`, else the host of ``url``
    canonical: str | None            # `Canonical` URL, when valid
    first_published_by: str | None   # `First-Published-By` domain, when valid
    states_own: bool                 # the header states `Kind: own`

    @property
    def lookalike(self) -> bool:
        """States `Kind: own` while registered to another host than its own."""
        return self.states_own and self.registrant != _host_domain(self.url)


def lineage(url: str, text: str) -> Lineage:
    lines = header(text)
    registrant = _domain_line(lines.get("Registrant")) or _host_domain(url)
    return Lineage(url, registrant, _canonical_line(lines.get("Canonical")),
                   _domain_line(lines.get("First-Published-By")),
                   lines.get("Kind", "").strip() == "own")


def page_kind(url: str, text: str, domain: str) -> str:
    """`Kind:` when it names a listed kind, else own for the company's host, else
    aggregator; and `own` only when the page's registrant is the company's domain."""
    kind = header(text).get("Kind", "").strip()
    if kind not in KINDS:
        kind = "own" if _host_domain(url) == domain else "aggregator"
    if kind == "own" and lineage(url, text).registrant != domain:
        kind = "aggregator"
    return kind


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
