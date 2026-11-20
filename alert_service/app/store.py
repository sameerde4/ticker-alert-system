"""PostgreSQL reads and writes for the alert service."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg

from .config import DEFAULT_PRICE_MOVE_THRESHOLD, DEFAULT_SENTIMENT_THRESHOLD, settings
from .perplexity_catalog import known_model
from .scoring import DEFAULT_SCORER, normalize_scorer
from .engine import AlertDraft

_ALERT_COLUMNS = """
    id, symbol, kind, bar_date, headline_id, price_change_pct, latest_close, prior_close,
    volume_ratio, volume_spike, sentiment_score, headline_title, summary, articles, sections,
    triggered_at, updated_at, created_at, price_move_threshold, sentiment_threshold, origin
"""

_ORIGIN_VALUES = frozenset({"live", "watchlist", "both"})


def normalize_alert_origin(value: str | None) -> str:
    origin = str(value or "watchlist").strip().lower()
    return origin if origin in _ORIGIN_VALUES else "watchlist"


def merge_alert_origin(existing: str | None, incoming: str | None) -> str:
    left = normalize_alert_origin(existing)
    right = normalize_alert_origin(incoming)
    if left == right:
        return left
    if left == "both" or right == "both":
        return "both"
    return "both"


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
    data["origin"] = normalize_alert_origin(data.get("origin"))
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


async def perplexity_api_key(conn: asyncpg.Connection) -> str:
    """The saved key, or an empty string when Settings has none."""
    row = await conn.fetchrow("SELECT perplexity_api_key FROM app_settings WHERE id")
    if row is None:
        return ""
    return str(row["perplexity_api_key"] or "").strip()


async def perplexity_model(conn: asyncpg.Connection) -> str:
    """The saved model, rewritten to an id the Perplexity agent accepts."""
    row = await conn.fetchrow("SELECT perplexity_model FROM app_settings WHERE id")
    raw = ""
    if row is not None:
        try:
            raw = row["perplexity_model"]
        except (KeyError, IndexError):
            raw = ""
    return known_model(str(raw or "") or settings.perplexity_model)


async def save_perplexity_api_key(conn: asyncpg.Connection, api_key: str) -> bool:
    """Store a key. Returns whether a key is now saved. An empty string clears it."""
    cleaned = api_key.strip()
    await conn.execute(
        """
        INSERT INTO app_settings (id, price_move_threshold, sentiment_threshold, perplexity_api_key)
        VALUES (TRUE, $1, $2, $3)
        ON CONFLICT (id) DO UPDATE SET
          perplexity_api_key = EXCLUDED.perplexity_api_key,
          updated_at = NOW()
        """,
        settings.price_move_threshold,
        settings.sentiment_threshold,
        cleaned,
    )
    return bool(cleaned)


async def save_perplexity_model(conn: asyncpg.Connection, model_id: str) -> str:
    """Store the dropdown choice. Returns the id that will be sent to Perplexity."""
    chosen = known_model(model_id)
    await conn.execute(
        """
        INSERT INTO app_settings (
          id, price_move_threshold, sentiment_threshold, perplexity_model
        )
        VALUES (TRUE, $1, $2, $3)
        ON CONFLICT (id) DO UPDATE SET
          perplexity_model = EXCLUDED.perplexity_model,
          updated_at = NOW()
        """,
        settings.price_move_threshold,
        settings.sentiment_threshold,
        chosen,
    )
    return chosen


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


async def list_live_ws_symbols(conn: asyncpg.Connection) -> list[dict[str, Any]]:
    """Symbols that take Alpaca WebSocket slots (Settings → Live WebSocket)."""
    rows = await conn.fetch(
        "SELECT symbol, added_at FROM live_ws_symbols ORDER BY symbol"
    )
    return [
        {"symbol": row["symbol"], "added_at": row["added_at"].isoformat()}
        for row in rows
    ]


async def add_live_ws_symbol(
    conn: asyncpg.Connection, symbol: str, *, limit: int | None = None
) -> dict[str, Any]:
    """Add a WebSocket priority symbol. Caps at Alpaca Basic's subscription limit."""
    from .config import LIVE_WS_SYMBOL_LIMIT

    cap = LIVE_WS_SYMBOL_LIMIT if limit is None else max(0, int(limit))
    already = await conn.fetchval("SELECT 1 FROM live_ws_symbols WHERE symbol = $1", symbol)
    if already:
        row = await conn.fetchrow(
            "SELECT symbol, added_at FROM live_ws_symbols WHERE symbol = $1", symbol
        )
        return {
            "symbol": row["symbol"],
            "added_at": row["added_at"].isoformat(),
            "already": True,
        }
    count = int(await conn.fetchval("SELECT COUNT(*) FROM live_ws_symbols") or 0)
    if count >= cap:
        raise ValueError(
            f"WebSocket list is full ({cap} symbols). Remove one before adding another."
        )
    row = await conn.fetchrow(
        """
        INSERT INTO live_ws_symbols (symbol)
        VALUES ($1)
        RETURNING symbol, added_at
        """,
        symbol,
    )
    return {
        "symbol": row["symbol"],
        "added_at": row["added_at"].isoformat(),
        "already": False,
    }


async def remove_live_ws_symbol(conn: asyncpg.Connection, symbol: str) -> bool:
    result = await conn.execute("DELETE FROM live_ws_symbols WHERE symbol = $1", symbol)
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


async def touch_live_consumer_heartbeat(conn: asyncpg.Connection) -> datetime:
    """Mark that ``python -m app.live`` is still running."""
    row = await conn.fetchrow(
        """
        INSERT INTO app_settings (
          id, price_move_threshold, sentiment_threshold, live_consumer_heartbeat_at
        )
        VALUES (TRUE, $1, $2, NOW())
        ON CONFLICT (id) DO UPDATE SET
          live_consumer_heartbeat_at = NOW()
        RETURNING live_consumer_heartbeat_at
        """,
        settings.price_move_threshold,
        settings.sentiment_threshold,
    )
    return row["live_consumer_heartbeat_at"]


async def clear_live_consumer_heartbeat(conn: asyncpg.Connection) -> None:
    """Clear the live cue when the consumer process exits cleanly."""
    await conn.execute(
        """
        UPDATE app_settings
        SET live_consumer_heartbeat_at = NULL
        WHERE id
        """
    )


def heartbeat_is_fresh(
    heartbeat: datetime | None,
    *,
    now: datetime | None = None,
    stale_after_seconds: int | None = None,
) -> bool:
    """True when the live-consumer heartbeat is recent enough for the UI cue."""
    if heartbeat is None:
        return False
    stamp = heartbeat if heartbeat.tzinfo else heartbeat.replace(tzinfo=UTC)
    moment = now or datetime.now(UTC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    limit = settings.live_heartbeat_stale_seconds if stale_after_seconds is None else stale_after_seconds
    age = (moment.astimezone(UTC) - stamp.astimezone(UTC)).total_seconds()
    return age <= max(5, int(limit))


async def get_live_alerts_armed(conn: asyncpg.Connection) -> bool:
    """Whether the user wants Live alerts processing on (Home arm switch)."""
    row = await conn.fetchrow("SELECT live_alerts_armed FROM app_settings WHERE id")
    if row is None or row["live_alerts_armed"] is None:
        return True
    return bool(row["live_alerts_armed"])


async def set_live_alerts_armed(conn: asyncpg.Connection, armed: bool) -> bool:
    """Persist the Live alerts arm switch. Disarming clears the heartbeat cue."""
    await conn.execute(
        """
        INSERT INTO app_settings (
          id, price_move_threshold, sentiment_threshold, live_alerts_armed
        )
        VALUES (TRUE, $1, $2, $3)
        ON CONFLICT (id) DO UPDATE SET live_alerts_armed = EXCLUDED.live_alerts_armed
        """,
        settings.price_move_threshold,
        settings.sentiment_threshold,
        bool(armed),
    )
    if not armed:
        await clear_live_consumer_heartbeat(conn)
    return bool(armed)


async def live_consumer_status(
    conn: asyncpg.Connection, *, stale_after_seconds: int | None = None, now: datetime | None = None
) -> dict[str, Any]:
    """Live cue: armed (user switch) and enabled (fresh consumer heartbeat)."""
    from .config import LIVE_WS_SYMBOL_LIMIT

    row = await conn.fetchrow(
        "SELECT live_consumer_heartbeat_at, live_alerts_armed FROM app_settings WHERE id"
    )
    heartbeat = None if row is None else row["live_consumer_heartbeat_at"]
    armed = True if row is None or row["live_alerts_armed"] is None else bool(row["live_alerts_armed"])
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    enabled = armed and heartbeat_is_fresh(
        heartbeat, now=now, stale_after_seconds=stale_after_seconds
    )
    try:
        ws_rows = await list_live_ws_symbols(conn)
        ws_symbols = [row["symbol"] for row in ws_rows]
    except Exception:
        # Migration 017 not applied yet — producer falls back to env priority.
        ws_symbols = []
    return {
        "armed": armed,
        "enabled": enabled,
        "heartbeat_at": heartbeat.isoformat() if heartbeat is not None else None,
        "ws_symbols": ws_symbols,
        "ws_limit": LIVE_WS_SYMBOL_LIMIT,
    }


async def fetch_recent_daily_bars(
    conn: asyncpg.Connection, symbol: str, *, limit: int = 40
) -> list[dict[str, Any]]:
    """Newest-first daily bars for live forest history (caller sorts as needed)."""
    rows = await conn.fetch(
        """
        SELECT symbol, dt, open, high, low, close, volume
        FROM daily_bars
        WHERE symbol = $1
        ORDER BY dt DESC
        LIMIT $2
        """,
        symbol.upper(),
        limit,
    )
    return [
        {
            "symbol": row["symbol"],
            "dt": row["dt"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for row in rows
    ]


async def insert_live_feature_row(
    conn: asyncpg.Connection,
    *,
    symbol: str,
    session_day: date,
    observed_at: datetime,
    gap_return: float,
    session_return: float,
    close_return: float,
    volume_zscore: float,
    forest_score: float,
    score_cutoff: float,
    anomalous: bool,
    model_id: str,
    open_px: float | None,
    last_px: float | None,
    prior_close: float | None,
    session_volume: float | None,
) -> None:
    """Append one live feature + forest score row (Timescale stand-in)."""
    await conn.execute(
        """
        INSERT INTO live_feature_rows (
          symbol, session_day, observed_at,
          gap_return, session_return, close_return, volume_zscore,
          forest_score, score_cutoff, anomalous, model_id,
          open_px, last_px, prior_close, session_volume
        )
        VALUES (
          $1, $2, $3,
          $4, $5, $6, $7,
          $8, $9, $10, $11,
          $12, $13, $14, $15
        )
        """,
        symbol.upper(),
        session_day,
        observed_at,
        gap_return,
        session_return,
        close_return,
        volume_zscore,
        forest_score,
        score_cutoff,
        anomalous,
        model_id,
        open_px,
        last_px,
        prior_close,
        session_volume,
    )


async def get_alert_for_day(
    conn: asyncpg.Connection, symbol: str, bar_date: date
) -> dict[str, Any] | None:
    """The one alert row for a symbol on a calendar day, if any."""
    row = await conn.fetchrow(
        f"""
        SELECT {_ALERT_COLUMNS}
        FROM alerts
        WHERE symbol = $1 AND bar_date = $2
        """,
        symbol,
        bar_date,
    )
    if row is None:
        return None
    return alert_record(row)


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


def _sections_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(loaded) if isinstance(loaded, dict) else {}
    return {}


def _iso_stamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat()
    text = str(value).strip()
    return text or None


_KIND_HISTORY_LABELS = {
    "price": "price-led",
    "news": "news-led",
    "news_price": "price + news",
}


def _kind_history_label(kind: Any) -> str:
    key = str(kind or "").strip()
    return _KIND_HISTORY_LABELS.get(key, key or "alert")


def _join_history_phrase(join: Any) -> str | None:
    if join == "headline":
        return "news joined via a strong headline"
    if join == "climate":
        return "news joined via the climate average"
    return None


def _history_note(draft: AlertDraft, previous: dict[str, Any] | None) -> str:
    """Human timeline note using the same alert-type labels as the UI chips."""
    kind_label = _kind_history_label(draft.kind)
    bits: list[str] = []
    if previous is None:
        return f"Alert created as {kind_label}"
    prev_kind = previous.get("kind")
    if prev_kind and prev_kind != draft.kind:
        bits.append(
            f"Alert type changed to {kind_label} (was {_kind_history_label(prev_kind)})"
        )
    else:
        bits.append(f"Refreshed {kind_label} alert")
    prev_score = previous.get("sentiment_score")
    if draft.sentiment_score is not None and prev_score != draft.sentiment_score:
        try:
            if prev_score is not None:
                bits.append(
                    "climate sentiment "
                    f"{float(prev_score):.0f}→{float(draft.sentiment_score):.0f}/100"
                )
            else:
                bits.append(f"climate sentiment {float(draft.sentiment_score):.0f}/100")
        except (TypeError, ValueError):
            bits.append("climate sentiment changed")
    prev_n = len(previous.get("articles") or [])
    next_n = len(draft.articles or ())
    if next_n != prev_n:
        bits.append(f"headlines listed {prev_n}→{next_n}")
    sections = draft.sections if isinstance(draft.sections, dict) else {}
    join_bit = _join_history_phrase(sections.get("news_join_path"))
    if join_bit:
        bits.append(join_bit)
    return "; ".join(bits)


def merge_alert_update_history(
    draft: AlertDraft,
    *,
    existing: dict[str, Any] | None,
    written_at: datetime | None = None,
) -> dict[str, Any]:
    """Keep a capped timeline of opens/updates inside ``sections.update_history``."""
    sections = _sections_dict(draft.sections)
    stamp = _iso_stamp(written_at or datetime.now(UTC)) or datetime.now(UTC).isoformat()
    history: list[dict[str, Any]] = []
    if existing:
        prev_sections = _sections_dict(existing.get("sections"))
        raw = prev_sections.get("update_history")
        if isinstance(raw, list):
            history = [dict(item) for item in raw if isinstance(item, dict)]
        if not history:
            opened_at = (
                _iso_stamp(existing.get("created_at"))
                or _iso_stamp(existing.get("triggered_at"))
                or stamp
            )
            seed_kind = existing.get("kind") or draft.kind
            history.append(
                {
                    "at": opened_at,
                    "event": "opened",
                    "kind": seed_kind,
                    "note": f"Alert created as {_kind_history_label(seed_kind)}",
                }
            )
        history.append(
            {
                "at": stamp,
                "event": "updated",
                "kind": draft.kind,
                "note": _history_note(draft, existing),
            }
        )
        if prev_sections.get("first_triggered_at"):
            sections["first_triggered_at"] = prev_sections["first_triggered_at"]
        else:
            sections["first_triggered_at"] = (
                _iso_stamp(existing.get("triggered_at"))
                or _iso_stamp(draft.triggered_at)
                or stamp
            )
    else:
        history.append(
            {
                "at": stamp,
                "event": "opened",
                "kind": draft.kind,
                "note": _history_note(draft, None),
            }
        )
        sections["first_triggered_at"] = _iso_stamp(draft.triggered_at) or stamp
    # Cap so sections stay small across a busy session.
    sections["update_history"] = history[-24:]
    return sections


async def upsert_alert(conn: asyncpg.Connection, draft: AlertDraft) -> dict[str, Any]:
    if draft.bar_date is None:
        raise ValueError("An alert needs a bar date so a symbol has one row per day.")
    origin = normalize_alert_origin(getattr(draft, "origin", None))
    existing_row = await conn.fetchrow(
        f"""
        SELECT {_ALERT_COLUMNS}
        FROM alerts
        WHERE symbol = $1 AND bar_date = $2
        """,
        draft.symbol,
        draft.bar_date,
    )
    existing = alert_record(existing_row) if existing_row else None
    written_at = datetime.now(UTC)
    sections = merge_alert_update_history(draft, existing=existing, written_at=written_at)
    conflict = "ON CONFLICT (symbol, bar_date)"
    row = await conn.fetchrow(
        f"""
        INSERT INTO alerts (
          symbol, kind, bar_date, headline_id, price_change_pct, latest_close, prior_close,
          volume_ratio, volume_spike, sentiment_score, headline_title, summary, articles, sections,
          triggered_at, price_move_threshold, sentiment_threshold, origin
        )
        VALUES (
          $1, $2, $3, $4::uuid, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14::jsonb,
          $15, $16, $17, $18
        )
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
          triggered_at = COALESCE(alerts.triggered_at, EXCLUDED.triggered_at),
          price_move_threshold = EXCLUDED.price_move_threshold,
          sentiment_threshold = EXCLUDED.sentiment_threshold,
          origin = CASE
            WHEN alerts.origin = EXCLUDED.origin THEN alerts.origin
            WHEN alerts.origin = 'both' OR EXCLUDED.origin = 'both' THEN 'both'
            ELSE 'both'
          END,
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
        json.dumps(sections),
        draft.triggered_at,
        draft.price_move_threshold,
        draft.sentiment_threshold,
        origin,
    )
    return alert_record(row)


async def delete_all_alerts(conn: asyncpg.Connection) -> int:
    """Delete every alert row. Returns how many were removed."""
    result = await conn.execute("DELETE FROM alerts")
    # asyncpg: "DELETE N"
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


def _delete_count(result: Any) -> int:
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


async def clear_watchlist_alerts(conn: asyncpg.Connection) -> dict[str, int]:
    """Remove Watchlist-only rows; demote ``both`` → live so Live history stays."""
    demoted = await conn.execute(
        """
        UPDATE alerts
        SET origin = 'live', updated_at = NOW()
        WHERE origin = 'both'
        """
    )
    deleted = await conn.execute("DELETE FROM alerts WHERE origin = 'watchlist'")
    return {"deleted": _delete_count(deleted), "demoted_to_live": _delete_count(demoted)}


async def clear_live_alerts(conn: asyncpg.Connection) -> dict[str, int]:
    """Remove Live-only rows; demote ``both`` → watchlist so Watchlist history stays."""
    demoted = await conn.execute(
        """
        UPDATE alerts
        SET origin = 'watchlist', updated_at = NOW()
        WHERE origin = 'both'
        """
    )
    deleted = await conn.execute("DELETE FROM alerts WHERE origin = 'live'")
    return {"deleted": _delete_count(deleted), "demoted_to_watchlist": _delete_count(demoted)}


async def delete_alerts_below_abs_change(conn: asyncpg.Connection, fraction: float) -> int:
    """Delete alerts whose |price_change_pct| is under ``fraction`` (e.g. 0.03 = 3%).

    Rows with a null price change are left alone (news-only cards).
    """
    if fraction != fraction or fraction < 0:
        raise ValueError("Price clear threshold must be zero or greater.")
    result = await conn.execute(
        """
        DELETE FROM alerts
        WHERE price_change_pct IS NOT NULL
          AND ABS(price_change_pct) < $1
        """,
        float(fraction),
    )
    try:
        return int(str(result).rsplit(" ", 1)[-1])
    except (TypeError, ValueError):
        return 0


def _qualified_alert_columns(alias: str = "alerts") -> str:
    names = [part.strip() for part in _ALERT_COLUMNS.split(",") if part.strip()]
    return ", ".join(f"{alias}.{name}" for name in names)


async def list_price_alerts_missing_climate(
    conn: asyncpg.Connection, *, limit: int = 500
) -> list[dict[str, Any]]:
    """Price-led rows needing a FinBERT climate refresh.

    Includes empty climate (null score / no articles) and older rows that have
    headlines but were saved before sentiment_split / agreement stamping.
    """
    rows = await conn.fetch(
        f"""
        SELECT {_ALERT_COLUMNS}
        FROM alerts
        WHERE kind = 'price'
          AND (
            sentiment_score IS NULL
            OR articles IS NULL
            OR articles = '[]'::jsonb
            OR COALESCE(sections->>'sentiment_split', '') = ''
            OR (
              articles IS NOT NULL
              AND articles <> '[]'::jsonb
              AND COALESCE(sections->>'agreement', '') = ''
            )
          )
        ORDER BY triggered_at DESC NULLS LAST, updated_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [alert_record(row) for row in rows]


async def list_alerts(conn: asyncpg.Connection, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        f"""
        SELECT {_qualified_alert_columns()}, symbols.sector
        FROM alerts
        LEFT JOIN symbols ON symbols.symbol = alerts.symbol
        ORDER BY alerts.updated_at DESC NULLS LAST, alerts.triggered_at DESC
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
