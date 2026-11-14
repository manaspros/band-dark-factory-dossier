"""One build of a dossier (§8 Builds), run as a background asyncio task.

Plan, all through Nimble (plans/stage-2-plan.md "Build strategy", plans/stage-4-plan.md U5):

A. At once: the lite searches (exactly one whose query is the bare normalised domain, one
   per field with that field's statement phrases, one with the executive titles' phrases,
   one with the investors phrases, one for the company name; never the same query twice)
   and one research run asking for the six fields of §4 only. Research starts only when the
   build can also hold 18 units for the pages its claims cite (stage-4 plan F98).
B. When research has finished (or given up after 3 failed polls): a rendered extract (the
   browser text, 3 units) of every page a research claim cites; then rendered extracts of
   the search result pages in priority order (snippet already states a value, then the
   company's own host, then URL) until the budget leaves no room for another. Pages the
   budget does not reach are logged as a count (documented budget limit DEV-S2).
C. Every rendered page with candidates gets its origin (app.origins): its `Canonical`
   originals are fetched, at most three hops, once per URL per build. Every URL is read at
   most once, and a URL that cannot be a page (not http(s), no valid host) never is.
D. Every rendered page becomes candidates (app.candidates); the fields are decided from
   them (app.fields). Research claims never become candidates themselves.

Retries: only refused calls (an error status, free) are retried. A 429 gets up to 3
retries, each 1.05 s later, so the retry is past the provider's one-second repeat window;
that waiting does not count toward the 10 s bound. Other refusals get up to 2 retries
1.05 s apart. Lost calls (timeouts, connection failures) are charged and not retried.
While every attempt has answered within 1 s (the "fast regime"), no call, retry or research
poll starts after 8 s of build time, which keeps the build within 10 s (§8).

Spending: every call reserves its units first, from the build's cap (80, or its share of a
batch) and from its batch's budget (app.budget); the build's reservations are written
durably before the call is made, so a restart can count them (stage-4 "Restarts").

The build writes its result at the end, in one synchronous step and one database
transaction (app.commit), and only if no reset or import replaced the state meanwhile
(§3.3, §10). A build cut short by a stop is ended `failed` at the next start, with the units
it had reserved (app.commit.recover_interrupted).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from app.budget import BUILD_CAP_UNITS, Budget, cost_of
from app.candidates import from_page
from app.clock import format_time
from app.commit import record_build
from app.fields import decide
from app.origins import Served, resolve
from app.pages import _host_domain, lineage, page_true_from, published_at
from app.selection import Candidate
from app.support import (FIELDS, STATEMENT_PHRASES, TITLE_PHRASES, candidates as supported,
                         company_name)
from app.web import PROVIDER, CallOutcome, Page, WebClient

log = logging.getLogger("dossier.build")

RESEARCH_UNITS = cost_of(PROVIDER, "research")
SEARCH_UNITS = cost_of(PROVIDER, "search", "lite")
RENDER_UNITS = cost_of(PROVIDER, "render")

RETRY_SECONDS = 1.05                     # after a refusal, past the 1 s repeat window
MAX_RETRIES = 2                          # for refusals other than 429
MAX_RATE_LIMIT_RETRIES = 3               # a 429 is never given a 4th time in a row
FAST_ANSWER_SECONDS = 1.0                # an attempt slower than this ends the fast regime
FAST_RETRY_CUTOFF_SECONDS = 8.0          # in the fast regime, no call starts after this
BUILD_DEADLINE_SECONDS = 270.0           # decide with what was gathered (300 s ceiling)
POLL_SECONDS_FAST, POLL_SECONDS_SLOW = 1.0, 2.0
MAX_FAILED_POLLS = 3                     # then research is given up (stage-4 provider failure)
CLAIM_RESERVE_UNITS = 6 * RENDER_UNITS   # research asks six fields: up to 6 claim pages

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


def executives_query(domain: str) -> str:
    """The domain plus every executive title's statement phrases (lead ruling: one lite
    search for executive pages; research still asks for the six fields only)."""
    phrases = [p for title in TITLE_PHRASES.values() for p in title]
    lowercase = [p for p in phrases if not p.isupper()]
    return f"{domain} {' '.join(lowercase + [p for p in phrases if p.isupper()])}"


def investors_query(domain: str) -> str:
    """Investors come only from pages (research never asks for them)."""
    return f"{domain} investors backed by led by"


def research_query(domain: str) -> str:
    return f"Company profile of {domain}: {', '.join(FIELDS)}"


def _own_host(url: str, domain: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return False
    return host == domain


def readable(url: str) -> bool:
    """Whether a provider could serve a page at ``url`` (http(s), with a valid host)."""
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme in ("http", "https") and _host_domain(url) is not None


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
                 retrieved_at: str | None = None, batch_id: str | None = None) -> None:
        self.domain = domain
        self.web = web
        self.budget = budget or Budget()
        self.retrieved_at = retrieved_at
        self.batch_id = batch_id
        self.succeeded = False       # some provider call succeeded
        self.fast = True             # every attempt so far answered within 1 s
        self.candidates: list[Candidate] = []
        self.pages: dict[str, str | None] = {}   # url -> true_from of every evidence page
        self.unreached = 0           # search pages the budget did not reach (DEV-S2)
        self._started = time.monotonic()
        self._rate_limit_waits: list[tuple[float, float]] = []
        self._extracts: dict[str, asyncio.Future] = {}   # url -> pages served (one call)
        self._read: set[str] = set()                     # page URLs taken as evidence
        self._origins: list[asyncio.Future] = []         # pending origin resolutions

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

    def past_guard(self) -> bool:
        """In the fast regime, no call starts after 8 s of build time (§8's 10 s bound)."""
        return self.fast and self.effective_elapsed() > FAST_RETRY_CUTOFF_SECONDS

    async def _wait_after_rate_limit(self) -> None:
        began = time.monotonic()
        await asyncio.sleep(RETRY_SECONDS)
        self._rate_limit_waits.append((began, time.monotonic()))

    # ------------------------------------------------------------------ calls

    async def _attempt(self, units: int, call: Callable[[], Awaitable[CallOutcome]],
                       use_hold: bool = False):
        # The reservation (written durably through the budget's on_change) and the send are
        # adjacent: nothing is awaited between them.
        if self.past_guard() or not self.budget.reserve(units, use_hold):
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

    async def call(self, units: int, call: Callable[[], Awaitable[CallOutcome]],
                   use_hold: bool = False):
        """Make one call, retrying refusals per the policy above. None if never made."""
        outcome, retries, rate_limit_retries = None, 0, 0
        while True:
            result = await self._attempt(units, call, use_hold)
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

    # ------------------------------------------------------------------ pages

    def _extract(self, url: str, use_hold: bool = False) -> asyncio.Future:
        """The pages a rendered extract of ``url`` serves: one call per URL per build, shared
        by every reader, and found again under the URL it was served at."""
        future = self._extracts.get(url)
        if future is None:
            future = asyncio.ensure_future(self._fetch(url, use_hold))
            self._extracts[url] = future
        return future

    async def _fetch(self, url: str, use_hold: bool) -> list[Page]:
        outcome = await self.call(RENDER_UNITS, lambda: self.web.extract_rendered(url),
                                  use_hold)
        pages = outcome.pages if outcome and outcome.ok else []
        for page in pages:
            self._extracts.setdefault(page.url, self._extracts[url])
        return pages

    async def read(self, url: str, use_hold: bool = False) -> None:
        """Read ``url`` as evidence: its candidates, once their page's origin is known."""
        if not readable(url):
            return
        for page in await self._extract(url, use_hold):
            if page.url in self._read:
                continue
            self._read.add(page.url)
            self.pages.setdefault(page.url, page_true_from(page.text, published_at(page.text)))
            found = from_page(page.url, page.text, PROVIDER, self.domain, self.retrieved_at)
            if found:   # originals are fetched only for a page with candidates (D4-3)
                self._origins.append(asyncio.ensure_future(self._with_origin(page, found)))

    async def _with_origin(self, page: Page, found: list[Candidate]) -> None:
        origin = await resolve(lineage(page.url, page.text), self.domain, self._original)
        self.candidates.extend(replace(c, origin=origin) for c in found)

    async def _original(self, url: str) -> Served | None:
        """An original for rule 2, or None when no provider serves it (or it cannot be
        afforded, or the build is past its guard)."""
        if not readable(url):
            return None
        pages = await self._extract(url)
        return Served(lineage(pages[0].url, pages[0].text)) if pages else None

    # ------------------------------------------------------------------ phases

    def queries(self) -> list[str]:
        return list(dict.fromkeys([
            self.domain, *field_queries(self.domain), executives_query(self.domain),
            investors_query(self.domain), company_name(self.domain)]))

    async def search_all(self) -> list[tuple[str, str]]:
        """The lite searches, at once: every (url, snippet) they return."""
        outcomes = await asyncio.gather(*(
            self.call(SEARCH_UNITS, lambda q=q: self.web.search(q)) for q in self.queries()))
        return [r for o in outcomes if o and o.ok for r in o.results]

    async def research_urls(self) -> list[str]:
        """Run research for the six fields; the distinct URLs its claims cite. Research is
        skipped when the build cannot also hold units for its claim pages, and given up
        after 3 failed polls in a row or at the guard."""
        await asyncio.sleep(0)   # the searches (scheduled after this task) reserve first
        if (self.budget.remaining < RESEARCH_UNITS + CLAIM_RESERVE_UNITS
                or not self.budget.hold(CLAIM_RESERVE_UNITS)):
            return []
        started = await self.call(RESEARCH_UNITS, lambda: self.web.start_research(
            research_query(self.domain), SIX_FIELD_SCHEMA))
        if started is None or not started.ok:
            return []
        failed_polls = 0
        while self.elapsed() < BUILD_DEADLINE_SECONDS and not self.past_guard():
            polled = await self.web.poll_research(started.job)
            if polled.done:
                urls = [claim.url for claim in polled.claims if claim.field in FIELDS]
                return list(dict.fromkeys(urls))
            if polled.rate_limited:   # polls are free; wait past the 429 window, off the clock
                await self._wait_after_rate_limit()
            elif not polled.ok:
                failed_polls += 1
                if failed_polls >= MAX_FAILED_POLLS:
                    return []
                await asyncio.sleep(RETRY_SECONDS)
            else:
                failed_polls = 0
                await asyncio.sleep(POLL_SECONDS_FAST if self.fast else POLL_SECONDS_SLOW)
        return []

    async def gather(self) -> None:
        research = asyncio.create_task(self.research_urls())
        results = await self.search_all()
        claim_urls = await research
        await asyncio.gather(*(self.read(url, use_hold=True) for url in claim_urls))
        self.budget.release_hold()
        remaining = [url for url in render_order(results, self.domain)
                     if readable(url) and url not in self._extracts]
        pending_origins = sum(1 for task in self._origins if not task.done())
        affordable = max(0, self.budget.remaining // RENDER_UNITS - pending_origins)
        self.unreached = max(0, len(remaining) - affordable)
        if self.unreached:
            log.info("budget limit: %d search pages not read", self.unreached)
        await asyncio.gather(*(self.read(url) for url in remaining[:affordable]))
        await asyncio.gather(*self._origins)

    async def run(self) -> dict | None:
        """Gather within the deadline; the decided fields, or None if the build failed.

        A build ends `failed` only when none of its calls succeeded and its batch's budget
        did not stop it (lead ruling D4-10: a build the batch budget stopped is `ready`)."""
        try:
            await asyncio.wait_for(self.gather(), timeout=BUILD_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            log.warning("build hit its deadline; deciding with what it has")
        except Exception:  # noqa: BLE001 - a build never takes the service down
            log.exception("build stopped early")
        ready = self.succeeded or self.budget.stopped_by_batch
        return decide(self.candidates) if ready else None


class Builds:
    """Starts builds and commits their results to the store."""

    def __init__(self, store, web_factory: Callable[[], WebClient] = WebClient) -> None:
        self.store = store
        self.web_factory = web_factory
        self._web: WebClient | None = None
        self._tasks: set[asyncio.Task] = set()
        self.started_count = 0

    def start(self, dossier, build_time, writer, batch=None,
              cap: int = BUILD_CAP_UNITS) -> None:
        """Start a build of ``dossier``; call inside the request's critical section, with its
        open transaction ``writer`` (the build is recorded there as in flight)."""
        if self._web is None:
            self._web = self.web_factory()
        generation = self.store.generation
        retrieved_at = format_time(build_time) if build_time is not None else None
        build = Build(dossier.domain, self._web, retrieved_at=retrieved_at,
                      batch_id=batch.id if batch else None)
        build.budget = Budget(cap, batch.budget if batch else None,
                              on_change=lambda: self._record_spend(dossier, build, batch,
                                                                   generation))
        writer.put_running(dossier.id, format_time(build_time), build.batch_id)
        dossier.build = build
        self.started_count += 1
        task = asyncio.create_task(self._run(dossier, build, build_time, batch, generation))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _current(self, dossier, generation: int) -> bool:
        return (self.store.generation == generation
                and self.store.state.dossiers.get(dossier.domain) is dossier)

    def _record_spend(self, dossier, build: Build, batch, generation: int) -> None:
        """Write the build's (and its batch's) reserved units before the call is made."""
        if not self._current(dossier, generation):
            return
        with self.store.transaction() as writer:
            writer.set_running_spent(dossier.id, build.budget.reserved)
            if batch is not None:
                batch.spent_units = batch.budget.reserved
                writer.put_batch(batch)

    async def _run(self, dossier, build: Build, build_time, batch, generation: int) -> None:
        # A build cancelled because the service is stopping records nothing now: it stays in
        # flight on disk and is ended at the next start (app.commit.recover_interrupted).
        fields = await build.run()
        self._commit(dossier, build, fields, build_time, batch, generation)

    def _commit(self, dossier, build: Build, fields, build_time, batch,
                generation: int) -> None:
        if not self._current(dossier, generation):
            return  # state was reset or imported meanwhile: write nothing
        dossier.build = None
        ready = fields is not None
        with self.store.transaction() as writer:
            if batch is not None:
                batch.spent_units = batch.budget.reserved
            record_build(self.store.state, dossier, writer, format_time(build_time),
                         build.budget.charged,
                         build.candidates if ready else None,
                         [{"url": url, "true_from": tf} for url, tf in build.pages.items()],
                         batch)
