# Proposal pipeline audit

CISC 525 deck and PDF, 30 August 2026. *Real-Time Equity Anomaly & Sentiment Fusion Platform.* Sameer De, Mahir Jhaveri, Gaurav Gulia, Runsen Ning.

Verdicts are against two constraints at once. The product raises one alert per symbol per day. The course requires a big-data architecture: a batch path over historical data, a streaming path over live data, a machine-learning model trained on the batch, and an AI step that writes the alert in plain English. Diagram steps match the deck as transcribed in [architecture.md](architecture.md).

## What the professor needs to see

The architecture has to read as big data on the diagram, not only as a Python job that happens to call Yahoo. These are the boxes that carry that, and each one has a job:

| Piece | Path | Job |
|---|---|---|
| Kafka | Streaming | The bus. Raw bars, raw headlines, sentiment scores, and anomaly scores are separate topics. |
| Flink | Streaming | Stateful windows. Holds the session open, the latest price, volume, and the headline slice, and scores the live feature vector. |
| TimescaleDB | Streaming | Sink for the live feature rows. This is the time-series store on the diagram. |
| S3 raw zone | Batch | Immutable landing of historical prices and the headlines we have persisted. |
| Spark | Batch | ELT and the training job. Builds the feature table and fits the model. |
| S3 curated Parquet | Batch | The training set Spark writes, one feature row per symbol per session. |
| Model registry | Both | The fitted model, the feature list, and the score cutoff. Flink loads this. It does not refit during the session. |
| FinBERT | Streaming | Machine learning on the headline. Score 0 to 100, published onto the sentiment topic. |
| Isolation Forest | Batch, then stream | Machine learning on the price and volume features. Trained on the curated table. Applied by Flink to the live vector. |
| Perplexity | After the decision | AI usage. Two sentences from the structured alert. The model does not decide the alert. |
| Postgres | Serving | One alert row per symbol per day, including the model score, the thresholds, and the Perplexity text. |

Cassandra, a second relational database, and a separate analyst BI tool stay off the diagram. One serving database is enough, and the alert screen is the dashboard. Aurora is the same engine as Postgres if the stack slide needs an AWS name.

The watchlist is about a dozen symbols, so this volume is not warehouse-scale. The architecture is still the big-data shape the course asked for: a lake, a batch compute engine, a log, and a stream processor, with the model crossing from the batch path to the stream path. Minute bars, not raw quotes, are the grain. A session move is the latest trade against the open. Aggregating at the source keeps Kafka and Flink on the decision instead of on reaggregation.

## Verdict

Keep batch and streaming as two engines. Give them one feature definition so they cannot drift.

The historical path exists to train the anomaly model. The streaming path exists to apply that model as the session unfolds and to score headlines as they arrive. Perplexity writes the two-sentence summary after the row is decided. A deterministic sentence stays as the fallback when the API is unavailable, which is what the app writes today.

| Choice | What it means |
|---|---|
| Two engines, one feature list | Spark fits the model on history. Flink scores the same features live. |
| Lake plus log | S3 holds the training set. Kafka holds the live events. |
| Three outcomes | News, price, or both. The model does not require both sides. |
| AI after the decision | Perplexity explains the row. It does not create it. |

## Machine learning

The deck names Isolation Forest and FinBERT and never says which one the alert waits for, or what the training rows are. This is that plan.

FinBERT is the news model. Use the published ProsusAI/finbert weights. A headline is scored 0 to 100, with 50 neutral, and it qualifies when the score is at least the configured distance from 50. Do not fine-tune it. A fine-tune needs labeled headlines this project does not have.

Isolation Forest is the price model, and the batch lake is why it exists. Spark builds one row per symbol per session from the historical bars and the stored headlines:

- Return of the close versus the prior close.
- Return of the open versus the prior close, the overnight gap.
- Return of the close versus the open, the regular session.
- Volume z-score against the prior 20 sessions.
- Count of qualifying headlines in each slice, and their average FinBERT score.

The forest is fit on those rows. Unsupervised fits this data, because there is no labeled set of true anomalies. The score cutoff is chosen by replaying the same table and seeing which cutoff marks the sessions worth an alert. Spark writes the model, the feature list, and that cutoff into the registry.

Flink computes that same vector on the live window and scores it with the registered model. The alert fires when the model score crosses the cutoff, or when FinBERT crosses the sentiment gate, or both. The card shows the percent and the model score, so a reader can see the move and not only a forest score. A rebuild of history calls the same feature function. It does not fit a second model with a second definition of "return."

## AI usage

Today the service writes a deterministic sentence from the alert fields. That stays as the fallback. The AI step is Perplexity, used the way Vajra already uses it: send the facts, ask for a short answer, store the reply.

After the alert row is decided, send Perplexity the structured payload: symbol, time, kind, the percent, the FinBERT score, the Isolation Forest score, the thresholds, and the headlines that fell in the slice. Ask for two sentences. The first says what moved. The second gives the candidate reason when a headline lined up with that slice, and says that no headline lined up when none did. Store the reply on the alert. If Perplexity is down or slow, show the deterministic sentence. The dashboard reads the row either way. The model never decides whether the alert exists.

## Slide 6 — High-level lambda

Streaming for live detection, batch for training. That split of purpose is what the course asked for. The split of logic is the part to fix: Spark and Flink have to compute the same features, and the stream has to load the model the batch just trained.

The live feed should be minute bars for the watchlist, written to Kafka. The live news feed is real, and every headline FinBERT scores has to be stored, because that store is the historical news the batch path trains on. Yahoo's list is a recent page, not an archive. Historical prices land in the raw zone for the same reason.

Kafka stays the bus. The batch ingest lands in the lake, and the feature definition it uses is the one Flink uses. Spark is the batch engine on the diagram. The raw zone and the curated zone are the lake. Timescale is the stream feature sink. The registry is how the fitted forest reaches Flink. Correlation stays the product join: symbol plus the slice that was in progress, with news-only and price-only allowed. Perplexity runs after that join. Slack or email is a webhook after the row exists, and a failed notification must not lose the alert.

| Step | Verdict | Why |
|---|---|---|
| Live tick feed | Change | Publish minute bars for the watchlist onto Kafka. Raw quotes force Flink to reaggregate before it can score. |
| Live news API | Keep | Headlines are the other half of the product. Persist each one FinBERT scores. That persisted set is the news history. |
| Historical OHLCV | Keep | The training set for the forest, and the replay set for a past session. |
| Historical news archive | Change | Build it by storing scored headlines. Do not assume a vendor archive you cannot download. |
| Kafka ingest | Keep | The streaming half of the architecture. Separate topics for bars, headlines, sentiment scores, and anomaly scores. |
| Separate batch ingest | Keep | The batch half. It must write features with the same definitions the stream uses, into the lake rather than a second schema. |
| Stream feature job | Keep | Flink. Session state, the live feature vector, and a score from the registered model. |
| Spark | Keep | The batch engine the diagram needs. ELT of the lake, the feature table, and the training job. |
| S3 raw zone | Keep | The landing zone. This is the big-data storage box. Replay and training both read from it. |
| Timescale feature store | Keep | The stream sink. Live feature rows land here. The alert itself lives in Postgres. |
| Curated lake zone | Keep | Parquet feature rows, one per symbol per session. This is the training set. |
| Alert store | Keep | One row per symbol per day, with the model score and the thresholds that were in force. |
| Model training | Keep | Fit Isolation Forest on the curated table. The batch path exists for this. |
| Model registry | Keep | Feature list, fitted model, and score cutoff. Flink loads it. A settings row is not a registry. |
| Sentiment scoring | Keep | FinBERT on the stream, 0 to 100, published to the sentiment topic. |
| Anomaly detection | Keep | The registered forest, applied by Flink to the live vector. The card also shows the percent. |
| Correlation | Keep | Join on symbol and on the price slice in progress. Allow price-only and news-only. |
| Perplexity summary | Keep | Two sentences from the structured payload, after the decision. Deterministic sentence if the call fails. |
| API and dashboard | Keep | One screen reads the alert table. |
| Notification | Keep | Slack or email after the row exists. It is not part of detection. |

## Slide 7 — Batch historical ELT

Extract and load, then transform. That order is what makes the lake reprocessable when the feature list changes.

The price archive is historical bars landed in the raw zone. The news archive is the headlines the stream has already scored and stored, landed the same way. Dedup on symbol plus URL, or title plus publish time, because news APIs resend the same story. Spark then builds the feature table: the three returns, the volume z-score against 20 sessions, and the FinBERT aggregates by slice. That table is the curated Parquet.

The training job reads the curated table, fits Isolation Forest, chooses the score cutoff by replaying the table, and writes the model to the registry. FinBERT is not trained here. Its weights are already a financial-language model, and this project has no labels to fine-tune them. The inference service on this slide is Flink loading the registry. It is not a second scoring implementation.

Postgres holds the alert rows and is the reporting database. The alert history is the analyst dashboard.

| Step | Verdict | Why |
|---|---|---|
| Price archive | Keep | Land historical bars in the raw zone. The forest and the replay both read them. |
| News archive | Change | Persist scored headlines and land those. That is the archive the batch path can actually train on. |
| Extract and load raw | Keep | Land first, then transform. A rule or feature change can rebuild the curated table from the raw zone. |
| S3 raw zone | Keep | The big-data landing zone for the batch path. |
| Schema check and dedup | Keep | News APIs resend the same story. Dedup on symbol plus URL, or title plus publish time. |
| Spark | Keep | The batch compute engine. Feature table and Isolation Forest training. Same feature definitions as Flink. |
| Feature engineering | Keep | Three returns, volume z-score versus 20 sessions, and FinBERT aggregates by slice. |
| Curated Parquet | Keep | The training set. One row per symbol per session. The alert table stays in Postgres. |
| Training pipeline | Keep | Fit the forest and pick the cutoff by replaying this table. |
| Isolation Forest | Keep | The machine-learning model the batch path is for. Unsupervised, so it does not need labeled anomalies. |
| FinBERT fine-tune | Drop | ProsusAI/finbert is already trained on financial text. Fine-tuning needs labels this project does not have. |
| Inference from the registry | Keep | Flink loads the fitted model. Training on the batch path is wasted if the stream computes a different score. |
| Reporting database | Keep | Postgres holds the alerts. Aurora is the same engine if the stack slide needs the AWS name. |
| Analyst dashboard | Drop | The alert history is the dashboard. A second BI tool does not add a big-data box. |

## Slide 8 — Streaming ETL

Kafka, Flink, FinBERT, and Timescale are the streaming half of the big-data architecture. Several boxes on this slide are the same step drawn twice. Collapse those. Leave the engines.

The producer writing minute bars to Kafka is the extract. A box in front of Kafka adds no step. The same is true on the news side. Windowed features and the volume z-score are the Flink job, not a stage before it. VWAP is not a feature the forest uses. Flink holds the session, builds the feature vector, and scores it with the registered model. The threshold gate is that registered cutoff, shared with the batch replay.

Timescale stores the live feature rows. That write is the stream sink on the diagram. The alert decision reads the score. It does not wait on the database write. FinBERT is one step: score the headline and publish the score. Correlation consumes that topic and the anomaly score. It emits news, price, or both. A diagram that requires both sides drops a strong story on a quiet tape, and a move with no matching story.

Cassandra is the box to remove. One alert per symbol per day is a Postgres write, and Cassandra does not make the architecture more visibly big-data once Kafka, Flink, and S3 are on the diagram. Perplexity, the dashboard, and Slack sit after the Postgres write.

| Step | Verdict | Why |
|---|---|---|
| Market websocket | Change | Publish minute bars for the watchlist to Kafka. The whole-market quote firehose is the wrong grain. |
| Extract, then Kafka bars | Change | The producer writing to Kafka is the extract. One raw-bars topic. |
| Volume z-score and session returns | Keep | These are Flink features, and they are the same features Spark trained on. VWAP is not one of them. |
| Flink | Keep | The stream processor. Session state, live vector, score from the registry. |
| Threshold gate | Keep | The cutoff stored with the model. The batch replay uses the same number. |
| Load into TimescaleDB | Keep | The time-series sink for live feature rows. The alert row is a separate write to Postgres. |
| News extract, then Kafka | Change | One raw-news topic. The producer is the extract. |
| FinBERT, then the score topic | Keep | One scoring step. Publish the 0 to 100 score. Correlation consumes that topic. |
| Correlation engine | Keep | Join symbol and slice. Emit news, price, or both. |
| Cassandra | Drop | Postgres holds the alert. Cassandra repeats that job and is not the big-data signal. |
| Perplexity | Keep | Two sentences after the row is stored. The deterministic sentence remains the fallback. |
| Dashboard | Keep | Read the alert table. Render the stored summary. |
| Slack or email | Keep | A consumer of the alert row. Failure to notify must not lose the alert. |

## Slide 9 — End-to-end sequence

The happy path on the slide always has both a tick and a headline. The product also has days with only one of them, and the model score has to appear in the sequence.

Stream a minute bar, or the latest trade against the open. Streaming a raw tick forces Flink to reaggregate before it can build the feature vector. "Consume a tick batch" is the honest shape: Flink micro-batches the Kafka topic. That is still stream processing. Rolling volatility is a different detector from the returns the forest was trained on. Compute those returns, and keep the volume z-score.

The window is the slice in progress: the overnight gap before 9:30 AM Eastern, the regular session until 4:00 PM, or the close after that. A few seconds misses the headline that prints later and explains the move. Lumentum on 13 November 2026 is the example: the close was down 4.49%, and the strong stories were in the gap and the midday session, both under 3%. The sequence has to allow the price alert and the news alert to stay unjoined when the slice does not match.

The structured payload is symbol, time, kind, percent, FinBERT score, Isolation Forest score, and the thresholds. Perplexity turns that payload into two sentences. The payload is what gets stored either way.

| Step | Verdict | Why |
|---|---|---|
| Stream a live bar | Change | Stream the minute bar or the latest trade against the open, onto Kafka. |
| Flink consumes the topic | Keep | Micro-batch consumption of Kafka is the stream path. |
| Build the trained feature vector | Change | Session returns and the volume z-score. Those are the features the forest was fit on. |
| Anomaly score | Keep | Score the vector with the registered model. Flag only when the registered cutoff trips. |
| Score the headline | Keep | FinBERT, independent of the price flag. A strong story with a quiet tape is still an alert. |
| Correlate inside the slice | Change | Name the window: gap, session, or close. Allow one side to alert alone. |
| Structured payload | Keep | Symbol, time, kind, percent, FinBERT score, forest score, and the thresholds. |
| Perplexity summary | Keep | Two sentences from that payload. Fall back to the template sentence if the call fails. |

## Slide 12 — No-code replacement

A workflow tool can send Slack and can call Perplexity. It cannot hold Flink session state, the Spark training job, or the slice join. That is the big-data argument on this slide, and it is the one to make. Drop the claim of a regulatory audit trail and a latency SLA the rest of the deck never defines. The threshold snapshot and the model version on the alert row are the audit trail you can defend.

## What the course still needs to see

A reviewer should be able to point at the diagram and name the batch engine, the stream engine, the lake, the model that crosses from one to the other, and the AI call that does not.

- Batch: S3 raw, Spark, curated Parquet, Isolation Forest, registry.
- Streaming: Kafka, Flink, FinBERT, Timescale.
- The handoff: Flink scores live bars with the model Spark trained.
- AI: Perplexity writes two sentences from the finished payload, with the template sentence as fallback.
- Product rules that stay: one alert per symbol per day, three outcomes, and the headline joined to the slice that was in progress.

## Source

Deck and PDF, CISC 525, 30 August 2026: `CISC 525 - Equity Anomaly and Sentiment Platform`. Diagrams as transcribed in [architecture.md](architecture.md). This note is the revised architecture for that proposal. The local FastAPI service runs Yahoo bars, local FinBERT, and a Perplexity summary when a key is saved. Settings stores the key as dots and offers five ChatGPT, five OpenAI, and five Gemini models. Together shows the name of the model that wrote it. The deterministic sentence is the fallback. Kafka, Flink, Spark, and the forest are still the target this document describes.
