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
from .land import (
    expected_latest_session,
    merge_fetch_start,
    raw_daily_dir,
    write_run_manifest,
    write_symbol_parquet,
)
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
    parser.add_argument(
        "--merge",
        action="store_true",
        help=(
            "Merge new daily rows into existing Parquet by date (incremental refresh). "
            "Without this flag the partition is replaced (full land)."
        ),
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
    merge = bool(args.merge)
    run_id = date.today().isoformat() + "-" + uuid.uuid4().hex[:8]
    # Merge refreshes: expect the last *completed* session (not a pre-open "today").
    session_target = expected_latest_session() if merge else end
    log.info(
        "Landing %s symbol(s) daily bars %s → %s into %s (%s; session target %s)",
        len(symbols),
        start.isoformat(),
        end.isoformat(),
        lake_root,
        "merge" if merge else "replace",
        session_target.isoformat(),
    )

    results: list[dict] = []
    skipped_current = 0
    for index, symbol in enumerate(symbols, start=1):
        did_fetch = False
        try:
            if merge:
                fetch_start = merge_fetch_start(
                    lake_root,
                    symbol,
                    window_start=start,
                )
                if fetch_start is None:
                    skipped_current += 1
                    results.append(
                        {
                            "symbol": symbol,
                            "rows": 0,
                            "path": str(raw_daily_dir(lake_root, symbol) / "part-000.parquet"),
                            "error": None,
                            "skipped": "up_to_date",
                            "fetch_start": None,
                        }
                    )
                    log.info(
                        "[%s/%s] %s already current through %s (skipped Yahoo)",
                        index,
                        len(symbols),
                        symbol,
                        session_target.isoformat(),
                    )
                    continue
            else:
                fetch_start = start

            rows = fetch_daily_bars(symbol, start=fetch_start, end=end)
            path = write_symbol_parquet(lake_root, symbol, rows, merge=merge)
            did_fetch = True
            results.append(
                {
                    "symbol": symbol,
                    "rows": len(rows),
                    "path": str(path) if path else None,
                    "error": None,
                    "fetch_start": fetch_start.isoformat(),
                }
            )
            log.info(
                "[%s/%s] %s landed %s row(s)%s%s",
                index,
                len(symbols),
                symbol,
                len(rows),
                " (merged)" if merge else "",
                f" from {fetch_start.isoformat()}" if merge else "",
            )
        except Exception as exc:
            log.warning("[%s/%s] %s failed: %s", index, len(symbols), symbol, exc)
            results.append(
                {"symbol": symbol, "rows": 0, "path": None, "error": str(exc)}
            )
        # Only throttle actual Yahoo calls — local up-to-date skips stay instant.
        if pause and did_fetch and index < len(symbols):
            time.sleep(pause)

    manifest = write_run_manifest(
        lake_root,
        run_id=run_id,
        start=start,
        end=end,
        symbols_requested=symbols,
        results=results,
        merge=merge,
        skipped_current=skipped_current,
        session_target=session_target,
    )
    landed = sum(1 for row in results if row["rows"] > 0)
    rows = sum(int(row["rows"]) for row in results)
    log.info(
        "Done. %s/%s symbols, %s rows, skipped_current=%s, manifest=%s",
        landed,
        len(symbols),
        rows,
        skipped_current,
        manifest,
    )
    return {
        "run_id": run_id,
        "symbols": len(symbols),
        "landed": landed,
        "rows": rows,
        "skipped_current": skipped_current,
        "manifest": str(manifest),
        "lake_root": str(lake_root),
    }


def main() -> None:
    run(parse_args())


if __name__ == "__main__":
    main()
