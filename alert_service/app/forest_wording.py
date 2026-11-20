"""Deterministic trader-facing copy when Isolation Forest fires a price alert.

Price-only rows stay off Perplexity; this module is the richer forest-aware wording.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .engine import PRICE_SPAN, AlertDraft, price_change_pct


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


def forest_driver_explanations(
    features: dict[str, Any] | None, *, limit: int = 2
) -> list[str]:
    """Loudest features as short 'number (why it matters)' phrases for What happened."""
    if not isinstance(features, dict):
        return []
    ranked: list[tuple[float, str]] = []
    gap = _as_float(features.get("gap_return"))
    session = _as_float(features.get("session_return"))
    close = _as_float(features.get("close_return"))
    volume_z = _as_float(features.get("volume_zscore"))
    if gap is not None:
        if gap <= -0.02:
            why = "big overnight drop vs prior close"
        elif gap >= 0.02:
            why = "big overnight jump vs prior close"
        else:
            why = "overnight move vs prior close"
        ranked.append((abs(gap), f"gap {_fmt_pct(gap)} ({why})"))
    if session is not None:
        ranked.append(
            (abs(session), f"open→last {_fmt_pct(session)} (regular-session move from the open)")
        )
    if close is not None:
        ranked.append(
            (abs(close), f"close vs prior {_fmt_pct(close)} (last vs prior close)")
        )
    if volume_z is not None:
        if volume_z <= -1.5:
            why = "session volume far below its usual level"
        elif volume_z >= 1.5:
            why = "session volume far above its usual level"
        else:
            why = "session volume vs its usual level"
        ranked.append((abs(volume_z) / 10.0, f"vol z {volume_z:+.2f} ({why})"))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [label for _, label in ranked[: max(0, limit)]]


def forest_driver_sentence(features: dict[str, Any] | None) -> str:
    """Name the strongest drivers so the card is not only a raw score dump."""
    lines = forest_driver_explanations(features, limit=2)
    if not lines:
        return "The registered model marked this session's price/volume pattern unusual."
    if len(lines) == 1:
        return f"What stood out most was {lines[0]}."
    return f"What stood out most was {lines[0]} and {lines[1]}."


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


def forest_evidence_bullets(forest: dict[str, Any] | None) -> list[str]:
    """Why-anomalous bullets for What happened (one driver per line)."""
    if not isinstance(forest, dict) or not forest.get("anomalous"):
        return []
    features = forest.get("features") if isinstance(forest.get("features"), dict) else None
    lines = forest_driver_explanations(features, limit=2)
    if lines:
        return list(lines)
    return ["Session price/volume pattern looked unusual versus recent history."]


def forest_evidence_detail(forest: dict[str, Any] | None) -> str:
    """Joined Why-anomalous copy (legacy single-string callers)."""
    bullets = forest_evidence_bullets(forest)
    if not bullets:
        return ""
    if len(bullets) == 1:
        return f"Marked anomalous: {bullets[0]}."
    return "Marked anomalous: " + "; ".join(bullets) + "."


def news_tail_from_sections(sections: dict[str, Any] | None, summary: str | None = None) -> str | None:
    """Reuse the news outcome already on a price-only draft when rewriting forest copy."""
    if isinstance(sections, dict):
        if sections.get("second_supports") is True:
            return "Near-term headlines lined up with this move."
        if sections.get("news_join_path") == "climate":
            return "News joined via climate FinBERT average (soft join)."
        if sections.get("news_gate_cleared") is False and (
            "climate sentiment" in str(sections.get("news") or "").lower()
            or "none cleared the" in str(sections.get("news") or "").lower()
            or "climate average" in (summary or "").lower()
            or "soft combined sentiment" in (summary or "").lower()
        ):
            return "Near-term headlines were scored below the FinBERT join gates (climate context only)."
        news = str(sections.get("news") or "")
        news_l = news.lower()
        if "were found on this trading day" in news_l or (
            "no near-term headlines" in news_l and "cleared" not in news_l
        ):
            return "News was checked; no near-term headlines were found."
        if "no near-term headlines" in news_l or "no news evidence" in news_l:
            return "News was checked with no qualifying headlines."
        if "did not line up" in news_l or "none of these headlines lined up" in news_l:
            return "Near-term headlines were checked; none lined up with this move."
        if "none cleared the" in news_l and "finbert gate" in news_l:
            return "Near-term headlines were scored below the FinBERT gate (soft lean only)."
    text = (summary or "").lower()
    if "no headline lined up" in text:
        return "No headline lined up with this move."
    if "soft combined sentiment" in text or "stays price-led" in text:
        return "Near-term headlines were scored below the FinBERT gate (soft lean only)."
    if "no qualifying headlines" in text or "no near-term headlines" in text:
        return "News was checked with no near-term headlines."
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
    sections.setdefault("price_span", PRICE_SPAN["live"])

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
