"""Candidates from one page's browser text (stage-2 "Candidates").

Every value a page supports for a field is one candidate of that field for that page. Its
excerpt is the first sentence of the page (in page order) that supports that value.
"""
from __future__ import annotations

from app.pages import page_kind, published_at
from app.selection import Candidate, value_key
from app.support import candidates as supported


def from_page(url: str, text: str, provider: str, domain: str,
              retrieved_at: str | None) -> list[Candidate]:
    kind = page_kind(url, text, domain)
    published = published_at(text)
    found: dict[tuple[str, str], Candidate] = {}
    for support in supported(text, domain):
        key = (support.field, value_key(support.value))
        if key not in found:
            found[key] = Candidate(support.field, support.value, url, support.excerpt, provider,
                                   kind, published, retrieved_at)
    return list(found.values())
