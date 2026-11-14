"""The eight fields of a dossier: the six of §4, `executives` (stage 3), `investors`
(stage 4)."""
from __future__ import annotations

from app.corroboration import current_keys
from app.executives import EXECUTIVES, decide_executives
from app.investors import decide_investors
from app.selection import Candidate, decide_field
from app.support import FIELDS, INVESTORS

ALL_FIELDS = FIELDS + (EXECUTIVES, INVESTORS)


def decide_one(name: str, candidates: list[Candidate]) -> dict:
    """One field from its candidates, with `origins` and `corroborated`; `learned_at` and
    `corroborated_since` depend on earlier builds and are set at commit (app.commit)."""
    if name == EXECUTIVES:
        field = decide_executives(candidates)
    elif name == INVESTORS:
        field = decide_investors(candidates)
    else:
        field = decide_field(candidates)
    return {**field, **current_keys(name, field), "corroborated_since": None}


def decide(candidates: list[Candidate]) -> dict:
    """All eight fields from a set of candidates."""
    return {name: decide_one(name, [c for c in candidates if c.field == name])
            for name in ALL_FIELDS}


def empty_fields() -> dict:
    return {name: decide_one(name, []) for name in ALL_FIELDS}


def field_candidates(fields: dict) -> list[Candidate]:
    """Every candidate held in a set of decided fields."""
    return [Candidate.from_json(name, c) for name in ALL_FIELDS if name in fields
            for c in fields[name]["candidates"]]
