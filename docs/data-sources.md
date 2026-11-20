# Data sources

## Sources

| Input | Source | Stored as |
|---|---|---|
| Daily OHLCV (Watchlist Scan today / rebuild) | Yahoo Finance through `yfinance` | `daily_bars` — focus-session product pass (today during/after RTH; last completed session pre-open / weekend) for the focus set (not the training lake) |
| Live / delayed minute bars | Alpaca `delayed_sip` via [`stream_ingest/`](../stream_ingest/) onto local Kafka (`prices.raw.bars`). Free Basic: WebSocket ≤30 symbols; REST fills the rest (demos may run REST-only and **backfill cash-open + latest** from 9:30 ET so SessionBook gets the real open without a full-day flood) | Consumed by `python -m app.live` for the **full S&P 500** (not Watchlist-only): open→last **percent** and Isolation Forest **price** alerts, same-day headline grade, `origin=live`; feature rows in `live_feature_rows`; Home Live alerts (arm switch + heartbeat; Clear uses `updated_at`) |
| Historical daily OHLCV (S&P 500, ~1 year) | Yahoo Finance via automatic first-boot land, [`batch_ingest/`](../batch_ingest/), or Settings → **Land** | Lake Parquet for **Isolation Forest training**: `data/lake/raw/prices/daily/symbol=TICKER/` |
| Incremental lake refresh | Per-symbol resume from latest lake `dt` (lookback capped ~14 calendar days) + `batch_train` when new rows land; skips Yahoo + retrain when already current through the last completed session (pre-open aware — before 4:00 PM Eastern “today” is not required; Kafka bars do not write the lake). Daily auto schedule; Settings → **Refresh lake + retrain** (finished stamp in US Eastern); CLI `--days 14 --merge` | Updated raw lake + new Isolation Forest registry when needed; live reloads on next rules refresh |
| Near-term headlines | Yahoo quote news, then Yahoo Search when quote news is empty | `headlines` |
| Sentiment | Local FinBERT. Score is 0–100 (50 neutral). Confidence is the winning class probability | `headlines.sentiment_score`, plus confidence and class shares on the alert |

FinBERT is the ProsusAI/finbert model, loaded locally with PyTorch. The first use downloads the weights. Later scoring does not call a hosted analysis API. The model returns positive, negative, and neutral probabilities. The score shown in the app is 0 to 100: 50 plus 50 times positive minus negative. Confidence is the winning class probability. A headline joins a news alert when that score is at least 25 points from 50. The alert score is the average of the headlines that clear that gate.

A headline is stored when its title names the ticker or the company's first distinctive name word (Yahoo `shortName`, so `AAPL` also matches "Apple"). Yahoo often tags unrelated market stories with the symbol. Those are not alerts. Class-share tickers are stored in Yahoo form: `BRK.B` becomes `BRK-B`.

**Historical headlines are not pulled into the lake.** News is near-term product logic for the same trading day. Batch training uses price and volume features only.

## Rules that read those tables

| Alert | Rule | Default |
|---|---|---|
| Price | While the market is open, one alert when open→last clears the percent rule **or** the registered Isolation Forest marks the session anomalous (same four features: gap, session, close, volume z-score). Live (`python -m app.live`) and **Watchlist Scan today** share that OR gate, then run a same-day headline check that grades how well the news explains the move (supports, conflicts, or does not explain). Before the open (and on weekends), Scan today evaluates the **last completed session**; after the close it scores that day’s OHLCV with the forest. A volume spike is **noted** on a completed close when volume is at least 2× the recent average — that note alone does not open an alert; unusual volume is mainly the forest’s volume z-score | 3% (percent) / registry cutoff (forest) |
| News | One alert for that trading day when a headline's 0–100 FinBERT score is at least 25 points from 50. Each headline keeps its score, confidence, breakdown, and link. The alert score is the average | 25 points from 50 |
| News + price | One alert when a headline's slice clears the same percent rule. Before 9:30 AM Eastern the slice is the overnight gap. From 9:30 AM to 4:00 PM it is the open-to-latest move, which is the open-to-close move after the market closes. After 4:00 PM it is the close versus the prior close. The words "candidate reason" are used only on this card. A headline whose slice is flat stays news, with the price left blank. A close that moved with no headline in that slice stays a price card — the headline check grades that the news does not explain the move | same rules |

### Percent **or** forest (price gate cases)

| Percent | Forest | Price-led alert? | Card tag |
|---|---|---|---|
| Clears | Normal / absent | **Yes** — percent alone | `(percent only)` |
| Clears | Anomalous | **Yes** — both | `(percent + forest)` |
| Under | Anomalous | **Yes** — forest alone | `(forest only)` |
| Under | Normal / absent | **No** price-led | `(neither gate)` |

### Price-trigger cases (what can fire a price-led row)

| # | Trigger | Opens alert alone? | Notes |
|---|---|---|---|
| 1 | Price move threshold (open→last or close vs prior) | **Yes** | Settings → Price move threshold (default 3%) |
| 2 | Isolation Forest anomalous | **Yes** | Same registry on Live and Scan today |
| 3 | Gap return | No — forest feature | Inside #2 |
| 4 | Session return | No — forest feature | Inside #1 / #2 |
| 5 | Close return | No — forest feature | Inside #2 |
| 6 | Volume z-score | No — forest feature | Unusual volume via the model |
| 7 | Volume spike note (~2× average) | **No** — note only | Annotation on some daily percent cards |

What happened shows both the gate tag and a trigger note such as `[triggers: #1 percent]` or `[triggers: #2 forest (#6 volume z, #3 gap)]`. See [architecture.md](architecture.md) for the same tables next to the Live / Watchlist diagram.

A normal check judges the current Eastern trading day only. Headlines from another day are not pulled in, even if they are newer than 72 hours. The 72-hour bound drops anything older than that. The admin rebuild on the Settings page deletes saved alerts and reruns these rules for each session in the last 1–40 calendar days. For that pass, Yahoo quote news is paged until a story is on or before the first day, or the list runs out. Each past session is judged as of 8:00 PM Eastern, so a headline published that day is scored for that day.

A headline and a price share a card only when the headline's slice clears the same percent rule. That card calls the headline a candidate reason. A strong headline on a flat slice stays a news card, and the price change is left off. A close that moved, with no headline in the slice that moved, stays a price card — the same-day check still ran; it grades that the news does not explain the move. Sharing an Eastern day is not that claim.

Alert History shows **Origin** (`live` / `watchlist` / `both`), **Company**, **Type**, **Price change**, and **Sentiment score** (sortable). **Both** means Live and Watchlist Scan today each wrote that symbol on the same `bar_date` (one row; origins merge). Expanded cards show Price change with `$from → $to` and a short span caption, and Sentiment score with FinBERT positive / negative / neutral headline counts.

The card time is when the condition was met, in US Eastern. During market hours a stock price move uses the time of the check and the change from the open. After 4:00 PM it uses the close. News uses the earliest qualifying headline from that trading day. When both fire, the time is the later of those two. The details title shows the symbol, the alert type, and that time on one line. The symbol on a card, in the history table, and in the details title links to `https://finance.yahoo.com/quote/{symbol}`.

## Class sources and lake

**S&P 500 Radar** system diagrams are in [architecture.md](architecture.md). Planned → landed decisions (and why we dropped AWS prod, Cassandra, a news lake, etc.) are in [proposal-pipeline-audit.md](proposal-pipeline-audit.md). The finished product path is **local** (Docker Kafka, Postgres, `data/lake`); the optional class deploy on branch `aws-deployment` is documented in [aws-deployment.md](aws-deployment.md) (EC2 Compose, S3 durable lake, CloudWatch, Elastic IP). Live / delayed minute bars come from Alpaca onto Kafka via [`stream_ingest/`](../stream_ingest/). On the free Basic plan the WebSocket covers 30 symbols (`delayed_sip`); the rest of the S&P 500 is filled by delayed SIP REST minute bars onto the same topic (REST-only demos backfill cash-open + latest). Paid Algo Trader Plus lifts the WebSocket cap. `python -m app.live` scores the **full S&P 500** Kafka stream (not only Watchlist chips), writes open→last **percent-rule** and Isolation Forest price alerts, then runs a same-day headline check that grades how well the news explains the session, keeps `origin=live` through that upgrade, sinks rows to `live_feature_rows`, and heartbeats on a background task so Home can show **Live alerts on** while news scoring runs. The Home cue is an arm switch (`live_alerts_armed`). **Watchlist Scan today** refreshes Yahoo daily bars and FinBERT headlines for the focus set, scores the same Isolation Forest registry as live (percent **or** forest), and shows results on the Watchlist tab. The product path is **price first, then headline grade** on both Live and Scan today. Historical **prices** for the index land in the lake as daily Parquet for **training only**. Settings **Refresh lake + retrain** targets the last completed session; Kafka minute bars do not write the lake. `batch_train` builds gap, session, close, and volume z-score features and fits an Isolation Forest into the local registry (Spark role on the diagram). After a news or news+price alert exists, Perplexity writes richer short reasoning from the payload; price-only keeps the rule sentence, and the deterministic sentence is the fallback when the call fails. Article URLs in that reply become clickable headline titles in Summary. The open dashboard tab can raise a Mac/Chrome desktop notification and a title/favicon badge when Scan today or live writes new rows (plain HTTP public IPs may block Notification permission). Slack and email are not used.

When a Perplexity key is saved in Settings, that call rewrites news and news + price cards. A check sends one JSON payload for those alerts: the price change when present, the headlines (with urls), and the FinBERT score, confidence, and class shares. The model is asked to cite headlines by title rather than paste raw https URLs. The model dropdown has five ChatGPT models, five OpenAI models, and five Gemini models. Perplexity writes three to four short sentences with the selected model. Price-only alerts stay deterministic (Isolation Forest rows get richer forest-aware wording without Perplexity). The key field shows dots when a key is saved. Together ends with the name of the model that wrote it. A check sends the alerts in batches of eight. The deterministic sentence remains when no key is saved or the call fails. Rule stays under Rule when the reply replaces Together.
