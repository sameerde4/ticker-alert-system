from app.finbert import explain_from_probabilities, score_from_probabilities
from app.scoring import attach_scores, normalize_scorer, score_texts
from app.sentiment import score_sentiment


def test_finbert_score_is_positive_minus_negative():
    probabilities = {"positive": 0.7, "negative": 0.1, "neutral": 0.2}
    assert score_from_probabilities(probabilities) == 0.6
    reason = explain_from_probabilities(probabilities)
    assert reason.startswith("FinBERT calls this positive")
    assert "negative 0.10" in reason
    assert "neutral 0.20" in reason


def test_finbert_score_stays_inside_minus_one_to_one():
    assert score_from_probabilities({"positive": 2, "negative": 0}) == 1
    assert score_from_probabilities({"positive": 0, "negative": 2}) == -1
    reason = explain_from_probabilities({"positive": 0.05, "negative": 0.9, "neutral": 0.05})
    assert "calls this negative" in reason


def test_custom_scorer_stays_on_the_lexicon():
    text = "Shares plunge after results"
    scored = score_texts([text], "custom")
    assert scored[0][0] == score_sentiment(text)
    assert "plunge" in scored[0][1]


def test_finbert_scorer_does_not_call_the_lexicon(monkeypatch):
    monkeypatch.setattr(
        "app.finbert.analyze_many",
        lambda texts: [(0.8, "FinBERT calls this positive (positive 0.90, negative 0.10, neutral 0.00).")] * len(texts),
    )
    attached = attach_scores([{"title": "Shares plunge after results", "body": ""}], "finbert")
    assert attached[0]["sentiment_score"] == 0.8
    assert attached[0]["reason"].startswith("FinBERT")
    assert "plunge" not in attached[0]["reason"]


def test_scorer_name_must_be_one_of_the_two():
    assert normalize_scorer("FinBERT") == "finbert"
    try:
        normalize_scorer("both")
    except ValueError as exc:
        assert "FinBERT" in str(exc)
    else:
        raise AssertionError("expected a rejection")
