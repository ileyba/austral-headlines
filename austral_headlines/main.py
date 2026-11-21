"""CLI entry point: python -m austral_headlines.main [--now] [--dry-run] ..."""
from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from .config import Settings, load_settings
from .delivery import deliver, save
from .fetchers.page_meta import FetchError, verify_page
from .fetchers.rss import fetch_feeds
from .fetchers.sitemap import fetch_sitemaps
from .filters.dedup import dedupe, normalize_url, resolve_duplicate_links
from .filters.domains import filter_bank_calls, filter_domains
from .filters.timewindow import filter_window
from .llm import LLMError
from .models import Candidate
from .render import NO_NEWS, Headline, render
from .window import RunWindow, compute_window, is_business_day

log = logging.getLogger("austral")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Austral Research breaking-news headlines")
    p.add_argument("--now", action="store_true",
                   help="run immediately using the nearest slot (skip schedule/weekday checks)")
    p.add_argument("--dry-run", action="store_true", help="do not send Telegram/email")
    p.add_argument("--slot", help="force a slot, e.g. 10:00")
    p.add_argument("--at", help="pretend current time is this ISO timestamp (testing)")
    p.add_argument("--no-search", action="store_true", help="feeds/sitemaps only, skip web search")
    p.add_argument("--no-llm", action="store_true",
                   help="skip Claude entirely; print verified raw candidates (debug)")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _verify_search_candidates(settings: Settings, cands: list[Candidate], known: set[str],
                              errors: list[str]) -> list[Candidate]:
    """Fetch each search-discovered page and read its published timestamp."""
    http = settings.raw["http"]
    todo, seen = [], set()
    for c in cands:
        k = normalize_url(c.url)
        if k in known or k in seen:
            continue
        seen.add(k)
        todo.append(c)
    limit = int(settings.raw["search"].get("max_page_checks", 60))
    if len(todo) > limit:
        log.info("verifying first %d of %d search URLs", limit, len(todo))
        todo = todo[:limit]

    def check(c: Candidate):
        src = settings.source_for_tag(c.source_tag)
        try:
            pub, title, desc = verify_page(
                c.url, naive_tz=src.naive_tz if src else None, timeout=http["timeout_seconds"],
                user_agent=http["user_agent"], max_bytes=http["max_page_bytes"])
        except FetchError as exc:
            errors.append(f"verify {c.source_tag} {c.url}: {exc}")
            return None
        if pub is None:
            log.debug("drop (no verifiable timestamp): %s", c.url)
            return None
        c.published_utc, c.ts_origin = pub, "page-meta"
        c.title = title or c.title
        c.summary = desc or c.summary
        return c if c.title else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        return [c for c in pool.map(check, todo) if c is not None]


def collect(settings: Settings, window: RunWindow, use_search: bool,
            errors: list[str]) -> tuple[list[Candidate], bool]:
    """Return (candidates, any_source_responded)."""
    feed_items = fetch_feeds(settings, errors) + fetch_sitemaps(settings, errors)
    responded = bool(feed_items)
    feed_items = filter_domains(feed_items, settings.sources, log)
    log.info("feeds/sitemaps: %d items on allowed domains", len(feed_items))

    search_items: list[Candidate] = []
    if use_search and settings.raw["search"].get("enabled", True):
        from .fetchers.websearch import search_candidates

        found = search_candidates(settings, window, errors)
        responded = responded or bool(found)
        raw = filter_domains(found, settings.sources, log)
        known = {normalize_url(c.url) for c in feed_items}
        search_items = _verify_search_candidates(settings, raw, known, errors)
        log.info("search: %d URLs on allowed domains, %d with verified timestamp",
                 len(raw), len(search_items))
    return feed_items + search_items, responded


def run(args) -> int:
    settings = load_settings(args.config)
    at = datetime.fromisoformat(args.at).astimezone(timezone.utc) if args.at else None
    window = compute_window(settings.runs, settings.timezone, at=at, slot=args.slot)
    log.info(window.describe())

    if not args.now and not args.slot:
        if not is_business_day(window.now_local):
            log.info("not a business day in %s – nothing to do", settings.timezone)
            return 0
        tol = float(settings.raw.get("slot_tolerance_minutes", 60))
        if abs(window.minutes_from_slot) > tol:
            log.info("%.0f min away from slot %s (> %g) – nothing to do. Use --now to force.",
                     window.minutes_from_slot, window.slot, tol)
            return 0

    errors: list[str] = []
    cands, responded = collect(settings, window, not args.no_search, errors)
    if not responded:
        log.error("every source failed (%d errors) – not reporting 'No material news.'", len(errors))
        return 3
    cands = filter_bank_calls(cands, settings.sources, settings.raw.get("investing_banks", []))
    cands = filter_window(cands, window.start_utc, window.end_utc,
                          settings.raw.get("future_skew_minutes", 5), log)
    cands = dedupe(cands)
    cands.sort(key=lambda c: (c.priority, -c.published_utc.timestamp()))
    cands = cands[: int(settings.raw.get("max_candidates_for_llm", 150))]
    for i, c in enumerate(cands, 1):
        c.id = f"c{i}"
    log.info("%d candidates inside the window after filtering/dedup", len(cands))

    if args.no_llm:
        text = "\n".join(
            f"{c.published_utc:%H:%M UTC} – {c.source_tag} – [{c.title}]({c.url})" for c in cands
        ) or NO_NEWS
    else:
        from .summarizer import select_headlines

        try:
            sel = select_headlines(settings, cands, window)
        except LLMError as exc:
            log.error("summarizer failed: %s", exc)
            for e in errors:
                log.warning("source error: %s", e)
            return 2
        by_id = {c.id: c for c in cands}
        picks = {p.id: p for p in sel.headlines if p.id in by_id}
        dup_map = {d.id: d.duplicate_of for d in sel.duplicates
                   if d.id in picks or d.duplicate_of in picks}
        drop = resolve_duplicate_links({i: by_id[i] for i in set(picks) | set(dup_map) |
                                        set(dup_map.values()) if i in by_id}, dup_map)
        headlines = []
        for pid, p in picks.items():
            if pid in drop:
                continue
            c = by_id[pid]
            if c.source_tag == "INVESTING" and not p.bank.strip():
                continue
            headlines.append(Headline(topic=p.topic, summary=p.summary, title_en=p.title_en,
                                      importance=p.importance, candidate=c,
                                      unconfirmed=p.unconfirmed, bank=p.bank.strip()))
        text = render(headlines, int(settings.raw.get("max_headlines", 15)))

    print(text)
    path = save(text, window, settings.output_dir)
    log.info("saved %s", path)
    errors += deliver(text, window, args.dry_run)
    if not args.no_llm:
        from .llm import usage_summary

        log.info(usage_summary(settings.model))
    if errors:
        log.info("%d non-fatal source/delivery errors (see warnings above)", len(errors))
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    for noisy in ("httpx", "httpcore", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
