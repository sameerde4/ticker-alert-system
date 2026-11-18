-- One alert per symbol per day: price, news, or news_price.

DELETE FROM alerts;

ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_kind_check;
ALTER TABLE alerts
  ADD CONSTRAINT alerts_kind_check CHECK (kind IN ('price', 'news', 'news_price'));

ALTER TABLE alerts
  ADD COLUMN IF NOT EXISTS sections JSONB NOT NULL DEFAULT '{}'::jsonb;

DROP INDEX IF EXISTS alerts_price_key;
DROP INDEX IF EXISTS alerts_fusion_key;
DROP INDEX IF EXISTS alerts_news_symbol_key;

CREATE UNIQUE INDEX IF NOT EXISTS alerts_symbol_day_key
  ON alerts (symbol, bar_date);
