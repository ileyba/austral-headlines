"""Configuration loading (config.yaml + environment / .env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_MODEL = "claude-sonnet-5-5"
ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Source:
    tag: str
    name: str
    domains: list[str]
    priority: int = 50
    feeds: list[str] = field(default_factory=list)
    sitemaps: list[str] = field(default_factory=list)
    language: str = "en"
    naive_tz: str | None = None
    bank_calls_only: bool = False


@dataclass
class Settings:
    raw: dict[str, Any]
    sources: list[Source]
    model: str
    fallbacks: str  # "default" or "off"
    output_dir: Path

    # convenient accessors -------------------------------------------------
    @property
    def timezone(self) -> str:
        return self.raw.get("timezone", "America/Montevideo")

    @property
    def runs(self) -> dict[str, float]:
        return {str(k): float(v) for k, v in self.raw["runs"].items()}

    @property
    def allowed_domains(self) -> list[str]:
        return [d for s in self.sources for d in s.domains]

    def source_for_tag(self, tag: str) -> Source | None:
        return next((s for s in self.sources if s.tag == tag), None)


def load_settings(config_path: str | Path | None = None) -> Settings:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:  # pragma: no cover
        pass

    path = Path(config_path) if config_path else ROOT / "config.yaml"
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    sources = [Source(**s) for s in raw["sources"]]
    return Settings(
        raw=raw,
        sources=sources,
        model=os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL,
        fallbacks=os.environ.get("ANTHROPIC_FALLBACKS", "").strip().lower() or "default",
        output_dir=Path(os.environ.get("OUTPUT_DIR", "").strip() or ROOT / "output"),
    )
