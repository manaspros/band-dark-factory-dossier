"""Recording a finished build: its build record, and for a ready build the new fields, the
history entries and the change feed entries it adds (stage 3), all in one transaction; and
(stage 4) ending at startup the builds a stop interrupted.

Called in one synchronous section with an open ``Writer``: memory and the database change
together, before any response can observe the build's result.
"""
from __future__ import annotations

from app.db import Writer
from app.fields import decide
from app.history import (entries_for_build, first_seen, stamp_candidates,
                         stamp_corroborated_since, stamp_fields)
from app.selection import Candidate
from app.store import Batch, BuildRecord, Dossier, State, Store, interrupted_builds


def record_build(state: State, dossier: Dossier, writer: Writer, time: str, spent_units: int,
                 candidates: list[Candidate] | None, pages: list[dict],
                 batch: Batch | None = None) -> None:
    """Record a build of ``dossier`` at ``time``: failed when ``candidates`` is None, else
    ready with those candidates, gathered from ``pages`` ([{url, true_from}]). The build is
    no longer in flight; its batch's durable spending is written with it."""
    writer.delete_running(dossier.id)
    if batch is not None:
        writer.put_batch(batch)
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
        fields = stamp_corroborated_since(fields, ready_before, time)
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


def recover_interrupted(store: Store) -> None:
    """End every build a stop interrupted, before the service answers (lead ruling D4-12):
    each is recorded `failed` at its own time with the units it had reserved, which include
    every unit a provider billed; its fields stay as they were."""
    by_id = {d.id: d for d in store.state.dossiers.values()}
    for row in interrupted_builds(store.db):
        with store.transaction() as writer:
            dossier = by_id.get(row.dossier_id)
            if dossier is None:
                writer.delete_running(row.dossier_id)
                continue
            record_build(store.state, dossier, writer, row.build_time, row.spent, None, [])
