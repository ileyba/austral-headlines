"""Thin wrapper around the Anthropic SDK (shared by search and summarizer)."""
from __future__ import annotations

import logging

import anthropic

from .config import Settings

log = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


_client: anthropic.Anthropic | None = None


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
        return client().beta.messages.create(**params)
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
