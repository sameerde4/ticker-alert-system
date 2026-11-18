"""Daily bar fetch from Yahoo Finance via yfinance."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import Any


def fetch_daily_bars(symbol: str, *, lookback_days: int, end_date: date | None = None) -> list[dict[str, Any]]:
    """Return normalized daily bars, oldest first. Empty when Yahoo has nothing usable."""
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - environment without the dependency
        raise RuntimeError("yfinance is not installed. Install requirements first.") from exc

    end = end_date or date.today()
    start = end - timedelta(days=lookback_days)
    ticker = yf.Ticker(symbol)
    try:
        hist = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
    except Exception:
        return []
    if hist is None or getattr(hist, "empty", True):
        return []

    rows: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        try:
            dt = idx.date()
        except Exception:
            continue
        if dt < start or dt > end:
            continue
        close = _positive(row.get("Close"))
        if close is None:
            continue
        rows.append(
            {
                "dt": dt,
                "open": _positive(row.get("Open")) or close,
                "high": _positive(row.get("High")) or close,
                "low": _positive(row.get("Low")) or close,
                "close": close,
                "volume": int(_positive(row.get("Volume")) or 0),
            }
        )
    rows.sort(key=lambda item: item["dt"])
    return rows


_FUND_QUOTES = {"ETF", "MUTUALFUND"}


def _label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def sector_label(info: dict[str, Any] | None, symbol: str) -> str | None:
    """Sector for a stock, the category a fund targets, or Crypto for a coin."""
    from .symbols import trades_all_day

    profile = info or {}
    quote = str(profile.get("quoteType") or "").strip().upper()
    if quote == "CRYPTOCURRENCY":
        return "Crypto"
    if quote in _FUND_QUOTES:
        category = _label(profile.get("category"))
        if category and category.casefold() == "digital assets":
            return "Crypto"
        return category
    sector = _label(profile.get("sector"))
    if sector:
        return sector
    if trades_all_day(symbol):
        return "Crypto"
    return None


def fetch_sector(symbol: str) -> str | None:
    """Cached label for the history table: stock sector, fund category, or Crypto."""
    from .symbols import trades_all_day

    try:
        import yfinance as yf
    except Exception:  # pragma: no cover
        return "Crypto" if trades_all_day(symbol) else None
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
    except Exception:
        return "Crypto" if trades_all_day(symbol) else None
    label = sector_label(info, symbol)
    if label:
        return label
    quote = str(info.get("quoteType") or "").strip().upper()
    if quote in _FUND_QUOTES:
        category = _fund_category(ticker)
        if category and category.casefold() == "digital assets":
            return "Crypto"
        if category:
            return category
    if trades_all_day(symbol):
        return "Crypto"
    return None


def _fund_category(ticker: Any) -> str | None:
    try:
        overview = ticker.funds_data.fund_overview or {}
    except Exception:
        return None
    return _label(overview.get("categoryName"))


def yahoo_lists_symbol(symbol: str) -> bool:
    """True when Yahoo has a last price for this ticker."""
    try:
        import yfinance as yf
    except Exception:  # pragma: no cover
        return False
    try:
        price = yf.Ticker(symbol).fast_info["last_price"]
        number = float(price)
    except Exception:
        return False
    return number == number and number > 0


def price_versus_24h(points: list[tuple[datetime, float]], now: datetime) -> tuple[float, float] | None:
    """Latest price at or before ``now``, and the price at or before 24 hours earlier."""
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    moment = moment.astimezone(UTC)
    cutoff = moment - timedelta(hours=24)
    usable = []
    for stamp, price in points:
        when = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
        when = when.astimezone(UTC)
        if when <= moment and price > 0:
            usable.append((when, price))
    if not usable:
        return None
    latest_at, latest = max(usable, key=lambda item: item[0])
    if moment - latest_at > timedelta(hours=3):
        return None
    earlier = [item for item in usable if item[0] <= cutoff]
    if not earlier:
        return None
    prior_at, prior = max(earlier, key=lambda item: item[0])
    if cutoff - prior_at > timedelta(hours=6):
        return None
    return latest, prior


def fetch_last_24h(symbol: str, *, now: datetime) -> dict[str, float] | None:
    """Hourly Yahoo prices for a market that does not stop at 4:00 PM."""
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("yfinance is not installed. Install requirements first.") from exc

    try:
        hist = yf.Ticker(symbol).history(period="5d", interval="1h", auto_adjust=False)
    except Exception:
        return None
    if hist is None or getattr(hist, "empty", True):
        return None
    points: list[tuple[datetime, float]] = []
    for idx, row in hist.iterrows():
        try:
            stamp = idx.to_pydatetime()
        except Exception:
            continue
        close = _positive(row.get("Close"))
        if close is None:
            continue
        points.append((stamp, close))
    picked = price_versus_24h(points, now if now.tzinfo else now.replace(tzinfo=UTC))
    if picked is None:
        return None
    latest, prior = picked
    return {"price": latest, "prior_price": prior, "points": points}


def open_to_last(
    points: list[tuple[datetime, float, float]], now: datetime
) -> dict[str, float] | None:
    """Today's opening price and the latest print while the cash session is open.

    Each point is (timestamp, bar open, bar close). Premarket prints are left out.
    A last print more than 45 minutes behind ``now`` is too stale to alert on.
    """
    from .engine import EASTERN, cash_session_open

    moment = now if now.tzinfo else now.replace(tzinfo=UTC)
    moment = moment.astimezone(EASTERN)
    if not cash_session_open(moment):
        return None
    start = datetime.combine(moment.date(), time(9, 30), tzinfo=EASTERN)
    usable: list[tuple[datetime, float, float]] = []
    for stamp, opened, closed in points:
        when = stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)
        when = when.astimezone(EASTERN)
        if when < start or when > moment or opened <= 0 or closed <= 0:
            continue
        usable.append((when, opened, closed))
    if not usable:
        return None
    usable.sort(key=lambda item: item[0])
    last_at, _, last_px = usable[-1]
    if moment - last_at > timedelta(minutes=45):
        return None
    return {"price": last_px, "open": usable[0][1]}


def fetch_open_to_last(symbol: str, *, now: datetime) -> dict[str, float] | None:
    """Minute bars for a stock check while the cash session is open."""
    from .engine import cash_session_open

    if not cash_session_open(now):
        return None
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("yfinance is not installed. Install requirements first.") from exc
    try:
        hist = yf.Ticker(symbol).history(period="1d", interval="1m", auto_adjust=False)
    except Exception:
        return None
    if hist is None or getattr(hist, "empty", True):
        return None
    points: list[tuple[datetime, float, float]] = []
    for idx, row in hist.iterrows():
        try:
            stamp = idx.to_pydatetime()
        except Exception:
            continue
        opened = _positive(row.get("Open"))
        closed = _positive(row.get("Close"))
        if opened is None or closed is None:
            continue
        points.append((stamp, opened, closed))
    return open_to_last(points, now)


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or non-positive
        return None
    return number
