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


WATCHLIST = "Watchlist company"
OUT_OF_SCOPE = "Out of scope"


def categories(settings: Settings) -> list[str]:
    wl = [WATCHLIST] if settings.raw.get("watchlist") else []
    return [t["name"] for t in settings.raw["topics"]] + wl + [OUT_OF_SCOPE]


class Pick(BaseModel):
    id: str
    category: str
    scope_evidence: str
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


def build_schema(settings: Settings) -> dict:
    schema = json.loads(json.dumps(_SCHEMA))
    item = schema["properties"]["headlines"]["items"]
    item["properties"]["category"] = {"type": "string", "enum": categories(settings)}
    item["properties"]["scope_evidence"] = {"type": "string"}
    item["required"] = ["id", "category", "scope_evidence"] + item["required"][1:]
    return schema


_SCHEMA = {
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
    watchlist = settings.raw.get("watchlist") or []
    tickers = ", ".join(f'{w["ticker"]} ({w["name"]})' for w in watchlist)
    wl_category = f"\n- {WATCHLIST}: {tickers}" if watchlist else ""
    if watchlist:
        company_rule = """- Watchlist companies: only material corporate news (results, guidance, production/reserves,
  strikes/accidents/force majeure, M&A/asset sales, project approvals/capex, regulatory/legal/tax
  rulings, major contracts, management changes, dividends/buybacks, financing/debt, bank rating or
  price-target changes). For these, `topic` is EXACTLY the ticker (e.g. "FCX", "YPF").
  Company news weighs the same as macro/commodities; results, guidance, M&A and operational
  disruptions rank high."""
        other_companies = "individual companies outside the watchlist"
        bank_scope = "commodities, rates, macro, or a rating/target change on a watchlist company"
    else:
        company_rule = """- Company news is out of scope (there is no company watchlist). The only exception is an event
  that is itself market-moving news for a covered category, e.g. a strike or force majeure that cuts
  supply at a major copper mine or oil field; then use that category and a commodity topic."""
        other_companies = "individual company news, earnings, ratings and price targets"
        bank_scope = "commodities, rates or macro – not on individual companies"
    topics_block = "\n".join(f'- {t["name"]}: {t["query"]}' for t in settings.raw["topics"])
    return f"""You are the breaking-news editor for Austral Research (@AustralRes_En), an English-language
markets account focused on commodities, macro and Latin America.

You receive candidate articles that have ALREADY been verified as published inside the current
time window by allowed outlets. Your job: pick only material, genuinely new, breaking news and write
one short English headline line for each.

STRICT SCOPE – every headline must belong to exactly one of these categories:
{topics_block}{wl_category}

Scope rules (most important):
- Set `category` to the category the ARTICLE ITSELF is about. If it does not clearly fit one, set
  `category` to "{OUT_OF_SCOPE}" (it will be discarded).
- `scope_evidence`: one short sentence stating what in the article (its title/summary, not your own
  inference) puts it in that category.
- No speculative links. A story is out of scope unless the article itself reports the covered angle.
  Examples: an earthquake, storm or accident is out of scope unless the article reports damage or
  disruption to mines, oil/gas output or ports; "country X is a big copper
  producer" is NOT enough.
- Out of scope unless directly about a category: US/global stock-index moves and equity-market
  recaps, {other_companies} (tech, AI, pharma, banks, retail, autos...),
  crypto, corporate legal cases, politics without an economic-policy/market angle, elections polls,
  society, health, weather, sports, entertainment.
- Countries: only Argentina, Brazil and Chile for LatAm; other countries only when the news fits
  another category (e.g. OPEC+ decision, China export controls on rare earths, ECB rate decision).

Selection rules:
- Material and new only. Exclude opinion, explainers, previews, generic analyst commentary, routine
  price recaps ("gold rises 0.5%").
- Gold, silver, copper: never a price move by itself; report the driver (policy, supply, demand,
  central banks) when there is material news.
{company_rule}
- Investing.com (tag INVESTING): include only if it reports a named bank's note/call (forecast change on
  {bank_scope}). Put the bank name in
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
        output_config={"effort": "medium", "format": {"type": "json_schema",
                                                     "schema": build_schema(settings)}},
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
