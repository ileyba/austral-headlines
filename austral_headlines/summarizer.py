"""Claude pass: materiality, translation/paraphrase to English, ranking.

The model returns structured JSON keyed by candidate id. URLs, times and
source tags are NEVER taken from the model; render.py reads them from the
verified candidate metadata."""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel, ValidationError

from .config import Settings
from .llm import LLMError, create, text_of
from .models import Candidate
from .window import RunWindow

log = logging.getLogger(__name__)


class Pick(BaseModel):
    id: str
    topic: str
    summary: str
    title_en: str
    importance: int
    unconfirmed: bool
    bank: str


class Dup(BaseModel):
    id: str
    duplicate_of: str


class Selection(BaseModel):
    headlines: list[Pick]
    duplicates: list[Dup]


SCHEMA = {
    "type": "object",
    "properties": {
        "headlines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "topic": {"type": "string"},
                    "summary": {"type": "string"},
                    "title_en": {"type": "string"},
                    "importance": {"type": "integer"},
                    "unconfirmed": {"type": "boolean"},
                    "bank": {"type": "string"},
                },
                "required": ["id", "topic", "summary", "title_en", "importance", "unconfirmed", "bank"],
                "additionalProperties": False,
            },
        },
        "duplicates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "duplicate_of": {"type": "string"}},
                "required": ["id", "duplicate_of"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["headlines", "duplicates"],
    "additionalProperties": False,
}


def build_system(settings: Settings) -> str:
    tickers = ", ".join(f'{w["ticker"]} ({w["name"]})' for w in settings.raw["watchlist"])
    topics = "; ".join(t["name"] for t in settings.raw["topics"])
    return f"""You are the breaking-news editor for Austral Research (@AustralRes_En), an English-language
markets account focused on commodities, macro and Latin America.

You receive candidate articles that have ALREADY been verified as published inside the current
time window by allowed outlets. Your job: pick only material, genuinely new, breaking news and write
one short English headline line for each.

Coverage: {topics}.
Company watchlist: {tickers}.

Selection rules:
- Material and new only. Exclude opinion, explainers, previews, generic analyst commentary, routine
  price recaps ("gold rises 0.5%"), lifestyle, sports, crime and anything outside coverage.
- Gold, silver, copper: never a price move by itself; report the driver (policy, supply, demand,
  central banks) when there is material news.
- Watchlist companies: only material corporate news (results, guidance, production/reserves,
  strikes/accidents/force majeure, M&A/asset sales, project approvals/capex, regulatory/legal/tax
  rulings, major contracts, management changes, dividends/buybacks, financing/debt, bank rating or
  price-target changes). For these, `topic` is EXACTLY the ticker (e.g. "FCX", "YPF").
  Company news weighs the same as macro/commodities; results, guidance, M&A and operational
  disruptions rank high.
- Investing.com (tag INVESTING): include only if it reports a named bank's note/call (forecast change on
  commodities, rates, macro, or a rating/target change on a watchlist company). Put the bank name in
  `bank` (e.g. "Goldman Sachs"). For every other item `bank` is "".
- ZeroHedge (tag ZH): set `unconfirmed` true when the claim is not attributed to an official/primary
  source. For every other source `unconfirmed` is false.
- TradingEconomics (tag TE): include material data releases/revisions (CPI, jobs, PMI, GDP, central bank
  decisions).
- One line per article. Never merge several articles into one line.
- If several candidates cover the same story, choose ONE (prefer the primary/original reporter, e.g.
  RTRS/BBG/WSJ/FT over aggregators) and list the others in `duplicates` with `duplicate_of` pointing at
  the one you kept. Do this across languages too.
- An ongoing story only qualifies if the candidate reports a genuinely new development.

Writing rules (English only):
- `topic`: 1-3 words (e.g. "Fed", "Oil", "Copper", "Argentina", "Tariffs") or the ticker.
- `summary`: what happened and why it matters, max ~20 words, paraphrased. Quote at most a few words.
  Translate Spanish/Portuguese naturally; keep proper nouns (YPF, Vaca Muerta, BCRA, Petrobras, Copom).
- `title_en`: the article's headline rendered in natural English (translated if needed), max ~14 words.
- `importance`: 1-100, higher = more market-moving.
- Return at most {settings.raw.get("max_headlines", 15)} headlines. Returning an empty list is correct
  when nothing is material and new.
"""


def _payload(cands: list[Candidate], window: RunWindow) -> str:
    rows = []
    for c in cands:
        rows.append({
            "id": c.id,
            "source": c.source_tag,
            "language": c.language,
            "published_utc": c.published_utc.strftime("%Y-%m-%d %H:%M") if c.published_utc else None,
            "title": c.title,
            "visible_summary": c.summary[:300],
        })
    return (
        f"Window: {window.start_utc:%Y-%m-%d %H:%M} to {window.end_utc:%Y-%m-%d %H:%M} UTC "
        f"(run slot {window.slot} Montevideo).\n\nCandidates (JSON):\n"
        + json.dumps(rows, ensure_ascii=False, indent=0)
    )


def select_headlines(settings: Settings, cands: list[Candidate], window: RunWindow) -> Selection:
    if not cands:
        return Selection(headlines=[], duplicates=[])
    resp = create(
        settings,
        max_tokens=16000,
        system=build_system(settings),
        messages=[{"role": "user", "content": _payload(cands, window)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if resp.stop_reason == "refusal":
        raise LLMError("summarizer refused")
    if resp.stop_reason == "max_tokens":
        raise LLMError("summarizer hit max_tokens")
    raw = text_of(resp.content)
    try:
        return Selection.model_validate_json(raw)
    except ValidationError as exc:
        raise LLMError(f"invalid JSON from summarizer: {exc}") from exc
