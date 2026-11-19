"""Land one year of Yahoo daily bars for the S&P 500 into the local lake.

  python -m app.main
  python -m app.main --symbols AAPL,MSFT --days 30
"""

from __future__ import annotations

import argparse
import logging
import time
import uuid
from datetime import date
from pathlib import Path

from .config import settings
from .land import write_run_manifest, write_symbol_parquet
from .symbols import load_symbols
from .yahoo_daily import fetch_daily_bars, window_for_days

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("batch_ingest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Land Yahoo daily OHLCV into data/lake/raw/prices/daily"
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbols (overrides the S&P file when set)",
    )
    parser.add_argument(
        "--symbols-file",
        default="",
        help="Symbol list file (default: stream_ingest/data/sp500_symbols.txt)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="Calendar days of history to pull (default: 365)",
    )
    parser.add_argument(
        "--lake-root",
        default="",
        help="Lake root directory (default: data/lake under the repo)",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="Optional cap for a shorter test run",
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=-1,
        help="Seconds to sleep between Yahoo calls (default from settings)",
    )
    return parser.parse_args()


def run(args: argparse.Namespace) -> dict:
    days = args.days or settings.lookback_days
    start, end = window_for_days(days)
    symbols = load_symbols(
        symbols_csv=args.symbols or settings.symbols,
        symbols_file=(
            ""
            if (args.symbols or settings.symbols)
            else (args.symbols_file or settings.symbols_file)
        ),
    )
    cap = args.max_symbols or settings.max_symbols
    if cap > 0:
        symbols = symbols[:cap]
    if not symbols:
        raise SystemExit("No symbols loaded. Check --symbols or the S&P file.")

    lake_root = Path(args.lake_root or settings.lake_root).resolve()
    pause = settings.request_pause_seconds if args.pause < 0 else max(0.0, args.pause)
    run_id = date.today().isoformat() + "-" + uuid.uuid4().hex[:8]
    log.info(
        "Landing %s symbol(s) daily bars %s → %s into %s",
        len(symbols),
        start.isoformat(),
        end.isoformat(),
        lake_root,
    )

    results: list[dict] = []
    for index, symbol in enumerate(symbols, start=1):
        try:
            rows = fetch_daily_bars(symbol, start=start, end=end)
            path = write_symbol_parquet(lake_root, symbol, rows)
            results.append(
                {
                    "symbol": symbol,
                    "rows": len(rows),
                    "path": str(path) if path else None,
                    "error": None,
                }
            )
            log.info(
                "[%s/%s] %s landed %s row(s)",
                index,
                len(symbols),
                symbol,
                len(rows),
            )
        except Exception as exc:
            log.warning("[%s/%s] %s failed: %s", index, len(symbols), symbol, exc)
            results.append(
                {"symbol": symbol, "rows": 0, "path": None, "error": str(exc)}
            )
        if pause and index < len(symbols):
            time.sleep(pause)

    manifest = write_run_manifest(
        lake_root,
        run_id=run_id,
        start=start,
        end=end,
        symbols_requested=symbols,
        results=results,
    )
    landed = sum(1 for row in results if row["rows"] > 0)
    rows = sum(int(row["rows"]) for row in results)
    log.info(
        "Done. %s/%s symbols, %s rows, manifest=%s",
        landed,
        len(symbols),
        rows,
        manifest,
    )
    return {
        "run_id": run_id,
        "symbols": len(symbols),
        "landed": landed,
        "rows": rows,
        "manifest": str(manifest),
        "lake_root": str(lake_root),
    }


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
