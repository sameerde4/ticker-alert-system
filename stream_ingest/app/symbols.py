"""Load and shard the equity universe for Alpaca subscriptions."""

from __future__ import annotations

from pathlib import Path


def normalize_symbol(raw: str) -> str:
    """Canonical form matches Yahoo / this repo: class shares use a hyphen (BRK-B)."""
    return raw.strip().upper().replace(".", "-")


def to_alpaca_symbol(symbol: str) -> str:
    """Alpaca REST/WebSocket expect a dot for class shares (BRK.B), not a hyphen."""
    return normalize_symbol(symbol).replace("-", ".")


def from_alpaca_symbol(symbol: str) -> str:
    """Map an Alpaca ticker back to the canonical hyphen form."""
    return normalize_symbol(symbol)


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


def prioritize_symbols(priority: list[str], universe: list[str]) -> list[str]:
    """Put priority tickers first (for WebSocket), then the rest of the universe."""
    found: list[str] = []
    seen: set[str] = set()
    for raw in [*priority, *universe]:
        symbol = normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        found.append(symbol)
    return found


def split_ws_rest(
    universe: list[str],
    *,
    ws_priority: list[str],
    limit: int,
    rest_enabled: bool = True,
) -> tuple[list[str], list[str]]:
    """WebSocket gets only the chosen priority symbols (capped); REST gets everyone else."""
    cap = max(0, int(limit))
    ws: list[str] = []
    seen: set[str] = set()
    for raw in ws_priority:
        symbol = normalize_symbol(raw)
        if not symbol or symbol in seen:
            continue
        if len(ws) >= cap:
            break
        seen.add(symbol)
        ws.append(symbol)
    if not rest_enabled:
        return ws, []
    rest = [symbol for symbol in universe if symbol not in seen]
    # Priority names missing from the universe file still stream on WS only.
    return ws, rest


def shard_symbols(symbols: list[str], *, limit: int) -> list[list[str]]:
    """Split symbols into WebSocket batches. Free Basic allows 30 per account."""
    if limit < 1:
        raise ValueError("Symbol limit must be at least 1.")
    return [symbols[i : i + limit] for i in range(0, len(symbols), limit)]
