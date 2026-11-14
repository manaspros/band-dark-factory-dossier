"""Independent origins behind a field's value (stage-4 "Origins"): `origins`, `corroborated`
and `corroborated_since`.

A field's **members** are what its value is made of: the selected value for the six fields of
§4, each `{title, name}` for executives, each name for investors. A member's candidates are
the field's candidates with that value (and title).
"""
from __future__ import annotations

from app.executives import EXECUTIVES
from app.selection import value_key
from app.support import INVESTORS


def member_keys(name: str, field: dict) -> list[tuple]:
    """The keys of the field's current members."""
    value = field["value"]
    if value is None:
        return []
    if name == EXECUTIVES:
        return [(m["title"], value_key(m["name"])) for m in value]
    if name == INVESTORS:
        return [(None, value_key(n)) for n in value]
    return [(None, value_key(value))]


def _candidate_key(name: str, candidate: dict) -> tuple:
    return (candidate.get("title") if name == EXECUTIVES else None,
            value_key(candidate["value"]))


def member_origins(name: str, field: dict) -> dict[tuple, set[str]]:
    """{member key: origins of the field's candidates of that member}."""
    keys = member_keys(name, field)
    origins: dict[tuple, set[str]] = {key: set() for key in keys}
    for candidate in field["candidates"]:
        key = _candidate_key(name, candidate)
        if key in origins and candidate.get("origin"):
            origins[key].add(candidate["origin"])
    return origins


def current_keys(name: str, field: dict) -> dict:
    """`origins` and `corroborated` of a decided field, from its candidates."""
    per_member = member_origins(name, field)
    origins = sorted(set().union(*per_member.values())) if per_member else []
    if name in (EXECUTIVES, INVESTORS):
        corroborated = bool(per_member) and all(len(o) >= 2 for o in per_member.values())
    else:
        corroborated = len(origins) >= 2
    return {"origins": origins, "corroborated": corroborated}


def corroborated_since(name: str, snapshots: list[tuple[str, dict]]) -> str | None:
    """The time of the earliest ready build after which every current member has had two or
    more standing origins, or None.

    ``snapshots`` are (build time, the field as that ready build decided it), in build order;
    the last is the current field. A member's standing origins accumulate from the last
    build at which it became a member (it was not one in the build before), whatever later
    builds gather.
    """
    current = snapshots[-1][1]
    keys = member_keys(name, current)
    if not keys:
        return None
    reached = []
    for key in keys:
        start = len(snapshots) - 1
        while start > 0 and key in member_keys(name, snapshots[start - 1][1]):
            start -= 1
        standing: set[str] = set()
        reach = None
        for index in range(start, len(snapshots)):
            for candidate in snapshots[index][1]["candidates"]:
                if _candidate_key(name, candidate) == key and candidate.get("origin"):
                    standing.add(candidate["origin"])
            if len(standing) >= 2:
                reach = index
                break
        if reach is None:
            return None
        reached.append(reach)
    return snapshots[max(reached)][0]
