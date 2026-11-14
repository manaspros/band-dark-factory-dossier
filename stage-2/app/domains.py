"""Domain normalisation and validation (§4 Domains)."""
from __future__ import annotations

import string

from app.errors import invalid

_LABEL_CHARS = frozenset(string.ascii_lowercase + string.digits + "-")


def normalise(raw: str) -> str:
    """Strip, lowercase, drop one trailing `.` and one leading `www.`, then validate."""
    domain = raw.strip().lower()
    if domain.endswith("."):
        domain = domain[:-1]
    if domain.startswith("www."):
        domain = domain[4:]
    if not is_valid(domain):
        raise invalid("domain is not a valid host name")
    return domain


def is_valid(domain: str) -> bool:
    if len(domain) > 253:
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    return all(1 <= len(label) <= 63 and set(label) <= _LABEL_CHARS
               and not label.startswith("-") and not label.endswith("-") for label in labels)
