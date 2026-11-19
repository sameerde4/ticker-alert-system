# S&P 500 Alert System architecture

Local decision-support service for the **S&P 500**. A watchlist of index constituents becomes one alert per symbol per day: a price move, a news-sentiment alert, or a news + price alert when both rules fire.

The class design (CISC 525) is a lambda architecture: Kafka and Flink on the live path, Spark and a data lake on the historical **price** path, FinBERT for near-term headline sentiment, an Isolation Forest trained on lake price/volume features, and Perplexity for the alert wording. The plan is [proposal-pipeline-audit.md](proposal-pipeline-audit.md).

This repository runs:

- Alpaca delayed SIP minute bars onto Kafka (`stream_ingest/`)
- A FastAPI consumer (`python -m app.live`) that writes open→last **price** alerts for the watchlist
- Yahoo daily bars and FinBERT headlines on **Run check** (near-term news only)
- A Perplexity summary when a key is saved
- A batch land of about one year of S&P daily prices into the lake (`batch_ingest/` or Settings → Historical prices)

Flink scoring and Isolation Forest training complete the class stack on that lake and Kafka path. **Historical headlines are not landed and are not training features.** News stays on the near-term check (and, in the class stream diagram, a live headline topic). There is no shared package with Vajra Astra Capital.

## Status

| Capability | Status |
|---|---|
| Watchlist of S&P 500 constituents (focus set for Run check, rebuild, and live price alerts), with ticker and company-name search. Add accepts index constituents only | **As-built** |
| Yahoo daily bars into `daily_bars` for a check | **As-built** |
| Near-term Yahoo headlines scored with local FinBERT (0–100), with confidence and class shares | **As-built** |
| Price alert: open→last while the market is open; close versus prior close after the close. Volume spike note on the completed close | **As-built** |
| News alert and news + price when the headline’s price slice clears the same percent | **As-built** |
| Plain-English summary; Perplexity two sentences when a key is saved | **As-built** |
| Home inbox, Alert History, saved thresholds, admin rebuild of recent sessions | **As-built** |
| Minute bars on Kafka from Alpaca `delayed_sip` (WebSocket ≤30 on Basic; REST fills the rest of the S&P 500) | **As-built** |
| Live Kafka consumer: open→last price alerts (`python -m app.live`); Home “Live alerts on” heartbeat | **As-built** |
| Historical Yahoo daily bars for the S&P 500 (~1 year) in the lake raw zone | **As-built** |
| Spark curated feature table (gap, session, close, volume z-score) and Isolation Forest registry | **Target** |
| Flink scores the registered forest on live session features; Timescale feature sink | **Target** |
| Near-term headline topic on Kafka with FinBERT scores for live slice join | **Target** |
| Slack or email after the alert row exists | **Target** |

Dropped from both the running design and the class target: Cassandra, FinBERT fine-tuning, VWAP as a stream stage, a generic LLM box, a historical news lake, and sentiment features inside Isolation Forest training.

A normal check writes the current Eastern trading day. The admin rebuild deletes saved alerts and reapplies rules over the last 1–40 calendar days for the watchlist. It is not the training lake. Model training reads lake Parquet, not the rebuild.

## Proposal audit

[proposal-pipeline-audit.md](proposal-pipeline-audit.md) is the revised plan. The mermaid diagrams below are that target. Cassandra, FinBERT fine-tune, VWAP, and a generic LLM box are gone. Historical news is not part of the batch lake.

Spark lands **historical S&P daily prices** in the lake, builds one price/volume feature row per symbol per session, and fits an Isolation Forest. The registry holds that model, the feature list, and the score cutoff. Flink scores the same vector on live minute bars from Kafka and writes feature rows to TimescaleDB. FinBERT scores **near-term** headlines (check today; live news topic on the class stream). Correlation joins a headline to the slice in progress and allows news-only and price-only. Perplexity writes two sentences after the row exists. Postgres is the alert of record.

### What this repository does

| Class target | This app |
|---|---|
| Minute bars on Kafka, scored by the registered forest | Minute bars on Kafka from Alpaca. `python -m app.live` applies the open→last percent rule and writes a **price** row. Forest scoring uses the same lake features once the model is registered |
| FinBERT on near-term headlines | FinBERT on each headline during a check. Weights on this machine. No historical news land |
| Slice join, news-only and price-only | Same Eastern day; gap, session, or close slice. Fusion only when that slice clears the price rule |
| Perplexity after the decision | When a key is saved; model name under Together; deterministic fallback |
| Lake, Spark training, registry | Raw daily prices under `data/lake/raw/` via `batch_ingest` or Settings. Curated features and forest training read that lake. Headlines are not in the batch land |
| One alert per symbol per day | One row per symbol per day |

## As-built check

**Run check** or rebuild. Live Kafka price path is the next diagram.

```mermaid
flowchart TB
    subgraph ingest [Ingestion]
        WL[S&P 500 watchlist] --> RUN[Run check or rebuild]
        RUN --> PX[Yahoo daily bars]
        RUN --> NW[Near-term Yahoo headlines]
        PX --> BARS[(daily_bars)]
        NW --> SCORE[Local FinBERT, 0 to 100]
        SCORE --> NEWS[(headlines)]
    end

    subgraph rules [Alert rules]
        BARS --> PRICE{Open to last while open, else close versus prior close}
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

Docker Kafka, Alpaca producer, and `python -m app.live`. Writes **price** alerts. News comes from Run check. Home reads `/v1/live/status`.

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
    RULE2 -->|yes, and day is price-only| PG
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

## As-built batch lake land

S&P 500 daily prices only. No historical headlines.

```mermaid
flowchart LR
    SP[S&P 500 symbol list] --> YF[Yahoo daily OHLCV ~1 year]
    YF --> LAND[batch_ingest or Settings land]
    LAND --> RAW[data/lake/raw/prices/daily]
    LAND --> MAN[raw/_runs manifest]
    RAW -.-> CURATE[Curated features Target]
    CURATE -.-> TRAIN[Isolation Forest Target]
```

## Revised target: high-level lambda architecture

Batch trains on **price history**. Stream applies that model and scores **near-term** news. No historical news lake.

```mermaid
flowchart LR
    subgraph sources [Data sources]
        BARS_LIVE[S&P minute bars]
        LIVE_NEWS[Near-term headlines]
        HIST_PX[Historical daily OHLCV]
    end

    subgraph ingest [Ingestion]
        KAFKA[Kafka]
        BATCH[Batch land prices into the lake]
    end

    subgraph process [Processing]
        FLINK[Flink session features]
        SPARK[Spark ELT and training]
    end

    subgraph storage [Storage]
        RAW[S3 or data/lake raw prices]
        TS[(TimescaleDB feature rows)]
        CURATED[Curated Parquet features]
        ALERTS[(Postgres alerts)]
    end

    subgraph model [Model plane]
        TRAIN[Isolation Forest training]
        REG[(Model registry)]
    end

    subgraph detect [Detection]
        SENT[FinBERT 0 to 100 near-term]
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

Land raw **prices**, build price/volume features, fit the forest. FinBERT is not fine-tuned and is not a batch input.

```mermaid
flowchart LR
    HP[Historical S&P daily bars] --> ELP[Land raw]
    ELP --> RAW[(Lake raw zone)]
    RAW --> VAL[Schema check and dedup]
    VAL --> SPARK[Spark]
    SPARK --> FEAT[Feature rows: gap, session, close, volume z-score]
    FEAT --> CUR[(Curated Parquet)]
    CUR --> TRAIN[Fit Isolation Forest and pick the cutoff]
    TRAIN --> REG[(Model registry)]
    REG -.-> FLINK[Flink loads the same model]
    CUR --> PG[(Postgres alert and reporting tables)]
    PG --> UI[Alert history dashboard]
```

## Revised target: streaming ETL

Minute bars scored by the registered forest. Near-term headlines scored by FinBERT. Postgres holds the alert. Perplexity writes after the row exists.

```mermaid
flowchart TD
    MKT[S&P minute bars] --> KT[Kafka raw bars]
    KT --> FLINK[Flink: session returns and volume z-score]
    FLINK --> GATE{Registered forest cutoff}
    FLINK --> LOADT[Load]
    LOADT --> TIMESCALE[(TimescaleDB feature rows)]
    GATE -->|score crosses cutoff| CORR[Slice correlation]

    NEWS[Near-term headline feed] --> KN[Kafka raw news]
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

Price-only and news-only are allowed. Perplexity never decides the alert. The forest features are price and volume only.

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
    Kafka->>FinBERT: Consume near-term headline
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

`watchlist` holds S&P 500 symbols a check will refresh. `symbols` caches the Yahoo sector or fund category. `daily_bars` and `headlines` are check inputs (near-term headlines only). `app_settings` stores the price fraction, the FinBERT sentiment threshold, the optional Perplexity API key, the selected Perplexity model, and `live_consumer_heartbeat_at` for the Home live cue. The default threshold is 25 points from 50. The default model is `openai/gpt-5.4-mini`. `alerts.kind` is `price`, `news`, or `news_price`.

One row per symbol per `bar_date`. A repeated check replaces that day's alert and keeps `created_at`. The row also stores `price_move_threshold` and `sentiment_threshold` from the moment it fired. When Perplexity rewrites Together, the alert `sections` keep the rule sentence, the model id, and the model label shown under Together. A headline is eligible only when it was published on that Eastern trading day and is inside the news lookback.

`sentiment_scorer` stays `finbert`. FinBERT loads ProsusAI/finbert on this machine. The stored score is 0 to 100, with 50 neutral. Confidence is the winning class probability. A headline is eligible when the score is at least the saved number of points from 50.

The lake under `data/lake/raw/prices/daily/` holds historical daily OHLCV for training. It is separate from Postgres alerts.
