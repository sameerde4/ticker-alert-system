"""PostgreSQL reads and writes for the alert service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg

from .config import DEFAULT_PRICE_MOVE_THRESHOLD, DEFAULT_SENTIMENT_THRESHOLD, settings
from .scoring import DEFAULT_SCORER, normalize_scorer
from .engine import AlertDraft

_ALERT_COLUMNS = """
    id, symbol, kind, bar_date, headline_id, price_change_pct, latest_close, prior_close,
    volume_ratio, volume_spike, sentiment_score, headline_title, summary, articles, sections,
    triggered_at, updated_at, created_at, price_move_threshold, sentiment_threshold
"""


def alert_record(row: asyncpg.Record | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for key in ("id", "headline_id"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    for key in (
        "price_change_pct",
        "latest_close",
        "prior_close",
        "volume_ratio",
        "sentiment_score",
        "price_move_threshold",
        "sentiment_threshold",
    ):
        if data.get(key) is not None:
            data[key] = float(data[key])
    for key in ("bar_date",):
        if isinstance(data.get(key), date):
            data[key] = data[key].isoformat()
    for key in ("triggered_at", "updated_at", "created_at"):
        if isinstance(data.get(key), datetime):
            data[key] = data[key].isoformat()
    for key, empty in (("articles", []), ("sections", {})):
        value = data.get(key)
        if isinstance(value, str):
            data[key] = json.loads(value)
        elif value is None:
            data[key] = empty
    return data


def _rule_record(price: float, sentiment: float, scorer: str) -> dict[str, float | str]:
    return {
        "price_move_threshold": price,
        "sentiment_threshold": sentiment,
        "sentiment_scorer": normalize_scorer(scorer),
        "price_move_threshold_default": DEFAULT_PRICE_MOVE_THRESHOLD,
        "sentiment_threshold_default": DEFAULT_SENTIMENT_THRESHOLD,
        "sentiment_scorer_default": DEFAULT_SCORER,
    }


async def get_alert_rules(conn: asyncpg.Connection) -> dict[str, float | str]:
    row = await conn.fetchrow(
        """
        SELECT price_move_threshold, sentiment_threshold, sentiment_scorer
        FROM app_settings WHERE id
        """
    )
    if row is None:
        return _rule_record(
            settings.price_move_threshold, settings.sentiment_threshold, DEFAULT_SCORER
        )
    return _rule_record(
        float(row["price_move_threshold"]),
        float(row["sentiment_threshold"]),
        str(row["sentiment_scorer"]),
    )


async def save_alert_rules(
    conn: asyncpg.Connection, *, price_move_threshold: float, sentiment_threshold: float
) -> dict[str, float]:
    await conn.execute(
        """
        INSERT INTO app_settings (id, price_move_threshold, sentiment_threshold)
        VALUES (TRUE, $1, $2)
        ON CONFLICT (id) DO UPDATE SET
          price_move_threshold = EXCLUDED.price_move_threshold,
          sentiment_threshold = EXCLUDED.sentiment_threshold,
          updated_at = NOW()
        """,
        price_move_threshold,
        sentiment_threshold,
    )
    return await get_alert_rules(conn)


async def save_sentiment_scorer(conn: asyncpg.Connection, scorer: str) -> dict[str, float | str]:
    """Store FinBERT or custom scoring. Price and sentiment thresholds stay as they are."""
    name = normalize_scorer(scorer)
    await conn.execute(
        """
        INSERT INTO app_settings (id, price_move_threshold, sentiment_threshold, sentiment_scorer)
        VALUES (TRUE, $1, $2, $3)
        ON CONFLICT (id) DO UPDATE SET
          sentiment_scorer = EXCLUDED.sentiment_scorer,
          updated_at = NOW()
        """,
        settings.price_move_threshold,
        settings.sentiment_threshold,
        name,
    )
    return await get_alert_rules(conn)


async def list_watchlist(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    rows = await conn.fetch("SELECT symbol, added_at FROM watchlist ORDER BY symbol")
    return [
        {"symbol": row["symbol"], "added_at": row["added_at"].isoformat()}
        for row in rows
    ]


async def add_symbol(conn: asyncpg.Connection, symbol: str) -> dict[str, Any]:
    already = await conn.fetchval("SELECT 1 FROM watchlist WHERE symbol = $1", symbol)
    row = await conn.fetchrow(
        """
        INSERT INTO watchlist (symbol)
        VALUES ($1)
        ON CONFLICT (symbol) DO UPDATE SET symbol = EXCLUDED.symbol
        RETURNING symbol, added_at
        """,
        symbol,
    )
    return {
        "symbol": row["symbol"],
        "added_at": row["added_at"].isoformat(),
        "already": bool(already),
    }


async def remove_symbol(conn: asyncpg.Connection, symbol: str) -> bool:
    result = await conn.execute("DELETE FROM watchlist WHERE symbol = $1", symbol)
    return result.endswith("1")


async def upsert_bars(conn: asyncpg.Connection, symbol: str, bars: list[dict[str, Any]]) -> None:
    for bar in bars:
        await conn.execute(
            """
            INSERT INTO daily_bars (symbol, dt, open, high, low, close, volume)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (symbol, dt) DO UPDATE SET
              open = EXCLUDED.open,
              high = EXCLUDED.high,
              low = EXCLUDED.low,
              close = EXCLUDED.close,
              volume = EXCLUDED.volume
            """,
            symbol,
            bar["dt"],
            bar["open"],
            bar["high"],
            bar["low"],
            bar["close"],
            int(bar["volume"]),
        )


async def load_bars(conn: asyncpg.Connection, symbol: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT dt, open, high, low, close, volume
        FROM daily_bars
        WHERE symbol = $1
        ORDER BY dt
        """,
        symbol,
    )
    return [dict(row) for row in rows]


async def load_headlines(conn: asyncpg.Connection, symbol: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, title, body, url, source, published_at, sentiment_score
        FROM headlines
        WHERE symbol = $1
        ORDER BY published_at
        """,
        symbol,
    )
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "body": row["body"],
            "url": row["url"],
            "source": row["source"],
            "published_at": row["published_at"],
            "sentiment_score": float(row["sentiment_score"]),
        }
        for row in rows
    ]


async def list_alert_days(conn: asyncpg.Connection, symbol: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT bar_date, price_move_threshold, sentiment_threshold
        FROM alerts
        WHERE symbol = $1 AND bar_date IS NOT NULL
        """,
        symbol,
    )
    return [dict(row) for row in rows]
    rows = await conn.fetch(
        """
        SELECT dt, open, high, low, close, volume
        FROM daily_bars
        WHERE symbol = $1
        ORDER BY dt
        """,
        symbol,
    )
    return [dict(row) for row in rows]


async def upsert_headlines(conn: asyncpg.Connection, symbol: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for item in items:
        row = await conn.fetchrow(
            """
            INSERT INTO headlines (symbol, title, body, url, source, published_at, sentiment_score)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (symbol, title, published_at) DO UPDATE SET
              body = EXCLUDED.body,
              url = EXCLUDED.url,
              source = EXCLUDED.source,
              sentiment_score = EXCLUDED.sentiment_score,
              fetched_at = NOW()
            RETURNING id, title, body, url, source, published_at, sentiment_score
            """,
            symbol,
            item["title"],
            item.get("body"),
            item.get("url"),
            item["source"],
            item["published_at"],
            item["sentiment_score"],
        )
        stored.append(
            {
                "id": str(row["id"]),
                "title": row["title"],
                "body": row["body"],
                "url": row["url"],
                "source": row["source"],
                "published_at": row["published_at"],
                "sentiment_score": float(row["sentiment_score"]),
            }
        )
    return stored


async def clear_symbol_day(conn: asyncpg.Connection, symbol: str, bar_date) -> None:
    """Remove this symbol's alert for one day. Earlier days stay as they were saved."""
    await conn.execute(
        """
        DELETE FROM alerts
        WHERE symbol = $1 AND bar_date = $2
        """,
        symbol,
        bar_date,
    )


async def upsert_alert(conn: asyncpg.Connection, draft: AlertDraft) -> dict[str, Any]:
    if draft.bar_date is None:
        raise ValueError("An alert needs a bar date so a symbol has one row per day.")
    conflict = "ON CONFLICT (symbol, bar_date)"
    row = await conn.fetchrow(
        f"""
        INSERT INTO alerts (
          symbol, kind, bar_date, headline_id, price_change_pct, latest_close, prior_close,
          volume_ratio, volume_spike, sentiment_score, headline_title, summary, articles, sections,
          triggered_at, price_move_threshold, sentiment_threshold
        )
        VALUES ($1, $2, $3, $4::uuid, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb, $15, $16, $17)
        {conflict}
        DO UPDATE SET
          kind = EXCLUDED.kind,
          headline_id = EXCLUDED.headline_id,
          price_change_pct = EXCLUDED.price_change_pct,
          latest_close = EXCLUDED.latest_close,
          prior_close = EXCLUDED.prior_close,
          volume_ratio = EXCLUDED.volume_ratio,
          volume_spike = EXCLUDED.volume_spike,
          sentiment_score = EXCLUDED.sentiment_score,
          headline_title = EXCLUDED.headline_title,
          summary = EXCLUDED.summary,
          articles = EXCLUDED.articles,
          sections = EXCLUDED.sections,
          triggered_at = EXCLUDED.triggered_at,
          price_move_threshold = EXCLUDED.price_move_threshold,
          sentiment_threshold = EXCLUDED.sentiment_threshold,
          updated_at = NOW()
        RETURNING {_ALERT_COLUMNS}
        """,
        draft.symbol,
        draft.kind,
        draft.bar_date,
        draft.headline_id,
        draft.price_change_pct,
        draft.latest_close,
        draft.prior_close,
        draft.volume_ratio,
        draft.volume_spike,
        draft.sentiment_score,
        draft.headline_title,
        draft.summary,
        json.dumps(list(draft.articles)),
        json.dumps(draft.sections),
        draft.triggered_at,
        draft.price_move_threshold,
        draft.sentiment_threshold,
    )
    return alert_record(row)


async def delete_all_alerts(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM alerts")


def _qualified_alert_columns(alias: str = "alerts") -> str:
    names = [part.strip() for part in _ALERT_COLUMNS.split(",") if part.strip()]
    return ", ".join(f"{alias}.{name}" for name in names)


async def list_alerts(conn: asyncpg.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        f"""
        SELECT {_qualified_alert_columns()}, symbols.sector
        FROM alerts
        LEFT JOIN symbols ON symbols.symbol = alerts.symbol
        ORDER BY alerts.triggered_at DESC
        LIMIT $1
        """,
        limit,
    )
    alerts = [alert_record(row) for row in rows]
    await _fill_missing_price_changes(conn, alerts)
    await _fill_article_publish_times(conn, alerts)
    return alerts


async def sectors_to_refresh(conn: asyncpg.Connection, symbols: list[str]) -> list[str]:
    """Symbols with no cached sector, or a failed lookup older than a day."""
    unique = list(dict.fromkeys(symbols))
    if not unique:
        return []
    rows = await conn.fetch(
        "SELECT symbol, sector, updated_at FROM symbols WHERE symbol = ANY($1::text[])",
        unique,
    )
    known = {row["symbol"]: row for row in rows}
    cutoff = datetime.now(UTC) - timedelta(days=1)
    needed: list[str] = []
    for symbol in unique:
        row = known.get(symbol)
        if row is None:
            needed.append(symbol)
            continue
        if row["sector"]:
            continue
        updated = row["updated_at"]
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        if updated < cutoff:
            needed.append(symbol)
    return needed


async def save_sector(conn: asyncpg.Connection, symbol: str, sector: str | None) -> None:
    await conn.execute(
        """
        INSERT INTO symbols (symbol, sector)
        VALUES ($1, $2)
        ON CONFLICT (symbol) DO UPDATE SET
          sector = EXCLUDED.sector,
          updated_at = NOW()
        """,
        symbol,
        sector,
    )


async def _fill_missing_price_changes(conn: asyncpg.Connection, alerts: list[dict[str, Any]]) -> None:
    """Older price rows with a blank move borrow that day's close. A news card leaves the price blank on purpose."""
    symbols = [
        alert["symbol"]
        for alert in alerts
        if alert.get("kind") != "news"
        and alert.get("price_change_pct") is None
        and alert.get("bar_date")
        and alert.get("symbol")
    ]
    if not symbols:
        return
    rows = await conn.fetch(
        """
        SELECT symbol, dt, close
        FROM daily_bars
        WHERE symbol = ANY($1::text[])
        ORDER BY symbol, dt
        """,
        list(dict.fromkeys(symbols)),
    )
    series: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        series.setdefault(row["symbol"], []).append((row["dt"], float(row["close"])))
    for alert in alerts:
        if alert.get("kind") == "news" or alert.get("price_change_pct") is not None:
            continue
        bar_date = alert.get("bar_date")
        if isinstance(bar_date, str):
            bar_date = date.fromisoformat(bar_date)
        if not isinstance(bar_date, date):
            continue
        prior: float | None = None
        close: float | None = None
        for dt, price in series.get(alert["symbol"], []):
            if dt < bar_date:
                prior = price
            elif dt == bar_date:
                close = price
                break
        if close is not None and prior is not None and prior > 0:
            alert["price_change_pct"] = (close - prior) / prior


async def _fill_article_publish_times(conn: asyncpg.Connection, alerts: list[dict[str, Any]]) -> None:
    """Older alert cards stored the headline without its publish time. Copy it from headlines."""
    wanted: dict[str, set[str]] = {}
    for alert in alerts:
        for article in alert.get("articles") or []:
            if article.get("published_at") or not article.get("title"):
                continue
            wanted.setdefault(alert["symbol"], set()).add(article["title"])
    if not wanted:
        return
    rows = await conn.fetch(
        """
        SELECT symbol, title, published_at
        FROM headlines
        WHERE symbol = ANY($1::text[])
        """,
        list(wanted),
    )
    found: dict[tuple[str, str], datetime] = {}
    for row in rows:
        titles = wanted.get(row["symbol"])
        if not titles or row["title"] not in titles or row["published_at"] is None:
            continue
        key = (row["symbol"], row["title"])
        current = found.get(key)
        if current is None or row["published_at"] > current:
            found[key] = row["published_at"]
    for alert in alerts:
        for article in alert.get("articles") or []:
            if article.get("published_at"):
                continue
            published = found.get((alert["symbol"], article.get("title")))
            if published is not None:
                article["published_at"] = published.isoformat()
