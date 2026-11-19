"""Screener ranks lake session movers by a signed percent filter."""

from datetime import date

from app.screener import (
    draft_as_alert,
    rank_session_movers,
    session_move_from_bars,
)
from app.engine import AlertDraft


def _write_lake_symbol(tmp_path, symbol: str, rows: list[dict]):
    import pandas as pd

    folder = tmp_path / "raw" / "prices" / "daily" / f"symbol={symbol}"
    folder.mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(folder / "part-000.parquet", index=False)


def test_session_move_from_bars_uses_prior_close():
    bars = [
        {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        {"dt": date(2026, 11, 18), "open": 100, "high": 110, "low": 100, "close": 108, "volume": 2},
    ]
    move = session_move_from_bars(bars, session_day=date(2026, 11, 18))
    assert move is not None
    assert abs(move["change_pct"] - 0.08) < 1e-9
    assert move["latest_close"] == 108.0
    assert move["prior_close"] == 100.0


def test_rank_session_movers_keeps_top_gains(monkeypatch, tmp_path):
    from app import screener

    monkeypatch.setattr(screener, "_lake_root", lambda: tmp_path)
    _write_lake_symbol(
        tmp_path,
        "AAA",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 110, "low": 100, "close": 110, "volume": 2},
        ],
    )
    _write_lake_symbol(
        tmp_path,
        "BBB",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 106, "low": 100, "close": 105, "volume": 2},
        ],
    )
    _write_lake_symbol(
        tmp_path,
        "CCC",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 102, "low": 100, "close": 101, "volume": 2},
        ],
    )
    top = rank_session_movers(
        session_day=date(2026, 11, 18),
        change_percent=3.0,
        limit=2,
        symbols=["AAA", "BBB", "CCC"],
    )
    assert [row["symbol"] for row in top] == ["AAA", "BBB"]
    assert top[0]["rank"] == 1
    assert top[0]["change_pct"] == 0.10


def test_rank_session_movers_keeps_top_declines(monkeypatch, tmp_path):
    from app import screener

    monkeypatch.setattr(screener, "_lake_root", lambda: tmp_path)
    _write_lake_symbol(
        tmp_path,
        "DOWN",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 100, "low": 90, "close": 90, "volume": 2},
        ],
    )
    _write_lake_symbol(
        tmp_path,
        "MILD",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 100, "low": 96, "close": 96, "volume": 2},
        ],
    )
    _write_lake_symbol(
        tmp_path,
        "UP",
        [
            {"dt": date(2026, 11, 17), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"dt": date(2026, 11, 18), "open": 100, "high": 110, "low": 100, "close": 110, "volume": 2},
        ],
    )
    top = rank_session_movers(
        session_day=date(2026, 11, 18),
        change_percent=-3.0,
        limit=10,
        symbols=["DOWN", "MILD", "UP"],
    )
    assert [row["symbol"] for row in top] == ["DOWN", "MILD"]
    assert top[0]["change_pct"] == -0.10


def test_rank_rejects_zero_filter():
    try:
        rank_session_movers(session_day=date(2026, 11, 18), change_percent=0.0, symbols=[])
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "non-zero" in str(exc).lower()


def test_draft_as_alert_marks_screener_origin():
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 18),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="AAPL moved.",
        origin="screener",
    )
    row = draft_as_alert(draft, rank=1)
    assert row["origin"] == "screener"
    assert row["screener_rank"] == 1
    assert row["id"].startswith("screener-AAPL-")
