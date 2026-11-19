# Batch ingest (Yahoo → lake)

Historical **daily** OHLCV for the S&P 500, landed as Parquet in the raw zone. Headlines are scored on the near-term check path, not in this batch land.

## Storage

```text
data/lake/raw/prices/daily/symbol=AAPL/part-000.parquet
data/lake/raw/_runs/<run-id>.json
```

Postgres holds alerts and app state. The lake holds training history. Spark (or an equivalent job) reads these files into curated session features for Isolation Forest training.

## Setup

```bash
cd batch_ingest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Uses `stream_ingest/data/sp500_symbols.txt`.

## Run

```bash
python -m app.main
python -m app.main --symbols AAPL,MSFT,NVDA --days 30
python -m app.main --max-symbols 5 --days 60
```

Or use **Settings → Historical prices (lake)** in the UI.

## Next on this path

1. Curated feature rows per symbol per session: gap, session return, close return, volume z-score (price/volume only).
2. Fit Isolation Forest and save a registry entry.
3. Score the same features on live Kafka bars.

Headlines stay on the near-term check path. They are not inputs to this lake.

## Tests

```bash
python -m pytest -q
```
