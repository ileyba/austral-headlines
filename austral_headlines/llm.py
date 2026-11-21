"""Thin wrapper around the Anthropic SDK (shared by search and summarizer)."""
from __future__ import annotations

import logging
import threading

import anthropic

from .config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


_client: anthropic.Anthropic | None = None

# List prices (USD per 1M tokens) for the per-run cost estimate in the log.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches

_lock = threading.Lock()
usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "searches": 0, "calls": 0}


def _record(resp) -> None:
    u = getattr(resp, "usage", None)
    if u is None:
        return
    stu = getattr(u, "server_tool_use", None)
    with _lock:
        usage["calls"] += 1
        usage["input"] += getattr(u, "input_tokens", 0) or 0
        usage["output"] += getattr(u, "output_tokens", 0) or 0
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        usage["searches"] += getattr(stu, "web_search_requests", 0) or 0


def usage_summary(model: str) -> str:
    pin, pout = PRICES.get(model, PRICES["claude-sonnet-5-5"])
    cost = (
        usage["input"] * pin + usage["cache_write"] * pin * 1.25 + usage["cache_read"] * pin * 0.1
        + usage["output"] * pout
    ) / 1e6 + usage["searches"] * WEB_SEARCH_USD
    return (f"API usage: {usage['calls']} calls, {usage['input']:,} input tokens, "
            f"{usage['output']:,} output tokens, {usage['searches']} web searches "
            f"≈ US${cost:.2f} at list prices ({model})")


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3, timeout=300)
    return _client


def create(settings: Settings, **kwargs):
    """messages.create with optional server-side refusal fallback.

    Uses the beta endpoint so the `fallbacks` param is available; set
    ANTHROPIC_FALLBACKS=off to disable it."""
    params = dict(model=settings.model, **kwargs)
    if settings.fallbacks != "off":
        params["betas"] = [FALLBACK_BETA]
        params["fallbacks"] = "default"
    try:
        resp = client().beta.messages.create(**params)
        _record(resp)
        return resp
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"connection error: {exc}") from exc
    except TypeError as exc:  # raised by the SDK when no credentials are configured
        if "authentication" in str(exc):
            raise LLMError("no Anthropic credentials – set ANTHROPIC_API_KEY") from exc
        raise


def run_with_pause(settings: Settings, messages: list, max_continues: int = 3, **kwargs):
    """Call the API, resending paused server-tool turns (stop_reason=pause_turn)."""
    resp = None
    all_content = []
    for _ in range(max_continues + 1):
        resp = create(settings, messages=messages, **kwargs)
        all_content.extend(resp.content)
        if resp.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": resp.content}]
    if resp is not None and resp.stop_reason == "refusal":
        cat = getattr(getattr(resp, "stop_details", None), "category", None)
        raise LLMError(f"model refused (category={cat})")
    return resp, all_content


def text_of(blocks) -> str:
    return "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", "") == "text")
