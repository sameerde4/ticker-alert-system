"""Deterministic trader-facing copy when Isolation Forest fires a price alert.

Price-only rows stay off Perplexity; this module is the richer forest-aware wording.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .engine import AlertDraft, price_change_pct


def forest_feature_callouts(features: dict[str, Any] | None) -> list[str]:
    """Plain-English notes for the four session features the forest scores."""
    if not isinstance(features, dict):
        return []
    out: list[str] = []
    gap = _as_float(features.get("gap_return"))
    session = _as_float(features.get("session_return"))
    close = _as_float(features.get("close_return"))
    volume_z = _as_float(features.get("volume_zscore"))
    if gap is not None:
        out.append(f"overnight gap {_fmt_pct(gap)}")
    if session is not None:
        out.append(f"open→last {_fmt_pct(session)}")
    if close is not None:
        out.append(f"close vs prior {_fmt_pct(close)}")
    if volume_z is not None:
        out.append(f"volume z-score {volume_z:+.2f}")
    return out


def forest_driver_sentence(features: dict[str, Any] | None) -> str:
    """Name the strongest drivers so the card is not only a raw score dump."""
    if not isinstance(features, dict):
        return "The registered model marked this session's price/volume pattern unusual."
    ranked: list[tuple[float, str]] = []
    gap = _as_float(features.get("gap_return"))
    session = _as_float(features.get("session_return"))
    close = _as_float(features.get("close_return"))
    volume_z = _as_float(features.get("volume_zscore"))
    if gap is not None:
        ranked.append((abs(gap), f"the overnight gap ({_fmt_pct(gap)})"))
    if session is not None:
        ranked.append((abs(session), f"the open→last move ({_fmt_pct(session)})"))
    if close is not None:
        ranked.append((abs(close), f"the close versus prior ({_fmt_pct(close)})"))
    if volume_z is not None:
        ranked.append((abs(volume_z) / 10.0, f"session volume (z {volume_z:+.2f})"))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if not ranked:
        return "The registered model marked this session's price/volume pattern unusual."
    top = [label for _, label in ranked[:2]]
    if len(top) == 1:
        return f"What stood out most was {top[0]}."
    return f"What stood out most was {top[0]} and {top[1]}."


def forest_price_summary(
    symbol: str,
    *,
    model_id: str,
    forest_score: float,
    score_cutoff: float,
    features: dict[str, Any],
    open_px: float,
    last_px: float,
    price_move_threshold: float,
    change: float | None = None,
    news_tail: str | None = None,
) -> str:
    """Full Summary text for a forest-led (or forest+percent) price-only alert."""
    move = change if change is not None else price_change_pct(last_px, open_px)
    percent_cleared = move is not None and abs(move) >= price_move_threshold
    rule_text = f"{price_move_threshold * 100:.1f}%"
    move_text = _fmt_pct(move) if move is not None else "n/a"
    callouts = forest_feature_callouts(features)
    feature_clause = (", ".join(callouts) + ".") if callouts else ""
    if percent_cleared:
        gate = (
            f"The Isolation Forest ({model_id}) marked the session anomalous "
            f"(score {forest_score:.4f}, at or below cutoff {score_cutoff:.4f}), and the "
            f"open→last move of {move_text} also cleared the {rule_text} percent rule "
            f"(from {_money(open_px)} to {_money(last_px)})."
        )
    else:
        gate = (
            f"The Isolation Forest ({model_id}) marked the session anomalous "
            f"(score {forest_score:.4f}, at or below cutoff {score_cutoff:.4f}) even though "
            f"open→last ({move_text}, {_money(open_px)} → {_money(last_px)}) stayed under "
            f"the {rule_text} percent rule — the model fired on the price/volume pattern, "
            "not the percent alone."
        )
    body = f"{symbol}: {gate} {forest_driver_sentence(features)}"
    if feature_clause:
        body = f"{body} Session features: {feature_clause}"
    if news_tail:
        body = f"{body.rstrip()} {news_tail.strip()}"
    return body.strip()


def forest_price_section(
    symbol: str,
    *,
    open_px: float,
    last_px: float,
    change: float | None,
    price_move_threshold: float,
    forest: dict[str, Any],
) -> str:
    """Price accordion text: levels + percent status + short forest note."""
    move = change if change is not None else price_change_pct(last_px, open_px)
    move_text = _fmt_pct(move) if move is not None else "n/a"
    rule_text = f"{price_move_threshold * 100:.1f}%"
    percent_cleared = move is not None and abs(move) >= price_move_threshold
    percent_line = (
        f"Open→last {move_text} cleared the {rule_text} rule."
        if percent_cleared
        else f"Open→last {move_text} stayed under the {rule_text} rule."
    )
    model_id = str(forest.get("model_id") or "isolation_forest")
    score = _as_float(forest.get("forest_score")) or 0.0
    cutoff = _as_float(forest.get("score_cutoff"))
    cutoff_text = f"{cutoff:.4f}" if cutoff is not None else "n/a"
    return (
        f"{symbol} is at {_money(last_px)}, from the open of {_money(open_px)} ({move_text}). "
        f"{percent_line} Isolation Forest {model_id} score {score:.4f} "
        f"(cutoff {cutoff_text}) marked the session anomalous. "
        f"{forest_driver_sentence(forest.get('features') if isinstance(forest.get('features'), dict) else {})}"
    )


def forest_evidence_detail(forest: dict[str, Any] | None) -> str:
    """Measurement line for What happened when the forest tripped."""
    if not isinstance(forest, dict) or not forest.get("anomalous"):
        return ""
    model_id = str(forest.get("model_id") or "model")
    score = _as_float(forest.get("forest_score")) or 0.0
    cutoff = _as_float(forest.get("score_cutoff"))
    cutoff_bit = f", cutoff {cutoff:.4f}" if cutoff is not None else ""
    drivers = forest_driver_sentence(
        forest.get("features") if isinstance(forest.get("features"), dict) else None
    )
    callouts = forest_feature_callouts(
        forest.get("features") if isinstance(forest.get("features"), dict) else None
    )
    feature_bit = f" Features: {', '.join(callouts)}." if callouts else ""
    return (
        f"Isolation Forest {model_id} marked the session anomalous "
        f"(score {score:.4f}{cutoff_bit}). {drivers}{feature_bit}"
    )


def news_tail_from_sections(sections: dict[str, Any] | None, summary: str | None = None) -> str | None:
    """Reuse the news outcome already on a price-only draft when rewriting forest copy."""
    if isinstance(sections, dict):
        if sections.get("second_supports") is True:
            return "Near-term headlines lined up with this move."
        news = str(sections.get("news") or "")
        if "no near-term headlines" in news.lower() or "no news evidence" in news.lower():
            return "News was checked with no qualifying headlines."
        if "did not line up" in news.lower() or "none of these headlines lined up" in news.lower():
            return "Near-term headlines were checked; none lined up with this move."
    text = (summary or "").lower()
    if "no headline lined up" in text:
        return "No headline lined up with this move."
    if "no qualifying headlines" in text:
        return "News was checked with no qualifying headlines."
    return None


def enrich_price_draft_with_forest_wording(draft: AlertDraft) -> AlertDraft:
    """Rewrite Summary / Price for price-only rows that carry an anomalous forest block.

    News / news_price keep their Together text; only the Price section is forest-aware.
    """
    sections = dict(draft.sections or {})
    forest = sections.get("forest")
    if not isinstance(forest, dict) or not forest.get("anomalous"):
        return draft

    # Prefer session open/last stamped when the forest scored (live or Scan today).
    # Fall back to draft levels for older rows.
    open_px = _as_float(forest.get("session_open"))
    last_px = _as_float(forest.get("session_last"))
    if open_px is None:
        open_px = float(draft.prior_close) if draft.prior_close is not None else None
    if last_px is None:
        last_px = float(draft.latest_close) if draft.latest_close is not None else None
    if open_px is None or last_px is None:
        return draft

    threshold = float(draft.price_move_threshold) if draft.price_move_threshold is not None else 0.03
    features = forest.get("features") if isinstance(forest.get("features"), dict) else {}
    model_id = str(forest.get("model_id") or "isolation_forest")
    forest_score = float(forest.get("forest_score") or 0.0)
    score_cutoff = float(forest.get("score_cutoff") or 0.0)
    session_change = price_change_pct(last_px, open_px)

    price_text = forest_price_section(
        draft.symbol,
        open_px=open_px,
        last_px=last_px,
        change=session_change,
        price_move_threshold=threshold,
        forest=forest,
    )
    sections["price"] = price_text

    if draft.kind != "price":
        return replace(draft, sections=sections)

    news_tail = news_tail_from_sections(sections, draft.summary)
    summary = forest_price_summary(
        draft.symbol,
        model_id=model_id,
        forest_score=forest_score,
        score_cutoff=score_cutoff,
        features=features,
        open_px=open_px,
        last_px=last_px,
        price_move_threshold=threshold,
        change=session_change,
        news_tail=news_tail,
    )
    sections["synthesis"] = summary
    sections.setdefault("entry", "price")
    if "second_supports" not in sections:
        sections["second_supports"] = False
    return replace(draft, summary=summary, sections=sections)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(change: float | None) -> str:
    if change is None:
        return "n/a"
    return f"{change * 100:+.2f}%"


def _money(value: float) -> str:
    return f"${value:,.2f}"
