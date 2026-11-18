import pytest

from datetime import date

from app.checks import rebuild_start
from app.config import DEFAULT_SENTIMENT_THRESHOLD, price_fraction_from_percent, sentiment_threshold_value


def test_rebuild_window_includes_today():
    today = date(2026, 11, 17)
    assert rebuild_start(today, 1) == today
    assert rebuild_start(today, 5) == date(2026, 11, 13)


def test_rebuild_rejects_a_window_outside_one_to_forty_days():
    today = date(2026, 11, 17)
    with pytest.raises(ValueError):
        rebuild_start(today, 0)
    with pytest.raises(ValueError):
        rebuild_start(today, 41)
    with pytest.raises(ValueError):
        rebuild_start(today, True)


def test_price_percent_becomes_a_fraction():
    assert price_fraction_from_percent(3) == pytest.approx(0.03)


def test_price_percent_rejects_zero_and_over_one_hundred():
    with pytest.raises(ValueError):
        price_fraction_from_percent(0)
    with pytest.raises(ValueError):
        price_fraction_from_percent(101)


def test_sentiment_threshold_is_points_from_neutral():
    assert sentiment_threshold_value(25) == pytest.approx(25)
    assert DEFAULT_SENTIMENT_THRESHOLD == pytest.approx(25)
    with pytest.raises(ValueError):
        sentiment_threshold_value(51)
