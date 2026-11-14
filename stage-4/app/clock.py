"""The service clock (§3.4): system time until first set, then standing still."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from app.errors import invalid


# RFC 3339 date-time: full date, `T`, hh:mm:ss, optional fraction, then `Z` or ±hh:mm.
_RFC3339 = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})")


def parse_rfc3339(raw) -> datetime:
    """An RFC 3339 timestamp with an explicit offset (`Z` or `±hh:mm`), else 422."""
    if not isinstance(raw, str) or not _RFC3339.fullmatch(raw):
        raise invalid("timestamp must be RFC 3339 with an explicit offset")
    text = raw.upper()
    text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(text)
    except ValueError:  # e.g. month 13 or second 60
        raise invalid("timestamp must be a valid RFC 3339 date and time") from None


def format_time(value: datetime) -> str:
    return value.isoformat()


class Clock:
    def __init__(self) -> None:
        self._now: datetime | None = None

    def now(self) -> datetime:
        if self._now is None:
            return datetime.now(timezone.utc).replace(microsecond=0)
        return self._now

    def check_set(self, value: datetime) -> None:
        """422 when ``value`` is earlier than now (the clock cannot move back)."""
        if value < self.now():
            raise invalid("the clock cannot move back")

    def set(self, value: datetime) -> None:
        """Move the clock to ``value``; 422 when that is earlier than now."""
        self.check_set(value)
        self._now = value

    def restore(self, saved: str | None) -> None:
        """The clock as last saved (app.db): standing at that time, or system time if unset."""
        self._now = parse_rfc3339(saved) if saved is not None else None

    def reset_to(self, value: datetime) -> None:
        """Reset sets the clock to the fixture's ``now``, whatever it was."""
        self._now = value
