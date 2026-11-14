"""The selection rule and status (stage-2 "The selection rule", "Status").

A field's candidates are ranked by authority of the page's kind, then recency, then URL
and provider, then value. The top candidate is selected; the field's value, status and
citations follow from the ranked candidates alone, so the same candidates always yield the
same field whatever order they arrive in.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from app.support import FIELDS

AUTHORITY = {"own": 3, "filing": 3, "news": 2, "aggregator": 1, None: 1}
PROVIDER_ORDER = ("nimble", "tavily", "kernel", "browserbase")


@dataclass(frozen=True)
class Candidate:
    """One value for one field, supported by one excerpt of one page."""
    field: str
    value: object
    url: str
    excerpt: str
    provider: str
    kind: str | None
    published_at: str | None   # RFC 3339, or None
    retrieved_at: str | None   # the build's time, RFC 3339

    def as_json(self, selected: bool) -> dict:
        return {"value": self.value, "url": self.url, "excerpt": self.excerpt,
                "provider": self.provider, "kind": self.kind,
                "published_at": self.published_at, "retrieved_at": self.retrieved_at,
                "selected": selected}

    @classmethod
    def from_json(cls, field: str, data: dict) -> "Candidate":
        return cls(field, data["value"], data["url"], data["excerpt"], data["provider"],
                   data["kind"], data["published_at"], data["retrieved_at"])


def normalised_value(value):
    """Values are the same when equal as JSON values, strings compared after stripping."""
    return value.strip() if isinstance(value, str) else value


def value_key(value) -> str:
    return json.dumps(normalised_value(value), sort_keys=True)


def _instant(published_at: str | None) -> float | None:
    if published_at is None:
        return None
    try:
        return datetime.fromisoformat(published_at).timestamp()
    except ValueError:
        return None


def _provider_rank(provider: str) -> int:
    return PROVIDER_ORDER.index(provider) if provider in PROVIDER_ORDER else len(PROVIDER_ORDER)


def rank_key(candidate: Candidate) -> tuple:
    """Sort key: smaller sorts first, i.e. ranks higher."""
    instant = _instant(candidate.published_at)
    value = normalised_value(candidate.value)
    return (-AUTHORITY.get(candidate.kind, 1),
            (0, -instant) if instant is not None else (1, 0.0),
            candidate.url,
            _provider_rank(candidate.provider),
            (0, value, "") if isinstance(value, int) else (1, 0, str(value)))


def rank(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=rank_key)


def unknown_field() -> dict:
    return {"value": None, "status": "unknown", "citations": [], "candidates": []}


def decide_field(candidates: list[Candidate]) -> dict:
    """``{value, status, citations, candidates}`` for one field's candidates."""
    if not candidates:
        return unknown_field()
    ranked = rank(candidates)
    selected = ranked[0]
    chosen = value_key(selected.value)
    distinct = {value_key(c.value) for c in ranked}
    return {
        "value": selected.value,
        "status": "known" if len(distinct) == 1 else "contested",
        "citations": [{"url": c.url, "excerpt": c.excerpt, "provider": c.provider}
                      for c in ranked if value_key(c.value) == chosen],
        "candidates": [c.as_json(selected=(i == 0)) for i, c in enumerate(ranked)],
    }


def decide(candidates: list[Candidate]) -> dict:
    """All six fields from a build's (or an import's) candidates."""
    return {field: decide_field([c for c in candidates if c.field == field]) for field in FIELDS}


def empty_fields() -> dict:
    return {field: unknown_field() for field in FIELDS}
