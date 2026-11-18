"""Cache sector labels so alert history does not look them up on every view."""

from __future__ import annotations

import asyncio

import asyncpg

from .prices import fetch_sector
from .store import save_sector, sectors_to_refresh


async def ensure_symbol_sectors(conn: asyncpg.Connection, symbols: list[str]) -> None:
    needed = await sectors_to_refresh(conn, symbols)
    if not needed:
        return
    fetched = await asyncio.gather(*(asyncio.to_thread(fetch_sector, symbol) for symbol in needed))
    for symbol, sector in zip(needed, fetched, strict=True):
        await save_sector(conn, symbol, sector)
