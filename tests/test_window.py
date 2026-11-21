from datetime import datetime, timedelta, timezone

import pytest

from austral_headlines.window import compute_window, is_business_day

RUNS = {"08:00": 5, "10:00": 2, "12:00": 2, "15:00": 3, "18:00": 3}


def utc(s):  # Montevideo = UTC-3 (no DST)
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize("utc_time,slot,hours", [
    ("2026-11-20 11:00", "08:00", 5),   # 08:00 MVD
    ("2026-11-20 13:05", "10:00", 2),   # 10:05 MVD
    ("2026-11-20 14:50", "12:00", 2),   # 11:50 MVD
    ("2026-11-20 18:02", "15:00", 3),   # 15:02 MVD
    ("2026-11-20 21:00", "18:00", 3),   # 18:00 MVD
    ("2026-11-20 16:40", "15:00", 3),   # 13:40 MVD: closer to 15:00 than 12:00
])
def test_nearest_slot_and_hours(utc_time, slot, hours):
    w = compute_window(RUNS, at=utc(utc_time))
    assert w.slot == slot
    assert w.hours == hours
    assert w.end_utc == utc(utc_time)
    slot_utc = w.now_local.replace(hour=int(slot[:2]), minute=0).astimezone(timezone.utc)
    assert w.start_utc == min(w.end_utc, slot_utc) - timedelta(hours=hours)


def test_late_run_has_no_gap():
    # 12:00 slot started 40 min late by GitHub: window still begins at 10:00 MVD
    w = compute_window(RUNS, at=utc("2026-11-20 15:40"))  # 12:40 MVD
    assert w.slot == "12:00"
    assert w.start_utc == utc("2026-11-20 13:00")          # 10:00 MVD
    assert w.end_utc == utc("2026-11-20 15:40")


def test_early_run_window_is_last_n_hours():
    w = compute_window(RUNS, at=utc("2026-11-20 12:50"))  # 09:50 MVD
    assert w.end_utc - w.start_utc == timedelta(hours=2)


def test_minutes_from_slot_signed():
    w = compute_window(RUNS, at=utc("2026-11-20 12:50"))  # 09:50 MVD
    assert w.slot == "10:00"
    assert w.minutes_from_slot == pytest.approx(-10)


def test_forced_slot():
    w = compute_window(RUNS, at=utc("2026-11-20 16:00"), slot="08:00")
    assert w.hours == 5 and w.slot == "08:00"


def test_unknown_slot():
    with pytest.raises(ValueError):
        compute_window(RUNS, at=utc("2026-11-20 16:00"), slot="09:00")


def test_business_day():
    sat = compute_window(RUNS, at=utc("2026-11-21 13:00")).now_local
    fri = compute_window(RUNS, at=utc("2026-11-20 13:00")).now_local
    assert not is_business_day(sat)
    assert is_business_day(fri)


def test_local_date_crossing_midnight_utc():
    # 2026-11-21 00:30 UTC is still Friday 21:30 in Montevideo
    w = compute_window(RUNS, at=utc("2026-11-21 00:30"))
    assert w.now_local.day == 20 and w.slot == "18:00"


def test_empty_env_vars_fall_back_to_defaults(monkeypatch):
    # GitHub Actions passes unset `vars.*` as empty strings
    from austral_headlines.config import DEFAULT_MODEL, load_settings

    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("ANTHROPIC_FALLBACKS", "")
    monkeypatch.setenv("OUTPUT_DIR", "")
    s = load_settings()
    assert s.model == DEFAULT_MODEL and s.fallbacks == "default" and s.output_dir.name == "output"
