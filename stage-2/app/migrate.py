"""Imported dossier fields, from a stage-1 or a stage-2 export (stage-2 "Existing clients
after an upgrade").

A stage-1 export records, per field, only the selected value and the citations supporting
it: no page texts, kinds or publication times (plans/builder-notes-stage-2.md). Each
imported stage-1 field therefore gets one candidate per (value, cited page), with the
excerpt and provider as exported, a null kind and publication time, and the dossier's
researched_at as its retrieval time (lead ruling DEV-S1). Values stage 1 saw but did not
select were never exported and cannot be recovered.

A stage-2 export carries its candidates; their field is decided again by the selection
rule, which gives back the exported field.
"""
from __future__ import annotations

from app.pages import KINDS
from app.selection import Candidate, decide_field

STAGE1_KEYS = {"value", "status", "citations"}
STAGE2_KEYS = STAGE1_KEYS | {"candidates"}
CANDIDATE_KEYS = {"value", "url", "excerpt", "provider", "kind", "published_at",
                  "retrieved_at", "selected"}
INTEGER_FIELDS = ("founded_year", "funding_total")


def _is_str(value) -> bool:
    return isinstance(value, str)


def _typed(field: str, value) -> bool:
    if field in INTEGER_FIELDS:
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, str)


def _valid_citation(c) -> bool:
    return isinstance(c, dict) and set(c) == {"url", "excerpt", "provider"} and all(
        _is_str(c[k]) for k in c)


def _valid_candidate(field: str, c) -> bool:
    return (isinstance(c, dict) and set(c) == CANDIDATE_KEYS and _typed(field, c["value"])
            and all(_is_str(c[k]) for k in ("url", "excerpt", "provider"))
            and (c["kind"] is None or c["kind"] in KINDS)
            and all(c[k] is None or _is_str(c[k]) for k in ("published_at", "retrieved_at"))
            and isinstance(c["selected"], bool))


def valid_field(field: str, value) -> bool:
    """Whether ``value`` is a field in the stage-1 or the stage-2 export shape."""
    if not isinstance(value, dict) or set(value) not in (STAGE1_KEYS, STAGE2_KEYS):
        return False
    citations = value["citations"]
    if not isinstance(citations, list) or not all(_valid_citation(c) for c in citations):
        return False
    if "candidates" in value:
        candidates = value["candidates"]
        return isinstance(candidates, list) and all(
            _valid_candidate(field, c) for c in candidates)
    if value["value"] is None:
        return value["status"] == "unknown" and citations == []
    return _typed(field, value["value"]) and value["status"] == "known" and len(citations) >= 1


def import_field(field: str, value: dict, researched_at: str | None) -> dict:
    """The stage-2 field for a validated exported field of either shape."""
    if "candidates" in value:
        return decide_field([Candidate.from_json(field, c) for c in value["candidates"]])
    if value["value"] is None:
        return decide_field([])
    first_per_page: dict[str, dict] = {}
    for citation in value["citations"]:
        first_per_page.setdefault(citation["url"], citation)
    return decide_field([
        Candidate(field, value["value"], c["url"], c["excerpt"], c["provider"], None, None,
                  researched_at)
        for c in first_per_page.values()])
