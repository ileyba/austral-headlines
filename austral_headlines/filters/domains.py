"""Strict allow-list domain validation."""
from __future__ import annotations

from urllib.parse import urlparse

from ..config import Source
from ..models import Candidate


def host_of(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https"):
        return ""
    host = (parsed.hostname or "").lower().rstrip(".")
    return host


def match_source(url: str, sources: list[Source]) -> Source | None:
    """Return the configured source whose domain matches the URL host exactly
    or as a dot-bounded subdomain (e.g. www1.folha.uol.com.br). Anything else
    (look-alikes, mirrors, aggregators) returns None."""
    host = host_of(url)
    if not host:
        return None
    for src in sources:
        for dom in src.domains:
            dom = dom.lower()
            if host == dom or host.endswith("." + dom):
                return src
    return None


def filter_domains(cands: list[Candidate], sources: list[Source], log=None,
                   exclude_patterns: list[str] | None = None) -> list[Candidate]:
    kept = []
    for c in cands:
        path = urlparse(c.url).path.lower()
        if exclude_patterns and any(p in path for p in exclude_patterns):
            if log:
                log.debug("drop (not an article): %s", c.url)
            continue
        src = match_source(c.url, sources)
        if src is None:
            if log:
                log.debug("drop (domain not allowed): %s", c.url)
            continue
        c.domain = host_of(c.url)
        c.source_tag = src.tag
        c.priority = src.priority
        c.language = src.language
        kept.append(c)
    return kept


def filter_bank_calls(cands: list[Candidate], sources: list[Source], banks: list[str]) -> list[Candidate]:
    """Investing.com items survive only if title/summary names a bank."""
    restricted = {s.tag for s in sources if s.bank_calls_only}
    lowered = [b.lower() for b in banks]
    out = []
    for c in cands:
        if c.source_tag in restricted:
            text = f"{c.title} {c.summary}".lower()
            if not any(b in text for b in lowered):
                continue
        out.append(c)
    return out
