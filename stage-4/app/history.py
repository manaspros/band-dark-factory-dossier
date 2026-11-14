"""The two times of values and the entries a ready build adds (stage-3 "Two times per value",
"Changes and corrections", "Executives").

Pure functions: the build commit (app.store) calls them inside its one transaction.
"""
from __future__ import annotations

from dataclasses import replace

from app.corroboration import corroborated_since
from app.executives import EXECUTIVES, member_true_froms
from app.fields import ALL_FIELDS, field_candidates
from app.investors import name_true_froms
from app.selection import Candidate, value_key
from app.support import INVESTORS


# --------------------------------------------------------------------------- learned_at

def first_seen(ready_fields: list[dict]) -> dict[tuple, str]:
    """{candidate identity: learned_at} over the field snapshots of ready builds, oldest
    build first: the time each (field, title, value, URL, provider) was first gathered."""
    seen: dict[tuple, str] = {}
    for fields in ready_fields:
        for candidate in field_candidates(fields):
            seen.setdefault(candidate.identity(), candidate.learned_at)
    return seen


def stamp_candidates(candidates: list[Candidate], seen: dict[tuple, str],
                     build_time: str) -> list[Candidate]:
    """Each candidate with its `learned_at`: the first build that gathered it, else this one."""
    return [replace(c, learned_at=seen.get(c.identity(), build_time)) for c in candidates]


def stamp_fields(new_fields: dict, previous_fields: dict, build_time: str) -> dict:
    """Each field's `learned_at`: unchanged while its selected value stays the same, the
    build's time when the build made a new value selected, null when unknown."""
    stamped = {}
    for name in ALL_FIELDS:
        new, old = new_fields[name], previous_fields[name]
        if new["value"] is None:
            learned_at = None
        elif same_value(old["value"], new["value"]) and old["learned_at"] is not None:
            learned_at = old["learned_at"]
        else:
            learned_at = build_time
        stamped[name] = {**new, "learned_at": learned_at}
    return stamped


# --------------------------------------------------------------------------- entries

def same_value(a, b) -> bool:
    return value_key(a) == value_key(b)


def _is_correction(old_value, old_true_from, new_value, new_true_from) -> bool:
    return (old_value is not None and new_value is not None
            and old_true_from is not None and new_true_from is not None
            and new_true_from <= old_true_from)


def _investors_type(old: dict, new: dict) -> str:
    """Typed by name: `correction` when no name was removed and every added name's
    true_from is on or before the earlier value's (stage-4 "Investors")."""
    old_names = {value_key(n) for n in old["value"] or []}
    new_names = {value_key(n): n for n in new["value"] or []}
    if old_names - new_names.keys():
        return "change"
    dates = name_true_froms(new)
    added = [n for key, n in new_names.items() if key not in old_names]
    return ("correction" if all(_is_correction(old["value"], old["true_from"], n, dates[n])
                                for n in added) else "change")


def entry_type(name: str, old: dict, new: dict) -> str:
    """`correction` or `change` for a field whose selected value differs."""
    if name == INVESTORS:
        return _investors_type(old, new)
    if name != EXECUTIVES:
        return ("correction" if _is_correction(old["value"], old["true_from"],
                                               new["value"], new["true_from"]) else "change")
    old_names = {m["title"]: m["name"] for m in old["value"] or []}
    new_names = {m["title"]: m["name"] for m in new["value"] or []}
    old_dates, new_dates = member_true_froms(old), member_true_froms(new)
    differing = [t for t in old_names.keys() | new_names.keys()
                 if not same_value(old_names.get(t), new_names.get(t))]
    corrections = all(_is_correction(old_names.get(t), old_dates.get(t),
                                     new_names.get(t), new_dates.get(t)) for t in differing)
    return "correction" if corrections else "change"


def history_entry(kind: str, field: dict, build_time: str) -> dict:
    """The history entry recording ``field``'s selected value, added by a build at
    ``build_time``."""
    return {"type": kind, "value": field["value"], "true_from": field["true_from"],
            "learned_at": build_time, "citations": field["citations"]}


def entries_for_build(previous_fields: dict, new_fields: dict, first_ready: bool,
                      build_time: str) -> list[tuple[str, dict, dict | None]]:
    """(field, history entry, feed entry or None) for each field the build adds an entry to,
    in field order (§4 order, then executives). Feed entries get their `seq` at commit."""
    added = []
    for name in ALL_FIELDS:
        old, new = previous_fields[name], new_fields[name]
        if first_ready:
            if new["value"] is not None:
                added.append((name, history_entry("initial", new, build_time), None))
            continue
        if same_value(old["value"], new["value"]):
            continue
        kind = entry_type(name, old, new)
        feed = {"field": name, "type": kind, "from": old["value"], "to": new["value"],
                "true_from": new["true_from"], "learned_at": build_time}
        added.append((name, history_entry(kind, new, build_time), feed))
    return added


def stamp_corroborated_since(new_fields: dict, ready_before: list, build_time: str) -> dict:
    """Each field's `corroborated_since`, over the ready builds before (app.store.BuildRecord)
    and this one."""
    return {name: {**field, "corroborated_since": corroborated_since(
                name, [(b.time, b.fields[name]) for b in ready_before] + [(build_time, field)])}
            for name, field in new_fields.items()}
