"""The service clock (§3.4): system time until first set, then standing still."""
from __future__ import annotations

from datetime import datetime, timezone

from app.errors import invalid


def parse_rfc3339(raw) -> datetime:
    """An RFC 3339 timestamp with an explicit offset (`Z` or `±hh:mm`), else 422."""
    if not isinstance(raw, str) or "T" not in raw.upper():
        raise invalid("timestamp must be RFC 3339 with an explicit offset")
    text = raw[:-1] + "+00:00" if raw.endswith(("Z", "z")) else raw
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("timestamp must be RFC 3339 with an explicit offset") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise invalid("timestamp needs an explicit offset")
    return value


def format_time(value: datetime) -> str:
    return value.isoformat()


class Clock:
    def __init__(self) -> None:
        self._now: datetime | None = None

    def now(self) -> datetime:
        if self._now is None:
            return datetime.now(timezone.utc).replace(microsecond=0)
        return self._now

    def set(self, value: datetime) -> None:
        """Move the clock to ``value``; 422 when that is earlier than now."""
        if value < self.now():
            raise invalid("the clock cannot move back")
        self._now = value

    def reset_to(self, value: datetime) -> None:
        """Reset sets the clock to the fixture's ``now``, whatever it was."""
        self._now = value
