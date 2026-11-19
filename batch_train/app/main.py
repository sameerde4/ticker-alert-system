"""CLI: curate lake features, then fit Isolation Forest into the local registry.

This is the local job that the architecture diagrams label as Spark ELT + training.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import (
    DEFAULT_CONTAMINATION,
    DEFAULT_LAKE_ROOT,
    DEFAULT_N_ESTIMATORS,
    DEFAULT_RANDOM_STATE,
)
from .curate import curate_session_features
from .train import train_and_register

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Curate session price/volume features from the raw lake and fit "
            "Isolation Forest into data/lake/registry/isolation_forest/current/."
        )
    )
    parser.add_argument(
        "--lake-root",
        type=Path,
        default=DEFAULT_LAKE_ROOT,
        help=f"Lake root (default: {DEFAULT_LAKE_ROOT})",
    )
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=None,
        help="Optional cap on raw symbols (for a quick smoke run).",
    )
    parser.add_argument(
        "--contamination",
        type=float,
        default=DEFAULT_CONTAMINATION,
        help="Expected anomaly fraction used to pick the score cutoff (default 0.02).",
    )
    parser.add_argument(
        "--n-estimators",
        type=int,
        default=DEFAULT_N_ESTIMATORS,
        help="Isolation Forest trees (default 200).",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=DEFAULT_RANDOM_STATE,
        help="RNG seed for a repeatable fit.",
    )
    parser.add_argument(
        "--curate-only",
        action="store_true",
        help="Write curated features only; skip training.",
    )
    parser.add_argument(
        "--train-only",
        action="store_true",
        help="Fit from existing curated Parquet; skip curate.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lake_root = args.lake_root.resolve()
    if args.curate_only and args.train_only:
        log.error("Use only one of --curate-only or --train-only.")
        return 2

    result: dict = {"lake_root": str(lake_root)}
    try:
        if not args.train_only:
            result["curate"] = curate_session_features(
                lake_root,
                max_symbols=args.max_symbols,
            )
        if not args.curate_only:
            result["train"] = train_and_register(
                lake_root,
                contamination=args.contamination,
                n_estimators=args.n_estimators,
                random_state=args.random_state,
            )
    except Exception as exc:
        log.error("%s", exc)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
