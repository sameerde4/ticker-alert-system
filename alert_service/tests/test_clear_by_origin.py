"""Origin-scoped alert clears keep the other path's history."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.checks import rebuild_history
from app.main import ClearAlertsIn, app
from app.store import clear_live_alerts, clear_watchlist_alerts


class _FakeConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args):
        self.calls.append((sql, args))
        text = " ".join(sql.split())
        if text.startswith("UPDATE"):
            return "UPDATE 2"
        if "origin = 'watchlist'" in text or 'origin = "watchlist"' in text:
            return "DELETE 3"
        if "origin = 'live'" in text or 'origin = "live"' in text:
            return "DELETE 4"
        return "DELETE 0"


@pytest.mark.asyncio
async def test_clear_watchlist_demotes_both_then_deletes_watchlist():
    conn = _FakeConn()
    result = await clear_watchlist_alerts(conn)
    assert result == {"deleted": 3, "demoted_to_live": 2}
    assert "both" in conn.calls[0][0]
    assert "live" in conn.calls[0][0]
    assert "watchlist" in conn.calls[1][0]


@pytest.mark.asyncio
async def test_clear_live_demotes_both_then_deletes_live():
    conn = _FakeConn()
    result = await clear_live_alerts(conn)
    assert result == {"deleted": 4, "demoted_to_watchlist": 2}
    assert "both" in conn.calls[0][0]
    assert "watchlist" in conn.calls[0][0]
    assert "live" in conn.calls[1][0]


def test_clear_alerts_in_accepts_origin_scopes():
    assert ClearAlertsIn(origin="watchlist").origin == "watchlist"
    assert ClearAlertsIn(origin="live").origin == "live"
    assert ClearAlertsIn(clear_all=True).clear_all is True
    assert ClearAlertsIn(below_percent=3).below_percent == 3


def test_clear_endpoint_requires_a_mode_before_database():
    client = TestClient(app)
    response = client.post("/v1/admin/alerts/clear", json={})
    assert response.status_code in (400, 503)


@pytest.mark.asyncio
async def test_rebuild_history_clears_watchlist_not_all_alerts():
    from contextlib import asynccontextmanager

    conn = AsyncMock()

    @asynccontextmanager
    async def acquire():
        yield conn

    pool = AsyncMock()
    pool.acquire = acquire
    with (
        patch(
            "app.checks.get_alert_rules",
            new=AsyncMock(
                return_value={
                    "price_move_threshold": 0.03,
                    "sentiment_threshold": 25.0,
                }
            ),
        ),
        patch("app.checks.list_watchlist", new=AsyncMock(return_value=[])),
        patch(
            "app.checks.clear_watchlist_alerts",
            new=AsyncMock(return_value={"deleted": 1, "demoted_to_live": 0}),
        ) as clear_wl,
        patch("app.checks.ensure_symbol_sectors", new=AsyncMock()),
        patch("app.checks.load_watchlist_forest_scorer", return_value=None),
        patch("app.checks.reason_alert_drafts", new=AsyncMock(return_value=([], None, None))),
    ):
        result = await rebuild_history(pool, days=1)
    clear_wl.assert_awaited()
    assert result["cleared"]["deleted"] == 1
    assert result["alerts"] == []
    import app.checks as checks_mod

    assert not hasattr(checks_mod, "delete_all_alerts")
