# Data sources

## As-built

| Input | Source | Stored as |
|---|---|---|
| Daily OHLCV | Yahoo Finance through `yfinance` | `daily_bars` |
| Live / delayed minute bars | Alpaca `delayed_sip` via [`stream_ingest/`](../stream_ingest/) onto local Kafka (`prices.raw.bars`). Free Basic: WebSocket ≤30 symbols; REST fills the rest of the S&P list | Not persisted as bars; consumed by `python -m app.live` for open→last **price** alerts |
| Headlines | Yahoo quote news, then Yahoo Search when quote news is empty | `headlines` |
| Sentiment | Local FinBERT. Score is 0–100 (50 neutral). Confidence is the winning class probability | `headlines.sentiment_score`, plus confidence and class shares on the alert |

FinBERT is the ProsusAI/finbert model, loaded locally with PyTorch. The first use downloads the weights. Later scoring does not call a hosted analysis API. The model returns positive, negative, and neutral probabilities. The score shown in the app is 0 to 100: 50 plus 50 times positive minus negative. Confidence is the winning class probability. A headline joins a news alert when that score is at least 25 points from 50. The alert score is the average of the headlines that clear that gate.

A headline is stored when its title names the ticker or the company's first distinctive name word (Yahoo `shortName`, so `AAPL` also matches "Apple"). Yahoo often tags unrelated market stories with the symbol. Those are not alerts. Class-share tickers are stored in Yahoo form: `BRK.B` becomes `BRK-B`.

## Rules that read those tables

| Alert | Rule | Default |
|---|---|---|
| Price | While the market is open, one alert when the latest price clears the move rule versus the opening price. That same open→last rule is what `python -m app.live` applies from Kafka bars for watchlist symbols. After the close, Run check uses the close versus the prior close. A 24-hour market such as BTC-USD uses the price change over the 24 hours before the check. A volume spike is noted for stocks on the completed close, when volume is at least 2× the recent average | 3% |
| News | One alert for that trading day when a headline's 0–100 FinBERT score is at least 25 points from 50. Each headline keeps its score, confidence, breakdown, and link. The alert score is the average | 25 points from 50 |
| News + price | One alert when a headline's slice clears the same percent rule. Before 9:30 AM Eastern the slice is the overnight gap. From 9:30 AM to 4:00 PM it is the open-to-latest move, which is the open-to-close move after the market closes. After 4:00 PM it is the close versus the prior close. A 24-hour market uses the four hours after the headline. The words "candidate reason" are used only on this card. A headline whose slice is flat stays news, with the price left blank. A close with no headline in the slice that moved stays a price card that says no headline lined up | same rules |

A live check measures a symbol ending in `-USD`, such as BTC-USD, from hourly Yahoo prices: the latest price at the moment of the check, and the price 24 hours earlier. Those hourly prints are not saved as daily bars. Rebuild history still replays daily closes, so it does not reconstruct that rolling window.

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound still drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days. For that pass, Yahoo quote news is paged until a story is on or before the first day, or the list runs out. Each past session is judged as of 8:00 PM Eastern, so a headline published that day is scored for that day.

A headline and a price share a card only when the headline's slice clears the same percent rule. That card calls the headline a candidate reason. A strong headline on a flat slice stays a news card, and the price change is left off. A close that moved, with no headline in the slice that moved, stays a price card that says no headline lined up. Sharing an Eastern day is not that claim.

Alert History fills a blank sector from the same Yahoo profile. A stock uses `sector`. An ETF or mutual fund uses the category of the product it targets (`category`, or the fund overview when the quote profile leaves that blank). A cryptocurrency, and a fund in the Digital Assets category, is labeled Crypto.

The card time is when the condition was met, in US Eastern. During market hours a stock price move uses the time of the check and the change from the open. After 4:00 PM it uses the close. A 24-hour market uses the time the check measured the last 24 hours. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The details title shows the symbol, the alert type, and that time on one line. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Target sources

The revised class target is in [proposal-pipeline-audit.md](proposal-pipeline-audit.md). Live / delayed minute bars come from Alpaca onto Kafka via [`stream_ingest/`](../stream_ingest/). On the free Basic plan the WebSocket covers 30 symbols (`delayed_sip`); the rest of the S&P 500 is filled by delayed SIP REST minute bars onto the same topic. Paid Algo Trader Plus lifts the WebSocket cap. The as-built consumer is `python -m app.live`: open→last price alerts for the watchlist, plus a heartbeat so Home can show Live alerts on. Headlines are still scored with FinBERT on Run check and persisted; that store is the news history, because there is no live news topic yet. Historical bars and those headlines still land in S3 in the target plan. Spark builds the feature table and fits an Isolation Forest. Flink applies that model. After the alert row exists, Perplexity writes two sentences from the payload, and the deterministic sentence is the fallback.

Kafka minute bars and the live price consumer are connected. Flink, Spark, and the lake are not. The as-built check diagram, the as-built live stream diagram, and the revised target diagrams are in [architecture.md](architecture.md). FinBERT does run here, on each headline during a check, from weights stored on this machine. When a Perplexity key is saved in Settings, that call takes the place of the rule sentence. A check sends one JSON payload for the alerts it just decided: the price change, the headlines, and the FinBERT score, confidence, and class shares. The model dropdown has five ChatGPT models, five OpenAI models, and five Gemini models. Perplexity writes two sentences with the selected model. The key field shows dots when a key is saved. Together ends with the name of the model that wrote it. A check sends the alerts in batches of eight. The deterministic sentence remains when no key is saved or the call fails. Rule stays under Rule when the reply replaces Together.
