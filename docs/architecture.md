# S&P 500 Alert System architecture

Local **S&P 500** alert service for price movements and Isolation Forest anomalies, with same-day headline checks that grade how well the news explains the session. One alert per symbol per day: a price move, a news-sentiment alert, or a news + price alert when both rules fire.

Two product paths sit side by side:

- **Live** — continuous Kafka minute bars → Home **Recent** (monitor the session while it is open).
- **Watchlist** — a focus set of index constituents plus on-demand **Scan today** → **Watchlist results** (session / day review under current rules, including after the close).

Both write the same Postgres `alerts` table. History shows **Origin**, **Company**, **Type**, **Price change**, and **Sentiment score** (sortable columns); click a row for the full write-up. The **batch lake** (`batch_ingest` + `batch_train`) trains Isolation Forest on historical prices; it is not the Watchlist UI. Watchlist Scan today is the useful product pass over the **focus session** (today during/after RTH; the last completed session before the open or on weekends) plus near-term headlines.

The class design (CISC 525) is a **local** lambda architecture: Docker Kafka on the live path, a batch lake on disk, a Spark-**role** training job, FinBERT for near-term headline sentiment, an Isolation Forest trained on lake price/volume features, and Perplexity for the alert wording. The plan is [proposal-pipeline-audit.md](proposal-pipeline-audit.md).

**Deploy target:** one developer machine (Docker Desktop + Postgres + local lake). Cloud names from the original deck (S3, Aurora, managed Flink) map to local stand-ins below. This project does **not** require an AWS production deploy for the class demo.

This repository runs today:

- Alpaca delayed SIP minute bars onto local Kafka (`stream_ingest/`)
- A FastAPI consumer (`python -m app.live`) that writes open→last **price** alerts from the stream (percent rule **or** registered Isolation Forest when the lake registry is present), then runs a same-day headline check and grades how well the news explains the move
- Live feature vectors + forest scores into Postgres `live_feature_rows` (Timescale stand-in)
- **Watchlist** tab: focus-set search, **Scan today** over Yahoo daily bars + FinBERT headlines — same **percent or forest** price gate as live, then the same-day headline grade; Watchlist results separate from Home Recent
- Perplexity richer reasoning for news / news+price when a key is saved (price-only stays deterministic); forest-aware deterministic wording when Isolation Forest fires; granular evidence story on Home, Watchlist, and Details (What happened leads with a tone-colored alignment outcome chip)
- Batch land of about one year of S&P daily prices into `data/lake/raw/` (automatic on first boot when the lake is empty; Settings **Land** / `batch_ingest/` as overrides) for **model training**
- Incremental **Refresh lake + retrain** (automatic on a daily schedule; Settings / CLI as overrides) — per-symbol resume from the latest lake date (lookback capped ~14 calendar days); skips Yahoo + retrain when already current through the last completed session; header progress % while running
- Curated session features + Isolation Forest registry (`batch_train/`) — used by **both** Live and Watchlist Scan today
- Alert History with Origin, Company, Type, Price change, and Sentiment score; Mac/Chrome desktop notifications and a tab badge when new alerts arrive

Still open for the **local final** stack: an optional near-term news **topic on Kafka** (deferred — today live and Scan today fetch Yahoo headlines directly). Forest-aware price-only wording, Watchlist forest parity, incremental lake refresh + retrain, live price → same-day headline grade, and the evidence-story popup are as-built. **Historical headlines are not landed and are not training features.** There is no shared package with Vajra Astra Capital.

## Status

| Capability | Status |
|---|---|
| Watchlist tab: S&P 500 focus set (search + chips), Scan today, Watchlist results separate from Home Recent | **As-built** |
| Home tab: **Recent alerts** feed with S&P 500 / Watchlist scope switch; Clear alerts; desktop notification controls | **As-built** |
| History tab: full list with Origin, Company, Type, Price change, Sentiment score; click row for details; sortable + draggable columns | **As-built** |
| Yahoo daily bars into `daily_bars` for Watchlist Scan today / rebuild (session-day product pass) | **As-built** |
| Near-term Yahoo headlines scored with local FinBERT (0–100), with confidence and class shares | **As-built** |
| Price alert: open→last while the market is open; close versus prior close after the close. Volume spike note on the completed close | **As-built** |
| News alert and news + price when the headline’s price slice clears the same percent | **As-built** |
| Plain-English summary; Perplexity richer news / news+price reasoning when a key is saved (price-only stays deterministic) | **As-built** |
| Saved thresholds; admin rebuild of recent sessions for the watchlist | **As-built** |
| Minute bars on Kafka from Alpaca `delayed_sip` (WebSocket ≤30 on Basic; REST fills the rest of the S&P 500) | **As-built** |
| Live Kafka consumer: open→last price alerts (`python -m app.live`); Home “Live alerts on” heartbeat | **As-built** |
| Historical Yahoo daily bars for the S&P 500 (~1 year) in the lake raw zone (**training lake**, not the Watchlist UI) | **As-built** |
| Auto first-boot lake land + train when `data/lake` is empty; header “Loading historical prices” cue + % progress | **As-built** |
| Incremental lake refresh: resume from each symbol’s latest lake date (cap ~14d); skip Yahoo + retrain when already current through the last completed session (pre-open aware); daily auto schedule; Settings / CLI overrides | **As-built** |
| Watchlist Scan today focus session: last completed session before the cash open / on weekends; today during RTH or after the close | **As-built** |
| Spark-role curated feature table (gap, session, close, volume z-score) and Isolation Forest registry via `batch_train` (local pandas/scikit-learn) | **As-built** |
| Live scorer loads the registry and scores session features from Kafka bars (Flink role); Postgres `live_feature_rows` sink | **As-built** |
| Watchlist Scan today / rebuild uses the same Isolation Forest registry (percent **or** forest) before the same-day headline grade | **As-built** |
| Mac/Chrome desktop notification (Notification Center) plus tab title/favicon badge when new alerts arrive from Scan today or live | **As-built** |
| Live price → same-day headline grade: after a percent or forest price alert, fetch/score headlines and grade how well the news explains the move (news / news+price when the slice supports it; price-only when it does not); Perplexity on news kinds | **As-built** |
| Evidence story with granular second-side alignment (supports / somewhat supports / neutral / disagrees / contradicts) on Home, Watchlist, and Details; What happened outcome chip emphasizes the grade | **As-built** |
| Richer forest-aware price-only wording (deterministic Summary / Price / Forest / What happened when Isolation Forest fires; percent status + feature drivers; still no Perplexity on bare price-only) | **As-built** |
| Near-term news topic on Kafka with FinBERT scores (optional bus; deferred — live and Scan today fetch Yahoo near-term headlines today) | **Local final target (deferred)** |

Dropped from both the running design and the local final target: Cassandra, FinBERT fine-tuning, VWAP as a stream stage, a generic LLM box, a historical news lake, sentiment features inside Isolation Forest training, and a mandatory AWS production deploy.

A normal check writes the current Eastern trading day. The admin rebuild deletes saved alerts and reapplies rules over the last 1–40 calendar days for the watchlist. It is not the training lake. Model training reads lake Parquet, not the rebuild.

## Proposal audit

[proposal-pipeline-audit.md](proposal-pipeline-audit.md) is the revised plan. Diagrams below separate **as-built** (running now) from **local final target** (still to wire on this machine). Cassandra, FinBERT fine-tune, VWAP, and a generic LLM box are gone. Historical news is not part of the batch lake. S3/Aurora on older slides mean `data/lake` and local Postgres.

### What this repository does

| Local final target | This app today |
|---|---|
| Minute bars on Kafka, scored by the registered forest | Minute bars on Kafka from Alpaca. `python -m app.live` applies the open→last **percent** rule and scores session features with the registered Isolation Forest; rows land in `live_feature_rows` |
| FinBERT on near-term headlines | FinBERT on Watchlist Scan today and after a live price / forest alert. Weights on this machine. No historical news land |
| Slice join, news-only and price-only | Same Eastern day; gap, session, or close slice. Live and Scan today: price first, then a headline check that grades how well the news explains the session; news-only still allowed on Scan today |
| Watchlist focus set beside the live feed | Watchlist tab for Scan today / Watchlist results; Home Recent for live; History Origin distinguishes the writer |
| Perplexity after the decision | When a key is saved for news / news+price; model name under Together; price-only keeps the rule sentence |
| Lake, Spark-role training, registry | Raw under `data/lake/raw/` via auto first-boot **Land**, scheduled **Refresh**, or Settings/CLI. Refresh resumes from latest local dates and no-ops when current. `batch_train` writes curated features and `data/lake/registry/isolation_forest/current/`. Live and Scan today both score with that registry |
| One alert per symbol per day | One row per symbol per day (`alerts.origin` tracks live / watchlist / both) |
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

Everything that runs on one machine today. Three paths stay distinct: the **training lake**, **Live** (continuous), and **Watchlist Scan today** (on-demand session pass). Live and Scan today both use the **percent rule or** the registered Isolation Forest (same lake registry) as the price gate, then a same-day headline check that grades how well the news explains the session.

```mermaid
flowchart TB
    subgraph batch [Batch lake — train Isolation Forest]
        YF[Yahoo daily OHLCV] --> LAND[Land full ~1y]
        YF --> REF[Refresh resume from latest dt]
        BOOT[API boot empty lake] --> LAND
        SCHED[Daily auto schedule] --> REF
        LAND --> RAW[(data/lake/raw/prices/daily)]
        REF -->|merge by date or skip if current| RAW
        REF -->|only when new rows| BT[batch_train pandas ELT]
        LAND --> BT
        RAW --> BT
        BT --> CUR[(curated/features/session)]
        CUR --> IF[Isolation Forest scikit-learn]
        IF --> REG[(registry/isolation_forest/current)]
    end

    subgraph stream [Live — continuous market feed]
        ALP[Alpaca delayed_sip] --> PROD[stream_ingest]
        PROD --> KAFKA[(Docker Kafka prices.raw.bars)]
        KAFKA --> LIVE[python -m app.live]
        REG --> LIVE
        LIVE -->|percent or forest then headline grade| PG[(Postgres alerts)]
        LIVE --> FEAT[(live_feature_rows)]
        LIVE --> HOME[Home Recent alerts]
    end

    subgraph watch [Watchlist — on-demand session check]
        WL[Focus set chips] --> RUN[Scan today]
        RUN --> FOCUS[Focus session today or last completed]
        FOCUS --> YB[Yahoo daily bars + near-term headlines]
        YB --> FB[Local FinBERT]
        REG --> RUN
        RUN -->|percent or forest then headline grade| PG
        RUN --> CHECK[Watchlist results]
    end

    subgraph serve [Serving]
        PG --> HIST[History Origin Company Type Price Sentiment score]
        PG --> API[FastAPI + UI tabs]
        API --> NOTE[Desktop notification and tab badge]
        HOME --> API
        CHECK --> API
        HIST --> API
    end
```

## As-built: Live and Watchlist side by side

| | Live | Watchlist Scan today |
|---|---|---|
| Job | Continuous monitoring while RTH is open | Deliberate review of the focus set under **current** rules |
| UI | Home → **Recent alerts** (scope: full S&P 500 or Watchlist only) | Watchlist → chips + **Scan today** → **Watchlist results** |
| Inputs | Kafka minute bars (+ near-term Yahoo headlines after a price/forest hit) | Yahoo `daily_bars` + near-term headlines for watchlist symbols |
| Focus session | Wall-clock RTH / live open→last | **Today** during RTH or after the close; **last completed weekday** before the open / on weekends |
| Price gate | open→last **percent or** Isolation Forest (lake registry) | Same **percent or** Isolation Forest on the focus session’s vector |
| When it shines | Deployed day; laptop left open on the stream | Pre-market catch-up; after the close; after changing Settings; class demo without Kafka |
| Origin on the row | `live` (or `both` if Scan today also wrote the day) | `watchlist` (or `both` if live also wrote the day) |

The lake batch path does **not** replace Watchlist. Lake Parquet trains the forest. Watchlist Scan today is the product pass over **this session’s** bars and headlines for names you care about.

## Price gates (percent **or** forest)

Either gate can open a **price-led** day. They are not both required. What happened tags the case in brackets on the price step (`(percent only)`, `(percent + forest)`, `(forest only)`, `(neither gate)`).

| Percent | Forest | Price-led alert? | What happened tag |
|---|---|---|---|
| Clears (e.g. ≥ 3%) | Normal / absent | **Yes** — percent alone | `(percent only)` |
| Clears | Anomalous | **Yes** — both | `(percent + forest)` |
| Under threshold | Anomalous | **Yes** — forest alone | `(forest only)` |
| Under threshold | Normal / absent | **No** price-led | `(neither gate)` — typical news-led Scan today case |

## What can trigger a price-led alert

| # | Trigger | Opens a price alert alone? | Notes |
|---|---|---|---|
| 1 | **Price move threshold** — open→last (RTH) or close vs prior (after close / Scan) ≥ Settings % (UI label: Price move threshold) | **Yes** | Live + Watchlist |
| 2 | **Isolation Forest anomalous** — score ≤ registry cutoff on the four-feature vector | **Yes** (even if under %) | Live + Watchlist |
| 3 | **Gap return** (open vs prior close) | No — forest **feature** | Inside #2 |
| 4 | **Session return** (open→last) | No — forest **feature** (and #1 if large enough) | Inside #1 / #2 |
| 5 | **Close return** (last vs prior close) | No — forest **feature** | Inside #2 |
| 6 | **Volume z-score** (today’s volume vs ~20 prior days) | No — forest **feature** | How “heavy trading” usually fires |
| 7 | **Volume spike note** (≥ ~2× recent average on a completed daily close) | **No** — annotation only | Shown when a percent-led daily card also spiked |

The price step also adds a compact trigger note, e.g. `[triggers: #1 percent]`, `[triggers: #2 forest (#6 volume z, #3 gap)]`, or `[triggers: #1 percent + #2 forest; #7 volume spike noted]`. News-led cards under both gates show `[triggers: none (price under both gates)]`.

## As-built Watchlist Scan today

**Scan today** or rebuild on the Watchlist tab. Live Kafka price path is the next diagram.

**Focus session:** during the cash session (9:30–16:00 Eastern) or after the close on a weekday, Scan today evaluates **today**. Before the open — and on weekends — it evaluates the **last completed weekday** (as of that session’s 4:00 PM close) so a pre-market run is not empty. Alert `when` stamps stay on that session’s clock.

```mermaid
flowchart TB
    subgraph ingest [Ingestion]
        WL[S&P 500 watchlist] --> RUN[Scan today or rebuild]
        RUN --> FOCUS[Focus session today or last completed]
        FOCUS --> PX[Yahoo daily bars]
        FOCUS --> NW[Near-term Yahoo headlines]
        PX --> BARS[(daily_bars)]
        NW --> SCORE[Local FinBERT, 0 to 100]
        SCORE --> NEWS[(headlines)]
    end

    subgraph rules [Alert rules]
        BARS --> PCT{Open to last while open, else close versus prior}
        BARS --> IF[Isolation Forest gap session close volume z]
        PCT -->|at or beyond percent| PA[Price alert]
        IF -->|score at or below cutoff| PA
        PCT --> VOL[Volume spike note on completed close]
        VOL -.->|annotation only| PA
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
        ALERTS --> UI[Watchlist results, History, Details]
        UI --> NOTE[Desktop notification and tab badge]
        PPLX -.->|model name under Together| UI
        RULE -.->|Rule section when replaced| UI
    end
```

Home asks for notification permission (Enable desktop notifications). When Scan today or a live refresh adds alert rows, the open tab raises a Mac/Chrome Notification Center popup and sets `(N)` on the title with a favicon badge. Opening Home clears the unread count. Scan today results stay on the Watchlist tab so Home Recent is not overwritten. Slack and email are not used.

## As-built live price stream

Docker Kafka, Alpaca producer, and `python -m app.live`. Writes **price** alerts with the **percent rule** and, when the lake registry is present, scores the same four session features with the registered Isolation Forest (Flink role). After a live price (or forest) alert, the consumer fetches near-term Yahoo headlines, scores them with FinBERT, and grades how well the news explains the session — upgrading to news or news+price when the same-day slice supports it, otherwise keeping price-only with that grade. Same join as Watchlist Scan today. News / news+price rows go through Perplexity when a key is saved. Feature vectors land in Postgres `live_feature_rows`. Home Recent polls alerts; `/v1/live/status` drives the Live alerts on pill. Rows are tagged `origin=live` (or merge to `both`).

```mermaid
flowchart LR
    subgraph sources [Sources]
        ALP[Alpaca delayed_sip]
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
        NEWSU[Same-day headline grade]
    end

    subgraph out2 [Output]
        PG[(Postgres alerts origin live)]
        FEAT[(live_feature_rows)]
        BEAT[live_consumer_heartbeat_at]
        API[GET /v1/live/status]
        UI2[Home Recent + Live alerts on]
        NOTE2[Desktop notification and tab badge]
    end

    ALP --> PROD --> TOPIC --> LIVE
    REG --> LIVE
    LIVE --> BOOK --> RULE2
    BOOK --> FOREST
    RULE2 -->|yes| NEWSU
    FOREST -->|anomalous| NEWSU
    NEWSU --> PG
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

## As-built batch lake land and refresh

S&P 500 daily prices only. No historical headlines. Local disk lake (S3 stand-in). On first API boot with an empty lake, **auto land + train** runs (~1 year) and the UI header shows “Loading historical prices” with a **% progress** bar. A **daily auto refresh** (and Settings **Refresh**) checks each symbol’s latest lake date first: if everything is already through the **last completed session** (pre-open aware — before 4:00 PM Eastern “today” is not required yet), it **skips Yahoo and retrain**. Otherwise it resumes from that latest date (lookback capped ~14 calendar days), merges by `dt`, then runs `batch_train`. Settings **Land** remains a full replace. Kafka minute bars do **not** write the lake.

```mermaid
flowchart LR
    SP[S&P 500 symbol list] --> YF[Yahoo daily OHLCV]
    YF --> LAND[Land full replace ~1 year]
    CHECK[Latest local dt vs last completed session] --> MER[Refresh fetch only what is missing]
    YF --> MER
    BOOT[API boot empty lake] --> LAND
    SCHED[Daily auto schedule] --> CHECK
    LAND --> RAW[data/lake/raw/prices/daily]
    MER -->|union by dt keep newest| RAW
    CHECK -->|already current| SKIP[Skip Yahoo and retrain]
    LAND --> MAN[raw/_runs manifest]
    MER --> MAN
    LAND --> TRAIN[batch_train curate + fit]
    MER -->|new rows only| TRAIN
    RAW --> TRAIN
    TRAIN --> REG[registry/isolation_forest/current]
```

## As-built curated features and Isolation Forest

Local Spark-**role** job [`batch_train`](../batch_train/): pandas ELT + scikit-learn Isolation Forest. Four price/volume features only. Registry under `data/lake/registry/isolation_forest/current/`. Not a Dataproc/EMR cluster; same *job* the diagrams call Spark training. Live and Watchlist Scan today both load this registry for the **percent or forest** price gate.

```mermaid
flowchart LR
    RAW[data/lake/raw/prices/daily] --> CURATE[batch_train curate]
    CURATE --> FEAT[curated/features/session]
    FEAT --> TRAIN[Fit Isolation Forest]
    TRAIN --> REG[registry/isolation_forest/current]
    REG --> LIVE[python -m app.live]
    REG --> SCAN[Watchlist Scan today]
```

## Local final target: high-level lambda architecture

Batch trains on **price history** (as-built), with automatic first-boot land and incremental **Refresh lake + retrain** so the registry stays current. Stream scores minute bars with that model and runs a same-day headline check that grades how well the news explains the session (as-built). Watchlist Scan today uses the **same percent or forest** gate and headline grade on daily bars (as-built). Optional Kafka news topic remains a deferred local final nicety. Everything stays on the local machine. No historical news lake. No AWS requirement.

```mermaid
flowchart LR
    subgraph sources [Data sources]
        BARS_LIVE[S&P minute bars Alpaca]
        LIVE_NEWS[Near-term headlines]
        HIST_PX[Historical daily OHLCV Yahoo]
        FOCUS[Watchlist focus set]
    end

    subgraph ingest [Ingestion]
        KAFKA[Docker Kafka]
        BATCH[batch_ingest Land or Refresh merge]
        DAY[Yahoo daily bars for Scan today]
    end

    subgraph process [Processing]
        LIVE_SCORE[Live scorer Flink role]
        TRAIN_JOB[batch_train Spark role]
        RUNCHK[Watchlist Scan today percent or forest]
    end

    subgraph storage [Storage on disk and local DB]
        RAW[data/lake raw prices]
        TS[(Feature rows Timescale or Postgres)]
        CURATED[data/lake curated features]
        ALERTS[(Postgres alerts + origin)]
        REG[(data/lake registry)]
    end

    subgraph detect [Detection]
        SENT[FinBERT 0 to 100 near-term]
        ANOM[Registered Isolation Forest]
        CORR[Slice correlation]
        PPLX[Perplexity richer reasoning]
    end

    subgraph serve [Serving]
        HOME[Home Recent]
        WATCHUI[Watchlist results]
        HIST[History Origin]
        NOTE[Desktop notification and tab badge]
    end

    BARS_LIVE --> KAFKA --> LIVE_SCORE --> TS
    LIVE_NEWS --> SENT
    HIST_PX --> BATCH --> RAW
    RAW --> TRAIN_JOB --> CURATED
    CURATED --> REG
    REG --> LIVE_SCORE
    REG --> RUNCHK
    REG --> ANOM
    LIVE_SCORE --> ANOM
    ANOM --> CORR
    SENT --> CORR
    CORR --> ALERTS
    FOCUS --> RUNCHK
    DAY --> RUNCHK
    RUNCHK --> SENT
    RUNCHK --> ALERTS
    ALERTS --> PPLX
    ALERTS --> HOME
    ALERTS --> WATCHUI
    ALERTS --> HIST
    HOME --> NOTE
    WATCHUI --> NOTE
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

Minute bars scored by the registered forest (as-built). **Product join is price-first (as-built on live and Watchlist Scan today):** when the percent rule or forest marks a live move, the scorer fetches near-term headlines for that symbol, scores them with FinBERT, and grades how well the news explains the session — upgrading to news or news+price when the same Eastern-day slice supports it, otherwise keeping price-only. Stale prior-day stories stay out. A Kafka news topic remains optional. Postgres holds the alert with `origin`. Perplexity writes after news / news+price rows exist. The details popup shows the evidence story with a granular second-side alignment (supports / somewhat supports / neutral / disagrees / contradicts). What happened leads with a muted check path plus a tone-colored outcome chip for that grade (mismatches also emphasize the final step).

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
    FINBERT --> SLICE{Headline explains the session?}
    SLICE -->|supports| UPGRADE[Upgrade to news or news_price]
    SLICE -->|does not explain| KEEP[Keep price-only with grade]
    UPGRADE --> PG[(Postgres alerts)]
    KEEP --> PG
    PG --> PPLX[Perplexity richer news or news_price]
    PPLX --> DASH[Trader alert dashboard]
    PG --> DASH
    PG --> NOTIFY[Desktop notification and tab badge]
```

## Local final target: end-to-end alert sequence

Price-only and news-only are allowed. The happy path below is **price noticed → headlines checked → grade how well the news explains the session**. Perplexity never decides the alert. The forest features are price and volume only. Watchlist Scan today uses the same join on daily bars for the focus set.

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
        alt Headline explains the session
            Scorer->>PG: Upgrade to news or news_price
        else News does not explain the move
            Scorer-->>PG: Leave price-only with grade
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

`watchlist` holds the S&P 500 focus set for Scan today and rebuild. `symbols` caches the Yahoo sector or fund category. `daily_bars` and `headlines` are Watchlist Scan today inputs (near-term headlines only). `app_settings` stores the price fraction, the FinBERT sentiment threshold, the optional Perplexity API key, the selected Perplexity model, and `live_consumer_heartbeat_at` for the Home live cue. The default threshold is 25 points from 50. The default model is `openai/gpt-5.4-mini`. `alerts.kind` is `price`, `news`, or `news_price`. `alerts.origin` is `live`, `watchlist`, or `both`. `live_feature_rows` stores live session feature vectors and Isolation Forest scores from `python -m app.live`.

One row per symbol per `bar_date`. A repeated check replaces that day's alert and keeps `created_at`. When live and watchlist both write the same day, `origin` becomes `both`. The row also stores `price_move_threshold` and `sentiment_threshold` from the moment it fired. When Perplexity rewrites Together, the alert `sections` keep the rule sentence, the model id, and the model label shown under Together. Evidence steps live under `sections.evidence` with an `alignment` grade. A headline is eligible only when it was published on that Eastern trading day and is inside the news lookback.

`sentiment_scorer` stays `finbert`. FinBERT loads ProsusAI/finbert on this machine. The stored score is 0 to 100, with 50 neutral. Confidence is the winning class probability. A headline is eligible when the score is at least the saved number of points from 50.

The lake under `data/lake/` holds raw daily OHLCV, curated session features, and the Isolation Forest registry. It is separate from Postgres alerts.
