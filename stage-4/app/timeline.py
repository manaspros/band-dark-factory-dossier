"""Answers about the past: the dossier as this service had it (`?as_of=`) and the values
the evidence says held on a date (`/values?true_at=`) (stage 3).

Both read a dossier's kept builds. A build counts at ``as_of`` when its time, compared as
an instant, is at or before ``as_of``; failed builds count only for spending.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime

from app.clock import parse_rfc3339
from app.fields import ALL_FIELDS, decide, field_candidates
from app.selection import Candidate
from app.store import BuildRecord, Dossier


def _instant(time: str) -> datetime:
    return parse_rfc3339(time)


def builds_known_at(dossier: Dossier, as_of: datetime) -> list[BuildRecord]:
    """The dossier's builds whose time is at or before ``as_of``, in build order."""
    return [b for b in dossier.builds if _instant(b.time) <= as_of]


def snapshot(dossier: Dossier, as_of: datetime) -> dict | None:
    """The dossier view as of ``as_of``: the latest ready build at or before it (the last
    in build order among equal times), or None when there is none."""
    known = builds_known_at(dossier, as_of)
    ready = [b for b in known if b.outcome == "ready"]
    if not ready:
        return None
    latest = max(ready, key=lambda b: (_instant(b.time), b.number))
    spent = dossier.imported_spent() + sum(b.spent_units for b in known)
    return {"dossier_id": dossier.id, "domain": dossier.domain, "state": "ready",
            "researched_at": latest.time, "spent_units": spent, "fields": latest.fields}


# --------------------------------------------------------------------------- page versions

@dataclass
class Version:
    """What one ready build gathered from one URL."""
    true_from: str | None
    candidates: list[Candidate]
    end: str | None = None          # the date it stops holding, if a later version ends it

    def holds_on(self, day: str) -> bool:
        return (self.true_from is not None and self.true_from <= day
                and (self.end is None or day < self.end))


def add_version(versions: list[Version], new: Version) -> None:
    """Add a later version of a URL: it replaces every earlier version whose `true_from` is
    on or after its own (all of them when its own is null), and the latest earlier version
    it does not replace stops holding on its `true_from`."""
    if new.true_from is None:
        versions.clear()
    else:
        versions[:] = [v for v in versions if v.true_from is None or v.true_from < new.true_from]
        if versions:
            versions[-1].end = new.true_from
    versions.append(new)


def candidates_at(builds: list[BuildRecord], day: str) -> list[Candidate]:
    """The candidates of every page version that holds on ``day``, given ready builds in
    build order."""
    versions: dict[str, list[Version]] = defaultdict(list)
    for build in builds:
        by_url: dict[str, list[Candidate]] = defaultdict(list)
        for candidate in field_candidates(build.fields):
            by_url[candidate.url].append(candidate)
        for page in build.pages:
            add_version(versions[page["url"]], Version(page["true_from"], by_url[page["url"]]))
    return [c for url_versions in versions.values() for v in url_versions if v.holds_on(day)
            for c in v.candidates]


def values(dossier: Dossier, true_at: date, as_of: datetime) -> dict | None:
    """Each field's value, `true_from`, citations, `origins` and `corroborated` on ``true_at``
    by the evidence known at ``as_of`` (lead ruling D4-5), or None when no build completed
    ready by then."""
    ready = [b for b in builds_known_at(dossier, as_of) if b.outcome == "ready"]
    if not ready:
        return None
    fields = decide(candidates_at(ready, true_at.isoformat()))
    keys = ("value", "true_from", "citations", "origins", "corroborated")
    return {name: {key: fields[name][key] for key in keys} for name in ALL_FIELDS}
