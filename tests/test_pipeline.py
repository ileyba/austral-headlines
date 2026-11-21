"""End-to-end run of main.run() with fetchers and Claude mocked out."""
from datetime import datetime, timedelta, timezone

import austral_headlines.main as m
import austral_headlines.summarizer as summ
from austral_headlines.models import Candidate
from austral_headlines.summarizer import Dup, Pick, Selection

NOW = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)  # 10:00 Montevideo, window 2h


def _cands():
    def c(title, url, minutes_ago, summary=""):
        return Candidate(title=title, url=url, published_utc=NOW - timedelta(minutes=minutes_ago),
                         ts_origin="feed", via="rss", summary=summary)
    return [
        c("Freeport cuts 2027 copper guidance after Grasberg outage", "https://www.reuters.com/a", 20),
        c("Freeport reduce guía de cobre", "https://www.infobae.com/a", 15),
        c("YPF aprueba inversión de US$2.000 millones en Vaca Muerta", "https://www.econojournal.com.ar/a", 40),
        c("Old story", "https://www.bloomberg.com/old", 60 * 24),              # outside window
        c("Mirror copy", "https://finance.yahoo.com/a", 10),                   # not allowed
        c("Goldman Sachs lifts gold forecast to $5,000", "https://www.investing.com/a", 30),
        c("Gold edges higher", "https://www.investing.com/b", 30),             # no bank → dropped
    ]


def test_pipeline(monkeypatch, tmp_path, settings, capsys):
    settings.output_dir = tmp_path
    monkeypatch.setattr(m, "load_settings", lambda _=None: settings)
    monkeypatch.setattr(m, "fetch_feeds", lambda s, e: _cands())
    monkeypatch.setattr(m, "fetch_sitemaps", lambda s, e: [])
    seen = {}

    def fake_select(s, cands, window):
        seen["titles"] = sorted(c.title for c in cands)
        ids = {c.url: c.id for c in cands}
        return Selection(
            headlines=[
                Pick(id=ids["https://www.reuters.com/a"], topic="FCX",
                     summary="Cuts 2027 copper guidance after Grasberg outage", title_en="Freeport cuts guidance",
                     importance=90, unconfirmed=False, bank=""),
                Pick(id=ids["https://www.infobae.com/a"], topic="FCX", summary="dup",
                     title_en="dup", importance=80, unconfirmed=False, bank=""),
                Pick(id=ids["https://www.econojournal.com.ar/a"], topic="YPF",
                     summary="Board approves $2bn Vaca Muerta investment", title_en="YPF approves $2bn Vaca Muerta spend",
                     importance=70, unconfirmed=False, bank=""),
                Pick(id=ids["https://www.investing.com/a"], topic="Gold",
                     summary="Goldman raises gold forecast on central-bank buying",
                     title_en="Goldman lifts gold forecast", importance=60, unconfirmed=False,
                     bank="Goldman Sachs"),
                Pick(id="c999", topic="X", summary="hallucinated id", title_en="x", importance=99,
                     unconfirmed=False, bank=""),
            ],
            duplicates=[Dup(id=ids["https://www.infobae.com/a"], duplicate_of=ids["https://www.reuters.com/a"])],
        )

    monkeypatch.setattr(summ, "select_headlines", fake_select)
    rc = m.run(m.parse_args(["--now", "--dry-run", "--no-search", "--at", NOW.isoformat()]))
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()

    assert "Old story" not in seen["titles"] and "Mirror copy" not in seen["titles"]
    assert "Gold edges higher" not in seen["titles"]
    assert len(out) == 3
    assert out[0].startswith("**FCX** – ") and "– RTRS – " in out[0] and "12:40 UTC" in out[0]
    assert out[1].startswith("**YPF** – ") and "– ECONOJOURNAL – " in out[1]
    assert "– INVESTING/GOLDMAN SACHS – " in out[2]
    assert not any("hallucinated" in line or "infobae" in line for line in out)
    files = list(tmp_path.glob("2026-11-20_1000.md"))
    assert files and "**FCX**" in files[0].read_text()


def test_pipeline_no_news(monkeypatch, tmp_path, settings, capsys):
    settings.output_dir = tmp_path
    monkeypatch.setattr(m, "load_settings", lambda _=None: settings)
    monkeypatch.setattr(m, "fetch_feeds", lambda s, e: _cands()[3:5])  # only old/mirror items
    monkeypatch.setattr(m, "fetch_sitemaps", lambda s, e: [])
    monkeypatch.setattr(summ, "select_headlines", lambda s, c, w: Selection(headlines=[], duplicates=[]))
    rc = m.run(m.parse_args(["--now", "--dry-run", "--no-search", "--at", NOW.isoformat()]))
    assert rc == 0
    assert capsys.readouterr().out.strip() == "No material news."
