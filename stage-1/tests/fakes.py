"""A fake WebClient: scripted provider answers, with a log of every attempt."""
from __future__ import annotations

import asyncio

from app.web import CallOutcome, Claim, Page

DOMAIN = "acme-robotics.test"

PAGES = {
    "https://acme-robotics.test/about": (
        "Kind: own\nFacts: {\"ceo\": \"Dana Ruiz\"}\n\n"
        "Acme Robotics was founded in 2014. Acme Robotics is based in Lisbon, Portugal.\n"
        "Dana Ruiz has led Acme Robotics as chief executive since 2021."),
    "https://news.test/acme": (
        "Acme Robotics has raised $12M. Acme Robotics employs about 120 people."),
}


class FakeWeb:
    def __init__(self, pages=None, refuse=None, delay=0.0, claims=None, lost=None):
        self.pages = dict(PAGES if pages is None else pages)
        self.refuse = refuse or (lambda method, arg, attempt: False)
        self.lost = lost or (lambda method, arg: False)
        self.delay = delay
        self.claims = claims or []
        self.calls: list[tuple[str, str]] = []
        self._attempts: dict[tuple[str, str], int] = {}

    async def _answer(self, method: str, arg: str):
        self.calls.append((method, arg))
        attempt = self._attempts.get((method, arg), 0) + 1
        self._attempts[(method, arg)] = attempt
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.refuse(method, arg, attempt):
            return CallOutcome(ok=False, charged=False, refused=True)
        if self.lost(method, arg):
            return CallOutcome(ok=False, charged=True)
        return None

    async def search(self, query):
        return await self._answer("search", query) or CallOutcome(
            ok=True, charged=True, urls=list(self.pages))

    async def extract(self, url):
        failed = await self._answer("extract", url)
        if failed:
            return failed
        text = self.pages.get(url)
        return CallOutcome(ok=True, charged=True, pages=[Page(url, text)] if text else [])

    async def start_research(self, query, schema):
        return await self._answer("research", query) or CallOutcome(
            ok=True, charged=True, job="job")

    async def poll_research(self, job):
        return CallOutcome(ok=True, charged=False, done=True,
                           claims=[Claim(f, u, (e,)) for f, u, e in self.claims])

    def count(self, method):
        return sum(1 for m, _ in self.calls if m == method)
