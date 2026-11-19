# S&P 500 Alert System architecture

Local decision-support service for the **S&P 500**. A watchlist of index constituents becomes one alert per symbol per day: a price move, a news-sentiment alert, or a news + price alert when both rules fire.

The class design (CISC 525) is a **local** lambda architecture: Docker Kafka on the live path, a batch lake on disk, a Spark-**role** training job, FinBERT for near-term headline sentiment, an Isolation Forest trained on lake price/volume features, and Perplexity for the alert wording. The plan is [proposal-pipeline-audit.md](proposal-pipeline-audit.md).

**Deploy target:** one developer machine (Docker Desktop + Postgres + local lake). Cloud names from the original deck (S3, Aurora, managed Flink) map to local stand-ins below. This project does **not** require an AWS production deploy for the class demo.

This repository runs today:

- Alpaca delayed SIP minute bars onto local Kafka (`stream_ingest/`)
- A FastAPI consumer (`python -m app.live`) that writes open→last **price** alerts for the watchlist (percent rule **and** registered Isolation Forest when the lake registry is present)
- Live feature vectors + forest scores into Postgres `live_feature_rows` (Timescale stand-in)
- Yahoo daily bars and FinBERT headlines on **Run check** (near-term news only) — the live path does **not** yet pull headlines after a price alert
- Perplexity richer reasoning for news / news+price when a key is saved (price-only stays deterministic)
- Batch land of about one year of S&P daily prices into `data/lake/raw/` (`batch_ingest/` or Settings)
- Curated session features + Isolation Forest registry (`batch_train/`)
- Mac/Chrome desktop notifications and a tab badge when new alerts arrive

Still open for the **local final** stack: after a live price move or forest anomaly, **pull near-term headlines for that symbol**, score them with FinBERT, and upgrade the day to news or news+price when the same-day slice lines up (skip stale prior-day stories). A dedicated near-term news topic on Kafka is optional; Run check already scores headlines for the watchlist. Popup “evidence story” UX (price noticed → news checked → evidence / none) and forest-aware price-only wording are also remaining. **Historical headlines are not landed and are not training features.** There is no shared package with Vajra Astra Capital.

## Status

| Capability | Status |
|---|---|
| Watchlist of S&P 500 constituents (focus set for Run check, rebuild, and live price alerts), with ticker and company-name search. Add accepts index constituents only | **As-built** |
| Yahoo daily bars into `daily_bars` for a check | **As-built** |
| Near-term Yahoo headlines scored with local FinBERT (0–100), with confidence and class shares | **As-built** |
| Price alert: open→last while the market is open; close versus prior close after the close. Volume spike note on the completed close | **As-built** |
| News alert and news + price when the headline’s price slice clears the same percent | **As-built** |
| Plain-English summary; Perplexity richer news / news+price reasoning when a key is saved (price-only stays deterministic) | **As-built** |
| Home inbox, Alert History, saved thresholds, admin rebuild of recent sessions | **As-built** |
| Minute bars on Kafka from Alpaca `delayed_sip` (WebSocket ≤30 on Basic; REST fills the rest of the S&P 500) | **As-built** |
| Live Kafka consumer: open→last price alerts (`python -m app.live`); Home “Live alerts on” heartbeat | **As-built** |
| Historical Yahoo daily bars for the S&P 500 (~1 year) in the lake raw zone | **As-built** |
| Spark-role curated feature table (gap, session, close, volume z-score) and Isolation Forest registry via `batch_train` (local pandas/scikit-learn) | **As-built** |
| Live scorer loads the registry and scores session features from Kafka bars (Flink role); Postgres `live_feature_rows` sink | **As-built** |
| Mac/Chrome desktop notification (Notification Center) plus tab title/favicon badge when new alerts arrive from Run check or live | **As-built** |
| Live price → near-term news: after a percent or forest price alert, fetch/score headlines and upgrade to news / news+price when the same-day slice matches | **Local final target** |
| Near-term news topic on Kafka with FinBERT scores (optional bus; Run check remains the near-term headline path today) | **Local final target** |
| Popup evidence story (price noticed → news checked → evidence / none) | **Local final target** |
| Richer forest-aware price-only wording | **Local final target** |

Dropped from both the running design and the local final target: Cassandra, FinBERT fine-tuning, VWAP as a stream stage, a generic LLM box, a historical news lake, sentiment features inside Isolation Forest training, and a mandatory AWS production deploy.

A normal check writes the current Eastern trading day. The admin rebuild deletes saved alerts and reapplies rules over the last 1–40 calendar days for the watchlist. It is not the training lake. Model training reads lake Parquet, not the rebuild.

## Proposal audit

[proposal-pipeline-audit.md](proposal-pipeline-audit.md) is the revised plan. Diagrams below separate **as-built** (running now) from **local final target** (still to wire on this machine). Cassandra, FinBERT fine-tune, VWAP, and a generic LLM box are gone. Historical news is not part of the batch lake. S3/Aurora on older slides mean `data/lake` and local Postgres.

### What this repository does

| Local final target | This app today |
|---|---|
| Minute bars on Kafka, scored by the registered forest | Minute bars on Kafka from Alpaca. `python -m app.live` applies the open→last **percent** rule and scores session features with the registered Isolation Forest; rows land in `live_feature_rows` |
| FinBERT on near-term headlines | FinBERT on each headline during a check. Weights on this machine. No historical news land. Live path does not yet pull headlines after a price alert |
| Slice join, news-only and price-only | Same Eastern day; gap, session, or close slice. On Run check, fusion when that slice clears the price rule. **Local final:** live price first, then look up news for that move |
| Perplexity after the decision | When a key is saved for news / news+price; model name under Together; price-only keeps the rule sentence |
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
| Flink on Kinesis/MSK | Local Flink-**role** live scorer in `python -m app.live`: same four features + registry cutoff |
| Timescale (managed) | Postgres `live_feature_rows` (Timescale stand-in) |
| Slack / email | Mac/Chrome desktop notification + tab badge |

## As-built: system overview

Everything that runs on one machine today. Live price alerts use the **percent rule** and, when the registry is present, the registered Isolation Forest on the same four session features.

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
        LIVE -->|percent rule or forest anomaly| PG[(Postgres alerts)]
        LIVE --> FEAT[(live_feature_rows)]
        REG --> LIVE
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
        KEY -->|yes, news kinds, batches of eight| PPLX[Perplexity richer reasoning]
        PPLX --> ALERTS
        ALERTS --> UI[Home, History, Details]
        UI --> NOTE[Desktop notification and tab badge]
        PPLX -.->|model name under Together| UI
        RULE -.->|Rule section when replaced| UI
    end
```

Home asks for notification permission (Enable desktop notifications). When Run check or a live refresh adds alert rows, the open tab raises a Mac/Chrome Notification Center popup and sets `(N)` on the title with a favicon badge. Opening Home clears the unread count. Slack and email are not used.

## As-built live price stream

Docker Kafka, Alpaca producer, and `python -m app.live`. Writes **price** alerts with the **percent rule** and, when the lake registry is present, scores the same four session features with the registered Isolation Forest (Flink role). Anomalous forest scores can also upsert a price alert. Feature vectors land in Postgres `live_feature_rows` (Timescale stand-in). Near-term headlines still come from **Run check** today; the local final step after a live price alert is to fetch and score headlines and upgrade the day when the same-day slice matches. Home reads `/v1/live/status`.

```mermaid
flowchart LR
    subgraph sources [Sources]
        ALP[Alpaca delayed_sip]
        WL2[Watchlist in Postgres]
        REG[Lake Isolation Forest registry]
    end

    subgraph bus [Local Kafka]
        PROD[stream_ingest producer]
        TOPIC[prices.raw.bars]
        LIVE[python -m app.live]
    end

    subgraph decide [Session move]
        BOOK[Open latest volume from RTH bars]
        RULE2{Move at or beyond saved percent}
        FOREST[Score with registry cutoff]
    end

    subgraph out2 [Output]
        PG[(Postgres alerts)]
        FEAT[(live_feature_rows)]
        BEAT[live_consumer_heartbeat_at]
        API[GET /v1/live/status]
        UI2[Home Live alerts on]
        NOTE2[Desktop notification and tab badge]
    end

    ALP --> PROD --> TOPIC --> LIVE
    WL2 --> LIVE
    REG --> LIVE
    LIVE --> BOOK --> RULE2
    BOOK --> FOREST
    RULE2 -->|yes, and day is price-only| PG
    FOREST -->|anomalous and day is price-only| PG
    FOREST --> FEAT
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
    Live->>Live: Update open latest volume for RTH
    Live->>Live: Build feature vector score registry
    Live->>PG: Append live_feature_rows when due
    Live->>PG: Heartbeat for Live alerts on
    alt Forest anomalous or open to last clears percent
        Live->>PG: Upsert price alert for today
        UI->>PG: Poll alerts
        PG->>UI: Price card
    else Below both gates or news row exists
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

Batch trains on **price history** (as-built). Stream scores minute bars with that model (as-built) and, for the product join, **looks up near-term news after a live price alert** (remaining). Everything stays on the local machine. No historical news lake. No AWS requirement.

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
        PPLX[Perplexity richer reasoning]
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

Minute bars scored by the registered forest (as-built). **Product join is price-first:** when the percent rule or forest marks a live move, the scorer fetches near-term headlines for that symbol, scores them with FinBERT, and upgrades the day to news or news+price when the same Eastern-day slice matches. Stale prior-day stories stay out. A Kafka news topic is optional; Yahoo near-term pull on the alert is enough for the demo. Postgres holds the alert. Perplexity writes after news / news+price rows exist.

```mermaid
flowchart TD
    MKT[S&P minute bars] --> KT[Docker Kafka raw bars]
    KT --> SCORE[Live scorer: session returns and volume z-score]
    SCORE --> GATE{Percent rule or forest cutoff}
    SCORE --> LOADT[Load]
    LOADT --> FEATSTORE[(live_feature_rows Postgres)]
    GATE -->|price alert| PRICE[Upsert price row]
    PRICE --> NEWSLOOK[Fetch near-term headlines for symbol]
    NEWSLOOK --> FINBERT[FinBERT 0 to 100]
    FINBERT --> SLICE{Same-day slice lines up?}
    SLICE -->|yes| UPGRADE[Upgrade to news or news_price]
    SLICE -->|no| KEEP[Keep price-only]
    UPGRADE --> PG[(Postgres alerts)]
    KEEP --> PG
    PG --> PPLX[Perplexity richer news or news_price]
    PPLX --> DASH[Trader alert dashboard]
    PG --> DASH
    PG --> NOTIFY[Desktop notification and tab badge]
```

## Local final target: end-to-end alert sequence

Price-only and news-only are allowed. The happy path below is **price noticed → news looked up → evidence or none**. Perplexity never decides the alert. The forest features are price and volume only.

```mermaid
sequenceDiagram
    participant Market as Minute bars
    participant Kafka
    participant Scorer as Live scorer
    participant Registry as Model registry
    participant News as Near-term headlines
    participant FinBERT
    participant PG as Postgres
    participant Pplx as Perplexity
    participant Trader

    Market->>Kafka: Stream minute bar
    Kafka->>Scorer: Consume bar batch
    Scorer->>Scorer: Build gap, session, close, volume z-score
    Registry->>Scorer: Load Isolation Forest and cutoff
    alt Percent or forest trips
        Scorer->>PG: Upsert price alert for today
        Scorer->>News: Pull near-term headlines for symbol
        News->>FinBERT: Score titles 0 to 100
        FinBERT->>Scorer: Sentiment + publish time
        alt Same-day slice matches
            Scorer->>PG: Upgrade to news or news_price
        else No matching headline
            Scorer-->>PG: Leave price-only
        end
    end
    PG->>Pplx: Structured payload for news kinds
    alt Key saved and call succeeds
        Pplx->>Trader: Three to four sentence summary
    else No key or call failed or price-only
        PG->>Trader: Deterministic summary
    end
    PG->>Trader: Desktop notification when the UI tab is open
```

## Local schema

`watchlist` holds S&P 500 symbols a check will refresh. `symbols` caches the Yahoo sector or fund category. `daily_bars` and `headlines` are check inputs (near-term headlines only). `app_settings` stores the price fraction, the FinBERT sentiment threshold, the optional Perplexity API key, the selected Perplexity model, and `live_consumer_heartbeat_at` for the Home live cue. The default threshold is 25 points from 50. The default model is `openai/gpt-5.4-mini`. `alerts.kind` is `price`, `news`, or `news_price`. `live_feature_rows` stores live session feature vectors and Isolation Forest scores from `python -m app.live`.

One row per symbol per `bar_date`. A repeated check replaces that day's alert and keeps `created_at`. The row also stores `price_move_threshold` and `sentiment_threshold` from the moment it fired. When Perplexity rewrites Together, the alert `sections` keep the rule sentence, the model id, and the model label shown under Together. A headline is eligible only when it was published on that Eastern trading day and is inside the news lookback.

`sentiment_scorer` stays `finbert`. FinBERT loads ProsusAI/finbert on this machine. The stored score is 0 to 100, with 50 neutral. Confidence is the winning class probability. A headline is eligible when the score is at least the saved number of points from 50.

The lake under `data/lake/` holds raw daily OHLCV, curated session features, and the Isolation Forest registry. It is separate from Postgres alerts.
