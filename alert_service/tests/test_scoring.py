import pytest

from app.finbert import confidence_from_probabilities, explain_from_probabilities, score_from_probabilities
from app.scoring import attach_scores, normalize_scorer, score_texts
from app.sentiment import score_sentiment


def test_finbert_score_is_out_of_one_hundred():
    probabilities = {"positive": 0.93, "negative": 0.046, "neutral": 0.024}
    assert score_from_probabilities(probabilities) == pytest.approx(94.2)
    assert confidence_from_probabilities(probabilities) == pytest.approx(93.0)
    reason = explain_from_probabilities(probabilities)
    assert "94/100" in reason
    assert "confidence 93.0%" in reason
    assert "Positive 93.0%" in reason
    assert "negative 4.6%" in reason
    assert "neutral 2.4%" in reason


def test_finbert_score_stays_inside_zero_to_one_hundred():
    assert score_from_probabilities({"positive": 2, "negative": 0}) == 100
    assert score_from_probabilities({"positive": 0, "negative": 2}) == 0
    assert "Negative" in explain_from_probabilities(
        {"positive": 0.05, "negative": 0.9, "neutral": 0.05}
    )


def test_custom_scorer_stays_on_the_lexicon():
    text = "Shares plunge after results"
    scored = score_texts([text], "custom")
    assert scored[0][0] == score_sentiment(text)
    assert "plunge" in scored[0][1]


def test_finbert_scorer_keeps_confidence_and_the_breakdown(monkeypatch):
    monkeypatch.setattr(
        "app.finbert.analyze_many",
        lambda texts: [
            {
                "sentiment_score": 94.2,
                "confidence": 93.0,
                "positive_pct": 93.0,
                "negative_pct": 4.6,
                "neutral_pct": 2.4,
                "reason": "FinBERT score 94/100, confidence 93.0%. Positive.",
            }
        ] * len(texts),
    )
    attached = attach_scores([{"title": "Shares plunge after results", "body": ""}], "finbert")
    assert attached[0]["sentiment_score"] == pytest.approx(94.2)
    assert attached[0]["confidence"] == pytest.approx(93.0)
    assert attached[0]["positive_pct"] == pytest.approx(93.0)
    assert "plunge" not in attached[0]["reason"]


def test_scorer_name_must_be_one_of_the_two():
    assert normalize_scorer("FinBERT") == "finbert"
    try:
        normalize_scorer("both")
    except ValueError as exc:
        assert "FinBERT" in str(exc)
    else:
        raise AssertionError("expected a rejection")
