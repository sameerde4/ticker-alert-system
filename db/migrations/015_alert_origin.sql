-- Where an alert came from: live Kafka consumer vs watchlist Run check.
-- When both paths touch the same symbol/day row, origin becomes 'both'.
ALTER TABLE alerts
  ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'watchlist';

ALTER TABLE alerts DROP CONSTRAINT IF EXISTS alerts_origin_check;
ALTER TABLE alerts
  ADD CONSTRAINT alerts_origin_check
  CHECK (origin IN ('live', 'watchlist', 'both'));

CREATE INDEX IF NOT EXISTS alerts_origin_idx ON alerts (origin);
