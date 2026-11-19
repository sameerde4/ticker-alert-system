"""Evidence story: every alert checks both sides; the last step grades alignment."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .engine import AlertDraft
from .forest_wording import forest_evidence_detail

# Granular second-side outcomes shown in What happened (step 3 + headline).
ALIGNMENT_SUPPORTS = "supports"
ALIGNMENT_LEANS = "leans"
ALIGNMENT_NEUTRAL = "neutral"
ALIGNMENT_LEANS_AGAINST = "leans_against"
ALIGNMENT_CONTRADICTS = "contradicts"


def attach_evidence_story(draft: AlertDraft) -> AlertDraft:
    """Add ``sections.evidence`` without changing the alert decision."""
    sections = dict(draft.sections or {})
    sections["evidence"] = build_evidence_story(draft)
    return replace(draft, sections=sections)


def build_evidence_story(draft: AlertDraft) -> dict[str, Any]:
    """Structured steps: entry side → other side measured → alignment grade."""
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    entry = str(sections.get("entry") or _infer_entry(draft))
    supports = sections.get("second_supports")
    if supports is None:
        supports = draft.kind == "news_price"
    supports = bool(supports)
    article_count = len(draft.articles or ())
    forest = sections.get("forest")
    alignment = classify_second_side_alignment(draft, entry=entry, supports=supports)
    move = _observed_move(draft)
    threshold = _price_threshold(draft)
    percent_cleared: bool | None = None
    if move is not None:
        try:
            percent_cleared = abs(float(move)) >= threshold
        except (TypeError, ValueError):
            percent_cleared = None
    forest_anomalous = isinstance(forest, dict) and bool(forest.get("anomalous"))
    gate_label = _price_gate_case(
        percent_cleared=percent_cleared, forest_anomalous=forest_anomalous
    )
    trigger_label = price_trigger_note(
        draft,
        forest,
        percent_cleared=percent_cleared,
        forest_anomalous=forest_anomalous,
    )

    if entry == "news":
        return {
            "headline": f"News checked → price checked → {alignment['headline_tail']}",
            "entry": "news",
            "second_supports": supports,
            "alignment": alignment["level"],
            "price_gate": gate_label.strip("()"),
            "price_triggers": trigger_label,
            "steps": [
                {
                    "id": "news_checked",
                    "ok": True,
                    "tone": "ok",
                    "label": "News checked",
                    "detail": (
                        f"FinBERT cleared the gate on {article_count} near-term headline(s) "
                        f"for {draft.symbol}."
                    ),
                },
                {
                    "id": "price_checked",
                    "ok": True,
                    "tone": "ok",
                    "label": "Price checked",
                    "detail": _price_checked_detail(draft, forest, as_support_check=True),
                },
                {
                    "id": "support",
                    "ok": alignment["ok"],
                    "tone": alignment["tone"],
                    "label": alignment["label"],
                    "detail": alignment["detail"],
                },
            ],
        }

    return {
        "headline": f"Price noticed → news checked → {alignment['headline_tail']}",
        "entry": "price",
        "second_supports": supports,
        "alignment": alignment["level"],
        "price_gate": gate_label.strip("()"),
        "price_triggers": trigger_label,
        "steps": [
            {
                "id": "price_noticed",
                "ok": True,
                "tone": "ok",
                "label": "Price noticed",
                "detail": _price_checked_detail(draft, forest, as_support_check=False),
            },
            {
                "id": "news_checked",
                "ok": True,
                "tone": "ok",
                "label": "News checked",
                "detail": (
                    f"Scored {article_count} near-term headline(s) for {draft.symbol}."
                    if article_count
                    else "Near-term headlines were checked; none cleared the FinBERT gate."
                ),
            },
            {
                "id": "support",
                "ok": alignment["ok"],
                "tone": alignment["tone"],
                "label": alignment["label"],
                "detail": alignment["detail"],
            },
        ],
    }


def classify_second_side_alignment(
    draft: AlertDraft,
    *,
    entry: str,
    supports: bool,
) -> dict[str, Any]:
    """Grade how the second side relates to the entry side (not only yes/no)."""
    if entry == "news":
        return _alignment_when_news_led(draft, supports=supports)
    return _alignment_when_price_led(draft, supports=supports)


def _alignment_when_news_led(draft: AlertDraft, *, supports: bool) -> dict[str, Any]:
    move = _observed_move(draft)
    threshold = _price_threshold(draft)
    news_dir = _news_direction(draft.sentiment_score)
    price_dir = _price_direction(move)
    move_text = _fmt_move(move)
    rule_text = f"{threshold * 100:.1f}%"

    if supports:
        return _alignment_result(
            ALIGNMENT_SUPPORTS,
            label="Price supports news",
            headline_tail="price supports the news",
            detail=(
                f"The session move ({move_text}) cleared the {rule_text} rule and points the "
                "same way as the headlines."
                if move is not None
                else "The price slice cleared the rule beside these headlines."
            ),
            tone="ok",
            ok=True,
        )

    if move is None:
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="Price has no clear reading",
            headline_tail="price has no clear reading",
            detail="Price was checked, but there was no usable session move to compare with the news.",
            tone="neutral",
            ok=False,
        )

    magnitude = abs(float(move))
    half = threshold * 0.5

    if news_dir and price_dir and news_dir == price_dir:
        if magnitude >= half:
            return _alignment_result(
                ALIGNMENT_LEANS,
                label="Price somewhat supports news",
                headline_tail="price somewhat supports the news",
                detail=(
                    f"Price moved {move_text} the same way as the news tone, but stayed under the "
                    f"{rule_text} rule — same direction, not enough to clear a price alert."
                ),
                tone="partial",
                ok=True,
            )
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="Price mostly flat vs news",
            headline_tail="price is mostly flat beside the news",
            detail=(
                f"Price only moved {move_text} (under {rule_text}). Direction loosely matches the "
                "news, but the move is too small to count as support."
            ),
            tone="neutral",
            ok=False,
        )

    if news_dir and price_dir and news_dir != price_dir:
        if magnitude >= half:
            return _alignment_result(
                ALIGNMENT_CONTRADICTS,
                label="Price contradicts news",
                headline_tail="price contradicts the news",
                detail=(
                    f"Price moved {move_text}, the opposite way from the headline tone, while still "
                    f"under the {rule_text} rule — a real disagreement, not just a missed threshold."
                ),
                tone="no",
                ok=False,
            )
        return _alignment_result(
            ALIGNMENT_LEANS_AGAINST,
            label="Price somewhat disagrees with news",
            headline_tail="price somewhat disagrees with the news",
            detail=(
                f"Price edged {move_text} against the news tone (under {rule_text}). Soft pushback, "
                "not a full opposite move."
            ),
            tone="partial",
            ok=False,
        )

    return _alignment_result(
        ALIGNMENT_NEUTRAL,
        label="Price does not confirm news",
        headline_tail="price does not confirm the news",
        detail=(
            f"Observed move was {move_text}, under the {rule_text} rule, with no clear "
            "direction match or clash against the news tone."
        ),
        tone="neutral",
        ok=False,
    )


def _alignment_when_price_led(draft: AlertDraft, *, supports: bool) -> dict[str, Any]:
    article_count = len(draft.articles or ())
    move = draft.price_change_pct
    news_dir = _news_direction(draft.sentiment_score)
    price_dir = _price_direction(move)
    move_text = _fmt_move(move)
    score = draft.sentiment_score
    score_text = f"{score:.0f}/100" if score is not None else "n/a"

    if supports:
        return _alignment_result(
            ALIGNMENT_SUPPORTS,
            label="News supports price",
            headline_tail="news supports the move",
            detail=(
                "Headline(s) lined up with the same price slice as the move, so news backs the "
                f"price alert (combined sentiment {score_text})."
            ),
            tone="ok",
            ok=True,
        )

    if article_count == 0:
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="No news evidence",
            headline_tail="no news evidence for the move",
            detail="No qualifying headlines cleared the FinBERT gate beside this price move.",
            tone="neutral",
            ok=False,
        )

    if news_dir and price_dir and news_dir == price_dir:
        return _alignment_result(
            ALIGNMENT_LEANS,
            label="News tone somewhat supports price",
            headline_tail="news tone somewhat supports the move",
            detail=(
                f"Near-term headlines were scored ({article_count}; combined {score_text}) and the "
                f"tone points the same way as the {move_text} move, but none lined up with the "
                "exact price slice that fired — soft agreement, not a fused alert."
            ),
            tone="partial",
            ok=True,
        )

    if news_dir and price_dir and news_dir != price_dir:
        return _alignment_result(
            ALIGNMENT_CONTRADICTS,
            label="News contradicts price",
            headline_tail="news contradicts the move",
            detail=(
                f"Headlines cleared FinBERT ({article_count}; combined {score_text}) but the tone "
                f"points the opposite way from the {move_text} move — disagreement, not missing news."
            ),
            tone="no",
            ok=False,
        )

    return _alignment_result(
        ALIGNMENT_NEUTRAL,
        label="News does not confirm price",
        headline_tail="news does not confirm the move",
        detail=(
            f"Headlines were reviewed ({article_count}; combined {score_text}); none lined up with "
            "the slice that moved, and the tone is too mixed to call support or contradiction."
        ),
        tone="neutral",
        ok=False,
    )


def _alignment_result(
    level: str,
    *,
    label: str,
    headline_tail: str,
    detail: str,
    tone: str,
    ok: bool,
) -> dict[str, Any]:
    return {
        "level": level,
        "label": label,
        "headline_tail": headline_tail,
        "detail": detail,
        "tone": tone,
        "ok": ok,
    }


def _infer_entry(draft: AlertDraft) -> str:
    if draft.kind == "news":
        return "news"
    if draft.kind == "news_price":
        return "price"
    return "price"


def _observed_move(draft: AlertDraft) -> float | None:
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    if draft.price_change_pct is not None:
        try:
            return float(draft.price_change_pct)
        except (TypeError, ValueError):
            pass
    raw = sections.get("observed_price_change_pct")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _price_threshold(draft: AlertDraft) -> float:
    try:
        value = float(draft.price_move_threshold) if draft.price_move_threshold is not None else 0.03
    except (TypeError, ValueError):
        value = 0.03
    return value if value > 0 else 0.03


def _news_direction(score: float | None) -> str | None:
    if score is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value >= 57.5:
        return "up"
    if value <= 42.5:
        return "down"
    return None


def _price_direction(change: float | None) -> str | None:
    if change is None:
        return None
    try:
        value = float(change)
    except (TypeError, ValueError):
        return None
    if value > 0.001:
        return "up"
    if value < -0.001:
        return "down"
    return None


def _fmt_move(change: float | None) -> str:
    if change is None:
        return "n/a"
    return f"{change * 100:+.2f}%"


def _price_gate_case(*, percent_cleared: bool | None, forest_anomalous: bool) -> str:
    """Short bracket tag: which price gates fired (percent / forest / both / neither)."""
    if percent_cleared is True and forest_anomalous:
        return "(percent + forest)"
    if percent_cleared is True:
        return "(percent only)"
    if forest_anomalous:
        return "(forest only)"
    return "(neither gate)"


def _forest_feature_case_tags(features: dict[str, Any] | None) -> list[str]:
    """Map loudest forest features to doc case numbers (#3–#6)."""
    if not isinstance(features, dict):
        return []
    ranked: list[tuple[float, str]] = []
    gap = _as_float_safe(features.get("gap_return"))
    session = _as_float_safe(features.get("session_return"))
    close = _as_float_safe(features.get("close_return"))
    volume_z = _as_float_safe(features.get("volume_zscore"))
    if gap is not None:
        ranked.append((abs(gap), "#3 gap"))
    if session is not None:
        ranked.append((abs(session), "#4 session"))
    if close is not None:
        ranked.append((abs(close), "#5 close"))
    if volume_z is not None:
        ranked.append((abs(volume_z) / 10.0, "#6 volume z"))
    ranked.sort(key=lambda row: row[0], reverse=True)
    return [label for _, label in ranked[:2]]


def price_trigger_note(
    draft: AlertDraft,
    forest: Any,
    *,
    percent_cleared: bool | None,
    forest_anomalous: bool,
) -> str:
    """Compact note naming which documented price-trigger cases apply.

    Doc cases: #1 percent, #2 forest, #3–#6 forest features, #7 volume-spike note.
    """
    bits: list[str] = []
    if percent_cleared is True:
        bits.append("#1 percent")
    if forest_anomalous:
        feature_tags = _forest_feature_case_tags(
            forest.get("features") if isinstance(forest, dict) else None
        )
        if feature_tags:
            bits.append(f"#2 forest ({', '.join(feature_tags)})")
        else:
            bits.append("#2 forest")
    if draft.volume_spike:
        bits.append("#7 volume spike noted")
    if not bits:
        return "triggers: none (price under both gates)"
    return "triggers: " + " + ".join(bits)


def _as_float_safe(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_checked_detail(draft: AlertDraft, forest: Any, *, as_support_check: bool) -> str:
    """Measurement-only copy for step 2 — verdict stays in the alignment step."""
    move = _observed_move(draft)
    move_text = _fmt_move(move)
    threshold = _price_threshold(draft)
    rule_text = f"{threshold * 100:.1f}%"
    parts: list[str] = []
    forest_anomalous = isinstance(forest, dict) and bool(forest.get("anomalous"))
    percent_cleared: bool | None = None
    if move is not None:
        try:
            percent_cleared = abs(float(move)) >= threshold
        except (TypeError, ValueError):
            percent_cleared = None
    gate = _price_gate_case(percent_cleared=percent_cleared, forest_anomalous=forest_anomalous)
    trigger = price_trigger_note(
        draft,
        forest,
        percent_cleared=percent_cleared,
        forest_anomalous=forest_anomalous,
    )

    if as_support_check:
        if move is None:
            parts.append(
                f"Session price was measured; no usable move was available beside the news. "
                f"{gate} [{trigger}]."
            )
        elif percent_cleared:
            parts.append(
                f"Observed session move {move_text} cleared the {rule_text} rule "
                f"{gate} [{trigger}]."
            )
        else:
            parts.append(
                f"Observed session move {move_text} stayed under the {rule_text} rule "
                f"{gate} [{trigger}]."
            )
    elif forest_anomalous:
        # Forest can fire under the percent rule — do not claim the percent gate cleared.
        if percent_cleared is True:
            parts.append(
                f"Session move {move_text} cleared the {rule_text} percent rule "
                f"{gate} [{trigger}]."
            )
        elif move is not None:
            parts.append(
                f"Session move {move_text} stayed under the {rule_text} percent rule "
                f"{gate} [{trigger}]."
            )
        else:
            parts.append(
                f"Session price was scored by the registered Isolation Forest "
                f"{gate} [{trigger}]."
            )
    else:
        parts.append(
            f"Session move {move_text} cleared the {rule_text} percent rule "
            f"{gate} [{trigger}]."
        )
    forest_line = forest_evidence_detail(forest if isinstance(forest, dict) else None)
    if forest_line:
        parts.append(forest_line)
    return " ".join(parts)
