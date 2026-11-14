"""Unit costs (§9) and the per-build 80-unit cap."""
from __future__ import annotations

BUILD_CAP_UNITS = 80

# (provider, method, depth) -> units per call; extract is per URL requested.
_COSTS = {
    ("nimble", "search", "lite"): 1, ("nimble", "search", "fast"): 5,
    ("nimble", "search", "deep"): 15,
    ("tavily", "search", "lite"): 8, ("tavily", "search", "fast"): 16,
    ("tavily", "search", "deep"): 16,
    ("nimble", "extract", None): 1, ("tavily", "extract", None): 2,
    ("nimble", "render", None): 3,           # extract that loads the page in a browser
    ("nimble", "research", None): 25,
    ("kernel", "open", None): 0, ("browserbase", "open", None): 2,
    ("kernel", "page", None): 1, ("browserbase", "page", None): 1,
    ("browserbase", "browse", None): 4,
}
_PER_URL = ("extract", "render")


def cost_of(provider: str, method: str, depth: str | None = None, urls: int = 1) -> int:
    units = _COSTS[(provider, method, depth)]
    return units * urls if method in _PER_URL else units


class BatchBudget:
    """The shared budget of a batch's builds (stage-4 "Batches"): units reserved by them never
    exceed ``cap``. Once a reservation does not fit, the batch is ``exhausted`` and makes no
    further calls."""

    def __init__(self, cap: int) -> None:
        self.cap = cap
        self.reserved = 0     # settled charges plus calls in flight
        self.charged = 0
        self.held = 0         # claim-page holds of its builds (not spent)
        self.exhausted = False

    @property
    def available(self) -> int:
        return self.cap - self.reserved - self.held


class Budget:
    """Units are reserved before a call starts and settled when it ends.

    ``reserved`` (settled charges plus calls in flight) never exceeds the cap, so the
    build can never spend more than the cap whatever its calls turn out to cost.
    ``charged`` is what finished calls actually cost. A build in a batch also reserves from
    the batch's ``BatchBudget``. A hold sets units aside for later calls of this build
    (its claim pages) without spending them. ``on_change`` is told whenever ``reserved``
    changes, so the build can record its spending durably before the call is made.
    """

    def __init__(self, cap: int = BUILD_CAP_UNITS, parent: BatchBudget | None = None,
                 on_change=None) -> None:
        self.cap = cap
        self.parent = parent
        self.on_change = on_change or (lambda: None)
        self.reserved = 0
        self.charged = 0
        self.held = 0
        self.stopped_by_batch = False   # a call was refused because the batch ran out

    @property
    def remaining(self) -> int:
        """Units a further call could still reserve (from this build and its batch)."""
        own = self.cap - self.reserved - self.held
        return own if self.parent is None else min(own, self.parent.available)

    def _move(self, units: int) -> None:
        self.reserved += units
        if self.parent is not None:
            self.parent.reserved += units

    def reserve(self, units: int, use_hold: bool = False) -> bool:
        """Reserve ``units`` for a call (from this build's hold first when ``use_hold``)."""
        if self.parent is not None and self.parent.exhausted:
            self.stopped_by_batch = True
            return False
        if use_hold and self.held >= units:
            self.release_hold(units)
        if units > self.cap - self.reserved - self.held:
            return False
        if self.parent is not None and units > self.parent.available:
            self.parent.exhausted = True
            self.stopped_by_batch = True
            return False
        self._move(units)
        self.on_change()
        return True

    def settle(self, units: int, charged: bool) -> None:
        """End a reserved call: keep its units if it costs them, else release them."""
        if charged:
            self.charged += units
            if self.parent is not None:
                self.parent.charged += units
        else:
            self._move(-units)
            self.on_change()

    def hold(self, units: int) -> bool:
        """Set ``units`` aside when both levels can; never exhausts the batch."""
        if units > self.remaining:
            return False
        self.held += units
        if self.parent is not None:
            self.parent.held += units
        return True

    def release_hold(self, units: int | None = None) -> None:
        units = self.held if units is None else min(units, self.held)
        self.held -= units
        if self.parent is not None:
            self.parent.held -= units
