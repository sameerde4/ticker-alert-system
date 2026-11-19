# Batch ingest (Yahoo → lake)

Historical **daily** OHLCV for the S&P 500, landed as Parquet in the raw zone. Headlines are scored on the near-term check path, not in this batch land.

## Storage

```text
data/lake/raw/prices/daily/symbol=AAPL/part-000.parquet
data/lake/raw/_runs/<run-id>.json
```

Postgres holds alerts and app state. The lake holds training history. [`batch_train/`](../batch_train/) is the local Spark-role job: it reads these files into curated session features, fits Isolation Forest, and writes the model registry.

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
# Full cold-start land (~1 year, replaces each symbol partition)
python -m app.main
python -m app.main --symbols AAPL,MSFT,NVDA --days 30
python -m app.main --max-symbols 5 --days 60
# Incremental refresh: merge recent sessions into existing Parquet
python -m app.main --days 14 --merge
```

The alert API also lands an empty lake on first boot and refreshes on a daily schedule. Refresh resumes from each symbol’s latest lake date and skips Yahoo (and the follow-on retrain) when already current through the last completed session. **Settings → Historical prices (lake)** remains available: **Land** (full) or **Refresh lake + retrain** as manual overrides.

## Next on this path

1. ~~Curated features + Isolation Forest registry~~ — see [`batch_train/`](../batch_train/).
2. Score the same features on live Kafka bars (Flink role on the diagram).

Headlines stay on the near-term check path. They are not inputs to this lake.

## Tests

```bash
python -m pytest -q
```
