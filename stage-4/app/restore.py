"""Validating the dossiers and change feed of a stage-3 or stage-4 export (stage-3 and
stage-4 "Upgrades": builds, history and feed survive the import).

Every check is type-first, so a JSON value of any type gives False, never an error, and
every imported excerpt must support the value it is given for (lead rulings on import).
A field must be exactly what its rules make of its candidates; a build's pages must cover
its candidates; the current fields must be those of the last ready build. A stage-4 field
also carries `origins`, `corroborated` (from its candidates) and `corroborated_since` (from
the ready builds up to it); a stage-3 field has none of these and no `investors`.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.corroboration import corroborated_since
from app.domains import is_valid as is_valid_domain
from app.executives import EXECUTIVES, decide_executives
from app.fields import ALL_FIELDS, decide_one, field_candidates
from app.migrate import (CANDIDATE_KEYS, excerpt_supports, in_field_format, is_int, is_rfc3339,
                         is_str, valid_citation, valid_source)
from app.pages import KINDS, parse_date
from app.selection import Candidate, decide_field, value_key
from app.support import FIELDS, INVESTORS, TITLES

FIELD3_KEYS = frozenset({"value", "status", "true_from", "learned_at", "citations",
                         "candidates"})
STAGE4_FIELD_KEYS = frozenset({"origins", "corroborated", "corroborated_since"})
CANDIDATE3_KEYS = frozenset(CANDIDATE_KEYS | {"true_from", "learned_at"})
BUILD_KEYS = {"number", "time", "outcome", "spent_units", "fields", "pages"}
ENTRY_KEYS = {"type", "value", "true_from", "learned_at", "citations"}
FEED_KEYS = {"seq", "domain", "field", "type", "from", "to", "true_from", "learned_at"}


@dataclass(frozen=True)
class Shape:
    """The keys an export of one stage writes."""
    fields: tuple[str, ...]
    field_keys: frozenset
    candidate_keys: frozenset
    stage4: bool

    def empty_fields(self) -> dict:
        return {name: self.decide(name, []) for name in self.fields}

    def decide(self, name: str, candidates: list[Candidate]) -> dict:
        """What the field's rules make of ``candidates``, in this stage's shape."""
        if self.stage4:
            return decide_one(name, candidates)
        field = decide_executives(candidates) if name == EXECUTIVES else decide_field(candidates)
        return {**field, "candidates": [{k: v for k, v in c.items() if k != "origin"}
                                        for c in field["candidates"]]}


STAGE3 = Shape(FIELDS + (EXECUTIVES,), FIELD3_KEYS, CANDIDATE3_KEYS, stage4=False)
STAGE4 = Shape(ALL_FIELDS, FIELD3_KEYS | STAGE4_FIELD_KEYS, CANDIDATE3_KEYS | {"origin"},
               stage4=True)


def shape_of(dossier: dict) -> Shape:
    """Stage 4 when the dossier's fields hold `investors`, else stage 3."""
    fields = dossier.get("fields")
    return STAGE4 if isinstance(fields, dict) and INVESTORS in fields else STAGE3


def is_date(value, nullable: bool) -> bool:
    return nullable if value is None else parse_date(value) is not None


def valid_value(name: str, value) -> bool:
    """A selected value of field ``name`` (not null). Executives: members in title order;
    investors: distinct names in code-point order."""
    if name == INVESTORS:
        return (isinstance(value, list) and bool(value)
                and all(in_field_format(INVESTORS, n) for n in value)
                and value == sorted(set(value)))
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


def _valid_candidate(name: str, c, domain: str, shape: Shape) -> bool:
    keys = shape.candidate_keys | ({"title"} if name == EXECUTIVES else set())
    if not isinstance(c, dict) or set(c) != keys:
        return False
    if shape.stage4 and not (is_str(c["origin"]) and is_valid_domain(c["origin"])):
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


def valid_field(name: str, value, domain: str, shape: Shape) -> bool:
    """Exactly what the field's rules make of its candidates, with a learned_at (and, in
    stage 4, a corroborated_since) that is null when the field has no value."""
    if not isinstance(value, dict) or set(value) != shape.field_keys:
        return False
    listed = value["candidates"]
    if not isinstance(listed, list) or not all(
            _valid_candidate(name, c, domain, shape) for c in listed):
        return False
    if not is_rfc3339(value["learned_at"], nullable=True) or (
            (value["value"] is None) != (value["learned_at"] is None)):
        return False
    kept = {"learned_at": value["learned_at"]}
    if shape.stage4:
        if not is_rfc3339(value["corroborated_since"], nullable=True) or (
                value["value"] is None and value["corroborated_since"] is not None):
            return False
        kept["corroborated_since"] = value["corroborated_since"]
    candidates = [Candidate.from_json(name, c) for c in listed]
    return {**shape.decide(name, candidates), **kept} == value


def valid_fields(fields, domain: str, shape: Shape) -> bool:
    return (isinstance(fields, dict) and set(fields) == set(shape.fields)
            and all(valid_field(name, fields[name], domain, shape) for name in shape.fields))


def _valid_pages(pages, fields: dict) -> bool:
    """One page per URL, and every candidate's page is listed."""
    if not isinstance(pages, list) or not all(
            isinstance(p, dict) and set(p) == {"url", "true_from"} and is_str(p["url"])
            and is_date(p["true_from"], nullable=True) for p in pages):
        return False
    urls = {p["url"] for p in pages}
    return len(urls) == len(pages) and all(c.url in urls for c in field_candidates(fields))


def valid_build(build, number: int, domain: str, shape: Shape) -> bool:
    if not (isinstance(build, dict) and set(build) == BUILD_KEYS and is_int(build["number"])
            and build["number"] == number and is_rfc3339(build["time"], nullable=False)
            and is_int(build["spent_units"]) and build["spent_units"] >= 0
            and is_str(build["outcome"]) and build["outcome"] in ("ready", "failed")):
        return False
    if build["outcome"] == "failed":
        return build["fields"] is None and build["pages"] == []
    return (valid_fields(build["fields"], domain, shape)
            and _valid_pages(build["pages"], build["fields"]))


def _cites_value(name: str, value, citation: dict, domain: str) -> bool:
    if name == EXECUTIVES:
        return any(excerpt_supports(citation["excerpt"], m["title"], m["name"], domain)
                   for m in value)
    if name == INVESTORS:
        return any(excerpt_supports(citation["excerpt"], INVESTORS, n, domain) for n in value)
    return excerpt_supports(citation["excerpt"], name, value, domain)


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


def valid_history(history, domain: str, shape: Shape) -> bool:
    return (isinstance(history, dict) and set(history) == set(shape.fields)
            and all(isinstance(history[n], list)
                    and all(valid_entry(n, e, domain) for e in history[n])
                    for n in shape.fields))


def valid_dossier_times(d: dict, shape: Shape) -> bool:
    """Builds in order, spending within the dossier's total, the current fields and
    researched_at those of the last ready build (or none at all), and in stage 4 each ready
    build's corroborated_since what the builds up to it give."""
    builds = d["builds"]
    if not isinstance(builds, list) or not all(
            valid_build(b, i + 1, d["domain"], shape) for i, b in enumerate(builds)):
        return False
    if sum(b["spent_units"] for b in builds) > d["spent_units"]:
        return False
    ready = [b for b in builds if b["outcome"] == "ready"]
    if shape.stage4:
        for index, build in enumerate(ready):
            for name in shape.fields:
                walk = [(b["time"], b["fields"][name]) for b in ready[:index + 1]]
                if build["fields"][name]["corroborated_since"] != corroborated_since(name, walk):
                    return False
    if not ready:
        return d["fields"] == shape.empty_fields() and d["researched_at"] is None
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

