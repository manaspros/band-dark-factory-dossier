"""The only module that talks to providers, always through WebRouter (§2 Web access).

Every call goes to the ``nimble`` provider. ``NIMBLE_API_KEY`` and ``NIMBLE_BASE_URL`` are
read from the environment by WebRouter and the Nimble SDK; this module never reads or
logs them. SDK retries are off so that every attempt is one billable call the build can
see and account for (§9).

Each call returns a ``CallOutcome`` that says whether it succeeded and whether it costs
units: a call the provider refuses with an error status costs nothing (a 429 is flagged
separately, since it is retried differently); a call whose answer never arrives (timeout,
connection failure) or that fails for any other reason is charged in full, which can only
over-count, never exceed the budget.

Page text comes only from Nimble's rendered extract: the text a browser shows once the
page has loaded, with no control activated (stage-2 "Page text").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PROVIDER = "nimble"
CALL_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class Page:
    """Text a provider served for ``url``."""
    url: str
    text: str


@dataclass(frozen=True)
class Claim:
    """A research claim: the field it backs and the excerpts cited for it."""
    field: str
    url: str
    excerpts: tuple[str, ...]


@dataclass
class CallOutcome:
    ok: bool
    charged: bool
    refused: bool = False
    rate_limited: bool = False                       # refused with 429
    results: list[tuple[str, str]] = field(default_factory=list)  # (url, snippet), ranked
    pages: list[Page] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    job: Any = None                                  # research job handle
    done: bool = False                               # research finished (ok or not)


def _sdk_error(exc: BaseException) -> BaseException:
    """The innermost SDK/HTTP exception behind a WebRouter error."""
    seen = set()
    while id(exc) not in seen:
        seen.add(id(exc))
        inner = getattr(exc, "original", None) or exc.__cause__
        if inner is None:
            return exc
        exc = inner
    return exc


def _status_code(exc: BaseException) -> int | None:
    status = getattr(_sdk_error(exc), "status_code", None)
    return status if isinstance(status, int) else None


def classify_failure(exc: BaseException, method: str) -> CallOutcome:
    """A failed call: refused (error status, free) or lost/unknown (charged).

    For extract, only 429 and 5xx count as refusals: a URL the provider answers with
    no page costs its units whatever status says so (§9).
    """
    status = _status_code(exc)
    refused = status is not None and status >= 400
    if method == "extract" and refused and not (status == 429 or status >= 500):
        refused = False
    return CallOutcome(ok=False, charged=not refused, refused=refused,
                       rate_limited=refused and status == 429)


class WebClient:
    """Thin async adapter over ``web_router.AsyncWebRouter`` for the build."""

    def __init__(self) -> None:
        self._router = None

    def _get_router(self):
        if self._router is None:
            from web_router import AsyncWebRouter  # imported lazily: never at startup

            self._router = AsyncWebRouter(PROVIDER, provider_config={
                PROVIDER: {"max_retries": 0, "timeout": CALL_TIMEOUT_SECONDS}})
        return self._router

    async def search(self, query: str) -> CallOutcome:
        try:
            response = await self._get_router().search(
                query, provider=PROVIDER, search_depth="lite", max_results=10)
        except Exception as exc:  # noqa: BLE001 - every failure is classified
            return classify_failure(exc, "search")
        return CallOutcome(ok=True, charged=True, results=[
            (r.url, r.description or "") for r in response.results if r.url])

    async def extract_rendered(self, url: str) -> CallOutcome:
        """The text a browser shows once ``url`` has loaded (3 units, §9 stage 2)."""
        try:
            response = await self._get_router().extract(
                url, provider=PROVIDER, format="markdown", provider_options={"render": True})
        except Exception as exc:  # noqa: BLE001
            return classify_failure(exc, "extract")
        pages = [Page(d.url or url, d.content) for d in response.documents if d.content]
        return CallOutcome(ok=True, charged=True, pages=pages)

    async def start_research(self, query: str, schema: dict) -> CallOutcome:
        try:
            job = await self._get_router().submit_research(
                query, provider=PROVIDER, output_schema=schema)
        except Exception as exc:  # noqa: BLE001
            return classify_failure(exc, "research")
        return CallOutcome(ok=True, charged=True, job=job)

    async def poll_research(self, job) -> CallOutcome:
        """One status check of a research run (free). ``done`` once it has finished.

        A failed poll is retried by the caller; a 429 is flagged so that the retry waits
        past the provider's one-second repeat window.
        """
        try:
            progress = await job.astatus()
        except Exception as exc:  # noqa: BLE001
            refusal = classify_failure(exc, "research")
            return CallOutcome(ok=False, charged=False, refused=refusal.refused,
                               rate_limited=refusal.rate_limited)
        if not progress.is_terminal:
            return CallOutcome(ok=True, charged=False)
        if progress.response is None:
            return CallOutcome(ok=False, charged=False, done=True)
        return CallOutcome(ok=True, charged=False, done=True,
                           claims=claims_from(progress.response.citations))


def claims_from(citations) -> list[Claim]:
    """Research citations that back a field (`$.<field>`), with every excerpt they carry."""
    claims = []
    for citation in citations:
        path = citation.field or ""
        if not path.startswith("$."):
            continue
        excerpts = citation.extra.get("excerpts") if isinstance(citation.extra, dict) else None
        if not isinstance(excerpts, list) or not excerpts:
            excerpts = [citation.snippet] if citation.snippet else []
        texts = tuple(e for e in excerpts if isinstance(e, str) and e.strip())
        if citation.url and texts:
            claims.append(Claim(path[2:], citation.url, texts))
    return claims
