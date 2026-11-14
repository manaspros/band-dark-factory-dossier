"""The origin of a page: the source behind it (stage-4 "Origins").

``resolve`` applies the four rules in order. Rule 2 follows the page's `Canonical` URL to its
original through ``fetch``, at most three hops from the starting page; the build supplies
``fetch`` (one rendered extract per URL, app.build). A fourth hop, or an original no provider
serves, gives the host of that URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from app.pages import Lineage, _host_domain

MAX_HOPS = 3


@dataclass(frozen=True)
class Served:
    """An original as a provider served it: at ``lineage.url``, which may differ from the
    URL requested (a redirect), and which is the original's own URL for the rules."""
    lineage: Lineage


Fetch = Callable[[str], Awaitable["Served | None"]]


def host_origin(url: str) -> str:
    """The host of ``url`` normalised, standing in for an original's origin."""
    return _host_domain(url) or url


async def resolve(page: Lineage, domain: str, fetch: Fetch, hops_left: int = MAX_HOPS) -> str:
    """The origin of ``page`` for the company at ``domain``."""
    if page.first_published_by:                                   # rule 1
        return page.first_published_by
    if page.canonical and page.canonical != page.url:             # rule 2
        if hops_left == 0:
            return host_origin(page.canonical)
        served = await fetch(page.canonical)
        if served is None:
            return host_origin(page.canonical)
        return await resolve(served.lineage, domain, fetch, hops_left - 1)
    if page.lookalike:                                            # rule 3
        return domain
    return page.registrant or host_origin(page.url)               # rule 4
