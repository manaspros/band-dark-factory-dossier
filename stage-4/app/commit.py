"""Recording a finished build: its build record, and for a ready build the new fields, the
history entries and the change feed entries it adds (stage 3), all in one transaction.

Called in one synchronous section with an open ``Writer``: memory and the database change
together, before any response can observe the build's result.
"""
from __future__ import annotations

from app.db import Writer
from app.fields import decide
from app.history import entries_for_build, first_seen, stamp_candidates, stamp_fields
from app.selection import Candidate
from app.store import BuildRecord, Dossier, State


def record_build(state: State, dossier: Dossier, writer: Writer, time: str, spent_units: int,
                 candidates: list[Candidate] | None, pages: list[dict]) -> None:
    """Record a build of ``dossier`` at ``time``: failed when ``candidates`` is None, else
    ready with those candidates, gathered from ``pages`` ([{url, true_from}])."""
    number = len(dossier.builds) + 1
    dossier.spent_units += spent_units
    if candidates is None:
        build = BuildRecord(number, time, "failed", spent_units)
        dossier.outcome = "failed"
    else:
        ready_before = dossier.ready_builds()
        seen = first_seen([b.fields for b in ready_before])
        fields = stamp_fields(decide(stamp_candidates(candidates, seen, time)),
                              dossier.fields, time)
        for name, entry, change in entries_for_build(dossier.fields, fields,
                                                     not ready_before, time):
            dossier.history[name].append(entry)
            writer.add_history(dossier.id, name, entry)
            if change is not None:
                change = {"seq": state.next_seq(), "domain": dossier.domain, **change}
                state.feed.append(change)
                writer.add_feed(change)
        build = BuildRecord(number, time, "ready", spent_units, fields, pages)
        dossier.fields = fields
        dossier.outcome = "ready"
        dossier.researched_at = time
    dossier.builds.append(build)
    writer.add_build(dossier.id, build)
    writer.put_dossier(dossier)
