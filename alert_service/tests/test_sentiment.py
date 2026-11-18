from app.sentiment import score_sentiment


def test_neutral_when_no_keywords():
    assert score_sentiment("Markets closed for holiday") == 0.0


def test_strong_negative_outranks_mild_negative():
    plunge = score_sentiment("Shares plunge after results")
    miss = score_sentiment("Shares miss after results")
    assert plunge < miss < 0


def test_negation_window_flips_polarity():
    positive = score_sentiment("Analysts upgrade the stock")
    negated = score_sentiment("Analysts do not upgrade the stock")
    assert positive > 0
    assert negated < 0
