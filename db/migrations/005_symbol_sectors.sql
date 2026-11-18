-- Cached Yahoo sector labels for the alert history table.

CREATE TABLE IF NOT EXISTS symbols (
  symbol TEXT PRIMARY KEY,
  sector TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
