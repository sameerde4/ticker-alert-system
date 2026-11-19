"""Load the equity universe for the historical land."""

from __future__ import annotations

from pathlib import Path


def normalize_symbol(raw: str) -> str:
    return raw.strip().upper().replace(".", "-")


def load_symbols(*, symbols_csv: str = "", symbols_file: str = "") -> list[str]:
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
