"""Validating the dossiers and change feed of a stage-3 export (stage-3 "Upgrades": its
builds, history and feed survive a stage-3 import unchanged).

Every check is type-first, so a JSON value of any type gives False, never an error, and
every imported excerpt must support the value it is given for (lead rulings on import).
A field must be exactly what the selection rule makes of its candidates; a build's pages
must cover its candidates; the current fields must be those of the last ready build.
"""
from __future__ import annotations

from app.executives import EXECUTIVES, decide_executives
from app.fields import ALL_FIELDS, empty_fields, field_candidates
from app.migrate import (CANDIDATE_KEYS, excerpt_supports, in_field_format, is_int, is_rfc3339,
                         is_str, valid_citation, valid_source)
from app.pages import KINDS, parse_date
from app.selection import Candidate, decide_field, value_key
from app.support import TITLES

FIELD_KEYS = {"value", "status", "true_from", "learned_at", "citations", "candidates"}
CANDIDATE3_KEYS = CANDIDATE_KEYS | {"true_from", "learned_at"}
BUILD_KEYS = {"number", "time", "outcome", "spent_units", "fields", "pages"}
ENTRY_KEYS = {"type", "value", "true_from", "learned_at", "citations"}
FEED_KEYS = {"seq", "domain", "field", "type", "from", "to", "true_from", "learned_at"}


def is_date(value, nullable: bool) -> bool:
    return nullable if value is None else parse_date(value) is not None


def valid_value(name: str, value) -> bool:
    """A selected value of field ``name`` (not null). Executives: members in title order."""
    if name != EXECUTIVES:
        return in_field_format(name, value)
    if not isinstance(value, list) or not value:
        return False
    if not all(isinstance(m, dict) and set(m) == {"title", "name"} and is_str(m["title"])
               and m["title"] in TITLES and in_field_format(m["title"], m["name"])
               for m in value):
        return False
    titles = [m["title"] for m in value]
    return titles == [t for t in TITLES if t in titles]


def _valid_candidate(name: str, c, domain: str) -> bool:
    keys = CANDIDATE3_KEYS | ({"title"} if name == EXECUTIVES else set())
    if not isinstance(c, dict) or set(c) != keys:
        return False
    subject = name
    if name == EXECUTIVES:
        if not (is_str(c["title"]) and c["title"] in TITLES):
            return False
        subject = c["title"]
    return (in_field_format(subject, c["value"]) and valid_source(c)
            and (c["kind"] is None or (is_str(c["kind"]) and c["kind"] in KINDS))
            and is_rfc3339(c["published_at"], nullable=True)
            and is_rfc3339(c["retrieved_at"], nullable=False)
            and is_date(c["true_from"], nullable=True)
            and is_rfc3339(c["learned_at"], nullable=False)
            and isinstance(c["selected"], bool)
            and excerpt_supports(c["excerpt"], subject, c["value"], domain))


def valid_field(name: str, value, domain: str) -> bool:
    """A stage-3 field: exactly what the selection rule makes of its candidates, with a
    learned_at that is null exactly when the field has no value."""
    if not isinstance(value, dict) or set(value) != FIELD_KEYS:
        return False
    listed = value["candidates"]
    if not isinstance(listed, list) or not all(_valid_candidate(name, c, domain) for c in listed):
        return False
    if not is_rfc3339(value["learned_at"], nullable=True) or (
            (value["value"] is None) != (value["learned_at"] is None)):
        return False
    candidates = [Candidate.from_json(name, c) for c in listed]
    decided = decide_executives(candidates) if name == EXECUTIVES else decide_field(candidates)
    return {**decided, "learned_at": value["learned_at"]} == value


def valid_fields(fields, domain: str) -> bool:
    return (isinstance(fields, dict) and set(fields) == set(ALL_FIELDS)
            and all(valid_field(name, fields[name], domain) for name in ALL_FIELDS))


def _valid_pages(pages, fields: dict) -> bool:
    """One page per URL; every candidate's page is listed with the candidate's true_from."""
    if not isinstance(pages, list) or not all(
            isinstance(p, dict) and set(p) == {"url", "true_from"} and is_str(p["url"])
            and is_date(p["true_from"], nullable=True) for p in pages):
        return False
    dates = {p["url"]: p["true_from"] for p in pages}
    return len(dates) == len(pages) and all(
        c.url in dates and dates[c.url] == c.true_from for c in field_candidates(fields))


def valid_build(build, number: int, domain: str) -> bool:
    if not (isinstance(build, dict) and set(build) == BUILD_KEYS and is_int(build["number"])
            and build["number"] == number and is_rfc3339(build["time"], nullable=False)
            and is_int(build["spent_units"]) and build["spent_units"] >= 0
            and is_str(build["outcome"]) and build["outcome"] in ("ready", "failed")):
        return False
    if build["outcome"] == "failed":
        return build["fields"] is None and build["pages"] == []
    return valid_fields(build["fields"], domain) and _valid_pages(build["pages"], build["fields"])


def _cites_value(name: str, value, citation: dict, domain: str) -> bool:
    if name != EXECUTIVES:
        return excerpt_supports(citation["excerpt"], name, value, domain)
    return any(excerpt_supports(citation["excerpt"], m["title"], m["name"], domain)
               for m in value)


def valid_entry(name: str, entry, domain: str) -> bool:
    """A history entry of field ``name``."""
    if not (isinstance(entry, dict) and set(entry) == ENTRY_KEYS
            and is_str(entry["type"]) and entry["type"] in ("initial", "change", "correction")
            and is_date(entry["true_from"], nullable=True)
            and is_rfc3339(entry["learned_at"], nullable=False)
            and isinstance(entry["citations"], list)
            and all(valid_citation(c) for c in entry["citations"])):
        return False
    if entry["value"] is None:
        return (entry["type"] != "initial" and entry["true_from"] is None
                and entry["citations"] == [])
    return (valid_value(name, entry["value"]) and len(entry["citations"]) >= 1
            and all(_cites_value(name, entry["value"], c, domain) for c in entry["citations"]))


def valid_history(history, domain: str) -> bool:
    return (isinstance(history, dict) and set(history) == set(ALL_FIELDS)
            and all(isinstance(history[n], list)
                    and all(valid_entry(n, e, domain) for e in history[n]) for n in ALL_FIELDS))


def valid_dossier_times(d: dict) -> bool:
    """Builds in order, spending within the dossier's total, and the current fields and
    researched_at those of the last ready build (or none at all)."""
    builds = d["builds"]
    if not isinstance(builds, list) or not all(
            valid_build(b, i + 1, d["domain"]) for i, b in enumerate(builds)):
        return False
    if sum(b["spent_units"] for b in builds) > d["spent_units"]:
        return False
    ready = [b for b in builds if b["outcome"] == "ready"]
    if not ready:
        return d["fields"] == empty_fields() and d["researched_at"] is None
    return d["fields"] == ready[-1]["fields"] and d["researched_at"] == ready[-1]["time"]


def valid_feed(feed, domains: set[str]) -> bool:
    """Feed entries with strictly increasing positive seq, each for an imported dossier."""
    if not isinstance(feed, list):
        return False
    last = 0
    for e in feed:
        if not (isinstance(e, dict) and set(e) == FEED_KEYS and is_int(e["seq"])
                and e["seq"] > last and is_str(e["domain"]) and e["domain"] in domains
                and is_str(e["field"]) and e["field"] in ALL_FIELDS
                and is_str(e["type"]) and e["type"] in ("change", "correction")
                and all(v is None or valid_value(e["field"], v) for v in (e["from"], e["to"]))
                and value_key(e["from"]) != value_key(e["to"])
                and is_date(e["true_from"], nullable=True)
                and is_rfc3339(e["learned_at"], nullable=False)):
            return False
        last = e["seq"]
    return True
