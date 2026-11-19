# Data lake

Raw, curated, and registry zones for the S&P 500 batch path. Layout matches the class S3 lake.

| Path | Role |
|---|---|
| `raw/prices/daily/symbol=TICKER/*.parquet` | Yahoo daily OHLCV from `batch_ingest` or Settings → Historical prices |
| `curated/features/session/*.parquet` | Session price/volume feature rows from `batch_train` |
| `registry/isolation_forest/current/` | Fitted Isolation Forest (`model.joblib`) + `meta.json` (feature list, score cutoff) |

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
