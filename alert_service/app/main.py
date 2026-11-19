"""Ticker Alert System API and single-page UI."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .checks import rebuild_history, rebuild_start, run_check
from .config import (
    DEFAULT_PRICE_MOVE_THRESHOLD,
    DEFAULT_SENTIMENT_THRESHOLD,
    price_fraction_from_percent,
    sentiment_threshold_value,
    settings,
)
from .db import db
from .sectors import ensure_symbol_sectors
from .perplexity_catalog import known_model, model_groups
from .store import (
    add_symbol,
    get_alert_rules,
    list_alerts,
    list_watchlist,
    live_consumer_status,
    perplexity_api_key,
    perplexity_model,
    remove_symbol,
    save_alert_rules,
    save_perplexity_api_key,
    save_perplexity_model,
)
from .prices import yahoo_lists_symbol
from .symbols import known_universe_symbol, normalize_symbol

_UI_DIR = Path(__file__).resolve().parents[1] / "ui"
_UI = _UI_DIR / "index.html"
_SYMBOL_UNIVERSE = _UI_DIR / "symbol_universe.json"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if os.environ.get("TICKER_ALERT_SKIP_DB") == "1":
        yield
        return
    await db.connect()
    try:
        yield
    finally:
        await db.disconnect()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


class WatchlistIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)


class RebuildIn(BaseModel):
    days: int


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
    return FileResponse(_UI)


@app.get("/ui/symbol_universe.json")
async def symbol_universe() -> FileResponse:
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
    if not known_universe_symbol(symbol) and not yahoo_lists_symbol(symbol):
        raise HTTPException(status_code=400, detail=f"{symbol} is not a ticker Yahoo recognizes.")
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
    """Whether ``python -m app.live`` is heartbeating (UI cue for live alerts)."""
    async with _pool().acquire() as conn:
        return await live_consumer_status(conn)


@app.post("/v1/checks/run")
async def post_check() -> dict:
    return await run_check(_pool())


@app.post("/v1/admin/rebuild")
async def post_rebuild(body: RebuildIn) -> dict:
    try:
        rebuild_start(date(2000, 1, 1), body.days)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return await rebuild_history(_pool(), days=body.days)
