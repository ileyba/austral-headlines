"""Discovery via Claude's web search tool, restricted with `allowed_domains`.

Search is used ONLY to discover candidate URLs. Titles/timestamps returned by
the model are never trusted: every URL is later domain-checked by code and its
publication time is verified from the page's own metadata (page_meta.py)."""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor

from ..config import Settings
from ..llm import LLMError, run_with_pause, text_of
from ..models import Candidate
from ..window import RunWindow

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+")

SYSTEM = (
    "You are a news-discovery assistant for a financial markets news desk. "
    "Use the web_search tool to find news ARTICLES (not section pages, tag pages, "
    "quote pages or videos) that were first published inside the time window the "
    "user gives you. Prefer breaking, material news; skip opinion columns and routine "
    "price recaps. When done, list every relevant article URL you found, one per line, "
    "between <urls> and </urls>. Do not summarize the articles."
)


_BLOCKED_RE = re.compile(r"not accessible to our user agent: \[([^\]]*)\]")


def _blocked_domains(message: str) -> set[str]:
    m = _BLOCKED_RE.search(message)
    return set(re.findall(r"'([^']+)'", m.group(1))) if m else set()


def build_queries(settings: Settings) -> list[tuple[str, str]]:
    queries = [(t["name"], t["query"]) for t in settings.raw["topics"]]
    wl = settings.raw["watchlist"]
    size = max(1, int(settings.raw["search"].get("watchlist_group_size", 5)))
    for i, start in enumerate(range(0, len(wl), size), start=1):
        chunk = wl[start:start + size]
        names = "; ".join(f'{c["name"]} ({c["ticker"]})' for c in chunk)
        queries.append((
            f"Watchlist {i}",
            f"Material corporate news for each of these companies: {names}. Material = results, "
            "guidance, production/reserves, strikes/accidents/force majeure, M&A or asset sales, "
            "project approvals or capex, regulatory/legal/tax rulings, major contracts, management "
            "changes, dividends/buybacks, financing/debt, bank rating or price-target changes. "
            "Search each company by name and by ticker.",
        ))
    return queries


def _one_search(settings: Settings, name: str, query: str, window: RunWindow,
                errors: list[str]) -> list[Candidate]:
    s = settings.raw["search"]
    fmt = "%Y-%m-%d %H:%M UTC"
    user = (
        f"Topic: {name}\n{query}\n\n"
        f"Time window: published between {window.start_utc.strftime(fmt)} and "
        f"{window.end_utc.strftime(fmt)} (the last {window.hours:g} hours). "
        "Only articles first published in that window are useful; older ones are useless. "
        "Spanish and Portuguese outlets are allowed sources too."
    )
    excluded = set(s.get("exclude_domains", []))
    blocks = None
    for _attempt in range(2):
        tool = {
            "type": s.get("tool_type", "web_search_20260209"),
            "name": "web_search",
            "max_uses": int(s.get("max_uses_per_query", 5)),
            "allowed_domains": [d for d in settings.allowed_domains if d not in excluded],
        }
        try:
            _, blocks = run_with_pause(
                settings,
                messages=[{"role": "user", "content": user}],
                system=SYSTEM,
                max_tokens=8000,
                tools=[tool],
                output_config={"effort": "low"},
            )
            break
        except LLMError as exc:
            blocked = _blocked_domains(str(exc))
            if blocked and not blocked <= excluded:
                log.warning("search '%s': web search cannot access %s – retrying without them. "
                            "Add them to search.exclude_domains in config.yaml.", name, sorted(blocked))
                excluded |= blocked
                continue
            msg = f"search '{name}': {exc}"
            log.warning(msg)
            errors.append(msg)
            return []
    if blocks is None:
        return []

    found: dict[str, Candidate] = {}
    for b in blocks:
        if getattr(b, "type", "") == "web_search_tool_result":
            content = getattr(b, "content", None)
            if not isinstance(content, list):  # error object
                errors.append(f"search '{name}': tool error {getattr(content, 'error_code', content)}")
                continue
            for r in content:
                url = getattr(r, "url", "")
                if url:
                    found.setdefault(url, Candidate(title=getattr(r, "title", "") or "", url=url,
                                                    via="search"))
    text = text_of(blocks)
    m = re.search(r"<urls>(.*?)</urls>", text, re.S)
    for url in _URL_RE.findall(m.group(1) if m else text):
        url = url.rstrip(".,;")
        found.setdefault(url, Candidate(title="", url=url, via="search"))
    log.info("search %-32s %3d urls", name, len(found))
    return list(found.values())


def search_candidates(settings: Settings, window: RunWindow, errors: list[str]) -> list[Candidate]:
    queries = build_queries(settings)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = pool.map(lambda q: _one_search(settings, q[0], q[1], window, errors), queries)
    return [c for batch in results for c in batch]
