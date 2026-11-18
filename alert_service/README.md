# Alert service

FastAPI process for the Ticker Alert System. Setup, the migration, and the run command are in the [repository README](../README.md).

| Path | Purpose |
|---|---|
| `app/engine.py` | Price, news, and fusion rules. A headline is a candidate reason only for the price slice it was published in |
| `app/sentiment.py` | Keyword sentiment lexicon |
| `app/finbert.py` | Local ProsusAI/finbert score from 0 to 100, plus confidence and the three class shares |
| `app/scoring.py` | Sends every headline to FinBERT. The lexicon remains in the repo and is not used by a check |
| `app/prices.py` | Yahoo daily bars, the last 24 hours of hourly prices for a market that trades all day, the open and latest price during the cash session, and the sector or fund category |
| `app/symbols.py` | Ticker normalization, the local symbol list, and which symbols trade all day |
| `app/news.py` | Yahoo headlines |
| `app/checks.py` | One watchlist pass, and the admin rebuild of recent sessions |
| `ui/index.html` | Home inbox, sortable history, settings, rebuild, Yahoo quote links, symbol search |
| `ui/symbol_universe.json` | Local ticker and company-name list for the Watchlist box |
| `tests/` | Rules, parsing, and API smoke tests |

```bash
python -m pytest -q
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```
