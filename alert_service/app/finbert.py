"""FinBERT headline sentiment.

ProsusAI/finbert returns positive, negative, and neutral probabilities.
The score is positive minus negative, in [-1, 1]. This module does not
read the keyword lexicon.
"""

from __future__ import annotations

_classifier = None


def score_from_probabilities(probabilities: dict[str, float]) -> float:
    """Map class probabilities to the same [-1, 1] range the alert rule uses."""
    positive = float(probabilities.get("positive") or 0.0)
    negative = float(probabilities.get("negative") or 0.0)
    score = positive - negative
    return max(-1.0, min(1.0, score))


def explain_from_probabilities(probabilities: dict[str, float]) -> str:
    """Name the winning FinBERT class and the three probabilities."""
    labels = ("positive", "negative", "neutral")
    known = {label: float(probabilities.get(label) or 0.0) for label in labels}
    winner = max(known, key=known.get)
    return (
        f"FinBERT calls this {winner} "
        f"(positive {known['positive']:.2f}, negative {known['negative']:.2f}, "
        f"neutral {known['neutral']:.2f})."
    )


def _model():
    global _classifier
    if _classifier is None:
        try:
            from transformers import pipeline
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("FinBERT requires the transformers and torch packages.") from exc
        _classifier = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
            top_k=None,
            truncation=True,
            max_length=512,
        )
    return _classifier


def _as_probabilities(row: list[dict] | dict) -> dict[str, float]:
    entries = row if isinstance(row, list) else [row]
    return {str(entry["label"]).lower(): float(entry["score"]) for entry in entries}


def analyze_many(texts: list[str]) -> list[tuple[float, str]]:
    """Score each headline. One model call covers the whole batch."""
    if not texts:
        return []
    raw = _model()(texts, batch_size=16)
    if raw and isinstance(raw[0], dict):
        raw = [raw]
    scored: list[tuple[float, str]] = []
    for row in raw:
        probabilities = _as_probabilities(row)
        scored.append(
            (score_from_probabilities(probabilities), explain_from_probabilities(probabilities))
        )
    return scored
