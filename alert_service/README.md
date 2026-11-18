# Alert service

FastAPI process for the Ticker Alert System. Setup, the migration, and the run command are in the [repository README](../README.md).

| Path | Purpose |
|---|---|
| `app/engine.py` | Price, news, and fusion rules |
| `app/sentiment.py` | Keyword sentiment lexicon |
| `app/finbert.py` | Local ProsusAI/finbert score, positive minus negative |
| `app/scoring.py` | Selects FinBERT or the lexicon. Does not average them |
| `app/prices.py` | Yahoo daily bars |
| `app/news.py` | Yahoo headlines |
| `app/checks.py` | One watchlist pass, and the admin rebuild of recent sessions |
| `ui/index.html` | Home inbox, sortable history, settings, rebuild, Yahoo quote links |
| `tests/` | Rules, parsing, and API smoke tests |

```bash
python -m pytest -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```
