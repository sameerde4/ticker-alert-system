# S&P 500 Alert System

Decision-support alerts for the **S&P 500**. Two product paths sit side by side: **Live** (Kafka open→last feed → Home Recent alerts) and **Watchlist** (focus set + Scan today → Today's results). The batch lake trains Isolation Forest; it is not the Watchlist UI. Each symbol gets one alert per day:

- **Price** — while the market is open, the latest price versus the opening price. After the close, the close versus the prior close.
- **News** — headlines that clear the FinBERT sentiment rule. The alert lists each score and link.
- **News + price** — both rules fired. The alert has a price section, a news section, and a short synthesis.

Each alert stores a plain-English explanation assembled from the alert fields. When a Perplexity key is saved, a check sends news and news + price facts and stores a richer three-to-four-sentence reply (what happened, why the headlines matter with titles/links, FinBERT reading, cautious forward look). Price-only alerts keep the rule sentence for now. Price, News, and Rule stay the sentences the app wrote. Together is the reply, and the model name is listed under it on Home and in the details popup. A check or rebuild sends at most eight alerts in one reply. FinBERT only produces the headline score. It does not write the paragraph. The rule sentence remains when no key is saved or the call fails. The time on a card is when the condition was met, in US Eastern: the 4:00 PM close for a stock price move, the earliest headline for news, and the later of the price time and the headline when both fire.

The UI tabs are **Home** (Recent alerts, with an S&P 500 / Watchlist scope switch), **Watchlist** (add symbols, Scan today, Today's results), **History**, and **Settings**. Home Recent alerts keep across refresh until you click Clear alerts. Watchlist Scan today shows results on the Watchlist tab so it does not overwrite Home. Before the cash open (and on weekends), Scan today covers the **last completed session**; during/after RTH it covers **today**. Alert History always has the full list, with **Origin**, **Company** (S&P universe name), and **Type** (kind + metrics); click a row for the write-up; drag column headings to reorder. When Scan today or the live path adds alerts, the open UI tab shows a count on the title and favicon, and Chrome raises a Mac desktop notification (Notification Center) if you allowed notifications—use Enable desktop notifications on Home if the OS popup never appears. Expandable cards and the details popup show the Yahoo symbol link beside the company name. The card clock is when the condition was met. "New" uses the time the alert was first saved.

A symbol on a Home card, in the History symbol column, and in the details title opens that ticker's Yahoo Finance quote in a new tab.

A headline belongs to the Eastern trading day it was published. Saturday and Sunday stay with Friday. A story from the next morning does not attach to the prior close. On that day, the publish time picks one price slice: the overnight gap before 9:30 AM Eastern, the regular session from the open to the latest price, or the close versus the prior close after 4:00 PM. During market hours the latest price is the print at the check. After the close it is the 4:00 PM close. A market that trades all day uses the four hours after the headline. The headline is a candidate reason only when that slice clears the same percent rule. A strong headline whose slice is flat stays a news card with no price change. A close that moved, with no headline in the slice that moved, stays a price card that says no headline lined up with the move.

Each alert keeps the price and sentiment thresholds from when it fired. Those values are shown in the details popup. Changing the settings can replace today's alert on the next check. Earlier days stay as they were saved.

Settings stores the price percent, the FinBERT threshold, and an optional Perplexity key. The key is write-only: the field shows dots when a key is saved, and the API reports only whether a key is saved. Clear key removes it. The model dropdown offers five ChatGPT models, five OpenAI models, and five Gemini models. A saved key rewrites news and news + price cards on the next check or rebuild, using the selected model. The details popup shows that reply under Together, and the rule sentence under Rule. FinBERT is the only headline scorer. The model weights download once; checks score headlines on this computer. The first FinBERT in the Home rules line opens an explanation of the model, the 0–100 score, the confidence, and the 25-point default. The words "matches the price move" in that same line open an explanation of the percent rule and the part of the day a headline can explain. The Watchlist tab suggests an S&P 500 ticker or company name. Choosing a suggestion or pressing Enter only fills the box. Add accepts constituents on that list. Use Scan today to re-evaluate the focus set under current rules (after the close, after changing thresholds, or when live was down). Under each headline, the sentiment score is bold and colored, then confidence, then the positive, negative, and neutral shares in brackets. Save and Reset to default change the two thresholds, and the Home rules line follows them. The next check rescores every saved headline. Volume stays an environment setting. Historical prices (lake) lands about one year of Yahoo daily bars for the full S&P 500 into `data/lake/raw/` for **model training**. Rebuild history deletes every saved alert, then reruns the current rules for each watchlist symbol over the last 1–40 calendar days, including today. A finished session uses that day's close. The rebuild pages Yahoo quote news back through the first day and scores each story on the trading day it was published.

This is a separate repository from Vajra Astra Capital. Shared ideas (FastAPI, PostgreSQL migrations, Yahoo bars, the keyword sentiment lexicon) are copied here. Nothing imports the other repo.

The class architecture is a **local** lambda stack: Docker Kafka (live), a batch lake + Spark-role training job (`batch_train`), Watchlist Scan today as the on-demand session product path, Isolation Forest on lake price/volume features, FinBERT, and a Perplexity summary. AWS production deploy is not required. That plan is [docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md). As-built vs local final target diagrams (including Live vs Watchlist) are in [docs/architecture.md](docs/architecture.md). Vendor details are in [docs/data-sources.md](docs/data-sources.md).

## Layout

| Path | Purpose |
|---|---|
| [`dev.sh`](dev.sh) | One-command start / restart / stop for the local stack |
| [`alert_service/`](alert_service/) | FastAPI app, single-page UI, tests, Kafka live price consumer (`python -m app.live`) |
| [`stream_ingest/`](stream_ingest/) | Alpaca delayed SIP → Kafka minute-bar producer (S&P 500) |
| [`batch_ingest/`](batch_ingest/) | Yahoo daily history → lake Parquet under `data/lake/raw/` |
| [`batch_train/`](batch_train/) | Curated session features + Isolation Forest registry (local Spark-role job) |
| [`data/lake/`](data/lake/) | Raw, curated, and registry lake layout (artifacts gitignored) |
| [`db/migrations/`](db/migrations/) | PostgreSQL schema |
| [`docs/`](docs/) | Architecture diagrams, the revised class proposal, and data sources |

## Prerequisites

- Python 3.11+
- PostgreSQL (local database `ticker_alert_db`)
- Docker Desktop (for local Kafka when using the live price path)
- Alpaca API keys in `stream_ingest/.env` (paper keys are fine)

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

The files are `001_init.sql` through `015_alert_origin.sql`. They create the watchlist, bars, headlines, one alert per symbol per day, saved thresholds, cached sectors, the first-seen time, the thresholds stored on each alert, the FinBERT score on a 0–100 scale with a 25-point gate around 50, the Perplexity key and selected model used for alert reasoning, the live-consumer heartbeat used by the Home “Live alerts on” cue, `live_feature_rows` for live Isolation Forest feature vectors (Timescale stand-in), and `alerts.origin` (`live` / `watchlist` / `both`) so History can tell how a row was written.

## Run

One command from the repo root starts Docker Kafka, the Alpaca producer, the live consumer, and the API/UI:

```bash
./dev.sh start
```

Open **http://127.0.0.1:8010/ui**. After backend edits, restart only the API (Kafka, producer, and live stay up):

```bash
./dev.sh restart
```

Useful extras: `./dev.sh status`, `./dev.sh logs`, `./dev.sh restart-live`, `./dev.sh restart-producer`, `./dev.sh stop`, `./dev.sh down`. By default the producer covers the full S&P 500 (WebSocket first 30 on Alpaca Basic, REST for the rest). Narrow it with `DEV_SYMBOLS=AAPL,MSFT,NVDA ./dev.sh start` if you want a short list.

Manual equivalent (three terminals) if you prefer not to use the script:

```bash
cd alert_service
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

On the **Watchlist** tab, add an S&P 500 ticker, then **Scan today**. The watchlist is the **focus set** for Scan today and rebuild. Live covers the streamed index on Home Recent. The product universe is the full index (lake land, symbol search, stream); Scan today does not automatically run all 500 names. Pre-market and weekend scans use the last completed session so the results pane is not empty before the open.

On first API boot with an empty lake, the service **lands** about one year of S&P Yahoo dailies and trains Isolation Forest automatically; a header cue shows “Loading historical prices” with a progress %. After that it **refreshes + retrains** on a daily schedule (override with `TICKER_ALERT_LAKE_REFRESH_INTERVAL_HOURS`, or disable with `TICKER_ALERT_SKIP_LAKE_AUTO=1`). Refresh checks local dates first and **skips Yahoo + retrain** when the lake is already current through the last completed session.

On **Settings → Historical prices (lake)** the buttons are manual overrides:
- **Land S&P 500 prices** — about one year of Yahoo dailies into `data/lake/raw/` (cold start / full replace; same as `batch_ingest`).
- **Refresh lake + retrain** — resume from each symbol’s latest lake date (lookback capped ~14 calendar days), merge into Parquet, then `batch_train` only when new rows land. If everything is already current, both Yahoo and retrain are skipped.

CLI equivalent for the incremental loop:

```bash
cd batch_ingest && python -m app.main --days 14 --merge
cd ../batch_train && python -m app.main
```

To build curated features and fit Isolation Forest into the local registry after a full land:

```bash
cd batch_train
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.main
```

That writes `data/lake/curated/features/session/` and `data/lake/registry/isolation_forest/current/` (model + score cutoff). It is the local job the diagrams label as Spark training.

For live open→last price alerts during the cash session:

```bash
# repo root — local Kafka
docker compose up -d

# terminal: Alpaca → Kafka (Basic WebSocket cap is 30 symbols; REST covers the rest of the index)
cd stream_ingest && source .venv/bin/activate
python -m app.main --ws-only --symbols AAPL,MSFT,NVDA

# terminal: Kafka → Postgres price alerts
cd alert_service && source .venv/bin/activate
python -m app.live
```

Home shows a pulsing **Live alerts on** pill while the consumer heartbeats. That process writes session price alerts from the stream (then near-term news upgrade when the slice matches) onto Home Recent with `origin=live`. **Watchlist Scan today** is the separate on-demand pass for the focus set. Diagrams: [docs/architecture.md](docs/architecture.md).

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
| `TICKER_ALERT_PRICE_MOVE_THRESHOLD` | While the market is open, the latest price versus the open. After the close, the close versus the prior close. A market that trades all day uses the prior 24 hours. Used until Settings is saved | `0.03` |
| `TICKER_ALERT_VOLUME_SPIKE_THRESHOLD` | Volume divided by the recent average. Not a Settings control | `2.0` |
| `TICKER_ALERT_SENTIMENT_THRESHOLD` | How far a 0–100 FinBERT score must sit from 50, used until Settings is saved | `25` |
| `TICKER_ALERT_NEWS_LOOKBACK_HOURS` | On a live check, a headline older than this is ignored. A rebuild judges each past day as of 8:00 PM Eastern, so that day's headlines are inside this window | `72` |
| `TICKER_ALERT_FUSION_WINDOW_HOURS` | Unused by the same-day rule. Kept so an older env file still loads | `48` |
| `TICKER_ALERT_PERPLEXITY_API_KEY` | Used only when Settings has no saved key. The saved key is not returned by the API | empty |
| `TICKER_ALERT_PERPLEXITY_MODEL` | Model used when Settings has not chosen one. OpenAI ids without a provider prefix are sent as `openai/...` | `openai/gpt-5.4-mini` |
