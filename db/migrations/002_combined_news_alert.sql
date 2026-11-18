-- One news alert per symbol, with the headlines that made it up.

DELETE FROM alerts WHERE kind = 'news';

ALTER TABLE alerts
  ADD COLUMN IF NOT EXISTS articles JSONB NOT NULL DEFAULT '[]'::jsonb;

DROP INDEX IF EXISTS alerts_news_key;

CREATE UNIQUE INDEX IF NOT EXISTS alerts_news_symbol_key
  ON alerts (symbol) WHERE kind = 'news';
