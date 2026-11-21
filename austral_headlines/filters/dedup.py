"""Deduplication: same URL, and same story across outlets (keep the primary)."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse, urlunparse

from ..models import Candidate

_STOP = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "as", "at", "by",
    "with", "from", "is", "are", "after", "over", "its", "it", "be", "says", "say",
    "de", "la", "el", "los", "las", "y", "en", "por", "para", "con", "del", "da",
    "do", "das", "dos", "e", "o", "um", "uma", "que", "se", "no", "na",
}


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunparse(("https", host, path, "", "", ""))


def _tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    words = re.findall(r"[a-z0-9$%.]+", t)
    return {w.strip(".") for w in words if w.strip(".") and w not in _STOP and len(w) > 1}


def title_similarity(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _better(a: Candidate, b: Candidate) -> Candidate:
    """Primary source wins; tie → earliest publication; then feed-verified."""
    if a.priority != b.priority:
        return a if a.priority < b.priority else b
    if a.published_utc and b.published_utc and a.published_utc != b.published_utc:
        return a if a.published_utc < b.published_utc else b
    return a


def dedupe(cands: list[Candidate], similarity_threshold: float = 0.6) -> list[Candidate]:
    # 1) exact URL duplicates
    by_url: dict[str, Candidate] = {}
    for c in cands:
        k = normalize_url(c.url)
        by_url[k] = _better(by_url[k], c) if k in by_url else c

    # 2) near-identical titles across outlets → one story, keep primary
    groups: list[Candidate] = []
    for c in by_url.values():
        for i, g in enumerate(groups):
            if title_similarity(c.title, g.title) >= similarity_threshold:
                groups[i] = _better(g, c)
                break
        else:
            groups.append(c)
    return groups


def resolve_duplicate_links(cands: dict[str, Candidate], duplicate_of: dict[str, str]) -> set[str]:
    """Given model-suggested duplicate links (id -> other id), return the ids to
    DROP so that each story group keeps only its best primary source."""
    parent: dict[str, str] = {i: i for i in cands}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in duplicate_of.items():
        if a in parent and b in parent:
            parent[find(a)] = find(b)

    groups: dict[str, list[str]] = {}
    for i in cands:
        groups.setdefault(find(i), []).append(i)

    drop: set[str] = set()
    for members in groups.values():
        best = members[0]
        for m in members[1:]:
            best_c = _better(cands[best], cands[m])
            best = best if best_c is cands[best] else m
        drop.update(m for m in members if m != best)
    return drop
