"""Stage-3 pure rules: executive titles, page dates, executives selection, history typing
and page versions (T3-T5, T13-T23, T25-T30, T34, T39-T42)."""
from datetime import datetime, timezone

from app.executives import decide_executives
from app.fields import ALL_FIELDS, empty_fields
from app.history import entries_for_build, entry_type, first_seen, stamp_candidates, stamp_fields
from app.pages import page_true_from, published_at
from app.selection import Candidate
from app.store import BuildRecord, Dossier
from app.support import supports
from app.timeline import Version, add_version, candidates_at, snapshot

D = "acme-robotics.test"
T1, T2, T3 = ("2026-03-01T09:00:00+00:00", "2026-04-01T09:00:00+00:00",
              "2026-05-01T09:00:00+00:00")


# --------------------------------------------------------------------------- W1

def test_title_statements_follow_the_ceo_rules():
    assert supports("Ana Silva is the chief financial officer of Acme Robotics.", "cfo", D) \
        == "Ana Silva"
    assert supports("Acme Robotics CTO: Ben Okafor.", "cto", D) == "Ben Okafor"
    assert supports("Lee Park is Acme Robotics COO.", "coo", D) == "Lee Park"
    assert supports("Sam Ortiz is the CEO of Acme Robotics.", "cfo", D) is None
    assert supports("Ana Silva is the CFO of Acme Robotics.", "ceo", D) is None
    assert supports("Ana Silva is the former CFO of Acme Robotics.", "cfo", D) is None
    two = "Ana Silva is CFO and Ben Okafor is CTO of Acme Robotics."
    assert supports(two, "cfo", D) is None and supports(two, "cto", D) is None


def test_true_from_is_effective_else_utc_published_date():
    def tf(text):
        return page_true_from(text, published_at(text))
    assert tf("Effective: 2025-03-01\nPublished: 2026-01-01T00:00:00Z\n\nx") == "2025-03-01"
    assert tf("Published: 2025-01-01T01:00:00+02:00\n\nx") == "2024-12-31"
    assert tf("Effective: 2025-02-30\nPublished: 2025-06-01T12:00:00Z\n\nx") == "2025-06-01"
    assert tf("Effective: 2025-2-1\n\nx") is None
    assert tf("Effective: 2025-03-01T00:00:00Z\n\nx") is None
    assert tf("No header at all.") is None


# --------------------------------------------------------------------------- W2

def cand(value, url, title=None, kind="own", true_from=None, field=None, provider="nimble"):
    return Candidate(field or ("executives" if title else "ceo"), value, url, f"{value}.",
                     provider, kind, None, T1, true_from, None, title)


def test_executives_selects_each_title_apart_in_title_order():
    field = decide_executives([
        cand("Ben Okafor", "https://b.test/1", "cto", true_from="2025-09-01"),
        cand("Ana Silva", "https://a.test/1", "cfo", true_from="2025-01-01"),
        cand("Ana Silva", "https://c.test/1", "cfo", kind="news", true_from="2025-02-01"),
    ])
    assert field["value"] == [{"title": "cfo", "name": "Ana Silva"},
                              {"title": "cto", "name": "Ben Okafor"}]
    assert field["status"] == "known"
    assert field["true_from"] == "2025-09-01"            # latest member's
    assert [c["url"] for c in field["citations"]] == [
        "https://a.test/1", "https://c.test/1", "https://b.test/1"]
    assert [(c["title"], c["url"], c["selected"]) for c in field["candidates"]] == [
        ("cfo", "https://a.test/1", True), ("cfo", "https://c.test/1", False),
        ("cto", "https://b.test/1", True)]


def test_executives_contested_null_true_from_and_unknown():
    field = decide_executives([
        cand("Lee Park", "https://a.test/1", "coo", true_from="2025-01-01"),
        cand("Kim Lee", "https://b.test/1", "coo", kind="news"),
        cand("Ana Silva", "https://a.test/2", "cfo"),
    ])
    assert field["status"] == "contested"
    assert field["value"] == [{"title": "cfo", "name": "Ana Silva"},
                              {"title": "coo", "name": "Lee Park"}]
    assert field["true_from"] is None                    # one member's is null
    assert decide_executives([])["value"] is None
    assert decide_executives([])["status"] == "unknown"


# --------------------------------------------------------------------------- W3

def field(value, true_from, learned_at=T1):
    return {"value": value, "status": "known", "true_from": true_from, "learned_at": learned_at,
            "citations": [{"url": "u", "excerpt": "e", "provider": "nimble"}], "candidates": []}


def exec_field(members):
    """members: [(title, name, true_from)]"""
    return {"value": [{"title": t, "name": n} for t, n, _ in members], "status": "known",
            "true_from": None, "learned_at": T1, "citations": [],
            "candidates": [{"title": t, "value": n, "true_from": tf, "selected": True}
                           for t, n, tf in members]}


def unknown():
    return empty_fields()["ceo"]


def test_change_and_correction_typing():
    assert entry_type("ceo", field("A", "2025-01-01"), field("B", "2024-06-01")) == "correction"
    assert entry_type("ceo", field("A", "2025-01-01"), field("B", "2025-01-01")) == "correction"
    assert entry_type("ceo", field("A", "2025-01-01"), field("B", "2025-02-01")) == "change"
    assert entry_type("ceo", field("A", None), field("B", "2024-01-01")) == "change"
    assert entry_type("ceo", field("A", "2025-01-01"), field("B", None)) == "change"
    assert entry_type("ceo", unknown(), field("B", "2024-01-01")) == "change"
    assert entry_type("ceo", field("A", "2025-01-01"), unknown()) == "change"


def test_executives_typing_by_title():
    old = exec_field([("cfo", "Ana", "2025-01-01"), ("cto", "Ben", "2025-01-01")])
    earlier_cfo = exec_field([("cfo", "Cy", "2024-01-01"), ("cto", "Ben", "2025-01-01")])
    later_cfo = exec_field([("cfo", "Cy", "2026-01-01"), ("cto", "Ben", "2025-01-01")])
    cto_gone = exec_field([("cfo", "Cy", "2024-01-01")])
    coo_new = exec_field([("cfo", "Ana", "2025-01-01"), ("coo", "Di", "2020-01-01"),
                          ("cto", "Ben", "2025-01-01")])
    null_date = exec_field([("cfo", "Cy", None), ("cto", "Ben", "2025-01-01")])
    assert entry_type("executives", old, earlier_cfo) == "correction"
    assert entry_type("executives", old, later_cfo) == "change"
    assert entry_type("executives", old, cto_gone) == "change"      # a title disappears
    assert entry_type("executives", old, coo_new) == "change"       # a title appears
    assert entry_type("executives", old, null_date) == "change"
    assert entry_type("executives", unknown(), old) == "change"


def fields_with(**values):
    fields = empty_fields()
    for name, f in values.items():
        fields[name] = f
    return fields


def test_entries_initial_then_change_once_in_field_order():
    first = fields_with(ceo=field("A", "2021-01-01"), founded_year=field(2014, None))
    added = entries_for_build(empty_fields(), first, True, T1)
    assert [(n, h["type"], f) for n, h, f in added] == [("ceo", "initial", None),
                                                         ("founded_year", "initial", None)]
    second = fields_with(ceo=field("B", "2026-03-20"), founded_year=field(2014, "2020-01-01"),
                         hq_city=field("Lisbon", None),
                         executives=exec_field([("cfo", "Ana", None), ("cto", "Ben", None)]))
    added = entries_for_build(first, second, False, T2)
    assert [n for n, _, _ in added] == ["hq_city", "ceo", "executives"]  # same 2014: nothing
    assert all(f is not None and f["learned_at"] == T2 for _, _, f in added)
    ceo = added[1][2]
    assert ceo == {"field": "ceo", "type": "change", "from": "A", "to": "B",
                   "true_from": "2026-03-20", "learned_at": T2}
    gone = entries_for_build(second, fields_with(ceo=field("B", "2026-03-20")), False, T3)
    assert [(n, h["type"], h["value"], h["citations"], h["true_from"]) for n, h, _ in gone] == [
        ("hq_city", "change", None, [], None), ("founded_year", "change", None, [], None),
        ("executives", "change", None, [], None)]


def test_learned_at_of_candidates_and_selected_values():
    c1 = cand("A", "https://a.test/1")
    seen = first_seen([])
    [stamped] = stamp_candidates([c1], seen, T1)
    assert stamped.learned_at == T1
    build1 = fields_with(ceo={**field("A", None), "candidates": [stamped.as_json(True)]})
    # gathered in build 1, missing in build 2, back in build 3: keeps build 1's time
    seen = first_seen([build1, empty_fields()])
    assert stamp_candidates([c1], seen, T3)[0].learned_at == T1
    assert stamp_candidates([cand("A", "https://a.test/1", provider="tavily")], seen,
                            T3)[0].learned_at == T3
    same = stamp_fields(fields_with(ceo=field("A", None, None)), build1, T2)
    assert same["ceo"]["learned_at"] == T1
    new = stamp_fields(fields_with(ceo=field("B", None, None)), build1, T2)
    assert new["ceo"]["learned_at"] == T2 and new["hq_city"]["learned_at"] is None


# --------------------------------------------------------------------------- W6, W7

def versions_on(versions, day):
    return [v.true_from for v in versions if v.holds_on(day)]


def test_page_version_replacement_and_ends():
    vs = []
    add_version(vs, Version("2020-01-01", []))
    add_version(vs, Version("2022-01-01", []))          # ends the 2020 one on 2022-01-01
    assert versions_on(vs, "2021-12-31") == ["2020-01-01"]
    assert versions_on(vs, "2022-01-01") == ["2022-01-01"]
    add_version(vs, Version("2021-01-01", []))          # replaces 2022, ends 2020 on 2021
    assert [v.true_from for v in vs] == ["2020-01-01", "2021-01-01"]
    assert versions_on(vs, "2020-12-31") == ["2020-01-01"]
    assert versions_on(vs, "2030-01-01") == ["2021-01-01"]
    assert versions_on(vs, "2019-12-31") == []
    add_version(vs, Version(None, []))                  # replaces all, holds nowhere
    assert [v.true_from for v in vs] == [None] and versions_on(vs, "2030-01-01") == []


def build_record(number, time, outcome="ready", spent=10, ceo=None, url="https://a.test/1",
                 true_from="2020-01-01"):
    fields = None
    pages = []
    if outcome == "ready":
        fields = empty_fields()
        pages = [{"url": url, "true_from": true_from}]
        if ceo:
            c = Candidate("ceo", ceo, url, f"{ceo}.", "nimble", "own", None, time, true_from,
                          time)
            fields["ceo"] = {**field(ceo, true_from, time), "candidates": [c.as_json(True)]}
    return BuildRecord(number, time, outcome, spent, fields, pages)


def test_candidates_at_a_date_follow_versions_across_builds():
    builds = [build_record(1, T1, ceo="Dana Ruiz", true_from="2021-04-01"),
              build_record(2, T2, ceo="Lee Park", true_from="2026-03-20")]
    assert [c.value for c in candidates_at(builds, "2025-06-01")] == ["Dana Ruiz"]
    assert [c.value for c in candidates_at(builds, "2026-03-20")] == ["Lee Park"]
    assert candidates_at(builds, "2021-03-31") == []
    # a later version with no candidates still ends the earlier one
    builds.append(build_record(3, T3, ceo=None, true_from="2026-04-01"))
    assert [c.value for c in candidates_at(builds, "2026-03-25")] == ["Lee Park"]
    assert candidates_at(builds, "2026-04-02") == []


def utc(text):
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def test_snapshot_picks_latest_ready_build_last_in_order_on_ties():
    d = Dossier("d_1", D)
    d.builds = [build_record(1, T1, ceo="A"),
                build_record(2, "2026-03-01T10:00:00+01:00", ceo="B"),   # same instant as T1
                build_record(3, T2, outcome="failed", spent=7)]
    d.spent_units = 27
    assert snapshot(d, utc("2026-02-28T00:00:00+00:00")) is None
    view = snapshot(d, utc(T1))
    assert view["fields"]["ceo"]["value"] == "B" and view["spent_units"] == 20
    assert view["researched_at"] == "2026-03-01T10:00:00+01:00" and view["state"] == "ready"
    assert snapshot(d, utc(T3))["spent_units"] == 27     # failed build's spend counts
    assert set(view["fields"]) == set(ALL_FIELDS)
