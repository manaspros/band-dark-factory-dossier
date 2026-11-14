"""The build runner: budget, retries, timing, research and provenance."""
import asyncio
import time

from app.budget import Budget
from app.build import Build, Builds
from app.store import Dossier, State, Store
from tests.fakes import DOMAIN, PAGES, FakeWeb


def run(build):
    return asyncio.run(build.run())


def test_domain_query_refused_once_then_made_once():
    web = FakeWeb(refuse=lambda m, a, n: m == "search" and a == DOMAIN and n == 1)
    run(Build(DOMAIN, web))
    assert web.calls.count(("search", DOMAIN)) == 2
    searches = [a for m, a in web.calls if m == "search"]
    assert len(searches) - searches.count(DOMAIN) == 7  # 6 field queries + the name


def test_domain_query_refused_three_times_continues_ready():
    web = FakeWeb(refuse=lambda m, a, n: m == "search" and a == DOMAIN)
    build = Build(DOMAIN, web)
    fields = run(build)
    assert web.calls.count(("search", DOMAIN)) == 3
    assert fields is not None and fields["ceo"]["value"] == "Dana Ruiz"


def test_every_call_refused_fails_fast_and_free():
    web = FakeWeb(refuse=lambda m, a, n: True)
    build = Build(DOMAIN, web)
    began = time.monotonic()
    assert run(build) is None
    assert time.monotonic() - began < 3      # two 1.05 s backoffs, nothing else
    assert build.budget.charged == 0
    assert max(web.calls.count(c) for c in web.calls) == 3


def test_budget_never_exceeds_cap_with_many_urls():
    pages = {f"https://site{i}.test/p": "Nothing here." for i in range(60)}
    web = FakeWeb(pages=pages)
    build = Build(DOMAIN, web)
    run(build)
    assert web.count("extract") == (80 - 8 - 25) // 3      # rendered pages, 3 units each
    assert web.count("research") == 1
    assert build.budget.charged == 8 + 25 + 15 * 3 <= 80
    assert build.unreached == 60 - 15


def test_lost_calls_are_charged_and_not_retried():
    web = FakeWeb(lost=lambda m, a: m == "extract")
    build = Build(DOMAIN, web)
    run(build)
    assert web.count("extract") == len(PAGES)
    assert build.budget.charged == 8 + 25 + 3 * len(PAGES)


def test_research_runs_once_beside_the_searches():
    pages = dict(PAGES)
    pages["https://acme-robotics.test/legal"] = "The legal name is Acme Robotics, Inc. today."
    web = FakeWeb(pages=pages)
    fields = run(Build(DOMAIN, web))
    assert web.count("research") == 1
    methods = [m for m, _ in web.calls]
    assert methods.index("research") < methods.index("extract")  # started before extracts
    assert all(f["status"] == "known" for f in fields.values())


def test_claim_pages_are_read_and_claims_are_never_candidates():
    pages = dict(PAGES)
    pages["https://registry.test/acme"] = (
        "Kind: filing\n\nThe registered name is Acme Robotics, Inc. for all filings.")
    pages["https://other.test/x"] = "Acme Robotics CEO: Sam Ortiz."
    claims = [  # the first claim's excerpt does not support it; its page still counts
        ("legal_name", "https://registry.test/acme", "Acme makes robots."),
        ("ceo", "https://other.test/x", "Acme Robotics chief executive Lee Park spoke.")]
    web = FakeWeb(pages=pages, claims=claims,
                  hidden={"https://registry.test/acme", "https://other.test/x"})
    fields = run(Build(DOMAIN, web))
    assert fields["legal_name"]["value"] == "Acme Robotics, Inc."
    assert fields["legal_name"]["candidates"][0]["kind"] == "filing"
    ceo_values = {c["value"] for c in fields["ceo"]["candidates"]}
    assert ceo_values == {"Dana Ruiz", "Sam Ortiz"}           # never the claim's "Lee Park"
    assert fields["ceo"]["status"] == "contested"
    assert fields["ceo"]["value"] == "Dana Ruiz"              # own site outranks aggregator
    rendered = [a for m, a in web.calls if m == "extract"]
    assert set(rendered[:2]) == {"https://registry.test/acme", "https://other.test/x"}


def test_render_order_prefers_stated_snippets_then_own_host():
    from app.build import render_order
    results = [("https://z.test/a", ""), ("https://acme-robotics.test/b", ""),
               ("https://b.test/c", "Acme Robotics was founded in 2014."),
               ("https://a.test/d", "")]
    assert render_order(results, DOMAIN) == [
        "https://b.test/c", "https://acme-robotics.test/b", "https://a.test/d",
        "https://z.test/a"]


def test_rate_limit_gets_three_retries_and_its_waits_are_not_build_time():
    web = FakeWeb(refuse=lambda m, a, n: 429 if (m == "search" and a == DOMAIN and n <= 3)
                  else False)
    build = Build(DOMAIN, web)
    fields = run(build)
    assert web.calls.count(("search", DOMAIN)) == 4
    assert fields["ceo"]["value"] == "Dana Ruiz"
    assert build.elapsed() > 3 * 1.05
    assert build.effective_elapsed() < 1.0


def test_other_refusals_get_two_retries():
    web = FakeWeb(refuse=lambda m, a, n: 500 if m == "search" and a == DOMAIN else False)
    run(Build(DOMAIN, web))
    assert web.calls.count(("search", DOMAIN)) == 3


def test_candidates_carry_build_time_kind_and_publication():
    pages = {"https://news.test/a": "Kind: news\nPublished: 2026-01-10T00:00:00Z\n\n"
                                    "Acme Robotics was founded in 2014."}
    fields = run(Build(DOMAIN, FakeWeb(pages=pages),
                       retrieved_at="2026-03-01T09:00:00+00:00"))
    [candidate] = fields["founded_year"]["candidates"]
    assert candidate == {"value": 2014, "url": "https://news.test/a",
                         "excerpt": "Acme Robotics was founded in 2014.", "provider": "nimble",
                         "kind": "news", "published_at": "2026-01-10T00:00:00+00:00",
                         "retrieved_at": "2026-03-01T09:00:00+00:00", "selected": True}


def test_citations_come_from_served_text():
    fields = run(Build(DOMAIN, FakeWeb()))
    for field in fields.values():
        for c in field["citations"]:
            assert c["provider"] == "nimble"
            assert c["excerpt"] in " ".join(PAGES[c["url"]].split())


def test_throttled_first_attempts_still_ready_within_ten_seconds():
    """Every call's first attempt is refused; every answer takes 0.9 s (R127)."""
    web = FakeWeb(delay=0.9, refuse=lambda m, a, n: n == 1)
    began = time.monotonic()
    fields = run(Build(DOMAIN, web))
    assert time.monotonic() - began < 10
    assert fields is not None and fields["ceo"]["value"] == "Dana Ruiz"
    assert web.calls.count(("search", DOMAIN)) == 2


def test_fast_regime_bound_with_two_refusals_and_many_urls():
    pages = {f"https://site{i}.test/p": "Nothing here." for i in range(60)}
    web = FakeWeb(pages=pages, delay=0.9,
                  refuse=lambda m, a, n: n < 3 or (m == "search" and a == DOMAIN))
    began = time.monotonic()
    run(Build(DOMAIN, web))
    assert time.monotonic() - began < 10


def test_reset_during_build_writes_nothing():
    async def scenario():
        store = Store()
        builds = Builds(store, web_factory=lambda: FakeWeb(delay=0.05))
        dossier = Dossier("d_1", DOMAIN)
        store.state.dossiers[DOMAIN] = dossier
        builds.start(dossier, None)
        store.replace(State())
        await asyncio.sleep(0.5)
        return store, dossier

    store, dossier = asyncio.run(scenario())
    assert store.state.dossiers == {}
    assert dossier.outcome == "failed" and dossier.researched_at is None


def test_budget_reservation():
    b = Budget(10)
    assert b.reserve(8) and not b.reserve(3)
    b.settle(8, charged=False)
    assert b.reserve(10) and b.remaining == 0
