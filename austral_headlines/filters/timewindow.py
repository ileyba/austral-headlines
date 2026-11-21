"""Strict publication-time window filter."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Candidate


def in_window(
    published: datetime | None,
    start_utc: datetime,
    end_utc: datetime,
    future_skew_minutes: float = 5,
) -> bool:
    """True only for timezone-aware timestamps inside [start, end + skew]."""
    if published is None or published.tzinfo is None:
        return False
    p = published.astimezone(timezone.utc)
    return start_utc <= p <= end_utc + timedelta(minutes=future_skew_minutes)


def filter_window(
    cands: list[Candidate],
    start_utc: datetime,
    end_utc: datetime,
    future_skew_minutes: float = 5,
    log=None,
) -> list[Candidate]:
    kept = []
    for c in cands:
        if in_window(c.published_utc, start_utc, end_utc, future_skew_minutes):
            kept.append(c)
        elif log:
            log.debug("drop (time %s outside window): %s", c.published_utc, c.url)
    return kept
