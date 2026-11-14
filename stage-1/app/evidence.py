"""Turn supported (field, value, excerpt) candidates into the six dossier fields (§4).

A field is ``known`` exactly when some candidate supports a value for it. When the
evidence supports several values, the field holds one of them and cites only the
excerpts that support that value:

- ``hq_city`` first prefers a value that some supporting excerpt follows with a comma
  (``based in Lisbon, Portugal``), then the shorter value (lead ruling L3, plan D32);
- then every field prefers the value with the most distinct supporting URLs, then the
  value gathered first, then the smallest JSON encoding (plan D7).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from app.support import FIELDS


@dataclass(frozen=True)
class Candidate:
    """One excerpt a provider served for ``url`` that supports ``value`` for ``field``.

    ``order`` is the gathering order: lower means gathered earlier.
    """
    field: str
    value: object
    url: str
    excerpt: str
    provider: str
    order: int


def unknown_field() -> dict:
    return {"value": None, "status": "unknown", "citations": []}


def empty_fields() -> dict:
    return {field: unknown_field() for field in FIELDS}


def _key(value: object) -> str:
    return json.dumps(value, sort_keys=True)


def _comma_after(candidate: Candidate) -> bool:
    return f"{candidate.value}," in candidate.excerpt


def _choose(field: str, by_value: dict[str, list[Candidate]]) -> str:
    def rank(key: str):
        group = by_value[key]
        urls = {c.url for c in group}
        first = min(c.order for c in group)
        city_rank = ()
        if field == "hq_city":
            city_rank = (not any(_comma_after(c) for c in group), len(str(group[0].value)))
        return (*city_rank, -len(urls), first, key)

    return min(by_value, key=rank)


def _citations(field: str, group: list[Candidate]) -> list[dict]:
    ordered = sorted(group, key=lambda c: c.order)
    if field == "hq_city":
        ordered.sort(key=lambda c: not _comma_after(c))  # stable: comma excerpts first
    seen, citations = set(), []
    for c in ordered:
        if (c.url, c.excerpt) in seen:
            continue
        seen.add((c.url, c.excerpt))
        citations.append({"url": c.url, "excerpt": c.excerpt, "provider": c.provider})
    return citations


def decide(candidates: list[Candidate]) -> dict:
    """All six fields, each ``{"value", "status", "citations"}``."""
    fields = empty_fields()
    for field in FIELDS:
        by_value: dict[str, list[Candidate]] = {}
        for c in candidates:
            if c.field == field:
                by_value.setdefault(_key(c.value), []).append(c)
        if not by_value:
            continue
        group = by_value[_choose(field, by_value)]
        fields[field] = {"value": group[0].value, "status": "known",
                         "citations": _citations(field, group)}
    return fields
