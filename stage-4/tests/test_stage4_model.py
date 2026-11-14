"""Stage-4 pure rules: lineage, kind, origins, investor names, investors, corroboration,
history typing and the nested budget (F4-F53, F66-F68, F98)."""
import asyncio

import pytest

from app.budget import BatchBudget, Budget
from app.corroboration import corroborated_since, current_keys
from app.fields import decide_one, empty_fields
from app.history import entry_type
from app.investors import decide_investors
from app.origins import Served, resolve
from app.pages import lineage, page_kind
from app.selection import Candidate
from app.support import investor_names

D = "acme-robotics.test"
T1, T2, T3 = ("2026-03-01T09:00:00+00:00", "2026-04-01T09:00:00+00:00",
              "2026-05-01T09:00:00+00:00")


# --------------------------------------------------------------------------- lineage (U1)

def test_lineage_lines_are_normalised_and_invalid_ones_ignored():
    lin = lineage("https://copy.test/a", "Registrant: WWW.Acme-Robotics.TEST.\n"
                  "Canonical: https://acme-robotics.test/news\nFirst-Published-By: Wire.TEST\n\nx")
    assert (lin.registrant, lin.canonical, lin.first_published_by) == (
        D, "https://acme-robotics.test/news", "wire.test")
    bad = lineage("https://www.copy.test/a", "Registrant: not a domain\nCanonical: ftp://x.test/\n"
                  "First-Published-By: ???\n\nx")
    assert (bad.registrant, bad.canonical, bad.first_published_by) == ("copy.test", None, None)


def test_kind_own_only_for_the_registrant_and_lookalikes():
    assert page_kind(f"https://{D}/a", "Kind: own\n\nx", D) == "own"
    assert page_kind("https://other.test/a", "Kind: own\n\nx", D) == "aggregator"
    assert page_kind(f"https://{D}/a", "Registrant: other.test\n\nx", D) == "aggregator"
    assert page_kind("https://x.test/a", f"Kind: own\nRegistrant: {D}\n\nx", D) == "own"
    assert lineage("https://acme-robotlcs.test/", "Kind: own\nRegistrant: shady.test\n\nx").lookalike
    assert not lineage("https://acme-robotlcs.test/", "Kind: own\n\nx").lookalike
    assert not lineage(f"https://{D}/", "Registrant: other.test\n\nx").lookalike


def origin_of(url, text, served):
    """served: {url: (served url, text)}; returns (origin, fetched urls)."""
    fetched = []

    async def fetch(target):
        fetched.append(target)
        if target not in served:
            return None
        at, body = served[target]
        return Served(lineage(at, body))
    return asyncio.run(resolve(lineage(url, text), D, fetch)), fetched


def test_origin_rules_in_order():
    assert origin_of("https://a.test/1", "First-Published-By: wire.test\n"
                     "Canonical: https://b.test/1\n\nx", {})[0] == "wire.test"
    assert origin_of("https://a.test/1", "Canonical: https://a.test/1\n\nx", {}) == (
        "a.test", [])                                        # self-canonical
    assert origin_of("https://acme-robotlcs.test/", "Kind: own\nRegistrant: shady.test\n\nx",
                     {})[0] == D                             # lookalike
    assert origin_of("https://a.test/1", "Registrant: reg.test\n\nx", {})[0] == "reg.test"


def test_canonical_chain_three_hops_then_host():
    chain = {f"https://h{i}.test/p": (f"https://h{i}.test/p",
                                      f"Canonical: https://h{i + 1}.test/p\n\nx")
             for i in range(1, 5)}
    origin, fetched = origin_of("https://h0.test/p", "Canonical: https://h1.test/p\n\nx", chain)
    assert fetched == ["https://h1.test/p", "https://h2.test/p", "https://h3.test/p"]
    assert origin == "h4.test"                               # the 4th hop is not followed
    chain["https://h2.test/p"] = ("https://h2.test/p", "First-Published-By: wire.test\n\nx")
    assert origin_of("https://h0.test/p", "Canonical: https://h1.test/p\n\nx",
                     chain)[0] == "wire.test"


def test_unserved_cycle_and_redirected_originals():
    assert origin_of("https://a.test/1", "Canonical: https://gone.test/x\n\nx", {})[0] \
        == "gone.test"
    cycle = {"https://b.test/1": ("https://b.test/1", "Canonical: https://a.test/1\n\nx"),
             "https://a.test/1": ("https://a.test/1", "Canonical: https://b.test/1\n\nx")}
    origin, fetched = origin_of("https://a.test/1", "Canonical: https://b.test/1\n\nx", cycle)
    assert len(fetched) == 3 and origin in ("a.test", "b.test")
    redirected = {"https://u.test/x": ("https://v.test/x", "Canonical: https://v.test/x\n\nx")}
    assert origin_of("https://a.test/1", "Canonical: https://u.test/x\n\nx",
                     redirected)[0] == "v.test"
    lookalike = {"https://u.test/x": ("https://v.test/x", "Kind: own\nRegistrant: s.test\n\nx")}
    assert origin_of("https://a.test/1", "Canonical: https://u.test/x\n\nx",
                     lookalike)[0] == D


# --------------------------------------------------------------------------- investors (U2, U3)

@pytest.mark.parametrize("text, names", [
    ("Acme Robotics raised $40M in a round led by General Atlantic.", ["General Atlantic"]),
    ("Acme Robotics is led by Dana Ruiz.", []),
    ("Acme Robotics is backed by Northwind Ventures and Bluebird Capital.",
     ["Northwind Ventures", "Bluebird Capital"]),
    ("Acme Robotics investors include Big Sky Capital Partners.", ["Big Sky Capital Partners"]),
    ("Acme Robotics investor Ventures said so.", []),
    ("Acme Robotics raised $5M led by Sequoia.", ["Sequoia"]),
    ("Acme Robotics is reportedly backed by Northwind Ventures.", []),
    ("Acme Robotics is backed by Northwind Ventures. It grew.", []),
    ("Northwind Ventures participated in the Acme Robotics round.", ["Northwind Ventures"]),
    ("Acme Robotics Ventures is an investor.", []),
])
def test_investor_names(text, names):
    assert investor_names(text, D) == names


def inv(name, url, kind="news", origin=None, true_from=None):
    return Candidate("investors", name, url, f"{name}.", "nimble", kind, None, T1, true_from,
                     T1, None, origin or url.split("/")[2])


def test_investor_membership_value_and_dates():
    field = decide_investors([
        inv("Northwind Ventures", "https://a.test/1", true_from="2024-05-02"),
        inv("Northwind Ventures", "https://b.test/1", true_from="2024-01-01"),
        inv("Bluebird Capital", f"https://{D}/x", kind="own"),
        inv("Solo Fund", "https://c.test/1"),
        inv("Echo Equity", "https://d.test/1"), inv("Echo Equity", "https://d.test/2"),
    ])
    assert field["value"] == ["Bluebird Capital", "Northwind Ventures"]
    assert field["status"] == "known"
    assert field["true_from"] is None                       # Bluebird has no date
    selected = {c["value"]: c["selected"] for c in field["candidates"]}
    assert selected == {"Northwind Ventures": True, "Bluebird Capital": True,
                        "Solo Fund": False, "Echo Equity": False}
    assert [c["url"] for c in field["citations"]] == [
        f"https://{D}/x", "https://a.test/1", "https://b.test/1"]
    dated = decide_investors([inv("Northwind Ventures", "https://a.test/1", true_from="2024-05-02"),
                              inv("Northwind Ventures", "https://b.test/1", true_from="2024-01-01")])
    assert dated["true_from"] == "2024-01-01"               # the member's earliest date
    none = decide_investors([inv("Solo Fund", "https://c.test/1")])
    assert none["value"] is None and none["status"] == "unknown" and len(none["candidates"]) == 1


# --------------------------------------------------------------------------- corroboration (U3)

def ceo(value, url, origin):
    return Candidate("ceo", value, url, f"{value}.", "nimble", "news", None, T1, None, T1,
                     None, origin)


def test_origins_count_the_selected_value_only():
    field = decide_one("ceo", [ceo("Dana Ruiz", "https://a.test/1", "a.test"),
                               ceo("Dana Ruiz", "https://b.test/1", "a.test"),
                               ceo("Lee Park", "https://c.test/1", "c.test")])
    assert field["origins"] == ["a.test"] and field["corroborated"] is False
    two = decide_one("ceo", [ceo("Dana Ruiz", "https://a.test/1", "a.test"),
                             ceo("Dana Ruiz", "https://b.test/1", "b.test")])
    assert two["origins"] == ["a.test", "b.test"] and two["corroborated"] is True
    assert empty_fields()["ceo"]["origins"] == [] and not empty_fields()["investors"]["corroborated"]


def snap(value, *origins):
    return decide_one("ceo", [ceo(value, f"https://{o}/x", o) for o in origins]) if value \
        else empty_fields()["ceo"]


def test_corroborated_since_walk():
    assert corroborated_since("ceo", [(T1, snap("A", "a.test"))]) is None
    assert corroborated_since("ceo", [(T1, snap("A", "a.test")),
                                      (T2, snap("A", "b.test"))]) == T2   # standing origins
    assert corroborated_since("ceo", [(T1, snap("A", "a.test", "b.test")),
                                      (T2, snap("A", "a.test"))]) == T1   # stays standing
    assert corroborated_since("ceo", [(T1, snap("A", "a.test", "b.test")),
                                      (T2, snap("B", "c.test")),
                                      (T3, snap("A", "a.test"))]) is None  # restarts
    exec_snap = decide_one("executives", [
        Candidate("executives", "Ana Silva", "https://a.test/1", "x.", "nimble", "news", None,
                  T1, None, T1, "cfo", "a.test")])
    assert current_keys("executives", exec_snap) == {"origins": ["a.test"],
                                                     "corroborated": False}


# --------------------------------------------------------------------------- history (U4)

def inv_field(names, true_from=None, dates=None):
    if names is None:
        return empty_fields()["investors"]
    dates = dates or {}
    field = decide_investors([inv(n, f"https://{D}/{i}", kind="own", true_from=dates.get(n))
                              for i, n in enumerate(names)])
    return {**field, "true_from": true_from}


def test_investors_typing_by_name():
    old = inv_field(["A Capital"], "2025-01-01")
    assert entry_type("investors", old, inv_field(
        ["A Capital", "B Capital"], dates={"B Capital": "2024-01-01"})) == "correction"
    assert entry_type("investors", old, inv_field(
        ["A Capital", "B Capital"], dates={"B Capital": "2026-01-01"})) == "change"
    assert entry_type("investors", old, inv_field(["B Capital"],
                                                  dates={"B Capital": "2024-01-01"})) == "change"
    assert entry_type("investors", old, inv_field(["A Capital", "B Capital"])) == "change"
    assert entry_type("investors", inv_field(None), inv_field(["B Capital"])) == "change"


# --------------------------------------------------------------------------- budget (U5)

def test_batch_budget_is_shared_and_exhaustion_stops_every_call():
    batch = BatchBudget(30)
    a, b = Budget(20, batch), Budget(20, batch)
    assert a.reserve(20) and b.reserve(10)
    assert not b.reserve(1) and batch.exhausted and b.stopped_by_batch
    a.settle(20, charged=False)                 # units released after exhaustion
    assert not a.reserve(1)                     # still no further call
    assert batch.reserved == 10


def test_hold_is_not_spend_and_never_exhausts():
    batch = BatchBudget(50)
    build = Budget(50, batch)
    assert build.hold(18) and batch.held == 18 and build.reserved == 0
    assert not build.hold(40) and not batch.exhausted
    assert build.reserve(3, use_hold=True) and build.held == 15 and build.reserved == 3
    build.release_hold()
    assert build.held == 0 and batch.held == 0 and batch.reserved == 3
