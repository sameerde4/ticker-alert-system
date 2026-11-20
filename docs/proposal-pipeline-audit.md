# Proposal pipeline audit

CISC 525 deck and PDF, 30 August 2026. *Real-Time Equity Anomaly & Sentiment Fusion Platform.* Sameer De, Mahir Jhaveri, Gaurav Gulia, Runsen Ning.

This note is the **planned → landed** story for the presentation. The finished system itself is documented in detail in [architecture.md](architecture.md) (system overview, Live / Watchlist, lake, lambda, batch ELT, streaming ETL, end-to-end sequence). Vendor and gate tables are in [data-sources.md](data-sources.md).

**S&P 500 Radar** is what we built: one alert per symbol per day for the **S&P 500**, with Live (Kafka session feed → Home Live alerts) and Watchlist (focus set + Scan today → Watchlist results), Isolation Forest trained on a local price lake, FinBERT on near-term headlines, and optional Perplexity wording after the decision. The course still gets a big-data shape — lake, batch train, log, stream apply, AI after the fact — runnable on one machine.

## How to use this document in the presentation

| Question | Where to look |
|---|---|
| What does the system look like now? | [architecture.md](architecture.md) |
| What did the deck propose, and what did we change? | Sections below (slide by slide) |
| Why did we drop AWS / Cassandra / news lake / …? | **Why we changed** tables in each slide section + the summary at the end |

## What the professor needs to see

The architecture has to read as big data on the diagram, not only as a Python job that happens to call Yahoo. These are the boxes that carry that, and each one has a job on the **local** stack we landed:

| Piece | Path | Job | Local stand-in (landed) |
|---|---|---|---|
| Kafka | Streaming | Bus for live minute bars | Docker Compose Kafka |
| Flink | Streaming | Session state, live feature vector, score with registered forest | Live scorer in `python -m app.live` (Flink **role**) |
| TimescaleDB | Streaming | Sink for live feature rows | Postgres `live_feature_rows` |
| S3 / lake raw zone | Batch | Historical **daily prices** for the S&P 500 | `data/lake/raw/` on disk |
| Spark | Batch | ELT + training job | `batch_train` Spark-**role** (pandas + scikit-learn) |
| Curated Parquet | Batch | One feature row per symbol per session | `data/lake/curated/features/session/` |
| Model registry | Both | Fitted forest, feature list, cutoff | `data/lake/registry/isolation_forest/current/` |
| FinBERT | Near-term product join | Headline score 0–100; not a batch lake input | Local Transformers + PyTorch |
| Isolation Forest | Batch, then stream | Price/volume anomalies | Fit in `batch_train`; apply in `python -m app.live` and Watchlist Scan today |
| Perplexity | After the decision | Richer news / news+price wording; never decides the alert; Summary cites headlines as clickable titles | Settings API key |
| Postgres | Serving | One alert row per symbol per day | Local `ticker_alert_db` |

## Major decisions (planned vs landed)

| Original plan (deck / early design) | What we landed | Why |
|---|---|---|
| Deploy the stack on **AWS** (managed Kafka, S3, Aurora, Flink/Spark clusters) | **Local** demo: Docker Kafka, `data/lake` on disk, local Postgres, pandas/scikit-learn Spark-role, live scorer Flink-role | We got the full lambda shape working on one laptop. An AWS production deploy was not required for the course demo and would have delayed proving Live + Watchlist + forest + FinBERT. Cloud names stay as slide aliases for the same boxes. |
| Continuous **Kafka news topic** with FinBERT scores on the bus | **Pull-after-price** (and Scan today): fetch near-term Yahoo headlines for the symbol after a percent/forest gate, then FinBERT-grade the slice | Price-first matches the product. Streaming every headline is heavier and not needed to explain a move that already fired. Same Eastern-day slice join either way. |
| Historical **news lake** + FinBERT features in forest training | **Price/volume lake only**; near-term headlines only | Old stories do not explain today’s slice and are not Isolation Forest features. Keeps batch training unsupervised and defensible. |
| **Cassandra** (or a second store) for alerts | **Postgres only** | One alert per symbol per day is a relational upsert. Two stores added complexity without a course benefit. |
| Separate **analyst BI** dashboard | **Alert History** in the UI | The alert table *is* the dashboard for the demo. |
| **FinBERT fine-tune** | Published **ProsusAI/finbert** weights | Fine-tuning needs labeled headlines we do not have. |
| **VWAP** as a stream feature | Dropped | Forest features are gap, session, close, volume z-score — same list in batch and live. |
| Slack / email notifications | **Mac/Chrome desktop notification** + tab badge | Enough for a local demo; fails soft without losing the alert row. |
| Single “check” path mixing train and product | **Three paths**: training lake, Live continuous, Watchlist Scan today | Lake trains the forest. Live monitors RTH. Watchlist is the on-demand session pass (including pre-open last completed session). Origin on the row separates writers. |

## Verdict (what we kept as the spine)

Keep batch and streaming as two engines. Give them one **price/volume** feature definition so they cannot drift.

| Choice | What it means now |
|---|---|
| Two engines, one feature list | `batch_train` fits the forest on price history. The live scorer (and Watchlist) scores the same features. |
| Lake plus log | `data/lake` holds training prices. Docker Kafka holds live bars. |
| Live plus Watchlist | Live → Home Live alerts. Scan today → Watchlist results. Same `alerts` table; Origin separates them. |
| Local demo, not AWS prod | Same architecture boxes; S3/Aurora/Dataproc are optional slide aliases. |
| Three outcomes | News, price, or both. Forest does not require a headline. |
| AI after the decision | Perplexity explains news / news+price rows. It does not create the alert. |
| Near-term news only | FinBERT on headlines for today’s slice. No multi-month news archive. |

## Machine learning

The deck names Isolation Forest and FinBERT and never says which one the alert waits for, or what the training rows are. This is what we landed.

**FinBERT** is the news model. Published ProsusAI/finbert weights; score 0–100 (50 neutral); qualifies when far enough from 50 (Settings). No fine-tune. Runs on the **near-term** path after a live price/forest hit or on Watchlist Scan today — not as a Kafka news consumer, and not as lake training input.

**Isolation Forest** is the price model; the batch lake exists to train it. Spark-role job builds one row per symbol per session from historical **bars only**:

- Close versus prior close  
- Open versus prior close (gap)  
- Close versus open (session)  
- Volume z-score versus ~20 prior sessions  

Unsupervised fit (no labeled anomalies). Cutoff chosen by replaying the curated table. Registry holds model, feature list, and cutoff. Live and Watchlist both apply that registry with the **percent or forest** price gate, then the same-day headline grade.

## AI usage

Deterministic sentence from alert fields stays as the fallback (and as the only wording for bare price-only rows, with richer forest-aware copy when Isolation Forest fired). After a news or news+price row exists, Perplexity gets a structured payload and returns three to four short sentences. Batches of eight on check/rebuild. The model never decides whether the alert exists. Together shows the name of the model that wrote it. Bare article URLs in the reply are linkified to the headline title (on save and at display for older rows). Live scores the full S&P 500 Kafka stream; Watchlist remains the Scan today focus set.

## Slide 6 — High-level lambda

**Planned:** Streaming for live detection, batch for training; managed cloud boxes on the deck.

**Landed:** Same split of purpose on one machine — diagrams in [architecture.md](architecture.md) (*High-level lambda architecture*, *System overview*). Minute bars on Kafka; historical prices in the lake; Spark-role train → registry → Flink-role live apply; Watchlist Scan today beside Live; Perplexity after news kinds; desktop notification after the row.

| Step | Verdict | Why |
|---|---|---|
| Live tick feed | **Change → landed** | Publish **minute bars** for the S&P 500 onto Kafka (Alpaca delayed SIP). Raw quotes would force reaggregation before scoring. |
| Live / near-term news | **Keep → landed as pull** | Headlines are half the product. Score them near-term after price (or on Scan today). Do not build a multi-month news lake. |
| Historical OHLCV | **Keep → landed** | Training set for the forest (`batch_ingest` / auto land / refresh). |
| Historical news archive | **Drop** | Old headlines do not explain today’s slice and are not forest features. |
| Kafka ingest | **Keep → landed** | Streaming half for **bars**. We did **not** require separate Kafka topics for headlines/sentiment/anomaly for the demo. |
| Separate batch ingest | **Keep → landed** | Land prices into the lake with the same feature definitions the stream uses. |
| Stream feature job | **Keep → landed** | Flink **role** in `python -m app.live`: session state, vector, registry score. |
| Spark | **Keep → landed as role** | ELT + Isolation Forest in `batch_train` (pandas/scikit-learn), not a Dataproc cluster. |
| S3 / lake raw zone | **Keep → local disk** | `data/lake/raw/` — same box, local stand-in. |
| Timescale feature store | **Keep → Postgres** | `live_feature_rows` stand-in. |
| Curated lake zone | **Keep → landed** | Parquet feature rows, one per symbol per session. |
| Alert store | **Keep → landed** | One row per symbol per day in Postgres. |
| Model training / registry | **Keep → landed** | Fit forest; store feature list, model, cutoff. |
| Sentiment scoring | **Keep → landed** | FinBERT 0–100 on near-term headlines. |
| Anomaly detection | **Keep → landed** | Registered forest on live (and Watchlist) price/volume vector. |
| Correlation | **Keep → landed** | Price first, then headline grade on symbol + slice. Allow price-only and news-only. |
| Perplexity summary | **Keep → landed** | Richer news / news+price after the decision; deterministic fallback. |
| API and dashboard | **Keep → landed** | Home Live alerts, Watchlist results, History with Origin. |
| Notification | **Keep → landed** | Desktop + tab badge (not Slack/email). |
| AWS production deploy | **Drop for demo** | Local stack proves the architecture; cloud names remain slide aliases. |

## Slide 7 — Batch historical ELT

**Planned:** Extract/load then transform; Spark trains on lake; optional news archive and FinBERT fine-tune on some decks.

**Landed:** See [architecture.md](architecture.md) (*Batch historical ELT*, *Batch lake land and refresh*, *Curated features and Isolation Forest*). Auto first-boot land + train; daily incremental refresh that skips Yahoo when already current; Settings Land/Refresh overrides.

| Step | Verdict | Why |
|---|---|---|
| Price archive | **Keep → landed** | Historical S&P daily bars in the raw zone. |
| News archive | **Drop** | Not used for forest training; near-term FinBERT only. |
| Extract and load raw | **Keep → landed** | Land prices first, then transform — lake stays reprocessable. |
| S3 / lake raw zone | **Keep → local** | Big-data landing zone as `data/lake/raw/`. |
| Schema check and dedup | **Keep → landed** | Clean symbol and session keys on the price land. |
| Spark / feature engineering | **Keep → landed as role** | Three returns + volume z-score; **no** FinBERT aggregates in training rows. |
| Curated Parquet / training / Isolation Forest | **Keep → landed** | Unsupervised price/volume model; cutoff by replay. |
| FinBERT fine-tune | **Drop** | Weights already trained; we lack labels. |
| FinBERT aggregates in training rows | **Drop** | News is product join logic, not batch forest input. |
| Inference from the registry | **Keep → landed** | Live scorer + Watchlist load the fitted model. |
| Reporting database | **Keep → landed** | Postgres alerts. |
| Separate analyst dashboard | **Drop** | Alert History is the dashboard. |

## Slide 8 — Streaming ETL

**Planned:** Kafka + Flink + FinBERT topic + Timescale + correlation; Cassandra on some slides; VWAP on some slides.

**Landed:** See [architecture.md](architecture.md) (*Streaming ETL*, *Live price stream*). Producer → Kafka bars → live scorer (percent **or** forest) → pull headlines → FinBERT grade → Postgres → UI / notification. VWAP and Cassandra removed.

| Step | Verdict | Why |
|---|---|---|
| Market websocket | **Change → landed** | Alpaca delayed SIP → Kafka minute bars (WebSocket cap + REST fill on Basic). |
| Extract, then Kafka bars | **Change → landed** | Producer is the extract; one raw-bars topic for the demo. |
| Volume z-score and session returns | **Keep → landed** | Same features Spark trained on. **VWAP dropped** — not a forest feature. |
| Flink | **Keep → landed as role** | Session state, live vector, registry score in `python -m app.live`. |
| Threshold gate | **Keep → landed** | Percent rule **or** registered forest cutoff. |
| Load into TimescaleDB | **Keep → Postgres** | `live_feature_rows`. |
| Near-term news after price | **Change → landed** | Fetch Yahoo headlines for that symbol after the gate; **no** required Kafka news topic. |
| FinBERT on those headlines | **Keep → landed** | 0–100 near-term scoring. |
| Correlation engine | **Keep → landed** | Price first, then headline grade; emit news, price, or both. |
| Cassandra | **Drop** | Postgres holds the alert. |
| Perplexity / dashboard / desktop notify | **Keep → landed** | After the row exists. |

## Slide 9 — End-to-end sequence

**Planned:** Stream → features → anomaly → correlate with news → LLM.

**Landed:** Happy path **price noticed → headlines checked → grade how well the news explains the session** ([architecture.md](architecture.md) *End-to-end alert sequence*). Alert type: `price-led` / `news-led` / `price + news`. Price shape: `volatile` / `anomalous` / `volatile + anomalous`. Direction: `agrees` / `disagrees` / `mixed`. History columns include those three. Price-trigger cases #1–#7 in architecture and data-sources.

| Step | Verdict | Why |
|---|---|---|
| Stream a live bar | **Change → landed** | Minute bar on Kafka. |
| Flink consumes / builds trained vector | **Keep → landed** | Micro-batch path; gap/session/close + volume z only. |
| Anomaly / percent gate | **Keep → landed** | Either gate can open a price-led day. |
| Upsert price when the gate trips | **Keep → landed** | Price-first product path. |
| Fetch / score near-term headlines | **Change → landed** | Pull after price; FinBERT 0–100. |
| Correlate inside the slice | **Change → landed** | Gap / session / close window; keep price-only when news does not explain the move. |
| Structured payload / Perplexity | **Keep → landed** | News / news+price only; template fallback. |

## Slide 12 — No-code replacement

**Planned / rhetorical:** A workflow tool cannot replace Flink session state, Spark training, or the slice join.

**Landed argument (unchanged spine):** Threshold snapshot and model version on the alert row are the audit trail we can defend. Desktop notifications are enough for a class demo; they are not a substitute for the stream path. Drop claims of a regulatory audit trail or latency SLA the rest of the deck never defines.

## What we landed (checklist for the demo)

A reviewer should point at [architecture.md](architecture.md) and name the batch path, the stream path, the lake, the model that crosses from one to the other, and the AI call that does not — all runnable locally.

- **Batch:** `data/lake` raw prices, `batch_train` (Spark role), curated Parquet, Isolation Forest, registry — **training only**. Auto first-boot land+train; daily **Refresh lake + retrain** (skip when current through last completed session); Settings overrides.
- **Watchlist Scan today:** focus session = last completed weekday before the open / weekends; today during RTH or after the close.
- **Streaming:** Docker Kafka, `python -m app.live` percent-rule + Isolation Forest, live **price → same-day headline grade**, `live_feature_rows`, Home Live alerts, desktop notifications.
- **Watchlist product path:** focus set, same **percent or forest** gate + headline grade, Watchlist results, `alerts.origin`, rebuild.
- **News join:** pull near-term Yahoo headlines after a price/forest hit (or on Scan today); no Kafka news topic.
- **Handoff:** live (and Watchlist) score with the model `batch_train` fitted on price history.
- **AI:** Perplexity on news / news+price; deterministic / forest-aware wording on price-only.
- **Product rules:** S&P 500 universe, one alert per symbol per day, three outcomes, same-day headline grades.
- **Deploy:** local machine. AWS production is out of scope for the demo.

## Source

Deck and PDF, CISC 525, 30 August 2026: `CISC 525 - Equity Anomaly and Sentiment Platform`. Finished-system diagrams: [architecture.md](architecture.md). This note records how that proposal became **S&P 500 Radar** on a local lambda stack — what we kept for the course shape, what we changed for a working demo, and why the drops (AWS prod, Cassandra, news lake, FinBERT fine-tune, VWAP, Kafka news bus, Slack/email) were the better architectural call for this class. Historical headlines are not part of the design. The local model registry under `data/lake/registry/isolation_forest/current/` is how Watchlist forest parity with Live is enforced (same percent or forest gate). An optional Kafka news topic was considered and rejected for the demo in favor of pull-after-price.
