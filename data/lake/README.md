# Data lake

Raw, curated, and registry zones for the S&P 500 batch path. Layout matches the class S3 lake.

| Path | Role |
|---|---|
| `raw/prices/daily/symbol=TICKER/*.parquet` | Yahoo daily OHLCV from automatic first-boot land, `batch_ingest`, or Settings **Land** (full) / **Refresh** (merge recent days) |
| `curated/features/session/*.parquet` | Session price/volume feature rows from `batch_train` |
| `registry/isolation_forest/current/` | Fitted Isolation Forest (`model.joblib`) + `meta.json` (feature list, score cutoff) |

Live Kafka bars do **not** write here. The alert API lands an empty lake on first boot and refreshes + retrains on a daily schedule (refresh skips Yahoo + retrain when already current through the last completed session). Settings **Refresh lake + retrain** (or `batch_ingest --days 14 --merge` then `batch_train`) remain manual overrides.

No historical headlines are stored here.

Raw Parquet, curated Parquet, and registry artifacts are gitignored. Only this README is committed.

```bash
cd batch_ingest
source .venv/bin/activate
python -m app.main                 # S&P 500, last ~365 calendar days
python -m app.main --symbols AAPL,MSFT --days 30

cd ../batch_train
source .venv/bin/activate
python -m app.main                 # curate features + fit Isolation Forest
```
