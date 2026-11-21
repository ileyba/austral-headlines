"""Final rendering – done by code from verified metadata."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timezone

from .models import Candidate

NO_NEWS = "No material news."


@dataclass
class Headline:
    topic: str
    summary: str
    title_en: str
    importance: int
    candidate: Candidate
    unconfirmed: bool = False
    bank: str = ""


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text.replace("**", "")


def _link_text(text: str) -> str:
    return _clean(text).replace("[", "(").replace("]", ")")


def source_label(h: Headline) -> str:
    tag = h.candidate.source_tag
    if tag == "INVESTING" and h.bank:
        return f"INVESTING/{h.bank.upper()}"
    return tag


def render_line(h: Headline) -> str:
    c = h.candidate
    when = c.published_utc.astimezone(timezone.utc).strftime("%H:%M UTC")
    summary = _clean(h.summary).rstrip(".")
    if h.unconfirmed and c.source_tag == "ZH":
        summary = f"unconfirmed (ZH): {summary}"
    url = c.url.replace(")", "%29").replace(" ", "%20")
    return (f"**{_clean(h.topic)}** – {summary} – {when} – {source_label(h)} – "
            f"[{_link_text(h.title_en)}]({url})")


def render(headlines: list[Headline], max_items: int = 15) -> str:
    if not headlines:
        return NO_NEWS
    ordered = sorted(headlines, key=lambda h: (-h.importance, h.candidate.priority))[:max_items]
    return "\n".join(render_line(h) for h in ordered)
