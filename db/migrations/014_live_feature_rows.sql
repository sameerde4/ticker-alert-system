-- Live session feature rows + Isolation Forest scores (Timescale stand-in).
-- Written by python -m app.live when the registry is present.

CREATE TABLE IF NOT EXISTS live_feature_rows (
  id BIGSERIAL PRIMARY KEY,
  symbol TEXT NOT NULL,
  session_day DATE NOT NULL,
  observed_at TIMESTAMPTZ NOT NULL,
  gap_return DOUBLE PRECISION NOT NULL,
  session_return DOUBLE PRECISION NOT NULL,
  close_return DOUBLE PRECISION NOT NULL,
  volume_zscore DOUBLE PRECISION NOT NULL,
  forest_score DOUBLE PRECISION NOT NULL,
  score_cutoff DOUBLE PRECISION NOT NULL,
  anomalous BOOLEAN NOT NULL,
  model_id TEXT NOT NULL,
  open_px DOUBLE PRECISION,
  last_px DOUBLE PRECISION,
  prior_close DOUBLE PRECISION,
  session_volume DOUBLE PRECISION,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS live_feature_rows_symbol_observed_idx
  ON live_feature_rows (symbol, observed_at DESC);

CREATE INDEX IF NOT EXISTS live_feature_rows_session_day_idx
  ON live_feature_rows (session_day, symbol);
