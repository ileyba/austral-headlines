from datetime import datetime, timedelta, timezone

from austral_headlines.config import Source
from austral_headlines.fetchers.dates import parse_datetime
from austral_headlines.fetchers.page_meta import extract_published, extract_title
from austral_headlines.fetchers.rss import parse_feed
from austral_headlines.fetchers.sitemap import parse_news_sitemap
from austral_headlines.filters.timewindow import filter_window, in_window
from austral_headlines.models import Candidate

END = datetime(2026, 11, 20, 13, 0, tzinfo=timezone.utc)
START = END - timedelta(hours=2)


def test_in_window_bounds():
    assert in_window(END - timedelta(minutes=30), START, END)
    assert in_window(START, START, END)
    assert not in_window(START - timedelta(minutes=1), START, END)
    assert not in_window(END - timedelta(days=1), START, END)          # same hour, a day old
    assert in_window(END + timedelta(minutes=3), START, END, 5)        # small clock skew ok
    assert not in_window(END + timedelta(minutes=30), START, END, 5)


def test_missing_or_naive_timestamp_rejected():
    assert not in_window(None, START, END)
    assert not in_window(datetime(2026, 11, 20, 12, 0), START, END)    # naive


def test_filter_window():
    cands = [Candidate("a", "u1", published_utc=END - timedelta(hours=1)),
             Candidate("b", "u2", published_utc=END - timedelta(hours=3)),
             Candidate("c", "u3", published_utc=None)]
    assert [c.title for c in filter_window(cands, START, END)] == ["a"]


def test_parse_datetime_variants():
    assert parse_datetime("2026-11-20T12:30:00Z") == datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    assert parse_datetime("2026-11-20T09:30:00-03:00") == datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    assert parse_datetime("Fri, 20 Nov 2026 12:30:00 GMT") == datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    assert parse_datetime("2026-11-20 09:30:00") is None                        # naive → unverifiable
    assert parse_datetime("2026-11-20 09:30:00", "America/Argentina/Buenos_Aires") == \
        datetime(2026, 11, 20, 12, 30, tzinfo=timezone.utc)
    assert parse_datetime("yesterday") is None


def test_page_meta_priority():
    html = """<html><head>
    <meta property="article:modified_time" content="2026-11-20T12:59:00Z">
    <meta property="article:published_time" content="2026-11-20T11:15:00+00:00">
    <meta property="og:title" content="Chile central bank cuts rates">
    </head></html>"""
    assert extract_published(html) == datetime(2026, 11, 20, 11, 15, tzinfo=timezone.utc)
    assert extract_title(html) == "Chile central bank cuts rates"


def test_page_jsonld_and_time_tag():
    html = ('<script type="application/ld+json">{"@type":"NewsArticle",'
            '"datePublished":"2026-11-20T08:00:00-03:00"}</script>')
    assert extract_published(html) == datetime(2026, 11, 20, 11, 0, tzinfo=timezone.utc)
    assert extract_published('<time datetime="2026-11-20T10:00:00Z">x</time>') == \
        datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)
    assert extract_published("<html><body>No dates here</body></html>") is None


def test_rss_feed_timestamps_and_origlink():
    xml = """<?xml version="1.0"?><rss version="2.0" xmlns:feedburner="http://rssnamespace.org/feedburner/ext/1.0"><channel>
    <item><title>Fed holds</title><link>https://feedproxy.google.com/~r/x</link>
      <feedburner:origLink>https://www.zerohedge.com/markets/fed-holds</feedburner:origLink>
      <pubDate>Fri, 20 Nov 2026 12:00:00 +0000</pubDate></item>
    <item><title>No date</title><link>https://www.zerohedge.com/x</link></item>
    </channel></rss>"""
    items = parse_feed(xml, Source(tag="ZH", name="ZH", domains=["zerohedge.com"]))
    assert items[0].url == "https://www.zerohedge.com/markets/fed-holds"
    assert items[0].published_utc == datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
    assert items[1].published_utc is None


def test_news_sitemap():
    xml = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
      xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
      <url><loc>https://www.reuters.com/markets/a/</loc><news:news>
        <news:publication_date>2026-11-20T12:10:00Z</news:publication_date>
        <news:title>Copper hits record on Chile supply outage</news:title></news:news></url>
    </urlset>"""
    items = parse_news_sitemap(xml, Source(tag="RTRS", name="Reuters", domains=["reuters.com"]))
    assert items[0].title.startswith("Copper")
    assert items[0].published_utc == datetime(2026, 11, 20, 12, 10, tzinfo=timezone.utc)
