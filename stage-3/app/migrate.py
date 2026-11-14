"""Imported dossier fields, from a stage-1 or a stage-2 export (stage-2 "Existing clients
after an upgrade", stage-3 "Upgrades").

A stage-1 export records, per field, only the selected value and the citations supporting
it: no page texts, kinds or publication times (plans/builder-notes-stage-2.md). Each
imported stage-1 field therefore gets one candidate per (value, cited page), with the
excerpt and provider as exported, a null kind and publication time, and the dossier's
researched_at as its retrieval time (lead ruling DEV-S1). Values stage 1 saw but did not
select were never exported and cannot be recovered.

A stage-2 export carries its candidates; each must hold a value §4 allows for its field,
and the field must be exactly what the selection rule makes of them. Anything else is an
invalid state (422, nothing changed).

Stage 3 (``upgrade_dossier``): such a dossier becomes one build that completed ready at its
researched_at, holding every imported candidate and the whole spent_units (lead ruling
DEV-S3a), or no build at all when researched_at is null. Each candidate's true_from is the
UTC date of its published_at, else null (the exports record no `Effective` line, lead ruling
DEV-S3b), and its learned_at is its retrieved_at. Every field with a value gets one `initial`
history entry; `executives` is unknown.
"""
from __future__ import annotations

from dataclasses import replace

from app.clock import parse_rfc3339
from app.errors import ApiError
from app.fields import ALL_FIELDS, decide, field_candidates
from app.history import history_entry
from app.pages import KINDS, utc_date
from app.selection import PROVIDER_ORDER, Candidate, decide_field
from app.support import HEADCOUNT_RANGES, MAX_EXCERPT_CHARS, supports

STAGE1_KEYS = {"value", "status", "citations"}
STAGE2_KEYS = STAGE1_KEYS | {"candidates"}
CANDIDATE_KEYS = {"value", "url", "excerpt", "provider", "kind", "published_at",
                  "retrieved_at", "selected"}
HEADCOUNT_LABELS = {label for _, _, label in HEADCOUNT_RANGES}


def is_str(value) -> bool:
    return isinstance(value, str)


def is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def in_field_format(field: str, value) -> bool:
    """Whether ``value`` is a value §4 allows for ``field``.

    The JSON type is always checked before any comparison or membership test, so a value
    of any JSON type (list, object, null, bool, float, ...) gives False, never an error.
    """
    if field == "founded_year":
        return is_int(value) and 1800 <= value <= 2099
    if field == "funding_total":
        return is_int(value) and value >= 0
    if field == "headcount_range":
        return is_str(value) and value in HEADCOUNT_LABELS
    return is_str(value) and value != "" and value == value.strip()


def is_rfc3339(value, nullable: bool) -> bool:
    """Whether ``value`` is an RFC 3339 timestamp string (or None, when ``nullable``)."""
    if value is None:
        return nullable
    try:
        parse_rfc3339(value)
    except ApiError:
        return False
    return True


def valid_source(c) -> bool:
    """url, excerpt (1 to 500 characters) and a known provider."""
    return (is_str(c.get("url")) and is_str(c.get("excerpt"))
            and 1 <= len(c["excerpt"]) <= MAX_EXCERPT_CHARS
            and is_str(c.get("provider")) and c["provider"] in PROVIDER_ORDER)


def valid_citation(c) -> bool:
    return isinstance(c, dict) and set(c) == {"url", "excerpt", "provider"} and valid_source(c)


def excerpt_supports(excerpt: str, field: str, value, domain: str) -> bool:
    """Whether ``excerpt`` alone states ``value`` for ``field`` of the company at ``domain``
    (Appendix A: a single sentence naming the company, with a statement phrase, no
    negation, and every value in the field's format normalising to ``value``)."""
    return supports(excerpt, field, domain) == value


def _valid_candidate(field: str, c, domain: str) -> bool:
    return (isinstance(c, dict) and set(c) == CANDIDATE_KEYS and in_field_format(field, c["value"])
            and valid_source(c) and (c["kind"] is None or (is_str(c["kind"]) and c["kind"] in KINDS))
            and is_rfc3339(c["published_at"], nullable=True)
            and is_rfc3339(c["retrieved_at"], nullable=False)
            and isinstance(c["selected"], bool)
            and excerpt_supports(c["excerpt"], field, c["value"], domain))


_STAGE3_KEYS = ("true_from", "learned_at")


def _stage2_view(field: dict) -> dict:
    """A decided field as a stage-2 service wrote it: without the stage-3 times."""
    def strip(item: dict) -> dict:
        return {k: v for k, v in item.items() if k not in _STAGE3_KEYS}
    return {**strip(field), "candidates": [strip(c) for c in field["candidates"]]}


def valid_field(field: str, value, domain: str) -> bool:
    """Whether ``value`` is a field of the dossier for ``domain``, in the stage-1 or the
    stage-2 export shape, with every excerpt supporting the value it is cited for (§1, §4)."""
    if not isinstance(value, dict) or set(value) not in (STAGE1_KEYS, STAGE2_KEYS):
        return False
    citations = value["citations"]
    if not isinstance(citations, list) or not all(valid_citation(c) for c in citations):
        return False
    if "candidates" in value:
        candidates = value["candidates"]
        if not isinstance(candidates, list) or not all(
                _valid_candidate(field, c, domain) for c in candidates):
            return False
        # The field (value, status, citations, order, selected) must be exactly what the
        # selection rule and the Status rule make of its candidates.
        return _stage2_view(decide_field([Candidate.from_json(field, c) for c in candidates])) == value
    if value["value"] is None:
        return value["status"] == "unknown" and citations == []
    return (in_field_format(field, value["value"]) and value["status"] == "known"
            and len(citations) >= 1
            and all(excerpt_supports(c["excerpt"], field, value["value"], domain) for c in citations))


def import_field(field: str, value: dict, researched_at: str | None) -> dict:
    """The stage-2 field for a validated exported field of either shape."""
    if "candidates" in value:
        return value  # valid_field has checked it equals the selection rule's result
    if value["value"] is None:
        return decide_field([])
    first_per_page: dict[str, dict] = {}
    for citation in value["citations"]:
        first_per_page.setdefault(citation["url"], citation)
    return decide_field([
        Candidate(field, value["value"], c["url"], c["excerpt"], c["provider"], None, None,
                  researched_at)
        for c in first_per_page.values()])


def same_page_dates(fields: dict) -> bool:
    """Whether every candidate of one URL has the same publication time, as candidates read
    from one page do: the URL is then one page version with one true_from."""
    published: dict[str, str | None] = {}
    return all(published.setdefault(c.url, c.published_at) == c.published_at
               for c in field_candidates(fields))


def upgrade_dossier(fields: dict, researched_at: str | None, spent_units: int):
    """(fields, builds, history) of a validated stage-1 or stage-2 dossier in stage 3.

    ``fields`` are the stage-2-shaped fields ``import_field`` made (``same_page_dates``
    holds for them); the builds are returned as JSON (app.store.BuildRecord.from_json).
    """
    candidates = [replace(c, true_from=utc_date(c.published_at), learned_at=c.retrieved_at)
                  for c in field_candidates(fields)]
    upgraded = decide(candidates)
    for field in upgraded.values():
        field["learned_at"] = researched_at if field["value"] is not None else None
    history = {name: [] for name in ALL_FIELDS}
    if researched_at is None:
        return upgraded, [], history
    for name in ALL_FIELDS:
        if upgraded[name]["value"] is not None:
            history[name].append(history_entry("initial", upgraded[name], researched_at))
    pages: dict[str, str | None] = {}
    for candidate in candidates:
        pages.setdefault(candidate.url, candidate.true_from)
    build = {"number": 1, "time": researched_at, "outcome": "ready", "spent_units": spent_units,
             "fields": upgraded,
             "pages": [{"url": url, "true_from": tf} for url, tf in pages.items()]}
    return upgraded, [build], history
