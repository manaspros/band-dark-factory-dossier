"""The selection rule and status (stage-2 "The selection rule", "Status").

A field's candidates are ranked by authority of the page's kind, then recency, then URL
and provider, then value. The top candidate is selected; the field's value, status and
citations follow from the ranked candidates alone, so the same candidates always yield the
same field whatever order they arrive in.

Stage 3: candidates also carry ``true_from`` (the page's date, app.pages) and
``learned_at`` (the first build that gathered them, stamped at commit, app.history), and a
candidate of ``executives`` carries its ``title`` (app.executives ranks each title apart).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

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
    true_from: str | None = None    # YYYY-MM-DD, or None
    learned_at: str | None = None   # time of the first build that gathered it
    title: str | None = None        # cfo/coo/cto for an executives candidate, else None
    origin: str | None = None       # the origin of its page (stage 4, app.origins)

    def as_json(self, selected: bool) -> dict:
        head = {"title": self.title} if self.title is not None else {}
        return {**head, "value": self.value, "url": self.url, "excerpt": self.excerpt,
                "provider": self.provider, "kind": self.kind, "origin": self.origin,
                "published_at": self.published_at, "retrieved_at": self.retrieved_at,
                "true_from": self.true_from, "learned_at": self.learned_at,
                "selected": selected}

    @classmethod
    def from_json(cls, field: str, data: dict) -> "Candidate":
        """A candidate of ``field`` from its JSON (stage-2 JSON has no times or title)."""
        return cls(field, data["value"], data["url"], data["excerpt"], data["provider"],
                   data["kind"], data["published_at"], data["retrieved_at"],
                   data.get("true_from"), data.get("learned_at"), data.get("title"),
                   data.get("origin"))

    def identity(self) -> tuple:
        """Same field (and title), value, URL and provider: the `learned_at` key."""
        return (self.field, self.title, value_key(self.value), self.url, self.provider)


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
    return {"value": None, "status": "unknown", "true_from": None, "learned_at": None,
            "citations": [], "candidates": []}


def citation(candidate: Candidate) -> dict:
    return {"url": candidate.url, "excerpt": candidate.excerpt, "provider": candidate.provider}


def decide_field(candidates: list[Candidate]) -> dict:
    """``{value, status, true_from, learned_at, citations, candidates}`` for one of the six
    fields. ``learned_at`` depends on earlier builds and is set at commit (app.history)."""
    if not candidates:
        return unknown_field()
    ranked = rank(candidates)
    selected = ranked[0]
    chosen = value_key(selected.value)
    distinct = {value_key(c.value) for c in ranked}
    return {
        "value": selected.value,
        "status": "known" if len(distinct) == 1 else "contested",
        "true_from": selected.true_from,
        "learned_at": None,
        "citations": [citation(c) for c in ranked if value_key(c.value) == chosen],
        "candidates": [c.as_json(selected=(i == 0)) for i, c in enumerate(ranked)],
    }
