# Proposal pipeline audit

CISC 525 deck and PDF, 30 August 2026. *Real-Time Equity Anomaly & Sentiment Fusion Platform.* Sameer De, Mahir Jhaveri, Gaurav Gulia, Runsen Ning.

Verdicts are against two constraints at once. The product raises one alert per symbol per day for the **S&P 500**. The course requires a big-data architecture: a batch path over historical **price** data, a streaming path over live data, a machine-learning model trained on the batch, and an AI step that writes the alert in plain English. The **as-built** and **local final target** diagrams live in [architecture.md](architecture.md). The class demo runs on one machine (Docker Kafka, local Postgres, `data/lake`). An AWS production deploy is not required; cloud names on the original deck map to local stand-ins. The tables below say what stayed from the original deck, what changed, and what came off.

## What the professor needs to see

The architecture has to read as big data on the diagram, not only as a Python job that happens to call Yahoo. These are the boxes that carry that, and each one has a job on the **local** stack:

| Piece | Path | Job | Local stand-in |
|---|---|---|---|
| Kafka | Streaming | The bus. Raw bars, near-term headlines, sentiment scores, and anomaly scores are separate topics. | Docker Compose Kafka |
| Flink | Streaming | Stateful windows. Holds the session open, the latest price, and volume, and scores the live price/volume feature vector. | Live scorer in `python -m app.live` (Flink **role**) — as-built |
| TimescaleDB | Streaming | Sink for the live feature rows. This is the time-series store on the diagram. | Postgres `live_feature_rows` (Timescale stand-in) — as-built |
| S3 / lake raw zone | Batch | Immutable landing of historical **daily prices** for the S&P 500. | `data/lake/raw/` on disk |
| Spark | Batch | ELT and the training job. Builds the price/volume feature table and fits the model. | `batch_train` Spark-**role** job (pandas + scikit-learn) — as-built |
| Curated Parquet | Batch | The training set the Spark-role job writes, one feature row per symbol per session. | `data/lake/curated/features/session/` |
| Model registry | Both | The fitted model, the feature list, and the score cutoff. The live scorer loads this. It does not refit during the session. | `data/lake/registry/isolation_forest/current/` |
| FinBERT | Streaming / check | Machine learning on the **near-term** headline. Score 0 to 100. Not a batch lake input. | Local Transformers + PyTorch |
| Isolation Forest | Batch, then stream | Machine learning on **price and volume** features. Trained on the curated table. Applied live once the scorer loads the registry. | scikit-learn in `batch_train`; live apply in `python -m app.live` |
| Perplexity | After the decision | AI usage. Two sentences from the structured alert. The model does not decide the alert. | Settings API key |
| Postgres | Serving | One alert row per symbol per day, including the model score, the thresholds, and the Perplexity text. | Local `ticker_alert_db` (Aurora on a slide = same engine) |

Cassandra, a second relational database, a separate analyst BI tool, a historical news lake, FinBERT fine-tuning, VWAP as a stream stage, and a mandatory AWS production deploy stay off the diagram. One serving database is enough, and the alert screen is the dashboard.

The product universe is the S&P 500. Three paths share that universe with different jobs: the **batch lake** trains Isolation Forest on historical prices; the **live stream** applies that model and the percent rule as the session unfolds (Home Recent); the **Watchlist** is a focus set with on-demand **Scan today** over today’s daily bars and near-term headlines (Today's results). Watchlist is not the training lake — it is the useful session-batch product pass beside Live. History tags each row’s `origin` as live, watchlist, or both. The architecture is the big-data shape the course asked for: a lake, a batch compute job, a log, and a stream processor, with the model crossing from the batch path to the stream path. Minute bars, not raw quotes, are the grain. A session move is the latest trade against the open. Aggregating at the source keeps Kafka and the live scorer on the decision instead of on reaggregation.

## Verdict

Keep batch and streaming as two engines. Give them one **price/volume** feature definition so they cannot drift.

The historical path exists to train the anomaly model on S&P daily history. The streaming path exists to apply that model as the session unfolds and to score near-term headlines as they arrive. Perplexity writes richer news / news+price reasoning after the row is decided. Price-only keeps the deterministic sentence for now. A deterministic sentence stays as the fallback when the API is unavailable.

| Choice | What it means |
|---|---|
| Two engines, one feature list | `batch_train` fits the forest on price history. The live scorer scores the same features from Kafka. |
| Lake plus log | `data/lake` holds training prices. Docker Kafka holds live bars. |
| Live plus Watchlist | Live = continuous feed → Home Recent alerts (S&P 500 or Watchlist scope). Watchlist Scan today = on-demand session pass → Today's results. Same `alerts` table; Origin separates them. |
| Local demo, not AWS prod | Same architecture boxes; S3/Aurora/Dataproc names are optional slide aliases. |
| Three outcomes | News, price, or both. The forest does not require a headline. |
| AI after the decision | Perplexity explains the row. It does not create it. |
| Near-term news only | FinBERT runs on headlines that matter for today’s slice. Old articles are not batch training data. |

## Machine learning

The deck names Isolation Forest and FinBERT and never says which one the alert waits for, or what the training rows are. This is that plan.

FinBERT is the news model. Use the published ProsusAI/finbert weights. A headline is scored 0 to 100, with 50 neutral, and it qualifies when the score is at least the configured distance from 50. Do not fine-tune it. A fine-tune needs labeled headlines this project does not have. Score headlines on the **near-term** path (Scan today; live news topic on the class stream). Do **not** pull months of old articles into the lake. An eight-month-old story does not explain today’s move and does not belong in forest training.

Isolation Forest is the price model, and the batch lake is why it exists. Spark builds one row per symbol per session from historical **bars only**:

- Return of the close versus the prior close.
- Return of the open versus the prior close, the overnight gap.
- Return of the close versus the open, the regular session.
- Volume z-score against the prior 20 sessions.

The forest is fit on those rows. Unsupervised fits this data, because there is no labeled set of true anomalies. The score cutoff is chosen by replaying the same table and seeing which cutoff marks the sessions worth an alert. Spark writes the model, the feature list, and that cutoff into the registry.

Flink computes that same vector on the live window and scores it with the registered model. The preferred live product path is **price first, then news**: when the percent rule or the forest marks a session anomalous, the scorer writes a price alert, then pulls near-term headlines for that symbol, scores them with FinBERT, and upgrades the day to news or news+price when the same Eastern-day slice matches. Watchlist **Scan today** applies the same **percent or forest** price gate and news join on Yahoo daily bars for the focus set (including after the close, and after you change Settings). A strong headline with no price move can still open a news-only row on Scan today. The card shows the percent and the model score when present. A rebuild of recent alert history replays product rules for the watchlist; it does not replace lake training.

## AI usage

Today the service writes a deterministic sentence from the alert fields. That stays as the fallback. The AI step is Perplexity, used the way Vajra already uses it: send the facts, ask for a short answer, store the reply.

After a news or news+price alert row is decided, send Perplexity the structured payload: symbol, time, kind, the percent when present, the FinBERT scores, the thresholds, and the headlines (titles, urls, scores) that fell in the slice. Ask for three to four short sentences: what happened, why the headlines matter (cite titles/urls), how FinBERT reads them, and a cautious forward look. Do not ask it to merely restate that price moved and headlines lined up. Price-only alerts skip this call and keep the rule sentence. If Perplexity is down or slow, show the deterministic sentence. The dashboard reads the row either way. The model never decides whether the alert exists. Together shows the name of the model that wrote it. A check or rebuild asks Perplexity in batches of eight.

## Slide 6 — High-level lambda

Streaming for live detection, batch for training. That split of purpose is what the course asked for. The split of logic is the part to fix: Spark and Flink have to compute the same **price/volume** features, and the stream has to load the model the batch just trained.

The live feed should be minute bars for the S&P 500, written to Kafka. Near-term headlines are scored with FinBERT for the product join; they are not archived into the training lake. Historical **prices** land in the raw zone for forest training.

Kafka stays the bus for minute bars. The batch ingest lands prices in the lake, and the feature definition it uses is the one Flink uses. Spark is the batch engine on the diagram. The raw zone and the curated zone are the lake. Timescale (or Postgres `live_feature_rows`) is the stream feature sink. The registry is how the fitted forest reaches Flink. Correlation is the product join: **price noticed → look up near-term news → evidence or none**, on symbol plus the slice that was in progress, with news-only and price-only still allowed. A dedicated Kafka news topic is optional; a near-term Yahoo pull after the price alert is enough for the local demo. Perplexity runs after that join for news / news+price. The dashboard watches for new alert rows and raises a Mac/Chrome desktop notification plus a tab badge; a failed notification must not lose the alert.

| Step | Verdict | Why |
|---|---|---|
| Live tick feed | Change | Publish minute bars for the S&P 500 onto Kafka. Raw quotes force Flink to reaggregate before it can score. |
| Live / near-term news | Keep | Headlines are the other half of the product. Score them near-term. Do not build a multi-month news lake. |
| Historical OHLCV | Keep | The training set for the forest. |
| Historical news archive | Drop | Old headlines do not explain today’s slice and are not forest features. |
| Kafka ingest | Keep | The streaming half. Topics for bars, near-term headlines, sentiment scores, and anomaly scores. |
| Separate batch ingest | Keep | Land prices into the lake with the same feature definitions the stream uses. |
| Stream feature job | Keep | Flink. Session state, the live feature vector, and a score from the registered model. |
| Spark | Keep | ELT of the price lake, the feature table, and the training job. |
| S3 / lake raw zone | Keep | Landing zone for historical prices. |
| Timescale feature store | Keep | Live feature rows. The alert itself lives in Postgres. |
| Curated lake zone | Keep | Parquet feature rows, one per symbol per session. |
| Alert store | Keep | One row per symbol per day. |
| Model training | Keep | Fit Isolation Forest on curated price/volume rows. |
| Model registry | Keep | Feature list, fitted model, and score cutoff. |
| Sentiment scoring | Keep | FinBERT on near-term headlines, 0 to 100. |
| Anomaly detection | Keep | Registered forest on the live price/volume vector. |
| Correlation | Keep | Join on symbol and slice. Allow price-only and news-only. |
| Perplexity summary | Keep | Richer news / news+price reasoning after the decision. Price-only stays deterministic. Deterministic fallback. |
| API and dashboard | Keep | Home Recent, Watchlist Today's results, and History with Origin all read the alert table. |
| Notification | Keep | Desktop (OS) notification and tab badge after the row exists. Slack and email are not used. |

## Slide 7 — Batch historical ELT

Extract and load, then transform. That order is what makes the lake reprocessable when the feature list changes.

The price archive is historical S&P daily bars landed in the raw zone. There is **no** news archive on this path. Spark builds the feature table: the three returns and the volume z-score against 20 sessions. That table is the curated Parquet.

The training job reads the curated table, fits Isolation Forest, chooses the score cutoff by replaying the table, and writes the model to the registry. FinBERT is not trained here and is not an input to these rows. The inference service on this slide is Flink loading the registry.

Postgres holds the alert rows and is the reporting database. The alert history is the analyst dashboard.

| Step | Verdict | Why |
|---|---|---|
| Price archive | Keep | Land historical S&P daily bars in the raw zone. |
| News archive | Drop | Not used for forest training. Near-term FinBERT only. |
| Extract and load raw | Keep | Land prices first, then transform. |
| S3 / lake raw zone | Keep | Big-data landing zone for the batch path. |
| Schema check and dedup | Keep | Clean symbol and session keys on the price land. |
| Spark | Keep | Feature table and Isolation Forest training. Same features as Flink. |
| Feature engineering | Keep | Three returns and volume z-score versus 20 sessions. No FinBERT aggregates. |
| Curated Parquet | Keep | The training set. One row per symbol per session. |
| Training pipeline | Keep | Fit the forest and pick the cutoff by replaying this table. |
| Isolation Forest | Keep | Unsupervised price/volume anomaly model. |
| FinBERT fine-tune | Drop | ProsusAI/finbert is already trained. Fine-tuning needs labels this project does not have. |
| FinBERT aggregates in training rows | Drop | News is near-term product logic, not batch forest input. |
| Inference from the registry | Keep | Flink loads the fitted model. |
| Reporting database | Keep | Postgres holds the alerts. |
| Analyst dashboard | Drop | The alert history is the dashboard. |

## Slide 8 — Streaming ETL

Kafka, Flink, FinBERT, and Timescale are the streaming half of the big-data architecture. Several boxes on this slide are the same step drawn twice. Collapse those. Leave the engines.

The producer writing minute bars to Kafka is the extract. Windowed features and the volume z-score are the Flink job. VWAP is not a feature the forest uses. Flink holds the session, builds the feature vector, and scores it with the registered model. The threshold gate is that registered cutoff, shared with the batch replay.

Timescale stores the live feature rows. FinBERT scores near-term headlines and publishes the score. Correlation consumes that topic and the anomaly score. It emits news, price, or both.

Cassandra is the box to remove. One alert per symbol per day is a Postgres write. Perplexity, the dashboard, and desktop notifications sit after the Postgres write.

| Step | Verdict | Why |
|---|---|---|
| Market websocket | Change | Publish S&P minute bars to Kafka. |
| Extract, then Kafka bars | Change | The producer writing to Kafka is the extract. One raw-bars topic. |
| Volume z-score and session returns | Keep | Same features Spark trained on. VWAP is not one of them. |
| Flink | Keep | Session state, live vector, score from the registry. |
| Threshold gate | Keep | Cutoff stored with the model. |
| Load into TimescaleDB | Keep | Stream feature sink. |
| Near-term news after price | Change | After a live price / forest alert, fetch near-term headlines for that symbol. Optional Kafka news topic. |
| FinBERT on those headlines | Keep | One scoring step for near-term news (0–100). |
| Correlation engine | Keep | Price first, then news for the same slice. Emit news, price, or both. |
| Cassandra | Drop | Postgres holds the alert. |
| Perplexity | Keep | Three to four sentences for news / news+price after the row is stored. Price-only stays deterministic. |
| Dashboard | Keep | Read the alert table. |
| Desktop notification and tab badge | Keep | Consumer of the alert row in the open dashboard tab (Mac/Chrome Notification Center). |

## Slide 9 — End-to-end sequence

The happy path is **price noticed → news looked up → evidence or none**. Days can stay price-only when no same-day headline matches, or news-only when FinBERT clears the gate with no price move (Scan today). The model score appears on the sequence when the forest trips. What happened tags the percent/forest gate case (`percent only` / `percent + forest` / `forest only` / `neither gate`) and names the price-trigger cases (#1 percent, #2 forest, #3–#6 features, #7 volume-spike note) — tables in [architecture.md](architecture.md) and [data-sources.md](data-sources.md).

Stream a minute bar. Flink micro-batches the Kafka topic. Compute the trained returns and the volume z-score. Write a price alert when the percent rule or the registered cutoff trips. Then fetch near-term headlines for that symbol, score them with FinBERT, and upgrade the day only when the publish time falls in the slice that moved.

The window is the slice in progress: the overnight gap before 9:30 AM Eastern, the regular session until 4:00 PM, or the close after that. Skip stale prior-day stories.

The structured payload is symbol, time, kind, percent, FinBERT score when present, Isolation Forest score when present, and the thresholds. Perplexity turns news / news+price payloads into richer short reasoning.

| Step | Verdict | Why |
|---|---|---|
| Stream a live bar | Change | Stream the minute bar onto Kafka. |
| Flink consumes the topic | Keep | Micro-batch consumption of Kafka is the stream path. |
| Build the trained feature vector | Change | Session returns and the volume z-score only. |
| Anomaly / percent gate | Keep | Score with the registered model; percent rule remains. |
| Upsert price when the gate trips | Keep | Price-first product path. |
| Fetch near-term headlines for that symbol | Change | Look up news after the price alert; optional Kafka news bus. |
| Score those headlines | Keep | FinBERT 0–100 on the near-term set. |
| Correlate inside the slice | Change | Name the window: gap, session, or close. Keep price-only when nothing matches. |
| Structured payload | Keep | Symbol, time, kind, percent, scores, thresholds. |
| Perplexity summary | Keep | Richer news / news+price write-up from that payload. Template fallback if the call fails. |

## Slide 12 — No-code replacement

A workflow tool can fire a webhook and can call Perplexity. It cannot hold Flink session state, the Spark training job, or the slice join. That is the big-data argument on this slide. Drop the claim of a regulatory audit trail and a latency SLA the rest of the deck never defines. The threshold snapshot and the model version on the alert row are the audit trail you can defend. Desktop notifications in the dashboard are enough for a class demo; they are not a substitute for the stream path.

## What the course still needs to see

A reviewer should be able to point at the diagram and name the batch path, the stream path, the lake, the model that crosses from one to the other, and the AI call that does not — all runnable locally.

- Batch **as-built**: `data/lake` raw prices, `batch_train` (Spark role), curated Parquet, Isolation Forest, registry — **training only**. Automatic first-boot land+train when the lake is empty, plus a daily incremental **Refresh lake + retrain** that resumes from each symbol’s latest local date (and skips Yahoo + retrain when already current through the last completed session), keeps the registry from going stale after the cold-start land. Settings buttons remain manual overrides.
- Watchlist **Scan today** focus session: last completed weekday before the cash open / on weekends; today during RTH or after the close — so pre-market demos are not empty.
- Streaming **as-built**: Docker Kafka, `python -m app.live` percent-rule + Isolation Forest, live **price → near-term news** upgrade, `live_feature_rows` sink, Home Recent, desktop notifications.
- Watchlist **as-built**: focus set, Scan today over the focus-session bars/headlines with the same **percent or forest** gate as live, Today's results panel, `alerts.origin`, rebuild of recent sessions.
- Streaming **local final gap** (deferred): optional Kafka news topic. Forest-aware price-only wording and evidence-story alignment grades are as-built.
- The handoff: live scorer scores Kafka bars with the model `batch_train` fitted on price history.
- AI: Perplexity writes richer news / news+price reasoning from the finished payload, with the template sentence as fallback; price-only stays deterministic, with richer forest-aware wording when Isolation Forest fires.
- Product rules that stay: S&P 500 universe, one alert per symbol per day, three outcomes, headline joined to the slice in progress (price first on live; same join on Watchlist Scan today).
- Deploy: local machine. AWS production is not part of the final target.

## Source

Deck and PDF, CISC 525, 30 August 2026: `CISC 525 - Equity Anomaly and Sentiment Platform`. The as-built and local final target diagrams are in [architecture.md](architecture.md). This note is the revised architecture for that proposal. The local FastAPI service covers the S&P 500: **Live** (`python -m app.live`) for continuous price → news alerts on Home Recent; **Watchlist Scan today** for an on-demand session pass over the focus set; Perplexity when a key is saved; `live_feature_rows` and a Home “Live alerts on” cue; History with Origin; desktop notifications and a tab badge; and a batch land of index daily prices into the lake for **forest training**. `batch_train` curates session price/volume features and fits Isolation Forest into a local model registry (the Spark training box on the diagram, run with pandas/scikit-learn — not a Dataproc cluster). Settings stores the key as dots and offers five ChatGPT, five OpenAI, and five Gemini models. Together shows the name of the model that wrote it. A check or rebuild asks Perplexity in batches of eight. The deterministic sentence is the fallback. Live price → near-term news, Watchlist forest parity, forest-aware price-only wording, and incremental lake refresh + retrain are as-built; the remaining local final gap is an optional Kafka news topic (deferred). Historical headlines are not part of the design. AWS production deploy is out of scope for the demo.
