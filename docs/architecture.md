# S&P 500 Alert System architecture

Local decision-support service for the **S&P 500**. A watchlist of index constituents becomes one alert per symbol per day: a price move, a news-sentiment alert, or a news + price alert when both rules fire.

The class design (CISC 525) is a **local** lambda architecture: Docker Kafka on the live path, a batch lake on disk, a Spark-**role** training job, FinBERT for near-term headline sentiment, an Isolation Forest trained on lake price/volume features, and Perplexity for the alert wording. The plan is [proposal-pipeline-audit.md](proposal-pipeline-audit.md).

**Deploy target:** one developer machine (Docker Desktop + Postgres + local lake). Cloud names from the original deck (S3, Aurora, managed Flink) map to local stand-ins below. This project does **not** require an AWS production deploy for the class demo.

This repository runs today:

- Alpaca delayed SIP minute bars onto local Kafka (`stream_ingest/`)
- A FastAPI consumer (`python -m app.live`) that writes open→last **price** alerts for the watchlist (percent rule)
- Yahoo daily bars and FinBERT headlines on **Run check** (near-term news only)
- A Perplexity summary when a key is saved
- Batch land of about one year of S&P daily prices into `data/lake/raw/` (`batch_ingest/` or Settings)
- Curated session features + Isolation Forest registry (`batch_train/`)
- Mac/Chrome desktop notifications and a tab badge when new alerts arrive

Still open for the **local final** stack: score live Kafka sessions with the registered forest (Flink **role**), optional Timescale/Postgres feature-row sink, and a near-term news topic on Kafka. **Historical headlines are not landed and are not training features.** There is no shared package with Vajra Astra Capital.

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
| Spark-role curated feature table (gap, session, close, volume z-score) and Isolation Forest registry via `batch_train` (local pandas/scikit-learn) | **As-built** |
| Mac/Chrome desktop notification (Notification Center) plus tab title/favicon badge when new alerts arrive from Run check or live | **As-built** |
| Live scorer loads the registry and scores session features from Kafka bars (Flink role); feature-row sink | **Local final target** |
| Near-term headline topic on Kafka with FinBERT scores for live slice join | **Local final target** |

Dropped from both the running design and the local final target: Cassandra, FinBERT fine-tuning, VWAP as a stream stage, a generic LLM box, a historical news lake, sentiment features inside Isolation Forest training, and a mandatory AWS production deploy.

A normal check writes the current Eastern trading day. The admin rebuild deletes saved alerts and reapplies rules over the last 1–40 calendar days for the watchlist. It is not the training lake. Model training reads lake Parquet, not the rebuild.

## Proposal audit

[proposal-pipeline-audit.md](proposal-pipeline-audit.md) is the revised plan. Diagrams below separate **as-built** (running now) from **local final target** (still to wire on this machine). Cassandra, FinBERT fine-tune, VWAP, and a generic LLM box are gone. Historical news is not part of the batch lake. S3/Aurora on older slides mean `data/lake` and local Postgres.

### What this repository does

| Local final target | This app today |
|---|---|
| Minute bars on Kafka, scored by the registered forest | Minute bars on Kafka from Alpaca. `python -m app.live` applies the open→last **percent** rule. Forest scoring from the registry is the remaining live gap |
| FinBERT on near-term headlines | FinBERT on each headline during a check. Weights on this machine. No historical news land |
| Slice join, news-only and price-only | Same Eastern day; gap, session, or close slice. Fusion only when that slice clears the price rule |
| Perplexity after the decision | When a key is saved; model name under Together; deterministic fallback |
| Lake, Spark-role training, registry | Raw under `data/lake/raw/` via `batch_ingest`. `batch_train` writes curated features and `data/lake/registry/isolation_forest/current/` |
| One alert per symbol per day | One row per symbol per day |
| Notify the trader after the row exists | OS desktop notification + tab badge (`ui/sw-notifications.js`). Slack and email are not used |

### Local stand-ins (no AWS required)

| Original deck / cloud name | Local stand-in in this repo |
|---|---|
| S3 data lake | `data/lake/` Parquet on disk |
| Aurora / RDS | Local Postgres `ticker_alert_db` |
| Managed Kafka | Docker Compose Kafka |
| Spark cluster (EMR / Dataproc) | `batch_train` Spark-**role** job (pandas ELT + scikit-learn Isolation Forest) |
| Flink on Kinesis/MSK | Local Flink-**role** live scorer (next): same four features + registry cutoff |
| Timescale (managed) | Local Timescale in Docker, or a Postgres feature-row table |
| Slack / email | Mac/Chrome desktop notification + tab badge |

## As-built: system overview

Everything that runs on one machine today. Live price alerts still use the **percent rule**; the forest is trained but not yet applied on the Kafka path.

```mermaid
flowchart TB
    subgraph batch [Batch path as-built]
        YF[Yahoo daily OHLCV] --> LAND[batch_ingest / Settings land]
        LAND --> RAW[(data/lake/raw/prices/daily)]
        RAW --> BT[batch_train pandas ELT]
        BT --> CUR[(curated/features/session)]
        CUR --> IF[Isolation Forest scikit-learn]
        IF --> REG[(registry/isolation_forest/current)]
    end

    subgraph stream [Live path as-built]
        ALP[Alpaca delayed_sip] --> PROD[stream_ingest]
        PROD --> KAFKA[(Docker Kafka prices.raw.bars)]
        KAFKA --> LIVE[python -m app.live]
        LIVE -->|open to last percent rule| PG[(Postgres alerts)]
    end

    subgraph check [Run check as-built]
        WL[Watchlist] --> RUN[Run check]
        RUN --> YB[Yahoo bars + headlines]
        YB --> FB[Local FinBERT]
        FB --> PG
        RUN -->|percent + news rules| PG
    end

    subgraph serve [Serving as-built]
        PG --> API[FastAPI + UI]
        API --> NOTE[Desktop notification and tab badge]
        REG -.->|not scored live yet| LIVE
    end
```

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
        UI --> NOTE[Desktop notification and tab badge]
        PPLX -.->|model name under Together| UI
        RULE -.->|Rule section when replaced| UI
    end
```

Home asks for notification permission (Enable desktop notifications). When Run check or a live refresh adds alert rows, the open tab raises a Mac/Chrome Notification Center popup and sets `(N)` on the title with a favicon badge. Opening Home clears the unread count. Slack and email are not used.

## As-built live price stream

Docker Kafka, Alpaca producer, and `python -m app.live`. Writes **price** alerts with the **percent rule**. News comes from Run check. Home reads `/v1/live/status`.

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
        NOTE2[Desktop notification and tab badge]
    end

    ALP --> PROD --> TOPIC --> LIVE
    WL2 --> LIVE
    LIVE --> BOOK --> RULE2
    RULE2 -->|yes, and day is price-only| PG
    LIVE --> BEAT --> API --> UI2
    PG --> UI2 --> NOTE2
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

S&P 500 daily prices only. No historical headlines. Local disk lake (S3 stand-in).

```mermaid
flowchart LR
    SP[S&P 500 symbol list] --> YF[Yahoo daily OHLCV ~1 year]
    YF --> LAND[batch_ingest or Settings land]
    LAND --> RAW[data/lake/raw/prices/daily]
    LAND --> MAN[raw/_runs manifest]
```

## As-built curated features and Isolation Forest

Local Spark-**role** job [`batch_train`](../batch_train/): pandas ELT + scikit-learn Isolation Forest. Four price/volume features only. Registry under `data/lake/registry/isolation_forest/current/`. Not a Dataproc/EMR cluster; same *job* the diagrams call Spark training.

```mermaid
flowchart LR
    RAW[data/lake/raw/prices/daily] --> CURATE[batch_train curate]
    CURATE --> FEAT[curated/features/session]
    FEAT --> TRAIN[Fit Isolation Forest]
    TRAIN --> REG[registry/isolation_forest/current]
```

## Local final target: high-level lambda architecture

Batch trains on **price history** (as-built). Stream applies that model and scores **near-term** news (remaining). Everything stays on the local machine. No historical news lake. No AWS requirement.

```mermaid
flowchart LR
    subgraph sources [Data sources]
        BARS_LIVE[S&P minute bars Alpaca]
        LIVE_NEWS[Near-term headlines]
        HIST_PX[Historical daily OHLCV Yahoo]
    end

    subgraph ingest [Ingestion]
        KAFKA[Docker Kafka]
        BATCH[batch_ingest into data/lake]
    end

    subgraph process [Processing]
        LIVE_SCORE[Live scorer Flink role]
        TRAIN_JOB[batch_train Spark role]
    end

    subgraph storage [Storage on disk and local DB]
        RAW[data/lake raw prices]
        TS[(Feature rows Timescale or Postgres)]
        CURATED[data/lake curated features]
        ALERTS[(Postgres alerts)]
        REG[(data/lake registry)]
    end

    subgraph detect [Detection]
        SENT[FinBERT 0 to 100 near-term]
        ANOM[Registered Isolation Forest]
        CORR[Slice correlation]
        PPLX[Perplexity two sentences]
    end

    subgraph serve [Serving]
        API[Alert API and dashboard]
        NOTE[Desktop notification and tab badge]
    end

    BARS_LIVE --> KAFKA --> LIVE_SCORE --> TS
    LIVE_NEWS --> KAFKA
    HIST_PX --> BATCH --> RAW
    RAW --> TRAIN_JOB --> CURATED
    CURATED --> REG
    REG --> ANOM
    LIVE_SCORE --> ANOM
    KAFKA --> SENT
    SENT --> CORR
    ANOM --> CORR
    CORR --> ALERTS
    ALERTS --> PPLX
    PPLX --> API --> NOTE
    ALERTS --> API
```

## Local final target: batch historical ELT

Land raw **prices**, build price/volume features, fit the forest. FinBERT is not fine-tuned and is not a batch input. **This path is as-built** via `batch_ingest` + `batch_train`.

```mermaid
flowchart LR
    HP[Historical S&P daily bars] --> ELP[batch_ingest land raw]
    ELP --> RAW[(data/lake raw zone)]
    RAW --> VAL[Schema check and dedup]
    VAL --> SPARK_ROLE[batch_train Spark role]
    SPARK_ROLE --> FEAT[Feature rows: gap, session, close, volume z-score]
    FEAT --> CUR[(Curated Parquet)]
    CUR --> TRAIN[Fit Isolation Forest and pick the cutoff]
    TRAIN --> REG[(data/lake registry)]
    REG -.-> LIVE[Live scorer loads the same model]
    CUR --> PG[(Postgres alert tables)]
    PG --> UI[Alert history dashboard]
```

## Local final target: streaming ETL

Minute bars scored by the registered forest. Near-term headlines scored by FinBERT. Postgres holds the alert. Perplexity writes after the row exists. **Percent-rule live path is as-built; forest scoring and live news topic are the remaining gap.**

```mermaid
flowchart TD
    MKT[S&P minute bars] --> KT[Docker Kafka raw bars]
    KT --> SCORE[Live scorer: session returns and volume z-score]
    SCORE --> GATE{Registered forest cutoff}
    SCORE --> LOADT[Load]
    LOADT --> FEATSTORE[(Feature rows local Timescale or Postgres)]
    GATE -->|score crosses cutoff| CORR[Slice correlation]

    NEWS[Near-term headline feed] --> KN[Kafka raw news]
    KN --> FINBERT[FinBERT 0 to 100]
    FINBERT --> SCORES[Kafka sentiment scores]
    SCORES --> CORR

    CORR --> PG[(Postgres alerts)]
    PG --> PPLX[Perplexity two sentences]
    PPLX --> DASH[Trader alert dashboard]
    PG --> DASH
    PG --> NOTIFY[Desktop notification and tab badge]
```

## Local final target: end-to-end alert sequence

Price-only and news-only are allowed. Perplexity never decides the alert. The forest features are price and volume only.

```mermaid
sequenceDiagram
    participant Market as Minute bars
    participant Kafka
    participant Scorer as Live scorer
    participant Registry as Model registry
    participant FinBERT
    participant Corr as Slice correlation
    participant PG as Postgres
    participant Pplx as Perplexity
    participant Trader

    Market->>Kafka: Stream minute bar
    Kafka->>Scorer: Consume bar batch
    Scorer->>Scorer: Build gap, session, close, volume z-score
    Registry->>Scorer: Load Isolation Forest and cutoff
    Scorer->>Corr: Anomaly score when the cutoff trips
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
    PG->>Trader: Desktop notification when the UI tab is open
```

## Local schema

`watchlist` holds S&P 500 symbols a check will refresh. `symbols` caches the Yahoo sector or fund category. `daily_bars` and `headlines` are check inputs (near-term headlines only). `app_settings` stores the price fraction, the FinBERT sentiment threshold, the optional Perplexity API key, the selected Perplexity model, and `live_consumer_heartbeat_at` for the Home live cue. The default threshold is 25 points from 50. The default model is `openai/gpt-5.4-mini`. `alerts.kind` is `price`, `news`, or `news_price`.

One row per symbol per `bar_date`. A repeated check replaces that day's alert and keeps `created_at`. The row also stores `price_move_threshold` and `sentiment_threshold` from the moment it fired. When Perplexity rewrites Together, the alert `sections` keep the rule sentence, the model id, and the model label shown under Together. A headline is eligible only when it was published on that Eastern trading day and is inside the news lookback.

`sentiment_scorer` stays `finbert`. FinBERT loads ProsusAI/finbert on this machine. The stored score is 0 to 100, with 50 neutral. Confidence is the winning class probability. A headline is eligible when the score is at least the saved number of points from 50.

The lake under `data/lake/` holds raw daily OHLCV, curated session features, and the Isolation Forest registry. It is separate from Postgres alerts.
