"""Settings for the historical price lander."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[1]
_REPO = _ROOT.parent
_DEFAULT_SYMBOLS = _REPO / "stream_ingest" / "data" / "sp500_symbols.txt"
_DEFAULT_LAKE = _REPO / "data" / "lake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    lake_root: str = str(_DEFAULT_LAKE)
    symbols_file: str = str(_DEFAULT_SYMBOLS)
    symbols: str = ""
    lookback_days: int = 365
    # Pause between Yahoo calls so a full S&P pass is less likely to get throttled.
    request_pause_seconds: float = 0.15
    max_symbols: int = 0  # 0 = no cap


settings = Settings()
