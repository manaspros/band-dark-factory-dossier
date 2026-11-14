"""Page kind and publication time from header lines (stage 2)."""
import pytest

from app.candidates import from_page
from app.pages import page_kind, published_at

D = "acme-robotics.test"


@pytest.mark.parametrize("kind", ["own", "filing", "news", "aggregator"])
def test_listed_kinds(kind):
    # stage 4: `own` only for a page registered to the company's domain
    expected = "aggregator" if kind == "own" else kind
    assert page_kind("https://x.test/a", f"Kind: {kind}\n\nBody.", D) == expected
    assert page_kind(f"https://{D}/a", f"Kind: {kind}\n\nBody.", D) == kind


@pytest.mark.parametrize("url, text, kind", [
    ("https://acme-robotics.test/about", "Body.", "own"),
    ("https://WWW.Acme-Robotics.TEST/about", "Kind: blog\n\nBody.", "own"),
    ("https://blog.acme-robotics.test/x", "Body.", "aggregator"),
    ("https://other.test/x", "Kind: News\n\nBody.", "aggregator"),   # case-sensitive kinds
    ("not a url", "Body.", "aggregator"),
])
def test_kind_falls_back_to_host(url, text, kind):
    assert page_kind(url, text, D) == kind


@pytest.mark.parametrize("text, expected", [
    ("Published: 2026-02-20T00:00:00Z\n\nBody.", "2026-02-20T00:00:00+00:00"),
    ("Kind: news\nPublished: 2026-02-20T10:00:00+02:00\n\nBody.", "2026-02-20T10:00:00+02:00"),
    ("Published: 2026-02-20\n\nBody.", None),
    ("Published: 2026-02-20T00:00:00\n\nBody.", None),
    ("Body.\nPublished: 2026-02-20T00:00:00Z", None),                  # not a header line
    ("Kind: news\n\nPublished: 2026-02-20T00:00:00Z", None),           # after the header
])
def test_publication_time(text, expected):
    assert published_at(text) == expected


def test_page_candidates_one_per_value_first_excerpt():
    text = ("Kind: news\n\nAcme Robotics was founded in 2014. Acme Robotics was established "
            "in 2014 too. Acme Robotics CEO: Sam Ortiz. Dana Ruiz is the CEO of Acme Robotics.")
    found = from_page("https://news.test/a", text, "nimble", D, "2026-03-01T09:00:00+00:00")
    years = [c for c in found if c.field == "founded_year"]
    assert len(years) == 1 and years[0].excerpt == "Acme Robotics was founded in 2014."
    assert {c.value for c in found if c.field == "ceo"} == {"Sam Ortiz", "Dana Ruiz"}
    for c in found:
        assert c.excerpt in " ".join(text.split())
        assert c.kind == "news" and c.provider == "nimble"
