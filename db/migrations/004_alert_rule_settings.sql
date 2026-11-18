-- Saved alert rules. One row for this local app.

CREATE TABLE IF NOT EXISTS app_settings (
  id BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (id),
  price_move_threshold NUMERIC(8, 6) NOT NULL,
  sentiment_threshold NUMERIC(8, 4) NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO app_settings (id, price_move_threshold, sentiment_threshold)
VALUES (TRUE, 0.030000, 0.3400)
ON CONFLICT (id) DO NOTHING;
