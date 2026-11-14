"""The eighth field, `investors` (stage-4 "Investors").

An investor name is a member when one of its candidates is from an `own` or `filing` page,
or its candidates have two or more distinct origins. The value is the members' names in
code-point order; there is no single selected value and the field is never `contested`.
"""
from __future__ import annotations

from app.selection import Candidate, citation, rank, unknown_field, value_key
from app.support import INVESTORS

MEMBER_KINDS = ("own", "filing")


def _by_name(ranked: list[Candidate]) -> dict[str, list[Candidate]]:
    groups: dict[str, list[Candidate]] = {}
    for c in ranked:
        groups.setdefault(value_key(c.value), []).append(c)
    return groups


def is_member(candidates: list[Candidate]) -> bool:
    """Whether the candidates of one name make it a member."""
    return (any(c.kind in MEMBER_KINDS for c in candidates)
            or len({c.origin for c in candidates}) >= 2)


def member_true_from(candidates: list[Candidate]) -> str | None:
    """The earliest true_from among one name's candidates that is not null."""
    dates = [c.true_from for c in candidates if c.true_from is not None]
    return min(dates) if dates else None


def decide_investors(candidates: list[Candidate]) -> dict:
    """The investors field from its candidates (``learned_at`` is set at commit)."""
    ranked = rank(candidates)
    groups = _by_name(ranked)
    members = sorted((group[0].value for group in groups.values() if is_member(group)))
    member_keys = {value_key(name) for name in members}
    listed = [c.as_json(selected=value_key(c.value) in member_keys) for c in ranked]
    if not members:
        return {**unknown_field(), "candidates": listed}
    dates = [member_true_from(groups[value_key(name)]) for name in members]
    return {
        "value": members,
        "status": "known",
        "true_from": None if None in dates else max(dates),
        "learned_at": None,
        "citations": [citation(c) for name in members for c in groups[value_key(name)]],
        "candidates": listed,
    }


def name_true_froms(field: dict) -> dict[str, str | None]:
    """{name: member true_from} for each member of an investors field (from its JSON)."""
    groups: dict[str, list[Candidate]] = {}
    for c in field["candidates"]:
        groups.setdefault(value_key(c["value"]), []).append(Candidate.from_json(INVESTORS, c))
    return {name: member_true_from(groups.get(value_key(name), []))
            for name in field["value"] or []}
