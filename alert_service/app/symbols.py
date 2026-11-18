"""Ticker symbol normalization."""

from __future__ import annotations

import json
import re
from pathlib import Path

_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:-[A-Z0-9]{1,4})?$")
_UNIVERSE: set[str] | None = None
_UNIVERSE_PATH = Path(__file__).resolve().parents[1] / "ui" / "symbol_universe.json"


def normalize_symbol(raw: str) -> str:
    """Uppercase a ticker and turn class-share dots into Yahoo-style hyphens (BRK.B -> BRK-B)."""
    text = (raw or "").strip().upper().replace(".", "-")
    if not _SYMBOL.fullmatch(text):
        raise ValueError("Enter a ticker such as AAPL or BRK.B.")
    return text


def trades_all_day(symbol: str) -> bool:
    """Yahoo crypto quotes, such as BTC-USD, keep printing after the stock close."""
    return symbol.upper().endswith("-USD")


def known_universe_symbol(symbol: str) -> bool:
    """True when the local ticker list already contains this symbol."""
    global _UNIVERSE
    if _UNIVERSE is None:
        try:
            payload = json.loads(_UNIVERSE_PATH.read_text(encoding="utf-8"))
            _UNIVERSE = {
                str(row.get("symbol") or "").upper()
                for row in payload.get("symbols") or []
            }
        except (OSError, json.JSONDecodeError):
            _UNIVERSE = set()
    return symbol in _UNIVERSE
