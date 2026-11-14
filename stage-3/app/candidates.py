"""Candidates from one page's browser text (stage-2 "Candidates", stage-3 "Executives").

Every value a page supports for a field is one candidate of that field for that page. Its
excerpt is the first sentence of the page (in page order) that supports that value. A value
supported for an executive title is a candidate of `executives` carrying that title. Every
candidate of a page has the page's `true_from` date.
"""
from __future__ import annotations

from app.executives import EXECUTIVES
from app.pages import page_kind, page_true_from, published_at
from app.selection import Candidate, value_key
from app.support import TITLES, candidates as supported


def from_page(url: str, text: str, provider: str, domain: str,
              retrieved_at: str | None) -> list[Candidate]:
    kind = page_kind(url, text, domain)
    published = published_at(text)
    true_from = page_true_from(text, published)
    found: dict[tuple[str, str], Candidate] = {}
    for support in supported(text, domain):
        key = (support.field, value_key(support.value))
        if key in found:
            continue
        title = support.field if support.field in TITLES else None
        found[key] = Candidate(EXECUTIVES if title else support.field, support.value, url,
                               support.excerpt, provider, kind, published, retrieved_at,
                               true_from=true_from, title=title)
    return list(found.values())
