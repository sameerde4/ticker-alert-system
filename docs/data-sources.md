# Data sources

## As-built

| Input | Source | Stored as |
|---|---|---|
| Daily OHLCV | Yahoo Finance through `yfinance` | `daily_bars` |
| Headlines | Yahoo quote news, then Yahoo Search when quote news is empty | `headlines` |
| Sentiment | Local FinBERT. Score is 0–100 (50 neutral). Confidence is the winning class probability | `headlines.sentiment_score`, plus confidence and class shares on the alert |

FinBERT is the ProsusAI/finbert model, loaded locally with PyTorch. The first use downloads the weights. Later scoring does not call a hosted analysis API. The model returns positive, negative, and neutral probabilities. The score shown in the app is 0 to 100: 50 plus 50 times positive minus negative. Confidence is the winning class probability. A headline joins a news alert when that score is at least 25 points from 50. The alert score is the average of the headlines that clear that gate.

A headline is stored when its title names the ticker or the company's first distinctive name word (Yahoo `shortName`, so `AAPL` also matches "Apple"). Yahoo often tags unrelated market stories with the symbol. Those are not alerts. Class-share tickers are stored in Yahoo form: `BRK.B` becomes `BRK-B`.

## Rules that read those tables

| Alert | Rule | Default |
|---|---|---|
| Price | While the market is open, one alert when the latest price clears the move rule versus the opening price. After the close, the close versus the prior close. A 24-hour market such as BTC-USD uses the price change over the 24 hours before the check. A volume spike is noted for stocks on the completed close, when volume is at least 2× the recent average | 3% |
| News | One alert for that trading day when a headline's 0–100 FinBERT score is at least 25 points from 50. Each headline keeps its score, confidence, breakdown, and link. The alert score is the average | 25 points from 50 |
| News + price | One alert when a headline's slice clears the same percent rule. Before 9:30 AM Eastern the slice is the overnight gap. From 9:30 AM to 4:00 PM it is the open-to-latest move, which is the open-to-close move after the market closes. After 4:00 PM it is the close versus the prior close. A 24-hour market uses the four hours after the headline. The words "candidate reason" are used only on this card. A headline whose slice is flat stays news, with the price left blank. A close with no headline in the slice that moved stays a price card that says no headline lined up | same rules |

A live check measures a symbol ending in `-USD`, such as BTC-USD, from hourly Yahoo prices: the latest price at the moment of the check, and the price 24 hours earlier. Those hourly prints are not saved as daily bars. Rebuild history still replays daily closes, so it does not reconstruct that rolling window.

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound still drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days. For that pass, Yahoo quote news is paged until a story is on or before the first day, or the list runs out. Each past session is judged as of 8:00 PM Eastern, so a headline published that day is scored for that day.

A headline and a price share a card only when the headline's slice clears the same percent rule. That card calls the headline a candidate reason. A strong headline on a flat slice stays a news card, and the price change is left off. A close that moved, with no headline in the slice that moved, stays a price card that says no headline lined up. Sharing an Eastern day is not that claim.

Alert History fills a blank sector from the same Yahoo profile. A stock uses `sector`. An ETF or mutual fund uses the category of the product it targets (`category`, or the fund overview when the quote profile leaves that blank). A cryptocurrency, and a fund in the Digital Assets category, is labeled Crypto.

The card time is when the condition was met, in US Eastern. During market hours a stock price move uses the time of the check and the change from the open. After 4:00 PM it uses the close. A 24-hour market uses the time the check measured the last 24 hours. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The details title shows the symbol, the alert type, and that time on one line. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Target sources

The revised class target is in [proposal-pipeline-audit.md](proposal-pipeline-audit.md). Live minute bars for the watchlist come from Alpaca or Databento onto Kafka. Headlines are scored with FinBERT and persisted; that store is the news history, because the live feed is not an archive. Historical bars and those headlines land in S3. Spark builds the feature table and fits an Isolation Forest. Flink applies that model. After the alert row exists, Perplexity writes two sentences from the payload, and the deterministic sentence is the fallback.

None of those feeds or jobs are connected. FinBERT does run here, on each headline during a check, from weights stored on this machine. The summary the app shows today is the deterministic sentence.
