-- Symbols that take Alpaca WebSocket slots (rest of the S&P uses REST poll).
-- Basic plan allows up to 30 WebSocket subscriptions per account.

CREATE TABLE IF NOT EXISTS live_ws_symbols (
  symbol TEXT PRIMARY KEY,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO live_ws_symbols (symbol) VALUES
  ('AAPL'),
  ('MSFT'),
  ('NVDA'),
  ('GOOGL'),
  ('AMZN'),
  ('META'),
  ('TSLA'),
  ('JPM'),
  ('XOM'),
  ('UNH')
ON CONFLICT (symbol) DO NOTHING;
