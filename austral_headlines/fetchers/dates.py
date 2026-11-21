"""Timestamp parsing helpers. A timestamp without an explicit offset is only
accepted if the source declares a `naive_tz`; otherwise it is unverifiable."""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo


def parse_datetime(value: str | None, naive_tz: str | None = None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    dt: datetime | None = None
    # ISO 8601 (handles "Z")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        dt = None
    if dt is None:
        try:
            dt = parsedate_to_datetime(s)  # RFC 822 (RSS)
        except (TypeError, ValueError, IndexError):
            dt = None
    if dt is None:
        return None
    if dt.tzinfo is None:
        if not naive_tz:
            return None
        dt = dt.replace(tzinfo=ZoneInfo(naive_tz))
    return dt.astimezone(timezone.utc)


def from_struct_time(st) -> datetime | None:
    """feedparser's *_parsed fields are already normalized to UTC."""
    if not st:
        return None
    return datetime.fromtimestamp(calendar.timegm(st), tz=timezone.utc)
