# Ticker Alert System

Watch a list of tickers. Each symbol gets one alert per day:

- **Price** — while the market is open, the latest price versus the opening price. After the close, the close versus the prior close. A symbol that trades around the clock, such as BTC-USD, is measured over the 24 hours before the check.
- **News** — only headlines cleared the sentiment rule. The alert lists each score and link.
- **News + price** — both rules fired. The alert has a price section, a news section, and a short synthesis.

Each alert stores a plain-English explanation assembled from the alert fields. When a Perplexity key is saved, a check sends those facts and stores the two-sentence reply. Price, News, and Rule stay the sentences the app wrote. Together is the reply, and the model name is listed under it on Home and in the details popup. A check or rebuild sends at most eight alerts in one reply. FinBERT only produces the headline score. It does not write the paragraph. The rule sentence remains when no key is saved or the call fails. The time on a card is when the condition was met, in US Eastern: the 4:00 PM close for a stock price move, the time of the check for a 24-hour crypto move, the earliest headline for news, and the later of the price time and the headline when both fire.

Home lists alerts saved after you last had the page open. Reloading the page starts that visit again, so older cards stay on Alert History. Alert History is the full list, newest first: symbol, sector, time, and one Alert details column. That column starts with a colored type pill, then the score out of 100, the price change, or both, and the details link. Sorting Alert details orders the rows by type. The other column headings sort on their own values. A stock shows its Yahoo sector. An ETF or mutual fund shows the category of the product it targets, such as Technology or Large Blend. A crypto quote, including a digital-asset fund, shows Crypto. Those labels are cached. The card clock is still when the condition was met. "New" uses the time the alert was first saved.

A symbol on a Home card, in the History symbol column, and in the details title opens that ticker's Yahoo Finance quote in a new tab.

A headline belongs to the Eastern trading day it was published. Saturday and Sunday stay with Friday. A story from the next morning does not attach to the prior close. On that day, the publish time picks one price slice: the overnight gap before 9:30 AM Eastern, the regular session from the open to the latest price, or the close versus the prior close after 4:00 PM. During market hours the latest price is the print at the check. After the close it is the 4:00 PM close. A market that trades all day uses the four hours after the headline. The headline is a candidate reason only when that slice clears the same percent rule. A strong headline whose slice is flat stays a news card with no price change. A close that moved, with no headline in the slice that moved, stays a price card that says no headline lined up with the move.

Each alert keeps the price and sentiment thresholds from when it fired. Those values are shown in the details popup. Changing the settings can replace today's alert on the next check. Earlier days stay as they were saved.

Settings stores the price percent, the FinBERT threshold, and an optional Perplexity key. The key is write-only: the field shows dots when a key is saved, and the API reports only whether a key is saved. Clear key removes it. The model dropdown offers five ChatGPT models, five OpenAI models, and five Gemini models. A saved key takes the place of the rule sentence on the next check or rebuild, using the selected model. The details popup shows the two-sentence reply, and the rule sentence under Rule. FinBERT is the only headline scorer. The model weights download once, and later checks score headlines on this computer. The first FinBERT in the Home rules line opens an explanation of the model, the 0–100 score, the confidence, and the 25-point default. The words "matches the price move" in that same line open an explanation of the percent rule and the part of the day a headline can explain. The Watchlist box suggests a ticker or company name from a local list of about 5,400 symbols. Choosing a suggestion or pressing Enter only fills the box. Add checks that list, and asks Yahoo when the symbol is not on it. The message next to Run check says the ticker was added, was already on the list, or is not a ticker Yahoo recognizes. Under each headline, the sentiment score is bold and colored, then confidence, then the positive, negative, and neutral shares in brackets. Save and Reset to default change the two thresholds, and the Home rules line follows them. The next check rescores every saved headline. Volume stays an environment setting. Rebuild history is an admin tool on that same page: it deletes every saved alert, then reruns the current rules for each watchlist symbol over the last 1–40 calendar days, including today. A finished session uses that day's close. The rebuild pages Yahoo quote news back through the first day and scores each story on the trading day it was published.

This is a separate repository from Vajra Astra Capital. Shared ideas (FastAPI, PostgreSQL migrations, Yahoo bars, the keyword sentiment lexicon) are copied here. Nothing imports the other repo.

The class target is a batch lake and a live stream: Kafka, Flink, Spark, an Isolation Forest trained on the historical feature table, FinBERT, and a Perplexity summary. That plan is [docs/proposal-pipeline-audit.md](docs/proposal-pipeline-audit.md). The deck diagrams and the smaller path this process runs today are in [docs/architecture.md](docs/architecture.md). Vendor details are in [docs/data-sources.md](docs/data-sources.md).

## Layout

| Path | Purpose |
|---|---|
| [`alert_service/`](alert_service/) | FastAPI app, single-page UI, tests |
| [`db/migrations/`](db/migrations/) | PostgreSQL schema |
| [`docs/`](docs/) | Architecture diagrams, the revised class proposal, and data sources |

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

The files are `001_init.sql` through `012_perplexity_model.sql`. They create the watchlist, bars, headlines, one alert per symbol per day, saved thresholds, cached sectors, the first-seen time, the thresholds stored on each alert, the FinBERT score on a 0–100 scale with a 25-point gate around 50, and the Perplexity key and selected model used for alert reasoning.

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
| `TICKER_ALERT_PRICE_MOVE_THRESHOLD` | While the market is open, the latest price versus the open. After the close, the close versus the prior close. A market that trades all day uses the prior 24 hours. Used until Settings is saved | `0.03` |
| `TICKER_ALERT_VOLUME_SPIKE_THRESHOLD` | Volume divided by the recent average. Not a Settings control | `2.0` |
| `TICKER_ALERT_SENTIMENT_THRESHOLD` | How far a 0–100 FinBERT score must sit from 50, used until Settings is saved | `25` |
| `TICKER_ALERT_NEWS_LOOKBACK_HOURS` | On a live check, a headline older than this is ignored. A rebuild judges each past day as of 8:00 PM Eastern, so that day's headlines are inside this window | `72` |
| `TICKER_ALERT_FUSION_WINDOW_HOURS` | Unused by the same-day rule. Kept so an older env file still loads | `48` |
| `TICKER_ALERT_PERPLEXITY_API_KEY` | Used only when Settings has no saved key. The saved key is not returned by the API | empty |
| `TICKER_ALERT_PERPLEXITY_MODEL` | Model used when Settings has not chosen one. OpenAI ids without a provider prefix are sent as `openai/...` | `openai/gpt-5.4-mini` |
