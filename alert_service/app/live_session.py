"""Track open → latest from Kafka minute bars during the cash session."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from .engine import cash_session_open, eastern_date


@dataclass
class SessionState:
    symbol: str
    session_day: date
    open: float
    last: float
    last_ts: datetime
    volume: float = 0.0


def parse_bar_ts(raw: Any) -> datetime | None:
    """Parse an Alpaca / Kafka bar timestamp into aware UTC."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    text = str(raw).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def _nonneg(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number < 0:
        return 0.0
    return number


class SessionBook:
    """Per-symbol session open, latest close, and cumulative RTH volume from minute bars."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}

    def get(self, symbol: str) -> SessionState | None:
        return self._states.get(symbol.upper())

    def apply(self, bar: dict[str, Any]) -> SessionState | None:
        """Update state from one Kafka bar. Returns the state when the bar counts."""
        symbol = str(bar.get("symbol") or "").upper()
        stamp = parse_bar_ts(bar.get("ts"))
        opened = _positive(bar.get("open"))
        closed = _positive(bar.get("close"))
        bar_volume = _nonneg(bar.get("volume"))
        if not symbol or stamp is None or opened is None or closed is None:
            return None
        if not cash_session_open(stamp):
            return None
        day = eastern_date(stamp)
        prior = self._states.get(symbol)
        if prior is None or prior.session_day != day:
            state = SessionState(
                symbol=symbol,
                session_day=day,
                open=opened,
                last=closed,
                last_ts=stamp,
                volume=bar_volume,
            )
        elif stamp < prior.last_ts:
            return prior
        else:
            state = SessionState(
                symbol=symbol,
                session_day=day,
                open=prior.open,
                last=closed,
                last_ts=stamp,
                volume=prior.volume + bar_volume,
            )
        self._states[symbol] = state
        return state

    def live_session(self, symbol: str) -> dict[str, float] | None:
        state = self.get(symbol)
        if state is None:
            return None
        return {"price": state.last, "open": state.open}
