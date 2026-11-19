# Stream ingest (Alpaca → Kafka)

Live / delayed minute bars for the streaming half of the class architecture.

## What it does

1. Loads the S&P 500 list from `data/sp500_symbols.txt` (or a custom list).
2. Opens Alpaca’s **`delayed_sip`** WebSocket and subscribes to **minute bars**.
3. Publishes each bar to Kafka topic `prices.raw.bars`.
4. On the free Basic plan, WebSocket subscriptions are capped at **30 symbols**. The remaining S&P names are covered by a **REST poller** of delayed SIP minute bars (same Kafka schema).

The FastAPI live consumer (`python -m app.live` in `alert_service/`) reads this topic and writes open→last **price** alerts for the watchlist. Flink / Isolation Forest remain the class target on top of the same topic.

## Important limit

| Plan | WebSocket symbols | Full-market live | Delayed full-market |
|---|---|---|---|
| Alpaca Basic (free) | **30** | IEX only | Yes (`delayed_sip` + REST) |
| Algo Trader Plus ($99/mo) | Unlimited | SIP | Not needed |

So: free can cover the whole S&P 500 with **WebSocket for 30 + REST for the rest**, both landing on the same Kafka topic. True live unlimited SIP needs the paid plan.

## What you need to provide

1. **Alpaca API key ID and secret** (Paper trading keys are fine) from [app.alpaca.markets](https://app.alpaca.markets/).
2. **Docker** running, so we can start local Kafka (`docker compose up -d` from the repo root).

Put the keys in `stream_ingest/.env` (copy from `.env.example`). Do not commit `.env`.

## Setup

```bash
# From repo root
docker compose up -d

cd stream_ingest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and paste ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY
```

## Run

Dry run (no Kafka; prints JSON bars):

```bash
cd stream_ingest
source .venv/bin/activate
python -m app.main --dry-run --symbols AAPL,MSFT,NVDA
```

After hours the WebSocket stays quiet (no new equity minute bars). Probe the last delayed bar instead:

```bash
python -m app.main --probe --dry-run --symbols AAPL,MSFT,NVDA
```

Into Kafka (full S&P file, WebSocket first 30 + REST for the rest):

```bash
python -m app.main
```

WebSocket only, or REST only:

```bash
python -m app.main --ws-only --symbols AAPL,MSFT,NVDA
python -m app.main --rest-only
```

## Kafka payload

```json
{
  "schema": "prices.raw.bars.v1",
  "symbol": "AAPL",
  "ts": "2026-11-18T20:00:00Z",
  "open": 270.1,
  "high": 270.5,
  "low": 269.9,
  "close": 270.2,
  "volume": 12000,
  "trade_count": 80,
  "vwap": 270.15,
  "feed": "delayed_sip",
  "source": "alpaca_ws"
}
```

`source` is `alpaca_ws` or `alpaca_rest`.

## Tests

```bash
cd stream_ingest
source .venv/bin/activate
python -m pytest -q
```
