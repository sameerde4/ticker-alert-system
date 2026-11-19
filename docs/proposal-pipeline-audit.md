# Proposal pipeline audit

CISC 525 deck and PDF, 30 August 2026. *Real-Time Equity Anomaly & Sentiment Fusion Platform.* Sameer De, Mahir Jhaveri, Gaurav Gulia, Runsen Ning.

Verdicts are against two constraints at once. The product raises one alert per symbol per day for the **S&P 500**. The course requires a big-data architecture: a batch path over historical **price** data, a streaming path over live data, a machine-learning model trained on the batch, and an AI step that writes the alert in plain English. The revised target diagrams live in [architecture.md](architecture.md). The tables below say what stayed from the original deck, what changed, and what came off.

## What the professor needs to see

The architecture has to read as big data on the diagram, not only as a Python job that happens to call Yahoo. These are the boxes that carry that, and each one has a job:

| Piece | Path | Job |
|---|---|---|
| Kafka | Streaming | The bus. Raw bars, near-term headlines, sentiment scores, and anomaly scores are separate topics. |
| Flink | Streaming | Stateful windows. Holds the session open, the latest price, and volume, and scores the live price/volume feature vector. |
| TimescaleDB | Streaming | Sink for the live feature rows. This is the time-series store on the diagram. |
| S3 / lake raw zone | Batch | Immutable landing of historical **daily prices** for the S&P 500. |
| Spark | Batch | ELT and the training job. Builds the price/volume feature table and fits the model. |
| Curated Parquet | Batch | The training set Spark writes, one feature row per symbol per session. |
| Model registry | Both | The fitted model, the feature list, and the score cutoff. Flink loads this. It does not refit during the session. |
| FinBERT | Streaming / check | Machine learning on the **near-term** headline. Score 0 to 100. Not a batch lake input. |
| Isolation Forest | Batch, then stream | Machine learning on **price and volume** features. Trained on the curated table. Applied by Flink to the live vector. |
| Perplexity | After the decision | AI usage. Two sentences from the structured alert. The model does not decide the alert. |
| Postgres | Serving | One alert row per symbol per day, including the model score, the thresholds, and the Perplexity text. |

Cassandra, a second relational database, a separate analyst BI tool, a historical news lake, FinBERT fine-tuning, and VWAP as a stream stage stay off the diagram. One serving database is enough, and the alert screen is the dashboard. Aurora is the same engine as Postgres if the stack slide needs an AWS name.

The product universe is the S&P 500. A watchlist of constituents drives Run check; the live and batch paths cover the index. The architecture is the big-data shape the course asked for: a lake, a batch compute engine, a log, and a stream processor, with the model crossing from the batch path to the stream path. Minute bars, not raw quotes, are the grain. A session move is the latest trade against the open. Aggregating at the source keeps Kafka and Flink on the decision instead of on reaggregation.

## Verdict

Keep batch and streaming as two engines. Give them one **price/volume** feature definition so they cannot drift.

The historical path exists to train the anomaly model on S&P daily history. The streaming path exists to apply that model as the session unfolds and to score near-term headlines as they arrive. Perplexity writes the two-sentence summary after the row is decided. A deterministic sentence stays as the fallback when the API is unavailable, which is what the app writes today.

| Choice | What it means |
|---|---|
| Two engines, one feature list | Spark fits the forest on price history. Flink scores the same features live. |
| Lake plus log | The lake holds training prices. Kafka holds live bars and near-term news. |
| Three outcomes | News, price, or both. The forest does not require a headline. |
| AI after the decision | Perplexity explains the row. It does not create it. |
| Near-term news only | FinBERT runs on headlines that matter for today’s slice. Old articles are not batch training data. |

## Machine learning

The deck names Isolation Forest and FinBERT and never says which one the alert waits for, or what the training rows are. This is that plan.

FinBERT is the news model. Use the published ProsusAI/finbert weights. A headline is scored 0 to 100, with 50 neutral, and it qualifies when the score is at least the configured distance from 50. Do not fine-tune it. A fine-tune needs labeled headlines this project does not have. Score headlines on the **near-term** path (Run check today; live news topic on the class stream). Do **not** pull months of old articles into the lake. An eight-month-old story does not explain today’s move and does not belong in forest training.

Isolation Forest is the price model, and the batch lake is why it exists. Spark builds one row per symbol per session from historical **bars only**:

- Return of the close versus the prior close.
- Return of the open versus the prior close, the overnight gap.
- Return of the close versus the open, the regular session.
- Volume z-score against the prior 20 sessions.

The forest is fit on those rows. Unsupervised fits this data, because there is no labeled set of true anomalies. The score cutoff is chosen by replaying the same table and seeing which cutoff marks the sessions worth an alert. Spark writes the model, the feature list, and that cutoff into the registry.

Flink computes that same vector on the live window and scores it with the registered model. The alert fires when the model score crosses the cutoff, or when FinBERT crosses the sentiment gate on a near-term headline, or both. The card shows the percent and the model score. A rebuild of recent alert history replays product rules; it does not replace lake training.

## AI usage

Today the service writes a deterministic sentence from the alert fields. That stays as the fallback. The AI step is Perplexity, used the way Vajra already uses it: send the facts, ask for a short answer, store the reply.

After the alert row is decided, send Perplexity the structured payload: symbol, time, kind, the percent, the FinBERT score when present, the Isolation Forest score when present, the thresholds, and the headlines that fell in the slice. Ask for two sentences. The first says what moved. The second gives the candidate reason when a headline lined up with that slice, and says that no headline lined up when none did. Store the reply on the alert. If Perplexity is down or slow, show the deterministic sentence. The dashboard reads the row either way. The model never decides whether the alert exists. Together shows the name of the model that wrote it. A check or rebuild asks Perplexity in batches of eight.

## Slide 6 — High-level lambda

Streaming for live detection, batch for training. That split of purpose is what the course asked for. The split of logic is the part to fix: Spark and Flink have to compute the same **price/volume** features, and the stream has to load the model the batch just trained.

The live feed should be minute bars for the S&P 500, written to Kafka. Near-term headlines are scored with FinBERT for the product join; they are not archived into the training lake. Historical **prices** land in the raw zone for forest training.

Kafka stays the bus. The batch ingest lands prices in the lake, and the feature definition it uses is the one Flink uses. Spark is the batch engine on the diagram. The raw zone and the curated zone are the lake. Timescale is the stream feature sink. The registry is how the fitted forest reaches Flink. Correlation stays the product join: symbol plus the slice that was in progress, with news-only and price-only allowed. Perplexity runs after that join. The dashboard watches for new alert rows and raises a Mac/Chrome desktop notification plus a tab badge; a failed notification must not lose the alert.

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
| Perplexity summary | Keep | Two sentences after the decision. Deterministic fallback. |
| API and dashboard | Keep | One screen reads the alert table. |
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
| Near-term news, then Kafka | Change | One raw-news topic for headlines that matter now. |
| FinBERT, then the score topic | Keep | One scoring step for near-term news. |
| Correlation engine | Keep | Join symbol and slice. Emit news, price, or both. |
| Cassandra | Drop | Postgres holds the alert. |
| Perplexity | Keep | Two sentences after the row is stored. The deterministic sentence remains the fallback. |
| Dashboard | Keep | Read the alert table. |
| Desktop notification and tab badge | Keep | Consumer of the alert row in the open dashboard tab (Mac/Chrome Notification Center). |

## Slide 9 — End-to-end sequence

The happy path on the slide always has both a tick and a headline. The product also has days with only one of them, and the model score has to appear in the sequence.

Stream a minute bar. Flink micro-batches the Kafka topic. Compute the trained returns and the volume z-score.

The window is the slice in progress: the overnight gap before 9:30 AM Eastern, the regular session until 4:00 PM, or the close after that. The sequence has to allow the price alert and the news alert to stay unjoined when the slice does not match.

The structured payload is symbol, time, kind, percent, FinBERT score when present, Isolation Forest score when present, and the thresholds. Perplexity turns that payload into two sentences.

| Step | Verdict | Why |
|---|---|---|
| Stream a live bar | Change | Stream the minute bar onto Kafka. |
| Flink consumes the topic | Keep | Micro-batch consumption of Kafka is the stream path. |
| Build the trained feature vector | Change | Session returns and the volume z-score only. |
| Anomaly score | Keep | Score with the registered model. |
| Score the near-term headline | Keep | FinBERT, independent of the price flag. |
| Correlate inside the slice | Change | Name the window: gap, session, or close. Allow one side alone. |
| Structured payload | Keep | Symbol, time, kind, percent, scores, thresholds. |
| Perplexity summary | Keep | Two sentences from that payload. Template fallback if the call fails. |

## Slide 12 — No-code replacement

A workflow tool can fire a webhook and can call Perplexity. It cannot hold Flink session state, the Spark training job, or the slice join. That is the big-data argument on this slide. Drop the claim of a regulatory audit trail and a latency SLA the rest of the deck never defines. The threshold snapshot and the model version on the alert row are the audit trail you can defend. Desktop notifications in the dashboard are enough for a class demo; they are not a substitute for the stream path.

## What the course still needs to see

A reviewer should be able to point at the diagram and name the batch engine, the stream engine, the lake, the model that crosses from one to the other, and the AI call that does not.

- Batch: lake raw prices, Spark, curated Parquet, Isolation Forest, registry.
- Streaming: Kafka, Flink, FinBERT on near-term news, Timescale.
- The handoff: Flink scores live bars with the model Spark trained on price history.
- AI: Perplexity writes two sentences from the finished payload, with the template sentence as fallback.
- Product rules that stay: S&P 500 universe, one alert per symbol per day, three outcomes, and the headline joined to the slice that was in progress.

## Source

Deck and PDF, CISC 525, 30 August 2026: `CISC 525 - Equity Anomaly and Sentiment Platform`. The revised target diagrams are in [architecture.md](architecture.md). This note is the revised architecture for that proposal. The local FastAPI service covers the S&P 500: Yahoo bars and FinBERT on a check, Perplexity when a key is saved, a Kafka consumer for open→last price alerts (`python -m app.live`) with a Home “Live alerts on” cue, desktop notifications and a tab badge when new alerts arrive, and a batch land of index daily prices into the lake. Settings stores the key as dots and offers five ChatGPT, five OpenAI, and five Gemini models. Together shows the name of the model that wrote it. A check or rebuild asks Perplexity in batches of eight. The deterministic sentence is the fallback. Flink scoring and Isolation Forest training complete the class stack on that price lake and Kafka path. Historical headlines are not part of the design.
