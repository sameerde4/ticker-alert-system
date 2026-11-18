"""Ticker symbol normalization."""

from __future__ import annotations

import re

_SYMBOL = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:-[A-Z0-9]{1,4})?$")


def normalize_symbol(raw: str) -> str:
    """Uppercase a ticker and turn class-share dots into Yahoo-style hyphens (BRK.B -> BRK-B)."""
    text = (raw or "").strip().upper().replace(".", "-")
    if not _SYMBOL.fullmatch(text):
        raise ValueError("Enter a ticker such as AAPL or BRK.B.")
    return text
