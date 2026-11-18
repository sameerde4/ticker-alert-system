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
| Price | One alert for the day when a stock close clears the move rule versus the prior close. A 24-hour market such as BTC-USD uses the price change over the 24 hours before the check. A volume spike is noted for stocks when volume is at least 2× the recent average | 3% |
| News | One alert for that trading day when a headline's 0–100 FinBERT score is at least 25 points from 50. Each headline keeps its score, confidence, breakdown, and link. The alert score is the average | 25 points from 50 |
| News + price | One alert for that trading day when the close and the same day's headlines both clear their rules | same rules |

A live check measures a symbol ending in `-USD`, such as BTC-USD, from hourly Yahoo prices: the latest price at the moment of the check, and the price 24 hours earlier. Those hourly prints are not saved as daily bars. Rebuild history still replays daily closes, so it does not reconstruct that rolling window.

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound still drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days.

The card time is when the condition was met, in US Eastern. A stock price move uses the 4:00 PM close because the feed is a daily bar. A 24-hour market uses the time the check measured the last 24 hours. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Target sources

The class design adds a live tick websocket (Alpaca or Databento), a newswire, historical OHLCV and labeled headlines in object storage, and an Isolation Forest trained on the curated lake. Those feeds are not connected. FinBERT itself does run here, on each headline during a check, from weights stored on this machine. The class deck’s FinBERT was a live score stream, which this slice does not have.
