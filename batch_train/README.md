# Batch train (curated features + Isolation Forest)

Local job for the **Spark** box on the class diagrams: read raw lake prices, write curated session features, fit **Isolation Forest**, and save a **model registry** the live scorer can load later.

Uses pandas + scikit-learn on one machine (**not** a Dataproc/EMR Spark cluster). Same feature contract and registry layout whether the lake is local disk or S3.

## Features (price / volume only)

One row per symbol per session:

| Field | Definition |
|---|---|
| `gap_return` | `(open − prior_close) / prior_close` |
| `session_return` | `(close − open) / open` |
| `close_return` | `(close − prior_close) / prior_close` |
| `volume_zscore` | `(volume − mean) / std` over the **prior** 20 sessions |

No FinBERT / news columns. Headlines stay on the near-term check path.

## Layout

```text
data/lake/raw/prices/daily/symbol=AAPL/part-000.parquet   # from batch_ingest
data/lake/curated/features/session/part-000.parquet       # this package
data/lake/registry/isolation_forest/current/
  model.joblib                                            # fitted forest
  meta.json                                               # feature list + score_cutoff
```

`meta.json` stores `feature_names`, `score_cutoff`, and `score_meaning`. A session is anomalous when `decision_function(x) <= score_cutoff`.

## Setup

```bash
cd batch_train
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Land raw prices first (`batch_ingest` or Settings → Historical prices). Keep the lake current with Settings **Refresh lake + retrain** (or `batch_ingest --days 14 --merge` then this job) so Live and Watchlist are not stuck on a stale registry.

## Run

```bash
# Curate + train on the whole raw lake
python -m app.main

# Quick smoke on a few symbols
python -m app.main --max-symbols 10

# Steps alone
python -m app.main --curate-only
python -m app.main --train-only
```

After training, both `python -m app.live` and Watchlist **Scan today** score sessions with `registry/isolation_forest/current/`.

## Tests

```bash
python -m pytest -q
```

## Consumers of this registry

- Live Kafka scorer (`python -m app.live`) — Flink role on the diagrams
- Watchlist Scan today / rebuild — same percent **or** forest price gate
