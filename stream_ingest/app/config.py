"""Settings for the Alpaca → Kafka price producer."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SYMBOLS = _ROOT / "data" / "sp500_symbols.txt"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    alpaca_api_key_id: str = ""
    alpaca_api_secret_key: str = ""
    alpaca_feed: str = "delayed_sip"
    alpaca_ws_symbol_limit: int = 30
    alpaca_ws_url_template: str = "wss://stream.data.alpaca.markets/v2/{feed}"
    alpaca_data_url: str = "https://data.alpaca.markets"

    kafka_bootstrap_servers: str = "127.0.0.1:9092"
    kafka_topic_bars: str = "prices.raw.bars"

    symbols_file: str = str(_DEFAULT_SYMBOLS)
    symbols: str = ""

    dry_run: bool = False
    rest_poll_enabled: bool = True
    rest_poll_seconds: int = 60
    rest_symbols_per_request: int = 100

    @property
    def ws_url(self) -> str:
        feed = self.alpaca_feed.strip() or "delayed_sip"
        return self.alpaca_ws_url_template.format(feed=feed)


settings = Settings()
