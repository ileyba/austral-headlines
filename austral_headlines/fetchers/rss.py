"""RSS/Atom fetcher (feedparser). Timestamps come from the feed itself."""
from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import feedparser

from ..config import Settings, Source
from ..models import Candidate
from .dates import from_struct_time, parse_datetime
from .http import FetchError, get_text

log = logging.getLogger(__name__)
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 400) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _entry_time(entry, src: Source):
    # Only the *published* date counts (not "updated"): we want first publication.
    dt = from_struct_time(entry.get("published_parsed"))
    if dt is None:
        dt = parse_datetime(entry.get("published"), src.naive_tz)
    return dt


def parse_feed(text: str, src: Source) -> list[Candidate]:
    parsed = feedparser.parse(text)
    out = []
    for e in parsed.entries:
        link = e.get("feedburner_origlink") or e.get("link") or ""
        title = _clean(e.get("title", ""), 300)
        if not link or not title:
            continue
        out.append(
            Candidate(
                title=title,
                url=link.strip(),
                published_utc=_entry_time(e, src),
                ts_origin="feed",
                summary=_clean(e.get("summary", "")),
                via="rss",
                language=src.language,
            )
        )
    return out


def _fetch_one(url: str, src: Source, settings: Settings, errors: list[str]) -> list[Candidate]:
    http = settings.raw["http"]
    try:
        text = get_text(url, timeout=http["timeout_seconds"], user_agent=http["user_agent"],
                        max_bytes=http["max_page_bytes"] * 4)
        items = parse_feed(text, src)
        log.info("feed %-10s %3d items  %s", src.tag, len(items), url)
        return items
    except FetchError as exc:
        msg = f"feed {src.tag} {url}: {exc}"
        log.warning(msg)
        errors.append(msg)
    except Exception as exc:  # never break the run
        msg = f"feed {src.tag} {url}: unexpected {type(exc).__name__}: {exc}"
        log.warning(msg)
        errors.append(msg)
    return []


def fetch_feeds(settings: Settings, errors: list[str]) -> list[Candidate]:
    jobs = [(u, s) for s in settings.sources for u in s.feeds]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = pool.map(lambda j: _fetch_one(j[0], j[1], settings, errors), jobs)
    return [c for batch in results for c in batch]
