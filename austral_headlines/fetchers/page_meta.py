"""Extract a verifiable publication timestamp (and title) from a page's HTML
metadata. Only the publicly served HTML head/markup is read; nothing is done to
get past paywalls or CAPTCHAs."""
from __future__ import annotations

import html as htmllib
import json
import logging
import re
from datetime import datetime

from .dates import parse_datetime
from .http import FetchError, get_text

log = logging.getLogger(__name__)

# meta names/properties that carry first-publication time, in order of trust
_META_KEYS = [
    "article:published_time",
    "og:article:published_time",
    "datepublished",
    "parsely-pub-date",
    "sailthru.date",
    "pubdate",
    "publishdate",
    "publish-date",
    "dc.date.issued",
    "dcterms.created",
    "date",
]
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r'([\w:.\-]+)\s*=\s*("([^"]*)"|\'([^\']*)\')', re.I)
_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)
_TIME_RE = re.compile(r'<time\b[^>]*\bdatetime=["\']([^"\']+)["\']', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def _metas(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in _META_RE.findall(html):
        attrs = {m.group(1).lower(): (m.group(3) if m.group(3) is not None else m.group(4))
                 for m in _ATTR_RE.finditer(tag)}
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key and "content" in attrs and key not in out:
            out[key] = htmllib.unescape(attrs["content"])
    return out


def _jsonld_dates(html: str) -> list[str]:
    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if "datePublished" in node and isinstance(node["datePublished"], str):
                found.append(node["datePublished"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for block in _JSONLD_RE.findall(html):
        try:
            walk(json.loads(block.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
    return found


def extract_published(html: str, naive_tz: str | None = None) -> datetime | None:
    metas = _metas(html)
    for key in _META_KEYS:
        dt = parse_datetime(metas.get(key), naive_tz)
        if dt:
            return dt
    for raw in _jsonld_dates(html):
        dt = parse_datetime(raw, naive_tz)
        if dt:
            return dt
    m = _TIME_RE.search(html)
    if m:
        return parse_datetime(m.group(1), naive_tz)
    return None


def extract_title(html: str) -> str:
    metas = _metas(html)
    title = metas.get("og:title") or metas.get("twitter:title")
    if not title:
        m = _TITLE_RE.search(html)
        title = htmllib.unescape(m.group(1)) if m else ""
    return re.sub(r"\s+", " ", title).strip()


def extract_description(html: str) -> str:
    metas = _metas(html)
    return (metas.get("og:description") or metas.get("description") or "").strip()[:400]


def verify_page(url: str, *, naive_tz: str | None, timeout: float, user_agent: str,
                max_bytes: int) -> tuple[datetime | None, str, str]:
    """Return (published_utc, title, description). Raises FetchError on failure."""
    html = get_text(url, timeout=timeout, user_agent=user_agent, max_bytes=max_bytes)
    return extract_published(html, naive_tz), extract_title(html), extract_description(html)


__all__ = ["verify_page", "extract_published", "extract_title", "FetchError"]
