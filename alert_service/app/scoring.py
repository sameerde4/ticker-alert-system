"""Choose one headline scorer. The two scorers do not share a score."""

from __future__ import annotations

from typing import Any

SCORERS = ("finbert", "custom")
DEFAULT_SCORER = "finbert"


def normalize_scorer(value: str) -> str:
    name = str(value or "").strip().lower()
    if name not in SCORERS:
        raise ValueError("Sentiment scorer must be FinBERT or custom scoring.")
    return name


def score_texts(texts: list[str], scorer: str) -> list[tuple[float, str]]:
    """Return (score, reason) for the lexicon. FinBERT uses attach_scores."""
    name = normalize_scorer(scorer)
    if name == "finbert":
        from .finbert import analyze_many

        return [(float(row["sentiment_score"]), str(row["reason"])) for row in analyze_many(texts)]
    from .sentiment import explain_matches, score_sentiment

    return [(score_sentiment(text), explain_matches(text)) for text in texts]


def attach_scores(items: list[dict[str, Any]], scorer: str) -> list[dict[str, Any]]:
    """Copy headline rows and set the selected scorer's fields."""
    texts = [f"{item.get('title') or ''} {item.get('body') or ''}".strip() for item in items]
    name = normalize_scorer(scorer)
    attached: list[dict[str, Any]] = []
    if name == "finbert":
        from .finbert import analyze_many

        for item, reading in zip(items, analyze_many(texts), strict=True):
            copy = dict(item)
            copy.update(reading)
            attached.append(copy)
        return attached
    for item, (score, reason) in zip(items, score_texts(texts, "custom"), strict=True):
        copy = dict(item)
        copy["sentiment_score"] = score
        copy["reason"] = reason
        attached.append(copy)
    return attached
