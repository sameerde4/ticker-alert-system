# Data sources

## As-built

| Input | Source | Stored as |
|---|---|---|
| Daily OHLCV | Yahoo Finance through `yfinance` | `daily_bars` |
| Headlines | Yahoo quote news, then Yahoo Search when quote news is empty | `headlines` |
| Sentiment | The selected scorer, score in [-1, 1]. FinBERT is the default. Custom scoring is the keyword lexicon | `headlines.sentiment_score` |

FinBERT is the ProsusAI/finbert model, loaded locally with PyTorch. The first use downloads the weights. Later scoring does not call a hosted analysis API. The model returns positive, negative, and neutral probabilities. The stored score is positive minus negative. Custom scoring is a local copy of the weighted lexicon used for company-news scoring in Vajra Astra. A negation in the previous three tokens flips a matched word, and the score is damped by `hits / 3`. A check uses one scorer for every headline and never averages the two. This repo does not import Vajra Astra.

A single mild keyword caps near ±0.33 because the score is scaled by `hits / 3`. The default news threshold is 0.34, so one mild word does not open an alert. A strong word such as "plunge" does.

A headline is stored when its title names the ticker or the company's first distinctive name word (Yahoo `shortName`, so `AAPL` also matches "Apple"). Yahoo often tags unrelated market stories with the symbol. Those are not alerts. Class-share tickers are stored in Yahoo form: `BRK.B` becomes `BRK-B`.

## Rules that read those tables

| Alert | Rule | Default |
|---|---|---|
| Price | One alert for the day when only the close clears the move rule. A volume spike is noted when volume is at least 2× the recent average | 3% |
| News | One alert for that trading day when headlines published that day clear the threshold. Each headline keeps its score and link. The alert score is the average | 0.34 |
| News + price | One alert for that trading day when the close and the same day's headlines both clear their rules | same rules |

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound still drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days.

The card time is when the condition was met, in US Eastern. A price move uses the 4:00 PM close because the feed is a daily bar. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Target sources

The class design adds a live tick websocket (Alpaca or Databento), a newswire, historical OHLCV and labeled headlines in object storage, and an Isolation Forest trained on the curated lake. Those feeds are not connected. FinBERT itself does run here, on each headline during a check, from weights stored on this machine. The class deck’s FinBERT was a live score stream, which this slice does not have.
