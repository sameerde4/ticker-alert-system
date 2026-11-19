-- S&P 500 Radar — initial schema
-- PostgreSQL 15+

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS watchlist (
  symbol TEXT PRIMARY KEY,
  added_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS daily_bars (
  symbol TEXT NOT NULL,
  dt DATE NOT NULL,
  open NUMERIC(20, 6) NOT NULL,
  high NUMERIC(20, 6) NOT NULL,
  low NUMERIC(20, 6) NOT NULL,
  close NUMERIC(20, 6) NOT NULL,
  volume BIGINT NOT NULL,
  PRIMARY KEY (symbol, dt)
);

CREATE TABLE IF NOT EXISTS headlines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  url TEXT,
  source TEXT NOT NULL,
  published_at TIMESTAMPTZ NOT NULL,
  sentiment_score NUMERIC(8, 4) NOT NULL,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (symbol, title, published_at)
);

CREATE INDEX IF NOT EXISTS headlines_symbol_published_idx
  ON headlines (symbol, published_at DESC);

CREATE TABLE IF NOT EXISTS alerts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('price', 'news', 'fusion')),
  bar_date DATE,
  headline_id UUID REFERENCES headlines(id) ON DELETE SET NULL,
  price_change_pct NUMERIC(12, 6),
  latest_close NUMERIC(20, 6),
  prior_close NUMERIC(20, 6),
  volume_ratio NUMERIC(12, 4),
  volume_spike BOOLEAN NOT NULL DEFAULT FALSE,
  sentiment_score NUMERIC(8, 4),
  headline_title TEXT,
  summary TEXT NOT NULL,
  triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One open price alert and one fusion alert per symbol per session bar.
CREATE UNIQUE INDEX IF NOT EXISTS alerts_price_key
  ON alerts (symbol, bar_date) WHERE kind = 'price';
CREATE UNIQUE INDEX IF NOT EXISTS alerts_fusion_key
  ON alerts (symbol, bar_date) WHERE kind = 'fusion';
-- One news alert per stored headline.
CREATE UNIQUE INDEX IF NOT EXISTS alerts_news_key
  ON alerts (headline_id) WHERE kind = 'news';

CREATE INDEX IF NOT EXISTS alerts_triggered_idx
  ON alerts (triggered_at DESC);
