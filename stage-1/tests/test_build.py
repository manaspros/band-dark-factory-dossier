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
    assert time.monotonic() - began < 2
    assert build.budget.charged == 0
    assert max(web.calls.count(c) for c in web.calls) == 3


def test_budget_never_exceeds_cap_with_many_urls():
    pages = {f"https://site{i}.test/p": "Nothing here." for i in range(60)}
    web = FakeWeb(pages=pages)
    build = Build(DOMAIN, web)
    run(build)
    assert build.budget.charged <= 80
    assert web.count("extract") == 80 - 8 - 25
    assert web.count("research") == 1
    assert build.budget.charged == 80


def test_lost_calls_are_charged_and_not_retried():
    web = FakeWeb(lost=lambda m, a: m == "extract")
    build = Build(DOMAIN, web)
    run(build)
    assert web.count("extract") == len(PAGES)
    assert build.budget.charged == 8 + len(PAGES) + 25


def test_research_skipped_when_every_field_known():
    pages = dict(PAGES)
    pages["https://acme-robotics.test/legal"] = "The legal name is Acme Robotics, Inc. today."
    web = FakeWeb(pages=pages)
    fields = run(Build(DOMAIN, web))
    assert web.count("research") == 0
    assert all(f["status"] == "known" for f in fields.values())


def test_research_claim_counts_only_when_supported():
    claims = [("legal_name", "https://registry.test/acme", "Acme Robotics's legal name is "
                                                           "Acme Robotics, Inc. here."),
              ("ceo", "https://x.test", "The boss is Sam Ortiz.")]
    fields = run(Build(DOMAIN, FakeWeb(claims=claims)))
    assert fields["legal_name"]["value"] == "Acme Robotics, Inc."
    assert fields["legal_name"]["citations"][0]["url"] == "https://registry.test/acme"
    assert fields["ceo"]["value"] == "Dana Ruiz"


def test_citations_come_from_served_text():
    fields = run(Build(DOMAIN, FakeWeb()))
    for field in fields.values():
        for c in field["citations"]:
            assert c["provider"] == "nimble"
            assert c["excerpt"] in " ".join(PAGES[c["url"]].split())


def test_fast_regime_ends_within_ten_seconds():
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
