"""S&P 500 Radar API and single-page UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .checks import rebuild_history, rebuild_start, run_check
from .screener import DEFAULT_SCREENER_LIMIT, run_screener
from .config import (
    DEFAULT_PRICE_MOVE_THRESHOLD,
    DEFAULT_SENTIMENT_THRESHOLD,
    LIVE_WS_SYMBOL_LIMIT,
    price_fraction_from_percent,
    sentiment_threshold_value,
    settings,
)
from .db import db
from .sectors import ensure_symbol_sectors
from .perplexity_catalog import known_model, model_groups
from .store import (
    add_live_ws_symbol,
    add_symbol,
    delete_alerts_below_abs_change,
    delete_all_alerts,
    get_alert_rules,
    list_alerts,
    list_live_ws_symbols,
    list_watchlist,
    live_consumer_status,
    perplexity_api_key,
    perplexity_model,
    remove_live_ws_symbol,
    remove_symbol,
    save_alert_rules,
    save_perplexity_api_key,
    save_perplexity_model,
)
from .lake_land import (
    DEFAULT_REFRESH_DAYS,
    lake_land_status,
    start_lake_auto_scheduler,
    start_lake_land,
    start_lake_refresh,
    stop_lake_auto_scheduler,
)
from .symbols import known_universe_symbol, normalize_symbol

_UI_DIR = Path(__file__).resolve().parents[1] / "ui"
_UI = _UI_DIR / "index.html"
_SYMBOL_UNIVERSE = _UI_DIR / "sp500_universe.json"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("TICKER_ALERT_SKIP_DB") == "1":
        yield
        return
    await db.connect()
    if settings.live_disarm_on_boot:
        from .store import set_live_alerts_armed

        assert db.pool is not None
        async with db.pool.acquire() as conn:
            await set_live_alerts_armed(conn, False)
    await start_lake_auto_scheduler()
    try:
        yield
    finally:
        await stop_lake_auto_scheduler()
        await db.disconnect()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


class WatchlistIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)


class RebuildIn(BaseModel):
    days: int


class ClearAlertsIn(BaseModel):
    """Wipe saved alerts. ``clear_all`` or delete rows under ``below_percent`` (e.g. 3 = 3%)."""

    clear_all: bool = False
    below_percent: float | None = None


class ScreenerIn(BaseModel):
    """Signed percent filter: 3 = up at least 3%, -3 = down at least 3%."""

    change_percent: float
    limit: int = DEFAULT_SCREENER_LIMIT


class AlertRulesIn(BaseModel):
    price_move_percent: float
    sentiment_threshold: float


class PerplexityKeyIn(BaseModel):
    perplexity_api_key: str | None = None
    clear_perplexity_api_key: bool = False
    perplexity_model: str | None = None


def _settings_payload(
    rules: dict[str, float | str], *, perplexity_key_saved: bool, perplexity_model_id: str
) -> dict[str, object]:
    return {
        "price_move_threshold": rules["price_move_threshold"],
        "volume_spike_threshold": settings.volume_spike_threshold,
        "sentiment_threshold": rules["sentiment_threshold"],
        "sentiment_scorer": "finbert",
        "news_lookback_hours": settings.news_lookback_hours,
        "fusion_window_hours": settings.fusion_window_hours,
        "display_timezone": settings.display_timezone,
        "price_move_threshold_default": DEFAULT_PRICE_MOVE_THRESHOLD,
        "sentiment_threshold_default": DEFAULT_SENTIMENT_THRESHOLD,
        "perplexity_key_saved": perplexity_key_saved,
        "perplexity_model": perplexity_model_id,
        "perplexity_models": model_groups(),
    }


async def _public_settings() -> dict[str, object]:
    async with _pool().acquire() as conn:
        rules = await get_alert_rules(conn)
        saved = bool(await perplexity_api_key(conn) or settings.perplexity_api_key.strip())
        chosen = await perplexity_model(conn)
    return _settings_payload(rules, perplexity_key_saved=saved, perplexity_model_id=chosen)


def _pool():
    if db.pool is None:
        raise HTTPException(status_code=503, detail="Database is not connected.")
    return db.pool


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
@app.get("/ui")
async def ui() -> FileResponse:
    # Avoid sticky "Loading historical prices" from a cached index.html after deploys.
    return FileResponse(
        _UI,
        headers={"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"},
    )


@app.get("/ui/sw-notifications.js")
async def ui_notification_worker() -> FileResponse:
    """Service worker so alert popups use the OS / Chrome notification center."""
    return FileResponse(
        _UI_DIR / "sw-notifications.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/ui"},
    )


@app.get("/ui/symbol_universe.json")
@app.get("/ui/sp500_universe.json")
async def symbol_universe() -> FileResponse:
    """S&P 500 tickers for watchlist autocomplete."""
    return FileResponse(_SYMBOL_UNIVERSE, media_type="application/json")


@app.get("/v1/settings")
async def public_settings() -> dict[str, object]:
    return await _public_settings()


@app.put("/v1/settings")
async def put_settings(body: AlertRulesIn) -> dict[str, object]:
    try:
        price = price_fraction_from_percent(body.price_move_percent)
        sentiment = sentiment_threshold_value(body.sentiment_threshold)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with _pool().acquire() as conn:
        await save_alert_rules(conn, price_move_threshold=price, sentiment_threshold=sentiment)
    return await _public_settings()


@app.put("/v1/settings/perplexity")
async def put_perplexity_key(body: PerplexityKeyIn) -> dict[str, object]:
    key: str | None
    if body.clear_perplexity_api_key:
        key = ""
    elif body.perplexity_api_key and body.perplexity_api_key.strip():
        key = body.perplexity_api_key.strip()
        if len(key) > 512 or any(char.isspace() for char in key):
            raise HTTPException(status_code=400, detail="Enter the Perplexity API key with no spaces.")
    elif body.perplexity_model and body.perplexity_model.strip():
        key = None
    else:
        raise HTTPException(status_code=400, detail="Enter a Perplexity API key, or clear the saved key.")
    chosen = known_model(body.perplexity_model) if body.perplexity_model else None
    async with _pool().acquire() as conn:
        if key is not None:
            await save_perplexity_api_key(conn, key)
        if chosen is not None:
            await save_perplexity_model(conn, chosen)
    return await _public_settings()


@app.post("/v1/settings/reset")
async def reset_settings() -> dict[str, object]:
    async with _pool().acquire() as conn:
        await save_alert_rules(
            conn,
            price_move_threshold=DEFAULT_PRICE_MOVE_THRESHOLD,
            sentiment_threshold=DEFAULT_SENTIMENT_THRESHOLD,
        )
    return await _public_settings()


@app.get("/v1/watchlist")
async def get_watchlist() -> dict[str, list]:
    async with _pool().acquire() as conn:
        return {"symbols": await list_watchlist(conn)}


@app.post("/v1/watchlist")
async def post_watchlist(body: WatchlistIn) -> dict:
    try:
        symbol = normalize_symbol(body.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not known_universe_symbol(symbol):
        raise HTTPException(
            status_code=400,
            detail=f"{symbol} is not an S&P 500 constituent.",
        )
    async with _pool().acquire() as conn:
        return await add_symbol(conn, symbol)


@app.delete("/v1/watchlist/{symbol}")
async def delete_watchlist(symbol: str) -> dict[str, bool]:
    try:
        normalized = normalize_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with _pool().acquire() as conn:
        removed = await remove_symbol(conn, normalized)
    return {"removed": removed}


@app.get("/v1/live/ws-symbols")
async def get_live_ws_symbols() -> dict[str, object]:
    """Symbols that stream on Alpaca WebSocket; the rest of the S&P uses REST."""
    async with _pool().acquire() as conn:
        try:
            symbols = await list_live_ws_symbols(conn)
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail="Live WebSocket list is unavailable. Apply migration 017_live_ws_symbols.",
            ) from exc
    return {"symbols": symbols, "limit": LIVE_WS_SYMBOL_LIMIT}


@app.post("/v1/live/ws-symbols")
async def post_live_ws_symbol(body: WatchlistIn) -> dict:
    try:
        symbol = normalize_symbol(body.symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not known_universe_symbol(symbol):
        raise HTTPException(
            status_code=400,
            detail=f"{symbol} is not an S&P 500 constituent.",
        )
    async with _pool().acquire() as conn:
        try:
            return await add_live_ws_symbol(conn, symbol)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/v1/live/ws-symbols/{symbol}")
async def delete_live_ws_symbol(symbol: str) -> dict[str, bool]:
    try:
        normalized = normalize_symbol(symbol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with _pool().acquire() as conn:
        removed = await remove_live_ws_symbol(conn, normalized)
    return {"removed": removed}


@app.get("/v1/alerts")
async def get_alerts(limit: int = 100) -> dict[str, list]:
    capped = min(max(limit, 1), 1000)
    async with _pool().acquire() as conn:
        alerts = await list_alerts(conn, limit=capped)
        await ensure_symbol_sectors(conn, [alert["symbol"] for alert in alerts])
        if alerts:
            rows = await conn.fetch(
                "SELECT symbol, sector FROM symbols WHERE symbol = ANY($1::text[])",
                list({alert["symbol"] for alert in alerts}),
            )
            sectors = {row["symbol"]: row["sector"] for row in rows}
            for alert in alerts:
                alert["sector"] = sectors.get(alert["symbol"]) or alert.get("sector")
        return {"alerts": alerts}


@app.get("/v1/live/status")
async def get_live_status() -> dict[str, object]:
    """Live alerts cue: ``armed`` is the user switch; ``enabled`` is a fresh consumer heartbeat."""
    async with _pool().acquire() as conn:
        return await live_consumer_status(conn)


class LiveArmedIn(BaseModel):
    armed: bool


@app.post("/v1/live/armed")
async def post_live_armed(body: LiveArmedIn) -> dict[str, object]:
    """Arm or disarm Live alerts from the Home cue (pauses live + producer when polled)."""
    from .store import set_live_alerts_armed

    async with _pool().acquire() as conn:
        await set_live_alerts_armed(conn, body.armed)
        return await live_consumer_status(conn)


@app.post("/v1/checks/run")
async def post_check() -> dict:
    return await run_check(_pool())


@app.post("/v1/screener/run")
async def post_screener(body: ScreenerIn) -> dict:
    """Experimental full-index screen: top session movers from the lake, then headlines.

    Results are ephemeral (not written to Alert History).
    """
    if body.change_percent == 0:
        raise HTTPException(
            status_code=400,
            detail="Enter a non-zero percent filter (for example 3 or -3).",
        )
    if abs(body.change_percent) > 50:
        raise HTTPException(status_code=400, detail="Percent filter must be at most 50.")
    try:
        pool = None if os.environ.get("TICKER_ALERT_SKIP_DB") == "1" else _pool()
        return await run_screener(
            pool,
            change_percent=body.change_percent,
            limit=body.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/admin/rebuild")
async def post_rebuild(body: RebuildIn) -> dict:
    try:
        rebuild_start(date(2000, 1, 1), body.days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await rebuild_history(_pool(), days=body.days)


@app.post("/v1/admin/alerts/clear")
async def post_clear_alerts(body: ClearAlertsIn) -> dict[str, object]:
    """Delete all alerts, or only those whose |price change| is under a percent floor."""
    if body.clear_all:
        async with _pool().acquire() as conn:
            deleted = await delete_all_alerts(conn)
        return {"deleted": deleted, "mode": "all"}
    if body.below_percent is None:
        raise HTTPException(
            status_code=400,
            detail="Set clear_all, or below_percent (for example 3 to drop moves under 3%).",
        )
    try:
        fraction = price_fraction_from_percent(body.below_percent)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    async with _pool().acquire() as conn:
        deleted = await delete_alerts_below_abs_change(conn, fraction)
    return {
        "deleted": deleted,
        "mode": "below_percent",
        "below_percent": body.below_percent,
    }


@app.get("/v1/admin/lake/status")
async def get_lake_status() -> dict[str, object]:
    """Progress for the Settings historical-price land into data/lake."""
    return lake_land_status()


@app.post("/v1/admin/lake/land")
async def post_lake_land() -> dict[str, object]:
    """Pull ~1 year of Yahoo daily bars for the S&P 500 into the local lake (background)."""
    try:
        return await start_lake_land(days=365)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/admin/lake/refresh")
async def post_lake_refresh() -> dict[str, object]:
    """Merge recent Yahoo dailies into the lake, then curate + retrain Isolation Forest."""
    try:
        return await start_lake_refresh(days=DEFAULT_REFRESH_DAYS)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
