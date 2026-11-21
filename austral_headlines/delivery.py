"""Output: console + file always; optional Telegram/email to the OWNER only.
This module never posts to X or messages anyone other than the configured
single recipient."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import httpx

from .window import RunWindow

log = logging.getLogger(__name__)


def save(text: str, window: RunWindow, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{window.now_local:%Y-%m-%d_%H%M}.md"
    header = f"<!-- {window.describe()} -->\n"
    path.write_text(header + text + "\n", encoding="utf-8")
    return path


def _telegram(text: str, subject: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
    if "," in chat:
        raise RuntimeError("TELEGRAM_CHAT_ID must be a single chat (your own)")
    body = f"{subject}\n\n{text}"
    for i in range(0, len(body), 3900):  # Telegram limit 4096 chars
        r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       data={"chat_id": chat, "text": body[i:i + 3900],
                             "disable_web_page_preview": "true"}, timeout=20)
        r.raise_for_status()


def _email(text: str, subject: str) -> None:
    to = os.environ.get("EMAIL_TO", "").strip()
    if not to or "," in to or ";" in to:
        raise RuntimeError("EMAIL_TO must be exactly one address (your own)")
    host, user = os.environ.get("SMTP_HOST"), os.environ.get("SMTP_USER")
    if not host or not user:
        raise RuntimeError("SMTP_HOST / SMTP_USER not set")
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(text)
    with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
        s.starttls()
        s.login(user, os.environ.get("SMTP_PASSWORD", ""))
        s.send_message(msg)


def deliver(text: str, window: RunWindow, dry_run: bool) -> list[str]:
    channels = [c.strip().lower() for c in os.environ.get("DELIVERY", "").split(",") if c.strip()]
    if not channels:
        return []
    if dry_run:
        log.info("dry-run: not sending to %s", channels)
        return []
    subject = f"Austral headlines – {window.now_local:%Y-%m-%d} {window.slot} (Montevideo)"
    errors = []
    for ch in channels:
        try:
            {"telegram": _telegram, "email": _email}[ch](text, subject)
            log.info("delivered via %s", ch)
        except KeyError:
            errors.append(f"unknown delivery channel {ch!r}")
        except Exception as exc:
            errors.append(f"delivery {ch}: {exc}")
            log.warning("delivery %s failed: %s", ch, exc)
    return errors
