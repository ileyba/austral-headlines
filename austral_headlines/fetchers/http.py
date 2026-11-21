"""Shared HTTP helper: polite, bounded, never tries to get around paywalls."""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)


class FetchError(Exception):
    pass


def get_text(url: str, *, timeout: float, user_agent: str, max_bytes: int) -> str:
    """GET a URL and return at most `max_bytes` of decoded body.

    No cookies, no paywall/CAPTCHA workarounds: a 401/403/429 or a challenge
    page is simply reported as an error and the caller moves on."""
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en,es;q=0.8,pt;q=0.7",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    raise FetchError(f"HTTP {resp.status_code}")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= max_bytes:
                        break
                body = b"".join(chunks)[:max_bytes]
                enc = resp.encoding or "utf-8"
                return body.decode(enc, errors="replace")
    except httpx.HTTPError as exc:
        raise FetchError(f"{type(exc).__name__}: {exc}") from exc
