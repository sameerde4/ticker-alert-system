"""Evidence story: every alert checks both sides; the last step grades alignment."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .engine import AlertDraft
from .forest_wording import forest_evidence_bullets

# Granular second-side outcomes shown in What happened (step 3 + headline).
ALIGNMENT_SUPPORTS = "supports"
ALIGNMENT_LEANS = "leans"
ALIGNMENT_NEUTRAL = "neutral"
ALIGNMENT_LEANS_AGAINST = "leans_against"
ALIGNMENT_CONTRADICTS = "contradicts"

# Direction agreement between price move and news tone (card chip).
AGREEMENT_AGREES = "agrees"
AGREEMENT_DISAGREES = "disagrees"
AGREEMENT_MIXED = "mixed"
AGREEMENT_NO_NEWS = "no_news"

AGREEMENT_LABELS = {
    AGREEMENT_AGREES: "agrees",
    AGREEMENT_DISAGREES: "disagrees",
    AGREEMENT_MIXED: "mixed",
    AGREEMENT_NO_NEWS: "no recent news",
}


def attach_evidence_story(draft: AlertDraft) -> AlertDraft:
    """Add evidence, price-shape, and agreement tags without changing the decision."""
    sections = dict(draft.sections or {})
    evidence = build_evidence_story(draft)
    sections["evidence"] = evidence
    # Keep sections.entry aligned with What happened (Live/forest force price-first).
    if evidence.get("entry"):
        sections["entry"] = evidence["entry"]
    shape = evidence.get("price_shape")
    if shape:
        sections["price_shape"] = shape
    else:
        sections.pop("price_shape", None)
    agreement = evidence.get("agreement")
    if agreement:
        sections["agreement"] = agreement
    else:
        sections.pop("agreement", None)
    return replace(draft, sections=sections)


def _price_first_door(draft: AlertDraft) -> bool:
    """True when the product path noticed price/forest before grading news.

    Live always opens on a price/forest door. Forest-anomalous rows (even under the
    percent floor) also entered via price. Those must not render as news→price in
    What happened just because the final kind chip is news-led.
    """
    if draft.origin in ("live", "both"):
        return True
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    forest = sections.get("forest")
    return isinstance(forest, dict) and bool(forest.get("anomalous"))


def build_evidence_story(draft: AlertDraft) -> dict[str, Any]:
    """Structured steps: entry side → other side measured → alignment grade."""
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    entry = str(sections.get("entry") or _infer_entry(draft))
    if _price_first_door(draft):
        entry = "price"
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
    shape_key = resolve_price_shape(
        percent_cleared=percent_cleared, forest_anomalous=forest_anomalous
    )
    gate_label = _price_gate_case(
        percent_cleared=percent_cleared, forest_anomalous=forest_anomalous
    )
    trigger_label = price_trigger_note(
        draft,
        forest,
        percent_cleared=percent_cleared,
        forest_anomalous=forest_anomalous,
    )

    # Direction chip compares move vs FinBERT tone (not "both sides present").
    agreement = resolve_direction_agreement(
        draft, forest_anomalous=forest_anomalous
    )

    if entry == "news":
        return {
            "headline": f"News checked → price checked → {alignment['headline_tail']}",
            "entry": "news",
            "second_supports": supports,
            "alignment": alignment["level"],
            "agreement": agreement,
            "price_shape": shape_key,
            "price_gate": gate_label.strip("()"),
            "price_triggers": trigger_label,
            "steps": [
                {
                    "id": "news_checked",
                    "ok": True,
                    "tone": "ok",
                    "label": "News checked",
                    "detail": _news_checked_detail(draft, article_count),
                },
                _price_step(
                    draft,
                    forest,
                    step_id="price_checked",
                    label="Price checked",
                    as_support_check=True,
                ),
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
        "agreement": agreement,
        "price_shape": shape_key,
        "price_gate": gate_label.strip("()"),
        "price_triggers": trigger_label,
        "steps": [
            _price_step(
                draft,
                forest,
                step_id="price_noticed",
                label="Price noticed",
                as_support_check=False,
            ),
            {
                "id": "news_checked",
                "ok": True,
                "tone": "ok",
                "label": "News checked",
                "detail": _news_checked_detail(draft, article_count),
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


def _news_join_path(draft: AlertDraft) -> str | None:
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    path = sections.get("news_join_path")
    if path in ("headline", "climate"):
        return str(path)
    return None


def _news_checked_detail(draft: AlertDraft, article_count: int) -> str:
    path = _news_join_path(draft)
    polarized = _sentiment_is_polarized(draft)
    split_note = " Headlines are polarized (both sides of 50)." if polarized else ""
    if path == "climate":
        return (
            f"Climate join for {draft.symbol}: scored {article_count} near-term headline(s); "
            f"no single headline cleared FinBERT, but the full average did.{split_note}"
        )
    if path == "headline":
        return (
            f"Scored {article_count} near-term headline(s) for {draft.symbol}; at least one "
            f"cleared the FinBERT gate (climate average used for Sentiment).{split_note}"
        )
    if article_count and not _news_gate_cleared(draft):
        return (
            f"Scored {article_count} near-term headline(s) for {draft.symbol}; neither a single "
            f"headline nor the climate average cleared the FinBERT gate (soft evidence only)."
            f"{split_note}"
        )
    if article_count:
        return (
            f"Scored {article_count} near-term headline(s) for {draft.symbol} "
            f"(climate average for Sentiment).{split_note}"
        )
    return "Near-term headlines were checked; none were found for this session."


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
    join_path = _news_join_path(draft)
    gate_cleared = _news_gate_cleared(draft)
    soft = join_path is None and not gate_cleared and article_count > 0
    polarized = _sentiment_is_polarized(draft)
    news_dir = None if polarized else _news_direction(draft.sentiment_score, soft=soft or join_path == "climate")
    price_dir = _price_direction(move)
    move_text = _fmt_move(move)
    score = draft.sentiment_score
    score_text = f"{score:.0f}/100" if score is not None else "n/a"

    if supports:
        if join_path == "climate":
            detail = (
                f"Climate join: the full near-term FinBERT average ({score_text}) cleared the gate "
                f"beside the {move_text} move (no single headline cleared on its own)."
            )
            if polarized:
                detail += " Headlines are polarized, so Direction reads mixed."
            return _alignment_result(
                ALIGNMENT_SUPPORTS,
                label="Climate news supports price",
                headline_tail="climate news supports the move",
                detail=detail,
                tone="ok",
                ok=True,
            )
        detail = (
            "Headline(s) lined up with the same price slice as the move, so news backs the "
            f"price alert (climate sentiment {score_text})."
        )
        if polarized:
            detail += " Headlines are polarized, so Direction reads mixed."
        return _alignment_result(
            ALIGNMENT_SUPPORTS,
            label="News supports price",
            headline_tail="news supports the move",
            detail=detail,
            tone="ok",
            ok=True,
        )

    if article_count == 0:
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="No news evidence",
            headline_tail="no news evidence for the move",
            detail="No near-term headlines were found beside this price move.",
            tone="neutral",
            ok=False,
        )

    if polarized and soft:
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="Soft news lean is polarized",
            headline_tail="soft news lean is polarized beside the move",
            detail=(
                f"Near-term headlines were scored ({article_count}; climate {score_text}) with both "
                "positive and negative leans — Direction is mixed; news did not join."
            ),
            tone="neutral",
            ok=False,
        )

    if soft:
        if news_dir and price_dir and news_dir == price_dir:
            return _alignment_result(
                ALIGNMENT_LEANS,
                label="Soft news lean supports price",
                headline_tail="soft news lean supports the move",
                detail=(
                    f"Near-term headlines were scored ({article_count}; climate {score_text}) "
                    f"and lean the same way as the {move_text} move, but neither a single headline "
                    "nor the climate average cleared the FinBERT gate — context only."
                ),
                tone="partial",
                ok=True,
            )
        if news_dir and price_dir and news_dir != price_dir:
            return _alignment_result(
                ALIGNMENT_LEANS_AGAINST,
                label="Soft news lean disagrees with price",
                headline_tail="soft news lean disagrees with the move",
                detail=(
                    f"Near-term headlines were scored ({article_count}; climate {score_text}) "
                    f"and lean against the {move_text} move. News did not join; soft disagreement only."
                ),
                tone="partial",
                ok=False,
            )
        return _alignment_result(
            ALIGNMENT_NEUTRAL,
            label="Soft news lean is mixed",
            headline_tail="soft news lean is mixed beside the move",
            detail=(
                f"Near-term headlines were scored ({article_count}; climate {score_text}); "
                "news did not join, and the climate lean is too close to neutral to call "
                "support or disagreement."
            ),
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
    if _price_first_door(draft):
        return "price"
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


def _news_gate_cleared(draft: AlertDraft) -> bool:
    """True when listed headlines cleared the FinBERT join gate (default for older rows)."""
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    if "news_gate_cleared" in sections:
        return bool(sections.get("news_gate_cleared"))
    # Legacy rows: articles on a price card meant gate-cleared (or empty = no soft list).
    return True


def _news_direction(score: float | None, *, soft: bool = False) -> str | None:
    if score is None:
        return None
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if soft:
        # Below-gate soft lean: any tilt off 50 counts for Direction.
        if value > 50.0:
            return "up"
        if value < 50.0:
            return "down"
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


# Price-shape keys stamped on ``sections.price_shape`` / evidence (UI chips).
PRICE_SHAPE_VOLATILE = "volatile"
PRICE_SHAPE_ANOMALOUS = "anomalous"
PRICE_SHAPE_BOTH = "volatile_anomalous"

PRICE_SHAPE_LABELS = {
    PRICE_SHAPE_VOLATILE: "volatile",
    PRICE_SHAPE_ANOMALOUS: "anomalous",
    PRICE_SHAPE_BOTH: "volatile + anomalous",
}


def resolve_price_shape(
    *, percent_cleared: bool | None, forest_anomalous: bool
) -> str | None:
    """Price-shape tag: volatile / anomalous / volatile+anomalous, or None if neither."""
    if percent_cleared is True and forest_anomalous:
        return PRICE_SHAPE_BOTH
    if percent_cleared is True:
        return PRICE_SHAPE_VOLATILE
    if forest_anomalous:
        return PRICE_SHAPE_ANOMALOUS
    return None


def price_shape_label(shape: str | None) -> str | None:
    """Human label for a price-shape key."""
    if not shape:
        return None
    return PRICE_SHAPE_LABELS.get(str(shape), str(shape).replace("_", " "))


def _has_price_and_news_sides(draft: AlertDraft, *, forest_anomalous: bool) -> bool:
    """True when we can compare price direction with news tone on the card."""
    has_news = draft.sentiment_score is not None or bool(draft.articles)
    has_price = (
        draft.price_change_pct is not None
        or _observed_move(draft) is not None
        or forest_anomalous
        or draft.kind == "news_price"
    )
    return bool(has_news and has_price)


def resolve_agreement(alignment_level: str | None, *, has_both_sides: bool) -> str | None:
    """Map granular evidence alignment → agrees / disagrees / mixed (or None)."""
    if not has_both_sides or not alignment_level:
        return None
    if alignment_level in (ALIGNMENT_SUPPORTS, ALIGNMENT_LEANS):
        return AGREEMENT_AGREES
    if alignment_level in (ALIGNMENT_CONTRADICTS, ALIGNMENT_LEANS_AGAINST):
        return AGREEMENT_DISAGREES
    return AGREEMENT_MIXED


def _sentiment_is_polarized(draft: AlertDraft) -> bool:
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    split = sections.get("sentiment_split")
    if isinstance(split, dict) and split.get("polarized"):
        return True
    scores = []
    for article in draft.articles or ():
        try:
            scores.append(float(article.get("sentiment_score")))
        except (TypeError, ValueError, AttributeError):
            continue
    if not scores:
        return False
    positive = sum(1 for score in scores if score > 50.0)
    negative = sum(1 for score in scores if score < 50.0)
    return positive > 0 and negative > 0


def resolve_direction_agreement(
    draft: AlertDraft, *, forest_anomalous: bool = False
) -> str | None:
    """Compare session move direction to FinBERT climate for the card chip.

    Polarized headline sets (both above-50 and below-50) always read mixed.
    Soft / below-join lists use a milder tilt-off-50 rule so Direction still shows.
    Price-led with no near-term headlines → ``no_news`` (not a blank dash).
    """
    has_news = draft.sentiment_score is not None or bool(draft.articles)
    has_price = (
        draft.price_change_pct is not None
        or _observed_move(draft) is not None
        or forest_anomalous
        or draft.kind in ("price", "news_price")
    )
    if has_price and not has_news:
        return AGREEMENT_NO_NEWS
    if not _has_price_and_news_sides(draft, forest_anomalous=forest_anomalous):
        return None
    if _sentiment_is_polarized(draft):
        return AGREEMENT_MIXED
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    joined = sections.get("news_join_path") in ("headline", "climate")
    soft = (not joined) and bool(draft.articles)
    news_dir = _news_direction(draft.sentiment_score, soft=soft)
    price_dir = _price_direction(_observed_move(draft))
    if news_dir and price_dir:
        return AGREEMENT_AGREES if news_dir == price_dir else AGREEMENT_DISAGREES
    return AGREEMENT_MIXED


def agreement_label(key: str | None) -> str | None:
    if not key:
        return None
    return AGREEMENT_LABELS.get(str(key), str(key))


def _price_gate_case(*, percent_cleared: bool | None, forest_anomalous: bool) -> str:
    """Short bracket tag for What happened (volatile / anomalous / both / neither)."""
    shape = resolve_price_shape(
        percent_cleared=percent_cleared, forest_anomalous=forest_anomalous
    )
    if shape == PRICE_SHAPE_BOTH:
        return "(volatile + anomalous)"
    if shape == PRICE_SHAPE_VOLATILE:
        return "(volatile)"
    if shape == PRICE_SHAPE_ANOMALOUS:
        return "(anomalous)"
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


def _percent_volatile_tag(percent_cleared: bool | None) -> str:
    """Percent-floor tag only — never conflate with forest anomalous."""
    if percent_cleared is True:
        return "(volatile)"
    if percent_cleared is False:
        return "(not volatile)"
    return ""


def _price_checked_bullets(
    draft: AlertDraft, forest: Any, *, as_support_check: bool
) -> list[str]:
    """Percent line, then separate anomalous-driver bullets when forest fired."""
    move = _observed_move(draft)
    move_text = _fmt_move(move)
    threshold = _price_threshold(draft)
    rule_text = f"{threshold * 100:.1f}%"
    forest_anomalous = isinstance(forest, dict) and bool(forest.get("anomalous"))
    percent_cleared: bool | None = None
    if move is not None:
        try:
            percent_cleared = abs(float(move)) >= threshold
        except (TypeError, ValueError):
            percent_cleared = None
    volatile_tag = _percent_volatile_tag(percent_cleared)
    trigger = price_trigger_note(
        draft,
        forest,
        percent_cleared=percent_cleared,
        forest_anomalous=forest_anomalous,
    )
    anomaly_bullets = forest_evidence_bullets(forest if isinstance(forest, dict) else None)
    # Case-number triggers only when there is no plain-English anomaly list.
    show_triggers = not anomaly_bullets
    trigger_bit = f" [{trigger}]" if show_triggers else ""
    tag_bit = f" {volatile_tag}" if volatile_tag else ""

    bullets: list[str] = []
    if move is None:
        if as_support_check:
            bullets.append(
                "Session price was measured; no usable move was available beside the news."
                + trigger_bit
            )
        else:
            bullets.append(
                "Session price was measured; no usable percent move was available." + trigger_bit
            )
    elif percent_cleared:
        lead = "Observed session move" if as_support_check else "Session move"
        bullets.append(
            f"{lead} {move_text} cleared the {rule_text} percent rule{tag_bit}." + trigger_bit
        )
    else:
        lead = "Observed session move" if as_support_check else "Session move"
        bullets.append(
            f"{lead} {move_text} stayed under the {rule_text} percent rule{tag_bit}." + trigger_bit
        )

    bullets.extend(anomaly_bullets)
    return [line.strip() for line in bullets if line and str(line).strip()]


def _price_step(
    draft: AlertDraft,
    forest: Any,
    *,
    step_id: str,
    label: str,
    as_support_check: bool,
) -> dict[str, Any]:
    details = _price_checked_bullets(draft, forest, as_support_check=as_support_check)
    return {
        "id": step_id,
        "ok": True,
        "tone": "ok",
        "label": label,
        "detail": " ".join(details),
        "details": details,
    }


def _price_checked_detail(draft: AlertDraft, forest: Any, *, as_support_check: bool) -> str:
    """Joined measurement copy — prefer ``_price_checked_bullets`` for display."""
    return " ".join(_price_checked_bullets(draft, forest, as_support_check=as_support_check))
