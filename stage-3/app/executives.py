"""The seventh field, `executives` (stage-3 "Executives").

Each title (cfo, coo, cto) is selected separately by the stage-2 selection rule; the field's
value lists one member per title that has a selected person, in title order.
"""
from __future__ import annotations

from app.selection import Candidate, citation, rank, unknown_field, value_key
from app.support import TITLES

EXECUTIVES = "executives"


def decide_executives(candidates: list[Candidate]) -> dict:
    """The executives field from its candidates (each with a ``title``)."""
    members, true_froms, citations, listed, contested = [], [], [], [], False
    for title in TITLES:
        ranked = rank([c for c in candidates if c.title == title])
        if not ranked:
            continue
        selected = ranked[0]
        chosen = value_key(selected.value)
        members.append({"title": title, "name": selected.value})
        true_froms.append(selected.true_from)
        citations += [citation(c) for c in ranked if value_key(c.value) == chosen]
        contested = contested or len({value_key(c.value) for c in ranked}) > 1
        listed += [c.as_json(selected=(i == 0)) for i, c in enumerate(ranked)]
    if not members:
        return unknown_field()
    return {
        "value": members,
        "status": "contested" if contested else "known",
        "true_from": None if None in true_froms else max(true_froms),
        "learned_at": None,
        "citations": citations,
        "candidates": listed,
    }


def member_true_froms(field: dict) -> dict[str, str | None]:
    """{title: true_from of that title's selected candidate} for an executives field."""
    return {c["title"]: c["true_from"] for c in field["candidates"] if c["selected"]}
