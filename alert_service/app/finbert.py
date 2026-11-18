"""FinBERT headline sentiment.

ProsusAI/finbert returns positive, negative, and neutral probabilities.
The score runs from 0 to 100: 0 is strongly negative, 50 is neutral, and 100
is strongly positive. Confidence is the winning class probability.
"""

from __future__ import annotations

_classifier = None


def _parts(probabilities: dict[str, float]) -> dict[str, float]:
    return {label: float(probabilities.get(label) or 0.0) for label in ("positive", "negative", "neutral")}


def score_from_probabilities(probabilities: dict[str, float]) -> float:
    """0 is strongly negative, 50 is neutral, 100 is strongly positive."""
    known = _parts(probabilities)
    gap = max(-1.0, min(1.0, known["positive"] - known["negative"]))
    return 50.0 + 50.0 * gap


def confidence_from_probabilities(probabilities: dict[str, float]) -> float:
    """Winning class probability, as a percent."""
    known = _parts(probabilities)
    return max(known.values()) * 100.0


def explain_from_probabilities(probabilities: dict[str, float]) -> str:
    """Score out of 100, confidence, and the three class percentages."""
    known = _parts(probabilities)
    winner = max(known, key=known.get)
    score = score_from_probabilities(probabilities)
    confidence = confidence_from_probabilities(probabilities)
    return (
        f"FinBERT score {score:.0f}/100, confidence {confidence:.1f}%. "
        f"{winner.capitalize()}. "
        f"Positive {known['positive'] * 100:.1f}%, "
        f"negative {known['negative'] * 100:.1f}%, "
        f"neutral {known['neutral'] * 100:.1f}%."
    )


def reading_from_probabilities(probabilities: dict[str, float]) -> dict[str, float | str]:
    known = _parts(probabilities)
    return {
        "sentiment_score": score_from_probabilities(probabilities),
        "confidence": confidence_from_probabilities(probabilities),
        "positive_pct": known["positive"] * 100.0,
        "negative_pct": known["negative"] * 100.0,
        "neutral_pct": known["neutral"] * 100.0,
        "reason": explain_from_probabilities(probabilities),
    }


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


def analyze_many(texts: list[str]) -> list[dict[str, float | str]]:
    """Score each headline. One model call covers the whole batch."""
    if not texts:
        return []
    raw = _model()(texts, batch_size=16)
    if raw and isinstance(raw[0], dict):
        raw = [raw]
    return [reading_from_probabilities(_as_probabilities(row)) for row in raw]
