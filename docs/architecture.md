# Ticker Alert System architecture

Local decision-support service that turns a watchlist into one alert per symbol per day: a price move, a news-sentiment alert, or a news + price alert when both rules fire.

The class design (CISC 525) is a lambda architecture: Kafka and Flink on the live path, Spark and a data lake on the historical path, FinBERT for sentiment, an Isolation Forest trained on that lake, and Perplexity for the alert wording. The revised plan is [proposal-pipeline-audit.md](proposal-pipeline-audit.md). This repository already runs part of the stream: Alpaca delayed SIP minute bars onto Kafka (`stream_ingest/`), and a FastAPI consumer (`python -m app.live`) that writes open→last **price** alerts for the watchlist. A normal **Run check** still uses Yahoo daily bars, local FinBERT on headlines, and a Perplexity summary when a key is saved. Flink, Spark, the lake, and Isolation Forest remain the class target.

There is no shared package with Vajra Astra Capital. Common logic lives in this repo as its own copy.

## Status

| Capability | Status |
|---|---|
| Watchlist of tickers, with a local symbol and company-name search. A suggestion fills the box. Add rejects a symbol that is not on that list and that Yahoo does not quote | **As-built** |
| Yahoo daily bars into `daily_bars` | **As-built** |
| Yahoo headlines scored with local FinBERT on a 0–100 scale, with confidence and a class breakdown | **As-built** |
| Price alert: while the market is open, the latest price versus the open; after the close, the close versus the prior close; the last 24 hours for a market that trades all day. A volume-spike flag is on the completed stock close | **As-built** |
| News alert: absolute sentiment at or beyond the configured threshold, on that headline's trading day | **As-built** |
| News plus price only when the headline's price slice clears the same percent rule. Otherwise news with no price, or price with no headline lined up | **As-built** |
| Plain-English summary from the alert fields, including the thresholds in force when it fired | **As-built** |
| Home inbox of alerts since the app was last opened, plus a sortable alert history | **As-built** |
| Saved price and sentiment thresholds | **As-built** |
| Admin rebuild: wipe alerts and rerun the current rules over the last 1–40 calendar days | **As-built** |
| Symbol links to the Yahoo Finance quote, from Home, History, and the details title | **As-built** |
| Minute bars on Kafka from Alpaca `delayed_sip` (WebSocket ≤30 on free Basic; REST fills the rest of the S&P 500). See `stream_ingest/` and `docker-compose.yml` | **As-built** (producer) |
| Live Kafka consumer: open → last price alerts into Postgres for the watchlist (`python -m app.live`). News stays on Run check | **As-built** (session-move only; Isolation Forest still target) |
| Home “Live alerts on” cue from the consumer heartbeat (`/v1/live/status`) | **As-built** |
| Flink session features scored with the registered Isolation Forest | **Target** |
| FinBERT inference on each headline, locally, during a check | **As-built**. Not a live score stream |
| Spark feature table on S3, Isolation Forest fit on that table, model registry | **Target** |
| Correlation on the price slice (gap, session, or close), including news-only and price-only | **Target** |
| Perplexity two-sentence summary, with the deterministic sentence as fallback | **As-built** when a key is saved |
| Slack or email notification | **Target** |

A normal check writes only the current Eastern trading day. The admin rebuild is the historical pass we can run now: it deletes saved alerts and reapplies the current rules to each session in the chosen window. It is not the proposal's training lake. Yahoo's quote-news list is newest first and can run out before the first day of a long window, especially for a busy ticker. A rebuild pages that list back through the window and scores each story for the trading day it was published. Sessions with no remaining headline stay price-only.

## Proposal audit

The class deck (CISC 525, 30 Aug 2026) asks for batch processing and stream processing in a big-data architecture, plus machine learning and an AI summary. [proposal-pipeline-audit.md](proposal-pipeline-audit.md) is the revised plan. The mermaid diagrams below are that revised target. The original deck still had Cassandra, a FinBERT fine-tune, VWAP as a stream stage, and a generic LLM box. Those are gone here. The audit tables still list every keep, change, and drop.

The revised target keeps both engines and one feature list. Spark lands historical bars and stored headlines in S3, builds one feature row per symbol per session, and fits an Isolation Forest. The registry holds that model, the feature list, and the score cutoff. Flink scores the same vector on live minute bars from Kafka and writes feature rows to TimescaleDB. FinBERT scores headlines on the stream. Correlation joins a headline to the slice in progress and still allows news-only and price-only. Perplexity writes two sentences from the finished payload. The deterministic sentence remains the fallback. Postgres is the alert of record. Cassandra is not part of the target.

### What this repository does instead

| Revised target | This app |
|---|---|
| Minute bars on Kafka, scored by the registered forest | Minute bars land on Kafka from Alpaca. `python -m app.live` applies the open→last percent rule during the cash session and writes a **price** row. Run check still measures open→last (or close versus prior close after the close, or 24 hours for `-USD`). Isolation Forest scoring on those bars is not built yet |
| FinBERT score stream | FinBERT on each headline during a check. The weights run on this machine. There is no score stream and no second scorer |
| Slice join, with news-only and price-only | Same Eastern trading day, then one slice: the overnight gap before 9:30 AM, the regular session until 4:00 PM, or the close after that. A 24-hour market uses the four hours after the headline. Fusion says "candidate reason" only when that slice clears the price rule. Otherwise the card is news with no price, or price with no headline lined up. Weekend stories stay with Friday |
| Perplexity, two sentences, after the decision | Perplexity when a key is saved, using the model chosen in Settings. The model name is shown under Together. Otherwise deterministic sentences, plus the thresholds saved on the alert |
| S3 lake, Spark training, model registry | Admin rebuild of the last 1–40 calendar days from Yahoo bars and stored headlines. Current settings are applied again, and previous alerts are deleted |
| One alert per symbol per day | One row per symbol per day |

The rebuild is the closest thing we have to the historical path. It replays rules. It does not train a model or tune a threshold.

## As-built check

What a **Run check** or rebuild runs today. Isolation Forest, Flink, and Spark are not on this path. The live Kafka price path is the next diagram.

```mermaid
flowchart TB
    subgraph ingest [Ingestion]
        WL[Watchlist] --> RUN[Run check or rebuild]
        RUN --> PX[Yahoo daily bars]
        RUN --> NW[Yahoo headlines]
        PX --> BARS[(daily_bars)]
        NW --> SCORE[Local FinBERT, 0 to 100]
        SCORE --> NEWS[(headlines)]
    end

    subgraph rules [Alert rules]
        BARS --> PRICE{Latest versus the open while the market is open, otherwise the close versus the prior close, or the last 24 hours}
        PRICE -->|at or beyond threshold| PA[Price alert]
        PRICE --> VOL[Volume versus recent average]
        VOL --> PA
        NEWS --> NA{Score at least 25 points from 50}
        NA -->|at or beyond threshold| NEWSALERT[News alert]
        PA --> ONE{Headline slice clears the same percent}
        NEWSALERT --> ONE
        ONE -->|yes| FA[News plus price alert]
        ONE -->|price only| PA
        ONE -->|news only| NEWSALERT
    end

    subgraph out [Output]
        PA --> RULE[Deterministic summary]
        NEWSALERT --> RULE
        FA --> RULE
        RULE --> KEY{Perplexity key saved}
        KEY -->|no or call failed| ALERTS[(alerts)]
        KEY -->|yes, batches of eight| PPLX[Perplexity two sentences]
        PPLX --> ALERTS
        ALERTS --> UI[Home, History, Details]
        PPLX -.->|model name under Together| UI
        RULE -.->|Rule section when replaced| UI
    end
```

## As-built live price stream

What runs when Docker Kafka, the Alpaca producer, and `python -m app.live` are up. This writes **price** alerts only. News and news_price still come from Run check. The Home pill reads `/v1/live/status`.

```mermaid
flowchart LR
    subgraph sources [Sources]
        ALP[Alpaca delayed_sip]
        WL2[Watchlist in Postgres]
    end

    subgraph bus [Local Kafka]
        PROD[stream_ingest producer]
        TOPIC[prices.raw.bars]
        LIVE[python -m app.live]
    end

    subgraph decide [Session move]
        BOOK[Open and latest from RTH bars]
        RULE2{Move at or beyond saved percent}
    end

    subgraph out2 [Output]
        PG[(Postgres alerts)]
        BEAT[live_consumer_heartbeat_at]
        API[GET /v1/live/status]
        UI2[Home Live alerts on]
    end

    ALP --> PROD --> TOPIC --> LIVE
    WL2 --> LIVE
    LIVE --> BOOK --> RULE2
    RULE2 -->|yes, and day is still price-only| PG
    LIVE --> BEAT --> API --> UI2
    PG --> UI2
```

```mermaid
sequenceDiagram
    participant Alpaca
    participant Producer as stream_ingest
    participant Kafka
    participant Live as app.live
    participant PG as Postgres
    participant UI as Home

    Alpaca->>Producer: Minute bar delayed_sip
    Producer->>Kafka: prices.raw.bars
    Live->>Kafka: Consume bar
    Live->>Live: Update open and latest for RTH
    Live->>PG: Heartbeat for Live alerts on
    alt Open to last clears threshold
        Live->>PG: Upsert price alert for today
        UI->>PG: Poll alerts
        PG->>UI: Price card
    else Below threshold or news row exists
        Live-->>PG: No price overwrite
    end
    UI->>PG: GET /v1/live/status
    PG->>UI: enabled when heartbeat is fresh
```

## Revised target: high-level lambda architecture

Streaming path for live detection. Batch path for training. This repository already runs Kafka minute bars and the open→last consumer. FinBERT on a check and Perplexity when a key is saved also run today. Flink, Spark, the lake, and Isolation Forest do not.

```mermaid
flowchart LR
    subgraph sources [Data sources]
        BARS_LIVE[Minute bars for the watchlist]
        LIVE_NEWS[News and headlines API]
        HIST_PX[Historical OHLCV]
        HIST_NEWS[Persisted scored headlines]
    end

    subgraph ingest [Ingestion]
        KAFKA[Kafka]
        BATCH[Batch land into the lake]
    end

    subgraph process [Processing]
        FLINK[Flink session features]
        SPARK[Spark ELT and training]
    end

    subgraph storage [Storage]
        RAW[S3 raw zone]
        TS[(TimescaleDB feature rows)]
        CURATED[S3 curated Parquet]
        ALERTS[(Postgres alerts)]
    end

    subgraph model [Model plane]
        TRAIN[Isolation Forest training]
        REG[(Model registry)]
    end

    subgraph detect [Detection]
        SENT[FinBERT 0 to 100]
        ANOM[Registered Isolation Forest]
        CORR[Slice correlation]
        PPLX[Perplexity two sentences]
    end

    subgraph serve [Serving]
        API[Alert API and dashboard]
        NOTE[Slack or email]
    end

    BARS_LIVE --> KAFKA --> FLINK --> TS
    LIVE_NEWS --> KAFKA
    HIST_PX --> BATCH --> RAW
    HIST_NEWS --> BATCH
    RAW --> SPARK --> CURATED
    CURATED --> TRAIN --> REG
    REG --> ANOM
    FLINK --> ANOM
    KAFKA --> SENT
    SENT --> CORR
    ANOM --> CORR
    CORR --> ALERTS
    ALERTS --> PPLX
    PPLX --> API --> NOTE
    ALERTS --> API
```

## Revised target: batch historical ELT

Land raw history, then build the feature table and fit the forest. FinBERT is not fine-tuned here.

```mermaid
flowchart LR
    HP[Historical price bars] --> ELP[Land raw]
    HN[Persisted scored headlines] --> ELN[Land raw]
    ELP --> RAW[(S3 raw zone)]
    ELN --> RAW
    RAW --> VAL[Schema check and dedup]
    VAL --> SPARK[Spark]
    SPARK --> FEAT[Feature rows: gap, session, close, volume z-score, FinBERT aggregates]
    FEAT --> CUR[(S3 curated Parquet)]
    CUR --> TRAIN[Fit Isolation Forest and pick the cutoff]
    TRAIN --> REG[(Model registry)]
    REG -.-> FLINK[Flink loads the same model]
    CUR --> PG[(Postgres alert and reporting tables)]
    PG --> UI[Alert history dashboard]
```

## Revised target: streaming ETL

Minute bars and headlines on Kafka. Flink scores the live vector with the registered forest. Postgres holds the alert. Perplexity writes after the row exists.

```mermaid
flowchart TD
    MKT[Minute bars for the watchlist] --> KT[Kafka raw bars]
    KT --> FLINK[Flink: session returns and volume z-score]
    FLINK --> GATE{Registered forest cutoff}
    FLINK --> LOADT[Load]
    LOADT --> TIMESCALE[(TimescaleDB feature rows)]
    GATE -->|score crosses cutoff| CORR[Slice correlation]

    NEWS[News headline feed] --> KN[Kafka raw news]
    KN --> FINBERT[FinBERT 0 to 100]
    FINBERT --> SCORES[Kafka sentiment scores]
    SCORES --> CORR

    CORR --> PG[(Postgres alerts)]
    PG --> PPLX[Perplexity two sentences]
    PPLX --> DASH[Trader alert dashboard]
    PG --> DASH
    PG --> NOTIFY[Slack or email]
```

## Revised target: end-to-end alert sequence

Price-only and news-only are allowed. Perplexity never decides the alert.

```mermaid
sequenceDiagram
    participant Market as Minute bars
    participant Kafka
    participant Flink
    participant Registry as Model registry
    participant FinBERT
    participant Corr as Slice correlation
    participant PG as Postgres
    participant Pplx as Perplexity
    participant Trader

    Market->>Kafka: Stream minute bar
    Kafka->>Flink: Consume bar batch
    Flink->>Flink: Build gap, session, close, volume z-score
    Registry->>Flink: Load Isolation Forest and cutoff
    Flink->>Corr: Anomaly score when the cutoff trips
    Kafka->>FinBERT: Consume news headline
    FinBERT->>Corr: Sentiment score 0 to 100
    Corr->>Corr: Join on symbol and slice, or keep one side alone
    Corr->>PG: Store alert row
    PG->>Pplx: Structured payload
    alt Key saved and call succeeds
        Pplx->>Trader: Two-sentence summary
    else No key or call failed
        PG->>Trader: Deterministic summary
    end
```

## Local schema

`watchlist` holds the symbols a check will refresh. `symbols` caches the history label: a Yahoo sector for a stock, the fund category for an ETF or mutual fund, and Crypto for a coin or a digital-asset fund. `daily_bars` and `headlines` are the inputs. `app_settings` stores the price fraction, the FinBERT sentiment threshold, the optional Perplexity API key, the selected Perplexity model, and `live_consumer_heartbeat_at` for the Home live cue. The default threshold is 25 points from 50. The default model is `openai/gpt-5.4-mini`. `alerts.kind` is `price`, `news`, or `news_price`.

One row per symbol per `bar_date`. A repeated check replaces that day's alert and keeps `created_at`. The row also stores `price_move_threshold` and `sentiment_threshold` from the moment it fired. When Perplexity rewrites Together, the alert `sections` keep the rule sentence, the model id, and the model label shown under Together. A headline is eligible only when it was published on that Eastern trading day and is inside the news lookback.

`sentiment_scorer` stays `finbert`. FinBERT loads ProsusAI/finbert on this machine. The stored score is 0 to 100, with 50 neutral. Confidence is the winning class probability. A headline is eligible when the score is at least the saved number of points from 50.
