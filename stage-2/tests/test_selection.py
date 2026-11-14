"""The selection rule and status (stage 2)."""
import itertools

from app.selection import Candidate, decide_field, rank

T = "2026-03-01T09:00:00+00:00"


def cand(value, url="https://a.test/x", kind="own", published=None, provider="nimble"):
    return Candidate("ceo", value, url, f"Acme Robotics CEO {value}.", provider, kind,
                     published, T)


def values(candidates):
    return [c.value for c in rank(candidates)]


def test_authority_first_own_and_filing_tie():
    agg = cand("Agg Person", "https://a.test/1", "aggregator", "2026-12-01T00:00:00Z")
    news = cand("News Person", "https://a.test/2", "news", "2026-11-01T00:00:00Z")
    own = cand("Own Person", "https://a.test/4", "own")
    filing = cand("Filing Person", "https://a.test/3", "filing")
    assert values([agg, news, own, filing]) == [
        "Filing Person", "Own Person", "News Person", "Agg Person"]


def test_null_kind_ranks_as_aggregator():
    imported = cand("Imported", "https://a.test/1", None)
    agg = cand("Agg", "https://a.test/2", "aggregator")
    assert values([agg, imported]) == ["Imported", "Agg"]  # tie broken by URL


def test_recency_and_missing_time_and_offsets():
    old = cand("Old", "https://a.test/1", "news", "2025-01-01T00:00:00+00:00")
    new = cand("New", "https://a.test/2", "news", "2026-01-01T00:00:00+00:00")
    none = cand("None", "https://a.test/0", "news", None)
    assert values([none, old, new]) == ["New", "Old", "None"]
    same_a = cand("Bb", "https://b.test/1", "news", "2026-01-01T02:00:00+02:00")
    same_b = cand("Aa", "https://c.test/1", "news", "2026-01-01T00:00:00Z")
    assert values([same_b, same_a]) == ["Bb", "Aa"]          # same instant: URL decides


def test_url_then_provider_then_value():
    a = cand("Zed Person", "https://a.test/x", provider="tavily")
    b = cand("Bob Person", "https://a.test/x", provider="nimble")
    c = cand("Al Person", "https://b.test/x")
    assert values([c, a, b]) == ["Bob Person", "Zed Person", "Al Person"]
    ints = [Candidate("founded_year", v, "https://a.test/x", "e", "nimble", "own", None, T)
            for v in (2015, 9, 2014)]
    assert [c.value for c in rank(ints)] == [9, 2014, 2015]  # numbers, not strings


def test_permutation_invariant():
    pool = [cand("A Person", "https://b.test/1", "news", "2026-01-01T00:00:00Z"),
            cand("B Person", "https://a.test/1", "news", "2026-01-01T00:00:00Z"),
            cand("C Person", "https://a.test/1", "own"),
            cand("D Person", "https://c.test/1", None),
            cand("E Person", "https://a.test/1", "aggregator", "2026-05-01T00:00:00Z")]
    expected = decide_field(pool)
    for perm in itertools.permutations(pool):
        assert decide_field(list(perm)) == expected


def test_status_value_citations_and_selected():
    assert decide_field([]) == {"value": None, "status": "unknown", "citations": [],
                                "candidates": []}
    one = decide_field([cand("Dana Ruiz", "https://a.test/1"),
                        cand("Dana Ruiz", "https://b.test/1", "news")])
    assert one["status"] == "known" and one["value"] == "Dana Ruiz"
    assert [c["url"] for c in one["citations"]] == ["https://a.test/1", "https://b.test/1"]
    two = decide_field([cand("Sam Ortiz", "https://z.test/1", "aggregator"),
                        cand("Dana Ruiz", "https://a.test/1"),
                        cand("Dana Ruiz", "https://y.test/1", "aggregator")])
    assert two["status"] == "contested" and two["value"] == "Dana Ruiz"
    assert [c["url"] for c in two["citations"]] == ["https://a.test/1", "https://y.test/1"]
    assert [c["selected"] for c in two["candidates"]] == [True, False, False]
