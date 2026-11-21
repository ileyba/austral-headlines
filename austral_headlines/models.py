"""Normalized candidate article."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Candidate:
    title: str
    url: str
    domain: str = ""
    source_tag: str = ""          # e.g. RTRS, BBG (set by the domain filter)
    priority: int = 99
    published_utc: datetime | None = None
    ts_origin: str = ""           # "feed", "sitemap", "page-meta"
    summary: str = ""             # visible summary/description only (never full text)
    via: str = ""                 # "rss", "sitemap", "search"
    language: str = "en"
    id: str = ""

    def key(self) -> str:
        from .filters.dedup import normalize_url

        return normalize_url(self.url)
