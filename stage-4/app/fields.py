"""The seven fields of a dossier: the six of §4, then `executives` (stage 3)."""
from __future__ import annotations

from app.executives import EXECUTIVES, decide_executives
from app.selection import Candidate, decide_field, unknown_field
from app.support import FIELDS

ALL_FIELDS = FIELDS + (EXECUTIVES,)


def decide(candidates: list[Candidate]) -> dict:
    """All seven fields from a set of candidates (``learned_at`` still unset)."""
    fields = {f: decide_field([c for c in candidates if c.field == f]) for f in FIELDS}
    fields[EXECUTIVES] = decide_executives([c for c in candidates if c.field == EXECUTIVES])
    return fields


def empty_fields() -> dict:
    return {field: unknown_field() for field in ALL_FIELDS}


def field_candidates(fields: dict) -> list[Candidate]:
    """Every candidate held in a set of decided fields."""
    return [Candidate.from_json(name, c) for name in ALL_FIELDS if name in fields
            for c in fields[name]["candidates"]]
