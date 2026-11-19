"""Runtime settings. Environment variables use the TICKER_ALERT_ prefix."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_PRICE_MOVE_THRESHOLD = 0.03
DEFAULT_SENTIMENT_THRESHOLD = 25.0
_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAKE_ROOT = str(_REPO_ROOT / "data" / "lake")


def price_fraction_from_percent(percent: float) -> float:
    """Turn a user-entered percentage (3 means 3%) into a fraction."""
    if percent != percent or percent <= 0 or percent > 100:
        raise ValueError("Price alert percentage must be greater than 0 and at most 100.")
    return percent / 100.0


def sentiment_threshold_value(score: float) -> float:
    """How far a 0–100 FinBERT score must sit from 50 before it opens a news alert."""
    if score != score or score <= 0 or score > 50:
        raise ValueError("Sentiment threshold must be greater than 0 and at most 50.")
    return float(score)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TICKER_ALERT_", env_file=".env", extra="ignore")

    app_name: str = "S&P 500 Alert System"
    app_env: str = "dev"
    app_port: int = 8010
    database_url: str = "postgresql://postgres:postgres@localhost:5432/ticker_alert_db"

    # Daily-bar price rule. A move at or beyond this fraction versus the prior close opens a price alert.
    price_move_threshold: float = DEFAULT_PRICE_MOVE_THRESHOLD
    # Latest volume divided by the average of the prior N bars. Attached to the price alert when known.
    volume_spike_threshold: float = 2.0
    volume_lookback: int = 20
    bar_lookback_days: int = 40

    # |score| at or beyond this opens a news alert. One mild keyword tops out near 0.33.
    sentiment_threshold: float = DEFAULT_SENTIMENT_THRESHOLD
    # Headlines newer than this are eligible for a news alert.
    news_lookback_hours: int = 72
    # Kept so older env files still load. A same-day check no longer writes a separate fusion row.
    fusion_window_hours: int = 48
    display_timezone: str = "America/New_York"
    # Saved in the database from Settings. This env value is used only when that column is empty.
    perplexity_api_key: str = ""
    perplexity_model: str = "openai/gpt-5.4-mini"
    perplexity_timeout_s: float = 45

    # Live Kafka → session-move path (python -m app.live).
    kafka_bootstrap_servers: str = "127.0.0.1:9092"
    kafka_topic_bars: str = "prices.raw.bars"
    kafka_group_id: str = "ticker-alert-live"
    live_watchlist_refresh_seconds: int = 30
    # UI treats the live consumer as on when the heartbeat is newer than this.
    live_heartbeat_stale_seconds: int = 15
    # Local lake root (registry + optional raw Parquet). Same path batch_train uses.
    lake_root: str = DEFAULT_LAKE_ROOT
    # Minimum seconds between live_feature_rows writes for one symbol (sink throttle).
    live_feature_min_interval_seconds: int = 60
    # When true, an Isolation Forest anomaly can upsert a live price alert (if no news row).
    live_forest_alerts: bool = True


settings = Settings()
