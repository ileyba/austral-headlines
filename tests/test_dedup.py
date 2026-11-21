from datetime import datetime, timezone

from austral_headlines.filters.dedup import dedupe, normalize_url, resolve_duplicate_links
from austral_headlines.models import Candidate

T = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def c(title, url, prio, minute=0):
    return Candidate(title=title, url=url, priority=prio, published_utc=T.replace(minute=minute))


def test_normalize_url():
    assert normalize_url("https://www.reuters.com/a/b/?utm=x#frag") == "https://reuters.com/a/b"
    assert normalize_url("http://reuters.com/a/b") == "https://reuters.com/a/b"


def test_same_url_once():
    out = dedupe([c("Fed holds rates", "https://www.cnbc.com/a?x=1", 6),
                  c("Fed holds rates", "https://cnbc.com/a", 6)])
    assert len(out) == 1


def test_same_story_keeps_primary_source():
    out = dedupe([
        c("Freeport declares force majeure at Grasberg mine", "https://www.zerohedge.com/a", 22),
        c("Freeport declares force majeure at Grasberg mine", "https://www.reuters.com/a", 1),
        c("Freeport declares force majeure at Grasberg mine", "https://www.mining.com/a", 8),
    ])
    assert len(out) == 1 and "reuters" in out[0].url


def test_different_stories_kept():
    out = dedupe([c("Fed holds rates steady", "https://www.reuters.com/a", 1),
                  c("Vale raises iron ore output guidance", "https://www.reuters.com/b", 1)])
    assert len(out) == 2


def test_resolve_model_duplicates_across_languages():
    cands = {
        "c1": c("YPF anuncia inversión en Vaca Muerta", "https://www.infobae.com/a", 16),
        "c2": c("YPF announces Vaca Muerta investment", "https://www.reuters.com/a", 1),
        "c3": c("YPF anuncia investimento", "https://valor.globo.com/a", 7),
    }
    drop = resolve_duplicate_links(cands, {"c1": "c3", "c3": "c2"})
    assert drop == {"c1", "c3"}
