"""One build of a dossier (§8 Builds), run as a background asyncio task.

Plan, all through Nimble (plan "Search strategy and budget"):

1. Lite searches at once: exactly one whose query is the bare normalised domain, one per
   field (the domain plus that field's statement phrases) and one for the company name.
2. Extract every result URL at once, in rank order (domain query first), up to what the
   budget allows while keeping 25 units for a research run.
3. Evaluate every gathered page with Appendix A.
4. Only if some field is still unknown and 25 units remain: one Nimble research run
   asking for all six fields; each claim counts only where its excerpt supports it.

Retries (lead ruling L1/L2): only calls the provider refuses with an error status (free)
are retried, at most twice, 0.05 s then 0.15 s apart. Lost calls (timeouts, connection
failures) are charged and not retried. While every attempt has answered within 1 s (the
"fast regime"), no retry starts after 4 s, which keeps the build within 10 s (§8).

The build only writes to the store at the end, in one synchronous step, and only if no
reset or import replaced the state meanwhile (§3.3, §10).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Awaitable, Callable

from app.budget import Budget, cost_of
from app.clock import format_time
from app.evidence import Candidate, decide
from app.support import FIELDS, STATEMENT_PHRASES, MAX_EXCERPT_CHARS, candidates, collapse
from app.support import company_name, supports
from app.web import PROVIDER, CallOutcome, WebClient

log = logging.getLogger("dossier.build")

RESEARCH_UNITS = cost_of(PROVIDER, "research")
SEARCH_UNITS = cost_of(PROVIDER, "search", "lite")
EXTRACT_UNITS = cost_of(PROVIDER, "extract")

RETRY_BACKOFF_SECONDS = (0.05, 0.15)     # at most 2 retries, 0.2 s in total
FAST_ANSWER_SECONDS = 1.0                # an attempt slower than this ends the fast regime
FAST_RETRY_CUTOFF_SECONDS = 4.0          # in the fast regime, no retry starts after this
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


class Build:
    """The work of one build; ``run`` gathers evidence and returns the decided fields."""

    def __init__(self, domain: str, web: WebClient, budget: Budget | None = None) -> None:
        self.domain = domain
        self.web = web
        self.budget = budget or Budget()
        self.succeeded = False       # some provider call succeeded
        self.fast = True             # every attempt so far answered within 1 s
        self.candidates: list[Candidate] = []
        self._started = time.monotonic()

    # ------------------------------------------------------------------ calls

    def elapsed(self) -> float:
        return time.monotonic() - self._started

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
        outcome = None
        for attempt in range(1 + len(RETRY_BACKOFF_SECONDS)):
            if attempt:
                if not outcome.refused:
                    break
                backoff = RETRY_BACKOFF_SECONDS[attempt - 1]
                if self.fast and self.elapsed() + backoff > FAST_RETRY_CUTOFF_SECONDS:
                    break
                await asyncio.sleep(backoff)
            result = await self._attempt(units, call)
            if result is None:
                break
            outcome = result
            if outcome.ok:
                break
        return outcome

    # ------------------------------------------------------------------ phases

    async def search_all(self) -> list[str]:
        """The lite searches, at once; result URLs in priority order, deduplicated."""
        queries = [self.domain, *field_queries(self.domain), company_name(self.domain)]
        outcomes = await asyncio.gather(*(
            self.call(SEARCH_UNITS, lambda q=q: self.web.search(q)) for q in queries))
        urls: list[str] = []
        for outcome in outcomes:
            for url in (outcome.urls if outcome and outcome.ok else []):
                if url not in urls:
                    urls.append(url)
        return urls

    async def extract_all(self, urls: list[str]) -> None:
        """Extract the URLs at once, keeping enough budget for a research run."""
        allowance = max(0, self.budget.remaining - RESEARCH_UNITS) // EXTRACT_UNITS
        chosen = urls[:allowance]

        async def one(rank: int, url: str) -> None:
            outcome = await self.call(EXTRACT_UNITS, lambda: self.web.extract(url))
            for page in (outcome.pages if outcome and outcome.ok else []):
                for index, s in enumerate(candidates(page.text, self.domain)):
                    self.candidates.append(Candidate(s.field, s.value, page.url, s.excerpt,
                                                     PROVIDER, rank * 100_000 + index))

        await asyncio.gather(*(one(rank, url) for rank, url in enumerate(chosen)))

    def unknown_fields(self) -> set[str]:
        return set(FIELDS) - {c.field for c in self.candidates}

    async def research(self) -> None:
        """One research run for all six fields, polled until done or the deadline."""
        started = await self.call(RESEARCH_UNITS, lambda: self.web.start_research(
            research_query(self.domain), SIX_FIELD_SCHEMA))
        if started is None or not started.ok:
            return
        order = 10 ** 9
        while self.elapsed() < BUILD_DEADLINE_SECONDS:
            polled = await self.web.poll_research(started.job)
            if polled.done:
                for claim in polled.claims:
                    if claim.field not in FIELDS:
                        continue
                    for excerpt in claim.excerpts:
                        text = collapse(excerpt)
                        value = supports(text, claim.field, self.domain)
                        if value is not None and 1 <= len(text) <= MAX_EXCERPT_CHARS:
                            self.candidates.append(Candidate(claim.field, value, claim.url, text,
                                                             PROVIDER, order))
                            order += 1
                return
            await asyncio.sleep(POLL_SECONDS_FAST if self.fast else POLL_SECONDS_SLOW)

    async def gather(self) -> None:
        urls = await self.search_all()
        await self.extract_all(urls)
        if self.unknown_fields() and self.budget.remaining >= RESEARCH_UNITS:
            await self.research()

    async def run(self) -> dict | None:
        """Gather within the deadline; the decided fields, or None if the build failed."""
        try:
            await asyncio.wait_for(self.gather(), timeout=BUILD_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            log.warning("build of %s hit its deadline; deciding with what it has", self.domain)
        except Exception:  # noqa: BLE001 - a build never takes the service down
            log.exception("build of %s stopped early", self.domain)
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
        build = Build(dossier.domain, self._web)
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
