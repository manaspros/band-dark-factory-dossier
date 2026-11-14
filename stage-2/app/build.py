"""One build of a dossier (§8 Builds), run as a background asyncio task.

Plan, all through Nimble (plans/stage-2-plan.md "Build strategy"):

A. At once: the lite searches (exactly one whose query is the bare normalised domain, one
   per field with that field's statement phrases, one for the company name) and one
   research run asking for all six fields.
B. When research has finished: a rendered extract (the browser text, 3 units) of every page
   a research claim cites, whether or not the claim holds; then rendered extracts of the
   search result pages in priority order (snippet already states a value, then the
   company's own host, then URL) until the 80-unit cap leaves no room for another. Pages
   the budget does not reach are logged as a count (documented budget limit DEV-S2).
C. Every rendered page becomes candidates (app.candidates); the selection rule decides
   each field (app.selection). Research claims never become candidates themselves.

Retries: only refused calls (an error status, free) are retried. A 429 gets up to 3
retries, each 1.05 s later, so the retry is past the provider's one-second repeat window;
that waiting does not count toward the 10 s bound. Other refusals get up to 2 retries
1.05 s apart. Lost calls (timeouts, connection failures) are charged and not retried.
While every attempt has answered within 1 s (the "fast regime"), no non-429 retry starts
after 8 s of build time, which keeps the build within 10 s (§8).

The build only writes to the store at the end, in one synchronous step, and only if no
reset or import replaced the state meanwhile (§3.3, §10).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from app.budget import Budget, cost_of
from app.candidates import from_page
from app.clock import format_time
from app.selection import Candidate, decide
from app.support import FIELDS, STATEMENT_PHRASES, candidates as supported, company_name
from app.web import PROVIDER, CallOutcome, WebClient

log = logging.getLogger("dossier.build")

RESEARCH_UNITS = cost_of(PROVIDER, "research")
SEARCH_UNITS = cost_of(PROVIDER, "search", "lite")
RENDER_UNITS = cost_of(PROVIDER, "render")

RETRY_SECONDS = 1.05                     # after a refusal, past the 1 s repeat window
MAX_RETRIES = 2                          # for refusals other than 429
MAX_RATE_LIMIT_RETRIES = 3               # a 429 is never given a 4th time in a row
FAST_ANSWER_SECONDS = 1.0                # an attempt slower than this ends the fast regime
FAST_RETRY_CUTOFF_SECONDS = 8.0          # in the fast regime, no retry starts after this
BUILD_DEADLINE_SECONDS = 270.0           # decide with what was gathered (300 s ceiling)
POLL_SECONDS_FAST, POLL_SECONDS_SLOW = 1.0, 2.0

SIX_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "legal_name": {"type": ["string", "null"]},
        "hq_city": {"type": ["string", "null"]},
        "ceo": {"type": ["string", "null"]},
        "founded_year": {"type": ["integer", "null"]},
        "headcount_range": {"type": ["string", "null"]},
        "funding_total": {"type": ["integer", "null"]},
    },
}


def field_queries(domain: str) -> list[str]:
    """One query per field: the domain plus that field's statement phrases."""
    return [f"{domain} {' '.join(STATEMENT_PHRASES[field])}" for field in FIELDS]


def research_query(domain: str) -> str:
    return f"Company profile of {domain}: {', '.join(FIELDS)}"


def _own_host(url: str, domain: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return False
    return host == domain


def render_order(results: list[tuple[str, str]], domain: str) -> list[str]:
    """Search result URLs in the order to read them: a snippet that already states a
    value first, then the company's own host, then by URL (code point)."""
    snippet_states = {}
    for url, snippet in results:
        snippet_states[url] = snippet_states.get(url, False) or bool(supported(snippet, domain))
    return sorted(snippet_states, key=lambda url: (not snippet_states[url],
                                                   not _own_host(url, domain), url))


class Build:
    """The work of one build; ``run`` gathers evidence and returns the decided fields."""

    def __init__(self, domain: str, web: WebClient, budget: Budget | None = None,
                 retrieved_at: str | None = None) -> None:
        self.domain = domain
        self.web = web
        self.budget = budget or Budget()
        self.retrieved_at = retrieved_at
        self.succeeded = False       # some provider call succeeded
        self.fast = True             # every attempt so far answered within 1 s
        self.candidates: list[Candidate] = []
        self.unreached = 0           # search pages the budget did not reach (DEV-S2)
        self._started = time.monotonic()
        self._rate_limit_waits: list[tuple[float, float]] = []

    # ------------------------------------------------------------------ clock

    def elapsed(self) -> float:
        return time.monotonic() - self._started

    def effective_elapsed(self) -> float:
        """Build time without the time spent waiting to retry after a 429 (stage-2 rate
        limits): overlapping waits of concurrent calls are counted once."""
        waited, covered_until = 0.0, float("-inf")
        for start, end in sorted(self._rate_limit_waits):
            start = max(start, covered_until)
            if end > start:
                waited += end - start
            covered_until = max(covered_until, end)
        return self.elapsed() - waited

    async def _wait_after_rate_limit(self) -> None:
        began = time.monotonic()
        await asyncio.sleep(RETRY_SECONDS)
        self._rate_limit_waits.append((began, time.monotonic()))

    # ------------------------------------------------------------------ calls

    async def _attempt(self, units: int, call: Callable[[], Awaitable[CallOutcome]]):
        if not self.budget.reserve(units):
            return None
        began = time.monotonic()
        try:
            outcome = await call()
        except asyncio.CancelledError:   # the answer never arrives: charged (§9)
            self.budget.settle(units, charged=True)
            raise
        if time.monotonic() - began > FAST_ANSWER_SECONDS:
            self.fast = False
        self.budget.settle(units, charged=outcome.charged)
        if outcome.ok:
            self.succeeded = True
        return outcome

    async def call(self, units: int, call: Callable[[], Awaitable[CallOutcome]]):
        """Make one call, retrying refusals per the policy above. None if never made."""
        outcome, retries, rate_limit_retries = None, 0, 0
        while True:
            result = await self._attempt(units, call)
            if result is None:
                return outcome
            outcome = result
            if outcome.ok or not outcome.refused:
                return outcome
            if outcome.rate_limited:
                if rate_limit_retries >= MAX_RATE_LIMIT_RETRIES:
                    return outcome
                rate_limit_retries += 1
                await self._wait_after_rate_limit()
                continue
            if retries >= MAX_RETRIES or (
                    self.fast
                    and self.effective_elapsed() + RETRY_SECONDS > FAST_RETRY_CUTOFF_SECONDS):
                return outcome
            retries += 1
            await asyncio.sleep(RETRY_SECONDS)

    # ------------------------------------------------------------------ phases

    def queries(self) -> list[str]:
        return [self.domain, *field_queries(self.domain), company_name(self.domain)]

    async def search_all(self) -> list[tuple[str, str]]:
        """The lite searches, at once: every (url, snippet) they return."""
        outcomes = await asyncio.gather(*(
            self.call(SEARCH_UNITS, lambda q=q: self.web.search(q)) for q in self.queries()))
        return [r for o in outcomes if o and o.ok for r in o.results]

    async def research_urls(self) -> list[str]:
        """Run research for all six fields; the distinct URLs its claims cite."""
        started = await self.call(RESEARCH_UNITS, lambda: self.web.start_research(
            research_query(self.domain), SIX_FIELD_SCHEMA))
        if started is None or not started.ok:
            return []
        while self.elapsed() < BUILD_DEADLINE_SECONDS:
            polled = await self.web.poll_research(started.job)
            if polled.done:
                urls = [claim.url for claim in polled.claims if claim.field in FIELDS]
                return list(dict.fromkeys(urls))
            if polled.rate_limited:   # polls are free; wait past the 429 window, off the clock
                await self._wait_after_rate_limit()
            else:
                await asyncio.sleep(POLL_SECONDS_FAST if self.fast else POLL_SECONDS_SLOW)
        return []

    async def render_all(self, urls: list[str]) -> None:
        """Read the pages' browser text at once and turn each into candidates."""
        async def one(url: str) -> None:
            outcome = await self.call(RENDER_UNITS, lambda: self.web.extract_rendered(url))
            for page in (outcome.pages if outcome and outcome.ok else []):
                self.candidates.extend(from_page(page.url, page.text, PROVIDER, self.domain,
                                                 self.retrieved_at))

        await asyncio.gather(*(one(url) for url in urls))

    async def gather(self) -> None:
        research = asyncio.create_task(self.research_urls())
        results = await self.search_all()
        claim_urls = await research
        await self.render_all(claim_urls)
        remaining = [url for url in render_order(results, self.domain) if url not in claim_urls]
        affordable = self.budget.remaining // RENDER_UNITS
        self.unreached = max(0, len(remaining) - affordable)
        if self.unreached:
            log.info("budget limit: %d search pages not read", self.unreached)
        await self.render_all(remaining[:affordable])

    async def run(self) -> dict | None:
        """Gather within the deadline; the decided fields, or None if the build failed."""
        try:
            await asyncio.wait_for(self.gather(), timeout=BUILD_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            log.warning("build hit its deadline; deciding with what it has")
        except Exception:  # noqa: BLE001 - a build never takes the service down
            log.exception("build stopped early")
        return decide(self.candidates) if self.succeeded else None


class Builds:
    """Starts builds and commits their results to the store."""

    def __init__(self, store, web_factory: Callable[[], WebClient] = WebClient) -> None:
        self.store = store
        self.web_factory = web_factory
        self._web: WebClient | None = None
        self._tasks: set[asyncio.Task] = set()
        self.started_count = 0

    def start(self, dossier, build_time) -> None:
        """Start a build of ``dossier``; call inside the request's critical section."""
        if self._web is None:
            self._web = self.web_factory()
        retrieved_at = format_time(build_time) if build_time is not None else None
        build = Build(dossier.domain, self._web, retrieved_at=retrieved_at)
        dossier.build = build
        self.started_count += 1
        task = asyncio.create_task(self._run(dossier, build, build_time, self.store.generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, dossier, build: Build, build_time, generation: int) -> None:
        fields = None
        try:
            fields = await build.run()
        finally:
            self._commit(dossier, build, fields, build_time, generation)

    def _commit(self, dossier, build: Build, fields, build_time, generation: int) -> None:
        current = self.store.state.dossiers.get(dossier.domain)
        if self.store.generation != generation or current is not dossier:
            return  # state was reset or imported meanwhile: write nothing
        dossier.spent_units += build.budget.charged
        dossier.build = None
        if fields is None:
            dossier.outcome = "failed"
        else:
            dossier.fields = fields
            dossier.outcome = "ready"
            dossier.researched_at = format_time(build_time)
