import pytest

from austral_headlines.filters.domains import filter_bank_calls, filter_domains, match_source
from austral_headlines.models import Candidate


@pytest.mark.parametrize("url,tag", [
    ("https://www.reuters.com/markets/x", "RTRS"),
    ("https://www.bloomberg.com/news/articles/x", "BBG"),
    ("https://www1.folha.uol.com.br/mercado/x.shtml", "FOLHA"),
    ("https://valor.globo.com/financas/x", "VALOR"),
    ("https://www.zerohedge.com/markets/x", "ZH"),
    ("https://es.investing.com/news/x", "INVESTING"),
    ("https://www.lmneuquen.com/x", "LMNEUQUEN"),
    ("https://shale24.com.ar/x", "SHALE24"),
    ("https://WWW.MINING.COM/x", "MINING"),
])
def test_allowed(settings, url, tag):
    assert match_source(url, settings.sources).tag == tag


@pytest.mark.parametrize("url", [
    "https://finance.yahoo.com/news/reuters-story",       # aggregator
    "https://g1.globo.com/economia/x",                    # globo.com but not Valor
    "https://www.uol.com.br/x",                           # uol but not Folha
    "https://notmining.com/x",                            # look-alike
    "https://reuters.com.evil.example/x",                 # suffix trick
    "https://www.marketscreener.com/reuters-x",
    "ftp://reuters.com/x",
    "https://news.google.com/articles/abc",
    "https://www.freeport-mcmoran.com/press",            # company press-release site
    "not a url",
])
def test_rejected(settings, url):
    assert match_source(url, settings.sources) is None


def test_filter_sets_metadata(settings):
    cands = [Candidate(title="a", url="https://www.cnbc.com/2026/11/20/a.html"),
             Candidate(title="b", url="https://www.yahoo.com/b")]
    out = filter_domains(cands, settings.sources)
    assert len(out) == 1
    assert out[0].source_tag == "CNBC" and out[0].domain == "www.cnbc.com"


def test_investing_requires_bank(settings):
    cands = filter_domains([
        Candidate(title="Goldman Sachs raises copper forecast to $12,000",
                  url="https://www.investing.com/news/a"),
        Candidate(title="Copper futures edge higher", url="https://www.investing.com/news/b"),
        Candidate(title="Copper futures edge higher", url="https://www.mining.com/b"),
    ], settings.sources)
    out = filter_bank_calls(cands, settings.sources, settings.raw["investing_banks"])
    assert [c.url for c in out] == ["https://www.investing.com/news/a", "https://www.mining.com/b"]


def test_video_and_non_article_urls_dropped(settings):
    cands = [Candidate(title="v", url="https://www.bloomberg.com/news/videos/2026-11-21/x"),
             Candidate(title="a", url="https://www.bloomberg.com/news/articles/2026-11-21/x")]
    out = filter_domains(cands, settings.sources, exclude_patterns=settings.raw["exclude_url_patterns"])
    assert [c.title for c in out] == ["a"]


def test_blocked_domains_parsed_from_api_error():
    from austral_headlines.fetchers.websearch import _blocked_domains

    msg = ("API error 400: {'message': \"The following domains are not accessible to our user agent: "
           "['ft.com', 'reuters.com', 'wsj.com']. Read more: https://support.anthropic.com/\"}")
    assert _blocked_domains(msg) == {"ft.com", "reuters.com", "wsj.com"}
    assert _blocked_domains("API error 500: overloaded") == set()
