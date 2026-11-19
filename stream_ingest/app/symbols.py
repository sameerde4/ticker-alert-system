"""Load and shard the equity universe for Alpaca subscriptions."""

from __future__ import annotations

from pathlib import Path


def normalize_symbol(raw: str) -> str:
    """Alpaca uses hyphen class shares (BRK-B), matching the Yahoo form."""
    return raw.strip().upper().replace(".", "-")


def load_symbols(*, symbols_csv: str = "", symbols_file: str = "") -> list[str]:
    """Return a de-duplicated symbol list from a comma string and/or a text file."""
    found: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        symbol = normalize_symbol(raw)
        if not symbol or symbol.startswith("#") or symbol in seen:
            return
        seen.add(symbol)
        found.append(symbol)

    for part in symbols_csv.split(","):
        add(part)
    path = Path(symbols_file) if symbols_file else None
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            add(line)
    return found


def shard_symbols(symbols: list[str], *, limit: int) -> list[list[str]]:
    """Split symbols into WebSocket batches. Free Basic allows 30 per account."""
    if limit < 1:
        raise ValueError("Symbol limit must be at least 1.")
    return [symbols[i : i + limit] for i in range(0, len(symbols), limit)]
