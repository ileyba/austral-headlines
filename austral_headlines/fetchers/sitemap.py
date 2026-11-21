"""Google-News sitemap fetcher (used for Reuters, which has no public RSS).
Each <url> carries <news:publication_date> and <news:title>."""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

from ..config import Settings, Source
from ..models import Candidate
from .dates import parse_datetime
from .http import FetchError, get_text

log = logging.getLogger(__name__)

NS = {
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
}


def parse_news_sitemap(xml_text: str, src: Source) -> list[Candidate]:
    root = ET.fromstring(xml_text)
    out = []
    for url_el in root.findall("sm:url", NS):
        loc = url_el.findtext("sm:loc", default="", namespaces=NS).strip()
        title = url_el.findtext("news:news/news:title", default="", namespaces=NS).strip()
        pub = url_el.findtext("news:news/news:publication_date", default="", namespaces=NS)
        if not loc or not title:
            continue
        out.append(Candidate(title=title, url=loc, published_utc=parse_datetime(pub, src.naive_tz),
                             ts_origin="sitemap", via="sitemap", language=src.language))
    return out


def fetch_sitemaps(settings: Settings, errors: list[str]) -> list[Candidate]:
    http = settings.raw["http"]
    out: list[Candidate] = []
    for src in settings.sources:
        for url in src.sitemaps:
            try:
                text = get_text(url, timeout=http["timeout_seconds"], user_agent=http["user_agent"],
                                max_bytes=http["max_page_bytes"] * 4)
                items = parse_news_sitemap(text, src)
                log.info("sitemap %-7s %3d items  %s", src.tag, len(items), url)
                out.extend(items)
            except (FetchError, ET.ParseError) as exc:
                msg = f"sitemap {src.tag} {url}: {exc}"
                log.warning(msg)
                errors.append(msg)
    return out
