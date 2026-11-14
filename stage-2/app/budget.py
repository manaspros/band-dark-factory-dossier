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
    ("nimble", "research", None): 25,
}


def cost_of(provider: str, method: str, depth: str | None = None, urls: int = 1) -> int:
    units = _COSTS[(provider, method, depth)]
    return units * urls if method == "extract" else units


class Budget:
    """Units are reserved before a call starts and settled when it ends.

    ``reserved`` (settled charges plus calls in flight) never exceeds the cap, so the
    build can never spend more than the cap whatever its calls turn out to cost.
    ``charged`` is what finished calls actually cost.
    """

    def __init__(self, cap: int = BUILD_CAP_UNITS) -> None:
        self.cap = cap
        self.reserved = 0
        self.charged = 0

    @property
    def remaining(self) -> int:
        return self.cap - self.reserved

    def reserve(self, units: int) -> bool:
        if units > self.remaining:
            return False
        self.reserved += units
        return True

    def settle(self, units: int, charged: bool) -> None:
        """End a reserved call: keep its units if it costs them, else release them."""
        if charged:
            self.charged += units
        else:
            self.reserved -= units
