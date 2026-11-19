"""Perplexity alert reasoning.

The decision is already made. News and news+price alerts get a richer trader-facing
write-up. Price-only alerts keep the deterministic rule sentence. A missing key or a
failed call leaves the deterministic summary.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from typing import Any
from urllib import request
from urllib.error import HTTPError

from .config import settings
from .engine import AlertDraft

# Price-only stays on the rule sentence for now; Isolation Forest wording comes later.
REASONING_KINDS = frozenset({"news", "news_price"})

_INSTRUCTIONS = (
    "You write trader-facing reasoning for equity alerts that have already been decided. "
    "Each alert in the JSON is either kind=news (headline sentiment only) or kind=news_price "
    "(price move plus headlines). Do not decide whether an alert should exist. "
    "Use only facts in the payload: prices, percents, FinBERT scores, headline titles, sources, "
    "publish times, and urls. Do not invent a price, score, ticker, or article that is not listed. "
    "You may quote or paraphrase headline titles and cite their urls from the payload. "
    "Do not merely restate that the price moved and that headlines lined up. "
    "For each alert write three to four short sentences: "
    "(1) What happened — for news_price, name the move with the percent and levels when present; "
    "for news, say this is a news-only alert and give the combined FinBERT score out of 100. "
    "(2) Why it likely moved or why the news matters — ground the reason in the specific headlines "
    "(company action, guidance, product, legal, sector, etc.), not generic market chatter. "
    "Name the most relevant headline title; include its url when one is present. "
    "(3) How the FinBERT scores support that reading (strong negative, positive, or mixed). "
    "(4) Forward look — one cautious sentence on what a trader might watch next given these stories "
    "(follow-up prints, guidance, sector peers). This is not personalized financial advice; "
    "keep it tentative (might, could, watch for). "
    "When headlines disagree in tone, say so instead of forcing a single story. "
    "Return one JSON object with an alerts array. Each item has symbol, bar_date, and summary."
)

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "alerts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "symbol": {"type": "string"},
                    "bar_date": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["symbol", "bar_date", "summary"],
            },
        }
    },
    "required": ["alerts"],
}


def drafts_for_reasoning(drafts: list[AlertDraft]) -> list[AlertDraft]:
    """News and news+price only. Price-only keeps the deterministic sentence."""
    return [draft for draft in drafts if draft.kind in REASONING_KINDS]


def reasoning_payload(drafts: list[AlertDraft]) -> dict[str, Any]:
    """Facts and instructions for one Perplexity call covering news / news+price alerts."""
    return {
        "instructions": _INSTRUCTIONS,
        "alerts": [_alert_facts(draft) for draft in drafts_for_reasoning(drafts)],
    }


def apply_reasoning(
    drafts: list[AlertDraft], parsed: dict[str, Any] | None, model: str | None = None
) -> list[AlertDraft]:
    """Replace summaries that Perplexity returned. Unmatched alerts keep the rule sentence."""
    if not parsed:
        return drafts
    by_key = {}
    for item in parsed.get("alerts") or []:
        if not isinstance(item, dict):
            continue
        summary = str(item.get("summary") or "").strip()
        symbol = str(item.get("symbol") or "").upper()
        bar_date = str(item.get("bar_date") or "")
        if symbol and bar_date and summary:
            by_key[(symbol, bar_date)] = summary
    updated = []
    for draft in drafts:
        text = by_key.get((draft.symbol.upper(), _date_text(draft.bar_date)))
        updated.append(_with_summary(draft, text, model) if text else draft)
    return updated


def complete_reasoning(
    api_key: str, drafts: list[AlertDraft], model: str | None = None
) -> tuple[list[AlertDraft], str | None]:
    """Call Perplexity for news / news+price drafts. Price-only rows pass through unchanged."""
    key = api_key.strip()
    if not key or not drafts:
        return drafts, None
    eligible = drafts_for_reasoning(drafts)
    if not eligible:
        return drafts, None
    from .perplexity_catalog import resolve_model

    payload = reasoning_payload(eligible)
    body = {
        "model": resolve_model(model or settings.perplexity_model),
        "instructions": _INSTRUCTIONS,
        "input": json.dumps(payload),
        "temperature": 0.3,
        "max_output_tokens": 6000,
        "tools": [],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "alert_reasoning", "schema": _SCHEMA},
        },
    }
    req = request.Request(
        url="https://api.perplexity.ai/v1/agent",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=settings.perplexity_timeout_s) as resp:
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
        return drafts, detail[:300]
    except Exception as exc:
        return drafts, str(exc)[:300]
    if raw.get("error"):
        return drafts, str(raw["error"])[:300]
    text = _agent_text(raw)
    if not text:
        return drafts, "Perplexity returned an empty response."
    try:
        parsed = _parse_json(text)
    except json.JSONDecodeError:
        return drafts, "Perplexity did not return JSON."
    reasoned = apply_reasoning(eligible, parsed, model)
    by_key = {(draft.symbol, draft.bar_date): draft for draft in reasoned}
    merged = [by_key.get((draft.symbol, draft.bar_date), draft) for draft in drafts]
    return merged, None


def _alert_facts(draft: AlertDraft) -> dict[str, Any]:
    return {
        "symbol": draft.symbol,
        "bar_date": _date_text(draft.bar_date),
        "kind": draft.kind,
        "price_change_pct": draft.price_change_pct,
        "latest_close": draft.latest_close,
        "prior_close": draft.prior_close,
        "volume_spike": draft.volume_spike,
        "sentiment_score": draft.sentiment_score,
        "sentiment_threshold": draft.sentiment_threshold,
        "price_move_threshold": draft.price_move_threshold,
        "headlines": [_headline_facts(article) for article in draft.articles],
    }


def _headline_facts(article: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": article.get("title"),
        "published_at": article.get("published_at"),
        "source": article.get("source"),
        "url": article.get("url"),
        "sentiment_score": article.get("sentiment_score"),
        "confidence": article.get("confidence"),
        "positive_pct": article.get("positive_pct"),
        "negative_pct": article.get("negative_pct"),
        "neutral_pct": article.get("neutral_pct"),
    }


def _with_summary(draft: AlertDraft, summary: str, model: str | None = None) -> AlertDraft:
    from .perplexity_catalog import known_model, model_label

    sections = dict(draft.sections)
    if draft.summary:
        sections["rules"] = draft.summary
    if draft.kind in REASONING_KINDS:
        sections["synthesis"] = summary
    if model:
        sections["model"] = known_model(model)
        sections["model_label"] = model_label(model)
    return replace(draft, summary=summary, sections=sections)


def _date_text(value: date | None) -> str:
    return value.isoformat() if value else ""


def _agent_text(payload: dict[str, Any]) -> str | None:
    top = payload.get("output_text")
    if isinstance(top, str) and top.strip():
        return top.strip()
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
    return None


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned[: cleaned.rfind("```")]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise json.JSONDecodeError("Expected an object", cleaned, 0)
    return parsed
