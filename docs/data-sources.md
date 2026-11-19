# Data sources

## As-built

| Input | Source | Stored as |
|---|---|---|
| Daily OHLCV (check) | Yahoo Finance through `yfinance` | `daily_bars` |
| Live / delayed minute bars | Alpaca `delayed_sip` via [`stream_ingest/`](../stream_ingest/) onto local Kafka (`prices.raw.bars`). Free Basic: WebSocket ≤30 symbols; REST fills the rest of the S&P list | Consumed by `python -m app.live` for open→last **percent** and Isolation Forest **price** alerts; feature rows in `live_feature_rows` |
| Historical daily OHLCV (S&P 500, ~1 year) | Yahoo Finance via [`batch_ingest/`](../batch_ingest/) or Settings → Historical prices | Lake Parquet: `data/lake/raw/prices/daily/symbol=TICKER/` |
| Near-term headlines | Yahoo quote news, then Yahoo Search when quote news is empty | `headlines` |
| Sentiment | Local FinBERT. Score is 0–100 (50 neutral). Confidence is the winning class probability | `headlines.sentiment_score`, plus confidence and class shares on the alert |

FinBERT is the ProsusAI/finbert model, loaded locally with PyTorch. The first use downloads the weights. Later scoring does not call a hosted analysis API. The model returns positive, negative, and neutral probabilities. The score shown in the app is 0 to 100: 50 plus 50 times positive minus negative. Confidence is the winning class probability. A headline joins a news alert when that score is at least 25 points from 50. The alert score is the average of the headlines that clear that gate.

A headline is stored when its title names the ticker or the company's first distinctive name word (Yahoo `shortName`, so `AAPL` also matches "Apple"). Yahoo often tags unrelated market stories with the symbol. Those are not alerts. Class-share tickers are stored in Yahoo form: `BRK.B` becomes `BRK-B`.

**Historical headlines are not pulled into the lake.** News is near-term product logic for the same trading day. Batch training uses price and volume features only.

## Rules that read those tables

| Alert | Rule | Default |
|---|---|---|
| Price | While the market is open, one alert when the latest price clears the move rule versus the opening price. `python -m app.live` applies that open→last percent rule and, when the lake registry is present, the registered Isolation Forest on the same four session features. After the close, Run check uses the close versus the prior close. A volume spike is noted on the completed close when volume is at least 2× the recent average. **Local final:** after a live price alert, look up near-term headlines and upgrade the day when the slice matches | 3% (percent) / registry cutoff (forest) |
| News | One alert for that trading day when a headline's 0–100 FinBERT score is at least 25 points from 50. Each headline keeps its score, confidence, breakdown, and link. The alert score is the average | 25 points from 50 |
| News + price | One alert when a headline's slice clears the same percent rule. Before 9:30 AM Eastern the slice is the overnight gap. From 9:30 AM to 4:00 PM it is the open-to-latest move, which is the open-to-close move after the market closes. After 4:00 PM it is the close versus the prior close. The words "candidate reason" are used only on this card. A headline whose slice is flat stays news, with the price left blank. A close with no headline in the slice that moved stays a price card that says no headline lined up | same rules |

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days. For that pass, Yahoo quote news is paged until a story is on or before the first day, or the list runs out. Each past session is judged as of 8:00 PM Eastern, so a headline published that day is scored for that day.

A headline and a price share a card only when the headline's slice clears the same percent rule. That card calls the headline a candidate reason. A strong headline on a flat slice stays a news card, and the price change is left off. A close that moved, with no headline in the slice that moved, stays a price card that says no headline lined up. Sharing an Eastern day is not that claim.

Alert History fills a blank sector from the same Yahoo profile. A stock uses `sector`. An ETF or mutual fund uses the category of the product it targets (`category`, or the fund overview when the quote profile leaves that blank).

The card time is when the condition was met, in US Eastern. During market hours a stock price move uses the time of the check and the change from the open. After 4:00 PM it uses the close. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The details title shows the symbol, the alert type, and that time on one line. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Class sources and lake

The revised class architecture is in [proposal-pipeline-audit.md](proposal-pipeline-audit.md). The demo stack is **local** (Docker Kafka, Postgres, `data/lake`); AWS production is not required. Live / delayed minute bars come from Alpaca onto Kafka via [`stream_ingest/`](../stream_ingest/). On the free Basic plan the WebSocket covers 30 symbols (`delayed_sip`); the rest of the S&P 500 is filled by delayed SIP REST minute bars onto the same topic. Paid Algo Trader Plus lifts the WebSocket cap. `python -m app.live` writes open→last **percent-rule** price alerts for the watchlist, scores live session features with the registered Isolation Forest when present, sinks rows to `live_feature_rows`, and heartbeats so Home can show Live alerts on. Headlines are scored with FinBERT on **Run check** for the near-term window. The local final product path is **price first, then news**: after a live price or forest alert, fetch near-term headlines for that symbol, score them, and upgrade to news / news+price when the same-day slice matches (skip stale prior-day stories). That live upgrade is not wired yet. Historical **prices** for the index land in the lake as daily Parquet. `batch_train` builds gap, session, close, and volume z-score features and fits an Isolation Forest into the local registry (Spark role on the diagram). After a news or news+price alert exists, Perplexity writes richer short reasoning from the payload; price-only keeps the rule sentence, and the deterministic sentence is the fallback when the call fails. The open dashboard tab can raise a Mac/Chrome desktop notification and a title/favicon badge when Run check or live writes new rows. Slack and email are not used.

As-built and local final target diagrams are in [architecture.md](architecture.md). When a Perplexity key is saved in Settings, that call rewrites news and news + price cards. A check sends one JSON payload for those alerts: the price change when present, the headlines (with urls), and the FinBERT score, confidence, and class shares. The model dropdown has five ChatGPT models, five OpenAI models, and five Gemini models. Perplexity writes three to four short sentences with the selected model. Price-only alerts keep the rule sentence. The key field shows dots when a key is saved. Together ends with the name of the model that wrote it. A check sends the alerts in batches of eight. The deterministic sentence remains when no key is saved or the call fails. Rule stays under Rule when the reply replaces Together.
