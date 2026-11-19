# Alert service

FastAPI process for the S&P 500 Alert System. Setup, the migration, and the run command are in the [repository README](../README.md). The class architecture (batch lake for training, live stream, Watchlist Scan today, Isolation Forest, Perplexity) is [docs/proposal-pipeline-audit.md](../docs/proposal-pipeline-audit.md). Diagrams for Live vs Watchlist, the running check path, the live price stream, and the full class stack are in [docs/architecture.md](../docs/architecture.md). This process serves the UI tabs (Home Recent, Watchlist Today's results, History with Origin) and runs a Kafka consumer for session-move price alerts (`python -m app.live`). Flink and Spark are the stream and batch engines on the class diagrams. A saved Perplexity key writes richer news / news + price reasoning (price-only stays deterministic; Isolation Forest alerts get richer forest-aware wording without Perplexity). The selected model is one of five ChatGPT, five OpenAI, or five Gemini choices. Its name is stored on the alert and shown under Together. A check sends at most eight alerts in one reply. When Scan today or live adds alerts, the open UI can raise a Mac/Chrome desktop notification and a tab badge (`ui/sw-notifications.js`). Slack and email are not used.

| Path | Purpose |
|---|---|
| `app/engine.py` | Price, news, and fusion rules. A headline is a candidate reason only for the price slice it was published in |
| `app/sentiment.py` | Keyword sentiment lexicon |
| `app/finbert.py` | Local ProsusAI/finbert score from 0 to 100, plus confidence and the three class shares |
| `app/scoring.py` | Sends every headline to FinBERT. The lexicon remains in the repo and is not used by a check |
| `app/prices.py` | Yahoo daily bars, the open and latest price during the cash session, and the sector or fund category |
| `app/symbols.py` | Ticker normalization, the local symbol list, and which symbols trade all day |
| `app/news.py` | Yahoo headlines |
| `app/perplexity.py` | JSON payload of price changes, headlines, and FinBERT scores. Richer news / news+price reply replaces Together and stores the model name |
| `app/perplexity_catalog.py` | Five ChatGPT, five OpenAI, and five Gemini model choices |
| `app/checks.py` | One watchlist pass, the admin rebuild of recent sessions, and Perplexity calls of at most eight alerts |
| `app/live_session.py` | Open → latest state from Kafka minute bars during the cash session |
| `app/live_alerts.py` | Session-move price drafts; does not overwrite news / news_price rows |
| `app/live_consumer.py` | Kafka consumer for `prices.raw.bars` → percent + Isolation Forest price alerts and `live_feature_rows` |
| `app/forest_live.py` | Load lake registry and score live session feature vectors (Flink role) |
| `app/forest_wording.py` | Deterministic forest-aware Summary / Price copy for price-only Isolation Forest alerts |
| `app/watchlist_forest.py` | Same Isolation Forest OR-gate on Scan today / rebuild as live |
| `app/live.py` | `python -m app.live` entry point; heartbeats so Home can show Live alerts on |
| `ui/index.html` | Home Recent, Watchlist (focus set + Scan today + Today's results), History with Origin + draggable columns, settings, lake land, rebuild, Yahoo quote links, symbol search, desktop notifications and tab badge |
| `ui/sw-notifications.js` | Service worker for OS/Chrome Notification Center popups |
| `ui/sp500_universe.json` | S&P 500 ticker and company-name list for the Watchlist box |
| `app/lake_land.py` | Settings: full lake land, or incremental refresh (merge + `batch_train`) |
| `tests/` | Rules, parsing, and API smoke tests |

```bash
python -m pytest -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Live session-move path (Kafka must be up; Alpaca producer publishing). Scan today owns news:

```bash
# terminal 1 — API / UI
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010

# terminal 2 — live price alerts from Kafka
python -m app.live
```
