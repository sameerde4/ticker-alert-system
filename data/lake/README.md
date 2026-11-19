# Data lake

Raw and curated zones for the S&P 500 batch path. Layout matches the class S3 lake.

| Path | Role |
|---|---|
| `raw/prices/daily/symbol=TICKER/*.parquet` | Yahoo daily OHLCV from `batch_ingest` or Settings → Historical prices |
| `curated/` | Session price/volume feature rows for Isolation Forest training |

No historical headlines are stored here.

Raw and curated Parquet files are gitignored. Only this README is committed.

```bash
cd batch_ingest
source .venv/bin/activate
python -m app.main                 # S&P 500, last ~365 calendar days
python -m app.main --symbols AAPL,MSFT --days 30
```
