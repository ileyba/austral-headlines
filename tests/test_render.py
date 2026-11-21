import re
from datetime import datetime, timezone

from austral_headlines.models import Candidate
from austral_headlines.render import NO_NEWS, Headline, render, render_line

T = datetime(2026, 11, 20, 12, 7, tzinfo=timezone.utc)
LINE_RE = re.compile(r"^\*\*[^*]+\*\* – .+ – \d{2}:\d{2} UTC – [A-Z0-9/ .]+ – \[[^\]]+\]\(https?://\S+\)$")


def h(tag, url, importance=50, topic="Fed", **kw):
    cand = Candidate(title="t", url=url, source_tag=tag, published_utc=T, priority=1)
    return Headline(topic=topic, summary="Fed holds rates; signals two cuts in 2027.",
                    title_en="Fed holds rates steady", importance=importance, candidate=cand, **kw)


def test_empty_is_exact_line():
    assert render([]) == "No material news."
    assert NO_NEWS == "No material news."


def test_line_format():
    line = render_line(h("RTRS", "https://www.reuters.com/markets/fed"))
    assert line == ("**Fed** – Fed holds rates; signals two cuts in 2027 – 12:07 UTC – RTRS – "
                    "[Fed holds rates steady](https://www.reuters.com/markets/fed)")
    assert LINE_RE.match(line)


def test_ticker_topic_bold():
    line = render_line(h("BBG", "https://www.bloomberg.com/a", topic="FCX"))
    assert line.startswith("**FCX** – ")


def test_investing_bank_label_and_zh_unconfirmed():
    inv = render_line(h("INVESTING", "https://www.investing.com/a", bank="Goldman Sachs"))
    assert " – INVESTING/GOLDMAN SACHS – " in inv
    zh = render_line(h("ZH", "https://www.zerohedge.com/a", unconfirmed=True))
    assert "– unconfirmed (ZH): " in zh and " – ZH – " in zh


def test_order_and_cap():
    items = [h("RTRS", f"https://www.reuters.com/{i}", importance=i) for i in range(20)]
    out = render(items, max_items=15).splitlines()
    assert len(out) == 15
    assert "reuters.com/19)" in out[0]
    assert all(LINE_RE.match(line) for line in out)


def test_link_text_sanitized():
    x = h("FT", "https://www.ft.com/content/a")
    x.title_en = "Oil [update] jumps"
    assert "[Oil (update) jumps](https://www.ft.com/content/a)" in render_line(x)


def test_no_watchlist_prompt_and_categories(settings):
    from austral_headlines import summarizer as summ

    assert settings.raw["watchlist"] == []
    assert summ.WATCHLIST not in summ.categories(settings)
    prompt = summ.build_system(settings)
    assert "Company news is out of scope" in prompt and "Watchlist company" not in prompt
    assert "must NEVER be a company name or ticker" in prompt
