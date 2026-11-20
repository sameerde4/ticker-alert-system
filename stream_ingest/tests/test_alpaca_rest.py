from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.alpaca_rest import _session_backfill_window


def test_session_backfill_window_none_on_weekend(monkeypatch):
    saturday = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)  # Saturday

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return saturday if tz is None else saturday.astimezone(tz)

    monkeypatch.setattr("app.alpaca_rest.datetime", _FrozenDateTime)
    assert _session_backfill_window() is None


def test_session_backfill_window_during_rth(monkeypatch):
    # Friday 12:30 ET = 17:30 UTC
    midday = datetime(2026, 11, 20, 17, 30, tzinfo=UTC)

    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return midday if tz is None else midday.astimezone(tz)

    monkeypatch.setattr("app.alpaca_rest.datetime", _FrozenDateTime)
    window = _session_backfill_window()
    assert window is not None
    start, end = window
    eastern = ZoneInfo("America/New_York")
    assert start.astimezone(eastern).hour == 9
    assert start.astimezone(eastern).minute == 30
    assert end == midday - timedelta(minutes=16)
