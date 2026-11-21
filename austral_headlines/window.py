"""Run-slot and time-window calculation (America/Montevideo reference)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class RunWindow:
    slot: str              # "10:00"
    hours: float
    start_utc: datetime
    end_utc: datetime
    now_local: datetime
    minutes_from_slot: float

    def describe(self) -> str:
        fmt = "%Y-%m-%d %H:%M UTC"
        if self.slot == "manual":
            return (f"manual run | last {self.hours:g}h | "
                    f"{self.start_utc.strftime(fmt)} → {self.end_utc.strftime(fmt)}")
        return (
            f"slot {self.slot} (Montevideo) | window {self.hours:g}h | "
            f"{self.start_utc.strftime(fmt)} → {self.end_utc.strftime(fmt)}"
        )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _slot_dt(local_now: datetime, slot: str) -> datetime:
    h, m = (int(x) for x in slot.split(":"))
    return local_now.replace(hour=h, minute=m, second=0, microsecond=0)


def nearest_slot(local_now: datetime, runs: dict[str, float]) -> tuple[str, float]:
    """Return (slot, signed minutes from slot) for the slot closest to local_now."""
    best = None
    for slot in runs:
        diff = (local_now - _slot_dt(local_now, slot)).total_seconds() / 60
        if best is None or abs(diff) < abs(best[1]):
            best = (slot, diff)
    assert best is not None, "no runs configured"
    return best


def compute_window(
    runs: dict[str, float],
    tz: str = "America/Montevideo",
    at: datetime | None = None,
    slot: str | None = None,
    hours: float | None = None,
) -> RunWindow:
    """Compute the strict look-back window.

    The window ends *now* (the actual run time) and starts `hours` before the
    scheduled slot time (or before now, if running early). Anchoring the start
    to the slot means a late start (e.g. GitHub Actions delays) never leaves a
    gap between consecutive runs.
    """
    end = (at or now_utc()).astimezone(timezone.utc)
    local_now = end.astimezone(ZoneInfo(tz))
    if hours is not None:  # manual run: simply the last N hours
        if hours <= 0:
            raise ValueError("hours must be positive")
        return RunWindow(slot="manual", hours=hours, start_utc=end - timedelta(hours=hours),
                         end_utc=end, now_local=local_now, minutes_from_slot=0.0)
    if slot is None:
        slot, diff = nearest_slot(local_now, runs)
    else:
        if slot not in runs:
            raise ValueError(f"unknown slot {slot!r}; configured: {list(runs)}")
        diff = (local_now - _slot_dt(local_now, slot)).total_seconds() / 60
    hours = runs[slot]
    anchor = min(end, _slot_dt(local_now, slot).astimezone(timezone.utc))
    return RunWindow(
        slot=slot,
        hours=hours,
        start_utc=anchor - timedelta(hours=hours),
        end_utc=end,
        now_local=local_now,
        minutes_from_slot=diff,
    )


def is_business_day(local_dt: datetime) -> bool:
    return local_dt.weekday() < 5
