# Ticker Alert System

Watch a list of tickers. Each symbol gets one alert per day:

- **Price** — only the close moved at least a configured percent versus the prior close.
- **News** — only headlines cleared the sentiment rule. The alert lists each score and link.
- **News + price** — both rules fired. The alert has a price section, a news section, and a short synthesis.

Each alert stores a plain-English explanation assembled from the alert fields. When FinBERT is selected, that model only produces the headline score. It does not write the paragraph. The time on a card is when the condition was met, in US Eastern: the 4:00 PM close for a price move, the earliest headline for news, and the later of those two when both fire.

Home lists alerts saved after you last had the page open. Reloading the page starts that visit again, so older cards stay on Alert History. Alert History is the full list, newest first: symbol, sector, type, time, the day's price change, news sentiment, and a details popup with the same write-up as the card. Column headings sort the table. Sector names come from Yahoo and are cached. The card clock is still when the condition was met. "New" uses the time the alert was first saved.

A symbol on a Home card, in the History symbol column, and in the details title opens that ticker's Yahoo Finance quote in a new tab.

A headline belongs to the Eastern trading day it was published. Saturday and Sunday stay with Friday. A story from the next morning does not attach to the prior close. News and price fuse only when both fire on that same day.

Each alert keeps the price and sentiment thresholds from when it fired. Those values are shown in the details popup. Changing the settings can replace today's alert on the next check. Earlier days stay as they were saved.

Settings stores the price percent and the FinBERT threshold. FinBERT is the only headline scorer. The model weights download once, and later checks score headlines on this computer. The first FinBERT in the Home rules line opens an explanation of the model, the 0–100 score, the confidence, and the 25-point default. The Watchlist box suggests a ticker or company name from a local list of about 5,400 symbols. Choosing a suggestion or pressing Enter only fills the box. Add checks that list, and asks Yahoo when the symbol is not on it. The message next to Run check says the ticker was added, was already on the list, or is not a ticker Yahoo recognizes. Under each headline, the sentiment score is bold and colored, then confidence, then the positive, negative, and neutral shares in brackets. Save and Reset to default change the two thresholds, and the Home rules line follows them. The next check rescores every saved headline. Volume stays an environment setting. Rebuild history is an admin tool on that same page: it deletes every saved alert, then reruns the current rules for each watchlist symbol over the last 1–40 calendar days, including today. Price history can be recomputed from daily closes. Headlines are only the stories already stored plus the recent list Yahoo returns now.

This is a separate repository from Vajra Astra Capital. Shared ideas (FastAPI, PostgreSQL migrations, Yahoo bars, the keyword sentiment lexicon) are copied here. Nothing imports the other repo.

The class target (Kafka, Flink, FinBERT, a historical lake) is drawn in [docs/architecture.md](docs/architecture.md). The process that runs today is the local path in that same document. Vendor details are in [docs/data-sources.md](docs/data-sources.md).

## Layout

| Path | Purpose |
|---|---|
| [`alert_service/`](alert_service/) | FastAPI app, single-page UI, tests |
| [`db/migrations/`](db/migrations/) | PostgreSQL schema |
| [`docs/`](docs/) | Architecture diagrams and data sources |

## Prerequisites

- Python 3.11+
- PostgreSQL (local database `ticker_alert_db`)

## Setup

```bash
cd alert_service
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Create the database and apply every migration from the repo root, in order:

```bash
psql postgresql://postgres:postgres@localhost:5432/postgres -c "CREATE DATABASE ticker_alert_db"
for f in db/migrations/*.sql; do
  psql postgresql://postgres:postgres@localhost:5432/ticker_alert_db -f "$f"
done
```

The files are `001_init.sql` through `010_finbert_score_out_of_100.sql`. They create the watchlist, bars, headlines, one alert per symbol per day, saved thresholds, cached sectors, the first-seen time, the thresholds stored on each alert, and the FinBERT score on a 0–100 scale with a 25-point gate around 50.

## Run

```bash
cd alert_service
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Open **http://127.0.0.1:8010/ui**. Add a ticker, then **Run check**.

The service listens on port **8010** so it can run beside another app on port 8000.

## Tests

```bash
cd alert_service
source .venv/bin/activate
python -m pytest -q
```

## Thresholds

The Settings tab stores the price percent and the sentiment threshold in `app_settings`. Until that row exists, a check uses the environment defaults in [`.env.example`](alert_service/.env.example).

| Variable | Meaning | Default |
|---|---|---|
| `TICKER_ALERT_PRICE_MOVE_THRESHOLD` | Absolute return versus the prior close, used until Settings is saved | `0.03` |
| `TICKER_ALERT_VOLUME_SPIKE_THRESHOLD` | Volume divided by the recent average. Not a Settings control | `2.0` |
| `TICKER_ALERT_SENTIMENT_THRESHOLD` | How far a 0–100 FinBERT score must sit from 50, used until Settings is saved | `25` |
| `TICKER_ALERT_NEWS_LOOKBACK_HOURS` | A headline older than this is ignored, even on its own trading day | `72` |
| `TICKER_ALERT_FUSION_WINDOW_HOURS` | Unused by the same-day rule. Kept so an older env file still loads | `48` |
